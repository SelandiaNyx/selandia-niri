"""Player identity, metadata and capability regression tests; no live bus used."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("media_backend", Path(__file__).resolve().parents[1] / "niri/shell/media_backend.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)

PROPERTIES = {"PlaybackStatus": "Playing", "CanControl": True, "CanPlay": True, "CanPause": True,
              "CanGoNext": False, "CanGoPrevious": False,
              "Metadata": {"xesam:title": "Only track · 单曲", "xesam:artist": ["Artist", "歌手"],
                           "xesam:album": "Album", "mpris:artUrl": "file:///tmp/example-cover.png"}}


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.one = media.PREFIX + "chromium.instance12"
        self.two = media.PREFIX + "plasma-browser-integration"
        self.owners = {self.one: ":1.21", self.two: ":1.22"}
        self.properties = {":1.21": copy.deepcopy(PROPERTIES), ":1.22": {**copy.deepcopy(PROPERTIES), "PlaybackStatus": "Paused"}}
        self.identities = {":1.21": "Chrome", ":1.22": "Google Chrome"}
        self.actions = []
        self.names = [self.one, self.two, "org.unrelated.Service"]
        self.connection = object()
        self.connection_patch = patch.object(media, "_connection", return_value=self.connection)
        self.call_patch = patch.object(media, "_call", side_effect=self.call)
        self.connection_patch.start()
        self.call_mock = self.call_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.addCleanup(self.call_patch.stop)

    def call(self, connection, destination, interface, method, parameters=None, reply="()", path=media.PATH):
        self.assertIs(connection, self.connection)
        args = parameters.unpack() if parameters is not None else ()
        if interface == media.BUS_NAME:
            if method == "ListNames":
                return (list(self.names),)
            if method == "GetNameOwner":
                try:
                    return (self.owners[args[0]],)
                except KeyError as error:
                    raise RuntimeError("Name has no owner") from error
        if interface == media.PROPERTIES and method == "GetAll":
            if args == (media.ROOT_INTERFACE,):
                return ({"Identity": self.identities[destination]},)
            return (copy.deepcopy(self.properties[destination]),)
        if interface == media.PLAYER_INTERFACE:
            self.actions.append((destination, method))
            if method in ("Play", "Pause"):
                self.properties[destination]["PlaybackStatus"] = {"Play": "Playing", "Pause": "Paused"}[method]
            return ()
        self.fail(f"Unexpected D-Bus operation: {(destination, interface, method, args)}")

    def identifier(self, name=None):
        name = name or self.one
        return f"{name}|{self.owners[name]}"

    def test_single_track_still_exposes_pause_without_next_or_previous(self):
        selected = media.read_state()["selected"]
        self.assertTrue(selected["can_pause"])
        self.assertTrue(selected["can_play"])
        self.assertFalse(selected["can_next"])
        self.assertFalse(selected["can_previous"])
        current = media.action(selected["id"], "pause")
        self.assertEqual(current["status"], "Paused")
        self.assertEqual(self.actions, [(":1.21", "Pause")])

    def test_active_browser_wins_over_paused_bridge_and_metadata_stays_together(self):
        self.properties[":1.22"]["Metadata"]["xesam:title"] = "Other bridge title"
        state = media.read_state()
        self.assertEqual(state["selected_id"], self.identifier())
        self.assertEqual(state["selected"]["title"], "Only track · 单曲")
        self.assertEqual(state["selected"]["artist"], "Artist · 歌手")
        self.assertEqual(state["selected"]["status"], "Playing")
        self.assertEqual(state["selected"]["album"], "Album")
        self.assertEqual(self.actions, [])

    def test_user_selection_is_honored_even_when_another_player_is_playing(self):
        selected = media.read_state(self.identifier(self.two))["selected"]
        self.assertEqual(selected["bus_name"], self.two)
        self.assertEqual(selected["status"], "Paused")
        media.action(selected["id"], "play")
        self.assertEqual(self.actions, [(":1.22", "Play")])

    def test_explicit_play_and_pause_are_idempotent_and_never_toggle(self):
        for requested in ("pause", "pause", "play", "play"):
            media.action(self.identifier(), requested)
        self.assertEqual([method for _, method in self.actions], ["Pause", "Pause", "Play", "Play"])

    def test_can_play_and_can_pause_are_independent(self):
        self.properties[":1.21"]["CanPlay"] = False
        self.assertTrue(media.read_state()["selected"]["can_pause"])
        media.action(self.identifier(), "pause")
        with self.assertRaisesRegex(RuntimeError, "does not support"):
            media.action(self.identifier(), "play")
        self.assertEqual(self.actions, [(":1.21", "Pause")])

    def test_unsupported_navigation_does_not_issue_a_command(self):
        for requested in ("next", "previous"):
            with self.assertRaisesRegex(RuntimeError, "does not support"):
                media.action(self.identifier(), requested)
        self.assertEqual(self.actions, [])
        self.assertTrue(media.read_state()["selected"]["can_pause"])

    def test_supported_navigation_calls_only_the_selected_player(self):
        self.properties[":1.22"].update(CanGoNext=True, CanGoPrevious=True)
        media.action(self.identifier(self.two), "next")
        media.action(self.identifier(self.two), "previous")
        self.assertEqual(self.actions, [(":1.22", "Next"), (":1.22", "Previous")])

    def test_capabilities_refresh_before_action(self):
        player = media.read_state()["selected"]
        self.assertTrue(player["can_pause"])
        self.properties[":1.21"]["CanPause"] = False
        with self.assertRaisesRegex(RuntimeError, "does not support"):
            media.action(player["id"], "pause")
        self.assertEqual(self.actions, [])

    def test_can_control_false_overrides_other_reported_capabilities(self):
        self.properties[":1.21"]["CanControl"] = False
        player = next(player for player in media.read_state()["players"] if player["bus_name"] == self.one)
        for name in ("can_control", "can_play", "can_pause", "can_next", "can_previous"):
            self.assertFalse(player[name])
        with self.assertRaises(RuntimeError):
            media.action(player["id"], "pause")
        self.assertEqual(self.actions, [])

    def test_stale_id_cannot_control_a_restarted_instance(self):
        identifier = self.identifier()
        self.owners[self.one] = ":1.99"
        with self.assertRaisesRegex(RuntimeError, "restarted"):
            media.action(identifier, "pause")
        self.assertEqual(self.actions, [])

    def test_disappearing_player_cannot_control_the_remaining_player(self):
        identifier = self.identifier()
        self.names.remove(self.one)
        del self.owners[self.one]
        state = media.read_state(identifier)
        self.assertEqual(state["selected_id"], self.identifier(self.two))
        with self.assertRaises(RuntimeError):
            media.action(identifier, "pause")
        self.assertEqual(self.actions, [])

    def test_reassignment_during_metadata_read_is_rejected(self):
        original = self.call
        def reassigned(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[1:4] == (":1.21", media.PROPERTIES, "GetAll"):
                self.owners[self.one] = ":1.99"
            return result
        self.call_mock.side_effect = reassigned
        with self.assertRaisesRegex(RuntimeError, "restarted"):
            media.action(self.identifier(), "pause")
        self.assertEqual(self.actions, [])

    def test_player_errors_do_not_hide_healthy_players(self):
        with patch.object(media, "_read_player", side_effect=lambda connection, name: (_ for _ in ()).throw(RuntimeError("Gone")) if name == self.one else media._snapshot(name, ":1.22", self.properties[":1.22"], "Other")):
            state = media.read_state()
        self.assertEqual(len(state["players"]), 1)
        self.assertEqual(state["selected_id"], self.identifier(self.two))
        self.assertIn("Gone", state["errors"][0]["error"])

    def test_empty_state_is_distinct_from_bus_failure(self):
        self.names = []
        self.assertEqual(media.read_state(), {"players": [], "selected_id": None, "selected": None, "errors": []})
        self.call_mock.side_effect = RuntimeError("Bus disconnected")
        with self.assertRaisesRegex(RuntimeError, "Bus disconnected"):
            media.read_state()

    def test_playerctld_proxy_is_hidden_when_real_players_exist(self):
        self.names.append(media.PREFIX + "playerctld")
        state = media.read_state()
        self.assertEqual(len(state["players"]), 2)
        self.assertEqual(state["errors"], [])

    def test_malformed_or_legacy_metadata_is_handled_without_fetching_artwork(self):
        self.properties[":1.21"]["Metadata"] = {"xesam:title": "A\x00title", "xesam:artist": "One artist", "mpris:artUrl": {"bad": "value"}}
        player = media.read_state()["selected"]
        self.assertEqual(player["title"], "Atitle")
        self.assertEqual(player["artist"], "One artist")
        self.assertEqual(player["art_url"], "")
        self.properties[":1.21"]["Metadata"] = "not-a-dictionary"
        self.assertEqual(media.read_state()["selected"]["title"], "")

    def test_missing_capabilities_are_not_treated_as_supported(self):
        player = media._snapshot(self.one, ":1.21", {"PlaybackStatus": "playing"}, "")
        self.assertEqual(player["status"], "Playing")
        self.assertEqual(player["identity"], "chromium.instance12")
        self.assertFalse(player["can_control"])
        self.assertFalse(player["can_pause"])

    def test_no_root_identity_still_allows_a_working_browser_interface(self):
        original = self.call
        def no_root(*args, **kwargs):
            if len(args) > 4 and args[4] is not None and args[4].unpack() == (media.ROOT_INTERFACE,):
                raise RuntimeError("Root missing")
            return original(*args, **kwargs)
        self.call_mock.side_effect = no_root
        self.assertEqual(media.read_state()["selected"]["identity"], "chromium.instance12")
        media.action(self.identifier(), "pause")
        self.assertEqual(self.actions, [(":1.21", "Pause")])

    def test_unknown_or_injected_ids_and_actions_never_touch_bus(self):
        for identifier in (None, self.one, "bad|:1.21", self.one + "|not-owner", self.one + "|:1.21|extra"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                media.action(identifier, "pause")
        for requested in ("play-pause", "Stop", "Quit", ["pause"], None):
            with self.subTest(requested=requested), self.assertRaises(ValueError):
                media.action(self.identifier(), requested)
        self.call_mock.assert_not_called()

    def test_acknowledged_but_unchanged_status_is_not_reported_as_paused(self):
        original = self.call
        def ignored(*args, **kwargs):
            if args[2:4] == (media.PLAYER_INTERFACE, "Pause"):
                self.actions.append((args[1], "Pause"))
                return ()
            return original(*args, **kwargs)
        self.call_mock.side_effect = ignored
        clock = [0.]
        def advance(seconds):
            clock[0] += seconds
        with patch.object(media.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(media.time, "sleep", side_effect=advance):
            state = media.action(self.identifier(), "pause")
        self.assertGreaterEqual(clock[0], .6)
        self.assertLess(clock[0], .7)
        self.assertEqual(state["status"], "Playing")
        self.assertTrue(state["action_pending"])
        self.assertEqual(self.actions, [(":1.21", "Pause")])

    def test_low_level_calls_never_autostart_players_and_have_bounded_timeout(self):
        self.call_patch.stop()
        connection = MagicMock()
        connection.call_sync.return_value = media.GLib.Variant("()", ())
        self.assertEqual(media._call(connection, ":1.21", media.PLAYER_INTERFACE, "Pause"), ())
        args = connection.call_sync.call_args.args
        self.assertEqual(args[0], ":1.21")
        self.assertEqual(args[5].dup_string(), "()")
        self.assertEqual(args[6], media.Gio.DBusCallFlags.NO_AUTO_START)
        self.assertEqual(args[7], media.TIMEOUT_MS)

    def test_low_level_glib_errors_are_readable(self):
        self.call_patch.stop()
        connection = MagicMock()
        connection.call_sync.side_effect = media.GLib.Error("Disconnected")
        with self.assertRaisesRegex(RuntimeError, "Disconnected"):
            media._call(connection, ":1.21", media.PLAYER_INTERFACE, "Pause")


if __name__ == "__main__":
    unittest.main()
