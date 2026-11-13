"""Publication failures and SIGKILL recovery, entirely in disposable directories."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import live_update


class LiveUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-live-update-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.target = self.root / "source", self.root / "target"
        self.source.mkdir()
        self.target.mkdir()
        for name in ("one", "two"):
            (self.source / name).write_text("new-" + name)
            (self.target / name).write_text("old-" + name)
        self.journal = self.root / "release"
        self.update = live_update.Update(self.target, self.journal)

    def test_success_and_explicit_rollback_restore_original_bytes(self):
        self.update.prepare(self.source, ["one", "two"])
        self.update.publish()
        self.assertEqual((self.target / "one").read_text(), "new-one")
        self.update.rollback()
        self.assertEqual((self.target / "one").read_text(), "old-one")
        self.assertEqual(self.update.read()["phase"], "rolled-back")

    def test_failed_reload_restores_every_file_and_reloads_old_configuration(self):
        self.update.prepare(self.source, ["one", "two"])
        calls = []
        def activate():
            calls.append((self.target / "one").read_text())
            if len(calls) == 1:
                raise RuntimeError("reload failed")
        with self.assertRaisesRegex(RuntimeError, "reload failed"):
            self.update.publish(activate)
        self.assertEqual(calls, ["new-one", "old-one"])
        self.assertEqual((self.target / "two").read_text(), "old-two")

    def test_killed_publisher_can_recover_all_files_from_durable_journal(self):
        self.update.prepare(self.source, ["one", "two"])
        marker = self.root / "ready"
        program = '''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import live_update
update=live_update.Update(sys.argv[2],sys.argv[3])
real=live_update.atomic
def blocked(path,data,mode=0o644):
 real(path,data,mode)
 if path == update.target / "one":
  Path(sys.argv[4]).write_text("ready")
  while True: time.sleep(.1)
live_update.atomic=blocked
update.publish()
'''
        child = subprocess.Popen([sys.executable, "-B", "-c", program, str(ROOT / "tools"), str(self.target), str(self.journal), str(marker)])
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        deadline = time.monotonic() + 4
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(marker.exists())
        child.kill()
        child.wait(timeout=3)
        self.assertEqual(self.update.read()["phase"], "publishing")
        self.update.rollback()
        self.assertEqual((self.target / "one").read_text(), "old-one")
        self.assertEqual((self.target / "two").read_text(), "old-two")

    def test_rollback_preserves_later_user_edits_before_any_mutation(self):
        self.update.prepare(self.source, ["one", "two"])
        self.update.publish()
        (self.target / "two").write_text("user change")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.update.rollback()
        self.assertEqual((self.target / "one").read_text(), "new-one")
        self.assertEqual((self.target / "two").read_text(), "user change")

    def test_symlink_and_path_escape_are_rejected_before_publication(self):
        (self.target / "one").unlink()
        (self.target / "one").symlink_to(self.root / "other")
        for name in ("one", "../other"):
            with self.assertRaises(ValueError):
                self.update.location(name)

    def test_appearance_state_and_new_files_are_rolled_back_with_source(self):
        state = self.root / "state/appearance.json"
        state.parent.mkdir()
        state.write_text("old preferences")
        (self.source / "new-module").write_text("new module")
        update = live_update.Update(self.target, self.journal, state_path=state)
        update.prepare(self.source, ["one", "new-module"], appearance=b"new preferences")
        update.publish()
        self.assertEqual(state.stat().st_mode & 0o777, 0o600)
        update.rollback()
        self.assertEqual(state.read_text(), "old preferences")
        self.assertFalse((self.target / "new-module").exists())

    def test_checksum_failure_cannot_publish_corrupt_staged_source(self):
        self.update.prepare(self.source, ["one", "two"])
        (self.journal / "new-1").write_text("corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.update.publish()
        self.assertEqual((self.target / "one").read_text(), "old-one")

    def test_edit_after_preparation_preserves_entire_live_batch(self):
        self.update.prepare(self.source, ["one", "two"])
        (self.target / "two").write_text("new user edit")
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            self.update.publish()
        self.assertEqual((self.target / "one").read_text(), "old-one")
        self.assertEqual((self.target / "two").read_text(), "new user edit")
        self.assertEqual(self.update.read()["phase"], "prepared")

    def test_corrupt_payload_is_found_before_any_live_write(self):
        self.update.prepare(self.source, ["one", "two"])
        (self.journal / "new-1").write_bytes(b"corrupt")
        with patch.object(live_update, "atomic") as write, self.assertRaisesRegex(ValueError, "checksum"):
            self.update.publish()
        write.assert_not_called()

    def test_corrupt_backup_is_found_before_any_rollback_write(self):
        self.update.prepare(self.source, ["one", "two"])
        self.update.publish()
        (self.journal / "old-0").write_bytes(b"corrupt")
        with patch.object(live_update, "atomic") as write, self.assertRaisesRegex(ValueError, "backup checksum"):
            self.update.rollback()
        write.assert_not_called()
        self.assertEqual((self.target / "two").read_text(), "new-two")

    def test_continually_replaced_main_process_does_not_pass_readiness(self):
        reloader = Mock()
        reloader.active.return_value = True
        reloader.service.side_effect = [str(pid) for pid in range(100, 200)]
        now = [0.]
        def sleep(delay):
            now[0] += delay
        with patch.object(live_update.time, "monotonic", side_effect=lambda: now[0]), \
                patch.object(live_update.time, "sleep", side_effect=sleep), self.assertRaisesRegex(RuntimeError, "did not remain ready"):
            live_update.verify_components(reloader, ["waybar"], timeout=3)

    def test_asynchronous_reload_failure_is_not_reported_as_ready(self):
        reloader = Mock()
        reloader.active.return_value = False
        with self.assertRaisesRegex(RuntimeError, "did not remain ready"):
            live_update.verify_components(reloader, ["waybar"], timeout=.02)

    def test_component_with_no_main_process_is_not_reported_as_ready(self):
        reloader = Mock()
        reloader.active.return_value = True
        reloader.service.return_value = "0"
        with self.assertRaisesRegex(RuntimeError, "did not remain ready"):
            live_update.verify_components(reloader, ["waybar"], timeout=.02)

    def test_appearance_concurrent_edit_is_rejected_before_publication(self):
        state = self.root / "appearance.json"
        state.write_bytes(b"user edit")
        update = live_update.Update(self.target, self.journal, state_path=state)
        with self.assertRaisesRegex(ValueError, "changed since staging"):
            update.prepare(self.source, ["one"], expected={"one": live_update.digest(b"old-one"),
                           "@appearance": live_update.digest(b"old preferences")}, appearance=b"new preferences")
        self.assertEqual(state.read_bytes(), b"user edit")
        self.assertEqual((self.target / "one").read_text(), "old-one")
