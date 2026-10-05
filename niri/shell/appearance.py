#!/usr/bin/env python3
"""Desktop appearance preferences and generated component overrides.

This generator only writes the checkout's theme/ assets; application_theme.py
separately synchronizes GTK, Qt and the desktop portal with recorded backups.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata

import font_scale
from i18n import tr

BASE = Path(__file__).resolve().parent.parent
PRESETS = {
    "glacier": {"label": "Glacier · 冰川", "background": "#101522", "surface": "#1c2638",
                "ink": "#eef5ff", "muted": "#9daec6", "accent": "#94dfff", "secondary": "#c4b5fd",
                "border": "#d6eaff", "success": "#a6eed7", "warning": "#f4d9a1", "error": "#ffb4c4"},
    "violet": {"label": "Twilight · 暮紫", "background": "#1c142a", "surface": "#30233f",
               "ink": "#f7efff", "muted": "#b8a3cc", "accent": "#c5a2ff", "secondary": "#f2b1d7",
               "border": "#e7d4ff", "success": "#b3e8d2", "warning": "#f5d7ae", "error": "#ffacbf"},
    "graphite": {"label": "Graphite · 石墨", "background": "#1a1b1c", "surface": "#2d2f31",
                 "ink": "#f4f2ec", "muted": "#b2afa6", "accent": "#edca8a", "secondary": "#a7d6cd",
                 "border": "#e7e2d6", "success": "#acd8b5", "warning": "#edca8a", "error": "#f4ada8"},
}
LIGHT_PRESETS = {
    "glacier": {"background": "#edf3fa", "surface": "#ffffff", "ink": "#172437", "muted": "#52667d",
                "accent": "#086f9f", "secondary": "#7056ad", "border": "#304c6e",
                "success": "#177451", "warning": "#8c5b08", "error": "#b82749"},
    "violet": {"background": "#f3eff9", "surface": "#ffffff", "ink": "#2c203a", "muted": "#705d81",
               "accent": "#7952b7", "secondary": "#a53875", "border": "#60446e",
               "success": "#237657", "warning": "#8e5b12", "error": "#b82749"},
    "graphite": {"background": "#f3f2ee", "surface": "#ffffff", "ink": "#272824", "muted": "#63665f",
                 "accent": "#84621b", "secondary": "#23756a", "border": "#51564a",
                 "success": "#23723a", "warning": "#8c5b08", "error": "#b52d2d"},
}
DEFAULTS = {"preset": "glacier", "color_mode": "dark", "reduced_motion": False, "font": "Inter", "font_size": 12,
            "mono_font": "JetBrainsMono Nerd Font", "mono_size": 11.5, "opacity": 0.86}
GENERATED_FILES = ("panel.css", "waybar.css", "swaync.css", "theme.kdl", "kitty.conf", "fuzzel.ini", "swaylock.conf")


def preferences_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/appearance.json"


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: expected {low}–{high} / 数值须为 {low}–{high}")
    return round(float(value), 2)


def _font(value, name):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
        raise ValueError(f"{name}: invalid font family / 字体名称无效")
    value = value.strip()
    # Keep CSS, Fontconfig, Kitty and INI values safe with one shared grammar.
    if any(not (unicodedata.category(char)[0] in "LMN" or char in " ._+-") for char in value):
        raise ValueError(f"{name}: use a font family name without quotes or control characters / 字体名称不能包含引号或控制字符")
    return value


def validate_settings(settings: dict) -> dict:
    if not isinstance(settings, dict) or set(settings) - set(DEFAULTS):
        raise ValueError("Unknown appearance settings / 外观选项无效")
    values = {**DEFAULTS, **settings}
    if not isinstance(values["preset"], str) or values["preset"] not in PRESETS:
        raise ValueError("Unknown theme preset / 主题不存在")
    if values["color_mode"] not in ("dark", "light"):
        raise ValueError("Color mode must be dark or light / 请选择深色或浅色模式")
    if not isinstance(values["reduced_motion"], bool):
        raise ValueError("Reduced motion must be true or false / 减少动态效果选项须为布尔值")
    for name in ("font", "mono_font"):
        values[name] = _font(values[name], name)
    values["font_size"] = _number(values["font_size"], "font_size", 9, 20)
    values["mono_size"] = _number(values["mono_size"], "mono_size", 8, 24)
    values["opacity"] = _number(values["opacity"], "opacity", 0.65, 1)
    return values


def load_settings(*, state_path: Path | None = None) -> dict:
    """Return safe defaults for absent, obsolete, or invalid saved preferences."""
    try:
        return validate_settings(json.loads(Path(state_path or preferences_path()).read_text()))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def _rgba(color, opacity):
    return "rgba({}, {}, {}, {:.3f})".format(*(int(color[index:index + 2], 16) for index in (1, 3, 5)), opacity)


def palette(settings: dict) -> dict:
    values = validate_settings(settings)
    return {**PRESETS[values["preset"]],
            **(LIGHT_PRESETS[values["preset"]] if values["color_mode"] == "light" else {})}


def _alpha(color, opacity):
    return color.removeprefix("#") + f"{round(opacity * 255):02x}"


def _scope_panel_css(css: str) -> str:
    """Our generated flat rules apply only inside the glass panel window.

    A global `button`/`entry` rule also styles GTK's separate font chooser,
    putting near-white panel text on that dialog's normal light background.
    Each generated selector starts on its own line; there are no nested rules.
    """
    lines = []
    for line in css.splitlines():
        if "{" in line and not line.startswith(("/*", "@")):
            selectors, contents = line.split("{", 1)
            line = ", ".join("window.glass-window " + item.strip()
                             for item in selectors.split(",")) + " {" + contents
        lines.append(line)
    return "\n".join(lines) + "\n"


def _dialog_css(palette: dict) -> str:
    """Separate native dialogs need opaque, fully contrasted surfaces."""
    bg, surface, ink, accent, border = (palette[key] for key in
                                      ("background", "surface", "ink", "accent", "border"))
    return f"""/* Native font chooser: solid surfaces, distinct actions and selection. */
dialog {{ background: {bg}; color: {ink}; }}
dialog headerbar {{ background: {surface}; color: {ink}; border-bottom: 1px solid {_rgba(border, .28)}; box-shadow: none; }}
dialog label {{ color: inherit; text-shadow: none; }}
dialog button {{ background: {surface}; color: {ink}; border: 1px solid {_rgba(border, .4)}; border-radius: 8px; box-shadow: none; text-shadow: none; padding: 7px 12px; }}
dialog button:hover {{ background: {_rgba(accent, .25)}; color: {ink}; border-color: {accent}; }}
dialog button:disabled {{ opacity: .45; }}
dialog button.suggested-action {{ background: {accent}; color: {bg}; border-color: {accent}; }}
dialog button:focus, dialog entry:focus {{ border-color: {accent}; }}
dialog entry, dialog spinbutton {{ background: {surface}; color: {ink}; caret-color: {accent}; border: 1px solid {_rgba(border, .4)}; box-shadow: none; }}
dialog entry selection {{ background: {accent}; color: {bg}; }}
dialog .view, dialog treeview, dialog viewport {{ background: {bg}; color: {ink}; }}
dialog .view:selected, dialog treeview:selected {{ background: {accent}; color: {bg}; }}
dialog textview, dialog textview text {{ background: {surface}; color: {ink}; }}
dialog separator {{ background: {_rgba(border, .28)}; }}
"""


def _replace_ini(source: str, section: str, values: dict) -> str:
    """Update only our keys and preserve unrelated lines from the base template."""
    lines = source.splitlines()
    active = ""
    left = dict(values)
    output = []
    section_seen = section == ""
    for line in lines:
        match = re.fullmatch(r"\s*\[([^]]+)\]\s*", line)
        if match:
            if active == section:
                output.extend(f"{key}={value}" for key, value in left.items())
                left.clear()
            active = match[1]
            section_seen |= active == section
        if active == section and "=" in line and not line.lstrip().startswith(("#", ";")):
            key = line.split("=", 1)[0].strip()
            if key in values:
                # Replace all duplicate occurrences as well, lest a later old key wins.
                line = f"{key}={values[key]}"
                left.pop(key, None)
        output.append(line)
    if left:
        if section and not section_seen:
            output.extend(("", f"[{section}]"))
        output.extend(f"{key}={value}" for key, value in left.items())
    return "\n".join(output) + "\n"


def render_files(settings: dict, *, base: Path | None = None) -> dict[str, str]:
    """Pure generation except for reading the existing launcher/lock templates."""
    values = validate_settings(settings)
    base = Path(base or BASE)
    p = palette(values)
    bg, surface, ink, muted = (p[key] for key in ("background", "surface", "ink", "muted"))
    accent, secondary, border = (p[key] for key in ("accent", "secondary", "border"))
    opacity, size = values["opacity"], values["font_size"]
    font, mono = values["font"], values["mono_font"]
    family = f'"{font}", "Noto Sans", "Noto Sans CJK SC", "JetBrainsMono Nerd Font", sans-serif'
    rgba = _rgba
    css_header = "/* Generated by Selandia appearance settings; edit templates or use Control Center. */\n"
    panel = css_header + f"""@define-color ink {ink};
@define-color muted {muted};
@define-color cyan {accent};
@define-color violet {secondary};
@define-color on_accent {bg};
@define-color danger {p['error']};
* {{ font-family: {family}; font-size: {size:g}px; }}
.glass-surface {{ color: {ink}; background-color: {rgba(bg, opacity)};
    background-image: linear-gradient(140deg, {rgba(accent, .12)}, {rgba(secondary, .025)} 42%, {rgba(accent, .055)});
    border-color: {rgba(border, .23)}; box-shadow: inset 0 1px {rgba(border, .22)}, inset 0 -1px {rgba(accent, .06)}; }}
.panel-header {{ border-bottom-color: {rgba(border, .09)}; }}
.card, .message, .metric-card {{ border-color: {rgba(border, .10)}; background-color: {rgba(border, .045)}; }}
.control-tabs {{ border-color: {rgba(border, .09)}; background-color: {rgba(bg, .3)}; }}
.control-tabs button {{ color: {muted}; background: transparent; border-color: transparent; }}
.control-tabs button:checked {{ color: {ink}; background-color: {rgba(accent, .14)}; border-color: {rgba(accent, .21)}; }}
.metric-value, .network-rate {{ color: {accent}; }}
spinbutton {{ color: {ink}; border-color: {rgba(border, .16)}; background-color: {rgba(bg, .3)}; }}
button {{ color: {ink}; background-color: {rgba(border, .065)}; border-color: {rgba(border, .12)}; }}
button:hover, menuitem:hover {{ background-color: {rgba(accent, .15)}; border-color: {rgba(accent, .4)}; }}
button:active {{ background-color: {rgba(accent, .25)}; }}
button:focus, entry:focus {{ border-color: {rgba(accent, .7)}; }}
button.tile.active {{ background-color: {rgba(accent, .15)};
    background-image: linear-gradient(140deg, {rgba(accent, .075)}, {rgba(secondary, .04)}); border-color: {rgba(accent, .34)}; }}
.active .tile-state {{ color: {ink}; }}
button.accent-button {{ color: {bg}; background-color: {accent}; background-image: linear-gradient(120deg, {accent}, {secondary}); border-color: {rgba(border, .45)}; }}
button.accent-button:hover {{ background-image: linear-gradient(120deg, {secondary}, {accent}); }}
button.power-button, .status.error {{ color: {p['error']}; }}
scale trough {{ background-color: {rgba(border, .1)}; }}
scale highlight {{ background-image: linear-gradient(to right, {secondary}, {accent}); }}
scale slider {{ background-color: {ink}; border-color: {rgba(border, .75)}; }}
progressbar trough, .metric-progress trough {{ background-color: {rgba(border, .09)}; border: none; border-radius: 7px; min-height: 5px; }}
progressbar progress, .metric-progress progress {{ background-image: linear-gradient(to right, {secondary}, {accent}); border: none; border-radius: 7px; min-height: 5px; }}
scrollbar slider {{ background-color: {rgba(border, .2)}; }}
scrollbar slider:hover {{ background-color: {rgba(border, .4)}; }}
menu, tooltip {{ color: {ink}; background-color: {surface}; border-color: {rgba(border, .22)}; }}
entry {{ color: {ink}; caret-color: {accent}; border-color: {rgba(border, .16)}; background-color: {rgba(bg, .35)}; }}
entry selection, textview text selection {{ background-color: {rgba(accent, .35)}; color: {ink}; }}
.keycap {{ font-family: "{mono}", monospace; color: {accent}; background-color: {rgba(accent, .07)}; border-color: {rgba(accent, .12)}; }}
.shortcut-description, .welcome-copy, .message-text {{ color: {ink}; }}
.user-message {{ background-color: {rgba(accent, .105)}; }}
.assistant-message {{ background-color: {rgba(secondary, .07)}; }}
.composer {{ border-color: {rgba(border, .16)}; background-color: {rgba(bg, .3)}; }}
textview, textview text {{ color: {ink}; caret-color: {accent}; }}
"""
    # Scale labels whose base design intentionally uses a different size.
    for selectors, pixels in ((".eyebrow, .section-title, .message-role", 9),
                              (".tile-state, .value, .hint, .provider-status, button.small-button, button.tool-button, .control-tabs button", 10),
                              (".subtitle, .tile-title, .control-label, .status", 11),
                              (".keycap", 11), (".shortcut-description, .welcome-copy, .message-text, textview", 12),
                              (".media-title", 13), (".panel-title, .metric-value", 27), (".network-rate", 18),
                              (".clock", 32), (".welcome-title", 21)):
        panel += f"{selectors} {{ font-size: {pixels * size / 12:g}px; }}\n"
    panel = _scope_panel_css(panel) + _dialog_css(p)
    waybar = '@import "../waybar/style.css";\n' + css_header + f"""* {{ font-family: {family}; font-size: {size:g}px; }}
window#waybar {{ color: {ink}; background: linear-gradient(115deg, {rgba(surface, opacity)}, {rgba(bg, opacity)} 55%, {rgba(secondary, opacity * .21)}); border-color: {rgba(border, .2)}; }}
tooltip {{ color: {ink}; background: {rgba(bg, .97)}; border-color: {rgba(border, .2)}; }}
#custom-launcher, #network, #custom-netrate {{ color: {accent}; }}
#window, #workspaces button {{ color: {muted}; }}
#workspaces button.active {{ background: {rgba(accent, .12)}; color: {ink}; }}
#workspaces button.focused {{ background: linear-gradient(130deg, {accent}, {secondary}); color: {bg}; }}
#workspaces button.urgent {{ background: {p['error']}; color: {bg}; }}
#workspaces button:hover {{ background: {rgba(border, .16)}; color: {ink}; }}
#custom-ai {{ color: {secondary}; background: linear-gradient(120deg, {rgba(secondary, .16)}, {rgba(accent, .09)}); border-color: {rgba(secondary, .2)}; }}
#pulseaudio, #battery, #cpu, #memory, #disk, #temperature, #custom-system {{ color: {ink}; }}
#network.disconnected, #pulseaudio.muted {{ color: {muted}; }}
#battery.charging, #battery.plugged {{ color: {p['success']}; }}
#battery.warning, #custom-system.warning {{ color: {p['warning']}; }}
#battery.critical, #custom-system.critical {{ color: {p['error']}; }}
#custom-control {{ color: {bg}; background: linear-gradient(130deg, {ink}, {accent}); }}
#custom-launcher:hover, #custom-shortcuts:hover, #custom-notification:hover, #pulseaudio:hover, #network:hover {{ background: {rgba(border, .1)}; }}
#custom-ai:hover {{ background: {rgba(secondary, .25)}; }}
#custom-control:hover {{ background: {ink}; }}
"""
    import bar_layout
    waybar += bar_layout.css(bar_layout.select(size=size), size)
    swaync = '@import "../swaync/style.css";\n' + css_header + f"""@define-color cc-bg {rgba(bg, opacity)};
@define-color noti-bg {rgba(surface, opacity)};
@define-color noti-border-color {rgba(border, .18)};
@define-color text-color {ink};
@define-color text-color-disabled {muted};
* {{ font-family: {family}; font-size: {size + 1:g}px; }}
.control-center {{ background: linear-gradient(145deg, {rgba(surface, opacity)}, {rgba(bg, opacity)} 58%, {rgba(surface, opacity)}); color: {ink}; border-color: {rgba(border, .18)}; }}
.summary, .widget-title {{ color: {ink}; }}
.body, .widget-dnd {{ color: {ink}; }}
.time, .app-name {{ color: {muted}; }}
.notification-row .notification-background .notification.critical {{ border-color: {rgba(p['error'], .6)}; }}
.notification-group:focus .notification, .notification-row:focus .notification, .notification-row:focus-within .notification {{ border-color: {rgba(accent, .4)}; }}
.widget-dnd {{ background: {rgba(border, .05)}; }}
button {{ color: {ink}; background: {rgba(border, .07)}; border-color: {rgba(border, .12)}; }}
button:hover {{ color: {ink}; background: {rgba(accent, .16)}; }}
.notification-default-action {{ background: transparent; }}
.close-button {{ background: {rgba(border, .1)}; }}
switch {{ background: {rgba(border, .12)}; }}
switch:checked {{ background: linear-gradient(120deg, {accent}, {secondary}); }}
switch slider {{ background: {ink}; }}
scrollbar slider {{ background: {rgba(border, .18)}; }}
"""
    kdl = f'''// Generated palette overrides. Keep layout preferences in conf/appearance.kdl.
layout {{
    background-color "{bg}"
    focus-ring {{
        active-gradient from="{accent}" to="{secondary}" angle=125
        inactive-color "{border}26"
        urgent-color "{p['error']}"
    }}
    tab-indicator {{
        active-gradient from="{accent}" to="{secondary}" angle=125
        inactive-color "{ink}22"
    }}
}}
overview {{ backdrop-color "{bg}"; }}
'''
    kitty = f'''# Generated scoped theme. Included at the end of ../kitty/kitty.conf.
font_family {mono}
font_size {values['mono_size']:g}
background {bg}
foreground {ink}
background_opacity {opacity:g}
selection_background {accent}
selection_foreground {bg}
cursor {accent}
cursor_text_color {bg}
url_color {secondary}
active_border_color {accent}
inactive_border_color {muted}
bell_border_color {p['warning']}
active_tab_background {accent}
active_tab_foreground {bg}
inactive_tab_background {surface}
inactive_tab_foreground {muted}
color0 {surface}
color1 {p['error']}
color2 {p['success']}
color3 {p['warning']}
color4 {accent}
color5 {secondary}
color6 {p['success']}
color7 {ink}
color8 {muted}
color9 {p['error']}
color10 {p['success']}
color11 {p['warning']}
color12 {accent}
color13 {secondary}
color14 {p['success']}
color15 {ink}
'''
    fuzzel = (base / "fuzzel/fuzzel.ini").read_text()
    # A generated launcher configuration is single-language too: never write the
    # bilingual template back. The launch script overrides this at run time so a
    # language switch applies without re-applying the theme.
    launcher_px = font_scale.launcher_pixels(size)
    fuzzel = _replace_ini(fuzzel, "main", {"font": f"{font_scale.fuzzel_pattern(font, launcher_px)},"
                                                   f"{font_scale.fuzzel_pattern('Noto Sans CJK SC', launcher_px)}",
                                         "line-height": max(36, round(launcher_px * 2.4)),
                                         "placeholder": tr("Search applications", "搜索应用")})
    fuzzel = _replace_ini(fuzzel, "colors", {"background": _alpha(bg, opacity), "text": _alpha(ink, 1),
        "prompt": _alpha(accent, 1), "placeholder": _alpha(muted, 1), "input": _alpha(ink, 1),
        "match": _alpha(accent, 1), "selection": _alpha(surface, .95), "selection-text": _alpha(ink, 1),
        "selection-match": _alpha(secondary, 1), "counter": _alpha(muted, 1), "border": _alpha(border, .33)})
    lock = _replace_ini((base / "swaylock/config").read_text(), "", {"color": bg[1:], "font": font,
        "font-size": font_scale.whole_points(font_scale.lock_pixels(size)), "inside-color": _alpha(bg, max(.9, opacity)), "ring-color": _alpha(border, .25),
        "text-color": ink[1:], "key-hl-color": accent[1:], "bs-hl-color": secondary[1:],
        "inside-ver-color": _alpha(surface, .94), "ring-ver-color": accent[1:], "text-ver-color": ink[1:],
        "inside-wrong-color": _alpha(surface, .94), "ring-wrong-color": p["error"][1:], "text-wrong-color": ink[1:]})
    return {"panel.css": panel, "waybar.css": waybar, "swaync.css": swaync, "theme.kdl": kdl,
            "kitty.conf": kitty, "fuzzel.ini": fuzzel, "swaylock.conf": lock}


@contextmanager
def _lock(state_path: Path):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with (state_path.parent / "appearance.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def _staged(path: Path, data: bytes, mode: int) -> Path:
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staging = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return staging
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def _commit(files: dict[Path, bytes], *, private: Path | None = None):
    """Stage before mutation, replace individual files atomically, roll back errors."""
    original = {}
    staged = {}
    committed = []
    try:
        for path, data in files.items():
            if path.is_symlink() or path.exists() and not path.is_file():
                raise OSError(f"Refusing to overwrite non-regular theme file / 拒绝覆盖非普通文件: {path}")
            old = path.read_bytes() if path.exists() else None
            mode = stat.S_IMODE(path.stat().st_mode) if old is not None else 0o644
            original[path] = (old, mode)
            staged[path] = _staged(path, data, 0o600 if path == private else mode)
        for path, staging in staged.items():
            os.replace(staging, path)
            committed.append(path)
    except BaseException:
        for path in reversed(committed):
            old, mode = original[path]
            if old is None:
                path.unlink(missing_ok=True)
            else:
                rollback = _staged(path, old, mode)
                try:
                    os.replace(rollback, path)
                finally:
                    rollback.unlink(missing_ok=True)
        raise
    finally:
        for staging in staged.values():
            staging.unlink(missing_ok=True)


def apply_settings(settings: dict, *, base: Path | None = None, state_path: Path | None = None) -> dict:
    """Persist a validated complete preference set; UI handles component reloads."""
    values = validate_settings(settings)
    base = Path(base or BASE).resolve()
    state_path = Path(state_path or preferences_path()).absolute()
    generated = render_files(values, base=base)
    directory = base / "theme"
    if directory.is_symlink():
        raise OSError("Theme directory must not be a symlink / 主题目录不能是符号链接")
    directory.mkdir(parents=True, exist_ok=True)
    with _lock(state_path):
        files = {directory / name: text.encode() for name, text in generated.items()}
        files[state_path] = (json.dumps(values, ensure_ascii=False, indent=2) + "\n").encode()
        _commit(files, private=state_path)
    return values


def restore_defaults(*, base: Path | None = None, state_path: Path | None = None) -> dict:
    return apply_settings(DEFAULTS, base=base, state_path=state_path)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["restore-saved"]:
        print("Usage: appearance.py restore-saved", file=sys.stderr)
        raise SystemExit(2)
    saved = preferences_path()
    try:
        if saved.exists():
            # Unlike initial UI loading, upgrade must not silently replace a
            # malformed saved preference file with defaults.
            apply_settings(json.loads(saved.read_text()))
            print("Saved appearance restored · 已恢复保存的外观设置")
    except (OSError, ValueError, TypeError) as error:
        print(f"Appearance restore failed · 外观恢复失败: {error}", file=sys.stderr)
        raise SystemExit(1)
