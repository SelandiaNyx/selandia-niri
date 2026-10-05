#!/usr/bin/env python3
"""Check the real FontButton dialog on smoke.py's private display and bus."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

ROOT = Path(__file__).resolve().parents[1]


def pump_until(predicate, timeout=5):
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
    raise AssertionError("Timed out waiting for GTK font chooser")


def luminance(color):
    values = [getattr(color, channel) for channel in ("red", "green", "blue")]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
              for value in values]
    return sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear))


def contrast(one, two):
    low, high = sorted((luminance(one), luminance(two)))
    return (high + .05) / (low + .05)


def descendants(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from descendants(child)


def private_dialog_window(dialog):
    result = subprocess.run(["niri", "msg", "--json", "windows"], check=True,
                            capture_output=True, text=True, timeout=3)
    return next((window for window in json.loads(result.stdout)
                 if window.get("pid") == os.getpid() and window.get("title") == dialog.get_title()), None)


def verify_contrast(widget, state=Gtk.StateFlags.NORMAL):
    context = widget.get_style_context()
    foreground = context.get_color(state)
    background = context.get_background_color(state)
    assert background.alpha > .99, (widget.get_name(), "transparent dialog surface", background)
    ratio = contrast(foreground, background)
    assert ratio >= 4.5, (widget.get_name(), "insufficient text contrast", ratio)
    return ratio


def main():
    if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1":
        raise RuntimeError("Run this probe only through tools/smoke.py's isolated session")
    Gtk.init([])
    providers = []
    for path in (ROOT / "niri/shell/style.css", ROOT / "niri/theme/panel.css"):
        provider = Gtk.CssProvider()
        provider.load_from_path(str(path))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        providers.append(provider)
    parent = Gtk.Window(title="Font contrast probe · 字体对话框测试")
    parent.get_style_context().add_class("glass-window")
    chooser = Gtk.FontButton()
    chooser.set_title("Font picker · 字体选择")
    chooser.set_font("Noto Sans 12")
    parent.add(chooser)
    parent.show_all()
    chooser.clicked()
    dialog = None
    try:
        pump_until(lambda: any(isinstance(item, Gtk.FontChooserDialog) and item.get_visible()
                               for item in Gtk.Window.list_toplevels()))
        dialog = next(item for item in Gtk.Window.list_toplevels()
                      if isinstance(item, Gtk.FontChooserDialog) and item.get_visible())
        pump_until(lambda: dialog.get_mapped())
        context = dialog.get_style_context()
        print("Font chooser CSS:", dialog.get_css_name(), context.list_classes(),
              context.get_path().to_string(), flush=True)
        assert dialog.get_css_name() == "dialog", "Font chooser CSS node changed"
        verify_contrast(dialog)
        buttons = [dialog.get_widget_for_response(response)
                   for response in (Gtk.ResponseType.CANCEL, Gtk.ResponseType.OK)]
        for button in buttons:
            assert button is not None and button.get_visible(), "Missing font chooser action"
            assert any(isinstance(child, Gtk.Label) and child.get_text().strip()
                       for child in descendants(button)), "Font chooser action has no readable label"
            verify_contrast(button)
        tree = next(item for item in descendants(dialog) if isinstance(item, Gtk.TreeView))
        verify_contrast(tree)
        verify_contrast(tree, Gtk.StateFlags.SELECTED)
        entry = next(item for item in descendants(dialog) if isinstance(item, Gtk.Entry))
        verify_contrast(entry)
        # Exercise the actual selection response, not only a standalone dialog.
        dialog.set_font("Noto Sans CJK SC 14")
        if len(sys.argv) == 2:
            # GTK can report mapped before it paints and commits a Wayland
            # buffer. Keep dispatching frames before asking Niri for a capture.
            paint_after = time.monotonic() + .6
            pump_until(lambda: time.monotonic() >= paint_after)
            pump_until(lambda: private_dialog_window(dialog) is not None)
            window = private_dialog_window(dialog)
            assert window is not None, "Font dialog was not mapped in private Niri"
            # Focus can take a moment when the compositor is busy with the other
            # probes, so keep asking and re-pumping frames instead of asserting
            # after a single fixed delay (that made this probe flaky).
            def focus_dialog():
                current = private_dialog_window(dialog)
                if current is None:
                    return False
                if not current.get("is_focused"):
                    subprocess.run(["niri", "msg", "action", "focus-window", "--id", str(current["id"])],
                                   check=False, capture_output=True, timeout=3)
                    return False
                return True

            try:
                pump_until(focus_dialog, timeout=6)
            except AssertionError:
                raise AssertionError("Font dialog is not visible/focused for screenshot")
            paint_after = time.monotonic() + .3
            pump_until(lambda: time.monotonic() >= paint_after)
            path = Path(sys.argv[1]).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            old = path.stat().st_mtime_ns if path.exists() else None
            subprocess.run(["niri", "msg", "action", "screenshot-screen", "--path", str(path),
                            "--show-pointer", "false"], check=True, capture_output=True, timeout=5)
            pump_until(lambda: path.exists() and path.stat().st_mtime_ns != old)
        dialog.response(Gtk.ResponseType.OK)
        pump_until(lambda: not dialog.get_visible())
        assert chooser.get_font_family() is not None, "Selected font was not returned to FontButton"
        assert chooser.get_font_size() == 14 * 1024, chooser.get_font()
        print("PASS native font chooser: visible action labels, solid surfaces, text contrast >=4.5:1, selection roundtrip")
        return 0
    finally:
        if dialog is not None:
            dialog.destroy()
        parent.destroy()
        for provider in providers:
            Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), provider)


if __name__ == "__main__":
    raise SystemExit(main())
