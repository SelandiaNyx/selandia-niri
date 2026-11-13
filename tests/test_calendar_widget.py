"""Unit tests for LocalizedCalendar widget navigation, boundary clamping, and interaction."""
from __future__ import annotations

import datetime
from pathlib import Path
import sys
import unittest

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
from calendar_widget import LocalizedCalendar, _days_in_month, _clamp


class TestLocalizedCalendar(unittest.TestCase):
    def setUp(self):
        self.cal = LocalizedCalendar(year=2026, month=10, day=12)  # November 12, 2026 (0-based month=10)

    def test_initial_date(self):
        self.assertEqual(self.cal.get_date(), (2026, 10, 12))
        self.assertEqual(self.cal.year, 2026)
        self.assertEqual(self.cal.month, 10)
        self.assertEqual(self.cal.day, 12)

    def test_days_in_month(self):
        self.assertEqual(_days_in_month(2026, 2), 28)
        self.assertEqual(_days_in_month(2024, 2), 29)  # leap year
        self.assertEqual(_days_in_month(2026, 11), 30)
        self.assertEqual(_days_in_month(2026, 12), 31)

    def test_clamp_helper(self):
        self.assertEqual(_clamp(15, 1, 31), 15)
        self.assertEqual(_clamp(0, 1, 31), 1)
        self.assertEqual(_clamp(35, 1, 31), 31)

    def test_month_navigation_forward_and_backward(self):
        self.cal._navigate_month(1)
        self.assertEqual(self.cal.get_date(), (2026, 11, 12))
        self.cal._navigate_month(1)
        self.assertEqual(self.cal.get_date(), (2027, 0, 12))  # wrapped to Jan 2027
        self.cal._navigate_month(-2)
        self.assertEqual(self.cal.get_date(), (2026, 10, 12))

    def test_select_day_and_signal(self):
        signals = []
        self.cal.connect("day-selected", lambda _: signals.append(True))
        self.cal.select_day(25)
        self.assertEqual(self.cal.day, 25)
        self.assertTrue(signals)

    def test_key_press_home_and_end(self):
        event = Gdk.EventKey()
        event.type = Gdk.EventType.KEY_PRESS
        event.state = 0
        event.keyval = Gdk.KEY_Home
        handled = self.cal._on_key_press(self.cal, event)
        self.assertTrue(handled)
        self.assertEqual(self.cal.day, 1)

        event.keyval = Gdk.KEY_End
        handled = self.cal._on_key_press(self.cal, event)
        self.assertTrue(handled)
        self.assertEqual(self.cal.day, 30)  # November has 30 days

    def test_key_press_arrows(self):
        self.cal.select_day(15)
        event = Gdk.EventKey()
        event.type = Gdk.EventType.KEY_PRESS
        event.state = 0
        event.keyval = Gdk.KEY_Left
        self.cal._on_key_press(self.cal, event)
        self.assertEqual(self.cal.day, 14)

        event.keyval = Gdk.KEY_Right
        self.cal._on_key_press(self.cal, event)
        self.assertEqual(self.cal.day, 15)

    def test_plain_scroll_propagates_without_changing_month(self):
        event = Gdk.EventScroll()
        event.direction = Gdk.ScrollDirection.DOWN
        event.state = 0
        self.assertFalse(self.cal._on_scroll(self.cal, event))
        self.assertEqual(self.cal.get_date(), (2026, 10, 12))

    def test_control_scroll_changes_month(self):
        event = Gdk.EventScroll()
        event.direction = Gdk.ScrollDirection.DOWN
        event.state = Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(self.cal._on_scroll(self.cal, event))
        self.assertEqual(self.cal.get_date(), (2026, 11, 12))
        event.direction = Gdk.ScrollDirection.UP
        self.assertTrue(self.cal._on_scroll(self.cal, event))
        self.assertEqual(self.cal.get_date(), (2026, 10, 12))


if __name__ == "__main__":
    unittest.main()
