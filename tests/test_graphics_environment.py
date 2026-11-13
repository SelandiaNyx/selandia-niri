"""Display-dependent tests must report their prerequisites on a headless host."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class GraphicsEnvironmentTests(unittest.TestCase):
    def test_icon_suite_without_a_display_reports_a_clear_skip(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="selandia-headless-") as temporary:
            env = dict(os.environ, XDG_RUNTIME_DIR=temporary,
                       WAYLAND_DISPLAY="missing-wayland-display", GDK_BACKEND="wayland",
                       GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1")
            for key in ("DISPLAY", "NIRI_SOCKET"):
                env.pop(key, None)
            result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover",
                                     "-s", "tests", "-p", "test_panel_icons.py", "-v"],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GTK display unavailable", result.stderr)
        self.assertIn("skipped=1", result.stderr)
        self.assertNotIn("AttributeError", result.stderr)
