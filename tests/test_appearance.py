"""Appearance generation uses temporary trees, never the logged-in desktop."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
# appearance.py uses its sibling i18n module for single-language output.
sys.path.insert(0, str(ROOT / "niri/shell"))
import bar_layout
SPEC = importlib.util.spec_from_file_location("appearance", ROOT / "niri/shell/appearance.py")
appearance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(appearance)


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="selandia-appearance-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.base = self.directory / "niri"
        self.state = self.directory / "state/appearance.json"
        for relative in ("fuzzel/fuzzel.ini", "swaylock/config"):
            path = self.base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / "niri" / relative).read_bytes())

    def apply(self, values):
        return appearance.apply_settings(values, base=self.base, state_path=self.state)

    def snapshot(self):
        return {str(path.relative_to(self.directory)): path.read_bytes()
                for path in self.directory.rglob("*") if path.is_file() and path.name != "appearance.lock"}

    def test_missing_and_invalid_preferences_load_defaults(self):
        self.assertEqual(appearance.load_settings(state_path=self.state), appearance.DEFAULTS)
        self.state.parent.mkdir()
        for invalid in ("not json", "[]", '{"font_size": 300}', '{"preset": "missing"}'):
            with self.subTest(invalid=invalid):
                self.state.write_text(invalid)
                self.assertEqual(appearance.load_settings(state_path=self.state), appearance.DEFAULTS)

    def test_roundtrip_and_all_component_files(self):
        values = self.apply({"preset": "violet", "font": "思源黑体", "font_size": 15,
                             "mono_font": "Iosevka Term", "mono_size": 14, "opacity": 0.92})
        self.assertEqual(appearance.load_settings(state_path=self.state), values)
        self.assertEqual(set(appearance.GENERATED_FILES), {path.name for path in (self.base / "theme").iterdir()})
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertIn('font-family: "思源黑体"', (self.base / "theme/panel.css").read_text())
        self.assertIn("font_size 14", (self.base / "theme/kitty.conf").read_text())

    def test_old_preferences_gain_dark_mode_without_losing_user_choices(self):
        self.state.parent.mkdir()
        self.state.write_text(json.dumps({"preset": "violet", "font": "Noto Sans CJK SC", "opacity": 1}))
        values = appearance.load_settings(state_path=self.state)
        self.assertEqual(values["color_mode"], "dark")
        self.assertFalse(values["reduced_motion"])
        self.assertEqual(values["font"], "Noto Sans CJK SC")
        self.assertEqual(values["preset"], "violet")
        self.assertEqual(values["opacity"], 1)

    def test_light_palette_reaches_every_component_with_readable_text(self):
        for preset in appearance.PRESETS:
            palette = appearance.palette({"preset": preset, "color_mode": "light"})
            files = appearance.render_files({"preset": preset, "color_mode": "light"}, base=self.base)
            for name, text in files.items():
                background = palette["background"]
                rgb = ", ".join(str(int(background[offset:offset + 2], 16)) for offset in (1, 3, 5))
                self.assertTrue(background.lstrip("#") in text or f"rgba({rgb}," in text, name)
                self.assertNotIn(appearance.PRESETS[preset]["background"], text, name)
            self.assertLess(int(palette["ink"][1:3], 16), int(palette["background"][1:3], 16))

    def test_rendering_never_queries_the_compositor(self):
        """render_files is pure generation: it must not spawn niri or any process.

        A subprocess here also breaks every caller that mocks the process table.
        """
        def forbidden(*arguments, **options):
            raise AssertionError(f"render_files ran {arguments!r}")

        # Patching the module attribute catches every caller, including the bar
        # layout helper, which is where the compositor query used to hide.
        with patch("subprocess.run", forbidden):
            files = appearance.render_files(dict(appearance.DEFAULTS), base=self.base)
        self.assertIn("waybar.css", files)
        self.assertIn("/* Bar layout: ", files["waybar.css"])

    def test_the_layout_comes_from_the_generated_bar_configuration(self):
        (self.base / "theme").mkdir(exist_ok=True)
        compact = bar_layout.build(json.loads((ROOT / "niri/waybar/config.jsonc").read_text()), "compact")
        (self.base / "theme/waybar.jsonc").write_text(json.dumps(compact))
        rendered = appearance.render_files(dict(appearance.DEFAULTS), base=self.base)
        self.assertIn("/* Bar layout: compact */", rendered["waybar.css"])
        self.assertIn("#workspaces button.empty", rendered["waybar.css"])

    def test_color_mode_and_motion_values_are_validated(self):
        for values in ({"color_mode": "auto"}, {"color_mode": None}, {"reduced_motion": "false"}, {"reduced_motion": 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                appearance.validate_settings(values)

    def run_restore_cli(self, contents=None):
        script = self.base / "shell/appearance.py"
        script.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "niri/shell/appearance.py", script)
        # appearance.py renders single-language output, so its sibling helper
        # belongs to the copied tree as well.
        shutil.copyfile(ROOT / "niri/shell/i18n.py", self.base / "shell/i18n.py")
        # The bar stylesheet is layout-aware and the fonts are unit-converted,
        # so those helpers belong in the copied tree as well.
        for helper in ("bar_layout.py", "font_scale.py"):
            shutil.copyfile(ROOT / "niri/shell" / helper, self.base / "shell" / helper)
        state_home = self.directory / "cli-state"
        saved = state_home / "selandia-niri/appearance.json"
        if contents is not None:
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(contents)
        result = subprocess.run([sys.executable, "-B", str(script), "restore-saved"],
                                env=dict(os.environ, XDG_STATE_HOME=str(state_home)),
                                capture_output=True, text=True, timeout=10)
        return result, saved

    def test_restore_cli_keeps_preset_after_project_asset_replacement(self):
        result, saved = self.run_restore_cli('{"preset":"violet","font_size":15}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(saved.read_text())["preset"], "violet")
        self.assertIn(appearance.PRESETS["violet"]["accent"], (self.base / "theme/waybar.css").read_text())

    def test_restore_cli_without_preferences_does_not_create_state_or_assets(self):
        result, saved = self.run_restore_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(saved.parent.exists())
        self.assertFalse((self.base / "theme").exists())

    def test_restore_cli_preserves_invalid_preferences_and_current_assets(self):
        self.apply({"preset": "graphite"})
        original = (self.base / "theme/waybar.css").read_bytes()
        result, saved = self.run_restore_cli("malformed prefs")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved.read_text(), "malformed prefs")
        self.assertEqual((self.base / "theme/waybar.css").read_bytes(), original)

    def test_font_and_numeric_injection_rejected_before_writes(self):
        unsafe = ({"font": 'Inter"; color: red'}, {"mono_font": "Mono\ninclude other.conf"},
                  {"font": "Inter:size=999"}, {"font": "Iosevka\\u0022"}, {"font": "A\x00B"},
                  {"font": ""}, {"font": "A" * 81}, {"opacity": "0.8"}, {"opacity": True},
                  {"opacity": float("nan")}, {"mono_size": float("inf")}, {"font_size": 8},
                  {"mono_size": 25}, {"opacity": 0.64}, {"preset": []}, {"other": "value"})
        before = self.snapshot()
        for values in unsafe:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.apply(values)
            self.assertEqual(self.snapshot(), before)

    def test_valid_font_names_and_boundaries(self):
        for font in ("Noto Sans CJK SC", "JetBrainsMono Nerd Font", "思源黑体", "Iosevka-Term", "M+ 1p"):
            with self.subTest(font=font):
                values = appearance.validate_settings({"font": font, "font_size": 20, "mono_size": 8, "opacity": 1})
                self.assertEqual(values["font"], font)

    def test_preserves_original_sources_and_unknown_launcher_options(self):
        original = self.base / "fuzzel/fuzzel.ini"
        original.write_text(original.read_text().replace("[main]", "[main]\nuse-bold=yes\n# User's preference"))
        before = {path: path.read_bytes() for path in (original, self.base / "swaylock/config")}
        self.apply({"preset": "graphite"})
        for path, contents in before.items():
            self.assertEqual(path.read_bytes(), contents)
        generated = (self.base / "theme/fuzzel.ini").read_text()
        self.assertIn("use-bold=yes", generated)
        self.assertIn("# User's preference", generated)
        self.assertIn("[dmenu]\nexit-immediately-if-empty=yes", generated)
        self.assertIn("ignore-empty-password", (self.base / "theme/swaylock.conf").read_text())

    def test_presets_cover_all_components_without_absolute_paths(self):
        for preset, palette in appearance.PRESETS.items():
            with self.subTest(preset=preset):
                files = appearance.render_files({"preset": preset}, base=self.base)
                for name, contents in files.items():
                    self.assertIn(palette["accent"].lstrip("#"), contents, name)
                    self.assertNotIn(str(self.directory), contents)
                self.assertTrue(files["waybar.css"].startswith('@import "../waybar/style.css";'))
                self.assertTrue(files["swaync.css"].startswith('@import "../swaync/style.css";'))

    def test_panel_widget_rules_do_not_leak_into_native_dialogs(self):
        sources = [(ROOT / "niri/shell/style.css").read_text()]
        sources.extend(appearance.render_files({"preset": preset}, base=self.base)["panel.css"]
                       for preset in appearance.PRESETS)
        for source in sources:
            css = re.sub(r"/\*.*?\*/|@define-color[^;]*;", "", source, flags=re.S)
            for selectors in re.findall(r"(?:^|})([^{}]+)\{", css):
                for selector in selectors.split(","):
                    self.assertTrue(selector.strip().startswith(("window.glass-window", "dialog")),
                                    selector)
            self.assertIn("dialog button.suggested-action", css)
            self.assertIn("dialog treeview:selected", css)

    def test_panel_css_and_dialog_overrides_parse_in_gtk(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        self.assertEqual(Gtk.FontChooserDialog.get_css_name(), "dialog")
        Gtk.CssProvider().load_from_path(str(ROOT / "niri/shell/style.css"))
        for preset in appearance.PRESETS:
            for mode in ("dark", "light"):
                css = appearance.render_files({"preset": preset, "color_mode": mode}, base=self.base)["panel.css"]
                Gtk.CssProvider().load_from_data(css.encode())

    def test_restore_defaults_resets_settings_and_all_assets(self):
        self.apply({"preset": "violet", "font_size": 18})
        restored = appearance.restore_defaults(base=self.base, state_path=self.state)
        self.assertEqual(restored, appearance.DEFAULTS)
        expected = appearance.render_files(appearance.DEFAULTS, base=self.base)
        for name, contents in expected.items():
            self.assertEqual((self.base / "theme" / name).read_text(), contents)

    def test_symlink_destination_refused_without_touching_target(self):
        self.apply({})
        external = self.directory / "unrelated.css"
        external.write_text("do not alter")
        path = self.base / "theme/panel.css"
        path.unlink()
        path.symlink_to(external)
        with self.assertRaises(OSError):
            self.apply({"preset": "violet"})
        self.assertEqual(external.read_text(), "do not alter")
        self.assertTrue(path.is_symlink())

    def test_symlink_directory_refused(self):
        other = self.directory / "external-theme"
        other.mkdir()
        (self.base / "theme").symlink_to(other, target_is_directory=True)
        with self.assertRaises(OSError):
            self.apply({})
        self.assertFalse(list(other.iterdir()))

    def test_mid_transaction_failure_restores_old_assets_and_preferences(self):
        self.apply({"preset": "graphite"})
        before = self.snapshot()
        replace = os.replace
        calls = 0

        def fail_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 5:
                raise OSError("simulated failed file replacement")
            return replace(source, destination)

        with patch.object(appearance.os, "replace", side_effect=fail_once), self.assertRaises(OSError):
            self.apply({"preset": "violet"})
        self.assertEqual(self.snapshot(), before)

    def test_first_install_failure_removes_committed_new_assets(self):
        before = self.snapshot()
        replace = os.replace
        calls = 0

        def fail_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("simulated first apply failure")
            return replace(source, destination)

        with patch.object(appearance.os, "replace", side_effect=fail_once), self.assertRaises(OSError):
            self.apply({"preset": "violet"})
        self.assertEqual(self.snapshot(), before)

    def test_state_write_failure_restores_all_assets(self):
        self.apply({})
        before = self.snapshot()
        replace = os.replace
        failed = False

        def fail_state_once(source, destination):
            nonlocal failed
            if Path(destination) == self.state and not failed:
                failed = True
                raise OSError("simulated state replacement failure")
            return replace(source, destination)

        with patch.object(appearance.os, "replace", side_effect=fail_state_once), self.assertRaises(OSError):
            self.apply({"preset": "violet"})
        self.assertEqual(self.snapshot(), before)

    def test_replaces_every_duplicate_ini_option(self):
        source = "[main]\nfont=old\nfont=old2\n[colors]\ntext=abc\n"
        generated = appearance._replace_ini(source, "main", {"font": "Inter:size=13", "lines": 8})
        self.assertNotIn("old", generated)
        self.assertEqual(generated.count("font=Inter:size=13"), 2)
        self.assertIn("lines=8\n[colors]", generated)

    def test_environment_state_path(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(self.directory / "preferences")}):
            expected = self.directory / "preferences/selandia-niri/appearance.json"
            self.assertEqual(appearance.preferences_path(), expected)


if __name__ == "__main__":
    unittest.main()
