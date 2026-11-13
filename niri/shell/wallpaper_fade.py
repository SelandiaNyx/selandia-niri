#!/usr/bin/env python3
"""Temporary input-transparent background overlay; the service owns its lifetime.

Draw the previous static wallpaper, then fade it away over the ready new swaybg.
No control-center timer or compositor restart is involved.
"""
import argparse
import math
from pathlib import Path
import signal
import time
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell
import cairo
from i18n import tr


def geometry(iw, ih, width, height, mode):
    if mode == 'stretch':
        return 0., 0., width / iw, height / ih
    factor = 1. if mode in ('center', 'tile') else (min if mode == 'fit' else max)(width / iw, height / ih)
    return (width - iw * factor) / 2, (height - ih * factor) / 2, factor, factor


def main(args):
    image = GdkPixbuf.Pixbuf.new_from_file(args.image)
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError(tr('Wayland display unavailable', 'Wayland 显示不可用'))
    windows, drawn = [], set()
    started = None
    def draw(area, context, index):
        alpha = 1. if started is None else max(0., 1 - (time.monotonic() - started) / args.duration)
        width, height = area.get_allocated_width(), area.get_allocated_height()
        context.push_group()
        context.set_source_rgb(16 / 255, 21 / 255, 34 / 255); context.paint()
        iw, ih = image.get_width(), image.get_height()
        if args.mode == 'tile':
            # swaybg tiles from the top-left, without scaling the source.
            for y in range(0, height, ih):
                for x in range(0, width, iw):
                    Gdk.cairo_set_source_pixbuf(context, image, x, y); context.paint()
        else:
            x, y, sx, sy = geometry(iw, ih, width, height, args.mode)
            context.save(); context.translate(x, y); context.scale(sx, sy)
            Gdk.cairo_set_source_pixbuf(context, image, 0, 0); context.paint(); context.restore()
        context.pop_group_to_source(); context.paint_with_alpha(alpha)
        drawn.add(index)
        if len(drawn) == len(windows):
            Path(args.ready).touch()
        return False
    for index in range(display.get_n_monitors()):
        window = Gtk.Window()
        window.set_app_paintable(True)
        provider = Gtk.CssProvider()
        provider.load_from_data(b"window { background: transparent; }")
        window.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        window.set_visual(window.get_screen().get_rgba_visual())
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, 'wallpaper-crossfade')
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.BOTTOM)
        GtkLayerShell.set_monitor(window, display.get_monitor(index))
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(window, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(window, edge, True)
        area = Gtk.DrawingArea()
        area.connect('draw', draw, index)
        window.add(area)
        window.connect('realize', lambda widget: widget.get_window().input_shape_combine_region(cairo.Region(), 0, 0))
        windows.append(window)
    for window in windows: window.show_all()
    # A private command marker begins fading only after the new renderer is ready.
    deadline = time.monotonic() + 15
    def tick():
        nonlocal started
        now = time.monotonic()
        if started is None and Path(args.begin).exists(): started = now
        if now > deadline or (started is not None and now - started >= args.duration):
            Gtk.main_quit(); return GLib.SOURCE_REMOVE
        for window in windows: window.queue_draw()
        return GLib.SOURCE_CONTINUE
    GLib.timeout_add(16, tick)
    for signum in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, lambda: (Gtk.main_quit(), False)[1])
    Gtk.main()
    for window in windows: window.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--mode', choices=('fill', 'cover', 'fit', 'stretch', 'center', 'tile'), required=True)
    parser.add_argument('--duration', type=float, required=True)
    parser.add_argument('--ready', required=True)
    parser.add_argument('--begin', required=True)
    args = parser.parse_args()
    if not math.isfinite(args.duration) or not .1 <= args.duration <= 10: parser.error('duration')
    main(args)
