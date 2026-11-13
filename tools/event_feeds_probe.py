#!/usr/bin/env python3
"""Exercise the actual island process with private audio/MPRIS fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import media_probe
from media_probe import backend, Gio, GLib

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / '.validation/event-feeds-20261014'
media_probe.XML = media_probe.XML.replace(
    '<property name="PlaybackStatus"',
    '<property name="Position" type="x" access="read"/>'
    '<property name="Rate" type="d" access="read"/>'
    '<property name="PlaybackStatus"')


class Player(media_probe.FakePlayers):
    def __init__(self):
        super().__init__(single=True)
        self.reads = 0
        self.position = 10_000_000
        self.rate = 1.
        self.title = 'Event-driven track'

    def property(self, entry, prop):
        if prop == 'PlaybackStatus': self.reads += 1
        if prop == 'Position': return GLib.Variant('x', self.position)
        if prop == 'Rate': return GLib.Variant('d', self.rate)
        if prop == 'Metadata':
            return GLib.Variant('a{sv}', {'xesam:title': GLib.Variant('s', self.title),
                'mpris:length': GLib.Variant('x', 100_000_000)})
        return super().property(entry, prop)

    def changed(self, *, seek=False):
        connection = self.entries[0]['connection']
        if seek:
            connection.emit_signal(None, backend.PATH, backend.PLAYER_INTERFACE, 'Seeked',
                                   GLib.Variant('(x)', (self.position,)))
        else:
            connection.emit_signal(None, backend.PATH, backend.PROPERTIES, 'PropertiesChanged',
                GLib.Variant('(sa{sv}as)', (backend.PLAYER_INTERFACE, {}, ['Metadata', 'PlaybackStatus', 'Rate'])))
        connection.flush_sync(None)


def wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.02)
    assert predicate(), 'event bridge did not update within deadline'


def main():
    media_probe.check_private_bus()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    player = Player(); player.start()
    try:
        with tempfile.TemporaryDirectory(prefix='selandia-event-fixture-') as temporary:
            root = Path(temporary)
            (root / 'volume').write_text('30')
            (root / 'mute').write_text('no')
            os.mkfifo(root / 'audio-events', 0o600)
            pipe = os.open(root / 'audio-events', os.O_RDWR | os.O_NONBLOCK)
            script = root / 'pactl'
            script.write_text('#!' + sys.executable + '\n' + '''import os,sys
from pathlib import Path
root=Path(__file__).resolve().parent
if sys.argv[1:]==['subscribe']:
    (root/'subscriber').write_text(str(os.getpid()))
    with (root/'audio-events').open('rb',buffering=0) as stream:
        while line:=stream.readline():
            sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
elif sys.argv[1:]==['get-sink-volume','@DEFAULT_SINK@']:
    with (root/'queries').open('a') as log:log.write('read\\n')
    print('Volume: front-left: 32768 / '+(root/'volume').read_text()+'% / -6.02 dB')
elif sys.argv[1:]==['get-sink-mute','@DEFAULT_SINK@']:
    with (root/'queries').open('a') as log:log.write('mute\\n')
    print('Mute: '+(root/'mute').read_text())
else:raise SystemExit('Unexpected fixture command')
''')
            script.chmod(0o700)
            values = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'])
            snapshot = Path(values['XDG_RUNTIME_DIR']) / ('selandia-island-' +
                hashlib.sha256(values['NIRI_SOCKET'].encode()).hexdigest()[:20] + '.json')
            def state():
                try: return json.loads(snapshot.read_text())
                except (OSError, ValueError): return {}
            def reads():
                return len((root / 'queries').read_text().splitlines()) if (root / 'queries').exists() else 0
            with (ARTIFACTS / 'island-stream.jsonl').open('w') as output, (ARTIFACTS / 'island-stderr.log').open('w') as errors:
                process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'niri/shell/island.py'), 'listen'],
                    env=values, stdout=output, stderr=errors)
                try:
                    wait(lambda: state().get('media') and state().get('volume') == 30 and state().get('has_progress'))
                    time.sleep(.6)
                    baseline = (reads(), player.reads)
                    progress_before = state()['progress']
                    time.sleep(3)
                    assert (reads(), player.reads) == baseline, (baseline, reads(), player.reads)
                    assert state()['progress'] > progress_before, state()
                    quiet = {'seconds': 3, 'audio_queries': 0, 'player_reads': 0, 'progress_advanced': True}
                    # Unrelated audio notifications do not cause a read.
                    os.write(pipe, b"Event 'change' on sink-input #7\n")
                    time.sleep(.4); assert reads() == baseline[0]
                    assert state()['muted'] is False
                    for muted in (True, False):
                        (root / 'mute').write_text('yes' if muted else 'no')
                        os.write(pipe, b"Event 'change' on sink #1\n")
                        wait(lambda: state().get('muted') is muted and state().get('kind') == 'volume', 2)
                        assert state()['volume'] == 30
                        assert ('Muted' in state()['title'] or '已静音' in state()['title']) == muted, state()
                        if not muted: assert '30%' in state()['title']
                    (root / 'volume').write_text('73')
                    started = time.monotonic()
                    os.write(pipe, b"Event 'change' on sink #1\n")
                    wait(lambda: state().get('volume') == 73, 2)
                    audio_latency = time.monotonic() - started
                    assert state()['kind'] == 'volume'
                    player.position = 70_000_000; player.changed(seek=True)
                    wait(lambda: 70 <= state().get('progress', 0) < 75, 2)
                    player.entries[0]['status'] = 'Paused'; player.changed()
                    wait(lambda: state().get('playing') is False, 2)
                    paused = state()['progress']; time.sleep(1.2)
                    assert state()['progress'] == paused
                    player.title = 'New track · 新曲'; player.position = 0; player.rate = 2
                    player.entries[0]['status'] = 'Playing'; player.changed()
                    wait(lambda: state().get('media_title') == player.title and state().get('playing'), 2)
                    player.close()
                    wait(lambda: state().get('media') is False and state().get('has_progress') is False, 2)
                    report = {'quiet_playback': quiet, 'audio_event_latency_seconds': audio_latency,
                              'mute_and_unmute_without_volume_change': True,
                              'seek_pause_track_change_owner_exit': True, 'isolated': True}
                finally:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=3); raise
                    os.close(pipe)
                assert process.returncode == 0, process.returncode
                pid = int((root / 'subscriber').read_text())
                assert not Path(f'/proc/{pid}').exists(), 'audio subscription child survived island exit'
                report['clean_process_exit'] = True
                (ARTIFACTS / 'event-feeds.json').write_text(json.dumps(report, indent=2) + '\n')
                print('PASS actual island: quiet playback without polling; sink events, seek, pause, track and owner changes; clean exit')
    finally:
        if player.thread.is_alive(): player.close()


if __name__ == '__main__': main()
