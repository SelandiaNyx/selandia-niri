#!/usr/bin/env python3
"""Local Wallpaper Engine library and the managed Niri wallpaper component.

Images, local videos and explicit experimental scene/Web playback are supported.
Metadata commands and Application projects are never launched.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from contextlib import contextmanager
import colorsys
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import secrets
import subprocess
import sys
import tempfile
import time
import wallpaper_audio
import wallpaper_playlist
import wallpaper_options
import wallpaper_remote
import engine_compatibility

from i18n import tr

BASE = Path(__file__).resolve().parent.parent
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg", ".gif"}
VIDEOS = {".mp4", ".webm", ".mkv", ".mov", ".m4v", ".avi"}
BACKEND_PACKAGES = {"mpvpaper": ("aur", "mpvpaper"),
                    "linux-wallpaperengine": ("aur", "linux-wallpaperengine-git"),
                    "ffmpeg": ("repo", "ffmpeg")}
CEF_LIBRARY = Path("/opt/linux-wallpaperengine/libcef.so")


def installation_hint(program):
    source, package = BACKEND_PACKAGES[program]
    if source == "aur":
        commands = f"paru -S --needed {package}\n" + tr("or: ", "或：") + f"yay -S --needed {package}"
        explanation = tr("Install in your terminal; review the AUR build and enter your sudo password there. Then Rescan.",
                         "在自己的终端安装，检查构建内容并在那里输入 sudo 密码；安装后点“重新扫描”。")
    else:
        commands = f"sudo pacman -S --needed {package}"
        explanation = tr("Install in your terminal and enter your sudo password there. Then Rescan.",
                         "在自己的终端安装并在那里输入 sudo 密码；安装后点“重新扫描”。")
    return explanation + "\n" + commands


def dependency_report():
    lines = []
    for program in BACKEND_PACKAGES:
        if shutil.which(program):
            lines.append(tr("Available: ", "已具备：") + program)
        else:
            lines.append(tr("Optional backend missing: ", "缺少可选后端：") + program + "\n" + installation_hint(program))
    return "\n".join(lines)
LIMIT = 1000


def state_dir():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri"


def cache_dir():
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "selandia-niri/wallpapers"


def read_json(path, limit=2_000_000):
    if path.stat().st_size > limit:
        raise ValueError(tr("Metadata is too large", "元数据文件过大"))
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(tr("Invalid wallpaper metadata", "壁纸元数据无效"))
    return value


def clean_path(value):
    if not isinstance(value, (str, Path)) or not str(value) or any(ord(c) < 32 for c in str(value)):
        raise ValueError(tr("Invalid local path", "本地路径无效"))
    return Path(value).expanduser().resolve()


def normalize_settings(value):
    try:
        roots = value.get("roots", [])
        if not isinstance(roots, list) or len(roots) > 32:
            raise ValueError("roots")
        selection = None
        entry = value.get("selection")
        if isinstance(entry, dict):
            try:
                mode = entry.get("mode", "preview")
                if mode not in ("live", "preview"):
                    raise ValueError("mode")
                selection = {"path": str(clean_path(entry.get("path", ""))), "mode": mode,
                             "fallback": str(clean_path(entry["fallback"])) if entry.get("fallback") else ""}
            except (ValueError, TypeError):
                pass
        try:
            audio = wallpaper_audio.validate(value.get("audio"))
        except ValueError:
            audio = dict(wallpaper_audio.DEFAULTS)
        registry = wallpaper_playlist.registry(value.get("playlists"), value.get("playlist"), clean_path)
        return {"roots": [str(clean_path(p)) for p in roots],
                "assets": str(clean_path(value["assets"])) if value.get("assets") else "",
                "selection": selection, "audio": audio,
                "playlist": wallpaper_playlist.current(registry)["settings"], "playlists": registry,
                "ratings": wallpaper_options.ratings(value.get("ratings"), clean_path),
                "rating_filter": wallpaper_options.rating_filter(value.get("rating_filter")),
                "display": wallpaper_options.display(value.get("display"))}
    except (OSError, ValueError, TypeError):
        return {"roots": [], "assets": "", "selection": None, "audio": dict(wallpaper_audio.DEFAULTS),
                "playlist": wallpaper_playlist.validate(None, clean_path),
                "playlists": wallpaper_playlist.registry(None, None, clean_path), "ratings": {},
                "rating_filter": dict(wallpaper_options.FILTER), "display": dict(wallpaper_options.DISPLAY)}


def load_settings():
    try:
        return normalize_settings(read_json(state_dir() / "wallpaper.json"))
    except (OSError, ValueError, TypeError):
        return normalize_settings({})


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wallpaper-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_settings(value):
    # Keep legacy writers working while the registry remains the persistent source.
    if "playlists" in value and "playlist" in value:
        registry = wallpaper_playlist.registry(value["playlists"], value["playlist"], clean_path)
        value = {**value, "playlists": wallpaper_playlist.with_current(registry, wallpaper_playlist.validate(value["playlist"], clean_path))}
    if "playlists" in value:
        active = wallpaper_playlist.current(value["playlists"])["settings"]
        # Older revisions can still read this projection after a release rollback.
        # Named lists, weights, seconds and shuffle state remain in the registry.
        legacy = {key: active[key] for key in ("enabled", "trigger", "minutes")}
        legacy["order"] = "random" if active["order"] == "shuffle" else active["order"]
        legacy["items"] = [{key: item[key] for key in ("path", "mode")} for item in active["items"]
                           if item.get("enabled", True) and wallpaper_options.allowed(value, item["path"])]
        value = {**value, "playlist": legacy}
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if len(data) > 2_000_000:
        raise ValueError(tr("Wallpaper preferences exceed the 2 MB limit", "壁纸偏好超过 2 MB 上限"))
    atomic_write(state_dir() / "wallpaper.json", data)


def steam_libraries(home=None):
    home = Path(home or Path.home())
    defaults = [home / ".local/share/Steam", home / ".steam/steam"]
    libraries = list(defaults)
    for root in defaults:
        metadata = root / "steamapps/libraryfolders.vdf"
        try:
            if metadata.stat().st_size > 2_000_000:
                continue
            # Valve's libraryfolders contains quoted path values. Unescape only
            # VDF's backslash/quote escapes; don't reinterpret UTF-8 characters.
            for raw in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', metadata.read_text()):
                path = re.sub(r'\\([\\"])', r'\1', raw)
                if path.startswith("/"):
                    libraries.append(Path(path))
        except (OSError, UnicodeError):
            pass
    return list(dict.fromkeys(p.resolve() for p in libraries))


def project_file(directory, value):
    if not isinstance(value, str) or not value:
        return None
    path = clean_path(directory / value.replace("\\", "/"))
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        return None
    return path


def describe(path):
    path = clean_path(path)
    if path.is_file() and path.suffix.lower() in IMAGES | VIDEOS:
        kind = "image" if path.suffix.lower() in IMAGES else "video"
        return {"path": str(path), "title": path.stem, "type": kind,
                "file": str(path), "preview": str(path) if kind == "image" else "",
                "contentrating": None, "rating_source": "local"}
    if path.name == "project.json":
        path = path.parent
    metadata = read_json(path / "project.json")
    kind = str(metadata.get("type", "unknown")).lower()
    preview = project_file(path, metadata.get("preview"))
    media = project_file(path, metadata.get("file"))
    if preview and preview.suffix.lower() not in IMAGES:
        preview = None
    if kind == "video" and (not media or media.suffix.lower() not in VIDEOS):
        kind = "unsupported"
    if kind == "scene" and not media:
        kind = "unsupported"
    if kind == "web" and (not media or media.suffix.lower() not in (".html", ".htm")):
        kind = "unsupported"
    if kind == "image" and (not media or media.suffix.lower() not in IMAGES):
        kind = "unsupported"
    title = " ".join(str(metadata.get("title") or path.name).split())[:180]
    return {"path": str(path), "title": title, "type": kind,
            "file": str(media) if media else "", "preview": str(preview) if preview else "",
            "contentrating": metadata.get("contentrating") if isinstance(metadata.get("contentrating"), str) and len(metadata["contentrating"]) <= 64 else None,
            "rating_source": "project"}


def discover(settings=None, *, libraries=None):
    settings = settings or load_settings()
    libraries = steam_libraries() if libraries is None else libraries
    roots = [Path(p) for p in settings["roots"]]
    assets = [settings.get("assets", "")]
    missing = []
    for library in libraries:
        library = Path(library)
        if not library.is_dir():
            missing.append(str(library))
        engine = library / "steamapps/common/wallpaper_engine"
        roots.extend([library / "steamapps/workshop/content/431960",
                      engine / "projects/myprojects", engine / "projects/defaultprojects"])
        assets.append(str(engine / "assets"))
    items, errors, visited = [], [], set()
    def visit(directory, depth):
        if len(items) >= LIMIT or len(visited) >= 5000 or depth > 3:
            return
        directory = directory.resolve()
        if directory in visited:
            return
        visited.add(directory)
        if (directory / "project.json").is_file():
            try:
                items.append(describe(directory))
            except (OSError, ValueError, TypeError) as error:
                errors.append(f"{directory.name}: {error}")
            return
        try:
            # Don't recursively follow directory symlinks or traverse a drive.
            for child in sorted(directory.iterdir(), key=lambda p: p.name.casefold()):
                if len(items) >= LIMIT:
                    break
                if child.is_symlink():
                    continue
                if child.is_file() and child.suffix.lower() in IMAGES | VIDEOS:
                    items.append(describe(child))
                elif child.is_dir():
                    visit(child, depth + 1)
        except OSError as error:
            if directory.exists():
                errors.append(str(error))
    for root in dict.fromkeys(roots):
        if root.is_dir():
            visit(root, 0)
    unique = {item["path"]: item for item in items}
    return {"items": sorted(unique.values(), key=lambda item: item["title"].casefold()),
            "missing": missing, "errors": errors, "limited": len(items) >= LIMIT or len(visited) >= 5000,
            "assets": next((p for p in assets if p and Path(p).is_dir()), ""),
            "backends": {name: bool(shutil.which(name)) for name in BACKEND_PACKAGES}}


def add_root(path):
    path = clean_path(path)
    if not path.is_dir():
        raise ValueError(tr("Folder not found", "目录不存在"))
    with settings_lock():
        settings = load_settings()
        roots = list(dict.fromkeys([*settings["roots"], str(path)]))
        if len(roots) > 32:
            raise ValueError(tr("At most 32 folders", "最多添加 32 个目录"))
        settings["roots"] = roots
        save_settings(settings)


@contextmanager
def settings_lock():
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "wallpaper.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def pixbuf(path, width=192, height=108):
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height, True)


def preview_image(item):
    source = item.get("preview") or (item["file"] if item["type"] == "image" else "")
    if source:
        return clean_path(source)
    if item["type"] != "video":
        raise ValueError(tr("This project has no usable preview image; choose one with a valid preview.",
                            "此项目没有可用的预览图，请选择带有效预览图的项目。"))
    if not shutil.which("ffmpeg"):
        raise ValueError(tr("No preview image; ffmpeg is required for video thumbnails", "没有预览图；视频缩略图需要 ffmpeg")
                         + "\n" + installation_hint("ffmpeg"))
    source = clean_path(item["file"])
    key = hashlib.sha256(f"{source}:{source.stat().st_mtime_ns}".encode()).hexdigest()
    target = cache_dir() / f"{key}.png"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        # Restrict FFmpeg to the chosen local file; no network protocols/playlists.
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                                 "-i", str(source), "-frames:v", "1", "-vf", "scale=640:-1",
                                 "-f", "image2pipe", "-vcodec", "png", "-"],
                                capture_output=True, timeout=15)
        if result.returncode or not result.stdout:
            raise ValueError(tr("Could not extract video preview", "无法提取视频预览图"))
        atomic_write(target, result.stdout)
    return target


def extract_seed(path):
    image = pixbuf(path, 64, 64)
    pixels = image.get_pixels()
    stride, channels = image.get_rowstride(), image.get_n_channels()
    buckets = Counter()
    for y in range(image.get_height()):
        for x in range(image.get_width()):
            offset = y * stride + x * channels
            if channels == 4 and pixels[offset + 3] < 128:
                continue
            rgb = tuple(pixels[offset + c] for c in range(3))
            _, light, saturation = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
            if .08 < light < .94:
                buckets[tuple(c // 24 for c in rgb)] += .15 + saturation
    if not buckets:
        return "#808080"
    return "#" + "".join(f"{min(255, c * 24 + 12):02x}" for c in buckets.most_common(1)[0][0])


def current_image():
    selection = load_settings()["selection"]
    candidates = [selection.get("fallback", "")] if selection else []
    try:
        candidates.append((state_dir() / "wallpaper").read_text().strip())
    except OSError:
        pass
    candidates.append(str(BASE / "assets/selandia-glass.svg"))
    return next(Path(p) for p in candidates if p and Path(p).is_file())


def with_wallpaper_colors(settings):
    values = dict(settings)
    if values.get("wallpaper_colors"):
        values["wallpaper_seed"] = extract_seed(current_image())
    return values


def playback_command(item, mode, *, assets="", outputs=None, audio=None, audio_available=None, display=None):
    if mode not in ("live", "preview"):
        raise ValueError(tr("Invalid wallpaper mode", "壁纸模式无效"))
    display = wallpaper_options.display(display)
    if mode == "preview" or item["type"] == "image":
        return static_command(preview_image(item), display)
    audio = wallpaper_audio.validate(audio)
    ready = wallpaper_audio.available() if audio_available is None else audio_available
    if item["type"] == "video":
        if not shutil.which("mpvpaper"):
            raise ValueError(tr("Video playback requires the optional AUR package mpvpaper", "视频播放需要可选 AUR 软件包 mpvpaper")
                             + "\n" + installation_hint("mpvpaper"))
        # Keep audio decoding alive while muted. All three backends use stream
        # volume, avoiding two multiplied gains and allowing mute without replay.
        sound = "audio=yes ao=pulse volume=100" if ready else "no-audio"
        return ["mpvpaper", "-o", f"no-config load-scripts=no {sound} loop-file=inf hwdec=auto terminal=no input-terminal=no {wallpaper_options.mpv_options(display['mode'])}", "ALL", item["file"]]
    if item["type"] in ("scene", "web"):
        if not shutil.which("linux-wallpaperengine"):
            raise ValueError(tr("Scene/Web playback requires linux-wallpaperengine-git (AUR, experimental)",
                                "场景/网页播放需要 linux-wallpaperengine-git（AUR，实验性支持）")
                             + "\n" + installation_hint("linux-wallpaperengine"))
        if not assets or not Path(assets).is_dir():
            raise ValueError(tr("Select the original Wallpaper Engine assets folder: Steam → Wallpaper Engine → Manage → Browse local files → assets",
                                "请指定正版 Wallpaper Engine 的 assets 目录：Steam → Wallpaper Engine → 管理 → 浏览本地文件 → assets"))
        if outputs is None:
            raw = subprocess.run(["niri", "msg", "--json", "outputs"], capture_output=True, text=True, check=True, timeout=5)
            outputs = [name for name, info in json.loads(raw.stdout).items() if info.get("current_mode") is not None]
        if not outputs:
            raise ValueError(tr("No active Niri outputs", "没有活动的 Niri 屏幕"))
        # Automute detection has an unbounded connection wait upstream. Explicit
        # user controls replace it; absent audio also disables its recorder.
        command = ["linux-wallpaperengine", "--noautomute", "--fps", "30", "--assets-dir", str(assets)]
        command += ["--volume", "128"] if ready else ["--silent"]
        if not ready:
            command.append("--no-audio-processing")
        if item["type"] == "web":
            command.append("--ozone-platform=wayland")
            command.append("--autoplay-policy=no-user-gesture-required")
            if not ready:
                command.append("--mute-audio")  # CEF does not honor SDL's --silent.
        for output in outputs:
            command.extend(["--screen-root", output, "--bg", item["path"], *wallpaper_options.engine_options(display["mode"])])
        return command
    raise ValueError(tr("This project supports static wallpaper only", "此类项目仅支持静态壁纸"))


def static_command(image, display):
    return ["swaybg", "-i", str(image), "-m", wallpaper_options.sway_mode(wallpaper_options.display(display)["mode"]), "-c", "#101522"]


def renderer_environment(item):
    """Keep the Arch CEF load-order workaround inside the Web child only.

    Upstream issue #628: libcef must precede libc for its close() interposer.
    Non-Arch layouts continue to use their launcher's own library arrangement.
    """
    environment = wallpaper_audio.environment()
    if item["type"] in ("scene", "web"):
        environment = engine_compatibility.environment(environment)
    environment["SDL_AUDIODRIVER"] = "pulseaudio"  # Never fall back to blocking ALSA device discovery.
    if item["type"] == "web" and CEF_LIBRARY.is_file():
        existing = environment.get("LD_PRELOAD", "")
        libraries = [entry for entry in re.split(r"[:\s]+", existing) if entry]
        if str(CEF_LIBRARY) not in libraries:
            environment["LD_PRELOAD"] = str(CEF_LIBRARY) + (" " + existing if existing else "")
    return environment


def restart_renderer():
    unit = "selandia-niri@wallpaper.service"
    # Explicit user switches should not consume the automatic crash-loop budget
    # shared by the template. Reset this single instance, then verify it runs.
    subprocess.run(["systemctl", "--user", "reset-failed", unit], check=True, capture_output=True, timeout=8)
    subprocess.run(["systemctl", "--user", "restart", unit], check=True, capture_output=True, timeout=15)
    subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit], check=True, capture_output=True, timeout=8)


def set_audio(audio):
    audio = wallpaper_audio.validate(audio)
    with settings_lock():
        before = load_settings()
        settings = {**before, "audio": audio}
        save_settings(settings)
        selection = settings["selection"]
        available = wallpaper_audio.available()
        record = wallpaper_audio.current_renderer(selection) if selection and selection["mode"] == "live" else None
        changed = {key for key in audio if before["audio"][key] != audio[key]}
        applied = set()
        if record and record["audio_available"] != available:
            try:
                restart_renderer()
            except (OSError, subprocess.SubprocessError):
                save_settings(before)
                restart_renderer()
                raise
        elif record:
            try:
                applied = wallpaper_audio.sync_streams(record["renderer"]["pid"], audio, fields=changed, strict=True)
            except RuntimeError:
                save_settings(before)
                raise
    return {"audio": audio, "available": available, "streams_updated": len(applied),
            "restarted": bool(record and record["audio_available"] != available)}


def activate(path, mode="live", *, assets="", handoff=None, expected=None, rotation=None):
    if mode not in ("live", "preview"):
        raise ValueError("mode")
    if handoff is None:
        remote = wallpaper_remote.request("activate", path=str(path), mode=mode, assets=assets, expected=expected, rotation=rotation)
        if remote is not wallpaper_remote.NO_SERVICE:
            return remote
    item = describe(path)  # Revalidate metadata and paths at the moment of use.
    settings = load_settings()
    assets = str(clean_path(assets)) if assets else discover(settings)["assets"]
    if not wallpaper_options.allowed(settings, item["path"], item=item):
        raise ValueError(tr("This wallpaper is hidden by the age-rating filter", "此壁纸被年龄分级过滤隐藏"))
    playback_command(item, mode, assets=assets, audio=settings["audio"], display=settings["display"])  # Reject missing capabilities before changing anything.
    preview = preview_image(item)
    from gi.repository import GdkPixbuf
    _format, width, height = GdkPixbuf.Pixbuf.get_file_info(str(preview))
    # Preserve small images at their original size for center/tile fallbacks.
    image = pixbuf(preview, min(1920, max(1, width)), min(1080, max(1, height)))
    seed = extract_seed(preview)
    # A durable fallback remains available when the original disk is unmounted.
    ok, image_bytes = image.save_to_bufferv("png", [], [])
    if not ok:
        raise ValueError(tr("Cannot cache wallpaper", "无法缓存壁纸"))
    fallback = cache_dir() / (hashlib.sha256(bytes(image_bytes)).hexdigest() + ".png")
    atomic_write(fallback, bytes(image_bytes))
    with settings_lock():
        recover_transition()
        settings = load_settings()
        if expected is not None and any(settings[key] != expected[key] for key in ("selection", "playlist", "playlists", "ratings", "rating_filter", "display")):
            raise RuntimeError(tr("Wallpaper changed during playlist switching; preserving the newer choice.",
                                  "轮播切换期间壁纸设置已更改，保留较新的选择。"))
        before = dict(settings)
        settings.update(assets=assets, selection={"path": item["path"], "mode": mode, "fallback": str(fallback)})
        if not wallpaper_options.allowed(settings, item["path"], item=item):
            raise ValueError(tr("This wallpaper is hidden by the age-rating filter", "此壁纸被年龄分级过滤隐藏"))
        if rotation is not None:
            settings = with_playlist(settings, rotation)
        commit_settings(before, settings, (lambda: handoff(load_settings())) if handoff else restart_renderer)
    warnings = wallpaper_options.notices(item, mode, settings["display"])
    import appearance
    values = appearance.load_settings()
    if values["wallpaper_colors"]:
        try:
            appearance.apply_settings({**values, "wallpaper_seed": seed})
            subprocess.run([str(BASE / "scripts/desktop"), "theme-reload"], check=True, capture_output=True, timeout=25)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            warnings.append(tr("Wallpaper changed; theme update failed: ", "壁纸已更换；主题更新失败：") + str(error))
    return {"item": item, "warnings": warnings}


def commit_settings(before, after, apply):
    """Durable intent, atomic preferences, rollback plus replay for every change."""
    transaction = state_dir() / "wallpaper-transition.json"
    intent = {"version": 1, "phase": "prepared", "before": before, "after": after}
    atomic_write(transaction, json.dumps(intent, ensure_ascii=False).encode())
    try:
        save_settings(after)
        apply()
        atomic_write(transaction, json.dumps({**intent, "phase": "committed"}, ensure_ascii=False).encode())
        transaction.unlink()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as failure:
        try:
            save_settings(before); apply()
            transaction.unlink(missing_ok=True)
            recovery = tr("Previous selection and renderer restored.", "已恢复原选择，并确认原壁纸服务运行。")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            recovery = tr("Previous wallpaper recovery failed: ", "原壁纸恢复失败：") + str(error)
        raise RuntimeError(tr("Wallpaper change failed: ", "壁纸切换失败：") + str(failure) + "; " + recovery) from failure


def recover_transition():
    """Normalize old journals too, without losing their valid legacy settings."""
    path = state_dir() / "wallpaper-transition.json"
    if not path.exists():
        return
    value = read_json(path, limit=8_100_000)
    current = load_settings()
    if (value.get("version") != 1 or value.get("phase") not in ("prepared", "committed") or
            not isinstance(value.get("before"), dict) or not isinstance(value.get("after"), dict)):
        raise RuntimeError(tr("Invalid interrupted wallpaper transaction", "中断的壁纸事务记录无效"))
    before, after = normalize_settings(value["before"]), normalize_settings(value["after"])
    if current not in (before, after):
        raise RuntimeError(tr("Preserving wallpaper settings edited after interruption", "保留壁纸中断后被修改的设置"))
    if value["phase"] == "prepared":
        save_settings(before)
        log_rotation("recovered", selection=before["selection"])
    path.unlink()


def with_playlist(settings, playlist):
    return {**settings, "playlist": playlist,
            "playlists": wallpaper_playlist.with_current(settings["playlists"], playlist)}


def with_registry(settings, registry):
    return {**settings, "playlists": registry, "playlist": wallpaper_playlist.current(registry)["settings"]}


def change_preferences(transform, handoff=None):
    with settings_lock():
        recover_transition()
        before = load_settings()
        after = transform(before)
        commit_settings(before, after, (lambda: handoff(load_settings())) if handoff else restart_renderer)
    return after


def log_rotation(event, **values):
    print(json.dumps({"wallpaper_playlist": event, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **values},
                     ensure_ascii=False), file=sys.stderr, flush=True)


def configure_playlist(value, *, identifier=None, registry=None, expected_registry=None, handoff=None):
    if handoff is None:
        remote = wallpaper_remote.request("configure_playlist", value=value, identifier=identifier, registry=registry, expected_registry=expected_registry)
        if remote is not wallpaper_remote.NO_SERVICE: return remote
    playlist = wallpaper_playlist.validate(value, clean_path)
    def update(before):
        if expected_registry is not None and wallpaper_playlist.configuration(before["playlists"]) != wallpaper_playlist.configuration(expected_registry):
            raise RuntimeError(tr("Playlists changed elsewhere; reopen before saving", "播放集已被其他操作更改，请重新打开后保存"))
        if registry is not None:
            validated = wallpaper_playlist.registry(registry, value, clean_path)
            validated = wallpaper_playlist.with_current(validated, playlist)
            return with_registry(before, wallpaper_playlist.merge_cycles(validated, before["playlists"]))
        if identifier is not None and identifier != before["playlists"]["active"]:
            raise RuntimeError(tr("Active playlist changed; reload before saving", "当前播放集已更改，请重新读取后保存"))
        return with_playlist(before, playlist)
    after = change_preferences(update, handoff)
    log_rotation("configured", playlist=playlist, playlist_id=after["playlists"]["active"])
    return playlist


def manage_playlists(action, *, title=None, identifier=None, handoff=None):
    if handoff is None:
        remote = wallpaper_remote.request("manage_playlists", action=action, title=title, identifier=identifier)
        if remote is not wallpaper_remote.NO_SERVICE: return remote
    after = change_preferences(lambda before: with_registry(before, wallpaper_playlist.manage(
        before["playlists"], action, title=title, identifier=identifier)), handoff)
    log_rotation(action, playlist_id=after["playlists"]["active"])
    return after["playlists"]


def configure_display(value, *, handoff=None):
    if handoff is None:
        remote = wallpaper_remote.request("configure_display", value=value)
        if remote is not wallpaper_remote.NO_SERVICE: return remote
    result = change_preferences(lambda before: {**before, "display": wallpaper_options.display(value)}, handoff)
    log_rotation("display-configured", display=result["display"])
    return result["display"]


def set_ratings(paths, rating, *, handoff=None):
    if rating not in wallpaper_options.RATINGS or not isinstance(paths, list) or len(paths) > 1000:
        raise ValueError(tr("Invalid wallpaper rating", "壁纸分级无效"))
    paths = [str(clean_path(path)) for path in paths]
    if handoff is None:
        remote = wallpaper_remote.request("set_ratings", paths=paths, rating=rating)
        if remote is not wallpaper_remote.NO_SERVICE: return remote
    def update(before):
        ratings = {**before["ratings"], **dict.fromkeys(paths, rating)}
        if len(ratings) > 1000:
            raise ValueError(tr("Up to 1000 rated wallpapers", "最多为 1000 张壁纸设置分级"))
        return {**before, "ratings": ratings}
    after = change_preferences(update, handoff)
    log_rotation("rated", paths=paths, rating=rating)
    return after["ratings"]


def configure_rating_filter(value, *, confirm_mature=False, handoff=None):
    if handoff is None:
        remote = wallpaper_remote.request("configure_rating_filter", value=value, confirm_mature=confirm_mature)
        if remote is not wallpaper_remote.NO_SERVICE: return remote
    value = wallpaper_options.rating_filter(value)
    def update(before):
        if value["mature"] and not before["rating_filter"]["mature"] and confirm_mature is not True:
            raise ValueError(tr("Confirm before showing Mature wallpapers", "显示 Mature 壁纸前需要确认"))
        return {**before, "rating_filter": value}
    after = change_preferences(update, handoff)
    log_rotation("rating-filter", rating_filter=after["rating_filter"])
    return after["rating_filter"]


def playlist_step(direction=1, *, handoff=None, expected=None):
    if direction not in (-1, 1):
        raise ValueError(tr("Invalid playlist direction", "播放集切换方向无效"))
    if handoff is None:
        remote = wallpaper_remote.request("playlist_step", direction=direction, expected=expected)
        if remote is not wallpaper_remote.NO_SERVICE: return remote
    settings = expected or load_settings()
    failures = []
    ordered = wallpaper_playlist.candidates(settings["playlist"], settings["selection"], direction,
        allowed=lambda item: wallpaper_options.allowed(settings, item["path"]))
    for index, item in enumerate(ordered):
        try:
            rotation = wallpaper_playlist.consume(settings["playlist"], ordered, index, direction)
            result = activate(item["path"], item["mode"], handoff=handoff, expected=settings, rotation=rotation)
            log_rotation("switched", path=item["path"], mode=item["mode"], order=settings["playlist"]["order"],
                         playlist_id=settings["playlists"]["active"], playlist_name=wallpaper_playlist.current(settings["playlists"])["name"],
                         trigger=settings["playlist"]["trigger"], seconds=settings["playlist"]["seconds"],
                         rating=wallpaper_options.rating_info(settings, item["path"])["rating"], weight=item["weight"], warnings=result["warnings"])
            return result
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(str(error)); log_rotation("skipped", path=item["path"], error=str(error))
            latest = load_settings()
            if any(latest[key] != settings[key] for key in ("selection", "playlist", "playlists", "ratings", "rating_filter", "display")):
                raise
    if failures:
        raise RuntimeError(tr("No playlist entry could be applied: ", "播放集条目均无法应用：") + "\n".join(failures))
    return None


class PlaylistRenderer:
    """Own both renderers during handoff; never restart our own systemd unit."""
    def __init__(self):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        self.runtime = Path(tempfile.mkdtemp(prefix="selandia-wallpaper-", dir=runtime))
        self.renderer = self.guard = self.record = self.selection = None
        self.ipc = None
        self.config = None
        self.display = dict(wallpaper_options.DISPLAY)
        self.applied = set()

    @staticmethod
    def stop(child):
        if child is None:
            return
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)

    @staticmethod
    def property(path, name):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(.25)
                client.connect(str(path))
                client.sendall((json.dumps({"command": ["get_property", name], "request_id": 1}) + "\n").encode())
                data = bytearray()
                while len(data) < 65536:
                    part = client.recv(4096)
                    if not part:
                        break
                    data.extend(part)
                    while b"\n" in data:
                        line, _, data = data.partition(b"\n")
                        reply = json.loads(line)
                        if reply.get("request_id") == 1:
                            return reply.get("data") if reply.get("error") == "success" else None
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def replace(self, settings):
        selection = settings["selection"]
        display = settings.get("display", wallpaper_options.DISPLAY)
        finite = settings["playlist"]["enabled"] and settings["playlist"]["trigger"] == "finished"
        config = (selection, display["mode"], finite)
        if config == self.config and self.renderer and self.renderer.poll() is None and not self.finished():
            self.display = dict(display)
            return
        item = describe(selection["path"]) if selection else None
        ready = wallpaper_audio.available() if selection and selection["mode"] == "live" else False
        guard = renderer = overlay = None
        initialized = set()
        ipc = self.runtime / (secrets.token_hex(8) + ".sock")
        try:
            static = not selection or selection["mode"] == "preview" or item["type"] == "image"
            if display["transition"] == "fade" and static and self.selection and self.record is None and self.renderer and self.renderer.poll() is None:
                old = self.selection
                try:
                    previous = preview_image(describe(old["path"]))
                except (OSError, ValueError):
                    previous = Path(old["fallback"])
                marker = self.runtime / (secrets.token_hex(8) + ".fade")
                overlay = subprocess.Popen([sys.executable, "-B", str(BASE / "shell/wallpaper_fade.py"),
                    "--image", str(previous), "--mode", self.display["mode"], "--duration", str(display["duration"]),
                    "--ready", str(marker), "--begin", str(marker) + ".begin"], start_new_session=True)
                deadline = time.monotonic() + 3
                while not marker.exists():
                    if overlay.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(tr("Fade overlay did not become ready", "淡入淡出图层未就绪"))
                    time.sleep(.02)
            fallback = static_command(current_image(), display)
            guard = subprocess.Popen(fallback, start_new_session=True)
            command = playback_command(item, selection["mode"], assets=settings["assets"], audio=settings["audio"],
                                       audio_available=ready, display=display) if selection else fallback
            if item and item["type"] == "video" and selection["mode"] == "live":
                if finite:
                    command[2] = command[2].replace("loop-file=inf", "loop-file=no keep-open=yes idle=yes")
                command[2] += " input-ipc-server=" + json.dumps(str(ipc))
            environment = renderer_environment(item) if command[0] == "linux-wallpaperengine" else wallpaper_audio.environment()
            renderer = subprocess.Popen(command, env=environment, start_new_session=True)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if renderer.poll() is not None or guard.poll() is not None:
                    raise RuntimeError(tr("New wallpaper renderer failed; keeping the previous one", "新壁纸渲染器失败，保留原壁纸"))
                if ready and item and item["type"] in ("video", "scene", "web"):
                    # Initialize each new stream once, including while readiness
                    # is pending. A saved mute must not briefly play at 100%.
                    wallpaper_audio.sync_streams(renderer.pid, load_settings()["audio"], applied=initialized)
                if time.monotonic() >= deadline - 3:
                    if command[0] != "mpvpaper" or self.property(ipc, "path") == item["file"]:
                        break
                time.sleep(.1)
            else:
                raise RuntimeError(tr("New wallpaper renderer did not become ready", "新壁纸渲染器未就绪"))
            if overlay is not None:
                Path(str(marker) + ".begin").touch()
                overlay.wait(timeout=display["duration"] + 2)
                if overlay.returncode != 0:
                    raise RuntimeError(tr("Fade overlay failed", "淡入淡出图层失败"))
                log_rotation("transition", effect="fade", duration=display["duration"], backend="swaybg", path=selection["path"])
            record = None
            if item and item["type"] in ("video", "scene", "web") and selection["mode"] == "live":
                record = {"supervisor": wallpaper_audio.process_identity(os.getpid()),
                          "renderer": wallpaper_audio.process_identity(renderer.pid), "selection": selection,
                          "kind": item["type"], "audio_available": ready}
                atomic_write(wallpaper_audio.runtime_path(), json.dumps(record).encode())
            else:
                wallpaper_audio.runtime_path().unlink(missing_ok=True)
            old_renderer, old_guard, old_ipc = self.renderer, self.guard, self.ipc
            self.renderer, self.guard, self.record, self.selection = renderer, guard, record, selection
            self.ipc, self.applied = ipc, initialized
            self.config, self.display = deepcopy(config), dict(display)
            renderer = guard = None
            self.stop(old_renderer)
            self.stop(old_guard)
            if old_ipc:
                old_ipc.unlink(missing_ok=True)
        finally:
            self.stop(renderer)
            self.stop(guard)
            self.stop(overlay)
            if overlay is not None:
                marker.unlink(missing_ok=True)
                Path(str(marker) + ".begin").unlink(missing_ok=True)
            if ipc != self.ipc:
                ipc.unlink(missing_ok=True)

    def finished(self):
        if self.renderer is None:
            return False
        if self.renderer.poll() is not None:
            return self.renderer.returncode == 0
        return bool(self.record and self.record["kind"] == "video" and self.property(self.ipc, "eof-reached") is True)

    def close(self):
        self.stop(self.renderer)
        self.stop(self.guard)
        try:
            record = read_json(wallpaper_audio.runtime_path())
            if record.get("supervisor", {}).get("pid") == os.getpid():
                wallpaper_audio.runtime_path().unlink()
        except (OSError, ValueError):
            pass
        shutil.rmtree(self.runtime)


def run_playlist():
    supervisor = PlaylistRenderer()
    schedule = wallpaper_playlist.Schedule(time.monotonic())
    previous = {}
    server = None
    def dispatch(command, values):
        functions = {"activate": activate, "configure_playlist": configure_playlist,
                     "manage_playlists": manage_playlists, "configure_display": configure_display,
                     "set_ratings": set_ratings, "configure_rating_filter": configure_rating_filter,
                     "playlist_step": playlist_step}
        if command not in functions:
            raise ValueError(tr("Unknown wallpaper service action", "壁纸服务操作未知"))
        result = functions[command](**values, handoff=supervisor.replace)
        schedule.attempted(time.monotonic(), True)
        return result
    def terminate(signum, frame):
        raise SystemExit(0)
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, terminate)
        server = wallpaper_remote.Server()
        settings = load_settings()
        try:
            supervisor.replace(settings)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            log_rotation("startup-fallback", error=str(error))
            supervisor.replace({**settings, "selection": None})
        while True:
            if server.poll(dispatch):
                continue
            settings = load_settings()
            now = time.monotonic()
            if schedule.due(settings, now, finished=supervisor.finished(),
                            allowed=lambda item: wallpaper_options.allowed(settings, item["path"])):
                try:
                    switched = playlist_step(handoff=supervisor.replace, expected=settings)
                    schedule.attempted(time.monotonic(), switched is not None)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    log_rotation("failed", error=str(error))
                    schedule.attempted(time.monotonic(), False)
            if supervisor.record and supervisor.record["audio_available"] and supervisor.renderer.poll() is None:
                wallpaper_audio.sync_streams(supervisor.renderer.pid, settings["audio"], applied=supervisor.applied)
            time.sleep(.5)
    finally:
        if server is not None: server.close()
        supervisor.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run():
    with settings_lock():
        recover_transition()
    # Always resident: edits and static fades use the same atomic handoff path,
    # including when rotation is disabled or the active playlist is empty.
    run_playlist()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "run", "set", "add-folder", "dependencies"))
    parser.add_argument("path", nargs="?")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--assets", default="")
    args = parser.parse_args()
    try:
        if args.action == "run":
            run()
        elif args.action == "list":
            print(json.dumps(discover(), ensure_ascii=False, indent=2))
        elif args.action == "dependencies":
            print(dependency_report())
        elif not args.path:
            parser.error("path is required")
        elif args.action == "add-folder":
            add_root(args.path)
        else:
            print(json.dumps(activate(args.path, "preview" if args.preview else "live", assets=args.assets), ensure_ascii=False))
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
