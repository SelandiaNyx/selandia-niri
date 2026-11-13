#!/usr/bin/env python3
"""Capture the native power submenu on smoke.py's private Wayland/D-Bus session.

Usage: SELANDIA_PRIVATE_PROBE=1 python3 -B tools/power_menu_probe.py [.validation]

The submenu replaced a fuzzel dmenu, so this probe records what the old design
could not show as evidence: five fixed actions with no search field, the
"Stay awake blocks sleep" annotation, and the confirmation that has to be
accepted before a session-ending action is reported. Accepting a confirmation
only makes the window report an identifier, so nothing is locked, logged out,
rebooted or shut down here.
"""
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))
import power_menu
from i18n import tr


def pump_until(predicate, timeout=10):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for _ in range(100):
            if not context.pending():
                break
            context.iteration(False)
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Timed out waiting for the power submenu")


def settle(seconds=.7):
    deadline = time.monotonic() + seconds
    pump_until(lambda: time.monotonic() >= deadline)


def descendants(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        children = []
        widget.forall(children.append)
        for child in children:
            yield from descendants(child)


def labels(widget):
    if isinstance(widget, Gtk.Label):
        yield widget.get_text()
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from labels(child)


def screenshot(directory, name):
    path = Path(directory) / name
    previous = path.stat().st_mtime_ns if path.exists() else None
    subprocess.run(["niri", "msg", "action", "screenshot-screen", "--path", str(path),
                    "--show-pointer", "false"], check=True, capture_output=True, timeout=5)
    for _ in range(60):
        if path.exists() and path.stat().st_size and path.stat().st_mtime_ns != previous:
            return path
        time.sleep(.1)
    raise AssertionError(f"Screenshot was not written: {path}")


def open_menu(app, *, blocked):
    menu = power_menu.PowerMenu(app, blocked=blocked)
    app.window = menu
    menu.show_all()
    menu.present()
    pump_until(lambda: menu.get_mapped())
    settle()
    return menu


def main():
    if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1":
        raise RuntimeError("Run this probe only through tools/smoke.py's isolated session")
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".validation"
    Gtk.init([])
    power_menu.load_theme()
    app = power_menu.PowerMenuApplication()
    if not app.register(None):
        raise RuntimeError("Cannot register the isolated power menu application")
    pointer = os.environ.get("SELANDIA_POINTER_PROBE")
    background = None
    if pointer:
        background = Gtk.Window(title="Pointer focus regression probe")
        background.set_default_size(900, 600)
        background.add(Gtk.Button(label="Foreground application"))
        background.maximize()
        background.show_all()
        background.present()
        settle()
        pump_until(background.is_active)
        geometry = Gdk.Display.get_default().get_monitor(0).get_geometry()

        def move(x, y, click=False):
            subprocess.run([pointer, str(int(x)), str(int(y)), str(geometry.width), str(geometry.height),
                            *(["click"] if click else [])], check=True, timeout=5)
            settle(.25)

        move(40, geometry.height / 2, True)
    menu = open_menu(app, blocked=False)
    if pointer:
        assert GtkLayerShell.get_keyboard_mode(menu) == GtkLayerShell.KeyboardMode.EXCLUSIVE
        with patch.object(app, "quit") as quit:
            # Cross the foreground application first, as in the user's report,
            # then reach the real button using Wayland pointer events.
            move(45, geometry.height / 2)
            move(80, geometry.height / 2 + 40)
            quit.assert_not_called()
            target = menu.action_buttons["restart"]
            x, y = target.translate_coordinates(menu, 0, 0)
            x += (geometry.width - menu.get_allocated_width()) / 2 + target.get_allocated_width() / 2
            y += (geometry.height - menu.get_allocated_height()) / 2 + target.get_allocated_height() / 2
            # Layer-shell centres inside the usable output area, which can be
            # shifted by Waybar's exclusive zone. Wayland does not expose the
            # window's global position to GTK. Find the actual hover target
            # before clicking; never guess which power action is underneath.
            for offset in (0, 12, -12, 24, -24, 36, -36, 48, -48, 60, -60, 80, -80):
                move(x, y + offset)
                if target.get_state_flags() & Gtk.StateFlags.PRELIGHT:
                    move(x, y + offset, True)
                    break
            else:
                raise AssertionError("Pointer did not reach the Restart button")
            pump_until(lambda: menu.stack.get_visible_child_name() == "confirm")
            quit.assert_not_called()
            assert menu.result is None
            menu.back()
        print("PASS real pointer: crossing foreground window keeps menu open; clicking Restart opens confirmation only")
    self_entries = [item for item in descendants(menu) if isinstance(item, Gtk.Entry)]
    assert not self_entries, "the power submenu must not contain a search or text field"
    # Labels follow the user's interface language, so compare against this
    # project's own catalogue rather than hard-coding either language.
    shown = list(labels(menu))
    for _identifier, _glyph, english, chinese, _question in power_menu.ACTIONS:
        title = tr(english, chinese)
        assert title in shown, f"missing action: {title}"
    screenshot(directory, "power-menu.png")
    menu.action_buttons["restart"].clicked()
    pump_until(lambda: menu.stack.get_visible_child_name() == "confirm")
    assert menu.result is None, "a restart was reported before its confirmation"
    assert menu.confirm_label.get_text() == tr(*power_menu.confirm_question("restart")), \
        "the confirmation does not name the action"
    settle()
    screenshot(directory, "power-menu-confirm.png")
    menu.cancel_button.clicked()
    pump_until(lambda: menu.stack.get_visible_child_name() == "actions")
    assert menu.result is None, "cancelling the confirmation still reported an action"
    menu.destroy()
    blocked = open_menu(app, blocked=True)
    note = tr("Stay awake blocks sleep", "保持唤醒已阻止睡眠")
    assert note in list(labels(blocked)), "the inhibitor note is missing"
    screenshot(directory, "power-menu-stay-awake.png")
    blocked.destroy()
    if background:
        background.destroy()
    print("PASS native power submenu: five fixed actions, no search or text field, "
          "confirmation before restart, Stay-awake annotation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
