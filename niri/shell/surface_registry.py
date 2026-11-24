"""Canonical surface keys, route aliases, command validation, and drawer metadata."""
from __future__ import annotations

from navigation_catalog import PAGE_ALIASES, PAGE_KEYS

CONTROL_MODES = frozenset(PAGE_KEYS) | frozenset(PAGE_ALIASES) | {"control"}
AUXILIARY_MODES = ("shortcuts", "ai", "calendar")
SURFACE_KEYS = tuple(dict.fromkeys((*PAGE_KEYS, *PAGE_ALIASES, "control", *AUXILIARY_MODES)))
DRAWER_SIDES = {"ai": "left", "calendar": "right"}

# English/Chinese title, then subtitle. Control keeps its existing dedicated
# header text in Panel; these entries cover the secondary surfaces.
SURFACE_COPY = {
    "calendar": ("Calendar", "日历", "Date, lunar calendar & quick copy", "公历、农历与快速复制"),
    "shortcuts": ("Keyboard Atlas", "快捷键总览",
                  "Find any Niri binding instantly",
                  "快速检索任意 Niri 快捷键"),
    "ai": ("Gemini Assistant", "AI 助手侧栏",
           "Streaming chat & local models",
           "流式对话与本地模型"),
}
