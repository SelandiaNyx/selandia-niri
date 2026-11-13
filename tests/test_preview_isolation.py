"""A nested desktop must not regenerate the live desktop's configuration."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("desktop_smoke", ROOT / "tools/smoke.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class PreviewIsolationTests(unittest.TestCase):
    def test_visibility_uses_host_hint_and_targets_only_owned_child_window(self):
        with tempfile.TemporaryDirectory(prefix="selandia-smoke-") as temporary:
            preview = Path(temporary) / "config/niri/preview.kdl"
            child = Mock(pid=4321, args=["niri", "--config", str(preview)])
            child.poll.return_value = None
            env = {"NIRI_SOCKET": "/private/socket", "SELANDIA_PROBE_HOST_SOCKET": "/host/socket"}
            response = subprocess.CompletedProcess([], 0, json.dumps([
                {"id": 99, "pid": 1234}, {"id": 12, "pid": 4321, "is_floating": False}]))
            with patch.object(smoke.subprocess, "run", return_value=response) as run:
                self.assertTrue(smoke.position_preview(child, preview, env, resize=True))
            self.assertEqual(len(run.call_args_list), 5)
            for call in run.call_args_list:
                self.assertEqual(call.kwargs["env"]["NIRI_SOCKET"], "/host/socket")
                if "action" in call.args[0]:
                    self.assertEqual(call.args[0][call.args[0].index("--id") + 1], "12")
            self.assertEqual(env["NIRI_SOCKET"], "/private/socket")

    def test_visibility_never_changes_unrelated_windows_or_exited_compositor(self):
        with tempfile.TemporaryDirectory(prefix="selandia-smoke-") as temporary:
            preview = Path(temporary) / "config/niri/preview.kdl"
            child = Mock(pid=4321, args=["niri", "--config", str(preview)])
            child.poll.return_value = None
            response = subprocess.CompletedProcess([], 0, '[{"id":99,"pid":1234}]')
            with patch.object(smoke.subprocess, "run", return_value=response) as run:
                self.assertFalse(smoke.position_preview(child, preview, {"NIRI_SOCKET": "/host/socket"}))
                self.assertEqual(run.call_count, 1)
                run.reset_mock()
                child.poll.return_value = 0
                self.assertFalse(smoke.position_preview(child, preview, {"NIRI_SOCKET": "/host/socket"}))
                run.assert_not_called()

    def test_visibility_rejects_formal_config_and_changed_child_command(self):
        child = Mock(pid=4321)
        child.poll.return_value = None
        for preview in (ROOT / "niri/config.kdl", Path("/tmp/other/config/niri/preview.kdl")):
            child.args = ["niri", "--config", str(preview)]
            with patch.object(smoke.subprocess, "run") as run:
                self.assertFalse(smoke.position_preview(child, preview, {"NIRI_SOCKET": "/host/socket"}))
                run.assert_not_called()
        with tempfile.TemporaryDirectory(prefix="selandia-smoke-") as temporary:
            preview = Path(temporary) / "config/niri/preview.kdl"
            child.args = ["niri", "--config", str(ROOT / "niri/config.kdl")]
            with patch.object(smoke.subprocess, "run") as run:
                self.assertFalse(smoke.position_preview(child, preview, {"NIRI_SOCKET": "/host/socket"}))
                run.assert_not_called()

    def test_config_source_and_allowed_preferences_are_independent_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            source = project / "niri/theme/waybar.jsonc"
            source.parent.mkdir(parents=True)
            source.write_text('{"modules-right": ["custom/control"]}')
            state = root / "host-state/selandia-niri"
            state.mkdir(parents=True)
            for name in ("appearance.json", "language.json", "application-theme.json", "ai.json"):
                (state / name).write_text(json.dumps({"marker": name}))
            preview = root / "selandia-smoke-test"
            preview.mkdir()
            original = {"XDG_STATE_HOME": str(state.parent), "XDG_CONFIG_HOME": str(root / "host-config"),
                        "WAYLAND_DISPLAY": "wayland-0", "NIRI_SOCKET": "/host/socket"}
            base, env = smoke.prepare_preview(project, preview, original)
            self.assertEqual(base, Path(env["XDG_CONFIG_HOME"]) / "niri")
            self.assertEqual(env["XDG_STATE_HOME"], str(preview))
            self.assertEqual(env["XDG_CACHE_HOME"], str(preview / "cache"))
            self.assertEqual(env["GSETTINGS_BACKEND"], "memory")
            self.assertEqual(env["WAYLAND_DISPLAY"], f"/run/user/{os.getuid()}/wayland-0")
            self.assertEqual(env["XDG_RUNTIME_DIR"], str(preview / "runtime"))
            self.assertEqual((preview / "runtime").stat().st_mode & 0o777, 0o700)
            self.assertEqual(original["XDG_CONFIG_HOME"], str(root / "host-config"))
            seeded = preview / "selandia-niri"
            self.assertEqual({path.name for path in seeded.iterdir()}, {"appearance.json", "language.json"})
            (base / "theme/waybar.jsonc").write_text("preview layout")
            (seeded / "appearance.json").write_text("preview preferences")
            self.assertIn("custom/control", source.read_text())
            self.assertEqual(json.loads((state / "appearance.json").read_text()), {"marker": "appearance.json"})

    def test_runtime_is_private_without_losing_absolute_host_display(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            (parent / "project/niri").mkdir(parents=True)
            (parent / "preview").mkdir()
            original = {"XDG_RUNTIME_DIR": "/host/runtime", "WAYLAND_DISPLAY": "/host/display",
                        "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/host/system-bus"}
            _, env = smoke.prepare_preview(parent / "project", parent / "preview", original)
            self.assertEqual(env["WAYLAND_DISPLAY"], "/host/display")
            self.assertEqual(env["XDG_RUNTIME_DIR"], str(parent / "preview/runtime"))
            self.assertEqual(env["DBUS_SYSTEM_BUS_ADDRESS"],
                             "unix:path=" + str(parent / "preview/runtime/no-system-bus"))
            self.assertEqual(original["DBUS_SYSTEM_BUS_ADDRESS"], "unix:path=/host/system-bus")
            self.assertEqual(original["XDG_RUNTIME_DIR"], "/host/runtime")


if __name__ == "__main__":
    unittest.main()
