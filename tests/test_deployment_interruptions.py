"""Real SIGKILL tests: no Python exception handler can perform the recovery."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r'''
import os,signal,subprocess,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, os.environ['TEST_SOURCE']+'/tools')
import deploy,transactions
point=os.environ.get('TEST_KILL_POINT','')
def die(): os.kill(os.getpid(),signal.SIGKILL)
move=transactions.Transaction.move
create=deploy.write_spec
manifest=deploy.save_manifest
save=transactions.Transaction.save
rename=transactions.os.rename
def moving(self, source, target):
    move(self, source, target)
    if point=='after-backup' and source==deploy.CONFIG/'niri': die()
    if point=='after-original-restore' and target==deploy.CONFIG/'niri': die()
    if point=='after-manifest-archive' and source==deploy.MANIFEST: die()
def creating(path, spec):
    if point=='before-first-create' and path==deploy.CONFIG/'niri': die()
    create(path,spec)
    if point=='after-first-create' and path==deploy.CONFIG/'niri': die()
    if point=='after-service-create' and path.name=='selandia-niri@.service': die()
def manifesting(data):
    manifest(data)
    if point=='after-manifest-write': die()
def saving(self):
    if point=='during-recovery' and self.path.exists() and self.data['operations']:
        die()  # Undo happened; its durable progress update has not.
    save(self)
def renaming(source,target):
    if point=='cross-copy-before-hold' and Path(source)==deploy.CONFIG/'niri': die()
    rename(source,target)
    if point=='cross-after-hold' and Path(source)==deploy.CONFIG/'niri': die()
def isolated(command,**kwargs):
    if point=='during-service-recovery' and 'start' in command: die()
    return subprocess.CompletedProcess(command,0)
deploy.subprocess.run=isolated
transactions.Transaction.move=moving
deploy.write_spec=creating
deploy.save_manifest=manifesting
if point=='during-recovery': transactions.Transaction.save=saving
if point.startswith('cross-'):
    transactions.Transaction.same_filesystem=staticmethod(lambda *args:False)
    transactions.os.rename=renaming
sys.argv=[deploy.__file__,sys.argv[1]]
try: deploy.main()
except (OSError,ValueError,RuntimeError) as error:
    print(error,file=sys.stderr); sys.exit(1)
'''


@unittest.skipIf(os.geteuid() == 0, "Deployment requires the desktop user")
class InterruptedDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="selandia-sigkill-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config, self.state = self.root / "config", self.root / "state/selandia-niri"
        (self.config / "niri").mkdir(parents=True)
        original = self.config / "niri/original.kdl"
        original.write_text("original desktop\n")
        original.chmod(0o600)
        (self.config / "unrelated").write_text("keep me")
        self.source = ROOT

    def child(self, mode, point="", success=True):
        environment = dict(os.environ, TEST_SOURCE=str(self.source), TEST_KILL_POINT=point,
                           XDG_CONFIG_HOME=str(self.config), XDG_STATE_HOME=str(self.state.parent),
                           NIRI_SOCKET="", PYTHONDONTWRITEBYTECODE="1", LC_ALL="C.UTF-8")
        result = subprocess.run([sys.executable, "-B", "-c", DRIVER, mode],
                                env=environment, capture_output=True, text=True, timeout=10)
        if point:
            self.assertEqual(result.returncode, -signal.SIGKILL, result.stdout + result.stderr)
        elif success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def originals(self):
        self.assertFalse((self.config / "niri").is_symlink())
        self.assertEqual((self.config / "niri/original.kdl").read_text(), "original desktop\n")
        self.assertEqual((self.config / "niri/original.kdl").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.config / "unrelated").read_text(), "keep me")
        self.assertFalse((self.state / "install.json").exists())
        self.assertFalse((self.state / "deployment-transaction.json").exists())

    def snapshot(self):
        result = {}
        for base in (self.config, self.state):
            for path in base.rglob("*"):
                if path.is_symlink():
                    result[str(path)] = os.readlink(path)
                elif path.is_file():
                    metadata = path.stat()
                    result[str(path)] = (path.read_bytes(), metadata.st_mode, metadata.st_mtime_ns)
        return result

    def test_install_sigkill_at_each_boundary_recovers_before_uninstall(self):
        for point in ("after-backup", "before-first-create", "after-first-create", "after-service-create", "after-manifest-write"):
            with self.subTest(point=point):
                self.child("install", point)
                self.assertTrue((self.state / "deployment-transaction.json").is_file())
                before = self.snapshot()
                self.child("dry-run")
                self.assertEqual(self.snapshot(), before)
                self.child("uninstall")
                self.originals()

    def test_uninstall_sigkill_at_each_boundary_restores_installed_state(self):
        for point in ("after-backup", "after-original-restore", "after-manifest-archive"):
            with self.subTest(point=point):
                self.child("install")
                installed = (self.state / "install.json").read_bytes()
                self.child("uninstall", point)
                self.child("recover")
                self.assertTrue((self.config / "niri").is_symlink())
                self.assertEqual((self.state / "install.json").read_bytes(), installed)
                entry = json.loads(installed)["entries"]["niri"]
                self.assertEqual((Path(entry["original"]) / "original.kdl").read_text(), "original desktop\n")
                self.child("uninstall")
                self.originals()

    def test_sigkill_during_undo_is_idempotent(self):
        self.child("install", "after-service-create")
        self.child("recover", "during-recovery")
        self.child("recover")
        self.originals()

    def test_sigkill_during_service_recovery_keeps_durable_record(self):
        self.child("install")
        installed = (self.state / "install.json").read_bytes()
        self.child("uninstall", "after-backup")
        self.child("recover", "during-service-recovery")
        self.assertTrue((self.state / "deployment-transaction.json").exists())
        self.child("recover")
        self.assertEqual((self.state / "install.json").read_bytes(), installed)
        self.assertTrue((self.config / "niri").is_symlink())
        self.child("uninstall")
        self.originals()

    def test_recovery_preserves_foreign_edit_and_keeps_journal(self):
        self.child("install", "after-first-create")
        target = self.config / "niri"
        target.unlink()
        target.write_text("new user configuration")
        result = self.child("recover", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Preserving", result.stderr)
        self.assertEqual(target.read_text(), "new user configuration")
        self.assertTrue((self.state / "deployment-transaction.json").exists())
        target.unlink()
        self.child("recover")
        self.originals()

    def test_cross_filesystem_copy_and_hold_interruptions_recover(self):
        for point in ("cross-copy-before-hold", "cross-after-hold"):
            with self.subTest(point=point):
                self.child("install", point)
                self.child("recover")
                self.originals()
                self.assertFalse(list(self.config.glob(".niri.selandia-*")))

    def test_interrupted_update_keeps_first_original_backup(self):
        self.child("install")
        original_manifest = (self.state / "install.json").read_bytes()
        self.source = self.root / "new-checkout"
        shutil.copytree(ROOT, self.source, ignore=shutil.ignore_patterns(".validation", ".staging", ".git", ".local", "dist", "__pycache__", "*.pyc"))
        self.child("install", "after-first-create")
        self.child("recover")
        self.assertEqual((self.state / "install.json").read_bytes(), original_manifest)
        self.child("uninstall")
        self.originals()


if __name__ == "__main__":
    unittest.main()
