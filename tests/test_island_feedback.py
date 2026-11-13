"""Real private IPC and read-only audio fixtures; never touch host devices."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
import island


class IslandFeedbackTests(unittest.TestCase):
    def test_dismissed_playing_media_stays_closed_until_reopened_or_playback_restarts(self):
        events = island.Events()
        self.assertEqual(events.current(1, True), 'media')
        events.receive({'action': 'dismiss'}, 2)
        self.assertEqual(events.current(2, True), 'idle')
        self.assertEqual(events.current(100, True), 'idle')
        events.receive({'action': 'notification', 'title': 'Mail'}, 101)
        self.assertEqual(events.current(102, True), 'notification')
        self.assertEqual(events.current(110, True), 'idle')
        events.receive({'action': 'show', 'kind': 'media'}, 111)
        self.assertEqual(events.current(120, True), 'media')
        events.receive({'action': 'dismiss'}, 121)
        self.assertEqual(events.current(122, False), 'idle')
        self.assertEqual(events.current(123, True), 'media')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='osd-ipc-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        identity = str(root / 'private-niri')
        self.path = root / ('selandia-island-' + hashlib.sha256(identity.encode()).hexdigest()[:20] + '.sock')
        self.environment = dict(os.environ, XDG_RUNTIME_DIR=str(root), NIRI_SOCKET=identity,
                                XDG_CONFIG_HOME=str(root/'config'), XDG_STATE_HOME=str(root/'state'))

    def show(self, *arguments):
        return subprocess.run([sys.executable, '-B', str(ROOT/'niri/shell/island.py'), 'show', *arguments],
                              env=self.environment, capture_output=True, text=True, timeout=4)

    def test_absent_stale_or_regular_endpoint_reports_failure(self):
        self.assertEqual(self.show('volume').returncode, 1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stream:
            stream.bind(str(self.path))
        self.assertEqual(self.show('brightness').returncode, 1)
        self.path.unlink()
        self.path.write_text('keep this file')
        self.assertEqual(self.show('volume').returncode, 1)
        self.assertEqual(self.path.read_text(), 'keep this file')

    def test_success_means_request_was_delivered(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stream:
            stream.bind(str(self.path)); stream.settimeout(2)
            for kind in ('volume', 'brightness', 'media'):
                with self.subTest(kind=kind):
                    self.assertEqual(self.show(kind).returncode, 0)
                    self.assertEqual(json.loads(stream.recv(8192)), {'action':'show', 'kind':kind})

    def test_invalid_show_never_delivers(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as stream:
            stream.bind(str(self.path)); stream.setblocking(False)
            for arguments in ((), ('unknown',), ('volume', 'extra')):
                with self.subTest(arguments=arguments):
                    self.assertEqual(self.show(*arguments).returncode, 1)
                    with self.assertRaises(BlockingIOError): stream.recv(8192)

    def test_congested_socket_returns_failure(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            receiver.bind(str(self.path)); sender.setblocking(False)
            for _ in range(1024):
                try: sender.sendto(b'{}', str(self.path))
                except BlockingIOError: break
            else: self.fail('Unable to fill private sender buffer')
            # Some kernels limit each sender before the receiver queue fills.
            # Reuse the congested sender to exercise the actual timeout path.
            with patch.object(island, 'endpoint', return_value=self.path), patch.object(island.socket, 'socket', return_value=sender):
                self.assertFalse(island.send('show', kind='volume'))

    def test_audio_includes_mute_even_at_zero_volume(self):
        for volume in (0, 73, 125):
            for muted in (False, True):
                with self.subTest(volume=volume, muted=muted), patch.object(island, 'call', side_effect=[
                        f'Volume: front-left: 32768 / {volume}% / -6.02 dB', 'Mute: yes\n' if muted else 'Mute: no\n']):
                    self.assertEqual(island.sample_audio(), {'volume':volume, 'has_audio':True, 'muted':muted})

    def test_invalid_or_failed_audio_does_not_retain_old_mute(self):
        for replies in (['bad volume', 'Mute: no'], ['Volume: 50%', 'bad mute'],
                        ['Volume: 50%', RuntimeError('gone')], [OSError('missing pactl')]):
            with self.subTest(replies=replies), patch.object(island, 'call', side_effect=replies):
                self.assertEqual(island.sample_audio(), {'volume':0, 'has_audio':False, 'muted':False})

    def test_brightness_reads_first_available_device_and_reports_unavailable(self):
        import brightness
        for devices, expected in [
                ([{'id': 'gone', 'available': False}, {'id': 'display', 'available': True, 'percent': 73}],
                 {'has_brightness': True, 'brightness': 73, 'brightness_id': 'display'}),
                ([], {'has_brightness': False, 'brightness': 0, 'brightness_id': ''})]:
            with self.subTest(devices=devices), patch.object(brightness, 'read_state', return_value={'devices': devices}):
                self.assertEqual(island.sample_brightness(), expected)


if __name__ == '__main__': unittest.main()
