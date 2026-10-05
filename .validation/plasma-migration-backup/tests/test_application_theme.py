"""Theme lifecycle tests use private configuration trees and fake GSettings."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
import application_theme as theme


class FakeDesktop:
    def __init__(self):
        self.values = {key: repr("previous " + key) for key in theme.GSETTINGS_KEYS}
        self.defaults = {key: repr("default " + key) for key in theme.GSETTINGS_KEYS}
        self.fail = None

    def get(self, key):
        return self.values.get(key, self.defaults[key])

    def user(self, key):
        return self.values.get(key)

    def set(self, key, value):
        if key == self.fail:
            self.fail = None
            raise RuntimeError("simulated dconf write failure")
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value


class ApplicationThemeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="selandia-app-theme-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / "config"
        self.state = self.root / "state/application-theme.json"
        self.data = self.root / "data"
        self.desktop = FakeDesktop()
        self.options = dict(config_home=self.home, state_path=self.state, data_dir=self.data,
                            desktop=self.desktop, notify=False)
        self.restore_options = {key: value for key, value in self.options.items() if key != "data_dir"}
        for mode in ("Breeze-Dark", "Breeze"):
            path = self.data / "themes" / mode / "gtk-3.0/gtk.css"
            path.parent.mkdir(parents=True)
            path.write_text("/* theme */")
        for icon in ("breeze-dark", "breeze"):
            path = self.data / "icons" / icon / "index.theme"
            path.parent.mkdir(parents=True)
            path.write_text("[Icon Theme]\n")
        for scheme, rgb in (("BreezeDark", "32,35,38"), ("BreezeLight", "239,240,241")):
            path = self.data / "color-schemes" / (scheme + ".colors")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"[Colors:Window]\nBackgroundNormal={rgb}\n[Colors:Header][Inactive]\nBackgroundNormal={rgb}\n[General]\nName=not copied\n")

    def write(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def files(self):
        return {str(path.relative_to(self.home)): path.read_bytes() for path in self.home.rglob("*") if path.is_file()}

    def test_dark_and_light_sync_installed_gtk_qt_portal_and_fonts(self):
        for mode, gtk, scheme, prefer in (("dark", "Breeze-Dark", "BreezeDark", "prefer-dark"),
                                          ("light", "Breeze", "BreezeLight", "prefer-light")):
            with self.subTest(mode=mode):
                result = theme.apply_mode({"color_mode": mode, "font": "Noto Sans CJK SC", "font_size": 13}, **self.options)
                self.assertEqual(result["mode"], mode)
                self.assertFalse(result["warnings"])
                source = (self.home / "gtk-3.0/settings.ini").read_text()
                self.assertIn("gtk-theme-name=" + gtk, source)
                self.assertIn("gtk-font-name=Noto Sans CJK SC 13", source)
                self.assertEqual(self.desktop.get("color-scheme"), repr(prefer))
                qt = (self.home / "kdeglobals").read_text()
                self.assertIn("ColorScheme=" + scheme, qt)
                self.assertIn("[Colors:Header][Inactive]", qt)
                self.assertNotIn("not copied", qt)
                self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_apply_preserves_unrelated_settings_and_comments(self):
        self.write("gtk-3.0/settings.ini", "# comment\n[Settings]\ngtk-cursor-theme-name=Mine\ngtk-im-module=fcitx\n[Other]\nCustom=keep\n")
        self.write("kdeglobals", "[General]\nBrowserApplication=firefox.desktop\n[Custom]\nUntouched=yes\n")
        theme.apply_mode({}, **self.options)
        self.assertIn("gtk-im-module=fcitx", (self.home / "gtk-3.0/settings.ini").read_text())
        self.assertIn("# comment", (self.home / "gtk-3.0/settings.ini").read_text())
        self.assertIn("BrowserApplication=firefox.desktop", (self.home / "kdeglobals").read_text())
        self.assertIn("Untouched=yes", (self.home / "kdeglobals").read_text())

    def test_restore_exact_original_files_and_gsettings_after_many_changes(self):
        self.write("gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name = Original\ngtk-theme-name=Other\n# kept\n")
        self.write("kdeglobals", "[General]\nColorScheme=Custom\n")
        before = self.files()
        preferences = dict(self.desktop.values)
        for mode in ("dark", "light", "dark"):
            theme.apply_mode({"color_mode": mode}, **self.options)
        theme.restore(**self.restore_options)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.desktop.values, preferences)
        self.assertFalse(self.state.exists())

    def test_restore_preserves_later_user_edits_to_managed_and_unrelated_keys(self):
        self.write("gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name=Original\ngtk-font-name=Old 11\n")
        theme.apply_mode({}, **self.options)
        path = self.home / "gtk-3.0/settings.ini"
        path.write_text(path.read_text().replace("gtk-theme-name=Breeze-Dark", "gtk-theme-name=NewUserTheme") + "user-setting=retained\n")
        self.desktop.set("color-scheme", repr("prefer-light"))
        result = theme.restore(**self.restore_options)
        self.assertIn("gtk-theme-name=NewUserTheme", path.read_text())
        self.assertIn("gtk-font-name=Old 11", path.read_text())
        self.assertIn("user-setting=retained", path.read_text())
        self.assertEqual(self.desktop.get("color-scheme"), repr("prefer-light"))
        self.assertIn("GSettings: color-scheme", result["preserved"])

    def test_reapply_tracks_intervening_user_edits_as_new_restore_baseline(self):
        self.write("gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name=Original\n")
        theme.apply_mode({}, **self.options)
        path = self.home / "gtk-3.0/settings.ini"
        path.write_text(path.read_text().replace("gtk-theme-name=Breeze-Dark", "gtk-theme-name=LaterChoice") + "unrelated=kept\n")
        self.desktop.set("font-name", repr("User changed font 10"))
        theme.apply_mode({"color_mode": "light"}, **self.options)
        theme.restore(**self.restore_options)
        self.assertIn("gtk-theme-name=LaterChoice", path.read_text())
        self.assertIn("unrelated=kept", path.read_text())
        self.assertEqual(self.desktop.get("font-name"), repr("User changed font 10"))

    def test_failed_gsettings_write_rolls_back_files_and_preferences(self):
        self.write("gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name=Original\n")
        before = self.files()
        preferences = dict(self.desktop.values)
        self.desktop.fail = "font-name"
        with self.assertRaises(RuntimeError):
            theme.apply_mode({}, **self.options)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.desktop.values, preferences)
        self.assertFalse(self.state.exists())

    def test_failed_reapply_restores_previous_journal_and_values(self):
        theme.apply_mode({}, **self.options)
        before = self.files()
        state = self.state.read_bytes()
        preferences = dict(self.desktop.values)
        self.desktop.fail = "gtk-theme"
        with self.assertRaises(RuntimeError):
            theme.apply_mode({"color_mode": "light"}, **self.options)
        self.assertEqual(self.files(), before)
        self.assertEqual(self.desktop.values, preferences)
        self.assertEqual(self.state.read_bytes(), state)

    def test_process_death_during_reapply_can_restore_exact_originals(self):
        """Kill the writer after real commits, so exception rollback cannot help."""
        self.write("gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name=Original\n")
        self.write("gtk-4.0/gtk.css", "/* GTK colors generated with Matugen */\n@define-color accent_color blue;\n")
        original = self.files()
        preferences = dict(self.desktop.values)
        script = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from test_application_theme import FakeDesktop, theme
home, state, data, gs_path = map(Path, sys.argv[2:6])
phase = sys.argv[6]
class DiskDesktop(FakeDesktop):
    def __init__(self):
        super().__init__()
        self.values = json.loads(gs_path.read_text())
    def set(self, key, value):
        super().set(key, value)
        gs_path.write_text(json.dumps(self.values))
        if phase == "gsettings":
            os._exit(73)
commit = theme.appearance._commit
def interrupted(files, **options):
    if state in files:
        commit(files, **options)
        if phase == "journal":
            os._exit(73)
    elif phase == "partial-files":
        path = next(iter(files))
        commit({path: files[path]}, **options)
        os._exit(73)
    else:
        commit(files, **options)
        if phase == "files":
            os._exit(73)
theme.appearance._commit = interrupted
theme.apply_mode({"color_mode": "light"}, config_home=home, state_path=state,
                 data_dir=data, desktop=DiskDesktop(), notify=False)
'''
        gs_path = self.root / "desktop.json"
        for phase, reapply in (("journal", False), ("partial-files", False), ("files", False),
                               ("gsettings", False), ("partial-files", True)):
            with self.subTest(phase=phase, reapply=reapply):
                theme.apply_mode({"color_mode": "dark"}, **self.options)
                gs_path.write_text(json.dumps(self.desktop.values))
                result = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "tests"),
                                         str(self.home), str(self.state), str(self.data), str(gs_path), phase],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
                self.desktop.values = json.loads(gs_path.read_text())
                if reapply:
                    theme.apply_mode({"color_mode": "dark"}, **self.options)
                theme.restore(**self.restore_options)
                self.assertEqual(self.files(), original)
                self.assertEqual(self.desktop.values, preferences)

    def test_successful_apply_does_not_claim_previous_mode_after_user_changes_it(self):
        theme.apply_mode({"color_mode": "dark"}, **self.options)
        theme.apply_mode({"color_mode": "light"}, **self.options)
        state = json.loads(self.state.read_text())
        self.assertNotIn("pending_applied", state["gsettings"]["color-scheme"])
        self.assertNotIn("pending_text", state["files"]["gtk-3.0/settings.ini"])
        self.desktop.set("color-scheme", repr("prefer-dark"))
        theme.restore(**self.restore_options)
        self.assertEqual(self.desktop.get("color-scheme"), repr("prefer-dark"))

    def test_failed_final_journal_commit_rolls_back_current_values(self):
        theme.apply_mode({"color_mode": "dark"}, **self.options)
        original = self.files()
        preferences = dict(self.desktop.values)
        state = self.state.read_bytes()
        commit = theme.appearance._commit
        journal_writes = 0

        def fail_final_journal(files, **options):
            nonlocal journal_writes
            if self.state in files:
                journal_writes += 1
                if journal_writes == 2:
                    raise OSError("simulated journal write failure")
            return commit(files, **options)

        with patch.object(theme.appearance, "_commit", side_effect=fail_final_journal), self.assertRaises(OSError):
            theme.apply_mode({"color_mode": "light"}, **self.options)
        self.assertEqual(self.files(), original)
        self.assertEqual(self.desktop.values, preferences)
        self.assertEqual(self.state.read_bytes(), state)

    def test_unset_gsettings_values_are_reset_not_replaced_with_schema_defaults(self):
        self.desktop.values.clear()
        theme.apply_mode({}, **self.options)
        theme.restore(**self.restore_options)
        self.assertEqual(self.desktop.values, {})

    def test_custom_gtk_css_is_reported_and_left_untouched(self):
        path = self.write("gtk-4.0/gtk.css", "/* user's custom theme */")
        result = theme.apply_mode({}, **self.options)
        self.assertTrue(any("Custom GTK CSS" in warning for warning in result["warnings"]))
        self.assertEqual(path.read_text(), "/* user's custom theme */")
        theme.restore(**self.restore_options)
        self.assertEqual(path.read_text(), "/* user's custom theme */")

    def test_old_matugen_overrides_are_backed_up_disabled_and_restored_exactly(self):
        original = "/* GTK colors generated with Matugen */\n@define-color window_bg_color #000;\n"
        paths = [self.write(relative, original) for relative in theme.CSS_FILES]
        result = theme.apply_mode({}, **self.options)
        self.assertEqual(result["migrated_css"], list(theme.CSS_FILES))
        self.assertFalse(result["warnings"])
        for path in paths:
            self.assertEqual(path.read_text(), theme.MIGRATED_CSS)
        state = theme.read_state(config_home=self.home, state_path=self.state, desktop=self.desktop)
        self.assertFalse(state["warnings"])
        theme.apply_mode({"color_mode": "light"}, **self.options)
        theme.restore(**self.restore_options)
        for path in paths:
            self.assertEqual(path.read_text(), original)

    def test_user_css_replacing_migrated_matugen_file_is_preserved_on_restore(self):
        path = self.write("gtk-3.0/gtk.css", "/* GTK colors generated with Matugen */\n")
        theme.apply_mode({}, **self.options)
        path.write_text("/* New custom theme */")
        report = theme.apply_mode({"color_mode": "light"}, **self.options)
        self.assertTrue(report["warnings"])
        result = theme.restore(**self.restore_options)
        self.assertIn("gtk-3.0/gtk.css", result["preserved"])
        self.assertEqual(path.read_text(), "/* New custom theme */")

    def test_failed_apply_restores_original_matugen_css(self):
        original = "/* GTK colors generated with Matugen */\n@define-color accent_color blue;\n"
        path = self.write("gtk-4.0/gtk.css", original)
        self.desktop.fail = "gtk-theme"
        with self.assertRaises(RuntimeError):
            theme.apply_mode({}, **self.options)
        self.assertEqual(path.read_text(), original)

    def test_interrupted_file_commit_leaves_originals_and_no_new_journal(self):
        self.write("gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name=Original\n")
        before = self.files()
        replace = theme.os.replace
        failed = False

        def fail_once(source, destination):
            nonlocal failed
            if Path(destination) == self.home / "kdeglobals" and not failed:
                failed = True
                raise OSError("simulated disk error")
            return replace(source, destination)

        with patch.object(theme.os, "replace", side_effect=fail_once), self.assertRaises(OSError):
            theme.apply_mode({}, **self.options)
        self.assertEqual(self.files(), before)
        self.assertFalse(self.state.exists())

    def test_missing_themes_report_fallback_without_selecting_nonexistent_gtk_theme(self):
        options = dict(self.options, data_dir=self.root / "empty")
        result = theme.apply_mode({}, **options)
        self.assertIn("gtk-theme-name=Adwaita-dark", (self.home / "gtk-3.0/settings.ini").read_text())
        self.assertEqual(len(result["warnings"]), 2)

    def test_symlink_config_file_is_refused_without_mutation(self):
        external = self.root / "original.ini"
        external.write_text("do not change")
        self.home.mkdir()
        (self.home / "kdeglobals").symlink_to(external)
        with self.assertRaises(OSError):
            theme.apply_mode({}, **self.options)
        self.assertEqual(external.read_text(), "do not change")
        self.assertFalse(self.state.exists())

    def test_symlink_config_parent_is_refused(self):
        external = self.root / "unrelated"
        external.mkdir()
        self.home.mkdir()
        (self.home / "gtk-3.0").symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            theme.apply_mode({}, **self.options)
        self.assertFalse(list(external.iterdir()))

    def test_malformed_or_wrong_root_journal_is_refused(self):
        self.state.parent.mkdir()
        for content in ("invalid", json.dumps({"version": 1, "config_home": "/wrong", "files": {}, "gsettings": {}})):
            self.state.write_text(content)
            with self.assertRaises(ValueError):
                theme.apply_mode({}, **self.options)
            self.assertFalse(self.home.exists())

    def test_malformed_nested_journal_is_refused_before_mutating_any_files(self):
        theme.apply_mode({}, **self.options)
        original = self.files()
        preferences = dict(self.desktop.values)
        state = json.loads(self.state.read_text())
        state["files"]["kdeglobals"]["keys"]["General"]["font"]["before"] = "invalid"
        self.state.write_text(json.dumps(state))
        for action, options in ((theme.apply_mode, self.options), (theme.restore, self.restore_options)):
            with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                action({}, **options) if action == theme.apply_mode else action(**options)
            self.assertEqual(self.files(), original)
            self.assertEqual(self.desktop.values, preferences)

    def test_restore_without_journal_does_not_connect_to_desktop(self):
        with patch.object(theme, "DesktopSettings", side_effect=AssertionError("must not connect")):
            self.assertEqual(theme.restore(config_home=self.home, state_path=self.state)["restored"], [])

    def test_ini_nested_groups_duplicates_and_no_final_newline(self):
        source = "# keep\n[Colors:Header][Inactive]\nColor=a\nColor=b\n[Other]\nlast=yes"
        edited = theme._set_values(source, "Colors:Header][Inactive", "Color", ["new"])
        self.assertIn("# keep\n", edited)
        self.assertEqual(theme._values(edited, "Colors:Header][Inactive", "Color"), ["new"])
        self.assertTrue(edited.endswith("last=yes"))
        edited = theme._set_values(edited, "General", "font", ["Noto 12"])
        self.assertIn("last=yes\n\n[General]\nfont=Noto 12\n", edited)

    def test_command_reports_dconf_critical_even_when_exit_status_is_zero(self):
        from subprocess import CompletedProcess
        with patch.object(theme.subprocess, "run", return_value=CompletedProcess([], 0, "", "dconf-CRITICAL: failed to commit changes")):
            with self.assertRaises(RuntimeError):
                theme.DesktopSettings._run(["gsettings", "set"])


if __name__ == "__main__":
    unittest.main()
