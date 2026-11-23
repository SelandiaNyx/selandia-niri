"""Read-only system inventory, usable without fastfetch, lspci or shell tools."""
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import time

from i18n import tr
from metrics import MetricsSampler, read_text, format_bytes, format_uptime


def niri_reply(request, environment):
    address = environment.get("NIRI_SOCKET")
    if not address:
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(.8)
            client.connect(address)
            client.sendall((json.dumps(request) + "\n").encode())
            data = bytearray()
            while b"\n" not in data and len(data) <= 512_000:
                part = client.recv(8192)
                if not part:
                    return None
                data.extend(part)
        response = json.loads(data.split(b"\n", 1)[0])
        return response.get("Ok", {}).get(request) if isinstance(response, dict) else None
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def installed_packages(var):
    local = Path(var) / "lib/pacman/local"
    try:
        if local.is_dir():
            return sum(entry.is_dir() and (entry / "desc").is_file() for entry in local.iterdir())
        status = Path(var) / "lib/dpkg/status"
        if status.is_file():
            return sum("Status: install ok installed" in block.splitlines()
                       for block in read_text(status).split("\n\n"))
    except OSError:
        pass
    return None


def local_addresses(proc):
    addresses = set()
    text = read_text(Path(proc) / "net/fib_trie")
    for raw in re.findall(r"\|--\s+([0-9.]+)\s*\n\s*/32 host LOCAL", text):
        try:
            address = ipaddress.ip_address(raw)
            if not address.is_loopback and not address.is_unspecified:
                addresses.add(str(address))
        except ValueError:
            pass
    for line in read_text(Path(proc) / "net/if_inet6").splitlines():
        fields = line.split()
        if len(fields) != 6:
            continue
        try:
            address = ipaddress.IPv6Address(int(fields[0], 16))
            if not address.is_loopback and not address.is_unspecified:
                addresses.add(str(address) + ("%" + fields[5] if address.is_link_local else ""))
        except ValueError:
            pass
    return sorted(addresses)


def desktop_preferences(config, *, gio=False):
    values = {}
    for filename in ("gtk-4.0/settings.ini", "gtk-3.0/settings.ini"):
        for line in read_text(Path(config) / filename).splitlines():
            if "=" in line and not line.lstrip().startswith(("#", ";")):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    if gio:
        try:
            from gi.repository import Gio
            source = Gio.SettingsSchemaSource.get_default()
            if source and source.lookup("org.gnome.desktop.interface", True):
                settings = Gio.Settings.new("org.gnome.desktop.interface")
                for output, key in (("gtk-theme-name", "gtk-theme"), ("gtk-icon-theme-name", "icon-theme"),
                                    ("gtk-font-name", "font-name")):
                    values.setdefault(output, settings.get_string(key))
        except (ImportError, ValueError, TypeError, RuntimeError):
            pass
    return values


def collect(*, proc=Path("/proc"), sys=Path("/sys"), etc=Path("/etc"), var=Path("/var"),
            environment=None, sampler=None, desktop=None):
    environment = dict(os.environ if environment is None else environment)
    proc, sys, etc = Path(proc), Path(sys), Path(etc)
    if sampler is None:
        sampler = MetricsSampler(proc, sys, etc_root=etc, detailed=True)
        data = sampler.inventory_sample()
    else:
        data = sampler.sample()
    system, cpu = data.get("system") or {}, data.get("cpu") or {}
    config = Path(environment.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    desktop = desktop if desktop is not None else desktop_preferences(config, gio=proc == Path("/proc"))
    missing = tr("Unavailable", "不可用")
    def show(value):
        return missing if value is None or value == "" else str(value)
    def pair(memory):
        return missing if not memory else format_bytes(memory.get("used")) + " / " + format_bytes(memory.get("total"))
    dmi = sys / "class/dmi/id"
    model = " · ".join(dict.fromkeys(value for name in ("sys_vendor", "product_name", "product_version")
                                     if (value := read_text(dmi / name)) and value not in ("None", "Default string", "To Be Filled By O.E.M.")))
    board = " · ".join(value for name in ("board_vendor", "board_name", "board_version") if (value := read_text(dmi / name)) and value not in ("None", "Default string", "To Be Filled By O.E.M."))
    shell = environment.get("SHELL")
    if not shell:
        for line in read_text(etc / "passwd").splitlines():
            fields = line.split(":")
            if len(fields) == 7 and fields[2] == str(os.getuid()):
                shell = fields[6]
                break
    displays = niri_reply("Outputs", environment)
    display_lines = []
    if isinstance(displays, dict):
        for name, output in displays.items():
            if not isinstance(output, dict):
                continue
            modes, index = output.get("modes") or [], output.get("current_mode")
            if type(index) is int and 0 <= index < len(modes) and isinstance(modes[index], dict):
                mode = modes[index]
                width, height, rate = (mode.get(key) for key in ("width", "height", "refresh_rate"))
                if all(type(value) is int and value > 0 for value in (width, height, rate)):
                    display_lines.append(f"{name}: {width}×{height} @ {rate / 1000:g} Hz")
    version = niri_reply("Version", environment)
    wm = ("Niri " + show(version) + " / Wayland") if environment.get("NIRI_SOCKET") else environment.get("XDG_CURRENT_DESKTOP")
    timezone = environment.get("TZ") or read_text(etc / "timezone")
    if not timezone:
        localtime = etc / "localtime"
        if localtime.is_symlink():
            target = str(localtime.resolve())
            timezone = target.split("/zoneinfo/", 1)[1] if "/zoneinfo/" in target else None
        elif etc == Path("/etc"):
            timezone = " / ".join(time.tzname)
    gpus = data.get("gpus") or []
    gpu_text = "\n".join(show(gpu.get("name")) + " · " + show(gpu.get("driver")) +
                         (" " + str(gpu["driver_version"]) if gpu.get("driver_version") else "") for gpu in gpus)
    terminal = environment.get("TERM_PROGRAM")
    if not terminal and (config / "niri/theme/alacritty.toml").is_file():
        import component_preferences
        terminal = component_preferences.load()['terminal'].capitalize() + " " + tr("(configured)", "（已配置）")
    rows = [
        (tr("Host", "主机"), read_text(proc / "sys/kernel/hostname")),
        (tr("Machine", "机型"), model), (tr("Mainboard", "主板"), board),
        (tr("Distribution", "发行版"), system.get("distribution")),
        (tr("Kernel", "内核"), system.get("kernel")), (tr("Architecture", "架构"), system.get("architecture")),
        (tr("Uptime", "运行时间"), format_uptime(data.get("uptime_seconds")) if data.get("uptime_seconds") is not None else None),
        (tr("Shell", "Shell"), shell), (tr("Desktop / WM", "桌面／窗口管理器"), wm),
        (tr("Terminal", "终端"), terminal), (tr("CPU", "处理器"), cpu.get("model")),
        (tr("Cores / threads", "物理核／逻辑线程"), show(cpu.get("physical_cores")) + " / " + show(cpu.get("logical_threads"))),
        (tr("CPU frequency", "处理器当前频率"), f"{cpu['frequency_mhz']:.0f} MHz" if cpu.get("frequency_mhz") is not None else None),
        (tr("GPU / driver", "显卡／驱动"), gpu_text), (tr("Memory", "内存"), pair(data.get("memory"))),
        (tr("Swap", "交换空间"), pair(data.get("swap"))), (tr("Root storage", "根分区"), pair(data.get("disk"))),
        (tr("Displays", "显示器"), "\n".join(display_lines)),
        (tr("Desktop theme", "桌面主题"), desktop.get("gtk-theme-name")),
        (tr("Icons", "图标主题"), desktop.get("gtk-icon-theme-name")),
        (tr("Font", "字体"), desktop.get("gtk-font-name")),
        (tr("Packages", "已安装包数量"), installed_packages(var)),
        (tr("Local IP", "本地 IP"), "\n".join(local_addresses(proc))),
        (tr("Language", "语言"), environment.get("LC_ALL") or environment.get("LC_MESSAGES") or environment.get("LANG")),
        (tr("Timezone", "时区"), timezone),
    ]
    return [(key, show(value)) for key, value in rows], displays if isinstance(displays, dict) else {}


def plain_text(rows):
    # Native Pango tab stops align translated keys, including fallback CJK fonts.
    lines = []
    for key, value in rows:
        parts = value.splitlines() or [tr("Unavailable", "不可用")]
        lines.append(key + "\t: " + parts[0])
        lines.extend("\t  " + part for part in parts[1:])
    return "\n".join(lines)
