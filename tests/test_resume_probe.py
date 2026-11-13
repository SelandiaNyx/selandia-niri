import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resume_probe', ROOT / 'tools/resume_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ResumeProbeTests(unittest.TestCase):
    def test_missing_files_and_commands_are_recorded_not_zero(self):
        self.assertIsNone(probe.read_text('/selandia-missing-file'))
        def missing(*args, **kwargs):
            raise FileNotFoundError('unavailable')
        self.assertIsNone(probe.command(['absent'], missing)['returncode'])

    def test_timeout_preserves_error(self):
        def slow(*args, **kwargs):
            raise subprocess.TimeoutExpired('niri', 8)
        self.assertIn('timed out', probe.command(['niri'], slow)['stderr'])

    def test_before_and_after_signals(self):
        self.assertEqual(probe.event('org.freedesktop.login1.Manager.PrepareForSleep (true,)'), 'before-sleep')
        self.assertEqual(probe.event('PrepareForSleep (false,)'), 'after-resume')
        self.assertIsNone(probe.event('unrelated true'))

    def test_connector_missing_fields_and_real_driver(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connector = root / 'card0-DP-1';connector.mkdir()
            (connector / 'status').write_text('disconnected\n')
            self.assertEqual(probe.devices(root), [{'connector':'card0-DP-1','status':'disconnected','enabled':None,'modes':None}])

    def test_capture_persists_unique_snapshots_and_never_mutates_services(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, 'evidence', '')
        with tempfile.TemporaryDirectory() as temporary, patch.dict(probe.os.environ, {'NIRI_SOCKET':'/tmp/test.sock'}):
            first = probe.capture(temporary, 'before', run)
            second = probe.capture(temporary, 'after', run)
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text())['label'], 'before')
            self.assertFalse(list(Path(temporary).glob('*.partial')))
        self.assertFalse(any(word in args for args in calls for word in ('restart','stop','suspend','power-on-monitors','power-off-monitors')))
        self.assertTrue(any(args[:4] == ['niri','msg','--json','outputs'] for args in calls))
        self.assertTrue(any('_COMM=niri' in args for args in calls))
