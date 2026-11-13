"""Unit tests for SettingsNavigation search filtering, category completeness, and keyboard navigation."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
from navigation_catalog import PAGES, PAGE_KEYS
from settings_navigation import SettingsNavigation


class DummyPanel:
    def __init__(self):
        self.control_stack = MagicMock()
        self.control_stack.get_visible_child_name.return_value = "quick"
        self.selected_tab = None

    def select_control_tab(self, key, focus=False):
        self.selected_tab = key


class TestSettingsNavigation(unittest.TestCase):
    def setUp(self):
        self.panel = DummyPanel()
        self.nav = SettingsNavigation(self.panel)
        self.addCleanup(self.nav.destroy)

    def test_eighteen_categories_registered(self):
        self.assertEqual(len(PAGE_KEYS), 18)
        self.assertEqual(len(self.nav.rows), 18)
        self.assertIn("notifications", self.nav.rows)
        self.assertIn("quick", self.nav.rows)
        self.assertIn("system", self.nav.rows)

    def test_search_filtering(self):
        self.nav.search.set_text("bluetooth")
        self.nav.filter()
        # Row for network should match ("bluetooth" is in keywords)
        matched_keys = [k for k, r in self.nav.rows.items() if self.nav.matches(r)]
        self.assertIn("network", matched_keys)
        self.assertNotIn("appearance", matched_keys)
        self.assertFalse(self.nav.empty.get_visible())

        # Non-matching search
        self.nav.search.set_text("xyznonexistentterm123")
        self.nav.filter()
        matched_keys = [k for k, r in self.nav.rows.items() if self.nav.matches(r)]
        self.assertEqual(len(matched_keys), 0)
        self.assertTrue(self.nav.empty.get_visible())

    def test_stop_search_clears_text(self):
        self.nav.search.set_text("wifi")
        self.assertEqual(self.nav.search.get_text(), "wifi")
        self.nav.search.emit("stop-search")
        self.assertEqual(self.nav.search.get_text(), "")

    def test_search_down_key_transfers_focus(self):
        self.nav.search.set_text("ethernet")
        event = Gdk.EventKey()
        event.type = Gdk.EventType.KEY_PRESS
        event.state = 0
        event.keyval = Gdk.KEY_Down
        handled = self.nav._on_search_key(self.nav.search, event)
        self.assertTrue(handled)
        self.assertEqual(self.panel.selected_tab, "network")
        self.assertEqual(self.nav.search.get_text(), "ethernet")


if __name__ == "__main__":
    unittest.main()
