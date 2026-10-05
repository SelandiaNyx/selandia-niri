#!/usr/bin/env python3
"""Confirm a Wayland screen lock through a per-display, cgroup-isolated service.

The locker never runs inside the caller's cgroup. The caller writes a
per-display request, asks systemd to run ``lock_client.py`` in a unit named
after the Wayland display, and only returns once the readiness record that the
client publishes verifies the PID, its start time and its display. A successful
``systemctl start`` is deliberately not accepted as proof of readiness.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

from i18n import tr

BASE = Path(__file__).resolve().parent.parent
CLIENT = Path(__file__).resolve().parent / "lock_client.py"
# Preferred: a dedicated per-display unit installed by tools/deploy.py.
LOCK_UNIT = "selandia-lock@.service"
# Compatibility: the already deployed component template, instance "lock-<key>".
COMPONENT_UNIT = "selandia-niri@.service"
# Only session-defining variables travel with a request; nothing else is copied
# into the unit's environment.
ENVIRONMENT_KEYS = ("XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE",
                    "XDG_SESSION_ID", "XDG_CURRENT_DESKTOP", "DISPLAY", "XAUTHORITY")


def display_identity(environment=None):
    environment = os.environ if environment is None else environment
    runtime = Path(environment["XDG_RUNTIME_DIR"])
    display = environment.get("WAYLAND_DISPLAY")
    if not runtime.is_absolute() or not display:
        raise RuntimeError(tr("A Wayland session is required for locking.", "锁屏需要有效的 Wayland 会话。"))
    return str((runtime / display).resolve())


def process_identity(pid):
    """PID alone is not identity: include process start time and display socket."""
    try:
        proc = Path("/proc") / str(pid)
        if proc.stat().st_uid != os.getuid() or proc.joinpath("comm").read_text().strip() != "swaylock":
            return None
        fields = proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        environment = dict(item.split("=", 1) for item in proc.joinpath("environ").read_bytes().decode().split("\0") if "=" in item)
        return {"pid": pid, "start": fields[19], "display": display_identity(environment)}
    except (OSError, ValueError, KeyError, IndexError, UnicodeError):
        return None


def confirmed(record, display):
    if not isinstance(record, dict) or record.get("display") != display or type(record.get("pid")) is not int:
        return False
    identity = process_identity(record["pid"])
    return identity is not None and identity == record


def paths(runtime, display):
    """One prefix per Wayland display: mutex, request, readiness record and log."""
    key = hashlib.sha256(display.encode()).hexdigest()[:20]
    return key, Path(runtime) / ("selandia-lock-" + key)


def read_record(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _atomic_write(path, text):
    path = Path(path)
    if path.is_symlink():
        raise OSError("Lock state file is not a regular file")
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_record(path, identity):
    _atomic_write(path, json.dumps(identity))


def capture_environment(environment=None):
    environment = os.environ if environment is None else environment
    return {key: environment[key] for key in ENVIRONMENT_KEYS if environment.get(key)}


def build_request(display, locker, config, timeout, environment):
    return {"version": 1, "display": display, "locker": [str(argument) for argument in locker],
            "config": str(config), "timeout": float(timeout), "environment": dict(environment)}


def inside_service_unit(cgroups=None):
    """True when this process already belongs to a systemd service unit.

    A nested preview or a plain terminal lives in a .scope, so a direct start is
    acceptable there. Inside a component service it is not: the locker would be
    killed together with that service.
    """
    if cgroups is None:
        try:
            cgroups = Path("/proc/self/cgroup").read_text()
        except OSError:
            return True
    for line in cgroups.splitlines():
        parts = [part for part in line.partition("::")[2].split("/") if part] or \
                [part for part in line.split("/") if part]
        tail = []
        for part in parts:
            if part.startswith("user@"):
                tail = []  # everything before the user manager is not ours
            else:
                tail.append(part)
        if any(part.endswith(".service") for part in tail):
            return True
    return False


def _systemctl(*arguments, timeout=10):
    return subprocess.run(["systemctl", "--user", *arguments], capture_output=True, text=True, timeout=timeout)


def unit_loaded(unit):
    try:
        result = _systemctl("show", unit, "--property=LoadState", "--value", timeout=8)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "loaded"


def systemd_launcher(unit_template):
    """Start the per-display unit; return a cheap failure probe for fast reporting."""
    def start(key, timeout):
        unit = unit_template.format(key=key)
        try:
            _systemctl("reset-failed", unit, timeout=8)
            result = _systemctl("start", unit, timeout=float(timeout) + 8)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(tr("Could not ask systemd to start the screen lock: ",
                                  "无法请求 systemd 启动锁屏：") + str(error)) from error
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(tr("The screen lock service did not start: ", "锁屏服务未能启动：") + (detail or unit))
        state = {"checked": 0.0, "failed": False}

        def failed():
            # The component template has no readiness notification, so a failed
            # client must be reported without waiting out the whole deadline.
            if state["failed"] or time.monotonic() - state["checked"] < .5:
                return state["failed"]
            state["checked"] = time.monotonic()
            try:
                state["failed"] = _systemctl("is-failed", "--quiet", unit, timeout=5).returncode == 0
            except (OSError, subprocess.SubprocessError):
                state["failed"] = False
            return state["failed"]
        return failed
    return start


def direct_launcher(runtime, note=None):
    """Nested-preview path: no reachable user manager, so no service to isolate from."""
    def start(key, timeout):
        prefix = Path(runtime) / ("selandia-lock-" + key)
        log_path = prefix.with_suffix(".log")
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as log:
            log.write((note or tr(
                "No user systemd manager was reachable; the locker runs in this process's session instead of an isolated unit.\n",
                "无法连接用户 systemd 管理器；锁屏进程运行在当前进程会话中，未使用独立单元。\n")))
            log.flush()
            process = subprocess.Popen([sys.executable, "-B", str(CLIENT), key], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
        return lambda: process.poll() is not None
    return start


def select_launcher(runtime, *, loaded=unit_loaded, inside=None):
    if loaded(LOCK_UNIT):
        return systemd_launcher("selandia-lock@{key}.service")
    if loaded(COMPONENT_UNIT):
        return systemd_launcher("selandia-niri@lock-{key}.service")
    if (inside_service_unit() if inside is None else inside):
        raise RuntimeError(tr("This service has no isolated screen-lock unit, so it refuses to start a locker that "
                              "would end with it. Run ./install.sh to install selandia-lock@.service.",
                              "当前服务没有独立锁屏单元，拒绝启动会随服务一起结束的锁屏进程。请运行 ./install.sh 安装 selandia-lock@.service。"))
    return direct_launcher(runtime)


def lock(*, base=BASE, timeout=10, locker=("swaylock",), runtime=None, launcher=None,
         environment=None):
    display = display_identity()
    source = os.environ if environment is None else environment
    runtime = Path(runtime or source["XDG_RUNTIME_DIR"])
    key, prefix = paths(runtime, display)
    record_path = prefix.with_suffix(".json")
    log_path = prefix.with_suffix(".log")
    with prefix.with_suffix(".lock").open("a") as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX)
        record = read_record(record_path)
        if confirmed(record, display):
            return record
        config = Path(base) / "theme/swaylock.conf"
        if not config.exists():
            config = Path(base) / "swaylock/config"
        if not config.exists():
            raise RuntimeError(tr("Lock configuration is missing: ", "缺少锁屏配置：") + str(config))
        _atomic_write(prefix.with_suffix(".request"),
                      json.dumps(build_request(display, locker, config, timeout, capture_environment(source))))
        start = launcher or select_launcher(runtime)
        launched = start(key, timeout)
        failed = launched if callable(launched) else (lambda: False)
        # Service start is not readiness: wait for the record the client publishes
        # only after swaylock reported ready on this display.
        deadline = time.monotonic() + max(2.0, float(timeout)) + 5
        while time.monotonic() < deadline:
            record = read_record(record_path)
            if confirmed(record, display):
                return record
            if failed():
                break
            time.sleep(.05)
        raise RuntimeError(tr("Current display lock was not confirmed; refusing sleep. See ",
                              "未确认当前屏幕已锁定，拒绝睡眠。日志：") + str(log_path))


if __name__ == "__main__":
    # ``--locker`` exists so the lock protocol can be exercised with a probe
    # binary; the desktop always uses the default swaylock.
    arguments = sys.argv[1:]
    options = {}
    if arguments[:1] == ["--locker"] and len(arguments) >= 2:
        options["locker"] = tuple(arguments[1:])
    elif arguments:
        print("Usage: lock_session.py [--locker COMMAND [ARG...]]", file=sys.stderr)
        raise SystemExit(2)
    try:
        lock(**options)
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
