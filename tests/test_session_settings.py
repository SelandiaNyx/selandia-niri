"""Session ownership and removal are confined to temporary XDG directories."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import session_settings as owned
import system_settings as settings


class SessionSettingsTests(unittest.TestCase):
    def setUp(self):
        private = tempfile.TemporaryDirectory(prefix="selandia-session-ownership-")
        self.addCleanup(private.cleanup)
        self.root = Path(private.name)
        self.home = self.root / "config"
        patcher = patch.dict(os.environ, XDG_CONFIG_HOME=str(self.home), XDG_STATE_HOME=str(self.root / "state"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.root / "app.desktop"
        self.source.write_text("[Desktop Entry]\nType=Application\nName=App\nExec=app\n")
        gio = MagicMock()
        gio.DesktopAppInfo.new.return_value.get_filename.return_value = str(self.source)
        patcher = patch.object(settings, "_gio", return_value=gio)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(settings, "run", side_effect=self.service)
        patcher.start()
        self.addCleanup(patcher.stop)

    def service(self, argv, **options):
        for unit in argv[3:]:
            if not unit.endswith(".service"):
                continue
            target = self.home / "systemd/user" / unit
            target.parent.mkdir(parents=True, exist_ok=True)
            if argv[2] == "mask":
                if not target.is_symlink():
                    target.symlink_to("/dev/null")
            elif argv[2] == "unmask":
                target.unlink(missing_ok=True)
        return ""

    def test_created_startup_and_masks_are_removed_but_unrelated_files_survive(self):
        settings.add_startup("app.desktop")
        settings.toggle_startup("selandia-niri-app.desktop", False)
        settings.set_service("bar", False)
        unrelated = self.home / "autostart/own.desktop"
        unrelated.write_text("user entry")
        result = owned.restore(self.home)
        self.assertEqual(len(result["restored"]), 2)
        self.assertFalse((self.home / "autostart/selandia-niri-app.desktop").exists())
        self.assertFalse((self.home / "systemd/user/selandia-niri@waybar.service").is_symlink())
        self.assertEqual(unrelated.read_text(), "user entry")
        self.assertFalse(owned.journal_path().exists())

    def test_original_mask_is_restored_after_explicit_enable(self):
        target = self.home / "systemd/user/selandia-niri@waybar.service"
        target.parent.mkdir(parents=True)
        target.symlink_to("/dev/null")
        settings.set_service("bar", True)
        self.assertFalse(target.is_symlink())
        owned.restore(self.home)
        self.assertEqual(os.readlink(target), "/dev/null")

    def test_preexisting_managed_startup_preserves_contents_and_permissions(self):
        target = self.home / "autostart/selandia-niri-app.desktop"
        target.parent.mkdir(parents=True)
        original = self.source.read_bytes() + b"X-Selandia-Niri-Managed=true\nHidden=true\n"
        target.write_bytes(original)
        target.chmod(0o600)
        settings.add_startup("app.desktop")
        owned.restore(self.home)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_later_user_edits_and_unrecorded_legacy_entries_are_preserved(self):
        settings.add_startup("app.desktop")
        target = self.home / "autostart/selandia-niri-app.desktop"
        target.write_text(target.read_text() + "# later edit\n")
        legacy = target.with_name("selandia-niri-legacy.desktop")
        legacy.write_text("unrecorded legacy entry")
        result = owned.restore(self.home)
        self.assertEqual(len(result["preserved"]), 2)
        self.assertIn("later edit", target.read_text())
        self.assertTrue(owned.journal_path().exists())
        with self.assertRaisesRegex(RuntimeError, "Preserving"):
            settings.toggle_startup(target.name, False)

    def test_partial_mask_failure_has_a_restorable_write_ahead_record(self):
        def fail(argv, **options):
            self.service([*argv[:4], argv[4]])
            raise RuntimeError("partial mask failure")
        with patch.object(settings, "run", side_effect=fail):
            with self.assertRaises(RuntimeError):
                settings.set_service("clipboard", False)
        self.assertTrue(owned.journal_path().exists())
        owned.restore(self.home)
        for component in ("clipboard-text", "clipboard-image"):
            self.assertFalse((self.home / "systemd/user" / ("selandia-niri@" + component + ".service")).is_symlink())

    def test_preview_is_read_only_and_rejects_redirected_records(self):
        settings.add_startup("app.desktop")
        before = owned.journal_path().read_bytes()
        self.assertEqual(owned.restoration_plan(self.home)[1], ["autostart/selandia-niri-app.desktop"])
        self.assertEqual(owned.journal_path().read_bytes(), before)
        data = json.loads(before)
        data["files"]["../../foreign"] = next(iter(data["files"].values()))
        owned.journal_path().write_text(json.dumps(data))
        with self.assertRaises(RuntimeError):
            owned.restore(self.home)


if __name__ == "__main__":
    unittest.main()
