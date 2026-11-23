"""Direct unit tests for shell UI/control modules and script/Rust hardening (M4, A3, A4, A6.2)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

import application_audio
import bluetooth_controls
import drawers
import i18n
import language_controls
import quick_controls
import scroll_guard
import surface_registry
import wallpaper_controls
import wallpaper_preferences


class SurfaceRegistryAndDrawerTests(unittest.TestCase):
    def test_surface_registry_keys_and_drawer_sides(self):
        self.assertIn("control", surface_registry.CONTROL_MODES)
        self.assertIn("quick", surface_registry.CONTROL_MODES)
        self.assertEqual(surface_registry.DRAWER_SIDES, {"ai": "left", "calendar": "right"})
        for mode in surface_registry.AUXILIARY_MODES:
            self.assertIn(mode, surface_registry.SURFACE_KEYS)
            self.assertEqual(len(surface_registry.SURFACE_COPY[mode]), 4)

    def test_bounded_canvas_clamps_dimensions_and_keeps_fixed_requisition(self):
        canvas = drawers.BoundedCanvas(0, -10)
        self.assertEqual((canvas.bounded_width, canvas.bounded_height), (1, 1))
        canvas = drawers.BoundedCanvas(440, 720)
        child = Gtk.Label(label="drawer")
        canvas.set_child(child)
        canvas.move_child(180.6)
        self.assertEqual(canvas.do_get_preferred_width(), (440, 440))
        self.assertEqual(canvas.do_get_preferred_height(), (720, 720))
        self.assertEqual(canvas.do_get_preferred_width_for_height(500), (440, 440))
        self.assertEqual(canvas.do_get_preferred_height_for_width(300), (720, 720))


class ScrollGuardTests(unittest.TestCase):
    def test_protect_attaches_once_and_redirects_closed_selector_scroll(self):
        scroller = Gtk.ScrolledWindow()
        box = Gtk.Box()
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        combo = Gtk.ComboBoxText()
        box.pack_start(scale, False, False, 0)
        box.pack_start(combo, False, False, 0)
        scroller.add(box)
        adjustment = scroller.get_vadjustment()
        adjustment.configure(100, 0, 500, 10, 100, 100)
        scroll_guard.protect(scroller)
        self.assertTrue(getattr(scroller, "_selandia_scroll_guard", False))
        self.assertTrue(getattr(scale, "_selandia_scroll_guard", False))
        self.assertTrue(getattr(combo, "_selandia_scroll_guard", False))

        event = MagicMock()
        event.type = Gdk.EventType.SCROLL
        event.direction = Gdk.ScrollDirection.DOWN
        self.assertTrue(scroll_guard.handle(scale, event))
        self.assertEqual(adjustment.get_value(), 140)

        non_scroll = MagicMock()
        non_scroll.type = Gdk.EventType.NOTHING
        self.assertFalse(scroll_guard.handle(scale, non_scroll))
        self.assertFalse(scroll_guard.handle(Gtk.Label(), event))


class FakePanel:
    def __init__(self, width=1280):
        self.panel_width = width
        self.pending = set()
        self.tasks = []
        self.feedbacks = []
        self.refreshed_audio = 0

    def protect_scroll_controls(self, widget):
        scroll_guard.protect(widget)

    def work(self, task, done=None, failed=None, commit=False):
        self.tasks.append((task, done, failed, commit))

    def feedback(self, message, error=False):
        self.feedbacks.append((str(message), error))

    def refresh_audio(self):
        self.refreshed_audio += 1

    def compact_label(self, text=""):
        return Gtk.Label(label=text, xalign=0)

    def card(self, parent, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.pack_start(Gtk.Label(label=title, xalign=0), False, False, 0)
        parent.pack_start(box, False, False, 0)
        return box

    def connect(self, *_args):
        return 1

    def audio_combo(self):
        return Gtk.ComboBoxText()

    def toggle_wifi(self):
        pass

    def toggle_bluetooth(self):
        pass

    def toggle_dnd(self):
        pass

    def toggle_idle(self):
        pass

    def desktop(self, *_args):
        pass

    def launch(self, *_args):
        pass

    def action(self, *_args):
        pass

    def scale_changed(self, *_args):
        pass

    def scale_drag_start(self, *_args):
        return False

    def scale_drag_end(self, *_args):
        return False

    def select_control_tab(self, *_args):
        pass

    def brightness_selected(self, *_args):
        pass

    def profile_changed(self, *_args):
        pass

    def manual_refresh_control(self, *_args):
        pass


class ControlsModulesTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)

    def test_application_audio_controls_lifecycle_and_flush(self):
        panel = FakePanel()
        controls = application_audio.ApplicationAudioControls(panel)
        stream = {
            "kind": "sink-input",
            "index": 7,
            "identity": [1, "7", "100", "org.test", "Player", "player"],
            "name": "Player",
            "media": "Song",
            "volume": 65.0,
            "mute": False,
            "volume_writable": True,
        }
        controls.update([stream])
        self.assertEqual(len(controls.entries), 1)
        key = next(iter(controls.entries))
        controls.change(key, muted=True)
        controls.cancel_timer(controls.entries[key])
        controls.flush(key)
        self.assertEqual(len(panel.tasks), 1)
        task, done, _failed, commit = panel.tasks.pop()
        self.assertTrue(commit)
        with patch.object(application_audio.audio_backend, "set_stream_audio") as set_audio:
            task()
            set_audio.assert_called_once_with(stream, muted=True)
        done(None)
        self.assertEqual(panel.refreshed_audio, 1)
        controls.update([])
        self.assertEqual(len(controls.entries), 0)
        controls.cleanup()

    def test_bluetooth_policy_controls_state_and_save(self):
        panel = FakePanel()
        widget = bluetooth_controls.BluetoothPolicyControls(panel)
        widget.mapped()
        self.assertEqual(len(panel.tasks), 1)
        _task, done, _failed, _commit = panel.tasks.pop()
        done({"auto_enable": False})
        self.assertTrue(widget.loaded)
        self.assertFalse(widget.apply.get_sensitive())
        widget.enabled.set_active(True)
        self.assertTrue(widget.apply.get_sensitive())
        widget.save()
        self.assertEqual(len(panel.tasks), 1)
        task, done, failed, commit = panel.tasks.pop()
        self.assertTrue(commit)
        with patch.object(bluetooth_controls.backend, "apply_auto_enable", return_value={"auto_enable": True}) as apply_fn:
            res = task()
            apply_fn.assert_called_once_with(True)
            done(res)
        self.assertTrue(widget.saved)
        failed(RuntimeError("polkit cancelled"))
        self.assertIn("polkit cancelled", widget.notice.get_text())

    def test_language_controls_refresh_and_apply_ui(self):
        panel = FakePanel()
        widget = language_controls.LanguageSettings(panel)
        self.assertEqual(len(panel.tasks), 1)
        _task, done, _failed, _commit = panel.tasks.pop()
        done({
            "locales": ["en_US.UTF-8", "zh_CN.UTF-8"],
            "session_locale": "en_US.UTF-8",
            "system_locale": "en_US.UTF-8",
            "preferences": {"ui_language": "en_US"},
            "overrides": {"LC_TIME": "C"},
            "missing_common": [],
        })
        self.assertEqual(widget.ui.get_active_id(), "en_US")
        widget.ui.set_active_id("zh_CN")
        widget.apply_ui()
        self.assertEqual(len(panel.tasks), 1)
        _task, done, _failed, _commit = panel.tasks.pop()
        done({"ui_language": "zh_CN"})
        self.assertEqual(i18n.get_language(), "zh_CN")

    def test_quick_controls_build_overview_wide_and_narrow(self):
        for width in (1280, 520):
            panel = FakePanel(width=width)
            with patch.object(quick_controls, "MediaControls", return_value=Gtk.Box()):
                overview = quick_controls.build_overview(panel)
            self.assertIsInstance(overview, Gtk.Box)
            self.assertEqual(set(panel.tiles), {"wifi", "bluetooth", "dnd", "idle"})
            self.assertEqual(set(panel.scales), {"volume", "brightness", "microphone"})
            self.assertEqual(set(panel.quick_pulse), {"cpu", "memory", "network", "temp"})
            panel.quick_details_button.set_active(True)
            self.assertTrue(panel.quick_details_revealer.get_reveal_child())

    def test_wallpaper_controls_and_preferences_draft_roundtrip(self):
        with tempfile.TemporaryDirectory(prefix="selandia-wp-ctrl-") as tmp:
            with patch.dict(os.environ, {"XDG_STATE_HOME": f"{tmp}/state", "XDG_CACHE_HOME": f"{tmp}/cache"}):
                panel = FakePanel(width=1280)
                controls = wallpaper_controls.WallpaperControls(panel)
                prefs = controls.preferences
                self.assertIsInstance(prefs, wallpaper_preferences.Preferences)
                self.assertEqual(controls.view_mode, "grid")
                controls.set_view("list")
                self.assertEqual(controls.view_mode, "list")
                prefs.name_entry.set_text("Custom Set")
                prefs.manage("create")
                self.assertEqual(len(prefs.registry["lists"]), 2)
                self.assertEqual(prefs.display_value()["mode"], "fill")
                controls.cleanup()


class ScriptAndRustHardeningTests(unittest.TestCase):
    def test_desktop_fast_path_skips_language_wrapper_for_power_and_clipboard(self):
        script = (ROOT / "niri/scripts/desktop").read_text()
        self.assertIn("power|clipboard|clipboard-clear", script)

    def test_input_region_escapes_stack_selected_name_for_json(self):
        source = (ROOT / "niri/eww/input_region.rs").read_text()
        self.assertIn('.replace(\'\\\\\',"\\\\\\\\").replace(\'"\',\"\\\\\\"\")', source)

    def test_control_sh_reports_when_both_paru_and_yay_are_missing(self):
        with tempfile.TemporaryDirectory(prefix="selandia-no-aur-helper-") as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            for name in ("control.sh", "check.sh", "install.sh"):
                shutil.copy2(ROOT / name, project / name)
            for directory in ("tools", "niri", "docs", "systemd", "portals"):
                shutil.copytree(ROOT / directory, project / directory,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (project / "packages.txt").write_text("# required aur eww | Rust bar\nniri\n")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            for cmd in ("bash", "awk", "sed", "grep", "env", "python3", "tr", "cat", "dirname", "mkdir"):
                resolved = shutil.which(cmd)
                if resolved:
                    (fake_bin / cmd).symlink_to(resolved)
            pacman = fake_bin / "pacman"
            pacman.write_text("#!/usr/bin/env bash\nif [[ \"$1\" == \"-Q\" && \"$2\" == \"eww\" ]]; then exit 1; fi\nexit 0\n")
            pacman.chmod(0o755)
            env = dict(os.environ, PATH=str(fake_bin), LC_ALL="en_US.UTF-8",
                       XDG_CONFIG_HOME=str(root / "cfg"), XDG_STATE_HOME=str(root / "state"))
            dry = subprocess.run(["/usr/bin/bash", str(project / "control.sh"), "--dry-run", "install"],
                                 cwd=project, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("Neither paru nor yay was found", dry.stdout)


if __name__ == "__main__":
    unittest.main()
