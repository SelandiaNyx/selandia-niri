#!/usr/bin/env python3
"""Deploy or restore this desktop's files; preserve originals and foreign edits."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "selandia-niri"
MANIFEST = STATE / "install.json"


def tr(english, chinese):
    # Keep recovery diagnostics usable even when shell modules are missing.
    code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "en_US")
    try:
        preferences = json.loads((STATE / "language.json").read_text())
        selected = preferences.get("ui_language", "system")
        if selected in ("zh_CN", "en_US"):
            code = selected
        elif selected == "system":
            code = preferences.get("session_locale") or code
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return chinese if str(code).lower().startswith("zh") else english


MANAGED_PATHS = {
    "niri",
    "systemd/user/selandia-niri.target",
    "systemd/user/selandia-niri@.service",
    "systemd/user/selandia-lock@.service",
    "xdg-desktop-portal/niri-portals.conf",
}
REQUIRED_SOURCES = (
    "control.sh", "install.sh", "check.sh", "packages.txt",
    "systemd/selandia-niri@.service.in", "systemd/selandia-niri.target",
    "systemd/selandia-lock@.service.in", "niri/shell/lock_client.py",
    "portals/niri-portals.conf", "niri/config.kdl", "niri/preview.kdl", "niri/monitor.kdl",
    "niri/assets/selandia-glass.svg", "niri/assets/icons/input-keyboard-symbolic.svg",
    "niri/kitty/kitty.conf",
    "niri/shell/style.css", "niri/shell/panel.py", "niri/shell/shortcuts.py",
    "niri/shell/ai_backend.py", "niri/swaync/config.json", "niri/swaync/style.css",
    "niri/waybar/config.jsonc", "niri/waybar/style.css", "niri/scripts/desktop",
    "niri/scripts/components", "niri/scripts/start-session", "niri/swayidle/sleep.conf",
    "niri/swayidle/config", "niri/swaylock/config", "niri/fuzzel/fuzzel.ini",
    "niri/conf/binds.kdl", "niri/conf/local.kdl", "niri/conf/windows.kdl",
    "niri/conf/appearance.kdl", "niri/conf/outputs.kdl", "niri/conf/input.kdl",
    "niri/shell/metrics.py", "niri/shell/appearance.py", "niri/shell/audio_backend.py", "niri/theme/theme.kdl",
    "niri/shell/display_backend.py", "niri/shell/display_controls.py", "niri/shell/brightness.py",
    "niri/shell/reload_components.py", "niri/conf/display-settings.kdl",
    "niri/shell/control_center.css", "niri/shell/control_widgets.py", "niri/shell/quick_controls.py",
    "niri/shell/application_theme.py", "niri/shell/panel_motion.py",
    "niri/shell/settings_navigation.py", "niri/shell/scroll_guard.py", "niri/shell/i18n.py",
    "niri/shell/system_settings.py", "niri/shell/system_controls.py", "niri/shell/ui_assets.py",
    "niri/shell/language_settings.py", "niri/shell/language_controls.py", "niri/conf/language.kdl",
    "niri/shell/desktop_settings.py", "niri/shell/desktop_controls.py", "niri/conf/desktop-settings.kdl",
    "niri/shell/media_backend.py", "niri/shell/media_controls.py",
    "niri/shell/bluetooth_policy.py", "niri/shell/bluetooth_controls.py",
    "niri/shell/sleep_guard.py",
    "niri/shell/power_actions.py",
    "niri/shell/bar_layout.py",
    "niri/shell/font_scale.py",
    "niri/shell/lock_session.py",
    "niri/theme/panel.css", "niri/theme/waybar.css", "niri/theme/swaync.css",
    "niri/theme/fuzzel.ini", "niri/theme/kitty.conf", "niri/theme/swaylock.conf",
)


def systemd_quote(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def python_command():
    return shutil.which("python3") or sys.executable


def desired():
    service = (ROOT / "systemd/selandia-niri@.service.in").read_text()
    service = service.replace("@COMPONENTS@", systemd_quote(CONFIG / "niri/scripts/components"))
    lock = (ROOT / "systemd/selandia-lock@.service.in").read_text()
    lock = lock.replace("@PYTHON@", systemd_quote(python_command()))
    lock = lock.replace("@LOCKCLIENT@", systemd_quote(CONFIG / "niri/shell/lock_client.py"))
    return {
        "niri": {"link": str(ROOT / "niri")},
        "systemd/user/selandia-niri.target": {"link": str(ROOT / "systemd/selandia-niri.target")},
        "systemd/user/selandia-niri@.service": {"text": service},
        "systemd/user/selandia-lock@.service": {"text": lock},
        "xdg-desktop-portal/niri-portals.conf": {"link": str(ROOT / "portals/niri-portals.conf")},
    }


def exists(path):
    return path.exists() or path.is_symlink()


def matches(path, spec):
    if "link" in spec:
        return path.is_symlink() and os.readlink(path) == spec["link"]
    return path.is_file() and not path.is_symlink() and path.read_text() == spec["text"]


def write_spec(path, spec):
    path.parent.mkdir(parents=True, exist_ok=True)
    if "link" in spec:
        path.symlink_to(spec["link"])
    else:
        path.write_text(spec["text"])


def save_manifest(data):
    handle, name = tempfile.mkstemp(prefix="manifest-", dir=STATE)
    try:
        with os.fdopen(handle, "w") as out:
            json.dump(data, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(name, MANIFEST)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def deployment_lock():
    """A second setup must not back up half of another setup's transaction."""
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(tr("Another setup is running.", "另一个安装或回退操作正在运行。")) from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def reload_units():
    # Configuration installation does not start desktop components.
    try:
        result = subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        if not result.returncode:
            return
    except FileNotFoundError:
        pass
    print(tr("User systemd unavailable; run systemctl --user daemon-reload after login.", "当前无法连接用户 systemd；请登录后运行 systemctl --user daemon-reload。"))


def check_owned(entries, *, allow_missing=False):
    if not isinstance(entries, dict):
        raise RuntimeError(tr("Invalid installation manifest.", "安装记录无效。"))
    for relative, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {"original", "installed"}:
            raise RuntimeError(tr("Invalid installation entry.", "安装记录条目无效。"))
        installed = entry["installed"]
        if (not isinstance(installed, dict) or set(installed) not in ({"link"}, {"text"})
                or not all(isinstance(value, str) for value in installed.values())):
            raise RuntimeError(tr("Invalid installed-file record.", "已安装文件记录无效。"))
        original = entry["original"]
        if original is not None:
            if not isinstance(original, str) or not Path(original).is_absolute():
                raise RuntimeError(tr("Invalid backup path.", "备份路径无效。"))
            if not exists(Path(original)):
                raise RuntimeError(tr("Missing original backup; no targets were changed: ", "原始备份丢失，未改动任何目标：") + original)
        if relative not in MANAGED_PATHS:
            raise RuntimeError(tr("Unknown managed path.", "安装记录包含未知目标。"))
        target = CONFIG / relative
        # Reinstall and restore can handle a removed target without replacing user data.
        # exists() deliberately includes dangling symlinks: those remain protected.
        if not exists(target):
            if allow_missing:
                continue
            raise RuntimeError(tr("Missing installed file; reinstall to repair: ", "已安装文件缺失，请先重新安装以修复：") + str(target))
        if not matches(target, entry["installed"]):
            raise RuntimeError(tr("Refusing to replace user edits: ", "检测到安装后被替换或修改的目标，已停止以保留改动：") + str(target))


def read_manifest(*, allow_missing=False):
    data = json.loads(MANIFEST.read_text())
    if not isinstance(data, dict) or "entries" not in data:
        raise RuntimeError(tr("Invalid installation manifest.", "安装记录无效。"))
    check_owned(data["entries"], allow_missing=allow_missing)
    return data


def preflight():
    """Check sources and protected edits without creating state or touching services."""
    missing = [str(ROOT / relative) for relative in REQUIRED_SOURCES
               if not (ROOT / relative).is_file()]
    if missing:
        raise RuntimeError(tr("Missing project source files; restore this checkout first:\n",
                              "项目源文件缺失，请先恢复项目目录：\n") + "\n".join(missing))
    return read_manifest(allow_missing=True) if MANIFEST.exists() else {"entries": {}}


def preview_install():
    old = preflight()
    for relative, spec in desired().items():
        target = CONFIG / relative
        if relative in old["entries"]:
            if not exists(target):
                action = tr("Repair missing", "修复缺失")
            elif matches(target, spec):
                action = tr("Keep current", "保留当前")
            else:
                action = tr("Update managed", "更新托管配置")
        elif exists(target):
            action = tr("Back up and install", "备份后安装")
        else:
            action = tr("Install new", "新建配置")
        print(f"{action}: {target} ← {spec.get('link', tr('generated systemd service', '生成的 systemd 服务'))}")
    print(tr("Backup and restore record: ", "备份及回退记录：") + str(MANIFEST))


def preview_uninstall():
    if not MANIFEST.exists():
        print(tr("Nothing to restore.", "没有本项目的安装记录，无需回退。"))
        return
    data = read_manifest(allow_missing=True)
    print(tr("Would stop this desktop's user services.", "将停止本项目的用户服务。"))
    for relative, entry in data["entries"].items():
        target = CONFIG / relative
        if exists(target):
            print(tr("Archive managed: ", "归档托管配置：") + str(target))
        else:
            print(tr("Already absent: ", "目标已缺失：") + str(target))
        if entry["original"]:
            print(tr("Restore original: ", "恢复原配置：") + f"{target} ← {entry['original']}")
    print(tr("Packages, wallpaper choice and clipboard data preserved.", "保留软件包、壁纸选择和剪贴板数据。"))


def status():
    data = preflight()
    if not MANIFEST.exists():
        print(tr("Not installed.", "尚未安装本项目的配置。"))
        return 1
    healthy = True
    for relative, spec in desired().items():
        target = CONFIG / relative
        if relative not in data["entries"]:
            print(tr("Not managed yet: ", "尚未部署：") + str(target))
            healthy = False
        elif not exists(target):
            print(tr("Missing managed file: ", "托管配置缺失：") + str(target))
            healthy = False
        elif not matches(target, spec):
            print(tr("Update needed: ", "需要更新：") + str(target))
            healthy = False
        else:
            print(tr("Ready: ", "正常：") + str(target))
    return 0 if healthy else 1


def install():
    old = preflight()
    STATE.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix="backup-", dir=STATE))
    entries = dict(old["entries"])
    changes = []
    try:
        for relative, spec in desired().items():
            target = CONFIG / relative
            if relative in entries and matches(target, spec):
                continue
            backup = transaction / relative if exists(target) else None
            if backup:
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))
            changes.append((target, backup))
            write_spec(target, spec)
            original = entries[relative]["original"] if relative in entries else (str(backup) if backup else None)
            entries[relative] = {"original": original, "installed": spec}
            print(tr("Install: ", "安装：") + str(target))
        save_manifest({"source": str(ROOT), "entries": entries})
    except BaseException:
        for target, backup in reversed(changes):
            if target.is_symlink() or target.is_file():
                target.unlink()
            if backup and exists(backup):
                shutil.move(str(backup), str(target))
        raise
    reload_units()
    print(tr("Configuration ready; backup record: ", "配置已就绪，备份记录：") + str(MANIFEST))
    print(tr("Log out when ready, then select Niri at login.", "保存工作后注销，在登录界面选择 Niri。"))


def uninstall():
    if not MANIFEST.exists():
        print(tr("Nothing to restore.", "没有本项目的安装记录，无需回退。"))
        return
    data = read_manifest(allow_missing=True)
    try:
        result = subprocess.run(["systemctl", "--user", "stop", "selandia-niri.target"], check=False)
    except FileNotFoundError as error:
        raise RuntimeError(tr("Cannot stop desktop services: systemctl is missing. Restore systemd and retry as your desktop user; "
                              "configuration was not changed.", "无法停止桌面服务：缺少 systemctl。请恢复 systemd 后以桌面用户重试；配置未改动。")) from error
    if result.returncode:
        raise RuntimeError(tr("Could not stop desktop services; configuration was not changed. "
                              "Check systemctl --user status selandia-niri.target from your desktop login, then retry.",
                              "无法停止桌面服务，配置未改动。请在桌面用户会话检查 systemctl --user status selandia-niri.target 后重试。"))
    archive = Path(tempfile.mkdtemp(prefix="removed-", dir=STATE))
    changes = []
    try:
        for relative, entry in data["entries"].items():
            target = CONFIG / relative
            saved = archive / relative if exists(target) else None
            if saved:
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(saved))
            original = Path(entry["original"]) if entry["original"] else None
            changes.append((target, saved, original))
            if original:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(original), str(target))
            print(tr("Restore: ", "回退：") + str(target))
        shutil.move(str(MANIFEST), str(archive / "install.json"))
    except BaseException:
        for target, saved, original in reversed(changes):
            if original and exists(target):
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(original))
            if saved and exists(saved):
                shutil.move(str(saved), str(target))
        raise
    reload_units()
    print(tr("Original configuration restored; removed files: ", "已恢复原配置，移除的配置保留在：") + str(archive))
    print(tr("Packages, wallpaper choice and clipboard data preserved.", "保留软件包、壁纸选择和剪贴板数据。"))


def main():
    if not CONFIG.is_absolute() or not STATE.is_absolute():
        raise RuntimeError(tr("XDG_CONFIG_HOME and XDG_STATE_HOME must be absolute paths.", "XDG_CONFIG_HOME 和 XDG_STATE_HOME 必须是绝对路径。"))
    mode = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    if mode == "preflight":
        preflight()
        print(tr("Deployment preflight passed.", "部署预检查通过。"))
        return
    if mode == "dry-run":
        preview_install()
        return
    if mode == "dry-run-uninstall":
        preview_uninstall()
        return
    if mode == "status":
        return status()
    if os.geteuid() == 0:
        raise RuntimeError(tr("Run as your desktop user; do not run this script with sudo.", "请以当前桌面用户运行安装脚本，不要 sudo 整个脚本。"))
    if mode not in {"install", "uninstall"}:
        raise RuntimeError(tr("Unknown operation: ", "未知操作：") + mode)
    with deployment_lock():
        if mode == "install":
            install()
        else:
            uninstall()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(tr("Error: ", "错误：") + str(error), file=sys.stderr)
        sys.exit(1)
