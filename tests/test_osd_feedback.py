"""OSD feedback for desktop volume and brightness actions.

The desktop script is copied into a private tree whose path contains spaces and
apostrophes.  Every command that could touch audio, notifications, brightness or
the compositor is a logging fake; only the real bash and dirname are available.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


class OsdFeedbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="osd feedback's ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "project with space's"
        self.base = self.root / "niri"
        self.bin = self.root / "bin"
        (self.base / "scripts").mkdir(parents=True)
        self.bin.mkdir()
        self.log = self.root / "calls.jsonl"
        self.desktop = self.base / "scripts/desktop"
        shutil.copy2(Path(__file__).resolve().parents[1] / "niri/scripts/desktop", self.desktop)
        for name in ("bash", "dirname"):
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ("wpctl", "notify-send", "python3"):
            self.fake(name)
        self.environment = {
            "PATH": str(self.bin),
            "HOME": str(self.root / "home"),
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEST_DESKTOP_CALLS": str(self.log),
        }

    def fake(self, name):
        path = self.bin / name
        path.write_text("#!" + sys.executable + "\n" + textwrap.dedent("""\
            import json, os, pathlib, sys

            name = pathlib.Path(sys.argv[0]).name
            with open(os.environ["TEST_DESKTOP_CALLS"], "a") as output:
                output.write(json.dumps([name, *sys.argv[1:]]) + "\\n")

            status = 0
            message = ""
            if name == "wpctl":
                status = int(os.environ.get("TEST_WPCTL_STATUS", "0"))
                if status == 0 and "get-volume" in sys.argv[1:]:
                    message = os.environ.get("TEST_WPCTL_OUTPUT", "Volume: 0.60 [MUTED]")
            elif name == "notify-send":
                status = int(os.environ.get("TEST_NOTIFY_STATUS", "0"))
            elif name == "python3":
                script = pathlib.Path(sys.argv[2]).name if len(sys.argv) > 2 else ""
                if script == "island.py":
                    mode = sys.argv[4] if len(sys.argv) > 4 else ""
                    status = int(os.environ.get("TEST_ISLAND_" + mode.upper() + "_STATUS", "0"))
                elif script == "brightness.py":
                    status = int(os.environ.get("TEST_BRIGHTNESS_STATUS", "0"))
                    message = os.environ.get("TEST_BRIGHTNESS_OUTPUT", "")
            if message:
                print(message)
            sys.exit(status)
            """))
        path.chmod(0o755)

    def invoke(self, *arguments, **environment):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(
            [str(self.bin / "bash"), str(self.desktop), *arguments],
            env={**self.environment, **environment},
            capture_output=True, text=True, timeout=5)
        calls = ([json.loads(line) for line in self.log.read_text().splitlines()]
                 if self.log.exists() else [])
        return result, calls

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def island(self, mode):
        return ["python3", "-B", str(self.base / "shell/island.py"), "show", mode]

    def brightness(self, direction):
        return ["python3", "-B", str(self.base / "shell/brightness.py"), "step", direction]

    def notifications(self, calls):
        return [call for call in calls if call[0] == "notify-send"]

    def test_sink_volume_uses_wpctl_then_osd_and_skips_duplicate_feedback(self):
        mutations = {
            "up": ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"],
            "down": ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
            "mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
        }
        for action, mutation in mutations.items():
            with self.subTest(action=action):
                result, calls = self.invoke("volume", action, TEST_ISLAND_VOLUME_STATUS="0")
                self.assert_success(result)
                self.assertEqual(calls, [mutation, self.island("volume")])
                self.assertFalse(any("get-volume" in call for call in calls))
                self.assertEqual(self.notifications(calls), [])

    def test_sink_volume_osd_failure_falls_back_to_one_notification(self):
        mutations = {
            "up": ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"],
            "down": ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
            "mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
        }
        for action, mutation in mutations.items():
            with self.subTest(action=action):
                result, calls = self.invoke(
                    "volume", action,
                    TEST_ISLAND_VOLUME_STATUS="1",
                    TEST_WPCTL_OUTPUT="Volume: 0.50 [MUTED]")
                self.assert_success(result)
                self.assertEqual(calls[:3], [
                    mutation,
                    self.island("volume"),
                    ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                ])
                notifications = self.notifications(calls)
                self.assertEqual(len(notifications), 1)
                self.assertTrue(any("[MUTED]" in argument for argument in notifications[0]))

    def test_microphone_uses_source_and_its_own_replacement_notification(self):
        result, calls = self.invoke("volume", "mic", TEST_ISLAND_VOLUME_STATUS="0")
        self.assert_success(result)
        self.assertEqual(calls[:2], [
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
        ])
        notifications = self.notifications(calls)
        self.assertEqual(len(notifications), 1)
        self.assertIn("Microphone", notifications[0])
        self.assertIn("string:x-canonical-private-synchronous:microphone", notifications[0])
        self.assertFalse(any("@DEFAULT_AUDIO_SINK@" in argument
                             for call in calls for argument in call))
        self.assertFalse(any("island.py" in argument
                             for call in calls for argument in call))

    def test_brightness_osd_success_suppresses_the_notification(self):
        for direction in ("up", "down"):
            with self.subTest(direction=direction):
                result, calls = self.invoke(
                    "brightness", direction,
                    TEST_BRIGHTNESS_OUTPUT="55", TEST_ISLAND_BRIGHTNESS_STATUS="0")
                self.assert_success(result)
                self.assertEqual(calls, [self.brightness(direction), self.island("brightness")])
                self.assertEqual(self.notifications(calls), [])

    def test_brightness_osd_failure_notifies_the_returned_step_value(self):
        for direction in ("up", "down"):
            with self.subTest(direction=direction):
                result, calls = self.invoke(
                    "brightness", direction,
                    TEST_BRIGHTNESS_OUTPUT="61", TEST_ISLAND_BRIGHTNESS_STATUS="1")
                self.assert_success(result)
                self.assertEqual(calls[:2], [self.brightness(direction), self.island("brightness")])
                notifications = self.notifications(calls)
                self.assertEqual(len(notifications), 1)
                self.assertIn("Brightness", notifications[0])
                self.assertTrue(any("61" in argument for argument in notifications[0]))

    def test_brightness_command_failure_reports_unavailable_without_osd(self):
        for direction in ("up", "down"):
            with self.subTest(direction=direction):
                result, calls = self.invoke(
                    "brightness", direction,
                    TEST_BRIGHTNESS_STATUS="1",
                    TEST_BRIGHTNESS_OUTPUT="backlight device not found")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls[0], self.brightness(direction))
                notifications = self.notifications(calls)
                self.assertEqual(len(notifications), 1)
                self.assertIn("Brightness unavailable", notifications[0])
                self.assertTrue(any("backlight device not found" in argument
                                    for argument in notifications[0]))
                self.assertNotIn(self.island("brightness"), calls)

    def test_invalid_arguments_never_change_a_device(self):
        for arguments in (("volume",), ("volume", "sideways"),
                          ("brightness",), ("brightness", "sideways"),
                          ("nonsense",)):
            with self.subTest(arguments=arguments):
                result, calls = self.invoke(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(
                    call[0] == "wpctl" and len(call) > 1 and "set-" in call[1]
                    for call in calls))
                self.assertFalse(any("brightness.py" in argument
                                     for call in calls for argument in call))
                self.assertFalse(any("island.py" in argument
                                     for call in calls for argument in call))

    def test_failed_wpctl_mutation_does_not_request_or_show_success_feedback(self):
        for action in ("up", "down", "mute", "mic"):
            with self.subTest(action=action):
                result, calls = self.invoke(
                    "volume", action,
                    TEST_WPCTL_STATUS="1", TEST_ISLAND_VOLUME_STATUS="0")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls[0][0], "wpctl")
                self.assertIn("set-", calls[0][1])
                self.assertFalse(any("island.py" in argument
                                     for call in calls for argument in call))
                self.assertEqual(self.notifications(calls), [])


if __name__ == "__main__":
    unittest.main()
