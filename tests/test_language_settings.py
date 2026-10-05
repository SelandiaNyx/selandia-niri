"""Language lifecycle tests never touch the host configuration or locale daemon."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import language_settings as language


class LanguageSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-language-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "state/language.json"
        self.config = self.root / "config"
        self.niri = self.root / "niri"
        self.options = dict(config_home=self.config, niri_home=self.niri, state_path=self.state)
        self.apply_options = dict(self.options, notify=False)
        self.locales = ["C", "C.utf8", "POSIX", "en_US.utf8", "zh_CN.utf8", "de_DE.utf8"]
        self.locale_patch = patch.object(language, "available_locales", return_value=self.locales)
        self.locale_patch.start()
        self.addCleanup(self.locale_patch.stop)
        self.run = patch.object(language, "_run", side_effect=AssertionError("Unexpected external command"))
        self.run_mock = self.run.start()
        self.addCleanup(self.run.stop)

    def apply(self, locale="zh_CN.UTF-8"):
        return language.apply_session_locale(locale, **self.apply_options)

    def path(self, key):
        return language._paths(self.config, self.niri)[key]

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_absent_invalid_and_old_preferences_have_safe_defaults(self):
        self.assertEqual(language.read_preferences(state_path=self.state), language.DEFAULTS)
        for value in ("not json", "[]", '{"ui_language":"bad"}', '{"session_locale":"foo\\nLANG=x"}',
                      '{"ui_language":false}', '{"unexpected":1}'):
            self.write(self.state, value)
            self.assertEqual(language.read_preferences(state_path=self.state), language.DEFAULTS)

    def test_interface_language_does_not_change_user_or_system_locale(self):
        self.write(self.state, '{"ui_language":"system", "session_locale":"en_US.UTF-8"}')
        result = language.save_ui_language("zh_CN", state_path=self.state)
        self.assertEqual(result, {"ui_language": "zh_CN", "session_locale": "en_US.UTF-8"})
        self.assertFalse(self.path("environment").exists())
        self.run_mock.assert_not_called()
        with self.assertRaises(ValueError):
            language.save_ui_language("fr_FR", state_path=self.state)

    def test_follow_system_uses_saved_session_and_locale_precedence(self):
        with patch.dict(os.environ, {"LANG": "en_US.UTF-8", "LC_MESSAGES": "zh_CN.UTF-8"}, clear=True):
            self.assertEqual(language.resolve_ui_language(state_path=self.state), "zh_CN")
            self.write(self.state, '{"session_locale":"en_US.UTF-8"}')
            self.assertEqual(language.resolve_ui_language(state_path=self.state), "en_US")
            self.assertEqual(language.resolve_ui_language("zh_CN", state_path=self.state), "zh_CN")

    def test_validate_aliases_and_reject_uninstalled_or_injected_locales(self):
        self.assertEqual(language.validate_locale("zh_CN.UTF-8"), "zh_CN.UTF-8")
        self.assertEqual(language.validate_locale("en_US.utf8"), "en_US.UTF-8")
        self.assertEqual(language.validate_locale("C.UTF-8"), "C.UTF-8")
        for value in ("fr_FR.UTF-8", "en_US.UTF-8;touch /tmp/x", "$(id)", "-help", "en_US\nLC_ALL=C", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                language.validate_locale(value)

    def test_user_locale_writes_scoped_config_and_clears_niri_overrides(self):
        language.save_ui_language("en_US", state_path=self.state)
        result = self.apply()
        self.assertEqual(result["locale"], "zh_CN.UTF-8")
        self.assertEqual(result["preferences"]["ui_language"], "en_US")
        source = self.path("niri").read_text()
        self.assertIn('LANG "zh_CN.UTF-8"', source)
        for key in language.OVERRIDES:
            self.assertIn(f"{key} null", source)
        environment = self.path("environment").read_text()
        self.assertIn("LANG=zh_CN.UTF-8\n", environment)
        self.assertNotIn("LC_ALL=", environment)
        self.assertNotIn("LANGUAGE=", environment)
        self.run_mock.assert_not_called()

    def test_multiple_changes_restore_original_files_and_keep_ui_preference(self):
        original = {"niri": "// original placeholder\n", "environment": "# own file\nLANG=de_DE.UTF-8\n"}
        for key, content in original.items():
            self.write(self.path(key), content)
        language.save_ui_language("en_US", state_path=self.state)
        self.apply()
        self.apply("en_US.UTF-8")
        result = language.restore(**self.options)
        self.assertFalse(result["conflicts"])
        for key, content in original.items():
            self.assertEqual(self.path(key).read_text(), content)
        self.assertEqual(language.read_preferences(state_path=self.state), {"ui_language": "en_US", "session_locale": ""})
        self.assertFalse(self.state.with_name("language-backup.json").exists())

    def test_restore_removes_created_files(self):
        self.apply()
        language.restore(**self.options)
        self.assertFalse(self.path("environment").exists())
        self.assertFalse(self.path("niri").exists())

    def test_apply_preserves_foreign_edits(self):
        self.apply()
        self.path("environment").write_text("# changed by user\nLANG=de_DE.UTF-8\n")
        original = self.path("niri").read_text()
        with self.assertRaises(RuntimeError):
            self.apply("en_US.UTF-8")
        self.assertEqual(self.path("environment").read_text(), "# changed by user\nLANG=de_DE.UTF-8\n")
        self.assertEqual(self.path("niri").read_text(), original)
        self.assertEqual(language.read_preferences(state_path=self.state)["session_locale"], "zh_CN.UTF-8")

    def test_restore_preserves_foreign_edits_and_retains_backup(self):
        self.apply()
        self.path("niri").write_text("// personal change\n")
        result = language.restore(**self.options)
        self.assertEqual(result["conflicts"], [str(self.path("niri"))])
        self.assertEqual(self.path("niri").read_text(), "// personal change\n")
        self.assertTrue(self.state.with_name("language-backup.json").exists())
        self.assertFalse(self.path("environment").exists())

    def test_second_file_write_failure_rolls_back_complete_transaction(self):
        for key in ("niri", "environment"):
            self.write(self.path(key), "# original " + key + "\n")
        language.save_ui_language("en_US", state_path=self.state)
        preferences = self.state.read_text()
        original_write = language._write
        failed = False

        def write(path, value, **options):
            nonlocal failed
            if Path(path) == self.path("niri") and not failed:
                failed = True
                raise OSError("simulated disk failure")
            return original_write(path, value, **options)

        with patch.object(language, "_write", side_effect=write), self.assertRaises(OSError):
            self.apply()
        self.assertEqual(self.state.read_text(), preferences)
        for key in ("niri", "environment"):
            self.assertEqual(self.path(key).read_text(), "# original " + key + "\n")
        self.assertFalse(self.state.with_name("language-backup.json").exists())

    def test_symlink_managed_file_is_never_followed(self):
        target = self.root / "foreign"
        target.write_text("foreign data")
        self.path("environment").parent.mkdir(parents=True)
        self.path("environment").symlink_to(target)
        with self.assertRaises(OSError):
            self.apply()
        self.assertEqual(target.read_text(), "foreign data")

    def test_journal_cannot_redirect_restoration_to_arbitrary_files(self):
        self.apply()
        path = self.state.with_name("language-backup.json")
        data = json.loads(path.read_text())
        data["files"]["niri"]["path"] = str(self.root / "unrelated")
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            language.restore(**self.options)

    def test_launch_environment_removes_overrides_and_preserves_other_variables(self):
        self.apply()
        source = {"LANG": "C", "LC_ALL": "C", "LANGUAGE": "en", "LC_TIME": "de_DE.UTF-8", "PATH": "/usr/bin", "WAYLAND_DISPLAY": "wayland-1"}
        result = language.session_environment(state_path=self.state, environ=source)
        self.assertEqual(result, {"LANG": "zh_CN.UTF-8", "PATH": "/usr/bin", "WAYLAND_DISPLAY": "wayland-1"})
        self.assertEqual(source["LC_ALL"], "C")

    def test_unconfigured_launch_environment_is_unchanged(self):
        source = {"LANG": "C", "LC_ALL": "en_US.UTF-8"}
        self.assertEqual(language.session_environment(state_path=self.state, environ=source), source)

    def test_session_sync_updates_future_activation_without_persistent_lc_all(self):
        with patch.object(language, "_run", return_value="") as run:
            result = language.sync_session("en_US.UTF-8")
        self.assertFalse(result["warnings"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["systemctl", "--user", "unset-environment", *language.OVERRIDES])
        self.assertEqual(commands[1], ["systemctl", "--user", "set-environment", "LANG=en_US.UTF-8"])
        self.assertIn("LC_ALL=", commands[2])
        self.assertIn("LANGUAGE=", commands[2])

    def test_session_sync_reports_failure_and_continues_other_targets(self):
        with patch.object(language, "_run", side_effect=[RuntimeError("no user manager"), "", ""]) as run:
            result = language.sync_session("zh_CN.UTF-8")
        self.assertEqual(result["warnings"], ["no user manager"])
        self.assertEqual(run.call_count, 3)

    def test_system_change_is_explicit_validated_and_authenticates_without_shell(self):
        with patch.object(language, "_run", return_value="") as run:
            result = language.apply_system_locale("zh_CN.utf8")
        run.assert_called_once_with(["pkexec", "/usr/bin/localectl", "set-locale", "LANG=zh_CN.UTF-8"], timeout=120)
        self.assertTrue(result["requires_login"])
        with self.assertRaises(ValueError):
            language.apply_system_locale("fr_FR.UTF-8")
        self.assertFalse(self.state.exists())

    def test_read_state_reports_installed_language_and_quoted_system_default(self):
        system_path = self.root / "locale.conf"
        system_path.write_text('# comment\nLANG="en_US.UTF-8" # language\nLC_TIME=de_DE.UTF-8\n')
        with patch.dict(os.environ, {"LANG": "zh_CN.UTF-8", "LC_ALL": "C"}, clear=True):
            state = language.read_state(state_path=self.state, system_path=system_path)
        self.assertEqual(state["system_locale"], "en_US.UTF-8")
        self.assertEqual(state["session_locale"], "zh_CN.UTF-8")
        self.assertEqual(state["overrides"], {"LC_ALL": "C"})
        self.assertFalse(state["missing_common"])
        self.run_mock.assert_not_called()

    def test_restore_saved_does_nothing_without_user_choice(self):
        result = language.restore_saved(**self.apply_options)
        self.assertEqual(result["locale"], "")
        self.assertFalse(self.path("environment").exists())
        self.run_mock.assert_not_called()

    def test_restore_saved_reapplies_chosen_locale_without_changing_system(self):
        self.apply()
        result = language.restore_saved(**self.apply_options)
        self.assertEqual(result["locale"], "zh_CN.UTF-8")
        self.run_mock.assert_not_called()

    def test_restore_saved_repairs_deleted_managed_user_file(self):
        self.apply()
        self.path("environment").unlink()
        result = language.restore_saved(**self.apply_options)
        self.assertEqual(result["locale"], "zh_CN.UTF-8")
        self.assertIn("LANG=zh_CN.UTF-8", self.path("environment").read_text())
        self.run_mock.assert_not_called()

    def test_interrupted_first_apply_can_restore_still_original_files(self):
        original = "// original placeholder\n"
        self.write(self.path("niri"), original)
        self.apply()
        journal_path = self.state.with_name("language-backup.json")
        journal = json.loads(journal_path.read_text())
        for key, record in journal["files"].items():
            record["pending"] = record["applied"]
            language._write(self.path(key), record["before"])
        journal_path.write_text(json.dumps(journal))
        result = language.restore(**self.options)
        self.assertFalse(result["conflicts"])
        self.assertEqual(self.path("niri").read_text(), original)
        self.assertFalse(self.path("environment").exists())
        self.assertFalse(journal_path.exists())


if __name__ == "__main__":
    unittest.main()
