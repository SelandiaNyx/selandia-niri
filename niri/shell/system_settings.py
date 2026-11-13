"""Arch desktop settings with explicit actions and bounded configuration writes."""
from __future__ import annotations

import configparser
import io
import json
import os
from pathlib import Path
import re
import subprocess
import base64
import session_settings

from appearance import BASE, _commit, preferences_path
from i18n import tr

MANAGED_UNITS = {
    "clipboard": ("selandia-niri@clipboard-text.service", "selandia-niri@clipboard-image.service"),
    "notifications": ("selandia-niri@notifications.service",),
    "bar": ("selandia-niri@waybar.service",),
}
DEFAULT_POWER = {"lock_minutes": 5, "screen_minutes": 10, "suspend_minutes": 0}
APP_TYPES = {"browser": ("x-scheme-handler/http", "x-scheme-handler/https"),
             "mail": ("x-scheme-handler/mailto",), "files": ("inode/directory",),
             "text": ("text/plain",), "pdf": ("application/pdf",),
             "image": ("image/png", "image/jpeg"), "video": ("video/mp4",)}
DESKTOP_ID = re.compile(r"[^/\x00\r\n]+\.desktop\Z")


def run(argv, *, timeout=8, check=True):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env=dict(os.environ, LC_ALL="C"))
    if check and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-500:] or str(argv[0]))
    return result.stdout.strip()


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _gio():
    from gi.repository import Gio
    return Gio


def application_state():
    Gio = _gio()
    result = {}
    for role, mime_types in APP_TYPES.items():
        default = Gio.AppInfo.get_default_for_type(mime_types[0], False)
        apps = Gio.AppInfo.get_all_for_type(mime_types[0])
        if default and not any(app.get_id() == default.get_id() for app in apps):
            apps.insert(0, default)
        choices = {app.get_id(): app.get_display_name() for app in apps if app.get_id()}
        result[role] = {"default": default.get_id() if default else None,
                        "choices": sorted(choices.items(), key=lambda pair: pair[1].casefold())}
    return result


def set_default_application(role, identifier):
    if (role not in APP_TYPES or not isinstance(identifier, str)
            or not DESKTOP_ID.fullmatch(identifier)):
        raise ValueError(tr("Choose an installed application.", "请选择已安装的应用。"))
    Gio = _gio()
    app = Gio.DesktopAppInfo.new(identifier)
    if app is None:
        raise ValueError(tr("The application is no longer installed.", "该应用已不再安装。"))
    # Updating related MIME types is explicit. Report failure instead of claiming
    # every association succeeded when the desktop database rejects one of them.
    for mime in APP_TYPES[role]:
        if not app.set_as_default_for_type(mime):
            raise RuntimeError(tr("Could not save the default application.", "无法保存默认应用。"))


def power_state(*, base=None, state_path=None):
    base = Path(base or BASE)
    path = Path(state_path or preferences_path().with_name("power.json"))
    saved = True
    try:
        values = validate_power(json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        values = dict(DEFAULT_POWER)
        saved = False
    managed = base / "swayidle/managed.conf"
    configured = managed.exists()
    effective = managed if configured else base / "swayidle/config"
    try:
        config = effective.read_text()
        error = ""
    except OSError as failure:
        config = ""
        error = str(failure)
    return {"settings": values, "configured": configured, "config_path": str(effective),
            "timers_enabled": _power_timers_enabled(config), "config_error": error,
            "consistent": (saved and not error and _power_commands(config)
                           == _power_commands(render_power(values))) if configured else None}


def _power_commands(config):
    """Compare generated settings without treating comments as configuration edits."""
    import shlex
    try:
        return [tuple(shlex.split(line, comments=True)) for line in config.splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    except ValueError:
        return None


def _power_timers_enabled(config):
    return any(int(seconds) > 0 for seconds in
               re.findall(r"^\s*timeout\s+([0-9]+)(?:\s|$)", config, re.MULTILINE))


def validate_power(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULT_POWER):
        raise ValueError(tr("Invalid power settings.", "电源设置无效。"))
    result = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 240:
            raise ValueError(tr("Timeouts must be whole minutes between 0 and 240.", "超时须为 0 至 240 之间的整数分钟。"))
        result[key] = value
    lock, screen, suspend = (result[key] for key in DEFAULT_POWER)
    if screen and lock and screen < lock:
        raise ValueError(tr("Screen off must follow automatic locking.", "自动息屏时间不能早于锁屏。"))
    if suspend and (not lock or suspend < lock or screen and suspend < screen):
        raise ValueError(tr("Automatic suspend requires an earlier lock timeout and must follow screen off.", "自动睡眠需要先锁屏，且时间不能早于息屏。"))
    return result


def render_power(values):
    values = validate_power(values)
    lines = ["# Managed by Selandia Niri power settings."]
    if values["lock_minutes"]:
        lines.append(f"timeout {values['lock_minutes'] * 60} '\"${{XDG_CONFIG_HOME:-$HOME/.config}}/niri/scripts/desktop\" lock'")
    if values["screen_minutes"]:
        lines.append(f"timeout {values['screen_minutes'] * 60} 'niri msg action power-off-monitors' resume 'niri msg action power-on-monitors'")
    if values["suspend_minutes"]:
        lines.append(f"timeout {values['suspend_minutes'] * 60} '\"${{XDG_CONFIG_HOME:-$HOME/.config}}/niri/scripts/desktop\" sleep'")
    # With no events swayidle exits successfully. This means timers are disabled,
    # not that a sleep inhibitor is held or that the user paused the service.
    return "\n".join(lines) + "\n"


def save_power(values, *, base=None, state_path=None, reload=True):
    import fcntl

    base = Path(base or BASE)
    state = Path(state_path or preferences_path().with_name("power.json"))
    values = validate_power(values)
    state.parent.mkdir(parents=True, exist_ok=True)
    (base / "swayidle").mkdir(parents=True, exist_ok=True)
    files = {base / "swayidle/managed.conf": render_power(values).encode(),
             state: (json.dumps(values) + "\n").encode()}
    # Keep a concurrent Apply from being rolled back by an earlier failed reload.
    with (state.parent / "power.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous_enabled = power_state(base=base, state_path=state)["timers_enabled"]
        original = {path: (path.read_bytes(), path.stat().st_mode & 0o7777)
                    if path.exists() else (None, None) for path in files}
        _commit(files, private=state)
        if reload:
            try:
                from sleep_guard import apply_timers
                apply_timers(any(values.values()))
            except Exception as failure:
                recovery_error = ""
                try:
                    _commit({path: data for path, (data, _mode) in original.items()
                             if data is not None})
                    for path, (data, mode) in original.items():
                        if data is None:
                            path.unlink(missing_ok=True)
                        else:
                            path.chmod(mode)
                except OSError as recovery:
                    recovery_error = tr("Could not restore the previous files: ", "无法恢复原配置文件：") + str(recovery)
                if not recovery_error:
                    try:
                        from sleep_guard import apply_timers
                        apply_timers(previous_enabled)
                    except Exception as recovery:
                        recovery_error = tr("Files restored, but the previous timers could not be reloaded: ",
                                            "配置文件已恢复，但原计时器未能重新加载：") + str(recovery)
                message = tr("Power settings were not applied. ", "电源设置未应用。") + str(failure)
                if recovery_error:
                    message += "\n" + recovery_error
                else:
                    message += tr(" Previous settings restored.", " 原设置已恢复。")
                raise RuntimeError(message) from failure
    return values


def service_state():
    result = {}
    for group, units in MANAGED_UNITS.items():
        states = [run(["systemctl", "--user", "is-enabled", unit], check=False) for unit in units]
        active = [run(["systemctl", "--user", "is-active", unit], check=False) for unit in units]
        if any(not value for value in states + active):
            # is-enabled/is-active also return nonzero for legitimate states
            # such as masked/inactive. An empty reply, however, is not a state
            # and commonly means that the user bus could not be reached.
            raise RuntimeError(tr("Could not read desktop services. Check the user session and try again.",
                                  "无法读取桌面服务状态，请检查用户会话后重试。"))
        result[group] = {"enabled": all(value not in ("masked", "masked-runtime", "not-found", "") for value in states),
                         "active": all(value == "active" for value in active)}
    return result


def set_service(group, enabled):
    if group not in MANAGED_UNITS or not isinstance(enabled, bool):
        raise ValueError(tr("Unknown desktop service.", "未知的桌面服务。"))
    units = MANAGED_UNITS[group]
    desired = {"systemd/user/" + unit: None if enabled else {"link": "/dev/null"} for unit in units}
    with session_settings.record_changes(config_home(), desired):
        if enabled:
            run(["systemctl", "--user", "unmask", *units])
            run(["systemctl", "--user", "start", *units])
        else:
            run(["systemctl", "--user", "mask", "--now", *units])


def time_state():
    output = run(["timedatectl", "show", "--property=Timezone,NTP,CanNTP,NTPSynchronized,LocalRTC"])
    values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    return {"timezone": values.get("Timezone", ""), "ntp": values.get("NTP") == "yes",
            "can_ntp": values.get("CanNTP") == "yes", "synchronized": values.get("NTPSynchronized") == "yes"}


def timezones():
    return run(["timedatectl", "list-timezones"]).splitlines()


def _timedate(method, signature, arguments):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    bus.call_sync("org.freedesktop.timedate1", "/org/freedesktop/timedate1",
                  "org.freedesktop.timedate1", method, GLib.Variant(signature, arguments), None,
                  Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 120000, None)


def set_timezone(zone):
    if not isinstance(zone, str) or zone not in timezones():
        raise ValueError(tr("Choose a timezone from the installed list.", "请选择系统提供的时区。"))
    _timedate("SetTimezone", "(sb)", (zone, True))


def set_ntp(enabled):
    if not isinstance(enabled, bool):
        raise ValueError(tr("Invalid time synchronization state.", "时间同步状态无效。"))
    _timedate("SetNTP", "(bb)", (enabled, True))


def external_startup(*, home=None, config_dirs=None, owned_ids=()):
    """Read effective XDG entries; a user file overrides a system file by name.

    NoDisplay hides a launcher, not an autostart. Existing third-party entries
    are displayed with their source and never claimed by our write/delete API.
    """
    home = Path(home or config_home())
    if config_dirs is None:
        config_dirs = [Path(value) for value in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")
                       if value and Path(value).is_absolute()]
    effective = {}
    for root in reversed([home, *map(Path, config_dirs)]):
        for path in sorted((root / "autostart").glob("*.desktop")):
            effective[path.name] = path
    result = []
    for identifier, path in sorted(effective.items()):
        if identifier in owned_ids:
            continue
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.optionxform = str
        try:
            config.read(path)
            entry = config["Desktop Entry"]
            only = set(filter(None, entry.get("OnlyShowIn", "").split(";")))
            excluded = set(filter(None, entry.get("NotShowIn", "").split(";")))
            if only and "niri" not in only or "niri" in excluded:
                continue
            if entry.get("Type", "Application") != "Application":
                continue
            try:
                app = _gio().DesktopAppInfo.new_from_filename(str(path))
            except TypeError:
                # Gio rejects entries with a missing TryExec or incomplete
                # launcher fields. They still have useful autostart metadata.
                app = None
            name = app.get_display_name() if app else entry.get("Name", path.stem)
            result.append({"id": identifier, "name": name, "path": str(path),
                           "source": "user" if path.parent == home / "autostart" else "system",
                           "enabled": entry.get("Hidden", "false").lower() != "true"})
        except (OSError, KeyError, configparser.Error):
            continue
    return result


def startup_state(*, home=None, config_dirs=None):
    Gio = _gio()
    directory = Path(home or config_home()) / "autostart"
    owned = []
    for path in sorted(directory.glob("selandia-niri-*.desktop")):
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.optionxform = str
        try:
            config.read(path)
            entry = config["Desktop Entry"]
            if entry.get("X-Selandia-Niri-Managed") != "true":
                continue
            owned.append({"id": path.name, "name": entry.get("Name", path.stem),
                          "enabled": entry.get("Hidden", "false").lower() != "true"})
        except (OSError, KeyError, configparser.Error):
            continue
    apps = {app.get_id(): app.get_display_name() for app in Gio.AppInfo.get_all()
            if app.get_id() and app.should_show()}
    return {"entries": owned, "applications": sorted(apps.items(), key=lambda pair: pair[1].casefold()),
            "external_entries": external_startup(home=home, config_dirs=config_dirs,
                                                 owned_ids={item["id"] for item in owned})}


def add_startup(identifier, *, home=None):
    if not isinstance(identifier, str) or not DESKTOP_ID.fullmatch(identifier):
        raise ValueError(tr("Choose an installed application.", "请选择已安装的应用。"))
    app = _gio().DesktopAppInfo.new(identifier)
    if app is None or not app.get_filename():
        raise ValueError(tr("Application desktop entry is unavailable.", "应用启动文件不可用。"))
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    config.read(app.get_filename())
    entry = config["Desktop Entry"]
    entry["OnlyShowIn"] = "niri;"
    for key in ("NotShowIn", "X-GNOME-Autostart-Delay", "X-GNOME-Autostart-enabled"):
        entry.pop(key, None)
    entry["Hidden"] = "false"
    entry["X-Selandia-Niri-Managed"] = "true"
    path = Path(home or config_home()) / "autostart" / ("selandia-niri-" + identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(tr("Startup entry is a symbolic link.", "启动项是符号链接，不能覆盖。"))
    if path.exists():
        existing = configparser.ConfigParser(interpolation=None, strict=False)
        existing.optionxform = str
        existing.read(path)
        if existing.get("Desktop Entry", "X-Selandia-Niri-Managed", fallback="") != "true":
            raise ValueError(tr("An unrelated startup entry already uses this name.", "同名启动项已被其他配置使用。"))
    stream = io.StringIO()
    config.write(stream, space_around_delimiters=False)
    contents = stream.getvalue().encode()
    value = {"bytes": base64.b64encode(contents).decode(), "mode": path.stat().st_mode & 0o7777 if path.exists() else 0o644}
    with session_settings.record_changes(path.parent.parent, {str(path.relative_to(path.parent.parent)): value}):
        _commit({path: contents})


def _managed_startup(identifier, home=None):
    """Resolve one entry this project owns; foreign names never resolve.

    Every managed entry is named ``selandia-niri-*.desktop``, so a name without
    that prefix, a name with a path separator, and a symbolic link are all
    refused before anything is read, rewritten or deleted.
    """
    if (not isinstance(identifier, str) or not identifier.startswith("selandia-niri-")
            or not DESKTOP_ID.fullmatch(identifier)):
        raise ValueError(tr("Invalid managed startup entry.", "托管启动项无效。"))
    path = Path(home or config_home()) / "autostart" / identifier
    if path.is_symlink():
        raise ValueError(tr("Startup entry is a symbolic link.", "启动项是符号链接。"))
    return path


def _owned_startup(path):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    config.read(path)
    if config.get("Desktop Entry", "X-Selandia-Niri-Managed", fallback="") != "true":
        raise ValueError(tr("This startup entry is not managed by Niri settings.", "此启动项不由 Niri 设置管理。"))
    return config


def toggle_startup(identifier, enabled, *, home=None):
    if not isinstance(enabled, bool):
        raise ValueError(tr("Invalid managed startup entry.", "托管启动项无效。"))
    path = _managed_startup(identifier, home)
    config = _owned_startup(path)
    config["Desktop Entry"]["Hidden"] = str(not enabled).lower()
    stream = io.StringIO()
    config.write(stream, space_around_delimiters=False)
    contents = stream.getvalue().encode()
    value = {"bytes": base64.b64encode(contents).decode(), "mode": path.stat().st_mode & 0o7777}
    with session_settings.record_changes(path.parent.parent, {str(path.relative_to(path.parent.parent)): value}):
        _commit({path: contents})


def remove_startup(identifier, *, home=None):
    """Delete one entry this project created; a user's own file is never removed."""
    path = _managed_startup(identifier, home)
    if not path.is_file():
        raise ValueError(tr("This startup entry no longer exists.", "此启动项已不存在。"))
    _owned_startup(path)
    try:
        with session_settings.record_changes(path.parent.parent, {str(path.relative_to(path.parent.parent)): None}):
            path.unlink()
    except OSError as error:
        raise RuntimeError(tr("Could not remove the startup entry: ", "无法移除启动项：")
                           + str(error)) from error


def _nm_fields(line):
    fields, value, escaped = [], [], False
    for char in line:
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(value))
            value = []
        else:
            value.append(char)
    fields.append("".join(value))
    return fields


def network_state():
    output = run(["nmcli", "--terse", "--escape", "yes", "--fields", "UUID,NAME,TYPE,DEVICE", "connection", "show"])
    profiles = []
    for line in output.splitlines():
        fields = _nm_fields(line)
        if len(fields) == 4 and re.fullmatch(r"[0-9a-fA-F-]{36}", fields[0]):
            profiles.append({"id": fields[0], "name": fields[1], "type": fields[2],
                             "device": "" if fields[3] == "--" else fields[3]})
    return profiles


def activate_connection(identifier, enabled):
    if (not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", identifier)
            or not isinstance(enabled, bool)):
        raise ValueError(tr("Choose a saved network connection.", "请选择已保存的网络连接。"))
    run(["nmcli", "--wait", "30", "connection", "up" if enabled else "down", "uuid", identifier], timeout=35)
