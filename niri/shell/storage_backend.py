"""Native storage (lsblk/udisksctl), USB/PCI hardware inventory, and CUPS probe."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from i18n import tr

ENV = dict(os.environ, LC_ALL="C")


def _capture(argv: list[str], *, timeout: int = 8) -> str | None:
    if not shutil.which(argv[0]):
        return None
    try:
        res = subprocess.run(argv, capture_output=True, text=True, env=ENV, timeout=timeout)
        return res.stdout if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def read_disks() -> list[dict]:
    """List physical disks and their partitions with live capacity and mount state."""
    raw = _capture(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL,MODEL,RM,TRAN,HOTPLUG"])
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    disks = []
    for dev in data.get("blockdevices") or []:
        if dev.get("type") != "disk":
            continue
        if str(dev.get("name", "")).startswith(("loop", "zram", "ram")):
            continue
        children = []
        for part in dev.get("children") or []:
            mp = part.get("mountpoint") or ""
            used = total = percent = None
            if mp and os.path.isdir(mp):
                try:
                    usage = shutil.disk_usage(mp)
                    used, total = usage.used, usage.total
                    percent = round((used / total) * 100, 1) if total > 0 else 0.0
                except OSError:
                    pass
            children.append({
                "name": part.get("name", ""),
                "path": part.get("path") or f"/dev/{part.get('name', '')}",
                "size": int(part.get("size") or 0),
                "fstype": part.get("fstype") or "",
                "mountpoint": mp,
                "label": part.get("label") or "",
                "used": used, "total": total, "percent": percent,
                "removable": bool(dev.get("rm") or dev.get("hotplug")),
            })
        disks.append({
            "name": dev.get("name", ""),
            "path": dev.get("path") or f"/dev/{dev.get('name', '')}",
            "model": (dev.get("model") or dev.get("name") or "").strip(),
            "size": int(dev.get("size") or 0),
            "tran": (dev.get("tran") or "").upper(),
            "removable": bool(dev.get("rm") or dev.get("hotplug")),
            "partitions": children,
        })
    return disks


def mount_partition(dev_path: str) -> str:
    if not shutil.which("udisksctl"):
        raise RuntimeError(tr("udisksctl is not installed", "未安装 udisksctl"))
    res = subprocess.run(["udisksctl", "mount", "-b", dev_path], capture_output=True, text=True, env=ENV, timeout=15)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or tr("Mount failed", "挂载失败"))
    return res.stdout.strip()


def unmount_partition(dev_path: str, *, power_off: bool = False) -> str:
    if not shutil.which("udisksctl"):
        raise RuntimeError(tr("udisksctl is not installed", "未安装 udisksctl"))
    res = subprocess.run(["udisksctl", "unmount", "-b", dev_path], capture_output=True, text=True, env=ENV, timeout=15)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or tr("Unmount failed", "卸载失败"))
    if power_off:
        subprocess.run(["udisksctl", "power-off", "-b", dev_path], capture_output=True, text=True, env=ENV, timeout=10)
    return res.stdout.strip()


def read_usb_devices() -> list[dict]:
    """Read connected USB devices straight from sysfs without external commands."""
    root = Path("/sys/bus/usb/devices")
    if not root.is_dir():
        return []
    items = []
    seen = set()
    for entry in sorted(root.iterdir()):
        prod_file = entry / "product"
        if not prod_file.is_file():
            continue
        try:
            product = prod_file.read_text(errors="ignore").strip()
            vendor = (entry / "manufacturer").read_text(errors="ignore").strip() if (entry / "manufacturer").is_file() else ""
            vid = (entry / "idVendor").read_text(errors="ignore").strip() if (entry / "idVendor").is_file() else ""
            pid = (entry / "idProduct").read_text(errors="ignore").strip() if (entry / "idProduct").is_file() else ""
        except OSError:
            continue
        if not product or "root hub" in product.lower():
            continue
        key = (vid, pid, product)
        if key in seen:
            continue
        seen.add(key)
        items.append({"name": product, "vendor": vendor, "id": f"{vid}:{pid}" if vid and pid else ""})
    return items[:24]


def read_pci_summary() -> list[dict]:
    import shlex
    raw = _capture(["lspci", "-mm"])
    if not raw:
        return []
    interesting = ("vga", "3d", "display", "audio", "network", "ethernet", "nvme")
    devices = []
    for line in raw.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 4:
            continue
        cls = parts[1]
        if any(tag in cls.lower() for tag in interesting):
            devices.append({"class": cls, "vendor": parts[2], "name": parts[3]})
    return devices[:16]


def read_printers() -> dict:
    if not shutil.which("lpstat"):
        return {"available": False, "printers": []}
    out = _capture(["lpstat", "-p"]) or ""
    printers = [line.strip() for line in out.splitlines() if line.strip().startswith("printer ")]
    return {"available": True, "printers": printers}


def read_state() -> dict:
    return {
        "disks": read_disks(),
        "usb": read_usb_devices(),
        "pci": read_pci_summary(),
        "printers": read_printers(),
        "udisks_available": bool(shutil.which("udisksctl")),
    }
