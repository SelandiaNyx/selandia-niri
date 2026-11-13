"""Setup failure must leave the active source, deployment and preferences intact."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import lifecycle

CRASH_DRIVER = r'''
import json,os,signal,subprocess,sys
from pathlib import Path
sys.path.insert(0,os.environ['TEST_SOURCE']+'/tools')
import lifecycle
point=os.environ.get('TEST_KILL_POINT','')
settings=Path(os.environ['TEST_DESKTOP'])
def die(): os.kill(os.getpid(),signal.SIGKILL)
class Desktop:
    def read(self): return json.loads(settings.read_text()) if settings.exists() else {}
    def user(self,key): return self.read().get(key)
    def get(self,key): return self.user(key) or "'original'"
    def default(self,key): return "'original'"
    def set(self,key,value):
        data=self.read(); data[key]=value; settings.write_text(json.dumps(data))
        if point=='during-gsettings' and key=='font-name': die()
run=subprocess.run
def isolated(command,**kwargs):
    if command[0] in ('systemctl','gdbus','dbus-update-activation-environment'):
        return subprocess.CompletedProcess(command,0,stdout='',stderr='')
    return run(command,**kwargs)
subprocess.run=isolated
replace=lifecycle.Transaction.replace
save=lifecycle.Transaction.save
install=lifecycle.deploy.install
uninstall=lifecycle.deploy.uninstall
def replacing(self,path,before,after):
    replace(self,path,before,after)
    if point=='after-file' and self.path==lifecycle.journal_path(): die()
    if point=='after-session-record' and Path(path)==lifecycle.deploy.STATE/lifecycle.session_settings.JOURNAL: die()
def saving(self):
    save(self)
    if point=='after-commit-decision' and self.path==lifecycle.journal_path() and self.data['phase']=='committed': die()
def installing(**kwargs):
    result=install(**kwargs)
    if point=='after-deployment': die()
    return result
def uninstalling(**kwargs):
    result=uninstall(**kwargs)
    if point=='after-deployment': die()
    return result
lifecycle.Transaction.replace=replacing
lifecycle.Transaction.save=saving
lifecycle.deploy.install=installing
lifecycle.deploy.uninstall=uninstalling
if sys.argv[1]=='recover':
    with lifecycle.deploy.deployment_lock(): lifecycle.recover(Desktop())
else: lifecycle.run(sys.argv[1],Desktop())
'''


class Desktop:
    def __init__(self):
        self.users = {key: None for key in lifecycle.application_theme.GSETTINGS_KEYS}
        self.calls = []
        self.fail = None

    def user(self, key):
        return self.users[key]

    def get(self, key):
        return self.users[key] or "'original'"

    def default(self, key):
        return "'original'"

    def set(self, key, value):
        self.calls.append((key, value))
        if key == self.fail:
            self.fail = None
            raise RuntimeError("injected GSettings failure")
        self.users[key] = value


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="selandia-lifecycle-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project, self.config, self.state = self.root / "project", self.root / 'config name\'s "quotes"', self.root / "state/selandia-niri"
        self.project.mkdir()
        for name in ("niri", "tools", "systemd", "portals", "docs"):
            shutil.copytree(ROOT / name, self.project / name, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("control.sh", "check.sh", "install.sh", "packages.txt"):
            shutil.copy2(ROOT / name, self.project / name)
        (self.config / "niri").mkdir(parents=True)
        (self.config / "niri/original.kdl").write_text("original desktop")
        self.state.mkdir(parents=True)
        (self.state / "appearance.json").write_text('{"preset":"violet","color_mode":"light"}')
        (self.state / "language.json").write_text('{"session_locale":"C.UTF-8"}')
        self.desktop = Desktop()
        self.commands = []
        self.stop_fails = False
        original_run = subprocess.run
        def run(command, **kwargs):
            self.commands.append(command)
            if command[0] in ("systemctl", "dbus-update-activation-environment", "gdbus"):
                code = int(self.stop_fails and "stop" in command)
                return subprocess.CompletedProcess(command, code, stdout="", stderr="")
            return original_run(command, **kwargs)
        for owner, name, value in ((lifecycle.deploy, "ROOT", self.project),
                                   (lifecycle.deploy, "CONFIG", self.config),
                                   (lifecycle.deploy, "STATE", self.state),
                                   (lifecycle.deploy, "MANIFEST", self.state / "install.json"),
                                   (subprocess, "run", run)):
            stub = patch.object(owner, name, value)
            stub.start()
            self.addCleanup(stub.stop)
        stub = patch.dict(os.environ, XDG_CONFIG_HOME=str(self.config), XDG_STATE_HOME=str(self.state.parent),
                          XDG_CACHE_HOME=str(self.root / "cache"), NIRI_SOCKET="", LC_ALL="C.UTF-8")
        stub.start()
        self.addCleanup(stub.stop)

    def snapshot(self):
        result = {}
        paths = set(lifecycle.targets()) | {lifecycle.deploy.MANIFEST}
        paths.update((self.project / "niri").rglob("*"))
        paths.update(self.config.rglob("*"))
        for path in paths:
            if path.is_symlink():
                result[str(path)] = ("link", os.readlink(path))
            elif path.is_file():
                metadata = path.stat()
                result[str(path)] = (path.read_bytes(), metadata.st_mode, metadata.st_mtime_ns)
        return result

    def install(self):
        lifecycle.run("install", self.desktop)

    def test_invalid_config_preserves_all_live_files_and_runtime(self):
        with (self.project / "niri/config.kdl").open("a") as stream:
            stream.write("\ninvalid-node-for-setup-test\n")
        before = self.snapshot()
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.desktop.calls, [])
        self.assertFalse(any(command[0] == "systemctl" for command in self.commands))
        self.assertFalse(lifecycle.journal_path().exists())

    def test_deployment_failure_rolls_back_generated_files_and_language(self):
        before = self.snapshot()
        create = lifecycle.deploy.write_spec
        def fail(path, spec):
            if path.name == "selandia-niri@.service":
                raise OSError("injected deployment failure")
            create(path, spec)
        with patch.object(lifecycle.deploy, "write_spec", side_effect=fail):
            with self.assertRaisesRegex(OSError, "injected"):
                self.install()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.desktop.calls, [])

    def test_staged_validation_still_checks_tools_and_root_shell_scripts(self):
        for relative, contents in (("tools/invalid_for_test.py", "def invalid syntax\n"),
                                   ("invalid_for_test.sh", "#!/bin/bash\nif broken\n")):
            with self.subTest(source=relative):
                source = self.project / relative
                source.write_text(contents)
                before = self.snapshot()
                try:
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.install()
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(self.desktop.calls, [])
                    self.assertFalse(lifecycle.journal_path().exists())
                finally:
                    source.unlink()

    def test_gsettings_failure_rolls_back_deployment_files_and_preferences(self):
        before = self.snapshot()
        self.desktop.fail = "font-name"
        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.install()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(value is None for value in self.desktop.users.values()))
        self.assertFalse(lifecycle.deploy.transaction_path().exists())
        self.assertFalse(lifecycle.journal_path().exists())

    def test_gsettings_rollback_handles_delayed_gio_user_value_cache(self):
        before = self.snapshot()
        self.desktop.fail = "font-name"
        with patch.object(self.desktop, "user", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.install()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(all(value is None for value in self.desktop.users.values()))
        self.assertFalse(lifecycle.journal_path().exists())

    def test_uninstall_stop_failure_leaves_language_and_theme_unchanged(self):
        self.install()
        before = self.snapshot()
        users = dict(self.desktop.users)
        self.stop_fails = True
        with self.assertRaisesRegex(RuntimeError, "Could not stop"):
            lifecycle.run("uninstall", self.desktop)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.desktop.users, users)

    def test_uninstall_restores_tracked_startup_and_component_masks(self):
        self.install()
        entry = self.config / "autostart/selandia-niri-app.desktop"
        contents = b"[Desktop Entry]\nType=Application\nExec=app\nX-Selandia-Niri-Managed=true\n"
        value = {"bytes": base64.b64encode(contents).decode(), "mode": 0o644}
        mask = self.config / "systemd/user/selandia-niri@waybar.service"
        with lifecycle.session_settings.record_changes(self.config, {
                "autostart/selandia-niri-app.desktop": value,
                "systemd/user/selandia-niri@waybar.service": {"link": "/dev/null"}}):
            entry.parent.mkdir(parents=True)
            entry.write_bytes(contents)
            mask.symlink_to("/dev/null")
        lifecycle.run("uninstall", self.desktop)
        self.assertFalse(entry.exists())
        self.assertFalse(mask.is_symlink())
        self.assertFalse((self.state / lifecycle.session_settings.JOURNAL).exists())
        self.assertEqual((self.config / "niri/original.kdl").read_text(), "original desktop")

    def test_uninstall_write_failure_restores_original_deployment_and_journals(self):
        self.install()
        before = self.snapshot()
        replace = lifecycle.Transaction.replace
        def fail(transaction, path, old, new):
            if path == self.config / "gtk-4.0/settings.ini":
                raise OSError("injected restore failure")
            return replace(transaction, path, old, new)
        with patch.object(lifecycle.Transaction, "replace", fail):
            with self.assertRaisesRegex(OSError, "injected"):
                lifecycle.run("uninstall", self.desktop)
        self.assertEqual(self.snapshot(), before)
        lifecycle.run("uninstall", self.desktop)
        self.assertEqual((self.config / "niri/original.kdl").read_text(), "original desktop")

    def test_success_uses_actual_paths_in_language_and_application_journals(self):
        self.install()
        app = json.loads((self.state / "application-theme.json").read_text())
        language = json.loads((self.state / "language-backup.json").read_text())
        self.assertEqual(app["config_home"], str(self.config))
        self.assertEqual(language["files"]["niri"]["path"], str(self.project / "niri/conf/language.kdl"))
        qt = (self.config / "qt6ct/qt6ct.conf").read_text()
        self.assertIn(json.dumps(str(self.config / "qt6ct/colors/selandia.conf")), qt)
        self.assertNotIn("selandia-setup-", qt)
        self.assertFalse(lifecycle.journal_path().exists())

    def test_project_move_with_language_backup_can_reinstall_and_uninstall(self):
        self.install()
        moved = self.root / "moved checkout's"
        self.project.rename(moved)
        self.project = moved
        with patch.object(lifecycle.deploy, "ROOT", moved):
            self.install()
            record = json.loads((self.state / "language-backup.json").read_text())
            self.assertEqual(record["files"]["niri"]["path"], str(moved / "niri/conf/language.kdl"))
            self.assertEqual((self.config / "niri").resolve(), moved / "niri")
            lifecycle.run("uninstall", self.desktop)
        self.assertEqual((self.config / "niri/original.kdl").read_text(), "original desktop")

    def child(self, mode, point=""):
        environment = dict(os.environ, TEST_SOURCE=str(self.project), TEST_KILL_POINT=point,
                           TEST_DESKTOP=str(self.root / "desktop.json"), PYTHONDONTWRITEBYTECODE="1")
        # Use the original subprocess runner: this is a real independently killed process.
        result = subprocess.Popen([sys.executable, "-B", "-c", CRASH_DRIVER, mode], env=environment,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = result.communicate(timeout=15)
        self.assertEqual(result.returncode, -signal.SIGKILL if point else 0, out + err)

    def test_sigkill_during_install_rolls_back_coordinated_files_deployment_and_gsettings(self):
        before = self.snapshot()
        for point in ("after-file", "after-deployment", "during-gsettings"):
            with self.subTest(point=point):
                self.child("install", point)
                self.assertTrue(lifecycle.journal_path().exists())
                self.child("recover")
                self.assertEqual(self.snapshot(), before)
                values = json.loads((self.root / "desktop.json").read_text()) if (self.root / "desktop.json").exists() else {}
                self.assertTrue(all(value is None for value in values.values()))

    def test_sigkill_after_commit_decision_finishes_both_transactions(self):
        self.child("install", "after-commit-decision")
        published = self.snapshot()
        self.child("recover")
        self.assertEqual(self.snapshot(), published)
        self.assertTrue((self.config / "niri").is_symlink())
        self.assertFalse(lifecycle.journal_path().exists())
        self.assertFalse(lifecycle.deploy.transaction_path().exists())

    def test_low_level_deployer_preserves_pending_coordinated_recovery(self):
        before = self.snapshot()
        self.child("install", "after-deployment")
        interrupted = self.snapshot()
        for action in (lifecycle.deploy.install, lifecycle.deploy.uninstall):
            with self.assertRaisesRegex(RuntimeError, "control.sh"):
                action()
            self.assertEqual(self.snapshot(), interrupted)
        self.child("recover")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(lifecycle.journal_path().exists())
        self.assertFalse(lifecycle.deploy.transaction_path().exists())

    def test_sigkill_during_uninstall_restores_installed_files_and_preferences(self):
        self.child("install")
        before = self.snapshot()
        users = (self.root / "desktop.json").read_bytes()
        for point in ("after-deployment", "after-file", "during-gsettings"):
            with self.subTest(point=point):
                self.child("uninstall", point)
                self.child("recover")
                self.assertEqual(self.snapshot(), before)
                self.assertEqual((self.root / "desktop.json").read_bytes(), users)

    def test_sigkill_after_session_journal_removal_recovers_masks_and_startup(self):
        self.child("install")
        desired = {"autostart/selandia-niri-app.desktop":
                   {"bytes": base64.b64encode(b"managed startup").decode(), "mode": 0o600},
                   "systemd/user/selandia-niri@waybar.service": {"link": "/dev/null"}}
        with lifecycle.session_settings.record_changes(self.config, desired):
            for relative, value in desired.items():
                lifecycle.session_settings.write_value(self.config / relative, value)
        before = self.snapshot()
        self.child("uninstall", "after-session-record")
        self.assertFalse((self.state / lifecycle.session_settings.JOURNAL).exists())
        self.child("recover")
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_preserves_later_startup_symlink_and_its_referent(self):
        self.install()
        relative = "autostart/selandia-niri-app.desktop"
        value = {"bytes": base64.b64encode(b"managed startup").decode(), "mode": 0o600}
        with lifecycle.session_settings.record_changes(self.config, {relative: value}):
            lifecycle.session_settings.write_value(self.config / relative, value)
        personal = self.root / "personal.desktop"
        personal.write_text("user's later startup")
        entry = self.config / relative
        entry.unlink()
        entry.symlink_to(personal)
        lifecycle.run("uninstall", self.desktop)
        self.assertTrue(entry.is_symlink())
        self.assertEqual(personal.read_text(), "user's later startup")
        self.assertEqual((self.config / "niri/original.kdl").read_text(), "original desktop")
        self.assertIn(relative, lifecycle.session_settings.load(self.config)["files"])


if __name__ == "__main__":
    unittest.main()
