"""Bounded PulseAudio detection and audio settings for owned wallpaper streams."""
import json
import os
from pathlib import Path
import shutil
import subprocess

DEFAULTS = {"muted": False, "volume": 50}


def validate(value=None):
    value = DEFAULTS if value is None else value
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("Invalid wallpaper audio settings / 壁纸声音设置无效")
    result = {**DEFAULTS, **value}
    if not isinstance(result["muted"], bool) or type(result["volume"]) is not int or not 0 <= result["volume"] <= 100:
        raise ValueError("Volume must be 0–100 / 音量须为 0–100")
    return result


def environment():
    # An explicit server prevents libpulse from auto-starting an unrelated daemon
    # or escaping a test's private runtime directory to the user's real session.
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return dict(os.environ, PULSE_SERVER=os.environ.get("PULSE_SERVER") or f"unix:{runtime}/pulse/native")


def available():
    if not shutil.which("pactl"):
        return False
    try:
        return subprocess.run(["pactl", "info"], env=environment(), capture_output=True, timeout=1.5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def runtime_path():
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "selandia-wallpaper-renderer.json"


def process_identity(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid renderer PID")
    path = Path(f"/proc/{pid}/stat")
    if path.stat().st_uid != os.getuid():
        raise ValueError("Renderer belongs to another user")
    fields = path.read_text().rsplit(")", 1)[1].split()
    if fields[0] == "Z":
        raise ValueError("Renderer exited")
    return {"pid": pid, "start": int(fields[19]), "parent": int(fields[1])}


def current_renderer(selection):
    """Accept only this wallpaper supervisor and its still-owned process group."""
    try:
        path = runtime_path()
        if path.is_symlink() or path.stat().st_size > 4096:
            return None
        record = json.loads(path.read_text())
        if (record.get("selection") != selection or type(record.get("audio_available")) is not bool or
                record.get("kind") not in ("video", "scene", "web")):
            return None
        supervisor = process_identity(record["supervisor"]["pid"])
        renderer = process_identity(record["renderer"]["pid"])
        if (supervisor != record["supervisor"] or renderer != record["renderer"] or
                renderer["parent"] != supervisor["pid"] or os.getpgid(renderer["pid"]) != renderer["pid"]):
            return None
        arguments = Path(f"/proc/{supervisor['pid']}/cmdline").read_bytes().split(b"\0")
        script = Path(__file__).with_name("wallpaper.py").resolve()
        if b"run" not in arguments or not any(Path(os.fsdecode(argument)).resolve() == script
                                             for argument in arguments if argument):
            return None
        return record
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def _owned_streams(pid):
    result = subprocess.run(["pactl", "--format=json", "list", "sink-inputs"], env=environment(),
                            capture_output=True, text=True, timeout=1.5, check=True)
    streams = json.loads(result.stdout)
    if not isinstance(streams, list):
        raise ValueError("Invalid audio stream response / 音频流响应无效")
    owned = {}
    for stream in streams:
        if not isinstance(stream, dict) or not isinstance(stream.get("properties"), dict):
            continue
        properties = stream["properties"]
        try:
            process = int(properties.get("application.process.id", 0))
            index = stream.get("index")
            if process <= 0 or type(index) is not int or index < 0 or os.getpgid(process) != pid:
                continue
        except (OSError, ValueError, TypeError):
            continue
        serial = properties.get("object.serial")
        serial = serial if isinstance(serial, (str, int)) else None
        owned[(index, process, serial)] = stream
    return owned


def _command(index, field, values):
    return ["pactl", "set-sink-input-" + ("mute" if field == "muted" else "volume"), str(index), *values]


def sync_streams(pid, audio, *, applied=None, fields=("volume", "muted"), strict=False):
    """Set volume only on the renderer's private process group, including CEF.

    CEF Web audio bypasses the engine's SDL --volume setting. Match process IDs,
    never application names, and don't repeatedly reset users' mixer changes.
    """
    audio = validate(audio)
    applied = set() if applied is None else applied
    fields = set(fields)
    if fields - set(DEFAULTS):
        raise ValueError("Invalid wallpaper audio control")
    if not fields:
        return applied
    undo, completed = [], set()
    try:
        streams = _owned_streams(pid)
        snapshots = {}
        if strict:
            # Capture actual mixer values, including per-channel balance. Stored
            # preferences may be older than changes made in another mixer.
            for identity, stream in streams.items():
                if identity in applied:
                    continue
                snapshot = {}
                if "muted" in fields:
                    if type(stream.get("mute")) is not bool:
                        raise ValueError("Missing stream mute state")
                    snapshot["muted"] = ["1" if stream["mute"] else "0"]
                if "volume" in fields:
                    channels = stream.get("volume")
                    if not isinstance(channels, dict) or not channels:
                        raise ValueError("Missing stream channel volumes")
                    values = [channel.get("value") if isinstance(channel, dict) else None
                              for channel in channels.values()]
                    if any(type(value) is not int or value < 0 for value in values):
                        raise ValueError("Invalid stream channel volumes")
                    snapshot["volume"] = [str(value) for value in values]
                snapshots[identity] = snapshot
        for identity in streams:
            if identity in applied:
                continue
            index = identity[0]
            # New streams get both settings once. An explicit mute change must
            # leave a volume previously edited in another mixer untouched.
            for field in ("volume", "muted"):
                if field not in fields:
                    continue
                if strict:
                    undo.append((identity, field, snapshots[identity][field]))
                values = [f"{audio['volume']}%"] if field == "volume" else ["1" if audio["muted"] else "0"]
                subprocess.run(_command(index, field, values), env=environment(),
                               capture_output=True, timeout=1.5, check=True)
            completed.add(identity)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as failure:
        if strict:
            recovery_errors = []
            if undo:
                try:
                    current = _owned_streams(pid)
                except (OSError, ValueError, TypeError, subprocess.SubprocessError) as recovery:
                    recovery_errors.append(recovery)
                    current = {}
                for identity, field, values in reversed(undo):
                    if identity in current:
                        try:
                            subprocess.run(_command(identity[0], field, values), env=environment(),
                                           capture_output=True, timeout=1.5, check=True)
                        except (OSError, subprocess.SubprocessError) as recovery:
                            recovery_errors.append(recovery)
            if recovery_errors:
                raise RuntimeError("Wallpaper audio failed; mixer recovery also failed / 壁纸声音调整及混音恢复失败") from recovery_errors[0]
            raise RuntimeError("Wallpaper audio was not applied / 壁纸声音未能应用，请检查音频服务") from failure
        # Background initialization remains best effort; a lost audio service
        # must never stop rendering or overwrite already-initialized streams.
    applied.update(completed)
    return applied
