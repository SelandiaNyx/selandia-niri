"""Exercise a fake readiness protocol; no real compositor or lock is touched.

The systemd manager is replaced by a small fake that runs the real
``lock_client.py`` as a separate process, so the request/record protocol, the
readiness handshake and the identity checks are the shipped ones.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import lock_client
import lock_session as locker


class FakeManager:
    """Emulate the parts of systemd this lock protocol depends on.

    Starting an already running unit is a no-op, exactly like ``systemctl
    start`` on an active unit.
    """

    def __init__(self, case):
        self.case = case
        self.clients = {}

    def start(self, key, timeout):
        existing = self.clients.get(key)
        if existing is not None and existing.poll() is None:
            return lambda: existing.poll() is not None
        process = subprocess.Popen([sys.executable, "-B", str(locker.CLIENT), key],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        self.clients[key] = process
        self.case.addCleanup(self.stop, process)
        return lambda: process.poll() is not None

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


class LockSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-lock-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        (self.base / "theme").mkdir()
        (self.base / "theme/swaylock.conf").write_text("color=000000\n")
        self.addCleanup(self.cleanup_children)
        environment = patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.base), WAYLAND_DISPLAY="test-wayland-1")
        environment.start()
        self.addCleanup(environment.stop)
        self.fake = self.base / "fake.py"
        self.fake.write_text('''import os, pathlib, sys, time
pathlib.Path('/proc/self/comm').write_text('swaylock')
pathlib.Path(os.environ['XDG_RUNTIME_DIR'], 'child-' + str(os.getpid())).write_text('')
fd = int(sys.argv[sys.argv.index('--ready-fd') + 1])
if os.environ.get('LOCK_PROBE_FAIL'):
    raise SystemExit(1)
os.write(fd, b'\\n')
os.close(fd)
time.sleep(30)
''')
        self.manager = FakeManager(self)

    def cleanup_children(self):
        for path in self.base.glob("child-*"):
            pid = int(path.name[6:])
            try:
                os.kill(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass

    def lock(self, launcher=None, **options):
        return locker.lock(base=self.base, timeout=2, locker=(sys.executable, str(self.fake)),
                           launcher=launcher or self.manager.start, **options)

    def test_ready_handshake_then_reuse_only_confirmed_process(self):
        first = self.lock()
        self.assertTrue(locker.confirmed(first, locker.display_identity()))
        second = self.lock()
        self.assertEqual(first, second)
        self.assertEqual(len(list(self.base.glob("child-*"))), 1)

    def test_another_display_gets_its_own_lock(self):
        first = self.lock()
        with patch.dict(os.environ, WAYLAND_DISPLAY="test-wayland-2"):
            self.assertFalse(locker.confirmed(first, locker.display_identity()))
            second = self.lock()
        self.assertNotEqual(first["pid"], second["pid"])
        self.assertEqual(len(list(self.base.glob("*.json"))), 2)

    def test_failure_before_ready_is_never_recorded_as_locked(self):
        with patch.dict(os.environ, LOCK_PROBE_FAIL="1"):
            with self.assertRaises(RuntimeError):
                self.lock()
        self.assertEqual(list(self.base.glob("*.json")), [])

    def test_stale_pid_or_start_time_cannot_confirm_lock(self):
        record = self.lock()
        stale = dict(record, start="0")
        self.assertFalse(locker.confirmed(stale, locker.display_identity()))
        os.kill(record["pid"], signal.SIGTERM)
        for _ in range(50):
            if not locker.confirmed(record, locker.display_identity()):
                break
            time.sleep(.05)
        self.assertFalse(locker.confirmed(record, locker.display_identity()))

    def test_successful_start_alone_never_confirms_the_lock(self):
        """A launcher that reports success without a locker must not pass."""
        with patch.object(locker, "tr", lambda english, chinese: english):
            with self.assertRaises(RuntimeError) as raised:
                self.lock(launcher=lambda key, timeout: None)
        self.assertIn("not confirmed", str(raised.exception))
        self.assertEqual(list(self.base.glob("*.json")), [])

    def test_missing_record_with_live_lock_refuses_to_double_lock(self):
        record = self.lock()
        for path in self.base.glob("*.json"):
            path.unlink()
        with self.assertRaises(RuntimeError):
            self.lock()
        # The confirmed locker was neither replaced nor killed.
        self.assertTrue(locker.process_identity(record["pid"]))
        self.assertEqual(len(list(self.base.glob("child-*"))), 1)

    def test_missing_wayland_display_is_rejected_before_launch(self):
        with patch.dict(os.environ, WAYLAND_DISPLAY=""), patch.object(locker.subprocess, "Popen") as popen:
            with self.assertRaises(RuntimeError):
                self.lock()
            popen.assert_not_called()

    def test_missing_lock_configuration_is_rejected_before_launch(self):
        (self.base / "theme/swaylock.conf").unlink()
        with self.assertRaises(RuntimeError):
            self.lock()
        self.assertEqual(list(self.base.glob("*.request")), [])

    def test_request_carries_the_session_and_no_other_variable(self):
        with patch.dict(os.environ, LD_PRELOAD="/tmp/evil.so"):
            self.lock()
        request = json.loads(next(self.base.glob("*.request")).read_text())
        self.assertEqual(request["environment"]["WAYLAND_DISPLAY"], "test-wayland-1")
        self.assertNotIn("LD_PRELOAD", request["environment"])
        self.assertEqual(request["timeout"], 2)


class LockerArgumentsTests(unittest.TestCase):
    def test_uses_generated_config_and_keeps_ready_fd(self):
        request = {"locker": ["swaylock"], "config": "/tmp/swaylock.conf"}
        arguments = lock_client.locker_arguments(request, 7)
        self.assertEqual(arguments, ["swaylock", "-C", "/tmp/swaylock.conf", "--ready-fd", "7"])
        self.assertNotIn("-f", arguments)
        self.assertEqual(int(arguments[-1]), 7)


class RequestTests(unittest.TestCase):
    def request(self, **overrides):
        base = {"version": 1, "display": "/run/wayland-0", "locker": ["swaylock"],
                "config": __file__, "timeout": 10, "environment": {"WAYLAND_DISPLAY": "wayland-0"}}
        base.update(overrides)
        return base

    def test_valid_request_is_accepted(self):
        self.assertEqual(lock_client.validate_request(self.request()), self.request())

    def test_rejects_unsupported_version(self):
        with self.assertRaises(ValueError):
            lock_client.validate_request(self.request(version=2))

    def test_rejects_missing_configuration(self):
        with self.assertRaises(ValueError):
            lock_client.validate_request(self.request(config="/nonexistent/swaylock.conf"))

    def test_rejects_empty_locker(self):
        with self.assertRaises(ValueError):
            lock_client.validate_request(self.request(locker=[]))

    def test_rejects_boolean_timeout(self):
        with self.assertRaises(ValueError):
            lock_client.validate_request(self.request(timeout=True))

    def test_rejects_environment_outside_the_session_whitelist(self):
        with self.assertRaises(ValueError):
            lock_client.validate_request(self.request(environment={"LD_PRELOAD": "/tmp/evil.so"}))

    def test_captures_only_session_variables(self):
        captured = locker.capture_environment({"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0",
                                               "PATH": "/usr/bin", "LD_PRELOAD": "/tmp/evil.so"})
        self.assertEqual(captured, {"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0"})


class IsolationSelectionTests(unittest.TestCase):
    def test_service_unit_is_distinguished_from_a_scope(self):
        self.assertTrue(locker.inside_service_unit(
            "0::/user.slice/user-1000.slice/user@1000.service/app.slice/selandia-niri@idle.service\n"))
        self.assertFalse(locker.inside_service_unit(
            "0::/user.slice/user-1000.slice/user@1000.service/app.slice/kitty-2047-0.scope\n"))

    def test_unknown_cgroup_refuses_the_direct_path(self):
        with patch.object(locker.Path, "read_text", side_effect=OSError("denied")):
            self.assertTrue(locker.inside_service_unit())

    def test_dedicated_unit_wins_over_the_component_template(self):
        seen = []

        def loaded(unit):
            seen.append(unit)
            return True

        start = locker.select_launcher("/run/user/1000", loaded=loaded, inside=False)
        self.assertEqual(seen[0], "selandia-lock@.service")
        with patch.object(locker, "_systemctl") as systemctl:
            systemctl.return_value = subprocess.CompletedProcess([], 0, "", "")
            start("abc123", 10)
        self.assertEqual(systemctl.call_args_list[-1].args[1], "selandia-lock@abc123.service")

    def test_component_template_is_used_until_the_dedicated_unit_is_deployed(self):
        start = locker.select_launcher("/run/user/1000",
                                       loaded=lambda unit: unit == "selandia-niri@.service", inside=True)
        with patch.object(locker, "_systemctl") as systemctl:
            systemctl.return_value = subprocess.CompletedProcess([], 0, "", "")
            start("abc123", 10)
        self.assertEqual(systemctl.call_args_list[-1].args[1], "selandia-niri@lock-abc123.service")

    def test_inside_a_service_without_any_unit_refuses_instead_of_degrading(self):
        with self.assertRaises(RuntimeError) as raised:
            locker.select_launcher("/run/user/1000", loaded=lambda unit: False, inside=True)
        self.assertIn("install.sh", str(raised.exception))

    def test_a_scope_falls_back_to_a_direct_client_when_no_manager_answers(self):
        with tempfile.TemporaryDirectory(prefix="selandia-lock-direct-") as runtime:
            start = locker.select_launcher(runtime, loaded=lambda unit: False, inside=False)
            with patch.object(locker.subprocess, "Popen") as popen:
                popen.return_value.poll.return_value = None
                failed = start("abc123", 10)
        arguments = popen.call_args.args[0]
        self.assertIn(str(locker.CLIENT), arguments)
        self.assertEqual(arguments[-1], "abc123")
        self.assertFalse(failed())

    def test_start_failure_is_reported_and_never_treated_as_a_lock(self):
        with patch.object(locker, "_systemctl") as systemctl:
            systemctl.return_value = subprocess.CompletedProcess([], 1, "", "Unit not found.")
            with self.assertRaises(RuntimeError) as failure:
                locker.systemd_launcher("selandia-lock@{key}.service")("abc123", 10)
        self.assertIn("Unit not found.", str(failure.exception))

    def test_failed_unit_is_reported_without_waiting_for_the_deadline(self):
        start = locker.systemd_launcher("selandia-lock@{key}.service")
        with patch.object(locker, "_systemctl") as systemctl:
            systemctl.return_value = subprocess.CompletedProcess([], 0, "", "")
            failed = start("abc123", 10)
            systemctl.return_value = subprocess.CompletedProcess([], 0, "", "")
            self.assertTrue(failed())


class CommandLineTests(unittest.TestCase):
    """The shipped CLI entry point, over a real process boundary."""

    def test_lock_command_confirms_a_record_or_refuses_an_unisolated_service(self):
        with tempfile.TemporaryDirectory(prefix="selandia-lock-cli-") as temporary:
            base = Path(temporary)
            (base / "bin").mkdir()
            (base / "theme").mkdir()
            (base / "theme/swaylock.conf").write_text("color=000000\n")
            fake = base / "fake.py"
            fake.write_text('''import os, pathlib, sys, time
pathlib.Path('/proc/self/comm').write_text('swaylock')
pathlib.Path(os.environ['XDG_RUNTIME_DIR'], 'child-' + str(os.getpid())).write_text('')
fd = int(sys.argv[sys.argv.index('--ready-fd') + 1])
os.write(fd, b'\\n')
os.close(fd)
time.sleep(20)
''')
            # No user manager answers, so the isolated services cannot be used.
            stub = base / "bin/systemctl"
            stub.write_text("#!/bin/sh\nexit 1\n")
            stub.chmod(0o755)
            environment = dict(os.environ, XDG_RUNTIME_DIR=str(base), WAYLAND_DISPLAY="cli-wayland-1",
                               PATH=str(base / "bin") + os.pathsep + os.environ["PATH"])
            result = subprocess.run([sys.executable, "-B", str(Path(locker.__file__)),
                                     "--locker", sys.executable, str(fake)],
                                    capture_output=True, text=True, timeout=40, env=environment)
            if result.returncode:
                # Only acceptable inside a systemd service, where a direct start
                # would recreate the defect this change removes.
                self.assertIn("install.sh", result.stderr)
                self.assertTrue(locker.inside_service_unit())
                return
            record = json.loads(next(base.glob("*.json")).read_text())
            self.assertTrue(locker.confirmed(record, record["display"]))
            for path in base.glob("child-*"):
                try:
                    os.kill(int(path.name[6:]), signal.SIGTERM)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    unittest.main()
