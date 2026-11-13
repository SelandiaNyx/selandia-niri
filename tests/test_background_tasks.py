"""Actual worker concurrency and disposed-view behavior, without a display."""
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'niri/shell'))
from background_tasks import ReadPool


class ReadPoolTests(unittest.TestCase):
    def pool(self, **kwargs):
        pool = ReadPool(**kwargs)
        self.addCleanup(pool.close)
        return pool

    def test_concurrency_is_bounded_and_queued_reads_eventually_complete(self):
        pool = self.pool(workers=3)
        release = threading.Event()
        self.addCleanup(release.set)
        condition = threading.Condition()
        active = peak = finished = 0
        def task():
            nonlocal active, peak, finished
            with condition:
                active += 1
                peak = max(active, peak)
                condition.notify_all()
            release.wait(2)
            with condition:
                active -= 1
                finished += 1
                condition.notify_all()
        for _ in range(9):
            pool.submit(task)
        with condition:
            self.assertTrue(condition.wait_for(lambda: active == 3, 2))
        self.assertEqual(peak, 3)
        release.set()
        with condition:
            self.assertTrue(condition.wait_for(lambda: finished == 9, 2))
        self.assertEqual(peak, 3)

    def test_disposed_owner_is_skipped_and_queue_capacity_is_bounded(self):
        pool = self.pool(workers=1, max_pending=1)
        started, release, done = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        pool.submit(lambda: (started.set(), release.wait(2)))
        self.assertTrue(started.wait(2))
        alive = [True]
        pool.submit(lambda: self.fail('disposed read ran'), valid=lambda: alive[0])
        with self.assertRaises(RuntimeError):
            pool.submit(lambda: None)
        alive[0] = False
        pool.submit(done.set)
        release.set()
        self.assertTrue(done.wait(2))

    def test_workers_expire_and_can_restart_after_idle(self):
        pool = self.pool(workers=1, idle_seconds=.02)
        done = threading.Event()
        pool.submit(done.set)
        self.assertTrue(done.wait(2))
        with pool._condition:
            self.assertTrue(pool._condition.wait_for(lambda: pool._workers == 0, 2))
        done.clear()
        pool.submit(done.set)
        self.assertTrue(done.wait(2))

    def test_task_exception_does_not_lose_worker_and_close_rejects_new_reads(self):
        pool = self.pool(workers=1)
        def fail():
            raise ValueError('failed read')
        done = threading.Event()
        pool.submit(fail)
        pool.submit(done.set)
        self.assertTrue(done.wait(2))
        pool.close()
        with self.assertRaises(RuntimeError):
            pool.submit(lambda: None)

    def test_completion_notification_does_not_destroy_idle_workers(self):
        pool = self.pool(workers=1, idle_seconds=.5)
        done = threading.Event()
        pool.submit(done.set)
        self.assertTrue(done.wait(2))
        with pool._condition:
            pool._condition.notify_all()
            expired = pool._condition.wait_for(lambda: pool._workers == 0, .05)
        self.assertFalse(expired)
