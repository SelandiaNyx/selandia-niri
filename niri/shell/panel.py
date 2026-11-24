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
from navigation_catalog import PAGE_KEYS, PAGES, resolve_route
from settings_navigation import SettingsNavigation
from command_palette import CommandPalette
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
        requested_tab, requested_subtab = resolve_route(mode) if mode in CONTROL_MODES and mode != "control" else ("quick", None)
        mode = "control" if mode in CONTROL_MODES else mode
        super().__init__(application=app, title=f"Selandia · {mode}")
        self.mode = mode
        self.alive = True
        self.closing = False
        self._close_callback = None
        self._nav_history = []
        self._nav_index = -1
        self._shortcut_timer = None
        self._shortcut_category = "all"
        self.command_palette = None
        self.header_avatar_image = None
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
            from appearance import mascot_asset
            avatar_path = mascot_asset(preferences.get("mascot", "gemini"), "avatar")
            if avatar_path.is_file():
                try:
                    gi.require_version("GdkPixbuf", "2.0")
                    from gi.repository import GdkPixbuf
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(avatar_path), 52, 52, True)
                    avatar_frame = box(spacing=0, css="mascot-avatar-frame")
                    avatar_frame.set_valign(Gtk.Align.CENTER)
                    self.header_avatar_image = Gtk.Image.new_from_pixbuf(pixbuf)
                    pack(avatar_frame, self.header_avatar_image)
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
            pack(titles, label(tr("Control Center", "控制中心"), "control-heading"))
            pack(titles, label(f"{greeting} · {platform.node()} · Niri", "control-caption", localize=False))
        else:
            pack(titles, label("G E M I N I  ✦  N I R I", "eyebrow", localize=False))
            pack(titles, label(title, "panel-title"))
            pack(titles, label(subtitle, "subtitle"))
        if mode == "control":
            nav_back = pack(header, button("‹", self.nav_back, "close-button", tr("Back (Alt+Left)", "后退（Alt+左）")))
            nav_back.set_valign(Gtk.Align.START)
            self.nav_back_btn = nav_back
            nav_fwd = pack(header, button("›", self.nav_forward, "close-button", tr("Forward (Alt+Right)", "前进（Alt+右）")))
            nav_fwd.set_valign(Gtk.Align.START)
            self.nav_fwd_btn = nav_fwd
            palette_btn = pack(header, button("⌘ Ctrl+K", self.open_command_palette, "small-button",
                                              tr("Quick search any setting (Ctrl+K)", "全局快搜任意设置或动作（Ctrl+K）")))
            palette_btn.set_valign(Gtk.Align.START)
            self.live_badge = pack(header, label(tr("●  LIVE", "●  实时"), "live-badge"))
            self.live_badge.set_valign(Gtk.Align.START)
            self.live_badge.set_no_show_all(True)
            help_button = pack(header, button("?", lambda: self.show_keyboard_help(help_button),
                                              "close-button", tr("Keyboard help (F1)", "键盘操作帮助（F1）")))
            self.help_button = help_button
            help_button.set_valign(Gtk.Align.START)
        close = pack(header, button("×", self.request_close, "close-button", tr("Close (Esc)", "关闭（Esc）")))
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
            self.command_palette = CommandPalette(self)
            self.shell.add_overlay(self.command_palette)
            self.protect_scroll_controls(self.content)
            self.control_stack.show_all()
            self.select_control_tab(requested_tab, subtab=requested_subtab)
        elif mode == "shortcuts":
            self.build_shortcuts()
        elif mode == "calendar":
            self.build_calendar()
        else:
            self.build_ai()

    def build_calendar(self):
        from calendar_widget import LocalizedCalendar, date_caption
        from i18n import get_language
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
        # Keep Today/Copy snugly beneath the calendar card inside the scroll body
        # so on tall 4K screens they are never stranded 1,400 px away at the bottom.
        footer = pack(body, box(spacing=10, css="card"))
        footer.get_style_context().add_class("calendar-footer")
        date_row = pack(footer, box(False, 10))
        self.calendar_date = pack(date_row, label("", "calendar-date"))
        self.calendar_date.set_ellipsize(Pango.EllipsizeMode.END)
        self.calendar_date.set_max_width_chars(12)
        self.calendar_lunar = pack(date_row, label("", "lunar-label", localize=False), True)
        self.calendar_lunar.set_xalign(1.0)
        self.calendar_lunar.set_ellipsize(Pango.EllipsizeMode.END)

        def get_formatted_date():
            year, month, day = self.calendar.get_date()
            return f"{year:04d}-{month+1:02d}-{day:02d}"

        def selected(*_):
            year, month, day = self.calendar.get_date()
            self.calendar_date.set_text(f"{year:04d}-{month+1:02d}-{day:02d}")
            self.calendar_lunar.set_text(date_caption(year, month + 1, day, get_language() == "zh_CN"))

        def today():
            date = datetime.date.today()
            self.calendar.select_month(date.month - 1, date.year)
            self.calendar.select_day(date.day)

        def copy_date():
            date_str = get_formatted_date()
            def write_clip():
                try:
                    subprocess.run(["wl-copy"], input=date_str, text=True,
                                   capture_output=True, check=True, timeout=4)
                    return True
                except (OSError, subprocess.SubprocessError):
                    return False
            def copied(ok):
                if not ok:
                    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
                    clipboard.set_text(date_str, -1)
                    clipboard.store()
                self.feedback(tr(f"Copied {date_str} to clipboard", f"已复制 {date_str} 到剪贴板"))
            self.work(write_clip, copied, commit=True)

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

    def refresh_header_avatar(self, skin: str | None = None):
        if self.header_avatar_image is None:
            return
        try:
            from appearance import mascot_asset
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            path = mascot_asset(skin, "avatar")
            if path.is_file():
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 52, 52, True)
                self.header_avatar_image.set_from_pixbuf(pix)
        except Exception:
            pass

    def open_command_palette(self):
        if self.command_palette is not None:
            self.command_palette.open()

    def nav_back(self):
        if self._nav_index > 0:
            self._nav_index -= 1
            tab, subtab = self._nav_history[self._nav_index]
            self.select_control_tab(tab, subtab=subtab, _record=False)

    def nav_forward(self):
        if 0 <= self._nav_index < len(self._nav_history) - 1:
            self._nav_index += 1
            tab, subtab = self._nav_history[self._nav_index]
            self.select_control_tab(tab, subtab=subtab, _record=False)

    def _update_nav_buttons(self):
        if hasattr(self, "nav_back_btn"):
            self.nav_back_btn.set_sensitive(self._nav_index > 0)
        if hasattr(self, "nav_fwd_btn"):
            self.nav_fwd_btn.set_sensitive(0 <= self._nav_index < len(self._nav_history) - 1)

    def open_unit_logs(self, scope: str, unit: str):
        self.select_control_tab("logs")
        entry = self.page_host.entries.get("logs") if self.page_host else None
        if entry is not None and hasattr(entry.content, "inspect_unit"):
            entry.content.inspect_unit(scope, unit)

    def desktop_script(self) -> str:
        return DESKTOP

    def launch_external(self, command):
        """Launch an auxiliary app or terminal WITHOUT destroying Control Center."""
        def start():
            subprocess.Popen(command, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        self.work(start, None, lambda err: self.feedback(str(err), True), commit=True)

    def show_keyboard_help(self, anchor):
        content = box(spacing=8)
        pack(content, label(tr("Keyboard shortcuts", "键盘操作快捷键"), "section-title"))
        for instruction in (tr("Ctrl + K  Global setting & command search", "Ctrl + K  全局命令与设置快搜"),
                            tr("Ctrl + F  Search sidebar / page", "Ctrl + F  搜索侧栏或当前页"),
                            tr("Alt + 1…6  Jump to category group", "Alt + 1…6  快速切换 6 大分组"),
                            tr("Ctrl + 1…9  Select page", "Ctrl + 1…9  切换前 9 页"),
                            tr("Alt + ← / →  Navigation history", "Alt + ← / →  页面浏览后退 / 前进"),
                            tr("Ctrl + S  Apply current page", "Ctrl + S  应用当前页更改"),
                            tr("F5 / Ctrl + R  Refresh current page", "F5 / Ctrl + R  刷新当前页"),
                            tr("Esc  Back / cancel / close", "Esc  逐层取消、返回总览或关闭")):
            pack(content, label(instruction, "hint"))
        self.show_popover(anchor, content)

    def protect_scroll_controls(self, widget):
        """Scrolling a settings page must not silently edit the hovered control."""
        protect_scroll(widget)

    def on_control_scroll(self, widget, event):
        return handle_scroll(widget, event)

    def show_connection_details(self, key, anchor):
        self.select_control_tab("bluetooth" if key == "bluetooth" else "network", focus=True)

    def on_key(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        if self.mode == "control":
            if event.keyval == Gdk.KEY_F1:
                self.show_keyboard_help(self.help_button)
                return True
            if event.keyval == Gdk.KEY_F5 or (ctrl and event.keyval in (Gdk.KEY_r, Gdk.KEY_R)):
                self.refresh_visible_page()
                return True
            if ctrl and event.keyval in (Gdk.KEY_k, Gdk.KEY_K):
                if self.command_palette is not None:
                    self.command_palette.close() if self.command_palette.is_open() else self.command_palette.open()
                return True
            if ctrl and event.keyval in (Gdk.KEY_w, Gdk.KEY_W):
                self.request_close()
                return True
            if ctrl and event.keyval in (Gdk.KEY_s, Gdk.KEY_S):
                self._apply_current_page()
                return True
            if alt and event.keyval == Gdk.KEY_Left:
                self.nav_back()
                return True
            if alt and event.keyval == Gdk.KEY_Right:
                self.nav_forward()
                return True
            if alt and Gdk.KEY_1 <= event.keyval <= Gdk.KEY_6:
                idx = event.keyval - Gdk.KEY_1
                groups = getattr(self.navigation, "group_first_keys", ())
                if idx < len(groups):
                    self.select_control_tab(groups[idx], focus=True)
                return True
            if ctrl:
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
        if self.mode == "ai" and ctrl:
            if event.keyval in (Gdk.KEY_period, Gdk.KEY_KP_Decimal):
                self.stop_chat()
                return True
        if event.keyval == Gdk.KEY_Escape:
            if self.mode == "control" and self.command_palette is not None and self.command_palette.is_open():
                self.command_palette.close()
                return True
            if self.active_popover:
                self.active_popover.popdown()
                return True
            if self.mode == "shortcuts" and getattr(self, "shortcut_search", None) is not None and self.shortcut_search.get_text():
                self.shortcut_search.set_text("")
                return True
            # If user is typing inside an in-page SearchEntry, clear it before leaving the page.
            focused = self.get_focus()
            if isinstance(focused, Gtk.SearchEntry) and focused is not getattr(getattr(self, "navigation", None), "search", None) and focused.get_text():
                focused.set_text("")
                return True
            if self.mode == "control" and self.page_host is not None:
                cur = self.control_stack.get_visible_child_name()
                entry = self.page_host.entries.get(cur)
                if cur == "displays" and entry is not None and getattr(entry.content, "token", None):
                    entry.content.revert()
                    return True
            if self.mode == "control" and self.navigation.search.get_text():
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

    def _apply_current_page(self):
        name = self.control_stack.get_visible_child_name()
        if name == "appearance":
            self.apply_appearance()
            return
        entry = self.page_host.entries.get(name) if self.page_host else None
        if entry is not None and hasattr(entry.content, "apply"):
            entry.content.apply()

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
                                             "wallpapers", "monitor"))
        self.settings_pages = PageMap(self.page_host, settings_keys)

    def _page_factory(self, key):
        if key == "quick":
            return self._build_quick()
        if key == "sound":
            return self._build_sound()
        if key in ("monitor", "system"):
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
        self.work(self.quick_sampler.prime)
        body = build_overview(self)
        revealer = getattr(self, "quick_details_revealer", None)
        if revealer is not None:
            revealer.set_transition_duration(
                160 if animations_enabled(self.surface, not self.reduced_motion) else 0)
        return PageEntry(body, scroller(body))

    def build_sound(self):
        """Compatibility adapter for the former eager page builder."""
        if self.page_host is not None:
            return self.page_host.ensure("sound").content
        return self._build_sound().content

    def build_system(self):
        """Compatibility adapter for the former eager page builder."""
        if self.page_host is not None:
            return self.page_host.ensure("monitor").content
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
        from desktop_controls import DesktopSettings, InputSettings
        from panel_bluetooth import BluetoothPage
        from panel_logs import LogsPage
        from panel_network import NetworkPage
        from panel_packages import PackagesPage
        from panel_preferences import PreferencesPage
        from panel_security import SecurityPage
        from panel_services import ServicesPage
        from panel_storage import StoragePage
        from system_controls import NotificationSettings, PowerSettings
        factories = {
            "network": NetworkPage,
            "bluetooth": BluetoothPage,
            "input": InputSettings,
            "storage": StoragePage,
            "desktop": DesktopSettings,
            "services": ServicesPage,
            "logs": LogsPage,
            "packages": PackagesPage,
            "security": SecurityPage,
            "power": PowerSettings,
            "notifications": NotificationSettings,
            "preferences": PreferencesPage,
        }
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
        if self.page_visible("quick"):
            self.refresh_control()
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "refresh"):
                media.refresh()
        elif self.page_visible("sound"):
            self.refresh_audio()
        elif self.page_visible("monitor") or self.page_visible("system"):
            self.refresh_system_info()
            self.refresh_metrics(prime=True)
        elif self.page_host is not None and name in self.page_host.entries:
            content = self.page_host.entries[name].content
            if hasattr(content, "refresh"):
                content.refresh()

    def refresh_visible_page(self, *_):
        name = self.control_stack.get_visible_child_name()
        if name is None:
            return
        refresh = getattr(self, "_refresh_page", None)
        if refresh is not None:
            refresh(name)
            return
        if self.page_visible("quick"):
            self.refresh_control()
            self.media_controls.refresh()
        elif self.page_visible("sound"):
            self.refresh_audio()
        elif self.page_visible("monitor") or self.page_visible("system"):
            self.refresh_system_info()
            self.refresh_metrics(prime=True)

    def _page_shown(self, name):
        if not self.page_visible(name):
            return
        if getattr(self, "live_badge", None) is not None:
            self.live_badge.set_visible(name in ("quick", "monitor"))
        if name == "quick":
            self.refresh_control()
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "resume"):
                media.resume()
            self.start_quick_tick()
        elif name == "sound":
            self.refresh_audio()
            self.start_audio_tick()
        elif name == "monitor":
            self.refresh_system_info()
            self.refresh_metrics(prime=True)
            self.start_metrics_tick()
        elif name == "wallpapers" and self.page_host is not None:
            entry = self.page_host.entries.get("wallpapers")
            if entry is not None:
                entry.content.resume()
        elif self.page_host is not None and name in self.page_host.entries:
            content = self.page_host.entries[name].content
            if hasattr(content, "resume"):
                content.resume()
            if hasattr(content, "refresh"):
                content.refresh()

    def _page_hidden(self, name):
        if name == "quick":
            self.stop_quick_tick()
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "suspend"):
                media.suspend()
        elif name == "sound":
            self.stop_audio_tick()
            changes = getattr(self, "audio_changes", None)
            if changes is not None:
                self.audio_changes = None
                changes.close()
                thread = changes.thread
                if thread.ident is not None:
                    self.work(lambda: thread.join(3), commit=True)
        elif name == "monitor":
            self.metrics_generation = getattr(self, "metrics_generation", 0) + 1
            self.stop_metrics_tick()
        elif self.page_host is not None and name in self.page_host.entries:
            content = self.page_host.entries[name].content
            if hasattr(content, "suspend"):
                content.suspend()

    def _page_dispose(self, name):
        self._page_hidden(name)
        if name == "quick":
            media = getattr(self, "media_controls", None)
            if media is not None and hasattr(media, "dispose"):
                media.dispose()
        elif name == "wallpapers" and self.page_host is not None:
            entry = self.page_host.entries.get("wallpapers")
            if entry is not None:
                entry.content.cleanup()

    def start_quick_tick(self):
        if self.quick_tick_source is None and self.alive:
            # 10s cadence (down from 5s) cuts idle Overview subprocess churn in half.
            self.quick_tick_source = GLib.timeout_add_seconds(10, self.refresh_control)
            self.pending.add(self.quick_tick_source)

    def stop_quick_tick(self):
        source = self.quick_tick_source
        self.quick_tick_source = None
        if source is not None:
            self.pending.discard(source)
            GLib.source_remove(source)

    def select_control_tab(self, tab, focus=False, subtab=None, _record=True):
        tab, alias_subtab = resolve_route(tab)
        subtab = subtab or alias_subtab
        if self.mode == "control" and tab in self.control_pages:
            configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
            if self.page_host is not None:
                entry = self.page_host.ensure(tab)
                if subtab and hasattr(entry.content, "select_subtab"):
                    entry.content.select_subtab(subtab)
            self.control_stack.set_visible_child_name(tab)
            self.navigation.select(tab, focus=focus)
            spec = next(item for item in PAGES if item[0] == tab)
            self.page_heading.set_text(tr(spec[1], spec[2]))
            self.page_heading.set_visible(self.panel_width >= 650 or tab != "wallpapers")
            if getattr(self, "live_badge", None) is not None:
                self.live_badge.set_visible(tab in ("quick", "monitor"))
            if _record:
                rec = (tab, subtab)
                if self._nav_index < 0 or self._nav_history[self._nav_index] != rec:
                    self._nav_history = self._nav_history[:self._nav_index + 1] + [rec]
                    self._nav_index = len(self._nav_history) - 1
            self._update_nav_buttons()
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
        self._shortcut_category = "all"
        search = Gtk.SearchEntry()
        search.set_placeholder_text(tr("Search keys or actions…", "搜索按键或功能…"))
        search.connect("search-changed", self.filter_shortcuts)
        self.shortcut_search = search
        pack(self.content, search)
        # Category filter strip for instant one-click narrowing.
        cat_flow = Gtk.FlowBox()
        cat_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        cat_flow.set_column_spacing(6)
        cat_flow.set_row_spacing(6)
        cat_flow.set_max_children_per_line(10)
        self._shortcut_cat_buttons = {}
        categories = [("all", (tr("All", "全部"), tr("All", "全部")))]
        seen_cats = set()
        for item in self.shortcuts:
            cat = item["category"]
            if cat not in seen_cats:
                seen_cats.add(cat)
                categories.append((cat, cat))
        for cat_key, cat_pair in categories:
            lbl = tr("All", "全部") if cat_key == "all" else tr(*cat_pair)
            btn = Gtk.ToggleButton(label=lbl)
            btn.get_style_context().add_class("small-button")
            btn.set_active(cat_key == "all")
            btn.connect("toggled", self._select_shortcut_category, cat_key)
            self._shortcut_cat_buttons[cat_key] = btn
            cat_flow.add(btn)
        pack(self.content, cat_flow)
        self.shortcut_summary = pack(self.content, label("", "subtitle"))
        self.shortcut_body = box(spacing=14)
        pack(self.content, scroller(self.shortcut_body), True)
        footer = pack(self.content, box(False, 8))
        pack(footer, label(tr("Mod = Super / Windows  ·  Esc = Clear search / Close", "Mod = Super / Windows  ·  Esc = 清空搜索或关闭"), "hint"), True)
        self.render_shortcuts("")
        GLib.idle_add(search.grab_focus)

    def _select_shortcut_category(self, toggle, category_key):
        if getattr(self, "_updating_shortcut_cats", False):
            return
        if not toggle.get_active():
            if self._shortcut_category == category_key:
                self._updating_shortcut_cats = True
                toggle.set_active(True)
                self._updating_shortcut_cats = False
            return
        self._updating_shortcut_cats = True
        try:
            self._shortcut_category = category_key
            for key, btn in self._shortcut_cat_buttons.items():
                btn.set_active(key == category_key)
        finally:
            self._updating_shortcut_cats = False
        self.render_shortcuts(self.shortcut_search.get_text().strip().casefold())

    def filter_shortcuts(self, search):
        if self._shortcut_timer is not None:
            self.pending.discard(self._shortcut_timer)
            GLib.source_remove(self._shortcut_timer)
            self._shortcut_timer = None
        query = search.get_text().strip().casefold()
        def run():
            if self._shortcut_timer is not None:
                self.pending.discard(self._shortcut_timer)
                self._shortcut_timer = None
            if self.alive:
                self.render_shortcuts(query)
            return GLib.SOURCE_REMOVE
        self._shortcut_timer = GLib.timeout_add(120, run)
        self.pending.add(self._shortcut_timer)

    def render_shortcuts(self, query):
        for child in self.shortcut_body.get_children():
            child.destroy()
        groups = {}
        count = 0
        active_cat = getattr(self, "_shortcut_category", "all")
        for item in self.shortcuts:
            if active_cat != "all" and item["category"] != active_cat:
                continue
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
            pack(self.shortcut_body, label(tr("No matching shortcuts", "未找到匹配的快捷键"), "empty-state"))
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
        if window is not None and window.mode == "control" and requested in CONTROL_MODES and requested != "control":
            target_tab, target_sub = resolve_route(requested)
            was_closing = window.closing
            if was_closing:
                window.reopen()
            if window.control_stack.get_visible_child_name() == target_tab and not target_sub and not was_closing:
                window.request_close()
            else:
                window.select_control_tab(target_tab, subtab=target_sub)
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
