import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "niri/shell/bluetooth_policy.py"
spec = importlib.util.spec_from_file_location("bluetooth_policy", MODULE)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class BluetoothPolicyTests(unittest.TestCase):
    def test_default_true_and_explicit_false(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.conf"
            path.write_text("[Policy]\n#AutoEnable=true\n")
            self.assertTrue(backend.read_state(path=path)["auto_enable"])
            path.write_text(backend.render_policy(path.read_text(), False))
            self.assertFalse(backend.read_state(path=path)["auto_enable"])

    def test_preserves_other_sections_and_comments(self):
        source = "[General]\nName=My adapter\n[Policy]\n# Keep pairing\nAutoEnable = true\nReconnectAttempts=7\n[AdvMon]\nRSSI=3\n"
        result = backend.render_policy(source, False)
        self.assertEqual(result, source.replace("AutoEnable = true", "AutoEnable=false"))
        self.assertEqual(backend.render_policy(result, False), result)

    def test_missing_section_and_final_newline(self):
        self.assertEqual(backend.render_policy("[General]\nName=Test", False),
                         "[General]\nName=Test\n\n[Policy]\nAutoEnable=false\n")
        self.assertEqual(backend.render_policy("[Policy]\n#AutoEnable=true", False),
                         "[Policy]\n#AutoEnable=true\nAutoEnable=false\n")

    def test_duplicate_or_invalid_options_rejected(self):
        for source in ("[Policy]\nAutoEnable=true\nAutoEnable=false\n", "[Policy]\n[Policy]\n",
                       "[Policy]\nAutoEnable=maybe\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                backend.render_policy(source, False)
        with self.assertRaises(ValueError):
            backend.render_policy("", "false")

    def test_atomic_write_backup_mode_and_idempotency(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.conf"
            original = "[Policy]\n#AutoEnable=true\n"
            path.write_text(original)
            path.chmod(0o640)
            backup = backend.write_policy(False, path=path)
            self.assertEqual(Path(backup).read_text(), original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            self.assertFalse(backend.read_state(path=path)["auto_enable"])
            self.assertIsNone(backend.write_policy(False, path=path))

    def test_symlink_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.conf"
            target = Path(directory) / "foreign"
            target.write_text("keep")
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                backend.write_policy(False, path=path)
            self.assertEqual(target.read_text(), "keep")

    def test_authentication_cancel_leaves_state_untouched(self):
        with patch.object(backend.subprocess, "run") as run, patch.object(backend, "read_state") as read:
            run.return_value.returncode = 126
            run.return_value.stderr = "Authentication cancelled"
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                backend.apply_auto_enable(False)
            read.assert_not_called()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:3], ["pkexec", "/usr/bin/python3", "-I"])
            self.assertEqual(argv[-2:], ["admin", "off"])
