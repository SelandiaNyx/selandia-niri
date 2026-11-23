#!/usr/bin/env python3
"""Publish one confirmed Wayland screen lock for a single display.

Started either by a per-display systemd user unit (its own cgroup, so stopping
the service that asked for the lock cannot end it) or, when no user manager is
reachable and the caller is not itself a service, directly by
``lock_session.py``. Both launchers share this one readiness implementation:
the client owns the swaylock ``--ready-fd`` handshake and writes the identity
record only after the locker confirmed readiness on the requested display.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys

from i18n import tr
from lock_session import (ENVIRONMENT_KEYS, confirmed, display_identity, paths, process_identity,
                          read_record, write_record)

KEY = re.compile(r"[0-9a-f]{20}")


def runtime_directory():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or not Path(runtime).is_absolute():
        raise RuntimeError(tr("XDG_RUNTIME_DIR is not set; cannot lock safely.", "未设置 XDG_RUNTIME_DIR，无法安全锁屏。"))
    return Path(runtime)


def validate_request(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("unsupported lock request")
    if not isinstance(data.get("display"), str) or not data["display"]:
        raise ValueError("lock request has no display")
    locker = data.get("locker")
    if not isinstance(locker, list) or not locker or not all(
            isinstance(argument, str) and argument and "\0" not in argument for argument in locker):
        raise ValueError("lock request has no usable locker command")
    if not isinstance(data.get("config"), str) or not Path(data["config"]).is_file():
        raise ValueError("lock request has no lock configuration")
    timeout = data.get("timeout")
    if type(timeout) not in (int, float) or not 0 < float(timeout) <= 120:
        raise ValueError("lock request has an invalid timeout")
    environment = data.get("environment", {})
    if not isinstance(environment, dict) or not all(
            key in ENVIRONMENT_KEYS and isinstance(value, str) and "\0" not in value
            for key, value in environment.items()):
        raise ValueError("lock request has an invalid environment")
    return data


def load_request(key):
    runtime = runtime_directory()
    request_path = (runtime / ("selandia-lock-" + key)).with_suffix(".request")
    if request_path.is_symlink():
        raise RuntimeError("Lock request is not a regular file")
    return runtime, validate_request(json.loads(request_path.read_text()))


def notify_ready():
    """Tell systemd this unit is up; harmless when there is no NOTIFY_SOCKET."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.connect(address)
            connection.send(b"READY=1")
    except OSError:
        return False
    return True


def note(log_path, message):
    try:
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as stream:
            stream.write(message.rstrip("\n") + "\n")
    except OSError:
        pass


def locker_arguments(request, ready_fd):
    return [*request["locker"], "-C", request["config"], "--ready-fd", str(ready_fd)]


def start_locker(request, display, log_path):
    """Run the locker with a readiness pipe; return (process, identity)."""
    read_fd, write_fd = os.pipe()
    process = None
    confirmed_ok = False
    try:
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "a") as log:
            process = subprocess.Popen(locker_arguments(request, write_fd),
                                       pass_fds=(write_fd,), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
        os.close(write_fd)
        write_fd = None
        ready = select.select([read_fd], [], [], float(request["timeout"]))[0]
        if not ready or os.read(read_fd, 1) != b"\n" or process.poll() is not None:
            raise RuntimeError(tr("Current display lock was not confirmed; refusing sleep. See ",
                                  "未确认当前屏幕已锁定，拒绝睡眠。日志：") + str(log_path))
        identity = process_identity(process.pid)
        if not identity or identity["display"] != display:
            raise RuntimeError(tr("Cannot verify the locker belongs to this display.",
                                  "无法确认锁屏进程属于当前显示会话。"))
        confirmed_ok = True
        return process, identity
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        if process is not None and not confirmed_ok:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            else:
                try:
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass


def serve(key):
    runtime, request = load_request(key)
    os.environ.update(request["environment"])
    display = request["display"]
    if display_identity() != display:
        raise RuntimeError(tr("The lock request belongs to another Wayland display.",
                              "锁屏请求属于其他 Wayland 显示会话。"))
    if paths(runtime, display)[0] != key:
        raise RuntimeError(tr("The lock request does not match its display key.",
                              "锁屏请求与显示标识不匹配。"))
    prefix = runtime / ("selandia-lock-" + key)
    record_path = prefix.with_suffix(".json")
    log_path = prefix.with_suffix(".log")
    if confirmed(read_record(record_path), display):
        # A confirmed lock already exists for this display; never start a second
        # locker, but still report readiness for a restarted unit.
        notify_ready()
        return 0
    process, identity = start_locker(request, display, log_path)
    try:
        write_record(record_path, identity)
    except OSError as error:
        note(log_path, "readiness record could not be published: " + str(error))
    notify_ready()
    # Keeping the main process alive is what keeps the unit's cgroup alive; the
    # locker is never signalled by this process.
    process.wait()
    return 0


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) != 2 or not KEY.fullmatch(argv[1]):
        print("Usage: lock_client.py <display-key>", file=sys.stderr)
        return 2
    try:
        return serve(argv[1])
    except Exception as error:
        print(str(error), file=sys.stderr)
        try:
            note((runtime_directory() / ("selandia-lock-" + argv[1])).with_suffix(".log"), str(error))
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
