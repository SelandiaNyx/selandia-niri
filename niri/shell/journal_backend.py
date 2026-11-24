"""Structured journalctl log reader with severity/unit/keyword filtering."""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess

from i18n import tr

ENV = dict(os.environ, LC_ALL="C")
_UNIT_RE = re.compile(r"^[A-Za-z0-9@._:-]{1,128}$")
PRIORITIES = {
    "err": "3",
    "warning": "4",
    "info": "6",
}


def read_logs(*, scope: str = "user", severity: str = "warning", unit: str = "", query: str = "", limit: int = 120) -> list[dict]:
    """Read recent structured journal entries without blocking or shell usage."""
    if not shutil.which("journalctl"):
        return []
    argv = ["journalctl", "--no-pager", "--output=json", "-n", str(max(20, min(400, limit))), "-b"]
    if scope == "user":
        argv.append("--user")
    if severity in PRIORITIES:
        argv.extend(["-p", PRIORITIES[severity]])
    cleaned_unit = unit.strip()
    if cleaned_unit and _UNIT_RE.fullmatch(cleaned_unit):
        argv.extend(["-u", cleaned_unit])

    try:
        res = subprocess.run(argv, capture_output=True, text=True, env=ENV, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0 and not res.stdout:
        return []

    needle = query.strip().casefold()
    entries = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("MESSAGE", "")
        if isinstance(msg, list):
            try:
                msg = bytes(msg).decode("utf-8", errors="replace")
            except Exception:
                msg = str(msg)
        msg = str(msg).strip()
        if not msg:
            continue
        src = str(obj.get("_SYSTEMD_USER_UNIT") or obj.get("_SYSTEMD_UNIT") or obj.get("SYSLOG_IDENTIFIER") or "system")
        if needle and needle not in msg.casefold() and needle not in src.casefold():
            continue
        try:
            prio = int(obj.get("PRIORITY", 6))
        except (TypeError, ValueError):
            prio = 6
        ts_us = obj.get("__REALTIME_TIMESTAMP")
        ts_str = ""
        if ts_us and str(ts_us).isdigit():
            try:
                dt = datetime.datetime.fromtimestamp(int(ts_us) / 1_000_000)
                ts_str = dt.strftime("%H:%M:%S")
            except (OSError, ValueError, OverflowError):
                pass
        level = "err" if prio <= 3 else ("warn" if prio == 4 else "info")
        entries.append({"time": ts_str, "unit": src, "level": level, "priority": prio, "message": msg[:500]})

    entries.reverse()
    return entries[:limit]


def format_plain_report(entries: list[dict]) -> str:
    if not entries:
        return tr("No matching journal entries.", "没有匹配的日志记录。")
    return "\n".join(f"[{e['time']}] [{e['level'].upper()}] {e['unit']}: {e['message']}" for e in entries)
