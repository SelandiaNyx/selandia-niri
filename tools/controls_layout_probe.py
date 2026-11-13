#!/usr/bin/env python3
"""Measure large and narrow control centres on smoke.py's private compositor."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get("XDG_STATE_HOME", ""))
if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1" or not PRIVATE.name.startswith("selandia-smoke-"):
    raise SystemExit("Run through tools/smoke.py on its private compositor")
sys.path.insert(0, str(ROOT / "niri/shell"))
import session_probe
import panel_probe
from panel_probe import Gdk, Gtk, PanelInteractionTests, pump_until
import metrics


def main():
    artifacts = ROOT / ".validation/controls-volume-20261009/layout"
    artifacts.mkdir(parents=True, exist_ok=True)
    pid = int(sys.argv[1])
    host = os.environ.get("SELANDIA_PROBE_HOST_SOCKET")
    if not host:
        raise RuntimeError("Host IPC is required only to resize our own nested window")
    saved_run, saved_popen = subprocess.run, subprocess.Popen
    PanelInteractionTests.setUpClass()
    PanelInteractionTests.app.reload_theme()
    sampler = metrics.MetricsSampler(detailed=True, enable_nvidia=False)
    sampler.sample()
    time.sleep(.15)
    inventory = sampler.sample()
    results = []
    for case, width, scale in (("wide", 2400, 1), ("narrow", 900, 1.5)):
        if not session_probe.resize_host_window(pid, width, host, height=1320 if case == "wide" else 1000):
            raise RuntimeError("Could not resize the owned preview window")
        output = session_probe.connected_output()[0]
        session_probe.niri("output", output, "scale", str(scale)).check_returncode()
        time.sleep(.4)
        pump_until(lambda: True)
        test = PanelInteractionTests(methodName="test_control_tabs_metrics_and_unavailable_readings")
        test.setUp()
        try:
            window = test.make_control("wallpapers")
            test.metric_fixture.update(inventory)
            window.apply_metrics(test.metric_fixture)
            card = window.wallpaper_controls
            pump_until(lambda: card.loaded)
            for index in range(7):
                card.add_item(dict(test.wallpaper_fixture, path=f"/probe/{index}", title=f"Wallpaper {index + 1}"))
            card.grid.show_all()
            card.set_view("grid")
            pump_until(lambda: all(entry["loaded"] for entry in list(card.items.values())[:2]))
            streams = test.streams()
            test.audio_fixture["streams"] = streams
            window.apply_audio(test.audio_fixture)
            monitor = Gdk.Display.get_default().get_monitor(0).get_geometry()
            allocation = window.get_allocation()
            if allocation.width > monitor.width - 24 or allocation.height > monitor.height - 48:
                raise RuntimeError(f"{case} panel exceeds viewport: {allocation.width}x{allocation.height} / {monitor.width}x{monitor.height}")
            columns = window.navigation.get_parent()
            if case == "narrow" and (window.panel_width >= 650 or columns.get_orientation() != Gtk.Orientation.VERTICAL):
                raise RuntimeError("Narrow screen did not select stacked navigation")
            if case == "wide" and window.panel_width < 1300:
                raise RuntimeError(f"Wide screen did not enlarge control centre: requested={window.panel_width}, monitor={monitor.width}x{monitor.height}")
            def screenshot(page):
                window.select_control_tab(page)
                pump_until(lambda: not window.control_stack.get_transition_running())
                time.sleep(.1)
                pump_until(lambda: True)
                # Only the synchronous screenshot command is unmocked. Its
                # environment points at the private nested Wayland display.
                with patch.object(subprocess, "Popen", saved_popen), patch.object(subprocess, "run", saved_run):
                    session_probe.screenshot(artifacts / f"{case}-{page}.png")
            for page in ("wallpapers", "sound", "system"):
                screenshot(page)
            if case == "narrow":
                test.destroy_panel()
                window = test.make_panel("shortcuts")
                if window.panel_width >= 650:
                    raise RuntimeError("Narrow shortcut layout was not exercised")
            results.append({"case": case, "logical_output": [monitor.width, monitor.height],
                "control": [allocation.width, allocation.height], "navigation": "stacked" if case == "narrow" else "sidebar",
                "thumbnail": [224, 126], "status": "passed"})
        finally:
            test.doCleanups()
    (artifacts / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print("PASS: enlarged wide control centre, narrow stacked navigation and shortcuts; grid/sound/system screenshots", flush=True)


if __name__ == "__main__":
    main()
