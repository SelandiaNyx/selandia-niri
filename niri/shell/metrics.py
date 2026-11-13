#!/usr/bin/env python3
"""Read-only Linux metrics shared by Waybar and the desktop's system page.

``MetricsSampler.sample()`` returns CPU percent; memory/swap/disk dictionaries
(byte counts and percent); a network dictionary (primary interface and byte/s,
plus per-interface readings); GPU and temperature lists; uptime and load average.
All missing readings and rate warmups use None, not a made-up zero. CPU and
network rates require two samples. Network summary follows one default-route
interface, so bridge/VPN traffic is never counted twice in an aggregate.

Call sample from a worker thread: proc/sys reads are fast, but optional NVIDIA
queries can take up to 0.8 seconds. No external monitoring package is required.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from i18n import tr
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import time


UNAVAILABLE = "—"


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def number(value, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    if minimum is not None and result < minimum:
        return None
    if maximum is not None and result > maximum:
        return None
    return result


def parse_cpu(text: str) -> tuple[int, int] | None:
    """Return total and idle ticks, without double-counting guest/guest_nice."""
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] == "cpu":
            try:
                values = [int(value) for value in fields[1:9]]
            except ValueError:
                return None
            if len(values) < 4 or any(value < 0 for value in values):
                return None
            return sum(values), values[3] + (values[4] if len(values) > 4 else 0)
    return None


def parse_memory(text: str) -> tuple[dict | None, dict | None]:
    values = {}
    for line in text.splitlines():
        fields = line.replace(":", "", 1).split()
        if len(fields) >= 2:
            try:
                value = int(fields[1])
                if value >= 0:
                    values[fields[0]] = value * 1024
            except ValueError:
                continue
    total = values.get("MemTotal", 0)
    memory = None
    if total:
        available = values.get("MemAvailable")
        if available is None and "MemFree" in values:
            available = sum(values.get(key, 0) for key in
                            ("MemFree", "Buffers", "Cached", "SReclaimable")) - values.get("Shmem", 0)
        if available is not None:
            available = min(total, max(0, available))
            memory = {"total": total, "available": available,
                      "used": total - available, "percent": 100 * (total - available) / total,
                      **{key: values.get(source) for key, source in
                         (("free", "MemFree"), ("cached", "Cached"), ("buffers", "Buffers"), ("reclaimable", "SReclaimable"))}}
    swap = None
    if "SwapTotal" in values and "SwapFree" in values:
        total = values["SwapTotal"]
        used = max(0, total - min(total, values["SwapFree"]))
        swap = {"total": total, "used": used, "percent": 100 * used / total if total else 0.0}
    return memory, swap


def parse_network(text: str) -> dict[str, tuple[int, int]]:
    result = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        interface, payload = line.rsplit(":", 1)
        fields = payload.split()
        if len(fields) < 16 or interface.strip() == "lo":
            continue
        try:
            counters = int(fields[0]), int(fields[8])
        except ValueError:
            continue
        if all(value >= 0 for value in counters):
            result[interface.strip()] = counters
    return result


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return UNAVAILABLE
    value = float(value)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(value) < 1024 or suffix == "PiB":
            return f"{value:.0f} {suffix}" if suffix == "B" else f"{value:.1f} {suffix}"
        value /= 1024
    return UNAVAILABLE


def format_rate(value: int | float | None) -> str:
    return format_bytes(value) + "/s" if value is not None else UNAVAILABLE


def format_percent(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else UNAVAILABLE


def gpu_activity_text(gpu):
    status = gpu.get('status')
    if gpu.get('percent') is None:
        return {
            'suspended': tr('Sleeping', '休眠中'),
            'warmup': tr('Collecting baseline…', '正在采集基线…'),
            'no-clients': tr('No readable GPU clients', '无可读取的 GPU 客户端'),
            'unreadable': tr('GPU clients unavailable', '无法读取 GPU 客户端'),
        }.get(status, tr('Unavailable', '不可用'))
    value = format_percent(gpu['percent'])
    if gpu.get('coverage') == 'readable-clients':
        return value + tr(' · readable clients, busiest engine', ' · 可读客户端，最忙引擎')
    return value


def format_uptime(seconds: float | None) -> str:
    if seconds is None:
        return UNAVAILABLE
    minutes = int(seconds) // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return (f"{days}d " if days else "") + f"{hours}h {minutes}m"


class MetricsSampler:
    def __init__(self, proc_root=Path("/proc"), sys_root=Path("/sys"),
                 disk_path=Path("/"), enable_nvidia=True, *, clock=None,
                 run=None, disk_usage=None, detailed=False, etc_root=Path("/etc"),
                 pci_ids=Path("/usr/share/hwdata/pci.ids")):
        self.proc = Path(proc_root)
        self.sys = Path(sys_root)
        self.disk_path = Path(disk_path)
        self.enable_nvidia = enable_nvidia
        self.clock = clock or time.monotonic
        self.run = run or subprocess.run
        self.disk_usage = disk_usage or shutil.disk_usage
        self.previous_cpu = None
        self.previous_network = {}
        self.previous_time = None
        self.nvidia_command = shutil.which("nvidia-smi") if enable_nvidia else None
        self.detailed = detailed
        self.etc = Path(etc_root)
        self.pci_ids = Path(pci_ids)
        self.pci_names = None
        self.previous_processes = {}
        self.previous_process_time = None
        self._inventory_cache = {}
        self.gpu_sampler = None
        self.gpu_read_allowed = lambda: True

    def _cached_inventory(self, key, seconds, load):
        now = self.clock()
        cached = self._inventory_cache.get(key)
        if cached is None or now < cached[0] or now - cached[0] >= seconds:
            cached = (now, load())
            self._inventory_cache[key] = cached
        return cached[1]

    def _cpu_rows(self):
        rows = []
        for block in read_text(self.proc / "cpuinfo").split("\n\n"):
            row = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
            row = {key.strip(): value.strip() for key, value in row.items()}
            if row:
                rows.append(row)
        return rows

    def _cpu_inventory(self):
        rows = self._cpu_rows()
        models = list(dict.fromkeys(row.get("model name") or row.get("Processor") for row in rows
                                   if row.get("model name") or row.get("Processor")))
        processors = {row["processor"] for row in rows if row.get("processor", "").isdigit()}
        topology = {(row["physical id"], row["core id"]) for row in rows
                    if row.get("physical id", "").isdigit() and row.get("core id", "").isdigit()}
        cores = len(topology) if rows and topology and all(row.get("core id", "").isdigit() and
                    row.get("physical id", "").isdigit() for row in rows) else None
        cpus, sys_topology, complete = [], set(), True
        for cpu in (self.sys / "devices/system/cpu").glob("cpu[0-9]*"):
            if not re.fullmatch(r"cpu\d+", cpu.name) or read_text(cpu / "online") == "0":
                continue
            cpus.append(cpu)
            package, core = (read_text(cpu / "topology" / name) for name in ("physical_package_id", "core_id"))
            if package.isdigit() and core.isdigit():
                sys_topology.add((package, core))
            else:
                complete = False
        if cores is None and sys_topology and complete:
            cores = len(sys_topology)
        return (dict(model=" / ".join(models) or None, physical_cores=cores,
                     logical_threads=len(processors) if processors else len(cpus) or None), cpus)

    def _cpu_info(self):
        # Topology/model do not need a full 24+ CPU inventory every two seconds.
        # A hotplug mask change invalidates immediately; a short TTL also covers
        # unusual kernels without a global online mask.
        online = read_text(self.sys / "devices/system/cpu/online")
        if getattr(self, "_cpu_online", None) != online:
            self._inventory_cache.pop("cpu", None)
            self._cpu_online = online
        static, cpus = self._cached_inventory("cpu", 30, self._cpu_inventory)
        frequencies = []
        for cpu in cpus:
            frequency = number(read_text(cpu / "cpufreq/scaling_cur_freq"), 1, 20000000)
            if frequency is not None:
                frequencies.append(frequency / 1000)
        if not frequencies:
            frequencies = [value for row in self._cpu_rows()
                           if (value := number(row.get("cpu MHz"), 1, 20000)) is not None]
        return {**static, "frequency_mhz": sum(frequencies) / len(frequencies) if frequencies else None,
                "min_mhz": min(frequencies) if frequencies else None,
                "max_mhz": max(frequencies) if frequencies else None}

    def _system(self):
        values = {}
        for line in read_text(self.etc / "os-release").splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            try:
                tokens = shlex.split(value)
                if len(tokens) == 1:
                    values[key] = tokens[0]
            except ValueError:
                pass
        return dict(distribution=values.get("PRETTY_NAME") or values.get("NAME"),
                    kernel=read_text(self.proc / "sys/kernel/osrelease") or None,
                    architecture=os.uname().machine if self.proc == Path("/proc") else None)

    def _mounts(self):
        mounts = {}
        pseudo = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "securityfs",
                  "pstore", "efivarfs", "debugfs", "tracefs", "configfs", "fusectl", "mqueue", "hugetlbfs",
                  "rpc_pipefs", "binfmt_misc", "nsfs", "ramfs"}
        for line in read_text(self.proc / "self/mountinfo").splitlines():
            left, separator, right = line.partition(" - ")
            fields, tail = left.split(), right.split()
            if not separator or len(fields) < 6 or len(tail) < 2 or tail[0] in pseudo:
                continue
            decode = lambda value: re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)
            mount, source = decode(fields[4]), decode(tail[1])
            if not mount.startswith("/"):
                continue
            mounts[mount] = dict(mount=mount, device=source, filesystem=tail[0], total=None, used=None, free=None, percent=None)
        for row in list(mounts.values())[:64]:
            # Do not let an unavailable network/autofs mount stall all metrics.
            if row["filesystem"] in ("nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs", "autofs"):
                continue
            try:
                usage = self.disk_usage(Path(row["mount"]))
                row.update(total=usage.total, used=usage.used, free=usage.free,
                           percent=100 * usage.used / usage.total if usage.total else None)
            except OSError:
                pass
        return sorted(mounts.values(), key=lambda row: row["mount"])[:64]

    def _processes(self, now):
        try:
            ticks, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError):
            return []
        elapsed = now - self.previous_process_time if self.previous_process_time is not None else 0
        previous, current, rows = self.previous_processes, {}, []
        for path in self.proc.glob("[0-9]*/stat"):
            try:
                raw = read_text(path)
                header, tail = raw.rsplit(")", 1)
                fields = tail.split()
                if fields[0] == "Z":
                    continue
                pid, start = int(path.parent.name), int(fields[19])
                cpu = int(fields[11]) + int(fields[12])
                resident = int(fields[21])
                if cpu < 0 or resident < 0:
                    continue
                key = (pid, start)
                percent = None
                if key in previous and elapsed > 0 and cpu >= previous[key]:
                    percent = 100 * (cpu - previous[key]) / ticks / elapsed
                current[key] = cpu
                name = " ".join(header.split("(", 1)[1].split())[:60]
                rows.append(dict(pid=pid, name=name, cpu_percent=percent, memory=resident * page))
            except (ValueError, IndexError):
                continue
        self.previous_processes, self.previous_process_time = current, now
        return sorted(rows, key=lambda row: (row["cpu_percent"] if row["cpu_percent"] is not None else -1,
                                            row["memory"]), reverse=True)[:8]

    def _pci_name(self, vendor, device):
        if self.pci_names is None:
            self.pci_names = {}
            current = None
            for line in read_text(self.pci_ids).splitlines():
                if re.match(r"^[0-9a-fA-F]{4}  ", line):
                    current = line[:4].lower()
                elif current and re.match(r"^\t[0-9a-fA-F]{4}  ", line):
                    self.pci_names[(current, line[1:5].lower())] = line[7:].strip()
        return self.pci_names.get((vendor.removeprefix("0x"), device.removeprefix("0x")))

    def _cpu(self):
        current = parse_cpu(read_text(self.proc / "stat"))
        previous, self.previous_cpu = self.previous_cpu, current
        if current is None or previous is None:
            return None
        total, idle = current[0] - previous[0], current[1] - previous[1]
        if total <= 0 or idle < 0 or idle > total:
            return None
        return 100 * (total - idle) / total

    def _primary_interface(self, available):
        candidates = []
        for line in read_text(self.proc / "net/route").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 8 and fields[0] in available and fields[1] == "00000000" and fields[7] == "00000000":
                try:
                    if int(fields[3], 16) & 1:
                        candidates.append((int(fields[6]), fields[0]))
                except ValueError:
                    continue
        if candidates:
            return min(candidates)[1]
        for line in read_text(self.proc / "net/ipv6_route").splitlines():
            fields = line.split()
            if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00" and fields[-1] in available:
                try:
                    if int(fields[8], 16) & 1:
                        candidates.append((int(fields[5], 16), fields[-1]))
                except ValueError:
                    continue
        if candidates:
            return min(candidates)[1]
        # Local traffic remains useful without a default route; prefer physical
        # interfaces and report exactly which interface supplies the summary.
        physical = [name for name in available if (self.sys / "class/net" / name / "device").exists()]
        return sorted(physical or available)[0] if available else None

    def _network(self, now):
        counters = parse_network(read_text(self.proc / "net/dev"))
        elapsed = now - self.previous_time if self.previous_time is not None else 0
        rows, next_previous = [], {}
        for interface, pair in sorted(counters.items()):
            directory = self.sys / "class/net" / interface
            if read_text(directory / "operstate") in ("down", "notpresent", "lowerlayerdown"):
                continue
            identity = read_text(directory / "ifindex")
            previous = self.previous_network.get(interface)
            down = up = None
            if previous and previous[2] == identity and elapsed > 0:
                received, sent = pair[0] - previous[0], pair[1] - previous[1]
                if received >= 0 and sent >= 0:
                    down, up = received / elapsed, sent / elapsed
            next_previous[interface] = (*pair, identity)
            rows.append({"name": interface, "down_bps": down, "up_bps": up,
                         "received": pair[0], "sent": pair[1]})
        self.previous_network = next_previous
        primary = self._primary_interface(next_previous)
        selected = next((row for row in rows if row["name"] == primary), {})
        return {"interface": primary, "down_bps": selected.get("down_bps"),
                "up_bps": selected.get("up_bps"), "interfaces": rows}

    def _temperatures(self):
        readings = []
        seen = set()
        for directory in sorted((self.sys / "class/hwmon").glob("hwmon*")):
            chip = read_text(directory / "name") or directory.name
            # xe hwmon callbacks acquire runtime-PM references: even a decorative
            # temperature read can wake an otherwise suspended discrete card.
            if read_text(directory / "device/power/runtime_status") in ("suspended", "suspending", "resuming"):
                if self.detailed:
                    readings.append({"name": chip, "celsius": None})
                continue
            for path in sorted(directory.glob("temp*_input")):
                value = number(read_text(path), -50000, 200000)
                if (value is None and not self.detailed) or path.resolve() in seen:
                    continue
                seen.add(path.resolve())
                label = read_text(path.with_name(path.name.replace("_input", "_label")))
                readings.append({"name": f"{chip} · {label or path.stem}", "celsius": value / 1000 if value is not None else None})
        if not any(item['celsius'] is not None for item in readings):
            for directory in sorted((self.sys / "class/thermal").glob("thermal_zone*")):
                value = number(read_text(directory / "temp"), -50000, 200000)
                if value is not None or self.detailed:
                    readings.append({"name": read_text(directory / "type") or directory.name,
                                     "celsius": value / 1000 if value is not None else None})
        return readings

    def _gpus(self):
        readings, seen, nvidia_paths, pci_readings = [], set(), [], {}
        client_devices, client_readings, nvidia_targets = {}, {}, []
        vendors = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}
        for card in sorted((self.sys / "class/drm").glob("card*")):
            if not re.fullmatch(r"card\d+", card.name):
                continue
            device = card / "device"
            if not device.exists() or device.resolve() in seen:
                continue
            seen.add(device.resolve())
            vendor = vendors.get(read_text(device / "vendor"), "GPU")
            if vendor == "NVIDIA":
                nvidia_paths.append(device)
            suspended_card = read_text(device / "power/runtime_status") in ("suspended", "suspending", "resuming")
            temperatures = [] if suspended_card else [number(read_text(path), -50000, 200000)
                            for path in device.glob("hwmon/hwmon*/temp*_input")]
            temperatures = [value / 1000 for value in temperatures if value is not None]
            reading = {
                "name": read_text(device / "product_name") or
                        (self._pci_name(read_text(device / "vendor"), read_text(device / "device")) if self.detailed else None) or f"{vendor} · {card.name}",
                "percent": None if suspended_card else number(read_text(device / "gpu_busy_percent"), 0, 100),
                "temperature": max(temperatures) if temperatures else None,
                "memory_used": None if suspended_card else number(read_text(device / "mem_info_vram_used"), 0),
                "memory_total": None if suspended_card else number(read_text(device / "mem_info_vram_total"), 0),
                "source": vendor,
                "driver": device.joinpath("driver").resolve().name if device.joinpath("driver").exists() else None,
                "pci_id": (read_text(device / "vendor") + ":" + read_text(device / "device")) if read_text(device / "device") else None,
                "status": "suspended" if suspended_card else "available",
            }
            reading['utilization_source'] = 'sysfs' if reading['percent'] is not None else None
            reading['coverage'] = 'whole-device' if reading['percent'] is not None else None
            readings.append(reading)
            address = device.resolve().name
            if re.fullmatch(r"[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", address):
                pci_readings[tuple(int(part, 16) for part in re.split(r"[:.]", address))] = reading
                if vendor == "NVIDIA":
                    nvidia_targets.append((address, device, reading))
                if self.detailed and reading['percent'] is None and reading['driver'] in ('i915', 'xe', 'amdgpu'):
                    client_devices[address] = device
                    client_readings[address] = reading
        # Detailed System-page sampling only. Decorative bar/Quick sampling must
        # neither scan /proc clients nor wake a discrete GPU for telemetry.
        if client_devices and self.gpu_read_allowed():
            if self.gpu_sampler is None:
                from gpu_metrics import DrmClientSampler
                self.gpu_sampler = DrmClientSampler(proc_root=self.proc, sys_root=self.sys, clock=self.clock)
            for address, values in self.gpu_sampler.sample(client_devices).items():
                reading = client_readings[address]
                reading.update(percent=values.get('percent'), engine_percent=values.get('engine_percent', {}),
                               utilization_source=values.get('source'), coverage=values.get('coverage'),
                               status=values.get('status'), clients=values.get('clients'),
                               discovery_complete=values.get('discovery_complete'),
                               inaccessible_processes=values.get('inaccessible_processes'),
                               unreadable_descriptors=values.get('unreadable_descriptors'))
        # A query without --id visits every NVIDIA card, including sleeping ones.
        # Keep that legacy fallback only when sysfs exposes no NVIDIA device.
        if not self.nvidia_command:
            return readings
        targets = nvidia_targets if nvidia_paths else [(None, None, None)]
        deadline = time.monotonic() + 0.8 if nvidia_paths else None
        for address, device, selected in targets:
            if not self.gpu_read_allowed():
                break
            if device is not None and read_text(device / "power/runtime_status") in ("suspended", "suspending", "resuming"):
                selected.update(percent=None, temperature=None, memory_used=None, memory_total=None,
                                status="suspended", utilization_source=None, coverage=None)
                continue
            timeout = deadline - time.monotonic() if deadline is not None else 0.8
            if timeout <= 0:
                break
            try:
                query = "name,utilization.gpu,temperature.gpu,memory.used,memory.total"
                if self.detailed or address is not None:
                    query += ",pci.bus_id,driver_version"
                command = [self.nvidia_command, "--query-gpu=" + query, "--format=csv,noheader,nounits"]
                if address is not None:
                    command.append("--id=" + address)
                result = self.run(command, capture_output=True, text=True, timeout=timeout, check=False)
                nvidia = []
                if result.returncode == 0:
                    for fields in csv.reader(result.stdout.splitlines()):
                        if len(fields) not in (5, 7):
                            continue
                        used, total = number(fields[3], 0), number(fields[4], 0)
                        original = {}
                        if len(fields) == 7:
                            reported = fields[5].strip()
                            if re.fullmatch(r"[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", reported):
                                original = pci_readings.get(tuple(int(part, 16) for part in re.split(r"[:.]", reported)), {})
                        # Never merge an unexpected response into another card,
                        # or accept an identity-free result for a targeted query.
                        if selected is not None and original is not selected:
                            continue
                        nvidia.append({**original, "name": fields[0].strip(), "percent": number(fields[1], 0, 100),
                                       "temperature": number(fields[2], -50, 200),
                                       "memory_used": int(used * 1024 ** 2) if used is not None else None,
                                       "memory_total": int(total * 1024 ** 2) if total is not None else None,
                                       "source": "NVIDIA", "utilization_source": "nvidia-smi",
                                       "coverage": "whole-device", "driver": original.get("driver"),
                                       "pci_id": original.get("pci_id"),
                                       "driver_version": fields[6].strip() if len(fields) == 7 and fields[6].strip() not in ("", "N/A", "[N/A]") else None})
                if nvidia:
                    if selected is not None:
                        selected.update(nvidia[0])
                    else:
                        readings.extend(nvidia)
            except (OSError, subprocess.SubprocessError):
                pass
        return readings

    def prime(self):
        """Capture a baseline so the next sample can report a real CPU/network rate.

        The control center calls this when the System page becomes visible, then
        samples a fraction of a second later. It is a cheap one-shot read, not a
        polling loop, and leaves the public sample() warmup contract unchanged.
        """
        if self.gpu_sampler is not None:
            self.gpu_sampler.reset()
        self.previous_cpu = parse_cpu(read_text(self.proc / "stat"))
        self.previous_time = self.clock()
        self._network(self.previous_time)

    def sample(self) -> dict:
        now = self.clock()
        memory, swap = parse_memory(read_text(self.proc / "meminfo"))
        network = self._network(now)
        self.previous_time = now
        try:
            usage = self.disk_usage(self.disk_path)
            disk = {"total": usage.total, "used": usage.used, "free": usage.free,
                    "percent": 100 * usage.used / usage.total if usage.total else None}
        except OSError:
            disk = None
        uptime = read_text(self.proc / "uptime").split()
        load = [number(field, 0) for field in read_text(self.proc / "loadavg").split()[:3]]
        result = {"cpu_percent": self._cpu(), "memory": memory, "swap": swap,
                "network": network, "gpus": self._gpus(), "temperatures": self._temperatures(),
                "disk": disk, "uptime_seconds": number(uptime[0], 0) if uptime else None,
                "load_average": load if len(load) == 3 and None not in load else None}
        if self.detailed:
            result.update(system=dict(self._cached_inventory("system", 300, self._system)),
                          cpu=self._cpu_info(),
                          mounts=[dict(row) for row in self._cached_inventory("mounts", 10, self._mounts)],
                          processes=self._processes(now))
        return result


def detailed_sections(values):
    """Plain text inventories: missing values stay explicitly unavailable."""
    unavailable = tr("Unavailable", "不可用")
    show = lambda value: unavailable if value is None or value == "" else str(value)
    size = lambda value: unavailable if value is None else format_bytes(value)
    cpu, memory, swap = values.get("cpu") or {}, values.get("memory") or {}, values.get("swap") or {}
    frequency = cpu.get("frequency_mhz")
    cpu_text = "\n".join([show(cpu.get("model")),
        tr("Physical cores: ", "物理核心：") + show(cpu.get("physical_cores")),
        tr("Logical threads: ", "逻辑线程：") + show(cpu.get("logical_threads")),
        tr("Current average: ", "当前平均频率：") + (f"{frequency:.0f} MHz" if frequency is not None else unavailable)])
    memory_text = "\n".join(tr(english, chinese) + size(memory.get(key)) for key, english, chinese in
                    (("total", "Total: ", "总计："), ("used", "Used: ", "已用："), ("available", "Available: ", "可用："),
                     ("free", "Free: ", "空闲："), ("cached", "Cache: ", "缓存："), ("buffers", "Buffers: ", "缓冲：")))
    memory_text += "\n" + tr("Swap used / total: ", "交换已用／总计：") + size(swap.get("used")) + " / " + size(swap.get("total"))
    memory_text += "\n" + tr("Swap free: ", "交换空闲：") + size(swap["total"] - swap["used"] if swap.get("total") is not None and swap.get("used") is not None else None)
    mount_text = "\n\n".join(f"{row['mount']} · {row['device']} · {row['filesystem']}\n" +
        tr("Used / total: ", "已用／总计：") + size(row["used"]) + " / " + size(row["total"]) +
        " · " + tr("Free: ", "可用：") + size(row["free"]) for row in values.get("mounts", [])) or unavailable
    gpu_text = "\n\n".join(show(gpu.get("name")) + "\n" + tr("Driver: ", "驱动：") + show(gpu.get("driver")) +
                            (" · " + gpu["driver_version"] if gpu.get("driver_version") else "") +
                            "\nPCI " + show(gpu.get("pci_id")) +
                            "\n" + tr("Activity: ", "活动：") + gpu_activity_text(gpu) +
                            ''.join('\n' + name + ': ' + format_percent(percent)
                                    for name, percent in (gpu.get('engine_percent') or {}).items()) +
                            ('\n' + tr('Coverage: readable clients only; other users may be excluded.',
                                       '覆盖范围：仅可读客户端，可能不含其他用户。')
                             if gpu.get('coverage') == 'readable-clients' else '')
                            for gpu in values.get("gpus", [])) or unavailable
    process_text = "\n".join(f"{row['pid']}  {row['name']}\nCPU " +
        (f"{row['cpu_percent']:.1f}%" if row["cpu_percent"] is not None else unavailable) + " · " +
        tr("Resident: ", "驻留内存：") + size(row["memory"]) for row in values.get("processes", [])) or unavailable
    return [(tr("CPU details", "处理器详情"), cpu_text), (tr("Memory details", "内存与交换详情"), memory_text),
            (tr("Mounted partitions", "挂载分区"), mount_text), (tr("GPU details and activity", "显卡信息与活动"), gpu_text),
            (tr("Top processes · CPU%, then resident memory", "占用最高的进程 · 先按 CPU，再按驻留内存"), process_text)]


def waybar_payload(data: dict) -> dict:
    memory, disk, swap = data.get("memory"), data.get("disk"), data.get("swap")
    text = f"󰍛 {format_percent(data.get('cpu_percent'))}  󰘚 {format_percent(memory['percent'] if memory else None)}"
    gpus = data.get("gpus", [])
    gpu_loads = [gpu["percent"] for gpu in gpus if gpu.get("percent") is not None]
    if gpu_loads:
        text += f"  󰢮 {format_percent(max(gpu_loads))}"
    lines = [tr("System monitor", "系统监控"), "CPU  " + format_percent(data.get("cpu_percent"))]
    if data.get("load_average"):
        lines.append(tr("Load  ", "平均负载  ") + " / ".join(f"{value:.2f}" for value in data["load_average"]))
    lines.append(tr("Memory  ", "内存  ") + (f"{format_bytes(memory['used'])} / {format_bytes(memory['total'])} ({format_percent(memory['percent'])})" if memory else UNAVAILABLE))
    lines.append(tr("Swap  ", "交换空间  ") + (f"{format_bytes(swap['used'])} / {format_bytes(swap['total'])}" if swap else UNAVAILABLE))
    lines.append(tr("Root storage  ", "根分区  ") + (f"{format_bytes(disk['used'])} / {format_bytes(disk['total'])} ({format_percent(disk['percent'])})" if disk else UNAVAILABLE))
    network = data.get("network", {})
    lines.append(tr("Network", "网络") + f" ({network.get('interface') or UNAVAILABLE})  ↓ {format_rate(network.get('down_bps'))}  ↑ {format_rate(network.get('up_bps'))}")
    for gpu in gpus:
        detail = f"GPU · {gpu['name']}  {format_percent(gpu.get('percent'))}"
        if gpu.get("temperature") is not None:
            detail += f" · {gpu['temperature']:.0f}°C"
        if gpu.get("memory_total"):
            detail += f" · VRAM {format_bytes(gpu.get('memory_used'))}/{format_bytes(gpu['memory_total'])}"
        lines.append(detail)
    # One hottest reading per sensor chip keeps dozens of CPU/VRAM channels
    # from pushing CPU package, NVMe and board temperatures out of the tooltip.
    chips = {}
    for temperature in data.get("temperatures", []):
        chip = temperature["name"].split(" · ", 1)[0]
        value = temperature.get("celsius")
        if chip not in chips or (value is not None and
                                 (chips[chip].get("celsius") is None or value > chips[chip]["celsius"])):
            chips[chip] = temperature
    for _, temperature in sorted(chips.items())[:6]:
        value = temperature.get("celsius")
        lines.append(f"{temperature['name']}  " + (f"{value:.0f}°C" if value is not None else UNAVAILABLE))
    lines += [tr("Uptime  ", "已运行  ") + format_uptime(data.get("uptime_seconds")),
              tr("Click: system details", "点击：系统详情"), tr("— Unavailable / warming up", "— 不可用 / 采样中")]
    percentages = [value for value in [data.get("cpu_percent"), memory["percent"] if memory else None, *gpu_loads] if value is not None]
    level = "critical" if any(value >= 95 for value in percentages) else "warning" if any(value >= 85 for value in percentages) else "normal"
    return {"text": text, "tooltip": html.escape("\n".join(lines)), "class": level}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waybar", action="store_true", help="Continuously emit Waybar JSON")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval < 0.25:
        parser.error("interval must be at least 0.25 seconds")
    sampler = MetricsSampler()
    try:
        while True:
            started = time.monotonic()
            data = sampler.sample()
            print(json.dumps(waybar_payload(data) if args.waybar else data, ensure_ascii=False), flush=True)
            if not args.waybar:
                break
            time.sleep(max(0, args.interval - (time.monotonic() - started)))
    except (BrokenPipeError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
