"""Interactive multi-monitor drag-and-snap arrangement canvas for Displays."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk


class DisplayArrangeCanvas(Gtk.DrawingArea):
    """Proportional display layout diagram with click-select and drag-to-arrange."""

    def __init__(self, on_select=None, on_move=None):
        super().__init__()
        self.on_select = on_select
        self.on_move = on_move
        self.outputs: list[dict] = []
        self.selected: str | None = None
        self._dragging: str | None = None
        self._drag_origin = (0.0, 0.0)
        self._orig_pos = (0, 0)
        self._transform = (1.0, 0.0, 0.0)  # scale, ox, oy

        self.set_size_request(-1, 168)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_release)

    def set_outputs(self, outputs: list[dict], selected: str | None = None):
        """Each output dict has: name, x, y, width, height, mode, scale."""
        self.outputs = [dict(o) for o in outputs]
        if selected is not None:
            self.selected = selected
        elif self.outputs and self.selected not in {o["name"] for o in self.outputs}:
            self.selected = self.outputs[0]["name"]
        self.queue_draw()

    def update_position(self, name: str, x: int, y: int):
        for o in self.outputs:
            if o["name"] == name:
                o["x"], o["y"] = int(x), int(y)
                break
        self.queue_draw()

    def _compute_transform(self, width: int, height: int):
        if not self.outputs:
            return 0.05, width / 2.0, height / 2.0
        min_x = min(o["x"] for o in self.outputs)
        min_y = min(o["y"] for o in self.outputs)
        max_x = max(o["x"] + max(640, o["width"]) for o in self.outputs)
        max_y = max(o["y"] + max(400, o["height"]) for o in self.outputs)
        span_x = max(1280, max_x - min_x)
        span_y = max(720, max_y - min_y)
        pad = 24.0
        scale = min((width - pad * 2) / span_x, (height - pad * 2) / span_y)
        ox = (width - span_x * scale) / 2.0 - min_x * scale
        oy = (height - span_y * scale) / 2.0 - min_y * scale
        return scale, ox, oy

    def _rect_for(self, o: dict):
        scale, ox, oy = self._transform
        rx = ox + o["x"] * scale
        ry = oy + o["y"] * scale
        rw = max(68.0, o["width"] * scale)
        rh = max(44.0, o["height"] * scale)
        return rx, ry, rw, rh

    def _on_draw(self, _widget, cr):
        w = self.get_allocated_width()
        h = self.get_allocated_height()
        self._transform = self._compute_transform(w, h)

        # Subtle rounded dark backing + grid dots
        cr.set_source_rgba(0.55, 0.52, 0.78, 0.09)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        cr.set_source_rgba(0.62, 0.66, 1.0, 0.14)
        for gx in range(18, w, 24):
            for gy in range(18, h, 24):
                cr.arc(gx, gy, 1.0, 0, 6.283)
                cr.fill()

        for o in self.outputs:
            rx, ry, rw, rh = self._rect_for(o)
            active = o["name"] == self.selected
            # Rounded monitor rectangle
            r = 10.0
            cr.new_sub_path()
            cr.arc(rx + rw - r, ry + r, r, -1.5708, 0)
            cr.arc(rx + rw - r, ry + rh - r, r, 0, 1.5708)
            cr.arc(rx + r, ry + rh - r, r, 1.5708, 3.1416)
            cr.arc(rx + r, ry + r, r, 3.1416, 4.7124)
            cr.close_path()
            if active:
                cr.set_source_rgba(0.61, 0.66, 1.0, 0.28)
            else:
                cr.set_source_rgba(0.45, 0.42, 0.62, 0.22)
            cr.fill_preserve()
            cr.set_line_width(2.0 if active else 1.2)
            if active:
                cr.set_source_rgba(0.62, 0.66, 1.0, 0.95)
            else:
                cr.set_source_rgba(0.82, 0.78, 0.92, 0.42)
            cr.stroke()

            # Labels
            cr.select_font_face("Sans", 0, 1 if active else 0)
            cr.set_font_size(12.5)
            cr.set_source_rgba(0.95, 0.93, 0.99, 0.95)
            cr.move_to(rx + 10, ry + 22)
            cr.show_text(o["name"])
            cr.set_font_size(10.5)
            cr.set_source_rgba(0.85, 0.81, 0.94, 0.82)
            cr.move_to(rx + 10, ry + 38)
            cr.show_text(f"{o.get('mode', '')} · {o.get('scale', 1) * 100:g}%")
        return False

    def _hit(self, x: float, y: float):
        for o in reversed(self.outputs):
            rx, ry, rw, rh = self._rect_for(o)
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return o
        return None

    def _on_press(self, _w, event):
        hit = self._hit(event.x, event.y)
        if hit is None:
            return False
        self.selected = hit["name"]
        self._dragging = hit["name"]
        self._drag_origin = (event.x, event.y)
        self._orig_pos = (hit["x"], hit["y"])
        if self.on_select:
            self.on_select(hit["name"])
        self.queue_draw()
        return True

    def _on_motion(self, _w, event):
        if not self._dragging or len(self.outputs) < 2:
            return False
        scale = max(0.01, self._transform[0])
        dx = round((event.x - self._drag_origin[0]) / scale)
        dy = round((event.y - self._drag_origin[1]) / scale)
        nx = self._orig_pos[0] + dx
        ny = self._orig_pos[1] + dy
        # Snap to neighboring monitor edges within 120 logical pixels
        moving = next((o for o in self.outputs if o["name"] == self._dragging), None)
        if moving:
            mw, mh = moving["width"], moving["height"]
            for other in self.outputs:
                if other["name"] == self._dragging:
                    continue
                ox, oy, ow, oh = other["x"], other["y"], other["width"], other["height"]
                for cand in (ox - mw, ox + ow, ox):
                    if abs(nx - cand) <= 120:
                        nx = cand
                        break
                for cand in (oy - mh, oy + oh, oy):
                    if abs(ny - cand) <= 120:
                        ny = cand
                        break
            moving["x"], moving["y"] = int(nx), int(ny)
            if self.on_move:
                self.on_move(self._dragging, int(nx), int(ny))
            self.queue_draw()
        return True

    def _on_release(self, _w, _event):
        self._dragging = None
        return False
