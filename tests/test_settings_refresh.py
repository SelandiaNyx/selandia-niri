"""A slow re-read must not overwrite a newer draft (audit A7).

The shipped ``SettingsPage.refresh`` and ``DisplaySettings.refresh`` run against
widget doubles: no GTK window, no display change and no user configuration is
touched. During a read the form and the apply/reset controls are frozen, and a
failed read restores exactly the sensitivity the controls had before, so
constraints such as a custom XKB file are never lifted by a reload.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
from desktop_controls import SettingsPage
from display_controls import DisplaySettings


class Widget:
    def __init__(self, sensitive=True):
        self.sensitive = sensitive

    def get_sensitive(self):
        return self.sensitive

    def set_sensitive(self, value):
        self.sensitive = value


class Notice:
    def __init__(self):
        self.text = ""

    def set_text(self, value):
        self.text = value


def page(**overrides):
    page = SimpleNamespace(
        busy=False, generation=0, frozen={}, group="desktop",
        form=Widget(), apply_button=Widget(), reset_button=Widget(), refresh_button=Widget(),
        notice=Notice(), populated=[], pending_calls=[],
        panel=SimpleNamespace(work=lambda task, done, failed, **options: page.pending_calls.append((done, failed, options))),
    )
    def populate(state):
        # The real populate() re-enables the form and the apply button.
        page.populated.append(state)
        page.form.set_sensitive(True)
        page.apply_button.set_sensitive(True)

    page.populate = populate
    page.frozen_widgets = lambda: SettingsPage.frozen_widgets(page)
    page.restore_frozen = lambda: SettingsPage.restore_frozen(page)
    for key, value in overrides.items():
        setattr(page, key, value)
    return page


class RefreshFreezeTests(unittest.TestCase):
    def test_form_is_frozen_while_a_read_is_in_flight(self):
        subject = page()
        SettingsPage.refresh(subject)
        self.assertFalse(subject.form.get_sensitive(), "the draft stayed editable during a read")
        self.assertFalse(subject.apply_button.get_sensitive())
        self.assertFalse(subject.reset_button.get_sensitive())
        self.assertFalse(subject.refresh_button.get_sensitive())
        self.assertTrue(subject.busy)

    def test_successful_read_releases_the_freeze_and_populates(self):
        subject = page()
        SettingsPage.refresh(subject)
        done, _failed, options = subject.pending_calls[0]
        self.assertEqual(options, {}, "a read is not a side-effecting commit")
        done({"settings": {"gaps": 8}, "saved": {"gaps": 16}})
        self.assertEqual(subject.populated, [{"settings": {"gaps": 8}, "saved": {"gaps": 16}}])
        self.assertTrue(subject.form.get_sensitive())
        self.assertTrue(subject.apply_button.get_sensitive())
        self.assertTrue(subject.refresh_button.get_sensitive())
        self.assertFalse(subject.busy)

    def test_failed_read_restores_the_previous_controls_and_keeps_the_error(self):
        subject = page()
        subject.apply_button.set_sensitive(False)  # e.g. a custom XKB file controls the keyboard
        SettingsPage.refresh(subject)
        _done, failed, _options = subject.pending_calls[0]
        failed("read failed")
        self.assertEqual(subject.populated, [], "a failed read must not populate")
        self.assertTrue(subject.form.get_sensitive())
        self.assertFalse(subject.apply_button.get_sensitive(),
                         "a reload must not re-enable a control the configuration disables")
        self.assertTrue(subject.refresh_button.get_sensitive())
        self.assertIn("read failed", subject.notice.text)

    def test_a_newer_read_wins_and_a_stale_result_is_ignored(self):
        subject = page()
        SettingsPage.refresh(subject)
        stale_done, _failed, _options = subject.pending_calls[0]
        subject.busy = False
        SettingsPage.refresh(subject)  # a newer read started
        stale_done({"settings": {}, "saved": {}})
        self.assertEqual(subject.populated, [], "a stale read replaced a newer draft")

    def test_a_newer_read_keeps_the_freeze_until_it_finishes(self):
        subject = page()
        SettingsPage.refresh(subject)
        _done, failed, _options = subject.pending_calls[0]
        subject.busy = False
        SettingsPage.refresh(subject)
        failed("stale failure")
        self.assertFalse(subject.form.get_sensitive(), "a stale failure released a newer read's freeze")

    def test_a_second_read_is_refused_while_one_is_running(self):
        subject = page()
        SettingsPage.refresh(subject)
        SettingsPage.refresh(subject)
        self.assertEqual(len(subject.pending_calls), 1)


class DisplayRefreshFreezeTests(unittest.TestCase):
    def subject(self):
        return SimpleNamespace(
            loading=False, busy=False, token=None, frozen={},
            form=Widget(), apply_button=Widget(), refresh_button=Widget(), notice=Notice(),
            pending_calls=[],
            panel=SimpleNamespace(work=lambda task, done, failed: self.subject_last.append((done, failed))),
        )

    def setUp(self):
        self.subject_last = []

    def test_form_and_apply_are_frozen_during_the_read(self):
        subject = self.subject()
        DisplaySettings.refresh(subject)
        self.assertFalse(subject.form.get_sensitive())
        self.assertFalse(subject.apply_button.get_sensitive())
        self.assertFalse(subject.refresh_button.get_sensitive())

    def test_failed_read_reports_and_unfreezes(self):
        subject = self.subject()
        subject.form.set_sensitive(True)
        DisplaySettings.refresh(subject)
        _done, failed = self.subject_last[0]
        failed("no outputs")
        self.assertFalse(subject.form.get_sensitive(), "a failed display read must not enable the form")
        self.assertIn("no outputs", subject.notice.text)
        self.assertTrue(subject.refresh_button.get_sensitive())


if __name__ == "__main__":
    unittest.main()
