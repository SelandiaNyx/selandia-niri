#!/usr/bin/env python3
"""Read-only persistent evidence for physical suspend and display wake failures.

This never suspends, unlocks, restarts services, or changes monitor power.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'niri/shell'))
from i18n import tr


def read_text(path):
    try:
        return Path(path).read_text().strip() or None
    except (OSError, UnicodeError):
        return None


def command(args, runner=subprocess.run):
    try:
        result = runner(args, capture_output=True, text=True, timeout=8)
        return {'command': args, 'returncode': result.returncode,
                'stdout': result.stdout[-500_000:], 'stderr': result.stderr[-32_000:]}
    except (OSError, subprocess.SubprocessError) as error:
        return {'command': args, 'returncode': None, 'stdout': '', 'stderr': str(error)}


def connect_system_bus(Gio, GLib):
    """Bound the recorder's setup; use only from the user's real terminal."""
    pending = Gio.Cancellable()
    loop = GLib.MainLoop()
    result = {}
    def complete(_source, response, _data):
        try:
            result['bus'] = Gio.bus_get_finish(response)
        except GLib.Error as error:
            result['error'] = error
        loop.quit()
    def expire():
        result['error'] = TimeoutError(tr('System bus connection timed out after 5 seconds.',
                                        '连接系统总线超过 5 秒，已停止等待。'))
        pending.cancel()
        loop.quit()
        return False
    deadline = GLib.timeout_add(5000, expire)
    Gio.bus_get(Gio.BusType.SYSTEM, pending, complete, None)
    loop.run()
    # An expired source removes itself; never remove a recycled source ID.
    if not isinstance(result.get('error'), TimeoutError):
        GLib.source_remove(deadline)
    if 'error' in result:
        raise result['error']
    return result['bus']


def devices(root=Path('/sys/class/drm')):
    result = []
    for path in sorted(Path(root).glob('card*')):
        if (path / 'status').exists():
            result.append({'connector': path.name, 'status': read_text(path / 'status'),
                           'enabled': read_text(path / 'enabled'), 'modes': read_text(path / 'modes')})
        elif (path / 'device').exists():
            result.append({'gpu': path.name, 'driver': (path / 'device/driver').resolve().name
                           if (path / 'device/driver').exists() else None,
                           'vendor': read_text(path / 'device/vendor'), 'device': read_text(path / 'device/device')})
    return result


def event(value):
    match = re.search(r'PrepareForSleep\s*\((true|false)\s*,?\)', value)
    return ('before-sleep' if match.group(1) == 'true' else 'after-resume') if match else None


def capture(output, label, runner=subprocess.run):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    commands = {
        'kernel': ['journalctl', '-b', '-k', '--no-pager', '-n', '800', '-o', 'short-monotonic'],
        'dmesg': ['dmesg', '--time-format', 'iso'],
        'niri-journal': ['journalctl', '--user', '-b', '-u', 'niri.service', '--no-pager', '-n', '400', '-o', 'short-monotonic'],
        'niri-process-journal': ['journalctl', '-b', '_COMM=niri', '--no-pager', '-n', '400', '-o', 'short-monotonic'],
        'sleep-journal': ['journalctl', '-b', '-u', 'systemd-suspend.service', '-u', 'systemd-logind.service', '--no-pager', '-n', '100', '-o', 'short-monotonic'],
        'lock-journal': ['journalctl', '--user', '-b', '-u', 'selandia-niri@sleep-lock.service', '-u', 'selandia-lock@*', '--no-pager', '-n', '150', '-o', 'short-monotonic'],
        'user-units': ['systemctl', '--user', 'show', 'niri.service', 'selandia-niri@idle.service', 'selandia-niri@sleep-lock.service', 'selandia-lock@*', '--property=Id,ActiveState,SubState,MainPID,Result,ExecMainStatus'],
        'sleep-units': ['systemctl', 'show', 'sleep.target', 'suspend.target', 'systemd-suspend.service', '--property=Id,ActiveState,SubState,MainPID,Result,ExecMainStatus'],
        'processes': ['ps', '-eo', 'pid,ppid,state,wchan:24,comm'],
        'inhibitors': ['systemd-inhibit', '--list', '--no-pager'],
    }
    if os.environ.get('NIRI_SOCKET'):
        commands['outputs'] = ['niri', 'msg', '--json', 'outputs']
    values = {'label': label, 'utc': datetime.now(timezone.utc).isoformat(),
              'monotonic': time.monotonic(), 'boot_id': read_text('/proc/sys/kernel/random/boot_id'),
              'mem_sleep': read_text('/sys/power/mem_sleep'), 'drm': devices(),
              'compositor_socket': os.environ.get('NIRI_SOCKET'),
              'commands': {name: command(args, runner) for name, args in commands.items()}}
    # A unique, atomic filename survives restart and never rewrites an earlier sample.
    path = output / (str(time.time_ns()) + '-' + label + '.json')
    temporary = path.with_suffix('.partial')
    with temporary.open('w') as handle:
        json.dump(values, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    print(tr('Evidence saved: ', '证据已保存：') + str(path), flush=True)
    return path


def record(output):
    import gi
    from gi.repository import Gio, GLib
    capture(output, 'start')
    bus = connect_system_bus(Gio, GLib)
    executor = ThreadPoolExecutor(max_workers=1)
    count = [0]
    def changed(_bus, _sender, _path, _iface, _signal, parameters, _data):
        sleeping = parameters.unpack()[0]
        count[0] += 1
        label = 'before-sleep' if sleeping else 'after-resume'
        marker = Path(output) / 'events.jsonl'
        with marker.open('a') as handle:
            handle.write(json.dumps({'event': label, 'utc': datetime.now(timezone.utc).isoformat(),
                                      'monotonic': time.monotonic()}) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        executor.submit(capture, output, label)
        if not sleeping:
            GLib.timeout_add_seconds(15, lambda: (executor.submit(capture, output, 'resume-plus-15s'), False)[1])
    subscription = bus.signal_subscribe('org.freedesktop.login1', 'org.freedesktop.login1.Manager',
                                       'PrepareForSleep', '/org/freedesktop/login1', None,
                                       Gio.DBusSignalFlags.NONE, changed, None)
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        bus.signal_unsubscribe(subscription)
        executor.shutdown(wait=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'record'))
    parser.add_argument('--output', type=Path, default=ROOT / '.validation/resume-actual')
    parser.add_argument('--label', choices=('before', 'after', 'failure', 'current'), default='current')
    args = parser.parse_args()
    record(args.output) if args.action == 'record' else capture(args.output, args.label)


if __name__ == '__main__':
    main()
