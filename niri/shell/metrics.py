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
from pathlib import Path
import re
import shutil
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
                values[fields[0]] = max(0, int(fields[1])) * 1024
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
                      "used": total - available, "percent": 100 * (total - available) / total}
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
                 run=None, disk_usage=None):
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
            for path in sorted(directory.glob("temp*_input")):
                value = number(read_text(path), -50000, 200000)
                if value is None or path.resolve() in seen:
                    continue
                seen.add(path.resolve())
                label = read_text(path.with_name(path.name.replace("_input", "_label")))
                readings.append({"name": f"{chip} · {label or path.stem}", "celsius": value / 1000})
        if not readings:
            for directory in sorted((self.sys / "class/thermal").glob("thermal_zone*")):
                value = number(read_text(directory / "temp"), -50000, 200000)
                if value is not None:
                    readings.append({"name": read_text(directory / "type") or directory.name,
                                     "celsius": value / 1000})
        return readings

    def _gpus(self):
        readings, seen, nvidia_paths = [], set(), []
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
            temperatures = [number(read_text(path), -50000, 200000)
                            for path in device.glob("hwmon/hwmon*/temp*_input")]
            temperatures = [value / 1000 for value in temperatures if value is not None]
            reading = {
                "name": read_text(device / "product_name") or f"{vendor} · {card.name}",
                "percent": number(read_text(device / "gpu_busy_percent"), 0, 100),
                "temperature": max(temperatures) if temperatures else None,
                "memory_used": number(read_text(device / "mem_info_vram_used"), 0),
                "memory_total": number(read_text(device / "mem_info_vram_total"), 0),
                "source": vendor,
            }
            readings.append(reading)
        # Avoid waking a runtime-suspended discrete GPU for a decorative meter.
        suspended = nvidia_paths and all(read_text(path / "power/runtime_status") == "suspended" for path in nvidia_paths)
        if self.nvidia_command and not suspended:
            try:
                result = self.run([self.nvidia_command,
                                   "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total",
                                   "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                  timeout=0.8, check=False)
                nvidia = []
                if result.returncode == 0:
                    for fields in csv.reader(result.stdout.splitlines()):
                        if len(fields) != 5:
                            continue
                        used, total = number(fields[3], 0), number(fields[4], 0)
                        nvidia.append({"name": fields[0].strip(), "percent": number(fields[1], 0, 100),
                                       "temperature": number(fields[2], -50, 200),
                                       "memory_used": int(used * 1024 ** 2) if used is not None else None,
                                       "memory_total": int(total * 1024 ** 2) if total is not None else None,
                                       "source": "NVIDIA"})
                if nvidia:
                    readings = [reading for reading in readings if reading["source"] != "NVIDIA"] + nvidia
            except (OSError, subprocess.SubprocessError):
                pass
        return readings

    def sample(self) -> dict:
        now = self.clock()
        memory, swap = parse_memory(read_text(self.proc / "meminfo"))
        network = self._network(now)
        self.previous_time = now
        try:
            usage = self.disk_usage(self.disk_path)
            disk = {"total": usage.total, "used": usage.used, "free": usage.free,
                    "percent": 100 * usage.used / usage.total if usage.total else 0.0}
        except OSError:
            disk = None
        uptime = read_text(self.proc / "uptime").split()
        load = [number(field, 0) for field in read_text(self.proc / "loadavg").split()[:3]]
        return {"cpu_percent": self._cpu(), "memory": memory, "swap": swap,
                "network": network, "gpus": self._gpus(), "temperatures": self._temperatures(),
                "disk": disk, "uptime_seconds": number(uptime[0], 0) if uptime else None,
                "load_average": load if len(load) == 3 and None not in load else None}


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
        if chip not in chips or temperature["celsius"] > chips[chip]["celsius"]:
            chips[chip] = temperature
    for _, temperature in sorted(chips.items())[:6]:
        lines.append(f"{temperature['name']}  {temperature['celsius']:.0f}°C")
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
