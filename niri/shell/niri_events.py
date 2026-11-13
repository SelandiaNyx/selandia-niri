"""Bounded direct IPC and a reconnecting, coalesced Niri desktop event cache.

Protocol: https://niri-wm.github.io/niri/IPC.html
Niri sends complete window/workspace snapshots when a stream connects.
"""
import copy
import json
import os
import socket
import threading
import time

MAX_MESSAGE = 8 * 1024 * 1024


def address():
    path = os.environ.get('NIRI_SOCKET')
    if not path:
        raise OSError('NIRI_SOCKET unavailable')
    return path


def request(value, *, path=None, timeout=3):
    """One request, one bounded reply, with a total (not per-read) deadline."""
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(timeout)
        stream.connect(path or address())
        stream.sendall(json.dumps(value).encode() + b'\n')
        data = bytearray()
        while b'\n' not in data:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Niri reply deadline exceeded')
            stream.settimeout(remaining)
            block = stream.recv(65536)
            if not block:
                raise OSError('Niri closed before replying')
            data.extend(block)
            if len(data) > MAX_MESSAGE:
                raise ValueError('Niri reply too large')
    reply = json.loads(data.split(b'\n', 1)[0])
    if not isinstance(reply, dict) or 'Ok' not in reply:
        raise RuntimeError('Niri rejected request')
    result = reply['Ok']
    if isinstance(value, dict) and result == 'Handled':
        return None
    if not isinstance(value, str) or not isinstance(result, dict) or value not in result:
        raise ValueError('Unexpected Niri response')
    return result[value]


class DesktopState:
    """Apply stream deltas; keep at most the current compositor state."""
    def __init__(self):
        self.windows = {}
        self.workspaces = {}
        self.focus = None
        self.ready = set()

    def apply(self, event):
        if not isinstance(event, dict) or len(event) != 1:
            raise ValueError('Invalid Niri event')
        kind, data = next(iter(event.items()))
        if kind == 'WindowsChanged':
            self.windows = {item['id']: dict(item) for item in data['windows']}
            self.focus = next((item['id'] for item in self.windows.values() if item.get('is_focused')), None)
            self.ready.add('windows')
        elif kind == 'WindowOpenedOrChanged':
            window = dict(data['window'])
            self.windows[window['id']] = window
            if window.get('is_focused'):
                self.focus = window['id']
            elif self.focus == window['id']:
                self.focus = None
        elif kind == 'WindowFocusChanged':
            self.focus = data['id']
        elif kind == 'WindowClosed':
            self.windows.pop(data['id'], None)
            if self.focus == data['id']:
                self.focus = None
        elif kind == 'WorkspacesChanged':
            self.workspaces = {item['id']: dict(item) for item in data['workspaces']}
            self.ready.add('workspaces')
        elif kind == 'WorkspaceActivated':
            target = self.workspaces.get(data['id'])
            if target:
                for item in self.workspaces.values():
                    if item.get('output') == target.get('output'):
                        item['is_active'] = item['id'] == target['id']
                    if data.get('focused'):
                        item['is_focused'] = item['id'] == target['id']
        elif kind == 'WorkspaceUrgencyChanged':
            if data['id'] in self.workspaces:
                self.workspaces[data['id']]['is_urgent'] = data['urgent']
        # Ignore future protocol variants and deltas irrelevant to this bar.

    def snapshot(self):
        return {'available': len(self.ready) == 2,
                'window': copy.deepcopy(self.windows.get(self.focus)),
                'workspaces': copy.deepcopy(list(self.workspaces.values()))}


class DesktopFeed:
    def __init__(self, stopping, *, path=None):
        self.stopping = stopping
        self.path = path
        self.lock = threading.Lock()
        self.value = DesktopState().snapshot()
        self.thread = threading.Thread(target=self.run, name='niri-events', daemon=True)

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def publish(self, state):
        with self.lock:
            self.value = state.snapshot()

    def run(self):
        retry = 1
        while not self.stopping.is_set():
            state = DesktopState()
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
                    stream.settimeout(.5)
                    stream.connect(self.path or address())
                    stream.sendall(b'"EventStream"\n')
                    pending = bytearray()
                    acknowledged = False
                    initial_deadline = time.monotonic() + 5
                    while not self.stopping.is_set():
                        if len(state.ready) < 2 and time.monotonic() > initial_deadline:
                            raise TimeoutError('Niri initial snapshot timed out')
                        try:
                            block = stream.recv(65536)
                        except socket.timeout:
                            continue
                        if not block:
                            raise OSError('Niri event stream closed')
                        pending.extend(block)
                        if len(pending) > MAX_MESSAGE:
                            raise ValueError('Niri event too large')
                        while b'\n' in pending:
                            line, _, rest = pending.partition(b'\n')
                            pending = bytearray(rest)
                            event = json.loads(line)
                            if not acknowledged:
                                if event != {'Ok': 'Handled'}:
                                    raise ValueError('Niri event stream rejected')
                                acknowledged = True
                            else:
                                state.apply(event)
                        self.publish(state)
                        if len(state.ready) == 2:
                            retry = 1
            except (OSError, ValueError, KeyError, TypeError):
                pass
            # Never present stale app/workspace state across a disconnect.
            self.publish(DesktopState())
            if self.stopping.wait(retry):
                break
            retry = min(retry * 2, 8)
