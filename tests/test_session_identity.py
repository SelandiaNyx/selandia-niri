"""Nested sessions cannot import their sockets into the host user manager."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
import session_identity


class SessionIdentityTests(unittest.TestCase):
    def setUp(self):
        self.env = {"NIRI_SOCKET": "/private/niri.sock", "WAYLAND_DISPLAY": "wayland-test",
                    "XDG_RUNTIME_DIR": "/private"}
        self.run = Mock(return_value=subprocess.CompletedProcess([], 0, "ActiveState=active\nMainPID=4321\n"))
        self.peer = Mock(return_value=(4321, os.getuid(), os.getgid()))

    def owns(self):
        return session_identity.owns_session(environment=self.env, run=self.run, credentials=self.peer)

    def test_both_sockets_must_belong_to_the_active_unit_main_process(self):
        self.assertTrue(self.owns())
        self.assertEqual(self.peer.call_count, 2)
        self.peer.side_effect = [(9876, os.getuid(), os.getgid()), (9876, os.getuid(), os.getgid())]
        self.assertFalse(self.owns())

    def test_host_ipc_with_nested_wayland_or_foreign_uid_is_rejected(self):
        for peers in ([(4321, os.getuid(), 0), (9876, os.getuid(), 0)],
                      [(4321, os.getuid() + 1, 0), (4321, os.getuid() + 1, 0)]):
            with self.subTest(peers=peers):
                self.peer.side_effect = peers
                self.assertFalse(self.owns())

    def test_unavailable_service_missing_sockets_and_invalid_environment_fail_closed(self):
        self.run.return_value.stdout = "ActiveState=inactive\nMainPID=0\n"
        self.assertFalse(self.owns())
        self.run.return_value.stdout = "ActiveState=activating\nMainPID=4321\n"
        self.peer.side_effect = OSError("stale socket")
        self.assertFalse(self.owns())
        self.env.pop("WAYLAND_DISPLAY")
        self.assertFalse(self.owns())

    def test_startup_guard_runs_before_any_environment_import_or_generation(self):
        with tempfile.TemporaryDirectory(prefix="selandia-session-script-") as temporary:
            root = Path(temporary)
            scripts = root / "niri/scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(ROOT / "niri/scripts/start-session", scripts / "start-session")
            fake = root / "bin"
            fake.mkdir()
            calls = root / "calls"
            for name in ("systemctl", "dbus-update-activation-environment", "python3"):
                path = fake / name
                path.write_text("#!" + sys.executable + "\nimport os,sys\n"
                                "with open(os.environ['TEST_CALLS'],'a') as stream: stream.write(' '.join(sys.argv)+'\\n')\n"
                                "if 'session_identity.py' in ' '.join(sys.argv): sys.exit(int(os.environ['TEST_OWNER']))\n")
                path.chmod(0o755)
            for name in ("dirname", "mkdir"):
                (fake / name).symlink_to(shutil.which(name))
            env = dict(os.environ, PATH=str(fake), HOME=str(root / "home"), TEST_CALLS=str(calls), TEST_OWNER="1")
            result = subprocess.run(["/usr/bin/bash", str(scripts / "start-session")], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(len(calls.read_text().splitlines()), 1)
            env["TEST_OWNER"] = "0"
            calls.unlink()
            result = subprocess.run(["/usr/bin/bash", str(scripts / "start-session")], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0)
            output = calls.read_text()
            self.assertIn("import-environment", output)
            self.assertLess(output.index("session_identity.py"), output.index("ui_assets.py"))


if __name__ == "__main__":
    unittest.main()
