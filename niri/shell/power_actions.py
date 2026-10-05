#!/usr/bin/env python3
"""One entry point for locking and sleeping, shared by menu and timer.

The manual power menu and the generated automatic timer both call this module.
A sleep request therefore always: confirms the real logind inhibitor state of
this project, refuses *before locking* when Stay awake blocks sleep, locks and
waits for readiness, and only then asks logind to suspend. Every failure is
reported with a reason. The guard is never disabled, no ignore-inhibitor option
is used, and sleep is never requested after an unconfirmed lock.
"""
from __future__ import annotations

import json
import subprocess
import sys

import lock_session
import sleep_guard
from i18n import tr


class SleepRefused(RuntimeError):
    """Refused before anything was locked or suspended."""


def blocked_reason(*, status=sleep_guard.status):
    """Return why sleep must not be requested, or None when it may proceed."""
    try:
        state = status()
    except Exception as error:
        return tr("The sleep-protection state could not be read, so sleep was not requested. ",
                  "无法读取睡眠保护状态，因此未发出睡眠请求。") + str(error)
    if state.get("awake"):
        return tr("Stay awake is blocking sleep. Turn that protection off first, then choose Suspend again.",
                  "“保持唤醒”正在阻止睡眠。请先关闭该保护，然后重新选择睡眠。")
    return None


def suspend(*, status=sleep_guard.status, lock=lock_session.lock, run=subprocess.run, timeout=25):
    """Lock this display and confirm readiness, then request suspend."""
    reason = blocked_reason(status=status)
    if reason:
        # Nothing is locked here on purpose: the request never starts.
        raise SleepRefused(reason)
    lock()  # raises unless the current display is confirmed locked
    result = run(["systemctl", "suspend"], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(tr("The system refused the suspend request: ", "系统拒绝睡眠请求：")
                           + (detail or f"systemctl exited with status {result.returncode}"))
    return tr("Suspend requested.", "已请求睡眠。")


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if arguments == ["suspend"]:
        try:
            print(suspend())
        except Exception as error:
            print(str(error), file=sys.stderr)
            return 1
        return 0
    if arguments == ["blocked"]:
        reason = blocked_reason()
        if reason:
            print(reason)
            return 0
        return 1
    if arguments == ["state"]:
        try:
            print(json.dumps(sleep_guard.status(), ensure_ascii=False))
        except Exception as error:
            print(json.dumps({"available": False, "error": True, "detail": str(error)}, ensure_ascii=False))
            return 1
        return 0
    print("Usage: power_actions.py {suspend|blocked|state}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
