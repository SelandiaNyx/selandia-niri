"""Audio parsing/routing regression checks. No live audio server is changed."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))

spec = importlib.util.spec_from_file_location("audio_backend", Path(__file__).resolve().parents[1] / "niri/shell/audio_backend.py")
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class AudioTests(unittest.TestCase):
    def read_fixture(self, sinks=(), sources=(), cards=(), default_sink="", default_source="", advanced=False):
        data = {"sinks": list(sinks), "sources": list(sources), "cards": list(cards)}
        defaults = {"get-default-sink": default_sink, "get-default-source": default_source}
        with patch.object(audio, "_list", side_effect=lambda kind: data.get(kind, [])), \
                patch.object(audio, "_run", side_effect=lambda command: defaults[command]) as run:
            state = audio.read_state(include_unavailable=advanced)
        self.assertEqual({call.args[0] for call in run.call_args_list}, set(defaults))
        return state

    def test_missing_localized_descriptions_have_readable_fallbacks(self):
        self.assertEqual(audio._description({"name": "analog-output-headphones", "description": "(null)"}), "Headphones · 耳机")
        self.assertIn("Analog stereo", audio._description({"name": "output:analog-stereo+input:analog-stereo"}))
        self.assertEqual(audio._description({"name": "vendor.device", "description": "USB speakers"}), "USB speakers")
    def test_volume_averages_channels_and_distinguishes_missing_data(self):
        self.assertEqual(audio._volume({"left": {"value_percent": "25%"}, "right": {"value_percent": "75%"}}), 50)
        self.assertEqual(audio._volume({"mono": {"value": 32768}}), 50)
        self.assertEqual(audio._volume({"mono": {"value_percent": "0%"}}), 0)
        self.assertIsNone(audio._volume({"mono": {"value_percent": "NaN"}}))
        self.assertIsNone(audio._volume(None))

    def test_profile_and_port_schema_variants_preserve_availability(self):
        choices = audio._choices({"analog": {"description": "Speaker", "available": True},
                                  "hdmi": {"description": "HDMI", "available": False}})
        self.assertTrue(choices[0]["available"])
        self.assertFalse(choices[1]["available"])
        choices = audio._choices([{"name": "headphones", "availability": "not available"},
                                  {"name": "line-out", "availability": "availability unknown"}])
        self.assertFalse(choices[0]["available"])
        self.assertTrue(choices[1]["available"])

    def test_monitor_detection_keeps_real_microphones(self):
        for item in ({"monitor_of_sink": 0}, {"name": "speaker.monitor"}, {"properties": {"device.class": "monitor"}}):
            self.assertTrue(audio._is_monitor(item))
        for value in (None, "n/a", 4294967295, "4294967295"):
            self.assertFalse(audio._is_monitor({"name": "microphone", "monitor_of_sink": value}))

    def test_read_state_supports_hotplug_without_default_and_filters_monitors(self):
        data = {
            "sinks": [{"name": "speaker", "description": "扬声器", "volume": {"mono": {"value_percent": "40%"}},
                       "ports": {"line-out": {"description": "Line out"}}, "active_port": "line-out", "mute": True}],
            "sources": [{"name": "microphone", "monitor_of_sink": 4294967295}, {"name": "speaker.monitor"}],
            "cards": [{"name": "card", "active_profile": {"name": "stereo"},
                       "profiles": {"stereo": {"description": "Stereo", "available": True}}}],
        }
        def run(*args):
            if args[0] == "get-default-sink":
                return "speaker"
            if args[0] == "get-default-source":
                raise RuntimeError("No default")
            self.fail(f"Unexpected command {args}")
        with patch.object(audio, "_list", side_effect=lambda name: data.get(name, [])), patch.object(audio, "_run", side_effect=run):
            state = audio.read_state()
        self.assertEqual(state["default_source"], "")
        self.assertEqual(state["default_sink"], "speaker")
        self.assertEqual([item["name"] for item in state["sources"]], ["microphone"])
        self.assertEqual(state["sinks"][0]["description"], "扬声器")
        self.assertTrue(state["sinks"][0]["mute"])
        self.assertEqual(state["cards"][0]["active_profile"], "stereo")

    def test_disconnected_ports_hidden_without_conflating_idle_and_disconnected(self):
        sinks = [
            {"name": "idle-headset", "state": "SUSPENDED", "active_port": "headphones",
             "ports": [{"name": "headphones", "availability": "availability unknown"}]},
            {"name": "unplugged-hdmi", "active_port": "hdmi", "ports": [{"name": "hdmi", "availability": "not available"}]},
            {"name": "speakers", "state": "SUSPENDED", "active_port": "speakers",
             "ports": [{"name": "speakers", "availability": "available"}, {"name": "headphones", "availability": "not available"}]},
            {"name": "no-jack-detection", "state": "SUSPENDED", "ports": []},
        ]
        state = self.read_fixture(sinks=sinks)
        self.assertEqual([sink["name"] for sink in state["sinks"]], ["idle-headset", "speakers", "no-jack-detection"])
        self.assertEqual(state["hidden_counts"]["sinks"], 1)
        self.assertEqual(state["sinks"][0]["availability"], "unknown")
        self.assertTrue(state["sinks"][0]["available"])

    def test_unavailable_default_stays_visible_with_honest_status(self):
        sink = {"name": "default-hdmi", "active_port": {"name": "hdmi"},
                "ports": {"hdmi": {"available": False}}}
        state = self.read_fixture(sinks=[sink], default_sink=sink["name"])
        self.assertEqual(len(state["sinks"]), 1)
        self.assertTrue(state["sinks"][0]["is_default"])
        self.assertFalse(state["sinks"][0]["available"])
        self.assertIn("disconnected", state["sinks"][0]["reason"])

    def test_all_ports_disconnected_is_hidden_but_mixed_unknown_is_retained(self):
        state = self.read_fixture(sinks=[
            {"name": "all-unplugged", "ports": {"one": {"available": False}, "two": {"available": False}}},
            {"name": "maybe-present", "ports": {"one": {"available": False}, "two": {}}},
        ])
        self.assertEqual([sink["name"] for sink in state["sinks"]], ["maybe-present"])
        self.assertEqual(state["sinks"][0]["availability"], "unknown")

    def test_pro_audio_raw_inventory_is_advanced_not_falsely_called_disconnected(self):
        sinks = [{"name": f"pro-{index}", "state": "SUSPENDED", "ports": [],
                  "properties": {"device.profile.pro": "true", "node.nick": label,
                                 "alsa.device": str(index), "device.name": "card"}}
                 for index, label in ((0, "USB headset"), (1, "USB Audio #1"), (3, "HDMI 0"))]
        normal = self.read_fixture(sinks=sinks, default_sink="pro-0")
        advanced = self.read_fixture(sinks=sinks, default_sink="pro-0", advanced=True)
        self.assertEqual([sink["name"] for sink in normal["sinks"]], ["pro-0"])
        self.assertEqual(normal["hidden_counts"]["sinks"], 2)
        self.assertEqual(advanced["hidden_counts"], normal["hidden_counts"])
        self.assertEqual(len(advanced["sinks"]), 3)
        self.assertEqual(normal["sinks"][0]["description"], "USB headset · PCM 0")
        for device in advanced["sinks"]:
            self.assertTrue(device["available"])
            self.assertEqual(device["availability"], "unknown")
            self.assertEqual(device["kind"], "pro")

    def test_running_pro_endpoints_stay_visible_but_running_monitors_do_not(self):
        sink = {"name": "studio-output", "state": "RUNNING", "properties": {"device.profile.pro": True}}
        source = {"name": "studio-output.monitor", "state": "RUNNING"}
        state = self.read_fixture(sinks=[sink], sources=[source])
        self.assertEqual(len(state["sinks"]), 1)
        self.assertEqual(state["sources"], [])
        advanced = self.read_fixture(sinks=[sink], sources=[source], advanced=True)
        self.assertEqual(advanced["sources"][0]["kind"], "monitor")
        self.assertIn("not a microphone", advanced["sources"][0]["reason"])

    def test_virtual_routes_available_in_advanced_and_defaults_always_preserved(self):
        sinks = [{"name": "effects", "properties": {"device.class": "filter"}},
                 {"name": "loopback", "properties": {"node.virtual": "true"}},
                 {"name": "auto_null"}]
        normal = self.read_fixture(sinks=sinks, default_sink="effects")
        self.assertEqual([sink["name"] for sink in normal["sinks"]], ["effects"])
        self.assertEqual(normal["sinks"][0]["kind"], "virtual")
        advanced = self.read_fixture(sinks=sinks, advanced=True)
        self.assertTrue(all(sink["kind"] == "virtual" for sink in advanced["sinks"]))
        self.assertEqual(len(advanced["sinks"]), 3)
        source = {"name": "chosen.monitor", "properties": {"device.class": "monitor"}}
        state = self.read_fixture(sources=[source], default_source=source["name"])
        self.assertEqual(len(state["sources"]), 1)
        self.assertTrue(state["sources"][0]["is_default"])

    def test_profile_recommendation_uses_available_normal_priority_and_never_mutates(self):
        card = {"name": "usb", "active_profile": "pro-audio", "profiles": {
            "off": {"priority": 999999, "available": True},
            "pro-audio": {"priority": 999998, "available": True},
            "output:hdmi-stereo": {"priority": 999997, "available": False},
            "output:analog-stereo": {"priority": 6500, "available": True},
            "output:analog-stereo+input:analog-stereo": {"priority": 6565, "available": True},
        }}
        state = self.read_fixture(cards=[card])
        self.assertEqual(state["cards"][0]["recommended_profile"], "output:analog-stereo+input:analog-stereo")
        self.assertIn("Analog stereo", state["cards"][0]["recommended_description"])
        self.assertEqual(state["pro_audio_cards"], state["cards"])
        self.assertEqual(card["active_profile"], "pro-audio")

    def test_no_normal_available_profile_does_not_invent_a_recommendation(self):
        state = self.read_fixture(cards=[{"name": "studio", "active_profile": "pro-audio",
                                         "profiles": [{"name": "pro-audio", "available": True}]}])
        self.assertEqual(state["cards"][0]["recommended_profile"], "")
        self.assertEqual(state["cards"][0]["recommended_description"], "")

    def test_unavailable_service_raises_instead_of_showing_empty_success(self):
        with patch.object(audio, "_list", side_effect=RuntimeError("No service")), patch.object(audio, "_run", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "No service"):
                audio.read_state()

    def test_invalid_json_rejected(self):
        for data in ("not-json", "{}", '["invalid"]'):
            with patch.object(audio, "_run", return_value=data):
                with self.assertRaises(RuntimeError):
                    audio._list("sinks")

    def test_actions_use_device_ids_as_arguments(self):
        name = "speaker with apostrophe's $(touch never)"
        with patch.object(audio, "_run") as run:
            audio.set_default("sink", name)
            run.assert_called_with("set-default-sink", name)
            audio.set_volume("source", "mic", 42.4)
            run.assert_called_with("set-source-volume", "mic", "42%")
            audio.set_mute("source", "mic", True)
            run.assert_called_with("set-source-mute", "mic", "1")
            audio.set_port("sink", name, "headphones")
            run.assert_called_with("set-sink-port", name, "headphones")
            audio.set_profile("card", "output:stereo+input:stereo")
            run.assert_called_with("set-card-profile", "card", "output:stereo+input:stereo")

    def test_invalid_actions_never_invoke_server(self):
        with patch.object(audio, "_run") as run:
            for kind, name in (("invalid", "sink"), ("sink", "--bad"), ("source", "bad\nname")):
                with self.assertRaises(ValueError):
                    audio.set_default(kind, name)
            for value in (-1, 101, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    audio.set_volume("sink", "speaker", value)
            with self.assertRaises(ValueError):
                audio.set_mute("sink", "speaker", "false")
            run.assert_not_called()

    def test_existing_streams_move_only_when_explicitly_requested(self):
        with patch.object(audio, "_list", return_value=[{"index": 12}, {"index": 18}]), patch.object(audio, "_run") as run:
            self.assertEqual(audio.move_streams("sink", "usb"), 2)
            self.assertEqual([call.args for call in run.call_args_list],
                             [("move-sink-input", "12", "usb"), ("move-sink-input", "18", "usb")])

    def test_partial_move_reports_failure_and_continues_other_streams(self):
        with patch.object(audio, "_list", return_value=[{"index": 1}, {"index": 2}]), \
                patch.object(audio, "_run", side_effect=[RuntimeError("Gone"), ""]) as run:
            with self.assertRaisesRegex(RuntimeError, "Moved 1 streams"):
                audio.move_streams("source", "mic")
            self.assertEqual(run.call_count, 2)

    def test_process_timeout_and_missing_binary_have_readable_errors(self):
        for failure in (FileNotFoundError("pactl"), subprocess.TimeoutExpired("pactl", 6)):
            with patch.object(audio.subprocess, "run", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "Audio service unavailable"):
                    audio._run("info")

    def test_process_uses_utf8_locale_and_preserves_error_details(self):
        with patch.object(audio.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "device unplugged")) as run:
            with self.assertRaisesRegex(RuntimeError, "device unplugged"):
                audio._run("get-default-sink")
            self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C.UTF-8")
            self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
