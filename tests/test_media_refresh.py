"""Visible media reads follow invalidations; hiding retires the old subscription."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'niri/shell'))
import media_controls


class View(SimpleNamespace):
    start = media_controls.MediaControls.start
    suspend = media_controls.MediaControls.suspend
    resume = media_controls.MediaControls.resume
    refresh = media_controls.MediaControls.refresh
    schedule_change = media_controls.MediaControls.schedule_change
    dispatch_change = media_controls.MediaControls.dispatch_change


class MediaRefreshTests(unittest.TestCase):
    def setUp(self):
        self.jobs = []
        self.visible = True
        self.panel = SimpleNamespace(alive=True, pending=set(),
            page_visible=lambda _: self.visible,
            work=lambda function, done=None, error=None, **options:
                self.jobs.append((function, done, error, options)))
        self.view = View(panel=self.panel, preferred=None, generation=0,
            loading=False, busy=False, media_changes=None, timer_source=None,
            change_lock=threading.Lock(), change_epoch=0, change_scheduled=False,
            apply_state=Mock(), show_error=Mock(), show_player=Mock())
        self.feed = SimpleNamespace(changed=threading.Event(),
            thread=Mock(ident=7), close=Mock())
        self.feed.changed.set()
        self.create = self.enter(patch.object(media_controls, 'MediaChanges', return_value=self.feed))
        self.timer = self.enter(patch.object(media_controls.GLib, 'timeout_add_seconds', return_value=41))
        self.coalesce = self.enter(patch.object(media_controls.GLib, 'timeout_add', return_value=42))
        self.remove = self.enter(patch.object(media_controls.GLib, 'source_remove'))
        self.read = self.enter(patch.object(media_controls.backend, 'read_state', return_value={'players': []}))

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def finish(self):
        function, done, _error, _options = self.jobs.pop(0)
        result = function()
        if done is not None:
            done(result)

    def test_visible_subscription_uses_thirty_second_calibration_and_reaps_on_hide(self):
        self.view.resume()
        self.view.start()
        self.create.assert_called_once()
        self.feed.thread.start.assert_called_once_with()
        self.timer.assert_called_once_with(30, self.view.refresh)
        self.assertEqual(self.panel.pending, {41})
        self.assertEqual(len(self.jobs), 1)
        self.finish()
        self.read.assert_called_once_with(None)
        callback = self.create.call_args.kwargs['on_change']
        self.view.suspend()
        self.feed.close.assert_called_once_with()
        self.feed.thread.join.assert_not_called()
        self.assertEqual(self.jobs[0][3], {'commit': True})
        self.finish()
        self.feed.thread.join.assert_called_once_with(3)
        self.assertEqual(self.panel.pending, set())
        self.remove.assert_called_once_with(41)
        callback()
        self.coalesce.assert_not_called()

    def test_burst_during_read_is_coalesced_and_followed_by_one_fresh_read(self):
        self.view.resume()
        callback = self.create.call_args.kwargs['on_change']
        self.feed.changed.set()
        for _ in range(100):
            callback()
        self.assertEqual(self.coalesce.call_count, 1)
        epoch = self.view.change_epoch
        self.view.dispatch_change(epoch)
        self.assertEqual(len(self.jobs), 1)
        self.assertTrue(self.feed.changed.is_set())
        self.finish()
        self.assertEqual(self.coalesce.call_count, 2)
        self.view.dispatch_change(epoch)
        self.assertEqual(len(self.jobs), 1)
        self.assertFalse(self.feed.changed.is_set())
        self.finish()
        self.assertEqual(self.read.call_count, 2)

    def test_stale_callback_cannot_read_after_hide_or_clear_a_new_subscription(self):
        self.view.resume()
        self.finish()
        old_epoch = self.view.change_epoch
        self.view.suspend()
        self.finish()
        self.visible = False
        self.view.dispatch_change(old_epoch)
        self.view.refresh()
        self.assertEqual(self.jobs, [])
        self.visible = True
        self.view.resume()
        self.finish()
        self.feed.changed.set()
        self.view.schedule_change(self.view.change_epoch)
        self.assertTrue(self.view.change_scheduled)
        self.view.dispatch_change(old_epoch)
        self.assertTrue(self.view.change_scheduled)
        self.assertEqual(self.read.call_count, 2)

    def test_calibration_still_reads_without_any_signal(self):
        self.view.resume()
        self.finish()
        self.assertFalse(self.feed.changed.is_set())
        self.timer.call_args.args[1]()
        self.finish()
        self.assertEqual(self.read.call_count, 2)

    def test_read_finishing_after_reopen_keeps_new_subscription_invalidation(self):
        replacement = SimpleNamespace(changed=threading.Event(), thread=Mock(ident=8), close=Mock())
        replacement.changed.set()
        self.create.side_effect = [self.feed, replacement]
        self.view.resume()  # The first read remains outstanding across hide/show.
        self.view.suspend()
        cleanup, _done, _error, _options = self.jobs.pop(1)
        cleanup()
        self.view.resume()
        callback = self.create.call_args.kwargs['on_change']
        callback()
        self.view.dispatch_change(self.view.change_epoch)
        self.assertEqual(len(self.jobs), 1)
        self.assertTrue(replacement.changed.is_set())
        self.finish()
        self.assertTrue(self.view.change_scheduled)
        self.view.dispatch_change(self.view.change_epoch)
        self.finish()
        self.assertEqual(self.read.call_count, 2)
        self.assertFalse(replacement.changed.is_set())


if __name__ == '__main__':
    unittest.main()
