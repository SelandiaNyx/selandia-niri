#!/usr/bin/env python3
"""Selandia's native layer-shell panels. No browser runtime or background daemon."""
from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading

import gi
import brightness
import sleep_guard
from panel_motion import PanelMotion, animations_enabled, configure_stack
from i18n import tr, tr_legacy
from settings_navigation import PAGE_KEYS, PAGES, SettingsNavigation
from control_widgets import prepare_icon_theme
from scroll_guard import protect as protect_scroll, handle as handle_scroll

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango

BASE = Path(__file__).resolve().parent.parent
DESKTOP = str(BASE / "scripts" / "desktop")
ENV = dict(os.environ, LC_ALL="C")
CONTROL_MODES = frozenset(PAGE_KEYS) | {"control"}


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


class Panel(Gtk.ApplicationWindow):
    def __init__(self, app, mode):
        requested_tab = mode if mode in PAGE_KEYS else "quick"
        mode = "control" if mode in CONTROL_MODES else mode
        super().__init__(application=app, title=f"Selandia · {mode}")
        self.mode = mode
        self.alive = True
        from appearance import load_settings
        preferences = load_settings()
        self.reduced_motion = preferences.get("reduced_motion", False)
        self.get_settings().set_property("gtk-application-prefer-dark-theme", preferences.get("color_mode", "dark") == "dark")
        self.active_popover = None
        self.pending = set()
        self.connect("destroy", self.on_destroy)
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
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geometry = monitor.get_geometry()
        width = min(860 if mode == "shortcuts" else (960 if mode == "control" else 440), max(300, geometry.width - 32))
        height = min(820, max(360, geometry.height - 104))
        self.panel_width = width
        self.available_height = geometry.height - 82
        self.set_default_size(width, height)
        self.set_size_request(width, height if mode == "shortcuts" else -1)
        if GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, f"selandia-{mode}")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)
            GtkLayerShell.set_exclusive_zone(self, 0)
            if mode != "shortcuts":
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
                GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 16)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 12 if mode == "control" else 66)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM,
                                         max(16, geometry.height - height - 70) if mode == "control" else 16)
        else:
            self.set_position(Gtk.WindowPosition.CENTER)
        self.surface = box(spacing=0, css="glass-surface")
        self.add(self.surface)
        self.motion = PanelMotion(self.surface, enabled=lambda: not self.reduced_motion)
        self.connect("map", self.on_map)
        title, subtitle = {
            "control": ("Control Center", "控制中心  ·  Your desktop, at a touch"),
            "shortcuts": ("Keyboard Atlas", "快捷键总览  ·  Find your next move"),
            "ai": ("Intelligence", "AI 侧边栏  ·  A little room to think"),
        }[mode]
        header = pack(self.surface, box(False, 12, "panel-header"))
        titles = pack(header, box(spacing=4), True)
        if mode == "control":
            header.get_style_context().add_class("control-header")
            pack(titles, label(tr("Settings", "设置"), "control-heading"))
            pack(titles, label("Selandia · Niri", "control-caption"))
            time = pack(header, box(spacing=2))
            self.clock = pack(time, label("", "control-clock"))
            self.date = pack(time, label("", "control-caption"))
        else:
            pack(titles, label("S E L A N D I A", "eyebrow"))
            pack(titles, label(title, "panel-title"))
            pack(titles, label(subtitle, "subtitle"))
        if mode == "control":
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
        else:
            self.build_ai()

    def on_destroy(self, *_):
        self.alive = False
        for source in self.pending:
            GLib.source_remove(source)
        self.pending.clear()
        if not getattr(self, "rebuilding", False):
            # A pending commit keeps the application alive until it is complete;
            # this window itself never waits for it.
            self.get_application().request_finish()

    def request_close(self):
        if self.alive:
            self.motion.dismiss(self.destroy)

    def on_map(self, *_):
        self.motion.reveal()
        if self.mode == "control":
            self.focus_control_tab()

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
        threading.Thread(target=run, daemon=True).start()

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
                      lambda _: self.destroy(), failed)
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
        columns = pack(self.content, box(False, 18), True)
        self.navigation = SettingsNavigation(self)
        self.control_switcher = self.navigation.list
        pack(columns, self.navigation)
        pages = pack(columns, box(spacing=12), True)
        self.page_heading = pack(pages, label("", "settings-page-title"))
        pack(pages, self.control_stack, True)
        from quick_controls import build_overview
        body = build_overview(self)
        self.control_stack.add_titled(scroller(body), "quick", "总览")
        self.build_sound()
        self.build_system()
        from display_controls import DisplaySettings
        self.display_settings = DisplaySettings(self)
        self.control_stack.add_titled(scroller(self.display_settings), "displays", "屏幕")
        self.build_appearance()
        from desktop_controls import InputSettings, DesktopSettings
        from language_controls import LanguageSettings
        from system_controls import (ApplicationsSettings, PowerSettings, TimeSettings,
                                     StartupSettings, ServicesSettings, ToolsSettings, ConnectionsSettings)
        self.settings_pages = {
            "input": InputSettings(self), "desktop": DesktopSettings(self),
            "language": LanguageSettings(self), "applications": ApplicationsSettings(self),
            "power": PowerSettings(self), "time": TimeSettings(self),
            "startup": StartupSettings(self), "services": ServicesSettings(self),
            "network": ConnectionsSettings(self),
            **{key: ToolsSettings(self, key) for key in ("hardware", "security")},
        }
        for key, page in self.settings_pages.items():
            self.control_stack.add_named(scroller(page), key)
        titles = {key: tr(english, chinese) for key, english, chinese, *_ in PAGES}
        for child in self.control_stack.get_children():
            name = self.control_stack.child_get_property(child, "name")
            self.control_stack.child_set_property(child, "title", titles[name])
        self.refresh_control()
        self.pending.add(GLib.timeout_add_seconds(5, self.refresh_control))

    def select_control_tab(self, tab, focus=False):
        if self.mode == "control" and tab in self.control_pages:
            configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
            self.control_stack.set_visible_child_name(tab)
            self.navigation.select(tab, focus=focus)
            spec = next(item for item in PAGES if item[0] == tab)
            self.page_heading.set_text(tr(spec[1], spec[2]))
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

    def build_sound(self):
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
        self.control_stack.add_titled(scroller(body), "sound", tr_legacy("Sound\n声音"))
        self.audio_status = pack(body, self.compact_label(tr_legacy("Reading audio devices… · 读取音频设备…")))
        self.audio_advanced = Gtk.CheckButton.new_with_label(tr_legacy("显示高级通道 · Show all audio channels"))
        self.audio_advanced.set_tooltip_text(tr_legacy("包括未连接接口、专业通道、虚拟设备与回录通道。\nIncludes disconnected ports, Pro Audio, virtual and monitor channels."))
        self.audio_advanced.connect("toggled", self.audio_advanced_changed)
        pack(body, self.audio_advanced)
        self.audio_controls = pack(body, box(spacing=12))
        for kind, heading in [("sink", tr_legacy("OUTPUT  /  输出设备")), ("source", tr_legacy("INPUT  /  输入设备"))]:
            card = self.card(self.audio_controls, heading)
            combo = self.audio_combo()
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
        pack(body, button(tr_legacy("Full mixer & app volumes · 完整混音器与应用音量"),
                          lambda: self.desktop("launch", "audio"), "accent-button"))
        pack(body, button(tr_legacy("Refresh audio devices · 刷新音频设备"), self.refresh_audio))
        self.audio_controls.set_sensitive(False)
        self.refresh_audio()
        self.pending.add(GLib.timeout_add_seconds(5, self.refresh_audio))

    def audio_advanced_changed(self, _check):
        self.audio_generation += 1
        self.audio_deferred_state = None
        self.refresh_audio()

    def refresh_audio(self):
        if not self.alive:
            return GLib.SOURCE_REMOVE
        if self.audio_loading or self.audio_busy:
            return GLib.SOURCE_CONTINUE
        from audio_backend import read_state
        self.audio_loading = True
        generation = self.audio_generation
        advanced = self.audio_advanced.get_active()

        def done(state):
            self.audio_loading = False
            if generation == self.audio_generation and not self.audio_busy:
                self.apply_audio(state)
            elif not self.audio_busy:
                self.refresh_audio()

        def failed(error):
            self.audio_loading = False
            if generation == self.audio_generation and not self.audio_busy:
                self.audio_controls.set_sensitive(False)
                self.audio_status.set_text(tr("Audio unavailable", "音频不可用") + f"\n{error}")
            elif not self.audio_busy:
                self.refresh_audio()
        self.work(lambda: read_state(include_unavailable=advanced), done, failed)
        return GLib.SOURCE_CONTINUE

    def apply_audio(self, state):
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
            details.append(tr(f"{count} advanced channels hidden", f"已收起 {count} 个高级通道"))
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

    def build_system(self):
        from metrics import MetricsSampler
        self.metrics_sampler = MetricsSampler()
        self.metrics_busy = False
        self.system_info_busy = False
        body = box(spacing=12)
        self.control_stack.add_titled(scroller(body), "system", tr_legacy("System\n系统"))
        header = pack(body, box(False, 6))
        pack(header, label(tr_legacy("LIVE  /  实时监控"), "section-title"), True)
        pack(header, label(tr_legacy("2 s · 每两秒"), "hint"))
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
            grid.attach(metric, index % 2, index // 2, 1, 1)
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
        system = self.card(body, tr_legacy("ABOUT THIS SYSTEM  /  系统信息"))
        self.system_detail = pack(system, self.compact_label(tr_legacy("Reading system… · 读取系统…")))
        self.system_detail.set_selectable(True)
        pack(system, button(tr_legacy("Refresh displays & system · 刷新屏幕与系统"), self.refresh_system_info, "small-button"))
        self.refresh_system_info()
        self.refresh_metrics()
        self.pending.add(GLib.timeout_add_seconds(2, self.refresh_metrics))

    def action_grid(self, parent, actions):
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        pack(parent, grid)
        for index, (title, callback) in enumerate(actions):
            grid.attach(button(title, callback, "tool-button"), index % 2, index // 2, 1, 1)

    def refresh_metrics(self):
        if not self.alive:
            return GLib.SOURCE_REMOVE
        if not self.metrics_busy:
            self.metrics_busy = True
            self.work(self.metrics_sampler.sample, self.apply_metrics, self.metrics_error)
        return GLib.SOURCE_CONTINUE

    def metrics_error(self, error):
        self.metrics_busy = False
        self.sensor_detail.set_text(tr("Monitoring unavailable", "监控不可用") + f"\n{error}")

    def apply_metrics(self, values):
        from metrics import format_bytes, format_rate, format_percent, format_uptime
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
            parts = [item.get("name") or "GPU", format_percent(item.get("percent"))]
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
            sensors.append(tr(f"Peak {max(item['celsius'] for item in temperatures):.0f}°C · {len(temperatures)} sensors",
                              f"最高温度 {max(item['celsius'] for item in temperatures):.0f}°C · {len(temperatures)} 个传感器"))
            self.sensor_readings.set_text("\n".join(f"{item['name']} · {item['celsius']:.0f}°C" for item in temperatures))
        else:
            sensors.append(tr_legacy("Temperature unavailable · 温度不可用"))
            self.sensor_readings.set_text(tr_legacy("No temperature sensors · 无温度传感器"))
        self.sensor_detail.set_text("\n".join(sensors))

    def refresh_system_info(self):
        if not self.alive or self.system_info_busy:
            return
        self.system_info_busy = True

        def read():
            try:
                system_name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
            except OSError:
                system_name = "Linux"
            output = probe(["niri", "msg", "--json", "outputs"])
            try:
                outputs = json.loads(output) if output else {}
            except (ValueError, TypeError):
                outputs = {}
            return (f"{system_name}\n{platform.release()} · {platform.machine()}\nNiri · Wayland",
                    self.describe_outputs(outputs))

        def done(result):
            self.system_info_busy = False
            self.system_detail.set_text(result[0])
            self.display_detail.set_text(result[1])

        def failed(error):
            self.system_info_busy = False
            self.system_detail.set_text(tr("Unavailable", "不可用") + f"\n{error}")
        self.work(read, done, failed)

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

    def build_appearance(self):
        from appearance import DEFAULTS, PRESETS, load_settings
        self.appearance_busy = True
        body = box(spacing=12)
        self.appearance_body = body
        self.control_stack.add_titled(scroller(body), "appearance", tr_legacy("Style\n外观"))
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
        pack(theme, self.compact_label(tr_legacy("统一桌面配色，并同步 GTK / Qt 应用的明暗模式。\nShared desktop palette and matching GTK / Qt light or dark mode.")))
        self.reduced_motion_check = Gtk.CheckButton(label=tr_legacy("减少动态效果 · Reduce motion"))
        pack(theme, self.reduced_motion_check)
        opacity_row = pack(theme, box(False, 6))
        pack(opacity_row, label(tr_legacy("Surface opacity · 面板不透明度"), "control-label"), True)
        self.opacity_value = pack(opacity_row, label("", "value"))
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 65, 100, 1)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.connect("value-changed", lambda scale: self.opacity_value.set_text(f"{scale.get_value():.0f}%"))
        pack(theme, self.opacity_scale)
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

    def populate_appearance(self, settings):
        self.color_mode_combo.set_active_id(settings.get("color_mode", "dark"))
        self.reduced_motion_check.set_active(settings.get("reduced_motion", False))
        self.theme_combo.set_active_id(settings["preset"])
        self.opacity_scale.set_value(settings["opacity"] * 100)
        installed = {family.get_name() for family in self.get_pango_context().list_families()}
        for key, size_key in [("font", "font_size"), ("mono_font", "mono_size")]:
            requested = settings[key]
            fallbacks = ("Noto Sans CJK SC", "Noto Sans", "Sans") if key == "font" else ("JetBrainsMono Nerd Font", "Monospace")
            selected = requested if requested in installed else next((name for name in fallbacks if name in installed), fallbacks[-1])
            self.font_buttons[key].set_font(f"{selected} {settings[size_key]}")
            self.font_buttons[key].set_tooltip_text(
                None if selected == requested else tr(f"{requested} is unavailable; using {selected}", f"未安装 {requested}；已选择 {selected}"))
            self.font_sizes[key].set_value(settings[size_key])

    def draft_appearance(self):
        return {
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
        self.quick_details_revealer.set_transition_duration(
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
            result = restore_defaults() if reset else apply_settings(settings)
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
        self.clock.set_text(datetime.datetime.now().strftime("%H:%M"))
        now = datetime.datetime.now()
        self.date.set_text(tr(now.strftime("%m.%d · %a"), now.strftime("%m月%d日 · ") + "星期" + "一二三四五六日"[now.weekday()]))
        if self.refreshing:
            return GLib.SOURCE_CONTINUE
        self.refreshing = True

        def read():
            queries = {
                "wifi": ["nmcli", "radio", "wifi"],
                "dnd": ["swaync-client", "--skip-wait", "-D"],
                "notifications": ["swaync-client", "--skip-wait", "-c"],
                "volume": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                "microphone": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                "profile": ["powerprofilesctl", "get"],
                "profiles": ["powerprofilesctl", "list"],
            }
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                tasks = {key: executor.submit(probe, value) for key, value in queries.items()}
                tasks["bluetooth"] = executor.submit(bluetooth_state)
                tasks["power_runtime"] = executor.submit(power_runtime_state)
                tasks["brightness"] = executor.submit(brightness.read_state)
                return {key: value.result() for key, value in tasks.items()}
        self.work(read, self.apply_control, self.control_error)
        return GLib.SOURCE_CONTINUE

    def control_error(self, error):
        self.refreshing = False
        self.feedback(error, True)

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

    def apply_control(self, state):
        self.refreshing = False
        self.state = state
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
                self.scale_values[key].set_text(tr_legacy("Unavailable · 不可用"))
        self.apply_brightness(state.get("brightness") or {})
        profile = state["profile"]
        available_profiles = re.findall(r"^\s*\*?\s*(power-saver|balanced|performance):", state["profiles"] or "", re.MULTILINE)
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
        from ai_backend import DEFAULTS, load_settings
        self.messages = []
        self.last_reply = ""
        self.ai_busy = False
        self.ai_saving = False
        self.model_generation = 0
        settings_error = None
        try:
            self.settings = load_settings()
        except (OSError, ValueError) as error:
            self.settings = dict(DEFAULTS)
            settings_error = str(error)
        toolbar = pack(self.content, box(False, 8))
        pack(toolbar, button("⌘  Codex", lambda: self.desktop("codex")), True)
        pack(toolbar, button("◌  ChatGPT", lambda: self.desktop("chatgpt")), True)
        pack(toolbar, button("⚙", self.toggle_settings, tooltip=tr_legacy("Connection settings · 连接设置")))
        self.settings_box = box(spacing=8, css="card")
        self.settings_container = pack(self.content, scroller(self.settings_box))
        settings_height = min(340, max(120, self.available_height - 410))
        self.settings_container.set_min_content_height(settings_height)
        self.settings_container.set_max_content_height(settings_height)
        self.settings_container.set_propagate_natural_height(True)
        self.settings_container.set_no_show_all(True)
        pack(self.settings_box, label(tr_legacy("CONNECTION  /  连接设置"), "section-title"))
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
        pack(self.settings_box, label(tr_legacy("Enter an environment variable name, never the secret itself.\n填写密钥的环境变量名，请勿填写密钥本身。"), "hint", wrap=True))
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
        pack(self.welcome, label(tr_legacy("Messages live in this panel only. Closing clears the conversation. Requests go to your configured provider.\n对话仅保留在当前面板中，关闭即清空；消息将发送至所配置的服务。"), "hint", wrap=True))
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
        self.clear_button = pack(composer_actions, button(tr_legacy("Clear · 清空"), self.clear_chat))
        self.copy_button = pack(composer_actions, button(tr_legacy("Copy · 复制"), self.copy_reply))
        self.copy_button.set_sensitive(False)
        self.send_button = pack(composer_actions, button(tr_legacy("Send  ↗  发送"), self.send_chat, "accent-button"), True)
        pack(composer, label(tr_legacy("Enter to send · 回车发送   /   Shift+Enter for newline · 换行"), "hint"))
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
        settings = dict(self.settings)
        settings.update({key: entry.get_text().strip() for key, entry in self.setting_entries.items()})
        settings["provider"] = self.provider.get_active_id() or "ollama"
        return settings

    def settings_edited(self, *_):
        self.model_generation += 1

    def save_ai_settings(self):
        if self.ai_busy or self.ai_saving:
            self.feedback(tr_legacy("Wait for the current request before changing connection.\n请等待当前请求完成后再更改连接。"), True)
            return
        from ai_backend import save_settings, validate_settings
        try:
            settings = validate_settings(self.draft_settings())
        except ValueError as error:
            self.feedback(str(error), True)
            return
        self.ai_saving = True
        self.model_generation += 1
        self.settings_box.set_sensitive(False)
        self.send_button.set_sensitive(False)
        changed = settings != self.settings

        def reset():
            self.ai_saving = False
            self.settings_box.set_sensitive(True)
            self.send_button.set_sensitive(True)

        def saved(_):
            reset()
            if changed:
                self.clear_chat()
            self.settings = settings
            self.settings_container.hide()
            self.update_provider_status()
            self.feedback(tr_legacy("Connection saved; conversation cleared · 已保存连接并清空对话") if changed else tr_legacy("Connection saved · 连接设置已保存"))

        def failed(error):
            reset()
            self.feedback(error, True)
        self.work(lambda: save_settings(settings), saved, failed, commit=True)

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
        from ai_backend import chat
        self.ai_busy = True
        self.model_generation += 1
        self.settings_box.set_sensitive(False)
        self.send_button.set_sensitive(False)
        self.clear_button.set_sensitive(False)
        self.send_button.set_label(tr_legacy("Thinking… · 思考中…"))
        self.messages.append({"role": "user", "content": text})
        self.add_message("user", text)
        buffer.set_text("")
        self.feedback(tr_legacy("Waiting for your model… · 正在等待模型回复…"))
        pending = self.add_message("assistant", "•••")
        snapshot = [dict(message) for message in self.messages]
        settings = dict(self.settings)

        def reset():
            self.ai_busy = False
            self.settings_box.set_sensitive(True)
            self.send_button.set_sensitive(True)
            self.clear_button.set_sensitive(True)
            self.send_button.set_label(tr_legacy("Send  ↗  发送"))

        def replied(response):
            reset()
            response = str(response)
            pending.set_text(response)
            self.messages.append({"role": "assistant", "content": response})
            self.last_reply = response
            self.copy_button.set_sensitive(True)
            self.feedback("")

        def failed(error):
            reset()
            pending.set_text(tr_legacy("Could not reach the model · 无法获取模型回复"))
            self.messages.pop()
            if not buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
                buffer.set_text(text)
            self.feedback(error, True)
        self.work(lambda: chat(snapshot, settings), replied, failed)

    def clear_chat(self):
        if self.ai_busy:
            return
        self.messages.clear()
        self.last_reply = ""
        self.welcome = None
        for child in self.chat_body.get_children():
            child.destroy()
        self.copy_button.set_sensitive(False)
        self.feedback(tr_legacy("Conversation cleared · 对话已清空"))

    def copy_reply(self):
        if self.last_reply:
            # wl-copy retains clipboard ownership after the sidebar closes.
            response = self.last_reply
            self.work(lambda: subprocess.run(["wl-copy"], input=response, capture_output=True,
                                              text=True, check=True, timeout=5),
                      lambda _: self.feedback(tr_legacy("Copied · 已复制")), commit=True)


class Shell(Gtk.Application):
    def __init__(self, mode):
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
        for index, provider in enumerate(providers):
            Gtk.StyleContext.add_provider_for_screen(screen, provider,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_command_line(self, command_line):
        args = command_line.get_arguments()
        requested = args[1] if len(args) > 1 else self.mode
        if requested not in CONTROL_MODES | {"shortcuts", "ai"}:
            return 2
        if self.window and requested in PAGE_KEYS:
            if self.window.control_stack.get_visible_child_name() == requested:
                self.window.request_close()
            else:
                self.window.select_control_tab(requested)
                if not self.window.is_active():
                    self.window.hide()
                    self.window.show_all()
                self.window.present()
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
        if self.window:
            self.window.request_close()
            return
        self.reload_theme()
        self.window = Panel(self, self.mode)
        self.window.show_all()
        self.window.present()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CONTROL_MODES | {"shortcuts", "ai"}:
        print("Usage: panel.py {control|system|appearance|sound|displays|shortcuts|ai}", file=sys.stderr)
        return 2
    return Shell(sys.argv[1]).run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
