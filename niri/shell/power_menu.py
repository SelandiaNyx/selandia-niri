#!/usr/bin/env python3
"""Native power submenu: the session's power actions without any text input.

The control center, the Ctrl+Alt+Delete binding and the "Power & locking" page
all open this one window. It replaces the previous fuzzel dmenu, whose search
field made no sense for five fixed entries and let an invisible filter pick a
destructive action: typing "r" silently narrowed the list to "Restart" and the
next Enter rebooted the machine. Here every entry is a button, and the actions
that end the session or the machine ask for confirmation in the same window.

The window only reports the chosen action on stdout; ``niri/scripts/desktop
power`` performs it, so locking and suspending still run through
``power_actions.py`` and share one entry point with the automatic timer.
"""
from __future__ import annotations

from pathlib import Path
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, Gtk, GtkLayerShell, Pango

import sleep_guard
from control_widgets import icon, pack, prepare_icon_theme, style
from i18n import tr

BASE = Path(__file__).resolve().parent.parent
MENU_WIDTH = 324

# identifier, symbolic icon, english label, chinese label, confirmation question.
# The question is None for actions that destroy nothing.
ACTIONS = (
    ("lock", "system-lock-screen-symbolic", "Lock", "锁屏", None),
    ("sleep", "system-suspend-symbolic", "Suspend", "睡眠", None),
    ("logout", "system-log-out-symbolic", "Log out of Niri", "注销 Niri",
     ("Log out of Niri?", "注销 Niri？")),
    ("restart", "system-reboot-symbolic", "Restart", "重启", ("Restart computer?", "重启电脑？")),
    ("shutdown", "system-shutdown-symbolic", "Shut down", "关机",
     ("Shut down computer?", "关闭电脑？")),
)
ACTION_IDS = tuple(action[0] for action in ACTIONS)
_QUESTIONS = {action[0]: action[4] for action in ACTIONS}
# Tooltips clarify the consequence without adding rows or changing any action.
_HINTS = {
    "lock": ("Lock the current session", "锁定当前会话"),
    "sleep": ("Suspend the computer", "让电脑进入睡眠"),
    "logout": ("End this Niri session", "结束当前 Niri 会话"),
    "restart": ("Reboot the computer", "重新启动电脑"),
    "shutdown": ("Power off the computer", "关闭电脑"),
}


def confirm_question(identifier):
    """The question this action must ask first, or None when it is immediate."""
    return _QUESTIONS.get(identifier)


def needs_confirmation(identifier):
    return confirm_question(identifier) is not None


def sleep_blocked(status=None):
    """True only for a confirmed Stay-awake inhibitor, never for a read error.

    A degraded sleep-protection service must not relabel Suspend; the suspend
    request itself still validates the real inhibitor state before locking.
    """
    read = sleep_guard.status if status is None else status
    try:
        return bool(read().get("awake"))
    except Exception:
        return False


def load_theme():
    """Apply the same native styles the control center uses, scoped by window class."""
    screen = Gdk.Screen.get_default()
    for path in (
        BASE / "shell/style.css",
        BASE / "theme/panel.css",
        BASE / "shell/control_center.css",
    ):
        if not path.exists():
            continue
        provider = Gtk.CssProvider()
        provider.load_from_path(str(path))
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class PowerMenu(Gtk.ApplicationWindow):
    """One layer-shell surface; it never contains an entry or a text input."""

    def __init__(self, app, *, blocked=None):
        super().__init__(application=app, title="Selandia · Power")
        from appearance import load_settings
        preferences = load_settings()
        reduced_motion = bool(preferences.get("reduced_motion", False))
        self.get_settings().set_property(
            "gtk-application-prefer-dark-theme",
            preferences.get("color_mode", "dark") == "dark",
        )
        self.result = None
        self.pending = None
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_app_paintable(True)
        self.set_default_size(MENU_WIDTH, -1)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        context = self.get_style_context()
        context.add_class("glass-window")
        context.add_class("power-menu-window")
        if reduced_motion:
            context.add_class("reduce-motion")
        surface = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "glass-surface")
        self.add(surface)
        header = pack(surface, style(Gtk.Box(spacing=10), "panel-header"))
        header_badge = style(Gtk.Box(), "power-header-icon")
        header_badge.set_valign(Gtk.Align.CENTER)
        pack(header_badge, icon("system-shutdown-symbolic", 16))
        pack(header, header_badge)
        pack(header, style(Gtk.Label(label=tr("Power", "电源"), xalign=0), "control-heading"), True)
        close = style(Gtk.Button(label="×"), "close-button")
        close.set_valign(Gtk.Align.CENTER)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text(tr("Close · Esc", "关闭 · Esc"))
        close.connect("clicked", lambda _: self.cancel())
        pack(header, close)
        content = pack(surface, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10),
                                      "panel-content"))
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(
            Gtk.StackTransitionType.NONE if reduced_motion else Gtk.StackTransitionType.CROSSFADE
        )
        self.stack.set_transition_duration(0 if reduced_motion else 140)
        # Keep the menu width stable, but let the window shrink to the shorter
        # confirmation instead of holding the action list's empty space.
        self.stack.set_vhomogeneous(False)
        pack(content, self.stack)
        self.action_buttons = {}
        actions = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "power-actions")
        blocked_sleep = sleep_blocked() if blocked is None else bool(blocked)
        for index, (identifier, glyph, english, chinese, question) in enumerate(ACTIONS, start=1):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            style(row, "power-action-row")
            widget = Gtk.Button()
            style(widget, "power-action")
            if question:
                style(widget, "danger")
            inner = Gtk.Box(spacing=12)
            badge = style(Gtk.Box(), "power-icon")
            badge.set_valign(Gtk.Align.CENTER)
            pack(badge, icon(glyph, 16))
            pack(inner, badge)
            pack(inner, Gtk.Label(label=tr(english, chinese), xalign=0), True)
            key_hint = style(Gtk.Label(label=str(index)), "hint")
            key_hint.set_valign(Gtk.Align.CENTER)
            pack(inner, key_hint)
            widget.add(inner)
            widget.get_accessible().set_name(tr(english, chinese))
            widget.set_tooltip_text(tr(*_HINTS[identifier]) + f" ({index})")
            widget.connect("clicked", lambda _widget, key=identifier: self.choose(key))
            pack(row, widget, True)
            if identifier == "sleep" and blocked_sleep:
                pack(row, style(Gtk.Label(label=tr("Stay awake blocks sleep", "保持唤醒已阻止睡眠"),
                                          xalign=0), "power-note"))
            self.action_buttons[identifier] = widget
            pack(actions, row)
        self.confirm_label = style(Gtk.Label(xalign=0), "power-question")
        self.confirm_label.set_line_wrap(True)
        self.confirm_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        confirm = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "power-confirm")
        pack(confirm, self.confirm_label)
        answers = pack(confirm, Gtk.Box(spacing=8))
        self.cancel_button = pack(answers, self.answer(tr("Cancel", "取消"), self.back), True)
        style(self.cancel_button, "text-button")
        self.confirm_button = pack(answers, self.answer(tr("Confirm", "确认"), self.confirm), True)
        style(self.confirm_button, "accent-button")
        self.stack.add_named(actions, "actions")
        self.stack.add_named(confirm, "confirm")
        self.stack.set_visible_child_name("actions")
        self.connect("key-press-event", self.on_key)
        self.connect("map", self.on_map)
        if GtkLayerShell.is_supported():
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "selandia-power-menu")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            # This short action menu is modal. With ON_DEMAND, Niri's
            # focus-follows-mouse can focus a window while the pointer travels
            # toward the menu; dismissing on that focus loss made it unclickable.
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
            GtkLayerShell.set_exclusive_zone(self, -1)
        else:
            self.set_position(Gtk.WindowPosition.CENTER)

    @staticmethod
    def answer(title, callback):
        widget = Gtk.Button(label=title)
        widget.connect("clicked", lambda _: callback())
        return widget

    def on_map(self, *_):
        self.action_buttons["lock"].grab_focus()

    def _move_action_focus(self, delta: int):
        focused = self.get_focus()
        ordered = [self.action_buttons[key] for key in ACTION_IDS]
        idx = ordered.index(focused) if focused in ordered else -1
        ordered[(idx + delta) % len(ordered)].grab_focus()

    def on_key(self, _widget, event):
        kv = event.keyval
        mods = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK)
        if self.stack.get_visible_child_name() == "confirm":
            if kv in (Gdk.KEY_Escape, Gdk.KEY_BackSpace):
                self.back()
                return True
            if kv in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down,
                      Gdk.KEY_KP_Left, Gdk.KEY_KP_Right, Gdk.KEY_KP_Up, Gdk.KEY_KP_Down):
                target = self.confirm_button if self.get_focus() is self.cancel_button else self.cancel_button
                target.grab_focus()
                return True
            return False
        if kv == Gdk.KEY_Escape:
            self.cancel()
            return True
        if kv in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self._move_action_focus(1)
            return True
        if kv in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self._move_action_focus(-1)
            return True
        if kv in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self.action_buttons[ACTION_IDS[0]].grab_focus()
            return True
        if kv in (Gdk.KEY_End, Gdk.KEY_KP_End):
            self.action_buttons[ACTION_IDS[-1]].grab_focus()
            return True
        if not mods:
            if Gdk.KEY_1 <= kv <= Gdk.KEY_5:
                self.choose(ACTION_IDS[kv - Gdk.KEY_1])
                return True
            if Gdk.KEY_KP_1 <= kv <= Gdk.KEY_KP_5:
                self.choose(ACTION_IDS[kv - Gdk.KEY_KP_1])
                return True
        return False

    def choose(self, identifier):
        question = confirm_question(identifier)
        if question is None:
            self.finish(identifier)
            return
        self.pending = identifier
        self.confirm_label.set_text(tr(*question))
        self.stack.set_visible_child_name("confirm")
        # Keep the non-destructive action focused by default so an accidental
        # Enter never triggers logout, reboot or shutdown.
        self.cancel_button.grab_focus()

    def back(self):
        restore = self.pending
        self.pending = None
        self.stack.set_visible_child_name("actions")
        if restore in self.action_buttons:
            self.action_buttons[restore].grab_focus()

    def confirm(self):
        if self.pending:
            self.finish(self.pending)

    def cancel(self):
        # Nothing was chosen; the caller treats a missing action as cancelled.
        if self.result is None:
            self.pending = None
            self.get_application().quit()

    def finish(self, identifier):
        if identifier not in ACTION_IDS:
            raise ValueError("Unknown power action · 未知电源操作")
        self.result = identifier
        self.pending = None
        self.get_application().result = identifier
        self.get_application().quit()


class PowerMenuApplication(Gtk.Application):
    def __init__(self):
        # Non-unique: a second menu may open while one is already waiting, and a
        # stuck instance must never swallow the next Ctrl+Alt+Delete.
        super().__init__(application_id="org.selandia.PowerMenu",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.window = None
        self.result = None

    def do_activate(self):
        if self.window is not None:
            return
        prepare_icon_theme()
        load_theme()
        self.window = PowerMenu(self)
        self.window.show_all()
        self.window.present()


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print("Usage: power_menu.py", file=sys.stderr)
        return 2
    if not Gtk.init_check()[0]:
        print(tr("A running Wayland session is required for the power menu.",
                 "电源菜单需要正在运行的 Wayland 会话。"), file=sys.stderr)
        return 1
    application = PowerMenuApplication()
    application.run([])
    if application.result:
        print(application.result)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
