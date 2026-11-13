"""Audio capability checks and stream controls never contact the real desktop."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import wallpaper
import wallpaper_audio as audio


class WallpaperAudioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-wallpaper-audio-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root), XDG_RUNTIME_DIR=str(self.root / "runtime"))
        env.start()
        self.addCleanup(env.stop)

    def command(self, kind, value=None, ready=True):
        item = {"type": kind, "file": "/tmp/movie.mp4", "path": "/tmp/project"}
        with patch.object(wallpaper.shutil, "which", return_value="/test/bin"):
            return wallpaper.playback_command(item, "live", assets=str(self.root), outputs=["DP-1"], audio=value, audio_available=ready)

    def test_sound_is_on_by_default_for_video_scene_and_web(self):
        video = self.command("video")
        self.assertIn("audio=yes", video[2])
        self.assertIn("volume=100", video[2])
        self.assertNotIn("no-audio", video[2])
        for kind in ("scene", "web"):
            command = self.command(kind)
            self.assertNotIn("--silent", command)
            self.assertNotIn("--mute-audio", command)
            self.assertIn("--noautomute", command)
            self.assertEqual(command[command.index("--volume") + 1], "128")

    def test_mute_and_zero_volume_keep_audio_decoding_for_live_stream_controls(self):
        for value in ({"muted": True, "volume": 70}, {"muted": False, "volume": 0}):
            self.assertNotIn("no-audio", self.command("video", value)[2])
            self.assertNotIn("--silent", self.command("scene", value))
            self.assertNotIn("--mute-audio", self.command("web", value))

    def test_absent_audio_disables_unbounded_engine_recorder_and_video_audio(self):
        self.assertIn("no-audio", self.command("video", ready=False)[2])
        for kind in ("scene", "web"):
            command = self.command(kind, ready=False)
            self.assertIn("--silent", command)
            self.assertIn("--no-audio-processing", command)

    def test_audio_probe_timeout_is_bounded_and_no_auto_start(self):
        with patch.object(audio.shutil, "which", return_value="/test/bin"), patch.object(audio.subprocess, "run", side_effect=subprocess.TimeoutExpired("pactl", 1.5)) as run:
            self.assertFalse(audio.available())
            self.assertEqual(run.call_args.kwargs["timeout"], 1.5)
            self.assertEqual(run.call_args.kwargs["env"]["PULSE_SERVER"], audio.environment()["PULSE_SERVER"])

    def test_web_volume_controls_only_owned_process_group_once(self):
        streams = [{"index": index, "properties": {"application.process.id": str(pid)}} for index, pid in ((1, 111), (2, 222), (3, 333))]
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps(streams) if "list" in command else "")
        with patch.object(audio.subprocess, "run", side_effect=run) as calls, patch.object(audio.os, "getpgid", side_effect=lambda pid: 999 if pid in (111, 333) else 222):
            applied = audio.sync_streams(999, {"muted": True, "volume": 35})
            audio.sync_streams(999, {"muted": True, "volume": 35}, applied=applied)
        mutations = [call.args[0] for call in calls.call_args_list if "list" not in call.args[0]]
        self.assertEqual({cmd[2] for cmd in mutations}, {"1", "3"})
        self.assertEqual(len(mutations), 4)
        self.assertIn(["pactl", "set-sink-input-volume", "1", "35%"], mutations)

    def test_old_settings_gain_audio_defaults_without_losing_wallpaper(self):
        wallpaper.save_settings({"roots": [str(self.root)], "selection": {"path": str(self.root), "mode": "live"}})
        settings = wallpaper.load_settings()
        self.assertEqual(settings["audio"], audio.DEFAULTS)
        self.assertEqual(settings["selection"]["path"], str(self.root))

    def test_availability_change_restarts_live_selection_and_rolls_back_failure(self):
        wallpaper.save_settings(dict(wallpaper.load_settings(), selection={"path": str(self.root), "mode": "live"}))
        before = wallpaper.load_settings()
        record = {"audio_available": False, "renderer": {"pid": 999}}
        with patch.object(audio, "current_renderer", return_value=record), patch.object(audio, "available", return_value=True), \
                patch.object(wallpaper, "restart_renderer", side_effect=[OSError("failure"), None]) as restart, self.assertRaises(OSError):
            wallpaper.set_audio({"muted": True, "volume": 25})
        self.assertEqual(restart.call_count, 2)
        self.assertEqual(wallpaper.load_settings(), before)

    def test_live_mute_changes_only_mute_and_never_restarts_renderer(self):
        wallpaper.save_settings(dict(wallpaper.load_settings(), selection={"path": str(self.root), "mode": "live"}))
        record = {"audio_available": True, "renderer": {"pid": 999}}
        with patch.object(audio, "current_renderer", return_value=record), patch.object(audio, "available", return_value=True), \
                patch.object(audio, "sync_streams", return_value={7}) as sync, patch.object(wallpaper, "restart_renderer") as restart:
            result = wallpaper.set_audio({"muted": True, "volume": 50})
        restart.assert_not_called()
        sync.assert_called_once_with(999, {"muted": True, "volume": 50}, fields={"muted"}, strict=True)
        self.assertFalse(result["restarted"])

    def test_live_volume_change_and_unchanged_settings_do_not_restart(self):
        wallpaper.save_settings(dict(wallpaper.load_settings(), selection={"path": str(self.root), "mode": "live"}))
        record = {"audio_available": True, "renderer": {"pid": 999}}
        with patch.object(audio, "current_renderer", return_value=record), patch.object(audio, "available", return_value=True), \
                patch.object(audio, "sync_streams", return_value=set()) as sync, patch.object(wallpaper, "restart_renderer") as restart:
            wallpaper.set_audio({"muted": False, "volume": 25})
            self.assertEqual(sync.call_args.kwargs["fields"], {"volume"})
            wallpaper.set_audio({"muted": False, "volume": 25})
            self.assertEqual(sync.call_args.kwargs["fields"], set())
        restart.assert_not_called()

    def test_stream_mute_does_not_write_volume_and_reused_streams_are_initialized(self):
        streams = [{"index": 7, "properties": {"application.process.id": "111", "object.serial": "1"}}]
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps(streams) if "list" in command else "")
        with patch.object(audio.subprocess, "run", side_effect=run) as calls, patch.object(audio.os, "getpgid", return_value=999):
            audio.sync_streams(999, {"muted": True, "volume": 50}, fields={"muted"})
            self.assertEqual([c.args[0][1] for c in calls.call_args_list], ["--format=json", "set-sink-input-mute"])
            applied = audio.sync_streams(999, audio.DEFAULTS)
            calls.reset_mock()
            streams[0]["properties"]["object.serial"] = "2"
            audio.sync_streams(999, audio.DEFAULTS, applied=applied)
            self.assertEqual(len(calls.call_args_list), 3)

    def test_missing_or_stale_renderer_record_never_restarts_another_service(self):
        wallpaper.save_settings(dict(wallpaper.load_settings(), selection={"path": str(self.root), "mode": "live"}))
        with patch.object(audio, "available", return_value=True), patch.object(wallpaper, "restart_renderer") as restart:
            wallpaper.set_audio({"muted": True, "volume": 50})
        restart.assert_not_called()

    def test_renderer_record_rejects_pid_reuse_foreign_group_and_changed_selection(self):
        selection = {"path": str(self.root), "mode": "live"}
        supervisor = {"pid": 101, "start": 1, "parent": 99}
        renderer = {"pid": 102, "start": 2, "parent": 101}
        record = dict(selection=selection, kind="video", audio_available=True,
                      supervisor=supervisor, renderer=renderer)
        audio.runtime_path().parent.mkdir()
        audio.runtime_path().write_text(json.dumps(record))
        identities = {101: supervisor, 102: renderer}
        with patch.object(audio, "process_identity", side_effect=lambda pid: identities[pid]), \
                patch.object(audio.os, "getpgid", return_value=102) as group, \
                patch.object(Path, "read_bytes", return_value=os.fsencode(Path(audio.__file__).with_name("wallpaper.py")) + b"\0run\0"):
            self.assertEqual(audio.current_renderer(selection), record)
            self.assertIsNone(audio.current_renderer(dict(selection, path="other")))
            identities[102] = dict(renderer, start=999)
            self.assertIsNone(audio.current_renderer(selection))
            identities[102] = renderer
            group.return_value = 500
            self.assertIsNone(audio.current_renderer(selection))

    def test_supervisor_only_initializes_new_streams_after_preferences_change(self):
        first = wallpaper.load_settings()
        latest = dict(first, audio={"muted":True,"volume":25})
        from unittest.mock import MagicMock
        supervisor = MagicMock(record={"audio_available":True},renderer=MagicMock(pid=102,poll=lambda:None),applied=set())
        supervisor.finished.return_value = False
        server = MagicMock(); server.poll.side_effect = [False,False,SystemExit(0)]
        with patch.object(wallpaper,"load_settings",side_effect=[first,first,latest]), \
             patch.object(wallpaper,"PlaylistRenderer",return_value=supervisor), \
             patch.object(wallpaper.wallpaper_remote,"Server",return_value=server), \
             patch.object(wallpaper.time,"sleep"), \
             patch.object(audio,"sync_streams",side_effect=lambda pid,value,**kwargs:kwargs["applied"]) as sync:
            with self.assertRaises(SystemExit):wallpaper.run_playlist()
        self.assertEqual(sync.call_count,2)
        self.assertTrue(all("applied" in call.kwargs and "fields" not in call.kwargs for call in sync.call_args_list))
        supervisor.close.assert_called_once()

    def test_static_selection_never_restarts_renderer_when_saving_audio(self):
        with patch.object(wallpaper, "restart_renderer") as restart, patch.object(audio, "available", return_value=False):
            result = wallpaper.set_audio({"muted": True, "volume": 25})
        restart.assert_not_called()
        self.assertFalse(result["available"])
        self.assertEqual(wallpaper.load_settings()["audio"], {"muted": True, "volume": 25})

    def test_invalid_values_rejected(self):
        for value in ({"volume": True}, {"volume": -1}, {"volume": 101}, {"muted": "false"}, {"key": "value"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audio.validate(value)

    def test_malformed_foreign_streams_do_not_hide_later_owned_stream(self):
        streams = [{"properties": None}, {"index": 1, "properties": {"application.process.id": "invalid"}},
                   {"index": 7, "properties": {"application.process.id": "111"}}]
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, json.dumps(streams) if "list" in command else "")
        with patch.object(audio.subprocess, "run", side_effect=run) as calls, patch.object(audio.os, "getpgid", return_value=999):
            self.assertEqual(len(audio.sync_streams(999, audio.DEFAULTS)), 1)
        self.assertEqual(len(calls.call_args_list), 3)

    def test_failed_explicit_audio_update_restores_preferences_without_restart(self):
        wallpaper.save_settings(dict(wallpaper.load_settings(), selection={"path": str(self.root), "mode": "live"}))
        before = wallpaper.load_settings()
        record = {"audio_available": True, "renderer": {"pid": 999}}
        with patch.object(audio, "available", return_value=True), patch.object(audio, "current_renderer", return_value=record), \
                patch.object(audio, "sync_streams", side_effect=RuntimeError("audio failed")), \
                patch.object(wallpaper, "restart_renderer") as restart, self.assertRaisesRegex(RuntimeError, "audio failed"):
            wallpaper.set_audio({"muted": True, "volume": 25})
        self.assertEqual(wallpaper.load_settings(), before)
        restart.assert_not_called()

    def test_partial_failure_restores_actual_channel_volumes_and_external_mute(self):
        streams = [{"index": 7, "mute": True, "volume": {"left": {"value": 12000}, "right": {"value": 24000}},
                    "properties": {"application.process.id": "111", "object.serial": "123"}}]
        mutations = []
        def run(command, **kwargs):
            if "list" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps(streams))
            mutations.append(command)
            if command[1] == "set-sink-input-mute" and command[-1] == "0":
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0, "")
        with patch.object(audio.subprocess, "run", side_effect=run), patch.object(audio.os, "getpgid", return_value=999), \
                self.assertRaisesRegex(RuntimeError, "not applied"):
            audio.sync_streams(999, audio.DEFAULTS, strict=True)
        self.assertEqual(mutations[-2:], [["pactl", "set-sink-input-mute", "7", "1"],
                                         ["pactl", "set-sink-input-volume", "7", "12000", "24000"]])

    def test_failure_recovery_does_not_touch_reused_stream_identity(self):
        stream = {"index": 7, "mute": False, "properties": {"application.process.id": "111", "object.serial": "123"}}
        mutations = []
        def run(command, **kwargs):
            if "list" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps([stream]))
            mutations.append(command)
            stream["properties"]["object.serial"] = "456"
            raise subprocess.CalledProcessError(1, command)
        with patch.object(audio.subprocess, "run", side_effect=run), patch.object(audio.os, "getpgid", return_value=999), self.assertRaises(RuntimeError):
            audio.sync_streams(999, {"muted": True, "volume": 50}, fields={"muted"}, strict=True)
        self.assertEqual(len(mutations), 1)
