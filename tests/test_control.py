"""Exercise lifecycle command boundaries without touching packages or user config."""
import fcntl
import os
from pathlib import Path
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipIf(os.geteuid() == 0, "Controller intentionally requires the desktop user")
class ControlScriptTests(unittest.TestCase):
    """Every mutable command is replaced by a logger inside a temporary tree."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="niri control's ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        source = Path(__file__).resolve().parents[1]
        for filename in ("control.sh", "install.sh"):
            shutil.copy2(source / filename, self.root / filename)
        (self.root / "packages.txt").write_text("# test dependencies\nalpha\npavucontrol\n")
        self.script(self.bin / "pacman", r'''#!/usr/bin/env bash
printf 'pacman:%s\n' "$*" >> "$TEST_CALLS"
case "$1" in
    -Q)
        [[ " ${TEST_MISSING:-} " != *" $2 "* ]]
        ;;
    -Qk)
        if [[ "${TEST_INTEGRITY_EXIT:-0}" != 0 ]]; then exit "$TEST_INTEGRITY_EXIT"; fi
        if [[ " ${TEST_DAMAGED:-} " == *" $2 "* ]]; then
            printf '%s: 5 total files, 1 missing file\n' "$2"
            exit 1
        fi
        printf '%s: 5 total files, 0 missing files\n' "$2"
        ;;
    -Syu)
        if [[ "${TEST_PACKAGE_EXIT:-0}" == 0 ]]; then : > "$TEST_PACKAGE_DONE"; fi
        exit "${TEST_PACKAGE_EXIT:-0}"
        ;;
    *) printf 'Unexpected pacman operation: %s\n' "$*" >&2; exit 91 ;;
esac
''')
        self.script(self.bin / "sudo", r'''#!/usr/bin/env bash
printf 'sudo:%s\n' "$*" >> "$TEST_CALLS"
exec "$@"
''')
        self.script(self.root / "check.sh", r'''#!/usr/bin/env bash
printf 'check:%s\n' "$*" >> "$TEST_CALLS"
exit "${TEST_CHECK_EXIT:-0}"
''')
        (self.root / "tools").mkdir()
        (self.root / "tools/export_config.py").write_text('''import os, sys
with open(os.environ["TEST_CALLS"], "a") as output:
    output.write("export:" + " ".join(sys.argv[1:]) + "\\n")
''')
        (self.root / "tools/deploy.py").write_text('''import os, sys
with open(os.environ["TEST_CALLS"], "a") as output:
    output.write("deploy:" + sys.argv[1] + "\\n")
if sys.argv[1] == os.environ.get("TEST_DEPLOY_FAIL_MODE"):
    sys.exit(int(os.environ.get("TEST_DEPLOY_EXIT", "8")))
''')
        shell = self.root / "niri/shell"
        shell.mkdir(parents=True)
        (shell / "application_theme.py").write_text('''import os, sys
with open(os.environ["TEST_CALLS"], "a") as output:
    output.write("application_theme:" + sys.argv[1] + "\\n")
sys.exit(int(os.environ.get("TEST_APPLICATION_THEME_EXIT", "0")))
''')
        (shell / "language_settings.py").write_text('''import os, sys
with open(os.environ["TEST_CALLS"], "a") as output:
    output.write("language:" + sys.argv[1] + "\\n")
sys.exit(int(os.environ.get("TEST_LANGUAGE_EXIT", "0")))
''')
        (shell / "ui_assets.py").write_text('''import os, sys
with open(os.environ["TEST_CALLS"], "a") as output:
    output.write("ui_assets:write\\n")
sys.exit(int(os.environ.get("TEST_UI_ASSETS_EXIT", "0")))
''')
        # The controller delegates one coordinated operation. Backend effects
        # are mocked here; test_lifecycle exercises its real staging/rollback.
        (self.root / "tools/lifecycle.py").write_text('''import os, pathlib, subprocess, sys
root = pathlib.Path(__file__).resolve().parents[1]
state = pathlib.Path(os.environ["XDG_STATE_HOME"]) / "selandia-niri"
def call(path, *args):
    result = subprocess.run([sys.executable, "-B", str(root / path), *args])
    if result.returncode: sys.exit(result.returncode)
if sys.argv[1] == "recover":
    with open(os.environ["TEST_CALLS"], "a") as output: output.write("lifecycle:recover\\n")
elif sys.argv[1] == "install":
    if (state / "appearance.json").exists(): call("niri/shell/appearance.py", "restore-saved")
    call("niri/shell/language_settings.py", "restore-saved")
    call("niri/shell/ui_assets.py")
    result = subprocess.run([str(root / "check.sh"), "--config"])
    if result.returncode: sys.exit(result.returncode)
    call("niri/shell/application_theme.py", "apply-saved")
    call("tools/deploy.py", "install")
else:
    if (state / "language-backup.json").exists(): call("niri/shell/language_settings.py", "restore")
    call("niri/shell/application_theme.py", "restore")
    call("tools/deploy.py", "uninstall")
''')
        self.environment = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "TEST_CALLS": str(self.calls),
            "TEST_PACKAGE_DONE": str(self.root / "packages-done"),
            "TEST_REAL_PYTHON": sys.executable,
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "LANG": "en_US.UTF-8", "LC_ALL": "C.UTF-8", "LC_MESSAGES": "",
        }

    @staticmethod
    def script(path, content):
        path.write_text(content)
        path.chmod(0o755)

    def run_control(self, *arguments, wrapper=False, **environment):
        self.calls.unlink(missing_ok=True)
        filename = "install.sh" if wrapper else "control.sh"
        result = subprocess.run(
            ["bash", str(self.root / filename), *arguments],
            env={**self.environment, **environment},
            input="", capture_output=True, text=True, timeout=10,
        )
        calls = self.calls.read_text().splitlines() if self.calls.exists() else []
        # Even accidental direct deployment is contained by these XDG overrides.
        self.assertFalse((self.root / "config").exists())
        return result, calls

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_no_mutation(self, calls):
        self.assertFalse(any(call.startswith(("sudo:", "pacman:-S", "check:", "application_theme:", "language:", "ui_assets:")) for call in calls), calls)
        self.assertNotIn("deploy:install", calls)
        self.assertNotIn("deploy:uninstall", calls)
        self.assertNotIn("lifecycle:recover", calls)

    def test_pending_transaction_status_and_previews_remain_read_only(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        for journal in ("lifecycle-transaction.json", "deployment-transaction.json"):
            (state / journal).write_text("{}")
        for arguments in (("status",), ("install", "--dry-run", "--no-packages"),
                          ("uninstall", "--dry-run")):
            with self.subTest(arguments=arguments):
                result, calls = self.run_control(*arguments)
                self.assert_success(result)
                self.assert_no_mutation(calls)
                for journal in ("lifecycle-transaction.json", "deployment-transaction.json"):
                    self.assertEqual((state / journal).read_text(), "{}")

    def test_install_recovers_pending_transaction_before_setup(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        (state / "lifecycle-transaction.json").write_text("{}")
        result, calls = self.run_control("install", "--no-packages")
        self.assert_success(result)
        self.assertLess(calls.index("lifecycle:recover"), calls.index("check:--config"))

    def assert_config_flow(self, calls, *, deployed=True, themed=True):
        self.assertEqual(calls[0], "deploy:preflight")
        expected = ["language:restore-saved", "ui_assets:write", "check:--config"]
        if themed:
            expected.append("application_theme:apply-saved")
        if deployed:
            expected.append("deploy:install")
        self.assertEqual([call for call in calls if call != "deploy:preflight"], expected)

    def installed_manifest(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        (state / "install.json").write_text("{}")

    def test_no_arguments_on_noninteractive_input_only_shows_help(self):
        result, calls = self.run_control()
        self.assert_success(result)
        for command in ("install", "update", "repair", "uninstall"):
            self.assertIn(command, result.stdout)
        self.assertEqual(calls, [])

    def test_interactive_menu_can_exit_without_mutating(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        try:
            process = subprocess.Popen(
                ["bash", str(self.root / "control.sh")],
                env=self.environment, stdin=slave, stdout=slave, stderr=slave,
            )
        finally:
            os.close(slave)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        os.write(master, b"0\n")
        self.assertEqual(process.wait(timeout=10), 0)
        output = os.read(master, 16384).decode()
        self.assertIn("Install", output)
        self.assertIn("Repair", output)
        self.assertNotIn("修复", output)
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.root / "state").exists())

    def test_invalid_command_and_unknown_options_do_nothing(self):
        for arguments in (("destroy",), ("install", "--unknown"), ("install", "update"),
                          ("install", "--yes"), ("repair", "--yes")):
            with self.subTest(arguments=arguments):
                result, calls = self.run_control(*arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(calls, [])

    def test_install_healthy_packages_skips_system_update(self):
        result, calls = self.run_control("install")
        self.assert_success(result)
        self.assertFalse(any(call.startswith("sudo:") for call in calls))
        self.assertEqual(calls[-3:], ["check:--config", "application_theme:apply-saved", "deploy:install"])

    def test_optional_aur_declarations_are_not_queried_or_sent_to_pacman(self):
        with (self.root / "packages.txt").open("a") as manifest:
            manifest.write("# optional aur mpvpaper | video playback\n"
                           "# optional-experimental aur linux-wallpaperengine-git | scenes\n")
        result, calls = self.run_control("install")
        self.assert_success(result)
        self.assertFalse(any("mpvpaper" in call or "linux-wallpaperengine" in call for call in calls))
        self.assertFalse(any(call.startswith("sudo:") for call in calls))

    def test_install_missing_package_upgrades_before_validation_and_deployment(self):
        result, calls = self.run_control("install", TEST_MISSING="alpha")
        self.assert_success(result)
        transaction = "sudo:pacman -Syu --needed -- alpha"
        self.assertIn(transaction, calls)
        self.assertLess(calls.index("deploy:preflight"), calls.index(transaction))
        self.assertEqual(calls[-3:], ["check:--config", "application_theme:apply-saved", "deploy:install"])

    def test_existing_qt_mixer_satisfies_install(self):
        result, calls = self.run_control("install", TEST_MISSING="pavucontrol")
        self.assert_success(result)
        self.assertIn("pacman:-Q pavucontrol-qt", calls)
        self.assertFalse(any(call.startswith("sudo:") for call in calls))

    def test_update_always_upgrades_configured_packages(self):
        result, calls = self.run_control("update")
        self.assert_success(result)
        transaction = "sudo:pacman -Syu --needed -- alpha pavucontrol"
        self.assertIn(transaction, calls)
        self.assertLess(calls.index("deploy:preflight"), calls.index(transaction))
        self.assertEqual(calls[-3:], ["check:--config", "application_theme:apply-saved", "deploy:install"])

    def test_update_keeps_existing_qt_mixer(self):
        result, calls = self.run_control("update", TEST_MISSING="pavucontrol")
        self.assert_success(result)
        self.assertIn("sudo:pacman -Syu --needed -- alpha pavucontrol-qt", calls)

    def test_repair_healthy_packages_skips_system_update(self):
        result, calls = self.run_control("repair")
        self.assert_success(result)
        self.assertIn("pacman:-Qk alpha", calls)
        self.assertIn("pacman:-Qk pavucontrol", calls)
        self.assertFalse(any(call.startswith("sudo:") for call in calls))
        self.assertEqual(calls[-3:], ["check:--config", "application_theme:apply-saved", "deploy:install"])

    def test_repair_reinstalls_damaged_package_without_needed(self):
        result, calls = self.run_control("repair", TEST_DAMAGED="alpha")
        self.assert_success(result)
        self.assertIn("sudo:pacman -Syu -- alpha", calls)
        self.assertFalse(any("--needed" in call for call in calls))

    def test_repair_missing_and_damaged_packages_in_one_transaction(self):
        result, calls = self.run_control("repair", TEST_MISSING="alpha", TEST_DAMAGED="pavucontrol")
        self.assert_success(result)
        transactions = [call for call in calls if call.startswith("sudo:")]
        self.assertEqual(len(transactions), 1, calls)
        self.assertEqual(set(transactions[0].split()[3:]), {"alpha", "pavucontrol"})
        self.assertTrue(transactions[0].startswith("sudo:pacman -Syu -- "), calls)
        self.assertNotIn("pacman:-Qk alpha", calls)

    def test_repair_checks_selected_qt_mixer(self):
        result, calls = self.run_control("repair", TEST_MISSING="pavucontrol", TEST_DAMAGED="pavucontrol-qt")
        self.assert_success(result)
        self.assertIn("pacman:-Qk pavucontrol-qt", calls)
        self.assertIn("sudo:pacman -Syu -- pavucontrol-qt", calls)

    def test_repair_can_bootstrap_python_with_missing_runtime_files(self):
        with (self.root / "packages.txt").open("a") as output:
            output.write("python\n")
        self.script(self.bin / "python3", r'''#!/usr/bin/env bash
if [[ ! -f "$TEST_PACKAGE_DONE" ]]; then exit 1; fi
exec "$TEST_REAL_PYTHON" "$@"
''')
        result, calls = self.run_control("repair", TEST_DAMAGED="python")
        self.assert_success(result)
        transaction = "sudo:pacman -Syu -- python"
        self.assertIn(transaction, calls)
        self.assertLess(calls.index(transaction), calls.index("deploy:preflight"))
        self.assertEqual(calls[-3:], ["check:--config", "application_theme:apply-saved", "deploy:install"])

    def test_no_packages_with_broken_python_stops_before_any_action(self):
        self.script(self.bin / "python3", "#!/usr/bin/env bash\nexit 1\n")
        result, calls = self.run_control("repair", "--no-packages")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])
        self.assertFalse((self.root / "state").exists())

    def test_integrity_check_error_aborts_before_package_changes(self):
        result, calls = self.run_control("repair", TEST_INTEGRITY_EXIT="2")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(calls)

    def test_preflight_failure_prevents_package_and_configuration_changes(self):
        for command in ("install", "update", "repair"):
            with self.subTest(command=command):
                result, calls = self.run_control(command, TEST_MISSING="alpha", TEST_DEPLOY_FAIL_MODE="preflight")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("deploy:preflight", calls)
                self.assert_no_mutation(calls)

    def test_package_failure_prevents_validation_and_deployment(self):
        for command in ("install", "update", "repair"):
            with self.subTest(command=command):
                result, calls = self.run_control(command, TEST_MISSING="alpha", TEST_PACKAGE_EXIT="7")
                self.assertEqual(result.returncode, 7)
                self.assertNotIn("check:--config", calls)
                self.assertNotIn("deploy:install", calls)

    def test_validation_failure_prevents_deployment(self):
        result, calls = self.run_control("repair", "--no-packages", TEST_CHECK_EXIT="6")
        self.assertEqual(result.returncode, 6)
        self.assert_config_flow(calls, deployed=False, themed=False)

    def test_deployment_failure_is_reported(self):
        result, calls = self.run_control("install", "--no-packages", TEST_DEPLOY_FAIL_MODE="install")
        self.assertEqual(result.returncode, 8)
        self.assert_config_flow(calls)

    def test_failed_theme_plan_prevents_config_deployment(self):
        result, calls = self.run_control("repair", "--no-packages", TEST_APPLICATION_THEME_EXIT="9")
        self.assertEqual(result.returncode, 9)
        self.assert_config_flow(calls, deployed=False)

    def test_failed_theme_restore_preserves_installed_config(self):
        self.installed_manifest()
        result, calls = self.run_control("uninstall", "--yes", TEST_APPLICATION_THEME_EXIT="9")
        self.assertEqual(result.returncode, 9)
        self.assertEqual(calls, ["deploy:dry-run-uninstall", "application_theme:restore"])

    def test_no_packages_bypasses_every_package_query_and_transaction(self):
        for command in ("install", "update", "repair"):
            with self.subTest(command=command):
                result, calls = self.run_control(command, "--no-packages")
                self.assert_success(result)
                self.assert_config_flow(calls)

    def prepare_saved_appearance(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        (state / "appearance.json").write_text('{"preset":"violet"}')
        directory = self.root / "niri/shell"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "appearance.py").write_text('''import os, sys
with open(os.environ["TEST_CALLS"], "a") as output:
    output.write("appearance:" + sys.argv[1] + "\\n")
sys.exit(int(os.environ.get("TEST_APPEARANCE_EXIT", "0")))
''')

    def test_update_restores_saved_appearance_before_validation_but_preview_does_not(self):
        self.prepare_saved_appearance()
        result, calls = self.run_control("update", "--no-packages")
        self.assert_success(result)
        self.assertLess(calls.index("appearance:restore-saved"), calls.index("check:--config"))
        result, calls = self.run_control("update", "--dry-run")
        self.assert_success(result)
        self.assertNotIn("appearance:restore-saved", calls)

    def test_invalid_saved_appearance_stops_deployment(self):
        self.prepare_saved_appearance()
        result, calls = self.run_control("repair", "--no-packages", TEST_APPEARANCE_EXIT="4")
        self.assertEqual(result.returncode, 4)
        self.assertNotIn("check:--config", calls)
        self.assertNotIn("deploy:install", calls)

    def test_saved_language_restores_and_labels_generate_before_validation(self):
        for command in ("install", "repair", "update"):
            with self.subTest(command=command):
                result, calls = self.run_control(command, "--no-packages")
                self.assert_success(result)
                self.assertLess(calls.index("language:restore-saved"), calls.index("ui_assets:write"))
                self.assertLess(calls.index("ui_assets:write"), calls.index("check:--config"))

    def test_language_restore_failure_stops_validation_and_deployment(self):
        result, calls = self.run_control("repair", "--no-packages", TEST_LANGUAGE_EXIT="4")
        self.assertEqual(result.returncode, 4)
        self.assertNotIn("ui_assets:write", calls)
        self.assertNotIn("check:--config", calls)
        self.assertNotIn("deploy:install", calls)

    def test_label_generation_failure_stops_validation_and_deployment(self):
        result, calls = self.run_control("repair", "--no-packages", TEST_UI_ASSETS_EXIT="5")
        self.assertEqual(result.returncode, 5)
        self.assertIn("language:restore-saved", calls)
        self.assertNotIn("check:--config", calls)
        self.assertNotIn("deploy:install", calls)

    def test_dry_runs_print_transaction_without_mutating(self):
        cases = (
            ("install", {"TEST_MISSING": "alpha"}, "sudo pacman -Syu --needed -- alpha"),
            ("update", {}, "sudo pacman -Syu --needed -- alpha pavucontrol"),
            ("repair", {"TEST_DAMAGED": "alpha"}, "sudo pacman -Syu -- alpha"),
        )
        for command, environment, plan in cases:
            with self.subTest(command=command):
                result, calls = self.run_control(command, "--dry-run", **environment)
                self.assert_success(result)
                self.assertIn(plan, result.stdout)
                self.assertIn("deploy:dry-run", calls)
                self.assert_no_mutation(calls)
                self.assertFalse((self.root / "state").exists())

    def test_uninstall_dry_run_only_previews_restore(self):
        result, calls = self.run_control("uninstall", "--dry-run")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall"])
        self.assertFalse((self.root / "state").exists())

    def test_noninteractive_uninstall_requires_explicit_confirmation(self):
        self.installed_manifest()
        result, calls = self.run_control("uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--yes", result.stdout + result.stderr)
        self.assert_no_mutation(calls)

    def test_uninstall_never_queries_packages_or_validates_config(self):
        self.installed_manifest()
        result, calls = self.run_control("uninstall", "--yes")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall", "application_theme:restore", "deploy:uninstall"])

    def test_uninstall_without_installation_is_a_noop(self):
        result, calls = self.run_control("uninstall")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall"])
        self.assertFalse((self.root / "state").exists())

    def test_uninstall_restores_orphaned_application_theme_journal(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        (state / "application-theme.json").write_text("{}")
        result, calls = self.run_control("uninstall", "--yes")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall", "application_theme:restore", "deploy:uninstall"])

    def prepare_language_backup(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True, exist_ok=True)
        (state / "language-backup.json").write_text("{}")

    def test_uninstall_restores_orphaned_language_journal_before_deployment(self):
        self.prepare_language_backup()
        result, calls = self.run_control("uninstall", "--yes")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall", "language:restore", "application_theme:restore", "deploy:uninstall"])

    def test_failed_language_restore_preserves_deployment(self):
        self.prepare_language_backup()
        result, calls = self.run_control("uninstall", "--yes", TEST_LANGUAGE_EXIT="3")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(calls, ["deploy:dry-run-uninstall", "language:restore"])

    def test_uninstall_language_preview_never_restores(self):
        self.prepare_language_backup()
        result, calls = self.run_control("uninstall", "--dry-run")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall"])
        self.assertIn("Restore managed user session language", result.stdout)

    def test_saved_interface_language_controls_help_without_altering_session(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        preferences = state / "language.json"
        for code, included, excluded in (("zh_CN", "桌面控制脚本", "Desktop controller"),
                                         ("en_US", "Desktop controller", "桌面控制脚本")):
            with self.subTest(language=code):
                preferences.write_text('{"ui_language":"' + code + '", "session_locale":"zh_CN.UTF-8"}')
                result, calls = self.run_control("--help")
                self.assert_success(result)
                self.assertIn(included, result.stdout)
                self.assertNotIn(excluded, result.stdout)
                self.assertEqual(calls, [])

    def test_follow_session_language_falls_back_to_environment_without_python(self):
        self.script(self.bin / "python3", "#!/usr/bin/env bash\nexit 1\n")
        result, calls = self.run_control("--help", LC_ALL="", LANG="zh_CN.UTF-8")
        self.assert_success(result)
        self.assertIn("桌面控制脚本", result.stdout)
        self.assertNotIn("Desktop controller", result.stdout)
        self.assertEqual(calls, [])

    def test_uninstall_dry_run_does_not_restore_application_theme(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        (state / "application-theme.json").write_text("{}")
        result, calls = self.run_control("uninstall", "--dry-run")
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall"])
        self.assertIn("Restore managed GTK/Qt", result.stdout)

    def test_uninstall_preflight_failure_preserves_installation(self):
        result, calls = self.run_control("uninstall", "--yes", TEST_DEPLOY_FAIL_MODE="dry-run-uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ["deploy:dry-run-uninstall"])

    def test_check_only_runs_existing_validator(self):
        result, calls = self.run_control("check")
        self.assert_success(result)
        self.assertEqual(calls, ["check:"])

    def test_check_propagates_validation_failure(self):
        result, calls = self.run_control("check", TEST_CHECK_EXIT="5")
        self.assertEqual(result.returncode, 5)
        self.assertEqual(calls, ["check:"])

    def test_status_inventories_and_checks_packages_without_mutating(self):
        result, calls = self.run_control("status")
        self.assert_success(result)
        self.assertIn("pacman:-Q alpha", calls)
        self.assertIn("pacman:-Qk alpha", calls)
        self.assertIn("deploy:status", calls)
        self.assert_no_mutation(calls)
        self.assertFalse((self.root / "state").exists())

    def test_status_reports_missing_or_damaged_packages_without_mutating(self):
        for environment in ({"TEST_MISSING": "alpha"}, {"TEST_DAMAGED": "alpha"}):
            with self.subTest(environment=environment):
                result, calls = self.run_control("status", **environment)
                self.assertEqual(result.returncode, 1)
                self.assertIn("deploy:status", calls)
                self.assert_no_mutation(calls)
                self.assertFalse((self.root / "state").exists())

    def test_status_reports_unhealthy_deployment_without_mutating(self):
        result, calls = self.run_control("status", TEST_DEPLOY_FAIL_MODE="status")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deploy:status", calls)
        self.assert_no_mutation(calls)

    def test_controller_lock_prevents_overlapping_mutations(self):
        state = self.root / "state/selandia-niri"
        state.mkdir(parents=True)
        with (state / "control.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, calls = self.run_control("repair", "--no-packages")
        self.assertNotEqual(result.returncode, 0)
        self.assert_no_mutation(calls)

    def test_legacy_install_defaults_to_install_without_opening_menu(self):
        result, calls = self.run_control("--no-packages", wrapper=True)
        self.assert_success(result)
        self.assert_config_flow(calls)

    def test_legacy_install_with_no_arguments_installs(self):
        result, calls = self.run_control(wrapper=True)
        self.assert_success(result)
        self.assertEqual(calls[-3:], ["check:--config", "application_theme:apply-saved", "deploy:install"])

    def test_legacy_conflicting_flags_do_nothing(self):
        for arguments in (("--packages", "--no-packages"), ("--uninstall", "--packages")):
            with self.subTest(arguments=arguments):
                result, calls = self.run_control(*arguments, wrapper=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(calls, [])

    def test_legacy_packages_flag_still_installs_missing_packages(self):
        result, calls = self.run_control("--packages", wrapper=True, TEST_MISSING="alpha")
        self.assert_success(result)
        self.assertIn("sudo:pacman -Syu --needed -- alpha", calls)

    def test_legacy_wrapper_forwards_explicit_lifecycle_commands(self):
        result, calls = self.run_control("update", "--no-packages", wrapper=True)
        self.assert_success(result)
        self.assert_config_flow(calls)

    def test_legacy_wrapper_forwards_export_without_installing(self):
        result, calls = self.run_control("export", wrapper=True)
        self.assert_success(result)
        self.assertEqual(calls, ["export:"])

    def test_legacy_uninstall_flag_uses_safe_restore(self):
        self.installed_manifest()
        result, calls = self.run_control("--uninstall", "--yes", wrapper=True)
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall", "application_theme:restore", "deploy:uninstall"])

    def test_legacy_uninstall_flag_can_preview_without_confirmation(self):
        result, calls = self.run_control("--uninstall", "--dry-run", wrapper=True)
        self.assert_success(result)
        self.assertEqual(calls, ["deploy:dry-run-uninstall"])


if __name__ == "__main__":
    unittest.main()
