"""The pixel probe may write and start components only inside its private tree."""
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("private_bar_measure", ROOT / "tools/session_probe.py")
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)


class BarMeasureIsolationTests(unittest.TestCase):


    def setUp(self):
        private = tempfile.TemporaryDirectory(prefix="selandia-bar-measure-")
        self.addCleanup(private.cleanup)
        self.root = Path(private.name)
        self.base = self.root / "config/niri"
        shutil.copytree(ROOT / "niri", self.base, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.env = dict(XDG_CONFIG_HOME=str(self.base.parent), XDG_STATE_HOME=str(self.root / "state"),
                        XDG_CACHE_HOME=str(self.root / "cache"), XDG_RUNTIME_DIR=str(self.root / "runtime"),
                        NIRI_SOCKET=str(self.root / "runtime/niri.sock"), WAYLAND_DISPLAY="wayland-private",
                        GSETTINGS_BACKEND="memory")

    def validate(self, **changes):
        return measure.private_base(4321, environment={**self.env, **changes},
                                    credentials=lambda path: (4321, os.getuid(), os.getgid()),
                                    commandline=["niri", "--config", str(self.base / "preview.kdl")])

    def test_private_configuration_and_generators_leave_source_unchanged(self):
        import appearance
        original = (ROOT / "niri/theme/eww.css").read_bytes()
        self.assertEqual(self.validate(), self.base)
        with patch.dict(os.environ, self.env):
            appearance.apply_settings({'font_size':16},base=self.base,state_path=self.root/'state/appearance.json')
        self.assertEqual((ROOT / "niri/theme/eww.css").read_bytes(), original)
        self.assertIn('16px', (self.base / "theme/eww.css").read_text())

    def test_source_symlinks_shared_state_and_wrong_compositor_are_rejected(self):
        for changes in ({"XDG_CONFIG_HOME": str(ROOT)}, {"XDG_STATE_HOME": str(ROOT / "state")},
                        {"GSETTINGS_BACKEND": "dconf"}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.validate(**changes)
        with self.assertRaises(RuntimeError):
            measure.private_base(4321, environment=self.env, credentials=lambda path: (9876, os.getuid(), 0),
                                 commandline=["niri", "--config", str(self.base / "preview.kdl")])
        with self.assertRaises(RuntimeError):
            measure.private_base(4321, environment=self.env, credentials=lambda path: (4321, os.getuid(), 0),
                                 commandline=["niri", "--config", str(ROOT / "niri/config.kdl")])




if __name__ == "__main__":
    unittest.main()
