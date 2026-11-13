"""One sleep entry point for the power menu and the automatic timer (audit A6).

The module runs with doubles for the lock, the inhibitor probe and the
subprocess runner: no real lock, sleep or hardware action happens. The four
required cases are guard on, lock failure, suspend failure and success.
"""
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import power_actions


def guard_state(**overrides):
    state = {"awake": False, "available": True, "error": False, "timers_enabled": True}
    state.update(overrides)
    return lambda: state


class EnglishMessages:
    """Assert on stable text: the spoken language depends on the host."""

    def setUp(self):
        patcher = patch.object(power_actions, "tr", side_effect=lambda english, chinese: english)
        patcher.start()
        self.addCleanup(patcher.stop)


class Recorder:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result if result is not None else subprocess.CompletedProcess([], 0, "", "")
        self.error = error

    def __call__(self, *arguments, **options):
        self.calls.append((arguments, options))
        if self.error:
            raise self.error
        return self.result


class SuspendTests(EnglishMessages, unittest.TestCase):
    def test_slow_lock_never_releases_project_sleep_request_early(self):
        entered, ready = threading.Event(), threading.Event()
        run = Recorder()
        errors = []
        def lock():
            entered.set()
            if not ready.wait(3):
                raise RuntimeError("test lock timeout")
        def worker():
            try:
                power_actions.suspend(status=guard_state(), lock=lock, run=run)
            except Exception as error:
                errors.append(error)
        process = threading.Thread(target=worker)
        process.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(run.calls, [])
        finally:
            ready.set()
            process.join(3)
        self.assertFalse(process.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(run.calls[0][0][0], ["systemctl", "suspend"])

    def test_documented_external_and_lid_limits_match_shipped_mechanisms(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text()
        for restriction in ("InhibitDelayMaxSec", "LidSwitchIgnoreInhibited=yes", "cannot cancel an external request"):
            self.assertIn(restriction, readme)
        sleep = (root / "niri/swayidle/sleep.conf").read_text()
        components = (root / "niri/scripts/components").read_text()
        self.assertIn("before-sleep", sleep)
        self.assertIn('swayidle -w -C "$base/swayidle/sleep.conf"', components)
        self.assertIn("--what=idle:sleep", components)
        self.assertNotIn("--what=handle-lid-switch", components)

    def test_stay_awake_refuses_before_anything_is_locked_or_suspended(self):
        lock = Recorder()
        run = Recorder()
        with self.assertRaises(power_actions.SleepRefused) as raised:
            power_actions.suspend(status=guard_state(awake=True), lock=lock, run=run)
        self.assertIn("Stay awake", str(raised.exception))
        self.assertEqual(lock.calls, [], "a blocked sleep must not lock the screen first")
        self.assertEqual(run.calls, [], "a blocked sleep must not reach systemctl")

    def test_unreadable_guard_state_refuses_instead_of_guessing(self):
        def broken():
            raise RuntimeError("systemctl is unavailable")

        lock = Recorder()
        run = Recorder()
        with self.assertRaises(power_actions.SleepRefused) as raised:
            power_actions.suspend(status=broken, lock=lock, run=run)
        self.assertIn("could not be read", str(raised.exception))
        self.assertEqual(lock.calls, [])
        self.assertEqual(run.calls, [])

    def test_lock_failure_stops_before_suspend(self):
        def broken_lock():
            raise RuntimeError("lock was not confirmed")

        run = Recorder()
        with self.assertRaises(RuntimeError) as raised:
            power_actions.suspend(status=guard_state(), lock=broken_lock, run=run)
        self.assertIn("lock was not confirmed", str(raised.exception))
        self.assertEqual(run.calls, [], "suspend must never follow an unconfirmed lock")

    def test_suspend_failure_is_reported_with_the_system_reason(self):
        lock = Recorder()
        run = Recorder(subprocess.CompletedProcess([], 1, "", "Sleep is inhibited by Selandia Niri"))
        with self.assertRaises(RuntimeError) as raised:
            power_actions.suspend(status=guard_state(), lock=lock, run=run)
        self.assertIn("Sleep is inhibited by Selandia Niri", str(raised.exception))
        self.assertEqual(len(lock.calls), 1, "the screen is already locked when suspend fails")

    def test_success_locks_then_requests_suspend_without_bypass_flags(self):
        lock_calls = []
        run_calls = []

        def fake_lock():
            lock_calls.append("lock")

        def fake_run(arguments, **options):
            run_calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, "", "")

        message = power_actions.suspend(status=guard_state(), lock=fake_lock, run=fake_run)
        self.assertTrue(message)
        self.assertEqual(lock_calls, ["lock"])
        self.assertEqual(run_calls[0][0], ["systemctl", "suspend"])
        for forbidden in ("--ignore-inhibitors", "-i", "--force"):
            self.assertNotIn(forbidden, run_calls[0][0])

    def test_order_is_lock_before_suspend(self):
        order = []

        def fake_lock():
            order.append("lock")

        def fake_run(arguments, **options):
            order.append("suspend")
            return subprocess.CompletedProcess(arguments, 0, "", "")

        power_actions.suspend(status=guard_state(), lock=fake_lock, run=fake_run)
        self.assertEqual(order, ["lock", "suspend"])


class BlockedReasonTests(EnglishMessages, unittest.TestCase):
    def test_allows_sleep_when_timers_report_an_error_but_nothing_blocks(self):
        self.assertIsNone(power_actions.blocked_reason(status=guard_state(error=True)))

    def test_reports_stay_awake(self):
        reason = power_actions.blocked_reason(status=guard_state(awake=True))
        self.assertIn("Stay awake", reason)

    def test_reports_an_unreadable_state(self):
        def broken():
            raise RuntimeError("no user manager")

        self.assertIn("no user manager", power_actions.blocked_reason(status=broken))


class CommandLineTests(EnglishMessages, unittest.TestCase):
    def test_blocked_exit_code_describes_the_sleep_decision(self):
        with patch.object(power_actions, "blocked_reason", return_value="blocked"):
            self.assertEqual(power_actions.main(["blocked"]), 0)
        with patch.object(power_actions, "blocked_reason", return_value=None):
            self.assertEqual(power_actions.main(["blocked"]), 1)

    def test_suspend_reports_failure_with_a_nonzero_status(self):
        def refused():
            raise power_actions.SleepRefused("blocked by Stay awake")

        with patch.object(power_actions, "suspend", refused):
            self.assertEqual(power_actions.main(["suspend"]), 1)

    def test_unknown_mode_is_a_usage_error(self):
        self.assertEqual(power_actions.main(["dance"]), 2)


if __name__ == "__main__":
    unittest.main()
