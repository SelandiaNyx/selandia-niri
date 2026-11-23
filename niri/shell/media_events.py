"""Coalesced MPRIS invalidation and a local playback clock for the top bar."""
import math
import os
import threading
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
import media_backend as backend

MIN_BACKOFF = 1.0
MAX_BACKOFF = 10.0
POLL = 0.2


class RefreshGate:
    """Keep changes arriving during a read, with burst and fallback bounds."""
    def __init__(self, changed=None, interval=30):
        self.changed = changed if changed is not None else threading.Event()
        self.changed.set()
        self.interval = interval
        self.next_allowed = self.fallback = 0
        self.future = None

    def start(self, now, pool, function):
        if self.future is not None or now < self.next_allowed:
            return
        if self.changed.is_set() or now >= self.fallback:
            self.changed.clear()
            self.next_allowed, self.fallback = now + .2, now + self.interval
            self.future = pool.submit(function)

    def take(self):
        if self.future is None or not self.future.done():
            return None
        future, self.future = self.future, None
        return future.result()


class PlaybackClock:
    def __init__(self):
        self.player = None

    def set(self, player, now=None):
        self.player = dict(player) if player else None
        self.at = (player or {}).get('position_at', time.monotonic()) if now is None else now

    def values(self, now):
        player = self.player or {}
        length, position = player.get('length'), player.get('position')
        if type(length) is not int or type(position) is not int or length <= 0:
            return {'progress': 0, 'has_progress': False}
        rate = player.get('rate', 1.0)
        if type(rate) not in (int, float) or not math.isfinite(rate):
            rate = 1.0
        if player.get('status') == 'Playing':
            position += max(0, now - self.at) * rate * 1_000_000
        return {'progress': round(max(0, min(100, position / length * 100)), 1), 'has_progress': True}


class MediaChanges:
    def __init__(self, stopping, *, address=None, on_change=None,
                 player_properties=None, watch_seek=True, initial_notify=True):
        self.stopping = stopping
        self.closed = threading.Event()
        self.changed = threading.Event()
        if initial_notify:
            self.changed.set()
        self.connected = False
        self.address = address
        self.on_change = on_change
        self.player_properties = None if player_properties is None else frozenset(player_properties)
        self.watch_seek = watch_seek
        self.initial_notify = initial_notify
        self.cancellable = Gio.Cancellable()
        self.lock = threading.Lock()
        self.loop = None
        self.thread = threading.Thread(target=self.run, name='mpris-events', daemon=True)

    def notify(self):
        self.changed.set()
        if self.on_change is not None:
            self.on_change()

    def done(self):
        return self.stopping.is_set() or self.closed.is_set()

    def close(self):
        self.closed.set()
        self.cancellable.cancel()
        with self.lock:
            loop = self.loop
        if loop is not None:
            loop.quit()

    def run(self):
        delay = MIN_BACKOFF
        connected_once = False
        while not self.done():
            context = GLib.MainContext.new()
            context.push_thread_default()
            connection = None
            timer = None
            subscribed = []
            closed_handler = None
            try:
                address = self.address or os.environ.get('DBUS_SESSION_BUS_ADDRESS')
                if not address:
                    address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, self.cancellable)
                connection = Gio.DBusConnection.new_for_address_sync(address,
                    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                    None, self.cancellable)
                connection.set_exit_on_close(False)
                loop = GLib.MainLoop.new(context, False)
                with self.lock:
                    self.loop = loop
                closed_handler = connection.connect('closed', lambda *_: loop.quit())

                def names(_con, _sender, _path, _interface, _signal, parameters, _data):
                    name, _, _ = parameters.unpack()
                    if isinstance(name, str) and name.startswith(backend.PREFIX):
                        self.notify()

                def properties(_con, _sender, _path, _interface, _signal, parameters, _data):
                    interface, changed, invalidated = parameters.unpack()
                    if (interface == backend.PLAYER_INTERFACE and self.player_properties is not None
                            and not self.player_properties.intersection(set(changed) | set(invalidated))):
                        return
                    if interface in (backend.ROOT_INTERFACE, backend.PLAYER_INTERFACE):
                        self.notify()

                def seeked(*_):
                    if self.watch_seek:
                        self.notify()

                for sender, interface, signal, path, callback in (
                    (backend.BUS_NAME, backend.BUS_NAME, 'NameOwnerChanged', backend.BUS_PATH, names),
                    (None, backend.PROPERTIES, 'PropertiesChanged', backend.PATH, properties),
                    (None, backend.PLAYER_INTERFACE, 'Seeked', backend.PATH, seeked),
                ):
                    subscribed.append(connection.signal_subscribe(sender, interface, signal, path, None,
                        Gio.DBusSignalFlags.NONE, callback, None))
                connection.flush_sync(self.cancellable)
                self.connected = True
                if self.initial_notify or connected_once:
                    self.notify()
                connected_once = True
                connected_at = time.monotonic()

                def check(*_):
                    if self.done() or connection.is_closed():
                        loop.quit()
                        return GLib.SOURCE_REMOVE
                    return GLib.SOURCE_CONTINUE

                # Explicit close and bus disconnect wake the loop immediately.
                # This slower safety check only covers callers setting stopping.
                timer = GLib.timeout_source_new(1000)
                timer.set_callback(check); timer.attach(context)
                if not self.done():
                    loop.run()
                if time.monotonic() - connected_at > 5:
                    delay = MIN_BACKOFF
            except (GLib.Error, OSError, ValueError):
                pass
            finally:
                self.connected = False
                self.notify()
                with self.lock:
                    self.loop = None
                if timer:
                    timer.destroy()
                if connection:
                    if closed_handler is not None:
                        connection.disconnect(closed_handler)
                    for identifier in subscribed:
                        connection.signal_unsubscribe(identifier)
                    if not connection.is_closed():
                        try:
                            connection.close_sync(None)
                        except GLib.Error:
                            pass
                context.pop_thread_default()
            deadline = time.monotonic() + delay
            while not self.done() and time.monotonic() < deadline:
                self.closed.wait(min(POLL, max(0, deadline - time.monotonic())))
            delay = min(delay * 2, MAX_BACKOFF)
