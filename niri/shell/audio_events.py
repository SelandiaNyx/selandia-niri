"""Coalesced PulseAudio changes for the top bar and visible sound controls.

One bounded ``pactl subscribe`` child is owned entirely by :meth:`AudioChanges.run`;
callers only start the thread and later ``close()`` it while joining.
"""
import os
import re
import select
import subprocess
import threading
import time

COMMAND = ['pactl', 'subscribe']
MAX_LINE = 4096
READ_SIZE = 65536
POLL = 0.25
MIN_BACKOFF = 1.0
MAX_BACKOFF = 10.0


class AudioChanges:
    def __init__(self, stopping, *, command=None, facilities=('sink', 'server')):
        self.stopping = stopping
        names = '|'.join(re.escape(name) for name in facilities)
        self.event = re.compile(r"^Event '(?:new|change|remove)' on (?:" + names + r") #\d+$") if names else re.compile(r'(?!)')
        self.command = list(command) if command else list(COMMAND)
        self.closed = threading.Event()
        self.changed = threading.Event()
        self.changed.set()
        self.connected = False
        self.child = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, name='audio-events', daemon=True)

    def done(self):
        return self.stopping.is_set() or self.closed.is_set()

    def close(self):
        """Signal the worker to stop; terminating the child only wakes its reader."""
        self.closed.set()
        with self.lock:
            child = self.child
        if child is not None and child.poll() is None:
            try:
                child.terminate()
            except OSError:
                pass

    def read(self, child):
        """Drain stdout until stop/EOF, coalescing matching lines into ``changed``."""
        stream, data, discard, received = child.stdout, b'', False, False
        while not self.done() and child.poll() is None:
            try:
                ready, _, _ = select.select([stream], [], [], POLL)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                block = stream.read1(READ_SIZE)
            except (OSError, ValueError):
                break
            if not block:
                break
            received = True
            data += block
            while True:
                index = data.find(b'\n')
                if index < 0:
                    break
                raw, data = data[:index], data[index + 1:]
                if discard:
                    discard = False
                elif len(raw) <= MAX_LINE and self.event.fullmatch(raw.decode('utf-8', 'replace').strip()):
                    self.changed.set()
            if len(data) > MAX_LINE:
                # Oversized partial line: drop it and ignore its tail as well.
                data, discard = b'', True
        return received

    def reap(self):
        """Worker-only teardown: terminate, bounded wait, kill, bounded wait."""
        with self.lock:
            child, self.child = self.child, None
        self.connected = False
        if child is None:
            return
        try:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill()
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
            else:
                child.wait()
        except OSError:
            pass
        if child.stdout is not None:
            child.stdout.close()

    def run(self):
        delay = MIN_BACKOFF
        while not self.done():
            received = False
            try:
                child = subprocess.Popen(self.command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False,
                    env=dict(os.environ, LC_ALL='C.UTF-8'))
                with self.lock:
                    self.child = child
                self.connected = True
                self.changed.set()
                received = self.read(child)
            except OSError:
                pass
            finally:
                self.reap()
                self.changed.set()
            if self.done():
                break
            if received:
                delay = MIN_BACKOFF
            deadline = time.monotonic() + delay
            while not self.done() and time.monotonic() < deadline:
                self.closed.wait(min(POLL, max(0.0, deadline - time.monotonic())))
            delay = min(delay * 2, MAX_BACKOFF)
