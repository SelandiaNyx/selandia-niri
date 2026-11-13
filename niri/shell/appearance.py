#!/usr/bin/env python3
"""Desktop appearance preferences and generated component overrides.

This generator only writes the checkout's theme/ assets; application_theme.py
separately synchronizes GTK, Qt and the desktop portal with recorded backups.
"""
from __future__ import annotations

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
    "glacier": {"label": "Obsidian · 黑曜", "background": "#0a0e14", "surface": "#121820",
                "surface_raised": "#1a232e", "surface_sunken": "#0e131a",
                "ink": "#f0f4f8", "muted": "#8b9bb0", "faint": "#3d4b5c",
                "accent": "#4c9eff", "secondary": "#6bb3ff", "accent_hover": "#6bb3ff", "on_accent": "#05101a",
                "border": "#263342", "border_subtle": "rgba(255, 255, 255, 0.06)",
                "success": "#34d399", "warning": "#fbbf24", "error": "#f87171", "danger": "#f87171"},
    "violet": {"label": "Twilight · 暮紫", "background": "#1c142a", "surface": "#30233f",
               "surface_raised": "#3e2e52", "surface_sunken": "#140e1f",
               "ink": "#f7efff", "muted": "#b8a3cc", "faint": "#5e4b70",
               "accent": "#c5a2ff", "secondary": "#f2b1d7", "accent_hover": "#d4baff", "on_accent": "#1c142a",
               "border": "#e7d4ff", "border_subtle": "rgba(255, 255, 255, 0.06)",
               "success": "#b3e8d2", "warning": "#f5d7ae", "error": "#ffacbf", "danger": "#ffacbf"},
    "graphite": {"label": "Graphite · 石墨", "background": "#1a1b1c", "surface": "#2d2f31",
                 "surface_raised": "#3b3e40", "surface_sunken": "#121314",
                 "ink": "#f4f2ec", "muted": "#b2afa6", "faint": "#5a5954",
                 "accent": "#edca8a", "secondary": "#a7d6cd", "accent_hover": "#f3d9a5", "on_accent": "#1a1b1c",
                 "border": "#e7e2d6", "border_subtle": "rgba(255, 255, 255, 0.06)",
                 "success": "#acd8b5", "warning": "#edca8a", "error": "#f4ada8", "danger": "#f4ada8"},
}
LIGHT_PRESETS = {
    "glacier": {"background": "#f4f6f9", "surface": "#ffffff",
                "surface_raised": "#e9edf2", "surface_sunken": "#eceff3",
                "ink": "#0f172a", "muted": "#526071", "faint": "#cbd5e1",
                "accent": "#0969da", "secondary": "#0854b2", "accent_hover": "#0854b2", "on_accent": "#ffffff",
                "border": "#d1d9e2", "border_subtle": "rgba(0, 0, 0, 0.06)",
                "success": "#0d8456", "warning": "#9a6700", "error": "#cf222e", "danger": "#cf222e"},
    "violet": {"background": "#f3eff9", "surface": "#ffffff",
               "surface_raised": "#ece5f5", "surface_sunken": "#f7f5fa",
               "ink": "#2c203a", "muted": "#705d81", "faint": "#c8bdd4",
               "accent": "#7952b7", "secondary": "#a53875", "accent_hover": "#65419e", "on_accent": "#ffffff",
               "border": "#60446e", "border_subtle": "rgba(0, 0, 0, 0.06)",
               "success": "#237657", "warning": "#8e5b12", "error": "#b82749", "danger": "#b82749"},
    "graphite": {"background": "#f3f2ee", "surface": "#ffffff",
                 "surface_raised": "#eae8e2", "surface_sunken": "#f7f6f4",
                 "ink": "#272824", "muted": "#63665f", "faint": "#c4c5be",
                 "accent": "#84621b", "secondary": "#23756a", "accent_hover": "#6c4f14", "on_accent": "#ffffff",
                 "border": "#51564a", "border_subtle": "rgba(0, 0, 0, 0.06)",
                 "success": "#23723a", "warning": "#8c5b08", "error": "#b52d2d", "danger": "#b52d2d"},
}
# Each collection has a light and a dark palette, rather than inverting colors.
for name, label, dark_bg, dark_surface, light_bg, accent, secondary, light_accent, light_secondary in (
    ("aurora", "Aurora · 极光", "#101e23", "#20353b", "#edf7f5", "#92ecd6", "#aebfff", "#116958", "#515cb0"),
    ("ocean", "Ocean · 深海", "#101c30", "#22344f", "#edf4fc", "#8cc8ff", "#80e3ee", "#225f9d", "#116975"),
    ("rose", "Rose Quartz · 蔷薇", "#261923", "#422b39", "#fcf0f4", "#ffbbce", "#dbc3ff", "#9c3e61", "#7450a0"),
    ("amber", "Amber · 琥珀", "#231c15", "#3b3023", "#fbf5e9", "#f3d39b", "#ffc0a3", "#846015", "#995239"),
    ("forest", "Forest · 林间", "#16201a", "#293c30", "#eff6ed", "#b5dcaa", "#e1db9e", "#396b31", "#71661c"),
    ("pearl", "Pearl · 珍珠", "#1c2028", "#303744", "#f4f5fa", "#d6e3ff", "#e7ccf6", "#536d9c", "#865c9e"),
):
    PRESETS[name] = {**PRESETS["glacier"], "label": label, "background": dark_bg,
                     "surface": dark_surface, "accent": accent, "secondary": secondary, "accent_hover": secondary}
    LIGHT_PRESETS[name] = {**LIGHT_PRESETS["glacier"], "background": light_bg,
                           "accent": light_accent, "secondary": light_secondary, "accent_hover": light_secondary}
DEFAULTS = {"preset": "glacier", "color_mode": "dark", "reduced_motion": False, "font": "Adwaita Sans", "font_size": 12,
            "mono_font": "JetBrainsMono Nerd Font", "mono_size": 11.5, "opacity": 0.92,
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


def render_files(settings: dict, *, base: Path | None = None, layout: str | None = None, bar: str = 'eww') -> dict[str, str]:
    """Pure generation except for reading the existing launcher/lock templates.

    The bar layout is supplied or derived from the already generated bar
    configuration; a rendering function never queries the compositor, so it stays
    testable and cannot spawn a subprocess inside a mocked context.
    """
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
    # One coherent MD3 layer.  Structural fallbacks live in shell/style.css and
    # shell/control_center.css; those files never re-declare colour recipes.
    panel = css_header + _role_definitions(r) + aliases + f"""* {{ font-family: {family}; font-size: {size:g}px; }}
.glass-surface {{ color: {r['on_surface']}; background-color: {rgba(r['surface'], opacity)}; background-image: none;
    border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['window']}px;
    box-shadow: inset 0 1px {rgba(r['on_surface'], .08)}, 0 18px 48px {r['shadow']}; }}
.panel-header {{ padding: 18px 20px 14px; border-bottom: 1px solid {r['outline']}; }}
.panel-content {{ padding: 16px 20px 20px; }}
.panel-title {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.3px; }}
.subtitle, .hint, .control-label {{ color: {r['on_surface_variant']}; font-size: {px('body')}; }}
.eyebrow, .section-title, .message-role {{ color: {r['primary']}; font-size: {px('overline')}; font-weight: 700; letter-spacing: 1.8px; }}
.clock {{ color: {r['on_surface']}; font-size: {px('display')}; font-weight: 600; letter-spacing: -.8px; }}
.card, .message, .metric-card, .pulse-card, .application-audio {{ padding: 14px; border: 1px solid {r['outline_variant']};
    background-color: {rgba(r['surface_container'], .72)}; background-image: none; border-radius: {MD3_SHAPE['card']}px;
    box-shadow: inset 0 1px {rgba(r['on_surface'], .06)}, 0 6px 18px {rgba('#000000', .10)}; }}
button {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .58)}; background-image: none;
    border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['button']}px; padding: 8px 12px; box-shadow: none;
    text-shadow: none; transition: background-color 140ms ease-out, border-color 140ms ease-out, color 140ms ease-out; }}
button:hover {{ background-color: {rgba(r['primary'], .12)}; border-color: {rgba(r['primary'], .35)}; border-radius: {MD3_SHAPE['button']}px; }}
button:checked, button:active {{ color: {r['on_primary_container']}; background-color: {r['primary_container']};
    border-color: {rgba(r['primary'], .50)}; border-radius: {MD3_SHAPE['button']}px; }}
button:focus, button:focus-within {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 2px {r['primary']}; }}
button:disabled {{ opacity: .38; }}
button.flat, button.md3-text-button {{ color: {r['primary']}; background-color: transparent;
    background-image: none; border-color: transparent; box-shadow: none; }}
button.flat:hover, button.md3-text-button:hover {{ color: {r['on_primary_container']};
    background-color: {rgba(r['primary'], .10)}; border-color: transparent; }}
button.flat:checked, button.md3-text-button:checked {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']}; border-color: transparent; }}
button.accent-button {{ color: {r['on_primary']}; background-color: {r['primary']}; background-image: none;
    border-color: {r['primary']}; font-weight: 700; }}
button.accent-button:hover {{ background-color: {accent_hover}; border-color: {accent_hover}; }}
button.accent-button:focus {{ box-shadow: inset 0 0 0 2px {r['on_primary']}; }}
button.power-button {{ color: {r['error']}; border-color: {rgba(r['error'], .30)}; background-color: {rgba(r['error'], .08)}; }}
button.power-button:hover {{ color: {r['error']}; border-color: {rgba(r['error'], .55)}; background-color: {r['error_container']}; }}
button.tile {{ padding: 13px 14px; border-radius: {MD3_SHAPE['tile']}px; min-height: 83px; background-color: {rgba(r['surface_container'], .55)}; }}
button.tile.active, button.tile:checked, button.tile:active {{ color: {r['on_primary_container']};
    border-radius: {MD3_SHAPE['tile']}px; background-color: {r['primary_container']}; background-image: none;
    border-color: {rgba(r['primary'], .48)}; box-shadow: inset 0 1px {rgba(r['on_primary_container'], .10)}; }}
.tile-icon {{ color: {r['on_surface_variant']}; font-size: {type_sizes['title_large']:g}px; }}
.active .tile-icon, .active .tile-state {{ color: {r['on_primary_container']}; }}
.tile-title {{ color: {r['on_surface']}; font-size: {px('title_medium')}; font-weight: 600; }}
.tile-state {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; }}
button.small-button {{ font-size: {px('caption')}; padding: 5px 8px; border-radius: {MD3_SHAPE['button']}px; }}
button.tool-button {{ padding: 9px 7px; font-size: {px('caption')}; }}
button.close-button {{ min-width: 30px; min-height: 30px; padding: 0; border-radius: {MD3_SHAPE['badge']}px;
    color: {r['on_surface_variant']}; background-color: transparent; border-color: transparent; font-size: {type_sizes['title_large']:g}px; }}
button.close-button:hover {{ color: {r['on_surface']}; background-color: {rgba(r['on_surface'], .08)}; border-color: {r['outline']}; }}
button.close-button:checked, button.close-button:active {{ border-radius: {MD3_SHAPE['badge']}px; }}
.control-tabs {{ padding: 4px; border: 1px solid {r['outline_variant']}; border-radius: {MD3_SHAPE['pill']}px;
    background-color: {rgba(r['surface_container_low'], .65)}; }}
.control-tabs button {{ color: {r['on_surface_variant']}; background: transparent; border-color: transparent;
    border-radius: {MD3_SHAPE['badge']}px; box-shadow: none; padding: 6px 4px; font-size: {px('caption')}; }}
.control-tabs button:hover {{ color: {r['on_surface']}; background-color: {rgba(r['primary'], .08)}; }}
.control-tabs button:checked, .control-tabs button:active, .control-tabs button:selected {{ color: {r['on_primary_container']};
    border-radius: {MD3_SHAPE['badge']}px; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .34)}; }}
.scale, scale {{ padding: 6px 2px; }}
scale trough {{ min-height: 4px; border: none; border-radius: {MD3_SHAPE['badge']}px; background-color: {rgba(r['surface_sunken'], .85)}; }}
scale highlight {{ min-height: 4px; border: none; border-radius: {MD3_SHAPE['badge']}px; background-color: {r['primary']}; background-image: none; }}
scale slider {{ min-width: 14px; min-height: 14px; margin: -4px; border: 1px solid {rgba(r['on_surface'], .65)};
    border-radius: {MD3_SHAPE['badge']}px; background-color: {r['on_surface']}; background-image: none; box-shadow: none; }}
scale:focus trough {{ outline: none; box-shadow: 0 0 0 2px {rgba(r['primary'], .45)}; }}
scale:disabled {{ opacity: .38; }}
progressbar trough, .metric-progress trough {{ min-height: 4px; border: none; border-radius: {MD3_SHAPE['badge']}px;
    background-color: {rgba(r['surface_sunken'], .85)}; }}
progressbar progress, .metric-progress progress {{ min-height: 4px; border: none; border-radius: {MD3_SHAPE['badge']}px;
    background-color: {r['primary']}; background-image: none; }}
.metric-value, .network-rate {{ color: {r['primary']}; font-family: {mono_family}; font-weight: 600;
    letter-spacing: -.3px; font-feature-settings: "tnum 1, cv01 1"; }}
.metric-value {{ font-size: {type_sizes['headline']:g}px; }}
.network-rate {{ font-size: {type_sizes['title_large']:g}px; }}
entry, spinbutton {{ color: {r['on_surface']}; caret-color: {r['primary']}; border: 1px solid {r['outline']};
    border-radius: {MD3_SHAPE['pill']}px; padding: 9px 12px; background-color: {rgba(r['surface_sunken'], .55)}; box-shadow: none; }}
entry:focus, spinbutton:focus {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 1px {rgba(r['primary'], .55)}; }}
entry selection, textview text selection {{ background-color: {r['primary_container']}; color: {r['on_primary_container']}; }}
spinbutton button {{ border: none; background: transparent; border-radius: {MD3_SHAPE['button']}px; padding: 5px 8px; }}
menu, tooltip {{ color: {r['on_surface']}; background-color: {r['surface_container_high']}; border: 1px solid {r['outline']};
    border-radius: {MD3_SHAPE['button']}px; padding: 5px; }}
menuitem {{ padding: 8px; border-radius: {MD3_SHAPE['button']}px; }}
menuitem:hover {{ background-color: {rgba(r['primary'], .12)}; }}
list.wallpaper-list {{ background: transparent; color: {r['on_surface']}; }}
list.wallpaper-list row {{ border: 1px solid {r['outline_variant']}; border-radius: {MD3_SHAPE['button']}px;
    margin: 2px 0; background: {rgba(r['surface_container'], .45)}; color: {r['on_surface']}; padding: 6px 8px; }}
list.wallpaper-list row:hover {{ background: {rgba(r['primary'], .08)}; }}
list.wallpaper-list row:selected, list.wallpaper-list row:active {{ border-radius: {MD3_SHAPE['button']}px;
    background: {r['primary_container']}; border-color: {rgba(r['primary'], .48)}; color: {r['on_primary_container']}; }}
flowbox.wallpaper-grid {{ background: transparent; padding: 4px; }}
flowbox.wallpaper-grid flowboxchild, .wallpaper-tile {{ padding: 10px; border: 1px solid {r['outline_variant']};
    border-radius: {MD3_SHAPE['card']}px; background-color: {rgba(r['surface_container'], .45)}; box-shadow: none; }}
flowbox.wallpaper-grid flowboxchild:hover, .wallpaper-tile:hover {{ background-color: {rgba(r['primary'], .08)}; }}
flowbox.wallpaper-grid flowboxchild:selected, .wallpaper-tile:selected {{ border-radius: {MD3_SHAPE['card']}px; background-image: none;
    border-color: {rgba(r['primary'], .55)}; background-color: {r['primary_container']}; }}
.audio-stream-row {{ padding: 12px; border: 1px solid {r['outline_variant']}; border-radius: {MD3_SHAPE['card']}px;
    background-color: {rgba(r['surface_container'], .45)}; }}
.audio-stream-row button:checked {{ border-radius: {MD3_SHAPE['button']}px; background-color: {r['primary_container']};
    border-color: {rgba(r['primary'], .48)}; color: {r['on_primary_container']}; }}
.system-inventory {{ color: {r['on_surface']}; font-size: {size:g}px; }}
label.system-summary {{ font-family: {mono_family}; color: {r['on_surface']}; }}
.keycap {{ font-family: {mono_family}; font-size: {px('caption')}; color: {r['primary']};
    background-color: {rgba(r['primary'], .08)}; border: 1px solid {rgba(r['primary'], .22)};
    border-radius: {MD3_SHAPE['button']}px; padding: 5px 8px; box-shadow: none; text-shadow: none; }}
.shortcut-description, .welcome-copy, .message-text {{ color: {r['on_surface']}; font-size: {px('body')}; }}
.user-message {{ background-color: {r['primary_container']}; }}
.assistant-message {{ background-color: {rgba(r['surface_container_high'], .72)}; }}
.composer {{ padding: 10px; border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['card']}px;
    background-color: {rgba(r['surface_container_low'], .55)}; box-shadow: none; }}
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
scrollbar slider {{ background-color: {rgba(r['on_surface'], .22)}; border-radius: {MD3_SHAPE['badge']}px; }}
scrollbar slider:hover {{ background-color: {rgba(r['on_surface'], .40)}; }}
scrollbar slider:active {{ background-color: {r['primary']}; }}
scrolledwindow, viewport {{ background: transparent; border: none; }}
row:focus {{ outline: none; box-shadow: inset 0 0 0 2px {rgba(r['primary'], .85)}; }}
calendar {{ background-color: transparent; color: {r['on_surface']}; border: 1px solid {r['outline_variant']};
    border-radius: {MD3_SHAPE['card']}px; padding: 10px 12px; }}
calendar:selected {{ background-color: {r['primary']}; color: {r['on_primary']}; }}
.glass-calendar {{ background-color: {rgba(r['surface_container'], .55)}; border-color: {r['outline_variant']}; }}
.calendar-page {{ padding: 12px; }}
.calendar-page .calendar-card, .calendar-page .calendar-footer {{ padding: 12px; }}
.calendar-card .glass-calendar {{ background: transparent; border: none; padding: 0; }}
.calendar-page.calendar-narrow .glass-calendar .calendar-title {{ font-size: {px('title_medium')}; }}
.calendar-page.calendar-narrow .glass-calendar button.calendar-day-btn {{ min-width: 0; padding: 4px 0; }}
.calendar-date {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.2px; }}
button.calendar-primary {{ color: {r['on_primary']}; background-color: {r['primary']};
    border: 1px solid {r['primary']}; font-weight: 700; min-height: 34px; padding: 0 16px;
    border-radius: 999px; box-shadow: 0 1px 3px {r['shadow']}; }}
button.calendar-primary:hover {{ color: {r['on_primary']}; background-color: {r['primary']};
    border-color: {r['primary']}; box-shadow: 0 2px 6px {rgba(r['primary'], .35)}; }}
button.calendar-primary:checked, button.calendar-primary:active {{ color: {r['on_primary']};
    background-color: {r['primary']}; border-color: {r['primary']}; }}
button.calendar-secondary {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .65)};
    border: 1px solid {r['outline']}; font-weight: 600; min-height: 34px; padding: 0 16px;
    border-radius: 999px; }}
button.calendar-secondary:hover {{ color: {r['on_surface']}; background-color: {rgba(r['primary'], .14)};
    border-color: {r['primary']}; }}
button.calendar-secondary:checked, button.calendar-secondary:active {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .50)}; }}
.glass-calendar .calendar-header {{ color: {r['on_surface']}; border-bottom: 1px solid {r['outline_variant']};
    padding-bottom: 6px; margin-bottom: 4px; }}
.glass-calendar .calendar-title {{ color: {r['on_surface']}; font-size: {round(type_sizes['title_large'] * 1.31, 2):g}px; font-weight: 700; letter-spacing: -.2px; }}
.glass-calendar .calendar-week-num {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; padding: 0 4px; }}
.glass-calendar .calendar-empty-cell {{ color: transparent; background-color: transparent; }}
.glass-calendar .calendar-weekday-header, .glass-calendar .calendar-week-header {{ color: {r['primary']};
    font-size: {round(type_sizes['caption'] * 1.16, 2):g}px; font-weight: 700; padding: 4px 0; }}
.glass-calendar button.calendar-nav-btn {{ color: {r['on_surface']}; background: {rgba(r['surface_container_high'], .55)};
    border: 1px solid {r['outline_variant']}; box-shadow: none; padding: 2px 4px; min-width: 32px;
    min-height: 32px; border-radius: 999px; }}
.glass-calendar button.calendar-nav-btn:checked, .glass-calendar button.calendar-nav-btn:active {{ color: {r['on_primary']};
    background-color: {r['primary']}; border-color: {r['primary']}; }}
.glass-calendar button.calendar-nav-btn:hover {{ color: {r['primary']}; background-color: {rgba(r['primary'], .10)}; }}
.glass-calendar button.calendar-day-btn {{ background: transparent; border: 1px solid transparent; box-shadow: none;
    padding: 4px 2px; min-width: 32px; min-height: 30px; border-radius: 999px;
    font-size: {round(type_sizes['body'] * 1.05, 2):g}px; font-weight: 500; color: {r['on_surface']}; }}
.glass-calendar button.calendar-day-btn:hover {{ background-color: {rgba(r['primary'], .12)}; border-color: {rgba(r['primary'], .30)}; }}
.glass-calendar button.calendar-day-btn.today {{ border-color: {r['primary']}; color: {r['on_surface']};
    background-color: {rgba(r['primary'], .15)}; font-weight: 700; }}
.glass-calendar button.calendar-day-btn.selected {{ background-image: none; background-color: {r['primary']};
    border-color: {r['primary']}; color: {r['on_primary']}; font-weight: 700;
    box-shadow: 0 1px 4px {r['shadow']}; }}
.glass-calendar button.calendar-day-btn.today.selected {{ color: {r['on_primary']}; background-color: {r['primary']};
    border: 2px solid {r['on_primary']}; }}
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
    border-color: {rgba(r['primary'], .18)};
    box-shadow: inset 0 1px {rgba(r['on_surface'], .10)}, inset 0 -1px {rgba(r['primary'], .10)}, 0 28px 72px {r['shadow']};
}}
window.glass-window.power-menu-window .glass-surface {{
    border-color: {rgba(r['primary'], .18)};
    box-shadow: inset 0 1px {rgba(r['on_surface'], .10)}, 0 18px 48px {r['shadow']};
}}
"""
    swaync = '@import "../swaync/style.css";\n' + css_header + _role_definitions(r) + f"""@define-color bg {bg};
@define-color cc-bg {rgba(r['surface_container_low'], opacity)};
@define-color noti-bg {rgba(r['surface_container_high'], .90)};
@define-color noti-border-color {r['outline']};
@define-color text-color {r['on_surface']};
@define-color text-color-disabled {r['on_surface_variant']};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
.control-center {{ background-color: {rgba(r['surface_container_low'], opacity)}; background-image: none; color: {r['on_surface']};
    border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['window']}px; padding: 16px;
    box-shadow: inset 0 1px {rgba(r['on_surface'], .08)}, 0 18px 48px {r['shadow']}; }}
.notification {{ background-color: {rgba(r['surface_container_high'], .90)}; background-image: none;
    border: 1px solid {r['outline_variant']}; border-radius: {MD3_SHAPE['card']}px; padding: 6px;
    box-shadow: inset 0 1px {rgba(r['on_surface'], .06)}; }}
.notification:hover {{ background-color: {rgba(r['surface_container_highest'], .94)}; border-color: {r['outline']}; }}
.summary, .widget-title {{ color: {r['on_surface']}; font-weight: 600; }}
.body, .widget-dnd {{ color: {r['on_surface']}; }}
.time, .app-name {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; }}
.notification-row .notification-background .notification.critical {{ border-color: {r['error']}; background-color: {r['error_container']}; }}
.notification-group:focus .notification, .notification-row:focus .notification,
.notification-row:focus-within .notification {{ outline: 2px solid {r['primary']}; outline-offset: -2px; }}
.widget-dnd {{ background-color: {rgba(r['surface_container'], .65)}; border: 1px solid {r['outline_variant']};
    border-radius: {MD3_SHAPE['pill']}px; }}
button {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .70)};
    border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['button']}px; box-shadow: none; text-shadow: none;
    transition: background-color 140ms ease-out, border-color 140ms ease-out; }}
button:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .35)}; }}
button:checked, button:active {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {r['primary']}; }}
button:disabled {{ opacity: .38; }}
button:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
button.suggested-action {{ background-color: {r['primary']}; color: {r['on_primary']}; border-color: {r['primary']}; font-weight: 600; }}
.notification-default-action {{ background: transparent; }}
.close-button {{ background-color: {rgba(r['on_surface'], .08)}; border-radius: {MD3_SHAPE['badge']}px; }}
switch {{ background-color: {rgba(r['surface_sunken'], .85)}; border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['badge']}px; }}
switch:checked {{ background-color: {r['primary']}; background-image: none; }}
switch slider {{ background-color: {r['on_primary']}; border-radius: {MD3_SHAPE['badge']}px; }}
scrollbar slider {{ background-color: {rgba(r['on_surface'], .22)}; border-radius: {MD3_SHAPE['badge']}px; }}
"""
    kdl = f'''// Generated palette overrides. Keep layout preferences in conf/appearance.kdl.
layout {{
    struts {{ top 0; }}
    background-color "{bg}"
    focus-ring {{
        active-color "{accent}"
        inactive-color "{border}66"
        urgent-color "{danger}"
        width 2
    }}
    tab-indicator {{
        active-color "{accent}"
        inactive-color "{ink}22"
    }}
}}
overview {{ backdrop-color "{bg}"; }}
// Low-opacity panel text uses a crisp outline and a noise-free blur surface.
window-rule {{
    match app-id=r#"^org\\.selandia\\.Glass$"# title="^Selandia · control$"
    background-effect {{ noise {0 if opacity < .40 else .02}; }}
    shadow {{ on; softness 32; spread 1; offset x=0 y=8; color "{bg}66"; }}
}}
layer-rule {{
    match namespace="^selandia-.*$"
    background-effect {{ noise {0 if opacity < .40 else .02}; }}
}}
layer-rule {{
    match namespace="^(launcher|selandia-.*)$"
    shadow {{ on; softness 38; spread 2; offset x=0 y=10; color "{bg}66"; }}
}}
layer-rule {{
    match namespace="^(selandia-bar-.*|selandia-island)$"
    shadow {{ off; }}
    background-effect {{ blur false; xray false; saturation 1.0; noise 0; }}
}}
'''
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
        "border": _alpha(border, .8)})
    fuzzel = _replace_ini(fuzzel, "border", {"radius": MD3_SHAPE["window"],
                                              "selection-radius": MD3_SHAPE["button"]})
    lock = _replace_ini((base / "swaylock/config").read_text(), "", {"color": bg[1:], "font": font,
        "font-size": font_scale.whole_points(font_scale.lock_pixels(size)), "inside-color": _alpha(bg, max(.9, opacity)), "ring-color": border[1:],
        "text-color": ink[1:], "key-hl-color": accent[1:], "bs-hl-color": p["warning"][1:],
        "inside-ver-color": _alpha(surface, .94), "ring-ver-color": accent[1:], "text-ver-color": ink[1:],
        "inside-wrong-color": _alpha(surface, .94), "ring-wrong-color": danger[1:], "text-wrong-color": ink[1:]})
    # Rust frontends consume the same generated roles as GTK; only their
    # selector vocabulary differs.  Bar geometry and timing stay owned by
    # bar_backend.py, so padding, heights and animation hooks are unchanged.
    outline = "text-shadow: -1px 0 " + bg + ", 1px 0 " + bg + ", 0 -1px " + bg + ", 0 1px " + bg + ";" if opacity < .40 else ""
    eww = css_header + _role_definitions(r) + f"""@define-color bg {bg};
@define-color surface {surface};
@define-color accent {r['primary']};
@define-color on_accent {r['on_primary']};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
window.background, window, .background {{ background-color: rgba(0, 0, 0, 0); background-image: none; border: none; box-shadow: none; }}
.bar-host {{ background-color: rgba(0, 0, 0, 0); background-image: none; border: none; box-shadow: none; }}
.segment {{ background: {rgba(r['surface_container_high'], opacity)}; border: 1px solid {r['outline']}; border-radius: 22px; padding: 2px 10px; box-shadow: inset 0 1px {rgba(r['on_surface'], .12)}; }}
button {{ background: transparent; border: none; box-shadow: none; }}
.pill {{ color: {r['on_surface']}; background: transparent; border: none; border-radius: {MD3_SHAPE['pill']}px; padding: 3px 8px; transition: background-color 140ms ease-out, color 140ms ease-out; }}
.segment .pill * {{ background-color: transparent; background-image: none; box-shadow: none; }}
.segment .pill, .segment .workspace {{ background: transparent; border: none; }}
.segment .pill.clock, .segment .pill.resources, .segment .pill.application {{ background: {rgba(r['surface_container_low'], .65)}; border-radius: 999px; padding: 3px 10px; margin: 0 2px; }}
/* 状态规则必须与上面 3 类选择器同优先级，否则底色被基础规则压住、只有文字变色。 */
.segment .pill.clock:hover, .segment .pill.resources:hover, .segment .pill.application:hover {{ color: {r['on_primary_container']}; background: {rgba(r['primary'], .18)}; }}
.segment .pill.clock:active, .segment .pill.clock:checked,
.segment .pill.resources:active, .segment .pill.resources:checked,
.segment .pill.application:active, .segment .pill.application:checked {{ color: {r['on_primary']}; background: {r['primary']}; }}
.segment .pill.clock:focus, .segment .pill.resources:focus, .segment .pill.application:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.workspace {{ color: {r['on_surface_variant']}; background: transparent; border: none; border-radius: 999px; padding: 3px 8px; min-width: 20px; font-weight: 500; transition: background-color 140ms ease-out, color 140ms ease-out; }}
.workspace:hover, .pill:hover {{ color: {r['on_primary_container']}; background: {rgba(r['primary'], .18)}; border-radius: 999px; }}
/* 工作区持久选中可以更宽；普通 pill 的按压/选中反馈只换配色，padding、字重等几何保持基态。 */
.workspace.active, .workspace:active {{ color: {r['on_primary']}; background: {r['primary']}; border-radius: 999px; font-weight: 700; min-width: 32px; padding: 3px 12px; box-shadow: 0 1px 4px {rgba(r['primary'], .40)}; }}
.pill:active, .pill:checked {{ color: {r['on_primary']}; background: {r['primary']}; }}
.workspace.active label, .workspace:active label, .pill:active label, .pill:checked label {{ color: {r['on_primary']}; }}
.compact .pill, .compact .workspace {{ padding: 2px 5px; }}
/* Side capsules keep their horizontal padding; only height and shape change. */
.segment .pill, .segment .workspace,
.segment .pill:hover, .segment .pill:active, .segment .pill:checked,
.segment .workspace:hover, .segment .workspace:active, .segment .workspace.active {{ border-radius: 999px; }}
.separator {{ background-color: {r['outline_variant']}; min-width: 1px; margin: 6px 4px; }}
.resource-row {{ background: transparent; }}
.resource {{ padding: 0 4px; }}
.resource-icon {{ color: {r['primary']}; font-size: {round(size * .80, 2):g}px; font-weight: 700; margin-right: 2px; }}
.resource-value {{ color: {r['on_surface']}; font-family: {mono_family}; font-size: {round(size * .90, 2):g}px; font-weight: 600; font-feature-settings: "tnum 1, cv01 1"; }}
.clock-time {{ color: {r['on_surface']}; font-family: {mono_family}; font-size: {round(size * 1.25, 2):g}px; font-weight: 700; letter-spacing: -0.4px; font-feature-settings: "tnum 1, cv01 1"; }}
.clock-date {{ color: {r['on_surface_variant']}; font-size: {round(size * .75, 2):g}px; font-weight: 600; letter-spacing: .06em; margin-top: 1px; }}
.island {{ background: {rgba(r['surface_container_highest'], opacity)}; border: 1px solid {r['outline']}; border-radius: 22px; padding: 8px 12px; box-shadow: inset 0 1px {rgba(r['on_surface'], .12)}; }}
.island button {{ color: {r['on_surface']}; padding: 3px 6px; border-radius: 999px; font-weight: 500; }}
.island button:hover {{ color: {r['on_primary_container']}; background: {rgba(r['primary'], .14)}; border-radius: 999px; }}
.island button:active {{ color: {r['on_primary']}; background: {r['primary']}; border-radius: 999px; }}
.island .pill {{ background: transparent; border-color: transparent; border-radius: {MD3_SHAPE['pill']}px; }}
.island .pill:checked {{ color: {r['on_primary']}; background: {r['primary']}; border-radius: {MD3_SHAPE['pill']}px; }}
.island:not(.expanded) {{ min-height: 30px; padding: 4px 14px; }}
.island:not(.expanded) button {{ min-height: 0; }}
.island label {{ font-weight: 600; letter-spacing: 0.02em; }}
label {{ {outline} }}
progressbar trough, scale trough {{ background: {rgba(r['on_surface'], .20)}; border-radius: 999px; min-height: 8px; margin: 4px 0; }}
progressbar progress, scale highlight {{ background: {r['primary']}; border-radius: 999px; min-height: 8px; }}
scale slider {{ background: {r['on_primary']}; border: 2px solid {r['primary']}; border-radius: 999px; min-width: 20px; min-height: 20px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45); margin: -6px 0; }}
button:focus, .pill:focus, .workspace:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.reduce-motion * {{ transition: none; }}
"""
    anyrun = css_header + _role_definitions(r) + f"""@define-color bg {bg};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
window {{ background: transparent; }}
box.main {{ background: {rgba(r['surface_container_high'], opacity)}; border: 1px solid {r['outline']};
    border-radius: {MD3_SHAPE['window']}px; padding: 16px; margin: 16px;
    box-shadow: inset 0 1px {rgba(r['on_surface'], .08)}, 0 18px 48px {r['shadow']}; }}
text {{ color: {r['on_surface']}; background: {rgba(r['surface_sunken'], .75)}; caret-color: {r['primary']};
    padding: 10px; border: 1px solid {r['outline']}; border-radius: {MD3_SHAPE['pill']}px; min-height: 32px; }}
text:focus {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.matches, list, row {{ background: transparent; }}
row {{ color: {r['on_surface']}; border-radius: {MD3_SHAPE['button']}px; padding: 6px; }}
row:hover {{ background: {rgba(r['primary'], .08)}; }}
row:selected, row:active, .match:selected {{ color: {r['on_primary_container']}; background: {r['primary_container']};
    border-left: 3px solid {r['primary']}; border-radius: {MD3_SHAPE['button']}px; }}
label {{ {outline} }}
"""
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
    return {"panel.css": panel, "swaync.css": swaync, "theme.kdl": kdl,
            "fuzzel.ini": fuzzel, "swaylock.conf": lock,
            "eww.css": eww, "anyrun.css": anyrun, "alacritty.toml": alacritty}


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
