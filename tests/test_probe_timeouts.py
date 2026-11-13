"""A missing/blocked daemon must never leave a maintenance check waiting forever."""
import ast
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import resume_probe
import run_tests


class ProbeTimeoutTests(unittest.TestCase):
    def test_all_synchronous_tool_commands_have_deadlines(self):
        missing = []
        for path in sorted((ROOT / 'tools').glob('*.py')):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == 'subprocess'
                        and node.func.attr in ('run', 'call', 'check_call', 'check_output')):
                    deadlines = [kw.value for kw in node.keywords if kw.arg == 'timeout']
                    if not deadlines or isinstance(deadlines[0], ast.Constant) and deadlines[0].value is None:
                        missing.append(f'{path.name}:{node.lineno}')
        self.assertEqual(missing, [], 'Unbounded maintenance subprocess: ' + ', '.join(missing))

    def test_hung_client_is_killed_and_saved_as_failure(self):
        # A real hung child and real Python timeout, on private files, with a
        # shortened test budget; no socket or system bus is contacted.
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / 'client.pid'
            script = ('import os,time; from pathlib import Path; '
                      f'Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)')
            def shortened(argv, **options):
                self.assertEqual(options['timeout'], 8)
                options['timeout'] = .3
                return subprocess.run(argv, **options)
            start = time.monotonic()
            result = resume_probe.command([sys.executable, '-B', '-c', script], shortened)
            self.assertLess(time.monotonic() - start, 3)
            self.assertIsNone(result['returncode'])
            self.assertIn('timed out', result['stderr'])
            self.assertFalse(Path('/proc/' + pid_file.read_text()).exists())

    def test_kill_after_bounds_a_client_that_ignores_term(self):
        # Exercise GNU timeout's process-group KILL fallback, without a pipe.
        script = ('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                  'print("READY",flush=True); time.sleep(60)')
        with tempfile.TemporaryFile() as log:
            start = time.monotonic()
            result = subprocess.run(['timeout', '--kill-after=0.2s', '0.3s',
                                     sys.executable, '-B', '-c', script],
                                    stdout=log, stderr=log, timeout=3)
            self.assertLess(time.monotonic() - start, 3)
            self.assertIn(result.returncode, (137, -signal.SIGKILL))
            log.seek(0)
            self.assertIn(b'READY', log.read())

    def test_standalone_suite_bounds_the_entire_private_group(self):
        with patch.object(run_tests.subprocess, 'run', return_value=subprocess.CompletedProcess([], 124)) as call:
            self.assertEqual(run_tests.main(['discover', '-s', 'tests']), 124)
        argv = call.call_args.args[0]
        self.assertEqual(argv[:4], ['timeout', '--kill-after=2s', '180s', 'dbus-run-session'])
        self.assertEqual(call.call_args.kwargs['timeout'], 185)

    def test_recorder_system_bus_connection_success_error_and_timeout(self):
        for outcome in ('success', 'error', 'timeout'):
            with self.subTest(outcome=outcome):
                state = {}
                class BusError(Exception):
                    pass
                class Pending:
                    def cancel(self):
                        state['cancelled'] = True
                class Loop:
                    def run(self):
                        if outcome == 'timeout':
                            state['expire']()
                        else:
                            state['callback'](None, object(), None)
                    def quit(self):
                        state['quit'] = True
                class FakeGLib:
                    Error = BusError
                    MainLoop = Loop
                    @staticmethod
                    def timeout_add(milliseconds, callback):
                        state['milliseconds'] = milliseconds
                        state['expire'] = callback
                        return 42
                    @staticmethod
                    def source_remove(source):
                        state['removed'] = source
                class FakeGio:
                    Cancellable = Pending
                    class BusType:
                        SYSTEM = object()
                    @staticmethod
                    def bus_get(kind, cancellable, callback, data):
                        state['callback'] = callback
                    @staticmethod
                    def bus_get_finish(response):
                        if outcome == 'error':
                            raise BusError('restricted bus')
                        return 'private fixture'
                if outcome == 'success':
                    self.assertEqual(resume_probe.connect_system_bus(FakeGio, FakeGLib), 'private fixture')
                else:
                    with self.assertRaises(TimeoutError if outcome == 'timeout' else BusError):
                        resume_probe.connect_system_bus(FakeGio, FakeGLib)
                self.assertEqual(state['milliseconds'], 5000)
                self.assertTrue(state['quit'])
                if outcome == 'timeout':
                    self.assertTrue(state['cancelled'])
                    self.assertNotIn('removed', state)
                else:
                    self.assertEqual(state['removed'], 42)
