"""Local fixtures only: never restart the user's wallpaper or touch Steam data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
import appearance
import wallpaper


class WallpaperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wallpaper user's ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        child_cleanup = patch.object(wallpaper.os, "killpg")
        child_cleanup.start()
        self.addCleanup(child_cleanup.stop)
        audio_probe = patch.object(wallpaper.wallpaper_audio, "available", return_value=False)
        audio_probe.start()
        self.addCleanup(audio_probe.stop)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root / "state"), XDG_CACHE_HOME=str(self.root / "cache"),
                         XDG_RUNTIME_DIR=str(self.root))
        env.start()
        self.addCleanup(env.stop)
        self.picture = self.root / "蓝色 test.svg"
        self.picture.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#2070d0"/></svg>')

    def project(self, kind="video", **metadata):
        folder = self.root / "library/431960/1234"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "preview.svg").write_bytes(self.picture.read_bytes())
        (folder / "movie.mp4").touch()
        (folder / "project.json").write_text(json.dumps({"type": kind, "title": "Test 项目", "preview": "preview.svg", "file": "movie.mp4", **metadata}))
        return folder

    def test_steam_discovers_unicode_space_and_unmounted_libraries(self):
        steam = self.root / ".local/share/Steam/steamapps"
        steam.mkdir(parents=True)
        path = self.root / "游戏 disk/SteamLibrary"
        (steam / "libraryfolders.vdf").write_text(f'"libraryfolders" {{ "1" {{ "path" "{path}" }} }}')
        self.assertIn(path, wallpaper.steam_libraries(self.root))
        result = wallpaper.discover({"roots": [], "assets": ""}, libraries=[path])
        self.assertEqual(result["missing"], [str(path)])
        self.assertEqual(result["items"], [])

    def test_project_library_deduplicates_and_does_not_list_project_assets(self):
        project = self.project()
        settings = {"roots": [str(project.parent), str(project)], "assets": ""}
        items = wallpaper.discover(settings, libraries=[])["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Test 项目")
        self.assertEqual(items[0]["type"], "video")

    def test_project_cannot_escape_folder_by_relative_absolute_or_symlink_paths(self):
        project = self.project()
        (project / "escape.svg").symlink_to(self.picture)
        for path in (str(self.picture), "../../../" + self.picture.name, "escape.svg"):
            with self.subTest(path=path):
                self.assertIsNone(wallpaper.project_file(project, path))

    def test_application_and_unknown_projects_cannot_launch(self):
        for kind in ("application", "unknown"):
            item = wallpaper.describe(self.project(kind))
            with self.assertRaises(ValueError):
                wallpaper.playback_command(item, "live")
            self.assertEqual(wallpaper.playback_command(item, "preview")[0], "swaybg")

    def test_web_requires_a_local_html_entry_and_uses_the_experimental_engine(self):
        project = self.project("web", file="index.html")
        (project / "index.html").write_text("<!doctype html><body>Wallpaper fixture</body>")
        item = wallpaper.describe(project)
        self.assertEqual(item["type"], "web")
        with patch.object(wallpaper.shutil, "which", return_value="/test/bin/linux-wallpaperengine"):
            command = wallpaper.playback_command(item, "live", assets=str(self.root), outputs=["DP-1"])
        self.assertEqual(command[0], "linux-wallpaperengine")
        self.assertEqual(command[command.index("--bg") + 1], str(project))
        self.assertIn("--silent", command)
        self.assertEqual(wallpaper.playback_command(item, "preview")[0], "swaybg")
        (project / "index.html").unlink()
        self.assertEqual(wallpaper.describe(project)["type"], "unsupported")

    def test_missing_web_backend_has_the_same_exact_aur_installation_hint(self):
        item = dict(wallpaper.describe(self.project()), type="web")
        with patch.object(wallpaper.shutil, "which", return_value=None):
            with self.assertRaises(ValueError) as error:
                wallpaper.playback_command(item, "live", assets=str(self.root), outputs=["DP-1"])
        self.assertIn("paru -S --needed linux-wallpaperengine-git", str(error.exception))

    def test_web_renderer_uses_wayland_and_isolates_cef_preload_from_parent(self):
        library = self.root / "libcef.so"
        library.write_text("fixture")
        item = dict(wallpaper.describe(self.project()), type="web")
        with patch.object(wallpaper, "CEF_LIBRARY", library), \
                patch.dict(os.environ, LD_PRELOAD="/existing.so:other.so"), \
                patch.object(wallpaper.shutil, "which", return_value="/test/bin/linux-wallpaperengine"):
            command = wallpaper.playback_command(item, "live", assets=str(self.root), outputs=["DP-1"])
            environment = wallpaper.renderer_environment(item)
            self.assertEqual(environment["LD_PRELOAD"], str(library) + " /existing.so:other.so")
            self.assertEqual(os.environ["LD_PRELOAD"], "/existing.so:other.so")
            self.assertEqual(wallpaper.renderer_environment(dict(item, type="scene"))["LD_PRELOAD"], "/existing.so:other.so")
            self.assertIn("--ozone-platform=wayland", command)
            self.assertIn("--noautomute", command)
        library.unlink()
        with patch.object(wallpaper, "CEF_LIBRARY", library):
            expected = wallpaper.engine_compatibility.environment(wallpaper.wallpaper_audio.environment())
            self.assertEqual(wallpaper.renderer_environment(item), dict(expected, SDL_AUDIODRIVER="pulseaudio"))

    def test_web_runtime_passes_compatibility_environment_only_to_engine(self):
        project = self.project("web", file="index.html")
        (project / "index.html").write_text("<!doctype html><body>fixture</body>")
        calls = []
        settings = wallpaper.normalize_settings({"assets": str(self.root), "selection": {
            "path": str(project), "mode": "live", "fallback": str(self.picture)}})
        def launch(command, **kwargs):
            calls.append((command, kwargs))
            return MagicMock(pid=123, returncode=None, poll=lambda: None)
        supervisor = wallpaper.PlaylistRenderer()
        ticks = iter(x / 10 for x in range(1000))
        with patch.object(wallpaper.shutil, "which", return_value="/test/bin"), \
             patch.object(wallpaper.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"DP-1":{"current_mode":0}}')), \
             patch.object(wallpaper.subprocess, "Popen", side_effect=launch), \
             patch.object(wallpaper.wallpaper_audio, "process_identity", return_value={"pid":123}), \
             patch.object(wallpaper.time, "monotonic", side_effect=lambda: next(ticks)), \
             patch.object(wallpaper.time, "sleep"), patch.object(supervisor, "stop"), \
             patch.object(wallpaper, "renderer_environment", return_value={"CEF_FIXTURE":"child-only"}) as environment:
            supervisor.replace(settings)
            self.assertEqual(calls[-1][1]["env"], {"CEF_FIXTURE":"child-only"})
            self.assertEqual(calls[-1][0][0], "linux-wallpaperengine")
            environment.assert_called_once()
            calls.clear()
            settings["selection"]["mode"] = "preview"
            supervisor.replace(settings)
            environment.assert_called_once()
            self.assertEqual(calls[-1][0][0], "swaybg")
            supervisor.close()

    def test_missing_video_backend_rejects_before_persist_or_restart(self):
        with patch.object(wallpaper.shutil, "which", return_value=None), patch.object(wallpaper.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                wallpaper.activate(self.project())
        run.assert_not_called()
        self.assertFalse((wallpaper.state_dir() / "wallpaper.json").exists())

    def test_optional_packages_are_declared_without_entering_required_pacman_list(self):
        lines = (ROOT / "packages.txt").read_text().splitlines()
        required = {line.split("#", 1)[0].strip() for line in lines if line.split("#", 1)[0].strip()}
        for command, (source, package) in wallpaper.BACKEND_PACKAGES.items():
            declarations = [line for line in lines if line.startswith("# optional") and
                            line.split("|", 1)[0].split()[-2:] == [source, package]]
            self.assertEqual(len(declarations), 1, command)
            self.assertNotIn(package, required)
        self.assertIn("# optional-experimental aur linux-wallpaperengine-git", "\n".join(lines))
        self.assertNotIn("nvidia-utils", required)

    def test_missing_backend_error_includes_real_aur_package_and_password_guidance(self):
        for kind, command, package in (("video", "mpvpaper", "mpvpaper"),
                                        ("scene", "linux-wallpaperengine", "linux-wallpaperengine-git")):
            item = wallpaper.describe(self.project(kind))
            with patch.object(wallpaper.shutil, "which", return_value=None):
                with self.assertRaises(ValueError) as error:
                    wallpaper.playback_command(item, "live", assets=str(self.root), outputs=["DP-1"])
            for instruction in (f"paru -S --needed {package}", f"yay -S --needed {package}", "sudo"):
                self.assertIn(instruction, str(error.exception))

    def test_video_thumbnail_hint_is_distinct_from_unavailable_scene_preview(self):
        item = dict(wallpaper.describe(self.project()), preview="")
        with patch.object(wallpaper.shutil, "which", return_value=None):
            with self.assertRaises(ValueError) as error:
                wallpaper.preview_image(item)
        self.assertIn("sudo pacman -S --needed ffmpeg", str(error.exception))
        with self.assertRaises(ValueError) as error:
            wallpaper.preview_image(dict(item, type="scene"))
        self.assertNotIn("pacman", str(error.exception))

    def test_dependency_report_is_read_only_and_does_not_suggest_nvidia(self):
        with patch.object(wallpaper.shutil, "which", return_value=None), patch.object(wallpaper.subprocess, "run") as run:
            report = wallpaper.dependency_report()
        self.assertIn("paru -S --needed mpvpaper", report)
        self.assertIn("paru -S --needed linux-wallpaperengine-git", report)
        self.assertNotIn("nvidia", report)
        run.assert_not_called()
        self.assertFalse(wallpaper.state_dir().exists())

    def test_renderer_commands_keep_paths_as_single_arguments_and_mute_audio(self):
        item = wallpaper.describe(self.project())
        with patch.object(wallpaper.shutil, "which", return_value="/test/bin"):
            command = wallpaper.playback_command(item, "live")
            self.assertEqual(command[-1], item["file"])
            self.assertIn("no-audio", command[2])
            self.assertIn("no-config", command[2])
            item["type"] = "scene"
            command = wallpaper.playback_command(item, "live", assets=str(self.root), outputs=["DP-1", "HDMI-A-1"])
            self.assertEqual(command.count("--bg"), 2)
            self.assertIn("--silent", command)
            self.assertEqual(command[command.index("--assets-dir") + 1], str(self.root))

    def test_image_activate_caches_fallback_and_preserves_manual_theme(self):
        with patch.object(wallpaper.subprocess, "run") as run, patch.object(appearance, "apply_settings") as theme:
            result = wallpaper.activate(self.picture)
        self.assertFalse(result["warnings"])
        theme.assert_not_called()
        self.assertEqual(run.call_count, 3)
        saved = wallpaper.load_settings()
        self.assertEqual(saved["selection"]["path"], str(self.picture))
        self.picture.unlink()
        self.assertTrue(wallpaper.current_image().is_file())
        self.assertEqual((wallpaper.state_dir() / "wallpaper.json").stat().st_mode & 0o777, 0o600)

    def test_wallpaper_selection_rolls_back_when_service_restart_fails(self):
        wallpaper.add_root(self.root)
        before = wallpaper.load_settings()
        with patch.object(wallpaper.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["systemctl"])):
            with self.assertRaisesRegex(RuntimeError, "recovery failed|恢复失败"):
                wallpaper.activate(self.picture)
        self.assertEqual(wallpaper.load_settings(), before)

    def test_failed_new_renderer_restores_old_selection_and_running_service(self):
        previous = dict(wallpaper.load_settings(), selection=None)
        wallpaper.save_settings(previous)
        restarts = []
        active = False
        def command(argv, **kwargs):
            nonlocal active
            if argv[2] == "restart":
                restarts.append(wallpaper.load_settings())
                if len(restarts) == 1:
                    active = False
                    raise subprocess.CalledProcessError(1, argv)
                active = True
            elif argv[2] == "is-active" and not active:
                raise subprocess.CalledProcessError(3, argv)
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(wallpaper.subprocess, "run", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "renderer restored|确认原壁纸"):
                wallpaper.activate(self.picture)
        self.assertTrue(active)
        self.assertEqual(restarts[1], previous)
        self.assertEqual(wallpaper.load_settings(), previous)

    def test_successful_restart_with_inactive_renderer_also_recovers_old_service(self):
        calls = []
        def command(argv, **kwargs):
            calls.append(argv[2])
            if argv[2] == "is-active" and calls.count("is-active") == 1:
                raise subprocess.CalledProcessError(3, argv)
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(wallpaper.subprocess, "run", side_effect=command):
            with self.assertRaisesRegex(RuntimeError, "restored|已恢复"):
                wallpaper.activate(self.picture)
        self.assertEqual(calls, ["reset-failed", "restart", "is-active"] * 2)

    def test_explicit_switches_reset_only_wallpaper_instance_start_limit(self):
        with patch.object(wallpaper.subprocess, "run") as run:
            for _ in range(5):
                wallpaper.activate(self.picture)
        self.assertEqual(run.call_count, 15)
        for offset in range(0, 15, 3):
            self.assertEqual(run.call_args_list[offset].args[0],
                             ["systemctl", "--user", "reset-failed", "selandia-niri@wallpaper.service"])

    def test_follow_colors_only_updates_saved_theme_when_enabled(self):
        values = dict(appearance.DEFAULTS, wallpaper_colors=True, font_size=16)
        with patch.object(wallpaper.subprocess, "run"), patch.object(appearance, "load_settings", return_value=values), \
                patch.object(appearance, "apply_settings") as apply:
            wallpaper.activate(self.picture)
        self.assertEqual(apply.call_args.args[0]["wallpaper_seed"], wallpaper.extract_seed(self.picture))
        self.assertEqual(apply.call_args.args[0]["font_size"], 16)

    def test_dominant_seed_extracts_blue_and_handles_transparency(self):
        seed = wallpaper.extract_seed(self.picture)
        self.assertGreater(int(seed[5:7], 16), int(seed[1:3], 16))
        self.picture.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
        self.assertEqual(wallpaper.extract_seed(self.picture), "#808080")

    def test_malformed_metadata_and_roots_are_reported_without_breaking_scan(self):
        project = self.project()
        (project / "project.json").write_text("[]")
        result = wallpaper.discover({"roots": [str(project)], "assets": ""}, libraries=[])
        self.assertEqual(result["items"], [])
        self.assertEqual(len(result["errors"]), 1)
        wallpaper.save_settings({"roots": [None]})
        self.assertEqual(wallpaper.load_settings()["roots"], [])

    def test_malformed_selection_keeps_library_roots_and_uses_bundled_fallback(self):
        wallpaper.save_settings({"roots": [str(self.root)], "selection": {
            "path": str(self.picture), "mode": "live", "fallback": {"invalid": True}}})
        settings = wallpaper.load_settings()
        self.assertEqual(settings["roots"], [str(self.root)])
        self.assertIsNone(settings["selection"])
        self.assertEqual(wallpaper.current_image(), wallpaper.BASE / "assets/selandia-glass.svg")

    @unittest.skipUnless(wallpaper.shutil.which("ffmpeg"), "Optional ffmpeg not installed")
    def test_local_video_without_preview_generates_a_real_thumbnail(self):
        video = self.root / "green clip.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=green:s=64x48:d=0.1", "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
        image = wallpaper.preview_image(wallpaper.describe(video))
        self.assertTrue(image.is_relative_to(wallpaper.cache_dir()))
        self.assertTrue(image.read_bytes().startswith(b"\x89PNG"))
        seed = wallpaper.extract_seed(image)
        self.assertGreater(int(seed[3:5], 16), int(seed[1:3], 16))

    def test_failed_renderer_switches_to_static_fallback(self):
        project = self.project()
        wallpaper.save_settings({"roots": [], "selection": {"path": str(project), "mode": "live", "fallback": str(self.picture)}})
        supervisor = MagicMock()
        supervisor.replace.side_effect = [RuntimeError("fixture failed"), None]
        supervisor.finished.return_value = False
        server = MagicMock()
        server.poll.side_effect = SystemExit(0)
        with patch.object(wallpaper, "PlaylistRenderer", return_value=supervisor), \
             patch.object(wallpaper.wallpaper_remote, "Server", return_value=server), \
             patch.object(wallpaper, "log_rotation") as log_rot:
            with self.assertRaises(SystemExit): wallpaper.run()
        log_rot.assert_called_once_with("startup-fallback", error="fixture failed")
        self.assertIsNone(supervisor.replace.call_args.args[0]["selection"])
        self.assertEqual(supervisor.replace.call_args.args[0]["display"]["mode"], "fill")
        supervisor.close.assert_called_once(); server.close.assert_called_once()
