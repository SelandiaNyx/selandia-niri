#!/usr/bin/env python3
"""Measure the real status-bar width inside a nested Niri session.

The A3 acceptance is about pixels on an output, not about a threshold constant:
this probe takes a screenshot with and without the bar, diffs them to find the
bar's bounding box, and compares that width with the output's logical width. It
also reports what the layout model predicted, so the model can be calibrated
against reality.

Run inside a private Niri session (tools/smoke.py does the session setup):

    python3 -B tools/bar_measure.py --pid <nested-niri-pid> --width 1100
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))
import bar_fit
import bar_layout

ARTIFACTS = ROOT / ".validation"
BAR_MARGIN = 18


def niri(*arguments, socket=None, timeout=10):
    """Talk to the nested session, or to the host when a socket is given.

    The host session is only ever used to resize this probe's own compositor
    window; every screenshot and layout decision stays inside the private one.
    """
    environment = dict(os.environ)
    if socket:
        environment["NIRI_SOCKET"] = socket
    return subprocess.run(["niri", "msg", *arguments], capture_output=True, text=True,
                          timeout=timeout, env=environment)


def outputs():
    result = niri("--json", "outputs")
    if result.returncode:
        raise RuntimeError("niri msg outputs failed: " + result.stderr.strip())
    return json.loads(result.stdout)


def connected_output():
    for name, output in outputs().items():
        logical = output.get("logical") or {}
        if logical.get("width"):
            return name, int(logical["width"]), float(logical.get("scale") or 1)
    raise RuntimeError("no connected output in this session")


def resize_host_window(pid, width, host_socket, height=1000):
    """Resize the nested compositor's window in the host session, if reachable."""
    if not pid or not host_socket:
        return False
    for _ in range(40):
        result = niri("--json", "windows", socket=host_socket)
        if result.returncode:
            return False
        try:
            windows = json.loads(result.stdout)
        except ValueError:
            return False
        window = next((item for item in windows if item.get("pid") == pid), None)
        if window:
            identifier = str(window["id"])
            if not window.get("is_floating"):
                niri("action", "toggle-window-floating", "--id", identifier, socket=host_socket)
            niri("action", "set-window-width", "--id", identifier, str(width), socket=host_socket)
            niri("action", "set-window-height", "--id", identifier, str(height), socket=host_socket)
            return True
        time.sleep(.1)
    return False


def screenshot(path):
    path = Path(path)
    previous = path.stat().st_mtime_ns if path.exists() else None
    niri("action", "screenshot-screen", "--path", str(path), "--show-pointer", "false")
    for _ in range(60):
        if path.exists() and path.stat().st_mtime_ns != previous and path.stat().st_size:
            return path
        time.sleep(.1)
    raise RuntimeError(f"screenshot was not written: {path}")


def diff_box(before, after, tolerance=6):
    """Bounding box of the pixels that differ between two screenshots."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    first = GdkPixbuf.Pixbuf.new_from_file(str(before))
    second = GdkPixbuf.Pixbuf.new_from_file(str(after))
    if (first.get_width(), first.get_height()) != (second.get_width(), second.get_height()):
        raise RuntimeError("screenshots have different sizes")
    width, height = first.get_width(), first.get_height()
    left, right, top, bottom = width, -1, height, -1
    for row in range(height):
        row_a = first.get_pixels()[row * first.get_rowstride():(row + 1) * first.get_rowstride()]
        row_b = second.get_pixels()[row * second.get_rowstride():(row + 1) * second.get_rowstride()]
        if row_a == row_b:
            continue
        channels = first.get_n_channels()
        for column in range(width):
            offset = column * channels
            if max(abs(row_a[offset + index] - row_b[offset + index]) for index in range(channels)) > tolerance:
                left = min(left, column)
                right = max(right, column)
                top = min(top, row)
                bottom = max(bottom, row)
    if right < 0:
        return None
    return {"x": left, "y": top, "width": right - left + 1, "height": bottom - top + 1}


def wait_for_layer(present, timeout=15):
    """Wait until the bar's layer surface is present (or gone).

    Repeated measurements in one session need this: a stale layer from the
    previous run makes the next one take its "before" screenshot with a bar
    already on screen, which silently measures nothing.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        layers = niri("layers")
        if layers.returncode == 0 and ("waybar" in layers.stdout) == present:
            return True
        time.sleep(.1)
    return False


def start_bar(environment):
    if not wait_for_layer(False, timeout=5):
        raise RuntimeError("a waybar layer was already running in this session; "
                           "measure in a private session without a bar")
    log = (ARTIFACTS / "bar-measure-waybar.log").open("w")
    process = subprocess.Popen([str(ROOT / "niri/scripts/components"), "waybar"], env=environment,
                               stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("waybar exited; see .validation/bar-measure-waybar.log")
        if wait_for_layer(True, timeout=1):
            return process, log
    raise RuntimeError("waybar layer did not appear")


def main():
    parser = argparse.ArgumentParser(description="Measure the real status-bar width")
    parser.add_argument("--pid", type=int, default=None, help="nested compositor pid for the host-side resize")
    parser.add_argument("--width", type=int, default=None, help="requested logical width of the nested output")
    parser.add_argument("--font-size", type=float, default=None)
    parser.add_argument("--host-socket", default=None,
                        help="host NIRI_SOCKET, used only to resize this probe's own window")
    parser.add_argument("--summary", action="store_true", help="print one machine-readable line")
    parser.add_argument("--layout", choices=bar_layout.LAYOUTS, default=None,
                        help="force a layout instead of selecting one, to measure its real requirement")
    arguments = parser.parse_args()

    ARTIFACTS.mkdir(exist_ok=True)
    resized = resize_host_window(arguments.pid, arguments.width, arguments.host_socket) if arguments.width else False
    if arguments.width:
        time.sleep(1.0)
    name, logical_width, scale = connected_output()
    if arguments.layout:
        from ui_assets import write
        write(layout=arguments.layout)
        layout = arguments.layout
    else:
        layout = bar_layout.apply(width=logical_width, size=arguments.font_size)

    before = screenshot(ARTIFACTS / "bar-measure-before.png")
    process, log = start_bar(dict(os.environ))
    time.sleep(1.5)
    after = screenshot(ARTIFACTS / "bar-measure-after.png")
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    log.close()
    wait_for_layer(False, timeout=5)

    box = diff_box(before, after)
    report = {
        "output": name,
        "scale": scale,
        "logical_width": logical_width,
        "resized": resized,
        "layout": layout,
        "bar_box": box,
        "measured_bar_width": round(box["width"] / scale) if box else None,
        "model_required": {name: bar_fit.required(name, arguments.font_size or 16.0)
                           for name in bar_fit.LAYOUTS},
    }
    if box:
        # The bar keeps a fixed 18px margin on both sides. Content that overflows
        # the output loses the margin on that side, so the margins are the pixel
        # evidence that the right-hand modules are complete and clickable.
        report["left_margin_logical"] = round(box["x"] / scale)
        report["right_margin_logical"] = round((logical_width - (box["x"] + box["width"]) / scale))
        report["right_edge_logical"] = round((box["x"] + box["width"]) / scale)
        report["keeps_margins"] = (report["left_margin_logical"] >= BAR_MARGIN - 2
                                   and report["right_margin_logical"] >= BAR_MARGIN - 2)
        report["fits"] = report["keeps_margins"]
    if arguments.summary:
        print("bar-measure " + " ".join(f"{key}={report.get(key)}" for key in
                                        ("logical_width", "scale", "layout", "measured_bar_width",
                                         "left_margin_logical", "right_margin_logical", "keeps_margins")), flush=True)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    (ARTIFACTS / "bar-measure.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not box:
        print("FAIL: no bar pixels were detected", file=sys.stderr)
        return 1
    if not report["fits"]:
        print("FAIL: the bar lost its margin, so the right-hand modules are clipped", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
