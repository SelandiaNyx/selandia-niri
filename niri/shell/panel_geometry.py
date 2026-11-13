"""Panel and drawer geometry in logical pixels, bounded by the chosen monitor."""
from __future__ import annotations

DRAWER_BOTTOM_MARGIN = 16
DRAWER_SIDE_MARGIN = 16
DRAWER_TOP_GAP = 12
# drawer_geometry receives the physical side from surface_registry.
DRAWER_WIDTHS = {"left": 440, "right": 420}


def dimensions(mode, width, height):
    """Legacy bounded sizes for direct callers; Panel uses drawer_geometry()."""
    available_width, available_height = max(1, width - 32), max(1, height - 80)
    if mode == "control":
        target_width = min(1600, max(1120, round(width * .60)))
        target_height = min(1120, max(880, round(height * .86)))
    else:
        target_width = 860 if mode == "shortcuts" else 440
        target_height = 440 if mode == "calendar" else 820
    return min(target_width, available_width), min(target_height, available_height)


def reserved_bar_height(font_size=16):
    """Read the bar's existing reservation formula without changing the bar."""
    try:
        from bar_backend import reserved_height
        return max(1, int(reserved_height(font_size)))
    except Exception:
        # Keep drawer placement usable if an optional bar dependency is absent.
        return max(44, round(float(font_size) * 2.8 + 22))


def drawer_top_margin(font_size=16, gap=DRAWER_TOP_GAP):
    return max(1, reserved_bar_height(font_size) + max(0, int(gap)))


def drawer_geometry(side, width, height, font_size=16, gap=DRAWER_TOP_GAP):
    """Fixed width plus the vertical span left by the bar reservation."""
    monitor_width = max(1, int(width))
    target_width = DRAWER_WIDTHS.get(side, 440)
    width = min(target_width, max(1, monitor_width - 2 * DRAWER_SIDE_MARGIN))
    top = min(drawer_top_margin(font_size, gap), max(1, int(height) - DRAWER_BOTTOM_MARGIN - 1))
    available = max(1, int(height) - top - DRAWER_BOTTOM_MARGIN)
    return width, available, top
