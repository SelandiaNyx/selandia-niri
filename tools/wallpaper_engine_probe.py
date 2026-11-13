#!/usr/bin/env python3
"""Exercise installed scene/Web rendering only in smoke.py's private compositor."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get("XDG_STATE_HOME", ""))
if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1" or not PRIVATE.name.startswith("selandia-smoke-"):
    raise SystemExit("Refusing Wallpaper Engine probe outside a private smoke session")
BASE = Path(os.environ["XDG_CONFIG_HOME"]) / "niri"
sys.path.insert(0, str(BASE / "shell"))
import wallpaper

ARTIFACTS = ROOT / ".validation/dependencies-20261009"
ARTIFACTS.mkdir(exist_ok=True)


def screenshot(name):
    path = ARTIFACTS / name
    previous = path.stat().st_mtime_ns if path.exists() else 0
    subprocess.run(["niri", "msg", "action", "screenshot-screen", "--path", str(path),
                    "--show-pointer", "false"], check=True, stdout=subprocess.DEVNULL, timeout=5)
    for _ in range(30):
        if path.exists() and path.stat().st_mtime_ns != previous:
            return wallpaper.pixbuf(path, 160, 100)
        time.sleep(.1)
    raise RuntimeError("Wallpaper Engine screenshot timeout")


def probe(item, assets, name):
    outputs = json.loads(subprocess.check_output(["niri", "msg", "--json", "outputs"], text=True, timeout=5))
    names = [name for name, value in outputs.items() if value.get("current_mode") is not None]
    command = wallpaper.playback_command(item, "live", assets=assets, outputs=names)
    environment = wallpaper.renderer_environment(item)
    baseline = screenshot(name + "-baseline.png")
    with (ARTIFACTS / (name + ".log")).open("w") as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            time.sleep(5)
            if process.poll() is not None:
                raise RuntimeError(f"{name} renderer exited ({process.returncode}); see {name}.log")
            first = screenshot(name + "-first.png")
            time.sleep(.13)
            second = screenshot(name + "-second.png")
            (ARTIFACTS / (name + "-layers.json")).write_text(subprocess.check_output(
                ["niri", "msg", "--json", "layers"], text=True, timeout=5))
            if first.get_pixels() == baseline.get_pixels():
                raise RuntimeError(name + " wallpaper is not visible")
            if name == "web":
                for interval in (.23, .41, .59):
                    if first.get_pixels() != second.get_pixels():
                        break
                    time.sleep(interval)
                    second = screenshot(name + "-second.png")
                if first.get_pixels() == second.get_pixels():
                    raise RuntimeError(name + " frames are not changing")
            windows = json.loads(subprocess.check_output(["niri", "msg", "--json", "windows"], text=True, timeout=5))
            if windows:
                raise RuntimeError(name + " wallpaper created an application window")
            print("PASS " + name + ": engine renders visible wallpaper on the private background" +
                  (" with changing frames" if name == "web" else ""), flush=True)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def main():
    catalog = wallpaper.discover()
    if not catalog["backends"]["linux-wallpaperengine"] or not catalog["assets"]:
        raise RuntimeError("Installed linux-wallpaperengine and original assets are required")
    # Use a small original bundled scene, copied before running any renderer.
    original = Path(catalog["assets"]).parent / "projects/defaultprojects/eagleflag"
    scene = PRIVATE / "engine-fixture/scene"
    shutil.copytree(original, scene)
    probe(wallpaper.describe(scene), catalog["assets"], "scene")
    web = PRIVATE / "engine-fixture/web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><body style='margin:0;background:#2070d0'>"
        "<script>setInterval(()=>{document.body.style.background='rgb('+"
        "(30+Math.floor(performance.now()/100)%180)+',100,180)'},80)</script>")
    shutil.copy2(BASE / "assets/selandia-glass.svg", web / "preview.svg")
    (web / "project.json").write_text(json.dumps({"type": "web", "title": "Local Web rendering fixture",
                                                  "file": "index.html", "preview": "preview.svg"}))
    probe(wallpaper.describe(web), catalog["assets"], "web")


if __name__ == "__main__":
    main()
