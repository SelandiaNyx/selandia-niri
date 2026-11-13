"""Short frame-clock transitions for the native GTK panel.

Animate the painted child, never layer-shell anchors or the window's allocation.
GTK's accessibility preference always wins over the local animation preference.
There are no timeout sources or background threads to outlive a closed panel.

The optional offset callback lets drawers slide their already-allocated content
while the same frame-clock tick also fades it. Opacity-only callers keep the
original constructor and behaviour.
"""
from __future__ import annotations


def animations_enabled(widget, enabled=None):
    """A bool or callable may further reduce motion, never override GTK's choice."""
    local = enabled() if callable(enabled) else enabled
    settings = widget.get_settings()
    return local is not False and bool(settings.get_property("gtk-enable-animations"))


def configure_stack(stack, *, enabled=None, duration_ms=160):
    """Call when selecting a page or changing the local motion preference."""
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    active = animations_enabled(stack, enabled)
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE if active
                              else Gtk.StackTransitionType.NONE)
    stack.set_transition_duration(max(0, int(duration_ms)) if active else 0)


def ease_out_cubic(progress):
    """Start promptly and settle gently, with a defined result after frame stalls."""
    return 1.0 - (1.0 - min(1.0, max(0.0, progress))) ** 3


class PanelMotion:
    """Reversible fade (and optional paint offset) driven by the frame clock.

    Call ``reveal()`` immediately before ``show_all()``. Route user close actions
    through ``dismiss(window.destroy)``; destruction still cancels any animation
    if shutdown bypasses that route. ``reveal()`` cancels a pending dismissal.
    ``enabled`` can be a function so an appearance preference is read each frame.
    ``offset_setter`` receives the current horizontal offset; ``travel`` is the
    offset used for a fully dismissed drawer.
    """

    def __init__(self, widget, *, duration_ms=180, enabled=None,
                 offset_setter=None, travel=0):
        self.widget = widget
        self.duration_ms = max(0, int(duration_ms))
        self.enabled = enabled
        self.offset_setter = offset_setter
        self.travel = float(travel)
        self._tick_id = None
        self._started_at = None
        self._done = None
        self._disposed = False
        self._revealed = False
        self._start_opacity = 1.0
        self._target = 1.0
        self._start_offset = 0.0
        self._target_offset = 0.0
        self._offset = 0.0
        self._duration_us = 0
        self._destroy_handler = widget.connect("destroy", lambda *_: self.dispose())

    @property
    def running(self):
        return self._tick_id is not None

    def _set_offset(self, value):
        self._offset = value
        if self.offset_setter is not None:
            self.offset_setter(value)

    def reveal(self):
        if self._disposed:
            return
        if not self._revealed:
            self.widget.set_opacity(0.0)
            if self.travel:
                self._set_offset(self.travel)
            self._revealed = True
        self._animate(1.0)

    def dismiss(self, on_finished):
        if self._disposed:
            return
        if not self.widget.get_mapped():
            self.cancel()
            self.widget.set_opacity(0.0)
            if self.travel:
                self._set_offset(self.travel)
            on_finished()
            return
        self._animate(0.0, on_finished)

    def cancel(self):
        """Leave the current frame in place and discard a pending completion."""
        tick = self._tick_id
        self._tick_id = None
        self._done = None
        self._started_at = None
        if tick is not None:
            self.widget.remove_tick_callback(tick)

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.cancel()
        handler = self._destroy_handler
        self._destroy_handler = None
        if handler is not None:
            try:
                self.widget.disconnect(handler)
            except (TypeError, RuntimeError):
                pass

    def _animate(self, target, done=None):
        self.cancel()
        self._target = target
        self._target_offset = 0.0 if target >= 1.0 else self.travel
        self._start_opacity = self.widget.get_opacity()
        self._start_offset = self._offset
        self._done = done
        distance = abs(target - self._start_opacity)
        self._duration_us = self.duration_ms * 1000 * distance
        if not animations_enabled(self.widget, self.enabled) or self._duration_us < 1:
            self._finish()
            return
        if target < 1.0 and distance < 1e-6 and abs(self._start_offset - self._target_offset) < 1e-6:
            self._finish()
            return
        self._tick_id = self.widget.add_tick_callback(self._tick)

    def _finish(self):
        # Clear ownership before invoking a callback which may destroy the widget
        # or start another transition. Returning False removes this frame source.
        self._tick_id = None
        self._started_at = None
        done, self._done = self._done, None
        self.widget.set_opacity(self._target)
        if self.travel:
            self._set_offset(self._target_offset)
        if done is not None:
            done()

    def _tick(self, _widget, frame_clock):
        if self._disposed:
            return False
        if not animations_enabled(self.widget, self.enabled):
            self._finish()
            return False
        now = frame_clock.get_frame_time()
        if self._started_at is None:
            self._started_at = now
        progress = (now - self._started_at) / self._duration_us
        if progress >= 1:
            self._finish()
            return False
        eased = ease_out_cubic(progress)
        opacity = self._start_opacity + (self._target - self._start_opacity) * eased
        self.widget.set_opacity(opacity)
        if self.travel:
            self._set_offset(self._start_offset + (self._target_offset - self._start_offset) * eased)
        return True
