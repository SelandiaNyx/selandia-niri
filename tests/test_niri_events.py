"""Regression coverage for direct Niri IPC and the reconnecting event cache.

Every socket in this file is a disposable AF_UNIX listener created under a
temporary directory. The real NIRI_SOCKET is never read or contacted: direct
requests always receive an explicit ``path`` (or a patched environment), and
the feeds always receive one.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
import niri_events


def wait_until(predicate, timeout=5.):
    """Poll ``predicate`` until it holds; return its final truthiness."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


def read_line(connection):
    data = bytearray()
    while b'\n' not in data and len(data) < 1 << 20:
        block = connection.recv(4096)
        if not block:
            break
        data.extend(block)
    return bytes(data)


def window(identifier, title='Title', *, focused=False, app_id='org.example.App'):
    return {'id': identifier, 'app_id': app_id, 'title': title, 'is_focused': focused}


def workspace(identifier, idx, output, *, active=False, focused=False, name=None):
    item = {'id': identifier, 'idx': idx, 'output': output, 'is_active': active, 'is_focused': focused}
    if name is not None:
        item['name'] = name
    return item


def windows_event(*entries):
    return json.dumps({'WindowsChanged': {'windows': list(entries)}}).encode() + b'\n'


def workspaces_event(*entries):
    return json.dumps({'WorkspacesChanged': {'workspaces': list(entries)}}).encode() + b'\n'


class DisposableServer:
    """A private AF_UNIX stream listener that accepts until closed.

    The first newline-terminated line of every connection is recorded in
    ``handshakes`` before ``handler(connection, index)`` runs.
    """

    def __init__(self, handler):
        self._root = tempfile.TemporaryDirectory(prefix='selandia-niri-events-')
        self.path = str(Path(self._root.name) / 'niri.sock')
        self._handler = handler
        self._closed = threading.Event()
        self.handshakes = []
        self.errors = []
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(self.path)
        self._listener.listen(8)
        self._listener.settimeout(.2)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._closed.is_set():
            try:
                connection, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(10)
                try:
                    self.handshakes.append(read_line(connection))
                    self._handler(connection, len(self.handshakes) - 1)
                except OSError:
                    pass
                except Exception as error:  # surfaced by close()/assertions
                    self.errors.append(error)

    def close(self):
        self._closed.set()
        try:
            self._listener.close()
        except OSError:
            pass
        self.thread.join(timeout=5)
        self._root.cleanup()


class RequestTests(unittest.TestCase):
    """One request, one bounded reply, with a total deadline."""

    def server(self, handler):
        server = DisposableServer(handler)
        self.addCleanup(server.close)
        return server

    def test_fragmented_reply_is_reassembled_across_reads(self):
        def handler(connection, _index):
            reply = json.dumps({'Ok': {'Outputs': {'DP-1': {'logical': {'width': 2560}}}}}).encode()
            for start, end in ((0, 7), (7, 23), (23, len(reply))):
                connection.sendall(reply[start:end])
                time.sleep(.05)
            connection.sendall(b'\n')

        server = self.server(handler)
        self.assertEqual(niri_events.request('Outputs', path=server.path),
                         {'DP-1': {'logical': {'width': 2560}}})
        self.assertEqual(server.handshakes, [b'"Outputs"\n'])

    def test_workspace_action_uses_stable_id_not_index(self):
        def handler(connection, _index):
            connection.sendall(b'{"Ok": "Handled"}\n')
        server = self.server(handler)
        action = {'Action': {'FocusWorkspace': {'reference': {'Id': 42}}}}
        self.assertIsNone(niri_events.request(action, path=server.path))
        self.assertEqual(json.loads(server.handshakes[0]), action)

    def test_reply_parsing_stops_at_the_first_newline(self):
        def handler(connection, _index):
            connection.sendall(b'{"Ok": {"Outputs": {}}}\n{"Ok": "trailing frame"}\n')

        server = self.server(handler)
        self.assertEqual(niri_events.request('Outputs', path=server.path), {})

    def test_stream_closing_before_a_reply_is_reported(self):
        def handler(connection, _index):
            return  # leave the connection: recv on the client must see EOF

        server = self.server(handler)
        with self.assertRaisesRegex(OSError, 'closed before replying'):
            niri_events.request('Outputs', path=server.path)

    def test_rejected_or_unexpected_replies_are_distinct_errors(self):
        for reply, error, pattern in (
                (b'{"Err": "unsupported"}\n', RuntimeError, 'rejected'),
                (b'[1, 2]\n', RuntimeError, 'rejected'),
                (b'null\n', RuntimeError, 'rejected'),
                (b'{"Ok": []}\n', ValueError, 'Unexpected Niri response'),
                (b'{"Ok": {}}\n', ValueError, 'Unexpected Niri response'),
                (b'{not json}\n', ValueError, '')):
            with self.subTest(reply=reply):
                def handler(connection, _index, reply=reply):
                    connection.sendall(reply)
                server = self.server(handler)
                with self.assertRaisesRegex(error, pattern):
                    niri_events.request('Outputs', path=server.path)

    def test_oversized_reply_is_bounded_before_it_is_parsed(self):
        def handler(connection, _index):
            connection.sendall(b'a' * 4096)

        server = self.server(handler)
        with patch.object(niri_events, 'MAX_MESSAGE', 512), \
                self.assertRaisesRegex(ValueError, 'too large'):
            niri_events.request('Outputs', path=server.path)

    def test_reply_deadline_is_total_and_not_reset_per_read(self):
        stop = threading.Event()

        def handler(connection, _index):
            while not stop.is_set():
                connection.sendall(b'x')
                time.sleep(.02)

        server = self.server(handler)
        self.addCleanup(stop.set)  # LIFO: stop the writer before closing it
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            niri_events.request('Outputs', path=server.path, timeout=.3)
        # A per-read reset would have kept the request alive for the whole
        # streaming window; the total deadline ends it promptly instead.
        self.assertLess(time.monotonic() - started, 1.5)

    def test_an_explicit_path_wins_over_the_environment(self):
        def handler(connection, _index):
            connection.sendall(b'{"Ok": {"Outputs": {"source": "environment"}}}\n')

        server = self.server(handler)
        with tempfile.TemporaryDirectory(prefix='selandia-niri-absent-') as root:
            missing = str(Path(root) / 'absent.sock')
            with patch.dict(os.environ, {'NIRI_SOCKET': server.path}):
                self.assertEqual(niri_events.request('Outputs'), {'source': 'environment'})
                # If the environment address were used here the call would
                # succeed, so a raised OSError proves the explicit path is used.
                with self.assertRaises(OSError):
                    niri_events.request('Outputs', path=missing, timeout=.4)

    def test_missing_socket_path_is_a_bounded_error(self):
        with tempfile.TemporaryDirectory(prefix='selandia-niri-absent-') as root:
            with self.assertRaises(OSError):
                niri_events.request('Outputs', path=str(Path(root) / 'absent.sock'), timeout=.4)

    def test_address_requires_the_socket_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(OSError, 'NIRI_SOCKET'):
                niri_events.address()
        with patch.dict(os.environ, {'NIRI_SOCKET': '/run/user/1/niri.sock'}):
            self.assertEqual(niri_events.address(), '/run/user/1/niri.sock')


class DesktopStateTests(unittest.TestCase):
    """Apply stream deltas; keep at most the current compositor state."""

    @staticmethod
    def indexed(state):
        return {item['id']: item for item in state.snapshot()['workspaces']}

    def test_only_single_key_dict_events_are_accepted(self):
        state = niri_events.DesktopState()
        for event in ({}, {'A': 1, 'B': 2}, None, [], 'WindowsChanged', 7):
            with self.subTest(event=event), self.assertRaises(ValueError):
                state.apply(event)

    def test_unknown_or_future_events_are_ignored_without_state_change(self):
        state = niri_events.DesktopState()
        state.apply({'WindowsChanged': {'windows': [window(1, focused=True)]}})
        state.apply({'WorkspacesChanged': {'workspaces': [workspace(1, 1, 'DP-1', active=True)]}})
        before = state.snapshot()
        for event in ({'OutputsChanged': {'outputs': {}}},
                      {'KeyboardLayoutsChanged': {'keyboard_layouts': {}}},
                      {'OverviewOpenedOrClosed': {'is_open': True}},
                      {'ConfigLoaded': {'failed': False}}):
            state.apply(event)
        self.assertEqual(state.snapshot(), before)
        # Urgency for a workspace this bar does not track is also ignored.
        state.apply({'WorkspaceUrgencyChanged': {'id': 999, 'urgent': True}})
        self.assertEqual(state.snapshot(), before)

    def test_workspace_activation_only_flips_active_on_the_target_output(self):
        state = niri_events.DesktopState()
        state.apply({'WorkspacesChanged': {'workspaces': [
            workspace(1, 1, 'DP-1', active=True, focused=True),
            workspace(2, 2, 'DP-1'),
            workspace(3, 1, 'HDMI-A-1', active=True),
            workspace(4, 2, 'HDMI-A-1'),
        ]}})
        before = self.indexed(state)
        state.apply({'WorkspaceActivated': {'id': 2, 'focused': True}})
        after = self.indexed(state)
        self.assertFalse(after[1]['is_active'])
        self.assertTrue(after[2]['is_active'])
        self.assertTrue(after[2]['is_focused'])
        self.assertFalse(after[1]['is_focused'])
        # The other monitor keeps its own active workspace.
        self.assertTrue(after[3]['is_active'])
        self.assertFalse(after[4]['is_active'])
        self.assertTrue(after[3]['is_active'] == before[3]['is_active'])
        # Activation reports are scoped: unrelated monitors only lose focus.
        self.assertFalse(after[3]['is_focused'])

    def test_activation_without_the_focused_flag_leaves_focus_untouched(self):
        state = niri_events.DesktopState()
        state.apply({'WorkspacesChanged': {'workspaces': [
            {'id': 1, 'idx': 1, 'output': 'DP-1', 'is_active': True, 'is_focused': True},
            {'id': 2, 'idx': 2, 'output': 'DP-1', 'is_active': False, 'is_focused': False},
        ]}})
        state.apply({'WorkspaceActivated': {'id': 2}})
        after = self.indexed(state)
        self.assertFalse(after[1]['is_active'])
        self.assertTrue(after[2]['is_active'])
        self.assertTrue(after[1]['is_focused'])
        self.assertFalse(after[2]['is_focused'])

    def test_activation_of_an_unknown_workspace_changes_nothing(self):
        state = niri_events.DesktopState()
        state.apply({'WorkspacesChanged': {'workspaces': [workspace(1, 1, 'DP-1', active=True)]}})
        before = state.snapshot()
        state.apply({'WorkspaceActivated': {'id': 404, 'focused': True}})
        self.assertEqual(state.snapshot(), before)

    def test_urgency_changes_only_tracked_workspaces(self):
        state = niri_events.DesktopState()
        state.apply({'WorkspacesChanged': {'workspaces': [workspace(1, 1, 'DP-1', active=True)]}})
        state.apply({'WorkspaceUrgencyChanged': {'id': 1, 'urgent': True}})
        self.assertTrue(self.indexed(state)[1]['is_urgent'])
        state.apply({'WorkspaceUrgencyChanged': {'id': 1, 'urgent': False}})
        self.assertFalse(self.indexed(state)[1]['is_urgent'])

    def test_window_open_change_and_close_track_focus(self):
        state = niri_events.DesktopState()
        state.apply({'WindowsChanged': {'windows': [
            window(1, 'One', focused=False), window(2, 'Two', focused=True)]}})
        self.assertEqual(state.snapshot()['window']['id'], 2)

        # A new unfocused window is added without stealing focus.
        state.apply({'WindowOpenedOrChanged': {'window': window(3, 'Three')}})
        self.assertEqual(state.snapshot()['window']['id'], 2)
        self.assertEqual(set(state.windows), {1, 2, 3})

        # A change that drops the focused window's flag clears focus but keeps
        # the window itself (only a close removes it).
        state.apply({'WindowOpenedOrChanged': {'window': window(2, 'Two renamed', focused=False)}})
        self.assertIsNone(state.focus)
        self.assertIsNone(state.snapshot()['window'])
        self.assertIn(2, state.windows)

        # A newly focused window wins again.
        state.apply({'WindowOpenedOrChanged': {'window': window(3, 'Three', focused=True)}})
        self.assertEqual(state.snapshot()['window']['id'], 3)

        # Closing the focused window removes it and clears focus.
        state.apply({'WindowClosed': {'id': 3}})
        self.assertNotIn(3, state.windows)
        self.assertIsNone(state.snapshot()['window'])

        # Closing a background window keeps the focused one.
        state.apply({'WindowFocusChanged': {'id': 1}})
        state.apply({'WindowClosed': {'id': 2}})
        self.assertEqual(state.snapshot()['window']['id'], 1)
        self.assertEqual(set(state.windows), {1})

        # Closing an unknown window is harmless.
        state.apply({'WindowClosed': {'id': 404}})
        self.assertEqual(set(state.windows), {1})

    def test_window_snapshots_replace_rather_than_merge(self):
        state = niri_events.DesktopState()
        state.apply({'WindowsChanged': {'windows': [window(1, focused=True)]}})
        state.apply({'WindowsChanged': {'windows': [window(2, focused=True)]}})
        self.assertEqual(set(state.windows), {2})
        state.apply({'WindowsChanged': {'windows': [window(3, focused=False)]}})
        self.assertIsNone(state.focus)

    def test_empty_focus_and_snapshot_availability(self):
        state = niri_events.DesktopState()
        empty = state.snapshot()
        self.assertEqual(empty, {'available': False, 'window': None, 'workspaces': []})

        # A window snapshot alone is not a usable desktop state.
        state.apply({'WindowsChanged': {'windows': [window(1, focused=True)]}})
        self.assertFalse(state.snapshot()['available'])
        self.assertFalse(state.snapshot()['workspaces'])

        state.apply({'WorkspacesChanged': {'workspaces': [workspace(1, 1, 'DP-1', active=True)]}})
        self.assertTrue(state.snapshot()['available'])

        # Niri reports "nothing focused" as a null id.
        state.apply({'WindowFocusChanged': {'id': None}})
        self.assertIsNone(state.focus)
        self.assertIsNone(state.snapshot()['window'])
        self.assertEqual([item['id'] for item in state.snapshot()['workspaces']], [1])

        # A snapshot with no focused windows also leaves focus empty.
        state.apply({'WindowsChanged': {'windows': [window(1, focused=False), window(2, focused=False)]}})
        self.assertIsNone(state.focus)
        self.assertIsNone(state.snapshot()['window'])

    def test_snapshots_do_not_expose_mutable_internal_state(self):
        state = niri_events.DesktopState()
        state.apply({'WindowsChanged': {'windows': [window(1, 'Original', focused=True)]}})
        state.apply({'WorkspacesChanged': {'workspaces': [workspace(1, 1, 'DP-1', active=True, name='W')]}})
        snapshot = state.snapshot()
        snapshot['window']['title'] = 'mutated'
        snapshot['workspaces'][0]['is_active'] = False
        snapshot['workspaces'].append(workspace(9, 9, 'DP-1'))
        fresh = state.snapshot()
        self.assertEqual(fresh['window']['title'], 'Original')
        self.assertTrue(fresh['workspaces'][0]['is_active'])
        self.assertEqual([item['id'] for item in fresh['workspaces']], [1])


class DesktopFeedTests(unittest.TestCase):
    """A real stream connection: disconnect, reconnect and stop."""

    def test_disconnect_clears_state_and_reconnect_publishes_a_fresh_snapshot(self):
        stopping = threading.Event()
        first_ready = threading.Event()
        drop_first = threading.Event()
        second_connected = threading.Event()
        send_second = threading.Event()
        finish = threading.Event()

        def handler(connection, index):
            if index == 0:
                connection.sendall(b'{"Ok": "Handled"}\n')
                connection.sendall(windows_event(window(11, 'First', focused=True)))
                connection.sendall(workspaces_event(workspace(7, 1, 'DP-1', active=True)))
                first_ready.set()
                drop_first.wait(5)  # returning closes the stream
            else:
                second_connected.set()
                send_second.wait(5)
                connection.sendall(b'{"Ok": "Handled"}\n')
                connection.sendall(windows_event(window(22, 'Second', focused=True)))
                connection.sendall(workspaces_event(workspace(8, 1, 'HDMI-A-1', active=True)))
                finish.wait(5)

        server = DisposableServer(handler)
        feed = niri_events.DesktopFeed(stopping, path=server.path)
        self.addCleanup(lambda: (finish.set(), send_second.set(), drop_first.set(),
                                 stopping.set(), feed.thread.join(timeout=3), server.close()))
        feed.thread.start()

        self.assertTrue(first_ready.wait(5))
        self.assertTrue(wait_until(lambda: (feed.snapshot()['window'] or {}).get('id') == 11))
        self.assertTrue(feed.snapshot()['available'])
        self.assertEqual(server.handshakes[0], b'"EventStream"\n')

        # The peer goes away: no stale application or workspace survives.
        drop_first.set()
        self.assertTrue(second_connected.wait(5))
        stale = feed.snapshot()
        self.assertFalse(stale['available'])
        self.assertIsNone(stale['window'])
        self.assertEqual(stale['workspaces'], [])
        self.assertEqual(server.handshakes[1], b'"EventStream"\n')

        # The same feed reconnects and publishes the fresh snapshot.
        send_second.set()
        self.assertTrue(wait_until(lambda: (feed.snapshot()['window'] or {}).get('id') == 22))
        fresh = feed.snapshot()
        self.assertTrue(fresh['available'])
        self.assertEqual(fresh['window']['title'], 'Second')
        self.assertEqual([item['id'] for item in fresh['workspaces']], [8])

        stopping.set()
        feed.thread.join(timeout=3)
        self.assertFalse(feed.thread.is_alive())
        self.assertEqual(server.errors, [])

    def test_only_a_complete_snapshot_is_marked_available(self):
        stopping = threading.Event()
        sent = threading.Event()
        hold = threading.Event()

        def handler(connection, _index):
            connection.sendall(b'{"Ok": "Handled"}\n')
            connection.sendall(windows_event(window(1, 'One', focused=True)))
            sent.set()
            hold.wait(5)

        server = DisposableServer(handler)
        feed = niri_events.DesktopFeed(stopping, path=server.path)
        self.addCleanup(lambda: (hold.set(), stopping.set(), feed.thread.join(timeout=3), server.close()))
        feed.thread.start()

        self.assertTrue(sent.wait(5))
        self.assertTrue(wait_until(lambda: (feed.snapshot()['window'] or {}).get('id') == 1))
        # Windows without workspaces is still an unusable desktop state.
        self.assertFalse(feed.snapshot()['available'])
        self.assertEqual(feed.snapshot()['workspaces'], [])
        stopping.set()
        feed.thread.join(timeout=2)
        self.assertFalse(feed.thread.is_alive())
        self.assertFalse(feed.snapshot()['available'])

    def test_stopping_while_connected_ends_the_thread_and_clears_state(self):
        stopping = threading.Event()
        connected = threading.Event()
        hold = threading.Event()

        def handler(connection, _index):
            connection.sendall(b'{"Ok": "Handled"}\n')
            connection.sendall(windows_event(window(5, 'Live', focused=True)))
            connection.sendall(workspaces_event(workspace(1, 1, 'DP-1', active=True)))
            connected.set()
            hold.wait(5)

        server = DisposableServer(handler)
        feed = niri_events.DesktopFeed(stopping, path=server.path)
        self.addCleanup(lambda: (hold.set(), stopping.set(), feed.thread.join(timeout=3), server.close()))
        feed.thread.start()

        self.assertTrue(connected.wait(5))
        self.assertTrue(wait_until(lambda: feed.snapshot()['available']))
        stopping.set()
        feed.thread.join(timeout=2)
        self.assertFalse(feed.thread.is_alive())
        # The worker clears the cache on the way out.
        self.assertFalse(feed.snapshot()['available'])
        self.assertIsNone(feed.snapshot()['window'])

    def test_stopping_interrupts_the_reconnect_backoff(self):
        stopping = threading.Event()
        with tempfile.TemporaryDirectory(prefix='selandia-niri-absent-') as root:
            feed = niri_events.DesktopFeed(stopping, path=str(Path(root) / 'absent.sock'))
            feed.thread.start()
            time.sleep(.3)  # the connect fails immediately, then the feed backs off
            started = time.monotonic()
            stopping.set()
            feed.thread.join(timeout=2)
            self.assertFalse(feed.thread.is_alive())
            self.assertLess(time.monotonic() - started, .5)

    def test_publish_and_snapshot_are_defensive_copies(self):
        feed = niri_events.DesktopFeed(threading.Event(), path='unused')
        state = niri_events.DesktopState()
        state.apply({'WindowsChanged': {'windows': [window(1, 'One', focused=True)]}})
        state.apply({'WorkspacesChanged': {'workspaces': [workspace(4, 1, 'DP-1', active=True)]}})
        feed.publish(state)
        snapshot = feed.snapshot()
        self.assertTrue(snapshot['available'])
        snapshot['window']['id'] = 999
        snapshot['workspaces'][0]['is_active'] = False
        again = feed.snapshot()
        self.assertEqual(again['window']['id'], 1)
        self.assertTrue(again['workspaces'][0]['is_active'])


if __name__ == '__main__':
    unittest.main()
