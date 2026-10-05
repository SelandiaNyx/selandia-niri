"""Power-state transitions never suspend, blank, or lock the actual desktop."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import sleep_guard as guard
import i18n


class SleepGuardTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)
        self.units = {key: {"ActiveState": "inactive", "LoadState": "loaded", "MainPID": "0"}
                      for key in ("idle", "awake")}
        unit = patch.object(guard, "_unit", side_effect=lambda key: self.units[key])
        unit.start()
        self.addCleanup(unit.stop)
        runner = patch.object(guard, "_run", return_value="active")
        self.run = runner.start()
        self.addCleanup(runner.stop)
        enabled = patch.object(guard, "timers_enabled", return_value=False)
        self.timers = enabled.start()
        self.addCleanup(enabled.stop)
        inhibit = patch.object(guard, "_has_inhibitor", return_value=False)
        self.inhibit = inhibit.start()
        self.addCleanup(inhibit.stop)
        service = patch.object(guard, "_service", side_effect=self.service)
        self.commands = service.start()
        self.addCleanup(service.stop)

    def service(self, unit, action):
        if action in ("start", "restart"):
            self.units[unit].update(ActiveState="active", MainPID="9876")
        elif action == "stop":
            self.units[unit].update(ActiveState="inactive", MainPID="0")

    def test_all_zero_timers_are_not_stay_awake(self):
        result = guard.status()
        self.assertFalse(result["awake"])
        self.assertFalse(result["error"])
        self.assertEqual(result["label"], "Timers disabled")
        self.inhibit.assert_not_called()

    def test_failed_timer_is_an_error_not_stay_awake(self):
        self.timers.return_value = True
        self.units["idle"]["ActiveState"] = "failed"
        result = guard.status()
        self.assertTrue(result["error"])
        self.assertFalse(result["awake"])

    def test_running_guard_requires_real_inhibitor(self):
        self.units["awake"].update(ActiveState="active", MainPID="9876")
        result = guard.status()
        self.assertFalse(result["awake"])
        self.assertTrue(result["error"])
        self.inhibit.return_value = True
        self.assertTrue(guard.status()["awake"])
        self.inhibit.assert_called_with(9876)

    def test_timer_reenable_starts_inactive_service(self):
        guard.apply_timers(True)
        self.assertEqual(self.units["idle"]["ActiveState"], "active")
        self.commands.assert_any_call("idle", "restart")

    def test_saving_timer_changes_keeps_explicit_guard(self):
        self.units["awake"]["ActiveState"] = "active"
        guard.apply_timers(True)
        self.commands.assert_called_once_with("idle", "stop")

    def test_all_zero_stops_timer_instead_of_starting_empty_swayidle(self):
        guard.apply_timers(False)
        self.commands.assert_called_once_with("idle", "stop")

    def test_enable_waits_for_inhibitor_before_stopping_timers(self):
        events = []
        self.commands.side_effect = lambda *args: (events.append(args), self.service(*args))[-1]
        self.inhibit.side_effect = lambda pid: (events.append(("inhibit", pid)), True)[-1]
        self.timers.return_value = True
        self.units["idle"]["ActiveState"] = "active"
        self.assertTrue(guard._set_awake(True)["awake"])
        self.assertLess(events.index(("inhibit", 9876)), events.index(("idle", "stop")))
        self.assertNotIn(("awake", "reset-failed"), events)

    def test_inhibitor_failure_does_not_stop_existing_timers(self):
        self.units["idle"]["ActiveState"] = "active"
        self.inhibit.side_effect = RuntimeError("Access denied")
        with self.assertRaisesRegex(RuntimeError, "Access denied"):
            guard._set_awake(True)
        self.assertEqual(self.units["idle"]["ActiveState"], "active")
        self.commands.assert_any_call("awake", "stop")
        self.assertNotIn(("idle", "stop"), [call.args for call in self.commands.call_args_list])

    def test_disable_guard_restores_only_configured_timers(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.timers.return_value = enabled
                self.units["awake"]["ActiveState"] = "active"
                result = guard._set_awake(False)
                self.assertFalse(result["awake"])
                self.assertEqual(self.units["idle"]["ActiveState"], "active" if enabled else "inactive")

    def test_timer_restore_failure_restores_guard(self):
        self.units["awake"]["ActiveState"] = "active"
        with patch.object(guard, "apply_timers", side_effect=RuntimeError("failed to start")):
            with self.assertRaisesRegex(RuntimeError, "failed to start"):
                guard._set_awake(False)
        self.assertEqual(self.units["awake"]["ActiveState"], "active")

    def test_nested_session_does_not_control_host_guard(self):
        self.run.return_value = "inactive"
        with self.assertRaises(RuntimeError):
            guard._set_awake(True)
        self.commands.assert_not_called()


class TimerConfigTests(unittest.TestCase):
    def test_only_active_positive_timeouts_enable_timers(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "swayidle").mkdir()
            (base / "swayidle/config").write_text("timeout 300 'lock'\n")
            self.assertTrue(guard.timers_enabled(base=base))
            managed = base / "swayidle/managed.conf"
            managed.write_text("# timeout 900 'systemctl suspend'\n")
            self.assertFalse(guard.timers_enabled(base=base))
            managed.write_text("timeout 0 'ignored'\n")
            self.assertFalse(guard.timers_enabled(base=base))
            managed.write_text("timeout 60 'lock'\n")
            self.assertTrue(guard.timers_enabled(base=base))
