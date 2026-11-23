"""Process, D-Bus and widget helpers shared by the panel and its page mixins."""
from __future__ import annotations

from pathlib import Path
import os
import subprocess

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gio, Gtk, Pango

from i18n import tr, tr_legacy

BASE = Path(__file__).resolve().parent.parent
DESKTOP = str(BASE / "scripts" / "desktop")
ENV = dict(os.environ, LC_ALL="C")


def capture(command, *, timeout=4, check=True):
    result = subprocess.run(command, capture_output=True, text=True, env=ENV, timeout=timeout)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[-400:]
        raise RuntimeError(detail or f"{command[0]} exited with status {result.returncode}")
    return result.stdout.strip()


def probe(command):
    try:
        return capture(command)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return None


def power_runtime_state():
    try:
        import sleep_guard
        return sleep_guard.status()
    except Exception as error:
        return {"available": False, "awake": False, "error": True,
                "label": tr("Power status unavailable", "无法读取电源状态"), "detail": str(error)}


def bluetooth_state():
    """Use BlueZ directly; bluez-utils/bluetoothctl is not required."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        result = bus.call_sync("org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
                               "GetManagedObjects", None, GLib.VariantType.new("(a{oa{sa{sv}}})"),
                               Gio.DBusCallFlags.NONE, 2500, None)
        objects = result.unpack()[0]
        adapters = []
        for path, interfaces in objects.items():
            properties = interfaces.get("org.bluez.Adapter1")
            if properties is not None:
                adapters.append({"path": path, "powered": bool(properties.get("Powered", False)),
                                 "name": properties.get("Alias", properties.get("Name", path))})
        return sorted(adapters, key=lambda adapter: (not adapter["powered"], adapter["path"]))[0] if adapters else None
    except GLib.Error:
        return None


def set_bluetooth(path, powered):
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    bus.call_sync("org.bluez", path, "org.freedesktop.DBus.Properties", "Set",
                  GLib.Variant("(ssv)", ("org.bluez.Adapter1", "Powered", GLib.Variant("b", powered))),
                  None, Gio.DBusCallFlags.NONE, 10000, None)


def panel_monitor(display):
    """The output this panel should size itself for.

    Niri opens a new layer surface on the focused output, so the monitor under
    the pointer is a better guess than Wayland's "primary" (which GTK resolves to
    the first monitor). Everything falls back to the previous behaviour when the
    seat or the point lookup is unavailable.
    """
    try:
        seat = display.get_default_seat()
        pointer = seat.get_pointer() if seat is not None else None
        if pointer is not None:
            _, x, y = pointer.get_position()
            monitor = display.get_monitor_at_point(x, y)
            if monitor is not None:
                return monitor
    except (AttributeError, TypeError, ValueError):
        pass
    return display.get_primary_monitor() or display.get_monitor(0)


def label(text, css=None, wrap=False, *, localize=True):
    widget = Gtk.Label(label=tr_legacy(text) if localize else text, xalign=0)
    if css:
        widget.get_style_context().add_class(css)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return widget


def box(vertical=True, spacing=10, css=None):
    widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
                     spacing=spacing)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def button(text, callback, css=None, tooltip=None):
    widget = Gtk.Button(label=tr_legacy(text)) if text else Gtk.Button()
    widget.connect("clicked", lambda _: callback())
    if css:
        widget.get_style_context().add_class(css)
    if tooltip:
        widget.set_tooltip_text(tr_legacy(tooltip))
    return widget


def pack(parent, child, expand=False):
    parent.pack_start(child, expand, expand, 0)
    return child


def scroller(child):
    widget = Gtk.ScrolledWindow()
    widget.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    widget.set_overlay_scrolling(False)
    widget.set_shadow_type(Gtk.ShadowType.NONE)
    widget.add(child)
    return widget
