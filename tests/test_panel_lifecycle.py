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

    def test_a_window_that_reopens_withdraws_a_pending_finish_request(self):
        """A sticky flag would quit a panel that is in use again.

        This is the regression that made the GTK probe see four unexpected quit
        calls after panels had been opened and closed repeatedly.
        """
        within_task = threading.Event()
        release = threading.Event()

        def task():
            within_task.set()
            release.wait(5)

        panel.Panel.work(self.window, task, commit=True)
        self.assertTrue(within_task.wait(2))
        panel.Panel.on_destroy(self.window)
        self.assertEqual(self.application.quits, 0, "the exit must wait for the commit")
        # A new window appears before the commit ends.
        self.application.tasks.resume()
        release.set()
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(self.application.quits, 0, "a reopened panel must not be quit")
        self.assertEqual(self.application.holds, self.application.releases)

    def test_a_late_callback_never_touches_a_destroyed_widget(self):
        touched = []
        widget = SimpleNamespace(set_text=lambda value: touched.append(value))
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def read():
            entered.set()
            release.wait(5)
            return "value"

        panel.Panel.work(self.window, read, lambda value: widget.set_text(value))
        # A queued read is now correctly discarded after destruction. Exercise
        # the distinct case of an already running read completing afterwards.
        self.assertTrue(entered.wait(2))
        panel.Panel.on_destroy(self.window)
        release.set()
        self.assertTrue(self.wait_for(lambda: bool(self.idle)))
        self.drain()
        self.assertEqual(touched, [])


if __name__ == "__main__":
    unittest.main()


class PanelMonitorTests(unittest.TestCase):
    """A layer surface opens on the focused output, not on Wayland's "primary"."""

    class Monitor:
        def __init__(self, name):
            self.name = name

        def get_geometry(self):
            return SimpleNamespace(width=1920, height=1080)

    def display(self, *, pointer=None, primary="primary", at_point=None, seat=True):
        class Seat:
            def get_pointer(self):
                return pointer

        class Display:
            def get_default_seat(self):
                return Seat() if seat else None

            def get_monitor_at_point(self, x, y):
                return at_point

            def get_primary_monitor(self):
                return self.monitors.get(primary)

            def get_monitor(self, index):
                return self.monitors.get("first")

        display = Display()
        display.monitors = {"primary": self.Monitor("primary"), "first": self.Monitor("first"),
                            "pointer": self.Monitor("pointer"), "at": at_point}
        display.at_point = at_point
        return display

    def test_the_pointer_monitor_wins_when_it_is_known(self):
        # Gdk.Device.get_position() returns (screen, x, y) in GTK 3.
        pointer = SimpleNamespace(get_position=lambda: (None, 10, 20))
        pointer_monitor = self.Monitor("pointer")
        display = self.display(pointer=pointer, at_point=pointer_monitor)
        self.assertIs(panel.panel_monitor(display), pointer_monitor)

    def test_a_missing_monitor_at_the_pointer_falls_back_to_primary(self):
        pointer = SimpleNamespace(get_position=lambda: (None, 10, 20))
        display = self.display(pointer=pointer, at_point=None)
        self.assertEqual(panel.panel_monitor(display).name, "primary")

    def test_a_missing_pointer_falls_back_to_primary(self):
        display = self.display(pointer=None, at_point=self.Monitor("at"))
        self.assertEqual(panel.panel_monitor(display).name, "primary")

    def test_a_broken_seat_never_breaks_the_panel(self):
        display = self.display(seat=False)
        self.assertEqual(panel.panel_monitor(display).name, "primary")

    def test_primary_absent_falls_back_to_the_first_monitor(self):
        display = self.display(pointer=None, primary="absent")
        self.assertEqual(panel.panel_monitor(display).name, "first")

    def test_a_two_element_position_is_tolerated(self):
        pointer = SimpleNamespace(get_position=lambda: (10, 20))
        display = self.display(pointer=pointer, at_point=self.Monitor("at"))
        self.assertEqual(panel.panel_monitor(display).name, "primary")

    def test_a_pointer_without_coordinates_falls_back_to_primary(self):
        class Broken:
            def get_position(self):
                raise TypeError("no coordinates")

        display = self.display(pointer=Broken(), at_point=self.Monitor("at"))
        self.assertEqual(panel.panel_monitor(display).name, "primary")
