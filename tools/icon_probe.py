#!/usr/bin/env python3
"""Render the panel's symbolic icons and report their alpha coverage.

Usage: python3 -B tools/icon_probe.py [output.png]

The report is the visual acceptance evidence for audit A4: it prints the resolved
file and the transparent/opaque pixel counts for every bundled icon at 100%,
150% and 200%, and writes a side-by-side PNG (before = the user's theme, after =
the panel's verified icon) so a solid square can be seen rather than assumed.
"""
import json
import os
from pathlib import Path
import sys
import tempfile

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gtk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))
import control_widgets


def statistics(pixbuf):
    data = pixbuf.get_pixels()
    channels = pixbuf.get_n_channels()
    stride = pixbuf.get_rowstride()
    counts = {"transparent": 0, "partial": 0, "opaque": 0}
    for row in range(pixbuf.get_height()):
        base = row * stride
        for column in range(pixbuf.get_width()):
            alpha = data[base + column * channels + channels - 1]
            counts["transparent" if alpha == 0 else "opaque" if alpha == 255 else "partial"] += 1
    counts["width"] = pixbuf.get_width()
    counts["height"] = pixbuf.get_height()
    counts["solid"] = counts["transparent"] == 0
    return counts


def load(theme, name, size, scale):
    info = theme.lookup_icon_for_scale(name, size, scale, Gtk.IconLookupFlags.FORCE_SYMBOLIC)
    if info is None:
        return None, None
    colour = Gdk.RGBA()
    colour.parse("#2e3436")
    loaded = info.load_symbolic(colour, colour, colour, colour)
    pixbuf = loaded[0] if isinstance(loaded, tuple) else loaded
    return pixbuf, info.get_filename()


def strip(images, size=48, gap=8):
    width = sum(image.get_width() for image in images) + gap * (len(images) + 1)
    height = max(image.get_height() for image in images) + gap * 2
    canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    canvas.fill(0xf0f0f0ff)
    offset = gap
    for image in images:
        image.composite(canvas, offset, gap, image.get_width(), image.get_height(), offset, gap, 1, 1,
                        GdkPixbuf.InterpType.BILINEAR, 255)
        offset += image.get_width() + gap
    return canvas


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".validation/fix-keyboard-icon.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    system_theme = Gtk.IconTheme.get_default()
    report = {"system_theme": Gtk.Settings.get_default().get_property("gtk-icon-theme-name"), "icons": {}}
    before, after = [], []
    with tempfile.TemporaryDirectory(prefix="selandia-icon-probe-") as runtime:
        for source in sorted(control_widgets.ICON_ASSETS.glob("*-symbolic.svg")):
            name = source.stem
            entry = {}
            for label, scale in (("100%", 1), ("150%", 2), ("200%", 3)):
                original, original_path = load(system_theme, name, 18, scale)
                entry[label] = {"before": statistics(original) if original else None, "before_file": original_path}
                if original is not None:
                    before.append(original.scale_simple(original.get_width() * 2, original.get_height() * 2,
                                                        GdkPixbuf.InterpType.BILINEAR))
            control_widgets.PREPARED.update(base=None, directory=None)
            directory = control_widgets.build_extension(
                control_widgets.active_theme_name(), runtime)
            theme = Gtk.IconTheme.new()
            theme.set_screen(Gdk.Screen.get_default())
            theme.set_search_path([str(directory), *system_theme.get_search_path()])
            theme.set_custom_theme(control_widgets.EXTENSION_NAME)
            for label, scale in (("100%", 1), ("150%", 2), ("200%", 3)):
                pixbuf, path = load(theme, name, 18, scale)
                entry[label]["after"] = statistics(pixbuf) if pixbuf else None
                entry[label]["after_file"] = path
                if pixbuf is not None:
                    after.append(pixbuf.scale_simple(pixbuf.get_width() * 2, pixbuf.get_height() * 2,
                                                     GdkPixbuf.InterpType.BILINEAR))
            report["icons"][name] = entry
    if before or after:
        strip(before + [GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 8, 8)] + after).savev(
            str(output), "png", [], [])
    (output.with_suffix(".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("wrote", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
