#!/usr/bin/env python3
"""Niri timer lifecycle and an explicit logind idle/sleep inhibitor.

No sleep or monitor power command is ever issued by this module. The guard is
bound to the desktop's systemd target and expires when the Niri session ends.
"""
import json
import fcntl
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from i18n import tr
from appearance import preferences_path

BASE = Path(__file__).resolve().parent.parent
WHO = "Selandia Niri"


def _run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=8)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "systemctl failed")
    return result.stdout.strip()


def _service(component, action):
    return _run(["systemctl", "--user", action, f"selandia-niri@{component}.service"])


def _unit(component):
    output = _run(["systemctl", "--user", "show", f"selandia-niri@{component}.service",
                   "--property=ActiveState,LoadState,MainPID"])
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def timers_enabled(*, base=BASE):
    base = Path(base)
    path = base / "swayidle/managed.conf"
    if not path.exists():
        path = base / "swayidle/config"
    return any(int(match[1]) > 0 for line in path.read_text().splitlines()
               if (match := re.match(r"\s*timeout\s+([0-9]+)\s+", line)))


def _has_inhibitor(pid):
    if not pid:
        return False
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    result = bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                           "org.freedesktop.login1.Manager", "ListInhibitors", None,
                           GLib.VariantType.new("(a(ssssuu))"), Gio.DBusCallFlags.NONE, 2500, None)
    return any(who == WHO and mode == "block" and uid == os.getuid() and owner == pid
               and {"idle", "sleep"} <= set(what.split(":"))
               for what, who, _reason, mode, uid, owner in result.unpack()[0])


def status():
    timer, guard = _unit("idle"), _unit("awake")
    enabled = timers_enabled()
    awake = guard.get("ActiveState") == "active" and _has_inhibitor(int(guard.get("MainPID", 0)))
    error = (guard.get("ActiveState") in ("failed", "active") and not awake
             or enabled and not awake and timer.get("ActiveState") != "active")
    if awake:
        title = tr("Sleep blocked", "已阻止睡眠")
        detail = tr("Niri timers are paused. A logind inhibitor blocks idle and sleep requests for this session; manual locking remains available.",
                    "Niri 计时已暂停，本次会话通过 logind 阻止自动空闲处理及睡眠请求；仍可手动锁屏。")
    elif error:
        title = tr("Power service error", "电源服务异常")
        detail = tr("The timer or sleep inhibitor is not running as requested. Reapply power settings or enable Stay awake.",
                    "计时器或睡眠抑制器未按设置运行，请重新应用电源设置或开启保持唤醒。")
    elif not enabled:
        title = tr("Timers disabled", "计时已关闭")
        detail = tr("Niri has no automatic lock, screen-off or sleep timer. Other programs can still request sleep; enable Stay awake to block it.",
                    "Niri 未设置自动锁屏、息屏或睡眠计时。其他程序仍可请求睡眠；开启保持唤醒可阻止这些请求。")
    else:
        title = tr("Timers running", "计时运行中")
        detail = tr("Niri's configured lock, screen-off and sleep timers are running.", "Niri 已按保存的设置运行锁屏、息屏及睡眠计时。")
    return {"awake": awake, "available": timer.get("LoadState") == "loaded" and guard.get("LoadState") == "loaded",
            "error": bool(error), "timers_enabled": enabled, "timer_state": timer.get("ActiveState"),
            "guard_state": guard.get("ActiveState"), "label": title, "detail": detail}


def apply_timers(enabled):
    if type(enabled) is not bool:
        raise ValueError("Timer state must be boolean")
    if not enabled or _unit("awake").get("ActiveState") == "active":
        _service("idle", "stop")
    else:
        if _unit("idle").get("ActiveState") == "failed":
            _service("idle", "reset-failed")
        # restart also starts an inactive service after all-zero timers exited.
        _service("idle", "restart")
        if _unit("idle").get("ActiveState") != "active":
            raise RuntimeError(tr("Idle timers did not start.", "空闲计时器未能启动。"))


def set_awake(enabled):
    path = preferences_path().with_name("power.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _set_awake(enabled)


def _set_awake(enabled):
    if type(enabled) is not bool:
        raise ValueError("Stay-awake state must be boolean")
    session = _run(["systemctl", "--user", "show", "niri.service", "--property=ActiveState", "--value"])
    if session != "active":
        raise RuntimeError(tr("Stay awake requires an active Niri session.", "保持唤醒需要已运行的 Niri 会话。"))
    if enabled:
        try:
            if _unit("awake").get("ActiveState") == "failed":
                _service("awake", "reset-failed")
            _service("awake", "start")
            deadline = time.monotonic() + 4
            while True:
                unit = _unit("awake")
                if unit.get("ActiveState") == "active" and _has_inhibitor(int(unit.get("MainPID", 0))):
                    break
                if unit.get("ActiveState") == "failed" or time.monotonic() >= deadline:
                    raise RuntimeError(tr("Could not acquire the system sleep inhibitor.", "无法取得系统睡眠抑制锁。"))
                time.sleep(.1)
            # Only pause timers once logind confirms the guard really exists.
            _service("idle", "stop")
        except Exception:
            try:
                _service("awake", "stop")
            except RuntimeError:
                pass
            raise
    else:
        _service("awake", "stop")
        try:
            apply_timers(timers_enabled())
        except Exception:
            _service("awake", "start")
            raise
    return status()


def main():
    args = sys.argv[1:]
    if args == ["toggle"]:
        current = status()
        result = set_awake(not current["awake"])
        print(result["detail"])
    elif args in (["on"], ["off"]):
        print(set_awake(args[0] == "on")["detail"])
    elif args == ["status"]:
        print(json.dumps(status(), ensure_ascii=False))
    elif args == ["waybar"]:
        result = status()
        print(json.dumps({"text": "󰅶" if result["awake"] else "󰒲",
                          "tooltip": result["detail"],
                          "class": "error" if result["error"] else "active" if result["awake"] else "normal"}, ensure_ascii=False))
    else:
        raise ValueError("Usage: sleep_guard.py {toggle|on|off|status|waybar}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
