"""Lightweight 60-point Cairo sparkline widget for live telemetry curves."""
from __future__ import annotations

from collections import deque

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class Sparkline(Gtk.DrawingArea):
    def __init__(self, color_rgb=(0.62, 0.66, 1.0), max_points: int = 60, height: int = 34):
        super().__init__()
        self._color = color_rgb
        self._points: deque[float] = deque(maxlen=max_points)
        self.set_size_request(110, height)
        self.connect("draw", self._draw)

    def push(self, value: float | None):
        if value is None:
            return
        clamped = max(0.0, min(100.0, float(value)))
        self._points.append(clamped)
        self.queue_draw()

    def _draw(self, _widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        if w <= 4 or h <= 4 or not self._points:
            return False
        r, g, b = self._color
        pad = 3.0
        usable_h = max(1.0, h - pad * 2)
        values = list(self._points)
        if len(values) == 1:
            values = [values[0], values[0]]
        n = len(values)
        step = w / max(1, n - 1)
        pts = [(i * step, h - pad - (val / 100.0) * usable_h) for i, val in enumerate(values)]

        # Area fill
        cr.move_to(pts[0][0], h)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], h)
        cr.close_path()
        cr.set_source_rgba(r, g, b, 0.18)
        cr.fill()

        # Crisp curve stroke
        cr.move_to(pts[0][0], pts[0][1])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgba(r, g, b, 0.92)
        cr.set_line_width(1.8)
        cr.stroke()
        return False
