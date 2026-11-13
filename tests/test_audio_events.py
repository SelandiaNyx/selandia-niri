"""Coalesced audio-event feed: line filtering, tail handling and worker lifecycle.

Nothing here contacts PulseAudio. The parsing tests drive ``AudioChanges.read``
with a scripted fake child/stream, and the lifecycle tests run tiny private
``sys.executable`` children instead of ``pactl``. No host socket or service is
ever started, and every worker is closed and joined with bounded waits.
"""
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
import audio_events


def wait_until(predicate, timeout=5.):
    """Poll ``predicate`` until it holds; return its final truthiness."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.01)
    return bool(predicate())


class FakeStream:
    """Deterministic stand-in for ``child.stdout``: read1 yields scripted blocks."""

    def __init__(self, *blocks):
        self.blocks = list(blocks)
        self.closed = False

    def read1(self, _size):
        return self.blocks.pop(0) if self.blocks else b''

    def close(self):
        self.closed = True


class FakeChild:
    """Minimal Popen look-alike that stays alive and exposes a scripted stdout."""

    def __init__(self, *blocks):
        self.stdout = FakeStream(*blocks)

    def poll(self):
        return None


class AudioEventsTests(unittest.TestCase):
    def drain(self, *blocks, facilities=('sink', 'server')):
        """Run one synchronous ``read`` pass over scripted stdout blocks.

        ``changed`` starts out set by contract, so it is cleared first: any
        truthy result afterwards was produced by this read pass alone.
        """
        changes = audio_events.AudioChanges(threading.Event(), facilities=facilities)
        changes.changed.clear()
        # A private select patch keeps the fake stream perpetually readable; it
        # is restored before the next test and never touches a real descriptor.
        with patch.object(audio_events.select, 'select',
                          lambda readable, writable, errors, timeout: (readable, writable, errors)):
            received = changes.read(FakeChild(*blocks))
        return changes, received

    def sleeper(self, seconds=30):
        return [sys.executable, '-B', '-c', f'import time; time.sleep({seconds})']

    def shutdown(self, changes):
        """Bounded teardown: stop, close, join, then kill any straggler child."""
        changes.stopping.set()
        changes.close()
        if changes.thread.ident is not None:
            changes.thread.join(5)
        with changes.lock:
            child = changes.child
        if child is not None and child.poll() is None:
            child.kill()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def start(self, command):
        stopping = threading.Event()
        changes = audio_events.AudioChanges(stopping, command=command)
        self.addCleanup(self.shutdown, changes)
        changes.thread.start()
        return changes

    def test_only_sink_and_server_events_signal_changed(self):
        # Matching sink/server lines of every kind must coalesce into ``changed``.
        changes, received = self.drain(
            b"Event 'new' on sink #1\n",
            b"Event 'change' on sink #42\n",
            b"Event 'remove' on server #0\n",
        )
        self.assertTrue(received)
        self.assertTrue(changes.changed.is_set())

        # Source, sink-input, source-output, client and card lines are not our
        # concern, and malformed sink lines must not slip through either.
        changes, _ = self.drain(
            b"Event 'new' on source #1\n",
            b"Event 'change' on sink-input #2\n",
            b"Event 'remove' on source-output #3\n",
            b"Event 'remove' on client #4\n",
            b"Event 'new' on card #5\n",
            b"Event 'new' on sink 12\n",
            b"Event 'new' on sink #\n",
            b"Event 'new' on server #x\n",
            b"Server changed\n",
        )
        self.assertFalse(changes.changed.is_set())

        # A matching line mixed in with ignored ones still fires.
        changes, _ = self.drain(
            b"Event 'new' on client #1\n",
            b"Event 'change' on sink #6\n",
            b"Event 'remove' on source #2\n",
        )
        self.assertTrue(changes.changed.is_set())

    def test_partial_line_is_reassembled_and_bare_tail_ignored(self):
        # A matching line split across reads must still be recognised.
        changes, _ = self.drain(b"Event 'new' on si", b"nk #7\n")
        self.assertTrue(changes.changed.is_set())

        # A trailing fragment with no newline is buffered, never matched as a
        # line, and producing any bytes still counts as receiving output.
        changes, received = self.drain(b"Event 'new' on sink #8")
        self.assertTrue(received)
        self.assertFalse(changes.changed.is_set())

    def test_sound_controls_recognize_each_requested_facility_and_event(self):
        facilities = ('sink', 'source', 'server', 'card', 'sink-input', 'source-output')
        for facility in facilities:
            for event in ('new', 'change', 'remove'):
                with self.subTest(facility=facility, event=event):
                    changes, received = self.drain(
                        f"Event '{event}' on {facility} #17\n".encode(),
                        facilities=facilities,
                    )
                    self.assertTrue(received)
                    self.assertTrue(changes.changed.is_set())

    def test_sound_controls_ignore_unrelated_and_partial_facility_names(self):
        facilities = ('sink', 'source', 'server', 'card', 'sink-input', 'source-output')
        for facility in ('client', 'module', 'sample', 'autoload', 'sinks',
                         'source-output-extra', 'sink-inputs', 'sound-card',
                         'server-extra', 'source-outputting'):
            with self.subTest(facility=facility):
                changes, received = self.drain(
                    f"Event 'change' on {facility} #17\n".encode(),
                    facilities=facilities,
                )
                self.assertTrue(received)
                self.assertFalse(changes.changed.is_set())

    def test_facility_filters_are_independent_and_empty_matches_nothing(self):
        default_before = audio_events.AudioChanges(threading.Event())
        facilities = ('sink', 'source', 'server', 'card', 'sink-input', 'source-output')
        expanded, _ = self.drain(b"Event 'change' on source #17\n",
                                 facilities=facilities)
        self.assertTrue(expanded.changed.is_set())
        default_after = audio_events.AudioChanges(threading.Event())

        # An expanded consumer must not widen either existing or new defaults.
        for changes in (default_before, default_after):
            changes.changed.clear()
            with patch.object(audio_events.select, 'select',
                              lambda readable, writable, errors, timeout:
                              (readable, writable, errors)):
                changes.read(FakeChild(b"Event 'change' on source #17\n"))
                self.assertFalse(changes.changed.is_set())
                changes.read(FakeChild(b"Event 'change' on sink #17\n"))
                self.assertTrue(changes.changed.is_set())

        empty, received = self.drain(
            *(f"Event 'change' on {facility} #17\n".encode()
              for facility in facilities),
            facilities=(),
        )
        self.assertTrue(received)
        self.assertFalse(empty.changed.is_set())

    def test_overlong_partial_line_and_its_tail_are_discarded(self):
        overlong = b'Z' * (audio_events.MAX_LINE + 1)

        # The oversized fragment's unterminated tail is dropped, so the matching
        # line that completes it must not fire.
        changes, _ = self.drain(overlong, b"Event 'new' on sink #9\n")
        self.assertFalse(changes.changed.is_set())

        # Only the discarded line is lost: the next complete line still matches.
        changes, _ = self.drain(overlong, b"Event 'new' on sink #9\n", b"Event 'change' on server #2\n")
        self.assertTrue(changes.changed.is_set())

    def test_close_terminates_and_reaps_subprocess(self):
        changes = self.start(self.sleeper())
        self.assertTrue(wait_until(lambda: changes.child is not None and changes.child.poll() is None, 5))
        child = changes.child

        changes.close()
        changes.thread.join(5)

        self.assertFalse(changes.thread.is_alive())
        self.assertTrue(changes.closed.is_set())
        self.assertFalse(changes.connected)
        self.assertIsNotNone(child.poll(), 'child must be terminated and reaped')
        self.assertIsNone(changes.child)
        self.assertTrue(changes.changed.is_set(), 'consumers must be woken by teardown')

    def test_global_stopping_event_prevents_spawn_and_halts_worker(self):
        # An already-set stopping event means no child is ever launched.
        stopping = threading.Event()
        stopping.set()
        changes = audio_events.AudioChanges(stopping, command=self.sleeper())
        self.addCleanup(self.shutdown, changes)
        with patch.object(audio_events.subprocess, 'Popen') as popen:
            start = time.monotonic()
            changes.run()
            elapsed = time.monotonic() - start
        popen.assert_not_called()
        self.assertLess(elapsed, 1.)
        self.assertIsNone(changes.child)
        self.assertTrue(changes.done())

        # A running worker observes the global event and tears its child down.
        changes = self.start(self.sleeper())
        self.assertTrue(wait_until(lambda: changes.child is not None, 5))
        child = changes.child
        changes.stopping.set()
        changes.thread.join(5)

        self.assertFalse(changes.thread.is_alive())
        self.assertIsNotNone(child.poll())
        self.assertIsNone(changes.child)

    def test_reconnect_after_child_death_with_bounded_backoff(self):
        real_popen = audio_events.subprocess.Popen
        spawned = []

        def factory(*args, **options):
            child = real_popen(*args, **options)
            spawned.append(child)
            return child

        # Shortened constants: a vanished child is replaced fast, but the capped
        # backoff must keep the respawn rate bounded rather than spin hot.
        with patch.object(audio_events, 'MIN_BACKOFF', .02), \
                patch.object(audio_events, 'MAX_BACKOFF', .08), \
                patch.object(audio_events, 'POLL', .01), \
                patch.object(audio_events.subprocess, 'Popen', side_effect=factory):
            changes = self.start([sys.executable, '-B', '-c', 'pass'])
            self.assertTrue(wait_until(lambda: len(spawned) >= 3, 5))
            time.sleep(.4)
            count = len(spawned)
            changes.close()
            changes.thread.join(5)

        self.assertFalse(changes.thread.is_alive())
        self.assertGreaterEqual(len(spawned), 3, 'worker must respawn a dead child')
        self.assertLess(count, 25, 'respawns must be bounded by MAX_BACKOFF, not a hot loop')
        for child in spawned:
            self.assertIsNotNone(child.poll(), 'no child may be left unreaped')


if __name__ == '__main__':
    unittest.main()
