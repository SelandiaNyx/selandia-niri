"""On-demand DRM client engine accounting; no daemon, subprocess or privileges.

Results cover readable clients of the current user, rather than all GPU work.
The summary is the busiest engine class, not a device-wide union of busy time.
Drivers may wake hardware when fdinfo is read, so suspended GPUs are skipped.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import re
import stat
import time


_PCI = re.compile(r"([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])\Z")
_UINT = re.compile(r"[0-9]+\Z")


def pci_address(value):
    match = _PCI.fullmatch(str(value))
    if match is None:
        return None
    domain, bus, slot, function = (int(part, 16) for part in match.groups())
    return f"{domain:04x}:{bus:02x}:{slot:02x}.{function:x}"


def _uint(value):
    if not isinstance(value, str) or not _UINT.fullmatch(value):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _text(path, limit=65536):
    with path.open(errors="replace") as stream:
        return stream.read(limit)


def parse_fdinfo(text):
    """Parse standard DRM counters; invalid/absent fields stay unavailable."""
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.startswith("drm-"):
            fields[key] = value.strip()
    device = pci_address(fields.get("drm-pdev"))
    client = _uint(fields.get("drm-client-id"))
    driver = fields.get("drm-driver", "")
    if device is None or client is None or not driver:
        return None
    capacities, engines = {}, {}
    memory = {"resident": {}, "shared": {}}
    for key, value in fields.items():
        if key.startswith("drm-engine-capacity-"):
            capacity = _uint(value)
            capacities[key.removeprefix("drm-engine-capacity-")] = capacity if capacity else None
        for kind in memory:
            prefix = f"drm-{kind}-"
            if key.startswith(prefix):
                tokens = value.split()
                amount = _uint(tokens[0]) if tokens else None
                multiplier = {"": 1, "KiB": 1024, "MiB": 1024 ** 2}.get(tokens[1] if len(tokens) == 2 else "")
                if amount is not None and multiplier is not None and len(tokens) <= 2:
                    memory[kind][key.removeprefix(prefix)] = amount * multiplier
    for key, value in fields.items():
        if key.startswith("drm-engine-") and not key.startswith("drm-engine-capacity-"):
            engine = key.removeprefix("drm-engine-")
            tokens = value.split()
            busy = _uint(tokens[0]) if len(tokens) == 2 and tokens[1] == "ns" else None
            if busy is not None:
                engines[engine] = ("time", busy, None)
        elif key.startswith("drm-cycles-"):
            engine = key.removeprefix("drm-cycles-")
            busy = _uint(value)
            total = _uint(fields.get(f"drm-total-cycles-{engine}"))
            if busy is not None and total is not None and engine not in engines:
                engines[engine] = ("cycles", busy, total)
    engines = {key: value for key, value in engines.items() if capacities.get(key, 1) is not None}
    return {"device": device, "client_id": client, "driver": driver,
            "engines": engines, "capacities": capacities, "memory": memory}


class DrmClientSampler:
    """Sample only when a detailed metrics page needs GPU readings.

    ``sample({pci_bdf: sysfs_device_path})`` returns one result per supplied GPU.
    Discovery of new clients is limited to once every ten seconds; cached unique
    clients are read at the caller's interval. Permission failures and sampling
    warmup are explicit. ``reset()`` drops all baselines when the page hides.
    """

    def __init__(self, proc_root=Path("/proc"), sys_root=Path("/sys"), *, clock=None,
                 uid=None, discovery_interval=10.0, max_gap=30.0,
                 scan_budget=0.05, max_descriptors=16384):
        self.proc = Path(proc_root)
        self.sys = Path(sys_root)
        self.clock = clock or time.monotonic
        self.uid = os.getuid() if uid is None else uid
        self.discovery_interval = discovery_interval
        self.max_gap = max_gap
        self.scan_budget = scan_budget
        self.max_descriptors = max_descriptors
        self.reset()

    def reset(self):
        self._paths = {}
        self._previous = {}
        self._last_scan = None
        self._last_time = None
        self._active = set()
        self._scan_complete = True
        self._inaccessible = 0
        self._unreadable = {}

    @staticmethod
    def _nodes(devices):
        nodes = {}
        for address, device in devices.items():
            for path in device.glob("drm/*/dev"):
                try:
                    major, minor = map(int, _text(path).strip().split(":"))
                    nodes[(major, minor)] = address
                except (OSError, ValueError):
                    pass
            # Also covers unusual sysfs layouts exposing only the card node.
            try:
                major, minor = map(int, _text(device.parent / "dev").strip().split(":"))
                nodes[(major, minor)] = address
            except (OSError, ValueError):
                pass
        return nodes

    @staticmethod
    def _fd_device(path, nodes):
        info = path.stat()
        if stat.S_ISCHR(info.st_mode):
            return nodes.get((os.major(info.st_rdev), os.minor(info.st_rdev)))
        return None

    def _record(self, path, nodes):
        address = self._fd_device(path, nodes)
        if address is None:
            return None
        try:
            record = parse_fdinfo(_text(path.parent.parent / "fdinfo" / path.name))
        except PermissionError:
            self._unreadable[address] = self._unreadable.get(address, 0) + 1
            return None
        if record is None or record["device"] != address:
            return None
        try:
            # PID reuse must not join the old process's sampling interval.
            process_stat = _text(path.parent.parent / "stat", 8192).rsplit(")", 1)[1].split()
            start_time = _uint(process_stat[19])
        except (OSError, IndexError):
            start_time = None
        record["owner"] = (path.parent.parent.name, start_time, path.name)
        return record

    def _discover(self, nodes):
        records, paths = {}, {}
        checked, started = 0, time.monotonic()
        self._scan_complete, self._inaccessible = True, 0
        try:
            with os.scandir(self.proc) as processes:
                for proc_entry in processes:
                    if not proc_entry.name.isdigit():
                        continue
                    try:
                        if proc_entry.stat().st_uid != self.uid:
                            continue
                        fd_dir = os.path.join(proc_entry.path, "fd")
                        with os.scandir(fd_dir) as descriptors:
                            for fd_entry in descriptors:
                                checked += 1
                                if checked > self.max_descriptors or (checked & 63 == 0 and time.monotonic() - started > self.scan_budget):
                                    self._scan_complete = False
                                    self._paths = paths
                                    return records
                                path = Path(fd_entry.path)
                                try:
                                    record = self._record(path, nodes)
                                except OSError:
                                    continue
                                if record is not None:
                                    key = (record["device"], record["client_id"])
                                    if key not in records:
                                        records[key], paths[key] = record, path
                    except PermissionError:
                        self._inaccessible += 1
                    except OSError:
                        continue
        except OSError:
            self._scan_complete = False
        self._paths = paths
        return records

    def _cached(self, nodes):
        records, missing = {}, False
        for key, path in self._paths.items():
            try:
                record = self._record(path, nodes)
            except OSError:
                record = None
            if record is None or (record["device"], record["client_id"]) != key:
                missing = True
            else:
                records[key] = record
        return records, missing

    def sample(self, devices):
        now = self.clock()
        supplied = {address: Path(path) for key, path in devices.items()
                    if (address := pci_address(key)) is not None}
        active = {}
        for address, device in supplied.items():
            try:
                power = _text(device / "power/runtime_status").strip()
            except OSError:
                power = ""
            if power not in ("suspended", "suspending", "resuming"):
                active[address] = device
        changed = set(active) != self._active
        if self._last_time is not None and (now <= self._last_time or now - self._last_time > self.max_gap):
            self._previous.clear()
        self._previous = {key: value for key, value in self._previous.items() if key[0] in active}
        self._last_time, self._active = now, set(active)
        self._unreadable = {}
        nodes = self._nodes(active)
        records = {}
        if nodes:
            if changed or self._last_scan is None or now - self._last_scan >= self.discovery_interval:
                records = self._discover(nodes)
                self._last_scan = now
            else:
                records, missing = self._cached(nodes)
                if missing:
                    records = self._discover(nodes)
                    self._last_scan = now
        else:
            self._paths.clear()
        results, next_previous = {}, {}
        for address in supplied:
            rows = [(key, record) for key, record in records.items() if key[0] == address]
            totals, capacities, unknown, memories = {}, {}, set(), {}
            for key, record in rows:
                previous = self._previous.get(key, {})
                same_owner = (record["owner"][1] is not None
                              and previous.get("owner") == record["owner"])
                baselines = {}
                for engine, (mode, busy, total) in record["engines"].items():
                    capacities[engine] = max(capacities.get(engine, 1), record["capacities"].get(engine, 1))
                    old = previous.get("engines", {}).get(engine) if same_owner else None
                    baseline = (mode, busy, total, now)
                    ratio = None
                    if old is not None and old[0] == mode:
                        if mode == "cycles" and total < old[2]:
                            pass  # GPU time reset: start a new interval.
                        elif busy < old[1]:
                            baseline = old  # Kernel permits temporary regression.
                        else:
                            elapsed = total - old[2] if mode == "cycles" else (now - old[3]) * 1e9
                            if elapsed > 0:
                                try:
                                    candidate = (busy - old[1]) / elapsed
                                    ratio = candidate if math.isfinite(candidate) else None
                                except OverflowError:
                                    pass
                    baselines[engine] = baseline
                    if ratio is None:
                        unknown.add(engine)
                    else:
                        totals[engine] = totals.get(engine, 0.0) + ratio
                next_previous[key] = {"owner": record["owner"], "engines": baselines}
                if len(memories) < 64:
                    memories[str(key[1])] = record["memory"]
            engines = {name: None if name in unknown else min(100.0, 100 * totals[name] / capacities[name])
                       for name in capacities}
            available = [value for value in engines.values() if value is not None]
            percent = max(available) if available and not unknown else None
            if address not in active:
                status = "suspended"
            elif not rows:
                status = "unreadable" if self._unreadable.get(address) or self._inaccessible else "no-clients"
                if address not in nodes.values():
                    status = "unavailable"
            else:
                status = "available" if percent is not None else "warmup" if engines else "unavailable"
            results[address] = {"percent": percent, "engine_percent": engines,
                                "source": "drm-fdinfo", "coverage": "readable-clients",
                                "status": status, "clients": len(rows),
                                "discovery_complete": self._scan_complete,
                                "inaccessible_processes": self._inaccessible,
                                "unreadable_descriptors": self._unreadable.get(address, 0),
                                "client_memory": memories, "client_memory_truncated": len(rows) > 64}
        self._previous = next_previous
        return results
