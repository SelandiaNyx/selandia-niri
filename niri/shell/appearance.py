#!/usr/bin/env python3
"""Desktop appearance preferences and generated component overrides.

This generator only writes the checkout's theme/ assets; application_theme.py
separately synchronizes GTK, Qt and the desktop portal with recorded backups.
"""
from __future__ import annotations

import inspect
import functools
from contextlib import contextmanager
import colorsys
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
    "glacier": {"label": "Glacier Glass · 琉璃冰川", "background": "#090d16", "surface": "#111827",
                "surface_raised": "#192338", "surface_sunken": "#060910",
                "ink": "#f1f6ff", "muted": "#9ab0cc", "faint": "#3b4c66",
                "accent": "#5ee7ff", "secondary": "#a78bfa", "accent_hover": "#80efff", "on_accent": "#04131c",
                "border": "#6482a8", "border_subtle": "rgba(241, 246, 255, 0.08)",
                "success": "#34d399", "warning": "#fbbf24", "error": "#fb7185", "danger": "#fb7185"},
    "violet": {"label": "Nebula · 星云暮紫", "background": "#130d24", "surface": "#201738",
               "surface_raised": "#2d214d", "surface_sunken": "#0c0818",
               "ink": "#f7f0ff", "muted": "#baa6d4", "faint": "#5a4678",
               "accent": "#c084fc", "secondary": "#f472b6", "accent_hover": "#d8b4fe", "on_accent": "#160a26",
               "border": "#a78bcc", "border_subtle": "rgba(247, 240, 255, 0.08)",
               "success": "#5eead4", "warning": "#fcd34d", "error": "#fda4af", "danger": "#fda4af"},
    "graphite": {"label": "Champagne · 流金石墨", "background": "#131418", "surface": "#1f2128",
                 "surface_raised": "#2b2e37", "surface_sunken": "#0c0d10",
                 "ink": "#f5f3ed", "muted": "#b4b1a8", "faint": "#57595f",
                 "accent": "#f5cb7a", "secondary": "#5eead4", "accent_hover": "#fadba0", "on_accent": "#1a1406",
                 "border": "#9e988c", "border_subtle": "rgba(245, 243, 237, 0.08)",
                 "success": "#6ee7b7", "warning": "#fbbf24", "error": "#fca5a5", "danger": "#fca5a5"},
}
LIGHT_PRESETS = {
    "glacier": {"background": "#eef4fc", "surface": "#ffffff",
                "surface_raised": "#e3edf9", "surface_sunken": "#dde7f5",
                "ink": "#0f172a", "muted": "#4b5d73", "faint": "#c2d0e3",
                "accent": "#0284c7", "secondary": "#6366f1", "accent_hover": "#0369a1", "on_accent": "#ffffff",
                "border": "#9cb4d1", "border_subtle": "rgba(15, 23, 42, 0.07)",
                "success": "#0d8456", "warning": "#b45309", "error": "#e11d48", "danger": "#e11d48"},
    "violet": {"background": "#f4effd", "surface": "#ffffff",
               "surface_raised": "#eae1fb", "surface_sunken": "#e4d8f8",
               "ink": "#251838", "muted": "#675382", "faint": "#cabbe0",
               "accent": "#7c3aed", "secondary": "#db2777", "accent_hover": "#6d28d9", "on_accent": "#ffffff",
               "border": "#a48bc9", "border_subtle": "rgba(37, 24, 56, 0.07)",
               "success": "#0f766e", "warning": "#a16207", "error": "#be123c", "danger": "#be123c"},
    "graphite": {"background": "#f3f2ee", "surface": "#ffffff",
                 "surface_raised": "#e9e7e0", "surface_sunken": "#e2dfd7",
                 "ink": "#222420", "muted": "#5d6058", "faint": "#c5c5bc",
                 "accent": "#9a6715", "secondary": "#0f766e", "accent_hover": "#7c5210", "on_accent": "#ffffff",
                 "border": "#9e9c92", "border_subtle": "rgba(34, 36, 32, 0.07)",
                 "success": "#15803d", "warning": "#a16207", "error": "#b91c1c", "danger": "#b91c1c"},
}
# Each collection has a curated dual-tone light and dark Liquid Glass palette.
for name, label, dark_bg, dark_surface, dark_raised, dark_sunken, dark_border, light_bg, light_raised, accent, secondary, light_accent, light_secondary in (
    ("aurora", "Aurora · 极光翡翠", "#09191f", "#122931", "#1b3842", "#051014", "#558c99", "#ebf8f6", "#dcf2ee", "#5eead4", "#60a5fa", "#0d7a69", "#2563eb"),
    ("ocean", "Ocean · 蔚蓝深海", "#091529", "#122440", "#1b3459", "#050d1a", "#587eb0", "#ecf5ff", "#ddebfc", "#38bdf8", "#2dd4bf", "#0369a1", "#0e7490"),
    ("rose", "Rose Quartz · 晨曦蔷薇", "#1f111c", "#321c2e", "#44273e", "#140a12", "#a8709b", "#fdf1f5", "#f8e2eb", "#fda4af", "#d8b4fe", "#be185d", "#7e22ce"),
    ("amber", "Amber · 落日琥珀", "#1c140d", "#2d2015", "#3e2d1f", "#120c07", "#a68560", "#fcf6ea", "#f6ead4", "#fcd34d", "#fb923c", "#b45309", "#c2410c"),
    ("forest", "Forest · 幽林清露", "#0e1a13", "#182b20", "#233b2d", "#08110c", "#628f74", "#eef7ef", "#dfefe1", "#6ee7b7", "#bef264", "#15803d", "#65a30d"),
    ("pearl", "Pearl · 虹彩珍珠", "#141824", "#21273a", "#2e364d", "#0d1018", "#7c89ad", "#f3f5fc", "#e6eaf8", "#93c5fd", "#f0abfc", "#3b5bdb", "#9c36b5"),
):
    PRESETS[name] = {**PRESETS["glacier"], "label": label, "background": dark_bg,
                     "surface": dark_surface, "surface_raised": dark_raised, "surface_sunken": dark_sunken,
                     "border": dark_border, "accent": accent, "secondary": secondary, "accent_hover": secondary}
    LIGHT_PRESETS[name] = {**LIGHT_PRESETS["glacier"], "background": light_bg,
                           "surface_raised": light_raised, "surface_sunken": light_raised,
                           "accent": light_accent, "secondary": light_secondary, "accent_hover": light_secondary}
DEFAULTS = {"preset": "glacier", "color_mode": "dark", "reduced_motion": False, "font": "Adwaita Sans", "font_size": 12,
            "mono_font": "JetBrainsMono Nerd Font", "mono_size": 11.5, "opacity": 0.78,
            "wallpaper_colors": False, "wallpaper_seed": None}
GENERATED_FILES = ("panel.css", "swaync.css", "theme.kdl", "fuzzel.ini", "swaylock.conf", "eww.css", "anyrun.css", "alacritty.toml")


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
    # Keep CSS, Fontconfig, TOML and INI values safe with one shared grammar.
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
    if not isinstance(values["wallpaper_colors"], bool):
        raise ValueError(tr("Invalid wallpaper color option", "壁纸配色选项无效"))
    seed = values["wallpaper_seed"]
    if seed is not None and (not isinstance(seed, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", seed)):
        raise ValueError(tr("Invalid wallpaper color", "壁纸颜色无效"))
    for name in ("font", "mono_font"):
        values[name] = _font(values[name], name)
    values["font_size"] = _number(values["font_size"], "font_size", 9, 20)
    values["mono_size"] = _number(values["mono_size"], "mono_size", 8, 24)
    values["opacity"] = _number(values["opacity"], "opacity", 0.20, 1)
    return values


_SETTINGS_CACHE: dict[str, tuple[tuple[int, int, int, int] | None, dict]] = {}


def load_settings(*, state_path: Path | None = None) -> dict:
    """Return safe defaults for absent, obsolete, or invalid saved preferences."""
    target = Path(state_path or preferences_path())
    cache_key = str(target)
    try:
        info = target.stat()
        sig = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size)
    except OSError:
        sig = None
    cached = _SETTINGS_CACHE.get(cache_key)
    if cached is not None and cached[0] == sig:
        return dict(cached[1])
    if sig is None:
        result = dict(DEFAULTS)
    else:
        try:
            result = validate_settings(json.loads(target.read_text()))
        except (OSError, ValueError, TypeError):
            result = dict(DEFAULTS)
    if len(_SETTINGS_CACHE) > 32:
        _SETTINGS_CACHE.clear()
    _SETTINGS_CACHE[cache_key] = (sig, result)
    return dict(result)


def _rgba(color, opacity):
    return "rgba({}, {}, {}, {:.3f})".format(*(int(color[index:index + 2], 16) for index in (1, 3, 5)), opacity)


def palette(settings: dict) -> dict:
    values = validate_settings(settings)
    result = {**PRESETS[values["preset"]],
              **(LIGHT_PRESETS[values["preset"]] if values["color_mode"] == "light" else {})}
    if values["wallpaper_colors"] and values["wallpaper_seed"]:
        seed = values["wallpaper_seed"]
        hue, _, saturation = colorsys.rgb_to_hls(*(int(seed[i:i + 2], 16) / 255 for i in (1, 3, 5)))
        saturation = min(.65, max(.12, saturation))
        def tint(lightness, strength=1, offset=0):
            return "#" + "".join(f"{round(c * 255):02x}" for c in
                                colorsys.hls_to_rgb((hue + offset) % 1, lightness, saturation * strength))
        dark = values["color_mode"] == "dark"
        result.update(background=tint(.075 if dark else .96, .45),
                      surface=tint(.13 if dark else .995, .35),
                      surface_raised=tint(.17 if dark else .93, .35),
                      surface_sunken=tint(.09 if dark else .95, .35),
                      ink=tint(.96 if dark else .10, .3),
                      muted=tint(.72 if dark else .32, .3),
                      faint=tint(.35 if dark else .75, .3),
                      accent=tint(.78 if dark else .26),
                      secondary=tint(.80 if dark else .27, .85, 0),
                      accent_hover=tint(.82 if dark else .24),
                      border=tint(.88 if dark else .25, .4))
    return result


def _alpha(color, opacity):
    return color.removeprefix("#") + f"{round(opacity * 255):02x}"


# Material Design 3 semantic role generation.  The numeric recipes below are the
# GTK3 translation of design/TOKENS.md: a single primary from the active preset,
# five tonal surface levels, 14 %/6 % outline alphas, and the 12/14/18/20/26 px
# shape scale.  Presets (including wallpaper tinting), light/dark mode and font
# size still flow through palette()/validate_settings(); nothing here reads the
# live desktop or hardcodes one collection.
MD3_SHAPE = {"window": 26, "card": 20, "tile": 18, "pill": 14,
             "button": 12, "badge": 999}
MD3_TYPE = {"display": 2.25, "headline": 1.50, "title_large": 1.25,
            "title_medium": 1.0, "body": 0.875, "caption": 0.75,
            "overline": 0.6875}


def _mix(first, second, weight):
    """Blend two #rrggbb colours; weight is the share of ``second``."""
    a = [int(first[index:index + 2], 16) for index in (1, 3, 5)]
    b = [int(second[index:index + 2], 16) for index in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * weight):02x}" for x, y in zip(a, b))


def _channels(color):
    return [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]


def _channel_luminance(channels):
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def _luminance(color):
    """WCAG relative luminance for an opaque #rrggbb colour."""
    return _channel_luminance(_channels(color))


def _contrast_luminance(first, second):
    high, low = sorted((first, second), reverse=True)
    return (high + .05) / (low + .05)


def _contrast(first, second):
    return _contrast_luminance(_luminance(first), _luminance(second))


def _contrast_mix(color, toward, reference, minimum=4.5):
    """Smallest bounded blend toward ``toward`` that clears ``minimum``.

    Returns ``color`` byte-identically when it already passes.  Twenty-four
    binary-search steps are deterministic and independent of preset names.
    """
    if _contrast(color, reference) >= minimum:
        return color
    low, high = 0.0, 1.0
    for _ in range(24):
        mid = (low + high) / 2
        if _contrast(_mix(color, toward, mid), reference) >= minimum:
            high = mid
        else:
            low = mid
    return _mix(color, toward, high)


def _composite_channels(color, opacity, under):
    return tuple(f * opacity + u * (1 - opacity)
                 for f, u in zip(_channels(color), under))


def _hex(channels):
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in channels)


def _composite(color, opacity, backdrop):
    """Alpha-composite two #rrggbb colours to a rounded 8-bit result."""
    return _hex(_composite_channels(color, opacity, _channels(backdrop)))


def _secondary_backdrops(roles: dict, opacity: float) -> list[tuple[str, float]]:
    """Samples of every generated surface that carries secondary text.

    Each sample pairs the rounded 8-bit colour with its continuous luminance.
    The list follows generated selectors: glass surface, low/high bars, SwayNC
    standalone and nested notifications, panel cards/tiles/tabs, and opaque
    role surfaces.  Only black/white backdrop endpoints are modelled;
    arbitrary wallpaper luminance and every user opacity are not proved.
    """
    def sample(color, alpha, under):
        channels = _composite_channels(color, alpha, under)
        return _hex(channels), _channel_luminance(channels), channels

    backdrops = []
    for backdrop in ("#000000", "#ffffff"):
        under = _channels(backdrop)
        glass_hex, glass_lum, glass = sample(roles["surface"], opacity, under)
        drawer_hex, drawer_lum, drawer = sample(roles["surface_container_low"], opacity, under)
        backdrops.extend((
            (glass_hex, glass_lum),
            (drawer_hex, drawer_lum),
            sample(roles["surface_container_high"], opacity, under)[:2],
            sample(roles["surface_container_high"], .90, under)[:2],
            sample(roles["surface_container_highest"], .94, under)[:2],
            sample(roles["surface_container_high"], .90, drawer)[:2],
            sample(roles["surface_container_highest"], .94, drawer)[:2],
            sample(roles["surface_container"], .72, glass)[:2],
            sample(roles["surface_container"], .55, glass)[:2],
            sample(roles["surface_container_low"], .65, glass)[:2],
        ))
    for name in ("surface", "surface_container_low", "surface_container",
                 "surface_container_high", "surface_container_highest"):
        backdrops.append((roles[name], _luminance(roles[name])))
    return backdrops


def _readable_secondary(roles: dict, opacity: float) -> str:
    """Bounded blend of secondary text toward on_surface for rendered surfaces.

    A role that clears 4.5:1 in both the continuous and rounded composite
    models is returned byte-identically.  Otherwise 24 deterministic steps
    search for a 4.55:1 guard in both models, leaving room for toolkit
    compositing.  If on_surface itself cannot clear the guard at a low user
    opacity, the result stops at that existing anchor.
    """
    color, ink = roles["on_surface_variant"], roles["on_surface"]
    backdrops = _secondary_backdrops(roles, opacity)

    def passes(candidate, minimum):
        candidate_luminance = _luminance(candidate)
        return all(
            _contrast(candidate, rounded) >= minimum
            and _contrast_luminance(candidate_luminance, continuous) >= minimum
            for rounded, continuous in backdrops
        )

    if passes(color, 4.5):
        return color
    low, high = 0.0, 1.0
    for _ in range(24):
        mid = (low + high) / 2
        if passes(_mix(color, ink, mid), 4.55):
            high = mid
        else:
            low = mid
    return _mix(color, ink, high)


def semantic_roles(palette_values: dict, mode: str) -> dict:
    """Map the active palette onto MD3 colour roles used by every consumer."""
    dark = mode == "dark"
    background = palette_values["background"]
    surface = palette_values["surface"]
    raised = palette_values.get("surface_raised", surface)
    sunken = palette_values.get("surface_sunken", background)
    ink = palette_values["ink"]
    muted = palette_values["muted"]
    primary = palette_values["accent"]
    secondary = palette_values["secondary"]
    error = palette_values.get("error", palette_values.get("danger", "#f87171"))
    on_primary = palette_values.get("on_accent", background)
    # Surface containers progress away from the window base in small steps so
    # cards, raised chips and popovers remain distinguishable without borders.
    container_low = _mix(background, raised, .28)
    container = _mix(background, raised, .52)
    container_high = raised
    container_highest = _mix(raised, ink, .05)
    primary_container = _mix(raised, primary, .36 if dark else .22)
    # Trusted contrast handoff: correct only roles that miss 4.5:1, moving the
    # smallest distance toward an existing anchor.  Passing colours are untouched.
    on_surface_variant = _contrast_mix(muted, ink, container_highest)
    primary_container = _contrast_mix(primary_container, raised, ink)
    secondary_container = _mix(raised, secondary, .28 if dark else .16)
    error_container = _mix(raised, error, .30 if dark else .16)
    return {
        "primary": primary,
        "on_primary": on_primary,
        "primary_container": primary_container,
        "on_primary_container": ink,
        "secondary": secondary,
        "on_secondary": on_primary,
        "secondary_container": secondary_container,
        "on_secondary_container": ink,
        "surface": background,
        "surface_container_low": container_low,
        "surface_container": container,
        "surface_container_high": container_high,
        "surface_container_highest": container_highest,
        "surface_sunken": sunken,
        "on_surface": ink,
        "on_surface_variant": on_surface_variant,
        "outline": _rgba(ink, .14),
        "outline_variant": _rgba(ink, .06),
        "error": error,
        "on_error": background if dark else "#ffffff",
        "error_container": error_container,
        "on_error_container": ink,
        "surface_tint": primary,
        "inverse_surface": ink,
        "inverse_on_surface": background,
        "scrim": _rgba("#000000", .32),
        "shadow": _rgba("#000000", .30 if dark else .16),
    }


def _role_definitions(roles: dict) -> str:
    return "".join(f"@define-color md3_{name} {value};\n" for name, value in roles.items())


def _font_sizes(size: float) -> dict:
    return {name: max(8, round(size * factor, 2)) for name, factor in MD3_TYPE.items()}


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


# SwayNC's GTK4 set_size_request applies the configured width to both the
# window and its inner content box.  The generated .control-center rule adds a
# 1px border and 16px padding on each side, so subtract both from the intended
# 420px outer drawer width.
SWAYNC_OUTER_WIDTH = 420
SWAYNC_CONTENT_INSET = 16
SWAYNC_CONTENT_BORDER = 1
SWAYNC_CONTENT_WIDTH = SWAYNC_OUTER_WIDTH - 2 * (SWAYNC_CONTENT_INSET + SWAYNC_CONTENT_BORDER)
SWAYNC_TOP_GAP = 12


def notification_config(settings: dict, *, base: Path | None = None) -> dict:
    """SwayNC config with compositor-reserved top clearance.

    With ``control-center-exclusive-zone`` true SwayNC anchors below the Eww
    bar's compositor exclusive zone, so the top margin is only the 12px gap
    (false would add SwayNC's 100px fallback).  SwayNC has no monitor-width/
    max-width field, so the 420px outer width is fixed; narrow-output behavior
    is unverified and no clamp is invented here.  ``fit-to-screen`` derives
    height from the top/bottom margins, so no ignored ``control-center-height``
    key is written.  The config schema has margins for the control center only;
    toasts have no equivalent margin key.
    """
    values = validate_settings(settings)
    base = Path(base or BASE)
    notification = json.loads((base / "swaync/config.json").read_text())
    notification.update({
        "control-center-exclusive-zone": True,
        "control-center-width": SWAYNC_CONTENT_WIDTH,
        "control-center-margin-top": SWAYNC_TOP_GAP,
        "control-center-margin-right": 16,
        "control-center-margin-bottom": 16,
        "control-center-margin-left": 16,
        "notification-window-width": SWAYNC_OUTER_WIDTH,
    })
    return notification


def render_notification_config(settings: dict, *, base: Path | None = None) -> str:
    """Serialize the private/generated niri/theme/swaync.json target."""
    return json.dumps(notification_config(settings, base=base), ensure_ascii=False, indent=2) + "\n"


def _dialog_css(roles: dict) -> str:
    """Native dialogs need opaque, fully contrasted MD3 surfaces.

    This stays outside the glass-window scope: the font chooser is a separate
    GTK dialog and must not inherit translucent panel text colours.
    """
    bg, surface, ink = roles["surface"], roles["surface_container_high"], roles["on_surface"]
    accent, outline = roles["primary"], roles["outline"]
    on_primary, error = roles["on_primary"], roles["error"]
    return f"""/* Native font chooser: solid MD3 surfaces, distinct actions and selection. */
dialog {{ background: {bg}; color: {ink}; }}
dialog headerbar {{ background: {surface}; color: {ink}; border-bottom: 1px solid {outline}; box-shadow: none; }}
dialog label {{ color: inherit; text-shadow: none; }}
dialog button {{ background: {surface}; color: {ink}; border: 1px solid {outline}; border-radius: {MD3_SHAPE['button']}px; box-shadow: none; text-shadow: none; padding: 8px 14px; }}
dialog button:hover {{ background: {roles['primary_container']}; color: {roles['on_primary_container']}; border-color: {roles['primary']}; }}
dialog button:disabled {{ opacity: .38; }}
dialog button.suggested-action {{ background: {accent}; color: {on_primary}; border-color: {accent}; font-weight: 600; }}
dialog button.destructive-action {{ background: {roles['error_container']}; color: {error}; border-color: {error}; }}
dialog button:focus, dialog entry:focus {{ outline: 2px solid {accent}; outline-offset: -2px; }}
dialog entry, dialog spinbutton {{ background: {surface}; color: {ink}; caret-color: {accent}; border: 1px solid {outline}; border-radius: {MD3_SHAPE['pill']}px; box-shadow: none; padding: 8px 12px; }}
dialog entry selection {{ background: {roles['primary_container']}; color: {roles['on_primary_container']}; }}
dialog .view, dialog treeview, dialog viewport {{ background: {bg}; color: {ink}; }}
dialog .view:selected, dialog treeview:selected {{ background: {roles['primary_container']}; color: {roles['on_primary_container']}; }}
dialog textview, dialog textview text {{ background: {surface}; color: {ink}; }}
dialog separator {{ background: {outline}; }}
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


def _render_context(settings: dict, base: Path | None = None) -> dict:
    """Validated settings and every derived value the target renderers share."""
    values = validate_settings(settings)
    base = Path(base or BASE)
    p = palette(values)
    bg, surface, ink, muted = (p[key] for key in ("background", "surface", "ink", "muted"))
    accent, secondary, border = (p[key] for key in ("accent", "secondary", "border"))
    surface_raised = p.get("surface_raised", surface)
    surface_sunken = p.get("surface_sunken", bg)
    faint = p.get("faint", border)
    danger = p.get("danger", p.get("error", "#f87171"))
    on_accent = p.get("on_accent", bg)
    accent_hover = p.get("accent_hover", secondary)
    border_subtle = p.get("border_subtle", _rgba(ink, 0.06))
    opacity, size = values["opacity"], values["font_size"]
    roles = semantic_roles(p, values["color_mode"])
    if opacity < .40:
        muted = ink  # Secondary text retains full contrast on very clear glass.
        roles = {**roles, "on_surface_variant": ink}
    else:
        roles = {**roles, "on_surface_variant": _readable_secondary(roles, opacity)}
    font, mono = values["font"], values["mono_font"]
    fallbacks = ["Adwaita Sans", "Noto Sans CJK SC", "Noto Sans", "sans-serif"]
    family = ", ".join([f'"{font}"'] + [f'"{f}"' if f != "sans-serif" else f for f in fallbacks if f != font])
    mono_fallbacks = ["JetBrainsMono Nerd Font", "Adwaita Mono", "Noto Sans Mono CJK SC", "monospace"]
    mono_family = ", ".join([f'"{mono}"'] + [f'"{f}"' if f != "monospace" else f for f in mono_fallbacks if f != mono])
    type_sizes = _font_sizes(size)
    def px(role):
        return f"{type_sizes[role]:g}px"
    r = roles
    rgba = _rgba
    css_header = "/* Generated by Selandia appearance settings; edit templates or use Control Center. */\n"
    aliases = f"""@define-color ink {ink};
@define-color muted {r['on_surface_variant']};
@define-color faint {faint};
@define-color cyan {accent};
@define-color violet {secondary};
@define-color accent {r['primary']};
@define-color secondary {r['secondary']};
@define-color accent_hover {accent_hover};
@define-color surface {surface};
@define-color surface_raised {surface_raised};
@define-color surface_sunken {surface_sunken};
@define-color bg {bg};
@define-color border {border};
@define-color border_subtle {border_subtle};
@define-color on_accent {r['on_primary']};
@define-color danger {r['error']};
@define-color success {p['success']};
@define-color warning {p['warning']};
"""
    # Liquid Glass MD3 layer: frosted translucency, specular top rim, dual-tone luminous accents.
    dark_mode = values["color_mode"] == "dark"
    sheen_a = .13 if dark_mode else .10
    sheen_b = .06 if dark_mode else .05
    rim_alpha = .28 if dark_mode else .24
    top_edge = rgba("#ffffff", .18 if dark_mode else .75)
    card_edge = rgba("#ffffff", .11 if dark_mode else .65)
    grad_accent = f"linear-gradient(135deg, {r['primary']}, {r['secondary']})"
    grad_bar = f"linear-gradient(90deg, {r['primary']}, {r['secondary']})"
    outline = "text-shadow: -1px 0 " + bg + ", 1px 0 " + bg + ", 0 -1px " + bg + ", 0 1px " + bg + ";" if opacity < .40 else ""
    context = dict(locals())
    context.pop("settings")
    return context


def _render_panel(*, accent_hover, aliases, bg, card_edge, css_header, dark_mode, family, grad_accent,
                  grad_bar, ink, mono_family, opacity, px, r, rgba, rim_alpha, sheen_a, sheen_b, size,
                  top_edge, type_sizes) -> str:
    """Render ``panel.css``."""
    panel = css_header + _role_definitions(r) + aliases + f"""* {{ font-family: {family}; font-size: {size:g}px; }}
.glass-surface {{ color: {r['on_surface']}; background-color: {rgba(r['surface'], opacity)};
    background-image: linear-gradient(148deg, {rgba(r['primary'], sheen_a)}, {rgba(r['secondary'], sheen_b)} 38%, transparent 74%);
    border: 1px solid {rgba(r['primary'], rim_alpha)}; border-radius: {MD3_SHAPE['window']}px;
    box-shadow: inset 0 1px {top_edge}, inset 0 -1px {rgba(r['secondary'], .10)}, 0 22px 56px {r['shadow']}; }}
.panel-header {{ padding: 18px 20px 14px; border-bottom: 1px solid {rgba(r['primary'], .16)};
    background-image: linear-gradient(90deg, {rgba(r['primary'], .09)}, {rgba(r['secondary'], .06)} 55%, transparent); }}
.panel-content {{ padding: 16px 20px 20px; }}
.panel-title {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.3px; }}
.subtitle, .hint, .control-label {{ color: {r['on_surface_variant']}; font-size: {px('body')}; }}
.eyebrow, .section-title, .message-role {{ color: {r['primary']}; font-size: {px('overline')}; font-weight: 700; letter-spacing: 1.8px; }}
.clock {{ color: {r['on_surface']}; font-size: {px('display')}; font-weight: 600; letter-spacing: -.8px; }}
.card, .message, .metric-card, .pulse-card, .application-audio {{ padding: 14px; border: 1px solid {rgba(r['on_surface'], .10)};
    background-color: {rgba(r['surface_container'], .68)};
    background-image: linear-gradient(165deg, {rgba('#ffffff', .05 if dark_mode else .45)}, transparent 42%);
    border-radius: {MD3_SHAPE['card']}px;
    box-shadow: inset 0 1px {card_edge}, 0 8px 24px {rgba('#000000', .14 if dark_mode else .07)}; }}
button {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .62)};
    background-image: linear-gradient(180deg, {rgba('#ffffff', .06 if dark_mode else .45)}, transparent);
    border: 1px solid {rgba(r['on_surface'], .14)}; border-radius: {MD3_SHAPE['button']}px; padding: 8px 13px;
    box-shadow: inset 0 1px {card_edge}; text-shadow: none;
    transition: background-color 150ms ease-out, border-color 150ms ease-out, color 150ms ease-out, box-shadow 150ms ease-out; }}
button:hover {{ background-color: {rgba(r['primary'], .16)}; border-color: {rgba(r['primary'], .48)};
    box-shadow: inset 0 1px {top_edge}, 0 4px 14px {rgba(r['primary'], .18)}; border-radius: {MD3_SHAPE['button']}px; }}
button:checked, button:active {{ color: {r['on_primary_container']}; background-color: {r['primary_container']};
    background-image: linear-gradient(135deg, {rgba(r['primary'], .28)}, {rgba(r['secondary'], .16)});
    border-color: {rgba(r['primary'], .58)}; border-radius: {MD3_SHAPE['button']}px; }}
button:focus, button:focus-within {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 2px {r['primary']}; }}
button:disabled {{ opacity: .38; }}
button.flat, button.md3-text-button {{ color: {r['primary']}; background-color: transparent;
    background-image: none; border-color: transparent; box-shadow: none; }}
button.flat:hover, button.md3-text-button:hover {{ color: {r['on_primary_container']};
    background-color: {rgba(r['primary'], .14)}; border-color: transparent; box-shadow: none; }}
button.flat:checked, button.md3-text-button:checked {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']}; border-color: transparent; }}
button.accent-button {{ color: {r['on_primary']}; background-color: {r['primary']}; background-image: {grad_accent};
    border-color: {rgba(r['primary'], .85)}; font-weight: 700;
    box-shadow: inset 0 1px {rgba('#ffffff', .35)}, 0 4px 16px {rgba(r['primary'], .34)}; }}
button.accent-button:hover {{ background-color: {accent_hover}; background-image: {grad_accent}; border-color: {r['secondary']};
    box-shadow: inset 0 1px {rgba('#ffffff', .45)}, 0 6px 20px {rgba(r['primary'], .45)}; }}
button.accent-button:focus {{ box-shadow: inset 0 0 0 2px {r['on_primary']}; }}
button.power-button {{ color: {r['error']}; border-color: {rgba(r['error'], .34)}; background-color: {rgba(r['error'], .10)}; background-image: none; }}
button.power-button:hover {{ color: {r['error']}; border-color: {rgba(r['error'], .62)}; background-color: {r['error_container']};
    box-shadow: 0 4px 14px {rgba(r['error'], .22)}; }}
button.small-button {{ font-size: {px('caption')}; padding: 5px 9px; border-radius: {MD3_SHAPE['button']}px; }}
button.tool-button {{ padding: 9px 7px; font-size: {px('caption')}; }}
button.close-button {{ min-width: 30px; min-height: 30px; padding: 0; border-radius: {MD3_SHAPE['badge']}px;
    color: {r['on_surface_variant']}; background-color: {rgba(r['on_surface'], .05)}; background-image: none;
    border-color: {rgba(r['on_surface'], .08)}; box-shadow: none; font-size: {type_sizes['title_large']:g}px; }}
button.close-button:hover {{ color: {r['on_surface']}; background-color: {rgba(r['primary'], .18)}; border-color: {rgba(r['primary'], .42)}; }}
button.close-button:checked, button.close-button:active {{ border-radius: {MD3_SHAPE['badge']}px; }}
.control-tabs {{ padding: 4px; border: 1px solid {rgba(r['primary'], .18)}; border-radius: {MD3_SHAPE['pill']}px;
    background-color: {rgba(r['surface_container_low'], .68)}; }}
.control-tabs button {{ color: {r['on_surface_variant']}; background: transparent; background-image: none; border-color: transparent;
    border-radius: {MD3_SHAPE['badge']}px; box-shadow: none; padding: 6px 4px; font-size: {px('caption')}; }}
.control-tabs button:hover {{ color: {r['on_surface']}; background-color: {rgba(r['primary'], .12)}; }}
.control-tabs button:checked, .control-tabs button:active, .control-tabs button:selected {{ color: {r['on_primary_container']};
    border-radius: {MD3_SHAPE['badge']}px; background-color: {r['primary_container']};
    background-image: linear-gradient(135deg, {rgba(r['primary'], .28)}, {rgba(r['secondary'], .18)});
    border-color: {rgba(r['primary'], .44)}; }}
.scale, scale {{ padding: 6px 2px; }}
scale trough {{ min-height: 6px; border: 1px solid {rgba(r['on_surface'], .12)}; border-radius: {MD3_SHAPE['badge']}px; background-color: {rgba(r['surface_sunken'], .85)}; background-image: none; }}
scale highlight {{ min-height: 6px; border: none; border-radius: {MD3_SHAPE['badge']}px; background-color: {r['primary']}; background-image: {grad_bar}; }}
scale slider {{ min-width: 16px; min-height: 16px; margin: -5px; border: 2px solid {r['primary']};
    border-radius: {MD3_SHAPE['badge']}px; background-color: #ffffff; background-image: none;
    box-shadow: 0 2px 8px {rgba('#000000', .38)}, 0 0 0 2px {rgba(r['primary'], .22)}; }}
scale:focus trough {{ outline: none; box-shadow: 0 0 0 2px {rgba(r['primary'], .45)}; }}
scale:disabled {{ opacity: .38; }}
progressbar trough, .metric-progress trough {{ min-height: 6px; border: 1px solid {rgba(r['on_surface'], .12)}; border-radius: {MD3_SHAPE['badge']}px;
    background-color: {rgba(r['surface_sunken'], .85)}; background-image: none; }}
progressbar progress, .metric-progress progress {{ min-height: 6px; border: none; border-radius: {MD3_SHAPE['badge']}px;
    background-color: {r['primary']}; background-image: {grad_bar}; }}
.metric-value, .network-rate, .quick-slider-value, .pulse-value {{ font-family: {mono_family}; font-feature-settings: "tnum 1, cv01 1"; }}
.spec-value {{ font-family: {mono_family}, {family}; }}
.metric-value, .network-rate {{ color: {r['primary']}; font-weight: 700; letter-spacing: -.3px; }}
.metric-value {{ font-size: {type_sizes['headline']:g}px; }}
.network-rate {{ font-size: {type_sizes['title_large']:g}px; }}
entry, spinbutton {{ color: {r['on_surface']}; caret-color: {r['primary']}; border: 1px solid {rgba(r['on_surface'], .14)};
    border-radius: {MD3_SHAPE['pill']}px; padding: 9px 12px; background-color: {rgba(r['surface_sunken'], .62)};
    box-shadow: inset 0 1px 3px {rgba('#000000', .18 if dark_mode else .06)}; }}
entry:focus, spinbutton:focus {{ outline: none; border-color: {r['primary']};
    box-shadow: inset 0 0 0 1px {rgba(r['primary'], .65)}, 0 0 0 3px {rgba(r['primary'], .16)}; }}
entry selection, textview text selection {{ background-color: {r['primary_container']}; color: {r['on_primary_container']}; }}
spinbutton button {{ border: none; background: transparent; background-image: none; box-shadow: none; border-radius: {MD3_SHAPE['button']}px; padding: 5px 8px; }}
menu, tooltip {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .95)};
    border: 1px solid {rgba(r['primary'], .28)}; border-radius: {MD3_SHAPE['button']}px; padding: 5px;
    box-shadow: 0 10px 28px {r['shadow']}; }}
menuitem {{ padding: 8px; border-radius: {MD3_SHAPE['button']}px; }}
menuitem:hover {{ background-color: {rgba(r['primary'], .16)}; }}
list.wallpaper-list {{ background: transparent; color: {r['on_surface']}; }}
list.wallpaper-list row {{ border: 1px solid {rgba(r['on_surface'], .08)}; border-radius: {MD3_SHAPE['button']}px;
    margin: 2px 0; background: {rgba(r['surface_container'], .52)}; color: {r['on_surface']}; padding: 6px 8px; }}
list.wallpaper-list row:hover {{ background: {rgba(r['primary'], .12)}; border-color: {rgba(r['primary'], .28)}; }}
list.wallpaper-list row:selected, list.wallpaper-list row:active {{ border-radius: {MD3_SHAPE['button']}px;
    background: {r['primary_container']}; background-image: linear-gradient(90deg, {rgba(r['primary'], .24)}, {rgba(r['secondary'], .10)});
    border-color: {rgba(r['primary'], .55)}; color: {r['on_primary_container']}; }}
flowbox.wallpaper-grid {{ background: transparent; padding: 4px; }}
flowbox.wallpaper-grid flowboxchild, .wallpaper-tile {{ padding: 10px; border: 1px solid {rgba(r['on_surface'], .09)};
    border-radius: {MD3_SHAPE['card']}px; background-color: {rgba(r['surface_container'], .52)};
    box-shadow: inset 0 1px {card_edge}; }}
flowbox.wallpaper-grid flowboxchild:hover, .wallpaper-tile:hover {{ background-color: {rgba(r['primary'], .12)}; border-color: {rgba(r['primary'], .35)}; }}
flowbox.wallpaper-grid flowboxchild:selected, .wallpaper-tile:selected {{ border-radius: {MD3_SHAPE['card']}px;
    background-image: linear-gradient(145deg, {rgba(r['primary'], .22)}, {rgba(r['secondary'], .12)});
    border-color: {rgba(r['primary'], .65)}; background-color: {r['primary_container']};
    box-shadow: 0 6px 18px {rgba(r['primary'], .22)}; }}
.audio-stream-row {{ padding: 12px; border: 1px solid {rgba(r['on_surface'], .09)}; border-radius: {MD3_SHAPE['card']}px;
    background-color: {rgba(r['surface_container'], .52)}; }}
.audio-stream-row button:checked {{ border-radius: {MD3_SHAPE['button']}px; background-color: {r['primary_container']};
    border-color: {rgba(r['primary'], .52)}; color: {r['on_primary_container']}; }}
.system-inventory {{ color: {r['on_surface']}; font-size: {size:g}px; }}
label.system-summary {{ font-family: {mono_family}; color: {r['on_surface']}; }}
.keycap {{ font-family: {mono_family}; font-size: {px('caption')}; color: {r['primary']}; font-weight: 600;
    background-color: {rgba(r['primary'], .12)}; background-image: linear-gradient(180deg, {rgba(r['primary'], .14)}, {rgba(r['secondary'], .06)});
    border: 1px solid {rgba(r['primary'], .32)};
    border-radius: {MD3_SHAPE['button']}px; padding: 5px 9px; box-shadow: inset 0 1px {card_edge}; text-shadow: none; }}
.shortcut-description, .welcome-copy, .message-text {{ color: {r['on_surface']}; font-size: {px('body')}; }}
.user-message {{ background-color: {r['primary_container']};
    background-image: linear-gradient(135deg, {rgba(r['primary'], .26)}, {rgba(r['secondary'], .16)});
    border-color: {rgba(r['primary'], .36)}; }}
.assistant-message {{ background-color: {rgba(r['surface_container_high'], .72)};
    border-left: 3px solid {r['secondary']}; }}
.composer {{ padding: 10px; border: 1px solid {rgba(r['primary'], .24)}; border-radius: {MD3_SHAPE['card']}px;
    background-color: {rgba(r['surface_container_low'], .64)};
    box-shadow: inset 0 1px {card_edge}; }}
textview, textview text {{ color: {r['on_surface']}; caret-color: {r['primary']}; background: transparent; }}
.media-title {{ color: {r['on_surface']}; font-size: {px('title_medium')}; font-weight: 600; }}
.empty-state {{ color: {r['on_surface_variant']}; padding: 40px; }}
.provider-status, .value {{ color: {r['primary']}; font-size: {px('caption')}; font-weight: 600; }}
.status {{ color: {r['primary']}; font-size: {px('body')}; }}
.status.error {{ color: {r['error']}; }}
.welcome-icon {{ color: {r['secondary']}; font-size: {type_sizes['headline']:g}px; margin-bottom: 4px; }}
.welcome-title {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.3px; }}
combobox button {{ padding: 7px 10px; }}
combobox arrow {{ color: {r['on_surface_variant']}; }}
scrollbar {{ background: transparent; opacity: 1; }}
scrollbar trough {{ background: transparent; }}
scrollbar slider {{ background-color: {rgba(r['on_surface'], .24)}; border-radius: {MD3_SHAPE['badge']}px; }}
scrollbar slider:hover {{ background-color: {rgba(r['primary'], .55)}; }}
scrollbar slider:active {{ background-color: {r['primary']}; }}
scrolledwindow, viewport {{ background: transparent; border: none; }}
row:focus {{ outline: none; box-shadow: inset 0 0 0 2px {rgba(r['primary'], .85)}; }}
.glass-calendar {{ background-color: {rgba(r['surface_container'], .55)}; border-color: {r['outline_variant']}; }}
.calendar-page {{ padding: 12px; }}
.calendar-page .calendar-card, .calendar-page .calendar-footer {{ padding: 12px; }}
.calendar-card .glass-calendar {{ background: transparent; border: none; padding: 0; }}
.calendar-page.calendar-narrow .glass-calendar .calendar-title {{ font-size: {px('title_medium')}; }}
.calendar-page.calendar-narrow .glass-calendar button.calendar-day-btn {{ min-width: 0; padding: 4px 0; }}
.calendar-date {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.2px; }}
button.calendar-primary {{ color: {r['on_primary']}; background-color: {r['primary']}; background-image: {grad_accent};
    border: 1px solid {r['primary']}; font-weight: 700; min-height: 34px; padding: 0 16px;
    border-radius: 999px; box-shadow: inset 0 1px {rgba('#ffffff', .35)}, 0 4px 14px {rgba(r['primary'], .35)}; }}
button.calendar-primary:hover {{ color: {r['on_primary']}; background-color: {accent_hover}; background-image: {grad_accent};
    border-color: {r['secondary']}; box-shadow: 0 6px 18px {rgba(r['primary'], .45)}; }}
button.calendar-primary:checked, button.calendar-primary:active {{ color: {r['on_primary']};
    background-color: {r['primary']}; border-color: {r['primary']}; }}
button.calendar-secondary {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .68)};
    border: 1px solid {rgba(r['on_surface'], .15)}; font-weight: 600; min-height: 34px; padding: 0 16px;
    border-radius: 999px; }}
button.calendar-secondary:hover {{ color: {r['on_surface']}; background-color: {rgba(r['primary'], .16)};
    border-color: {rgba(r['primary'], .50)}; }}
button.calendar-secondary:checked, button.calendar-secondary:active {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .55)}; }}
.glass-calendar .calendar-header {{ color: {r['on_surface']}; border-bottom: 1px solid {rgba(r['primary'], .18)};
    padding-bottom: 6px; margin-bottom: 4px; }}
.glass-calendar .calendar-title {{ color: {r['on_surface']}; font-size: {round(type_sizes['title_large'] * 1.31, 2):g}px; font-weight: 700; letter-spacing: -.2px; }}
.glass-calendar .calendar-week-num {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; padding: 0 4px; }}
.glass-calendar .calendar-empty-cell {{ color: transparent; background-color: transparent; }}
.glass-calendar .calendar-weekday-header, .glass-calendar .calendar-week-header {{ color: {r['primary']};
    font-size: {round(type_sizes['caption'] * 1.16, 2):g}px; font-weight: 700; padding: 4px 0; }}
.glass-calendar button.calendar-nav-btn {{ color: {r['on_surface']}; background: {rgba(r['surface_container_high'], .58)};
    border: 1px solid {rgba(r['on_surface'], .12)}; box-shadow: none; padding: 2px 4px; min-width: 32px;
    min-height: 32px; border-radius: 999px; }}
.glass-calendar button.calendar-nav-btn:checked, .glass-calendar button.calendar-nav-btn:active {{ color: {r['on_primary']};
    background-color: {r['primary']}; background-image: {grad_accent}; border-color: {r['primary']}; }}
.glass-calendar button.calendar-nav-btn:hover {{ color: {r['primary']}; background-color: {rgba(r['primary'], .14)}; border-color: {rgba(r['primary'], .40)}; }}
.glass-calendar button.calendar-day-btn {{ background: transparent; background-image: none; border: 1px solid transparent; box-shadow: none;
    padding: 4px 2px; min-width: 32px; min-height: 30px; border-radius: 999px;
    font-size: {round(type_sizes['body'] * 1.05, 2):g}px; font-weight: 500; color: {r['on_surface']}; }}
.glass-calendar button.calendar-day-btn:hover {{ background-color: {rgba(r['primary'], .16)}; border-color: {rgba(r['primary'], .38)}; }}
.glass-calendar button.calendar-day-btn.today {{ border-color: {r['primary']}; color: {r['on_surface']};
    background-color: {rgba(r['primary'], .18)}; font-weight: 700; box-shadow: 0 0 0 1px {rgba(r['primary'], .28)}; }}
.glass-calendar button.calendar-day-btn.selected {{ background-image: {grad_accent}; background-color: {r['primary']};
    border-color: {r['primary']}; color: {r['on_primary']}; font-weight: 700;
    box-shadow: 0 3px 12px {rgba(r['primary'], .42)}; }}
.glass-calendar button.calendar-day-btn.today.selected {{ color: {r['on_primary']}; background-color: {r['primary']};
    background-image: {grad_accent}; border: 2px solid {r['on_primary']}; }}
.glass-calendar button.calendar-day-btn.selected label {{ color: {r['on_primary']}; text-shadow: none; font-weight: 700; }}
.glass-calendar button:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
"""
    if opacity < .40:
        panel += f"""/* Low-opacity legibility: no change to the requested surface alpha. */
label {{ color: {ink}; text-shadow: 1px 0 0 {bg}, -1px 0 0 {bg}, 0 1px 0 {bg}, 0 -1px 0 {bg}; }}
.card, .message, .metric-card {{ border-color: {r['outline']}; }}
.panel-header, .control-tabs {{ border-color: {r['outline']}; }}
separator {{ background-color: {r['outline']}; }}
"""
    panel = _scope_panel_css(panel) + _dialog_css(r)
    panel += f"""window.glass-window.control-center-window .glass-surface {{
    border-color: {rgba(r['primary'], .30)};
    background-image: linear-gradient(148deg, {rgba(r['primary'], sheen_a)}, {rgba(r['secondary'], sheen_b)} 36%, transparent 72%);
    box-shadow: inset 0 1px {top_edge}, inset 0 -1px {rgba(r['secondary'], .14)}, 0 28px 72px {r['shadow']};
}}
window.glass-window.power-menu-window .glass-surface {{
    border-color: {rgba(r['primary'], .30)};
    background-image: linear-gradient(155deg, {rgba(r['primary'], sheen_a)}, {rgba(r['secondary'], sheen_b)} 42%, transparent 78%);
    box-shadow: inset 0 1px {top_edge}, 0 22px 54px {r['shadow']};
}}
"""
    return panel


def _render_swaync(*, bg, card_edge, css_header, dark_mode, family, grad_accent, grad_bar, opacity, px,
                   r, rgba, rim_alpha, sheen_a, sheen_b, size, top_edge) -> str:
    """Render ``swaync.css``."""
    swaync = '@import "../swaync/style.css";\n' + css_header + _role_definitions(r) + f"""@define-color bg {bg};
@define-color cc-bg {rgba(r['surface_container_low'], opacity)};
@define-color noti-bg {rgba(r['surface_container_high'], max(.82, opacity))};
@define-color noti-border-color {rgba(r['primary'], .24)};
@define-color text-color {r['on_surface']};
@define-color text-color-disabled {r['on_surface_variant']};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
.control-center {{ background-color: {rgba(r['surface_container_low'], opacity)};
    background-image: linear-gradient(155deg, {rgba(r['primary'], sheen_a)}, {rgba(r['secondary'], sheen_b)} 42%, transparent 78%);
    color: {r['on_surface']};
    border: 1px solid {rgba(r['primary'], rim_alpha)}; border-radius: {MD3_SHAPE['window']}px; padding: 16px;
    box-shadow: inset 0 1px {top_edge}, 0 22px 56px {r['shadow']}; }}
.notification {{ background-color: {rgba(r['surface_container_high'], max(.86, opacity))};
    background-image: linear-gradient(160deg, {rgba('#ffffff', .05 if dark_mode else .50)}, transparent 45%);
    border: 1px solid {rgba(r['on_surface'], .12)}; border-left: 3px solid {r['primary']};
    border-radius: {MD3_SHAPE['card']}px; padding: 8px;
    box-shadow: inset 0 1px {card_edge}, 0 8px 24px {rgba('#000000', .22 if dark_mode else .10)}; }}
.notification:hover {{ background-color: {rgba(r['surface_container_highest'], .94)};
    border-color: {rgba(r['primary'], .45)}; border-left-color: {r['secondary']}; }}
.summary, .widget-title {{ color: {r['on_surface']}; font-weight: 700; }}
.body, .widget-dnd {{ color: {r['on_surface']}; }}
.time, .app-name {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; font-weight: 600; }}
.notification-row .notification-background .notification.critical {{ border-color: {r['error']}; border-left: 3px solid {r['error']}; background-color: {r['error_container']}; }}
.notification-group:focus .notification, .notification-row:focus .notification,
.notification-row:focus-within .notification {{ outline: 2px solid {r['primary']}; outline-offset: -2px; }}
.widget-dnd {{ background-color: {rgba(r['surface_container'], .68)}; border: 1px solid {rgba(r['on_surface'], .10)};
    border-radius: {MD3_SHAPE['pill']}px; box-shadow: inset 0 1px {card_edge}; }}
button {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .72)};
    border: 1px solid {rgba(r['on_surface'], .14)}; border-radius: {MD3_SHAPE['button']}px; box-shadow: none; text-shadow: none;
    transition: background-color 140ms ease-out, border-color 140ms ease-out; }}
button:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .45)}; }}
button:checked, button:active {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {r['primary']}; }}
button:disabled {{ opacity: .38; }}
button:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
button.suggested-action {{ background-color: {r['primary']}; background-image: {grad_accent}; color: {r['on_primary']}; border-color: {r['primary']}; font-weight: 700; }}
.notification-default-action {{ background: transparent; }}
.close-button {{ background-color: {rgba(r['on_surface'], .10)}; border-radius: {MD3_SHAPE['badge']}px; }}
.close-button:hover {{ background-color: {rgba(r['error'], .22)}; color: {r['error']}; }}
switch {{ background-color: {rgba(r['surface_sunken'], .85)}; border: 1px solid {rgba(r['on_surface'], .16)}; border-radius: {MD3_SHAPE['badge']}px; }}
switch:checked {{ background-color: {r['primary']}; background-image: {grad_bar}; border-color: {r['primary']}; }}
switch slider {{ background-color: #ffffff; border-radius: {MD3_SHAPE['badge']}px; box-shadow: 0 1px 4px rgba(0, 0, 0, .35); }}
scrollbar slider {{ background-color: {rgba(r['on_surface'], .24)}; border-radius: {MD3_SHAPE['badge']}px; }}
"""
    return swaync


def _render_kdl(*, accent, bg, border, danger, ink, opacity, secondary) -> str:
    """Render ``theme.kdl``."""
    kdl = f'''// Generated palette overrides. Keep layout preferences in conf/appearance.kdl.
layout {{
    struts {{ top 0; }}
    background-color "{bg}"
    focus-ring {{
        active-gradient from="{accent}" to="{secondary}" angle=135
        inactive-color "{border}48"
        urgent-color "{danger}"
        width 2
    }}
    tab-indicator {{
        active-gradient from="{accent}" to="{secondary}" angle=90
        inactive-color "{ink}22"
    }}
}}
overview {{ backdrop-color "{bg}"; }}
// Low-opacity panel text uses a crisp outline and a noise-free blur surface.
window-rule {{
    match app-id=r#"^org\\.selandia\\.Glass$"# title="^Selandia · control$"
    background-effect {{ noise {0 if opacity < .40 else .02}; }}
    shadow {{ on; softness 38; spread 2; offset x=0 y=10; color "{bg}77"; }}
}}
layer-rule {{
    match namespace="^selandia-.*$"
    background-effect {{ noise {0 if opacity < .40 else .02}; }}
}}
layer-rule {{
    match namespace="^(launcher|selandia-.*)$"
    shadow {{ on; softness 42; spread 3; offset x=0 y=12; color "{bg}77"; }}
}}
layer-rule {{
    match namespace="^(selandia-bar-.*|selandia-island)$"
    shadow {{ off; }}
    background-effect {{ blur false; xray false; saturation 1.0; noise 0; }}
}}
'''
    return kdl


def _render_fuzzel(*, accent, base, bg, font, opacity, r, size) -> str:
    """Render ``fuzzel.ini``."""
    # Retained dmenu protocol uses the same palette as Anyrun.
    fuzzel = (base / "fuzzel/fuzzel.ini").read_text()
    # A generated launcher configuration is single-language too: never write the
    # bilingual template back. The launch script overrides this at run time so a
    # language switch applies without re-applying the theme.
    launcher_px = font_scale.launcher_pixels(size)
    fuzzel = _replace_ini(fuzzel, "main", {"font": f"{font_scale.fuzzel_pattern(font, launcher_px)},"
                                                   f"{font_scale.fuzzel_pattern('Noto Sans CJK SC', launcher_px)}",
                                         "line-height": max(36, round(launcher_px * 2.4)),
                                         "placeholder": tr("Select an item", "选择条目")})
    fuzzel = _replace_ini(fuzzel, "colors", {"background": _alpha(bg, opacity),
        "text": _alpha(r['on_surface'], 1), "prompt": _alpha(r['primary'], 1),
        "placeholder": _alpha(r['on_surface_variant'], 1), "input": _alpha(r['on_surface'], 1),
        "match": _alpha(r['primary'], 1), "selection": _alpha(r['primary_container'], 1),
        "selection-text": _alpha(r['on_primary_container'], 1),
        "selection-match": _alpha(r['primary'], 1), "counter": _alpha(r['on_surface_variant'], 1),
        "border": _alpha(accent, .65)})
    fuzzel = _replace_ini(fuzzel, "border", {"radius": MD3_SHAPE["window"],
                                              "selection-radius": MD3_SHAPE["button"]})
    return fuzzel


def _render_lock(*, accent, base, bg, border, danger, font, ink, opacity, secondary, size, surface) -> str:
    """Render ``swaylock.conf``."""
    lock = _replace_ini((base / "swaylock/config").read_text(), "", {"color": bg[1:], "font": font,
        "font-size": font_scale.whole_points(font_scale.lock_pixels(size)), "inside-color": _alpha(bg, max(.86, opacity)), "ring-color": border[1:],
        "text-color": ink[1:], "key-hl-color": accent[1:], "bs-hl-color": secondary[1:],
        "inside-ver-color": _alpha(surface, .92), "ring-ver-color": accent[1:], "text-ver-color": ink[1:],
        "inside-wrong-color": _alpha(surface, .92), "ring-wrong-color": danger[1:], "text-wrong-color": ink[1:]})
    return lock


def _render_eww(*, bg, css_header, dark_mode, family, grad_accent, grad_bar, mono_family, opacity,
                outline, p, r, rgba, size, surface, top_edge) -> str:
    """Render ``eww.css``."""
    # Rust frontends consume the same generated roles as GTK; only their
    # selector vocabulary differs.  Bar geometry and timing stay owned by
    # bar_backend.py, so padding, heights and animation hooks are unchanged.
    bar_top = rgba(_mix(r['surface_container_high'], r['primary'], .12 if dark_mode else .06), opacity)
    bar_bot = rgba(r['surface_container'], opacity)
    island_top = rgba(_mix(r['surface_container_highest'], r['primary'], .16 if dark_mode else .08), opacity)
    island_bot = rgba(r['surface_container_low'], opacity)
    eww = css_header + _role_definitions(r) + f"""@define-color bg {bg};
@define-color surface {surface};
@define-color accent {r['primary']};
@define-color secondary {r['secondary']};
@define-color on_accent {r['on_primary']};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
window.background, window, .background {{ background-color: rgba(0, 0, 0, 0); background-image: none; border: none; box-shadow: none; }}
.bar-host {{ background-color: rgba(0, 0, 0, 0); background-image: none; border: none; box-shadow: none; }}
.segment {{ background-color: {rgba(r['surface_container_high'], opacity)};
    background-image: linear-gradient(180deg, {bar_top}, {bar_bot});
    border: 1px solid {rgba(r['primary'], .26 if dark_mode else .22)}; border-radius: 22px; padding: 2px 10px;
    box-shadow: inset 0 1px {top_edge}, inset 0 -1px {rgba(r['secondary'], .10)}; }}
button {{ background: transparent; border: none; box-shadow: none; }}
.pill {{ color: {r['on_surface']}; background: transparent; border: none; border-radius: {MD3_SHAPE['pill']}px; padding: 3px 8px; transition: background-color 140ms ease-out, color 140ms ease-out, box-shadow 140ms ease-out; }}
.segment .pill * {{ background-color: transparent; background-image: none; box-shadow: none; }}
.segment .pill, .segment .workspace {{ background: transparent; border: none; }}
.segment .pill.launcher-btn {{ color: {r['primary']}; background: {rgba(r['primary'], .14)}; padding: 3px 10px; font-weight: 700; }}
.segment .pill.launcher-btn:hover {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; box-shadow: 0 2px 10px {rgba(r['primary'], .42)}; }}
.segment .pill.control-btn {{ color: {r['primary']}; }}
.segment .pill.audio-btn.muted {{ color: {r['error']}; background: {rgba(r['error'], .14)}; }}
.segment .pill.clock, .segment .pill.resources, .segment .pill.current-app {{
    background-color: {rgba(r['surface_container_low'], .72)};
    background-image: linear-gradient(180deg, {rgba('#ffffff', .05 if dark_mode else .50)}, transparent);
    border: 1px solid {rgba(r['on_surface'], .09)};
    border-radius: 999px; padding: 2px 10px; margin: 0 2px; }}
.segment .pill.clock {{ padding: 0 11px; border-color: {rgba(r['secondary'], .24)}; }}
.segment .pill.current-app {{ border-color: {rgba(r['primary'], .22)}; }}
.app-dot {{ color: {r['primary']}; font-size: {round(size * .72, 2):g}px; margin-right: 4px; }}
.app-label {{ font-weight: 600; }}
/* 状态规则必须与上面 3 类选择器同优先级，否则底色被基础规则压住、只有文字变色。 */
.segment .pill.clock:hover, .segment .pill.resources:hover, .segment .pill.current-app:hover {{
    color: {r['on_primary_container']}; background: {rgba(r['primary'], .20)}; border-color: {rgba(r['primary'], .45)}; }}
.segment .pill.clock:active, .segment .pill.clock:checked,
.segment .pill.resources:active, .segment .pill.resources:checked,
.segment .pill.current-app:active, .segment .pill.current-app:checked {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; }}
.segment .pill.clock:focus, .segment .pill.resources:focus, .segment .pill.current-app:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.workspace {{ color: {r['on_surface_variant']}; background: transparent; border: none; border-radius: 999px; padding: 3px 8px; min-width: 20px; font-weight: 600; transition: background-color 140ms ease-out, color 140ms ease-out; }}
.workspace:hover, .pill:hover {{ color: {r['on_primary_container']}; background: {rgba(r['primary'], .20)}; border-radius: 999px; }}
/* 工作区持久选中可以更宽；普通 pill 的按压/选中反馈只换配色，padding、字重等几何保持基态。 */
.workspace.active, .workspace:active {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent};
    border-radius: 999px; font-weight: 700; min-width: 32px; padding: 3px 12px;
    box-shadow: inset 0 1px {rgba('#ffffff', .35)}, 0 2px 10px {rgba(r['primary'], .45)}; }}
.pill:active, .pill:checked {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; }}
.workspace.active label, .workspace:active label, .pill:active label, .pill:checked label {{ color: {r['on_primary']}; }}
.compact .pill, .compact .workspace {{ padding: 2px 5px; }}
/* Side capsules keep their horizontal padding; only height and shape change. */
.segment .pill, .segment .workspace,
.segment .pill:hover, .segment .pill:active, .segment .pill:checked,
.segment .workspace:hover, .segment .workspace:active, .segment .workspace.active {{ border-radius: 999px; }}
.separator {{ background-color: {rgba(r['primary'], .22)}; min-width: 1px; margin: 7px 4px; }}
.resource-row {{ background: transparent; }}
.resource {{ padding: 0 3px; }}
.resource-icon {{ color: {r['primary']}; font-size: {round(size * .76, 2):g}px; font-weight: 700; margin-right: 3px; }}
.resource.cpu .resource-icon {{ color: {r['primary']}; }}
.resource.ram .resource-icon {{ color: {r['secondary']}; }}
.resource.temp .resource-icon {{ color: {p['warning']}; }}
.pill.network-btn .resource-icon {{ color: {p['success']}; }}
.resource-value {{ color: {r['on_surface']}; font-family: {mono_family}; font-size: {round(size * .88, 2):g}px; font-weight: 600; font-feature-settings: "tnum 1, cv01 1"; }}
.clock-time {{ color: {r['on_surface']}; font-family: {mono_family}; font-size: {round(size * 1.06, 2):g}px; font-weight: 700; letter-spacing: -0.3px; font-feature-settings: "tnum 1, cv01 1"; }}
.clock-date {{ color: {r['primary']}; font-size: {round(size * .70, 2):g}px; font-weight: 600; letter-spacing: .05em; margin-top: 0; }}
.island {{ background-color: {rgba(r['surface_container_highest'], opacity)};
    background-image: linear-gradient(180deg, {island_top}, {island_bot});
    border: 1px solid {rgba(r['primary'], .30 if dark_mode else .24)}; border-radius: 22px; padding: 8px 12px;
    box-shadow: inset 0 1px {top_edge}, inset 0 -1px {rgba(r['secondary'], .12)}; }}
.island.playing, .island.expanded {{ border-color: {rgba(r['primary'], .52)};
    box-shadow: inset 0 1px {top_edge}, 0 0 14px {rgba(r['primary'], .24)}; }}
.island-idle-icon {{ color: {r['primary']}; font-size: {round(size * 1.05, 2):g}px; font-weight: 700; }}
.island.playing .island-idle-icon {{ color: {r['secondary']}; }}
.island-title {{ color: {r['on_surface']}; font-weight: 700; }}
.island-summary {{ color: {r['on_surface_variant']}; font-size: {round(size * .90, 2):g}px; }}
.island-cover {{ border-radius: 10px; border: 1px solid {rgba(r['primary'], .28)}; padding: 2px; background: {rgba(r['surface_sunken'], .55)}; }}
.island button {{ color: {r['on_surface']}; padding: 4px 8px; border-radius: 999px; font-weight: 600; }}
.island button:hover {{ color: {r['on_primary_container']}; background: {rgba(r['primary'], .20)}; border-radius: 999px; }}
.island button:active {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; border-radius: 999px; }}
.island button.island-play {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; padding: 4px 12px;
    box-shadow: 0 2px 10px {rgba(r['primary'], .38)}; }}
.island button.island-play label {{ color: {r['on_primary']}; }}
.island .pill {{ background: transparent; border-color: transparent; border-radius: {MD3_SHAPE['pill']}px; }}
.island .pill:checked {{ color: {r['on_primary']}; background: {r['primary']}; border-radius: {MD3_SHAPE['pill']}px; }}
.island:not(.expanded) {{ min-height: 30px; padding: 4px 14px; }}
.island:not(.expanded) button {{ min-height: 0; }}
.island label {{ font-weight: 600; letter-spacing: 0.02em; }}
label {{ {outline} }}
progressbar trough, scale trough {{ background: {rgba(r['on_surface'], .18)}; border-radius: 999px; min-height: 8px; margin: 4px 0; }}
progressbar progress, scale highlight {{ background: {r['primary']}; background-image: {grad_bar}; border-radius: 999px; min-height: 8px; }}
scale slider {{ background: #ffffff; border: 2px solid {r['primary']}; border-radius: 999px; min-width: 18px; min-height: 18px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.45); margin: -5px 0; }}
button:focus, .pill:focus, .workspace:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.reduce-motion * {{ transition: none; }}
"""
    return eww


def _render_anyrun(*, bg, css_header, dark_mode, family, opacity, outline, r, rgba, rim_alpha, sheen_a,
                   sheen_b, size, top_edge) -> str:
    """Render ``anyrun.css``."""
    anyrun = css_header + _role_definitions(r) + f"""@define-color bg {bg};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
window {{ background: transparent; }}
box.main {{ background-color: {rgba(r['surface_container_high'], opacity)};
    background-image: linear-gradient(150deg, {rgba(r['primary'], sheen_a)}, {rgba(r['secondary'], sheen_b)} 42%, transparent 78%);
    border: 1px solid {rgba(r['primary'], rim_alpha)};
    border-radius: {MD3_SHAPE['window']}px; padding: 18px; margin: 16px;
    box-shadow: inset 0 1px {top_edge}, 0 24px 60px {r['shadow']}; }}
text {{ color: {r['on_surface']}; background: {rgba(r['surface_sunken'], .72)}; caret-color: {r['primary']};
    padding: 12px 14px; border: 1px solid {rgba(r['primary'], .24)}; border-radius: {MD3_SHAPE['pill']}px; min-height: 34px;
    box-shadow: inset 0 1px 4px {rgba('#000000', .22 if dark_mode else .06)}; }}
text:focus {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 2px {r['primary']}, 0 0 12px {rgba(r['primary'], .24)}; }}
.matches, list, row {{ background: transparent; }}
row {{ color: {r['on_surface']}; border: 1px solid transparent; border-radius: {MD3_SHAPE['button']}px; padding: 8px 10px; margin: 2px 0; }}
row:hover {{ background: {rgba(r['primary'], .12)}; border-color: {rgba(r['primary'], .22)}; }}
row:selected, row:active, .match:selected {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']};
    background-image: linear-gradient(90deg, {rgba(r['primary'], .26)}, {rgba(r['secondary'], .12)});
    border: 1px solid {rgba(r['primary'], .42)}; border-left: 3px solid {r['primary']};
    border-radius: {MD3_SHAPE['button']}px; }}
label {{ {outline} }}
"""
    return anyrun


def _render_alacritty(*, accent, bg, ink, mono, opacity, values) -> str:
    """Render ``alacritty.toml``."""
    alacritty = f'''# Generated by appearance.py; use Control Center.
[window]
opacity = {opacity:g}
[font]
size = {values['mono_size']:g}
[font.normal]
family = {json.dumps(mono)}
[colors.primary]
background = "{bg}"
foreground = "{ink}"
[colors.cursor]
cursor = "{accent}"
text = "{bg}"
[colors.selection]
background = "{accent}"
text = "{bg}"
'''
    return alacritty


RENDERERS = {
    "panel.css": _render_panel,
    "swaync.css": _render_swaync,
    "theme.kdl": _render_kdl,
    "fuzzel.ini": _render_fuzzel,
    "swaylock.conf": _render_lock,
    "eww.css": _render_eww,
    "anyrun.css": _render_anyrun,
    "alacritty.toml": _render_alacritty,
}


@functools.cache
def _renderer_inputs(renderer) -> tuple[str, ...]:
    return tuple(inspect.signature(renderer).parameters)


def render_files(settings: dict, *, base: Path | None = None, layout: str | None = None, bar: str = 'eww') -> dict[str, str]:
    """Pure generation except for reading the existing launcher/lock templates.

    The bar layout is supplied or derived from the already generated bar
    configuration; a rendering function never queries the compositor, so it stays
    testable and cannot spawn a subprocess inside a mocked context.
    """
    context = _render_context(settings, base)
    return {target: renderer(**{key: context[key] for key in _renderer_inputs(renderer)})
            for target, renderer in RENDERERS.items()}


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
            target_mode = 0o600 if path == private else mode
            if old is not None and old == data and mode == target_mode:
                continue
            original[path] = (old, mode)
            staged[path] = _staged(path, data, target_mode)
        for path, staging in staged.items():
            os.replace(staging, path)
            committed.append(path)
            _SETTINGS_CACHE.pop(str(path), None)
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


def apply_settings(settings: dict, *, base: Path | None = None, state_path: Path | None = None, bar: str | None = None) -> dict:
    """Persist a validated complete preference set; UI handles component reloads."""
    values = validate_settings(settings)
    base = Path(base or BASE).resolve()
    state_path = Path(state_path or preferences_path()).absolute()
    directory = base / "theme"
    if directory.is_symlink():
        raise OSError("Theme directory must not be a symlink / 主题目录不能是符号链接")
    directory.mkdir(parents=True, exist_ok=True)
    from ui_assets import render as render_ui_assets
    with _lock(state_path):
        generated = render_files(values, base=base, bar='eww')
        files = {directory / name: text.encode() for name, text in generated.items()}
        files.update({directory / name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
                      for name, value in render_ui_assets(base=base, settings=values).items()})
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
