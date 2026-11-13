"""Desktop actions use argv safely; no terminal, service or package is started."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class DesktopActionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="niri desktop's ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "project with space's"
        self.base = self.root / "niri"
        self.bin = self.root / "bin"
        self.bin.mkdir(parents=True)
        (self.base / "scripts").mkdir(parents=True)
        source = Path(__file__).resolve().parents[1] / "niri/scripts/desktop"
        self.desktop = self.base / "scripts/desktop"
        shutil.copy2(source, self.desktop)
        self.log = self.root / "calls.jsonl"
        runtime = self.root / "runtime"
        runtime.mkdir()
        self.environment = {**os.environ, "PATH": str(self.bin),
                            "TEST_DESKTOP_CALLS": str(self.log),
                            "HOME": str(self.root / "home"),
                            "XDG_RUNTIME_DIR": str(runtime),
                            "XDG_CONFIG_HOME": str(self.root / "config"),
                            "XDG_STATE_HOME": str(self.root / "state")}
        # PATH is deliberately isolated: unexpected commands cannot touch the
        # host, even if future desktop hooks accidentally invoke them directly.
        for command in ("dirname", "bash"):
            (self.bin / command).symlink_to(shutil.which(command))
        for command in ("alacritty", "python3", "niri", "systemctl", "notify-send", "fuzzel", "anyrun", "anyrun-provider", "swaylock", "flock", "pgrep"):
            self.stub(self.bin / command)
        self.stub(self.root / "control.sh")
        shell=self.base/'shell';shell.mkdir()
        source=Path(__file__).resolve().parents[1]/'niri/shell'
        for name in ('component_preferences.py','appearance.py','font_scale.py','session_identity.py'):
            shutil.copy2(source/name,shell/name)
        shutil.copy2(source/'i18n.py',shell/'i18n.py')
        state=self.root/'state/selandia-niri';state.mkdir(parents=True)
        (state/'components.json').write_text('{"bar":"waybar","launcher":"fuzzel","terminal":"alacritty"}')

    def stub(self, path):
        path.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ["TEST_DESKTOP_CALLS"], "a") as output:
    if not (name == "python3" and len(sys.argv)>2 and pathlib.Path(sys.argv[2]).name in ("component_preferences.py", "language_settings.py", "i18n.py")):
        output.write(json.dumps([name, *sys.argv[1:]]) + "\\n")
if name == "pgrep":
    sys.exit(1)
if name == "niri":
    sys.exit(int(os.environ.get("TEST_NIRI_STATUS", "0")))
if name == "python3" and len(sys.argv)>2 and pathlib.Path(sys.argv[2]).name=="component_preferences.py":
    sys.path.insert(0,str(pathlib.Path(sys.argv[2]).parent))
    import component_preferences as c
    if sys.argv[3]=='terminal':
        args=c.terminal_command(sys.argv[4:]);os.execv(args[0] if '/' in args[0] else str(pathlib.Path(sys.argv[0]).parent/args[0]),args)
    elif sys.argv[3]=='launcher':c.launch()
if name == "python3" and len(sys.argv)>2 and pathlib.Path(sys.argv[2]).name=="i18n.py":
    os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
if name == "python3" and os.environ.get("TEST_DESKTOP_STDOUT"):
    print(os.environ["TEST_DESKTOP_STDOUT"])
if name == "python3" and os.environ.get("TEST_DESKTOP_STATUS"):
    sys.exit(int(os.environ["TEST_DESKTOP_STATUS"]))
if name == "alacritty" and os.environ.get("TEST_LANGUAGE_LOG"):
    keys = ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE", "SELANDIA_LANGUAGE_WRAPPED")
    pathlib.Path(os.environ["TEST_LANGUAGE_LOG"]).write_text(json.dumps({key: os.environ[key] for key in keys if key in os.environ}))
''')
        path.chmod(0o755)

    def invoke(self, *arguments, **environment):
        self.log.unlink(missing_ok=True)
        result = subprocess.run(["/usr/bin/bash", str(self.desktop), *arguments],
                                env={**self.environment, **environment}, capture_output=True,
                                text=True, timeout=5)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_maintenance_uses_held_terminal_and_separate_controller_arguments(self):
        for action in ("updates", "repair", "status", "check"):
            with self.subTest(action=action):
                result, calls = self.invoke(action)
                self.assert_success(result)
                self.assertEqual(len(calls), 1)
                call, = calls
                self.assertEqual(call[0], "alacritty")
                self.assertIn("--hold", call)
                self.assertEqual(Path(call[-2]).resolve(), self.root / "control.sh")
                self.assertEqual(call[-1], "update" if action == "updates" else action)
                self.assertNotIn("-c", call)

    def test_maintenance_without_controller_fails_before_terminal(self):
        (self.root / "control.sh").unlink()
        result, calls = self.invoke("updates")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["notify-send"])

    def test_panel_modes_preserve_mode_and_quoted_script_path(self):
        for mode in ("control", "quick", "system", "appearance", "sound", "displays", "input", "desktop",
                     "network", "hardware", "applications", "language", "time", "startup", "services", "security",
                     "shortcuts", "ai"):
            with self.subTest(mode=mode):
                result, calls = self.invoke(mode)
                self.assert_success(result)
                self.assertEqual(calls, [["python3", "-B", str(self.base / "shell/panel.py"), mode]])
        result, calls = self.invoke("power-settings")
        self.assert_success(result)
        self.assertEqual(calls, [["python3", "-B", str(self.base / "shell/panel.py"), "power"]])

    def prepare_language_helpers(self, *, ui="zh_CN", session="en_US.UTF-8"):
        source = Path(__file__).resolve().parents[1] / "niri/shell"
        (self.base / "shell").mkdir(exist_ok=True)
        for name in ("i18n.py", "language_settings.py"):
            shutil.copy2(source / name, self.base / "shell" / name)
        (self.bin / "python3").unlink()
        (self.bin / "python3").symlink_to(sys.executable)
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True,exist_ok=True)
        (state / "language.json").write_text(json.dumps({"ui_language": ui, "session_locale": session}))

    def test_saved_interface_language_and_terminal_locale_remain_independent(self):
        self.prepare_language_helpers()
        environment_log = self.root / "terminal-language.json"
        result, calls = self.invoke("status", TEST_LANGUAGE_LOG=str(environment_log), LANG="zh_CN.UTF-8",
                                    LC_ALL="C.UTF-8", LC_MESSAGES="zh_CN.UTF-8", LANGUAGE="zh_CN:en")
        self.assert_success(result)
        call, = calls
        self.assertIn("桌面维护 — status", call)
        self.assertNotIn("Desktop maintenance — status", call)
        self.assertEqual(json.loads(environment_log.read_text()), {"LANG": "en_US.UTF-8"})

    def test_new_launch_reads_updated_language_preferences(self):
        self.prepare_language_helpers(ui="en_US", session="")
        result, calls = self.invoke("status", LANG="C.UTF-8", LC_ALL="C.UTF-8")
        self.assert_success(result)
        self.assertIn("Desktop maintenance — status", calls[0])
        (self.root / "state/selandia-niri/language.json").write_text('{"ui_language":"zh_CN", "session_locale":""}')
        result, calls = self.invoke("status", LANG="C.UTF-8", LC_ALL="C.UTF-8")
        self.assert_success(result)
        self.assertIn("桌面维护 — status", calls[0])

    def test_process_monitor_prefers_btop_then_htop_then_top(self):
        for command in ("btop", "htop", "top"):
            self.stub(self.bin / command)
        for expected in ("btop", "htop", "top"):
            result, calls = self.invoke("system-monitor")
            self.assert_success(result)
            call, = calls
            self.assertEqual(call[0], "alacritty")
            self.assertEqual(call[-1], expected)
            (self.bin / expected).unlink()
        result, calls = self.invoke("system-monitor")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["notify-send"])

    def test_theme_reload_validates_before_reloading_managed_components(self):
        result, calls = self.invoke("theme-reload")
        self.assert_success(result)
        self.assertEqual(calls, [
            ["niri", "validate", "-c", str(self.base / "config.kdl")],
            ["python3", "-B", str(self.base / "shell/reload_components.py"), "theme"],
        ])
        result, calls = self.invoke("theme-reload", TEST_NIRI_STATUS="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["niri"])



    def test_power_uses_the_native_menu_and_dispatches_only_what_it_reports(self):
        # The submenu has no search field any more: fuzzel is never involved, so
        # a hidden filter cannot turn one stray keystroke into a reboot.
        for choice, expected in (
                ("lock", ["python3", "-B", str(self.base / "shell/lock_session.py")]),
                ("sleep", ["python3", "-B", str(self.base / "shell/power_actions.py"), "suspend"]),
                ("logout", ["niri", "msg", "action", "quit", "--skip-confirmation"]),
                ("restart", ["systemctl", "reboot"]),
                ("shutdown", ["systemctl", "poweroff"]),
        ):
            with self.subTest(choice=choice):
                result, calls = self.invoke("power", TEST_DESKTOP_STDOUT=choice)
                self.assert_success(result)
                self.assertEqual(calls[0], ["python3", "-B", str(self.base / "shell/power_menu.py")])
                self.assertEqual(calls[1:], [expected])
                self.assertFalse(any(call[0] == "fuzzel" for call in calls))

    def test_cancelling_the_power_menu_performs_no_session_action(self):
        result, calls = self.invoke("power", TEST_DESKTOP_STATUS="1")
        self.assert_success(result)
        self.assertEqual(calls, [["python3", "-B", str(self.base / "shell/power_menu.py")]])

    def test_unknown_power_output_is_refused(self):
        result, calls = self.invoke("power", TEST_DESKTOP_STDOUT="reboot-now")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(calls), 1)

    def test_dmenu_confirmation_does_not_reuse_the_application_placeholder(self):
        result, calls = self.invoke("clipboard-clear", LC_ALL="C", TEST_DESKTOP_STDOUT="Cancel")
        self.assert_success(result)
        fuzzel = [call for call in calls if call[0] == "fuzzel"]
        self.assertTrue(fuzzel)
        self.assertIn("--dmenu", fuzzel[0])
        placeholder = fuzzel[0][fuzzel[0].index("--placeholder") + 1]
        self.assertNotEqual(placeholder, "Search applications")
        self.assertNotIn(" · ", placeholder)
        # Cancelling must not wipe the clipboard: only the menu ran.
        self.assertEqual([call[0] for call in calls], ["fuzzel"])

    def test_lock_uses_session_scoped_readiness_helper(self):
        result, calls = self.invoke("lock")
        self.assert_success(result)
        self.assertEqual(calls, [["python3", "-B", str(self.base / "shell/lock_session.py")]])

    def test_stay_awake_uses_explicit_inhibitor_not_service_inactivity(self):
        result, calls = self.invoke("idle-toggle")
        self.assert_success(result)
        self.assertEqual(calls[0], ["python3", "-B", str(self.base / "shell/sleep_guard.py"), "toggle"])
        self.assertFalse(any(call[0] == "systemctl" for call in calls))


if __name__ == "__main__":
    unittest.main()
