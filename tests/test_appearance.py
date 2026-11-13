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
SPEC = importlib.util.spec_from_file_location("appearance", ROOT / "niri/shell/appearance.py")
appearance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(appearance)


def generated_roles(files):
    """Read the opaque generated roles back from the emitted GTK CSS."""
    return {name: value for name, value in re.findall(
        r"@define-color md3_(\w+) (#[0-9a-f]{6});", files["panel.css"])}


def color_channels(color):
    return tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))


def channel_luminance(channels):
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast_luminance(first, second):
    high, low = sorted((first, second), reverse=True)
    return (high + .05) / (low + .05)


def alpha_composite(color, opacity, under):
    """Independently model continuous alpha compositing over opaque channels."""
    channels = tuple(f * opacity + u * (1 - opacity)
                     for f, u in zip(color_channels(color), under))
    rounded = "#" + "".join(f"{round(channel * 255):02x}" for channel in channels)
    return rounded, channel_luminance(channels), channels


def secondary_surfaces(roles, opacity):
    """Generated surfaces with rounded 8-bit colour and continuous luminance."""
    surfaces = []
    for backdrop in ("#000000", "#ffffff"):
        under = color_channels(backdrop)
        glass_hex, glass_lum, glass = alpha_composite(roles["surface"], opacity, under)
        drawer_hex, drawer_lum, drawer = alpha_composite(
            roles["surface_container_low"], opacity, under)
        surfaces.extend((
            ("glass surface", glass_hex, glass_lum),
            ("low surface", drawer_hex, drawer_lum),
            ("high surface",) + alpha_composite(
                roles["surface_container_high"], opacity, under)[:2],
            ("standalone notification",) + alpha_composite(
                roles["surface_container_high"], .90, under)[:2],
            ("standalone notification hover",) + alpha_composite(
                roles["surface_container_highest"], .94, under)[:2],
            ("nested notification",) + alpha_composite(
                roles["surface_container_high"], .90, drawer)[:2],
            ("nested notification hover",) + alpha_composite(
                roles["surface_container_highest"], .94, drawer)[:2],
            ("panel card",) + alpha_composite(
                roles["surface_container"], .72, glass)[:2],
            ("panel tile",) + alpha_composite(
                roles["surface_container"], .55, glass)[:2],
            ("panel tabs",) + alpha_composite(
                roles["surface_container_low"], .65, glass)[:2],
        ))
    for name in ("surface", "surface_container_low", "surface_container",
                 "surface_container_high", "surface_container_highest"):
        surfaces.append((f"opaque {name}", roles[name],
                         channel_luminance(color_channels(roles[name]))))
    return surfaces


class AppearanceTests(unittest.TestCase):
    def test_nine_collections_have_complete_light_and_dark_palettes(self):
        self.assertEqual(len(appearance.PRESETS), 9)
        self.assertEqual(set(appearance.PRESETS), set(appearance.LIGHT_PRESETS))
        for preset in appearance.PRESETS:
            for mode in ("light", "dark"):
                with self.subTest(preset=preset, mode=mode):
                    files = appearance.render_files({"preset": preset, "color_mode": mode}, base=self.base)
                    self.assertEqual(set(files), set(appearance.GENERATED_FILES))
                    self.assertIn("inset 0 1px", files["panel.css"])
                    self.assertIn("inset 0 1px", files["swaync.css"])
                    self.assertIn('namespace="^(launcher|selandia-.*)$"', files["theme.kdl"])

    def test_default_secondary_text_reaches_4_5_on_rendered_composites(self):
        for preset in appearance.PRESETS:
            for mode in ("dark", "light"):
                files = appearance.render_files({"preset": preset, "color_mode": mode}, base=self.base)
                roles = generated_roles(files)
                variant = roles["on_surface_variant"]
                for surface, background, continuous in secondary_surfaces(roles, .92):
                    with self.subTest(preset=preset, mode=mode, surface=surface):
                        self.assertGreaterEqual(
                            appearance._contrast(variant, background), 4.55,
                            f"rounded {preset} {mode} {surface}: {variant} on {background}")
                        self.assertGreaterEqual(
                            contrast_luminance(appearance._luminance(variant), continuous), 4.55,
                            f"continuous {preset} {mode} {surface}: {variant}")

    def test_passing_secondary_role_stays_byte_identical(self):
        for preset in appearance.PRESETS:
            for mode in ("dark", "light"):
                roles = appearance.semantic_roles(
                    appearance.palette({"preset": preset, "color_mode": mode}), mode)
                roles["on_surface_variant"] = roles["on_surface"]
                before = dict(roles)
                for surface, background, continuous in secondary_surfaces(roles, .92):
                    with self.subTest(preset=preset, mode=mode, surface=surface):
                        self.assertGreaterEqual(
                            appearance._contrast(roles["on_surface_variant"], background), 4.5)
                        self.assertGreaterEqual(
                            contrast_luminance(appearance._luminance(roles["on_surface"]),
                                               continuous), 4.5)
                with self.subTest(preset=preset, mode=mode):
                    self.assertEqual(appearance._readable_secondary(roles, .92),
                                     roles["on_surface"])
                    self.assertEqual(roles, before)

    def test_seeded_wallpaper_secondary_reaches_4_5(self):
        adjusted = False
        for mode in ("dark", "light"):
            settings = {"preset": "glacier", "color_mode": mode, "opacity": .92,
                        "wallpaper_colors": True, "wallpaper_seed": "#ffff00"}
            files = appearance.render_files(settings, base=self.base)
            roles = generated_roles(files)
            semantic = appearance.semantic_roles(appearance.palette(settings), mode)
            adjusted |= roles["on_surface_variant"] != semantic["on_surface_variant"]
            for surface, background, continuous in secondary_surfaces(roles, .92):
                with self.subTest(mode=mode, surface=surface):
                    self.assertGreaterEqual(
                        appearance._contrast(roles["on_surface_variant"], background), 4.55,
                        f"seed rounded {mode} {surface}")
                    self.assertGreaterEqual(
                        contrast_luminance(appearance._luminance(roles["on_surface_variant"]),
                                           continuous), 4.55,
                        f"seed continuous {mode} {surface}")
        self.assertTrue(adjusted, "seeded case should exercise the correction")

    def test_low_opacity_stays_bounded_and_keeps_shadow_without_full_proof(self):
        for mode in ("dark", "light"):
            files = appearance.render_files(
                {"preset": "glacier", "color_mode": mode, "opacity": .20}, base=self.base)
            roles = generated_roles(files)
            semantic = appearance.semantic_roles(
                appearance.palette({"preset": "glacier", "color_mode": mode}), mode)
            self.assertEqual(roles["on_surface_variant"], roles["on_surface"])
            start = [int(semantic["on_surface_variant"][i:i + 2], 16) for i in (1, 3, 5)]
            anchor = [int(roles["on_surface"][i:i + 2], 16) for i in (1, 3, 5)]
            result = [int(roles["on_surface_variant"][i:i + 2], 16) for i in (1, 3, 5)]
            for lower, value, upper in zip(start, result, anchor):
                self.assertGreaterEqual(value, min(lower, upper))
                self.assertLessEqual(value, max(lower, upper))
            self.assertIn("0.200)", files["panel.css"])
            self.assertIn("Low-opacity legibility", files["panel.css"])
            self.assertIn("text-shadow:", files["panel.css"])

    def test_low_opacity_glyphs_have_crisp_outline_and_no_noise_without_raising_alpha(self):
        for opacity in (.20, .25, .30):
            files = appearance.render_files({"opacity": opacity}, base=self.base)
            self.assertIn(f", {opacity:.3f})", files["panel.css"])
            self.assertIn("1px 0 0", files["panel.css"])
            self.assertNotIn("0 1px 2px", files["panel.css"])
            panel_rule = files["theme.kdl"].split('match namespace="^selandia-.*$"',1)[1].split("\n}",1)[0]
            self.assertIn("noise 0", panel_rule)
            control_rule = files["theme.kdl"].split('title="^Selandia · control$"', 1)[1].split("\n}", 1)[0]
            self.assertIn("noise 0", control_rule)
        files = appearance.render_files({"opacity": .40}, base=self.base)
        self.assertIn("noise 0.02", files["theme.kdl"])


    def test_all_eighteen_palettes_parse_in_real_gtk3_css(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        for preset in appearance.PRESETS:
            for mode in ("light", "dark"):
                files = appearance.render_files({"preset": preset, "color_mode": mode}, base=self.base)
                for component, template in (("panel", None), ("eww", None), ("swaync", "swaync/style.css")):
                    with self.subTest(preset=preset, mode=mode, component=component):
                        text = files[component + ".css"]
                        if template:
                            text = (ROOT / "niri" / template).read_text() + "\n" + text.split("\n", 1)[1]
                        provider = Gtk.CssProvider()
                        provider.load_from_data(text.encode())

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="selandia-appearance-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.base = self.directory / "niri"
        self.state = self.directory / "state/appearance.json"
        for relative in ("fuzzel/fuzzel.ini", "swaylock/config", "swaync/config.json"):
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
        import i18n
        previous_lang = i18n.get_language()
        i18n.set_language("zh_CN")
        self.addCleanup(i18n.set_language, previous_lang)

        values = self.apply({"preset": "violet", "font": "思源黑体", "font_size": 15,
                             "mono_font": "Iosevka Term", "mono_size": 14, "opacity": 0.92})
        self.assertEqual(appearance.load_settings(state_path=self.state), values)
        expected_files = set(appearance.GENERATED_FILES) | {"swaync.json"}
        self.assertEqual(expected_files, {path.name for path in (self.base / "theme").iterdir()})
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        self.assertIn('font-family: "思源黑体"', (self.base / "theme/panel.css").read_text())
        self.assertIn("size = 14", (self.base / "theme/alacritty.toml").read_text())
        swaync = json.loads((self.base / "theme/swaync.json").read_text())
        self.assertEqual(swaync["control-center-width"], 386)
        self.assertEqual(swaync["control-center-width"] + 2 * (16 + 1), 420)
        self.assertIs(swaync["control-center-exclusive-zone"], True)
        for font_size in (12, 16, 20):
            configured = appearance.notification_config({**values, "font_size": font_size}, base=self.base)
            self.assertEqual(configured["control-center-margin-top"], 12)
            self.assertIs(configured["control-center-exclusive-zone"], True)
            self.assertEqual(configured["control-center-width"] + 2 * (16 + 1), 420)
        self.assertEqual(swaync["control-center-margin-top"], 12)
        self.assertEqual(swaync["control-center-margin-right"], 16)
        self.assertEqual(swaync["control-center-margin-bottom"], 16)
        self.assertEqual(swaync["control-center-margin-left"], 16)
        self.assertEqual(swaync["notification-window-width"], 420)
        self.assertEqual(swaync["widget-config"]["title"]["text"], "通知")
        self.assertEqual(swaync["widget-config"]["title"]["button-text"], "清空")
        self.assertEqual(swaync["widget-config"]["dnd"]["text"], "勿扰")
        self.assertEqual(swaync["text-empty"], "暂无通知")
        self.assertEqual(swaync["timeout"], 6)
        self.assertTrue(swaync["fit-to-screen"])
        self.assertFalse(swaync["layer-shell-cover-screen"])

        # Also validate explicit English rendering
        from ui_assets import render as render_ui_assets
        i18n.set_language("en_US")
        en_swaync = render_ui_assets(base=self.base, settings=values)["swaync.json"]
        self.assertEqual(en_swaync["widget-config"]["title"]["text"], "Notifications")
        self.assertEqual(en_swaync["widget-config"]["title"]["button-text"], "Clear")
        self.assertEqual(en_swaync["widget-config"]["dnd"]["text"], "Do not disturb")
        self.assertEqual(en_swaync["text-empty"], "All caught up")

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
        self.assertIn("eww.css", files)
        self.assertNotIn("waybar.css", files)
        self.assertNotIn("kitty.conf", files)


    def test_color_mode_and_motion_values_are_validated(self):
        for values in ({"color_mode": "auto"}, {"color_mode": None}, {"reduced_motion": "false"}, {"reduced_motion": 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                appearance.validate_settings(values)

    def run_restore_cli(self, contents=None):
        script = self.base / "shell/appearance.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        # Copy complete niri/shell sources into the private base tree
        for helper in (ROOT / "niri/shell").glob("*.py"):
            shutil.copyfile(helper, self.base / "shell" / helper.name)
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
        self.assertIn(appearance.PRESETS["violet"]["accent"], (self.base / "theme/eww.css").read_text())

    def test_restore_cli_without_preferences_does_not_create_state_or_assets(self):
        result, saved = self.run_restore_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(saved.parent.exists())
        self.assertFalse((self.base / "theme").exists())

    def test_restore_cli_preserves_invalid_preferences_and_current_assets(self):
        self.apply({"preset": "graphite"})
        original = (self.base / "theme/eww.css").read_bytes()
        result, saved = self.run_restore_cli("malformed prefs")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(saved.read_text(), "malformed prefs")
        self.assertEqual((self.base / "theme/eww.css").read_bytes(), original)

    def test_font_and_numeric_injection_rejected_before_writes(self):
        unsafe = ({"font": 'Inter"; color: red'}, {"mono_font": "Mono\ninclude other.conf"},
                  {"font": "Inter:size=999"}, {"font": "Iosevka\\u0022"}, {"font": "A\x00B"},
                  {"font": ""}, {"font": "A" * 81}, {"opacity": "0.8"}, {"opacity": True},
                  {"opacity": float("nan")}, {"mono_size": float("inf")}, {"font_size": 8},
                  {"mono_size": 25}, {"opacity": 0.19}, {"preset": []}, {"other": "value"})
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

    def test_twenty_percent_opacity_persists_without_resetting_other_preferences(self):
        values = {**appearance.DEFAULTS, "preset": "rose", "color_mode": "light", "opacity": .20, "font": "Noto Sans"}
        self.apply(values)
        self.assertEqual(appearance.load_settings(state_path=self.state), appearance.validate_settings(values))
        for filename in ("panel.css", "eww.css", "swaync.css"):
            self.assertIn("0.200)", (self.base / "theme" / filename).read_text())
        css = (self.base / "theme/panel.css").read_text()
        self.assertIn("Low-opacity legibility", css)
        self.assertIn("text-shadow:", css)

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
                self.assertIn("window.background, window", files["eww.css"])
                self.assertIn(".segment", files["eww.css"])
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
        from ui_assets import render as render_ui_assets
        expected_ui = render_ui_assets(base=self.base, settings=appearance.DEFAULTS)
        for name, value in expected_ui.items():
            self.assertEqual(json.loads((self.base / "theme" / name).read_text()), value)

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
