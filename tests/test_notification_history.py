#!/usr/bin/env python3
"""Unit tests for notification history recording, TTL pruning and settings."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import notification_history as nh


class NotificationHistorySettingsTests(unittest.TestCase):
    def test_default_settings(self):
        self.assertEqual(nh.DEFAULT_SETTINGS["limit"], 100)
        self.assertEqual(nh.DEFAULT_SETTINGS["expire_days"], 7)
        self.assertTrue(nh.DEFAULT_SETTINGS["enabled"])

    def test_validate_settings_normalizes_and_clamps(self):
        # Empty or invalid types
        self.assertEqual(nh.validate_settings({}), nh.DEFAULT_SETTINGS)
        self.assertEqual(nh.validate_settings(None), nh.DEFAULT_SETTINGS)
        self.assertEqual(nh.validate_settings("string"), nh.DEFAULT_SETTINGS)

        # Valid inputs
        valid = {"limit": "50", "expire_days": "14", "enabled": False}
        res = nh.validate_settings(valid)
        self.assertEqual(res["limit"], 50)
        self.assertEqual(res["expire_days"], 14)
        self.assertFalse(res["enabled"])

        # Boundary values
        self.assertEqual(nh.validate_settings({"limit": 0})["limit"], 0)
        self.assertEqual(nh.validate_settings({"expire_days": 0})["expire_days"], 0)
        self.assertEqual(nh.validate_settings({"limit": -1})["limit"], 100)
        self.assertEqual(nh.validate_settings({"limit": 99999})["limit"], 100)
        self.assertEqual(nh.validate_settings({"expire_days": -5})["expire_days"], 7)


class NotificationPruningTests(unittest.TestCase):
    def test_prune_entries_by_limit(self):
        now = 1000000.0
        entries = [
            {"id": i, "summary": f"Title {i}", "timestamp": now - i * 10}
            for i in range(10)
        ]
        # entries[0] is newest (now), entries[9] is oldest (now - 90)
        settings = {"limit": 5, "expire_days": 0, "enabled": True}
        pruned = nh.prune_entries(entries, settings=settings, now=now)
        self.assertEqual(len(pruned), 5)
        self.assertEqual([e["id"] for e in pruned], [0, 1, 2, 3, 4])

    def test_prune_entries_unlimited(self):
        now = 1000000.0
        entries = [
            {"id": i, "summary": f"Title {i}", "timestamp": now - i * 10}
            for i in range(150)
        ]
        settings = {"limit": 0, "expire_days": 0, "enabled": True}
        pruned = nh.prune_entries(entries, settings=settings, now=now)
        self.assertEqual(len(pruned), 150)

    def test_prune_entries_by_expiry(self):
        now = 1000000.0
        one_day = 86400.0
        entries = [
            {"id": 1, "summary": "Recent", "timestamp": now - 3600},                  # 1 hr ago
            {"id": 2, "summary": "Yesterday", "timestamp": now - one_day * 0.9},      # 0.9 days ago
            {"id": 3, "summary": "Two days ago", "timestamp": now - one_day * 2},     # 2 days ago
            {"id": 4, "summary": "Old", "timestamp": now - one_day * 4},              # 4 days ago
        ]
        # Set expire_days to 3 days
        settings = {"limit": 100, "expire_days": 3, "enabled": True}
        pruned = nh.prune_entries(entries, settings=settings, now=now)
        self.assertEqual(len(pruned), 3)
        self.assertEqual([e["id"] for e in pruned], [1, 2, 3])

    def test_prune_sorts_newest_first(self):
        now = 1000000.0
        entries = [
            {"id": 1, "timestamp": now - 100},
            {"id": 2, "timestamp": now - 10},
            {"id": 3, "timestamp": now - 50},
        ]
        pruned = nh.prune_entries(entries, settings={"limit": 10, "expire_days": 0}, now=now)
        self.assertEqual([e["id"] for e in pruned], [2, 3, 1])


class NotificationStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.patch_dir = patch.object(nh, "state_dir", return_value=self.state)
        self.patch_dir.start()

    def tearDown(self):
        self.patch_dir.stop()
        self.tmp.cleanup()

    def test_save_and_load_settings(self):
        nh.save_settings({"limit": 50, "expire_days": 3, "enabled": True})
        loaded = nh.load_settings()
        self.assertEqual(loaded["limit"], 50)
        self.assertEqual(loaded["expire_days"], 3)
        self.assertTrue(loaded["enabled"])

    def test_record_notification_lifecycle(self):
        # 1. Record item
        item = {
            "id": 101,
            "app_name": "TestApp",
            "summary": "Hello World",
            "body": "This is a test notification",
            "icon": "dialog-information",
            "urgency": 1,
        }
        ok = nh.record_notification(item)
        self.assertTrue(ok)

        history = nh.load_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["id"], 101)
        self.assertEqual(history[0]["app_name"], "TestApp")
        self.assertEqual(history[0]["summary"], "Hello World")

        # 2. Duplicate detection within short interval
        duplicate_ok = nh.record_notification(item)
        self.assertFalse(duplicate_ok)
        self.assertEqual(len(nh.load_history()), 1)

        # 3. Record second different item
        item2 = {
            "id": 102,
            "app_name": "TestApp",
            "summary": "Another Alert",
            "body": "Different body",
            "urgency": 2,
        }
        self.assertTrue(nh.record_notification(item2))
        history2 = nh.load_history()
        self.assertEqual(len(history2), 2)
        # Newest first
        self.assertEqual(history2[0]["id"], 102)

        # 4. Delete single item
        deleted = nh.delete_notification(101)
        self.assertTrue(deleted)
        history3 = nh.load_history()
        self.assertEqual(len(history3), 1)
        self.assertEqual(history3[0]["id"], 102)

        # 5. Clear history
        nh.clear_history()
        self.assertEqual(nh.load_history(), [])

    def test_record_respects_limit(self):
        nh.save_settings({"limit": 3, "expire_days": 0, "enabled": True})
        for i in range(5):
            nh.record_notification({
                "id": i + 1,
                "app_name": f"App{i}",
                "summary": f"Summary {i}",
                "body": f"Body {i}",
                "timestamp": time.time() + i,
            })
        history = nh.load_history()
        self.assertEqual(len(history), 3)
        self.assertEqual([h["id"] for h in history], [5, 4, 3])

    def test_record_disabled(self):
        nh.save_settings({"limit": 100, "expire_days": 7, "enabled": False})
        res = nh.record_notification({"id": 1, "summary": "Disabled test"})
        self.assertFalse(res)
        self.assertEqual(nh.load_history(), [])

    def test_reused_daemon_ids_have_distinct_stable_history_ids(self):
        nh.record_notification({"id": 42, "summary": "Original"})
        nh.record_notification({"id": 42, "summary": "Replacement"})
        initial = nh.load_history()
        self.assertEqual([entry["id"] for entry in initial], [42, 42])
        keys = [entry["history_id"] for entry in initial]
        self.assertEqual(len(set(keys)), 2)
        self.assertEqual([entry["history_id"] for entry in nh.load_history()], keys)
        # Deleting the row a client selected remains precise after a new row is inserted.
        nh.record_notification({"id": 42, "summary": "New instance"})
        self.assertTrue(nh.delete_notification(keys[1]))
        remaining = nh.load_history()
        self.assertEqual(len(remaining), 2)
        self.assertNotIn(keys[1], [entry["history_id"] for entry in remaining])
        self.assertIn(keys[0], [entry["history_id"] for entry in remaining])
        self.assertFalse(nh.delete_notification(keys[1]), "a repeated deletion must not target another row")

    def test_legacy_rows_migrate_once_even_with_duplicate_or_empty_row_keys(self):
        now = time.time()
        records = [
            {"id": 7, "summary": "First", "timestamp": now, "history_id": "shared"},
            {"id": 7, "summary": "Second", "timestamp": now - 1, "history_id": "shared"},
            {"id": 7, "summary": "Third", "timestamp": now - 2, "history_id": ""},
            {"id": 7, "summary": "Fourth", "timestamp": now - 3},
        ]
        nh.history_path().write_text(json.dumps(records))
        first = nh.load_history()
        keys = [entry["history_id"] for entry in first]
        self.assertEqual(keys[0], "shared")
        self.assertEqual(len(set(keys)), 4)
        on_disk = nh.history_path().read_bytes()
        self.assertEqual([entry["history_id"] for entry in nh.load_history()], keys)
        self.assertEqual(nh.history_path().read_bytes(), on_disk)

    def test_legacy_deletion_removes_one_row_and_empty_identity_is_ignored(self):
        nh.record_notification({"id": 42, "summary": "First"})
        nh.record_notification({"id": 42, "summary": "Second"})
        self.assertFalse(nh.delete_notification(None))
        self.assertFalse(nh.delete_notification(""))
        self.assertEqual(len(nh.load_history()), 2)
        self.assertTrue(nh.delete_notification("42"))
        self.assertEqual(len(nh.load_history()), 1)

    def test_concurrent_processes_migrate_the_same_legacy_row_keys(self):
        now = time.time()
        nh.history_path().write_text(json.dumps([
            {"id": 3, "summary": "First", "timestamp": now},
            {"id": 3, "summary": "Second", "timestamp": now - 1},
        ]))
        script = (
            "import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
            "import notification_history as h; h.state_dir=lambda:Path(sys.argv[2]); "
            "print(json.dumps([r['history_id'] for r in h.load_history()]))"
        )
        command = [sys.executable, "-B", "-c", script,
                   str(Path(nh.__file__).parent), str(self.state)]
        children = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True) for _ in range(2)]
        try:
            results = []
            for child in children:
                output, error = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, error)
                results.append(json.loads(output))
            self.assertEqual(results[0], results[1])
            self.assertEqual(len(set(results[0])), 2)
            self.assertEqual([row["history_id"] for row in nh.load_history()], results[0])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=2)


class NotificationSettingsPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.patch_dir = patch.object(nh, "state_dir", return_value=self.state)
        self.patch_dir.start()

    def tearDown(self):
        self.patch_dir.stop()
        self.tmp.cleanup()

    def test_page_lifecycle_and_actions(self):
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        from system_controls import NotificationSettings

        class FakePanel:
            def __init__(self):
                self.protect_scroll_controls = lambda w: None
                self.launch = lambda args: None

            def work(self, task, done, failed, commit=False):
                try:
                    res = task()
                    if done:
                        done(res)
                except Exception as e:
                    if failed:
                        failed(e)

        panel = FakePanel()
        page = NotificationSettings(panel)
        page.show_all()

        # Seed initial history and settings
        nh.save_settings({"limit": 100, "expire_days": 7, "enabled": True})
        nh.record_notification({"id": 1, "summary": "Test 1", "body": "Body 1"})
        nh.record_notification({"id": 2, "summary": "Test 2", "body": "Body 2"})

        page.refresh()
        self.assertEqual(page.limit_combo.get_active_id(), "100")
        self.assertEqual(page.expire_combo.get_active_id(), "7")
        self.assertTrue(page.enabled_check.get_active())
        self.assertEqual(len(page.history_container.get_children()), 2)

        # Apply settings change
        page.limit_combo.set_active_id("50")
        page.expire_combo.set_active_id("3")
        page.apply_settings()

        saved = nh.load_settings()
        self.assertEqual(saved["limit"], 50)
        self.assertEqual(saved["expire_days"], 3)

        # Delete single entry
        page.delete_entry(1)
        self.assertEqual(len(nh.load_history()), 1)

        # Clear history
        page.clear_history()
        self.assertEqual(len(nh.load_history()), 1)
        page.confirm_clear_history()
        self.assertEqual(len(nh.load_history()), 0)


if __name__ == "__main__":
    unittest.main()
