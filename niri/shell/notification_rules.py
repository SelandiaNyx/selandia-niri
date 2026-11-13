#!/usr/bin/env python3
"""Evaluate SwayNC ``notification-visibility`` rules without side effects.

The shell hands this module the parsed SwayNC configuration and asks it to
decide whether an unpacked Notify tuple may be shown and which urgency should
be used. Rules are compiled once, when :class:`Rules` is constructed, with the
same GLib regular-expression engine SwayNC 0.12.6 uses.

Only the first matching rule applies. Every recognized matcher in a rule is
ANDed, patterns are searched (not anchored) and case sensitive unless they
embed ``(?i)``, and ``body`` is compiled without ``MULTILINE`` while every
other matcher gets it. All matchers reject empty matches (``NOTEMPTY``), so a
pattern such as ``.*`` does not match an empty field.

No D-Bus, GUI, filesystem, or network access is performed, and no input is
mutated.
"""
from __future__ import annotations

from gi.repository import GLib

VISIBILITY_KEY = "notification-visibility"

_URGENCY_NAMES = {0: "Low", 1: "Normal", 2: "Critical"}
_URGENCY_OVERRIDES = {"low": 0, "normal": 1, "critical": 2}
_HIDDEN_STATES = frozenset(("muted", "ignored"))

# (config field, Notify tuple index) for the text fields.
_TEXT_MATCHERS = (("app-name", 0), ("summary", 3), ("body", 4))
# Hint keys that may be used as string matchers.
_HINT_MATCHERS = ("desktop-entry", "category", "sound-name", "sound-file")

_MULTILINE = GLib.RegexCompileFlags.MULTILINE
_NO_FLAGS = GLib.RegexCompileFlags(0)
_NOTEMPTY = GLib.RegexMatchFlags.NOTEMPTY


def _compile(pattern, flags):
    """Compile one pattern; None means the rule can never match."""
    try:
        return GLib.Regex.new(pattern, flags, _NOTEMPTY)
    except GLib.Error:
        return None


class _Rule:
    """One compiled notification-visibility rule."""

    __slots__ = ("checks", "visible", "override", "valid")

    def __init__(self, raw):
        self.checks = []
        self.visible = True
        self.override = None
        self.valid = True

        state = raw.get("state")
        # Unknown or non-string states default to enabled.
        if isinstance(state, str) and state in _HIDDEN_STATES:
            self.visible = False

        override = raw.get("override-urgency")
        if isinstance(override, str):
            self.override = _URGENCY_OVERRIDES.get(override)

        for field, index in _TEXT_MATCHERS:
            value = raw.get(field)
            if not isinstance(value, str):
                continue
            flags = _NO_FLAGS if field == "body" else _MULTILINE
            regex = _compile(value, flags)
            if regex is None:
                self.valid = False
                continue
            self.checks.append(("data", index, regex))

        for field in _HINT_MATCHERS:
            value = raw.get(field)
            if not isinstance(value, str):
                continue
            regex = _compile(value, _MULTILINE)
            if regex is None:
                self.valid = False
                continue
            self.checks.append(("hint", field, regex))

        value = raw.get("urgency")
        if isinstance(value, str):
            regex = _compile(value, _MULTILINE)
            if regex is None:
                self.valid = False
            else:
                self.checks.append(("urgency", None, regex))

    def matches(self, data, urgency):
        """True only when every configured matcher matches."""
        if not self.valid:
            return False
        for source, key, regex in self.checks:
            if source == "data":
                value = data[key]
            elif source == "hint":
                hints = data[6]
                if not isinstance(hints, dict):
                    return False
                value = hints.get(key)
            else:
                value = _URGENCY_NAMES[urgency]
            if not isinstance(value, str):
                return False
            try:
                matched = regex.match(value, _NOTEMPTY)[0]
            except GLib.Error:
                return False
            if not matched:
                return False
        return True


class Rules:
    """Compiled notification-visibility rules from a parsed configuration."""

    def __init__(self, config):
        self.rules = []
        if not isinstance(config, dict):
            return
        visibility = config.get(VISIBILITY_KEY)
        if not isinstance(visibility, dict):
            return
        for raw in visibility.values():
            if isinstance(raw, dict):
                self.rules.append(_Rule(raw))

    def decide(self, data, urgency):
        """Return ``(visible, effective_urgency)``; input urgency is normalized 0–2."""
        for rule in self.rules:
            if rule.matches(data, urgency):
                effective = urgency if rule.override is None else rule.override
                return rule.visible, effective
        return True, urgency
