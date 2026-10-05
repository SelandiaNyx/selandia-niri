#!/usr/bin/env python3
"""Compute the logical width the status bar needs, from real font metrics.

The bar must not be rescued by shrinking the font, so the wide/compact decision
is a measurement: every module's worst-case text is measured with Pango at its
effective font size, its padding and margin are added, and the sum is compared
with the narrowest connected output.

Design sizes are expressed relative to the 12px base, exactly like the panel
stylesheet (``appearance.render_files``), so the interface size scales the whole
bar. If Pango is unavailable the documented fallback constants are used instead,
because a wrong-but-safe layout beats a bar that cannot start.
"""
from __future__ import annotations

# Design base: the panel stylesheet uses the same 12px reference.
DESIGN_BASE = 12.0
# Bar margins from waybar/config.jsonc plus a conservative inter-module allowance.
BAR_MARGIN = 18 + 18
MODULE_SPACING = 2
# Measurement headroom: glyph fallbacks, tray icons and rounding.
HEADROOM = 1.08
HEADROOM_PADDING = 8
# Used only when Pango cannot be loaded; they are the values this module
# replaced, so the bar still selects a sane layout in a broken environment.
FALLBACK_WIDE = 68.0
FALLBACK_COMPACT = 40.0

# (module, worst-case text, design font size, horizontal padding+margin, extra)
WIDE_LEFT = (
    ("custom/launcher", "󰣇", 20, 24 + 2, 8),
    ("niri/workspaces", "10", DESIGN_BASE, 18 + 2, 8),          # per workspace button
    ("niri/window", "W" * 18, 11, 20 + 2, 0),
)
WIDE_CENTER = (
    ("clock", "Sun  12.31   23:59", DESIGN_BASE, 36 + 2, 0),
    ("clock", "周日  12.31   23:59", DESIGN_BASE, 36 + 2, 0),
)
WIDE_RIGHT = (
    ("custom/layout", "", DESIGN_BASE, 0, 0),
    ("custom/ai", "✦ AI", DESIGN_BASE, 24 + 2, 0),
    ("custom/shortcuts", "󰌌", 16, 20 + 2, 0),
    ("custom/system", "󰍛 100%  󰘚 100%", 10, 16 + 2, 0),
    ("pulseaudio", "󰕾 100%", 11, 16 + 2, 0),
    ("network", "󰈀 ↓999.9MiB ↑999.9MiB", 10, 14 + 2, 0),
    ("battery", "󰁹 100%", 11, 16 + 2, 0),
    ("tray", "", DESIGN_BASE, 20 + 2, 4 * 16 + 3 * 10),
    ("custom/notification", "󱅫", 16, 20 + 2, 0),
    ("custom/control", "󰒓", DESIGN_BASE, 20 + 2, 0),
)
COMPACT_LEFT = (
    ("custom/launcher", "󰣇", 20, 24 + 2, 8),
    ("niri/workspaces", "10", DESIGN_BASE, 18 + 2, 0),          # empty workspaces are hidden
)
COMPACT_CENTER = (("clock", "23:59", DESIGN_BASE, 36 + 2, 0),)
COMPACT_RIGHT = (
    ("custom/layout", "", DESIGN_BASE, 0, 0),
    ("pulseaudio", "󰕾 100%", 11, 16 + 2, 0),
    ("network", "󰈀", 10, 14 + 2, 0),
    ("battery", "󰁹 100%", 11, 16 + 2, 0),
    ("tray", "", DESIGN_BASE, 20 + 2, 4 * 16 + 3 * 10),
    ("custom/notification", "󱅫", 16, 20 + 2, 0),
    ("custom/control", "󰒓", DESIGN_BASE, 20 + 2, 0),
)
LAYOUTS = {
    "wide": (WIDE_LEFT, WIDE_CENTER, WIDE_RIGHT),
    "compact": (COMPACT_LEFT, COMPACT_CENTER, COMPACT_RIGHT),
}


def _font_map():
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    return Pango, PangoCairo.FontMap.get_default()


class Measurer:
    """Pango text widths, cached per (text, pixel size)."""

    def __init__(self, family="Noto Sans"):
        self.family = family
        self.cache = {}
        self._pango = None
        self._context = None

    @property
    def available(self):
        try:
            self._context_for(12)
        except Exception:
            return False
        return True

    def _context_for(self, size):
        if self._context is None:
            self._pango, font_map = _font_map()
            self._context = font_map.create_context()
        return self._context

    def width(self, text, size):
        if not text:
            return 0
        key = (text, round(size, 2))
        if key in self.cache:
            return self.cache[key]
        context = self._context_for(size)
        layout = self._pango.Layout(context)
        description = self._pango.FontDescription()
        description.set_family(self.family)
        description.set_absolute_size(float(size) * self._pango.SCALE)
        layout.set_font_description(description)
        layout.set_text(text, -1)
        measured = layout.get_pixel_size()[0]
        self.cache[key] = measured
        return measured


def scale(design_size, interface_size):
    """A design font size for the current interface size (same rule as the panel)."""
    return float(design_size) * float(interface_size) / DESIGN_BASE


def required(layout, interface_size, *, measurer=None):
    """Logical pixels the bar needs for one layout, or None if unmeasurable."""
    if layout not in LAYOUTS:
        raise ValueError("Unknown bar layout: " + str(layout))
    measurer = measurer or Measurer()
    try:
        if not measurer.available:
            return None
        total = BAR_MARGIN
        count = 0
        for group in LAYOUTS[layout]:
            for _module, text, design_size, padding, extra in group:
                total += measurer.width(text, scale(design_size, interface_size))
                total += padding + extra + MODULE_SPACING
                count += 1
        # Workspaces: ten buttons, ten labels, empty ones hidden in compact mode.
        if layout == "wide":
            workspaces = next(item for item in WIDE_LEFT if item[0] == "niri/workspaces")
            total += 9 * (measurer.width(workspaces[1], scale(workspaces[2], interface_size))
                          + workspaces[3] + MODULE_SPACING)
        total = total * HEADROOM + HEADROOM_PADDING
        return int(total + 0.999)
    except Exception:
        return None


def fits(layout, width, interface_size, *, measurer=None):
    """True when the layout is measured to fit; unknown geometry never blocks."""
    if not width:
        return True
    needed = required(layout, interface_size, measurer=measurer)
    if needed is None:
        factor = FALLBACK_WIDE if layout == "wide" else FALLBACK_COMPACT
        return float(width) >= factor * float(interface_size)
    return float(width) >= needed


def choose(width, interface_size, *, measurer=None):
    """The widest layout that fits, falling back to compact."""
    if not width:
        return "wide"  # unknown geometry must not silently degrade the bar
    if fits("wide", width, interface_size, measurer=measurer):
        return "wide"
    return "compact"


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Status-bar width requirement")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--font-size", type=float, default=16.0, dest="font_size")
    arguments = parser.parse_args()
    report = {"font_size": arguments.font_size,
              "required": {layout: required(layout, arguments.font_size) for layout in LAYOUTS},
              "chosen": choose(arguments.width, arguments.font_size)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
