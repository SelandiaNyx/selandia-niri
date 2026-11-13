"""Notification preview policy: suppression, bypass, replacement, durations."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import notification_policy as policy


def notification(summary="Summary", body="Body", icon="icon", replaces_id=0, hints=None, timeout=-1):
    return ("app", replaces_id, icon, summary, body, [], hints if hints is not None else {}, timeout)


class NotificationPolicyTest(unittest.TestCase):
    def test_visibility_rule_blocks_critical_and_closes_only_matching_replacement(self):
        events=[]; p=policy.Policy(events.append);p.update(available=True)
        p.notify(1,notification(hints={'urgency':2}))
        p.notify(2,notification(hints={'urgency':2,'SWAYNC_BYPASS_DND':True}),visible=False)
        self.assertEqual(len(events),1)
        p.notify(1,notification(replaces_id=1,hints={'urgency':2}),visible=False)
        self.assertEqual(events[-1],{'action':'notification-close','notification_id':1})

    def test_new_defaults_do_not_replay_or_close_existing_previews(self):
        events=[];p=policy.Policy(events.append);p.update(available=True)
        p.notify(1,notification());previous=list(events)
        p.configure({'timeout':1,'timeout-low':2})
        self.assertEqual(events,previous)
        p.notify(2,notification());self.assertEqual(events[-1]['duration'],1)
        p.notify(3,notification(hints={'urgency':0}));self.assertEqual(events[-1]['duration'],2)

    def setUp(self):
        self.events = []
        self.policy = policy.Policy(self.events.append)

    def actions(self):
        return [event["action"] for event in self.events]

    def test_unavailable_suppresses_and_never_replays(self):
        self.policy.notify(1, notification())
        self.policy.update(available=True)
        self.assertEqual(self.events, [])
        self.policy.notify(1, notification())
        self.assertEqual(self.actions(), ["notification"])
        self.policy.update(available=False)
        self.assertEqual(self.actions(), ["notification", "notification-close"])
        self.policy.update(available=True)
        self.assertEqual(self.actions(), ["notification", "notification-close"])
        self.assertIsNone(self.policy.active_id)

    def test_dnd_and_inhibitor_close_active_and_suppress_new_previews(self):
        self.policy.update(available=True)
        self.policy.notify(1, notification())
        self.policy.update(available=True, dnd=True)
        self.assertEqual(self.events[-1], {"action": "notification-close", "notification_id": 1})
        self.assertIsNone(self.policy.active_id)
        self.policy.notify(2, notification())
        self.policy.update(available=True, inhibited=True)
        self.policy.notify(3, notification())
        self.assertEqual(self.actions(), ["notification", "notification-close"])

    def test_critical_urgency_alone_bypasses_dnd_and_inhibitors(self):
        self.policy.update(available=True, dnd=True, inhibited=True)
        self.policy.notify(1, notification(hints={"urgency": 2}))
        self.assertEqual(self.actions(), ["notification"])
        self.assertEqual(self.policy.active_id, 1)
        self.assertTrue(self.policy.active_bypass)
        # Restating DND/inhibitors must not withdraw the critical preview.
        self.policy.update(available=True, dnd=True, inhibited=True)
        self.assertEqual(self.actions(), ["notification"])
        # Without critical urgency or a bypass hint nothing gets through.
        self.policy.notify(2, notification())
        self.policy.notify(3, notification(hints={"urgency": 1}))
        self.assertEqual(self.actions(), ["notification"])

    def test_bypass_hint_alone_bypasses_dnd_for_an_ordinary_notification(self):
        self.policy.update(available=True, dnd=True)
        self.policy.notify(1, notification(hints={"SWAYNC_BYPASS_DND": True}))
        self.assertEqual(self.actions(), ["notification"])
        self.assertEqual(self.policy.active_id, 1)
        self.assertTrue(self.policy.active_bypass)
        self.events.clear()
        self.policy.notify(2, notification(hints={"SWAYNC_BYPASS_DND": 1}))
        self.assertEqual(self.actions(), ["notification"])
        self.assertEqual(self.policy.active_id, 2)
        self.events.clear()
        # A bypassed ordinary preview also survives inhibitors.
        self.policy.update(available=True, dnd=True, inhibited=True)
        self.assertEqual(self.actions(), [])

    def test_malformed_bypass_hints_are_rejected(self):
        self.policy.update(available=True, dnd=True)
        for value in ("1", 1.0, 2, 0, False, None, [], {}):
            self.policy.notify(1, notification(hints={"SWAYNC_BYPASS_DND": value}))
        self.assertEqual(self.events, [])
        self.assertIsNone(self.policy.active_id)
        self.policy.notify(1, notification(hints={"SWAYNC_BYPASS_DND": True}))
        self.assertEqual(self.actions(), ["notification"])

    def test_lowercase_bypass_hint_does_not_bypass_a_normal_notification(self):
        self.policy.update(available=True, dnd=True)
        self.policy.notify(1, notification(hints={"swaync-bypass-dnd": True}))
        self.policy.notify(2, notification(hints={"swaync-bypass-dnd": 1}))
        self.assertEqual(self.events, [])
        self.policy.notify(3, notification(hints={"SWAYNC_BYPASS_DND": True}))
        self.assertEqual(self.actions(), ["notification"])

    def test_control_center_blocks_critical_and_bypass_previews(self):
        self.policy.update(available=True)
        self.policy.notify(1, notification(hints={"urgency": 2}))
        self.policy.update(available=True, cc_open=True)
        self.assertEqual(self.actions(), ["notification", "notification-close"])
        self.policy.notify(2, notification(hints={"urgency": 2}))
        self.policy.notify(3, notification(hints={"SWAYNC_BYPASS_DND": True}))
        self.assertEqual(self.actions(), ["notification", "notification-close"])
        self.assertIsNone(self.policy.active_id)
        self.assertFalse(self.policy.active_bypass)

    def test_suppressed_replacement_closes_the_active_critical_preview(self):
        # Start from a live critical preview that bypassed DND, so the
        # replacement below acts on an id that is actually active.
        self.policy.update(available=True, dnd=True)
        self.policy.notify(1, notification(hints={"urgency": 2}))
        self.assertEqual(self.actions(), ["notification"])
        self.assertEqual(self.policy.active_id, 1)
        # A normal notification replacing the active critical one is suppressed
        # by DND and must withdraw the preview it was meant to replace.
        self.policy.notify(2, notification(replaces_id=1))
        self.assertEqual(self.events[-1], {"action": "notification-close", "notification_id": 1})
        self.assertEqual(self.actions(), ["notification", "notification-close"])
        self.assertIsNone(self.policy.active_id)
        # The replaced id is gone, so a third attempt emits nothing further.
        self.policy.notify(3, notification(replaces_id=1))
        self.assertEqual(self.actions(), ["notification", "notification-close"])

    def test_allowed_replacement_replaces_without_close(self):
        self.policy.update(available=True)
        self.policy.notify(1, notification())
        self.policy.notify(2, notification(summary="Second", replaces_id=1))
        self.assertEqual(self.actions(), ["notification", "notification"])
        self.assertEqual([event["notification_id"] for event in self.events], [1, 2])
        self.assertEqual(self.events[-1]["title"], "Second")
        self.assertEqual(self.policy.active_id, 2)

    def test_suppressed_unrelated_notification_keeps_critical_preview(self):
        self.policy.update(available=True, dnd=True)
        self.policy.notify(1, notification(hints={"urgency": 2}))
        self.policy.notify(2, notification())
        self.policy.notify(3, notification(replaces_id=99))
        self.policy.notify(4, notification(replaces_id=0))
        self.assertEqual(self.actions(), ["notification"])
        self.assertEqual(self.policy.active_id, 1)

    def test_closed_validates_ids_and_matches_active_id_only(self):
        self.policy.closed(1)
        self.assertEqual(self.events, [])
        self.policy.update(available=True)
        self.policy.notify(1, notification())
        self.assertEqual(self.actions(), ["notification"])
        # True, 1.0, "1" and 0 must never close id 1.
        for bad in (True, False, 1.0, "1", 0, -1, None, 2 ** 32, [], {}):
            self.policy.closed(bad)
        self.policy.closed(2)
        self.assertEqual(self.actions(), ["notification"])
        self.assertEqual(self.policy.active_id, 1)
        self.policy.closed(1)
        self.assertEqual(self.events[-1], {"action": "notification-close", "notification_id": 1})
        self.assertIsNone(self.policy.active_id)
        self.policy.closed(1)
        self.assertEqual(self.actions(), ["notification", "notification-close"])

    def test_durations_for_low_normal_default_and_critical(self):
        self.policy.update(available=True)
        self.policy.notify(1, notification(timeout=2500))                     # explicit milliseconds
        self.policy.notify(2, notification(timeout=0))                        # never expire
        self.policy.notify(3, notification(timeout=30000))                    # beyond the cap
        self.policy.notify(4, notification(timeout=-1))                       # default -> NORMAL
        self.policy.notify(5, notification(timeout=-1, hints={"urgency": 1}))  # NORMAL
        self.policy.notify(6, notification(timeout=-1, hints={"urgency": 0}))  # LOW
        self.policy.notify(7, notification(timeout=-1, hints={"urgency": 2}))  # CRITICAL
        self.assertEqual([event["duration"] for event in self.events], [2.5, 8, 8, 6, 6, 3, 8])

        custom_events = []
        custom = policy.Policy(custom_events.append,
                               defaults={"timeout": 10, "timeout-low": 1.5, "timeout-critical": 4})
        custom.update(available=True)
        custom.notify(1, notification(timeout=-1))
        custom.notify(2, notification(timeout=-1, hints={"urgency": 0}))
        custom.notify(3, notification(timeout=-1, hints={"urgency": 2}))
        self.assertEqual([event["duration"] for event in custom_events], [8, 1.5, 4])

    def test_text_is_bounded_verbatim_without_markup_changes(self):
        self.policy.update(available=True)
        self.policy.notify(1, notification(summary="<b>" + "x" * 400,
                                           body="&amp;" + "y" * 500,
                                           icon="i" * 150))
        event = self.events[-1]
        self.assertEqual(len(event["title"]), policy.TITLE_LIMIT)
        self.assertEqual(len(event["summary"]), policy.BODY_LIMIT)
        self.assertEqual(len(event["icon"]), policy.ICON_LIMIT)
        self.assertTrue(event["title"].startswith("<b>"))
        self.assertTrue(event["summary"].startswith("&amp;"))

    def test_invalid_ids_and_non_integer_urgency_never_convert(self):
        self.policy.update(available=True, dnd=True)
        for identifier in (None, "", "1", "   ", 0, -1, True, False, 3.5, 2 ** 32, [], {}):
            self.policy.notify(identifier, notification())
        # Floats, NaN, infinity, booleans and out-of-range ints are NORMAL, not
        # CRITICAL, so they are still suppressed while DND holds.
        for value in (2.0, float("nan"), float("inf"), float("-inf"), True, 3, -1):
            self.policy.notify(1, notification(hints={"urgency": value}))
        self.assertEqual(self.events, [])
        self.assertIsNone(self.policy.active_id)

        self.policy.update(available=True, dnd=False)
        self.policy.notify(1, notification(timeout=-1, hints={"urgency": float("nan")}))
        self.policy.notify(2, notification(timeout=-1, hints={"urgency": 2.0}))
        self.assertEqual([event["duration"] for event in self.events], [6, 6])
        self.assertEqual([event["notification_id"] for event in self.events], [1, 2])

        self.events.clear()
        self.policy.notify(1, notification())
        self.policy.notify(4294967295, notification())
        self.policy.notify(4294967296, notification())
        self.assertEqual([event["notification_id"] for event in self.events], [1, 4294967295])

    def test_malformed_payloads_never_emit_or_raise(self):
        self.policy.update(available=True)
        for data in (None, "text", 42, (1, 2, 3),
                     ("app", 0, "icon", "Summary", "Body", [], None, -1),
                     ("app", 0, "icon", 5, "Body", [], {}, -1),
                     ("app", 0, "icon", "Summary", None, [], {}, -1),
                     ("app", 0, None, "Summary", "Body", [], {}, -1),
                     ("app", "1", "icon", "Summary", "Body", [], {}, -1),
                     ("app", 0, "icon", "Summary", "Body", [], {}, "soon"),
                     ("app", 0, "icon", "Summary", "Body", [], {}, float("nan")),
                     ("app", 0, "icon", "Summary", "Body", [], {}, True),
                     ("app", 0, "icon", "Summary", "Body", [], {}, 2 ** 31),
                     ("app", 2 ** 32, "icon", "Summary", "Body", [], {}, -1)):
            self.policy.notify(1, data)
        self.assertEqual(self.events, [])
        self.assertIsNone(self.policy.active_id)
        self.policy.notify(1, notification(hints={"other": True}))
        self.assertEqual(self.actions(), ["notification"])


if __name__ == "__main__":
    unittest.main()
