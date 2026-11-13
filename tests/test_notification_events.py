"""NotificationFeed connection lifecycle on a disposable private bus.

Every test starts its own ``dbus-daemon`` on a temporary unix socket, so no
live user/session bus, no SwayNC, no GUI and no activatable session service is
touched.  The feed's base directory stays empty, exactly like a fresh install
without a ``theme/swaync.json``.
"""
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'niri/shell'))
from gi.repository import Gio, GLib
import notification_events as notifications

UNAVAILABLE = {'notifications_available': False, 'notification_dnd': False,
               'notification_center_open': False, 'notification_inhibited': False}


class ConfigTests(unittest.TestCase):
    def test_json_glib_comments_and_invalid_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'config.json'
            path.write_text('{ /* comment */ "timeout": 2, "notification-visibility": {"quiet":{"state":"muted"}} }')
            self.assertEqual(notifications.read_config(path)['notification-visibility']['quiet']['state'],'muted')
            for value in ('[]','invalid json'):
                path.write_text(value);self.assertEqual(notifications.read_config(path),{})

    def test_timeouts_match_daemon_defaults(self):
        self.assertEqual(notifications.timeouts({}),{'timeout':10,'timeout-low':5,'timeout-critical':0})
        self.assertEqual(notifications.timeouts({'timeout':-1,'timeout-low':True,'timeout-critical':'2'}),
                         {'timeout':10,'timeout-low':5,'timeout-critical':0})
        self.assertEqual(notifications.timeouts({'timeout':1,'timeout-low':2,'timeout-critical':3}),
                         {'timeout':1,'timeout-low':2,'timeout-critical':3})

    def test_custom_daemon_path_and_non_daemon_fallback(self):
        with tempfile.TemporaryDirectory(prefix="notification config's ") as temporary:
            root=Path(temporary);config=root/'custom config.json';config.write_text('{}')
            fallback=root/'theme/swaync.json';fallback.parent.mkdir();fallback.write_text('{}')
            feed=notifications.NotificationFeed(queue.Queue(),threading.Event(),base=root)
            for arguments in (['swaync','-c',str(config)],['/usr/bin/swaync','--config',str(config)],
                              ['swaync','--config='+str(config)]):
                with self.subTest(arguments=arguments),patch.object(feed,'call',return_value=(os.getpid(),)), \
                     patch.object(Path,'read_bytes',return_value=b'\0'.join(os.fsencode(arg) for arg in arguments)+b'\0'):
                    self.assertEqual(feed.config_path(None,':1.2'),config)
            with patch.object(feed,'call',return_value=(os.getpid(),)), \
                 patch.object(Path,'read_bytes',return_value=b'python3\0-c\0arbitrary source code\0'):
                self.assertEqual(feed.config_path(None,':1.2'),fallback)


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix='selandia-notifications-')
        self.addCleanup(self.root.cleanup)
        self.base = Path(self.root.name)
        self.socket = self.base / 'bus'
        self.address = 'unix:path=' + str(self.socket)
        self.marker = self.base / 'activated'
        self.write_spy_service()
        self.buses = []
        self.connections = []
        self.addCleanup(self.stop_buses)
        self.bus = self.start_bus()
        # Empty state directory: the feed must cope without a swaync.json.
        self.state = self.base / 'state'
        self.state.mkdir()
        self.events = queue.Queue()
        self.stopping = threading.Event()
        self.feed = notifications.NotificationFeed(self.events, self.stopping,
                                                   base=self.state, address=self.address)
        self.feed.thread.start()
        self.addCleanup(self.stop_feed)
        self.wait(lambda: self.feed.connected)
        self.client = self.connect()

    # -- private bus and cleanup -------------------------------------------
    def write_spy_service(self):
        """Register an activatable notifications service that records starts."""
        directory = self.base / 'data/dbus-1/services'
        directory.mkdir(parents=True)
        script = self.base / 'spy.sh'
        script.write_text('#!/bin/sh\necho started > %s\n' % self.marker)
        script.chmod(0o755)
        (directory / (notifications.NOTIFY + '.service')).write_text(
            '[D-BUS Service]\nName=%s\nExec=%s\n' % (notifications.NOTIFY, script))

    def start_bus(self):
        environment = dict(os.environ, XDG_DATA_HOME=str(self.base / 'data-home'),
                           XDG_DATA_DIRS=str(self.base / 'data'))
        process = subprocess.Popen(['dbus-daemon', '--session', '--nofork',
                                    '--address=' + self.address], env=environment,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.buses.append(process)
        self.wait(lambda: self.socket.exists())
        return process

    def connect(self):
        connection = Gio.DBusConnection.new_for_address_sync(self.address,
            Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        connection.set_exit_on_close(False)
        self.connections.append(connection)
        return connection

    def stop_feed(self):
        self.feed.close()
        self.feed.thread.join(3)
        self.assertFalse(self.feed.thread.is_alive(), 'notification feed thread outlived close()')
        self.assertFalse(self.feed.connected)

    def stop_buses(self):
        for connection in self.connections:
            if not connection.is_closed():
                try: connection.close_sync(None)
                except GLib.Error: pass
        for process in self.buses:
            if process.poll() is None: process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=3)

    # -- helpers -----------------------------------------------------------
    def wait(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.01)
        self.assertTrue(predicate(), 'deadline expired')

    def call(self, connection, method, arguments=None, reply=None, *,
             flags=Gio.DBusCallFlags.NONE, destination=notifications.BUS,
             path=notifications.BUS_PATH, interface=notifications.BUS, timeout=1200):
        return connection.call_sync(destination, path, interface, method, arguments,
            GLib.VariantType.new(reply) if reply else None, flags, timeout, None)

    def bus_call(self, method, arguments=None, reply=None):
        return self.call(self.client, method, arguments, reply)

    def drain(self):
        events = []
        while True:
            try: events.append(self.events.get_nowait())
            except queue.Empty: return events

    def policies(self, events):
        return [event for event in events if event.get('action') == 'notification-policy']

    def previews(self, events):
        return [event for event in events
                if event.get('action') in ('notification', 'notification-close')]

    def assert_notifications_unowned(self, connection=None):
        with self.assertRaises(GLib.Error) as caught:
            self.call(connection or self.client, 'GetNameOwner',
                      GLib.Variant('(s)', (notifications.NOTIFY,)), '(s)')
        self.assertRegex(caught.exception.message, 'NameHasNoOwner|no such name')

    # -- tests -------------------------------------------------------------
    def test_absent_swaync_stays_unavailable_without_activation_and_reconnects(self):
        # The feed reached the private bus while no SwayNC exists there.
        events = self.drain()
        reports = self.policies(events)
        self.assertTrue(reports, 'no notification-policy report after connecting')
        self.assertEqual(reports[0]['values'], UNAVAILABLE)
        self.assertTrue(all(not report['values']['notifications_available'] for report in reports))
        # An activatable notifications service exists on this bus, so a preview
        # (or activation) below would be possible if the feed mishandled it.
        self.assertIn(notifications.NOTIFY,
                      self.bus_call('ListActivatableNames', None, '(as)').unpack()[0])
        self.assert_notifications_unowned()
        time.sleep(.3)
        self.assertFalse(self.marker.exists(), 'notification feed activated a service')

        # Force-closing the feed's own connection must be noticed and retried.
        first = self.feed.connection
        self.assertIsNotNone(first)
        first.close_sync(None)
        self.wait(lambda: not self.feed.connected and self.feed.connection is None)
        self.wait(lambda: self.feed.connected and self.feed.connection is not first, 12)
        self.assertIsNot(self.feed.connection, first)
        self.assertTrue(first.is_closed())

        # Unrelated forged signals, and a well-formed call that must not
        # auto-start the absent service, never produce a preview.
        self.drain()
        self.client.emit_signal(None, notifications.CC_PATH, notifications.CC, 'SubscribeV2',
                                GLib.Variant('(ubbb)', (7, True, True, True)))
        self.client.emit_signal(None, notifications.NOTIFY_PATH, notifications.NOTIFY, 'NotificationClosed',
                                GLib.Variant('(uu)', (1, 1)))
        with self.assertRaises(GLib.Error):
            self.call(self.client, 'Notify',
                      GLib.Variant('(susssasa{sv}i)', ('app', 0, 'icon', 'Title', 'Body', [], {}, -1)),
                      flags=Gio.DBusCallFlags.NO_AUTO_START, destination=notifications.NOTIFY,
                      path=notifications.NOTIFY_PATH, interface=notifications.NOTIFY)
        self.client.flush_sync(None)
        time.sleep(.5)
        events = self.drain()
        self.assertEqual(self.previews(events), [])
        self.assertTrue(all(not report['values']['notifications_available']
                            for report in self.policies(events)))
        self.assertFalse(self.marker.exists(), 'notification feed activated a service')

    def test_close_joins_thread_cleans_connections_and_keeps_client_usable(self):
        connection = self.feed.connection
        self.assertIsNotNone(connection)
        self.feed.close()
        self.feed.thread.join(3)
        self.assertFalse(self.feed.thread.is_alive())
        self.assertFalse(self.feed.connected)
        self.assertIsNone(self.feed.connection)
        self.assertTrue(connection.is_closed(), 'feed left its monitor connection open')
        # An independent client survives the feed's teardown.
        self.assertIn('org.freedesktop.DBus', self.bus_call('ListNames', None, '(as)').unpack()[0])
        self.assertTrue(self.bus_call('GetId', None, '(s)').unpack()[0])

    def test_bus_restart_reconnects_then_stopping_event_alone_exits_bounded(self):
        first = self.feed.connection
        self.bus.terminate()
        self.bus.wait(3)
        self.wait(lambda: not self.feed.connected)
        self.wait(lambda: not self.socket.exists(), 3)
        self.bus = self.start_bus()
        self.wait(lambda: self.feed.connected and self.feed.connection is not first, 15)
        self.assertIsNot(self.feed.connection, first)
        # The replacement bus is live: an independent client can use it too.
        self.client = self.connect()
        self.assertIn('org.freedesktop.DBus', self.bus_call('ListNames', None, '(as)').unpack()[0])
        # Setting the stopping event alone must end the thread within 3s.
        started = time.monotonic()
        self.stopping.set()
        self.feed.thread.join(3)
        self.assertFalse(self.feed.thread.is_alive(), 'stopping event did not end the thread in 3s')
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(self.feed.connected)
        self.assertIsNone(self.feed.connection)


if __name__ == '__main__':
    unittest.main()
