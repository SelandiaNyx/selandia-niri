"""Exercise repeated Apply and failed-unit recovery without the user's services."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
SPEC = importlib.util.spec_from_file_location("reload_components", ROOT / "niri/shell/reload_components.py")
reload = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reload)
import i18n


class ReloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-reload-")
        self.addCleanup(temporary.cleanup)
        self.environment = patch.dict(os.environ, {"XDG_STATE_HOME": temporary.name, "LC_ALL": "C.UTF-8"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.calls = []
        self.states = {"notifications": "active", "waybar": "active"}
        self.failures = set()
        self.masked = set()
        self.css = patch.object(reload, "validate_css")
        self.css_mock = self.css.start()
        self.addCleanup(self.css.stop)
        runner = patch.object(reload, "run", side_effect=self.run_command)
        runner.start()
        self.addCleanup(runner.stop)

    def run_command(self, arguments, **_kwargs):
        self.calls.append(arguments)
        if arguments[0] in self.failures or tuple(arguments) in self.failures:
            raise RuntimeError("simulated failure")
        if arguments[0] == "systemctl":
            unit = arguments[-1].removeprefix("selandia-niri@").removesuffix(".service")
            if "show" in arguments:
                if "--property=UnitFileState" in arguments:
                    return "masked" if unit in self.masked else "static"
                return self.states.get(unit, "inactive")
            if "start" in arguments or "restart" in arguments:
                self.states[unit] = "active"
        return ""

    def test_repeated_theme_apply_restarts_only_the_managed_bar_without_signals(self):
        for _ in range(12):
            reload.reload_components()
        mutations = [call for call in self.calls
                     if any(action in call for action in ("restart", "start", "reset-failed", "kill"))]
        self.assertEqual(mutations, [
            ["systemctl", "--user", "reset-failed", "selandia-niri@waybar.service"],
            ["systemctl", "--user", "restart", "selandia-niri@waybar.service"],
        ] * 12)
        self.assertFalse(any("--signal=SIGUSR2" in call for call in self.calls))
        self.assertEqual(self.calls.count(["swaync-client", "--skip-wait", "--reload-css"]), 12)
        self.assertNotIn(["swaync-client", "--skip-wait", "--reload-config"], self.calls)

    def test_intentionally_disabled_components_stay_disabled(self):
        self.masked = {"notifications", "waybar"}
        self.states = {"notifications": "inactive", "waybar": "inactive"}
        reload.reload_components()
        self.assertFalse(any(action in call for call in self.calls
                             for action in ("start", "restart", "kill", "reset-failed")))
        self.assertFalse(any(call[0] == "swaync-client" for call in self.calls))

    def test_failed_services_clear_start_limits_and_start_notifications_first(self):
        self.states = {"notifications": "failed", "waybar": "failed"}
        reload.reload_components()
        mutations = [call for call in self.calls if "start" in call or "reset-failed" in call]
        self.assertEqual(mutations, [
            ["systemctl", "--user", "reset-failed", "selandia-niri@notifications.service"],
            ["systemctl", "--user", "start", "selandia-niri@notifications.service"],
            ["systemctl", "--user", "reset-failed", "selandia-niri@waybar.service"],
            ["systemctl", "--user", "start", "selandia-niri@waybar.service"],
        ])
        self.assertEqual(self.states, {"notifications": "active", "waybar": "active"})

    def test_notification_failure_still_recovers_bar_and_is_reported(self):
        self.states["waybar"] = "failed"
        self.failures.add("gdbus")
        with self.assertRaisesRegex(RuntimeError, "Notifications"):
            reload.reload_components()
        self.assertEqual(self.states["waybar"], "active")
        self.assertFalse(any(call[0] == "swaync-client" for call in self.calls))

    def test_restart_failure_is_not_reported_as_success(self):
        self.failures.add(("systemctl", "--user", "restart",
                           "selandia-niri@waybar.service"))
        with self.assertRaisesRegex(RuntimeError, "Status bar"):
            reload.reload_components()
        self.assertFalse(any("start" in call for call in self.calls))

    def test_reset_failure_does_not_submit_a_restart(self):
        self.failures.add(("systemctl", "--user", "reset-failed", "selandia-niri@waybar.service"))
        with self.assertRaisesRegex(RuntimeError, "Status bar"):
            reload.reload_components()
        self.assertFalse(any("restart" in call for call in self.calls))

    def test_inactive_bar_after_restart_is_reported(self):
        original = self.run_command
        def inactive_after_restart(arguments, **kwargs):
            result = original(arguments, **kwargs)
            if "restart" in arguments:
                self.states["waybar"] = "failed"
            return result
        with patch.object(reload, "run", side_effect=inactive_after_restart):
            with self.assertRaisesRegex(RuntimeError, "Service did not start"):
                reload.reload_components()

    def test_bad_css_does_not_touch_any_service(self):
        self.css_mock.side_effect = RuntimeError("invalid stylesheet")
        with self.assertRaisesRegex(RuntimeError, "invalid stylesheet"):
            reload.reload_components()
        self.assertEqual(self.calls, [])

    def test_full_reload_updates_notification_configuration_and_wallpaper(self):
        reload.reload_components(full=True)
        self.assertIn(["swaync-client", "--skip-wait", "--reload-config"], self.calls)
        self.assertIn(["systemctl", "--user", "restart", "selandia-niri@wallpaper.service"], self.calls)
        self.assertFalse(any("restart" in call and call[-1] not in
                             ("selandia-niri@waybar.service", "selandia-niri@wallpaper.service")
                             for call in self.calls))

    def test_concurrent_apply_calls_are_serialized_by_shared_writer_lock(self):
        entered = threading.Event()
        release = threading.Event()
        started = []
        errors = []

        def validate(_base):
            started.append(threading.current_thread().name)
            entered.set()
            release.wait(timeout=2)

        def perform():
            try:
                reload.reload_components()
            except Exception as error:
                errors.append(error)

        self.css_mock.side_effect = validate
        first = threading.Thread(target=perform, name="first")
        second = threading.Thread(target=perform, name="second")
        first.start()
        self.assertTrue(entered.wait(timeout=2))
        second.start()
        time.sleep(.05)
        self.assertEqual(started, ["first"])
        release.set()
        first.join(timeout=3)
        second.join(timeout=3)
        self.assertEqual(started, ["first", "second"])
        self.assertEqual(errors, [])


class ComponentStartupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-component-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(ROOT/'niri',self.root/'niri',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.jsonl"
        for command in ("bash", "dirname", "python3"):
            (self.bin / command).symlink_to(shutil.which(command))
        for command in ("waybar", "gdbus", "swaync-client"):
            path = self.bin / command
            path.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ["CALL_LOG"], "a") as output:
    output.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "gdbus":
    sys.exit(int(os.environ.get("WAIT_STATUS", "1")))
''')
            path.chmod(0o755)

    def invoke(self, component, **extra):
        state=self.root/'state/selandia-niri';state.mkdir(parents=True,exist_ok=True)
        (state/'components.json').write_text('{"bar":"waybar"}')
        result = subprocess.run(["/usr/bin/bash", str(self.root / "niri/scripts/components"), component],
                                env=dict(os.environ, PATH=str(self.bin), CALL_LOG=str(self.log),XDG_STATE_HOME=str(self.root/'state'),NIRI_SOCKET='', **extra),
                                text=True, capture_output=True, timeout=3)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return result, calls


    def test_notification_stream_does_not_autostart_an_unmanaged_daemon(self):
        result, calls = self.invoke("notification-stream")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["gdbus"])

    def test_ready_notification_service_allows_subscriber(self):
        result, calls = self.invoke("notification-stream", WAIT_STATUS="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1], ["swaync-client", "--skip-wait", "--subscribe-waybar"])


class ReloadLanguageTests(unittest.TestCase):
    def test_command_diagnostics_preserve_raw_payload_in_both_languages(self):
        raw = "/home/用户/设置.conf: permission denied / 拒绝访问"
        for language in ("en_US", "zh_CN"):
            with self.subTest(language=language), patch.object(i18n, "get_language", return_value=language):
                for stderr, stdout in ((raw, ""), ("", raw)):
                    result = subprocess.CompletedProcess([], 1, stdout=stdout, stderr=stderr)
                    with patch.object(reload.subprocess, "run", return_value=result):
                        with self.assertRaises(RuntimeError) as caught:
                            reload.run(["command", "--file", "/home/用户/设置.conf"])
                    self.assertEqual(str(caught.exception), raw)

    def test_command_failure_fallback_uses_one_language(self):
        for language, expected in (("en_US", "Command failed: tool --value"),
                                   ("zh_CN", "命令失败：tool --value")):
            result = subprocess.CompletedProcess([], 1, stdout="", stderr="")
            with self.subTest(language=language), patch.object(i18n, "get_language", return_value=language), \
                    patch.object(reload.subprocess, "run", return_value=result):
                with self.assertRaises(RuntimeError) as caught:
                    reload.run(["tool", "--value"])
                self.assertEqual(str(caught.exception), expected)

    def test_reload_success_and_failure_messages_use_selected_language(self):
        raw = "Audio · 耳机 / Settings"
        for language, success, failure in (("en_US", "Desktop reloaded", "Reload failed: "),
                                           ("zh_CN", "桌面已重载", "重载失败：")):
            with self.subTest(language=language), patch.object(i18n, "get_language", return_value=language), \
                    patch.object(sys, "argv", ["reload_components.py", "theme"]), \
                    patch.object(reload, "reload_components") as action:
                output = io.StringIO()
                with patch.object(sys, "stdout", output):
                    self.assertEqual(reload.main(), 0)
                self.assertEqual(output.getvalue(), success + "\n")
                action.side_effect = RuntimeError(raw)
                output = io.StringIO()
                with patch.object(sys, "stderr", output):
                    self.assertEqual(reload.main(), 1)
                self.assertEqual(output.getvalue(), failure + raw + "\n")


if __name__ == "__main__":
    unittest.main()
