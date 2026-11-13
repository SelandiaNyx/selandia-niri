"""Verify that installing this desktop cannot silently overwrite later user edits."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("deploy", Path(__file__).resolve().parents[1] / "tools/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="niri deploy's ")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config, self.state = root / "config", root / "state"
        environment = patch.dict(os.environ, {"LC_ALL": "C.UTF-8"})
        environment.start()
        self.addCleanup(environment.stop)
        for name, value in [("CONFIG", self.config), ("STATE", self.state), ("MANIFEST", self.state / "install.json")]:
            p = patch.object(deploy, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(deploy.subprocess, "run", return_value=__import__("subprocess").CompletedProcess([], 0))
        self.subprocess_run = p.start()
        self.addCleanup(p.stop)
        self.config.mkdir()
        (self.config / "niri").mkdir()
        (self.config / "niri/config.kdl").write_text("old settings\n")
        (self.config / "hypr").mkdir()
        (self.config / "hypr/keep").write_text("untouched")

    def assert_originals(self):
        self.assertFalse((self.config / "niri").is_symlink())
        self.assertEqual((self.config / "niri/config.kdl").read_text(), "old settings\n")
        self.assertEqual((self.config / "hypr/keep").read_text(), "untouched")

    def snapshot(self):
        result = {}
        for path in Path(self.temp.name).rglob("*"):
            metadata = path.lstat()
            if path.is_symlink():
                value = ("link", str(path.readlink()))
            elif path.is_file():
                value = ("file", path.read_bytes())
            else:
                value = ("directory",)
            result[str(path)] = (value, metadata.st_mtime_ns)
        return result

    def test_reinstall_and_restore_directory_and_dangling_link(self):
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        portal.parent.mkdir()
        portal.symlink_to("old-missing-portal.conf")
        deploy.install()
        self.assertTrue((self.config / "niri").is_symlink())
        deploy.install()
        deploy.uninstall()
        self.assert_originals()
        self.assertEqual(portal.readlink(), Path("old-missing-portal.conf"))
        self.assertFalse(deploy.MANIFEST.exists())
        self.assertFalse((self.config / "systemd/user/selandia-niri@.service").exists())

    def test_reinstall_repairs_missing_portal_preserving_original_backup(self):
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        portal.parent.mkdir()
        portal.write_text("original portal settings\n")
        deploy.install()
        manifest = json.loads(deploy.MANIFEST.read_text())
        entry = manifest["entries"]["xdg-desktop-portal/niri-portals.conf"]
        original = Path(entry["original"])
        portal.unlink()

        deploy.install()

        self.assertTrue(deploy.matches(portal, entry["installed"]))
        self.assertEqual(json.loads(deploy.MANIFEST.read_text()), manifest)
        self.assertEqual(original.read_text(), "original portal settings\n")
        deploy.uninstall()
        self.assertEqual(portal.read_text(), "original portal settings\n")
        self.assert_originals()

    def test_reinstall_repairs_missing_portal_without_inventing_original(self):
        deploy.install()
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        manifest = json.loads(deploy.MANIFEST.read_text())
        entry = manifest["entries"]["xdg-desktop-portal/niri-portals.conf"]
        self.assertIsNone(entry["original"])
        portal.unlink()

        deploy.install()

        self.assertTrue(deploy.matches(portal, entry["installed"]))
        self.assertEqual(json.loads(deploy.MANIFEST.read_text()), manifest)
        deploy.uninstall()
        self.assertFalse(deploy.exists(portal))
        self.assert_originals()

    def test_repair_refuses_modified_portal_and_foreign_dangling_symlink(self):
        deploy.install()
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        manifest = deploy.MANIFEST.read_bytes()
        for replacement in ("regular file", "dangling symlink"):
            with self.subTest(replacement=replacement):
                portal.unlink()
                if replacement == "regular file":
                    portal.write_text("my portal settings\n")
                else:
                    portal.symlink_to("my-missing-portal.conf")
                for mode in ("install", "dry-run"):
                    with self.subTest(mode=mode):
                        with patch.object(sys, "argv", ["deploy.py", mode]):
                            with self.assertRaisesRegex(RuntimeError, "Refusing to replace user edits"):
                                if mode == "install":
                                    deploy.install()
                                else:
                                    deploy.main()
                        self.assertEqual(deploy.MANIFEST.read_bytes(), manifest)
                        if replacement == "regular file":
                            self.assertFalse(portal.is_symlink())
                            self.assertEqual(portal.read_text(), "my portal settings\n")
                        else:
                            self.assertEqual(portal.readlink(), Path("my-missing-portal.conf"))

    def test_failed_repair_restores_missing_portal_and_preserves_manifest(self):
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        portal.parent.mkdir()
        portal.write_text("original portal settings\n")
        deploy.install()
        manifest = deploy.MANIFEST.read_bytes()
        original = Path(json.loads(manifest)["entries"]["xdg-desktop-portal/niri-portals.conf"]["original"])
        portal.unlink()

        with patch.object(deploy, "save_manifest", side_effect=OSError("simulated manifest write failure")):
            with self.assertRaisesRegex(OSError, "simulated manifest write failure"):
                deploy.install()

        self.assertFalse(deploy.exists(portal))
        self.assertEqual(deploy.MANIFEST.read_bytes(), manifest)
        self.assertEqual(original.read_text(), "original portal settings\n")
        for relative, entry in json.loads(manifest)["entries"].items():
            if relative != "xdg-desktop-portal/niri-portals.conf":
                self.assertTrue(deploy.matches(self.config / relative, entry["installed"]))

    def test_dry_run_reports_missing_portal_repair_without_writes(self):
        deploy.install()
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        portal.unlink()

        def snapshot():
            result = {}
            for path in Path(self.temp.name).rglob("*"):
                metadata = path.lstat()
                if path.is_symlink():
                    value = ("link", str(path.readlink()))
                elif path.is_file():
                    value = ("file", path.read_bytes())
                else:
                    value = ("directory",)
                result[str(path)] = (value, metadata.st_mtime_ns)
            return result

        before = snapshot()
        output = io.StringIO()
        with patch.object(sys, "argv", ["deploy.py", "dry-run"]), patch.object(sys, "stdout", output):
            deploy.main()

        self.assertIn("Repair missing", output.getvalue())
        self.assertIn(str(portal), output.getvalue())
        self.assertEqual(snapshot(), before)
        self.assertFalse(deploy.exists(portal))

    def test_refuse_foreign_modification_before_uninstall(self):
        deploy.install()
        unit = self.config / "systemd/user/selandia-niri@.service"
        unit.write_text("user replacement")
        with self.assertRaisesRegex(RuntimeError, "Refusing to replace user edits"):
            deploy.uninstall()
        self.assertEqual(unit.read_text(), "user replacement")
        self.assertTrue(deploy.MANIFEST.exists())
        self.assertTrue((self.config / "niri").is_symlink())

    def test_failed_install_restores_previous_config(self):
        original = deploy.write_spec
        def fail_on_service(path, value):
            if path.name == "selandia-niri@.service":
                raise OSError("simulated disk write failure")
            original(path, value)
        with patch.object(deploy, "write_spec", fail_on_service):
            with self.assertRaisesRegex(OSError, "simulated"):
                deploy.install()
        self.assert_originals()
        self.assertFalse(deploy.MANIFEST.exists())
        self.assertFalse((self.config / "systemd/user/selandia-niri.target").is_symlink())

    def test_quote_systemd_path(self):
        self.assertEqual(deploy.systemd_quote('/tmp/a b\'s/$x%y"'), '"/tmp/a b\'s/$$x%%y\\\""')

    def test_missing_original_backup_refuses_reinstall_and_uninstall(self):
        deploy.install()
        manifest = json.loads(deploy.MANIFEST.read_text())
        original = Path(manifest["entries"]["niri"]["original"])
        original.rename(original.with_name("temporarily-missing"))
        for action in (deploy.install, deploy.uninstall, deploy.preflight, deploy.preview_uninstall):
            with self.assertRaisesRegex(RuntimeError, "Missing original backup"):
                action()
        self.assertTrue((self.config / "niri").is_symlink())
        self.assertEqual(json.loads(deploy.MANIFEST.read_text()), manifest)

    def test_failed_uninstall_restores_the_installed_state(self):
        deploy.install()
        original_move = shutil.move
        def fail_portal(source, target):
            if str(source) == str(self.config / "xdg-desktop-portal/niri-portals.conf"):
                raise OSError("simulated restore failure")
            return original_move(source, target)
        with patch.object(deploy.shutil, "move", fail_portal):
            with self.assertRaisesRegex(OSError, "simulated"):
                deploy.uninstall()
        self.assertTrue(deploy.MANIFEST.exists())
        deploy.check_owned(json.loads(deploy.MANIFEST.read_text())["entries"])
        deploy.uninstall()
        self.assert_originals()

    def test_uninstall_restores_originals_when_managed_targets_were_removed(self):
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        portal.parent.mkdir()
        portal.write_text("original portal\n")
        deploy.install()
        (self.config / "niri").unlink()
        portal.unlink()
        portal.parent.rmdir()
        unit = self.config / "systemd/user/selandia-niri@.service"
        unit.unlink()

        deploy.uninstall()

        self.assert_originals()
        self.assertEqual(portal.read_text(), "original portal\n")
        self.assertFalse(deploy.exists(unit))
        self.assertFalse(deploy.MANIFEST.exists())

    def test_failed_uninstall_rolls_back_restored_original_of_absent_target(self):
        deploy.install()
        (self.config / "niri").unlink()
        manifest = deploy.MANIFEST.read_bytes()
        original = Path(json.loads(manifest)["entries"]["niri"]["original"])
        original_move = shutil.move

        def fail_portal(source, target):
            if str(source) == str(self.config / "xdg-desktop-portal/niri-portals.conf"):
                raise OSError("simulated restore failure")
            return original_move(source, target)

        with patch.object(deploy.shutil, "move", fail_portal):
            with self.assertRaisesRegex(OSError, "simulated restore failure"):
                deploy.uninstall()

        self.assertFalse(deploy.exists(self.config / "niri"))
        self.assertEqual((original / "config.kdl").read_text(), "old settings\n")
        self.assertEqual(deploy.MANIFEST.read_bytes(), manifest)
        deploy.check_owned(json.loads(manifest)["entries"], allow_missing=True)
        deploy.uninstall()
        self.assert_originals()

    def test_uninstall_preview_is_read_only_with_missing_managed_target(self):
        deploy.install()
        (self.config / "niri").unlink()
        before = self.snapshot()
        self.subprocess_run.reset_mock()
        output = io.StringIO()

        with patch.object(sys, "argv", ["deploy.py", "dry-run-uninstall"]), patch.object(sys, "stdout", output):
            deploy.main()

        self.assertIn("Already absent", output.getvalue())
        self.assertIn("Restore original", output.getvalue())
        self.assertEqual(self.snapshot(), before)
        self.subprocess_run.assert_not_called()

    def test_uninstall_preview_without_manifest_does_not_create_state(self):
        before = self.snapshot()
        with patch.object(sys, "argv", ["deploy.py", "dry-run-uninstall"]):
            deploy.main()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state.exists())
        self.subprocess_run.assert_not_called()

    def test_uninstall_stop_failure_leaves_all_files_untouched(self):
        deploy.install()
        for failure in (subprocess.CompletedProcess([], 1), FileNotFoundError("systemctl")):
            with self.subTest(failure=failure):
                before = self.snapshot()
                kwargs = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with patch.object(deploy.subprocess, "run", **kwargs):
                    with self.assertRaisesRegex(RuntimeError, "configuration was not changed"):
                        deploy.uninstall()
                self.assertEqual(self.snapshot(), before)

    def test_uninstall_does_not_require_intact_project_sources(self):
        deploy.install()
        output = io.StringIO()
        with patch.object(deploy, "ROOT", Path(self.temp.name) / "deleted-project"), \
                patch.dict(sys.modules, {"session_settings": None}):
            with patch("sys.stdout", output):
                deploy.preview_uninstall()
            deploy.uninstall()
        self.assertIn("helper unavailable", output.getvalue())
        self.assert_originals()

    def test_preflight_accepts_missing_target_but_refuses_foreign_edits_without_mutation(self):
        deploy.install()
        portal = self.config / "xdg-desktop-portal/niri-portals.conf"
        portal.unlink()
        self.subprocess_run.reset_mock()
        before = self.snapshot()
        with patch.object(sys, "argv", ["deploy.py", "preflight"]):
            deploy.main()
        self.assertEqual(self.snapshot(), before)

        portal.write_text("my replacement\n")
        before = self.snapshot()
        with patch.object(sys, "argv", ["deploy.py", "preflight"]):
            with self.assertRaisesRegex(RuntimeError, "Refusing to replace user edits"):
                deploy.main()
        self.assertEqual(self.snapshot(), before)
        self.subprocess_run.assert_not_called()

    def test_preflight_refuses_missing_project_script_before_any_writes(self):
        checkout = Path(self.temp.name) / "checkout"
        for relative in deploy.REQUIRED_SOURCES:
            path = checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(deploy.ROOT / relative, path)
        (checkout / "niri/scripts/components").unlink()
        before = self.snapshot()
        with patch.object(deploy, "ROOT", checkout):
            for action in (deploy.preflight, deploy.install, deploy.preview_install):
                with self.subTest(action=action.__name__):
                    with self.assertRaisesRegex(RuntimeError, "niri/scripts/components"):
                        action()
                    self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state.exists())
        self.subprocess_run.assert_not_called()

    def test_status_reports_uninstalled_missing_and_stale_config_without_mutation(self):
        before = self.snapshot()
        self.assertEqual(deploy.status(), 1)
        self.assertEqual(self.snapshot(), before)
        deploy.install()
        self.subprocess_run.reset_mock()
        before = self.snapshot()
        self.assertEqual(deploy.status(), 0)
        desired = deploy.desired()
        updated = {**desired, "systemd/user/selandia-niri@.service": {"text": "new service\n"}}
        output = io.StringIO()
        with patch.object(deploy, "desired", return_value=updated), patch.object(sys, "stdout", output):
            self.assertEqual(deploy.status(), 1)
        self.assertIn("Update needed", output.getvalue())
        self.assertEqual(self.snapshot(), before)

        (self.config / "niri").unlink()
        before = self.snapshot()
        output = io.StringIO()
        with patch.object(sys, "stdout", output):
            self.assertEqual(deploy.status(), 1)
        self.assertIn("Missing managed file", output.getvalue())
        self.assertEqual(self.snapshot(), before)
        self.subprocess_run.assert_not_called()

    def test_reinstall_updates_generated_unit_preserving_first_backup(self):
        unit = self.config / "systemd/user/selandia-niri@.service"
        unit.parent.mkdir(parents=True)
        unit.write_text("original service\n")
        deploy.install()
        original = deploy.desired()
        updated = {**original, "systemd/user/selandia-niri@.service": {"text": "new generated service\n"}}
        with patch.object(deploy, "desired", return_value=updated):
            deploy.install()
            self.assertEqual(unit.read_text(), "new generated service\n")
            deploy.uninstall()
        self.assertEqual(unit.read_text(), "original service\n")
        self.assert_originals()

    def test_dry_run_does_not_create_state(self):
        with patch.object(sys, "argv", ["deploy.py", "dry-run"]):
            deploy.main()
        self.assertFalse(self.state.exists())
        self.assert_originals()

    def test_saved_interface_language_controls_diagnostics_without_writes(self):
        self.state.mkdir()
        preferences = self.state / "language.json"
        for language, expected, absent in (("zh_CN", "尚未安装", "Not installed"),
                                          ("en_US", "Not installed", "尚未安装")):
            preferences.write_text(json.dumps({"ui_language": language}))
            before = self.snapshot()
            output = io.StringIO()
            with self.subTest(language=language), patch.object(sys, "stdout", output):
                self.assertEqual(deploy.status(), 1)
            self.assertIn(expected, output.getvalue())
            self.assertNotIn(absent, output.getvalue())
            self.assertEqual(self.snapshot(), before)
        self.subprocess_run.assert_not_called()

    def test_invalid_language_preferences_do_not_block_recovery(self):
        self.state.mkdir()
        preferences = self.state / "language.json"
        for invalid in ("{broken", "[]", "null"):
            preferences.write_text(invalid)
            self.assertEqual(deploy.tr("Ready", "正常"), "Ready")

    def test_system_interface_language_follows_saved_session_locale(self):
        self.state.mkdir()
        (self.state / "language.json").write_text(json.dumps({"ui_language": "system",
                                                            "session_locale": "zh_CN.UTF-8"}))
        self.assertEqual(deploy.tr("Ready", "正常"), "正常")

    def test_root_refused_before_any_config_or_state_write(self):
        with patch.object(sys, "argv", ["deploy.py", "install"]), patch.object(os, "geteuid", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "desktop user"):
                deploy.main()
        self.assertFalse(self.state.exists())
        self.assert_originals()

    def test_simultaneous_deployment_is_refused(self):
        with deploy.deployment_lock():
            with self.assertRaisesRegex(RuntimeError, "Another setup"):
                with deploy.deployment_lock():
                    self.fail("A second transaction acquired the lock")
        self.assert_originals()

    def test_malformed_manifest_is_rejected_without_changes(self):
        self.state.mkdir()
        deploy.MANIFEST.write_text('{"entries": {"niri": {"installed": 42}}}')
        with self.assertRaisesRegex(RuntimeError, "Invalid installation entry"):
            deploy.install()
        self.assert_originals()


    def test_hand_written_sources_are_all_covered_by_preflight(self):
        """A new source file must be added to REQUIRED_SOURCES, or preflight lies.

        Generated files under niri/theme and niri/swayidle/managed.conf are
        produced by this project at runtime and are deliberately not required.
        """
        listed = set(deploy.REQUIRED_SOURCES)
        generated = {"managed.conf"}
        sources = [path for path in (deploy.ROOT / "niri").rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts]
        missing = []
        for path in sources:
            relative = str(path.relative_to(deploy.ROOT))
            name = path.name
            if relative.startswith("niri/theme/") or name in generated:
                continue
            if path.suffix not in (".py", ".sh", ".css", ".svg", ".kdl", ".json", ".jsonc", ".conf", ".ini"):
                continue
            if relative not in listed:
                missing.append(relative)
        self.assertEqual(sorted(missing), [], "add these to deploy.REQUIRED_SOURCES")


if __name__ == "__main__":
    unittest.main()
