"""Unit tests for MD3 drawer runtime geometry, motion lifecycle, and PageHost lazy/draft/lifecycle.

Scope: Pure unit tests for drawer geometry clamping/anchoring, PanelMotion deterministic lifecycle,
and PageHost cold-lazy / cached-draft / suspended-read hooks.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from niri.shell.panel_geometry import (
    DRAWER_BOTTOM_MARGIN,
    DRAWER_SIDE_MARGIN,
    DRAWER_TOP_GAP,
    DRAWER_WIDTHS,
    drawer_geometry,
    drawer_top_margin,
    reserved_bar_height,
)
from niri.shell.page_host import PageEntry, PageHost, PageMap, PageSpec
from niri.shell.panel_motion import PanelMotion


class FakeClock:
    def __init__(self, start_us=0):
        self.time_us = start_us

    def get_frame_time(self):
        return self.time_us

    def advance(self, delta_us):
        self.time_us += delta_us


class FakeMotionWidget:
    def __init__(self):
        self.opacity = 1.0
        self.animations = True
        self.mapped = True
        self.callbacks = {}
        self.handlers = {}
        self.sequence = 0

    def get_settings(self):
        return self

    def get_property(self, key):
        if key == "gtk-enable-animations":
            return self.animations
        raise KeyError(key)

    def get_opacity(self):
        return self.opacity

    def set_opacity(self, value):
        self.opacity = value

    def get_mapped(self):
        return self.mapped

    def connect(self, signal, callback):
        self.sequence += 1
        self.handlers[self.sequence] = callback
        return self.sequence

    def disconnect(self, identifier):
        self.handlers.pop(identifier, None)

    def add_tick_callback(self, callback):
        self.sequence += 1
        self.callbacks[self.sequence] = callback
        return self.sequence

    def remove_tick_callback(self, identifier):
        self.callbacks.pop(identifier, None)

    def step_ticks(self, clock):
        for identifier, cb in list(self.callbacks.items()):
            keep = cb(self, clock)
            if not keep:
                self.callbacks.pop(identifier, None)


class DummyGtkStack:
    """Deterministic fake GtkStack for headless unit testing of PageHost."""

    def __init__(self):
        self.children = {}
        self.titled = {}
        self.visible_child_name = None
        self._handlers = {}
        self._next_handler_id = 1

    def add_titled(self, widget, name, title):
        self.children[name] = widget
        self.titled[name] = title

    def remove(self, widget):
        for k, v in list(self.children.items()):
            if v is widget:
                del self.children[k]
                break

    def get_visible_child_name(self):
        return self.visible_child_name

    def set_visible_child_name(self, name):
        old = self.visible_child_name
        self.visible_child_name = name
        if old != name:
            self._notify("notify::visible-child-name")

    def connect(self, signal, callback):
        hid = self._next_handler_id
        self._next_handler_id += 1
        self._handlers[hid] = (signal, callback)
        return hid

    def disconnect(self, handler_id):
        self._handlers.pop(handler_id, None)

    def _notify(self, signal):
        for hid, (sig, cb) in list(self._handlers.items()):
            if sig == signal:
                cb(self, None)


class TestDrawerGeometryContract(unittest.TestCase):
    """Test drawer geometry clamp, gaps, font dynamic preservation, and right-side anchoring."""

    def test_shared_drawer_gap_is_twelve(self):
        """Authoritative design errata: shared drawer gap must be 12 (not stale 8)."""
        self.assertEqual(DRAWER_TOP_GAP, 12)
        margin = drawer_top_margin(16)
        expected = reserved_bar_height(16) + 12
        self.assertEqual(margin, expected)

    def test_font_dynamic_preservation_no_default_16_floor(self):
        """Configured font 13 must be dynamically preserved and not floored to 16."""
        top_13 = drawer_top_margin(font_size=13)
        top_16 = drawer_top_margin(font_size=16)
        self.assertLess(
            top_13,
            top_16,
            f"Font size 13 produced top {top_13} which was not less than font 16 top {top_16} (possible floor bug)",
        )

    def test_drawer_geometry_clamping_small_monitor(self):
        """Drawer geometry clamps gracefully when monitor dimensions are constrained."""
        width, available, top = drawer_geometry("right", width=400, height=300, font_size=13, gap=12)
        self.assertEqual(width, 400 - 2 * DRAWER_SIDE_MARGIN)
        self.assertGreater(available, 0)
        self.assertLessEqual(top + available + DRAWER_BOTTOM_MARGIN, 300)



class TestPageHostColdLazyLifecycle(unittest.TestCase):
    """Test PageHost cold-lazy construction, draft caching, and show/hide hooks."""

    def setUp(self):
        self.panel = MagicMock()
        self.stack = DummyGtkStack()

        self.mock_factories = {
            "page1": MagicMock(side_effect=lambda: PageEntry(content=MagicMock(name="content1"), widget=MagicMock(name="widget1"))),
            "page2": MagicMock(side_effect=lambda: PageEntry(content=MagicMock(name="content2"), widget=MagicMock(name="widget2"))),
            "page3": MagicMock(side_effect=lambda: PageEntry(content=MagicMock(name="content3"), widget=MagicMock(name="widget3"))),
        }
        self.specs = [
            PageSpec("page1", "Title 1", self.mock_factories["page1"]),
            PageSpec("page2", "Title 2", self.mock_factories["page2"]),
            PageSpec("page3", "Title 3", self.mock_factories["page3"]),
        ]
        self.host = PageHost(self.panel, self.stack, self.specs)

    def test_cold_lazy_never_visited_pages_not_built(self):
        """Never-visited pages are not built; initial stack holds placeholders."""
        for key in ("page1", "page2", "page3"):
            self.assertFalse(self.host.built(key))
            self.mock_factories[key].assert_not_called()
            self.assertIn(key, self.host.placeholders)

    def test_cached_draft_preserves_built_page(self):
        """Visiting a page builds it once; subsequent accesses reuse the cached draft."""
        entry1 = self.host.ensure("page1")
        self.assertTrue(self.host.built("page1"))
        self.assertEqual(self.mock_factories["page1"].call_count, 1)
        self.assertNotIn("page1", self.host.placeholders)

        entry2 = self.host.ensure("page1")
        content = self.host.page("page1")
        self.assertIs(entry1, entry2)
        self.assertIs(content, entry1.content)
        self.assertEqual(self.mock_factories["page1"].call_count, 1)

        self.assertFalse(self.host.built("page2"))
        self.mock_factories["page2"].assert_not_called()

    def test_page_shown_and_hidden_lifecycle_hooks(self):
        """Switching visible child notifies panel._page_hidden and panel._page_shown."""
        self.host.ensure("page1")
        self.host.ensure("page2")

        self.stack.set_visible_child_name("page1")
        self.panel._page_shown.assert_called_with("page1")
        self.panel._page_hidden.assert_not_called()

        self.panel.reset_mock()
        self.stack.set_visible_child_name("page2")
        self.panel._page_hidden.assert_called_once_with("page1")
        self.panel._page_shown.assert_called_once_with("page2")


    def test_dispose_cleans_up_active_and_entries(self):
        """Disposing PageHost notifies _page_hidden on active, _page_dispose on entries, and disconnects."""
        self.host.ensure("page1")
        self.stack.set_visible_child_name("page1")

        self.host.dispose()
        self.assertTrue(self.host.disposed)
        self.assertIsNone(self.host.active)
        self.panel._page_hidden.assert_called_with("page1")
        self.panel._page_dispose.assert_called_with("page1")
        self.assertEqual(len(self.host.entries), 0)

        with self.assertRaises(RuntimeError):
            self.host.ensure("page2")

    def test_pagemap_keys_order_dict_compatibility_and_pure_membership(self):
        """PageMap provides callable ordered keys, Mapping compatibility, and lazy membership."""
        from collections.abc import Mapping
        mapping = PageMap(self.host, ("page1", "page2", "page3"))

        # mapping.keys() callable/order
        self.assertTrue(callable(mapping.keys))
        self.assertEqual(list(mapping.keys()), ["page1", "page2", "page3"])

        # Dict mapping compatibility
        self.assertTrue(issubclass(PageMap, Mapping))
        self.assertIsInstance(mapping, Mapping)
        self.assertEqual(len(mapping), 3)

        # Pure membership checks do not build pages or trigger factories
        self.assertIn("page1", mapping)
        self.assertIn("page2", mapping)
        self.assertNotIn("unregistered", mapping)
        for key in ("page1", "page2", "page3"):
            self.assertFalse(self.host.built(key))
            self.mock_factories[key].assert_not_called()

        # Accessing one page builds only that page without building hidden pages
        page1_content = mapping["page1"]
        self.assertTrue(self.host.built("page1"))
        self.assertFalse(self.host.built("page2"))
        self.assertFalse(self.host.built("page3"))
        self.assertEqual(self.mock_factories["page1"].call_count, 1)
        self.mock_factories["page2"].assert_not_called()
        self.mock_factories["page3"].assert_not_called()


class TestPanelMotionLifecycle(unittest.TestCase):
    """Test PanelMotion lifecycle: cancel, reversal, settle, and reduced motion."""

    def test_panel_motion_reduced_motion_settles_immediately(self):
        """Reduced motion skips frame clock ticks and finishes immediately."""
        widget = FakeMotionWidget()
        widget.animations = False
        motion = PanelMotion(widget, duration_ms=180)
        motion.reveal()
        self.assertFalse(motion.running)
        self.assertEqual(widget.get_opacity(), 1.0)

    def test_rapid_reversal_cancels_queued_destroy(self):
        """Rapid reversal from dismiss back to reveal must cancel queued destroy completion."""
        widget = FakeMotionWidget()
        widget.set_opacity(1.0)
        motion = PanelMotion(widget, duration_ms=180)

        destroy_callback = MagicMock()
        motion.dismiss(destroy_callback)
        self.assertTrue(motion.running)

        # Rapid user re-trigger reveals before dismissal completes
        motion.reveal()
        self.assertTrue(motion.running)

        # Step frame clock to completion
        clock = FakeClock(start_us=100_000)
        widget.step_ticks(clock)
        clock.advance(300_000)
        widget.step_ticks(clock)

        self.assertFalse(motion.running)
        self.assertEqual(widget.get_opacity(), 1.0)
        # Queued destroy callback must NOT have been called
        destroy_callback.assert_not_called()

    def test_panel_motion_frame_clock_settle_lifecycle(self):
        """Dismiss animation settles opacity to 0.0 and fires completion callback."""
        widget = FakeMotionWidget()
        widget.set_opacity(1.0)
        motion = PanelMotion(widget, duration_ms=100)

        completed = MagicMock()
        motion.dismiss(completed)
        self.assertTrue(motion.running)

        clock = FakeClock(start_us=1_000_000)
        widget.step_ticks(clock)

        # Halfway
        clock.advance(50_000)
        widget.step_ticks(clock)
        self.assertTrue(motion.running)
        self.assertLess(widget.get_opacity(), 1.0)
        self.assertGreater(widget.get_opacity(), 0.0)

        # Full duration exceeded
        clock.advance(60_000)
        widget.step_ticks(clock)
        self.assertFalse(motion.running)
        self.assertEqual(widget.get_opacity(), 0.0)
        completed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
