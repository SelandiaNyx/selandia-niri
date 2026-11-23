"""Niri/Arch hardware brightness via Linux backlight and monitor DDC/CI.

Run read_state/set_percent off the GTK thread: DDC communication can be slow.
DRM connector links select the exact I²C bus; enumeration display numbers are
deliberately not used because they can change when a monitor is unplugged.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time


SYSFS = Path("/sys")
DEVICES = Path("/dev")
READ_INTERVAL = 15
FAILED_INTERVAL = 30
COMMAND_TIMEOUT = 6
_STEP_REUSE_WINDOW = 2.0
_lock = threading.RLock()
_cache = {}


def _text(path):
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return ""


def _run(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, text=True,
                                timeout=COMMAND_TIMEOUT,
                                env=dict(os.environ, LC_ALL="C.UTF-8"))
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Brightness request timed out · 亮度操作超时；请检查显示器 DDC/CI") from error
    except OSError as error:
        raise RuntimeError(f"Brightness command unavailable · 亮度命令不可用: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-400:]
        raise RuntimeError("Brightness request failed · 亮度操作失败" + (f": {detail}" if detail else ""))
    return result.stdout.strip()


def parse_vcp(output):
    """ddcutil --brief getvcp 10 returns decimal current and maximum values."""
    match = re.search(r"^VCP\s+10\s+C\s+(\d+)\s+(\d+)\s*$", output, re.MULTILINE)
    if not match:
        raise RuntimeError("Brightness VCP 0x10 unavailable; enable DDC/CI in the monitor menu · 显示器未返回亮度；请在屏幕菜单启用 DDC/CI")
    current, maximum = map(int, match.groups())
    if maximum <= 0 or current > maximum:
        raise RuntimeError("Invalid monitor brightness range · 显示器返回的亮度范围无效")
    return current, maximum


def _edid(connector):
    try:
        data = (connector / "edid").read_bytes()
    except OSError:
        data = b""
    model = ""
    if len(data) >= 128:
        for start in (54, 72, 90, 108):
            if data[start:start + 5] == b"\x00\x00\x00\xfc\x00":
                model = data[start + 5:start + 18].decode("ascii", errors="replace").strip("\x00\n \r")
                break
    return (hashlib.sha256(data).hexdigest()[:16] if data else "unknown"), model


def _discover():
    """Cheap sysfs inventory on each poll also invalidates hotplugged buses."""
    devices = []
    for backlight in sorted((SYSFS / "class/backlight").glob("*")):
        if not (backlight / "brightness").exists():
            continue
        devices.append({"id": f"backlight:{backlight.name}", "label": f"Built-in · 内置屏幕 ({backlight.name})",
                        "backend": "backlight", "output": "", "name": backlight.name,
                        "path": str(backlight), "percent": None, "available": False, "reason": ""})
    has_backlight = bool(devices)
    for connector in sorted((SYSFS / "class/drm").glob("card*-*")):
        if _text(connector / "status") != "connected":
            continue
        output = re.sub(r"^card\d+-", "", connector.name)
        if has_backlight and output.startswith(("eDP-", "LVDS-")):
            continue
        fingerprint, model = _edid(connector)
        bus_name = (connector / "ddc").resolve().name
        bus_match = re.fullmatch(r"i2c-(\d+)", bus_name)
        devices.append({"id": f"ddc:{connector.name}:{fingerprint}",
                        "label": f"{model} · {output}" if model else output,
                        "backend": "ddc", "output": output, "connector": connector.name,
                        "fingerprint": fingerprint,
                        "bus": int(bus_match.group(1)) if bus_match else None,
                        "percent": None, "available": False, "reason": ""})
    return devices


def _read_device(device):
    if device["backend"] == "backlight":
        if not shutil.which("brightnessctl"):
            raise RuntimeError("Install brightnessctl with ./control.sh repair · 请运行 ./control.sh repair 安装 brightnessctl")
        path = Path(device["path"])
        try:
            current, maximum = int(_text(path / "brightness")), int(_text(path / "max_brightness"))
        except ValueError as error:
            raise RuntimeError("Backlight brightness unavailable · 无法读取内置屏幕亮度") from error
        if maximum <= 0 or current < 0 or current > maximum:
            raise RuntimeError("Invalid backlight range · 内置背光范围无效")
    else:
        if not shutil.which("ddcutil"):
            raise RuntimeError("Install ddcutil with ./control.sh repair · 请运行 ./control.sh repair 安装 ddcutil")
        bus = device["bus"]
        if bus is None:
            raise RuntimeError("No DDC bus for this connector · 此接口未提供 DDC 总线；请检查连接线或转接器")
        node = DEVICES / f"i2c-{bus}"
        if not node.exists():
            if not (SYSFS / "module/i2c_dev").exists():
                raise RuntimeError("Load i2c-dev: sudo modprobe i2c-dev · 请加载 I²C 内核模块：sudo modprobe i2c-dev")
            raise RuntimeError(f"{node} unavailable · I²C 设备不可访问；请检查显示器连接与设备访问权限")
        if not os.access(node, os.R_OK | os.W_OK):
            raise RuntimeError(f"No read/write access to {node}; re-login after installing ddcutil · 无 I²C 读写权限；安装 ddcutil 后请重新登录以应用 udev 权限")
        current, maximum = parse_vcp(_run(["ddcutil", "--noconfig", "--bus", str(bus), "--brief", "getvcp", "10"]))
    device.update(percent=round(current / maximum * 100), current=current, maximum=maximum,
                  available=True, reason="")
    return device


def read_state(force=False):
    """Hardware values are cached 5 s; failures 30 s. No brightness is changed."""
    with _lock:
        now = time.monotonic()
        devices = _discover()
        active = {device["id"] for device in devices}
        for identifier in list(_cache):
            if identifier not in active:
                del _cache[identifier]
        for index, device in enumerate(devices):
            cached = _cache.get(device["id"])
            # Include bus/path in comparison: a stable connector may move buses.
            identity = (device.get("bus"), device.get("path"))
            if cached and cached[2] == identity and not force:
                interval = READ_INTERVAL if cached[1]["available"] else FAILED_INTERVAL
                if now - cached[0] < interval:
                    devices[index] = copy.deepcopy(cached[1])
                    continue
            try:
                _read_device(device)
            except RuntimeError as error:
                device.update(available=False, percent=None, reason=str(error))
            _cache[device["id"]] = (time.monotonic(), copy.deepcopy(device), identity)
        reason = "" if any(device["available"] for device in devices) else (
            "\n".join(f'{device["label"]}: {device["reason"]}' for device in devices)
            or "No connected brightness device · 未检测到可调亮度的屏幕")
        return {"devices": devices, "reason": reason}


def set_percent(device_id, value):
    """Validate a currently attached device, then set verified hardware brightness."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Brightness must be 0–100% · 亮度必须在 0–100% 范围内")
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("Select a brightness device · 请选择亮度设备")
    with _lock:
        devices = _discover()
        device = next((item for item in devices if item["id"] == device_id), None)
        if device is None:
            raise RuntimeError("Selected display disconnected or replaced · 所选屏幕已断开或被替换，请重新选择")
        # Read the live maximum; never assume monitors use a 0–100 VCP range.
        # Reuse a very fresh cached reading (e.g., from step()) to avoid double DDC I2C.
        identity = (device.get("bus"), device.get("path"))
        cached = _cache.get(device_id)
        if (cached and cached[2] == identity and cached[1].get("available")
                and cached[1].get("maximum") and time.monotonic() - cached[0] < _STEP_REUSE_WINDOW):
            device.update(maximum=cached[1]["maximum"], current=cached[1]["current"],
                          percent=cached[1]["percent"], available=True, reason="")
        else:
            _read_device(device)
        target = round(value * device["maximum"] / 100)
        if device["backend"] == "backlight":
            _run(["brightnessctl", "--class=backlight", "--device", device["name"], "set", str(target)])
            _read_device(device)
        else:
            # Recheck EDID/bus after the read so a hotplug cannot redirect a write.
            current = next((item for item in _discover() if item["id"] == device_id), None)
            if current is None or current["bus"] != device["bus"]:
                raise RuntimeError("Display connection changed; retry · 显示器连接已变化，请重试")
            _run(["ddcutil", "--noconfig", "--bus", str(device["bus"]), "--verify", "setvcp", "10", str(target)])
            device.update(current=target, percent=round(target / device["maximum"] * 100))
        _cache[device_id] = (time.monotonic(), copy.deepcopy(device), identity)
        return device


_DEFAULT_RUN = _run


def _focused_output():
    if _run is _DEFAULT_RUN and os.environ.get("NIRI_SOCKET"):
        try:
            from niri_events import request as niri_request
            output = niri_request("FocusedOutput", timeout=2)
            return output.get("name", "") if isinstance(output, dict) else ""
        except (ImportError, OSError, RuntimeError, ValueError):
            pass
    try:
        output = json.loads(_run(["niri", "msg", "--json", "focused-output"]))
        return output.get("name", "") if isinstance(output, dict) else ""
    except (RuntimeError, ValueError):
        return ""


def step(direction, device_id=None):
    if direction not in ("up", "down"):
        raise ValueError("Use up or down · 请使用 up 或 down")
    with _lock:
        discovered = _discover()
        if not discovered:
            raise RuntimeError("No connected brightness device · 未检测到可调亮度的屏幕")
        target = None
        if device_id:
            target = next((item for item in discovered if item["id"] == device_id), None)
            if target is None:
                raise RuntimeError("Selected brightness device unavailable · 所选亮度设备不可用")
        else:
            focused = _focused_output()
            target = next((item for item in discovered if item["output"] == focused), None)
            if target is None:
                target = next((item for item in discovered if item["backend"] == "backlight"), None)
            if target is None and len(discovered) == 1:
                target = discovered[0]
        if target is not None:
            try:
                _read_device(target)
                _cache[target["id"]] = (time.monotonic(), copy.deepcopy(target), (target.get("bus"), target.get("path")))
                device = target
            except RuntimeError as error:
                if device_id or len(discovered) == 1:
                    raise RuntimeError(f'{target["label"]}: {error}') from error
                device = None
        else:
            device = None
    if device is None:
        state = read_state(force=True)
        devices = [item for item in state["devices"] if item["available"]]
        focused = _focused_output()
        device = next((item for item in devices if item["output"] == focused), None)
        if device is None:
            device = next((item for item in devices if item["backend"] == "backlight"), None)
        if device is None and len(devices) == 1:
            device = devices[0]
        if device is None:
            raise RuntimeError(state["reason"] or "Select a monitor in Control Center · 请在控制中心选择显示器")
    return set_percent(device["id"], max(0, min(100, device["percent"] + (5 if direction == "up" else -5))))


def main():
    parser = argparse.ArgumentParser(description="Hardware brightness · 硬件亮度控制")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("get")
    stepping = commands.add_parser("step")
    stepping.add_argument("direction", choices=("up", "down"))
    stepping.add_argument("--device")
    setting = commands.add_parser("set")
    setting.add_argument("device")
    setting.add_argument("percent", type=float)
    arguments = parser.parse_args()
    try:
        if arguments.command == "get":
            print(json.dumps(read_state(), ensure_ascii=False))
        else:
            device = (step(arguments.direction, arguments.device) if arguments.command == "step"
                      else set_percent(arguments.device, arguments.percent))
            print(f'{device["label"]}: {device["percent"]}%')
    except (RuntimeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
