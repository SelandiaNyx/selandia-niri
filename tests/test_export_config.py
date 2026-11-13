"""The shared archive must be standalone and must not mutate the live checkout."""
import hashlib
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import export_config


class PortableExportTests(unittest.TestCase):
    def test_archive_install_first_display_apply_confirm_revert_and_timeout(self):
        with tempfile.TemporaryDirectory(prefix="selandia-portable-integration-") as temporary:
            private = Path(temporary)
            archive = private / "shared.tar.gz"
            export_config.export(archive)
            with tarfile.open(archive) as package:
                package.extractall(private / "unpacked", filter="data")
            checkout = private / "unpacked/selandia-niri"
            fake_bin = private / "bin"
            fake_bin.mkdir()
            raw = {"DP-1": {"name": "DP-1", "make": "Synthetic", "model": "Test display",
                            "modes": [{"width": 1920, "height": 1080, "refresh_rate": 60000, "is_preferred": True}],
                            "current_mode": 0, "logical": {"x": 0, "y": 0, "scale": 1.0, "transform": "Normal"},
                            "vrr_supported": False, "vrr_enabled": False}}
            import json
            niri = shutil.which("niri")
            shim = fake_bin / "niri"
            shim.write_text("#!" + sys.executable + "\nimport json,os,sys\n"
                            "if sys.argv[1:2] == ['validate']: os.execv(" + repr(niri) + ", [" + repr(niri) + ", *sys.argv[1:]])\n"
                            "if 'outputs' in sys.argv: print(" + repr(json.dumps(raw)) + ")\n")
            shim.chmod(0o755)
            for name in ("systemctl", "gdbus", "dbus-update-activation-environment"):
                path = fake_bin / name
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            shim = fake_bin / "gsettings"
            shim.write_text("#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\n"
                            "path=Path(os.environ['PORTABLE_GSETTINGS'])\n"
                            "values=json.loads(path.read_text()) if path.exists() else {}\n"
                            "action,key=sys.argv[1],sys.argv[3]\n"
                            "if action=='get': print(values.get(key, \"'original'\"))\n"
                            "elif action=='set': values[key]=sys.argv[4]; path.write_text(json.dumps(values))\n"
                            "elif action=='reset': values.pop(key,None); path.write_text(json.dumps(values))\n")
            shim.chmod(0o755)
            runtime = private / "runtime"
            runtime.mkdir(mode=0o700)
            environment = dict(os.environ, PATH=str(fake_bin) + ":" + os.environ["PATH"],
                               XDG_CONFIG_HOME=str(private / "config"), XDG_STATE_HOME=str(private / "state"),
                               XDG_CACHE_HOME=str(private / "cache"), XDG_RUNTIME_DIR=str(runtime),
                               DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(private / "no-bus"),
                               NIRI_SOCKET=str(private / "synthetic.sock"), GSETTINGS_BACKEND="memory",
                               PORTABLE_GSETTINGS=str(private / "desktop.json"), LC_ALL="C.UTF-8")
            result = subprocess.run([str(checkout / "control.sh"), "install", "--no-packages"],
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((private / "config/niri").resolve(), checkout / "niri")
            driver = '''import json,time
from pathlib import Path
import display_backend as display
target=display.BASE / display.GENERATED
empty=display.render_settings({})
assert target.read_text()==empty
values={"mode":"1920x1080@60","scale":1.25,"max_bpc":None,"transform":"normal","x":0,"y":0,"vrr":False}
token=display.begin_apply("DP-1", values)
assert display.revert(token) and target.read_text()==empty
assert not (display._state_dir()/"settings.json").exists()
token=display.begin_apply("DP-1", values)
assert display.confirm(token)
confirmed=target.read_text()
assert json.loads((display._state_dir()/"settings.json").read_text())["outputs"]["DP-1"]["scale"]==1.25
token=display.begin_apply("DP-1", {**values,"scale":1.5})
assert display.revert(token) and target.read_text()==confirmed
display.CONFIRM_SECONDS=.25
display.begin_apply("DP-1", {**values,"scale":1.75})
deadline=time.monotonic()+4
while (display._state_dir()/"pending.json").exists() and time.monotonic()<deadline: time.sleep(.05)
assert not (display._state_dir()/"pending.json").exists()
assert target.read_text()==confirmed
manual=confirmed+"// user's manual change\\n"
target.write_text(manual)
try: display.begin_apply("DP-1", values)
except RuntimeError: pass
else: raise AssertionError("manual edit protection was bypassed")
assert target.read_text()==manual
'''
            result = subprocess.run([sys.executable, "-B", "-c", driver], cwd=private / "config/niri/shell",
                                    env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_staging_neutralizes_hardware_and_theme_without_copying_personal_artifacts(self):
        before = {name: (ROOT / "niri" / name).read_bytes() for name in
                  ("conf/display-settings.kdl", "conf/outputs.kdl", "monitor.kdl", "theme/panel.css")}
        with tempfile.TemporaryDirectory(prefix="niri export user's ") as temporary:
            target = Path(temporary) / "package"
            export_config.stage(target)
            for name in ("conf/display-settings.kdl", "conf/outputs.kdl", "monitor.kdl"):
                self.assertNotIn("output ", (target / "niri" / name).read_text())
            self.assertNotIn("timeout ", (target / "niri/swayidle/config").read_text())
            for relative in (".git", ".validation", ".codex", ".local/wallpaper-engine", "ai-workspace.json",
                             "niri/monitor.kdl.bak", "niri/swayidle/managed.conf"):
                self.assertFalse((target / relative).exists(), relative)
            self.assertTrue((target / "niri/shell/wallpaper.py").is_file())
            self.assertTrue((target / "niri/shell/wallpaper_playlist.py").is_file())
            self.assertTrue((target / "niri/shell/system_info.py").is_file())
            self.assertIn("20–100%", (target / "VALIDATION.md").read_text())
            self.assertIn("播放集", (target / "README.md").read_text())
            self.assertTrue((target / "tools/export_config.py").is_file())
            self.assertTrue((target / "tools/visual_defects_probe.py").is_file())
            self.assertTrue((target / "docs/CONTROL_CENTER.md").is_file())
            for relative in ("niri/shell/background_tasks.py", "niri/shell/gpu_metrics.py",
                             "docs/DAILY_USE.md", "docs/GPU_MONITORING.md"):
                self.assertTrue((target / relative).is_file(), relative)
            self.assertTrue((target / "PORTABLE").is_file())
            self.assertIn("无显示服务器时 GTK 图标渲染测试会明确跳过", (target / "VALIDATION.md").read_text())
            self.assertIn("LidSwitchIgnoreInhibited=yes", (target / "README.md").read_text())
            from test_documentation import relative_links
            for document in (target / "README.md", target / "docs/INSTALL.md", target / "VALIDATION.md"):
                for link in relative_links(document):
                    self.assertTrue((document.parent / link).is_file(), f"{document.name}: {link}")
            self.assertEqual((target / "tools/wallpaper_engine_compat.py").read_bytes(),
                             (ROOT / "tools/wallpaper_engine_compat.py").read_bytes())
            self.assertIn("font-size: 12px", (target / "niri/theme/panel.css").read_text())
            for line in (target / "SHA256SUMS").read_text().splitlines():
                expected, relative = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((target / relative).read_bytes()).hexdigest(), expected)
            env = dict(os.environ, XDG_CONFIG_HOME=str(Path(temporary) / "config"),
                       XDG_STATE_HOME=str(Path(temporary) / "state"))
            subprocess.run([sys.executable, "-B", str(target / "tools/deploy.py"), "dry-run"],
                           env=env, check=True, capture_output=True)
        self.assertEqual(before, {name: (ROOT / "niri" / name).read_bytes() for name in before})

    def test_export_does_not_overwrite_existing_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "shared.tar.gz"
            target.write_bytes(b"keep")
            with patch.object(export_config, "stage"), patch.object(export_config.shutil, "which", return_value=None):
                with self.assertRaises(FileExistsError):
                    export_config.export(target)
            self.assertEqual(target.read_bytes(), b"keep")

    @staticmethod
    def minimal_stage(target):
        target.mkdir()
        (target / "README.md").write_text("Portable fixture\n")

    def test_equal_exports_are_byte_identical_despite_name_and_source_mtime(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(export_config, "stage", side_effect=self.minimal_stage), \
                patch.object(export_config.shutil, "which", return_value=None):
            first = export_config.export(Path(temporary) / "first.tar.gz")
            second = export_config.export(Path(temporary) / "other-name.tar.gz")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_archive_write_failure_never_exposes_a_partial_final_archive(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(export_config, "stage", side_effect=self.minimal_stage), \
                patch.object(export_config.shutil, "which", return_value=None), \
                patch.object(export_config.tarfile.TarFile, "add", side_effect=OSError("disk full")):
            target = Path(temporary) / "shared.tar.gz"
            with self.assertRaisesRegex(OSError, "disk full"):
                export_config.export(target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_racing_export_never_overwrites_another_completed_archive(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(export_config, "stage", side_effect=self.minimal_stage), \
                patch.object(export_config.shutil, "which", return_value=None):
            target = Path(temporary) / "shared.tar.gz"
            link = export_config.os.link
            def race(source, destination):
                target.write_bytes(b"other completed export")
                return link(source, destination)
            with patch.object(export_config.os, "link", side_effect=race), self.assertRaises(FileExistsError):
                export_config.export(target)
            self.assertEqual(target.read_bytes(), b"other completed export")
            self.assertEqual(list(Path(temporary).iterdir()), [target])

    def test_sigkill_during_archive_write_leaves_no_published_archive(self):
        with tempfile.TemporaryDirectory(prefix="selandia-export-kill-") as temporary:
            target = Path(temporary) / "shared.tar.gz"
            marker = Path(temporary) / "writing"
            program = '''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1]); import export_config
def stage(path):
 path.mkdir(); (path/'README.md').write_text('Fixture')
export_config.stage=stage
export_config.shutil.which=lambda name: None
original=export_config.tarfile.TarFile.add
def blocked(*args,**kwargs):
 original(*args,**kwargs)
 Path(sys.argv[3]).write_text('writing')
 while True: time.sleep(.1)
export_config.tarfile.TarFile.add=blocked
export_config.export(sys.argv[2])
'''
            child = subprocess.Popen([sys.executable, "-B", "-c", program, str(ROOT / "tools"), str(target), str(marker)])
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                child.kill()
                child.wait(timeout=3)
                self.assertFalse(target.exists())
                with patch.object(export_config, "stage", side_effect=self.minimal_stage), \
                        patch.object(export_config.shutil, "which", return_value=None):
                    export_config.export(target)
                with tarfile.open(target) as archive:
                    self.assertIn("selandia-niri/README.md", archive.getnames())
            finally:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
