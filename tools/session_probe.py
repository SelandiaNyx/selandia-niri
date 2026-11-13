#!/usr/bin/env python3
"""Geometry, screenshot and ownership helpers for private Niri probes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))
import session_identity

ARTIFACTS = ROOT / ".validation"
BAR_MARGIN = 18


def private_base(pid, *, environment=None, credentials=None, commandline=None):
    environment = os.environ if environment is None else environment
    required = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR", "NIRI_SOCKET", "WAYLAND_DISPLAY")
    if not pid or any(not environment.get(key) for key in required) or environment.get("GSETTINGS_BACKEND") != "memory":
        raise RuntimeError("Measure only in a private compositor with --pid and isolated XDG paths/GSettings")
    config, state, cache, runtime = [Path(environment[key]) for key in required[:4]]
    base = config / "niri"
    if any(not path.is_absolute() for path in (config, state, cache, runtime)) or not base.is_dir():
        raise RuntimeError("Private configuration paths must exist and be absolute")
    if (base.is_symlink() or base.resolve() == (ROOT / "niri").resolve() or
            any(path.resolve().is_relative_to(ROOT.resolve()) for path in (config, state, cache)) or
            any(path.resolve() == default.resolve() for path, default in
                ((config, Path.home()/".config"), (state, Path.home()/".local/state"), (cache, Path.home()/".cache"))) or
            any(path.is_symlink() for path in base.rglob("*"))):
        raise RuntimeError("Refusing the source/live tree or linked private configuration")
    argv = commandline if commandline is not None else Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
    configs = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value in ("--config", "-c")]
    configs += [value.split("=", 1)[1] for value in argv if value.startswith("--config=")]
    if not any(Path(value).is_absolute() and Path(value).resolve().is_relative_to(base.resolve()) for value in configs):
        raise RuntimeError("Compositor was not started with this private configuration")
    credentials = credentials or session_identity.peer
    display = Path(environment["WAYLAND_DISPLAY"])
    display = display if display.is_absolute() else runtime / display
    if not all(owner == pid and uid == os.getuid() for owner, uid, _gid in
               (credentials(environment["NIRI_SOCKET"]), credentials(display))):
        raise RuntimeError("IPC/Wayland belongs to a different compositor")
    return base


def stop_bar(process, log):
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    finally:
        log.close()


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


