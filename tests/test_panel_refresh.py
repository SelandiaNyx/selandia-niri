"""Page visibility and coalesced sound refreshes without GTK or host services.

Real Panel/MediaControls methods run against plain widget and job-queue doubles.
Only asynchronous work, audio subscriptions and backend reads are substituted.
"""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'niri/shell'))
import audio_backend
import audio_events
import media_controls
import panel


class WindowDouble(SimpleNamespace):
    page_visible = panel.Panel.page_visible
    refresh_visible_page = panel.Panel.refresh_visible_page
    refresh_audio = panel.Panel.refresh_audio
    tick_audio = panel.Panel.tick_audio
    refresh_metrics = panel.Panel.refresh_metrics
    refresh_control = panel.Panel.refresh_control
    on_destroy = panel.Panel.on_destroy

    def work(self, function, done=None, failed=None, **options):
        self.jobs.append((function, done, failed, options))

    def finish_next(self):
        function, done, _failed, _options = self.jobs.pop(0)
        value = function()
        if done is not None:
            done(value)


class MediaDouble(SimpleNamespace):
    refresh = media_controls.MediaControls.refresh


def subscription():
    changed = threading.Event()
    changed.set()
    return SimpleNamespace(changed=changed, thread=Mock(), close=Mock())


def window(*, page='sound', mapped=True, changes=None):
    result = WindowDouble(
        alive=True, mode='control', mapped=mapped, page=page, jobs=[], pending=set(),
        audio_changes=changes, audio_refresh_at=0, audio_loading=False,
        audio_busy=False, audio_generation=0, audio_advanced=Mock(),
        apply_audio=Mock(), metrics_busy=False,
        metrics_sampler=SimpleNamespace(sample=Mock(return_value={'cpu_percent': 1}), prime=Mock()),
        apply_metrics=Mock(), metrics_error=Mock(), refresh_system_info=Mock(),
        refreshing=False, clock=Mock(), date=Mock(), apply_control=Mock(),
        control_error=Mock(), application=SimpleNamespace(request_finish=Mock()),
    )
    result.audio_advanced.get_active.return_value = False
    result.get_mapped = lambda: result.mapped
    result.control_stack = SimpleNamespace(get_visible_child_name=lambda: result.page)
    result.get_application = lambda: result.application
    result.media_controls = MediaDouble(panel=result, loading=False, busy=False,
        preferred=None, generation=0, apply_state=Mock(), show_error=Mock())
    return result


class PanelRefreshTests(unittest.TestCase):
    def test_hidden_or_unmapped_pages_dispatch_no_reads(self):
        with patch.object(audio_events, 'AudioChanges') as create_subscription, \
                patch.object(audio_backend, 'read_state') as audio_read, \
                patch.object(media_controls.backend, 'read_state') as media_read:
            for mapped, page in ((False, 'sound'), (False, 'system'),
                                 (False, 'quick'), (True, 'wallpapers')):
                with self.subTest(mapped=mapped, page=page):
                    changes = subscription()
                    view = window(mapped=mapped, page=page, changes=changes)
                    view.refresh_audio()
                    view.tick_audio()
                    view.refresh_metrics()
                    view.refresh_control()
                    view.media_controls.refresh()
                    view.refresh_visible_page()
                    self.assertEqual(view.jobs, [])
                    self.assertTrue(changes.changed.is_set())
                    view.metrics_sampler.sample.assert_not_called()
                    view.refresh_system_info.assert_not_called()
            create_subscription.assert_not_called()
            audio_read.assert_not_called()
            media_read.assert_not_called()

        # Mapping a selected page opens only its own refresh path.
        view = window(page='system')
        view.refresh_visible_page()
        self.assertEqual(len(view.jobs), 1)
        view.finish_next()
        view.metrics_sampler.sample.assert_called_once_with()
        view.refresh_system_info.assert_called_once_with()
        view.apply_metrics.assert_called_once_with({'cpu_percent': 1})

        view = window(page='quick')
        view.refresh_visible_page()
        self.assertEqual(len(view.jobs), 2)  # Quick state and media state.
        self.assertTrue(view.refreshing)
        self.assertTrue(view.media_controls.loading)
        self.assertIsNone(view.audio_changes)

    def test_sound_events_coalesce_and_survive_reads_and_busy_controls(self):
        changes = subscription()
        view = window(changes=changes)
        with patch.object(panel.time, 'monotonic', return_value=100), \
                patch.object(audio_backend, 'read_state', return_value={'sinks': []}) as read:
            view.audio_busy = True
            view.tick_audio()
            self.assertEqual(view.jobs, [])
            self.assertTrue(changes.changed.is_set())

            view.audio_busy = False
            view.tick_audio()
            self.assertEqual(len(view.jobs), 1)
            self.assertFalse(changes.changed.is_set())
            self.assertTrue(view.audio_loading)

            # A burst during the outstanding read survives until its completion.
            for _ in range(5):
                changes.changed.set()
                view.tick_audio()
            self.assertEqual(len(view.jobs), 1)
            self.assertTrue(changes.changed.is_set())
            view.finish_next()
            self.assertFalse(view.audio_loading)
            self.assertTrue(changes.changed.is_set())

            # Device actions also retain the pending event instead of clearing it.
            view.audio_busy = True
            view.tick_audio()
            self.assertEqual(view.jobs, [])
            self.assertTrue(changes.changed.is_set())
            view.audio_busy = False
            view.tick_audio()
            self.assertEqual(len(view.jobs), 1)
            self.assertFalse(changes.changed.is_set())
            view.finish_next()
            view.tick_audio()
            self.assertEqual(view.jobs, [])
            self.assertEqual(read.call_count, 2)
            self.assertEqual(view.apply_audio.call_count, 2)

    def test_sound_calibration_reads_after_thirty_seconds_without_events(self):
        changes = subscription()
        view = window(changes=changes)
        with patch.object(panel.time, 'monotonic', return_value=100) as now, \
                patch.object(audio_backend, 'read_state', return_value={}) as read:
            view.tick_audio()
            view.finish_next()
            self.assertEqual(view.audio_refresh_at, 130)
            self.assertFalse(changes.changed.is_set())
            now.return_value = 129.99
            view.tick_audio()
            self.assertEqual(view.jobs, [])
            now.return_value = 130
            view.tick_audio()
            self.assertEqual(len(view.jobs), 1)
            view.finish_next()
            self.assertEqual(read.call_count, 2)
            self.assertEqual(view.audio_refresh_at, 160)

    def test_first_visible_sound_read_starts_one_subscription_and_reuses_it(self):
        changes = subscription()
        view = window(mapped=False)
        with patch.object(audio_events, 'AudioChanges', return_value=changes) as create, \
                patch.object(audio_backend, 'read_state', return_value={}) as read:
            view.refresh_audio()
            create.assert_not_called()
            view.mapped = True
            view.refresh_audio()
            create.assert_called_once()
            self.assertIsInstance(create.call_args.args[0], threading.Event)
            self.assertEqual(create.call_args.kwargs, {'facilities': (
                'sink', 'source', 'server', 'card', 'sink-input', 'source-output')})
            changes.thread.start.assert_called_once_with()
            view.finish_next()
            view.refresh_audio()
            view.finish_next()
            create.assert_called_once()
            changes.thread.start.assert_called_once_with()
            self.assertEqual(read.call_count, 2)
            read.assert_called_with(include_unavailable=False)

    def test_close_schedules_worker_cleanup_without_joining_on_ui_thread(self):
        changes = subscription()
        view = window(changes=changes)
        view.pending = {41, 42}
        with patch.object(panel.GLib, 'source_remove') as remove:
            view.on_destroy()
        self.assertFalse(view.alive)
        changes.close.assert_called_once_with()
        changes.thread.join.assert_not_called()
        self.assertEqual(len(view.jobs), 1)
        self.assertEqual(view.jobs[0][3], {'commit': True})
        self.assertEqual({call.args[0] for call in remove.call_args_list}, {41, 42})
        self.assertEqual(view.pending, set())
        view.application.request_finish.assert_called_once_with()
        view.finish_next()
        changes.thread.join.assert_called_once_with(3)
        self.assertEqual(view.tick_audio(), panel.GLib.SOURCE_REMOVE)

    def test_system_read_queued_before_hide_does_not_sample_or_stick_busy(self):
        view = window(page='system')
        view.refresh_metrics()
        view.page = 'quick'
        view.metrics_generation = 1
        view.finish_next()
        view.metrics_sampler.sample.assert_not_called()
        view.apply_metrics.assert_not_called()
        self.assertFalse(view.metrics_busy)

    def test_reopened_system_replaces_stale_queued_read_with_fresh_baseline(self):
        view = window(page='system')
        view.refresh_metrics()
        view.metrics_generation = 1  # Hide and reopen before the queued read ran.
        view.finish_next()
        self.assertEqual(len(view.jobs), 1)
        view.metrics_sampler.sample.assert_not_called()
        view.finish_next()
        view.metrics_sampler.prime.assert_called_once_with()
        view.metrics_sampler.sample.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
