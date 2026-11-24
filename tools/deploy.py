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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from transactions import Transaction, atomic_bytes, file_value

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
    "tools/run_tests.py",
    "niri/shell/notification_events.py", "niri/shell/notification_policy.py", "niri/shell/notification_rules.py", "niri/shell/notification_history.py",
    "niri/shell/audio_events.py", "niri/shell/media_events.py", "niri/shell/calendar_widget.py",
    "niri/eww/input_region.rs", "niri/shell/eww_input.py",
    "tools/protocols/wlr-virtual-pointer.xml",
    "niri/shell/component_preferences.py", "niri/shell/bar_backend.py", "niri/shell/island.py", "niri/shell/niri_events.py", "niri/assets/icons/empty.svg",
    "niri/anyrun/config.ron", "niri/anyrun/style.css",
    "niri/theme/eww.css", "niri/theme/anyrun.css", "niri/theme/alacritty.toml",
    "control.sh", "install.sh", "check.sh", "packages.txt",
    "tools/export_config.py", "tools/lifecycle.py", "tools/transactions.py", "docs/INSTALL.md",
    "systemd/selandia-niri@.service.in", "systemd/selandia-niri.target",
    "systemd/selandia-lock@.service.in", "niri/shell/lock_client.py",
    "portals/niri-portals.conf", "niri/config.kdl", "niri/preview.kdl", "niri/monitor.kdl",
    "niri/assets/selandia-glass.svg", "niri/assets/icons/input-keyboard-symbolic.svg",
    "niri/assets/anime/README.md",
    "niri/assets/anime/mascot-full.png", "niri/assets/anime/mascot-gemini.png",
    "niri/assets/anime/mascot-antigravity.png", "niri/assets/anime/mascot-engineer.png",
    "niri/assets/anime/mascot-obsidian.png", "niri/assets/anime/mascot-peek.png",
    "niri/assets/anime/mascot-avatar.png", "niri/assets/anime/mascot-avatar-64.png",
    "niri/assets/anime/mascot-avatar-gemini.png", "niri/assets/anime/mascot-avatar-antigravity.png",
    "niri/assets/anime/mascot-avatar-engineer.png", "niri/assets/anime/mascot-avatar-obsidian.png",
    "niri/assets/anime/mascot-sleepy.png", "niri/assets/anime/mascot-thinking.png",
    "niri/assets/anime/lock-bg.png", "niri/assets/anime/lock-bg-light.png",
    "niri/assets/anime/paw.svg", "niri/assets/anime/paw-symbolic.svg",
    "niri/assets/anime/sakura.svg", "niri/assets/anime/sakura-symbolic.svg",
    "niri/assets/anime/star-sparkle.svg", "niri/assets/anime/star-sparkle-symbolic.svg",
    "niri/assets/anime/heart.svg", "niri/assets/anime/heart-symbolic.svg",
    "niri/assets/anime/cat-ears.svg", "niri/assets/anime/cat-ears-symbolic.svg",
    "niri/assets/anime/ribbon.svg", "niri/assets/anime/ribbon-symbolic.svg",
    "niri/assets/anime/cloud.svg", "niri/assets/anime/cloud-symbolic.svg",
    "niri/shell/style.css", "niri/shell/panel.py", "niri/shell/surface_registry.py",
    "niri/shell/panel_support.py", "niri/shell/panel_audio.py", "niri/shell/panel_system.py",
    "niri/shell/panel_appearance.py", "niri/shell/panel_quick.py", "niri/shell/panel_ai.py",
    "niri/shell/panel_network.py", "niri/shell/panel_bluetooth.py", "niri/shell/panel_storage.py",
    "niri/shell/panel_services.py", "niri/shell/panel_logs.py", "niri/shell/panel_packages.py",
    "niri/shell/panel_security.py", "niri/shell/panel_preferences.py",
    "niri/shell/polkit_helper.py", "niri/shell/network_backend.py", "niri/shell/bluetooth_backend.py",
    "niri/shell/storage_backend.py", "niri/shell/night_light.py", "niri/shell/process_backend.py",
    "niri/shell/systemd_backend.py", "niri/shell/journal_backend.py", "niri/shell/package_docker_backend.py",
    "niri/shell/security_backend.py", "niri/shell/command_palette.py",
    "niri/shell/display_canvas.py", "niri/shell/sparkline_widget.py",
    "niri/shell/navigation_catalog.py", "niri/shell/page_host.py", "niri/shell/drawers.py",
    "niri/shell/background_tasks.py", "niri/shell/gpu_metrics.py",
    "niri/shell/shortcuts.py",
    "niri/shell/ai_backend.py", "niri/shell/ai_store.py", "niri/shell/wallpaper_audio.py", "niri/shell/engine_compatibility.py",
    "niri/swaync/config.json", "niri/swaync/style.css",
    "niri/scripts/desktop",
    "niri/shell/application_audio.py", "niri/shell/panel_geometry.py",
    "niri/shell/system_info.py", "niri/shell/wallpaper_playlist.py",
    "niri/shell/wallpaper_options.py", "niri/shell/wallpaper_preferences.py", "niri/shell/wallpaper_remote.py", "niri/shell/wallpaper_fade.py",
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
    "niri/shell/session_settings.py",
    "niri/shell/session_identity.py",
    "niri/shell/language_settings.py", "niri/shell/language_controls.py", "niri/conf/language.kdl",
    "niri/shell/desktop_settings.py", "niri/shell/desktop_controls.py", "niri/conf/desktop-settings.kdl",
    "niri/shell/media_backend.py", "niri/shell/media_controls.py",
    "niri/shell/bluetooth_policy.py", "niri/shell/bluetooth_controls.py",
    "niri/shell/sleep_guard.py",
    "niri/shell/power_actions.py",
    "niri/shell/power_menu.py",
    "niri/shell/wallpaper.py", "niri/shell/wallpaper_controls.py",
    "niri/shell/font_scale.py",
    "niri/shell/lock_session.py",
    "niri/theme/panel.css", "niri/theme/swaync.css",
    "niri/theme/fuzzel.ini", "niri/theme/swaylock.conf",
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
    if ACTIVE_TRANSACTION is not None:
        ACTIVE_TRANSACTION.create(path, spec)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        if "link" in spec:
            path.symlink_to(spec["link"])
        else:
            atomic_bytes(path, spec["text"].encode(), 0o644)


def save_manifest(data):
    contents = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    if ACTIVE_TRANSACTION is None:
        atomic_bytes(MANIFEST, contents)
    else:
        import base64
        ACTIVE_TRANSACTION.replace(MANIFEST, file_value(MANIFEST),
                                   {"bytes": base64.b64encode(contents).decode(), "mode": 0o600})


ACTIVE_TRANSACTION = None


def transaction_path():
    return STATE / "deployment-transaction.json"


def transaction_allowed(path):
    if path == MANIFEST or path in {CONFIG / name for name in MANAGED_PATHS}:
        return True
    try:
        relative = path.relative_to(STATE)
    except ValueError:
        return False
    return (len(relative.parts) > 1 and relative.parts[0].startswith(("backup-", "removed-"))
            and str(Path(*relative.parts[1:])) in MANAGED_PATHS | {"install.json"})


def transaction(metadata=None):
    return Transaction(transaction_path(), {"source": str(ROOT), "config": str(CONFIG)},
                       allowed=transaction_allowed, metadata=metadata)


def recover(*, restart=True, commit=False):
    if not transaction_path().exists():
        return
    pending = transaction()
    if commit or pending.data["phase"] == "committed":
        pending.commit()
    else:
        def restore_services(saved):
            if restart and saved.get("was_active"):
                subprocess.run(["systemctl", "--user", "start", "selandia-niri.target"], check=True, timeout=15)
        pending.rollback(restore_services)
    reload_units()


def check_coordinator(*, defer=False):
    if not defer and (STATE / "lifecycle-transaction.json").exists():
        raise RuntimeError(tr("Coordinated setup needs recovery; retry control.sh install or uninstall.",
                              "存在需要恢复的完整安装事务；请重试 control.sh install 或 uninstall。"))


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
        result = subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, timeout=15)
        if not result.returncode:
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
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


def preflight(*, coordinated=False):
    """Check sources and protected edits without creating state or touching services."""
    if transaction_path().exists() or (not coordinated and (STATE / "lifecycle-transaction.json").exists()):
        print(tr("Interrupted setup will be recovered before changes.", "将先恢复中断的部署事务，再执行改动。"))
        return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"entries": {}}
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
    if transaction_path().exists() or (STATE / "lifecycle-transaction.json").exists():
        print(tr("Would recover interrupted setup before calculating removal.", "将先恢复中断的部署事务，再计算卸载操作。"))
        return
    sys.path.insert(0, str(ROOT / "niri/shell"))
    try:
        import session_settings
    except ModuleNotFoundError as error:
        if error.name != "session_settings":
            raise
        print(tr("Session settings helper unavailable; their original-state records remain preserved. Restore the source to preview those settings.",
                 "会话设置模块缺失；保留其原状态记录，恢复源码后才能预览这些条目。"))
    else:
        _data, restored, preserved = session_settings.restoration_plan(CONFIG, STATE / session_settings.JOURNAL)
        for relative in restored:
            print(tr("Would restore session setting: ", "将恢复项目会话设置：") + str(CONFIG / relative))
        for relative in preserved:
            print(tr("Preserve edited or unrecorded session setting: ", "保留手工编辑或无原状态记录的会话设置：") + str(CONFIG / relative))
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
    if transaction_path().exists() or (STATE / "lifecycle-transaction.json").exists():
        print(tr("Interrupted setup needs recovery.", "存在中断的部署事务，需要恢复。"))
        return 1
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


def install(*, defer=False):
    global ACTIVE_TRANSACTION
    check_coordinator(defer=defer)
    recover()
    old = preflight(coordinated=defer)
    STATE.mkdir(parents=True, exist_ok=True)
    backup_directory = Path(tempfile.mkdtemp(prefix="backup-", dir=STATE))
    entries = dict(old["entries"])
    pending = transaction({"action": "install"})
    ACTIVE_TRANSACTION = pending
    try:
        for relative, spec in desired().items():
            target = CONFIG / relative
            if relative in entries and matches(target, spec):
                continue
            backup = backup_directory / relative if exists(target) else None
            if backup:
                backup.parent.mkdir(parents=True, exist_ok=True)
                pending.move(target, backup)
            pending.create_intent(target, spec)
            write_spec(target, spec)
            original = entries[relative]["original"] if relative in entries else (str(backup) if backup else None)
            entries[relative] = {"original": original, "installed": spec}
            print(tr("Install: ", "安装：") + str(target))
        save_manifest({"source": str(ROOT), "entries": entries})
    except BaseException:
        pending.rollback()
        raise
    finally:
        ACTIVE_TRANSACTION = None
    if not defer:
        pending.commit()
        reload_units()
    print(tr("Configuration ready; backup record: ", "配置已就绪，备份记录：") + str(MANIFEST))
    print(tr("Log out when ready, then select Niri at login.", "保存工作后注销，在登录界面选择 Niri。"))


def uninstall(*, defer=False):
    check_coordinator(defer=defer)
    recover()
    if not MANIFEST.exists():
        print(tr("Nothing to restore.", "没有本项目的安装记录，无需回退。"))
        return
    data = read_manifest(allow_missing=True)
    try:
        was_active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "selandia-niri.target"], check=False, timeout=5).returncode == 0
    except FileNotFoundError as error:
        raise RuntimeError(tr("Cannot stop desktop services: systemctl is missing; configuration was not changed.",
                              "无法停止桌面服务：缺少 systemctl；配置未改动。")) from error
    state_times = (STATE.stat().st_atime_ns, STATE.stat().st_mtime_ns)
    pending = transaction({"action": "uninstall", "was_active": was_active})
    pending.save()  # Includes service state before stop, even before the first file move.
    try:
        result = subprocess.run(["systemctl", "--user", "stop", "selandia-niri.target"], check=False, timeout=15)
    except FileNotFoundError as error:
        pending.rollback()
        os.utime(STATE, ns=state_times)
        raise RuntimeError(tr("Cannot stop desktop services: systemctl is missing. Restore systemd and retry as your desktop user; "
                              "configuration was not changed.", "无法停止桌面服务：缺少 systemctl。请恢复 systemd 后以桌面用户重试；配置未改动。")) from error
    if result.returncode:
        pending.rollback()
        os.utime(STATE, ns=state_times)
        raise RuntimeError(tr("Could not stop desktop services; configuration was not changed. "
                              "Check systemctl --user status selandia-niri.target from your desktop login, then retry.",
                              "无法停止桌面服务，配置未改动。请在桌面用户会话检查 systemctl --user status selandia-niri.target 后重试。"))
    archive = Path(tempfile.mkdtemp(prefix="removed-", dir=STATE))
    try:
        for relative, entry in data["entries"].items():
            target = CONFIG / relative
            saved = archive / relative if exists(target) else None
            if saved:
                saved.parent.mkdir(parents=True, exist_ok=True)
                pending.move(target, saved)
            original = Path(entry["original"]) if entry["original"] else None
            if original:
                target.parent.mkdir(parents=True, exist_ok=True)
                pending.move(original, target)
            print(tr("Restore: ", "回退：") + str(target))
        pending.move(MANIFEST, archive / "install.json")
    except BaseException:
        def restore_services(metadata):
            if metadata.get("was_active") and not defer:
                subprocess.run(["systemctl", "--user", "start", "selandia-niri.target"], check=True, timeout=15)
        pending.rollback(restore_services)
        raise
    if not defer:
        pending.commit()
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
    if mode not in {"install", "uninstall", "recover"}:
        raise RuntimeError(tr("Unknown operation: ", "未知操作：") + mode)
    with deployment_lock():
        if mode == "recover":
            check_coordinator()
            recover()
        elif mode == "install":
            install()
        else:
            uninstall()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(tr("Error: ", "错误：") + str(error), file=sys.stderr)
        sys.exit(1)
