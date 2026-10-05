"""The interface size has one unit and an explicit conversion per backend (A8).

These assertions are about *meaning*: a logical pixel size becomes the matching
whole point size for GTK/Qt at 96 DPI, Fuzzel is pinned to pixels so no DPI is
applied twice, and the terminal's independent point size is never converted.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import font_scale


class ConversionTests(unittest.TestCase):
    def test_the_documented_pixel_sizes_map_to_the_expected_points(self):
        for logical_px, points in ((12, 9), (16, 12), (20, 15)):
            with self.subTest(logical_px=logical_px):
                self.assertEqual(font_scale.points(logical_px), points)
                self.assertEqual(font_scale.whole_points(logical_px), points)

    def test_gtk_and_qt_receive_the_same_converted_size(self):
        self.assertEqual(font_scale.pango("Noto Sans", 16), "Noto Sans 12")
        self.assertEqual(font_scale.qt("Noto Sans", 16), "Noto Sans,12,-1,5,50,0,0,0,0,0")

    def test_an_odd_pixel_size_rounds_to_whole_points(self):
        self.assertEqual(font_scale.points(13), 9.75)
        self.assertEqual(font_scale.whole_points(13), 10)

    def test_the_size_is_not_handed_over_unchanged(self):
        for logical_px in (12, 16, 20):
            with self.subTest(logical_px=logical_px):
                self.assertNotEqual(font_scale.whole_points(logical_px), logical_px,
                                    "a logical pixel size must never be written as a point size")

    def test_the_terminal_keeps_its_own_point_size(self):
        self.assertEqual(font_scale.pango_points("Iosevka Term", 14), "Iosevka Term 14")
        self.assertEqual(font_scale.qt_points("Iosevka Term", 14), "Iosevka Term,14,-1,5,50,0,0,0,0,0")
        self.assertEqual(font_scale.points_value(14), 14)

    def test_fuzzel_is_pinned_to_pixels_and_keeps_the_launcher_step(self):
        pattern = font_scale.fuzzel_pattern("Inter", font_scale.launcher_pixels(16))
        self.assertEqual(pattern, "Inter:pixelsize=17")
        self.assertNotIn(":size=", pattern)

    def test_the_lock_screen_keeps_its_larger_step_in_points(self):
        self.assertEqual(font_scale.lock_pixels(16), 32)
        self.assertEqual(font_scale.whole_points(font_scale.lock_pixels(16)), 24)

    def test_design_steps_scale_with_the_interface_size(self):
        for logical_px in (12, 16, 20):
            with self.subTest(logical_px=logical_px):
                self.assertEqual(font_scale.launcher_pixels(logical_px), logical_px + 1)
                self.assertEqual(font_scale.lock_pixels(logical_px), logical_px * 2)


class GeneratedFileTests(unittest.TestCase):
    """The generated files must carry the converted numbers, not the raw ones."""

    def setUp(self):
        import tempfile
        import appearance
        self.temporary = tempfile.TemporaryDirectory(prefix="selandia-font-scale-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        (self.base / "fuzzel").mkdir()
        (self.base / "fuzzel/fuzzel.ini").write_text(
            "[main]\nfont=x:size=1\nline-height=1\nplaceholder=Search applications\n[colors]\nbackground=000000ff\n")
        (self.base / "swaylock").mkdir()
        (self.base / "swaylock/config").write_text("color=000000\nfont=x\nfont-size=1\n")
        self.appearance = appearance

    def render(self, font_size):
        settings = dict(self.appearance.DEFAULTS, font_size=font_size)
        return self.appearance.render_files(settings, base=self.base)

    def test_the_launcher_uses_pixelsize_matching_the_interface_size(self):
        for font_size, expected in ((12, 13), (16, 17), (20, 21)):
            with self.subTest(font_size=font_size):
                fuzzel = self.render(font_size)["fuzzel.ini"]
                self.assertIn(f"pixelsize={expected}", fuzzel)
                self.assertNotIn(":size=", fuzzel)

    def test_the_lock_screen_size_is_a_converted_point_size(self):
        for font_size, expected in ((12, 18), (16, 24), (20, 30)):
            with self.subTest(font_size=font_size):
                lock = self.render(font_size)["swaylock.conf"]
                converted = f"font-size={expected}"
                self.assertIn(converted, lock)
                self.assertNotIn(f"font-size={int(font_size) * 2}", lock.replace(converted, ""),
                                 "the raw pixel figure must not be written as points")

    def test_the_panel_stylesheet_stays_in_logical_pixels(self):
        for font_size in (12, 16, 20):
            with self.subTest(font_size=font_size):
                panel = self.render(font_size)["panel.css"]
                self.assertIn(f"font-size: {font_size:g}px", panel)


if __name__ == "__main__":
    unittest.main()
