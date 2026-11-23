"""Regression tests covering performance optimizations and bug fixes."""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
sys.path.insert(0, str(ROOT / "tools"))

import appearance
import component_preferences
import i18n
import language_settings
import lifecycle
import lock_client
import lock_session
import metrics
import notification_history
import wallpaper


class LifecycleThemeListTests(unittest.TestCase):
    def test_themes_match_all_generated_files_plus_swaync_json(self):
        expected = set(appearance.GENERATED_FILES) | {"swaync.json"}
        self.assertEqual(set(lifecycle.THEMES), expected)
        for required in ("eww.css", "anyrun.css", "alacritty.toml", "swaync.json"):
            self.assertIn(required, lifecycle.THEMES)
        for obsolete in ("waybar.css", "kitty.conf"):
            self.assertNotIn(obsolete, lifecycle.THEMES)


class ControlAurStatusTests(unittest.TestCase):
    def test_status_and_dry_run_detect_missing_required_aur_package(self):
        with tempfile.TemporaryDirectory(prefix="selandia-aur-test-") as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            for name in ("control.sh", "check.sh", "install.sh"):
                shutil.copy2(ROOT / name, project / name)
            for directory in ("tools", "niri", "docs", "systemd", "portals"):
                shutil.copytree(ROOT / directory, project / directory,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (project / "packages.txt").write_text(
                "# required aur eww | Rust bar\n"
                "# required aur anyrun | Rust launcher\n"
                "niri\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            for cmd in ("bash", "awk", "sed", "grep", "env", "python3", "tr", "cat", "dirname", "mkdir"):
                resolved = shutil.which(cmd)
                if resolved:
                    (fake_bin / cmd).symlink_to(resolved)
            pacman = fake_bin / "pacman"
            pacman.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == \"-Q\" && \"$2\" == \"eww\" ]]; then exit 1; fi\n"
                "exit 0\n"
            )
            pacman.chmod(0o755)
            for helper in ("paru", "anyrun", "anyrun-provider"):
                stub = fake_bin / helper
                stub.write_text("#!/usr/bin/env bash\nexit 0\n")
                stub.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin), XDG_CONFIG_HOME=str(root / "cfg"),
                       XDG_STATE_HOME=str(root / "state"), XDG_CACHE_HOME=str(root / "cache"))
            status = subprocess.run(["/usr/bin/bash", str(project / "control.sh"), "status"],
                                    cwd=project, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(status.returncode, 1)
            self.assertIn("eww", status.stdout)
            dry = subprocess.run(["/usr/bin/bash", str(project / "control.sh"), "--dry-run", "install"],
                                 cwd=project, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("eww", dry.stdout)


class DesktopScriptFixesTests(unittest.TestCase):
    def test_notifications_mode_and_eww_env_scrubbing(self):
        with tempfile.TemporaryDirectory(prefix="selandia-desktop-fix-") as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / "niri", root / "niri",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            fake_bin = root / "bin"
            fake_bin.mkdir()
            log = root / "calls.jsonl"
            for cmd in ("bash", "dirname", "mkdir"):
                (fake_bin / cmd).symlink_to(shutil.which(cmd))
            py = fake_bin / "python3"
            py.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\n"
                "with open(os.environ['CALL_LOG'], 'a') as f:\n"
                "    f.write(json.dumps({'argv': sys.argv[1:], 'exclusive': os.environ.get('SELANDIA_EWW_EXCLUSIVE_ZONE'), "
                "'input_lib': os.environ.get('SELANDIA_EWW_INPUT_LIB'), 'geom': os.environ.get('SELANDIA_EWW_GEOMETRY')}) + '\\n')\n"
            )
            py.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin), CALL_LOG=str(log),
                       XDG_STATE_HOME=str(root / "state"),
                       SELANDIA_EWW_EXCLUSIVE_ZONE="1",
                       SELANDIA_EWW_INPUT_LIB="/tmp/fake.so",
                       SELANDIA_EWW_GEOMETRY="1600")
            res = subprocess.run(["/usr/bin/bash", str(root / "niri/scripts/desktop"), "notifications"],
                                 env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(res.returncode, 0, res.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0]["argv"][-2].endswith("panel.py"))
            self.assertEqual(calls[0]["argv"][-1], "notifications")
            self.assertIsNone(calls[0]["exclusive"])
            self.assertIsNone(calls[0]["input_lib"])
            self.assertIsNone(calls[0]["geom"])


class StatCacheInvalidationTests(unittest.TestCase):
    def test_language_appearance_and_wallpaper_caches_follow_writes_and_env_changes(self):
        with tempfile.TemporaryDirectory(prefix="selandia-cache-a-") as a, \
                tempfile.TemporaryDirectory(prefix="selandia-cache-b-") as b:
            with patch.dict(os.environ, {"XDG_STATE_HOME": a}):
                self.assertEqual(language_settings.read_preferences()["ui_language"], "system")
                language_settings.save_ui_language("en_US")
                self.assertEqual(language_settings.read_preferences()["ui_language"], "en_US")
                self.assertEqual(i18n.get_language(), "en_US")
                language_settings.save_ui_language("zh_CN")
                self.assertEqual(i18n.get_language(), "zh_CN")

                self.assertEqual(appearance.load_settings()["preset"], appearance.DEFAULTS["preset"])
                app_file = Path(a) / "selandia-niri/appearance.json"
                app_file.parent.mkdir(parents=True, exist_ok=True)
                app_file.write_text(json.dumps({"preset": "violet", "color_mode": "light"}))
                self.assertEqual(appearance.load_settings()["preset"], "violet")

                wp_file = Path(a) / "selandia-niri/wallpaper.json"
                wp_file.write_text(json.dumps({"audio": {"muted": False, "volume": 42}}))
                self.assertEqual(wallpaper.load_settings()["audio"]["volume"], 42)
                wp_file.write_text(json.dumps({"audio": {"muted": True, "volume": 15}}))
                self.assertEqual(wallpaper.load_settings()["audio"]["volume"], 15)

            with patch.dict(os.environ, {"XDG_STATE_HOME": b}):
                self.assertEqual(language_settings.read_preferences()["ui_language"], "system")
                self.assertEqual(appearance.load_settings()["preset"], appearance.DEFAULTS["preset"])
                self.assertEqual(wallpaper.load_settings()["audio"]["volume"], 50)


class LockHardeningTests(unittest.TestCase):
    def test_lock_forwards_explicit_environment_to_display_identity(self):
        with tempfile.TemporaryDirectory(prefix="selandia-lock-env-") as tmp:
            base = Path(tmp)
            (base / "theme").mkdir()
            (base / "theme/swaylock.conf").write_text("color=000000\n")
            custom_env = {"XDG_RUNTIME_DIR": tmp, "WAYLAND_DISPLAY": "explicit-wayland-9"}
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmp, "WAYLAND_DISPLAY": ""}, clear=False), \
                    patch.object(lock_session, "READY_GRACE", 0.05):
                with self.assertRaises(RuntimeError):
                    lock_session.lock(base=base, environment=custom_env,
                                      timeout=0.1, launcher=lambda key, timeout: None)
            req = json.loads(next(base.glob("*.request")).read_text())
            self.assertEqual(req["environment"]["WAYLAND_DISPLAY"], "explicit-wayland-9")
            self.assertIn("explicit-wayland-9", req["display"])

    def test_process_identity_handles_non_utf8_environ(self):
        pid = os.getpid()
        real_read_text = Path.read_text
        real_read_bytes = Path.read_bytes

        def fake_read_text(self, *args, **kwargs):
            if self == Path(f"/proc/{pid}/comm"):
                return "swaylock\n"
            return real_read_text(self, *args, **kwargs)

        def fake_read_bytes(self):
            if self == Path(f"/proc/{pid}/environ"):
                return b"WAYLAND_DISPLAY=wayland-1\x00BAD=\xff\xfe\x00XDG_RUNTIME_DIR=/tmp\x00"
            return real_read_bytes(self)

        with patch.object(Path, "read_text", fake_read_text), \
                patch.object(Path, "read_bytes", fake_read_bytes):
            identity = lock_session.process_identity(pid)
        self.assertIsNotNone(identity)
        self.assertEqual(identity["pid"], pid)
        self.assertEqual(identity["display"], str((Path("/tmp") / "wayland-1").resolve()))

    def test_start_locker_terminates_process_if_confirmation_fails(self):
        with tempfile.TemporaryDirectory(prefix="selandia-lock-reap-") as tmp:
            script = Path(tmp) / "hang.py"
            script.write_text("import os, sys, time\n"
                              "fd = int(sys.argv[sys.argv.index('--ready-fd') + 1])\n"
                              "os.write(fd, b'\\n'); os.close(fd); time.sleep(30)\n")
            cfg = Path(tmp) / "swaylock.conf"
            cfg.write_text("color=000000\n")
            log_path = Path(tmp) / "lock.log"
            request = {
                "version": 1,
                "display": "/run/nonexistent/wayland-0",
                "locker": [sys.executable, str(script)],
                "config": str(cfg),
                "timeout": 2,
                "environment": {"WAYLAND_DISPLAY": "wayland-0"},
            }
            spawned = []
            real_popen = lock_client.subprocess.Popen

            def spy(*args, **kwargs):
                proc = real_popen(*args, **kwargs)
                spawned.append(proc)
                return proc

            with patch.object(lock_client.subprocess, "Popen", side_effect=spy), \
                    patch.object(lock_client, "process_identity", return_value=None):
                with self.assertRaises(RuntimeError):
                    lock_client.start_locker(request, request["display"], log_path)
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].poll())


class NotificationHistoryHardeningTests(unittest.TestCase):
    def test_normalizes_invalid_timestamps_without_mutating_input_and_drops_expired(self):
        entries = [
            {"id": 1, "timestamp": 1000000.0},
            {"id": 2, "timestamp": True},
            {"id": 3, "timestamp": math.nan},
            {"id": 4, "timestamp": "bad"},
            {"id": 5, "timestamp": 100.0},
        ]
        snapshot = [dict(e) for e in entries]
        pruned = notification_history.prune_entries(
            entries, {"limit": 10, "expire_days": 1}, now=1000100.0
        )
        # Input dicts were not mutated in place
        self.assertEqual(entries[0]["timestamp"], snapshot[0]["timestamp"])
        self.assertIs(entries[1]["timestamp"], True)
        self.assertTrue(math.isnan(entries[2]["timestamp"]))
        self.assertEqual(entries[3]["timestamp"], "bad")
        # Expired entry id=5 dropped; invalid timestamps normalized to now
        by_id = {e["id"]: e for e in pruned}
        self.assertNotIn(5, by_id)
        self.assertEqual(by_id[1]["timestamp"], 1000000.0)
        for bad_id in (2, 3, 4):
            self.assertEqual(by_id[bad_id]["timestamp"], 1000100.0)
            self.assertIs(type(by_id[bad_id]["timestamp"]), float)


class ComponentHealthCompactionTests(unittest.TestCase):
    def test_compact_health_bounds_log_and_preserves_stability_sessions(self):
        with tempfile.TemporaryDirectory(prefix="selandia-health-") as tmp:
            with patch.dict(os.environ, {"XDG_STATE_HOME": tmp}):
                log = component_preferences.path().parent / "component-health.jsonl"
                log.parent.mkdir(parents=True, exist_ok=True)
                lines = [json.dumps({"time": "2026-01-01T00:00:00+00:00", "event": "fallback", "deliberate_drill": False})]
                for i in range(12):
                    lines.append(json.dumps({
                        "time": f"2026-01-{i + 2:02d}T00:00:00+00:00",
                        "event": "eww-ready",
                        "session": f"boot:{100 + i}:1",
                        "deliberate_drill": False,
                    }))
                for _ in range(500):
                    lines.append(json.dumps({
                        "time": "2026-02-01T00:00:00+00:00",
                        "event": "eww-ready",
                        "session": "boot:999:1",
                        "deliberate_drill": False,
                    }))
                compacted = component_preferences._compact_health(lines)
                self.assertLessEqual(len(compacted), component_preferences.HEALTH_MAX_RECORDS)
                log.write_text("\n".join(compacted) + "\n")
                report = component_preferences.stability()
                self.assertTrue(report["ready"])
                self.assertEqual(report["successful_logins"], 13)
                self.assertIsNotNone(report["last_failure"])


class MetricsPciStreamingTests(unittest.TestCase):
    def test_pci_name_streams_vendor_and_device_without_loading_full_table(self):
        with tempfile.TemporaryDirectory(prefix="selandia-pci-") as tmp:
            pci = Path(tmp) / "pci.ids"
            pci.write_text(
                "# comment\n"
                "1002  Advanced Micro Devices, Inc. [AMD/ATI]\n"
                "\t744c  Navi 31 [Radeon RX 7900 XT/XTX]\n"
                "\t\t1002 0e3a  Subsystem\n"
                "10de  NVIDIA Corporation\n"
                "\t2684  AD102 [GeForce RTX 4090]\n"
                "8086  Intel Corporation\n"
                "\t56a0  DG2 [Arc A770]\n"
            )
            sampler = metrics.MetricsSampler(pci_ids=pci)
            self.assertEqual(sampler._pci_name("0x1002", "0x744c"), "Navi 31 [Radeon RX 7900 XT/XTX]")
            self.assertEqual(sampler._pci_name("0x10de", "0x2684"), "AD102 [GeForce RTX 4090]")
            self.assertIsNone(sampler._pci_name("0xdead", "0xbeef"))
            # Only queried pairs are cached, never the untouched Intel entry.
            self.assertEqual(len(sampler.pci_names), 3)
            self.assertNotIn(("8086", "56a0"), sampler.pci_names)


if __name__ == "__main__":
    unittest.main()
