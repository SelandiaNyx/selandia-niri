"""Bounded child canvas for painted drawer translation.

A plain Gtk.Fixed reports a preferred width that includes a moved child's
offset, so sliding a right drawer outward can grow the native window despite a
size request.  This fixed-size container keeps requisition independent of the
child offset while still letting PanelMotion move only the painted child.
"""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class BoundedCanvas(Gtk.Fixed):
    __gtype_name__ = "SelandiaBoundedCanvas"

    def __init__(self, width, height):
        super().__init__()
        self.bounded_width = max(1, int(width))
        self.bounded_height = max(1, int(height))
        self._child = None
        self.set_size_request(self.bounded_width, self.bounded_height)

    def set_child(self, child):
        self._child = child
        self.put(child, 0, 0)

    def move_child(self, value):
        if self._child is not None:
            self.move(self._child, int(round(value)), 0)

    def do_get_preferred_width(self):
        return self.bounded_width, self.bounded_width

    def do_get_preferred_height(self):
        return self.bounded_height, self.bounded_height

    def do_get_preferred_width_for_height(self, _height):
        return self.bounded_width, self.bounded_width

    def do_get_preferred_height_for_width(self, _width):
        return self.bounded_height, self.bounded_height
