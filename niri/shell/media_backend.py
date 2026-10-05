#!/usr/bin/env python3
"""MPRIS metadata and explicit controls for one selected, owner-pinned player.

Call from a worker thread. Merely reading state never starts a player. Each
snapshot obtains metadata/status/capabilities together through GetAll; controls
use the same unique D-Bus owner instead of playerctl's changing default player.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

PREFIX = "org.mpris.MediaPlayer2."
ROOT_INTERFACE = "org.mpris.MediaPlayer2"
PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
PROPERTIES = "org.freedesktop.DBus.Properties"
PATH = "/org/mpris/MediaPlayer2"
BUS_NAME = "org.freedesktop.DBus"
BUS_PATH = "/org/freedesktop/DBus"
TIMEOUT_MS = 1200
ACTIONS = {"play": ("Play", "can_play"), "pause": ("Pause", "can_pause"),
           "next": ("Next", "can_next"), "previous": ("Previous", "can_previous")}


def _connection():
    try:
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as error:
        raise RuntimeError(f"Media session unavailable · 媒体会话不可用: {error.message}") from error


def _call(connection, destination, interface, method, parameters=None, reply="()", path=PATH):
    try:
        result = connection.call_sync(destination, path, interface, method, parameters,
                                      GLib.VariantType.new(reply), Gio.DBusCallFlags.NO_AUTO_START,
                                      TIMEOUT_MS, None)
        return result.unpack()
    except GLib.Error as error:
        raise RuntimeError(f"Media player unavailable · 媒体播放器不可用: {error.message}") from error


def _owner(connection, name):
    owner, = _call(connection, BUS_NAME, BUS_NAME, "GetNameOwner", GLib.Variant("(s)", (name,)),
                  "(s)", BUS_PATH)
    if not isinstance(owner, str) or not Gio.dbus_is_unique_name(owner):
        raise RuntimeError("Invalid media player owner · 媒体播放器连接标识无效")
    return owner


def _player_name(value):
    return isinstance(value, str) and value.startswith(PREFIX) and Gio.dbus_is_name(value)


def _identifier(value):
    if not isinstance(value, str) or value.count("|") != 1:
        raise ValueError("Select a media player first · 请先选择媒体播放器")
    name, owner = value.split("|", 1)
    if not _player_name(name) or not Gio.dbus_is_unique_name(owner):
        raise ValueError("Invalid media player identifier · 媒体播放器标识无效")
    return name, owner


def _text(value, limit=4096):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()[:limit]


def _snapshot(name, owner, properties, identity):
    if not isinstance(properties, dict):
        raise RuntimeError("Invalid media player properties · 媒体播放器属性无效")
    metadata = properties.get("Metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    artists = metadata.get("xesam:artist", [])
    artist = " · ".join(filter(None, (_text(value) for value in artists))) if isinstance(artists, (list, tuple)) else _text(artists)
    status = _text(properties.get("PlaybackStatus"), 32).casefold()
    status = {"playing": "Playing", "paused": "Paused", "stopped": "Stopped"}.get(status, "Unknown")
    controlled = properties.get("CanControl") is True
    result = {"id": f"{name}|{owner}", "bus_name": name, "owner": owner,
              "identity": _text(identity, 512) or name.removeprefix(PREFIX),
              "status": status, "title": _text(metadata.get("xesam:title")), "artist": artist,
              "album": _text(metadata.get("xesam:album")), "art_url": _text(metadata.get("mpris:artUrl"), 8192),
              "can_control": controlled}
    for output, prop in (("can_play", "CanPlay"), ("can_pause", "CanPause"),
                         ("can_next", "CanGoNext"), ("can_previous", "CanGoPrevious")):
        # Track navigation and pause are independent MPRIS capabilities.
        result[output] = controlled and properties.get(prop) is True
    return result


def _read_player(connection, name, owner=None):
    owner = owner or _owner(connection, name)
    properties, = _call(connection, owner, PROPERTIES, "GetAll",
                        GLib.Variant("(s)", (PLAYER_INTERFACE,)), "(a{sv})")
    try:
        root, = _call(connection, owner, PROPERTIES, "GetAll",
                     GLib.Variant("(s)", (ROOT_INTERFACE,)), "(a{sv})")
        identity = root.get("Identity", "") if isinstance(root, dict) else ""
    except RuntimeError:
        # Some browser integrations omit the friendly-name interface.
        identity = ""
    if _owner(connection, name) != owner:
        raise RuntimeError("Media player restarted; refresh and select again · 播放器已重启，请刷新后重新选择")
    return _snapshot(name, owner, properties, identity)


def read_state(preferred=None):
    """Read running players; honor an explicit preference, else choose playing."""
    connection = _connection()
    names, = _call(connection, BUS_NAME, BUS_NAME, "ListNames", reply="(as)", path=BUS_PATH)
    names = sorted({name for name in names if _player_name(name)})
    if len(names) > 1:
        # playerctld is a forwarding proxy, so prefer the real selectable players.
        names = [name for name in names if name != PREFIX + "playerctld"]
    players, errors = [], []
    if names:
        with ThreadPoolExecutor(max_workers=min(4, len(names))) as executor:
            pending = [(name, executor.submit(_read_player, connection, name)) for name in names]
            for name, task in pending:
                try:
                    players.append(task.result())
                except RuntimeError as error:
                    # Exiting or unresponsive players must not hide other applications.
                    errors.append({"bus_name": name, "error": str(error)})
    players.sort(key=lambda player: ({"Playing": 0, "Paused": 1, "Stopped": 2}.get(player["status"], 3),
                                     not player["can_control"], not player["can_pause"],
                                     player["identity"].casefold(), player["id"]))
    selected = next((player for player in players if player["id"] == preferred), players[0] if players else None)
    return {"players": players, "selected_id": selected["id"] if selected else None,
            "selected": selected, "errors": errors}


def action(player_id, requested):
    """Refresh capability/owner and send one explicit method to that instance.

Returns actual refreshed state. The optional action_pending flag means a player
accepted the command but has not yet reported its new playback status.
"""
    if not isinstance(requested, str) or requested not in ACTIONS:
        raise ValueError("Unknown media action · 媒体操作无效")
    name, owner = _identifier(player_id)
    connection = _connection()
    if _owner(connection, name) != owner:
        raise RuntimeError("Media player restarted; refresh and select again · 播放器已重启，请刷新后重新选择")
    player = _read_player(connection, name, owner)
    method, capability = ACTIONS[requested]
    if not player[capability]:
        raise RuntimeError(f"{player['identity']} does not support {requested} for this track · 当前曲目不支持此操作")
    # Address the unique owner: a name reassignment cannot redirect this command.
    _call(connection, owner, PLAYER_INTERFACE, method)
    expected = {"play": "Playing", "pause": "Paused"}.get(requested)
    deadline = time.monotonic() + 0.6
    while True:
        current = _read_player(connection, name, owner)
        if expected is None or current["status"] == expected:
            return current
        if time.monotonic() >= deadline:
            current["action_pending"] = True
            return current
        time.sleep(0.05)


if __name__ == "__main__":
    # A read-only diagnostic: deliberately omit track/artwork URLs from logs.
    state = read_state()
    summary = {"selected_id": state["selected_id"], "players": [
        {key: value for key, value in player.items()
         if key not in ("title", "artist", "album", "art_url")}
        for player in state["players"]], "errors": state["errors"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
