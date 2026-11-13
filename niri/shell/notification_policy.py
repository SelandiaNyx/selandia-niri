#!/usr/bin/env python3
"""Notification preview policy deciding what the island may show.

Pure Python: no D-Bus, GUI, filesystem, or network access. The shell feeds this
module session state (``update``), unpacked Notify tuples (``notify``), and
close signals (``closed``); every decision is reported to the ``emit`` callback
as a plain dictionary so that rendering and markup stay in the island.

Previews are only shown while the shell is available and no state forbids them.
A notification bypasses Do-Not-Disturb and inhibitors when its urgency is
critical (``2``) or when it carries the ``SWAYNC_BYPASS_DND`` hint (``True`` or
integer ``1``); either condition alone is enough. An unavailable shell or an
open control center always suppresses previews, bypass or not. Text is bounded
here, verbatim, without any markup transformation.
"""
from __future__ import annotations

import math

TITLE_LIMIT = 160
BODY_LIMIT = 320
ICON_LIMIT = 100
DURATION_CAP = 8
UINT32_MAX = 4294967295
INT32_MIN = -2147483648
INT32_MAX = 2147483647
FALLBACK_TIMEOUTS = {"timeout": 6, "timeout-low": 3, "timeout-critical": 0}


def _is_number(value):
    """True for finite real numbers; booleans and NaN/infinity are malformed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float):
        return not (math.isnan(value) or math.isinf(value))
    return True


def _valid_uint32(value):
    """True for D-Bus ``u`` values: integers in 0..4294967295, never booleans."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= UINT32_MAX


def _valid_int32(value):
    """True for D-Bus ``i`` values: signed integers, never booleans or floats."""
    return isinstance(value, int) and not isinstance(value, bool) and INT32_MIN <= value <= INT32_MAX


def _valid_id(identifier):
    """Notification ids are strictly positive uint32 integers, never strings."""
    return _valid_uint32(identifier) and identifier > 0


def _same(left, right):
    """Equality that never raises on foreign payload objects."""
    try:
        return left == right
    except Exception:
        return False


def _urgency(hints):
    """Urgency 0 (low), 1 (normal) or 2 (critical); anything else is normal.

    The D-Bus urgency hint is a byte, so floats, booleans, NaN, infinity and
    out-of-range values are never converted; they fall back to NORMAL.
    """
    value = hints.get("urgency")
    if isinstance(value, bool) or not isinstance(value, int):
        return 1
    return value if value in (0, 1, 2) else 1


def _bypass_hint(hints):
    """Only boolean True or the integer 1 for SWAYNC_BYPASS_DND requests a bypass."""
    value = hints.get("SWAYNC_BYPASS_DND")
    if value is True:
        return True
    return isinstance(value, int) and not isinstance(value, bool) and value == 1


def _bound_seconds(value):
    """Clamp seconds to (0, DURATION_CAP]; a zero or negative duration caps out."""
    if value <= 0 or value > DURATION_CAP:
        return DURATION_CAP
    return int(value) if float(value).is_integer() else round(float(value), 3)


def _parse(data):
    """Return the fields the preview needs, or None for a malformed tuple."""
    if not isinstance(data, (tuple, list)) or len(data) != 8:
        return None
    _, replaces_id, icon, summary, body, _, hints, expire_timeout = data
    if not _valid_uint32(replaces_id) or not _valid_int32(expire_timeout):
        return None
    if not isinstance(icon, str) or not isinstance(summary, str) or not isinstance(body, str):
        return None
    if not isinstance(hints, dict):
        return None
    return replaces_id, icon, summary, body, hints, expire_timeout


class Policy:
    """Track notification state and emit bounded preview dictionaries."""

    def __init__(self, emit, defaults=None):
        self._emit = emit
        self.configure(defaults)
        self.available = False
        self.dnd = False
        self.cc_open = False
        self.inhibited = False
        self.active_id = None
        self.active_bypass = False

    def configure(self, defaults):
        """Use newly accepted daemon defaults for subsequent previews only."""
        self._defaults = dict(FALLBACK_TIMEOUTS)
        if isinstance(defaults, dict):
            for key, value in defaults.items():
                name = str(key).replace("_", "-")
                if name in self._defaults and _is_number(value):
                    self._defaults[name] = value

    def update(self, *, available, dnd=False, cc_open=False, inhibited=False):
        """Store session state; withdraw an active preview that is no longer allowed."""
        self.available = bool(available)
        self.dnd = bool(dnd)
        self.cc_open = bool(cc_open)
        self.inhibited = bool(inhibited)
        self._sync()

    def notify(self, identifier, data, *, visible=True):
        """Handle one Notify request; emit at most one preview or one close."""
        if not _valid_id(identifier):
            return
        parsed = _parse(data)
        if parsed is None:
            return
        replaces_id, icon, summary, body, hints, expire_timeout = parsed
        urgency = _urgency(hints)
        critical = urgency == 2
        bypass = critical or _bypass_hint(hints)
        duration = self._duration(expire_timeout, urgency, critical)
        if duration is None:
            return
        if not visible or not self._allowed(bypass):
            # A suppressed replacement withdraws the visible preview; unrelated
            # suppressed notifications never dismiss an allowed critical preview.
            if self.active_id is not None and replaces_id != 0 and _same(replaces_id, self.active_id):
                self._close_active()
            return
        self.active_id = identifier
        self.active_bypass = bypass
        self._send({"action": "notification", "notification_id": identifier,
                    "title": summary[:TITLE_LIMIT], "summary": body[:BODY_LIMIT],
                    "icon": icon[:ICON_LIMIT], "duration": duration})

    def closed(self, identifier):
        """A close signal withdraws only the matching active preview.

        The id is validated first so a malformed signal (``True``, ``1.0``,
        ``"1"``, zero or negative) can never close a valid preview.
        """
        if not _valid_id(identifier) or self.active_id is None:
            return
        if _same(identifier, self.active_id):
            self._close_active()

    def _allowed(self, bypass):
        if not self.available or self.cc_open:
            return False
        return bypass or not (self.dnd or self.inhibited)

    def _sync(self):
        if self.active_id is None:
            return
        blocked = not self.available or self.cc_open or ((self.dnd or self.inhibited) and not self.active_bypass)
        if blocked:
            self._close_active()

    def _close_active(self):
        identifier = self.active_id
        self.active_id = None
        self.active_bypass = False
        self._send({"action": "notification-close", "notification_id": identifier})

    def _send(self, event):
        emit = self._emit
        if callable(emit):
            emit(event)

    def _duration(self, expire_timeout, urgency, critical):
        """Preview seconds; None when the expire timeout is malformed."""
        if not _valid_int32(expire_timeout):
            return None
        if expire_timeout > DURATION_CAP * 1000:
            return DURATION_CAP
        if expire_timeout > 0:
            return _bound_seconds(expire_timeout / 1000.0)
        if expire_timeout == 0:
            return DURATION_CAP
        if critical:
            return _bound_seconds(self._defaults["timeout-critical"])
        if urgency == 0:
            return _bound_seconds(self._defaults["timeout-low"])
        return _bound_seconds(self._defaults["timeout"])
