"""A closing window must never truncate a settings transaction (audit A2).

The check drives the shipped ``Panel.work`` / ``Panel.on_destroy`` code with a
test double for the widgets and for ``GLib.idle_add``, so no GTK window, lock,
sleep or hardware action is involved. Only side-effecting ("commit") tasks are
allowed to keep the application alive; read-only tasks end with the process.
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import panel


class FakeApplication:
    def __init__(self):
        self.tasks = panel.Tasks(self)
        self.holds = 0
        self.releases = 0
        self.quits = 0

    def hold(self):
        self.holds += 1

    def release(self):
        self.releases += 1

    def quit(self):
        self.quits += 1

    def request_finish(self):
        if self.tasks.request_finish():
            self.quit()


class PanelLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.idle = []
        patcher = patch.object(panel.GLib, "idle_add", self._idle_add)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.application = FakeApplication()
        self.window = SimpleNamespace(alive=True, pending=set(), get_application=lambda: self.application,
                                      feedback=lambda *arguments, **options: None)

    def _idle_add(self, callback, *arguments):
        self.idle.append((callback, arguments))
        return len(self.idle)

    def drain(self):
        while self.idle:
            callback, arguments = self.idle.pop(0)
            callback(*arguments)

    def wait_for(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(.01)
        return False

    def test_commit_task_completes_after_the_window_is_destroyed(self):
        phases = []
        within_task = threading.Event()

        def task():
            phases.append("write_one")
            within_task.set()
            time.sleep(.2)
            try:
                phases.append("write_two")
            finally:
                phases.append("finally")

        panel.Panel.work(self.window, task, commit=True)
        self.assertTrue(within_task.wait(2))
        panel.Panel.on_destroy(self.window)
        # Closing the window must not end the transaction.
        self.assertEqual(self.application.quits, 0)
        self.assertFalse(self.window.alive)
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(phases, ["write_one", "write_two", "finally"])
        self.assertEqual(self.application.quits, 1)
        self.assertEqual(self.application.holds, 1)
        self.assertEqual(self.application.releases, 1)

    def test_several_commits_keep_the_application_alive_until_the_last_one(self):
        started = [threading.Event(), threading.Event()]
        release = [threading.Event(), threading.Event()]
        finished = []

        def task(index):
            def run():
                started[index].set()
                release[index].wait(5)
                finished.append(index)
            return run

        for index in (0, 1):
            panel.Panel.work(self.window, task(index), commit=True)
        self.assertTrue(all(event.wait(2) for event in started))
        panel.Panel.on_destroy(self.window)
        release[0].set()
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(self.application.quits, 0, "one unfinished commit must still block the exit")
        release[1].set()
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(sorted(finished), [0, 1])
        self.assertEqual(self.application.quits, 1)

    def test_read_only_task_never_holds_the_application(self):
        panel.Panel.work(self.window, lambda: "state", commit=False)
        panel.Panel.on_destroy(self.window)
        self.assertEqual(self.application.holds, 0)
        self.assertEqual(self.application.quits, 1)

    def test_destroyed_window_receives_no_completion_callback(self):
        seen = []
        errors = []
        within_task = threading.Event()

        def failing():
            within_task.set()
            raise RuntimeError("rollback finished")

        panel.Panel.work(self.window, failing, lambda value: seen.append(value),
                         lambda error: errors.append(error), commit=True)
        self.assertTrue(within_task.wait(2))
        panel.Panel.on_destroy(self.window)
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(seen, [])
        self.assertEqual(errors, [])
        # The failure still released its hold exactly once, so the app can exit.
        self.assertEqual(self.application.quits, 1)
        self.assertEqual(self.application.holds, 1)
        self.assertEqual(self.application.releases, 1)

    def test_a_late_callback_never_touches_a_destroyed_widget(self):
        touched = []
        widget = SimpleNamespace(set_text=lambda value: touched.append(value))
        panel.Panel.work(self.window, lambda: "value", lambda value: widget.set_text(value))
        panel.Panel.on_destroy(self.window)
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(touched, [])


if __name__ == "__main__":
    unittest.main()
