"""Native Niri settings validate staged files and preserve unowned configuration."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import desktop_settings as desktop


class DesktopSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-desktop-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name) / "niri"
        (self.base / "conf").mkdir(parents=True)
        self.state = Path(temporary.name) / "state/settings.json"
        self.target = self.base / desktop.GENERATED
        self.target.write_text("// Placeholder\n")
        self.source = self.base / "conf/source.kdl"
        self.source.write_text('''input {
    keyboard { xkb { layout "us"; model "pc105"; }; repeat-delay 300; }
    mouse { accel-profile "flat"; middle-emulation; }
    touchpad { tap; dwt; natural-scroll; click-method "clickfinger"; }
}
layout { gaps 12; focus-ring { width 3; active-color "#112233"; }; }
cursor { xcursor-size 28; xcursor-theme "Example"; }
''')
        (self.base / "config.kdl").write_text('include "conf/source.kdl"\ninclude "conf/desktop-settings.kdl"\n')
        # A test fixture must never ask the live compositor to load itself.
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("NIRI_SOCKET", None)

    def values(self, group, **changes):
        result = {key: desktop.DEFAULTS[key] for key in desktop.GROUPS[group]}
        result.update(changes)
        return result

    def apply(self, group, **changes):
        return desktop.apply_settings(group, self.values(group, **changes), base=self.base, state_path=self.state)

    def test_reads_originals_without_writing(self):
        result = desktop.read_state(base=self.base, state_path=self.state)
        self.assertEqual(result["settings"]["keyboard_repeat_delay"], 300)
        self.assertEqual(result["settings"]["gaps"], 12)
        self.assertEqual(result["settings"]["focus_ring_width"], 3)
        self.assertEqual(result["settings"]["cursor_size"], 28)
        self.assertFalse(self.state.exists())

    def test_rejects_invalid_values_before_any_write_or_command(self):
        values = [self.values("desktop", gaps=True), self.values("desktop", gaps=float("nan")),
                  self.values("desktop", column_width=0), self.values("desktop", cursor_size=300),
                  self.values("desktop", column_center="unknown")]
        with patch.object(desktop, "_run") as command:
            for value in values:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    desktop.apply_settings("desktop", value, base=self.base, state_path=self.state)
            with self.assertRaises(ValueError):
                desktop.validate_settings("input", self.values("input", keyboard_layout='us"; spawn "evil'))
            command.assert_not_called()
        self.assertEqual(self.target.read_text(), "// Placeholder\n")
        self.assertFalse(self.state.exists())

    @unittest.skipUnless(shutil.which("niri"), "installed Niri parser required")
    def test_both_groups_validate_with_installed_niri_and_preserve_source(self):
        original = self.source.read_text()
        self.apply("input", keyboard_layout="us,de", keyboard_variant=",", mouse_left_handed=True)
        self.apply("desktop", gaps=24, focus_ring=False, border=True, focus_follows_mouse=False)
        contents = self.target.read_text()
        self.assertIn("middle-emulation", contents)
        self.assertIn('click-method "clickfinger"', contents)
        self.assertIn('model "pc105"', contents)
        self.assertEqual(contents.count("input {"), 1)
        self.assertEqual(self.source.read_text(), original)
        result = desktop.read_state(base=self.base, state_path=self.state)
        self.assertEqual(set(result["configured"]), {"input", "desktop"})
        self.assertEqual(result["settings"]["gaps"], 24)
        self.assertTrue(result["settings"]["mouse_left_handed"])
        desktop._run("validate", "--config", str(self.base / "config.kdl"))

    @unittest.skipUnless(shutil.which("niri"), "installed Niri parser required")
    def test_restore_one_group_retains_other_and_original_defaults(self):
        self.apply("input", mouse_accel_speed=.5)
        self.apply("desktop", gaps=20)
        result = desktop.restore_defaults("desktop", base=self.base, state_path=self.state)
        self.assertEqual(result["configured"], ["input"])
        self.assertEqual(result["settings"]["gaps"], 12)
        self.assertEqual(result["settings"]["mouse_accel_speed"], .5)
        self.assertNotIn("layout {", self.target.read_text())

    def test_failed_validation_does_not_replace_configuration(self):
        with patch.object(desktop, "_run", side_effect=RuntimeError("invalid fixture")):
            with self.assertRaisesRegex(RuntimeError, "invalid fixture"):
                self.apply("desktop", gaps=30)
        self.assertEqual(self.target.read_text(), "// Placeholder\n")
        self.assertFalse(self.state.exists())

    def test_manual_edits_are_preserved(self):
        with patch.object(desktop, "_run"):
            self.apply("desktop")
        prior_state = self.state.read_text()
        self.target.write_text("// User edit\nlayout { gaps 33; }\n")
        with self.assertRaises(RuntimeError):
            self.apply("desktop", gaps=20)
        self.assertIn("gaps 33", self.target.read_text())
        self.assertEqual(self.state.read_text(), prior_state)

    def test_edits_during_validation_preserve_target_and_saved_state(self):
        with patch.object(desktop, "_run"):
            self.apply("desktop", gaps=20)
        prior_state = self.state.read_bytes()
        manual = "// User edit during validation\nlayout { gaps 33; }\n"
        with patch.object(desktop, "_run", side_effect=lambda *args: self.target.write_text(manual)):
            with self.assertRaisesRegex(RuntimeError, "preserved|保留"):
                self.apply("desktop", gaps=30)
        self.assertEqual(self.target.read_text(), manual)
        self.assertEqual(self.state.read_bytes(), prior_state)

    def test_edit_between_initial_read_and_snapshot_is_preserved(self):
        identity = desktop._identity
        edited = False
        manual = "// User edit before snapshot\nlayout { gaps 33; }\n"
        def snapshot(path):
            nonlocal edited
            if path == self.target and not edited:
                edited = True
                self.target.write_text(manual)
            return identity(path)
        with patch.object(desktop, "_identity", side_effect=snapshot), patch.object(desktop, "_run") as command:
            with self.assertRaisesRegex(RuntimeError, "preserved|保留"):
                self.apply("desktop", gaps=30)
        self.assertEqual(self.target.read_text(), manual)
        command.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_identical_content_replacement_during_validation_is_preserved(self):
        old = self.target.read_bytes()
        def replace(*args):
            replacement = self.target.with_suffix(".replacement")
            replacement.write_bytes(old)
            replacement.replace(self.target)
        with patch.object(desktop, "_run", side_effect=replace):
            with self.assertRaisesRegex(RuntimeError, "preserved|保留"):
                self.apply("desktop", gaps=30)
        self.assertEqual(self.target.read_bytes(), old)
        self.assertFalse(self.state.exists())

    def test_saved_state_edit_during_validation_is_preserved(self):
        def edit(*args):
            self.state.parent.mkdir(parents=True, exist_ok=True)
            self.state.write_text('{"user":"new preference"}')
        with patch.object(desktop, "_run", side_effect=edit):
            with self.assertRaises(RuntimeError):
                self.apply("desktop", gaps=30)
        self.assertEqual(self.target.read_text(), "// Placeholder\n")
        self.assertEqual(self.state.read_text(), '{"user":"new preference"}')

    def test_reload_failure_preserves_later_manual_edit(self):
        manual = "// Edit during reload\nlayout { gaps 39; }\n"
        def command(*args):
            if args[0] == "msg":
                self.target.write_text(manual)
                raise RuntimeError("reload rejected")
        with patch.dict(os.environ, NIRI_SOCKET="/probe/socket"), patch.object(desktop, "_run", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "reload rejected"):
                self.apply("desktop", gaps=30)
        self.assertEqual(self.target.read_text(), manual)
        self.assertFalse(self.state.exists())

    def test_reload_failure_rolls_back_both_saved_and_generated_state(self):
        with patch.object(desktop, "_run"):
            self.apply("desktop", gaps=20)
        before = self.target.read_text(), self.state.read_text()
        def command(*args):
            if args[0] == "msg":
                raise RuntimeError("reload rejected")
            return ""
        with patch.dict(os.environ, NIRI_SOCKET="/probe/socket"), patch.object(desktop, "_run", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "reload rejected"):
                self.apply("desktop", gaps=30)
        self.assertEqual((self.target.read_text(), self.state.read_text()), before)

    def test_include_must_follow_original_options(self):
        (self.base / "config.kdl").write_text('include "conf/desktop-settings.kdl"\ninclude "conf/source.kdl"\n')
        with patch.object(desktop, "_run") as command:
            with self.assertRaises(RuntimeError):
                self.apply("desktop")
            command.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_custom_keymap_is_detected_and_never_overridden(self):
        self.source.write_text('input { keyboard { xkb { file "custom.xkb"; }; }; }\n')
        self.assertTrue(desktop.read_state(base=self.base, state_path=self.state)["custom_keymap"])
        with patch.object(desktop, "_run") as command:
            with self.assertRaises(ValueError):
                self.apply("input")
            command.assert_not_called()
        self.assertEqual(self.target.read_text(), "// Placeholder\n")

    def test_original_focus_rule_cannot_be_disabled_by_an_include(self):
        self.source.write_text('input { focus-follows-mouse max-scroll-amount="0%"; }\n')
        state = desktop.read_state(base=self.base, state_path=self.state)
        self.assertTrue(state["focus_from_source"])
        self.assertTrue(state["settings"]["focus_follows_mouse"])
        with patch.object(desktop, "_run") as command:
            with self.assertRaises(ValueError):
                self.apply("desktop", focus_follows_mouse=False)
            command.assert_not_called()
        self.assertEqual(self.target.read_text(), "// Placeholder\n")

    def test_missing_keyboard_layout_is_rejected_by_libxkbcommon(self):
        with patch.object(desktop, "_run") as command:
            with self.assertRaises(ValueError):
                self.apply("input", keyboard_layout="selandia_nonexistent_layout")
            command.assert_not_called()
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
