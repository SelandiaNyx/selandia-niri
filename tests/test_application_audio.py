"""Stream identity and independent playback/recording controls; no audio server."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import audio_backend as audio


def fixture(index=7, serial="100"):
    return {"index": index, "client": 3, "properties": {"application.name": "Player", "object.serial": serial,
            "application.process.id": "123", "media.name": "Track"}, "volume": {"mono": {"value_percent": "70%"}},
            "mute": False, "has_volume": True, "volume_writable": True}


class ApplicationAudioTests(unittest.TestCase):
    def test_state_includes_separate_playback_and_recording_without_mutations(self):
        values = {"sinks": [], "sources": [], "cards": [], "sink-inputs": [fixture()], "source-outputs": [fixture(8)]}
        with patch.object(audio, "_list", side_effect=lambda kind: values[kind]), patch.object(audio, "_run", return_value="") as run:
            state = audio.read_state()
        self.assertEqual([(s["kind"], s["index"], s["name"], s["volume"]) for s in state["streams"]],
                         [("sink-input", 7, "Player", 70), ("source-output", 8, "Player", 70)])
        self.assertTrue(all(call.args[0].startswith("get-default-") for call in run.call_args_list))

    def test_stream_listing_failure_preserves_device_inventory_and_reports_error(self):
        def listing(kind):
            if kind == "sink-inputs":
                raise RuntimeError("Playback unavailable")
            return []
        with patch.object(audio, "_list", side_effect=listing), patch.object(audio, "_run", return_value=""):
            state = audio.read_state()
        self.assertEqual(state["stream_errors"], ["Playback unavailable"])
        self.assertEqual(state["sinks"], [])

    def test_each_stream_type_uses_only_its_own_volume_and_mute_commands(self):
        for kind in ("sink-input", "source-output"):
            raw = fixture()
            with patch.object(audio, "_list", return_value=[raw]), patch.object(audio, "_run") as run:
                audio.set_stream_audio(audio._stream(raw, kind), volume=25, muted=True)
            self.assertEqual([call.args for call in run.call_args_list],
                             [(f"set-{kind}-volume", "7", "25%"), (f"set-{kind}-mute", "7", "1")])

    def test_mute_alone_does_not_reset_mixer_volume(self):
        raw = fixture()
        with patch.object(audio, "_list", return_value=[raw]), patch.object(audio, "_run") as run:
            audio.set_stream_audio(audio._stream(raw, "sink-input"), muted=True)
        run.assert_called_once_with("set-sink-input-mute", "7", "1")

    def test_disappeared_or_reused_id_is_never_controlled(self):
        stream = audio._stream(fixture(), "sink-input")
        for current in ([], [fixture(serial="101")], [dict(fixture(), client=4)]):
            with patch.object(audio, "_list", return_value=current), patch.object(audio, "_run") as run:
                with self.assertRaises(RuntimeError):
                    audio.set_stream_audio(stream, volume=30)
            run.assert_not_called()

    def test_unknown_volume_is_unavailable_and_recording_mute_still_works(self):
        raw = dict(fixture(), volume=None)
        stream = audio._stream(raw, "source-output")
        self.assertIsNone(stream["volume"])
        with patch.object(audio, "_list", return_value=[raw]), patch.object(audio, "_run") as run:
            with self.assertRaises(RuntimeError):
                audio.set_stream_audio(stream, volume=40)
            audio.set_stream_audio(stream, muted=True)
        run.assert_called_once_with("set-source-output-mute", "7", "1")

    def test_invalid_identifiers_and_values_never_run_commands(self):
        for index in (-1, True, "7", "--help"):
            self.assertIsNone(audio._stream(fixture(index), "sink-input"))
        for values in (dict(volume=-1), dict(volume=101), dict(volume=float("nan")), dict(muted="false")):
            with patch.object(audio, "_run") as run, self.assertRaises(ValueError):
                audio.set_stream_audio(audio._stream(fixture(), "sink-input"), **values)
            run.assert_not_called()
