"""Bounded refresh, playback progress and real signals on a disposable bus."""
from concurrent.futures import Future
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'niri/shell'))
import media_backend as backend
import media_events
from media_events import Gio, GLib, MediaChanges, PlaybackClock, RefreshGate


class RefreshTests(unittest.TestCase):
    def test_coalesces_burst_keeps_events_during_read_and_periodically_recovers(self):
        event = threading.Event()
        gate = RefreshGate(event, interval=30)
        pool = Mock(); first = Future(); second = Future(); third = Future()
        pool.submit.side_effect = [first, second, third]
        read = Mock()
        gate.start(0, pool, read)
        self.assertEqual(pool.submit.call_count, 1)
        self.assertFalse(event.is_set())
        event.set()
        gate.start(.1, pool, read)
        self.assertIsNone(gate.take())
        first.set_result({'volume': 25})
        self.assertEqual(gate.take(), {'volume': 25})
        gate.start(.15, pool, read)
        self.assertEqual(pool.submit.call_count, 1)
        gate.start(.2, pool, read)
        self.assertEqual(pool.submit.call_count, 2)
        second.set_result({'volume': 30}); gate.take()
        gate.start(30, pool, read)
        self.assertEqual(pool.submit.call_count, 2)
        gate.start(30.3, pool, read)
        self.assertEqual(pool.submit.call_count, 3)

    def test_failed_read_can_be_retried(self):
        pool = Mock(); failed = Future()
        pool.submit.return_value = failed
        gate = RefreshGate(); gate.start(0, pool, Mock())
        failed.set_exception(RuntimeError('disconnected'))
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            gate.take()
        self.assertIsNone(gate.future)
        gate.changed.set(); gate.start(1, pool, Mock())
        self.assertEqual(pool.submit.call_count, 2)


class ProgressTests(unittest.TestCase):
    def test_clock_uses_sample_timestamp_playback_rate_and_clamps(self):
        clock = PlaybackClock()
        clock.set({'length': 100_000_000, 'position': 10_000_000,
                   'position_at': 50, 'rate': 2., 'status': 'Playing'})
        self.assertEqual(clock.values(55), {'progress': 20., 'has_progress': True})
        self.assertEqual(clock.values(500)['progress'], 100)
        clock.set({**clock.player, 'rate': -2.}, now=50)
        self.assertEqual(clock.values(70)['progress'], 0)

    def test_pause_seek_and_replacement_reset_clock(self):
        clock = PlaybackClock()
        clock.set({'length': 100_000_000, 'position': 50_000_000, 'status': 'Paused'}, now=1)
        self.assertEqual(clock.values(100)['progress'], 50)
        clock.set({**clock.player, 'position': 10_000_000, 'status': 'Playing'}, now=100)
        self.assertEqual(clock.values(101)['progress'], 11)
        clock.set(None)
        self.assertEqual(clock.values(102), {'progress': 0, 'has_progress': False})

    def test_missing_or_invalid_progress_does_not_invent_a_percentage(self):
        clock = PlaybackClock()
        for length, position in [(None, 0), (0, 1), (100, None), (True, 1), (100, False)]:
            with self.subTest(length=length, position=position):
                clock.set({'length': length, 'position': position}, now=0)
                self.assertFalse(clock.values(1)['has_progress'])
        for rate in (None, True, float('nan'), float('inf')):
            clock.set({'length': 10_000_000, 'position': 0, 'status': 'Playing', 'rate': rate}, now=0)
            self.assertEqual(clock.values(1)['progress'], 10)

    def test_backend_validates_position_and_metadata_before_publishing(self):
        for length, position, rate in [('123', '10', float('nan')), (True, True, False), (-1, -1, None)]:
            result = backend._snapshot(backend.PREFIX + 'Test', ':1.10', {
                'Metadata': {'mpris:length': length}, 'Position': position, 'Rate': rate}, 'Test')
            self.assertIsNone(result['length']); self.assertIsNone(result['position'])
            self.assertEqual(result['rate'], 1.)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix='selandia-mpris-')
        self.addCleanup(self.root.cleanup)
        self.address = 'unix:path=' + str(Path(self.root.name) / 'bus')
        self.buses = []; self.connections = []
        self.addCleanup(self.stop_buses)
        self.bus = self.start_bus()
        self.stopping = threading.Event()
        backoff = patch.multiple(media_events, MIN_BACKOFF=0.05, MAX_BACKOFF=0.2, POLL=0.02)
        backoff.start()
        self.addCleanup(backoff.stop)
        self.feed = MediaChanges(self.stopping, address=self.address)
        self.feed.thread.start()
        self.addCleanup(self.stop_feed)
        self.wait(lambda: self.feed.connected)
        self.sender = self.connect()
        # A round-trip and a quiet interval let initial subscriptions settle.
        self.bus_call('ListNames', None, '(as)')
        time.sleep(.1); self.feed.changed.clear()

    def wait(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.01)
        self.assertTrue(predicate(), 'event/connection deadline expired')

    def start_bus(self):
        process = subprocess.Popen(['dbus-daemon', '--session', '--nofork',
                                    '--address=' + self.address],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.buses.append(process)
        self.wait(lambda: Path(self.root.name, 'bus').exists())
        return process

    def connect(self):
        connection = Gio.DBusConnection.new_for_address_sync(self.address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        connection.set_exit_on_close(False)
        self.connections.append(connection)
        return connection

    def stop_feed(self):
        self.feed.close(); self.feed.thread.join(3)
        self.assertFalse(self.feed.thread.is_alive())
        self.assertFalse(self.feed.connected)

    def stop_buses(self):
        for connection in self.connections:
            if not connection.is_closed(): connection.close_sync(None)
        for process in self.buses:
            if process.poll() is None: process.terminate()
            process.wait(timeout=3)

    def bus_call(self, method, args, reply):
        return self.sender.call_sync(backend.BUS_NAME, backend.BUS_PATH, backend.BUS_NAME,
            method, args, GLib.VariantType.new(reply), Gio.DBusCallFlags.NONE, 1200, None)

    def emit(self, interface, signal, args):
        self.sender.emit_signal(None, backend.PATH, interface, signal, args)
        self.sender.flush_sync(None)

    def expect_change(self, function):
        self.feed.changed.clear(); function()
        self.assertTrue(self.feed.changed.wait(2), 'MPRIS change was lost')
        time.sleep(.03); self.feed.changed.clear()

    def test_owners_properties_seek_disappearance_and_unrelated_signals(self):
        name = backend.PREFIX + 'EventTest'
        self.bus_call('RequestName', GLib.Variant('(su)', ('org.example.Unrelated', 4)), '(u)')
        self.emit(backend.PROPERTIES, 'PropertiesChanged', GLib.Variant('(sa{sv}as)', ('org.example.Unrelated', {}, [])))
        self.assertFalse(self.feed.changed.wait(.15))
        self.expect_change(lambda: self.bus_call('RequestName', GLib.Variant('(su)', (name, 4)), '(u)'))
        for interface in (backend.PLAYER_INTERFACE, backend.ROOT_INTERFACE):
            self.expect_change(lambda: self.emit(backend.PROPERTIES, 'PropertiesChanged',
                GLib.Variant('(sa{sv}as)', (interface, {}, ['Metadata']))))
        self.expect_change(lambda: self.emit(backend.PLAYER_INTERFACE, 'Seeked', GLib.Variant('(x)', (30_000_000,))))
        self.expect_change(lambda: self.bus_call('ReleaseName', GLib.Variant('(s)', (name,)), '(u)'))
        # Closing the event connection must leave other connections usable.
        self.feed.close(); self.feed.thread.join(3)
        self.assertTrue(self.bus_call('ListNames', None, '(as)').unpack()[0])

    def test_bus_restart_reconnects_and_stop_event_exits(self):
        self.bus.terminate(); self.bus.wait(3)
        self.wait(lambda: not self.feed.connected)
        self.start_bus()
        self.wait(lambda: self.feed.connected)
        self.sender = self.connect(); time.sleep(.1)
        self.expect_change(lambda: self.emit(backend.PLAYER_INTERFACE, 'Seeked', GLib.Variant('(x)', (2,))))
        self.stopping.set(); self.feed.thread.join(3)
        self.assertFalse(self.feed.thread.is_alive())

    def test_callback_notifies_changes_and_close_wakes_without_safety_timer(self):
        notified = threading.Event()
        self.feed.on_change = notified.set
        self.emit(backend.PLAYER_INTERFACE, 'Seeked', GLib.Variant('(x)', (10,)))
        self.assertTrue(notified.wait(2))
        self.feed.close()
        self.feed.thread.join(.5)
        self.assertFalse(self.feed.thread.is_alive(), 'close must wake the event loop directly')

    def test_metadata_only_consumer_ignores_progress_but_keeps_invalidated_fields(self):
        self.feed.player_properties = frozenset(('Metadata', 'PlaybackStatus'))
        self.feed.watch_seek = False
        self.feed.changed.clear()
        self.emit(backend.PROPERTIES, 'PropertiesChanged', GLib.Variant('(sa{sv}as)',
            (backend.PLAYER_INTERFACE, {'Position': GLib.Variant('x', 100)}, [])))
        self.emit(backend.PLAYER_INTERFACE, 'Seeked', GLib.Variant('(x)', (100,)))
        self.assertFalse(self.feed.changed.wait(.15))
        self.expect_change(lambda: self.emit(backend.PROPERTIES, 'PropertiesChanged',
            GLib.Variant('(sa{sv}as)', (backend.PLAYER_INTERFACE, {}, ['Metadata']))))


if __name__ == '__main__':
    unittest.main()
