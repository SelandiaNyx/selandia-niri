#!/usr/bin/env python3
"""Actual 20% Apply/reopen, private clipboard and >=3 one-minute service rotations."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = Path(os.environ.get('XDG_STATE_HOME', ''))
if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1' or not PRIVATE.name.startswith('selandia-smoke-'):
    raise SystemExit('Run only via tools/smoke.py --review-probe-only')
BASE = Path(os.environ['XDG_CONFIG_HOME']) / 'niri'
sys.path.insert(0, str(BASE / 'shell'))
import appearance
import i18n
import metrics
import system_info
import wallpaper
import wallpaper_playlist
import panel_probe
from panel_probe import PanelInteractionTests, pump_until, labels, Gdk


def main():
    artifacts = ROOT / '.validation/review-fixes-20261010/probe'
    artifacts.mkdir(parents=True, exist_ok=True)
    saved_run, saved_popen = subprocess.run, subprocess.Popen
    appearance_apply = appearance.apply_settings
    inventory, outputs = system_info.collect()
    assert outputs and 'Niri' in dict(inventory)[i18n.tr('Desktop / WM', '桌面／窗口管理器')]
    text = system_info.plain_text(inventory)
    (artifacts / 'system-info.txt').write_text(text)
    PanelInteractionTests.setUpClass()
    test = PanelInteractionTests(methodName='test_control_tabs_metrics_and_unavailable_readings')
    test.setUp()
    try:
        test.appearance_fixture = dict(appearance.DEFAULTS, opacity=.65, preset='rose', font_size=13)
        window = test.make_control('appearance')
        with patch.object(appearance, 'BASE', BASE), patch.object(appearance, 'apply_settings', side_effect=appearance_apply), \
             patch.object(panel_probe.panel, 'capture', return_value=''):
            window.opacity_scale.set_value(20)
            window.apply_appearance()
            pump_until(lambda: not window.appearance_busy)
            actual = json.loads(appearance.preferences_path().read_text())
            assert actual['opacity'] == .20 and actual['preset'] == 'rose' and actual['font_size'] == 13
            for filename in ('panel.css', 'eww.css', 'swaync.css'):
                assert '.200)' in (BASE / 'theme' / filename).read_text()
            test.appearance_fixture = actual
            test.app.reload_theme()
            window.destroy(); test.window = None
            window = test.make_control('appearance')
            assert window.opacity_scale.get_value() == 20 and window.theme_combo.get_active_id() == 'rose'
        # Parse the generated low-opacity CSS with real GTK, then apply only to our private panel.
        provider = panel_probe.Gtk.CssProvider()
        provider.load_from_path(str(BASE / 'theme/panel.css'))
        panel_probe.Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, 601)
        def screenshot(name):
            path = artifacts / name
            previous = path.stat().st_mtime_ns if path.exists() else 0
            deadline = time.monotonic() + .5
            while time.monotonic() < deadline:
                pump_until(lambda: True)
                time.sleep(.02)
            with patch.object(subprocess, 'Popen', saved_popen):
                saved_run(['niri', 'msg', 'action', 'screenshot-screen', '--path', str(artifacts / name)], check=True,
                          capture_output=True, timeout=5)
            pump_until(lambda: path.exists() and path.stat().st_mtime_ns != previous)
        time.sleep(.4); screenshot('opacity-20.png')
        window.select_control_tab('wallpapers')
        card = window.wallpaper_controls
        pump_until(lambda: card.loaded)
        i18n.set_language('zh_CN')
        # Recreate to obtain Chinese labels using the exact production translation path.
        window.destroy(); test.window = None
        window = test.make_control('wallpapers'); card = window.wallpaper_controls
        pump_until(lambda: card.loaded)
        assert [card.view_buttons[key].get_label() for key in ('grid', 'list')] == ['网格', '列表']
        assert not any('预览' in value for value in labels(card))
        screenshot('wallpapers.png')
        window.select_control_tab('system')
        window.system_detail.set_text(text)
        window.align_system_info()
        assert window.system_detail.get_selectable()
        with patch.object(subprocess, 'run', saved_run), patch.object(subprocess, 'Popen', saved_popen):
            window.system_copy.clicked()
            clipboard = ''
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                pump_until(lambda: True)
                result = saved_run(['wl-paste', '--no-newline'], capture_output=True, text=True, timeout=2)
                clipboard = result.stdout
                if clipboard == text: break
                time.sleep(.03)
            assert clipboard == window.system_detail.get_text() == text
            (artifacts / 'clipboard.txt').write_text(clipboard)
        screenshot('system-info.png')
        # Resize only our owned nested compositor; never a user's application.
        import session_probe
        host = os.environ.get('SELANDIA_PROBE_HOST_SOCKET')
        if host:
            pid = int(Path(os.environ['NIRI_SOCKET']).name.rsplit('.', 2)[1])
            with patch.object(subprocess, 'Popen', saved_popen), patch.object(subprocess, 'run', saved_run):
                assert session_probe.resize_host_window(pid, 900, host, height=1000)
            with patch.object(subprocess, 'Popen', saved_popen), patch.object(subprocess, 'run', saved_run):
                output = session_probe.connected_output()[0]
                session_probe.niri('output', output, 'scale', '1.5').check_returncode()
            time.sleep(.5); pump_until(lambda: True)
            window.destroy(); test.window = None
            window = test.make_control('system')
            window.system_detail.set_text(text)
            window.align_system_info()
            screenshot('system-info-narrow.png')
            monitor = Gdk.Display.get_default().get_monitor(0).get_geometry()
            allocation = window.get_allocation()
            assert allocation.width <= monitor.width - 24
            assert window.panel_width < 650 and window.system_detail.get_line_wrap()
            window.select_control_tab('wallpapers')
            card = window.wallpaper_controls
            pump_until(lambda: card.loaded)
            card.section_switch.set_active_id('playlist')
            adjustment = card.sections.get_visible_child().get_vadjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            screenshot('playlist-narrow.png')
    finally:
        test.doCleanups()
    print('PASS real GTK: Apply 20%, JSON/CSS, reopen, bilingual Grid/List and exact wl-copy/wl-paste', flush=True)
    if os.environ.get('SELANDIA_REVIEW_UI_ONLY') == '1':
        return
    # No GTK window remains while the wallpaper process runs for three real minutes.
    fixtures = PRIVATE / 'playlist-fixtures'; fixtures.mkdir()
    entries = []
    for index, color in enumerate(('#3050a0', '#b05030', '#208050')):
        image = fixtures / f'image-{index}.svg'
        image.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="{color}"/></svg>')
        entries.append({'path': str(image), 'mode': 'live'})
    wallpaper.save_settings({'selection': None, 'audio': {'volume': 50, 'muted': False},
                             'playlist': dict(wallpaper_playlist.DEFAULTS, enabled=True, items=entries, order='random', minutes=1, seconds=60)})
    children = []
    def start(name):
        path = artifacts / (name + '.log')
        with path.open('w') as out:
            child = saved_popen([sys.executable, '-B', str(BASE / 'shell/wallpaper.py'), 'run'],
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        children.append(child)
        return child, path
    def stop(child):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=3)
    def events(path):
        result = []
        for line in path.read_text().splitlines():
            try: value = json.loads(line)
            except ValueError: continue
            if isinstance(value, dict) and value.get('wallpaper_playlist') == 'switched': result.append(value)
        return result
    def wait_switches(child, path, count, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if child.poll() is not None: raise RuntimeError(path.read_text())
            result = events(path)
            if len(result) >= count: return result
            time.sleep(.2)
        raise RuntimeError('Insufficient rotations: ' + path.read_text())
    try:
        child, log = start('timer-random')
        started = time.monotonic()
        switches = wait_switches(child, log, 3, 205)
        elapsed = time.monotonic() - started
        assert elapsed >= 180
        assert len({item['path'] for item in switches}) >= 2
        assert all(left['path'] != right['path'] for left, right in zip(switches, switches[1:]))
        before_restart = wallpaper.load_settings()
        stop(child)
        child, restart_log = start('restart-persistence')
        time.sleep(2)
        assert child.poll() is None and wallpaper.load_settings() == before_restart
        stop(child)
        print(f'PASS timer/random: {len(switches)} switches in {elapsed:.2f}s, panel closed, same supervisor, restart persisted', flush=True)
        videos = []
        for index, color in enumerate(('teal', 'purple')):
            video = fixtures / f'video-{index}.mp4'
            saved_run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                       f'color=c={color}:s=320x180:r=15:d=4', '-c:v', 'libx264', str(video)], check=True, timeout=15)
            videos.append({'path': str(video), 'mode': 'live'})
        # Give preview generation a bounded, real video decoder; it never touches the source file.
        selected = dict(videos[0], fallback=str(Path(entries[0]['path'])))
        settings = {**before_restart, 'selection': selected,
                    'playlist': dict(before_restart['playlist'], items=videos, trigger='finished', order='sequential')}
        wallpaper.save_settings(settings)
        child, finished_log = start('finished-video')
        finished_switches = wait_switches(child, finished_log, 2, 30)
        stop(child)
        wallpaper.save_settings({**settings, 'playlist': dict(settings['playlist'], trigger='timer')})
        child, loop_log = start('timer-video')
        time.sleep(10)
        assert child.poll() is None and not events(loop_log)
        stop(child)
        wallpaper.save_settings({**settings, 'playlist': dict(settings['playlist'], items=[])})
        child, empty_log = start('empty-playlist')
        time.sleep(2)
        assert child.poll() is None and not events(empty_log)
        stop(child)
        result = {'timer_elapsed_seconds': elapsed, 'timer_switches': switches, 'finite_video_switches': finished_switches,
                  'timer_video_ten_seconds_no_switch': True, 'empty_playlist_idle': True,
                  'restarted_configuration_identical': True, 'clipboard_matches_screen': True, 'opacity_apply_reopen': .20}
        (artifacts / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('PASS natural video EOF vs looping timer; empty playlist idle; owned children waited/reaped', flush=True)
    finally:
        for child in reversed(children): stop(child)


if __name__ == '__main__': main()
