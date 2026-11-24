"""Consume wheel events before unfocused nested selector widgets can edit values."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk


def _control(widget):
    current = widget
    while current:
        if isinstance(current, (Gtk.ComboBox, Gtk.Scale, Gtk.SpinButton)):
            return current
        current = current.get_parent()
    return None


def handle(widget, event):
    if event.type != Gdk.EventType.SCROLL:
        return False
    control = _control(widget)
    if control is None:
        return False
    # A popup is a separate list: its own scrolling remains available.
    if isinstance(control, Gtk.ComboBox) and control.get_property("popup-shown"):
        return False
    # Explicitly focused Scale/SpinButton allows intentional wheel fine-tuning.
    if isinstance(control, (Gtk.Scale, Gtk.SpinButton)) and control.has_focus():
        return False
    parent = control.get_parent()
    while parent and not isinstance(parent, Gtk.ScrolledWindow):
        parent = parent.get_parent()
    if parent:
        dx = 0.0
        delta = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(event.direction, 0)
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dx, delta = event.get_scroll_deltas()
        elif event.direction in (Gdk.ScrollDirection.LEFT, Gdk.ScrollDirection.RIGHT):
            return False
        if delta == 0 and dx != 0:
            return False
        adjustment = parent.get_vadjustment()
        low = adjustment.get_lower()
        page = adjustment.get_page_size()
        step = max(40.0, min(96.0, page * 0.12)) if page > 0 else 48.0
        high = max(low, adjustment.get_upper() - page)
        adjustment.set_value(min(high, max(low, adjustment.get_value() + delta * step)))
    return True


def protect(widget):
    if getattr(widget, "_selandia_scroll_guard", False):
        return
    widget._selandia_scroll_guard = True
    # ::event runs before ::scroll-event and before the default handler. Watching
    # every descendant matters: ComboBox forwards input to an internal button.
    widget.connect("event", handle)
    # Also cover callers and backends which dispatch the specific signal.
    widget.connect("scroll-event", handle)
    if isinstance(widget, Gtk.Container):
        widget.connect("add", lambda _container, child: protect(child))
        # get_children() excludes GTK's internal ComboBox button; forall()
        # reaches the widget that actually receives pointer events.
        widget.forall(protect)
