#!/usr/bin/env python3
"""Exercise native panel interactions on smoke.py's private Wayland/D-Bus session.

Every AI operation is mocked. No real provider, clipboard, system setting, or
hardware command is used. Run through tools/smoke.py, not in the live desktop.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))

import ai_backend as ai
import appearance
import application_theme
import audio_backend
import brightness
import display_backend
import media_backend
import metrics
import i18n
import ui_assets
import desktop_settings
import language_settings
import system_settings
import sleep_guard
import bluetooth_policy
import panel
from panel import Gdk, GLib, Gtk, Panel, Shell


def pump_until(predicate, timeout=3):
    """Let real worker callbacks run on GTK's main thread, with a hard deadline."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for _ in range(100):
            if not context.pending():
                break
            context.iteration(False)
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("Timed out waiting for the panel's GTK callback")


def drain():
    pump_until(lambda: True)


def labels(widget):
    if isinstance(widget, Gtk.Label):
        yield widget.get_text()
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from labels(child)


def descendants(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        children = []
        widget.forall(children.append)
        for child in children:
            yield from descendants(child)


def input_text(window):
    buffer = window.input.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


class PanelInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # GTK exports process-wide D-Bus objects, so use one application and fresh
        # windows instead of registering several applications in the same process.
        cls.app = Shell("ai")
        cls.app.set_application_id(f"org.selandia.PanelProbe.p{os.getpid()}")
        if not cls.app.register(None) or cls.app.get_is_remote():
            raise RuntimeError("Cannot register the isolated probe application")

    def setUp(self):
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.app, "quit"))
        self.stack.enter_context(patch.object(ui_assets, "write"))
        self.settings = dict(ai.DEFAULTS, model="probe-model")
        self.stack.enter_context(patch.object(ai, "load_settings", return_value=dict(self.settings)))
        self.chat = self.stack.enter_context(patch.object(ai, "chat", side_effect=AssertionError("Unmocked chat")))
        self.models = self.stack.enter_context(patch.object(ai, "discover_models", side_effect=AssertionError("Unmocked model lookup")))
        self.save = self.stack.enter_context(patch.object(ai, "save_settings", side_effect=AssertionError("Unmocked settings write")))
        self.stack.enter_context(patch.object(ai, "_request", side_effect=AssertionError("Provider access prohibited")))
        self.stack.enter_context(patch.object(media_backend, "_connection", side_effect=AssertionError("Live media access prohibited")))
        # A regression must never turn a GUI check into a host action.
        for owner, attribute in ((panel, "capture"), (panel, "set_bluetooth"),
                                 (panel.subprocess, "Popen"), (panel.subprocess, "run")):
            self.stack.enter_context(patch.object(owner, attribute, side_effect=AssertionError("External action prohibited")))
        self.window = None

    def make_panel(self, mode="ai"):
        self.window = Panel(self.app, mode)
        self.addCleanup(self.destroy_panel)
        self.window.show_all()
        drain()
        return self.window

    def destroy_panel(self):
        if self.window is not None and self.window.alive:
            self.window.destroy()
        drain()

    def send_success(self, window, prompt="Hello · 你好", response="Answer · 回复"):
        self.chat.side_effect = None
        self.chat.return_value = response
        window.input.get_buffer().set_text(prompt)
        window.send_chat()
        self.assertTrue(window.ai_busy)
        self.assertFalse(window.send_button.get_sensitive())
        self.assertFalse(window.clear_button.get_sensitive())
        pump_until(lambda: not window.ai_busy)
        return prompt, response

    def make_control(self, mode="control"):
        # Every newly added settings page is isolated, including read calls that
        # might otherwise reach the host's system bus or configured applications.
        self.desktop_fixture = {"settings": dict(desktop_settings.DEFAULTS), "configured": [],
                                "path": "/probe/desktop-settings.kdl", "custom_keymap": False}
        self.stack.enter_context(patch.object(desktop_settings, "read_state", return_value=self.desktop_fixture))
        self.native_apply = self.stack.enter_context(patch.object(desktop_settings, "apply_settings", return_value=self.desktop_fixture))
        self.stack.enter_context(patch.object(desktop_settings, "restore_defaults", return_value=self.desktop_fixture))
        preferences = {"ui_language": "en_US", "session_locale": "en_US.UTF-8"}
        self.locale_fixture = {"preferences": preferences, "locales": ["en_US.utf8", "zh_CN.utf8"],
                               "session_locale": "en_US.UTF-8", "system_locale": "en_US.UTF-8", "missing_common": []}
        self.stack.enter_context(patch.object(language_settings, "read_preferences", return_value=preferences))
        self.stack.enter_context(patch.object(language_settings, "read_state", return_value=self.locale_fixture))
        self.ui_language = self.stack.enter_context(patch.object(language_settings, "save_ui_language", side_effect=lambda value: dict(preferences, ui_language=value)))
        self.session_language = self.stack.enter_context(patch.object(language_settings, "apply_session_locale", side_effect=lambda value: {"locale": value, "preferences": preferences}))
        self.system_language = self.stack.enter_context(patch.object(language_settings, "apply_system_locale", side_effect=lambda value: {"locale": value}))
        self.power_fixture = {"settings": dict(system_settings.DEFAULT_POWER), "configured": True,
                              "consistent": True, "timers_enabled": True, "config_error": "",
                              "config_path": "/probe/swayidle/managed.conf"}
        self.power_runtime_fixture = {"awake": False, "available": True, "error": False,
                                      "timers_enabled": True, "timer_state": "active", "guard_state": "inactive",
                                      "label": "Timers running", "detail": "Niri timers are running."}
        self.power_runtime = self.stack.enter_context(patch.object(sleep_guard, "status", return_value=self.power_runtime_fixture))
        self.stack.enter_context(patch.object(sleep_guard, "set_awake", side_effect=AssertionError("Live sleep inhibitor action prohibited")))
        self.stack.enter_context(patch.object(sleep_guard, "apply_timers", side_effect=AssertionError("Live timer action prohibited")))
        fixtures = {
            "application_state": {role: {"choices": [("probe.desktop", "Probe App · 测试应用"), ("second.desktop", "Second App")], "default": "probe.desktop"} for role in system_settings.APP_TYPES},
            "power_state": self.power_fixture,
            "time_state": {"timezone": "Asia/Shanghai", "ntp": True, "can_ntp": True, "synchronized": True},
            "timezones": ["Asia/Shanghai", "UTC"],
            "service_state": {key: {"enabled": True, "active": True} for key in system_settings.MANAGED_UNITS},
            "startup_state": {"applications": [("probe.desktop", "Probe App")], "entries": []},
            "network_state": [{"id": "12345678-1234-1234-1234-123456789abc", "name": "Probe Wi-Fi · 测试网络", "device": "", "type": "802-11-wireless"}],
        }
        for name, result in fixtures.items():
            self.stack.enter_context(patch.object(system_settings, name, return_value=result))
        self.system_writes = {}
        for name in ("set_default_application", "save_power", "set_timezone", "set_ntp", "set_service", "add_startup", "toggle_startup", "activate_connection"):
            self.system_writes[name] = self.stack.enter_context(patch.object(system_settings, name))
        self.stack.enter_context(patch.object(bluetooth_policy, "read_state", return_value={
            "auto_enable": True, "configured": False, "path": "/etc/bluetooth/main.conf"}))
        self.bluetooth_policy_apply = self.stack.enter_context(patch.object(bluetooth_policy, "apply_auto_enable",
            side_effect=lambda value: {"auto_enable": value, "configured": True, "path": "/etc/bluetooth/main.conf"}))
        self.stack.enter_context(patch.object(Panel, "refresh_control", return_value=GLib.SOURCE_CONTINUE))
        self.stack.enter_context(patch.object(Panel, "refresh_system_info"))
        self.stack.enter_context(patch.object(appearance, "load_settings", return_value=dict(appearance.DEFAULTS)))
        self.appearance_save = self.stack.enter_context(patch.object(appearance, "apply_settings", side_effect=lambda value: dict(value)))
        self.appearance_defaults = self.stack.enter_context(patch.object(appearance, "restore_defaults", return_value=dict(appearance.DEFAULTS)))
        self.application_theme = self.stack.enter_context(patch.object(application_theme, "apply_mode", return_value={"warnings": []}))
        self.reload_theme = self.stack.enter_context(patch.object(self.app, "reload_theme"))
        self.metric_fixture = {
            "cpu_percent": 42.5,
            "memory": {"used": 4 * 1024**3, "total": 16 * 1024**3, "percent": 25},
            "disk": {"free": 64 * 1024**3, "percent": 20},
            "gpus": [{"name": "Probe GPU", "percent": 12.5, "temperature": 45}],
            "network": {"interface": "eth-probe", "down_bps": 1024**2, "up_bps": 2048},
            "load_average": [0.5, 0.4, 0.3], "uptime_seconds": 3600,
            "swap": {"used": 0, "total": 1024**3}, "temperatures": [],
        }
        self.sample = self.stack.enter_context(patch.object(metrics.MetricsSampler, "sample", return_value=self.metric_fixture))
        ports = [{"name": "speaker", "description": "Speakers", "available": True},
                 {"name": "headphone", "description": "Headphones", "available": True}]
        self.audio_fixture = {
            "sinks": [{"name": name, "description": name, "volume": 42, "mute": False,
                       "ports": ports, "active_port": "speaker"} for name in ("probe-output", "second-output")],
            "sources": [{"name": "probe-input", "description": "Microphone", "volume": 63,
                         "mute": True, "ports": [], "active_port": None}],
            "default_sink": "probe-output", "default_source": "probe-input",
            "cards": [{"name": "probe-card", "description": "Test card", "active_profile": "duplex",
                       "profiles": [{"name": name, "description": name, "available": True}
                                    for name in ("duplex", "off")]}],
        }
        self.audio_read = self.stack.enter_context(patch.object(audio_backend, "read_state", return_value=self.audio_fixture))
        self.audio_calls = {}
        for name in ("set_default", "set_volume", "set_mute", "set_port", "set_profile", "move_streams"):
            self.audio_calls[name] = self.stack.enter_context(patch.object(audio_backend, name))
        self.audio_calls["set_default"].side_effect = lambda kind, name: self.audio_fixture.update({f"default_{kind}": name})
        current = {"mode": "1920x1080@60", "scale": 1.5, "max_bpc": None,
                   "transform": "normal", "x": 0, "y": 0, "vrr": False}
        self.display_fixture = {
            "outputs": [{"name": "DP-6", "description": "Test display", "current": current,
                         "modes": [{"mode": "1920x1080@60"}, {"mode": "3840x2160@120"}],
                         "vrr_supported": True}],
            "saved": {}, "pending": None, "max_bpc_supported": False,
        }
        self.stack.enter_context(patch.object(display_backend, "read_state", return_value=self.display_fixture))
        self.display_apply = self.stack.enter_context(patch.object(display_backend, "begin_apply", return_value="test-token"))
        self.display_keep = self.stack.enter_context(patch.object(display_backend, "confirm", return_value=True))
        self.display_revert = self.stack.enter_context(patch.object(display_backend, "revert", return_value=True))
        self.brightness_write = self.stack.enter_context(patch.object(brightness, "set_percent"))
        self.media_players = [{
            "id": "org.mpris.MediaPlayer2.probe|:1.901", "identity": "Probe player",
            "status": "Playing", "title": "Single track", "artist": "Probe artist", "album": "Test album",
            "art_url": "", "can_control": True, "can_play": True, "can_pause": True,
            "can_next": False, "can_previous": False,
        }]
        self.media_read = self.stack.enter_context(patch.object(media_backend, "read_state", side_effect=self.media_snapshot))
        self.media_action = self.stack.enter_context(patch.object(media_backend, "action", side_effect=self.media_change))
        window = self.make_panel(mode)
        pump_until(lambda: not window.audio_loading and not window.metrics_busy and not window.appearance_busy
                   and not window.display_settings.loading and not window.media_controls.loading
                   and not any(getattr(page, "busy", False) for page in window.settings_pages.values()))
        return window

    def media_snapshot(self, preferred=None):
        players = deepcopy(self.media_players)
        selected = next((player for player in players if player["id"] == preferred), players[0] if players else None)
        return {"players": players, "selected": selected,
                "selected_id": selected["id"] if selected else None, "errors": []}

    def media_change(self, identifier, action):
        player = next(player for player in self.media_players if player["id"] == identifier)
        if action not in ("pause", "play"):
            raise AssertionError("This single-track fixture has no playlist navigation")
        player["status"] = "Paused" if action == "pause" else "Playing"
        return dict(player)

    def add_second_player(self, window):
        self.media_players.append(dict(self.media_players[0], id="org.mpris.MediaPlayer2.second|:1.902",
                                       identity="Second player", title="Second track", status="Paused"))
        window.media_controls.refresh()
        pump_until(lambda: not window.media_controls.loading)
        return self.media_players[1]["id"]

    def test_single_track_can_pause_without_previous_or_next(self):
        window = self.make_control()
        media = window.media_controls
        self.assertEqual(media.title.get_text(), "Single track")
        self.assertIn("Playing", media.status.get_text())
        self.assertTrue(media.buttons["toggle"].get_sensitive())
        self.assertFalse(media.buttons["previous"].get_sensitive())
        self.assertFalse(media.buttons["next"].get_sensitive())
        self.assertEqual(media.play_icon.get_icon_name()[0], "media-playback-pause-symbolic")
        media.buttons["toggle"].clicked()
        pump_until(lambda: not media.busy and not media.loading)
        self.media_action.assert_called_once_with(self.media_players[0]["id"], "pause")
        self.assertIn("Paused", media.status.get_text())
        self.assertEqual(media.play_icon.get_icon_name()[0], "media-playback-start-symbolic")
        self.assertTrue(media.buttons["toggle"].get_sensitive())
        self.assertFalse(media.buttons["previous"].get_sensitive())
        self.assertFalse(media.buttons["next"].get_sensitive())

    def test_paused_track_play_button_sends_explicit_play(self):
        window = self.make_control()
        media = window.media_controls
        media.buttons["toggle"].clicked()
        pump_until(lambda: not media.busy and not media.loading)
        media.buttons["toggle"].clicked()
        pump_until(lambda: not media.busy and not media.loading)
        self.assertEqual([call.args for call in self.media_action.call_args_list],
                         [(self.media_players[0]["id"], "pause"), (self.media_players[0]["id"], "play")])
        self.assertIn("Playing", media.status.get_text())
        self.assertEqual(media.play_icon.get_icon_name()[0], "media-playback-pause-symbolic")

    def test_explicit_player_source_survives_refresh_and_targets_that_player(self):
        window = self.make_control()
        media = window.media_controls
        second = self.add_second_player(window)
        media.source.set_active_id(second)
        pump_until(lambda: not media.loading and media.selected and media.selected["id"] == second)
        self.media_read.assert_called_with(second)
        self.assertEqual(media.title.get_text(), "Second track")
        self.assertIn("Paused", media.status.get_text())
        media.refresh()
        pump_until(lambda: not media.loading)
        self.assertEqual(media.source.get_active_id(), second)
        self.assertEqual(media.selected["id"], second)
        media.buttons["toggle"].clicked()
        pump_until(lambda: not media.busy and not media.loading)
        self.media_action.assert_called_once_with(second, "play")
        self.assertEqual(self.media_players[0]["status"], "Playing")
        self.assertEqual(media.title.get_text(), "Second track")

    def test_stale_media_poll_cannot_override_new_source(self):
        window = self.make_control()
        media = window.media_controls
        second = self.add_second_player(window)
        release, started, finished = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def delayed_read(preferred=None):
            snapshot = self.media_snapshot(preferred)
            if preferred is None:
                started.set()
                if not release.wait(2):
                    raise AssertionError("Probe failed to release stale media read")
                finished.set()
            return snapshot

        self.media_read.side_effect = delayed_read
        media.refresh()
        pump_until(started.is_set)
        media.source.set_active_id(second)
        release.set()
        pump_until(finished.is_set)
        pump_until(lambda: not media.loading)
        # A queued result from automatic selection cannot restore the old track.
        self.assertEqual(media.source.get_active_id(), second)
        self.assertNotEqual(media.title.get_text(), "Single track")
        pump_until(lambda: media.selected and media.selected["id"] == second)
        self.assertEqual(media.title.get_text(), "Second track")
        self.media_action.assert_not_called()

    def test_media_action_failure_preserves_track_and_enables_retry(self):
        window = self.make_control()
        media = window.media_controls
        self.media_action.side_effect = RuntimeError("Player restarted; refresh and select again · 播放器已重启，请重新选择")
        media.buttons["toggle"].clicked()
        pump_until(lambda: not media.busy and not media.loading)
        self.assertTrue(media.error.get_visible())
        self.assertIn("refresh and select", media.error.get_tooltip_text())
        self.assertIn("Player restarted", window.status.get_text())
        self.assertEqual(media.title.get_text(), "Single track")
        self.assertTrue(media.buttons["toggle"].get_sensitive())
        self.assertTrue(media.source.get_sensitive())

    def test_overview_primary_controls_fit_with_sidebar_at_960_by_820(self):
        # Render actual widgets with the default font, independent of the user's
        # saved theme and the nested compositor's available logical height.
        screen = Gdk.Screen.get_default()
        for css in ((ROOT / "niri/shell/style.css").read_text(),
                    appearance.render_files(dict(appearance.DEFAULTS))["panel.css"],
                    (ROOT / "niri/shell/control_center.css").read_text()):
            provider = Gtk.CssProvider()
            provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.addCleanup(Gtk.StyleContext.remove_provider_for_screen, screen, provider)
        window = self.make_control()
        window.hide()
        surface = window.surface
        window.remove(surface)
        canvas = Gtk.OffscreenWindow()
        self.addCleanup(canvas.destroy)
        canvas.get_style_context().add_class("glass-window")
        canvas.get_style_context().add_class("control-center-window")
        canvas.set_default_size(960, 820)
        canvas.set_size_request(960, 820)
        canvas.add(surface)
        canvas.show_all()
        scroll = window.control_stack.get_visible_child()
        pump_until(lambda: scroll.get_allocated_height() > 1)
        self.assertEqual(canvas.get_allocated_width(), 960)
        self.assertEqual(canvas.get_allocated_height(), 820)
        self.assertEqual(scroll.get_vadjustment().get_value(), 0)
        widgets = {name: window.tiles[name][0] for name in ("wifi", "bluetooth", "dnd", "idle")}
        widgets.update(media=window.media_controls.buttons["toggle"],
                       volume=window.scales["volume"], brightness=window.scales["brightness"],
                       notifications=window.notification_button)
        allocations = {}
        for name, widget in widgets.items():
            coordinates = widget.translate_coordinates(scroll, 0, 0)
            self.assertIsNotNone(coordinates, name)
            x, y = coordinates
            width, height = widget.get_allocated_width(), widget.get_allocated_height()
            allocations[name] = (x, y, width, height)
            self.assertTrue(widget.get_mapped(), name)
            self.assertGreater(height, 1, name)
            self.assertGreaterEqual(x, 0, (name, allocations))
            self.assertGreaterEqual(y, 0, (name, allocations))
            self.assertLessEqual(x + width, scroll.get_allocated_width(), (name, allocations))
            self.assertLessEqual(y + height, scroll.get_allocated_height(), (name, allocations))

    def test_control_focus_is_on_demand(self):
        window = self.make_control()
        self.assertEqual(panel.GtkLayerShell.get_keyboard_mode(window), panel.GtkLayerShell.KeyboardMode.ON_DEMAND)

    def test_light_mode_renders_readable_controls(self):
        screen = Gdk.Screen.get_default()
        settings = dict(appearance.DEFAULTS, color_mode="light", opacity=1)
        for css in ((ROOT / "niri/shell/style.css").read_text(),
                    appearance.render_files(settings)["panel.css"],
                    (ROOT / "niri/shell/control_center.css").read_text()):
            provider = Gtk.CssProvider()
            provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.addCleanup(Gtk.StyleContext.remove_provider_for_screen, screen, provider)
        window = self.make_control()
        window.apply_local_appearance(settings)
        window.hide()
        window.motion.cancel()
        window.surface.set_opacity(1)
        window.remove(window.surface)
        canvas = Gtk.OffscreenWindow()
        self.addCleanup(canvas.destroy)
        for name in ("glass-window", "control-center-window"):
            canvas.get_style_context().add_class(name)
        canvas.set_default_size(960, 820)
        canvas.set_size_request(960, 820)
        canvas.add(window.surface)
        canvas.show_all()
        pump_until(lambda: canvas.get_pixbuf() is not None)
        surface = window.surface.get_style_context().get_background_color(Gtk.StateFlags.NORMAL)
        self.assertGreater(surface.red, .8)
        button = window.media_controls.buttons["toggle"].get_style_context()
        foreground = button.get_color(Gtk.StateFlags.NORMAL)
        background = button.get_background_color(Gtk.StateFlags.NORMAL)
        self.assertGreater(foreground.red, .8)
        self.assertLess(background.red, .2)
        danger = window.power_button.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        # The light palette's darker red must replace the old pale pink.
        self.assertLess(danger.green, .3)
        self.assertLess(danger.blue, .4)
        canvas.get_pixbuf().savev(str(ROOT / ".validation/control-light.png"), "png", [], [])

    def test_keyboard_pages_and_escape_return_before_closing(self):
        window = self.make_control()
        def key(value, state=0):
            return window.on_key(window, SimpleNamespace(keyval=value, state=state))
        self.assertIn(window.get_focus(), window.control_switcher.get_children())
        self.assertTrue(key(Gdk.KEY_1 + window.control_pages.index("appearance"), Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(window.control_stack.get_visible_child_name(), "appearance")
        self.assertTrue(key(Gdk.KEY_Tab, Gdk.ModifierType.CONTROL_MASK))
        self.assertEqual(window.control_stack.get_visible_child_name(), "desktop")
        key(Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(window.control_stack.get_visible_child_name(), "appearance")
        key(Gdk.KEY_Escape)
        self.assertEqual(window.control_stack.get_visible_child_name(), "quick")
        self.assertTrue(window.alive)
        window.quick_details_button.set_active(True)
        self.assertTrue(window.quick_details_revealer.get_reveal_child())
        key(Gdk.KEY_Escape)
        self.assertFalse(window.quick_details_revealer.get_reveal_child())
        self.assertTrue(window.alive)
        key(Gdk.KEY_Escape)
        pump_until(lambda: not window.alive)

    def test_animation_has_intermediate_frames_and_finishes_close(self):
        window = self.make_control()
        settings = window.get_settings()
        original = settings.get_property("gtk-enable-animations")
        self.addCleanup(settings.set_property, "gtk-enable-animations", original)
        settings.set_property("gtk-enable-animations", True)
        pump_until(lambda: not window.motion.running)
        window.request_close()
        self.assertTrue(window.alive)
        pump_until(lambda: 0 < window.surface.get_opacity() < 1)
        self.assertTrue(window.alive)
        pump_until(lambda: not window.alive)
        self.assertFalse(window.motion.running)

    def test_reduce_motion_closes_immediately(self):
        window = self.make_control()
        window.apply_local_appearance(dict(appearance.DEFAULTS, reduced_motion=True))
        window.request_close()
        self.assertFalse(window.alive)

    def test_tile_poll_does_not_send_actions_and_click_exposes_toggle_state(self):
        window = self.make_control()
        with patch.object(window, "action") as action:
            window.state["wifi"] = "disabled"
            window.set_tile("wifi", True, False, "Off · 已关闭")
            action.assert_not_called()
            widget = window.tiles["wifi"][0]
            self.assertIsInstance(widget, Gtk.ToggleButton)
            widget.clicked()
            self.assertTrue(widget.get_active())
            self.assertFalse(widget.get_sensitive())
            action.assert_called_once()
            window.set_tile("wifi", True, True, "Enabled · 已开启")
            self.assertTrue(widget.get_sensitive())
            self.assertEqual(action.call_count, 1)

    def test_audio_poll_retains_model_selection_and_focus(self):
        window = self.make_control("sound")
        combo = window.audio_devices["sink"]
        combo.set_active_id("second-output")
        combo.grab_focus()
        focus = window.get_focus()
        self.assertIsNotNone(focus)
        self.assertTrue(focus is combo or focus.is_ancestor(combo))
        model = combo.get_model()
        deleted = []
        model.connect("row-deleted", lambda *_: deleted.append(True))
        window.apply_audio(deepcopy(self.audio_fixture))
        self.assertIs(combo.get_model(), model)
        self.assertEqual(deleted, [])
        self.assertEqual(combo.get_active_id(), "second-output")
        self.assertIs(window.get_focus(), focus)
        self.audio_calls["set_default"].assert_not_called()

    def test_audio_advanced_channels_request_is_read_only(self):
        window = self.make_control("sound")
        window.audio_advanced.set_active(True)
        pump_until(lambda: not window.audio_loading)
        self.audio_read.assert_called_with(include_unavailable=True)
        for operation in self.audio_calls.values():
            operation.assert_not_called()

    def test_scroll_over_combo_does_not_change_selection(self):
        window = self.make_control("appearance")
        combo = window.color_mode_combo
        selected = combo.get_active_id()
        event = Gdk.Event.new(Gdk.EventType.SCROLL)
        event.direction = Gdk.ScrollDirection.DOWN
        self.assertTrue(combo.emit("scroll-event", event))
        self.assertEqual(combo.get_active_id(), selected)

    def wheel(self, widget):
        event = Gdk.Event.new(Gdk.EventType.SCROLL)
        event.window = widget.get_window()
        event.send_event = True
        event.direction = Gdk.ScrollDirection.DOWN
        event.time = Gdk.CURRENT_TIME
        # Widget.event dispatches GTK's real generic event path before default
        # handlers, unlike emitting scroll-event only on the outer ComboBox.
        self.assertTrue(widget.event(event))

    def test_wheel_on_nested_combo_button_scrolls_page_without_selecting(self):
        window = self.make_control("input")
        page = window.settings_pages["input"]
        combo = page.fields["keyboard_track_layout"]
        child = next(widget for widget in descendants(combo) if isinstance(widget, Gtk.ToggleButton))
        scroll = window.control_stack.get_visible_child()
        adjustment = scroll.get_vadjustment()
        pump_until(lambda: adjustment.get_upper() > adjustment.get_page_size())
        adjustment.set_value(0)
        selected = combo.get_active_id()
        self.wheel(child)
        self.assertEqual(combo.get_active_id(), selected)
        self.assertGreater(adjustment.get_value(), 0)
        self.native_apply.assert_not_called()

    def test_wheel_on_focused_spin_and_scale_preserves_values(self):
        window = self.make_control("input")
        page = window.settings_pages["input"]
        spin = page.fields["keyboard_repeat_delay"]
        spin.grab_focus()
        original = spin.get_value()
        self.wheel(spin)
        self.assertEqual(spin.get_value(), original)
        window.select_control_tab("appearance")
        scale = window.opacity_scale
        scale.grab_focus()
        original = scale.get_value()
        self.wheel(scale)
        self.assertEqual(scale.get_value(), original)
        self.appearance_save.assert_not_called()

    def test_dynamic_combo_entry_is_protected_before_default_scroll_handler(self):
        window = self.make_control("input")
        page = window.settings_pages["input"]
        combo = Gtk.ComboBoxText.new_with_entry()
        combo.append_text("First")
        combo.append_text("Second")
        combo.set_active(0)
        page.form.add(combo)
        combo.show_all()
        drain()
        self.wheel(combo.get_child())
        self.assertEqual(combo.get_active(), 0)

    def test_navigation_search_both_languages_and_keyboard_focus(self):
        window = self.make_control()
        self.assertEqual(len(window.control_pages), 16)
        self.assertTrue(window.on_key(window, SimpleNamespace(keyval=Gdk.KEY_f, state=Gdk.ModifierType.CONTROL_MASK)))
        self.assertIs(window.get_focus(), window.navigation.search)
        for query, expected in (("键盘", "input"), ("timezone", "time"), ("终端", "language")):
            window.navigation.search.set_text(query)
            window.navigation.filter()
            window.navigation.search.emit("activate")
            self.assertEqual(window.control_stack.get_visible_child_name(), expected)
        window.navigation.search.set_text("no-matching-setting-999")
        window.navigation.filter()
        self.assertTrue(window.navigation.empty.get_visible())
        window.on_key(window, SimpleNamespace(keyval=Gdk.KEY_Escape, state=0))
        self.assertEqual(window.navigation.search.get_text(), "")
        self.assertEqual(window.control_stack.get_visible_child_name(), "language")
        for operation in self.system_writes.values():
            operation.assert_not_called()

    def test_language_scopes_require_separate_apply_actions(self):
        window = self.make_control("language")
        page = window.settings_pages["language"]
        changed = self.stack.enter_context(patch.object(window, "language_changed"))
        page.ui.set_active_id("zh_CN")
        page.session.set_active_id("zh_CN.UTF-8")
        page.system.set_active_id("zh_CN.UTF-8")
        for operation in (self.ui_language, self.session_language, self.system_language):
            operation.assert_not_called()
        page.apply_ui()
        pump_until(lambda: not page.busy)
        self.ui_language.assert_called_once_with("zh_CN")
        changed.assert_called_once()
        self.session_language.assert_not_called()
        self.system_language.assert_not_called()
        page.apply_session()
        pump_until(lambda: not page.busy)
        self.session_language.assert_called_once_with("zh_CN.UTF-8")
        self.system_language.assert_not_called()
        page.apply_system()
        pump_until(lambda: not page.busy)
        self.system_language.assert_called_once_with("zh_CN.UTF-8")

    def test_chinese_navigation_uses_one_language_and_preserves_app_names(self):
        i18n.set_language("zh_CN")
        window = self.make_control("applications")
        navigation_labels = list(labels(window.navigation))
        self.assertIn("默认应用", navigation_labels)
        self.assertNotIn("Default applications", navigation_labels)
        page = window.settings_pages["applications"]
        self.assertEqual(page.choices["browser"].get_active_text(), "Probe App · 测试应用")

    def test_interface_language_rebuilds_window_on_same_page_without_quitting(self):
        original = self.make_control("language")
        self.app.window = original
        self.addCleanup(setattr, self.app, "window", None)
        reload_command = self.stack.enter_context(patch.object(panel, "capture", return_value=""))
        page = original.settings_pages["language"]
        page.ui.set_active_id("zh_CN")
        page.apply_ui()
        pump_until(lambda: self.app.window is not original)
        self.window = self.app.window
        self.assertFalse(original.alive)
        self.assertTrue(self.window.alive)
        self.assertEqual(self.window.control_stack.get_visible_child_name(), "language")
        self.assertEqual(self.window.page_heading.get_text(), "语言与地区")
        self.app.quit.assert_not_called()
        ui_assets.write.assert_called_once_with()
        reload_command.assert_called_once_with([panel.DESKTOP, "reload"], timeout=20)
        self.session_language.assert_not_called()
        self.system_language.assert_not_called()

    def test_native_input_and_window_drafts_apply_only_the_selected_group(self):
        window = self.make_control("input")
        page = window.settings_pages["input"]
        page.fields["keyboard_repeat_delay"].set_value(500)
        page.fields["mouse_left_handed"].set_active(True)
        self.native_apply.assert_not_called()
        page.apply()
        pump_until(lambda: not page.busy)
        group, values = self.native_apply.call_args.args
        self.assertEqual(group, "input")
        self.assertEqual(values["keyboard_repeat_delay"], 500)
        self.assertTrue(values["mouse_left_handed"])
        self.assertEqual(set(values), desktop_settings.GROUPS["input"])
        page = window.settings_pages["desktop"]
        page.fields["gaps"].set_value(24)
        page.apply()
        pump_until(lambda: not page.busy)
        self.assertEqual(self.native_apply.call_args.args[0], "desktop")
        self.assertEqual(self.native_apply.call_args.args[1]["gaps"], 24)

    def test_system_pages_do_not_apply_on_selection_or_population(self):
        window = self.make_control("applications")
        applications = window.settings_pages["applications"]
        applications.choices["browser"].set_active_id("second.desktop")
        self.system_writes["set_default_application"].assert_not_called()
        applications.apply("browser")
        pump_until(lambda: not applications.busy)
        self.system_writes["set_default_application"].assert_called_once_with("browser", "second.desktop")
        window.select_control_tab("network")
        network = window.settings_pages["network"]
        pump_until(lambda: network.loaded and not network.busy)
        self.assertEqual(network.profile.get_active_text(), "Probe Wi-Fi · 测试网络")
        self.system_writes["activate_connection"].assert_not_called()
        network.connect_button.clicked()
        pump_until(lambda: not network.busy)
        self.system_writes["activate_connection"].assert_called_once_with("12345678-1234-1234-1234-123456789abc", True)

    def test_power_page_reports_actual_status_and_does_not_discard_drafts_on_refresh(self):
        window = self.make_control("power")
        page = window.settings_pages["power"]
        self.assertEqual(page.runtime_label.get_text(), "Timers running")
        self.assertIn("only to Niri", page.scope_note.get_text())
        self.assertFalse(page.config_warning.get_visible())
        page.spins["lock_minutes"].set_value(17)
        self.power_runtime_fixture.update(awake=True, label="Sleep blocked", detail="A confirmed inhibitor is active.")
        page.status_refresh.clicked()
        pump_until(lambda: not page.busy)
        self.assertEqual(page.runtime_label.get_text(), "Sleep blocked")
        self.assertEqual(page.runtime_detail.get_text(), "A confirmed inhibitor is active.")
        self.assertEqual(page.spins["lock_minutes"].get_value_as_int(), 17)
        self.system_writes["save_power"].assert_not_called()
        sleep_guard.set_awake.assert_not_called()
        sleep_guard.apply_timers.assert_not_called()

    def test_power_page_warns_when_effective_config_differs_from_saved_values(self):
        window = self.make_control("power")
        page = window.settings_pages["power"]
        self.power_fixture["consistent"] = False
        page.refresh_status()
        pump_until(lambda: not page.busy)
        self.assertTrue(page.config_warning.get_visible())
        self.assertIn("differs from the saved values", page.config_warning.get_text())
        self.system_writes["save_power"].assert_not_called()

    def test_power_page_keeps_settings_visible_if_runtime_read_fails(self):
        window = self.make_control("power")
        page = window.settings_pages["power"]
        self.power_runtime.side_effect = RuntimeError("service manager unavailable")
        page.refresh()
        pump_until(lambda: not page.busy)
        self.assertEqual(page.runtime_label.get_text(), "Power state unavailable")
        self.assertIn("service manager unavailable", page.runtime_detail.get_text())
        self.assertEqual(page.spins["lock_minutes"].get_value_as_int(), 5)
        self.assertTrue(page.spins["lock_minutes"].is_sensitive())
        self.system_writes["save_power"].assert_not_called()

    def test_power_timeouts_apply_only_on_confirmation_and_expose_backend_failure(self):
        window = self.make_control("power")
        page = window.settings_pages["power"]
        values = {"lock_minutes": 7, "screen_minutes": 12, "suspend_minutes": 30}
        for key, value in values.items():
            page.spins[key].set_value(value)
        self.system_writes["save_power"].assert_not_called()
        self.system_writes["save_power"].side_effect = RuntimeError("Reload failed; previous settings restored.")
        page.apply()
        pump_until(lambda: not page.busy)
        self.system_writes["save_power"].assert_called_once_with(values)
        self.assertEqual(page.notice.get_text(), "Reload failed; previous settings restored.")
        self.assertEqual(page.spins["lock_minutes"].get_value_as_int(), 7)

    def test_overview_requires_confirmed_inhibitor_to_show_stay_awake(self):
        window = self.make_control()
        state = {"wifi": "disabled", "bluetooth": {}, "dnd": "false", "notifications": "0",
                 "volume": None, "microphone": None, "brightness": {}, "profile": None, "profiles": ""}
        scenarios = [
            dict(self.power_runtime_fixture, awake=False, timers_enabled=False, timer_state="inactive", label="Timers disabled"),
            dict(self.power_runtime_fixture, awake=False, error=True, timer_state="failed", label="Power service error"),
            dict(self.power_runtime_fixture, awake=True, guard_state="active", label="Sleep blocked"),
        ]
        with patch.object(window, "action") as action:
            for runtime in scenarios:
                with self.subTest(label=runtime["label"]):
                    window.apply_control(dict(state, power_runtime=runtime))
                    toggle, label = window.tiles["idle"]
                    self.assertEqual(toggle.get_active(), runtime["awake"])
                    self.assertEqual(label.get_text(), runtime["label"])
                    self.assertEqual(toggle.get_tooltip_text(), runtime["detail"])
            action.assert_not_called()

    def test_bluetooth_boot_policy_applies_only_explicitly_and_recovers_from_error(self):
        from bluetooth_controls import BluetoothPolicyControls
        window = self.make_control("network")
        controls = next(widget for widget in descendants(window.settings_pages["network"])
                        if isinstance(widget, BluetoothPolicyControls))
        pump_until(lambda: controls.loaded and not controls.busy)
        self.assertTrue(controls.enabled.get_active())
        self.assertFalse(controls.apply.get_sensitive())
        controls.enabled.set_active(False)
        self.bluetooth_policy_apply.assert_not_called()
        self.assertTrue(controls.apply.get_sensitive())
        self.bluetooth_policy_apply.side_effect = RuntimeError("Authentication cancelled")
        controls.apply.clicked()
        pump_until(lambda: not controls.busy)
        self.assertTrue(controls.enabled.get_sensitive())
        self.assertTrue(controls.apply.get_sensitive())
        self.assertIn("Authentication cancelled", controls.notice.get_text())
        self.bluetooth_policy_apply.side_effect = lambda value: {"auto_enable": value}
        controls.apply.clicked()
        pump_until(lambda: not controls.busy)
        self.assertFalse(controls.saved)
        self.assertFalse(controls.apply.get_sensitive())
        self.assertEqual([call.args for call in self.bluetooth_policy_apply.call_args_list], [(False,), (False,)])

    def test_native_display_apply_and_visible_confirmation(self):
        window = self.make_control("displays")
        view = window.display_settings
        self.assertEqual(window.control_stack.get_visible_child_name(), "displays")
        self.assertFalse(view.depth.get_sensitive())
        self.assertIn("max-bpc", view.depth_note.get_text())
        self.assertFalse(view.keep_box.get_visible())
        view.mode.get_child().set_text("1920*1080@60Hz")
        view.scale.set_value(100)
        view.apply()
        self.assertTrue(view.busy)
        pump_until(lambda: view.token is not None)
        self.assertEqual(self.display_apply.call_args.args[0], "DP-6")
        self.assertEqual(self.display_apply.call_args.args[1]["mode"], "1920x1080@60")
        self.assertEqual(self.display_apply.call_args.args[1]["scale"], 1)
        self.assertTrue(view.keep_box.get_mapped())
        self.assertTrue(view.keep_label.get_visible())
        self.assertFalse(view.form.get_sensitive())
        view.keep()
        pump_until(lambda: not view.busy and not view.loading)
        self.display_keep.assert_called_once_with("test-token")
        self.assertFalse(view.keep_box.get_visible())
        self.assertIsNone(view.token)
        self.assertIsNone(view.timer)

    def test_native_display_timeout_and_failed_apply(self):
        window = self.make_control("displays")
        view = window.display_settings
        view.wait_for_confirmation("expiring", .01)
        pump_until(lambda: view.token is None and not view.loading)
        self.display_revert.assert_called_once_with("expiring")
        self.display_apply.side_effect = RuntimeError("Unsupported mode · 不支持此模式")
        view.apply()
        pump_until(lambda: not view.busy)
        self.assertIn("Unsupported mode", view.notice.get_text())
        self.assertTrue(view.form.get_sensitive())

    def test_brightness_device_selection_and_unavailable_state(self):
        window = self.make_control()
        state = {"devices": [{"id": "ddc:1", "label": "DP-6", "available": True,
                              "backend": "ddc", "percent": 100},
                             {"id": "ddc:2", "label": "HDMI-1", "available": False,
                              "percent": None, "reason": "Enable DDC/CI"}]}
        window.apply_brightness(state)
        self.assertEqual(window.brightness_combo.get_active_id(), "ddc:1")
        self.assertEqual(window.scales["brightness"].get_value(), 100)
        self.assertIn("DDC/CI", window.backlight_note.get_text())
        window.brightness_combo.set_active_id("ddc:2")
        self.assertFalse(window.scales["brightness"].get_sensitive())
        self.assertEqual(window.scale_values["brightness"].get_text(), "—")
        self.assertIn("Enable", window.backlight_note.get_text())
        self.brightness_write.assert_not_called()

    def test_brightness_drag_is_coalesced_and_runs_off_main_thread(self):
        window = self.make_control()
        device = {"id": "ddc:1", "label": "DP-6", "available": True, "backend": "ddc", "percent": 100}
        window.apply_brightness({"devices": [device]})
        thread_ids = []
        release = threading.Event()
        self.addCleanup(release.set)
        def write(identifier, value):
            thread_ids.append(threading.get_ident())
            release.wait(2)
            return dict(device, percent=value)
        self.brightness_write.side_effect = write
        scale = window.scales["brightness"]
        window.scale_drag_start(scale, None, "brightness")
        scale.set_value(40)
        scale.set_value(45)
        pump_until(lambda: "brightness" not in window.scale_timers)
        self.brightness_write.assert_not_called()
        window.scale_drag_end(scale, None, "brightness")
        pump_until(lambda: window.brightness_busy)
        window.set_brightness(50)
        window.set_brightness(55)
        release.set()
        pump_until(lambda: not window.brightness_busy)
        self.assertEqual([call.args for call in self.brightness_write.call_args_list], [("ddc:1", 45), ("ddc:1", 55)])
        self.assertTrue(all(identifier != threading.get_ident() for identifier in thread_ids))
        self.assertEqual(scale.get_value(), 55)

    def test_control_tabs_metrics_and_unavailable_readings(self):
        window = self.make_control("system")
        self.assertEqual(window.mode, "control")
        self.assertEqual(window.control_stack.get_visible_child_name(), "system")
        self.assertIn("42", window.metric_values["cpu"].get_text())
        self.assertIn("eth-probe", window.network_detail.get_text())
        self.assertIn("Probe GPU", window.metric_details["gpu"].get_text())
        self.assertAlmostEqual(window.metric_bars["memory"].get_fraction(), .25)
        window.apply_metrics({})
        self.assertEqual(window.metric_values["cpu"].get_text(), "—")
        self.assertEqual(window.metric_values["download"].get_text(), "—")
        self.assertFalse(window.metric_bars["cpu"].get_sensitive())
        self.assertIn("Unavailable", window.metric_details["gpu"].get_text())
        window.select_control_tab("sound")
        self.assertEqual(window.control_stack.get_visible_child_name(), "sound")

    def test_existing_control_window_switches_tab_then_toggles(self):
        window = self.make_control()
        self.app.window = window
        self.addCleanup(setattr, self.app, "window", None)
        command_line = SimpleNamespace(get_arguments=lambda: ["panel.py", "appearance"])
        self.assertEqual(self.app.do_command_line(command_line), 0)
        self.assertEqual(window.control_stack.get_visible_child_name(), "appearance")
        self.assertTrue(window.alive)
        self.assertEqual(self.app.do_command_line(command_line), 0)
        pump_until(lambda: not window.alive)
        self.assertFalse(window.alive)
        self.assertFalse(window.pending)

    def test_appearance_apply_runs_off_main_thread_and_reset(self):
        window = self.make_control("appearance")
        thread_ids = []

        def save(settings):
            thread_ids.append(threading.get_ident())
            return dict(settings)

        self.appearance_save.side_effect = save
        reload_command = self.stack.enter_context(patch.object(panel, "capture", return_value=""))
        window.theme_combo.set_active_id("violet")
        window.opacity_scale.set_value(73)
        window.font_sizes["font"].set_value(14)
        window.color_mode_combo.set_active_id("light")
        window.reduced_motion_check.set_active(True)
        window.apply_appearance()
        self.assertTrue(window.appearance_busy)
        self.assertFalse(window.appearance_body.get_sensitive())
        pump_until(lambda: not window.appearance_busy)
        self.assertNotEqual(thread_ids[0], threading.get_ident())
        self.assertEqual(self.appearance_save.call_args.args[0]["preset"], "violet")
        self.assertEqual(self.appearance_save.call_args.args[0]["opacity"], .73)
        self.assertEqual(self.appearance_save.call_args.args[0]["font_size"], 14)
        self.assertEqual(self.application_theme.call_args.args[0]["color_mode"], "light")
        self.assertFalse(window.get_settings().get_property("gtk-application-prefer-dark-theme"))
        self.assertEqual(window.control_stack.get_transition_duration(), 0)
        self.assertEqual(window.quick_details_revealer.get_transition_duration(), 0)
        reload_command.assert_called_once_with([panel.DESKTOP, "theme-reload"], timeout=20)
        self.reload_theme.assert_called_once()
        window.apply_appearance(reset=True)
        pump_until(lambda: not window.appearance_busy)
        self.appearance_defaults.assert_called_once_with()
        self.assertEqual(window.theme_combo.get_active_id(), appearance.DEFAULTS["preset"])

    def test_appearance_failed_save_keeps_edit_and_enables_retry(self):
        window = self.make_control("appearance")
        self.appearance_save.side_effect = OSError("Read-only probe")
        window.theme_combo.set_active_id("graphite")
        window.apply_appearance()
        pump_until(lambda: not window.appearance_busy)
        self.assertEqual(window.theme_combo.get_active_id(), "graphite")
        self.assertTrue(window.appearance_body.get_sensitive())
        self.assertIn("Read-only probe", window.status.get_text())
        self.reload_theme.assert_not_called()

    def test_missing_saved_font_selects_an_installed_fallback(self):
        window = self.make_control("appearance")
        window.populate_appearance(dict(appearance.DEFAULTS, font="Uninstalled Probe Font 999"))
        draft = window.draft_appearance()
        self.assertNotEqual(draft["font"], "Uninstalled Probe Font 999")
        self.assertTrue(draft["font"])
        appearance.validate_settings(draft)
        self.assertIn("unavailable", window.font_buttons["font"].get_tooltip_text())

    def test_audio_refresh_never_mutates_and_device_selection_sets_default(self):
        window = self.make_control("sound")
        for method in self.audio_calls.values():
            method.assert_not_called()
        self.assertEqual(window.audio_devices["sink"].get_active_id(), "probe-output")
        self.assertEqual(window.audio_volumes["source"].get_value(), 63)
        window.audio_devices["sink"].set_active_id("second-output")
        self.audio_calls["set_default"].assert_not_called()
        window.apply_audio(self.audio_fixture)
        self.assertEqual(window.audio_devices["sink"].get_active_id(), "second-output")
        window.audio_use_device("sink")
        pump_until(lambda: not window.audio_busy and not window.audio_loading)
        self.audio_calls["set_default"].assert_called_once_with("sink", "second-output")
        self.assertEqual(window.audio_devices["sink"].get_active_id(), "second-output")
        window.audio_toggle_mute("source")
        pump_until(lambda: not window.audio_busy and not window.audio_loading)
        self.audio_calls["set_mute"].assert_called_once_with("source", "probe-input", False)

    def test_audio_volume_port_and_existing_app_routing(self):
        window = self.make_control("sound")
        window.audio_volumes["sink"].set_value(50)
        window.audio_volumes["sink"].set_value(65)
        pump_until(lambda: self.audio_calls["set_volume"].called and not window.audio_busy)
        self.audio_calls["set_volume"].assert_called_once_with("sink", "probe-output", 65)
        pump_until(lambda: not window.audio_loading)
        window.audio_ports["sink"].set_active_id("headphone")
        self.audio_calls["set_port"].assert_not_called()
        window.audio_apply_port("sink")
        pump_until(lambda: not window.audio_busy and not window.audio_loading)
        self.audio_calls["set_port"].assert_called_once_with("sink", "probe-output", "headphone")
        window.audio_move_streams("sink")
        pump_until(lambda: not window.audio_busy and not window.audio_loading)
        self.audio_calls["move_streams"].assert_called_once_with("sink", "probe-output")

    def test_audio_profile_requires_explicit_apply_and_survives_refresh(self):
        window = self.make_control("sound")
        window.audio_profile_combo.set_active_id("off")
        self.audio_calls["set_profile"].assert_not_called()
        window.apply_audio(self.audio_fixture)
        self.assertEqual(window.audio_profile_combo.get_active_id(), "off")
        window.audio_apply_profile()
        pump_until(lambda: not window.audio_busy and not window.audio_loading)
        self.audio_calls["set_profile"].assert_called_once_with("probe-card", "off")

    def test_unavailable_audio_disables_controls_without_affecting_other_tabs(self):
        window = self.make_control("sound")
        self.audio_read.side_effect = RuntimeError("No audio server")
        window.refresh_audio()
        pump_until(lambda: not window.audio_loading)
        self.assertFalse(window.audio_controls.get_sensitive())
        self.assertIn("No audio server", window.audio_status.get_text())
        window.select_control_tab("system")
        self.assertEqual(window.control_stack.get_visible_child_name(), "system")

    def test_display_summary_uses_niri_mode_and_scale(self):
        text = Panel.describe_outputs({"DP-1": {"model": "Probe panel", "current_mode": 0,
                                               "modes": [{"width": 2560, "height": 1440, "refresh_rate": 165000}],
                                               "logical": {"scale": 1.25, "x": 0, "y": 0}}})
        for detail in ("2560 × 1440", "165 Hz", "1.25×", "Probe panel"):
            self.assertIn(detail, text)
        self.assertIn("unavailable", Panel.describe_outputs({}))

    def test_async_reply_history_busy_guard_and_clear(self):
        window = self.make_panel()
        self.chat.side_effect = None
        self.chat.return_value = "Native reply · 原生回复"
        window.input.get_buffer().set_text("Hello · 你好")
        window.send_chat()
        self.assertTrue(window.ai_busy)
        self.assertFalse(window.send_button.get_sensitive())
        window.send_chat()  # A duplicate Enter while waiting cannot start another request.
        window.clear_chat()
        self.assertEqual(window.messages, [{"role": "user", "content": "Hello · 你好"}])
        pump_until(lambda: not window.ai_busy)
        self.chat.assert_called_once()
        self.assertEqual(self.chat.call_args.args[0], [{"role": "user", "content": "Hello · 你好"}])
        self.assertEqual(window.messages, [{"role": "user", "content": "Hello · 你好"},
                                           {"role": "assistant", "content": "Native reply · 原生回复"}])
        self.assertEqual(input_text(window), "")
        self.assertTrue(window.send_button.get_sensitive())
        self.assertTrue(window.clear_button.get_sensitive())
        self.assertTrue(window.copy_button.get_sensitive())
        self.assertIn("Native reply · 原生回复", list(labels(window.chat_body)))
        window.clear_chat()
        self.assertEqual(window.messages, [])
        self.assertEqual(window.last_reply, "")
        self.assertFalse(window.copy_button.get_sensitive())
        self.assertEqual(window.chat_body.get_children(), [])

    def test_failed_reply_restores_input_without_polluting_history(self):
        window = self.make_panel()
        self.send_success(window)
        original = [dict(message) for message in window.messages]
        self.chat.side_effect = ValueError("Offline for probe · 测试离线")
        window.input.get_buffer().set_text("Please retry · 请重试")
        window.send_chat()
        pump_until(lambda: not window.ai_busy)
        self.assertEqual(window.messages, original)
        self.assertEqual(input_text(window), "Please retry · 请重试")
        self.assertIn("Offline for probe", window.status.get_text())
        self.assertTrue(window.send_button.get_sensitive())
        self.assertTrue(window.clear_button.get_sensitive())

    def test_failed_reply_keeps_a_new_draft(self):
        window = self.make_panel()
        release = threading.Event()
        self.addCleanup(release.set)

        def failure(*_):
            if not release.wait(2):
                raise AssertionError("Probe failed to release blocked worker")
            raise ValueError("Simulated provider failure")

        self.chat.side_effect = failure
        window.input.get_buffer().set_text("Sent prompt")
        window.send_chat()
        window.input.get_buffer().set_text("New draft · 新草稿")
        release.set()
        pump_until(lambda: not window.ai_busy)
        self.assertEqual(input_text(window), "New draft · 新草稿")
        self.assertEqual(window.messages, [])

    def test_model_discovery_populates_selectable_models(self):
        window = self.make_panel()
        window.toggle_settings()
        self.models.side_effect = None
        self.models.return_value = ["local-alpha", "local-beta"]
        window.find_models()
        pump_until(lambda: len(window.model_choices.get_model()) == 2)
        self.models.assert_called_once()
        self.assertEqual([row[0] for row in window.model_choices.get_model()], ["local-alpha", "local-beta"])
        self.assertTrue(window.model_choices.get_visible())
        window.model_choices.set_active(1)
        self.assertEqual(window.setting_entries["model"].get_text(), "local-beta")

    def test_provider_change_clears_prior_provider_history(self):
        window = self.make_panel()
        self.send_success(window, "Private local prompt", "Private local reply")
        window.toggle_settings()
        window.provider.set_active_id("openai-compatible")
        window.setting_entries["endpoint"].set_text("https://example.invalid/v1")
        window.setting_entries["model"].set_text("remote-probe")
        self.save.side_effect = None
        self.save.return_value = None
        window.save_ai_settings()
        pump_until(lambda: window.settings.get("provider") == "openai-compatible")
        self.save.assert_called_once()
        self.assertEqual(window.messages, [])
        self.assertEqual(window.last_reply, "")
        self.assertFalse(window.copy_button.get_sensitive())
        self.assertNotIn("Private local prompt", list(labels(window.chat_body)))
        self.send_success(window, "Fresh remote prompt", "Fresh remote reply")
        self.assertEqual(self.chat.call_args.args[0], [{"role": "user", "content": "Fresh remote prompt"}])

    def test_stale_model_lookup_cannot_replace_current_provider_models(self):
        window = self.make_panel()
        window.toggle_settings()
        release = threading.Event()
        old_finished = threading.Event()
        self.addCleanup(release.set)

        def discover(settings):
            if settings["endpoint"].startswith("http://localhost"):
                if not release.wait(2):
                    raise AssertionError("Probe failed to release model worker")
                old_finished.set()
                return ["stale-local-model"]
            return ["current-remote-model"]

        self.models.side_effect = discover
        window.find_models()
        window.provider.set_active_id("openai-compatible")
        window.setting_entries["endpoint"].set_text("https://example.invalid/v1")
        window.find_models()
        pump_until(lambda: window.model_choices.get_active_text() == "current-remote-model")
        release.set()
        pump_until(old_finished.is_set)
        # Give the old worker's queued completion time to reach GTK.
        deadline = time.monotonic() + .05
        pump_until(lambda: time.monotonic() >= deadline)
        self.assertEqual(window.model_choices.get_active_text(), "current-remote-model")
        self.assertEqual(window.setting_entries["model"].get_text(), "current-remote-model")

    def test_shortcut_search_english_chinese_and_no_results(self):
        window = self.make_panel("shortcuts")
        total = len(window.shortcuts)
        self.assertGreater(total, 100)
        for query in ("workspace", "工作区"):
            with self.subTest(query=query):
                window.filter_shortcuts(SimpleNamespace(get_text=lambda: query))
                visible = list(labels(window.shortcut_body))
                self.assertTrue(any("workspace" in text.lower() for text in visible))
                self.assertNotIn("0 shortcuts", window.shortcut_summary.get_text())
                self.assertNotIn(f"{total} shortcuts", window.shortcut_summary.get_text())
        window.filter_shortcuts(SimpleNamespace(get_text=lambda: "no-such-shortcut-49817"))
        self.assertIn("0 shortcuts", window.shortcut_summary.get_text())
        self.assertIn("No matching shortcuts", list(labels(window.shortcut_body)))
        window.filter_shortcuts(SimpleNamespace(get_text=lambda: ""))
        self.assertIn(f"{total} shortcuts", window.shortcut_summary.get_text())

    def test_ime_can_consume_enter_before_chat_submission(self):
        owner = SimpleNamespace(send_chat=MagicMock())
        widget = SimpleNamespace(im_context_filter_keypress=MagicMock(return_value=True))
        event = SimpleNamespace(keyval=Gdk.KEY_Return, state=Gdk.ModifierType(0))
        self.assertTrue(Panel.input_key(owner, widget, event))
        widget.im_context_filter_keypress.assert_called_once_with(event)
        owner.send_chat.assert_not_called()
        widget.im_context_filter_keypress.return_value = False
        self.assertTrue(Panel.input_key(owner, widget, event))
        owner.send_chat.assert_called_once()
        event.state = Gdk.ModifierType.SHIFT_MASK
        self.assertFalse(Panel.input_key(owner, widget, event))
        owner.send_chat.assert_called_once()


def main():
    state = Path(os.environ.get("XDG_STATE_HOME", ""))
    if (not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            or not state.is_absolute() or not state.name.startswith("selandia-smoke-")):
        print("Run this probe through tools/smoke.py on its isolated session.", file=sys.stderr)
        return 2

    def timed_out(_signum, _frame):
        print("Panel interaction probe exceeded 20 seconds", file=sys.stderr, flush=True)
        os._exit(124)

    signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(20)
    try:
        if not Gtk.init_check()[0]:
            raise RuntimeError("Cannot connect to the nested GTK display")
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PanelInteractionTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
