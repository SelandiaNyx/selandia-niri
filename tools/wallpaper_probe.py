#!/usr/bin/env python3
"""Real wallpaper playback on the private compositor created by smoke.py."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get("XDG_STATE_HOME", ""))
if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1" or not PRIVATE.name.startswith("selandia-smoke-"):
    raise SystemExit("Refusing wallpaper probe outside an isolated smoke session")
BASE = Path(os.environ["XDG_CONFIG_HOME"]) / "niri"
sys.path.insert(0, str(BASE / "shell"))
import wallpaper
import appearance

ARTIFACTS = ROOT / ".validation/wallpaper-20261009"
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
    raise RuntimeError("Wallpaper screenshot timeout")


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=4)


def main():
    library = PRIVATE / "fixture/431960/100"
    library.mkdir(parents=True)
    image = library / "preview.svg"
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#cb44a4"/></svg>')
    video = library / "movie.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=10:duration=2", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=10)
    (library / "project.json").write_text(json.dumps({"type": "video", "title": "动态壁纸测试", "file": "movie.mp4", "preview": "preview.svg"}))
    wallpaper.save_settings({"roots": [str(library.parent)], "assets": "", "selection": {
        "path": str(library), "mode": "live", "fallback": str(image)}})
    if not wallpaper.shutil.which("mpvpaper"):
        raise RuntimeError("This optional playback probe requires mpvpaper in PATH")
    handle = (ARTIFACTS / "video-runtime.log").open("w")
    runtime = subprocess.Popen([sys.executable, "-B", str(BASE / "shell/wallpaper.py"), "run"],
                               stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    panel = None
    try:
        time.sleep(3)
        if runtime.poll() is not None:
            raise RuntimeError("Wallpaper runner exited")
        first = screenshot("video-first.png").get_pixels()
        time.sleep(.4)
        second = screenshot("video-second.png").get_pixels()
        if first == second:
            raise RuntimeError("Video frames are not changing")
        windows = json.loads(subprocess.check_output(["niri", "msg", "--json", "windows"], text=True, timeout=5))
        if windows:
            raise RuntimeError("Wallpaper unexpectedly created an application window")
        print("PASS video: changing frames on background layer; no application window", flush=True)
        children = Path(f"/proc/{runtime.pid}/task/{runtime.pid}/children").read_text().split()
        player = next(int(pid) for pid in children if Path(f"/proc/{pid}/comm").read_text().strip() == "mpvpaper")
        os.kill(player, signal.SIGTERM)
        time.sleep(1)
        fallback = screenshot("video-fallback.png")
        rgb = fallback.get_pixels()[:3]
        if not (rgb[0] > 150 and rgb[1] < 110 and rgb[2] > 110):
            raise RuntimeError(f"Static fallback is not visible: {list(rgb)}")
        print("PASS renderer exit: static fallback visible", flush=True)
        settings = appearance.load_settings()
        appearance.apply_settings({**settings, "wallpaper_colors": True, "wallpaper_seed": wallpaper.extract_seed(image)})
        panel = subprocess.Popen([sys.executable, "-B", str(BASE / "shell/panel.py"), "wallpapers"],
                                 stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        time.sleep(2)
        if panel.poll() is not None:
            raise RuntimeError("Wallpaper settings window exited")
        subprocess.run(["swaync-client", "--skip-wait", "--hide-all"], check=False, timeout=3,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        screenshot("wallpaper-library.png")
        print("PASS appearance: wallpaper library and wallpaper-derived theme rendered", flush=True)
    finally:
        if panel:
            stop(panel)
        stop(runtime)
        handle.close()


if __name__ == "__main__":
    main()
