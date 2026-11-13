"""SwayNC notification-visibility rules: matching, ordering, states, urgency."""
from collections import OrderedDict
import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import notification_rules


HINT_FIELDS = ("desktop-entry", "category", "sound-name", "sound-file")


def notification(app_name="app", summary="Summary", body="Body", hints=None,
                 replaces_id=0, icon="icon", timeout=-1):
    return (app_name, replaces_id, icon, summary, body, [],
            {} if hints is None else hints, timeout)


def full_hints(overrides=None, **values):
    hints = {
        "desktop-entry": "org.example.App",
        "category": "im.received",
        "sound-name": "message-new-instant",
        "sound-file": "/usr/share/sounds/bell.ogg",
    }
    hints.update(overrides or {})
    hints.update({key.replace("_", "-"): value for key, value in values.items()})
    return hints


def full_notification(app_name="my-app", summary="a summary", body="the body", hints=None):
    return notification(app_name=app_name, summary=summary, body=body,
                        hints=full_hints() if hints is None else hints)


def rules(*items):
    return notification_rules.Rules({"notification-visibility": OrderedDict(items)})


class NotificationRulesTest(unittest.TestCase):
    def test_first_matching_rule_wins_in_configured_order(self):
        data = notification(app_name="app")
        with self.subTest("first muted, second enabled"):
            instance = rules(("first", {"app-name": "app", "state": "muted"}),
                             ("second", {"app-name": "app", "state": "enabled"}))
            self.assertEqual(instance.decide(data, 1), (False, 1))
        with self.subTest("first enabled, second muted"):
            instance = rules(("first", {"app-name": "app", "state": "enabled"}),
                             ("second", {"app-name": "app", "state": "muted"}))
            self.assertEqual(instance.decide(data, 1), (True, 1))
        with self.subTest("later urgency override never applies"):
            instance = rules(("first", {"app-name": "app", "override-urgency": "low"}),
                             ("second", {"app-name": "app", "override-urgency": "critical"}))
            self.assertEqual(instance.decide(data, 1), (True, 0))
        with self.subTest("non-matching first rule is skipped"):
            instance = rules(("first", {"app-name": "other", "state": "muted"}),
                             ("second", {"app-name": "app", "state": "muted"}))
            self.assertEqual(instance.decide(data, 1), (False, 1))

    def test_all_recognized_matchers_are_anded(self):
        rule = {"app-name":"app", "summary":"sum", "body":"body", "urgency":"Critical",
                "desktop-entry":"desk", "category":"cat", "sound-name":"bell", "sound-file":"sound.ogg",
                "state":"muted"}
        data = list(full_notification(hints={"desktop-entry":"com.desk", "category":"x.cat.y",
                                            "sound-name":"bell", "sound-file":"/sounds/sound.ogg"}))
        instance = rules(("all", rule))
        self.assertEqual(instance.decide(data, 2), (False, 2))
        for field, index in (("app-name",0),("summary",3),("body",4)):
            with self.subTest(field=field):
                changed=copy.deepcopy(data);changed[index]="other"
                self.assertEqual(instance.decide(changed, 2), (True, 2))
        self.assertEqual(instance.decide(data, 1), (True, 1))
        for field in HINT_FIELDS:
            with self.subTest(field=field):
                changed=copy.deepcopy(data);changed[6][field]="other"
                self.assertEqual(instance.decide(changed, 2), (True, 2))

    def test_missing_and_non_string_hints_fail_their_matcher(self):
        data = full_notification()
        for field in HINT_FIELDS:
            with self.subTest(field=field, case="missing"):
                instance = rules(("hint", {field: "value", "state": "muted"}))
                hints = full_hints()
                hints.pop(field)
                self.assertEqual(instance.decide(notification(hints=hints), 1), (True, 1))
            for value in (None, 3, True, ["value"], {"value": "value"}):
                with self.subTest(field=field, value=value):
                    instance = rules(("hint", {field: "value", "state": "muted"}))
                    hints = full_hints()
                    hints[field] = value
                    self.assertEqual(instance.decide(notification(hints=hints), 1), (True, 1))
            with self.subTest(field=field, case="string matches"):
                instance = rules(("hint", {field: "value", "state": "muted"}))
                hints = full_hints()
                hints[field] = "a value here"
                self.assertEqual(instance.decide(notification(hints=hints), 1), (False, 1))

    def test_patterns_search_case_sensitively_unless_inline_flag(self):
        data = full_notification(app_name="my-app", summary="a Summary line")
        with self.subTest("substring search"):
            self.assertEqual(rules(("r", {"app-name": "app", "state": "muted"})).decide(data, 1),
                             (False, 1))
            self.assertEqual(rules(("r", {"summary": "Summary", "state": "muted"})).decide(data, 1),
                             (False, 1))
        with self.subTest("anchored search, not fullmatch"):
            self.assertEqual(rules(("r", {"app-name": "^my-app$", "state": "muted"})).decide(data, 1),
                             (False, 1))
            self.assertEqual(rules(("r", {"app-name": "^app", "state": "muted"})).decide(data, 1),
                             (True, 1))
        with self.subTest("case sensitive"):
            self.assertEqual(rules(("r", {"app-name": "APP", "state": "muted"})).decide(data, 1),
                             (True, 1))
            self.assertEqual(rules(("r", {"summary": "summary", "state": "muted"})).decide(data, 1),
                             (True, 1))
        with self.subTest("inline case-insensitive flag"):
            self.assertEqual(rules(("r", {"app-name": "(?i)APP", "state": "muted"})).decide(data, 1),
                             (False, 1))
            self.assertEqual(rules(("r", {"summary": "(?i)SUMMARY", "state": "muted"})).decide(data, 1),
                             (False, 1))

    def test_body_compiles_without_multiline_while_summary_has_it(self):
        multiline = "top\nmiddle\nbottom"
        data = full_notification(summary=multiline, body=multiline)
        with self.subTest("summary anchored per line"):
            self.assertEqual(rules(("r", {"summary": "^middle$", "state": "muted"})).decide(data, 1),
                             (False, 1))
            self.assertEqual(rules(("r", {"summary": "middle$", "state": "muted"})).decide(data, 1),
                             (False, 1))
        with self.subTest("body anchors only the whole string"):
            self.assertEqual(rules(("r", {"body": "^middle", "state": "muted"})).decide(data, 1),
                             (True, 1))
            self.assertEqual(rules(("r", {"body": "middle$", "state": "muted"})).decide(data, 1),
                             (True, 1))
        with self.subTest("body still searches"):
            self.assertEqual(rules(("r", {"body": "middle", "state": "muted"})).decide(data, 1),
                             (False, 1))
            self.assertEqual(rules(("r", {"body": "^top", "state": "muted"})).decide(data, 1),
                             (False, 1))

    def test_notempty_rejects_empty_string_matches(self):
        for field in ("summary", "body"):
            with self.subTest(field=field, pattern=".*", case="empty"):
                instance = rules(("r", {field: ".*", "state": "muted"}))
                self.assertEqual(instance.decide(notification(**{field: ""}), 1), (True, 1))
            with self.subTest(field=field, pattern=".*", case="nonempty"):
                instance = rules(("r", {field: ".*", "state": "muted"}))
                self.assertEqual(instance.decide(notification(**{field: "x"}), 1), (False, 1))
            with self.subTest(field=field, pattern="a*", case="empty"):
                instance = rules(("r", {field: "a*", "state": "muted"}))
                self.assertEqual(instance.decide(notification(**{field: ""}), 1), (True, 1))
            with self.subTest(field=field, pattern="", case="empty"):
                instance = rules(("r", {field: "", "state": "muted"}))
                self.assertEqual(instance.decide(notification(**{field: ""}), 1), (True, 1))

    def test_glib_pcre_named_capture_is_supported(self):
        data = full_notification(summary="prefix foo suffix")
        with self.subTest("named capture group"):
            instance = rules(("r", {"summary": "(?<word>foo)", "state": "muted"}))
            self.assertEqual(instance.decide(data, 1), (False, 1))
        with self.subTest("named capture plus backreference"):
            instance = rules(("r", {"summary": "(?<word>foo).*\\k<word>", "state": "muted"}))
            other = full_notification(summary="foo then foo")
            self.assertEqual(instance.decide(other, 1), (False, 1))
            self.assertEqual(instance.decide(data, 1), (True, 1))

    def test_malformed_config_and_rules_are_tolerated(self):
        data = notification(app_name="app")
        for config in (None, [], "config", 3,
                       {}, {"notification-visibility": None},
                       {"notification-visibility": []},
                       {"notification-visibility": "rules"}):
            with self.subTest(config=config):
                self.assertEqual(notification_rules.Rules(config).decide(data, 1), (True, 1))

        with self.subTest("non-object rules are skipped"):
            config = {"notification-visibility": OrderedDict((
                ("none", None), ("list", ["app-name"]), ("text", "rule"),
                ("number", 4), ("good", {"state": "muted"})))}
            self.assertEqual(notification_rules.Rules(config).decide(data, 1), (False, 1))

        for field in ("app-name", "summary", "body", "urgency") + HINT_FIELDS:
            with self.subTest(invalid_regex_field=field):
                config = {"notification-visibility": OrderedDict((
                    ("bad", {field: "(", "state": "muted"}),
                    ("good", {"state": "transient"})))}
                self.assertEqual(notification_rules.Rules(config).decide(data, 1), (True, 1))

        with self.subTest("invalid regex fails even without a later rule"):
            instance = rules(("bad", {"summary": "[", "state": "muted"}))
            self.assertEqual(instance.decide(data, 1), (True, 1))

        with self.subTest("unknown rule fields are ignored"):
            instance = rules(("unknown", {"unknown-matcher": "x", "state": "muted"}))
            self.assertEqual(instance.decide(data, 1), (False, 1))

        for field in ("app-name", "summary", "body", "urgency") + HINT_FIELDS:
            with self.subTest(non_string_matcher=field):
                instance = rules(("r", {field: 7, "state": "muted"}))
                self.assertEqual(instance.decide(data, 1), (False, 1))

    def test_urgency_override_uses_original_urgency_and_only_first_rule(self):
        data = full_notification()
        with self.subTest("matching still uses the original urgency"):
            instance = rules(("r", {"urgency": "Critical", "override-urgency": "low"}))
            self.assertEqual(instance.decide(data, 1), (True, 1))
            self.assertEqual(instance.decide(data, 2), (True, 0))
        with self.subTest("first matching override wins"):
            instance = rules(("first", {"override-urgency": "low"}),
                             ("second", {"override-urgency": "critical"}))
            self.assertEqual(instance.decide(data, 1), (True, 0))
        with self.subTest("all exact lowercase overrides"):
            for name, effective in (("low", 0), ("normal", 1), ("critical", 2)):
                instance = rules(("r", {"urgency": "Normal", "override-urgency": name}))
                self.assertEqual(instance.decide(data, 1), (True, effective))
        with self.subTest("unknown or non-string overrides leave urgency unchanged"):
            for value in ("LOW", "Critical", "urgent", "", None, 2, True, ["low"]):
                instance = rules(("r", {"override-urgency": value}))
                self.assertEqual(instance.decide(data, 1), (True, 1))
        with self.subTest("override on a non-matching rule is ignored"):
            instance = rules(("r", {"app-name": "other", "override-urgency": "critical"}))
            self.assertEqual(instance.decide(data, 1), (True, 1))

    def test_urgency_low_matching_and_override(self):
        data = full_notification()
        with self.subTest("low urgency zero matches Low"):
            instance = rules(("r", {"urgency": "Low", "state": "muted"}))
            self.assertEqual(instance.decide(data, 0), (False, 0))
        with self.subTest("low urgency zero does not match other names"):
            for pattern in ("Normal", "Critical"):
                instance = rules(("r", {"urgency": pattern, "state": "muted"}))
                self.assertEqual(instance.decide(data, 0), (True, 0))
        with self.subTest("low urgency zero with anchored pattern"):
            instance = rules(("r", {"urgency": "^Low$", "state": "muted"}))
            self.assertEqual(instance.decide(data, 0), (False, 0))
            self.assertEqual(instance.decide(data, 1), (True, 1))
        with self.subTest("low urgency zero override"):
            instance = rules(("r", {"urgency": "Low", "override-urgency": "critical"}))
            self.assertEqual(instance.decide(data, 0), (True, 2))

    def test_states_control_visibility_including_critical_override(self):
        data = full_notification()
        cases = (("enabled", True), ("transient", True), ("muted", False),
                 ("ignored", False), ("disabled", True), ("", True),
                 (None, True), (1, True), (["muted"], True))
        for state, visible in cases:
            with self.subTest(state=state):
                instance = rules(("r", {"state": state}))
                self.assertEqual(instance.decide(data, 1), (visible, 1))
        with self.subTest("muted stays invisible with critical effective urgency"):
            instance = rules(("r", {"state": "muted", "override-urgency": "critical"}))
            self.assertEqual(instance.decide(data, 1), (False, 2))
        with self.subTest("muted critical input stays invisible"):
            instance = rules(("r", {"state": "muted"}))
            self.assertEqual(instance.decide(data, 2), (False, 2))
        with self.subTest("ignored with low override"):
            instance = rules(("r", {"state": "ignored", "override-urgency": "low"}))
            self.assertEqual(instance.decide(data, 2), (False, 0))
        with self.subTest("transient remains visible"):
            instance = rules(("r", {"state": "transient", "override-urgency": "critical"}))
            self.assertEqual(instance.decide(data, 1), (True, 2))

    def test_no_match_and_empty_rule_semantics(self):
        data = full_notification()
        with self.subTest("no rules"):
            instance = rules()
            for urgency in (0, 1, 2):
                self.assertEqual(instance.decide(data, urgency), (True, urgency))
        with self.subTest("no matching rule"):
            instance = rules(("r", {"app-name": "other", "state": "muted",
                                    "override-urgency": "critical"}))
            for urgency in (0, 1, 2):
                self.assertEqual(instance.decide(data, urgency), (True, urgency))
        with self.subTest("empty rule matches everything"):
            instance = rules(("r", {}))
            for urgency in (0, 1, 2):
                self.assertEqual(instance.decide(data, urgency), (True, urgency))
        with self.subTest("empty rule with muted state matches everything"):
            instance = rules(("r", {"state": "muted"}))
            self.assertEqual(instance.decide(data, 2), (False, 2))

    def test_inputs_are_not_mutated_and_decisions_are_repeatable(self):
        config = {"notification-visibility": OrderedDict((
            ("first", {"app-name": "app", "override-urgency": "critical"}),
            ("second", {"summary": "sum", "state": "muted"})))}
        data = full_notification(hints=full_hints())
        original_config = copy.deepcopy(config)
        original_data = copy.deepcopy(data)
        instance = notification_rules.Rules(config)
        first = instance.decide(data, 1)
        second = instance.decide(data, 1)
        self.assertEqual(first, (True, 2))
        self.assertEqual(second, first)
        self.assertEqual(config, original_config)
        self.assertEqual(data, original_data)


if __name__ == "__main__":
    unittest.main()
