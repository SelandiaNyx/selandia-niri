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
from panel_support import (
    BASE,
    DESKTOP,
    ENV,
    capture,
    probe,
    power_runtime_state,
    bluetooth_state,
    set_bluetooth,
    panel_monitor,
    label,
    box,
    button,
    pack,
    scroller,
)
from panel_audio import AudioPage
from panel_system import SystemPage
from panel_appearance import AppearancePage
from panel_quick import QuickControlsPage
from panel_ai import AiPage

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango


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


class Panel(AudioPage, SystemPage, AppearancePage, QuickControlsPage, AiPage, Gtk.ApplicationWindow):
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
        self.get_style_context().add_class(f"{mode}-window")
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
        header = pack(self.surface, box(False, 14, "panel-header"))
        if mode == "control":
            header.get_style_context().add_class("control-header")
            avatar_path = BASE / "assets/anime/mascot-avatar.png"
            if avatar_path.is_file():
                try:
                    gi.require_version("GdkPixbuf", "2.0")
                    from gi.repository import GdkPixbuf
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(avatar_path), 54, 54, True)
                    avatar_frame = box(spacing=0, css="mascot-avatar-frame")
                    avatar_frame.set_valign(Gtk.Align.CENTER)
                    pack(avatar_frame, Gtk.Image.new_from_pixbuf(pixbuf))
                    pack(header, avatar_frame)
                except (GLib.Error, OSError, ValueError):
                    pass
        titles = pack(header, box(spacing=4), True)
        if mode == "control":
            hour = datetime.datetime.now().hour
            if 5 <= hour < 12:
                greeting = tr("Good morning, Master", "早上好，主人")
            elif 12 <= hour < 18:
                greeting = tr("Good afternoon, Master", "下午好，主人")
            elif 18 <= hour < 23:
                greeting = tr("Good evening, Master", "晚上好，主人")
            else:
                greeting = tr("Late night, Master", "夜深了，主人")
            pack(titles, label(tr("Settings", "设置"), "control-heading"))
            pack(titles, label(f"{greeting} · {platform.node()} · Niri", "control-caption", localize=False))
        else:
            pack(titles, label("S E L A N D I A  ✦  N Y X", "eyebrow", localize=False))
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
            if getattr(self.navigation, "mascot_box", None) is not None:
                self.navigation.mascot_box.set_no_show_all(True)
                self.navigation.mascot_box.hide()
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
