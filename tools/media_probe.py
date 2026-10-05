#!/usr/bin/env python3
"""Exercise real MPRIS calls against fake players on smoke.py's private bus.

The fake services have distinct D-Bus connections and one track each. Playback
changes affect Python dictionaries only; no host player or audio device is used.
"""
import os
from pathlib import Path
import signal
import sys
import threading
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))
import media_backend as backend

XML = """<node>
<interface name="org.mpris.MediaPlayer2">
  <property name="Identity" type="s" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
  <method name="Play"/><method name="Pause"/><method name="Next"/>
  <method name="Previous"/><method name="PlayPause"/>
  <property name="PlaybackStatus" type="s" access="read"/>
  <property name="CanControl" type="b" access="read"/>
  <property name="CanPlay" type="b" access="read"/>
  <property name="CanPause" type="b" access="read"/>
  <property name="CanGoNext" type="b" access="read"/>
  <property name="CanGoPrevious" type="b" access="read"/>
  <property name="Metadata" type="a{sv}" access="read"/>
</interface>
</node>"""


class FakePlayers:
    def __init__(self, single=False):
        self.ready = threading.Event()
        self.error = None
        self.calls = []
        self.entries = [
            {"name": backend.PREFIX + "SelandiaProbeActive", "identity": "Probe active browser", "status": "Playing"},
            {"name": backend.PREFIX + "SelandiaProbeBridge", "identity": "Probe paused bridge", "status": "Paused"},
        ]
        if single:
            self.entries = [{"name": backend.PREFIX + "SelandiaTest",
                             "identity": "Single-track test · 单曲测试", "status": "Playing"}]
        for entry in self.entries:
            entry["can_pause"] = True
            entry["can_next"] = False
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        context = GLib.MainContext.new()
        context.push_thread_default()
        self.loop = GLib.MainLoop.new(context, False)
        connections = []
        try:
            node = Gio.DBusNodeInfo.new_for_xml(XML)
            for entry in self.entries:
                connection = Gio.DBusConnection.new_for_address_sync(
                    os.environ["DBUS_SESSION_BUS_ADDRESS"],
                    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                    None, None)
                connections.append(connection)
                entry["connection"] = connection
                entry["owner"] = connection.get_unique_name()
                for interface in node.interfaces:
                    connection.register_object(backend.PATH, interface,
                                               lambda c, s, p, i, m, a, invocation, e=entry: self.method(e, m, invocation),
                                               lambda c, s, p, i, prop, e=entry: self.property(e, prop), None)
                response = connection.call_sync(backend.BUS_NAME, backend.BUS_PATH, backend.BUS_NAME,
                                                "RequestName", GLib.Variant("(su)", (entry["name"], 4)),
                                                GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NO_AUTO_START, 1200, None)
                if response.unpack() != (1,):
                    raise AssertionError("Cannot own the isolated probe player name")
            self.ready.set()
            self.loop.run()
        except BaseException as error:
            self.error = error
            self.ready.set()
        finally:
            for connection in connections:
                connection.close_sync(None)
            context.pop_thread_default()

    def method(self, entry, method, invocation):
        self.calls.append((entry["name"], method))
        if method == "Play":
            entry["status"] = "Playing"
        elif method == "Pause":
            if not entry["can_pause"]:
                invocation.return_dbus_error("org.mpris.MediaPlayer2.Error.NotSupported", "Pause unavailable")
                return
            entry["status"] = "Paused"
        elif method in ("Next", "Previous", "PlayPause"):
            invocation.return_dbus_error("org.mpris.MediaPlayer2.Error.NotSupported", "Unexpected method in a single-track test")
            return
        invocation.return_value(GLib.Variant("()", ()))

    @staticmethod
    def property(entry, prop):
        if prop == "Identity":
            return GLib.Variant("s", entry["identity"])
        if prop == "PlaybackStatus":
            return GLib.Variant("s", entry["status"])
        if prop == "Metadata":
            return GLib.Variant("a{sv}", {"xesam:title": GLib.Variant("s", "Single-track test · 单曲测试"),
                                          "xesam:artist": GLib.Variant("as", ["Probe artist", "测试歌手"]),
                                          "mpris:trackid": GLib.Variant("o", "/probe/only_track")})
        values = {"CanControl": True, "CanPlay": True, "CanPause": entry["can_pause"],
                  "CanGoNext": entry["can_next"], "CanGoPrevious": False}
        return GLib.Variant("b", values[prop])

    def start(self):
        self.thread.start()
        if not self.ready.wait(5):
            raise AssertionError("Fake MPRIS services did not start")
        if self.error:
            raise self.error

    def close(self):
        if hasattr(self, "loop"):
            self.loop.quit()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise AssertionError("Fake MPRIS services did not stop")


def check_private_bus():
    if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1":
        raise RuntimeError("Run this probe only on smoke.py's private D-Bus")
    # Refuse a bus with other MPRIS players, even if its caller set the guard.
    if backend.read_state()["players"]:
        raise RuntimeError("The media probe requires a private bus without real players")


def serve():
    """Keep one fake single-track service alive for actual panel screenshots."""
    check_private_bus()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    services = FakePlayers(single=True)
    services.start()
    print("READY fake single-track player · 单曲测试播放器已启动", flush=True)
    try:
        stopped.wait()
    finally:
        services.close()


def main():
    check_private_bus()
    services = FakePlayers()
    services.start()
    try:
        state = backend.read_state()
        active, bridge = services.entries
        active_id = f"{active['name']}|{active['owner']}"
        bridge_id = f"{bridge['name']}|{bridge['owner']}"
        assert state["selected_id"] == active_id, state
        player = state["selected"]
        assert player["can_pause"] and not player["can_next"] and not player["can_previous"]
        assert player["artist"] == "Probe artist · 测试歌手"
        assert backend.action(active_id, "pause")["status"] == "Paused"
        assert services.calls == [(active["name"], "Pause")]
        assert backend.action(active_id, "play")["status"] == "Playing"
        print("PASS media: actual MPRIS single-track Pause and Play without navigation capabilities")

        assert backend.read_state(bridge_id)["selected_id"] == bridge_id
        assert backend.action(bridge_id, "play")["status"] == "Playing"
        assert services.calls[-1] == (bridge["name"], "Play")
        assert active["status"] == "Playing"
        print("PASS media: explicit selection controls only the selected player instance")

        before = list(services.calls)
        for requested in ("next", "previous"):
            try:
                backend.action(active_id, requested)
                raise AssertionError("Unsupported navigation was accepted")
            except RuntimeError as error:
                assert "does not support" in str(error)
        active["can_pause"] = False
        try:
            backend.action(active_id, "pause")
            raise AssertionError("Stale pause capability was accepted")
        except RuntimeError as error:
            assert "does not support" in str(error)
        assert services.calls == before
        print("PASS media: capabilities refresh before commands; unsupported actions send no method")

        # Releasing a well-known name invalidates the displayed instance ID.
        active["connection"].call_sync(backend.BUS_NAME, backend.BUS_PATH, backend.BUS_NAME,
                                        "ReleaseName", GLib.Variant("(s)", (active["name"],)),
                                        GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NO_AUTO_START, 1200, None)
        try:
            backend.action(active_id, "play")
            raise AssertionError("Closed player identity was accepted")
        except RuntimeError:
            pass
        assert services.calls == before
        assert backend.read_state(active_id)["selected_id"] == bridge_id
        print("PASS media: stale player ID never redirects a command to another player")
    finally:
        services.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit("Usage: media_probe.py [--serve]")
