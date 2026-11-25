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
from i18n import tr, tr_legacy

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
# Warm collections carry their own warm ink/muted tones instead of cool blue-grey.
for name, label, dark_bg, dark_surface, dark_raised, dark_sunken, dark_border, dark_ink, dark_muted, light_bg, light_surface, light_raised, accent, secondary, light_accent, light_secondary in (
    ("aurora", "Aurora · 极光翡翠", "#101e24", "#182d35", "#223d48", "#0b151a", "#5f96a3", "#eaf5f7", "#b5d1d8", "#eaf4f3", "#f6fbfa", "#dcece9", "#5eead4", "#60a5fa", "#0d7a69", "#2563eb"),
    ("ocean", "Ocean · 蔚蓝深海", "#101b2d", "#182843", "#22385c", "#0b1320", "#6489bb", "#ecf3fc", "#b7cae2", "#ebf2fb", "#f7faff", "#dce8f8", "#38bdf8", "#2dd4bf", "#0369a1", "#0e7490"),
    ("rose", "Rose Quartz · 晨曦蔷薇", "#231620", "#33202f", "#452d40", "#180f16", "#b27ba6", "#f5eaf0", "#cfb5c4", "#f8edf2", "#fdf7fa", "#f1dde6", "#fda4af", "#d8b4fe", "#be185d", "#7e22ce"),
    ("amber", "Amber · 落日琥珀", "#211912", "#31251b", "#423325", "#17110c", "#b0906c", "#f5ede2", "#cebeaa", "#f7f0e4", "#fcf8f1", "#efe3cf", "#fcd34d", "#fb923c", "#b45309", "#c2410c"),
    ("forest", "Forest · 幽林清露", "#142019", "#1e3025", "#294032", "#0e1712", "#6e9b80", "#ebf4ee", "#b4ccb9", "#edf5ee", "#f7fbf7", "#deeadd", "#6ee7b7", "#bef264", "#15803d", "#65a30d"),
    ("pearl", "Pearl · 虹彩珍珠", "#191d2a", "#252b3e", "#323b52", "#12151f", "#8491b5", "#f0f2fa", "#bfc6dc", "#f1f3fa", "#fafbfe", "#e4e8f6", "#93c5fd", "#f0abfc", "#3b5bdb", "#9c36b5"),
):
    PRESETS[name] = {**PRESETS["glacier"], "label": label, "background": dark_bg,
                     "surface": dark_surface, "surface_raised": dark_raised, "surface_sunken": dark_sunken,
                     "ink": dark_ink, "muted": dark_muted,
                     "border": dark_border, "accent": accent, "secondary": secondary, "accent_hover": secondary}
    LIGHT_PRESETS[name] = {**LIGHT_PRESETS["glacier"], "background": light_bg, "surface": light_surface,
                           "surface_raised": light_raised, "surface_sunken": light_raised,
                           "accent": light_accent, "secondary": light_secondary, "accent_hover": light_secondary}
# Gemini Starlight & Sakura Nyan anime collections: high-clarity eye-care MD3
# tonal surfaces (11.5-13.8:1 dark anti-halation contrast, warm paper light
# surfaces without #ffffff glare) plus saturated dual-tone anime accents.
ANIME_PRESETS = {
    "gemini": (("Gemini Starlight", "星辉双子"),
               {"background": "#1b1728", "surface": "#241f35", "surface_raised": "#312a47", "surface_sunken": "#13101d",
                "ink": "#efeaf8", "muted": "#cfc5e4", "faint": "#5a5078", "accent": "#9da8ff", "secondary": "#ff8dc7",
                "accent_hover": "#b8c0ff", "on_accent": "#16112b", "border": "#968ec9",
                "border_subtle": "rgba(239, 234, 248, 0.10)", "success": "#7ce0be", "warning": "#ffd878",
                "error": "#ff8aa0", "danger": "#ff8aa0"},
               {"background": "#f4f1fa", "surface": "#fbf9fe", "surface_raised": "#e7e1f7", "surface_sunken": "#ece7f8",
                "ink": "#1f1833", "muted": "#4b4166", "faint": "#cbc2e4", "accent": "#4d46b8", "secondary": "#b51f6e",
                "accent_hover": "#3d379c", "on_accent": "#fbf9fe", "border": "#9990cc",
                "border_subtle": "rgba(31, 24, 51, 0.08)", "success": "#0b7a4b", "warning": "#9a5b00",
                "error": "#b8143b", "danger": "#b8143b"}),
    "sakura": (("Sakura Nyan", "樱花喵"),
               {"background": "#201720", "surface": "#2b202b", "surface_raised": "#3a2b3a", "surface_sunken": "#160f16",
                "ink": "#f5e9ef", "muted": "#d9c2ce", "faint": "#634b5c", "accent": "#ff8fbf", "secondary": "#8fd3ff",
                "accent_hover": "#ffb3d4", "on_accent": "#340a1e", "border": "#c98aa8",
                "border_subtle": "rgba(245, 233, 239, 0.10)", "success": "#7ce0be", "warning": "#ffd479",
                "error": "#ff8a9a", "danger": "#ff8a9a"},
               {"background": "#f8eef2", "surface": "#fff8fa", "surface_raised": "#f2dde6", "surface_sunken": "#f3e3ea",
                "ink": "#2a1421", "muted": "#5a394b", "faint": "#e0bdd0", "accent": "#b81858", "secondary": "#026aa8",
                "accent_hover": "#991248", "on_accent": "#fff8fa", "border": "#d48cad",
                "border_subtle": "rgba(42, 20, 33, 0.08)", "success": "#0b7a4b", "warning": "#9a5b00",
                "error": "#b8143b", "danger": "#b8143b"}),
    "sora": (("Sora Nyan", "晴空喵"),
             {"background": "#151d2b", "surface": "#1d283b", "surface_raised": "#27364f", "surface_sunken": "#0e141f",
              "ink": "#ebf2fb", "muted": "#c4d5ea", "faint": "#475c7a", "accent": "#7cc8ff", "secondary": "#ffa6c9",
              "accent_hover": "#a6dbff", "on_accent": "#071f36", "border": "#7f9fc9",
              "border_subtle": "rgba(235, 242, 251, 0.10)", "success": "#7ce0be", "warning": "#ffd479",
              "error": "#ff8a9a", "danger": "#ff8a9a"},
             {"background": "#eef4fb", "surface": "#f9fcff", "surface_raised": "#dfeafa", "surface_sunken": "#e5eef9",
              "ink": "#101f33", "muted": "#364d68", "faint": "#b8cce5", "accent": "#0a5ea8", "secondary": "#b81858",
              "accent_hover": "#084c8a", "on_accent": "#f9fcff", "border": "#8aadcf",
              "border_subtle": "rgba(16, 31, 51, 0.08)", "success": "#0b7a4b", "warning": "#9a5b00",
              "error": "#b8143b", "danger": "#b8143b"}),
    "lavender": (("Lavender Nyan", "薰衣草喵"),
                 {"background": "#1b1726", "surface": "#262036", "surface_raised": "#332b48", "surface_sunken": "#120f1b",
                  "ink": "#f1ebf9", "muted": "#d3c6e8", "faint": "#5a4d7d", "accent": "#c7a6ff", "secondary": "#ffb0d0",
                  "accent_hover": "#dac4ff", "on_accent": "#231045", "border": "#a48bcc",
                  "border_subtle": "rgba(241, 235, 249, 0.10)", "success": "#7ce0be", "warning": "#ffd479",
                  "error": "#ff8a9a", "danger": "#ff8a9a"},
                 {"background": "#f3effa", "surface": "#fbf9ff", "surface_raised": "#e7def9", "surface_sunken": "#ece4fa",
                  "ink": "#211636", "muted": "#4b3d6b", "faint": "#cec1ea", "accent": "#643bba", "secondary": "#b21558",
                  "accent_hover": "#512d9c", "on_accent": "#fbf9ff", "border": "#a692d4",
                  "border_subtle": "rgba(33, 22, 54, 0.08)", "success": "#0b7a4b", "warning": "#9a5b00",
                  "error": "#b8143b", "danger": "#b8143b"}),
    "mint": (("Mint Nyan", "薄荷喵"),
             {"background": "#14201c", "surface": "#1c2d27", "surface_raised": "#263c35", "surface_sunken": "#0e1714",
              "ink": "#e9f5f0", "muted": "#c2dfd4", "faint": "#43695b", "accent": "#7fe8c4", "secondary": "#ffb38a",
              "accent_hover": "#a6f0d6", "on_accent": "#07261c", "border": "#79b8a1",
              "border_subtle": "rgba(233, 245, 240, 0.10)", "success": "#7ce0be", "warning": "#ffd479",
              "error": "#ff8a9a", "danger": "#ff8a9a"},
             {"background": "#edf6f2", "surface": "#f8fcfa", "surface_raised": "#daeee5", "surface_sunken": "#e2f2eb",
              "ink": "#0e261d", "muted": "#315044", "faint": "#b5dbcc", "accent": "#0a7453", "secondary": "#ad450e",
              "accent_hover": "#085e43", "on_accent": "#f8fcfa", "border": "#82bfa8",
              "border_subtle": "rgba(14, 38, 29, 0.08)", "success": "#0b7a4b", "warning": "#9a5b00",
              "error": "#b8143b", "danger": "#b8143b"}),
}
for name, ((label_en, label_zh), dark_values, light_values) in ANIME_PRESETS.items():
    PRESETS[name] = {"label_en": label_en, "label_zh": label_zh, "label": label_en, **dark_values}
    LIGHT_PRESETS[name] = dict(light_values)
# The anime collections lead the picker; the earlier glass collections follow.
PRESETS = {name: PRESETS[name] for name in (*ANIME_PRESETS, *(key for key in PRESETS if key not in ANIME_PRESETS))}
LIGHT_PRESETS = {name: LIGHT_PRESETS[name] for name in PRESETS}

EYE_CARE_MODES = {
    "off": ("Standard vivid", "标准鲜明"),
    "comfort": ("Eye-care comfort", "舒目护眼"),
    "night_warm": ("Night warm paper", "夜间暖纸"),
}
MASCOT_SKINS = {
    "gemini": ("Gemini Starlight", "经典全能 Gemini"),
    "antigravity": ("Antigravity Balloon", "Antigravity 气球"),
    "engineer": ("Cyber Engineer", "赛博工程师"),
    "obsidian": ("Obsidian Prism", "黑曜棱镜"),
}


def preset_label(name: str) -> str:
    """Return the localized display label for a theme preset."""
    preset = PRESETS[name]
    if "label_en" in preset and "label_zh" in preset:
        return tr(preset["label_en"], preset["label_zh"])
    return tr_legacy(preset["label"])


def mascot_asset(skin: str | None = None, variant: str = "full", *, base: Path | None = None) -> Path:
    """Resolve the active Gemini mascot artwork file for a chosen skin and pose."""
    root = Path(base or BASE) / "assets/anime"
    chosen = skin if skin in MASCOT_SKINS else load_settings().get("mascot", "gemini")
    if variant == "full":
        candidate = root / f"mascot-{chosen}.png"
        return candidate if candidate.is_file() else root / "mascot-full.png"
    if variant == "avatar":
        candidate = root / f"mascot-avatar-{chosen}.png"
        return candidate if candidate.is_file() else root / "mascot-avatar.png"
    if variant == "avatar64":
        if chosen == "gemini":
            return root / "mascot-avatar-64.png"
        candidate = root / f"mascot-avatar-{chosen}.png"
        return candidate if candidate.is_file() else root / "mascot-avatar-64.png"
    return root / f"mascot-{variant}.png"


DEFAULTS = {"preset": "gemini", "color_mode": "dark", "eye_care": "comfort", "mascot": "gemini",
            "reduced_motion": False, "font": "Adwaita Sans", "font_size": 14,
            "mono_font": "JetBrainsMono Nerd Font", "mono_size": 11.5, "opacity": 0.95,
            "wallpaper_colors": False, "wallpaper_seed": None}
# Text roles must clear this ratio on every generated surface (WCAG AAA).
TEXT_CONTRAST = 7.0
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
    if values["eye_care"] not in EYE_CARE_MODES:
        raise ValueError(tr("Invalid eye-care mode", "护眼模式选项无效"))
    if values["mascot"] not in MASCOT_SKINS:
        raise ValueError(tr("Invalid mascot skin", "看板娘形态选项无效"))
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
    if values["eye_care"] == "night_warm":
        dark = values["color_mode"] == "dark"
        warm_bg = "#261d15" if dark else "#f3e8d6"
        warm_ink = "#f2e5d2" if dark else "#2b1f14"
        for key, weight in (("background", .26), ("surface", .24), ("surface_raised", .22), ("surface_sunken", .26)):
            if key in result:
                result[key] = _mix(result[key], warm_bg, weight)
        result["ink"] = _mix(result["ink"], warm_ink, .22)
        result["muted"] = _mix(result["muted"], warm_ink, .18)
    elif values["eye_care"] == "off":
        dark = values["color_mode"] == "dark"
        result["background"] = _mix(result["background"], "#08080c" if dark else "#ffffff", .22)
        result["ink"] = _mix(result["ink"], "#ffffff" if dark else "#0a0a10", .25)
    return result


def _alpha(color, opacity):
    return color.removeprefix("#") + f"{round(opacity * 255):02x}"


# Material Design 3 semantic role generation.  The numeric recipes below are the
# GTK3 translation of design/TOKENS.md: a single primary from the active preset,
# five tonal surface levels, 14 %/6 % outline alphas, and the 12/14/18/20/26 px
# shape scale.  Presets (including wallpaper tinting), light/dark mode and font
# size still flow through palette()/validate_settings(); nothing here reads the
# live desktop or hardcodes one collection.
MD3_SHAPE = {"window": 28, "card": 24, "tile": 20, "pill": 16,
             "button": 14, "badge": 999}
MD3_TYPE = {"display": 2.15, "headline": 1.45, "title_large": 1.22,
            "title_medium": 1.0, "body": 0.94, "caption": 0.84,
            "overline": 0.78}


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

    if passes(color, TEXT_CONTRAST):
        return color
    low, high = 0.0, 1.0
    for _ in range(24):
        mid = (low + high) / 2
        if passes(_mix(color, ink, mid), TEXT_CONTRAST + .05):
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
    error = palette_values.get("error", palette_values.get("danger", "#f87171"))
    on_primary = palette_values.get("on_accent", background)
    # Filled buttons carry text: nudge the accent toward ink (away from its own
    # on-colour) only when the pair misses the text contrast target.
    primary = _contrast_mix(palette_values["accent"], ink, on_primary, TEXT_CONTRAST)
    # Surface containers progress away from the window base in small steps so
    # cards, raised chips and popovers remain distinguishable without borders.
    container_low = _mix(background, raised, .28)
    container = _mix(background, raised, .52)
    container_high = raised
    container_highest = _mix(raised, ink, .05)
    # Secondary doubles as icon/accent text; keep it legible on every surface.
    secondary = _contrast_mix(palette_values["secondary"], ink, container_highest, 4.5)
    primary_container = _mix(raised, primary, .36 if dark else .22)
    # Trusted contrast handoff: correct only roles that miss the target, moving
    # the smallest distance toward an existing anchor.  Passing colours stay intact.
    on_surface_variant = _contrast_mix(muted, ink, container_highest, TEXT_CONTRAST)
    primary_container = _contrast_mix(primary_container, raised, ink, TEXT_CONTRAST)
    secondary_container = _mix(raised, secondary, .28 if dark else .16)
    secondary_container = _contrast_mix(secondary_container, raised, ink, TEXT_CONTRAST)
    error_container = _mix(raised, error, .30 if dark else .16)
    error_container = _contrast_mix(error_container, raised, ink, TEXT_CONTRAST)
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
    floors = {"body": 12.0, "caption": 11.5, "overline": 11.0} if size >= 12 else {}
    return {name: max(floors.get(name, 8.0), round(size * factor, 2)) for name, factor in MD3_TYPE.items()}


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
    # Sakura Nyan MD3 Tonal Surface tokens: crisp layered opacity, clean rims,
    # and anime candy dual-tone accent reserved for primary controls & active pills.
    dark_mode = values["color_mode"] == "dark"
    rim_alpha = .36 if dark_mode else .30
    card_alpha = min(.98, max(opacity, .94)) if opacity >= .40 else opacity
    ctrl_alpha = min(.98, max(opacity, .92)) if opacity >= .40 else opacity
    top_edge = rgba(r['primary'], .22 if dark_mode else .18)
    card_edge = rgba(r['on_surface'], .08 if dark_mode else .06)
    grad_accent = f"linear-gradient(135deg, {r['primary']}, {r['secondary']})"
    grad_bar = f"linear-gradient(90deg, {r['primary']}, {r['secondary']})"
    outline = "text-shadow: -1px 0 " + bg + ", 1px 0 " + bg + ", 0 -1px " + bg + ", 0 1px " + bg + ";" if opacity < .40 else ""
    context = dict(locals())
    context.pop("settings")
    return context


def _render_panel(*, accent_hover, aliases, bg, card_alpha, card_edge, css_header, ctrl_alpha, dark_mode,
                  family, grad_accent, grad_bar, ink, mono_family, opacity, px, r, rgba, rim_alpha, size,
                  top_edge, type_sizes) -> str:
    """Render ``panel.css``."""
    panel = css_header + _role_definitions(r) + aliases + f"""* {{ font-family: {family}; font-size: {size:g}px; }}
.glass-surface {{ color: {r['on_surface']}; background-color: {rgba(r['surface'], opacity)};
    background-image: none;
    border: 1px solid {rgba(r['primary'], rim_alpha)}; border-radius: {MD3_SHAPE['window']}px;
    box-shadow: inset 0 1px {top_edge}, 0 24px 60px {r['shadow']}; }}
.panel-header {{ padding: 18px 22px 16px; border-bottom: 1px solid {rgba(r['primary'], .24)};
    background-color: {rgba(r['surface_container_low'], min(.98, opacity))};
    background-image: url("../assets/anime/sakura.svg");
    background-repeat: no-repeat; background-position: 98% 20%; background-size: 46px 46px; }}
.panel-content {{ padding: 18px 22px 22px; }}
.panel-title {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.3px; }}
.subtitle, .hint, .control-label {{ color: {r['on_surface_variant']}; font-size: {px('body')}; }}
.eyebrow, .section-title, .message-role {{ color: {r['primary']}; font-size: {px('overline')}; font-weight: 700; letter-spacing: 1.8px; }}
.clock {{ color: {r['on_surface']}; font-size: {px('display')}; font-weight: 700; letter-spacing: -.8px; }}
.card, .message, .metric-card, .pulse-card, .application-audio {{ padding: 16px; border: 1px solid {rgba(r['on_surface'], .12)};
    background-color: {rgba(r['surface_container'], card_alpha)};
    background-image: none;
    border-radius: {MD3_SHAPE['card']}px;
    box-shadow: inset 0 1px {card_edge}, 0 6px 20px {rgba('#000000', .16 if dark_mode else .06)}; }}
button {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], ctrl_alpha)};
    background-image: none;
    border: 1px solid {rgba(r['on_surface'], .16)}; border-radius: {MD3_SHAPE['button']}px; padding: 8px 14px;
    box-shadow: none; text-shadow: none;
    transition: background-color 140ms ease-out, border-color 140ms ease-out, color 140ms ease-out, box-shadow 140ms ease-out; }}
button:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .58)};
    box-shadow: 0 3px 12px {rgba(r['primary'], .20)}; border-radius: {MD3_SHAPE['button']}px; }}
button:checked, button:active {{ color: {r['on_primary_container']}; background-color: {r['primary_container']};
    border-color: {r['primary']}; border-radius: {MD3_SHAPE['button']}px; }}
button:focus, button:focus-within {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 2px {r['primary']}; }}
button:disabled {{ opacity: .38; }}
button.flat, button.md3-text-button {{ color: {r['primary']}; background-color: transparent;
    background-image: none; border-color: transparent; box-shadow: none; }}
button.flat:hover, button.md3-text-button:hover {{ color: {r['on_primary_container']};
    background-color: {rgba(r['primary'], .16)}; border-color: transparent; box-shadow: none; }}
button.flat:checked, button.md3-text-button:checked {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']}; border-color: transparent; }}
button.accent-button {{ color: {r['on_primary']}; background-color: {r['primary']}; background-image: {grad_accent};
    border-color: {r['primary']}; font-weight: 700;
    box-shadow: 0 4px 16px {rgba(r['primary'], .36)}; }}
button.accent-button:hover {{ background-color: {accent_hover}; background-image: {grad_accent}; border-color: {r['secondary']};
    box-shadow: 0 6px 20px {rgba(r['primary'], .48)}; }}
button.accent-button:focus {{ box-shadow: inset 0 0 0 2px {r['on_primary']}; }}
button.power-button {{ color: {r['error']}; border-color: {rgba(r['error'], .40)}; background-color: {rgba(r['error'], .12)}; background-image: none; }}
button.power-button:hover {{ color: {r['on_error_container']}; border-color: {r['error']}; background-color: {r['error_container']};
    box-shadow: 0 4px 14px {rgba(r['error'], .24)}; }}
button.small-button {{ font-size: {px('caption')}; padding: 5px 10px; border-radius: {MD3_SHAPE['button']}px; }}
button.tool-button {{ padding: 9px 8px; font-size: {px('caption')}; }}
button.close-button {{ min-width: 32px; min-height: 32px; padding: 0; border-radius: {MD3_SHAPE['badge']}px;
    color: {r['on_surface_variant']}; background-color: {rgba(r['surface_container_high'], .86)}; background-image: none;
    border-color: {rgba(r['on_surface'], .14)}; box-shadow: none; font-size: {type_sizes['title_large']:g}px; }}
button.close-button:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .55)}; }}
button.close-button:checked, button.close-button:active {{ border-radius: {MD3_SHAPE['badge']}px; }}
.control-tabs {{ padding: 4px; border: 1px solid {rgba(r['primary'], .26)}; border-radius: {MD3_SHAPE['pill']}px;
    background-color: {rgba(r['surface_container_low'], card_alpha)}; }}
.control-tabs button {{ color: {r['on_surface_variant']}; background: transparent; background-image: none; border-color: transparent;
    border-radius: {MD3_SHAPE['badge']}px; box-shadow: none; padding: 6px 6px; font-size: {px('caption')}; font-weight: 600; }}
.control-tabs button:hover {{ color: {r['on_surface']}; background-color: {rgba(r['primary'], .16)}; }}
.control-tabs button:checked, .control-tabs button:active, .control-tabs button:selected {{ color: {r['on_primary_container']};
    border-radius: {MD3_SHAPE['badge']}px; background-color: {r['primary_container']};
    border-color: {rgba(r['primary'], .55)}; font-weight: 700; }}
.scale, scale {{ padding: 6px 2px; }}
scale trough {{ min-height: 7px; border: 1px solid {rgba(r['on_surface'], .14)}; border-radius: {MD3_SHAPE['badge']}px; background-color: {rgba(r['surface_sunken'], .92)}; background-image: none; }}
scale highlight {{ min-height: 7px; border: none; border-radius: {MD3_SHAPE['badge']}px; background-color: {r['primary']}; background-image: {grad_bar}; }}
scale slider {{ min-width: 18px; min-height: 18px; margin: -6px; border: 2px solid {r['primary']};
    border-radius: {MD3_SHAPE['badge']}px; background-color: {r['on_surface'] if dark_mode else r['surface']}; background-image: none;
    box-shadow: 0 2px 6px {rgba('#000000', .32)}, 0 0 0 2px {rgba(r['primary'], .24)}; }}
scale:focus trough {{ outline: none; box-shadow: 0 0 0 2px {rgba(r['primary'], .55)}; }}
scale:disabled {{ opacity: .38; }}
progressbar trough, .metric-progress trough {{ min-height: 7px; border: 1px solid {rgba(r['on_surface'], .14)}; border-radius: {MD3_SHAPE['badge']}px;
    background-color: {rgba(r['surface_sunken'], .92)}; background-image: none; }}
progressbar progress, .metric-progress progress {{ min-height: 7px; border: none; border-radius: {MD3_SHAPE['badge']}px;
    background-color: {r['primary']}; background-image: {grad_bar}; }}
.metric-value, .network-rate, .quick-slider-value, .pulse-value {{ font-family: {mono_family}; font-feature-settings: "tnum 1, cv01 1"; }}
.spec-value {{ font-family: {mono_family}, {family}; }}
.metric-value, .network-rate {{ color: {r['primary']}; font-weight: 700; letter-spacing: -.3px; }}
.metric-value {{ font-size: {type_sizes['headline']:g}px; }}
.network-rate {{ font-size: {type_sizes['title_large']:g}px; }}
entry, spinbutton {{ color: {r['on_surface']}; caret-color: {r['primary']}; border: 1px solid {rgba(r['on_surface'], .18)};
    border-radius: {MD3_SHAPE['pill']}px; padding: 9px 13px; background-color: {rgba(r['surface_sunken'], ctrl_alpha)};
    box-shadow: none; }}
entry:focus, spinbutton:focus {{ outline: none; border-color: {r['primary']};
    box-shadow: inset 0 0 0 1px {rgba(r['primary'], .72)}, 0 0 0 3px {rgba(r['primary'], .18)}; }}
entry selection, textview text selection {{ background-color: {r['primary_container']}; color: {r['on_primary_container']}; }}
spinbutton button {{ border: none; background: transparent; background-image: none; box-shadow: none; border-radius: {MD3_SHAPE['button']}px; padding: 5px 8px; }}
menu, tooltip {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], .98)};
    border: 1px solid {rgba(r['primary'], .36)}; border-radius: {MD3_SHAPE['button']}px; padding: 6px;
    box-shadow: 0 10px 28px {r['shadow']}; }}
menuitem {{ padding: 8px 10px; border-radius: {MD3_SHAPE['button']}px; }}
menuitem:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; }}
list.wallpaper-list {{ background: transparent; color: {r['on_surface']}; }}
list.wallpaper-list row {{ border: 1px solid {rgba(r['on_surface'], .12)}; border-radius: {MD3_SHAPE['button']}px;
    margin: 2px 0; background: {rgba(r['surface_container'], card_alpha)}; color: {r['on_surface']}; padding: 7px 10px; }}
list.wallpaper-list row:hover {{ background: {rgba(r['primary'], .14)}; border-color: {rgba(r['primary'], .38)}; }}
list.wallpaper-list row:selected, list.wallpaper-list row:active {{ border-radius: {MD3_SHAPE['button']}px;
    background: {r['primary_container']}; border-color: {r['primary']}; color: {r['on_primary_container']}; font-weight: 700; }}
flowbox.wallpaper-grid {{ background: transparent; padding: 4px; }}
flowbox.wallpaper-grid flowboxchild, .wallpaper-tile {{ padding: 10px; border: 1px solid {rgba(r['on_surface'], .12)};
    border-radius: {MD3_SHAPE['card']}px; background-color: {rgba(r['surface_container'], card_alpha)};
    box-shadow: inset 0 1px {card_edge}; }}
flowbox.wallpaper-grid flowboxchild:hover, .wallpaper-tile:hover {{ background-color: {rgba(r['surface_container_high'], card_alpha)}; border-color: {rgba(r['primary'], .45)}; }}
flowbox.wallpaper-grid flowboxchild:selected, .wallpaper-tile:selected {{ border-radius: {MD3_SHAPE['card']}px;
    background-image: none; border-color: {r['primary']}; background-color: {r['primary_container']};
    box-shadow: 0 6px 18px {rgba(r['primary'], .24)}; }}
.audio-stream-row {{ padding: 12px 14px; border: 1px solid {rgba(r['on_surface'], .12)}; border-radius: {MD3_SHAPE['card']}px;
    background-color: {rgba(r['surface_container'], card_alpha)}; }}
.audio-stream-row button:checked {{ border-radius: {MD3_SHAPE['button']}px; background-color: {r['primary_container']};
    border-color: {r['primary']}; color: {r['on_primary_container']}; }}
.system-inventory {{ color: {r['on_surface']}; font-size: {size:g}px; }}
label.system-summary {{ font-family: {mono_family}; color: {r['on_surface']}; }}
.keycap {{ font-family: {mono_family}; font-size: {px('caption')}; color: {r['on_primary_container']}; font-weight: 700;
    background-color: {r['primary_container']}; background-image: none;
    border: 1px solid {rgba(r['primary'], .48)};
    border-radius: {MD3_SHAPE['button']}px; padding: 5px 10px; box-shadow: none; text-shadow: none; }}
.shortcut-description, .welcome-copy, .message-text {{ color: {r['on_surface']}; font-size: {px('body')}; }}
.user-message {{ background-color: {r['primary_container']}; background-image: none;
    border-color: {rgba(r['primary'], .46)}; border-bottom-right-radius: 8px; }}
.assistant-message {{ background-color: {rgba(r['surface_container_high'], card_alpha)};
    border-left: 4px solid {r['secondary']}; border-bottom-left-radius: 8px; }}
.composer {{ padding: 12px; border: 1px solid {rgba(r['primary'], .30)}; border-radius: {MD3_SHAPE['card']}px;
    background-color: {rgba(r['surface_container_low'], card_alpha)}; box-shadow: none; }}
textview, textview text {{ color: {r['on_surface']}; caret-color: {r['primary']}; background: transparent; }}
.media-title {{ color: {r['on_surface']}; font-size: {px('title_medium')}; font-weight: 700; }}
.empty-state {{ color: {r['on_surface_variant']}; padding: 40px; }}
.provider-status, .value {{ color: {r['primary']}; font-size: {px('caption')}; font-weight: 700; }}
.status {{ color: {r['primary']}; font-size: {px('body')}; font-weight: 600; }}
.status.error {{ color: {r['error']}; }}
.welcome-icon {{ color: {r['secondary']}; font-size: {type_sizes['headline']:g}px; margin-bottom: 4px; }}
.welcome-title {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.3px; }}
combobox button {{ padding: 8px 11px; }}
combobox arrow {{ color: {r['on_surface_variant']}; }}
scrollbar {{ background: transparent; opacity: 1; }}
scrollbar trough {{ background: transparent; }}
scrollbar slider {{ background-color: {rgba(r['on_surface'], .26)}; border-radius: {MD3_SHAPE['badge']}px; }}
scrollbar slider:hover {{ background-color: {rgba(r['primary'], .65)}; }}
scrollbar slider:active {{ background-color: {r['primary']}; }}
scrolledwindow, viewport {{ background: transparent; border: none; }}
row:focus {{ outline: none; box-shadow: inset 0 0 0 2px {rgba(r['primary'], .90)}; }}
.glass-calendar {{ background-color: {rgba(r['surface_container'], card_alpha)}; border-color: {r['outline_variant']}; }}
.calendar-page {{ padding: 12px; }}
.calendar-page .calendar-card, .calendar-page .calendar-footer {{ padding: 14px; }}
.calendar-card .glass-calendar {{ background: transparent; border: none; padding: 0; }}
.calendar-page.calendar-narrow .glass-calendar .calendar-title {{ font-size: {px('title_medium')}; }}
.calendar-page.calendar-narrow .glass-calendar button.calendar-day-btn {{ min-width: 0; padding: 4px 0; }}
.calendar-date {{ color: {r['on_surface']}; font-size: {px('headline')}; font-weight: 700; letter-spacing: -.2px; }}
button.calendar-primary {{ color: {r['on_primary']}; background-color: {r['primary']}; background-image: {grad_accent};
    border: 1px solid {r['primary']}; font-weight: 700; min-height: 36px; padding: 0 18px;
    border-radius: 999px; box-shadow: 0 4px 14px {rgba(r['primary'], .36)}; }}
button.calendar-primary:hover {{ color: {r['on_primary']}; background-color: {accent_hover}; background-image: {grad_accent};
    border-color: {r['secondary']}; box-shadow: 0 6px 18px {rgba(r['primary'], .48)}; }}
button.calendar-primary:checked, button.calendar-primary:active {{ color: {r['on_primary']};
    background-color: {r['primary']}; border-color: {r['primary']}; }}
button.calendar-secondary {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], ctrl_alpha)};
    border: 1px solid {rgba(r['on_surface'], .18)}; font-weight: 600; min-height: 36px; padding: 0 18px;
    border-radius: 999px; }}
button.calendar-secondary:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']};
    border-color: {rgba(r['primary'], .55)}; }}
button.calendar-secondary:checked, button.calendar-secondary:active {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']}; border-color: {r['primary']}; }}
.glass-calendar .calendar-header {{ color: {r['on_surface']}; border-bottom: 1px solid {rgba(r['primary'], .24)};
    padding-bottom: 8px; margin-bottom: 6px; }}
.glass-calendar .calendar-title {{ color: {r['on_surface']}; font-size: {round(type_sizes['title_large'] * 1.31, 2):g}px; font-weight: 700; letter-spacing: -.2px; }}
.glass-calendar .calendar-week-num {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; padding: 0 4px; }}
.glass-calendar .calendar-empty-cell {{ color: transparent; background-color: transparent; }}
.glass-calendar .calendar-weekday-header, .glass-calendar .calendar-week-header {{ color: {r['primary']};
    font-size: {round(type_sizes['caption'] * 1.16, 2):g}px; font-weight: 700; padding: 4px 0; }}
.glass-calendar button.calendar-nav-btn {{ color: {r['on_surface']}; background: {rgba(r['surface_container_high'], ctrl_alpha)};
    border: 1px solid {rgba(r['on_surface'], .16)}; box-shadow: none; padding: 2px 4px; min-width: 32px;
    min-height: 32px; border-radius: 999px; }}
.glass-calendar button.calendar-nav-btn:checked, .glass-calendar button.calendar-nav-btn:active {{ color: {r['on_primary']};
    background-color: {r['primary']}; background-image: {grad_accent}; border-color: {r['primary']}; }}
.glass-calendar button.calendar-nav-btn:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .50)}; }}
.glass-calendar button.calendar-day-btn {{ background: transparent; background-image: none; border: 1px solid transparent; box-shadow: none;
    padding: 4px 2px; min-width: 32px; min-height: 30px; border-radius: 999px;
    font-size: {round(type_sizes['body'] * 1.05, 2):g}px; font-weight: 600; color: {r['on_surface']}; }}
.glass-calendar button.calendar-day-btn:hover {{ background-color: {rgba(r['primary'], .18)}; border-color: {rgba(r['primary'], .44)}; }}
.glass-calendar button.calendar-day-btn.today {{ border-color: {r['primary']}; color: {r['on_surface']};
    background-color: {rgba(r['primary'], .22)}; font-weight: 700; box-shadow: 0 0 0 1px {rgba(r['primary'], .36)}; }}
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
    border-color: {rgba(r['primary'], rim_alpha)};
    background-image: none;
    box-shadow: inset 0 1px {top_edge}, 0 28px 72px {r['shadow']};
}}
window.glass-window.power-menu-window .glass-surface {{
    border-color: {rgba(r['primary'], rim_alpha)};
    background-image: none;
    box-shadow: inset 0 1px {top_edge}, 0 22px 54px {r['shadow']};
}}
"""
    return panel


def _render_swaync(*, bg, card_alpha, card_edge, css_header, ctrl_alpha, dark_mode, family, grad_accent,
                   grad_bar, opacity, px, r, rgba, rim_alpha, size, top_edge) -> str:
    """Render ``swaync.css``."""
    swaync = '@import "../swaync/style.css";\n' + css_header + _role_definitions(r) + f"""@define-color bg {bg};
@define-color cc-bg {rgba(r['surface_container_low'], opacity)};
@define-color noti-bg {rgba(r['surface_container_high'], max(.90, opacity))};
@define-color noti-border-color {rgba(r['primary'], .32)};
@define-color text-color {r['on_surface']};
@define-color text-color-disabled {r['on_surface_variant']};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
.control-center {{ background-color: {rgba(r['surface_container_low'], opacity)};
    background-image: url("../assets/anime/sakura.svg");
    background-repeat: no-repeat; background-position: right top; background-size: 56px 56px;
    color: {r['on_surface']};
    border: 1px solid {rgba(r['primary'], rim_alpha)}; border-radius: {MD3_SHAPE['window']}px; padding: 16px;
    box-shadow: inset 0 1px {top_edge}, 0 22px 56px {r['shadow']}; }}
.notification {{ background-color: {rgba(r['surface_container_high'], max(.90, opacity))};
    background-image: none;
    border: 1px solid {rgba(r['on_surface'], .14)}; border-left: 4px solid {r['primary']};
    border-radius: {MD3_SHAPE['card']}px; padding: 8px;
    box-shadow: inset 0 1px {card_edge}, 0 8px 24px {rgba('#000000', .20 if dark_mode else .08)}; }}
.notification:hover {{ background-color: {rgba(r['surface_container_highest'], .96)};
    border-color: {rgba(r['primary'], .48)}; border-left-color: {r['secondary']}; }}
.summary, .widget-title {{ color: {r['on_surface']}; font-weight: 700; }}
.body, .widget-dnd {{ color: {r['on_surface']}; }}
.time, .app-name {{ color: {r['on_surface_variant']}; font-size: {px('caption')}; font-weight: 600; }}
.notification-row .notification-background .notification.critical {{ border-color: {r['error']}; border-left: 4px solid {r['error']}; background-color: {r['error_container']}; }}
.notification-group:focus .notification, .notification-row:focus .notification,
.notification-row:focus-within .notification {{ outline: 2px solid {r['primary']}; outline-offset: -2px; }}
.widget-dnd {{ background-color: {rgba(r['surface_container'], card_alpha)}; border: 1px solid {rgba(r['on_surface'], .12)};
    border-radius: {MD3_SHAPE['pill']}px; box-shadow: inset 0 1px {card_edge}; }}
button {{ color: {r['on_surface']}; background-color: {rgba(r['surface_container_high'], ctrl_alpha)};
    border: 1px solid {rgba(r['on_surface'], .16)}; border-radius: {MD3_SHAPE['button']}px; box-shadow: none; text-shadow: none;
    transition: background-color 140ms ease-out, border-color 140ms ease-out; }}
button:hover {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {rgba(r['primary'], .50)}; }}
button:checked, button:active {{ color: {r['on_primary_container']}; background-color: {r['primary_container']}; border-color: {r['primary']}; }}
button:disabled {{ opacity: .38; }}
button:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
button.suggested-action {{ background-color: {r['primary']}; background-image: {grad_accent}; color: {r['on_primary']}; border-color: {r['primary']}; font-weight: 700; }}
.notification-default-action {{ background: transparent; }}
.close-button {{ background-color: {rgba(r['on_surface'], .10)}; border-radius: {MD3_SHAPE['badge']}px; }}
.close-button:hover {{ background-color: {rgba(r['error'], .22)}; color: {r['error']}; }}
switch {{ background-color: {rgba(r['surface_sunken'], .92)}; border: 1px solid {rgba(r['on_surface'], .16)}; border-radius: {MD3_SHAPE['badge']}px; }}
switch:checked {{ background-color: {r['primary']}; background-image: {grad_bar}; border-color: {r['primary']}; }}
switch slider {{ background-color: {r['on_surface'] if dark_mode else r['surface']}; border-radius: {MD3_SHAPE['badge']}px; box-shadow: 0 1px 4px rgba(0, 0, 0, .30); }}
scrollbar slider {{ background-color: {rgba(r['on_surface'], .26)}; border-radius: {MD3_SHAPE['badge']}px; }}
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
    match namespace="^(launcher|anyrun|selandia-.*)$"
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


def _render_lock(*, accent, base, bg, border, danger, dark_mode, font, ink, opacity, secondary, size, surface) -> str:
    """Render ``swaylock.conf``."""
    lock = _replace_ini((base / "swaylock/config").read_text(), "", {"color": bg[1:],
        "image": "~/.config/niri/assets/anime/lock-bg.png" if dark_mode else "~/.config/niri/assets/anime/lock-bg-light.png",
        "scaling": "fill",
        "font": font,
        "font-size": font_scale.whole_points(font_scale.lock_pixels(size)), "inside-color": _alpha(bg, max(.90, opacity)), "ring-color": border[1:],
        "text-color": ink[1:], "key-hl-color": accent[1:], "bs-hl-color": secondary[1:],
        "inside-ver-color": _alpha(surface, .94), "ring-ver-color": accent[1:], "text-ver-color": ink[1:],
        "inside-wrong-color": _alpha(surface, .94), "ring-wrong-color": danger[1:], "text-wrong-color": ink[1:]})
    return lock


def _render_eww(*, bg, css_header, dark_mode, family, grad_accent, grad_bar, mono_family, opacity,
                outline, p, r, rgba, rim_alpha, size, surface, top_edge) -> str:
    """Render ``eww.css``."""
    # Rust frontends consume the same generated roles as GTK; only their
    # selector vocabulary differs.  Bar geometry and timing stay owned by
    # bar_backend.py, so padding, heights and animation hooks stay synchronized.
    # Zero infinite idle @keyframes: prevents 160 Hz CPU Cairo repaints on idle.
    icon_px = max(11.0, round(size * .80, 2))
    val_px = max(12.0, round(size * .90, 2))
    date_px = max(11.0, round(size * .82, 2))
    eww = css_header + _role_definitions(r) + f"""@define-color bg {bg};
@define-color surface {surface};
@define-color accent {r['primary']};
@define-color secondary {r['secondary']};
@define-color on_accent {r['on_primary']};
* {{ font-family: {family}; font-size: {size:g}px; color: {r['on_surface']}; }}
window.background, window, .background {{ background-color: rgba(0, 0, 0, 0); background-image: none; border: none; box-shadow: none; }}
.bar-host {{ background-color: rgba(0, 0, 0, 0); background-image: none; border: none; box-shadow: none; }}
.segment {{ background-color: {rgba(r['surface_container_high'], opacity)};
    background-image: none;
    border: 1px solid {rgba(r['primary'], rim_alpha)}; border-radius: 22px; padding: 2px 10px;
    box-shadow: inset 0 1px {top_edge}; }}
button {{ background: transparent; border: none; box-shadow: none; }}
.pill {{ color: {r['on_surface']}; background: transparent; border: none; border-radius: {MD3_SHAPE['pill']}px; padding: 3px 8px; transition: background-color 140ms ease-out, color 140ms ease-out; }}
.segment .pill * {{ background-color: transparent; background-image: none; box-shadow: none; }}
.segment .pill, .segment .workspace {{ background: transparent; border: none; }}
.segment .pill.launcher-btn {{ color: {r['primary']}; background: {rgba(r['primary'], .16)}; border: 1px solid {rgba(r['primary'], .42)}; padding: 2px 8px; font-weight: 700; }}
.segment .pill.launcher-btn:hover {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; border-color: {r['secondary']}; }}
.launcher-avatar {{ border-radius: 999px; }}
.segment .pill.control-btn {{ color: {r['primary']}; }}
.segment .pill.bt-btn {{ color: {r['on_surface_variant']}; }}
.segment .pill.bt-btn.active {{ color: {r['primary']}; }}
.segment .pill.audio-btn.muted {{ color: {r['error']}; background: {rgba(r['error'], .16)}; }}
.segment .pill.resources, .segment .pill.current-app {{
    background-color: {rgba(r['surface_container_low'], .90)};
    background-image: none;
    border: 1px solid {rgba(r['on_surface'], .12)};
    border-radius: 999px; padding: 2px 12px; margin: 0 2px; }}
.segment .pill.current-app {{ border-color: {rgba(r['primary'], .30)}; padding: 0; }}
.segment .pill.current-app > box {{ padding: 2px 12px; }}
.app-dot {{ color: {r['primary']}; font-size: {max(10.0, round(size * .76, 2)):g}px; margin-right: 4px; }}
.app-label {{ font-weight: 700; color: {r['on_surface']}; }}
.segment .pill.resources:hover, .segment .pill.current-app:hover {{
    color: {r['on_primary_container']}; background: {r['primary_container']}; border-color: {rgba(r['primary'], .55)}; }}
.segment .pill.resources:active, .segment .pill.resources:checked,
.segment .pill.current-app:active, .segment .pill.current-app:checked {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; }}
.segment .pill.resources:focus, .segment .pill.current-app:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.workspace {{ color: {r['on_surface_variant']}; background: transparent; border: none; border-radius: 999px; padding: 3px 9px; min-width: 22px; font-weight: 700; transition: background-color 140ms ease-out, color 140ms ease-out; }}
.workspace:hover, .pill:hover {{ color: {r['on_primary_container']}; background: {r['primary_container']}; border-radius: 999px; }}
.workspace.active, .workspace:active {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent};
    border-radius: 999px; font-weight: 700; min-width: 34px; padding: 3px 12px;
    box-shadow: inset 0 1px {rgba('#ffffff', .35)}; }}
.pill:active, .pill:checked {{ color: {r['on_primary']}; background: {r['primary']}; background-image: {grad_accent}; }}
.workspace.active label, .workspace:active label, .pill:active label, .pill:checked label {{ color: {r['on_primary']}; }}
.compact .pill, .compact .workspace {{ padding: 2px 5px; }}
/* Side capsules keep their horizontal padding; only height and shape change. */
.segment .pill, .segment .workspace,
.segment .pill:hover, .segment .pill:active, .segment .pill:checked,
.segment .workspace:hover, .segment .workspace:active, .segment .workspace.active {{ border-radius: 999px; }}
.separator {{ background-color: {rgba(r['primary'], .28)}; min-width: 1px; margin: 7px 4px; }}
.resource-row {{ background: transparent; }}
.resource {{ padding: 0 3px; }}
.resource-icon {{ color: {r['primary']}; font-size: {icon_px:g}px; font-weight: 700; margin-right: 3px; }}
.resource.cpu .resource-icon {{ color: {r['primary']}; }}
.resource.ram .resource-icon {{ color: {r['secondary']}; }}
.resource.temp .resource-icon {{ color: {p['warning']}; }}
.pill.network-btn .resource-icon {{ color: {p['success']}; }}
.resource-value {{ color: {r['on_surface']}; font-family: {mono_family}; font-size: {val_px:g}px; font-weight: 700; font-feature-settings: "tnum 1, cv01 1"; }}
.clock-time {{ color: {r['on_surface']}; font-family: {mono_family}; font-size: {round(size * 1.04, 2):g}px; font-weight: 700; letter-spacing: -0.3px; font-feature-settings: "tnum 1, cv01 1"; }}
.clock-date {{ color: {r['primary']}; font-size: {date_px:g}px; font-weight: 700; letter-spacing: .04em; margin-top: 0; }}
.island {{ background-color: {rgba(r['surface_container_highest'], opacity)};
    background-image: url("../assets/anime/sakura.svg");
    background-repeat: no-repeat; background-position: 95% center; background-size: 18px 18px;
    border: 1px solid {rgba(r['primary'], .44 if dark_mode else .36)}; border-radius: 22px; padding: 8px 12px;
    box-shadow: inset 0 1px {top_edge}; transition: border-color 160ms ease-out; }}
.island.playing, .island.expanded {{ border-color: {r['primary']};
    box-shadow: inset 0 1px {top_edge}, inset 0 0 0 1px {rgba(r['primary'], .36)}; }}
.island-idle-row {{ background: transparent; padding-right: 16px; }}
.island-idle-icon {{ color: {r['primary']}; font-size: {round(size * 1.05, 2):g}px; font-weight: 700; }}
.island.playing .island-idle-icon {{ color: {r['secondary']}; }}
.island-clock {{ padding: 2px 10px; border-radius: 999px; background-color: transparent; border: 1px solid transparent; }}
.island-clock:hover {{ background-color: {r['primary_container']}; border-color: {r['primary']}; }}
.island-title {{ color: {r['on_surface']}; font-weight: 700; }}
.island-summary {{ color: {r['on_surface_variant']}; font-size: {val_px:g}px; }}
.island-cover {{ border-radius: 12px; border: 1px solid {rgba(r['primary'], .36)}; padding: 2px; background: {rgba(r['surface_sunken'], .75)}; }}
.island button {{ color: {r['on_surface']}; padding: 4px 8px; border-radius: 999px; font-weight: 600; }}
.island button:hover {{ color: {r['on_primary_container']}; background: {r['primary_container']}; border-radius: 999px; }}
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
scale slider {{ background: {r['on_surface'] if dark_mode else r['surface']}; border: 2px solid {r['primary']}; border-radius: 999px; min-width: 18px; min-height: 18px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.38); margin: -5px 0; }}
button:focus, .pill:focus, .workspace:focus {{ outline: none; box-shadow: inset 0 0 0 2px {r['primary']}; }}
.reduce-motion, .reduce-motion * {{ transition: none; animation: none; }}
"""
    return eww


def _render_anyrun(*, bg, css_header, ctrl_alpha, dark_mode, family, opacity, outline, r, rgba, rim_alpha,
                   size, top_edge) -> str:
    """Render ``anyrun.css``."""
    launcher_px = font_scale.anyrun_pixels(size)
    anyrun = css_header + _role_definitions(r) + f"""@define-color bg {bg};
* {{ font-family: {family}; font-size: {launcher_px:g}px; color: {r['on_surface']}; }}
window {{ background: transparent; }}
box.main {{ background-color: {rgba(r['surface_container_high'], opacity)};
    background-image: url("../assets/anime/star-sparkle.svg");
    background-repeat: no-repeat; background-position: right top; background-size: 30px 30px;
    border: 1px solid {rgba(r['primary'], rim_alpha)};
    border-radius: {MD3_SHAPE['window']}px; padding: 18px; margin: 16px;
    box-shadow: inset 0 1px {top_edge}, 0 24px 60px {r['shadow']}; }}
text {{ color: {r['on_surface']}; background: {rgba(r['surface_sunken'], ctrl_alpha)}; caret-color: {r['primary']};
    padding: 12px 14px; border: 1px solid {rgba(r['primary'], .34)}; border-radius: {MD3_SHAPE['pill']}px; min-height: 34px;
    box-shadow: none; }}
text:focus {{ outline: none; border-color: {r['primary']}; box-shadow: inset 0 0 0 2px {r['primary']}, 0 0 12px {rgba(r['primary'], .28)}; }}
.matches, list, row {{ background: transparent; }}
row {{ color: {r['on_surface']}; border: 1px solid transparent; border-radius: {MD3_SHAPE['button']}px; padding: 8px 12px; margin: 2px 0; }}
row:hover {{ color: {r['on_primary_container']}; background: {rgba(r['primary'], .14)}; border-color: {rgba(r['primary'], .32)}; }}
row:selected, row:active, .match:selected {{ color: {r['on_primary_container']};
    background-color: {r['primary_container']};
    background-image: none;
    border: 1px solid {rgba(r['primary'], .58)}; border-left: 4px solid {r['primary']};
    border-radius: {MD3_SHAPE['button']}px; font-weight: 700; }}
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
