"""The bar width requirement is measured, not a magic number (audit A3).

These tests pin the model to the published acceptance geometry and to the real
stylesheet: the design font sizes used for measurement must be the ones the bar
actually renders, so the two cannot drift apart silently.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import bar_fit

ROOT = Path(__file__).resolve().parents[1]
STYLE = (ROOT / "niri/waybar/style.css").read_text()


class UnavailableMeasurer:
    available = False

    def width(self, text, size):  # pragma: no cover - must never be called
        raise AssertionError("width() used without an available font map")


def declared_font_size(selector):
    """The fixed font-size a module declares, or None when it inherits the base.

    Grouped selectors such as ``#pulseaudio, #battery { font-size: 11px }`` are
    common in this stylesheet, so every block's selector list is inspected.
    """
    for match in re.finditer(r"([^{}]+)\{([^}]*)\}", STYLE):
        selectors = [item.strip() for item in match.group(1).split(",")]
        if f"#{selector}" not in selectors:
            continue
        size = re.search(r"font-size:\s*([0-9.]+)px", match.group(2))
        if size:
            return float(size.group(1))
    return None


class MeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measurer = bar_fit.Measurer()
        if not cls.measurer.available:
            raise unittest.SkipTest("no font map available in this environment")

    def test_the_wide_layout_needs_more_room_than_the_compact_one(self):
        for size in (12, 16, 20):
            with self.subTest(size=size):
                wide = bar_fit.required("wide", size, measurer=self.measurer)
                compact = bar_fit.required("compact", size, measurer=self.measurer)
                self.assertGreater(wide, compact)

    def test_the_requirement_grows_with_the_interface_size(self):
        for layout in bar_fit.LAYOUTS:
            sizes = [bar_fit.required(layout, size, measurer=self.measurer) for size in (12, 16, 20)]
            self.assertEqual(sizes, sorted(sizes), layout)
            self.assertLess(sizes[0], sizes[-1])

    def test_the_reported_narrow_output_is_measured_to_need_the_compact_layout(self):
        # 1600x1000 at 150% is the 1067 logical pixels where the control-centre
        # button was clipped.
        self.assertEqual(bar_fit.choose(1067, 16, measurer=self.measurer), "compact")
        self.assertTrue(bar_fit.fits("compact", 1067, 16, measurer=self.measurer))

    def test_a_wide_output_keeps_the_full_layout(self):
        for width in (2560, 3840):
            for size in (12, 16, 20):
                with self.subTest(width=width, size=size):
                    self.assertEqual(bar_fit.choose(width, size, measurer=self.measurer), "wide")

    def test_the_chosen_layout_always_fits_the_output(self):
        for width in (900, 1067, 1280, 1600, 1920, 2560, 3840):
            for size in (12, 16, 20):
                with self.subTest(width=width, size=size):
                    chosen = bar_fit.choose(width, size, measurer=self.measurer)
                    self.assertTrue(bar_fit.fits(chosen, width, size, measurer=self.measurer),
                                    f"{chosen} was chosen but does not fit {width}px at {size}px")

    def test_the_boundary_is_exact(self):
        for layout in bar_fit.LAYOUTS:
            needed = bar_fit.required(layout, 16, measurer=self.measurer)
            with self.subTest(layout=layout):
                self.assertTrue(bar_fit.fits(layout, needed, 16, measurer=self.measurer))
                self.assertFalse(bar_fit.fits(layout, needed - 1, 16, measurer=self.measurer))

    def test_unknown_geometry_never_degrades_the_bar(self):
        self.assertEqual(bar_fit.choose(None, 16, measurer=self.measurer), "wide")

    def test_an_unknown_layout_is_rejected(self):
        with self.assertRaises(ValueError):
            bar_fit.required("tiny", 16, measurer=self.measurer)
        with self.assertRaises(ValueError):
            bar_fit.fits("tiny", 1000, 16, measurer=self.measurer)


class FallbackTests(unittest.TestCase):
    """A broken font stack must not stop the bar from choosing a layout."""

    def test_the_documented_constants_are_used_when_measurement_fails(self):
        self.assertIsNone(bar_fit.required("wide", 16, measurer=UnavailableMeasurer()))
        self.assertEqual(bar_fit.choose(1067, 16, measurer=UnavailableMeasurer()), "compact")
        self.assertEqual(bar_fit.choose(3840, 16, measurer=UnavailableMeasurer()), "wide")
        self.assertEqual(bar_fit.choose(None, 16, measurer=UnavailableMeasurer()), "wide")

    def test_choose_never_raises_on_a_measurer_that_breaks(self):
        class Broken:
            available = True

            def width(self, text, size):
                raise RuntimeError("font map disappeared")

        self.assertIsNone(bar_fit.required("wide", 16, measurer=Broken()))
        self.assertEqual(bar_fit.choose(3840, 16, measurer=Broken()), "wide")


class StylesheetAgreementTests(unittest.TestCase):
    """The model's design sizes must match what the stylesheet renders."""

    def test_design_font_sizes_match_the_shipped_stylesheet(self):
        expected = {"custom-launcher": 20.0, "custom-shortcuts": 16.0, "window": 11.0,
                    "pulseaudio": 11.0, "battery": 11.0, "network": 10.0, "custom-system": 10.0}
        for selector, size in expected.items():
            with self.subTest(selector=selector):
                self.assertEqual(declared_font_size(selector), size,
                                 f"#{selector} font-size changed; update bar_fit's table")
        modelled = {"custom/launcher": bar_fit.WIDE_LEFT[0][2],
                    "custom/shortcuts": bar_fit.WIDE_RIGHT[2][2],
                    "custom/system": bar_fit.WIDE_RIGHT[3][2],
                    "pulseaudio": bar_fit.WIDE_RIGHT[4][2],
                    "network": bar_fit.WIDE_RIGHT[5][2],
                    "battery": bar_fit.WIDE_RIGHT[6][2],
                    "custom/notification": bar_fit.WIDE_RIGHT[8][2],
                    "niri/window": bar_fit.WIDE_LEFT[2][2]}
        self.assertEqual(modelled["custom/launcher"], 20.0)
        self.assertEqual(modelled["custom/shortcuts"], 16.0)
        self.assertEqual(modelled["custom/system"], 10.0)
        self.assertEqual(modelled["pulseaudio"], 11.0)
        self.assertEqual(modelled["network"], 10.0)
        self.assertEqual(modelled["battery"], 11.0)
        self.assertEqual(modelled["custom/notification"], 16.0)
        self.assertEqual(modelled["niri/window"], 11.0)

    def test_the_scale_rule_matches_the_panel_stylesheet_rule(self):
        # appearance.py scales design sizes with size/12 for both surfaces.
        self.assertEqual(bar_fit.scale(20, 16), 20 * 16 / 12)
        self.assertEqual(bar_fit.scale(12, 12), 12)


if __name__ == "__main__":
    unittest.main()
