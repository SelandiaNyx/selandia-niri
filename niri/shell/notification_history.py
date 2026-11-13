#!/usr/bin/env python3
"""Notification history persistence, pruning limits, and configuration.

Maintains a bounded, time-expiring record of desktop notifications.
Thread-safe and process-safe using atomic staging and file locks.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

DEFAULT_SETTINGS = {
    "limit": 100,         # Maximum number of stored notifications (0 = unlimited)
    "expire_days": 7,     # Days to keep notifications before expiry (0 = never)
    "enabled": True,      # Whether recording is active
}

LIMIT_CHOICES = (20, 50, 100, 200, 500, 0)
EXPIRE_CHOICES = (1, 3, 7, 14, 30, 0)


def state_dir() -> Path:
    """Return the base state directory for selandia-niri."""
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri"
    base.mkdir(parents=True, exist_ok=True)
    return base


def history_path() -> Path:
    return state_dir() / "notification_history.json"


def settings_path() -> Path:
    return state_dir() / "notification_settings.json"


@contextmanager
def _lock(lock_name: str = "notification.lock"):
    path = state_dir() / lock_name
    with path.open("a") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic_write(target: Path, text: str):
    """Write text atomically via temporary file and replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def validate_settings(data: dict) -> dict:
    """Validate and normalize notification history settings."""
    result = dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return result

    if "limit" in data:
        try:
            limit = int(data["limit"])
            if 0 <= limit <= 5000:
                result["limit"] = limit
        except (ValueError, TypeError):
            pass

    if "expire_days" in data:
        try:
            days = float(data["expire_days"])
            if 0 <= days <= 365:
                result["expire_days"] = int(days) if days.is_integer() else round(days, 2)
        except (ValueError, TypeError):
            pass

    if "enabled" in data:
        result["enabled"] = bool(data["enabled"])

    return result


def load_settings() -> dict:
    path = settings_path()
    try:
        if path.is_file():
            return validate_settings(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> dict:
    valid = validate_settings(settings)
    with _lock():
        _atomic_write(settings_path(), json.dumps(valid, indent=2, ensure_ascii=False) + "\n")
        # Re-prune history with the updated settings immediately
        _prune_file(valid)
    return valid


def prune_entries(entries: list[dict], settings: dict | None = None, now: float | None = None) -> list[dict]:
    """Prune a list of notification dictionaries according to expiry and count limit.

    Always sorts newest-first by timestamp.
    """
    if not isinstance(entries, list):
        return []
    cfg = validate_settings(settings) if settings is not None else load_settings()
    current_time = time.time() if now is None else float(now)

    valid_entries = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp")
        if not isinstance(ts, (int, float)):
            ts = current_time
            item["timestamp"] = ts

        # Check expiry
        expire_days = cfg.get("expire_days", 0)
        if expire_days > 0:
            ttl_seconds = expire_days * 86400
            if current_time - ts > ttl_seconds:
                continue
        valid_entries.append(item)

    # Sort descending by timestamp
    valid_entries.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # Apply limit
    limit = cfg.get("limit", 0)
    if limit > 0 and len(valid_entries) > limit:
        valid_entries = valid_entries[:limit]

    return valid_entries


def _load_history_unlocked() -> list[dict]:
    path = history_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except (OSError, ValueError, TypeError):
        pass
    return []


def _save_history_unlocked(entries: list[dict]):
    path = history_path()
    _atomic_write(path, json.dumps(entries, indent=2, ensure_ascii=False) + "\n")


def _ensure_history_ids(entries: list[dict]) -> bool:
    """Give each stored row a stable identity independent of the daemon ID.

    Notification IDs can be replaced and reused when SwayNC restarts. Persist
    migration while holding the history lock so concurrent readers see the same
    row identities, including legacy rows with duplicate notification IDs.
    """
    seen = set()
    changed = False
    for entry in entries:
        identifier = entry.get("history_id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            identifier = uuid.uuid4().hex
            entry["history_id"] = identifier
            changed = True
        seen.add(identifier)
    return changed


def _prune_file(settings: dict | None = None):
    entries = _load_history_unlocked()
    pruned = prune_entries(entries, settings=settings)
    _save_history_unlocked(pruned)


def load_history() -> list[dict]:
    """Return all active notification history records, newest first."""
    with _lock():
        entries = _load_history_unlocked()
        pruned = prune_entries(entries)
        migrated = _ensure_history_ids(pruned)
        if migrated or len(pruned) != len(entries):
            _save_history_unlocked(pruned)
        return pruned


def record_notification(item: dict) -> bool:
    """Record a single incoming notification if history is enabled.

    Returns True if recorded, False if rejected or history is disabled.
    """
    if not isinstance(item, dict):
        return False
    cfg = load_settings()
    if not cfg.get("enabled", True):
        return False

    now = time.time()
    record = {
        "history_id": uuid.uuid4().hex,
        "id": item.get("id") or item.get("notification_id") or int(now * 1000),
        "app_name": str(item.get("app_name") or item.get("app") or "").strip()[:80],
        "summary": str(item.get("summary") or item.get("title") or "").strip()[:160],
        "body": str(item.get("body") or item.get("message") or "").strip()[:500],
        "icon": str(item.get("icon") or "").strip()[:120],
        "timestamp": float(item.get("timestamp") or now),
        "urgency": int(item.get("urgency", 1)) if item.get("urgency") in (0, 1, 2) else 1,
        "category": str(item.get("category") or "").strip()[:40],
    }

    with _lock():
        entries = [entry for entry in _load_history_unlocked() if isinstance(entry, dict)]
        # Avoid exact duplicate spam within 1 second for same app + title + body
        for existing in entries[:5]:
            if (existing.get("app_name") == record["app_name"] and
                existing.get("summary") == record["summary"] and
                existing.get("body") == record["body"] and
                abs(existing.get("timestamp", 0) - record["timestamp"]) < 1.0):
                return False

        entries.insert(0, record)
        pruned = prune_entries(entries, settings=cfg, now=now)
        _ensure_history_ids(pruned)
        _save_history_unlocked(pruned)
    return True


def delete_notification(identifier) -> bool:
    """Delete one history row, with a legacy daemon-ID fallback.

    New callers pass history_id. Older clients may still pass a notification
    ID; remove only their first matching row rather than every reused ID.
    """
    if identifier is None or identifier == "":
        return False
    with _lock():
        entries = _load_history_unlocked()
        target = next((index for index, entry in enumerate(entries)
                       if isinstance(entry, dict) and entry.get("history_id") == identifier), None)
        if target is None:
            target = next((index for index, entry in enumerate(entries)
                           if isinstance(entry, dict) and entry.get("id") is not None
                           and str(entry["id"]) == str(identifier)), None)
        if target is not None:
            del entries[target]
            _save_history_unlocked(entries)
            return True
    return False


def clear_history():
    """Clear all stored notification history."""
    with _lock():
        _save_history_unlocked([])
