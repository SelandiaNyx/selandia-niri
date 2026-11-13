"""Actual logical output dimensions govern enlarged panels and narrow layouts."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
from panel_geometry import dimensions


class PanelGeometryTests(unittest.TestCase):
    def test_control_expands_on_large_logical_outputs(self):
        self.assertEqual(dimensions("control", 3840, 2160), (1600, 1120))
        self.assertEqual(dimensions("control", 2560, 1440), (1536, 1120))

    def test_150_and_200_percent_outputs_fit_with_margins(self):
        for w, h in ((1280, 720), (1920, 1080), (1067, 667), (2560, 1440)):
            width, height = dimensions("control", w, h)
            self.assertLessEqual(width, w - 32)
            self.assertLessEqual(height, h - 80)

    def test_narrow_shortcut_and_control_branches_remain_reachable(self):
        for mode in ("shortcuts", "control"):
            self.assertLess(dimensions(mode, 640, 720)[0], 650)

    def test_tiny_outputs_never_get_an_invented_300_pixel_minimum(self):
        for mode in ("control", "shortcuts", "ai"):
            self.assertEqual(dimensions(mode, 240, 300), (208, 220))

    def test_sidebar_width_and_shortcut_width_remain_compatible(self):
        self.assertEqual(dimensions("ai", 2560, 1440)[0], 440)
        self.assertEqual(dimensions("shortcuts", 2560, 1440)[0], 860)
