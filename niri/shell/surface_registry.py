"""Canonical surface keys, command validation, and drawer metadata."""
from __future__ import annotations

from navigation_catalog import PAGE_KEYS

CONTROL_MODES = frozenset(PAGE_KEYS) | {"control"}
AUXILIARY_MODES = ("shortcuts", "ai", "calendar")
SURFACE_KEYS = tuple(dict.fromkeys((*PAGE_KEYS, "control", *AUXILIARY_MODES)))
DRAWER_SIDES = {"ai": "left", "calendar": "right"}

# English/Chinese title, then subtitle. Control keeps its existing dedicated
# header text in Panel; these entries cover the secondary surfaces.
SURFACE_COPY = {
    "calendar": ("Calendar", "日历", "Choose a date", "选择日期"),
    "shortcuts": ("Keyboard Atlas", "Keyboard Atlas",
                  "快捷键总览  ·  Find your next move",
                  "快捷键总览  ·  Find your next move"),
    "ai": ("Intelligence", "Intelligence",
           "AI 侧边栏  ·  A little room to think",
           "AI 侧边栏  ·  A little room to think"),
}



