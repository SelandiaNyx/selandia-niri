"""Brightness hardware and hotplug tests with fake sysfs; never changes a screen."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import i18n

spec = importlib.util.spec_from_file_location("brightness", Path(__file__).resolve().parents[1] / "niri/shell/brightness.py")
brightness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brightness)


class BrightnessTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sysfs, self.devices = self.root / "sys", self.root / "dev"
        self.devices.mkdir()
        for directory in ("class/drm", "class/backlight", "module/i2c_dev"):
            (self.sysfs / directory).mkdir(parents=True)
        for name, value in (("SYSFS", self.sysfs), ("DEVICES", self.devices)):
            patcher = patch.object(brightness, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(brightness.shutil, "which", return_value="/usr/bin/fake")
        patcher.start()
        self.addCleanup(patcher.stop)
        brightness._cache.clear()

    def display(self, output="DP-6", bus=29, connected=True, model="P275MV PLUS", serial=1):
        connector = self.sysfs / "class/drm" / f"card0-{output}"
        connector.mkdir(exist_ok=True)
        (connector / "status").write_text("connected" if connected else "disconnected")
        edid = bytearray(128)
        edid[12:16] = serial.to_bytes(4, "little")
        edid[54:59] = b"\x00\x00\x00\xfc\x00"
        edid[59:72] = model.encode("ascii").ljust(13, b" ")[:13]
        (connector / "edid").write_bytes(edid)
        if bus is not None:
            target = self.sysfs / "bus/i2c/devices" / f"i2c-{bus}"
            target.mkdir(parents=True, exist_ok=True)
            ddc = connector / "ddc"
            if ddc.is_symlink():
                ddc.unlink()
            ddc.symlink_to(target)
            (self.devices / f"i2c-{bus}").touch()
        return connector

    def backlight(self, current=40, maximum=200):
        path = self.sysfs / "class/backlight/intel_backlight"
        path.mkdir()
        (path / "brightness").write_text(str(current))
        (path / "max_brightness").write_text(str(maximum))
        return path

    def test_vcp_parser_rescales_real_monitor_range_and_preserves_zero(self):
        self.assertEqual(brightness.parse_vcp("warning\nVCP 10 C 0 255\n"), (0, 255))
        for response in ("VCP 10 ERR", "VCP 10 C 5 0", "VCP 10 C 256 255", "VCP 12 C 50 100", "garbage"):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                brightness.parse_vcp(response)

    def test_connected_connector_selects_exact_ddc_bus(self):
        self.display()
        self.display("DP-1", bus=8, connected=False)
        with patch.object(brightness, "_run", return_value="VCP 10 C 127 254") as run:
            state = brightness.read_state()
        self.assertEqual(len(state["devices"]), 1)
        device = state["devices"][0]
        self.assertEqual(device["label"], "P275MV PLUS · DP-6")
        self.assertEqual(device["percent"], 50)
        self.assertTrue(device["available"])
        self.assertEqual(device["output"], "DP-6")
        run.assert_called_once_with(["ddcutil", "--noconfig", "--bus", "29", "--brief", "getvcp", "10"])

    def test_read_cache_avoids_requery_and_does_not_leak_mutable_state(self):
        self.display()
        with patch.object(brightness, "_run", return_value="VCP 10 C 40 100") as run:
            state = brightness.read_state()
            state["devices"][0]["percent"] = 99
            again = brightness.read_state()
            self.assertEqual(again["devices"][0]["percent"], 40)
            run.assert_called_once()
            brightness.read_state(force=True)
            self.assertEqual(run.call_count, 2)

    def test_hotplug_and_bus_move_invalidate_cached_values(self):
        connector = self.display()
        with patch.object(brightness, "_run", return_value="VCP 10 C 100 100") as run:
            old = brightness.read_state()["devices"][0]
            self.display(bus=30)
            same = brightness.read_state()["devices"][0]
            self.assertEqual(same["id"], old["id"])
            self.assertEqual(same["bus"], 30)
            self.assertEqual(run.call_count, 2)
            (connector / "status").write_text("disconnected")
            self.assertEqual(brightness.read_state()["devices"], [])
            self.assertFalse(brightness._cache)

    def test_replaced_monitor_rejects_stale_selector_before_writing(self):
        self.display()
        identifier = brightness._discover()[0]["id"]
        self.display(serial=2)
        with patch.object(brightness, "_run") as run, self.assertRaisesRegex(RuntimeError, "replaced"):
            brightness.set_percent(identifier, 50)
        run.assert_not_called()

    def test_unavailable_returns_none_with_actionable_reason_not_false_zero(self):
        self.display()
        for error in ("enable DDC/CI", "Brightness request timed out"):
            with patch.object(brightness, "_run", side_effect=RuntimeError(error)):
                state = brightness.read_state(force=True)
            self.assertIsNone(state["devices"][0]["percent"])
            self.assertFalse(state["devices"][0]["available"])
            self.assertIn(error, state["reason"])

    def test_missing_package_bus_module_and_access_report_distinct_errors(self):
        self.display()
        with patch.object(brightness.shutil, "which", return_value=None):
            self.assertIn("control.sh repair", brightness.read_state(force=True)["reason"])
        with patch.object(brightness.os, "access", return_value=False):
            self.assertIn("No read/write access", brightness.read_state(force=True)["reason"])
        (self.devices / "i2c-29").unlink()
        self.assertIn("I²C", brightness.read_state(force=True)["reason"])
        (self.sysfs / "module/i2c_dev").rmdir()
        self.assertIn("modprobe i2c-dev", brightness.read_state(force=True)["reason"])

    def test_no_ddc_link_reports_connection_instead_of_scanning_other_buses(self):
        self.display(bus=None)
        with patch.object(brightness, "_run") as run:
            self.assertIn("No DDC bus", brightness.read_state()["reason"])
        run.assert_not_called()

    def test_ddc_set_scales_range_and_keeps_verification_enabled(self):
        self.display()
        identifier = brightness._discover()[0]["id"]
        with patch.object(brightness, "_run", side_effect=["VCP 10 C 0 200", ""]) as run:
            device = brightness.set_percent(identifier, 25)
        self.assertEqual(device["percent"], 25)
        self.assertEqual(device["current"], 50)
        self.assertEqual(run.call_args.args[0], ["ddcutil", "--noconfig", "--bus", "29", "--verify", "setvcp", "10", "50"])

    def test_hotplug_during_get_aborts_before_set(self):
        self.display()
        identifier = brightness._discover()[0]["id"]
        def change_connection(arguments):
            self.display(bus=31)
            return "VCP 10 C 50 100"
        with patch.object(brightness, "_run", side_effect=change_connection) as run:
            with self.assertRaisesRegex(RuntimeError, "connection changed"):
                brightness.set_percent(identifier, 40)
        self.assertEqual(run.call_count, 1)

    def test_invalid_values_never_access_hardware(self):
        with patch.object(brightness, "_run") as run:
            for value in (-1, 101, float("nan"), float("inf"), True, "50"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    brightness.set_percent("ddc:test", value)
        run.assert_not_called()

    def test_backlight_uses_real_range_and_absolute_device_selection(self):
        path = self.backlight()
        self.display("eDP-1", bus=9)
        state = brightness.read_state()
        self.assertEqual(len(state["devices"]), 1)
        self.assertEqual(state["devices"][0]["percent"], 20)
        def write(arguments):
            self.assertEqual(arguments, ["brightnessctl", "--class=backlight", "--device", "intel_backlight", "set", "100"])
            (path / "brightness").write_text("100")
            return ""
        with patch.object(brightness, "_run", side_effect=write):
            self.assertEqual(brightness.set_percent("backlight:intel_backlight", 50)["percent"], 50)

    def test_zero_backlight_is_valid_but_missing_values_are_unavailable(self):
        path = self.backlight(current=0)
        self.assertEqual(brightness.read_state()["devices"][0]["percent"], 0)
        (path / "max_brightness").write_text("0")
        self.assertIsNone(brightness.read_state(force=True)["devices"][0]["percent"])

    def test_keyboard_uses_focused_niri_output(self):
        self.display()
        self.display("HDMI-A-1", bus=23)
        with patch.object(brightness, "_run", return_value="VCP 10 C 98 100"), \
                patch.object(brightness, "_focused_output", return_value="HDMI-A-1"), \
                patch.object(brightness, "set_percent", return_value={}) as setter:
            brightness.step("up")
        self.assertIn("HDMI-A-1", setter.call_args.args[0])
        self.assertEqual(setter.call_args.args[1], 100)

    def test_keyboard_does_not_change_arbitrary_monitor_when_focus_unknown(self):
        self.display()
        self.display("HDMI-A-1", bus=23)
        with patch.object(brightness, "_run", return_value="VCP 10 C 50 100"), \
                patch.object(brightness, "_focused_output", return_value=""), \
                patch.object(brightness, "set_percent") as setter, \
                self.assertRaisesRegex(RuntimeError, "Select a monitor"):
            brightness.step("down")
        setter.assert_not_called()

    def test_timeout_and_failed_command_surface_as_errors(self):
        with patch.object(brightness.subprocess, "run", side_effect=subprocess.TimeoutExpired("ddcutil", 6)):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                brightness._run(["ddcutil"])
        result = subprocess.CompletedProcess([], 1, "", "I²C access denied")
        with patch.object(brightness.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "access denied"):
                brightness._run(["ddcutil"])


if __name__ == "__main__":
    unittest.main()
