#!/usr/bin/env python3
"""Native settings windows and layer-shell panels, without a browser runtime."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time

import gi
from drawers import BoundedCanvas
from panel_motion import PanelMotion, animations_enabled, configure_stack
from page_host import PageEntry, PageHost, PageMap, PageSpec
from background_tasks import READ_POOL
from surface_registry import CONTROL_MODES, DRAWER_SIDES, SURFACE_COPY, SURFACE_KEYS
from i18n import tr, tr_legacy
from navigation_catalog import PAGE_KEYS, PAGES
from settings_navigation import SettingsNavigation
from control_widgets import prepare_icon_theme
from scroll_guard import protect as protect_scroll, handle as handle_scroll

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango

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


class Tasks:
    """Application-level lifetime for work that must not be truncated.

    Closing the window ends the interface, not a settings transaction: the
    application stays alive until every side-effecting task has finished, so a
    multi-step commit and its failure rollback both complete. Read-only tasks do
    not hold the process; their results are simply dropped with it.
    """

    def __init__(self, application):
        self.application = application
        self.lock = threading.Lock()
        self.active = 0
        self.finish_requested = False

    def begin(self):
        with self.lock:
            self.active += 1
        # hold/release always run on the GTK main thread: begin() is called from
        # a widget callback and end() from the idle callback registered in work().
        self.application.hold()

    def end(self):
        with self.lock:
            self.active = max(0, self.active - 1)
            quit_now = self.finish_requested and not self.active
        self.application.release()
        if quit_now:
            self.application.quit()

    def request_finish(self):
        """Return True when nothing is left to commit and the app may quit."""
        with self.lock:
            self.finish_requested = True
            return not self.active

    def resume(self):
        """A window exists again, so a pending finish request is withdrawn.

        Without this the flag stays set for the rest of the process and the next
        completed commit would quit an application that is in use again.
        """
        with self.lock:
            self.finish_requested = False


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app, mode):
        requested_tab = mode if mode in PAGE_KEYS else "quick"
        mode = "control" if mode in CONTROL_MODES else mode
        super().__init__(application=app, title=f"Selandia · {mode}")
        self.mode = mode
        self.alive = True
        self.closing = False
        self._close_callback = None
        self.drawer_side = DRAWER_SIDES.get(mode)
        app.tasks.resume()
        from appearance import load_settings
        preferences = load_settings()
        self.reduced_motion = preferences.get("reduced_motion", False)
        self.get_settings().set_property("gtk-application-prefer-dark-theme", preferences.get("color_mode", "dark") == "dark")
        self.active_popover = None
        self.pending = set()
        self.quick_tick_source = None
        self.audio_tick_source = None
        self.metrics_tick_source = None
        self.page_host = None
        self.connect("destroy", self.on_destroy)
        self.connect("unmap", self.on_unmap)
        self.connect("key-press-event", self.on_key)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.get_style_context().add_class("glass-window")
        if not animations_enabled(self, not self.reduced_motion):
            self.get_style_context().add_class("reduce-motion")
        if mode == "control":
            self.get_style_context().add_class("control-center-window")
        display = Gdk.Display.get_default()
        monitor = panel_monitor(display)
        geometry = monitor.get_geometry()
        font_size = preferences.get("font_size", 16)
        from panel_geometry import dimensions, drawer_geometry
        if self.drawer_side:
            width, height, drawer_top = drawer_geometry(
                self.drawer_side, geometry.width, geometry.height, font_size)
        else:
            width, height = dimensions(mode, geometry.width, geometry.height)
            drawer_top = None
        self.panel_width = width
        self.available_height = height if self.drawer_side else geometry.height - 82
        self.drawer_top = drawer_top
        self.drawer_travel = (-width if self.drawer_side == "left" else width) if self.drawer_side else 0
        self.set_default_size(width, height)
        self.set_size_request(width, -1 if self.drawer_side else
                              height if mode in ("shortcuts", "control") else -1)
        # Settings must participate in normal window stacking: native choosers,
        # authentication agents and other applications can open above them.
        if mode != "control" and GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, f"selandia-{mode}")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
            # Overlays retain monitor-relative placement; the bar reservation
            # applies to ordinary application windows, not these panels.
            GtkLayerShell.set_exclusive_zone(self, -1)
            GtkLayerShell.set_monitor(self, monitor)
            # Drawers attach to one side; their native allocation stays fixed
            # while PanelMotion slides only the painted child.
            if self.drawer_side:
                edge = (GtkLayerShell.Edge.LEFT if self.drawer_side == "left"
                        else GtkLayerShell.Edge.RIGHT)
                GtkLayerShell.set_anchor(self, edge, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
                GtkLayerShell.set_margin(self, edge, 16)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, drawer_top)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 16)
        else:
            self.set_position(Gtk.WindowPosition.CENTER)
        self.surface = box(spacing=0, css="glass-surface")
        self.drawer_host = None
        if self.drawer_side:
            self.drawer_host = BoundedCanvas(width, height)
            self.add(self.drawer_host)
            self.surface.set_size_request(width, height)
            self.drawer_host.set_child(self.surface)
        elif mode == "control":
            # A paint-through overlay keeps the 1 px shell above child cards,
            # so their backgrounds cannot clip or erase the rounded outline.
            self.shell = Gtk.Overlay()
            self.add(self.shell)
            self.shell.add(self.surface)
            self.frame = Gtk.Box()
            self.frame.set_halign(Gtk.Align.FILL)
            self.frame.set_valign(Gtk.Align.FILL)
            self.frame.set_hexpand(True)
            self.frame.set_vexpand(True)
            self.frame.set_can_focus(False)
            self.frame.get_style_context().add_class("panel-frame")
            self.shell.add_overlay(self.frame)
            try:
                Gtk.Overlay.set_overlay_pass_through(self.shell, self.frame, True)
            except AttributeError:
                pass
        else:
            self.add(self.surface)
        offset_setter = None
        if self.drawer_host is not None:
            offset_setter = self.drawer_host.move_child
        self.motion = PanelMotion(self.surface, enabled=lambda: not self.reduced_motion,
                                  offset_setter=offset_setter, travel=self.drawer_travel)
        if self.drawer_host is not None:
            # Start offscreen and transparent so the first mapped frame cannot
            # flash at the final position before on_map starts the reveal.
            self.surface.set_opacity(0.0)
            self.drawer_host.move_child(self.drawer_travel)
        self.connect("map", self.on_map)
        if mode == "control":
            title, subtitle = "Control Center", "控制中心  ·  Your desktop, at a touch"
        else:
            copy = SURFACE_COPY[mode]
            title, subtitle = tr(copy[0], copy[1]), tr(copy[2], copy[3])
        header = pack(self.surface, box(False, 12, "panel-header"))
        titles = pack(header, box(spacing=4), True)
        if mode == "control":
            header.get_style_context().add_class("control-header")
            pack(titles, label(tr("Settings", "设置"), "control-heading"))
            pack(titles, label(f"{platform.node()} · Niri", "control-caption"))
        else:
            pack(titles, label("S E L A N D I A", "eyebrow"))
            pack(titles, label(title, "panel-title"))
            pack(titles, label(subtitle, "subtitle"))
        if mode == "control":
            badge = pack(header, label(tr("●  LIVE", "●  实时"), "live-badge"))
            badge.set_valign(Gtk.Align.START)
            help_button = pack(header, button("?", lambda: self.show_keyboard_help(help_button),
                                              "close-button", "Keyboard help · 键盘操作  F1"))
            self.help_button = help_button
            help_button.set_valign(Gtk.Align.START)
        close = pack(header, button("×", self.request_close, "close-button", "Close · 关闭  Esc"))
        close.set_valign(Gtk.Align.START)
        self.content = pack(self.surface, box(spacing=12, css="panel-content"), True)
        self.status = label("", "status", wrap=True)
        self.status.set_no_show_all(True)
        self.status.set_margin_start(22)
        self.status.set_margin_end(22)
        self.status.set_margin_bottom(14)
        pack(self.surface, self.status)
        if mode == "control":
            self.build_control()
            self.protect_scroll_controls(self.content)
            self.control_stack.show_all()
            self.select_control_tab(requested_tab)
        elif mode == "shortcuts":
            self.build_shortcuts()
        elif mode == "calendar":
            self.build_calendar()
        else:
            self.build_ai()

    def build_calendar(self):
        from calendar_widget import LocalizedCalendar
        self.content.get_style_context().add_class("calendar-page")
        if self.panel_width < 360:
            self.content.get_style_context().add_class("calendar-narrow")
        body = box(spacing=12, css="calendar-body")
        pack(self.content, scroller(body), True)
        calendar_card = box(spacing=0, css="card")
        calendar_card.get_style_context().add_class("calendar-card")
        pack(body, calendar_card)
        self.calendar = LocalizedCalendar()
        self.calendar.set_hexpand(True)
        pack(calendar_card, self.calendar)
        # Keep Today/Copy reachable while only the calendar grid scrolls in a
        # short viewport or at a large font size.
        footer = pack(self.content, box(spacing=12, css="card"))
        footer.set_margin_top(12)
        footer.get_style_context().add_class("calendar-footer")
        self.calendar_date = pack(footer, label("", "calendar-date"))
        self.calendar_date.set_ellipsize(Pango.EllipsizeMode.END)
        self.calendar_date.set_max_width_chars(10)

        def get_formatted_date():
            year, month, day = self.calendar.get_date()
            return f"{year:04d}-{month+1:02d}-{day:02d}"

        def selected(*_):
            self.calendar_date.set_text(get_formatted_date())

        def today():
            date = datetime.date.today()
            self.calendar.select_month(date.month - 1, date.year)
            self.calendar.select_day(date.day)

        def copy_date():
            date_str = get_formatted_date()
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(date_str, -1)
            clipboard.store()
            self.feedback(tr(f"Copied {date_str} to clipboard", f"已复制 {date_str} 到剪贴板"))

        self.calendar.connect("day-selected", selected)
        actions = pack(footer, box(self.panel_width < 360, 8, "calendar-actions"), True)
        for title, callback, css in (
                (tr("Today", "今天"), today, "calendar-primary"),
                (tr("Copy Date", "复制日期"), copy_date, "calendar-secondary")):
            pack(actions, button(title, callback, css), True)
        selected()

    def on_destroy(self, *_):
        self.alive = False
        self.closing = False
        self._close_callback = None
        popover = getattr(self, "active_popover", None)
        if popover is not None:
            popover.popdown()
            self.active_popover = None
        host = getattr(self, "page_host", None)
        if host is not None:
            host.dispose()
            self.page_host = None
        changes = getattr(self, 'audio_changes', None)
        if changes is not None:
            self.audio_changes = None
            changes.close()
            thread = changes.thread
            # Join only a worker that was started; an unstarted thread raises in
            # the cleanup task. commit=True keeps the process alive until the
            # child is reaped without blocking GTK or a settings commit.
            if thread.ident is not None:
                self.work(lambda: thread.join(3), commit=True)
        for source in tuple(self.pending):
            GLib.source_remove(source)
        self.pending.clear()
        if not getattr(self, "rebuilding", False):
            # A pending commit keeps the application alive until it is complete;
            # this window itself never waits for it.
            self.get_application().request_finish()

    def request_close(self, on_finished=None):
        if not self.alive or getattr(self, "closing", False):
            return
        popover = getattr(self, "active_popover", None)
        if popover is not None:
            popover.popdown()
            self.active_popover = None
        self.closing = True

        def finished():
            if not self.alive:
                return
            self._close_callback = None
            if on_finished is not None:
                on_finished()
            self.destroy()

        self._close_callback = finished
        self.motion.dismiss(finished)

    def reopen(self):
        """Reverse a close in progress on the same live window."""
        if not self.alive:
            return False
        self._close_callback = None
        self.closing = False
        self.motion.reveal()
        if not self.get_visible():
            self.show_all()
        self.present()
        self._refresh_drawer()
        return True

    def _refresh_drawer(self):
        if self.mode == "calendar" and getattr(self, "calendar", None) is not None:
            self.calendar.refresh_today()
        elif self.mode == "ai" and getattr(self, "input", None) is not None:
            if self.get_focus() is None:
                GLib.idle_add(self.input.grab_focus)

    def on_unmap(self, *_):
        if self.mode == "control" and self.alive and self.page_host is not None:
            name = self.control_stack.get_visible_child_name()
            if name is not None:
                self._page_hidden(name)

    def on_map(self, *_):
        if not self.alive:
            return
        self.motion.reveal()
        if self.mode == "control":
            self.focus_control_tab()
            name = self.control_stack.get_visible_child_name()
            if self.page_host is not None and name in self.page_host.entries:
                self._page_shown(name)
            else:
                self.refresh_visible_page()
        else:
            self._refresh_drawer()

    def focus_control_tab(self):
        self.navigation.focus_current()

    def show_popover(self, anchor, content):
        if self.active_popover:
            self.active_popover.popdown()
        popover = Gtk.Popover.new(anchor)
        popover.get_style_context().add_class("control-popover")
        content.set_border_width(14)
        popover.add(content)
        self.active_popover = popover
        def closed(*_):
            if self.active_popover is popover:
                self.active_popover = None
            anchor.grab_focus()
        popover.connect("closed", closed)
        popover.show_all()
        popover.popup()
        content.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def show_keyboard_help(self, anchor):
        content = box(spacing=8)
        pack(content, label("键盘操作 · Keyboard", "section-title"))
        for instruction in (tr("Ctrl + F  Search settings", "Ctrl + F  搜索设置"),
                            tr("Ctrl + 1…9  Select page", "Ctrl + 1…9  切换页面"),
                            tr("Ctrl + Tab  Next page", "Ctrl + Tab  下一页"),
                            tr("Tab / Shift + Tab  Move focus", "Tab / Shift + Tab  移动焦点"),
                            tr("Space / Enter  Activate", "Space / Enter  激活"),
                            tr("← →  Adjust slider", "← →  调节滑块"),
                            tr("Esc  Back, then close", "Esc  返回总览，再关闭")):
            pack(content, label(instruction, "hint"))
        self.show_popover(anchor, content)

    def protect_scroll_controls(self, widget):
        """Scrolling a settings page must not silently edit the hovered control."""
        protect_scroll(widget)

    def on_control_scroll(self, widget, event):
        return handle_scroll(widget, event)

    def show_connection_details(self, key, anchor):
        self.select_control_tab("network", focus=True)

    def on_key(self, _widget, event):
        if self.mode == "control":
            if event.keyval == Gdk.KEY_F1:
                self.show_keyboard_help(self.help_button)
                return True
            if event.state & Gdk.ModifierType.CONTROL_MASK:
                if event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
                    self.navigation.search.grab_focus()
                    return True
                if Gdk.KEY_1 <= event.keyval <= Gdk.KEY_9:
                    self.select_control_tab(self.control_pages[event.keyval - Gdk.KEY_1], focus=True)
                    return True
                if event.keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
                    direction = -1 if event.state & Gdk.ModifierType.SHIFT_MASK else 1
                    index = self.control_pages.index(self.control_stack.get_visible_child_name())
                    self.select_control_tab(self.control_pages[(index + direction) % len(self.control_pages)], focus=True)
                    return True
        if self.mode == "ai" and (event.state & Gdk.ModifierType.CONTROL_MASK):
            if event.keyval in (Gdk.KEY_period, Gdk.KEY_KP_Decimal):
                self.stop_chat()
                return True
        if event.keyval == Gdk.KEY_Escape:
            if self.active_popover:
                self.active_popover.popdown()
            elif self.mode == "control" and self.navigation.search.get_text():
                self.navigation.search.set_text("")
                self.focus_control_tab()
            elif self.mode == "control" and self.control_stack.get_visible_child_name() != "quick":
                self.select_control_tab("quick", focus=True)
            elif self.mode == "control" and self.quick_details_button.get_active():
                self.quick_details_button.set_active(False)
                self.quick_details_button.grab_focus()
            else:
                self.request_close()
            return True
        return False

    def feedback(self, text="", error=False):
        if not self.alive:
            return
        self.status.set_text(tr_legacy(text))
        context = self.status.get_style_context()
        (context.add_class if error else context.remove_class)("error")
        self.status.set_visible(bool(text))

    def work(self, task, done=None, error=None, *, commit=False):
        """Run every subprocess/network operation away from GTK's event loop.

        ``commit=True`` marks a task with side effects (a settings transaction,
        a hardware change). Such a task keeps the application alive so closing
        the window cannot truncate it; read-only tasks end with the process.
        """
        registry = self.get_application().tasks
        if commit:
            registry.begin()
        finished = False

        def finish(result, exception):
            nonlocal finished
            if not finished:
                finished = True
                if commit:
                    registry.end()
            if not self.alive:
                return GLib.SOURCE_REMOVE
            if exception:
                if error:
                    error(exception)
                else:
                    self.feedback(f"Could not complete · 操作失败: {exception}", True)
            elif done:
                done(result)
            return GLib.SOURCE_REMOVE

        def run():
            try:
                result = task()
            except Exception as exception:
                GLib.idle_add(finish, None, str(exception))
            else:
                GLib.idle_add(finish, result, None)
        if commit:
            try:
                threading.Thread(target=run, daemon=True).start()
            except RuntimeError as exception:
                GLib.idle_add(finish, None, str(exception))
        else:
            try:
                READ_POOL.submit(run, valid=lambda: self.alive)
            except RuntimeError as exception:
                GLib.idle_add(finish, None, str(exception))

    def action(self, command):
        self.feedback("Applying… · 正在应用…")
        def failed(error):
            self.feedback(f"Could not complete · 操作失败: {error}", True)
            self.refresh_control()
        self.work(command if callable(command) else lambda: capture(command, timeout=12),
                  lambda _: (self.feedback("Updated · 已更新"), self.refresh_control()), failed, commit=True)

    def launch(self, command):
        """Unmap before launch so screenshots and external dialogs get a clear stage."""
        self.hide()

        def failed(error):
            self.show()
            self.feedback(error, True)

        def start():
            self.pending.discard(source)
            self.work(lambda: subprocess.Popen(command, start_new_session=True,
                                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL),
                      lambda _: self.destroy(), failed, commit=True)
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add(120, start)
        self.pending.add(source)

    def desktop(self, *args):
        self.launch([DESKTOP, *args])

    def card(self, parent, title=None):
        card = pack(parent, box(spacing=10, css="card"))
        if title:
            pack(card, label(title, "section-title"))
        return card

    def build_control(self):
        self.refreshing = False
        self.manual_control_refresh = False
        self.state = {}
        self.updating_scales = False
        self.scale_timers = {}
        self.dragging_scales = set()
        self.brightness_busy = False
        self.brightness_target = None
        self.brightness_devices = {}
        self.control_stack = Gtk.Stack()
        configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
        self.control_stack.set_hhomogeneous(False)
        self.control_stack.set_vhomogeneous(False)
        self.control_pages = PAGE_KEYS
        narrow = self.panel_width < 650
        columns = pack(self.content, box(narrow, 4 if narrow else 18), True)
        self.navigation = SettingsNavigation(self)
        if narrow:
            self.navigation.set_size_request(-1, 110)
        self.control_switcher = self.navigation.list
        pack(columns, self.navigation)
        pages = pack(columns, box(spacing=4 if narrow else 12), True)
        self.page_heading = pack(pages, label("", "settings-page-title"))
        self.page_heading.set_no_show_all(True)
        pack(pages, self.control_stack, True)
        self.quick_sampler = None
        titles = {key: tr(english, chinese) for key, english, chinese, *_ in PAGES}
        specs = [PageSpec(key, titles[key], lambda k=key: self._page_factory(k))
                 for key in PAGE_KEYS]
        self.page_host = PageHost(self, self.control_stack, specs)
        settings_keys = tuple(key for key in PAGE_KEYS
                              if key not in ("quick", "sound", "displays", "appearance",
                                             "wallpapers", "system"))
        self.settings_pages = PageMap(self.page_host, settings_keys)

    def _page_factory(self, key):
        if key == "quick":
            return self._build_quick()
        if key == "sound":
            return self._build_sound()
        if key == "system":
            return self._build_system()
        if key == "displays":
            return self._build_displays()
        if key == "appearance":
            return self._build_appearance()
        if key == "wallpapers":
            return self._build_wallpapers()
        return self._build_settings_page(key)

    def _build_quick(self):
        from metrics import MetricsSampler
        from quick_controls import build_overview
        self.quick_sampler = MetricsSampler(detailed=False, enable_nvidia=False)
        self.quick_sampler.prime()
        body = build_overview(self)
        revealer = getattr(self, "quick_details_revealer", None)
        if revealer is not None:
            revealer.set_transition_duration(
                180 if animations_enabled(self.surface, not self.reduced_motion) else 0)
        return PageEntry(body, scroller(body))

    def build_sound(self):
        """Compatibility adapter for the former eager page builder."""
        if self.page_host is not None:
            return self.page_host.ensure("sound").content
        return self._build_sound().content

    def build_system(self):
        """Compatibility adapter for the former eager page builder."""
        if self.page_host is not None:
            return self.page_host.ensure("system").content
        return self._build_system().content

    def build_appearance(self):
        """Compatibility adapter for the former eager page builder."""
        if self.page_host is not None:
            return self.page_host.ensure("appearance").content
        return self._build_appearance().content

    def _build_displays(self):
        from display_controls import DisplaySettings
        page = DisplaySettings(self)
        return PageEntry(page, scroller(page))

    def _build_wallpapers(self):
        from wallpaper_controls import WallpaperControls
        page = WallpaperControls(self)
        return PageEntry(page, page)

    def _build_settings_page(self, key):
        from desktop_controls import InputSettings, DesktopSettings
        from language_controls import LanguageSettings
        from system_controls import (ApplicationsSettings, PowerSettings, TimeSettings,
                                     StartupSettings, ServicesSettings, ToolsSettings,
                                     ConnectionsSettings, NotificationSettings)
        factories = {
            "input": InputSettings, "desktop": DesktopSettings,
            "language": LanguageSettings, "applications": ApplicationsSettings,
            "power": PowerSettings, "time": TimeSettings,
            "startup": StartupSettings, "services": ServicesSettings,
            "network": ConnectionsSettings,
            "notifications": NotificationSettings,
        }
        if key in ("hardware", "security"):
            page = ToolsSettings(self, key)
        else:
            page = factories[key](self)
        return PageEntry(page, scroller(page))

    @property
    def display_settings(self):
        return self.page_host.page("displays")

    @property
    def wallpaper_controls(self):
        return self.page_host.page("wallpapers")

    def page_visible(self, name):
        return (self.alive and self.mode == 'control' and self.get_mapped()
                and self.control_stack.get_visible_child_name() == name)

    def _refresh_page(self, name):
        if self.page_visible('quick'):
            self.refresh_control()
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "refresh"):
                media.refresh()
        elif self.page_visible('sound'):
            self.refresh_audio()
        elif self.page_visible('system'):
            self.refresh_system_info()
            # Prime a fresh baseline in the worker and sample 50 ms later, so
            # the first visible CPU/network values are real rates rather than a
            # dash followed by a two-second wait.
            self.refresh_metrics(prime=True)

    def refresh_visible_page(self, *_):
        name = self.control_stack.get_visible_child_name()
        if name is None:
            return
        refresh = getattr(self, "_refresh_page", None)
        if refresh is not None:
            refresh(name)
            return
        # Narrow compatibility for test/direct doubles that only provide the
        # legacy page-visible methods.
        if self.page_visible('quick'):
            self.refresh_control()
            self.media_controls.refresh()
        elif self.page_visible('sound'):
            self.refresh_audio()
        elif self.page_visible('system'):
            self.refresh_system_info()
            self.refresh_metrics(prime=True)

    def _page_shown(self, name):
        if not self.page_visible(name):
            return
        if name == 'quick':
            self.refresh_control()
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "resume"):
                media.resume()
            self.start_quick_tick()
        elif name == 'sound':
            self.refresh_audio()
            self.start_audio_tick()
        elif name == 'system':
            self.refresh_system_info()
            self.refresh_metrics(prime=True)
            self.start_metrics_tick()
        elif name == 'wallpapers' and self.page_host is not None:
            entry = self.page_host.entries.get('wallpapers')
            if entry is not None:
                entry.content.resume()

    def _page_hidden(self, name):
        if name == 'quick':
            self.stop_quick_tick()
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "suspend"):
                media.suspend()
        elif name == 'sound':
            self.stop_audio_tick()
            changes = getattr(self, 'audio_changes', None)
            if changes is not None:
                self.audio_changes = None
                changes.close()
                thread = changes.thread
                if thread.ident is not None:
                    self.work(lambda: thread.join(3), commit=True)
        elif name == 'system':
            self.metrics_generation = getattr(self, 'metrics_generation', 0) + 1
            self.stop_metrics_tick()
        elif name == 'wallpapers' and self.page_host is not None:
            entry = self.page_host.entries.get('wallpapers')
            if entry is not None:
                entry.content.suspend()

    def _page_dispose(self, name):
        self._page_hidden(name)
        if name == 'quick':
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "dispose"):
                media.dispose()
        elif name == 'wallpapers' and self.page_host is not None:
            entry = self.page_host.entries.get('wallpapers')
            if entry is not None:
                entry.content.cleanup()

    def start_quick_tick(self):
        if self.quick_tick_source is None and self.alive:
            self.quick_tick_source = GLib.timeout_add_seconds(5, self.refresh_control)
            self.pending.add(self.quick_tick_source)

    def stop_quick_tick(self):
        source = self.quick_tick_source
        self.quick_tick_source = None
        if source is not None:
            self.pending.discard(source)
            GLib.source_remove(source)

    def select_control_tab(self, tab, focus=False):
        if self.mode == "control" and tab in self.control_pages:
            configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
            if self.page_host is not None:
                self.page_host.ensure(tab)
            self.control_stack.set_visible_child_name(tab)
            self.navigation.select(tab, focus=focus)
            spec = next(item for item in PAGES if item[0] == tab)
            self.page_heading.set_text(tr(spec[1], spec[2]))
            self.page_heading.set_visible(self.panel_width >= 650 or tab != "wallpapers")
            if focus:
                self.focus_control_tab()

    def language_changed(self, *_):
        # Recreate this settings window through the application. Preserve the
        # selected page; never terminate another process or discard an AI chat.
        app = self.get_application()
        tab = self.control_stack.get_visible_child_name()
        def update():
            from ui_assets import write
            write()
            try:
                capture([DESKTOP, "reload"], timeout=20)
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                return str(error)
            return None
        def done(error):
            app.rebuild_control(tab)
            if error:
                app.window.feedback(tr("Language saved; some components could not reload: ",
                                       "语言已保存，部分组件未能重载：") + error, True)
        self.work(update, done, commit=True)

    def compact_label(self, text="", css="hint"):
        widget = label(text, css, wrap=True)
        widget.set_max_width_chars(34)
        return widget

    @staticmethod
    def audio_placeholder(combo, text):
        """Show what the disabled combo is waiting for instead of a blank row."""
        combo.append("", tr_legacy(text))
        combo.set_active(0)

    def audio_combo(self):
        combo = Gtk.ComboBoxText()
        combo._audio_rows = ()
        for renderer in combo.get_cells():
            if isinstance(renderer, Gtk.CellRendererText):
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                renderer.set_property("max-width-chars", 25)
        combo.connect("notify::popup-shown", self.audio_popup_changed)
        return combo

    def audio_popup_changed(self, combo, _property):
        if combo.get_property("popup-shown") or not self.alive:
            return
        # GTK can still be dispatching the selection event as the popup closes.
        # Apply the latest snapshot on the next loop turn, after that selection.
        def finish():
            self.pending.discard(source)
            if self.alive and self.audio_deferred_state is not None:
                state = self.audio_deferred_state
                self.audio_deferred_state = None
                self.apply_audio(state)
            return GLib.SOURCE_REMOVE
        source = GLib.idle_add(finish)
        self.pending.add(source)

    @staticmethod
    def audio_set_choices(combo, rows, preferred=None, fallback=None):
        rows = tuple(rows)
        selected = preferred if preferred is not None else combo.get_active_id()
        names = {name for name, _title in rows}
        if selected not in names:
            selected = fallback if fallback in names else (rows[0][0] if rows else None)
        if combo._audio_rows != rows:
            combo.remove_all()
            for name, title in rows:
                combo.append(name, title)
            combo._audio_rows = rows
        if combo.get_active_id() != selected:
            if selected is None:
                combo.set_active(-1)
            else:
                combo.set_active_id(selected)
        combo.set_sensitive(bool(rows))

    @staticmethod
    def audio_device_title(device):
        title = device.get("description") or device["name"]
        if device.get("availability") == "unavailable":
            title += tr(" · Disconnected", " · 未连接")
        elif device.get("kind") == "monitor":
            title += tr(" · Monitor", " · 回录")
        elif device.get("kind") == "virtual":
            title += tr(" · Virtual", " · 虚拟")
        elif device.get("kind") == "pro":
            title += tr(" · Pro channel", " · 专业通道")
        return title

    def _build_sound(self):
        self.audio_state = {}
        self.audio_busy = False
        self.audio_loading = False
        self.audio_updating = False
        self.audio_generation = 0
        self.audio_timers = {}
        self.audio_dragging = set()
        self.audio_profile_dirty = False
        self.audio_deferred_state = None
        self.audio_devices = {}
        self.audio_ports = {}
        self.audio_volumes = {}
        self.audio_values = {}
        self.audio_mutes = {}
        self.audio_device_apply = {}
        self.audio_port_apply = {}
        self.audio_device_notes = {}
        self.audio_port_devices = {}
        self.audio_port_rows = {}
        body = box(spacing=12)
        self.audio_status = pack(body, self.compact_label(tr_legacy("Reading audio devices… · 读取音频设备…")))
        # The connected status is normally two lines; reserve that height so the
        # cards below do not jump when the first read replaces the placeholder.
        self.audio_status.set_lines(2)
        from application_audio import ApplicationAudioControls
        self.application_audio = pack(body, ApplicationAudioControls(self))
        self.audio_advanced = Gtk.CheckButton.new_with_label(tr_legacy("显示高级通道 · Show all audio channels"))
        self.audio_advanced.set_tooltip_text(tr_legacy("包括未连接接口、专业通道、虚拟设备与回录通道。\nIncludes disconnected ports, Pro Audio, virtual and monitor channels."))
        self.audio_advanced.connect("toggled", self.audio_advanced_changed)
        pack(body, self.audio_advanced)
        self.audio_controls = pack(body, box(spacing=12))
        for kind, heading in [("sink", tr_legacy("OUTPUT  /  输出设备")), ("source", tr_legacy("INPUT  /  输入设备"))]:
            card = self.card(self.audio_controls, heading)
            combo = self.audio_combo()
            self.audio_placeholder(combo, "Detecting audio devices… · 正在检测音频设备…")
            self.audio_devices[kind] = pack(card, combo)
            combo.connect("changed", self.audio_device_changed, kind)
            selection = pack(card, box(False, 8))
            self.audio_device_notes[kind] = pack(selection, self.compact_label(), True)
            self.audio_device_apply[kind] = pack(selection, button(tr_legacy("使用 · Use"),
                lambda k=kind: self.audio_use_device(k), "small-button", tr_legacy("设为默认设备 · Use as default")))
            row = pack(card, box(False, 8))
            self.audio_values[kind] = pack(row, label("—", "value"), True)
            self.audio_mutes[kind] = pack(row, button(tr_legacy("Mute · 静音"), lambda k=kind: self.audio_toggle_mute(k), "small-button"))
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            scale.set_draw_value(False)
            scale.connect("value-changed", self.audio_volume_changed, kind)
            scale.connect("button-press-event", lambda _w, _e, k=kind: self.audio_dragging.add(k) or False)
            scale.connect("button-release-event", lambda _w, _e, k=kind: self.audio_dragging.discard(k) or False)
            scale.connect("focus-out-event", lambda _w, _e, k=kind: self.audio_dragging.discard(k) or False)
            self.audio_volumes[kind] = pack(card, scale)
            port_row = pack(card, box(spacing=6))
            port_row.set_no_show_all(True)
            self.audio_port_rows[kind] = port_row
            pack(port_row, label(tr_legacy("Port · 接口"), "hint"))
            ports = self.audio_combo()
            self.audio_ports[kind] = pack(port_row, ports)
            ports.connect("changed", self.audio_port_changed, kind)
            self.audio_port_apply[kind] = pack(port_row, button(tr_legacy("应用接口 · Apply port"),
                lambda k=kind: self.audio_apply_port(k), "small-button"))
            for child in port_row.get_children():
                child.show_all()
            pack(card, button(tr_legacy("Route active apps here · 将运行中的应用切换至此"),
                              lambda k=kind: self.audio_move_streams(k), "small-button"))
        profiles = self.card(self.audio_controls, tr_legacy("DEVICE PROFILE  /  声卡模式"))
        self.audio_card_combo = self.audio_combo()
        self.audio_profile_combo = self.audio_combo()
        self.audio_placeholder(self.audio_card_combo, "Detecting sound cards… · 正在检测声卡…")
        self.audio_placeholder(self.audio_profile_combo, "Detecting profiles… · 正在检测配置…")
        pack(profiles, self.audio_card_combo)
        pack(profiles, self.audio_profile_combo)
        self.audio_card_combo.connect("changed", self.audio_card_changed)
        self.audio_profile_combo.connect("changed", self.audio_profile_changed)
        self.audio_profile_apply = pack(profiles, button(tr_legacy("Apply profile · 应用设备配置"), self.audio_apply_profile))
        self.audio_profile_recommend = pack(profiles, button(tr_legacy("使用推荐桌面模式 · Use desktop profile"),
            self.audio_apply_recommended_profile, "accent-button"))
        self.audio_profile_recommend.set_no_show_all(True)
        self.audio_profile_note = pack(profiles, self.compact_label())
        pack(profiles, self.compact_label(tr_legacy("模式决定模拟、数字或蓝牙连接；Off 会关闭该声卡。\nProfiles select analog, digital or Bluetooth modes; Off disables the card.")))
        pack(body, self.compact_label(tr_legacy("选择后点击「设为默认」或「应用接口」。音量和静音控制当前所选设备。\nConfirm device and port changes with the buttons. Volume and mute affect the selected device.")))
        pack(body, button(tr("Advanced mixer", "高级混音器"),
                          lambda: self.desktop("launch", "audio"), "accent-button"))
        self.audio_refresh_button = pack(body, button(tr_legacy("Refresh audio devices · 刷新音频设备"), self.refresh_audio))
        self.audio_controls.set_sensitive(False)
        self.audio_changes = None
        self.audio_refresh_at = 0
        return PageEntry(body, scroller(body))

    def start_audio_tick(self):
        if self.audio_tick_source is None and self.alive:
            self.audio_tick_source = GLib.timeout_add(250, self.tick_audio)
            self.pending.add(self.audio_tick_source)

    def stop_audio_tick(self):
        source = self.audio_tick_source
        self.audio_tick_source = None
        if source is not None:
            self.pending.discard(source)
            GLib.source_remove(source)

    def tick_audio(self):
        if not self.alive:
            return GLib.SOURCE_REMOVE
        # A read or a committing audio action already owns the next refresh.
        # Keeping pending events through both is refresh_audio's job, so this
        # 250 ms tick must not call into it repeatedly while they are busy.
        if (not self.page_visible('sound') or self.audio_loading
                or self.audio_busy):
            return GLib.SOURCE_CONTINUE
        if (self.audio_changes is None
                or self.audio_changes.changed.is_set()
                or time.monotonic() >= self.audio_refresh_at):
            self.refresh_audio()
        return GLib.SOURCE_CONTINUE

    def audio_advanced_changed(self, _check):
        self.audio_generation += 1
        self.audio_deferred_state = None
        self.refresh_audio()

    def refresh_audio(self):
        if not self.alive:
            return GLib.SOURCE_REMOVE
        if not self.page_visible('sound'):
            return GLib.SOURCE_CONTINUE
        if self.audio_loading or self.audio_busy:
            return GLib.SOURCE_CONTINUE
        if self.audio_changes is None:
            from audio_events import AudioChanges
            self.audio_changes = AudioChanges(threading.Event(), facilities=(
                'sink', 'source', 'server', 'card', 'sink-input', 'source-output'))
            self.audio_changes.thread.start()
        self.audio_changes.changed.clear()
        self.audio_refresh_at = time.monotonic() + 30
        from audio_backend import read_state
        self.audio_loading = True
        refresh_button = getattr(self, 'audio_refresh_button', None)
        if refresh_button is not None:
            refresh_button.set_sensitive(False)
        generation = self.audio_generation
        advanced = self.audio_advanced.get_active()

        def done(state):
            self.audio_loading = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            if generation == self.audio_generation and not self.audio_busy:
                self.apply_audio(state)
            elif not self.audio_busy:
                self.refresh_audio()

        def failed(error):
            self.audio_loading = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            if generation == self.audio_generation and not self.audio_busy:
                self.audio_controls.set_sensitive(False)
                message = str(error)
                lower = message.lower()
                if any(token in lower for token in ("connection refused", "connection failure", "pa_context_connect")):
                    friendly = (tr("Audio service unavailable", "音频服务不可用") + "\n" +
                                tr("Start PipeWire or reconnect to your session.", "请启动 PipeWire 或重新连接当前会话。"))
                else:
                    friendly = tr("Audio unavailable", "音频不可用") + f"\n{message}"
                self.application_audio.update([], [friendly])
                self.audio_status.set_text(friendly)
                self.audio_status.set_tooltip_text(message)
                self.audio_deferred_state = None
                self.audio_updating = True
                try:
                    # An initial failed read has finished. Do not leave a
                    # disabled selector claiming it is still detecting devices.
                    for combo in (*self.audio_devices.values(), *self.audio_ports.values(),
                                  self.audio_card_combo, self.audio_profile_combo):
                        self.audio_set_choices(combo, [("", tr("Audio unavailable", "音频不可用"))])
                finally:
                    self.audio_updating = False
            elif not self.audio_busy:
                self.refresh_audio()
        self.work(lambda: read_state(include_unavailable=advanced), done, failed)
        return GLib.SOURCE_CONTINUE

    def apply_audio(self, state):
        self.application_audio.update(state.get("streams", []), state.get("stream_errors", []))
        combos = [*self.audio_devices.values(), *self.audio_ports.values(),
                  self.audio_card_combo, self.audio_profile_combo]
        if any(combo.get_property("popup-shown") for combo in combos):
            self.audio_deferred_state = state
            return
        self.audio_state = state
        self.audio_updating = True
        try:
            for kind, collection in [("sink", "sinks"), ("source", "sources")]:
                self.audio_set_choices(self.audio_devices[kind],
                    [(device["name"], self.audio_device_title(device)) for device in state.get(collection, [])],
                    fallback=state.get(f"default_{kind}"))
                self.populate_audio_device(kind)
            prior_card = self.audio_card_combo.get_active_id()
            prior_profile = self.audio_profile_combo.get_active_id()
            cards = state.get("cards", [])
            self.audio_set_choices(self.audio_card_combo,
                [(card["name"], card.get("description") or card["name"]) for card in cards])
            preserve = self.audio_profile_dirty and prior_card == self.audio_card_combo.get_active_id()
            self.populate_audio_profiles(prior_profile if preserve else None)
        finally:
            self.audio_updating = False
        self.audio_controls.set_sensitive(True)
        hidden = state.get("hidden_counts") or {}
        count = sum(hidden.get(key, 0) for key in ("sinks", "sources"))
        details = [tr_legacy("音频已连接 · Audio connected")]
        if count and not self.audio_advanced.get_active():
            details.append(tr(f"{count} advanced channel{'s' if count != 1 else ''} hidden",
                              f"已收起 {count} 个高级通道"))
        pro_cards = state.get("pro_audio_cards") or []
        self.audio_status.set_tooltip_text(tr_legacy("Pro Audio 会暴露底层通道，可在下方声卡模式中切换至桌面模式。\nPro Audio exposes raw channels. A desktop profile can be selected below.")
                                          if pro_cards else "PipeWire / PulseAudio")
        self.audio_status.set_text("\n".join(details))

    def populate_audio_device(self, kind):
        device = self.selected_audio_device(kind)
        name = device["name"] if device else None
        default = self.audio_state.get(f"default_{kind}")
        use = self.audio_device_apply[kind]
        use.set_label("✓" if name and name == default else tr_legacy("使用 · Use"))
        use.set_sensitive(bool(device) and name != default and device.get("available", True))
        self.audio_devices[kind].set_tooltip_text(self.audio_device_title(device) if device else None)
        note = tr_legacy("默认设备 · Default") if name and name == default else tr_legacy("尚未应用 · Not applied")
        if device and device.get("availability") == "unavailable":
            note += tr("\nPort disconnected", "\n接口未连接")
        self.audio_device_notes[kind].set_text(note if device else tr_legacy("未检测到设备 · No device detected"))
        scale = self.audio_volumes[kind]
        self.audio_mutes[kind].set_sensitive(bool(device))
        volume = device.get("volume") if device else None
        scale.set_sensitive(volume is not None)
        if volume is not None:
            if kind not in self.audio_timers and kind not in self.audio_dragging:
                scale.set_value(min(volume, 100))
                self.audio_values[kind].set_text(f"{volume:.0f}%")
        else:
            self.audio_values[kind].set_text(tr_legacy("Unavailable · 不可用"))
        muted = device.get("mute", False) if device else False
        self.audio_mutes[kind].set_label(tr_legacy("Unmute · 取消静音") if muted else tr_legacy("Mute · 静音"))
        ports = self.audio_ports[kind]
        active = device.get("active_port") if device else None
        same_device = self.audio_port_devices.get(kind) == name
        rows = []
        for port in device.get("ports", []) if device else []:
            if port.get("available") not in (False, "no") or port["name"] == active or self.audio_advanced.get_active():
                title = port.get("description") or port["name"]
                if port.get("available") in (False, "no"):
                    title += tr(" · Disconnected", " · 未连接")
                rows.append((port["name"], title))
        self.audio_set_choices(ports, rows, preferred=None if same_device else active, fallback=active)
        self.audio_port_rows[kind].set_visible(bool(rows))
        self.audio_port_devices[kind] = name
        self.update_audio_port_button(kind)

    def update_audio_port_button(self, kind):
        device = self.selected_audio_device(kind)
        selected = self.audio_ports[kind].get_active_id()
        port = next((item for item in device.get("ports", []) if item["name"] == selected), None) if device else None
        active = device.get("active_port") if device else None
        self.audio_port_apply[kind].set_sensitive(bool(port) and selected != active
                                                  and port.get("available") not in (False, "no"))
        self.audio_port_apply[kind].set_label(tr_legacy("正在使用 · In use") if selected and selected == active else tr_legacy("应用接口 · Apply port"))

    def selected_audio_device(self, kind):
        selected = self.audio_devices[kind].get_active_id()
        return next((device for device in self.audio_state.get("sinks" if kind == "sink" else "sources", [])
                     if device["name"] == selected), None)

    def audio_action(self, task):
        if self.audio_busy:
            return False
        self.audio_generation += 1
        self.audio_deferred_state = None
        self.audio_busy = True
        # Keep the focused widget enabled; a busy operation must not reset the
        # keyboard position or close a combo that the user is browsing.
        self.audio_status.set_text(tr_legacy("Applying audio… · 正在应用音频设置…"))

        def done(_):
            self.audio_busy = False
            self.refresh_audio()

        def failed(error):
            self.audio_busy = False
            self.audio_status.set_text(tr("Audio change failed", "音频设置失败") + f"\n{error}")
        self.work(task, done, failed, commit=True)
        return True

    def audio_device_changed(self, combo, kind):
        if self.audio_updating or not combo.get_active_id():
            return
        prior = self.audio_timers.pop(kind, None)
        if prior:
            GLib.source_remove(prior)
            self.pending.discard(prior)
        self.audio_updating = True
        try:
            self.populate_audio_device(kind)
        finally:
            self.audio_updating = False

    def audio_use_device(self, kind):
        from audio_backend import set_default
        device = self.selected_audio_device(kind)
        if device and device.get("available", True) and device["name"] != self.audio_state.get(f"default_{kind}"):
            name = device["name"]
            self.audio_action(lambda: set_default(kind, name))

    def audio_toggle_mute(self, kind):
        from audio_backend import set_mute
        device = self.selected_audio_device(kind)
        if device:
            self.audio_action(lambda: set_mute(kind, device["name"], not device["mute"]))

    def audio_port_changed(self, combo, kind):
        if not self.audio_updating:
            self.update_audio_port_button(kind)

    def audio_apply_port(self, kind):
        from audio_backend import set_port
        device = self.selected_audio_device(kind)
        port = self.audio_ports[kind].get_active_id()
        if device and port and self.audio_port_apply[kind].get_sensitive():
            name = device["name"]
            self.audio_action(lambda: set_port(kind, name, port))

    def audio_volume_changed(self, scale, kind):
        if self.audio_updating:
            return
        from audio_backend import set_volume
        device = self.selected_audio_device(kind)
        if not device:
            return
        volume = round(scale.get_value())
        name = device["name"]
        self.audio_values[kind].set_text(f"{volume}%")
        prior = self.audio_timers.pop(kind, None)
        if prior:
            GLib.source_remove(prior)
            self.pending.discard(prior)

        def apply():
            self.pending.discard(self.audio_timers.pop(kind, None))
            if self.audio_busy or kind in self.audio_dragging:
                source = GLib.timeout_add(100, apply)
                self.audio_timers[kind] = source
                self.pending.add(source)
            else:
                self.audio_action(lambda: set_volume(kind, name, volume))
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add(180, apply)
        self.audio_timers[kind] = source
        self.pending.add(source)

    def audio_move_streams(self, kind):
        from audio_backend import move_streams
        device = self.selected_audio_device(kind)
        if device:
            self.audio_action(lambda: move_streams(kind, device["name"]))

    def selected_audio_card(self):
        return next((card for card in self.audio_state.get("cards", [])
                     if card["name"] == self.audio_card_combo.get_active_id()), None)

    def populate_audio_profiles(self, preferred=None):
        card = self.selected_audio_card()
        active = card.get("active_profile") if card else None
        rows = [(profile["name"], profile.get("description") or profile["name"])
                for profile in card.get("profiles", []) if profile.get("available") not in (False, "no")] if card else []
        self.audio_set_choices(self.audio_profile_combo, rows,
                               preferred=preferred if preferred is not None else active, fallback=active)
        self.update_audio_profile_buttons()

    def update_audio_profile_buttons(self):
        card = self.selected_audio_card()
        selected = self.audio_profile_combo.get_active_id()
        active = card.get("active_profile") if card else None
        self.audio_profile_apply.set_sensitive(bool(selected) and selected != active)
        recommendation = card.get("recommended_profile") if card else None
        recommend = active == "pro-audio" and bool(recommendation)
        self.audio_profile_recommend.set_visible(recommend)
        description = card.get("recommended_description") or recommendation if card else ""
        self.audio_profile_recommend.set_tooltip_text(description or None)
        if active == "pro-audio":
            detail = tr_legacy("专业模式会列出底层通道。桌面模式通常更适合扬声器和麦克风。\nPro Audio lists raw channels. A desktop profile simplifies speakers and microphones.")
            if recommendation:
                detail += tr("\nRecommended: ", "\n推荐：") + description
        else:
            detail = tr_legacy("切换声卡模式会改变可用设备。选择后点击应用。\nA card profile changes available devices. Select, then apply.")
        self.audio_profile_note.set_text(detail)

    def audio_card_changed(self, _combo):
        if not self.audio_updating:
            self.audio_profile_dirty = False
            self.audio_updating = True
            try:
                self.populate_audio_profiles()
            finally:
                self.audio_updating = False

    def audio_profile_changed(self, _combo):
        if not self.audio_updating:
            self.audio_profile_dirty = True
            self.update_audio_profile_buttons()

    def audio_apply_profile(self):
        from audio_backend import set_profile
        card = self.audio_card_combo.get_active_id()
        profile = self.audio_profile_combo.get_active_id()
        if card and profile and not self.audio_busy:
            self.audio_profile_dirty = False
            self.audio_action(lambda: set_profile(card, profile))

    def audio_apply_recommended_profile(self):
        from audio_backend import set_profile
        card = self.selected_audio_card()
        profile = card.get("recommended_profile") if card else None
        if profile and not self.audio_busy:
            self.audio_profile_dirty = False
            name = card["name"]
            self.audio_action(lambda: set_profile(name, profile))

    def _build_system(self):
        from metrics import MetricsSampler
        self.metrics_sampler = MetricsSampler(detailed=True)
        self.metrics_busy = False
        self.system_info_busy = False
        body = box(spacing=12)
        system_scroller = scroller(body)
        # The live readings make this page taller than the window. Reserve the
        # gutter from the first frame so the first sample cannot shift cards
        # sideways when the scrollbar appears.
        system_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.ALWAYS)
        header = pack(body, box(False, 6))
        pack(header, label(tr_legacy("LIVE  /  实时监控"), "section-title"), True)
        pack(header, label(tr("Live rates · 2 s", "实时速率 · 每两秒"), "hint"))
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        pack(body, grid)
        self.metric_values = {}
        self.metric_details = {}
        self.metric_bars = {}
        for index, (key, title) in enumerate([
            ("cpu", tr_legacy("CPU · 处理器")), ("memory", tr_legacy("RAM · 内存")),
            ("gpu", tr_legacy("GPU · 显卡")), ("disk", tr_legacy("Storage · 根目录")),
        ]):
            metric = box(spacing=6, css="metric-card")
            pack(metric, label(title, "hint"))
            self.metric_values[key] = pack(metric, label("—", "metric-value"))
            progress = Gtk.ProgressBar()
            progress.get_style_context().add_class("metric-progress")
            self.metric_bars[key] = pack(metric, progress)
            self.metric_details[key] = pack(metric, self.compact_label(tr_legacy("Reading… · 读取中…")))
            columns = 4 if self.panel_width >= 1300 else 2
            grid.attach(metric, index % columns, index // columns, 1, 1)
        system = self.card(body, tr_legacy("ABOUT THIS SYSTEM  /  系统信息"))
        tools = pack(system, box(False, 8))
        self.system_copy = pack(tools, button(tr("Copy system information", "复制系统信息"), self.copy_system_info, "small-button"))
        self.system_refresh_button = pack(tools, button(tr_legacy("Refresh displays & system · 刷新屏幕与系统"), self.refresh_system_info, "small-button"))
        self.system_specs = Gtk.Grid(column_spacing=18, row_spacing=9)
        pack(system, self.system_specs)
        self.system_specs_placeholder = label(tr_legacy("Reading system… · 读取系统…"), "hint")
        self.system_specs.attach(self.system_specs_placeholder, 0, 0, 2, 1)
        # Kept selectable but hidden: copy/export still has the complete text,
        # while the visible card is a structured key/value table instead of a
        # terminal dump.
        self.system_detail = label("", "system-summary", localize=False)
        self.system_detail.set_no_show_all(True)
        self.system_detail.set_visible(False)
        self.system_detail.set_selectable(True)
        network = self.card(body, tr_legacy("NETWORK  /  网络速率"))
        rates = pack(network, box(False, 10))
        for key, heading in [("download", tr_legacy("↓ Download · 下载")), ("upload", tr_legacy("↑ Upload · 上传"))]:
            side = pack(rates, box(spacing=4), True)
            pack(side, label(heading, "hint"))
            self.metric_values[key] = pack(side, label("—", "network-rate"))
        self.network_detail = pack(network, self.compact_label())
        self.sensor_detail = pack(body, self.compact_label())
        sensors = Gtk.Expander(label=tr_legacy("All temperature sensors · 全部温度传感器"))
        self.sensor_readings = self.compact_label()
        sensor_scroll = scroller(self.sensor_readings)
        sensor_scroll.set_min_content_height(140)
        sensor_scroll.set_max_content_height(180)
        sensor_scroll.set_propagate_natural_height(True)
        sensors.add(sensor_scroll)
        pack(body, sensors)
        pack(body, button(tr_legacy("Open process monitor · 查看进程"), lambda: self.desktop("system-monitor")))
        self.inventory = pack(body, Gtk.FlowBox())
        self.inventory.set_selection_mode(Gtk.SelectionMode.NONE)
        self.inventory.set_min_children_per_line(1)
        self.inventory.set_max_children_per_line(2 if self.panel_width >= 1200 else 1)
        self.inventory.set_column_spacing(12)
        self.inventory.set_row_spacing(12)
        self.inventory_labels = []
        from metrics import detailed_sections
        for heading, content in detailed_sections({}):
            card = box(spacing=8, css="card")
            pack(card, label(heading, "section-title", wrap=True))
            value = pack(card, label(content, "system-inventory", wrap=True, localize=False))
            value.set_selectable(True)
            value.set_max_width_chars(44)
            self.inventory_labels.append(value)
            self.inventory.add(card)
        display = self.card(body, tr_legacy("DISPLAYS  /  屏幕设置"))
        self.display_detail = pack(display, self.compact_label(tr_legacy("Reading displays… · 读取显示器…")))
        self.display_detail.set_selectable(True)
        pack(display, button(tr_legacy("Resolution, scale & layout · 分辨率、缩放与排列"),
                             lambda: self.select_control_tab("displays"), "tool-button"))
        pack(display, self.compact_label(tr_legacy("Set resolution, refresh, scale and bit-depth limit in Screen.\n在屏幕页直接设置分辨率、刷新率、缩放和位深上限。")))
        maintenance = self.card(body, tr_legacy("MAINTENANCE  /  系统维护"))
        self.action_grid(maintenance, [
            (tr_legacy("↻  Update · 系统更新"), lambda: self.desktop("updates")),
            (tr_legacy("⚒  Repair · 修复桌面"), lambda: self.desktop("repair")),
            (tr_legacy("✓  Status · 安装状态"), lambda: self.desktop("status")),
            (tr_legacy("⌕  Diagnose · 完整自检"), lambda: self.desktop("check")),
        ])
        pack(maintenance, self.compact_label(tr_legacy("Update opens a terminal for a full Arch upgrade. Review packages before confirming.\n更新将打开终端执行完整 Arch 升级，请检查软件包后确认。")))
        utilities = self.card(body, tr_legacy("UTILITIES  /  实用工具"))
        self.action_grid(utilities, [
            (tr_legacy("▤  Files · 文件"), lambda: self.desktop("launch", "files")),
            (tr_legacy("⌘  Terminal · 终端"), lambda: self.desktop("launch", "terminal")),
            (tr_legacy("▧  Wallpaper · 壁纸"), lambda: self.desktop("wallpaper")),
            (tr_legacy("⌖  Screenshot · 截图"), lambda: self.launch(["niri", "msg", "action", "screenshot"])),
        ])
        return PageEntry(body, system_scroller)

    def start_metrics_tick(self):
        if self.metrics_tick_source is None and self.alive:
            self.metrics_tick_source = GLib.timeout_add_seconds(2, self.refresh_metrics)
            self.pending.add(self.metrics_tick_source)

    def stop_metrics_tick(self):
        source = self.metrics_tick_source
        self.metrics_tick_source = None
        if source is not None:
            self.pending.discard(source)
            GLib.source_remove(source)

    def action_grid(self, parent, actions):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        pack(parent, grid)
        for index, (title, callback) in enumerate(actions):
            grid.attach(button(title, callback, "tool-button"), index % 2, index // 2, 1, 1)

    def refresh_metrics(self, *, prime=False):
        if not self.alive or getattr(self, "metrics_sampler", None) is None:
            return GLib.SOURCE_REMOVE
        if not self.page_visible('system'):
            return GLib.SOURCE_CONTINUE
        if not self.metrics_busy:
            self.metrics_busy = True
            generation = getattr(self, 'metrics_generation', 0)
            valid = lambda: self.alive and generation == getattr(self, 'metrics_generation', 0)

            def task():
                if not valid():
                    return None
                if prime:
                    self.metrics_sampler.prime()
                    time.sleep(0.05)
                if not valid():
                    return None
                self.metrics_sampler.gpu_read_allowed = valid
                return self.metrics_sampler.sample()

            def complete(value=None, error=None):
                self.metrics_busy = False
                if not valid() or value is None and error is None:
                    if self.page_visible('system'):
                        self.refresh_metrics(prime=True)
                    return
                if error is not None:
                    self.metrics_error(error)
                else:
                    self.apply_metrics(value)
            self.work(task, complete, lambda error: complete(error=error))
        return GLib.SOURCE_CONTINUE

    def metrics_error(self, error):
        self.metrics_busy = False
        self.sensor_detail.set_text(tr("Monitoring unavailable", "监控不可用") + f"\n{error}")

    def apply_metrics(self, values):
        from metrics import detailed_sections
        for widget, (_heading, content) in zip(self.inventory_labels, detailed_sections(values)):
            widget.set_text(content)
        from metrics import format_bytes, format_rate, format_percent, format_uptime, gpu_activity_text
        self.metrics_busy = False
        unavailable = tr_legacy("Unavailable · 不可用")

        def metric(key, percent, detail):
            self.metric_values[key].set_text(format_percent(percent))
            self.metric_bars[key].set_fraction(max(0, min(1, percent / 100)) if percent is not None else 0)
            self.metric_bars[key].set_sensitive(percent is not None)
            self.metric_details[key].set_text(detail)

        load = values.get("load_average")
        metric("cpu", values.get("cpu_percent"),
               tr("Load ", "负载 ") + " / ".join(f"{value:.2f}" for value in load) if load else unavailable)
        memory = values.get("memory") or {}
        metric("memory", memory.get("percent"),
               f"{format_bytes(memory['used'])} / {format_bytes(memory['total'])}" if memory else unavailable)
        disk = values.get("disk") or {}
        metric("disk", disk.get("percent"), tr(f"{format_bytes(disk['free'])} free", f"可用 {format_bytes(disk['free'])}") if disk else unavailable)
        gpus = values.get("gpus") or []
        measured = [item for item in gpus if item.get("percent") is not None]
        gpu = max(measured, key=lambda item: item["percent"]) if measured else (gpus[0] if gpus else {})
        gpu_lines = []
        for item in gpus:
            parts = [item.get("name") or "GPU", gpu_activity_text(item)]
            if item.get("temperature") is not None:
                parts.append(f"{item['temperature']:.0f}°C")
            if item.get("memory_used") is not None and item.get("memory_total") is not None:
                parts.append(f"VRAM {format_bytes(item['memory_used'])} / {format_bytes(item['memory_total'])}")
            gpu_lines.append(" · ".join(parts))
        metric("gpu", gpu.get("percent"), "\n".join(gpu_lines) or unavailable)
        network = values.get("network") or {}
        self.metric_values["download"].set_text(format_rate(network.get("down_bps")))
        self.metric_values["upload"].set_text(format_rate(network.get("up_bps")))
        self.network_detail.set_text(network.get("interface") or tr_legacy("No active interface · 无活动网络接口"))
        sensors = [tr("Uptime ", "已运行 ") + format_uptime(values.get('uptime_seconds'))]
        swap = values.get("swap")
        if swap:
            sensors.append(tr("Swap ", "交换分区 ") + f"{format_bytes(swap['used'])} / {format_bytes(swap['total'])}")
        temperatures = values.get("temperatures") or []
        if temperatures:
            measured_temperatures = [item['celsius'] for item in temperatures if item.get('celsius') is not None]
            if measured_temperatures:
                sensors.append(tr(f"Peak {max(measured_temperatures):.0f}°C · {len(temperatures)} sensors",
                                  f"最高温度 {max(measured_temperatures):.0f}°C · {len(temperatures)} 个传感器"))
            else:
                sensors.append(tr_legacy("Temperature unavailable · 温度不可用"))
            self.sensor_readings.set_text("\n".join(item['name'] + " · " +
                (f"{item['celsius']:.0f}°C" if item.get('celsius') is not None else unavailable) for item in temperatures))
        else:
            sensors.append(tr_legacy("Temperature unavailable · 温度不可用"))
            self.sensor_readings.set_text(tr_legacy("No temperature sensors · 无温度传感器"))
        self.sensor_detail.set_text("\n".join(sensors))

    def refresh_system_info(self):
        if not self.alive or getattr(self, "system_info_busy", None) is None:
            return
        if self.system_info_busy:
            return
        # A display transaction can finish after the user left this page. The
        # page is refreshed on re-entry, so hidden work must not scan the host.
        if not self.page_visible('system'):
            return
        self.system_info_busy = True
        refresh_button = getattr(self, 'system_refresh_button', None)
        if refresh_button is not None:
            refresh_button.set_sensitive(False)

        def read():
            from system_info import collect, plain_text
            rows, outputs = collect()
            return rows, plain_text(rows), self.describe_outputs(outputs)

        def done(result):
            rows, text, display = result
            self.system_info_busy = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            self.system_detail.set_text(text)
            self.populate_system_specs(rows)
            self.display_detail.set_text(display)

        def failed(error):
            self.system_info_busy = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            self.system_detail.set_text(tr("Unavailable", "不可用") + f"\n{error}")
            for child in self.system_specs.get_children():
                self.system_specs.remove(child)
                child.destroy()
            self.system_specs.attach(label(tr("Unavailable", "不可用") + f"\n{error}", "hint"), 0, 0, 2, 1)
            self.system_specs.show_all()
        self.work(read, done, failed)

    def populate_system_specs(self, rows):
        for child in self.system_specs.get_children():
            self.system_specs.remove(child)
            child.destroy()
        for index, (key, value) in enumerate(rows):
            key_label = label(key, "spec-key", localize=False)
            key_label.set_size_request(150 if self.panel_width >= 1200 else 112, -1)
            value_label = label(value, "spec-value", wrap=True, localize=False)
            value_label.set_hexpand(True)
            value_label.set_max_width_chars(72 if self.panel_width >= 1200 else 38)
            value_label.set_selectable(True)
            self.system_specs.attach(key_label, 0, index, 1, 1)
            self.system_specs.attach(value_label, 1, index, 1, 1)
        self.system_specs.show_all()

    def align_system_info(self):
        keys = [line.split("\t", 1)[0] for line in self.system_detail.get_text().splitlines() if "\t" in line]
        if keys:
            stop = max(self.system_detail.create_pango_layout(key).get_pixel_size()[0] for key in keys) + 12
            tabs = Pango.TabArray.new(1, True)
            tabs.set_tab(0, Pango.TabAlign.LEFT, stop)
            self.system_detail.get_layout().set_tabs(tabs)

    def copy_system_info(self):
        # Capture the visible text now, not a new sample or hidden inventory.
        content = self.system_detail.get_text()
        self.work(lambda: subprocess.run(["wl-copy"], input=content, capture_output=True,
                                         text=True, check=True, timeout=5),
                  lambda _: self.feedback(tr("System information copied", "系统信息已复制")), commit=True)

    @staticmethod
    def describe_outputs(outputs):
        if not isinstance(outputs, dict) or not outputs:
            return tr_legacy("Display information unavailable · 无法读取屏幕信息")
        descriptions = []
        for name, output in outputs.items():
            if not isinstance(output, dict):
                continue
            modes = output.get("modes") or []
            current = output.get("current_mode")
            detail = tr_legacy("Off · 已关闭")
            if isinstance(current, int) and 0 <= current < len(modes):
                mode = modes[current]
                detail = f"{mode.get('width', '?')} × {mode.get('height', '?')}"
                refresh = mode.get("refresh_rate")
                if isinstance(refresh, (int, float)):
                    detail += f" · {refresh / 1000:g} Hz"
            logical = output.get("logical") or {}
            if logical.get("scale") is not None:
                detail += f" · {logical['scale']:g}×"
            if logical.get("x") is not None and logical.get("y") is not None:
                detail += tr("\nPosition ", "\n位置 ") + f"{logical['x']}, {logical['y']}"
            descriptions.append(f"{name} · {output.get('model') or output.get('make') or 'Display'}\n{detail}")
        return "\n\n".join(descriptions) or tr_legacy("No displays · 未检测到屏幕")

    def _build_appearance(self):
        from appearance import DEFAULTS, PRESETS, load_settings
        self.appearance_busy = True
        body = box(spacing=12)
        self.appearance_body = body
        theme = self.card(body, tr_legacy("COLOR & GLASS  /  主题与玻璃质感"))
        pack(theme, label(tr_legacy("应用与桌面 · Apps & desktop"), "control-label"))
        self.color_mode_combo = Gtk.ComboBoxText()
        self.color_mode_combo.append("dark", tr_legacy("深色 · Dark"))
        self.color_mode_combo.append("light", tr_legacy("浅色 · Light"))
        pack(theme, self.color_mode_combo)
        self.theme_combo = Gtk.ComboBoxText()
        for key, preset in PRESETS.items():
            self.theme_combo.append(key, tr_legacy(preset["label"]))
        pack(theme, self.theme_combo)
        swatch_row = pack(theme, box(False, 8, "palette-preview"))
        self.palette_swatches = []
        for _ in range(5):
            chip = box(css="palette-swatch")
            chip.set_size_request(28, 18)
            provider = Gtk.CssProvider()
            chip.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            pack(swatch_row, chip)
            self.palette_swatches.append(provider)
        self.theme_combo.connect("changed", lambda *_: self._refresh_palette_preview())
        self.color_mode_combo.connect("changed", lambda *_: self._refresh_palette_preview())
        self.wallpaper_colors_check = Gtk.CheckButton(label=tr("Follow wallpaper colors", "主题配色跟随当前壁纸"))
        pack(theme, self.wallpaper_colors_check)
        self.wallpaper_colors_check.connect("toggled", lambda check: self.theme_combo.set_sensitive(not check.get_active()))
        pack(theme, self.compact_label(tr("Uses the image or project preview; keeps your chosen light/dark mode.", "根据图片或项目预览图取色；保留所选明暗模式。")))
        pack(theme, self.compact_label(tr_legacy("统一桌面配色，并同步 GTK / Qt 应用的明暗模式。\nShared desktop palette and matching GTK / Qt light or dark mode.")))
        self.reduced_motion_check = Gtk.CheckButton(label=tr_legacy("减少动态效果 · Reduce motion"))
        pack(theme, self.reduced_motion_check)
        opacity_row = pack(theme, box(False, 6))
        pack(opacity_row, label(tr_legacy("Surface opacity · 面板不透明度"), "control-label"), True)
        self.opacity_value = pack(opacity_row, label("", "value"))
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 1)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.connect("value-changed", lambda scale: self.opacity_value.set_text(f"{scale.get_value():.0f}%"))
        pack(theme, self.opacity_scale)
        pack(theme, self.compact_label(tr("20–100%. Below 40%, text edges and separators are strengthened; readability still depends on the wallpaper.",
                                         "可调 20–100%。低于 40% 会加强文字边缘和分隔线；可读性仍取决于壁纸。")))
        fonts = self.card(body, tr_legacy("FONTS  /  字体"))
        self.font_buttons = {}
        self.font_sizes = {}
        for key, title, minimum, maximum, unit in [
            ("font", tr_legacy("Interface · 界面字体"), 9, 20, "px"),
            ("mono_font", tr_legacy("Terminal · 终端字体"), 8, 24, "pt"),
        ]:
            pack(fonts, label(title, "control-label"))
            chooser = Gtk.FontButton()
            chooser.set_show_style(False)
            chooser.set_show_size(False)
            chooser.set_use_font(False)
            chooser.set_use_size(False)
            chooser.set_title(title)
            self.font_buttons[key] = pack(fonts, chooser)
            row = pack(fonts, box(False, 8))
            pack(row, label(tr(f"Size ({unit})", f"字号 ({unit})"), "hint"), True)
            size = Gtk.SpinButton.new_with_range(minimum, maximum, 0.5)
            size.set_digits(1)
            self.font_sizes[key] = pack(row, size)
        pack(fonts, self.compact_label(tr_legacy("Applies to this desktop's components. Existing terminals use the new font when reopened.\n应用于本桌面组件；已有终端重新打开后使用新字体。")))
        actions = pack(body, box(False, 8))
        self.appearance_apply = pack(actions, button(tr_legacy("Apply · 应用设置"), self.apply_appearance, "accent-button"), True)
        self.appearance_reset = pack(actions, button(tr_legacy("Defaults · 恢复默认"), lambda: self.apply_appearance(reset=True)), True)
        pack(body, self.compact_label(tr_legacy("Preferences are saved locally when you Apply.\n偏好保存在本地，选好主题与字体后点击应用。")))
        self.populate_appearance(DEFAULTS)
        body.set_sensitive(False)

        def loaded(settings):
            self.populate_appearance(settings)
            self.apply_local_appearance(settings)
            self.appearance_busy = False
            body.set_sensitive(True)

        def failed(error):
            self.appearance_busy = False
            body.set_sensitive(True)
            self.feedback(tr("Could not load appearance: ", "无法加载外观设置：") + str(error), True)
        self.work(load_settings, loaded, failed)
        return PageEntry(body, scroller(body))

    def populate_appearance(self, settings):
        self.wallpaper_colors_check.set_active(settings.get("wallpaper_colors", False))
        self.color_mode_combo.set_active_id(settings.get("color_mode", "dark"))
        self.reduced_motion_check.set_active(settings.get("reduced_motion", False))
        self.theme_combo.set_active_id(settings["preset"])
        self._refresh_palette_preview()
        self.opacity_scale.set_value(settings["opacity"] * 100)
        installed = getattr(self, "_installed_fonts", None)
        if installed is None:
            installed = {family.get_name() for family in self.get_pango_context().list_families()}
            self._installed_fonts = installed
        for key, size_key in [("font", "font_size"), ("mono_font", "mono_size")]:
            requested = settings[key]
            fallbacks = ("Noto Sans CJK SC", "Noto Sans", "Sans") if key == "font" else ("JetBrainsMono Nerd Font", "Monospace")
            selected = requested if requested in installed else next((name for name in fallbacks if name in installed), fallbacks[-1])
            self.font_buttons[key].set_font(f"{selected} {settings[size_key]}")
            self.font_buttons[key].set_tooltip_text(
                None if selected == requested else tr(f"{requested} is unavailable; using {selected}", f"未安装 {requested}；已选择 {selected}"))
            self.font_sizes[key].set_value(settings[size_key])

    def _refresh_palette_preview(self):
        swatches = getattr(self, "palette_swatches", None)
        if not swatches:
            return
        preset = self.theme_combo.get_active_id() or "glacier"
        mode = self.color_mode_combo.get_active_id() or "dark"
        from appearance import palette
        colors = palette({"preset": preset, "color_mode": mode})
        keys = ("background", "surface_raised", "accent", "secondary", "ink")
        for provider, key in zip(swatches, keys):
            color = colors.get(key, "#5ee7ff")
            provider.load_from_data(
                f"box.palette-swatch {{ background-color: {color}; border-radius: 999px; "
                f"border: 1px solid rgba(255, 255, 255, 0.25); }}".encode()
            )

    def draft_appearance(self):
        return {
            "wallpaper_colors": self.wallpaper_colors_check.get_active(),
            "color_mode": self.color_mode_combo.get_active_id(),
            "reduced_motion": self.reduced_motion_check.get_active(),
            "preset": self.theme_combo.get_active_id(),
            "font": self.font_buttons["font"].get_font_desc().get_family(),
            "font_size": self.font_sizes["font"].get_value(),
            "mono_font": self.font_buttons["mono_font"].get_font_desc().get_family(),
            "mono_size": self.font_sizes["mono_font"].get_value(),
            "opacity": self.opacity_scale.get_value() / 100,
        }

    def apply_local_appearance(self, settings):
        self.reduced_motion = settings.get("reduced_motion", False)
        self.get_settings().set_property("gtk-application-prefer-dark-theme", settings.get("color_mode", "dark") == "dark")
        configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
        revealer = getattr(self, "quick_details_revealer", None)
        if revealer is not None:
            revealer.set_transition_duration(
                180 if animations_enabled(self.surface, not self.reduced_motion) else 0)
        context = self.get_style_context()
        (context.add_class if not animations_enabled(self.surface, not self.reduced_motion)
         else context.remove_class)("reduce-motion")

    def apply_appearance(self, reset=False):
        if self.appearance_busy:
            return
        from appearance import apply_settings, restore_defaults
        from application_theme import apply_mode
        settings = self.draft_appearance()
        self.appearance_busy = True
        self.appearance_body.set_sensitive(False)
        self.feedback(tr_legacy("Applying appearance… · 正在应用外观…"))

        def apply():
            from wallpaper import with_wallpaper_colors
            result = restore_defaults() if reset else apply_settings(with_wallpaper_colors(settings))
            errors = []
            try:
                report = apply_mode(result)
                errors.extend(report.get("warnings", []))
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(tr("Application theme: ", "应用主题：") + str(error))
            try:
                capture([DESKTOP, "theme-reload"], timeout=20)
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                errors.append(str(error))
            return result, "; ".join(errors) or None

        def done(result):
            settings, reload_error = result
            self.appearance_busy = False
            self.appearance_body.set_sensitive(True)
            self.populate_appearance(settings)
            self.apply_local_appearance(settings)
            try:
                self.get_application().reload_theme()
            except (GLib.Error, OSError) as error:
                reload_error = str(error)
            if reload_error:
                self.feedback(tr("Saved with issues: ", "已保存，部分设置未生效：") + reload_error, True)
            else:
                self.feedback(tr_legacy("外观已同步；部分应用需重新打开。\nAppearance synced; some apps need reopening."))

        def failed(error):
            self.appearance_busy = False
            self.appearance_body.set_sensitive(True)
            self.feedback(tr("Could not apply appearance: ", "无法应用外观：") + str(error), True)
        self.work(apply, done, failed, commit=True)

    def refresh_control(self):
        if not self.alive or self.mode != "control":
            return GLib.SOURCE_REMOVE
        if not self.page_visible('quick'):
            return GLib.SOURCE_CONTINUE
        if self.refreshing:
            return GLib.SOURCE_CONTINUE
        self.refreshing = True

        def read():
            import concurrent.futures
            import brightness
            queries = {
                "wifi": ["nmcli", "radio", "wifi"],
                "dnd": ["swaync-client", "--skip-wait", "-D"],
                "notifications": ["swaync-client", "--skip-wait", "-c"],
                "volume": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                "microphone": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                "profiles": ["powerprofilesctl", "list"],
            }
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                tasks = {key: executor.submit(probe, value) for key, value in queries.items()}
                tasks["bluetooth"] = executor.submit(bluetooth_state)
                tasks["power_runtime"] = executor.submit(power_runtime_state)
                tasks["brightness"] = executor.submit(brightness.read_state)
                if getattr(self, "quick_sampler", None) is not None:
                    tasks["quick_metrics"] = executor.submit(self.quick_sampler.sample)
                results = {key: value.result() for key, value in tasks.items()}
            active = re.search(r"^\s*\*\s*(power-saver|balanced|performance):", results.get("profiles") or "", re.MULTILINE)
            results["profile"] = active.group(1) if active else None
            return results
        self.work(read, self.apply_control, self.control_error)
        return GLib.SOURCE_CONTINUE

    def control_error(self, error):
        self.refreshing = False
        self.finish_manual_control_refresh()
        self.feedback(error, True)

    def finish_manual_control_refresh(self):
        if self.manual_control_refresh:
            self.manual_control_refresh = False
            button = getattr(self, 'quick_refresh_button', None)
            if button is not None:
                button.set_sensitive(True)

    def manual_refresh_control(self):
        """Give the explicit Quick refresh click an immediate disabled state."""
        if not self.alive or self.mode != "control" or self.refreshing:
            return
        self.manual_control_refresh = True
        button = getattr(self, 'quick_refresh_button', None)
        if button is not None:
            button.set_sensitive(False)
        self.refresh_control()
        if not self.refreshing:
            self.finish_manual_control_refresh()

    def set_tile(self, key, available, active, state):
        tile, text = self.tiles[key]
        self.updating_tiles = True
        tile.set_active(active and available)
        self.updating_tiles = False
        tile.set_sensitive(available)
        text.set_text(state)
        tile.set_tooltip_text(state)
        context = self.tile_groups[key].get_style_context()
        (context.add_class if active and available else context.remove_class)("active")

    def apply_quick_metrics(self, data):
        labels = getattr(self, "quick_pulse", None)
        if not data or not labels:
            return
        from metrics import format_rate
        cpu = data.get("cpu_percent")
        memory = (data.get("memory") or {}).get("percent")
        network = data.get("network") or {}
        down, up = network.get("down_bps"), network.get("up_bps")
        temperatures = [item for item in (data.get("temperatures") or [])
                        if item.get("celsius") is not None]
        hottest = max(temperatures, key=lambda item: item["celsius"]) if temperatures else None
        labels["cpu"].set_text(f"{cpu:.0f}%" if cpu is not None else "—")
        labels["memory"].set_text(f"{memory:.0f}%" if memory is not None else "—")
        labels["network"].set_text(f"↓{format_rate(down)} ↑{format_rate(up)}"
                                   if down is not None or up is not None else "—")
        labels["temp"].set_text(f"{hottest['celsius']:.0f}°C" if hottest else "—")

    def apply_control(self, state):
        self.refreshing = False
        self.finish_manual_control_refresh()
        self.state = state
        self.apply_quick_metrics(state.get("quick_metrics"))
        wifi = state["wifi"]
        self.set_tile("wifi", wifi in ("enabled", "disabled"), wifi == "enabled",
                      {"enabled": tr_legacy("Enabled · 已开启"), "disabled": tr_legacy("Off · 已关闭")}.get(wifi, tr_legacy("Unavailable · 不可用")))
        bluetooth = state["bluetooth"] or {}
        bt_available = bool(bluetooth.get("path"))
        bt_on = bluetooth.get("powered", False)
        self.set_tile("bluetooth", bt_available, bt_on,
                      (tr_legacy("Enabled · 已开启") if bt_on else tr_legacy("Off · 已关闭")) if bt_available else tr_legacy("No adapter · 无适配器"))
        self.tiles["bluetooth"][0].set_tooltip_text(str(bluetooth.get("name", tr_legacy("No Bluetooth controller · 未检测到蓝牙控制器"))))
        dnd = (state["dnd"] or "").lower()
        self.set_tile("dnd", dnd in ("true", "false"), dnd == "true",
                      {"true": tr_legacy("Quiet · 已静音"), "false": tr_legacy("All notifications · 接收通知")}.get(dnd, tr_legacy("Unavailable · 不可用")))
        count = state["notifications"]
        self.notification_button.set_tooltip_text(tr(f"Notifications {count}", f"通知 {count}") if count and count.isdigit() else tr("Notifications", "通知"))
        self.notification_button.get_child().get_children()[-1].set_text(
            tr(f"Notifications {min(int(count), 99)}", f"通知 {min(int(count), 99)}") if count and count.isdigit() and int(count) else tr("Notifications", "通知"))
        self.notification_button.set_sensitive(count is not None)
        power = state.get("power_runtime") or {}
        self.set_tile("idle", power.get("available", False), power.get("awake", False),
                      power.get("label", tr("Unavailable", "不可用")))
        self.tiles["idle"][0].set_tooltip_text(power.get("detail", ""))
        self.updating_scales = True
        for key in ("volume", "microphone"):
            raw = state[key] or ""
            match = re.search(r"Volume:\s*([\d.]+)", raw)
            self.scales[key].set_sensitive(bool(match))
            self.mute_buttons[key].set_sensitive(bool(match))
            if match:
                value = round(float(match.group(1)) * 100)
                if key not in self.scale_timers and key not in self.dragging_scales:
                    self.scales[key].set_value(min(value, 100))
                self.scale_values[key].set_text(f"{value}%")
                self.mute_buttons[key].set_tooltip_text(tr_legacy("Unmute · 取消静音") if "MUTED" in raw else tr_legacy("Mute · 静音"))
                context = self.mute_buttons[key].get_style_context()
                (context.add_class if "MUTED" in raw else context.remove_class)("muted")
            else:
                # The value column is deliberately narrow; "Unavailable" would
                # ellipsize in English. Use the same compact fallback as N/A.
                self.scale_values[key].set_text(tr("N/A", "不可用"))
        self.apply_brightness(state.get("brightness") or {})
        profiles_raw = state.get("profiles") or ""
        profile = state.get("profile")
        if profile is None and profiles_raw:
            active = re.search(r"^\s*\*\s*(power-saver|balanced|performance):", profiles_raw, re.MULTILINE)
            profile = active.group(1) if active else None
        available_profiles = re.findall(r"^\s*\*?\s*(power-saver|balanced|performance):", profiles_raw, re.MULTILINE)
        self.profile_combo.remove_all()
        for name, title in [("power-saver", tr_legacy("Power saver · 节能")), ("balanced", tr_legacy("Balanced · 平衡")),
                            ("performance", tr_legacy("Performance · 性能"))]:
            if name in available_profiles:
                self.profile_combo.append(name, title)
        self.profile_combo.set_sensitive(bool(available_profiles))
        if profile in available_profiles:
            self.profile_combo.set_active_id(profile)
        self.profile_note.set_text("" if available_profiles else tr_legacy("Power profiles unavailable on this system.\n此系统未提供电源模式服务。"))
        self.updating_scales = False

    def apply_brightness(self, state):
        if self.brightness_busy or "brightness" in self.scale_timers or "brightness" in self.dragging_scales:
            return
        selected = self.brightness_combo.get_active_id()
        self.brightness_devices = {device["id"]: device for device in state.get("devices", [])}
        updating = self.updating_scales
        self.updating_scales = True
        self.brightness_combo.remove_all()
        for identifier, device in self.brightness_devices.items():
            self.brightness_combo.append(identifier, device["label"])
        if selected not in self.brightness_devices:
            selected = next(iter(self.brightness_devices), None)
        if selected:
            self.brightness_combo.set_active_id(selected)
        self.brightness_combo.set_sensitive(bool(self.brightness_devices))
        self.updating_scales = updating
        self.show_brightness(state.get("reason", ""))

    def show_brightness(self, reason=""):
        device = self.brightness_devices.get(self.brightness_combo.get_active_id(), {})
        available = device.get("available", False) and device.get("percent") is not None
        self.scales["brightness"].set_sensitive(available)
        updating = self.updating_scales
        self.updating_scales = True
        if available:
            self.scales["brightness"].set_value(device["percent"])
            self.scale_values["brightness"].set_text(f'{device["percent"]:g}%')
        else:
            self.scale_values["brightness"].set_text("—")
        self.updating_scales = updating
        self.backlight_note.set_text(
            (tr_legacy("DDC/CI · Monitor brightness / 显示器硬件亮度") if device.get("backend") == "ddc" else "")
            if available else (device.get("reason") or reason or tr_legacy("No brightness device · 未检测到可调亮度设备")))
        self.brightness_summary.set_text(device.get("label", tr_legacy("无可调亮度设备 · Unavailable")) if available
                                         else tr_legacy("亮度不可用 · 在更多控制中查看原因"))
        self.brightness_summary.set_tooltip_text(self.backlight_note.get_text())

    def brightness_selected(self, _combo):
        if self.updating_scales:
            return
        source = self.scale_timers.pop("brightness", None)
        if source:
            GLib.source_remove(source)
            self.pending.discard(source)
        self.show_brightness()

    def set_brightness(self, value):
        identifier = self.brightness_combo.get_active_id()
        if not identifier:
            return
        self.brightness_target = (identifier, value)
        if not self.brightness_busy:
            self.write_brightness()

    def write_brightness(self):
        identifier, value = self.brightness_target
        self.brightness_target = None
        self.brightness_busy = True
        self.brightness_combo.set_sensitive(False)
        self.backlight_note.set_text(tr_legacy("Applying brightness… · 正在调整硬件亮度…"))

        def done(device):
            self.brightness_busy = False
            self.brightness_devices[identifier] = device
            if self.brightness_target:
                self.write_brightness()
                return
            self.brightness_combo.set_sensitive(True)
            if "brightness" not in self.scale_timers and "brightness" not in self.dragging_scales:
                self.show_brightness()

        def failed(error):
            self.brightness_busy = False
            self.brightness_target = None
            self.brightness_combo.set_sensitive(True)
            self.backlight_note.set_text(error)
            self.feedback(error, True)
        import brightness
        self.work(lambda: brightness.set_percent(identifier, value), done, failed, commit=True)

    def toggle_wifi(self):
        self.action(["nmcli", "radio", "wifi", "off" if self.state.get("wifi") == "enabled" else "on"])

    def toggle_bluetooth(self):
        adapter = self.state.get("bluetooth") or {}
        if adapter.get("path"):
            self.action(lambda: set_bluetooth(adapter["path"], not adapter["powered"]))

    def toggle_dnd(self):
        self.action(["swaync-client", "--skip-wait", "-d"])

    def toggle_idle(self):
        self.action([DESKTOP, "idle-toggle"])

    def scale_drag_start(self, _scale, _event, key):
        self.dragging_scales.add(key)
        return False

    def scale_drag_end(self, _scale, _event, key):
        was_dragging = key in self.dragging_scales
        self.dragging_scales.discard(key)
        if key == "brightness" and was_dragging:
            self.scale_changed(_scale, key)
        return False

    def scale_changed(self, scale, key):
        if self.updating_scales:
            return
        value = round(scale.get_value())
        self.scale_values[key].set_text(f"{value}%")
        old = self.scale_timers.pop(key, None)
        if old:
            GLib.source_remove(old)
            self.pending.discard(old)

        def apply():
            source = self.scale_timers.pop(key, None)
            self.pending.discard(source)
            if key == "brightness":
                if key not in self.dragging_scales:
                    self.set_brightness(value)
            else:
                command = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@" if key == "volume" else "@DEFAULT_AUDIO_SOURCE@", f"{value}%"]
                self.action(command)
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add(180, apply)
        self.scale_timers[key] = source
        self.pending.add(source)

    def profile_changed(self, combo):
        if not self.updating_scales and combo.get_active_id():
            self.action(["powerprofilesctl", "set", combo.get_active_id()])

    def build_shortcuts(self):
        from shortcuts import load_shortcuts
        self.shortcuts = load_shortcuts()
        search = Gtk.SearchEntry()
        search.set_placeholder_text(tr_legacy("Search keys or actions…  搜索按键或功能…"))
        search.connect("search-changed", self.filter_shortcuts)
        pack(self.content, search)
        self.shortcut_summary = pack(self.content, label("", "subtitle"))
        self.shortcut_body = box(spacing=14)
        pack(self.content, scroller(self.shortcut_body), True)
        footer = pack(self.content, box(False, 8))
        pack(footer, label(tr_legacy("Mod = Super / Windows  ·  Esc = Close / 关闭"), "hint"), True)
        self.render_shortcuts("")
        GLib.idle_add(search.grab_focus)

    def filter_shortcuts(self, search):
        self.render_shortcuts(search.get_text().strip().casefold())

    def render_shortcuts(self, query):
        for child in self.shortcut_body.get_children():
            child.destroy()
        groups = {}
        count = 0
        for item in self.shortcuts:
            # Search indexes both languages; the row itself renders only one.
            if query and query not in item["search"]:
                continue
            groups.setdefault(item["category"], []).append(item)
            count += 1
        for category, items in groups.items():
            section = self.card(self.shortcut_body, tr(*category))
            for item in items:
                narrow = self.panel_width < 650
                row = pack(section, box(narrow, 7 if narrow else 14, "shortcut-row"))
                keys = pack(row, label(item["keys"], "keycap"))
                if not narrow:
                    keys.set_size_request(245, -1)
                keys.set_line_wrap(True)
                pack(row, label(tr(*item["description"]), "shortcut-description", wrap=True, localize=False), True)
        if not count:
            pack(self.shortcut_body, label(tr_legacy("No matching shortcuts · 未找到匹配的快捷键"), "empty-state"))
        self.shortcut_summary.set_text(tr(f"{count} shortcuts · From your configuration", f"{count} 个快捷键 · 根据配置生成"))
        self.shortcut_body.show_all()

    def build_ai(self):
        import ai_store
        self.ai_request = None
        self.messages = []
        self.last_reply = ""
        self.ai_busy = False
        self.ai_saving = False
        self.model_generation = 0
        self.ai_refreshing = False
        settings_error = None
        try:
            self.workspace = ai_store.load()
        except (OSError, ValueError) as error:
            self.workspace = ai_store.defaults()
            settings_error = str(error)
        self.settings = dict(ai_store.profile(self.workspace)["settings"])
        toolbar = pack(self.content, box(False, 8))
        self.profile_choices = pack(toolbar, Gtk.ComboBoxText(), True)
        self.add_profile_button = pack(toolbar, button("+", self.add_ai_profile, tooltip=tr("Add connection", "新增连接配置")))
        pack(toolbar, button("⚙", self.toggle_settings, tooltip=tr_legacy("Connection settings · 连接设置")))
        history_row = pack(self.content, box(False, 8))
        self.conversation_choices = pack(history_row, Gtk.ComboBoxText(), True)
        self.new_chat_button = pack(history_row, button(tr("New chat", "新对话"), self.new_ai_chat))
        self.settings_box = box(spacing=8, css="card")
        self.settings_container = pack(self.content, scroller(self.settings_box))
        settings_height = min(340, max(120, self.available_height - 410))
        self.settings_container.set_min_content_height(settings_height)
        self.settings_container.set_max_content_height(settings_height)
        self.settings_container.set_propagate_natural_height(True)
        self.settings_container.set_no_show_all(True)
        pack(self.settings_box, label(tr_legacy("CONNECTION  /  连接设置"), "section-title"))
        pack(self.settings_box, label(tr("Connection name", "配置名称"), "hint"))
        self.profile_name = pack(self.settings_box, Gtk.Entry())
        self.profile_name.set_text(ai_store.profile(self.workspace)["name"])
        self.provider = Gtk.ComboBoxText()
        self.provider.append("ollama", tr_legacy("Ollama · 本地模型"))
        self.provider.append("openai-compatible", tr_legacy("OpenAI-compatible API · 兼容 API"))
        self.provider.set_active_id(self.settings.get("provider", "ollama"))
        pack(self.settings_box, self.provider)
        self.setting_entries = {}
        for key, title, fallback in [
            ("endpoint", tr_legacy("Server URL · 服务地址"), "http://127.0.0.1:11434"),
            ("model", tr_legacy("Model · 模型"), ""),
            ("api_key_env", tr_legacy("API key environment variable · 密钥环境变量名"), "OPENAI_API_KEY"),
        ]:
            pack(self.settings_box, label(title, "hint"))
            entry = Gtk.Entry()
            entry.set_text(str(self.settings.get(key, fallback)))
            entry.set_placeholder_text(fallback)
            pack(self.settings_box, entry)
            self.setting_entries[key] = entry
            entry.connect("changed", self.settings_edited)
            if key == "endpoint":
                pack(self.settings_box, label(tr_legacy("API base example · API 基地址示例: https://api.openai.com/v1"), "hint", wrap=True))
        self.provider.connect("changed", self.settings_edited)
        pack(self.settings_box, label(tr("Enter the environment variable name, never the key. After exporting keys, close this sidebar and run the command below from that terminal.",
                                        "只填环境变量名，不填密钥。设置环境变量后，关闭侧栏，再从该终端运行下方命令。"), "hint", wrap=True))
        pack(self.settings_box, label("~/.config/niri/scripts/desktop ai", "hint", localize=False)).set_selectable(True)
        settings_actions = pack(self.settings_box, box(False, 8))
        pack(settings_actions, button(tr_legacy("Find models · 查找模型"), self.find_models), True)
        pack(settings_actions, button(tr_legacy("Save · 保存"), self.save_ai_settings, "accent-button"), True)
        self.model_choices = Gtk.ComboBoxText()
        self.model_choices.set_no_show_all(True)
        self.model_choices.connect("changed", lambda combo: self.setting_entries["model"].set_text(combo.get_active_text() or ""))
        pack(self.settings_box, self.model_choices)
        self.provider_status = pack(self.content, label("", "provider-status", wrap=True))
        self.update_provider_status()
        self.chat_body = box(spacing=12)
        self.chat_scroll = pack(self.content, scroller(self.chat_body), True)
        self.welcome = self.card(self.chat_body)
        pack(self.welcome, label("✦", "welcome-icon"))
        pack(self.welcome, label(tr("Start with an idea.", "从一个想法开始。"), "welcome-title"))
        pack(self.welcome, label(tr_legacy("Ask, draft, debug, or explore. Connect Ollama locally or configure an API endpoint.\n提问、写作、调试或探索。连接本地 Ollama，或配置 API 服务。"), "welcome-copy", wrap=True))
        pack(self.welcome, label(tr("Conversations are saved locally. Each keeps its own connection; only Send contacts that provider. API keys are never saved.",
                                   "对话保存在本机，每个对话保留自己的连接；点击发送才会联系该服务。密钥不会保存。"), "hint", wrap=True))
        self.chat_scroll.get_vadjustment().connect("changed", self.scroll_chat)
        composer = pack(self.content, box(spacing=8, css="composer"))
        self.input = Gtk.TextView()
        self.input.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input.set_left_margin(10)
        self.input.set_right_margin(10)
        self.input.set_top_margin(10)
        self.input.set_bottom_margin(10)
        self.input.connect("key-press-event", self.input_key)
        input_scroll = scroller(self.input)
        input_scroll.set_min_content_height(82)
        input_scroll.set_max_content_height(150)
        pack(composer, input_scroll)
        composer_actions = pack(composer, box(False, 8))
        self.clear_button = pack(composer_actions, button(tr("Delete chat", "删除对话"), self.clear_chat))
        self.copy_button = pack(composer_actions, button(tr_legacy("Copy · 复制"), self.copy_reply))
        self.copy_button.set_sensitive(False)
        self.send_button = pack(composer_actions, button(tr_legacy("Send  ↗  发送"), self.send_chat, "accent-button"), True)
        self.stop_button = pack(composer_actions, button(tr("Stop", "停止"), self.stop_chat,
                                                       "accent-button", tooltip="Ctrl+."), True)
        self.stop_button.set_no_show_all(True)
        pack(composer, label(tr_legacy("Enter to send · 回车发送   /   Shift+Enter for newline · 换行"), "hint"))
        self.update_ai_workspace(self.workspace)
        self.profile_choices.connect("changed", self.choose_ai_profile)
        self.conversation_choices.connect("changed", self.choose_ai_chat)
        GLib.idle_add(self.input.grab_focus)
        if settings_error:
            self.feedback(settings_error, True)

    def scroll_chat(self, adjustment):
        adjustment.set_value(max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size()))

    def toggle_settings(self):
        visible = not self.settings_container.get_visible()
        if visible:
            self.settings_container.set_no_show_all(False)
            self.settings_container.show_all()
            self.settings_container.set_no_show_all(True)
        else:
            self.settings_container.hide()

    def draft_settings(self):
        import ai_store
        settings = dict(ai_store.profile(self.workspace)["settings"])
        settings.update({key: entry.get_text().strip() for key, entry in self.setting_entries.items()})
        settings["provider"] = self.provider.get_active_id() or "ollama"
        return settings

    def settings_edited(self, *_):
        self.model_generation += 1

    def save_ai_settings(self):
        if self.ai_busy or self.ai_saving:
            self.feedback(tr("Wait for the current request.", "请等待当前请求完成。"), True)
            return
        import ai_store
        from ai_backend import validate_settings
        try:
            settings = validate_settings(self.draft_settings())
        except ValueError as error:
            self.feedback(str(error), True)
            return
        def saved():
            self.settings_container.hide()
            self.feedback(tr("Connection saved; previous conversations remain in history.", "连接已保存；原对话仍保留在历史中。"))
        identifier, name = self.workspace["active_profile"], self.profile_name.get_text().strip()
        self.ai_commit(lambda: ai_store.save_profile(identifier, name, settings), after=saved)

    def set_ai_sensitive(self, sensitive):
        for widget in (self.settings_box, self.send_button, self.clear_button, self.profile_choices,
                       self.conversation_choices, self.add_profile_button, self.new_chat_button):
            widget.set_sensitive(sensitive)

    def ai_commit(self, task, *, after=None):
        if self.ai_busy or self.ai_saving:
            return
        self.ai_saving = True
        self.model_generation += 1
        self.set_ai_sensitive(False)
        def reset():
            self.ai_saving = False
            self.set_ai_sensitive(True)
        def done(value):
            reset()
            self.input.get_buffer().set_text("")
            self.update_ai_workspace(value)
            if after:
                after()
        def failed(error):
            reset()
            self.update_ai_workspace(self.workspace)
            self.feedback(error, True)
        self.work(task, done, failed, commit=True)

    def update_ai_workspace(self, value):
        import ai_store
        self.workspace = value
        self.ai_refreshing = True
        selected = ai_store.profile(value)
        self.profile_choices.remove_all()
        for profile in value["profiles"]:
            self.profile_choices.append(profile["id"], profile["name"])
        self.profile_choices.set_active_id(selected["id"])
        self.profile_name.set_text(selected["name"])
        self.provider.set_active_id(selected["settings"]["provider"])
        for key, entry in self.setting_entries.items():
            entry.set_text(selected["settings"][key])
        self.conversation_choices.remove_all()
        self.conversation_choices.append("new", tr("New conversation", "新对话"))
        for conversation in value["conversations"]:
            if conversation["profile_id"] == selected["id"]:
                title = conversation["title"][:36]
                if conversation["settings"] != selected["settings"]:
                    title += tr(" · earlier connection", " · 较早连接")
                self.conversation_choices.append(conversation["id"], title)
        conversation = ai_store.current_chat(value)
        self.conversation_choices.set_active_id(conversation["id"] if conversation else "new")
        self.settings = dict(conversation["settings"] if conversation else selected["settings"])
        self.messages = [dict(message) for message in conversation["messages"]] if conversation else []
        self.last_reply = next((m["content"] for m in reversed(self.messages) if m["role"] == "assistant"), "")
        self.copy_button.set_sensitive(bool(self.last_reply))
        if self.messages:
            for child in self.chat_body.get_children():
                child.destroy()
            self.welcome = None
            for message in self.messages:
                self.add_message(message["role"], message["content"])
        elif self.welcome is None:
            for child in self.chat_body.get_children():
                child.destroy()
        self.update_provider_status()
        self.ai_refreshing = False

    def choose_ai_profile(self, combo):
        if self.ai_refreshing or self.ai_busy or self.ai_saving:
            return
        import ai_store
        identifier = combo.get_active_id()
        if identifier and identifier != self.workspace["active_profile"]:
            self.ai_commit(lambda: ai_store.select_profile(identifier))

    def choose_ai_chat(self, combo):
        if self.ai_refreshing or self.ai_busy or self.ai_saving:
            return
        import ai_store
        identifier = combo.get_active_id()
        if identifier:
            self.ai_commit(ai_store.new_chat if identifier == "new" else lambda: ai_store.select_chat(identifier))

    def add_ai_profile(self):
        import ai_store
        self.ai_commit(ai_store.add_profile, after=lambda: self.toggle_settings() if not self.settings_container.get_visible() else None)

    def new_ai_chat(self):
        import ai_store
        self.ai_commit(ai_store.new_chat)

    def update_provider_status(self):
        provider = tr_legacy("LOCAL · 本地") if self.settings.get("provider") == "ollama" else tr_legacy("API · 接口")
        model = self.settings.get("model") or tr_legacy("Choose a model in settings · 请在设置中选择模型")
        self.provider_status.set_text(f"●  {provider}  /  {model}")

    def find_models(self):
        if self.ai_busy or self.ai_saving:
            return
        from ai_backend import discover_models
        settings = self.draft_settings()
        self.model_generation += 1
        generation = self.model_generation
        self.feedback(tr_legacy("Looking for models… · 正在查找模型…"))

        def current():
            return generation == self.model_generation and settings == self.draft_settings()

        def found(models):
            if not current():
                return
            self.model_choices.remove_all()
            for model in models:
                self.model_choices.append_text(model)
            self.model_choices.set_visible(bool(models))
            if models:
                self.model_choices.set_active(0)
            self.feedback(tr(f"Found {len(models)} models", f"找到 {len(models)} 个模型") if models else tr_legacy("No models found. Check the server and install a model.\n未找到模型，请检查服务并安装模型。"), not bool(models))

        def failed(error):
            if current():
                self.feedback(error, True)
        self.work(lambda: discover_models(settings), found, failed)

    def input_key(self, widget, event):
        # Let Chinese and other IMEs confirm composition before Enter sends a chat.
        if widget.im_context_filter_keypress(event):
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.send_chat()
            return True
        return False

    def add_message(self, role, text):
        if self.welcome:
            self.welcome.destroy()
            self.welcome = None
        bubble = pack(self.chat_body, box(spacing=6, css="message"))
        bubble.get_style_context().add_class("user-message" if role == "user" else "assistant-message")
        pack(bubble, label(tr_legacy("YOU · 你") if role == "user" else tr_legacy("ASSISTANT · 助手"), "message-role"))
        content = pack(bubble, label(text, "message-text", wrap=True, localize=False))
        content.set_selectable(True)
        content.set_max_width_chars(40)
        bubble.show_all()
        return content

    def stop_chat(self):
        request = self.ai_request
        if not self.ai_busy or not request:
            return
        if request.cancel() or request.cancelled:
            self.stop_button.set_sensitive(False)
            self.feedback(tr("Stopping…", "正在停止…"))
        else:
            self.feedback(tr("Saving reply…", "正在保存回复…"))

    def send_chat(self):
        if self.ai_busy or self.ai_saving:
            return
        buffer = self.input.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if not text:
            return
        if not self.settings.get("model"):
            self.feedback(tr_legacy("Choose a model in connection settings first.\n请先在连接设置中选择模型。"), True)
            if not self.settings_container.get_visible():
                self.toggle_settings()
            return
        from ai_backend import ChatRequest
        self.ai_busy = True
        self.model_generation += 1
        self.set_ai_sensitive(False)
        self.send_button.set_no_show_all(True)
        self.send_button.hide()
        self.stop_button.set_no_show_all(False)
        self.stop_button.show()
        self.stop_button.set_sensitive(True)
        self.send_button.set_label(tr_legacy("Thinking… · 思考中…"))
        self.messages.append({"role": "user", "content": text})
        self.add_message("user", text)
        buffer.set_text("")
        self.feedback(tr_legacy("Waiting for your model… · 正在等待模型回复…"))
        pending = self.add_message("assistant", "•••")
        snapshot = [dict(message) for message in self.messages]
        settings = dict(self.settings)
        request = ChatRequest(snapshot, settings)
        self.ai_request = request
        import ai_store
        profile_id = self.workspace["active_profile"]
        conversation = ai_store.current_chat(self.workspace)
        chat_id = conversation["id"] if conversation else None
        before = snapshot[:-1]

        def reset():
            self.ai_busy = False
            self.ai_request = None
            self.stop_button.set_sensitive(False)
            self.stop_button.hide()
            self.stop_button.set_no_show_all(True)
            self.send_button.set_no_show_all(False)
            self.send_button.show()
            self.set_ai_sensitive(True)
            self.send_button.set_label(tr_legacy("Send  ↗  发送"))

        def replied(result):
            if self.ai_request is not request:
                return
            reset()
            self.update_ai_workspace(result)
            self.feedback("")

        def failed(error):
            if self.ai_request is not request:
                return
            reset()
            # work() converts exceptions to display text. Request state retains
            # the cancellation outcome without parsing translated messages.
            if request.cancelled:
                self.update_ai_workspace(self.workspace)
                if not buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
                    buffer.set_text(text)
                self.feedback(tr("Generation stopped", "已停止生成"))
            else:
                pending.set_text(tr_legacy("Could not reach the model · 无法获取模型回复"))
                self.messages.pop()
                if not buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
                    buffer.set_text(text)
                self.feedback(error, True)

        def request_and_save():
            response = request.run()
            return request.commit(lambda: ai_store.append_turn(profile_id, chat_id, settings, before, text, response))
        self.work(request_and_save, replied, failed, commit=True)

    def clear_chat(self):
        if self.ai_busy or self.ai_saving:
            return
        import ai_store
        self.ai_commit(ai_store.delete_chat, after=lambda: self.feedback(tr("Conversation deleted", "对话已删除")))

    def copy_reply(self):
        if self.last_reply:
            # wl-copy retains clipboard ownership after the sidebar closes.
            response = self.last_reply
            self.work(lambda: subprocess.run(["wl-copy"], input=response, capture_output=True,
                                              text=True, check=True, timeout=5),
                      lambda _: self.feedback(tr_legacy("Copied · 已复制")), commit=True)


class Shell(Gtk.Application):
    def __init__(self, mode):
        # GTK 3 uses the program name for xdg_toplevel.app_id, independently of
        # the per-display D-Bus application ID below. Keep compositor rules stable.
        GLib.set_prgname("org.selandia.Glass")
        # A nested preview must never toggle a panel in the user's real session.
        display_id = re.sub(r"[^A-Za-z0-9_]", "_", os.environ.get("WAYLAND_DISPLAY", "desktop"))
        identity = "control" if mode in CONTROL_MODES else mode
        super().__init__(application_id=f"org.selandia.Glass.{identity}.d{display_id}",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.mode = mode
        self.window = None
        self.theme_providers = []
        self.tasks = Tasks(self)

    def request_finish(self):
        """Quit now unless a side-effecting task still has to complete."""
        if self.tasks.request_finish():
            self.quit()

    def reload_theme(self):
        # Re-check the icon theme too: the panel's verified symbolic icons must
        # win again after a light/dark switch changes gtk-icon-theme-name.
        prepare_icon_theme()
        screen = Gdk.Screen.get_default()
        providers = []
        for index, path in enumerate((BASE / "shell" / "style.css", BASE / "theme" / "panel.css",
                                      BASE / "shell" / "control_center.css")):
            if index and not path.exists():
                continue
            provider = Gtk.CssProvider()
            provider.load_from_path(str(path))
            providers.append(provider)
        for provider in self.theme_providers:
            Gtk.StyleContext.remove_provider_for_screen(screen, provider)
        self.theme_providers = providers
        for provider in providers:
            Gtk.StyleContext.add_provider_for_screen(screen, provider,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _live_window(self):
        if self.window is not None and not self.window.alive:
            self.window = None
        return self.window

    def do_command_line(self, command_line):
        args = command_line.get_arguments()
        requested = args[1] if len(args) > 1 else self.mode
        if requested not in SURFACE_KEYS:
            return 2
        window = self._live_window()
        if window is not None and window.mode == "control" and requested in PAGE_KEYS:
            was_closing = window.closing
            if was_closing:
                window.reopen()
            if window.control_stack.get_visible_child_name() == requested and not was_closing:
                window.request_close()
            else:
                window.select_control_tab(requested)
                if not window.is_active():
                    window.hide()
                    window.show_all()
                window.present()
        else:
            self.mode = requested
            self.activate()
        return 0

    def rebuild_control(self, tab):
        old = self.window
        # Keep the application alive while replacing the window after a locale
        # change. Existing workers see old.alive=False and discard stale results.
        self.hold()
        old.rebuilding = True
        old.destroy()
        self.reload_theme()
        self.window = Panel(self, tab)
        self.window.show_all()
        self.release()

    def do_activate(self):
        window = self._live_window()
        if window is not None:
            if window.closing:
                window.reopen()
            else:
                window.request_close()
            return
        self.reload_theme()
        self.window = Panel(self, self.mode)
        self.window.show_all()
        self.window.present()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SURFACE_KEYS:
        print(f"Usage: panel.py {{{'|'.join(SURFACE_KEYS)}}}", file=sys.stderr)
        return 2
    return Shell(sys.argv[1]).run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
