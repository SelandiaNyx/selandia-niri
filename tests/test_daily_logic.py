"""Daily settings actions preserve independent drafts and delete exact rows."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import notification_history as history
from navigation_catalog import PAGES
import system_controls as controls


class QueuedPanel:
    """Run the real settings callbacks with explicitly completed background work."""
    def __init__(self):
        self.jobs = []

    def work(self, operation, done=None, failed=None, *, commit=False):
        self.jobs.append((operation, done, failed, commit))

    def finish(self, error=None):
        operation, done, failed, commit = self.jobs.pop(0)
        if error is not None:
            failed(error)
        else:
            result = operation()
            if done:
                done(result)
        return commit

    def protect_scroll_controls(self, _widget):
        pass

    def launch(self, _arguments):
        raise AssertionError("external applications are not part of this test")


class NotificationDraftTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-daily-notifications-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name)
        patcher = patch.object(history, "state_dir", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)
        history.record_notification({"id": 42, "summary": "First"})
        history.record_notification({"id": 42, "summary": "Replacement"})
        self.panel = QueuedPanel()
        self.page = controls.NotificationSettings(self.panel)
        self.addCleanup(self.page.destroy)
        self.page.show_all()
        self.page.refresh()
        self.panel.finish()

    def edit_draft(self):
        self.page.limit_combo.set_active_id("500")
        self.page.expire_combo.set_active_id("30")
        self.page.enabled_check.set_active(False)

    def assert_draft(self):
        self.assertEqual(self.page.draft_settings(),
                         {"limit": 500, "expire_days": 30, "enabled": False})

    def test_single_delete_preserves_unapplied_settings_and_other_reused_id(self):
        self.edit_draft()
        selected = history.load_history()[0]
        self.page.delete_entry(selected["history_id"])
        self.assertTrue(self.panel.finish(), "deletion must hold the application alive")
        self.assertTrue(self.page.busy)
        self.panel.finish()
        self.assert_draft()
        remaining = history.load_history()
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0]["history_id"], selected["history_id"])
        self.assertEqual(history.load_settings()["limit"], 100)

    def test_clear_requires_confirmation_cancel_preserves_data_and_draft(self):
        self.edit_draft()
        self.page.clear_history()
        self.assertEqual(self.page.history_actions.get_visible_child_name(), "confirm")
        self.assertEqual(len(history.load_history()), 2)
        self.assertFalse(self.panel.jobs)
        self.page.cancel_clear_history()
        self.assertEqual(self.page.history_actions.get_visible_child_name(), "actions")
        self.assertEqual(len(history.load_history()), 2)
        self.assert_draft()
        self.page.clear_history()
        self.page.confirm_clear_history()
        self.panel.finish()
        self.panel.finish()
        self.assertEqual(history.load_history(), [])
        self.assertEqual(self.page.history_actions.get_visible_child_name(), "actions")
        self.assert_draft()

    def test_read_and_write_failures_keep_draft_and_allow_retry(self):
        self.edit_draft()
        self.page.refresh()
        self.assertFalse(self.page.history_card.get_sensitive())
        self.panel.finish(error="read failed")
        self.assert_draft()
        self.assertFalse(self.page.busy)
        self.assertIn("read failed", self.page.notice.get_text())
        selected = history.load_history()[0]
        self.page.delete_entry(selected["history_id"])
        self.panel.finish(error="delete failed")
        self.assert_draft()
        self.assertFalse(self.page.busy)
        self.assertEqual(len(history.load_history()), 2)
        self.page.refresh()
        self.panel.finish()
        self.assert_draft()

    def test_apply_commits_only_after_action_and_reads_back_saved_state(self):
        self.edit_draft()
        self.page.apply_settings()
        self.assertEqual(history.load_settings()["limit"], 100)
        self.assertTrue(self.panel.finish())
        self.assertEqual(history.load_settings(), self.page.draft_settings())
        self.panel.finish()
        self.assert_draft()
        self.assertEqual(self.page.saved_history_settings, self.page.draft_settings())

    def test_custom_valid_saved_values_are_shown_and_retained(self):
        history.save_settings({"limit": 123, "expire_days": 2.5, "enabled": True})
        self.page.refresh()
        self.panel.finish()
        self.assertEqual(self.page.draft_settings(),
                         {"limit": 123, "expire_days": 2.5, "enabled": True})
        self.page.apply_settings()
        self.panel.finish()
        self.panel.finish()
        self.assertEqual(history.load_settings()["expire_days"], 2.5)

    def test_clear_failure_preserves_confirmation_and_allows_retry(self):
        self.page.confirm_clear_history()
        self.assertFalse(self.panel.jobs, "confirmation callback needs an active prompt")
        self.edit_draft()
        self.page.clear_history()
        self.page.confirm_clear_history()
        self.panel.finish(error="clear failed")
        self.assertEqual(len(history.load_history()), 2)
        self.assertEqual(self.page.history_actions.get_visible_child_name(), "confirm")
        self.assert_draft()
        self.page.confirm_clear_history()
        self.panel.finish()
        self.panel.finish()
        self.assertEqual(history.load_history(), [])
        self.assert_draft()

    def test_history_search_batches_rows_and_keeps_search_and_draft_on_delete(self):
        history.clear_history()
        for index in range(65):
            history.record_notification({"id": 42, "app_name": "Mail" if index % 2 == 0 else "Calendar",
                                         "summary": f"Meeting {index}",
                                         "body": "needle" if index < 2 else "archive"})
        self.page.refresh()
        self.panel.finish()
        self.assertEqual(len(history.load_history()), 65)
        self.assertEqual(len(self.page.history_container.get_children()), 30)
        self.assertTrue(self.page.history_more.get_visible())
        self.page.history_more.clicked()
        self.assertEqual(len(self.page.history_container.get_children()), 60)
        self.page.history_search.set_text("mAiL")
        self.page.history_search.emit("search-changed")
        self.assertEqual(len(self.page.history_container.get_children()), 30)
        self.assertIn("33", self.page.history_count.get_text())
        self.page.history_search.set_text("needle")
        self.page.history_search.emit("search-changed")
        self.assertEqual(len(self.page.history_container.get_children()), 2)
        self.assertFalse(self.page.history_more.get_visible())
        self.edit_draft()
        selected = next(row for row in history.load_history() if row["body"] == "needle")
        self.page.delete_entry(selected["history_id"])
        self.panel.finish()
        self.panel.finish()
        self.assertEqual(self.page.history_search.get_text(), "needle")
        self.assertEqual(len(self.page.history_container.get_children()), 1)
        self.assert_draft()
        self.assertEqual(len(history.load_history()), 64)
        self.page.history_search.set_text("")
        self.page.history_search.emit("search-changed")
        self.assertEqual(len(self.page.history_container.get_children()), 30)
        self.assertEqual(len(history.load_history()), 64, "paging must not prune saved records")


class IndependentSettingsDraftTests(unittest.TestCase):
    def setUp(self):
        self.panel = QueuedPanel()

    def page(self, kind):
        result = kind(self.panel)
        self.addCleanup(result.destroy)
        return result

    def test_applying_one_default_preserves_other_role_and_refresh_drafts(self):
        page = self.page(controls.ApplicationsSettings)
        state = {key: {"default": "first.desktop", "choices": [
            ("first.desktop", "First"), ("second.desktop", "Second")]}
                 for key in page.choices}
        def apply(role, identifier):
            state[role]["default"] = identifier
        with patch.object(controls.backend, "application_state", side_effect=lambda: state), \
             patch.object(controls.backend, "set_default_application", side_effect=apply) as change:
            page.refresh()
            self.panel.finish()
            page.choices["browser"].set_active_id("second.desktop")
            page.choices["mail"].set_active_id("second.desktop")
            page.apply("browser")
            self.panel.finish()
            self.panel.finish()
            change.assert_called_once_with("browser", "second.desktop")
            self.assertEqual(page.choices["mail"].get_active_id(), "second.desktop")
            self.assertEqual(state["mail"]["default"], "first.desktop")
            page.refresh()
            self.panel.finish()
            self.assertEqual(page.choices["mail"].get_active_id(), "second.desktop")
            state["mail"]["choices"] = [("first.desktop", "First")]
            page.refresh()
            self.panel.finish()
            self.assertEqual(page.choices["mail"].get_active_id(), "first.desktop")

    def test_applying_one_service_preserves_other_pending_switch(self):
        page = self.page(controls.ServicesSettings)
        state = {key: {"enabled": True} for key in page.checks}
        def apply(key, enabled):
            state[key]["enabled"] = enabled
        with patch.object(controls.backend, "service_state", side_effect=lambda: state), \
             patch.object(controls.backend, "set_service", side_effect=apply) as change:
            page.refresh()
            self.panel.finish()
            page.checks["clipboard"].set_active(False)
            page.checks["notifications"].set_active(False)
            page.apply("clipboard")
            self.panel.finish()
            self.panel.finish()
            self.assertFalse(page.checks["clipboard"].get_active())
            self.assertFalse(page.checks["notifications"].get_active())
            self.assertTrue(state["notifications"]["enabled"])
            change.assert_called_once_with("clipboard", False)

    def test_time_zone_and_sync_apply_preserve_each_others_drafts(self):
        page = self.page(controls.TimeSettings)
        state = {"timezone": "UTC", "ntp": True, "can_ntp": True, "synchronized": True}
        with patch.object(controls.backend, "time_state", side_effect=lambda: state), \
             patch.object(controls.backend, "timezones", return_value=["UTC", "Asia/Shanghai"]), \
             patch.object(controls.backend, "set_timezone", side_effect=lambda zone: state.update(timezone=zone)):
            page.refresh()
            self.panel.finish()
            page.zone.set_text("Asia/Shanghai")
            page.ntp.set_active(False)
            page.apply_zone()
            self.panel.finish()
            self.panel.finish()
            self.assertEqual(page.zone.get_text(), "Asia/Shanghai")
            self.assertFalse(page.ntp.get_active())
            self.assertTrue(state["ntp"])

    def test_empty_notice_stays_hidden_after_show_all_and_read_recovers(self):
        page = self.page(controls.ServicesSettings)
        page.show_all()
        self.assertFalse(page.notice.get_visible())
        page.refresh()
        self.assertTrue(page.notice.get_visible())
        self.panel.finish(error=RuntimeError("user bus unavailable"))
        self.assertTrue(page.notice.get_visible())
        self.assertFalse(any(check.is_sensitive() for check in page.checks.values()))
        self.assertFalse(page.loaded)
        state = {key: {"enabled": True} for key in page.checks}
        with patch.object(controls.backend, "service_state", return_value=state):
            page.refresh()
            self.panel.finish()
        self.assertFalse(page.notice.get_visible())
        self.assertTrue(all(check.is_sensitive() for check in page.checks.values()))
        self.assertTrue(all(check.get_active() for check in page.checks.values()))
        page.show_all()
        self.assertFalse(page.notice.get_visible())

    def test_failed_time_read_disables_unknown_state_and_preserves_known_draft(self):
        page = self.page(controls.TimeSettings)
        page.refresh()
        self.panel.finish(error=RuntimeError("system bus unavailable"))
        self.assertFalse(page.zone.is_sensitive())
        self.assertFalse(page.zone_apply.is_sensitive())
        self.assertFalse(page.ntp_apply.is_sensitive())
        state = {"timezone": "UTC", "ntp": True, "can_ntp": False, "synchronized": True}
        with patch.object(controls.backend, "time_state", return_value=state), \
             patch.object(controls.backend, "timezones", return_value=["UTC", "Asia/Shanghai"]):
            page.refresh()
            self.panel.finish()
            self.assertTrue(page.zone_apply.is_sensitive())
            self.assertFalse(page.ntp_apply.is_sensitive(), "cannot enable NTP on an unsupported backend")
            page.zone.set_text("Asia/Shanghai")
            page.refresh()
            self.panel.finish(error=RuntimeError("later failure"))
            self.assertEqual(page.zone.get_text(), "Asia/Shanghai")
            self.assertFalse(page.zone_apply.is_sensitive())
            page.refresh()
            self.panel.finish()
        self.assertEqual(page.zone.get_text(), "Asia/Shanghai")
        self.assertTrue(page.zone_apply.is_sensitive())

    def test_missing_application_has_explanation_without_a_fake_selection(self):
        page = self.page(controls.ApplicationsSettings)
        state = {key: {"default": "", "choices": []} for key in page.choices}
        page.show_all()
        with patch.object(controls.backend, "application_state", return_value=state):
            page.refresh()
            self.panel.finish()
            self.assertTrue(page.empty_choices["mail"].get_visible())
            self.assertFalse(page.choices["mail"].is_sensitive())
            self.assertFalse(page.buttons["mail"].is_sensitive())
            self.assertIsNone(page.choices["mail"].get_active_id())
            state["mail"] = {"default": "mail.desktop", "choices": [("mail.desktop", "Mail")]}
            page.refresh()
            self.panel.finish()
        self.assertFalse(page.empty_choices["mail"].get_visible())
        self.assertTrue(page.buttons["mail"].is_sensitive())

    def test_input_method_search_has_one_canonical_page_and_tool(self):
        searches = {key: " ".join((english, chinese, terms)).casefold()
                    for key, english, chinese, _icon, _group, terms in PAGES}
        for term in ("input method", "输入法", "fcitx5"):
            self.assertIn(term, searches["input"])
            self.assertNotIn(term, searches["storage"])
        self.assertFalse(any("fcitx" in command[0]
                             for _titles, _descriptions, candidates, _package in controls.TOOLS["hardware"]
                             for command in candidates))


if __name__ == "__main__":
    unittest.main()
