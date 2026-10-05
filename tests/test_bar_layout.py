"""The status bar must fit the real output instead of clipping (audit A3).

Layout selection is a pure decision over (logical width, font size), so it is
tested without a compositor. The module lists keep the required controls, the
live network rate moves into a tooltip, and the bar widths are bounded so changing
digits cannot push the right-hand modules off the output.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import bar_fit
import bar_layout

ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG = json.loads((ROOT / "niri/waybar/config.jsonc").read_text())


def outputs(payload, returncode=0):
    def run(*arguments, **options):
        return subprocess.CompletedProcess(arguments, returncode, json.dumps(payload), "")
    return run


class LayoutSelectionTests(unittest.TestCase):
    def test_the_reported_narrow_output_gets_the_compact_layout(self):
        # 1600x1000 at 150% is about 1067 logical pixels, where the wide bar
        # pushed the control-centre button off the output.
        self.assertEqual(bar_layout.select(width=1067, size=16), "compact")

    def test_acceptance_resolutions_and_font_sizes(self):
        # The acceptance is "the right-hand end stays complete and inside the
        # output": whatever is chosen must be measured to fit, and the compact
        # layout must always be available for the narrow logical widths.
        cases = {"1920x1080@150%": 1280, "2560x1440@200%": 1280, "3840x2160@150%": 2560}
        for size in (12, 16, 20):
            for name, width in cases.items():
                with self.subTest(size=size, output=name):
                    chosen = bar_layout.select(width=width, size=size)
                    self.assertIn(chosen, bar_layout.LAYOUTS)
                    self.assertTrue(bar_fit.fits(chosen, width, size),
                                    f"{name} at {size}px chose {chosen}, which does not fit")
                    if chosen == "compact":
                        self.assertTrue(bar_fit.fits("compact", width, size))

    def test_the_wide_layout_is_only_chosen_when_it_is_measured_to_fit(self):
        for size in (12, 16, 20):
            needed = bar_fit.required("wide", size)
            with self.subTest(size=size):
                self.assertEqual(bar_layout.select(width=needed, size=size), "wide")
                self.assertEqual(bar_layout.select(width=needed - 1, size=size), "compact")

    def test_unknown_geometry_keeps_the_full_layout(self):
        self.assertEqual(bar_layout.select(width=None, size=16, run=outputs({})), "wide")

    def test_the_narrowest_output_decides(self):
        payload = {"DP-1": {"logical": {"width": 2560}}, "eDP-1": {"logical": {"width": 1280}}}
        self.assertEqual(bar_layout.select(size=20, run=outputs(payload)), "compact")

    def test_mode_and_scale_are_used_when_logical_size_is_absent(self):
        payload = {"DP-1": {"scale": 2, "current_mode": 1,
                            "modes": [{"width": 1280}, {"width": 2560}]}}
        self.assertEqual(bar_layout.output_widths(run=outputs(payload)), [1280])

    def test_unavailable_niri_is_not_an_error(self):
        self.assertEqual(bar_layout.output_widths(run=outputs({}, returncode=1)), [])


class LayoutBuildTests(unittest.TestCase):
    def test_wide_modules_match_the_shipped_configuration(self):
        self.assertEqual(tuple(BASE_CONFIG["modules-left"]), bar_layout.WIDE_MODULES_LEFT)
        self.assertEqual(tuple(BASE_CONFIG["modules-right"]), bar_layout.WIDE_MODULES_RIGHT)

    def test_build_never_mutates_the_source_configuration(self):
        original = json.loads(json.dumps(BASE_CONFIG))
        bar_layout.build(BASE_CONFIG, "compact")
        bar_layout.build(BASE_CONFIG, "wide")
        self.assertEqual(BASE_CONFIG, original)

    def test_unknown_layout_is_rejected(self):
        with self.assertRaises(ValueError):
            bar_layout.build(BASE_CONFIG, "tiny")

    def test_compact_keeps_the_required_controls_and_drops_the_window_title(self):
        bar = bar_layout.build(BASE_CONFIG, "compact")
        for module in ("custom/launcher", "niri/workspaces", "pulseaudio",
                       "custom/notification", "custom/control"):
            self.assertIn(module, bar["modules-right"] + bar["modules-left"], module)
        for module in ("niri/window", "custom/ai", "custom/shortcuts", "custom/system"):
            self.assertNotIn(module, bar["modules-right"] + bar["modules-left"], module)

    def test_compact_shortens_the_clock(self):
        bar = bar_layout.build(BASE_CONFIG, "compact")
        self.assertEqual(bar["clock"]["format"], "{:%H:%M}")
        self.assertNotIn("%a", bar["clock"]["format"])
        self.assertIn("%Y", bar["clock"]["format-alt"])

    def test_compact_moves_the_live_rate_into_the_tooltip(self):
        bar = bar_layout.build(BASE_CONFIG, "compact")
        for key in ("format-wifi", "format-ethernet"):
            self.assertNotIn("bandwidth", bar["network"][key])
        self.assertIn("{bandwidthDownBytes}", bar["network"]["tooltip-format"])
        self.assertIn("{bandwidthUpBytes}", bar["network"]["tooltip-format"])
        self.assertIn("system monitor", bar["network"]["tooltip-format"])

    def test_wide_keeps_the_rate_and_bounds_its_width(self):
        bar = bar_layout.build(BASE_CONFIG, "wide")
        self.assertIn("{bandwidthDownBytes}", bar["network"]["format-wifi"])
        self.assertLessEqual(bar["network"]["min-length"], bar["network"]["max-length"])
        self.assertGreater(bar["network"]["min-length"], 0)

    def test_compact_also_bounds_the_rate_that_is_no_longer_shown(self):
        bar = bar_layout.build(BASE_CONFIG, "compact")
        self.assertLessEqual(bar["network"]["max-length"], bar["network"]["min-length"] + 4)


class LayoutCssTests(unittest.TestCase):
    def test_compact_hides_empty_workspaces(self):
        css = bar_layout.css("compact", 16)
        self.assertIn("#workspaces button.empty", css)
        self.assertIn("min-width: 0", css)

    def test_wide_keeps_empty_workspaces_visible(self):
        self.assertNotIn("#workspaces button.empty", bar_layout.css("wide", 16))

    def test_the_helper_module_never_takes_bar_space(self):
        for layout in bar_layout.LAYOUTS:
            with self.subTest(layout=layout):
                css = bar_layout.css(layout, 16)
                self.assertIn("#custom-layout { padding: 0; margin: 0; min-width: 0;", css)

    def test_the_network_band_grows_with_the_font(self):
        small = bar_layout.css("wide", 12)
        large = bar_layout.css("wide", 20)
        self.assertNotEqual(small, large)
        self.assertIn("min-width", small)
        self.assertIn("min-width", large)

    def test_every_layout_stylesheet_is_valid_gtk_css(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        for layout in bar_layout.LAYOUTS:
            for size in (12, 16, 20):
                with self.subTest(layout=layout, size=size):
                    provider = Gtk.CssProvider()
                    provider.load_from_data(bar_layout.css(layout, size).encode())

    def test_css_rejects_an_unknown_layout(self):
        with self.assertRaises(ValueError):
            bar_layout.css("tiny", 16)


class LayoutApplyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="selandia-bar-layout-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        (self.base / "theme").mkdir()

    def generated(self, layout):
        (self.base / "theme/waybar.jsonc").write_text(json.dumps(bar_layout.build(BASE_CONFIG, layout)))

    def test_a_changed_layout_rewrites_the_bar_once(self):
        with patch("ui_assets.write") as write:
            self.assertEqual(bar_layout.apply(base=self.base, width=1067, size=16), "compact")
            write.assert_called_once()
            self.generated("compact")
            bar_layout.apply(base=self.base, width=1067, size=16)
            write.assert_called_once()
            bar_layout.apply(base=self.base, width=2560, size=16)
            self.assertEqual(write.call_count, 2)

    def test_the_generated_configuration_decides_the_current_layout(self):
        self.assertIsNone(bar_layout.current_layout(base=self.base))
        (self.base / "theme/waybar.jsonc").write_text("{ not json")
        self.assertIsNone(bar_layout.current_layout(base=self.base))
        (self.base / "theme/waybar.jsonc").write_text(json.dumps({"modules-left": ["x"]}))
        self.assertIsNone(bar_layout.current_layout(base=self.base))
        self.generated("compact")
        self.assertEqual(bar_layout.current_layout(base=self.base), "compact")
        self.generated("wide")
        self.assertEqual(bar_layout.current_layout(base=self.base), "wide")

    def test_a_settled_layout_does_not_reload_the_bar_forever(self):
        self.generated("compact")
        with patch("ui_assets.write") as write, patch.object(bar_layout, "reload_bar") as reload_bar:
            bar_layout.apply(base=self.base, width=1067, size=16, notify=True)
        write.assert_not_called()
        reload_bar.assert_not_called()

    def test_the_changed_layout_asks_the_managed_bar_to_reload(self):
        with patch("ui_assets.write"), patch.object(bar_layout, "reload_bar") as reload_bar:
            bar_layout.apply(base=self.base, width=1067, size=16, notify=True)
        reload_bar.assert_called_once()
        # Reloading is only ever requested for the managed unit, and only when
        # the layout actually changed.
        reload_bar.reset_mock()
        self.generated("compact")
        with patch("ui_assets.write"):
            bar_layout.apply(base=self.base, width=1067, size=16, notify=True)
        reload_bar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
