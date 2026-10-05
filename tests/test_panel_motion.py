"""Animation lifetimes and accessibility, without a real desktop or wall-clock sleeps."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("panel_motion", Path(__file__).resolve().parents[1]
                                            / "niri/shell/panel_motion.py")
motion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(motion)


class FakeWidget:
    def __init__(self):
        self.opacity = 1.0
        self.animations = True
        self.mapped = True
        self.callbacks = {}
        self.handlers = {}
        self.sequence = 0
        self.time_us = 0

    def get_settings(self):
        return self

    def get_property(self, key):
        assert key == "gtk-enable-animations"
        return self.animations

    def get_opacity(self):
        return self.opacity

    def set_opacity(self, value):
        self.opacity = value

    def get_mapped(self):
        return self.mapped

    def connect(self, signal, callback):
        assert signal == "destroy"
        self.sequence += 1
        self.handlers[self.sequence] = callback
        return self.sequence

    def disconnect(self, identifier):
        del self.handlers[identifier]

    def add_tick_callback(self, callback):
        self.sequence += 1
        self.callbacks[self.sequence] = callback
        return self.sequence

    def remove_tick_callback(self, identifier):
        del self.callbacks[identifier]

    def get_frame_time(self):
        return self.time_us

    def frame(self, milliseconds):
        self.time_us = int(milliseconds * 1000)
        for identifier, callback in tuple(self.callbacks.items()):
            if not callback(self, self):
                self.callbacks.pop(identifier, None)

    def destroy(self):
        for callback in tuple(self.handlers.values()):
            callback(self)


class PanelMotionTests(unittest.TestCase):
    def setUp(self):
        self.widget = FakeWidget()
        self.motion = motion.PanelMotion(self.widget)

    def test_open_starts_at_first_frame_and_finishes_without_a_timer(self):
        self.motion.reveal()
        self.assertEqual(self.widget.opacity, 0)
        self.widget.frame(4000)
        self.assertEqual(self.widget.opacity, 0)
        self.widget.frame(4090)
        self.assertAlmostEqual(self.widget.opacity, 0.875)
        self.widget.frame(4180)
        self.assertEqual(self.widget.opacity, 1)
        self.assertFalse(self.motion.running)
        self.assertFalse(self.widget.callbacks)

    def test_close_callback_runs_once_after_final_frame(self):
        closed = []
        self.motion.dismiss(lambda: closed.append(self.widget.opacity))
        self.widget.frame(0)
        self.widget.frame(90)
        self.assertFalse(closed)
        self.widget.frame(180)
        self.widget.frame(360)
        self.assertEqual(closed, [0])

    def test_reverse_close_while_opening_does_not_jump_or_extend_duration(self):
        self.motion.reveal()
        self.widget.frame(0)
        self.widget.frame(90)
        before = self.widget.opacity
        closed = []
        self.motion.dismiss(lambda: closed.append(True))
        self.assertEqual(self.widget.opacity, before)
        self.assertEqual(len(self.widget.callbacks), 1)
        self.widget.frame(90)
        self.widget.frame(90 + 180 * before)
        self.assertEqual(closed, [True])

    def test_reopening_cancels_pending_close_completion(self):
        self.motion.reveal()
        self.widget.frame(0)
        self.widget.frame(180)
        closed = []
        self.motion.dismiss(lambda: closed.append(True))
        self.widget.frame(200)
        self.widget.frame(250)
        before = self.widget.opacity
        self.motion.reveal()
        self.assertEqual(self.widget.opacity, before)
        self.widget.frame(250)
        self.widget.frame(1000)
        self.assertEqual(self.widget.opacity, 1)
        self.assertFalse(closed)

    def test_gtk_reduced_motion_completes_immediately(self):
        self.widget.animations = False
        self.motion.reveal()
        self.assertEqual(self.widget.opacity, 1)
        self.assertFalse(self.widget.callbacks)
        closed = []
        self.motion.dismiss(lambda: closed.append(True))
        self.assertEqual(closed, [True])
        self.assertFalse(self.widget.callbacks)

    def test_local_setting_can_disable_motion_but_not_override_accessibility(self):
        self.motion.dispose()
        self.motion = motion.PanelMotion(self.widget, enabled=False)
        self.motion.reveal()
        self.assertFalse(self.widget.callbacks)
        self.motion.dispose()
        self.widget.animations = False
        self.motion = motion.PanelMotion(self.widget, enabled=True)
        self.motion.reveal()
        self.assertFalse(self.widget.callbacks)

    def test_preference_change_during_animation_finishes_next_frame(self):
        preference = [True]
        self.motion.dispose()
        self.motion = motion.PanelMotion(self.widget, enabled=lambda: preference[0])
        self.motion.reveal()
        self.widget.frame(0)
        preference[0] = False
        self.widget.frame(30)
        self.assertEqual(self.widget.opacity, 1)
        self.assertFalse(self.widget.callbacks)

    def test_destroy_cancels_pending_callback_and_releases_widget_handler(self):
        closed = []
        self.motion.dismiss(lambda: closed.append(True))
        self.widget.destroy()
        self.widget.frame(300)
        self.motion.reveal()
        self.assertFalse(closed)
        self.assertFalse(self.widget.callbacks)
        self.assertFalse(self.widget.handlers)

    def test_completion_may_destroy_widget_without_removing_same_source_twice(self):
        self.motion.dismiss(self.widget.destroy)
        self.widget.frame(0)
        self.widget.frame(180)
        self.assertFalse(self.widget.callbacks)
        self.assertFalse(self.widget.handlers)

    def test_completion_can_schedule_another_animation(self):
        self.motion.reveal()
        self.widget.frame(0)
        self.widget.frame(180)
        self.motion.dismiss(self.motion.reveal)
        self.widget.frame(200)
        self.widget.frame(380)
        self.assertEqual(len(self.widget.callbacks), 1)
        self.widget.frame(400)
        self.widget.frame(580)
        self.assertEqual(self.widget.opacity, 1)
        self.assertFalse(self.widget.callbacks)

    def test_closing_before_map_never_waits_for_a_nonexistent_frame_clock(self):
        self.widget.mapped = False
        self.motion.reveal()
        closed = []
        self.motion.dismiss(lambda: closed.append(True))
        self.assertEqual(closed, [True])
        self.assertFalse(self.widget.callbacks)

    def test_stalled_or_backward_frame_time_remains_bounded(self):
        self.motion.reveal()
        self.widget.frame(100)
        self.widget.frame(90)
        self.assertEqual(self.widget.opacity, 0)
        self.widget.frame(10000)
        self.assertEqual(self.widget.opacity, 1)

    def test_zero_duration_completes_synchronously(self):
        self.motion.dispose()
        self.motion = motion.PanelMotion(self.widget, duration_ms=0)
        self.motion.reveal()
        self.assertEqual(self.widget.opacity, 1)
        self.assertFalse(self.widget.callbacks)


if __name__ == "__main__":
    unittest.main()
