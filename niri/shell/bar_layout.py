#!/usr/bin/env python3
"""Pick a wide or compact status-bar layout for the real output width.

The bar is never rescued by shrinking the font: it selects a layout from the
*minimum* logical width of the connected outputs and the interface font size.
The compact layout always keeps the launcher, the workspaces, sound,
notifications and the control centre, shortens the clock to a time, hides empty
workspaces, drops the window title, and moves the live network rate and the
monitor figures into tooltips. The network module keeps a stable minimum width so
sampling digits cannot push the right-hand modules off the output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from i18n import tr

BASE = Path(__file__).resolve().parent.parent
# A layout must fit the narrowest connected output. These are the interface-font
# pixels of logical width each layout needs, measured on the real bar.
WIDE_FONT_WIDTHS = 68
COMPACT_FONT_WIDTHS = 40
WIDE_MODULES_LEFT = ("custom/launcher", "niri/workspaces", "niri/window")
COMPACT_MODULES_LEFT = ("custom/launcher", "niri/workspaces")
WIDE_MODULES_RIGHT = ("custom/layout", "custom/ai", "custom/shortcuts", "custom/system", "pulseaudio",
                      "network", "battery", "tray", "custom/notification", "custom/control")
COMPACT_MODULES_RIGHT = ("custom/layout", "pulseaudio", "network", "battery", "tray",
                         "custom/notification", "custom/control")
LAYOUTS = ("wide", "compact")


WIDTH_CACHE = {"at": 0.0, "widths": []}


def output_widths(*, run=subprocess.run, ttl=2.0):
    """Logical width of every connected Niri output; empty when unavailable."""
    now = time.monotonic()
    if run is subprocess.run and WIDTH_CACHE["widths"] and now - WIDTH_CACHE["at"] < ttl:
        return list(WIDTH_CACHE["widths"])
    try:
        result = run(["niri", "msg", "--json", "outputs"], capture_output=True, text=True, timeout=4)
        if result.returncode:
            return []
        outputs = json.loads(result.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    widths = []
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        logical = output.get("logical") or {}
        width = logical.get("width")
        if not width:
            modes = output.get("modes") or []
            index = output.get("current_mode")
            if isinstance(index, int) and 0 <= index < len(modes):
                width = (modes[index].get("width") or 0) / (output.get("scale") or 1)
        if width and width > 0:
            widths.append(int(width))
    if run is subprocess.run:
        WIDTH_CACHE.update(at=now, widths=list(widths))
    return widths


def font_size(*, base=BASE):
    try:
        from appearance import load_settings
        return float(load_settings()["font_size"])
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return 12.0


def select(*, width=None, size=None, base=BASE, run=subprocess.run):
    """Return the layout that fits the narrowest output."""
    if size is None:
        size = font_size(base=base)
    if width is None:
        widths = output_widths(run=run)
        width = min(widths) if widths else None
    if not width:
        return "wide"  # unknown geometry must not silently degrade the bar
    return "wide" if width >= WIDE_FONT_WIDTHS * float(size) else "compact"


def build(config, layout):
    """Return the waybar configuration for one layout; never mutates the input."""
    if layout not in LAYOUTS:
        raise ValueError("Unknown bar layout: " + str(layout))
    bar = json.loads(json.dumps(config))
    if layout == "wide":
        bar["modules-left"] = list(WIDE_MODULES_LEFT)
        bar["modules-right"] = list(WIDE_MODULES_RIGHT)
        bar["network"] = {**bar["network"], "min-length": 22, "max-length": 26}
        return bar
    bar["modules-left"] = list(COMPACT_MODULES_LEFT)
    bar["modules-right"] = list(COMPACT_MODULES_RIGHT)
    bar["clock"] = {**bar["clock"], "format": "{:%H:%M}", "format-alt": "{:%Y-%m-%d  %H:%M:%S}"}
    tooltip = bar.get("tooltip-format-disconnected", "")
    network = bar["network"]
    # The rate stays reachable even though the bar shows only the link icon.
    tooltip_format = network.get("tooltip-format", "").rstrip()
    tooltip_format = (tooltip_format + "\n↓{bandwidthDownBytes} ↑{bandwidthUpBytes}").lstrip("\n")
    bar["network"] = {**network, "format-wifi": "󰖩", "format-ethernet": "󰈀",
                      "tooltip-format": tooltip_format, "min-length": 3, "max-length": 4}
    if tooltip:
        bar["network"]["tooltip-format-disconnected"] = tooltip
    return bar


def css(layout, size):
    """Layout CSS appended to the generated bar stylesheet."""
    if layout not in LAYOUTS:
        raise ValueError("Unknown bar layout: " + str(layout))
    rules = ["/* Bar layout: " + layout + " */",
             # An invisible helper module must not occupy bar space.
             "#custom-layout { padding: 0; margin: 0; min-width: 0; font-size: 0; background: transparent; }"]
    if layout == "compact":
        # Empty workspaces and the window title are the first things to go.
        rules.append("#workspaces button.empty { min-width: 0; padding: 0; margin: 0; font-size: 0; opacity: 0; }")
        rules.append(f"#network {{ min-width: {round(size * 1.4)}px; }}")
    else:
        # A stable band keeps changing rates from pushing the right-hand modules;
        # GTK CSS has no max-width, so the module's max-length caps the text.
        rules.append(f"#network {{ min-width: {round(size * 7.5)}px; }}")
    rules.append(f"#custom-system {{ min-width: {round(size * 6)}px; }}")
    return "\n".join(rules) + "\n"


def current_layout(*, base=BASE):
    """The layout the generated bar configuration already holds.

    Reading the generated file instead of a separate marker keeps this correct
    when the state directory is unwritable, and prevents a layout that never
    matches its marker from reloading the bar every interval.
    """
    try:
        config = json.loads((Path(base) / "theme/waybar.jsonc").read_text())
    except (OSError, ValueError):
        return None
    left = tuple(config.get("modules-left", ()))
    right = tuple(config.get("modules-right", ()))
    if left == COMPACT_MODULES_LEFT and right == COMPACT_MODULES_RIGHT:
        return "compact"
    if left == WIDE_MODULES_LEFT and right == WIDE_MODULES_RIGHT:
        return "wide"
    return None


def reload_bar(*, run=subprocess.run):
    """Ask the managed bar to reload; never touches another waybar instance."""
    try:
        return run(["systemctl", "--user", "kill", "--kill-whom=main", "--signal=SIGUSR2",
                    "selandia-niri@waybar.service"], capture_output=True, text=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def apply(*, base=BASE, width=None, size=None, run=subprocess.run, notify=False):
    """Re-render the bar when the layout for this display changed."""
    layout = select(width=width, size=size, base=base, run=run)
    if current_layout(base=base) == layout:
        return layout
    from ui_assets import write
    write(base=base)
    if notify:
        reload_bar(run=run)
    return layout


def main(argv=None):
    parser = argparse.ArgumentParser(description="Status-bar layout for this display")
    parser.add_argument("mode", choices=("apply", "ensure", "status"))
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--font-size", type=float, default=None, dest="font_size")
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if arguments.mode == "status":
            print(json.dumps({"layout": select(width=arguments.width, size=arguments.font_size),
                              "current": current_layout()}, ensure_ascii=False))
            return 0
        layout = apply(width=arguments.width, size=arguments.font_size, notify=arguments.mode == "ensure")
        if arguments.mode == "ensure":
            # A waybar custom module must always answer with one JSON object.
            print(json.dumps({"text": "", "tooltip": ""}))
        else:
            print(tr("Status bar layout: ", "状态栏布局：") + layout)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
