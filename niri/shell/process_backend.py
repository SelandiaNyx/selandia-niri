"""Pure-/proc interactive process inspector with safe terminate/kill guards."""
from __future__ import annotations

import os
from pathlib import Path
import pwd
import signal
import time

from i18n import tr

_CLK_TCK = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", "SC_CLK_TCK")) if hasattr(os, "sysconf") else 100
_PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_PROTECTED_NAMES = frozenset({"systemd", "init", "niri", "niri-session"})


class ProcessSampler:
    def __init__(self):
        self._prev: dict[int, tuple[int, float]] = {}
        self._cpus = max(1, os.cpu_count() or 1)

    def sample(self, *, query: str = "", sort_by: str = "cpu", limit: int = 35) -> list[dict]:
        now = time.monotonic()
        needle = query.strip().casefold()
        uid_cache: dict[int, str] = {}
        rows = []
        next_prev: dict[int, tuple[int, float]] = {}
        my_pid = os.getpid()

        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                stat_text = Path(entry.path, "stat").read_text(errors="ignore")
                rparen = stat_text.rfind(")")
                lparen = stat_text.find("(")
                if lparen < 0 or rparen < 0:
                    continue
                comm = stat_text[lparen + 1:rparen]
                parts = stat_text[rparen + 2:].split()
                if len(parts) < 22:
                    continue
                state = parts[0]
                cpu_ticks = int(parts[11]) + int(parts[12])
                rss_bytes = max(0, int(parts[21])) * _PAGE_SIZE
                st = os.stat(entry.path)
                uid = st.st_uid
            except (OSError, ValueError, IndexError):
                continue

            prev = self._prev.get(pid)
            cpu_pct = 0.0
            if prev is not None:
                dt = now - prev[1]
                if dt > 0.05:
                    cpu_pct = max(0.0, ((cpu_ticks - prev[0]) / _CLK_TCK) / dt * 100.0)
            next_prev[pid] = (cpu_ticks, now)

            if uid not in uid_cache:
                try:
                    uid_cache[uid] = pwd.getpwuid(uid).pw_name
                except KeyError:
                    uid_cache[uid] = str(uid)
            user = uid_cache[uid]

            cmdline = ""
            try:
                raw_cmd = Path(entry.path, "cmdline").read_bytes()
                cmdline = raw_cmd.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
            except OSError:
                pass
            if needle and needle not in comm.casefold() and needle not in cmdline.casefold() and needle != str(pid):
                continue

            protected = pid <= 1 or pid == my_pid or comm in _PROTECTED_NAMES or uid != os.getuid()
            rows.append({
                "pid": pid,
                "name": comm,
                "user": user,
                "state": state,
                "cpu": round(cpu_pct, 1),
                "rss": rss_bytes,
                "cmdline": cmdline[:200] or comm,
                "protected": protected,
            })

        self._prev = next_prev
        if sort_by == "memory":
            rows.sort(key=lambda r: (-r["rss"], -r["cpu"], r["pid"]))
        elif sort_by == "name":
            rows.sort(key=lambda r: (r["name"].casefold(), r["pid"]))
        else:
            rows.sort(key=lambda r: (-r["cpu"], -r["rss"], r["pid"]))
        return rows[:limit]


def signal_process(pid: int, *, force: bool = False) -> None:
    if pid <= 1 or pid == os.getpid():
        raise PermissionError(tr("Cannot terminate protected system or panel process", "不能终止受保护的系统或当前面板进程"))
    try:
        comm = Path(f"/proc/{pid}/comm").read_text(errors="ignore").strip()
    except OSError:
        raise RuntimeError(tr("Process no longer exists", "该进程已退出"))
    if comm in _PROTECTED_NAMES:
        raise PermissionError(tr(f"Protected compositor/system process: {comm}", f"受保护的核心进程：{comm}"))
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
    except PermissionError as err:
        raise PermissionError(tr("Insufficient permission to signal this process", "没有权限终止该进程")) from err
    except ProcessLookupError:
        return
