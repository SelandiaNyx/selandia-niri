"""Native display regression tests; hardware is never changed by this suite."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "niri/shell/display_backend.py"
sys.path.insert(0, str(MODULE.parent))
import i18n

spec = importlib.util.spec_from_file_location("display_backend", MODULE)
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)

RAW = {"DP-6": {"name": "DP-6", "make": "Example", "model": "Display",
                "modes": [{"width": 3840, "height": 2160, "refresh_rate": 160000, "is_preferred": True},
                          {"width": 1920, "height": 1080, "refresh_rate": 60000},
                          {"width": 1920, "height": 1080, "refresh_rate": 59940},
                          {"width": 1920, "height": 1080, "refresh_rate": 60000}],
                "current_mode": 0, "logical": {"x": -100, "y": 20, "scale": 1.5, "transform": "Normal"},
                "vrr_supported": True, "vrr_enabled": False}}
VALUES = {"mode": "1920x1080@60", "scale": 1.0, "max_bpc": None, "transform": "normal", "x": 0, "y": 0, "vrr": False}


class NativeDisplayTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / "niri"
        self.state = self.root / "state"
        (self.base / "conf").mkdir(parents=True)
        self.target = self.base / display.GENERATED
        self.target.write_text(display.render_settings({}))
        (self.base / "config.kdl").write_text('include "conf/display-settings.kdl"\ninclude "monitor.kdl"\n')
        (self.base / "monitor.kdl").write_text('// Keep arbitrary user defaults untouched.\noutput "DP-6" { mode "3840x2160@160"; scale 1.5; }\n')
        self.patch_base = patch.object(display, "BASE", self.base)
        self.patch_state = patch.object(display, "_state_dir", return_value=self.state)
        self.patch_base.start()
        self.patch_state.start()
        self.addCleanup(self.patch_base.stop)
        self.addCleanup(self.patch_state.stop)
        self.command_calls = []
        self.runner = patch.object(display, "_run", side_effect=self.run_niri)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.watch = patch.object(display, "_spawn_watchdog")
        self.watch_mock = self.watch.start()
        self.addCleanup(self.watch.stop)

    def run_niri(self, *args):
        self.command_calls.append(args)
        return json.dumps(RAW) if args == ("msg", "--json", "outputs") else ""

    def begin(self, **changes):
        return display.begin_apply("DP-6", {**VALUES, **changes})

    def test_live_modes_keep_exact_millihertz_and_deduplicate(self):
        output = display.read_outputs()[0]
        self.assertEqual([mode["mode"] for mode in output["modes"]], ["3840x2160@160", "1920x1080@60", "1920x1080@59.94"])
        self.assertEqual(output["current"]["mode"], "3840x2160@160")
        self.assertEqual(output["current"]["scale"], 1.5)
        self.assertEqual(output["current"]["transform"], "normal")

    def test_disabled_outputs_and_transform_values(self):
        raw = copy.deepcopy(RAW)
        raw["DP-6"]["current_mode"] = None
        with patch.object(display, "_run", return_value=json.dumps(raw)):
            self.assertIsNone(display.read_outputs()[0]["current"])
        self.assertEqual(display._transform("Flipped90"), "flipped-90")

    def test_malformed_output_data_is_reported(self):
        for raw in ("invalid", "[]", '{"DP-6": 3}', '{"DP-6":{"name":"bad\nname"}}'):
            with self.subTest(raw=raw), patch.object(display, "_run", return_value=raw):
                with self.assertRaises(RuntimeError):
                    display.read_outputs()

    def test_read_state_exposes_saved_and_pending_without_writing(self):
        state = display.read_state()
        self.assertFalse(self.state.exists())
        self.assertEqual(state["saved"], {})
        self.assertIsNone(state["pending"])
        token = self.begin()
        state = display.read_state()
        self.assertEqual(state["pending"]["token"], token)
        self.assertEqual(state["pending"]["output"], "DP-6")
        self.assertNotIn("previous_contents", state["pending"])

    def test_common_mode_formats_normalize_and_missing_hz_selects_highest(self):
        for value in ("1920*1080@60Hz", "1920×1080@60.000", "1920X1080@60"):
            self.assertEqual(display.validate_settings({**VALUES, "mode": value})["mode"], VALUES["mode"])
        token = self.begin(mode="1920x1080")
        self.assertTrue(display.confirm(token))
        self.assertEqual(display._saved()["DP-6"]["mode"], "1920x1080@60")

    def test_invalid_parameters_never_write_or_start_watchdog(self):
        bad = [("mode", '1920x1080@60"; off'), ("mode", "0x1080@60"), ("mode", "1920x1080@0"),
               ("scale", float("nan")), ("scale", True), ("scale", 0), ("scale", 10),
               ("max_bpc", 9), ("max_bpc", True), ("x", 1.5), ("y", 999999),
               ("vrr", "true"), ("transform", 'normal"')]
        before = self.target.read_text()
        for key, value in bad:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.begin(**{key: value})
        self.watch_mock.assert_not_called()
        self.assertEqual(self.target.read_text(), before)
        self.assertFalse(self.state.exists())

    def test_unsupported_modes_and_disconnected_output_rejected(self):
        with self.assertRaisesRegex(ValueError, "not reported"):
            self.begin(mode="1920x1080@61")
        with self.assertRaisesRegex(ValueError, "connected"):
            display.begin_apply("HDMI-A-9", VALUES)
        with self.assertRaises(ValueError):
            display.begin_apply('--bad', VALUES)
        self.watch_mock.assert_not_called()

    def test_unsupported_bpc_and_vrr_cannot_change_config(self):
        with patch.object(display, "max_bpc_supported", return_value=False), self.assertRaisesRegex(ValueError, "upgrade"):
            self.begin(max_bpc=10)
        outputs = display.read_outputs()
        outputs[0]["vrr_supported"] = False
        with patch.object(display, "read_outputs", return_value=outputs), self.assertRaisesRegex(ValueError, "VRR"):
            self.begin(vrr=True)
        self.watch_mock.assert_not_called()

    def test_preview_preserves_user_config_and_does_not_save_until_confirmed(self):
        original = (self.base / "monitor.kdl").read_bytes()
        token = self.begin()
        self.assertIn('mode "1920x1080@60"', self.target.read_text())
        self.assertEqual((self.base / "monitor.kdl").read_bytes(), original)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertEqual(len(token), 32)
        self.watch_mock.assert_called_once_with(token)
        self.assertIn(("msg", "action", "load-config-file"), self.command_calls)
        self.assertTrue(display.confirm(token))
        self.assertEqual(display._saved()["DP-6"], VALUES)
        self.assertFalse((self.state / "pending.json").exists())
        self.assertFalse(display.confirm(token))

    def test_revert_restores_file_and_original_temporary_runtime(self):
        old = self.target.read_text()
        token = self.begin()
        self.assertTrue(display.revert(token))
        self.assertEqual(self.target.read_text(), old)
        self.assertFalse((self.state / "settings.json").exists())
        self.assertIn(("msg", "output", "DP-6", "mode", "3840x2160@160"), self.command_calls)
        self.assertIn(("msg", "output", "DP-6", "position", "set", "--", "-100", "20"), self.command_calls)
        self.assertFalse(display.revert(token))

    def test_no_runtime_commands_sent_into_a_different_niri_session(self):
        with patch.dict(os.environ, {"NIRI_SOCKET": "/old-session"}):
            token = self.begin()
        self.command_calls.clear()
        with patch.dict(os.environ, {"NIRI_SOCKET": "/other-session"}):
            display.revert(token)
        self.assertEqual(self.command_calls, [])

    def test_second_apply_blocks_until_first_is_handled(self):
        token = self.begin()
        with self.assertRaisesRegex(RuntimeError, "previous preview"):
            self.begin(scale=1.25)
        self.assertEqual(display.read_state()["pending"]["token"], token)

    def test_wrong_token_does_not_cancel_another_preview(self):
        token = self.begin()
        self.assertFalse(display.revert("wrong"))
        self.assertFalse(display.confirm("wrong"))
        self.assertEqual(display.read_state()["pending"]["token"], token)

    def test_expired_confirm_reverts_instead_of_saving(self):
        original = self.target.read_text()
        token = self.begin()
        with patch.object(display.time, "time", return_value=time.time() + 30):
            self.assertFalse(display.confirm(token))
        self.assertEqual(self.target.read_text(), original)
        self.assertFalse((self.state / "settings.json").exists())

    def test_subsequent_apply_recovers_a_stale_pending_preview(self):
        self.begin()
        with patch.object(display.time, "time", return_value=time.time() + 30):
            token = self.begin(scale=1.25)
        self.assertEqual(display.read_state()["pending"]["token"], token)
        self.assertIn("scale 1.25", self.target.read_text())

    def test_failed_validation_never_reaches_live_file(self):
        original = self.target.read_text()
        with patch.object(display, "_validate_config", side_effect=RuntimeError("invalid configuration")), self.assertRaises(RuntimeError):
            self.begin()
        self.assertEqual(self.target.read_text(), original)
        self.watch_mock.assert_not_called()
        self.assertFalse((self.state / "pending.json").exists())

    def test_watchdog_failure_leaves_original_file_intact(self):
        original = self.target.read_text()
        self.watch_mock.side_effect = RuntimeError("timer failed")
        with self.assertRaisesRegex(RuntimeError, "timer failed"):
            self.begin()
        self.assertEqual(self.target.read_text(), original)
        self.assertFalse((self.state / "pending.json").exists())

    def test_reload_failure_rolls_back_without_confirming(self):
        original = self.target.read_text()
        def run(*args):
            if args == ("msg", "action", "load-config-file"):
                raise RuntimeError("reload failed")
            return self.run_niri(*args)
        with patch.object(display, "_run", side_effect=run), self.assertRaisesRegex(RuntimeError, "reload failed"):
            self.begin()
        self.assertEqual(self.target.read_text(), original)
        self.assertFalse((self.state / "pending.json").exists())

    def test_manual_edits_are_not_clobbered_before_or_after_apply(self):
        self.target.write_text("// Personal edit\n")
        with self.assertRaisesRegex(RuntimeError, "edited"):
            self.begin()
        self.assertEqual(self.target.read_text(), "// Personal edit\n")
        self.target.write_text(display.render_settings({}))
        token = self.begin()
        self.target.write_text("// New concurrent edit\n")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            display.confirm(token)
        with self.assertRaisesRegex(RuntimeError, "preserved"):
            display.revert(token)
        self.assertEqual(self.target.read_text(), "// New concurrent edit\n")

    def test_edit_while_validation_runs_is_preserved(self):
        def edited(_):
            self.target.write_text("// edited during validation\n")
        with patch.object(display, "_validate_config", side_effect=edited), self.assertRaisesRegex(RuntimeError, "validation"):
            self.begin()
        self.assertEqual(self.target.read_text(), "// edited during validation\n")

    def test_symlink_target_is_rejected(self):
        outside = self.root / "personal.kdl"
        outside.write_text("untouched")
        self.target.unlink()
        self.target.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, "replaced"):
            self.begin()
        self.assertEqual(outside.read_text(), "untouched")

    def test_confirm_retains_other_outputs(self):
        saved = {"HDMI-A-1": {**VALUES, "x": 1920}}
        display._write_json(self.state / "settings.json", {"version": 1, "outputs": saved})
        self.target.write_text(display.render_settings(saved))
        display.confirm(self.begin())
        self.assertEqual(display._saved()["HDMI-A-1"], saved["HDMI-A-1"])
        self.assertIn('output "HDMI-A-1"', self.target.read_text())

    def test_validation_requires_first_include_due_to_niri_first_match(self):
        (self.base / "config.kdl").write_text('include "monitor.kdl"\ninclude "conf/display-settings.kdl"\n')
        with self.assertRaisesRegex(RuntimeError, "first"):
            self.begin()
        self.watch_mock.assert_not_called()

    def test_committed_journal_completes_saved_state_after_interrupted_confirm(self):
        token = self.begin()
        journal = display._read_json(self.state / "pending.json")
        journal["phase"] = "confirmed"
        display._write_json(self.state / "pending.json", journal)
        self.assertFalse(display.revert(token))
        self.assertEqual(display._saved()["DP-6"], VALUES)

    @unittest.skipUnless(shutil.which("niri"), "niri validation is unavailable")
    def test_rendered_full_config_validates_with_actual_niri_without_hardware_changes(self):
        self.runner.stop()
        display._validate_config(display.render_settings({"DP-6": {**VALUES, "vrr": True, "transform": "flipped-90", "x": -1920}}))
        # The depth probe uses a temporary config only, never IPC or a live file.
        self.assertIsInstance(display.max_bpc_supported(), bool)

    def test_detached_watchdog_reverts_after_its_parent_exits(self):
        token = self.begin()
        pending = display._read_json(self.state / "pending.json")
        pending["deadline"] = time.time() + 0.7
        pending["socket"] = "/nonexistent-test-session"
        display._write_json(self.state / "pending.json", pending)
        # A separate short-lived parent starts the real detached helper.
        script = """import importlib.util, pathlib, sys
s=importlib.util.spec_from_file_location('display_backend',sys.argv[1])
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
m.BASE=pathlib.Path(sys.argv[2]); m._state_dir=lambda:pathlib.Path(sys.argv[3])
m._spawn_watchdog(sys.argv[4])
"""
        result = subprocess.run([sys.executable, "-B", "-c", script, str(MODULE), str(self.base), str(self.state), token],
                                capture_output=True, text=True, timeout=5, env={**os.environ, "NIRI_SOCKET": "/different-test-session"})
        self.assertEqual(result.returncode, 0, result.stderr)
        limit = time.monotonic() + 4
        while (self.state / "pending.json").exists() and time.monotonic() < limit:
            time.sleep(0.05)
        self.assertFalse((self.state / "pending.json").exists())
        self.assertEqual(self.target.read_text(), display.render_settings({}))


if __name__ == "__main__":
    unittest.main()
