#!/usr/bin/env python3
"""Exercise daily settings flows on smoke.py's private GTK/Wayland session."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1":
    raise SystemExit("Run through smoke.py --daily-logic-probe-only")

import panel_probe
from panel_probe import PanelInteractionTests, Gtk, descendants, pump_until, wait_gtk
import notification_history
import system_settings

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".validation" / "daily-logic"
REAL_RUN, REAL_POPEN = subprocess.run, subprocess.Popen


class DailyLogicInteractionTests(PanelInteractionTests):
    def setUp(self):
        super().setUp()
        # Native widgets and real async callbacks; storage is exclusively private.
        self.private_history = Path(os.environ["XDG_STATE_HOME"]) / ("daily-history-" + self._testMethodName)
        self.private_history.mkdir()
        self.stack.enter_context(patch.object(notification_history, "state_dir", return_value=self.private_history))
        notification_history.record_notification({"id": 42, "summary": "First version", "body": "Original body"})
        notification_history.record_notification({"id": 42, "summary": "Replacement", "body": "A reused daemon ID"})

    def page(self, key):
        window = self.make_control(key, eager=False)
        page = window.settings_pages[key]
        pump_until(lambda: page.loaded and not page.busy)
        return window, page

    def click(self, parent, title):
        button = next(widget for widget in descendants(parent)
                      if isinstance(widget, Gtk.Button) and widget.get_label() == title
                      and widget.is_visible())
        self.assertTrue(button.is_sensitive(), title)
        button.clicked()

    def settle(self, page):
        pump_until(lambda: not page.busy)
        wait_gtk(.03)

    def draft_notifications(self, page):
        page.limit_combo.set_active_id("500")
        page.expire_combo.set_active_id("30")
        page.enabled_check.set_active(False)

    def assert_notification_draft(self, page):
        self.assertEqual(page.draft_settings(), {"limit": 500, "expire_days": 30, "enabled": False})

    def capture(self, name):
        wait_gtk(.35)
        target = ARTIFACTS / (name + ".png")
        previous = target.stat().st_mtime_ns if target.exists() else 0
        with patch.object(subprocess, "run", REAL_RUN), patch.object(subprocess, "Popen", REAL_POPEN):
            REAL_RUN(["niri", "msg", "action", "screenshot-screen", "--path", str(target),
                      "--show-pointer", "false"], capture_output=True, check=True, timeout=5)
        pump_until(lambda: target.exists() and target.stat().st_mtime_ns != previous and target.stat().st_size > 0)

    def test_native_notifications_delete_exact_row_and_preserve_draft(self):
        window, page = self.page("notifications")
        self.draft_notifications(page)
        selected = notification_history.load_history()[0]["history_id"]
        row = page.history_container.get_children()[0]
        self.click(row, "×")
        self.settle(page)
        remaining = notification_history.load_history()
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0]["history_id"], selected)
        self.assertEqual(len(page.history_container.get_children()), 1)
        self.assert_notification_draft(page)
        window.select_control_tab("services")
        pump_until(lambda: window.settings_pages["services"].loaded and not window.settings_pages["services"].busy)
        window.select_control_tab("notifications")
        self.assert_notification_draft(page)
        self.capture("notifications-after-single-delete")

    def test_native_clear_confirmation_cancel_then_confirm(self):
        _window, page = self.page("notifications")
        self.draft_notifications(page)
        self.click(page.history_actions, "Clear all history…")
        self.assertEqual(page.history_actions.get_visible_child_name(), "confirm")
        self.assertEqual(len(notification_history.load_history()), 2)
        self.capture("notifications-clear-confirmation")
        scroll = page.get_ancestor(Gtk.ScrolledWindow)
        _x, top = page.cancel_history_button.translate_coordinates(scroll, 0, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(top + page.cancel_history_button.get_allocated_height(), scroll.get_allocated_height(),
                             {"mapped": page.get_mapped(), "position": top,
                              "adjustment": scroll.get_vadjustment().get_value(),
                              "page_size": scroll.get_vadjustment().get_page_size()})
        self.click(page.history_actions, "Cancel")
        self.assertEqual(page.history_actions.get_visible_child_name(), "actions")
        self.assertEqual(len(notification_history.load_history()), 2)
        self.click(page.history_actions, "Clear all history…")
        self.click(page.history_actions, "Clear all history")
        self.settle(page)
        self.assertEqual(notification_history.load_history(), [])
        self.assertEqual(page.history_actions.get_visible_child_name(), "actions")
        self.assert_notification_draft(page)
        self.capture("notifications-empty-after-confirm")

    def test_native_notification_refresh_failure_keeps_draft_and_recovers(self):
        _window, page = self.page("notifications")
        self.draft_notifications(page)
        with patch.object(notification_history, "load_history", side_effect=RuntimeError("Probe read failure")):
            self.click(page.history_actions, "Refresh")
            self.settle(page)
        self.assertIn("Probe read failure", page.notice.get_text())
        self.assert_notification_draft(page)
        self.click(page.history_actions, "Refresh")
        self.settle(page)
        self.assert_notification_draft(page)
        self.assertEqual(len(page.history_container.get_children()), 2)

    def test_native_applications_apply_one_role_keeps_other_draft(self):
        _window, page = self.page("applications")
        state = system_settings.application_state.return_value
        self.system_writes["set_default_application"].side_effect = (
            lambda role, identifier: state[role].update(default=identifier))
        page.choices["browser"].set_active_id("second.desktop")
        page.choices["mail"].set_active_id("second.desktop")
        self.system_writes["set_default_application"].assert_not_called()
        page.buttons["browser"].clicked()
        self.settle(page)
        self.system_writes["set_default_application"].assert_called_once_with("browser", "second.desktop")
        self.assertEqual(page.choices["browser"].get_active_id(), "second.desktop")
        self.assertEqual(page.choices["mail"].get_active_id(), "second.desktop")
        self.assertEqual(state["mail"]["default"], "probe.desktop")
        self.capture("applications-pending-mail-draft")

    def test_native_services_apply_one_switch_keeps_other_draft(self):
        _window, page = self.page("services")
        state = system_settings.service_state.return_value
        self.system_writes["set_service"].side_effect = (
            lambda key, enabled: state[key].update(enabled=enabled))
        page.checks["clipboard"].set_active(False)
        page.checks["notifications"].set_active(False)
        self.system_writes["set_service"].assert_not_called()
        self.click(page.checks["clipboard"].get_parent(), "Apply")
        self.settle(page)
        self.system_writes["set_service"].assert_called_once_with("clipboard", False)
        self.assertFalse(page.checks["clipboard"].get_active())
        self.assertFalse(page.checks["notifications"].get_active())
        self.assertTrue(state["notifications"]["enabled"])
        self.capture("services-pending-notification-draft")

    def test_native_notification_search_and_batched_history(self):
        notification_history.clear_history()
        for index in range(65):
            notification_history.record_notification({
                "id": 42, "app_name": "Mail" if index % 2 == 0 else "Calendar",
                "summary": f"Meeting {index}", "body": "needle" if index < 2 else "archive"})
        _window, page = self.page("notifications")
        self.assertEqual(len(page.history_container.get_children()), 30)
        self.assertTrue(page.history_more.get_visible())
        page.history_more.clicked()
        self.assertEqual(len(page.history_container.get_children()), 60)
        page.history_search.set_text("mAiL")
        pump_until(lambda: "33" in page.history_count.get_text())
        self.assertEqual(len(page.history_container.get_children()), 30)
        page.history_search.set_text("needle")
        pump_until(lambda: len(page.history_container.get_children()) == 2)
        self.assertFalse(page.history_more.get_visible())
        self.draft_notifications(page)
        selected = next(row["history_id"] for row in notification_history.load_history() if row["body"] == "needle")
        self.click(page.history_container.get_children()[0], "×")
        self.settle(page)
        self.assertEqual(page.history_search.get_text(), "needle")
        self.assertEqual(len(page.history_container.get_children()), 1)
        self.assert_notification_draft(page)
        self.assertNotIn(selected, [row["history_id"] for row in notification_history.load_history()])
        scroll = page.get_ancestor(Gtk.ScrolledWindow)
        wait_gtk(.05)
        _x, top = page.history_search.translate_coordinates(scroll, 0, 0)
        adjustment = scroll.get_vadjustment()
        adjustment.set_value(adjustment.get_value() + top - 8)
        self.capture("notifications-filtered-history")
        page.history_search.set_text("")
        pump_until(lambda: "64" in page.history_count.get_text())
        self.assertEqual(len(page.history_container.get_children()), 30)
        self.assertEqual(len(notification_history.load_history()), 64)

    def test_native_unavailable_state_is_disabled_then_recovers_without_losing_drafts(self):
        window = self.make_control("quick", eager=False)
        with patch.object(system_settings, "network_state", side_effect=RuntimeError("Probe initial bus unavailable")):
            window.select_control_tab("network")
            network = window.settings_pages["network"]
            self.settle(network)
        self.assertFalse(network.loaded)
        self.assertFalse(network.connect_button.is_sensitive())
        self.assertFalse(network.disconnect_button.is_sensitive())
        network.refresh()
        self.settle(network)
        self.assertTrue(network.connect_button.is_sensitive())
        self.assertFalse(network.disconnect_button.is_sensitive())
        with patch.object(system_settings, "network_state", side_effect=RuntimeError("Probe bus unavailable")):
            network.refresh()
            self.settle(network)
        self.assertFalse(network.connect_button.is_sensitive())
        self.assertFalse(network.disconnect_button.is_sensitive())
        self.assertTrue(network.notice.get_visible())
        self.capture("network-unavailable-state")
        network.refresh()
        self.settle(network)
        self.assertFalse(network.notice.get_visible())
        self.assertTrue(network.connect_button.is_sensitive())
        with patch.object(system_settings, "service_state", side_effect=RuntimeError("Probe initial bus unavailable")):
            window.select_control_tab("services")
            services = window.settings_pages["services"]
            self.settle(services)
        self.assertFalse(services.loaded)
        self.assertFalse(any(check.is_sensitive() for check in services.checks.values()))
        self.assertTrue(services.notice.get_mapped())
        services.refresh()
        self.settle(services)
        services.checks["clipboard"].set_active(False)
        with patch.object(system_settings, "service_state", side_effect=RuntimeError("Probe bus unavailable")):
            services.refresh()
            self.settle(services)
        self.assertFalse(services.checks["clipboard"].get_active())
        self.assertTrue(services.checks["notifications"].get_active(), "failed refresh cannot invent disabled services")
        self.assertFalse(any(check.is_sensitive() for check in services.checks.values()))
        services.refresh()
        self.settle(services)
        self.assertFalse(services.checks["clipboard"].get_active(), "draft survives recovery")
        self.assertTrue(all(check.is_sensitive() for check in services.checks.values()))
        window.select_control_tab("time")
        clock = window.settings_pages["time"]
        pump_until(lambda: clock.loaded and not clock.busy)
        clock.zone.set_text("UTC")
        with patch.object(system_settings, "time_state", side_effect=RuntimeError("Probe bus unavailable")):
            clock.refresh()
            self.settle(clock)
        self.assertEqual(clock.zone.get_text(), "UTC")
        self.assertFalse(clock.zone_apply.is_sensitive())
        self.assertFalse(clock.ntp_apply.is_sensitive())
        clock.refresh()
        self.settle(clock)
        self.assertEqual(clock.zone.get_text(), "UTC")
        self.assertTrue(clock.zone_apply.is_sensitive())
        for change in self.system_writes.values():
            change.assert_not_called()

    def test_native_missing_application_has_visible_explanation(self):
        _window, page = self.page("applications")
        state = system_settings.application_state.return_value
        state["mail"] = {"choices": [], "default": ""}
        page.refresh()
        self.settle(page)
        self.assertTrue(page.empty_choices["mail"].get_mapped())
        self.assertFalse(page.buttons["mail"].is_sensitive())
        self.assertFalse(page.choices["mail"].is_sensitive())
        self.assertIsNone(page.choices["mail"].get_active_id())
        self.assertFalse(page.notice.get_visible())
        self.capture("applications-no-mail-candidate")


def main():
    state = Path(os.environ.get("XDG_STATE_HOME", ""))
    if (not state.is_absolute() or not state.name.startswith("selandia-smoke-")
            or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            or not os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Daily logic probe requires smoke.py's isolated session")
    if not Gtk.init_check()[0]:
        raise RuntimeError("Cannot connect to private GTK display")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    names = [name for name in DailyLogicInteractionTests.__dict__ if name.startswith("test_native_")]
    suite = unittest.TestSuite(DailyLogicInteractionTests(name) for name in names)
    def timeout(_signal, _frame):
        raise TimeoutError("Daily logic native probe exceeded 45 seconds")
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(45)
    started = time.monotonic()
    try:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        summary = {"native_tests": result.testsRun, "failures": len(result.failures),
                   "errors": len(result.errors), "seconds": round(time.monotonic() - started, 3),
                   "screenshots": sorted(path.name for path in ARTIFACTS.glob("*.png")),
                   "private_state": True, "real_hardware_commands": False}
        (ARTIFACTS / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary), flush=True)
        return 0 if result.wasSuccessful() else 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
