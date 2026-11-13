"""Bounded, idle-expiring daemon workers for disposable interface reads.

Settings writes deliberately bypass this pool: closing a view must not cancel a
transaction or its rollback. No worker exists until the first read is submitted.
"""
from collections import deque
import threading


class ReadPool:
    def __init__(self, workers=3, max_pending=64, idle_seconds=10):
        if workers < 1 or max_pending < 1 or idle_seconds <= 0:
            raise ValueError("invalid read pool limits")
        self.limit, self.max_pending, self.idle_seconds = workers, max_pending, idle_seconds
        self._condition = threading.Condition()
        self._queue = deque()
        self._workers = self._active = self._sequence = 0
        self._closed = False

    def submit(self, task, *, valid=lambda: True):
        with self._condition:
            if self._closed:
                raise RuntimeError("read pool is closed")
            self._queue = deque(item for item in self._queue if item[1]())
            if len(self._queue) >= self.max_pending:
                raise RuntimeError("too many pending interface reads")
            self._queue.append((task, valid))
            if self._workers < min(self.limit, self._active + len(self._queue)):
                self._workers += 1
                self._sequence += 1
                thread = threading.Thread(target=self._run, daemon=True,
                                          name=f"interface-read-{self._sequence}")
                try:
                    thread.start()
                except RuntimeError:
                    self._workers -= 1
                    self._queue.pop()
                    raise
            self._condition.notify()

    def _run(self):
        with self._condition:
            while True:
                if not self._queue:
                    if self._closed:
                        self._workers -= 1
                        self._condition.notify_all()
                        return
                    self._condition.wait_for(lambda: self._queue or self._closed,
                                             timeout=self.idle_seconds)
                    if not self._queue:
                        self._workers -= 1
                        self._condition.notify_all()
                        return
                task, valid = self._queue.popleft()
                self._active += 1
                self._condition.release()
                try:
                    if valid():
                        task()
                except Exception:
                    # Panel.work translates task failures into main-thread
                    # callbacks. A faulty client must not permanently lose a slot.
                    pass
                finally:
                    self._condition.acquire()
                    self._active -= 1
                    self._condition.notify_all()

    def close(self):
        """Discard queued reads; already running reads may complete normally."""
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._condition.notify_all()


READ_POOL = ReadPool()
