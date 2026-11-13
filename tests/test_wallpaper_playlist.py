"""Playlist policy, renderer ownership and SIGKILL recovery in disposable state."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
import appearance
import i18n
import wallpaper as w
import wallpaper_playlist as policy


class PlaylistPolicyTests(unittest.TestCase):
    def playlist(self, **values):
        return policy.validate(dict(policy.DEFAULTS, items=[{'path': '/a', 'mode': 'live'}, {'path': '/b', 'mode': 'preview'}], **({**values, 'seconds': values['minutes'] * 60} if 'minutes' in values else values)), Path)

    def test_unknown_and_malformed_settings_are_safe_defaults(self):
        for value in (None, [], {'unknown': True}, {'items': 'bad'}, {'items': [{}] * 1001}):
            self.assertEqual(policy.validate(value, Path), policy.DEFAULTS)
        result = policy.validate({'enabled': 'true', 'minutes': True, 'order': 'bad', 'trigger': 'bad',
                                  'items': [{'path': '/a', 'mode': 'live'}, {'path': '/a', 'mode': 'live'}, {}, {'path': '/b', 'mode': 'bad'}]}, Path)
        self.assertFalse(result['enabled']); self.assertEqual(result['minutes'], 10)
        self.assertEqual(result['items'], [{'path': '/a', 'mode': 'live', 'enabled': True, 'weight': 1}])

    def test_minutes_boundaries_and_valid_options_persist(self):
        for minutes in (1, 180):
            value = self.playlist(enabled=True, minutes=minutes, trigger='finished', order='random')
            self.assertEqual(policy.validate(value, Path), value)
        for minutes in (0, 181, 1.5, '1'):
            self.assertEqual(policy.validate({'minutes': minutes}, Path)['minutes'], 10)

    def test_sequential_wrap_previous_and_random_excludes_current(self):
        values = self.playlist()
        self.assertEqual(policy.candidates(values, {'path': '/a', 'mode': 'live', 'fallback': '/cached'})[0]['path'], '/b')
        self.assertEqual(policy.candidates(values, {'path': '/a', 'mode': 'live'}, -1)[0]['path'], '/b')
        values['order'] = 'random'
        self.assertEqual(policy.candidates(values, {'path': '/a', 'mode': 'live'}, choose=lambda items: items[0]), [values['items'][1]])
        self.assertEqual(policy.candidates(dict(values, items=[]), None), [])

    def test_timer_three_real_minute_intervals_and_selection_reset(self):
        settings = {'selection': None, 'playlist': self.playlist(enabled=True, minutes=1)}
        schedule = policy.Schedule(0)
        self.assertFalse(schedule.due(settings, 0, finished=True))
        for start in (0, 60, 120):
            self.assertFalse(schedule.due(settings, start + 59))
            self.assertTrue(schedule.due(settings, start + 60))
            schedule.attempted(start + 60, True)
        settings['selection'] = {'path': '/a', 'mode': 'live'}
        self.assertFalse(schedule.due(settings, 190))
        self.assertFalse(schedule.due(settings, 249)); self.assertTrue(schedule.due(settings, 250))

    def test_finished_empty_disabled_and_failure_backoff(self):
        settings = {'selection': None, 'playlist': self.playlist(enabled=True, trigger='finished')}
        schedule = policy.Schedule(0)
        self.assertFalse(schedule.due(settings, 10000, finished=False))
        self.assertTrue(schedule.due(settings, 10001, finished=True))
        schedule.attempted(10001, False)
        self.assertFalse(schedule.due(settings, 10030, finished=True)); self.assertTrue(schedule.due(settings, 10031, finished=True))
        settings['playlist']['items'] = []
        self.assertFalse(schedule.due(settings, 20000, finished=True))
        settings['playlist'] = self.playlist(enabled=False)
        self.assertFalse(schedule.due(settings, 30000, finished=True))


class PlaylistTransactionsTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language('en_US')
        self.addCleanup(i18n.set_language, None)
        temp = tempfile.TemporaryDirectory(prefix='selandia-playlist-test-')
        self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root / 'state'), XDG_CACHE_HOME=str(self.root / 'cache'),
                         XDG_RUNTIME_DIR=str(self.root), PYTHONPATH=str(ROOT / 'niri/shell'))
        env.start(); self.addCleanup(env.stop)
        self.image = self.root / 'image.svg'
        self.image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"><rect width="100" height="60" fill="#2080aa"/></svg>')
        w.save_settings({'audio': {'muted': True, 'volume': 27}, 'selection': None})
        self.before = w.load_settings()
        self.stack_audio = patch.object(w.wallpaper_audio, 'available', return_value=False)
        self.stack_audio.start(); self.addCleanup(self.stack_audio.stop)

    def test_playlist_does_not_reset_existing_audio_or_selection(self):
        with patch.object(w, 'restart_renderer'):
            value = w.configure_playlist({'enabled': True, 'items': [{'path': str(self.image), 'mode': 'live'}], 'order': 'random', 'minutes': 1})
        self.assertEqual(w.load_settings()['playlist'], value)
        self.assertEqual(w.load_settings()['audio'], self.before['audio'])
        self.assertEqual(w.load_settings()['selection'], self.before['selection'])
        w.save_settings({**w.load_settings(), 'playlist': {'nonsense': 1}})
        self.assertEqual(w.load_settings()['playlist'], policy.DEFAULTS)
        self.assertEqual(w.load_settings()['audio'], self.before['audio'])

    def test_handoff_failure_restores_previous_selection_and_replays_it(self):
        calls = []
        def handoff(value):
            calls.append(value['selection'])
            if value['selection']:
                raise RuntimeError('fixture readiness failure')
        with patch.object(w, 'restart_renderer') as restart:
            with self.assertRaisesRegex(RuntimeError, 'readiness failure'):
                w.activate(self.image, handoff=handoff)
            restart.assert_not_called()
        self.assertEqual(calls[-1], None)
        self.assertEqual(w.load_settings(), self.before)
        self.assertFalse((w.state_dir() / 'wallpaper-transition.json').exists())

    def test_manual_change_wins_over_stale_scheduler_snapshot(self):
        old = w.load_settings()
        w.save_settings({**old, 'playlist': policy.validate({'minutes': 20}, Path)})
        with patch.object(w, 'restart_renderer') as restart:
            with self.assertRaisesRegex(RuntimeError, 'changed during playlist'):
                w.activate(self.image, expected=old)
            restart.assert_not_called()
        self.assertEqual(w.load_settings()['playlist']['minutes'], 20)

    def test_follow_wallpaper_colors_reuses_theme_reload_for_handoff(self):
        with patch.object(appearance, 'load_settings', return_value=dict(appearance.DEFAULTS, wallpaper_colors=True)), \
             patch.object(appearance, 'apply_settings') as apply, patch.object(w.subprocess, 'run') as run, \
             patch.object(w, 'restart_renderer') as restart:
            w.activate(self.image, handoff=Mock())
        restart.assert_not_called(); apply.assert_called_once()
        self.assertEqual(run.call_args.args[0], [str(w.BASE / 'scripts/desktop'), 'theme-reload'])

    def test_bad_entry_is_skipped_without_losing_good_selection(self):
        settings = dict(self.before, playlist=dict(policy.DEFAULTS, items=[{'path': '/absent.svg', 'mode': 'live'}, {'path': str(self.image), 'mode': 'live'}]))
        w.save_settings(settings)
        with patch.object(w, 'restart_renderer') as restart:
            result = w.playlist_step(handoff=Mock())
        restart.assert_not_called(); self.assertEqual(result['item']['path'], str(self.image))

    def test_sigkill_during_handoff_restores_durable_previous_selection(self):
        ready = self.root / 'handoff-ready'
        worker = self.root / 'worker.py'
        worker.write_text("import time\nfrom pathlib import Path\nimport wallpaper as w\n"
                          f"def handoff(settings):\n Path({str(ready)!r}).touch()\n time.sleep(60)\n"
                          f"w.activate({str(self.image)!r}, handoff=handoff)\n")
        process = subprocess.Popen([sys.executable, '-B', str(worker)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(ready.exists(), process.stderr.read().decode() if process.poll() is not None else 'worker did not reach handoff')
            process.kill(); process.wait(timeout=3)
            self.assertIsNotNone(w.load_settings()['selection'])
            with w.settings_lock(): w.recover_transition()
            self.assertEqual(w.load_settings(), self.before)
            self.assertFalse((w.state_dir() / 'wallpaper-transition.json').exists())
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=3)
            process.stderr.close()

    def test_committed_transition_survives_restart_and_foreign_edit_is_preserved(self):
        after = w.with_playlist(self.before, policy.validate({'minutes': 22}, Path))
        path = w.state_dir() / 'wallpaper-transition.json'
        w.save_settings(after)
        w.atomic_write(path, json.dumps({'version': 1, 'phase': 'committed', 'before': self.before, 'after': after}).encode())
        with w.settings_lock(): w.recover_transition()
        self.assertEqual(w.load_settings(), after)
        w.atomic_write(path, json.dumps({'version': 1, 'phase': 'prepared', 'before': self.before, 'after': after}).encode())
        foreign = dict(after, audio={'muted': False, 'volume': 50}); w.save_settings(foreign)
        with self.assertRaisesRegex(RuntimeError, 'Preserving wallpaper'):
            with w.settings_lock(): w.recover_transition()
        self.assertEqual(w.load_settings(), foreign)

    def test_new_renderer_failure_keeps_previous_children_and_reaps_candidate(self):
        supervisor = w.PlaylistRenderer()
        old = Mock(pid=901, poll=Mock(return_value=None))
        supervisor.renderer = old; supervisor.guard = Mock(pid=902); supervisor.selection = {'path': '/old', 'mode': 'live'}
        guard = Mock(pid=903, poll=Mock(return_value=None))
        candidate = Mock(pid=904, poll=Mock(return_value=1))
        selection = {'path': str(self.image), 'mode': 'live'}
        with patch.object(w.subprocess, 'Popen', side_effect=[guard, candidate]), patch.object(supervisor, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'New wallpaper renderer failed'):
                supervisor.replace(dict(self.before, selection=selection))
            self.assertIs(supervisor.renderer, old)
            self.assertEqual([call.args[0] for call in stop.call_args_list], [candidate, guard, None])
            supervisor.close()

    def test_stop_waits_for_every_child_and_escalates_only_its_own_group(self):
        child = Mock(pid=920, wait=Mock(side_effect=[subprocess.TimeoutExpired('fixture', 2), 0]))
        with patch.object(w.os, 'killpg') as kill:
            w.PlaylistRenderer.stop(child)
        self.assertEqual(child.wait.call_count, 2)
        self.assertEqual([call.args for call in kill.call_args_list], [(920, signal.SIGTERM), (920, signal.SIGKILL)])

    def test_finite_video_uses_real_eof_while_timer_keeps_looping(self):
        supervisor = w.PlaylistRenderer()
        supervisor.renderer = Mock(poll=Mock(return_value=None))
        supervisor.record = {'kind': 'video'}
        with patch.object(supervisor, 'property', return_value=False): self.assertFalse(supervisor.finished())
        with patch.object(supervisor, 'property', return_value=True): self.assertTrue(supervisor.finished())
        supervisor.record = {'kind': 'scene'}
        with patch.object(supervisor, 'property', return_value=True): self.assertFalse(supervisor.finished())
        with patch.object(supervisor, 'stop'): supervisor.close()
