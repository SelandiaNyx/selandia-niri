#!/usr/bin/env python3
"""Synchronize Niri appearance with GTK, portal, qt6ct and KDE preferences.

Only named settings are managed. A private journal records their original values;
restore preserves later user edits. Nothing is applied merely by importing this file.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re

import font_scale
import subprocess
import sys

import appearance

SCHEMA = "org.gnome.desktop.interface"
CSS_FILES = ("gtk-3.0/gtk.css", "gtk-4.0/gtk.css")
QT6CT_CONFIG = "qt6ct/qt6ct.conf"
QT6CT_PALETTE = "qt6ct/colors/selandia.conf"
RELATIVE_FILES = ("gtk-3.0/settings.ini", "gtk-4.0/settings.ini", "kdeglobals",
                  QT6CT_CONFIG, QT6CT_PALETTE, *CSS_FILES)
MIGRATED_CSS = "/* Selandia Niri: previous Matugen overrides are backed up in application-theme.json. */\n"
GSETTINGS_KEYS = ("color-scheme", "gtk-theme", "font-name", "monospace-font-name", "icon-theme")


def config_directory() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).absolute()


def journal_path() -> Path:
    return appearance.preferences_path().with_name("application-theme.json")


def _read(path: Path) -> str | None:
    if path.is_symlink() or path.exists() and not path.is_file():
        raise OSError(f"Non-regular configuration file / 配置文件不是普通文件: {path}")
    return path.read_text() if path.exists() else None


def _lines(source: str):
    section = ""
    for line in source.splitlines(keepends=True):
        header = re.fullmatch(r"\s*\[(.+)\]\s*", line)
        if header:
            section = header[1]
        key = None
        if not header and "=" in line and not line.lstrip().startswith(("#", ";")):
            key = line.split("=", 1)[0].strip()
        yield section, key, line


def _values(source: str, section: str, key: str) -> list[str]:
    return [line.split("=", 1)[1].strip() for group, name, line in _lines(source)
            if (group, name) == (section, key)]


def _set_values(source: str, section: str, key: str, values: list[str]) -> str:
    """Replace one INI key, including duplicate entries, keeping other lines exact."""
    result = []
    seen = False
    inserted = False
    previous = ""
    replacement = "".join(f"{key}={value}\n" for value in values)
    for group, name, line in _lines(source):
        if previous == section and group != section and not inserted:
            result.append(replacement)
            inserted = True
        if group == section:
            seen = True
        if (group, name) == (section, key):
            if not inserted:
                result.append(replacement)
                inserted = True
        else:
            result.append(line)
        previous = group
    if not inserted and values:
        if result and not result[-1].endswith("\n"):
            result.append("\n")
        if not seen:
            result.append(f"\n[{section}]\n")
        result.append(replacement)
    return "".join(result)


def _restore_owned(source: str, records: dict) -> tuple[str, list[str]]:
    skipped = []
    for section, keys in records.items():
        for key, record in keys.items():
            current = _values(source, section, key)
            if (current == [record["applied"]] or
                    "pending_applied" in record and current == record["pending_applied"]):
                source = _set_values(source, section, key, record["before"])
            else:
                skipped.append(f"{section}/{key}")
    return source, skipped


def _safe_parent(path: Path, root: Path):
    # Do not follow user-config symlinks to files outside the expected tree.
    parent = path.parent
    while parent != root.parent:
        if parent.is_symlink():
            raise OSError(f"Refusing symlink configuration directory / 拒绝写入符号链接目录: {parent}")
        if parent == root:
            break
        parent = parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    if lock.is_symlink():
        raise OSError("Application theme lock is a symlink / 应用主题锁不能是符号链接")
    with lock.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def _load_journal(path: Path, config_home: Path) -> dict:
    source = _read(path)
    if source is None:
        return {"version": 1, "config_home": str(config_home), "files": {}, "gsettings": {}}
    state = json.loads(source)
    if (not isinstance(state, dict) or state.get("version") != 1 or
            state.get("config_home") != str(config_home) or
            not isinstance(state.get("files"), dict) or
            not isinstance(state.get("gsettings"), dict) or
            set(state["files"]) - set(RELATIVE_FILES) or
            set(state["gsettings"]) - set(GSETTINGS_KEYS)):
        raise ValueError("Invalid application theme backup / 应用主题备份无效")
    try:
        for relative, record in state["files"].items():
            if not isinstance(record["before_text"], (str, type(None))) or not isinstance(record["applied_text"], str):
                raise ValueError
            if "pending_text" in record and not isinstance(record["pending_text"], (str, type(None))):
                raise ValueError
            if record.get("kind") not in (None, "matugen-css") or (record.get("kind") and relative not in CSS_FILES):
                raise ValueError
            for section, entries in record["keys"].items():
                if not isinstance(section, str):
                    raise ValueError
                for key, item in entries.items():
                    if not isinstance(key, str) or not isinstance(item["applied"], str):
                        raise ValueError
                    for values in (item["before"], item.get("pending_applied", [])):
                        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                            raise ValueError
        for record in state["gsettings"].values():
            if not isinstance(record["before"], (str, type(None))) or not isinstance(record["applied"], str):
                raise ValueError
            if "pending_applied" in record and not isinstance(record["pending_applied"], str):
                raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError("Invalid application theme backup / 应用主题备份无效") from error
    return state


class DesktopSettings:
    """GSettings serializations retain exact typed values and reset semantics."""
    def __init__(self):
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup(SCHEMA, True) if source else None
        if schema is None or not all(schema.has_key(key) for key in GSETTINGS_KEYS):
            raise RuntimeError("Missing gsettings-desktop-schemas / 缺少桌面设置架构")
        self.settings = Gio.Settings.new_full(schema, None, None)

    def get(self, key: str) -> str:
        return self._run(["gsettings", "get", SCHEMA, key]).strip()

    def user(self, key: str) -> str | None:
        value = self.settings.get_user_value(key)
        return value.print_(True) if value is not None else None

    def set(self, key: str, value: str | None):
        argv = ["gsettings", "reset", SCHEMA, key] if value is None else ["gsettings", "set", SCHEMA, key, value]
        self._run(argv)
        if value is not None and self.get(key) != value:
            raise RuntimeError(f"GSettings value was not persisted / 桌面设置未生效: {key}")

    @staticmethod
    def _run(argv: list[str]) -> str:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=8)
        if result.returncode or re.search(r"CRITICAL|failed to commit", result.stderr, re.I):
            raise RuntimeError(result.stderr.strip() or "GSettings command failed / 桌面设置命令失败")
        return result.stdout


def _variant(value: str) -> str:
    from gi.repository import GLib
    return GLib.Variant("s", value).print_(True)


def _notify_qt() -> list[str]:
    warnings = []
    # qt6ct watches its configuration directory and reloads after atomic writes.
    # Retain these signals for existing KDE applications during migration.
    for path, signal, arguments in (("/KGlobalSettings", "org.kde.KGlobalSettings.notifyChange", ["0", "0"]),
                                    ("/KDEPlatformTheme", "org.kde.KDEPlatformTheme.refreshFonts", [])):
        try:
            result = subprocess.run(["gdbus", "emit", "--session", "--object-path", path,
                                     "--signal", signal, *arguments], capture_output=True, text=True, timeout=5)
            if result.returncode:
                warnings.append("Restart existing Qt applications to refresh their appearance / 请重启已打开的 Qt 应用以更新外观")
                break
        except (OSError, subprocess.TimeoutExpired):
            warnings.append("Restart existing Qt applications to refresh their appearance / 请重启已打开的 Qt 应用以更新外观")
            break
    return warnings


def _qt6ct_palette(kde: dict, dark: bool) -> dict:
    """Map the installed Breeze colors to Qt 6's 22 QPalette color roles.

    qt6ct reads three QStringLists in QPalette enum order (including NoRole and
    Accent). Keeping the scheme in our journal allows exact/individual-key undo.
    """
    background = "#ff202326" if dark else "#ffeff0f1"
    foreground = "#fffcfcfc" if dark else "#ff232629"

    def color(section, key, fallback):
        value = kde.get("Colors:" + section, {}).get(key, "")
        if re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value):
            channels = [int(part) for part in value.split(",")]
            if all(channel <= 255 for channel in channels):
                return "#ff" + "".join(f"{channel:02x}" for channel in channels)
        return fallback

    def mix(first, second, weight):
        return "#ff" + "".join(f"{round(int(first[index:index+2], 16) * (1-weight) + int(second[index:index+2], 16) * weight):02x}"
                               for index in (3, 5, 7))

    window = color("Window", "BackgroundNormal", background)
    window_text = color("Window", "ForegroundNormal", foreground)
    button = color("Button", "BackgroundNormal", window)
    base = color("View", "BackgroundNormal", "#ff1b1e20" if dark else "#ffffffff")
    text = color("View", "ForegroundNormal", foreground)
    selection = color("Selection", "BackgroundNormal", "#ff3daee9")
    active = [window_text, button, mix(button, "#ffffffff", .25),
              mix(button, "#ffffffff", .12), mix(button, "#ff000000", .35),
              mix(button, "#ff000000", .18), text, "#ffffffff",
              color("Button", "ForegroundNormal", foreground), base, window, "#ff000000",
              selection, color("Selection", "ForegroundNormal", "#ffffffff"),
              color("View", "ForegroundLink", "#ff1d99f3" if dark else "#ff2980b9"),
              color("View", "ForegroundVisited", "#ff9b59b6"),
              color("View", "BackgroundAlternate", window), window_text,
              color("Tooltip", "BackgroundNormal", window),
              color("Tooltip", "ForegroundNormal", foreground),
              color("View", "ForegroundInactive", mix(text, base, .45)), selection]
    disabled = list(active)
    for role, section, surface in ((0, "Window", window), (6, "View", base),
                                   (8, "Button", button), (19, "Tooltip", active[18])):
        disabled[role] = color(section, "ForegroundInactive", mix(active[role], surface, .55))
    disabled[12] = mix(selection, window, .65)
    disabled[13] = disabled[0]
    disabled[21] = disabled[12]
    return {"ColorScheme": {"active_colors": ", ".join(active),
                            "inactive_colors": ", ".join(active),
                            "disabled_colors": ", ".join(disabled)}}


def _targets(settings: dict, data_dir: Path, config_home: Path) -> tuple[dict, dict, list[str]]:
    dark = settings["color_mode"] == "dark"
    gtk_name = "Breeze-Dark" if dark else "Breeze"
    warnings = []
    if not (data_dir / "themes" / gtk_name / "gtk-3.0/gtk.css").exists():
        gtk_name = "Adwaita-dark" if dark else "Adwaita"
        warnings.append("Breeze GTK theme unavailable; using Adwaita / Breeze GTK 主题缺失，使用 Adwaita")
    icon = "breeze-dark" if dark else "breeze"
    if not (data_dir / "icons" / icon / "index.theme").exists():
        icon = "Adwaita"
    # Interface size is logical pixels; GTK/Pango wants points. The terminal
    # size is already points and is passed through unchanged.
    font = font_scale.pango(settings["font"], settings["font_size"])
    mono = font_scale.pango_points(settings["mono_font"], settings["mono_size"])
    gtk = {"gtk-theme-name": gtk_name, "gtk-application-prefer-dark-theme": str(dark).lower(),
           "gtk-font-name": font, "gtk-icon-theme-name": icon}
    files = {"gtk-3.0/settings.ini": {"Settings": gtk},
             "gtk-4.0/settings.ini": {"Settings": {key: value for key, value in gtk.items() if key != "gtk-theme-name"}}}
    scheme = "BreezeDark" if dark else "BreezeLight"
    scheme_file = data_dir / "color-schemes" / (scheme + ".colors")
    kde = {"General": {"ColorScheme": scheme,
                       "font": font_scale.qt(settings["font"], settings["font_size"]),
                       "fixed": font_scale.qt_points(settings["mono_font"], settings["mono_size"])},
           "Icons": {"Theme": icon}, "KDE": {"widgetStyle": "Breeze"}}
    if scheme_file.exists():
        for section, key, line in _lines(scheme_file.read_text()):
            if key and section.startswith(("Colors:", "ColorEffects:")):
                kde.setdefault(section, {})[key] = line.split("=", 1)[1].strip()
    else:
        warnings.append("Breeze Qt color scheme is missing / 缺少 Breeze Qt 配色，请运行控制脚本 repair")
    files["kdeglobals"] = kde
    # QSettings treats unquoted commas as QStringList; fonts and paths must be
    # quoted strings, while palette arrays deliberately remain comma-separated.
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    files[QT6CT_PALETTE] = _qt6ct_palette(kde, dark)
    files[QT6CT_CONFIG] = {
        "Appearance": {"style": "Breeze", "custom_palette": "true",
                       "color_scheme_path": quote(str(config_home / QT6CT_PALETTE)),
                       "icon_theme": icon, "standard_dialogs": "xdgdesktopportal"},
        "Fonts": {"general": quote(kde["General"]["font"]),
                  "fixed": quote(kde["General"]["fixed"])}
    }
    desktop = {"color-scheme": _variant("prefer-dark" if dark else "prefer-light"),
               "gtk-theme": _variant(gtk_name), "font-name": _variant(font),
               "monospace-font-name": _variant(mono), "icon-theme": _variant(icon)}
    return files, desktop, warnings


def _custom_css_warnings(config_home: Path) -> list[str]:
    present = [str(config_home / version / "gtk.css") for version in ("gtk-3.0", "gtk-4.0")
               if (config_home / version / "gtk.css").is_file() and
               (config_home / version / "gtk.css").read_text() not in ("", MIGRATED_CSS)]
    return (["Custom GTK CSS may override application colors / 自定义 GTK CSS 可能覆盖应用颜色: " + ", ".join(present)]
            if present else [])


def apply_mode(settings: dict, *, config_home: Path | None = None, state_path: Path | None = None,
               data_dir: Path = Path("/usr/share"), desktop=None, notify=True) -> dict:
    """Apply settings transactionally; return component status and any limitations."""
    values = appearance.validate_settings(settings)
    home = Path(config_home or config_directory()).absolute()
    state_path = Path(state_path or journal_path()).absolute()
    desktop = desktop if desktop is not None else DesktopSettings()
    targets, desired_gs, warnings = _targets(values, data_dir, home)
    with _lock(state_path):
        old = _load_journal(state_path, home)
        updated = {"version": 1, "config_home": str(home), "mode": values["color_mode"], "files": {}, "gsettings": {}}
        writes = {}
        originals = {}
        for relative, sections in targets.items():
            path = home / relative
            _safe_parent(path, home)
            before = _read(path)
            originals[path] = before
            source = before or ""
            previous = old["files"].get(relative)
            restoration = before
            if previous:
                if (source == previous["applied_text"] or
                        "pending_text" in previous and source == previous["pending_text"]):
                    restoration = previous["before_text"]
                else:
                    restoration = _restore_owned(source, previous["keys"])[0]
            keys = {}
            for section, entries in sections.items():
                for key, value in entries.items():
                    keys.setdefault(section, {})[key] = {"before": _values(restoration or "", section, key), "applied": value}
                    source = _set_values(source, section, key, [value])
            updated["files"][relative] = {"before_text": restoration, "applied_text": source, "keys": keys}
            writes[path] = source.encode()
        migrated_css = []
        for relative in CSS_FILES:
            path = home / relative
            before = _read(path)
            previous = old["files"].get(relative)
            if before is not None and ("GTK colors generated with Matugen" in before[:512] or
                                       previous and before == previous["applied_text"]):
                _safe_parent(path, home)
                restoration = previous["before_text"] if previous and before == previous["applied_text"] else before
                updated["files"][relative] = {"before_text": restoration, "applied_text": MIGRATED_CSS,
                                               "keys": {}, "kind": "matugen-css"}
                writes[path] = MIGRATED_CSS.encode()
                originals[path] = before
                migrated_css.append(relative)
            elif before and before != MIGRATED_CSS:
                warnings.append(f"Custom GTK CSS may override application colors / 自定义 GTK CSS 可能覆盖应用颜色: {path}")
                if previous:
                    updated["files"][relative] = previous
        before_gs = {}
        effective_gs = {}
        for key, value in desired_gs.items():
            before_gs[key] = desktop.user(key)
            effective_gs[key] = desktop.get(key)
            previous = old["gsettings"].get(key)
            owned = previous and (effective_gs[key] == previous["applied"] or
                                  effective_gs[key] == previous.get("pending_applied"))
            before = previous["before"] if owned else before_gs[key]
            updated["gsettings"][key] = {"before": before, "applied": value}
        previous_state = _read(state_path)
        # During a transaction either the old or new managed value can still be
        # present. Record both until all writes finish, then discard the old one
        # so later user edits are never mistaken for an interrupted commit.
        pending = deepcopy(updated)
        for relative, record in pending["files"].items():
            if home / relative not in originals:
                continue
            record["pending_text"] = originals[home / relative]
            for section, entries in record["keys"].items():
                for key, item in entries.items():
                    item["pending_applied"] = _values(record["pending_text"] or "", section, key)
        for key, record in pending["gsettings"].items():
            record["pending_applied"] = effective_gs[key]
        appearance._commit({state_path: (json.dumps(pending, ensure_ascii=False, indent=2) + "\n").encode()}, private=state_path)
        changed_gs = []
        try:
            appearance._commit(writes)
            for key, value in desired_gs.items():
                changed_gs.append(key)
                desktop.set(key, value)
            appearance._commit({state_path: (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode()}, private=state_path)
        except BaseException:
            for key in reversed(changed_gs):
                try:
                    desktop.set(key, before_gs[key])
                except Exception:
                    # Keep the journal on rollback failure so restore can finish.
                    raise RuntimeError("Application theme rollback incomplete; run restore / 应用主题回滚未完成，请运行 restore")
            rollback = {path: text.encode() for path, text in originals.items() if text is not None}
            appearance._commit(rollback)
            for path, text in originals.items():
                if text is None:
                    path.unlink(missing_ok=True)
            if previous_state is None:
                state_path.unlink(missing_ok=True)
            else:
                appearance._commit({state_path: previous_state.encode()}, private=state_path)
            raise
    if notify:
        warnings += _notify_qt()
    return {"mode": values["color_mode"], "applied": ["GTK 3", "GTK 4 / portal", "Qt 6 / qt6ct", "KDE applications"],
            "migrated_css": migrated_css, "warnings": warnings,
            "restart_hint": "Applications with their own theme override may need adjustment or restart / 应用内独立主题可能需要调整或重启"}


def restore(*, config_home: Path | None = None, state_path: Path | None = None, desktop=None, notify=True) -> dict:
    """Restore managed values while retaining edits made after the last apply."""
    home = Path(config_home or config_directory()).absolute()
    state_path = Path(state_path or journal_path()).absolute()
    if not state_path.exists():
        return {"restored": [], "preserved": [], "warnings": []}
    desktop = desktop if desktop is not None else DesktopSettings()
    with _lock(state_path):
        state = _load_journal(state_path, home)
        restored, preserved = [], []
        for relative, record in state["files"].items():
            path = home / relative
            _safe_parent(path, home)
            current = _read(path)
            if current is None:
                preserved.append(relative)
                continue
            if (current == record["applied_text"] or
                    "pending_text" in record and current == record["pending_text"]):
                result = record["before_text"]
            elif record.get("kind") == "matugen-css":
                preserved.append(relative)
                continue
            else:
                result, skipped = _restore_owned(current, record["keys"])
                preserved.extend(f"{relative}: {key}" for key in skipped)
            if result is None:
                path.unlink()
            elif result != current:
                appearance._commit({path: result.encode()})
            restored.append(relative)
        for key, record in state["gsettings"].items():
            current = desktop.get(key)
            if current == record["applied"] or current == record.get("pending_applied"):
                desktop.set(key, record["before"])
                restored.append("GSettings: " + key)
            else:
                preserved.append("GSettings: " + key)
        state_path.unlink()
    return {"restored": restored, "preserved": preserved, "warnings": _notify_qt() if notify else []}


def read_state(*, config_home: Path | None = None, state_path: Path | None = None, desktop=None) -> dict:
    home = Path(config_home or config_directory()).absolute()
    state = Path(state_path or journal_path()).absolute()
    warnings = _custom_css_warnings(home)
    try:
        desktop = desktop if desktop is not None else DesktopSettings()
        settings = {key: desktop.get(key) for key in GSETTINGS_KEYS}
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        settings = {}
        warnings.append(str(error))
    return {"managed": state.exists(), "settings": settings, "warnings": warnings}


def main() -> int:
    if sys.argv[1:] not in (["apply-saved"], ["restore"], ["status"]):
        print("Usage: application_theme.py {apply-saved|restore|status}", file=sys.stderr)
        return 2
    try:
        action = sys.argv[1]
        if action == "apply-saved":
            result = apply_mode(appearance.load_settings())
        elif action == "restore":
            result = restore()
        else:
            result = read_state()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Application theme failed / 应用主题操作失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
