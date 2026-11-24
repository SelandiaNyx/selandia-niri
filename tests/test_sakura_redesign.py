"""Regression tests for the Sakura Nyan MD3 + anime frontend redesign."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
sys.path.insert(0, str(ROOT / "tools"))

import appearance
import bar_backend
import deploy
import i18n


class SakuraRedesignTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(None)

    def test_defaults_and_anime_presets_lead_picker(self):
        self.assertEqual(appearance.DEFAULTS["preset"], "gemini")
        self.assertEqual(appearance.DEFAULTS["font_size"], 14)
        self.assertEqual(appearance.DEFAULTS["opacity"], 0.95)
        self.assertEqual(appearance.DEFAULTS["eye_care"], "comfort")
        self.assertEqual(appearance.DEFAULTS["mascot"], "gemini")
        self.assertEqual(appearance.TEXT_CONTRAST, 7.0)
        self.assertEqual(appearance.MD3_SHAPE, {"window": 28, "card": 24, "tile": 20, "pill": 16, "button": 14, "badge": 999})
        self.assertEqual(tuple(appearance.PRESETS)[:5], ("gemini", "sakura", "sora", "lavender", "mint"))
        i18n.set_language("zh_CN")
        self.assertEqual(appearance.preset_label("gemini"), "星辉双子")
        self.assertEqual(appearance.preset_label("sakura"), "樱花喵")
        self.assertEqual(appearance.preset_label("sora"), "晴空喵")
        i18n.set_language("en_US")
        self.assertEqual(appearance.preset_label("gemini"), "Gemini Starlight")
        self.assertEqual(appearance.preset_label("sakura"), "Sakura Nyan")
        self.assertEqual(appearance.preset_label("mint"), "Mint Nyan")

    def test_all_palettes_and_eye_care_modes_meet_aaa_text_and_secondary_contrast(self):
        for preset in appearance.PRESETS:
            for mode in ("dark", "light"):
                for eye_care in ("off", "comfort", "night_warm"):
                    with self.subTest(preset=preset, mode=mode, eye_care=eye_care):
                        p = appearance.palette({"preset": preset, "color_mode": mode, "eye_care": eye_care})
                        r = appearance.semantic_roles(p, mode)
                        self.assertGreaterEqual(appearance._contrast(r["on_surface"], r["surface"]), 7.0)
                        self.assertGreaterEqual(appearance._contrast(r["on_surface_variant"], r["surface_container_highest"]), 7.0)
                        self.assertGreaterEqual(appearance._contrast(r["on_primary"], r["primary"]), 7.0)
                        self.assertGreaterEqual(appearance._contrast(r["on_primary_container"], r["primary_container"]), 7.0)
                        self.assertGreaterEqual(appearance._contrast(r["on_secondary_container"], r["secondary_container"]), 7.0)
                        self.assertGreaterEqual(appearance._contrast(r["on_error_container"], r["error_container"]), 7.0)
                        self.assertGreaterEqual(appearance._contrast(r["secondary"], r["surface_container_highest"]), 4.5)

    def test_anime_assets_exist_render_and_are_registered_for_deploy(self):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        anime_dir = ROOT / "niri/assets/anime"
        expected_pngs = (
            "mascot-full.png", "mascot-gemini.png", "mascot-antigravity.png",
            "mascot-engineer.png", "mascot-obsidian.png", "mascot-peek.png",
            "mascot-avatar.png", "mascot-avatar-64.png", "mascot-avatar-gemini.png",
            "mascot-avatar-antigravity.png", "mascot-avatar-engineer.png",
            "mascot-avatar-obsidian.png", "mascot-sleepy.png", "mascot-thinking.png",
            "lock-bg.png", "lock-bg-light.png",
        )
        expected_svgs = (
            "paw.svg", "paw-symbolic.svg",
            "sakura.svg", "sakura-symbolic.svg",
            "star-sparkle.svg", "star-sparkle-symbolic.svg",
            "heart.svg", "heart-symbolic.svg",
            "cat-ears.svg", "cat-ears-symbolic.svg",
            "ribbon.svg", "ribbon-symbolic.svg",
            "cloud.svg", "cloud-symbolic.svg",
        )
        required = set(deploy.REQUIRED_SOURCES)
        self.assertIn("niri/assets/anime/README.md", required)
        self.assertTrue((anime_dir / "README.md").is_file())
        for filename in (*expected_pngs, *expected_svgs):
            path = anime_dir / filename
            with self.subTest(asset=filename):
                self.assertTrue(path.is_file())
                self.assertIn(f"niri/assets/anime/{filename}", required)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
                self.assertGreater(pixbuf.get_width(), 0)
                self.assertGreater(pixbuf.get_height(), 0)
                if filename.endswith("-symbolic.svg"):
                    self.assertIn("#000000", path.read_text())

    def test_three_segment_bar_island_clock_and_rust_right_marker(self):
        for width in (800, 960, 1600, 2560, 3840):
            for size in (12, 13, 16, 20):
                with self.subTest(width=width, size=size):
                    g = bar_backend.geometry(width, size)
                    self.assertLessEqual(g["left"] + 12 + g["island"] / 2, width / 2)
                    self.assertGreaterEqual(width - g["right"] - 12 - g["island"] / 2, width / 2)
                    self.assertLess(g["collapsed"], g["island"])
        rendered, _ = bar_backend.render([("DP-1", 1920)], size=13)
        left, right, center = rendered.split("(defwindow ")[1:]
        self.assertIn("mascot-avatar-64.png", left)
        self.assertIn("bar-right", right)
        self.assertNotIn("island-clock", right)
        self.assertIn("island-clock", center)
        self.assertIn("reduce-motion", left)
        self.assertIn("reduce-motion", right)
        self.assertIn("reduce-motion", center)
        rust_source = (ROOT / "niri/eww/input_region.rs").read_text()
        self.assertIn('b"bar-right\\0"', rust_source)

    def test_reduced_motion_and_zero_infinite_idle_keyframes(self):
        eww_css = appearance.render_files(dict(appearance.DEFAULTS))["eww.css"]
        cc_css = (ROOT / "niri/shell/control_center.css").read_text()
        self.assertNotIn("infinite;", eww_css)
        self.assertIn("animation: none;", eww_css)
        self.assertNotIn("infinite;", cc_css)
        self.assertIn("animation: none;", cc_css)

    def test_all_gtk4_stylesheets_parse_without_errors(self):
        files = appearance.render_files(dict(appearance.DEFAULTS))
        script = (
            "import gi, sys\n"
            "gi.require_version('Gtk', '4.0')\n"
            "from gi.repository import Gtk\n"
            "errs = []\n"
            "for p in sys.argv[1:]:\n"
            "    pr = Gtk.CssProvider()\n"
            "    pr.connect('parsing-error', lambda _p, _s, e, f=p: errs.append(f'{f}: {e.message}'))\n"
            "    pr.load_from_path(p)\n"
            "if errs:\n"
            "    sys.exit('\\n'.join(errs))\n"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", script,
             str(ROOT / "niri/swaync/style.css"),
             str(ROOT / "niri/theme/swaync.css"),
             str(ROOT / "niri/theme/anyrun.css"),
             str(ROOT / "niri/anyrun/style.css")],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sakura.svg", files["swaync.css"])
        self.assertIn("star-sparkle.svg", files["anyrun.css"])


if __name__ == "__main__":
    unittest.main()
