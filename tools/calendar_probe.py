#!/usr/bin/env python3
"""Render the actual calendar in both UI languages and monitor sizes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

if os.environ.get('SELANDIA_PRIVATE_PROBE') != '1':
    raise SystemExit('Run through smoke.py --calendar-probe-only')
import panel_probe
import session_probe
from panel_probe import PanelInteractionTests, Gdk, Gtk, pump_until
import appearance
import i18n

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / '.validation/event-feeds-20261014/calendar'


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    PanelInteractionTests.setUpClass()
    results = []
    real_run, real_popen = subprocess.run, subprocess.Popen
    for size, width, height, scale, theme in (
            ('wide', 1800, 1100, 1, 'dark'), ('narrow', 900, 1000, 1.5, 'light')):
        assert session_probe.resize_host_window(int(sys.argv[1]), width,
                    os.environ['SELANDIA_PROBE_HOST_SOCKET'], height=height)
        output = session_probe.connected_output()[0]
        session_probe.niri('output', output, 'scale', str(scale)).check_returncode()
        deadline = time.monotonic() + .4
        pump_until(lambda: time.monotonic() >= deadline)
        with patch.object(appearance, 'BASE', Path(os.environ['XDG_CONFIG_HOME']) / 'niri'):
            appearance.apply_settings({**appearance.load_settings(), 'color_mode': theme, 'wallpaper_colors': False})
        with patch.object(panel_probe.panel, 'BASE', Path(os.environ['XDG_CONFIG_HOME']) / 'niri'):
            PanelInteractionTests.app.reload_theme()
        for language in ('en_US', 'zh_CN'):
            case = size + '-' + language
            test = PanelInteractionTests(methodName='test_calendar_is_independent_and_today_restores_selected_date')
            test.setUp(); i18n.set_language(language)
            try:
                window = test.make_panel('calendar')
                widget = window.calendar
                widget.select_month(0, 2023); widget.select_day(31)
                deadline = time.monotonic() + .25
                pump_until(lambda: time.monotonic() >= deadline)
                geometry = Gdk.Display.get_default().get_monitor(0).get_geometry()
                assert window.get_allocated_width() <= geometry.width
                assert window.get_allocated_height() <= geometry.height
                assert len(widget.day_buttons) == 31
                for button in widget.day_buttons.values():
                    x, y = button.translate_coordinates(window, 0, 0)
                    assert x >= 0 and y >= 0
                    assert x + button.get_allocated_width() <= window.get_allocated_width()
                    assert y + button.get_allocated_height() <= window.get_allocated_height()
                assert widget.month_label.get_text() == ('2023年 一月' if language == 'zh_CN' else 'January 2023')
                path = ARTIFACTS / (case + '.png')
                before = path.stat().st_mtime_ns if path.exists() else 0
                with patch.object(subprocess, 'run', real_run), patch.object(subprocess, 'Popen', real_popen):
                    real_run(['niri', 'msg', 'action', 'screenshot-screen', '--path', str(path),
                              '--show-pointer', 'false'], check=True, capture_output=True, timeout=5)
                    pump_until(lambda: path.exists() and path.stat().st_mtime_ns != before)
                results.append({'case': case, 'theme': theme, 'month': widget.month_label.get_text(),
                    'weekdays': [label.get_text() for label in widget.weekday_labels],
                    'allocation': [window.get_allocated_width(), window.get_allocated_height()],
                    'six_weeks_fit': True})
            finally:
                test.doCleanups()
    (ARTIFACTS / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
    print('PASS calendar: English/Chinese in wide dark and narrow light layouts; six full weeks visible')


if __name__ == '__main__': main()
