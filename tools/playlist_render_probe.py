#!/usr/bin/env python3
"""Playlist video must visibly animate above its guard, survive EOF and failures."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('XDG_STATE_HOME', ''))
if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1' or not PRIVATE.name.startswith('selandia-smoke-'):
    raise SystemExit('Run through the private smoke session')
BASE = Path(os.environ['XDG_CONFIG_HOME']) / 'niri'
sys.path.insert(0, str(BASE / 'shell'))
import appearance
import wallpaper as w
import wallpaper_playlist as policy


def main():
    artifacts = ROOT / '.validation/review-fixes-20261010/render'
    artifacts.mkdir(parents=True, exist_ok=True)
    video = PRIVATE / 'animated.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=15:duration=3', '-c:v', 'libx264', str(video)], check=True, timeout=10)
    appearance.apply_settings({**appearance.load_settings(), 'wallpaper_colors': False})
    preview = w.preview_image(w.describe(video))
    entries = [{'path': str(video), 'mode': 'live'}]
    settings = {'selection': dict(entries[0], fallback=str(preview)),
                'playlist': dict(policy.DEFAULTS, enabled=True, items=entries, trigger='finished', minutes=1, seconds=60)}
    w.save_settings(settings)
    handle = (artifacts / 'runtime.log').open('w')
    child = subprocess.Popen([sys.executable, '-B', str(BASE / 'shell/wallpaper.py'), 'run'],
                             stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
    def shot(name):
        path = artifacts / name
        subprocess.run(['niri', 'msg', 'action', 'screenshot-screen', '--path', str(path), '--show-pointer', 'false'],
                       capture_output=True, check=True, timeout=5)
        deadline = time.monotonic() + 3
        while not path.exists() and time.monotonic() < deadline: time.sleep(.02)
        return w.pixbuf(path, 160, 100).get_pixels()
    try:
        time.sleep(1.5)
        first = shot('animated-first.png')
        time.sleep(.5)
        second = shot('animated-second.png')
        assert first != second, 'Static guard is hiding video frames'
        # A one-video playlist must replay after EOF without replacing its service.
        deadline = time.monotonic() + 18
        events = []
        while time.monotonic() < deadline:
            events = [line for line in (artifacts / 'runtime.log').read_text().splitlines() if '"wallpaper_playlist": "switched"' in line]
            if len(events) >= 2: break
            assert child.poll() is None
            time.sleep(.1)
        assert len(events) >= 2, events
        assert child.poll() is None
        children = Path(f'/proc/{child.pid}/task/{child.pid}/children').read_text().split()
        assert len(children) == 2, children
        assert all(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z' for pid in children)
        print('PASS playlist renderer: changing pixels above static guard; one-video EOF replay; two owned children, zero zombies', flush=True)
    finally:
        if child.poll() is None: os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=6); handle.close()


if __name__ == '__main__': main()
