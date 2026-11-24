"""Native Storage & Devices page: disks, mount/eject, USB/PCI inventory & printers."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from control_widgets import (
    card_grid,
    data_row,
    grid_add,
    icon,
    nyx_guide_banner,
    pack,
    status_badge,
    style,
    wrap_label,
)
from i18n import tr
from metrics import format_bytes
import storage_backend as backend


class StoragePage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.busy = False

        pack(self, nyx_guide_banner(
            "storage",
            tr("Inspect every NVMe/SATA/USB drive, mount or safely eject partitions, and browse USB/PCI peripherals.",
               "直接查看所有硬盘与分区容量、一键挂载或安全弹出移动存储，并浏览本机 USB / PCI 外设清单。"),
        ))

        top = pack(self, Gtk.Box(spacing=8))
        self.notice = pack(top, wrap_label("", "hint"), True)
        refresh_btn = style(Gtk.Button(label=tr("Refresh devices", "刷新设备")), "small-button")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        pack(top, refresh_btn)

        # Disks card (full width)
        disks_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(disks_card, wrap_label(tr("DISKS & PARTITIONS", "磁盘与分区挂载"), "section-title"))
        self.disks_box = pack(disks_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8))
        pack(self, disks_card)

        wide = getattr(panel, "panel_width", 1200) >= 1020
        grid = pack(self, card_grid(wide, 12))

        usb_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(usb_card, wrap_label(tr("USB PERIPHERALS", "USB 外设"), "section-title"))
        self.usb_box = pack(usb_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        grid_add(grid, usb_card)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        pci_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(pci_card, wrap_label(tr("PCI HARDWARE", "PCI 硬件总线"), "section-title"))
        self.pci_box = pack(pci_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        pack(right, pci_card)

        print_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(print_card, wrap_label(tr("PRINTERS (CUPS)", "打印机服务"), "section-title"))
        self.printer_box = pack(print_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        pack(right, print_card)
        grid_add(grid, right)

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.notice.set_text(tr("Scanning storage and peripherals…", "正在扫描磁盘与外设…"))
        self.panel.work(backend.read_state, self._done, self._failed)

    def _failed(self, err):
        self.busy = False
        self.notice.set_text(str(err))

    def _done(self, state: dict):
        self.busy = False
        self.notice.set_text("")
        udisks_ok = state.get("udisks_available", False)

        for box in (self.disks_box, self.usb_box, self.pci_box, self.printer_box):
            for child in box.get_children():
                child.destroy()

        disks = state.get("disks") or []
        if not disks:
            pack(self.disks_box, wrap_label(tr("No block storage detected.", "未检测到块存储设备。"), "hint"))
        for disk in disks:
            header = Gtk.Box(spacing=8)
            pack(header, icon("drive-removable-media-symbolic" if disk["removable"] else "drive-harddisk-symbolic", 18))
            pack(header, wrap_label(f"{disk['model']}  ({disk['path']})", "control-label"), True)
            tag = f"{format_bytes(disk['size'])}" + (f" · {disk['tran']}" if disk["tran"] else "")
            pack(header, status_badge(tag, "warn" if disk["removable"] else "info"))
            pack(self.disks_box, header)

            for part in disk["partitions"]:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                col._row_expand = True
                title = f"{part['path']}" + (f" · {part['label']}" if part["label"] else "")
                subtitle = f"{part['fstype'] or 'raw'} · {format_bytes(part['size'])}"
                if part["mountpoint"]:
                    subtitle += f" · {part['mountpoint']}"
                pack(col, wrap_label(title, "control-label"))
                pack(col, wrap_label(subtitle, "hint"))
                if part["percent"] is not None:
                    bar = style(Gtk.ProgressBar(), "metric-progress")
                    bar.set_fraction(max(0.0, min(1.0, part["percent"] / 100.0)))
                    bar.set_tooltip_text(f"{format_bytes(part['used'])} / {format_bytes(part['total'])} ({part['percent']}%)")
                    pack(col, bar)
                actions = Gtk.Box(spacing=6)
                if part["mountpoint"]:
                    if part["mountpoint"] not in ("/", "/boot", "/boot/efi", "/home"):
                        um = style(Gtk.Button(label=tr("Eject", "安全弹出") if part["removable"] else tr("Unmount", "卸载")), "small-button")
                        um.set_sensitive(udisks_ok)
                        um.connect("clicked", lambda _b, p=part: self._unmount(p["path"], p["removable"]))
                        pack(actions, um)
                    else:
                        pack(actions, status_badge(tr("System", "系统卷"), "ok"))
                elif part["fstype"] and part["fstype"] != "swap":
                    mt = style(Gtk.Button(label=tr("Mount", "挂载")), "small-button")
                    mt.set_sensitive(udisks_ok)
                    mt.connect("clicked", lambda _b, p=part: self._mount(p["path"]))
                    pack(actions, mt)
                pack(self.disks_box, data_row(col, actions))

        usb = state.get("usb") or []
        if not usb:
            pack(self.usb_box, wrap_label(tr("No external USB devices detected.", "未检测到外部 USB 设备。"), "hint"))
        for item in usb:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col._row_expand = True
            pack(col, wrap_label(item["name"], "control-label"))
            sub = " · ".join(p for p in (item["vendor"], item["id"]) if p)
            if sub:
                pack(col, wrap_label(sub, "hint"))
            pack(self.usb_box, data_row(icon("drive-removable-media-symbolic", 16), col))

        pci = state.get("pci") or []
        if not pci:
            pack(self.pci_box, wrap_label(tr("PCI summary unavailable.", "无法读取 PCI 硬件信息。"), "hint"))
        for dev in pci:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col._row_expand = True
            pack(col, wrap_label(dev["name"], "control-label"))
            pack(col, wrap_label(f"{dev['class']} · {dev['vendor']}", "hint"))
            pack(self.pci_box, data_row(col))

        pr = state.get("printers") or {}
        if not pr.get("available"):
            cups_cmd = "pacman -S cups"
            pack(self.printer_box, wrap_label(
                tr(f"CUPS printing service is not installed. Install cups ({cups_cmd}) to manage printers and queues here.",
                   f"本机未安装 CUPS 打印服务。如需管理打印机，可执行 {cups_cmd} 并启用 cups.service。"),
                "hint",
            ))
        elif not pr.get("printers"):
            pack(self.printer_box, wrap_label(tr("CUPS is installed; no printers configured yet.", "CUPS 已就绪，当前尚未配置打印机。"), "hint"))
        else:
            for line in pr["printers"]:
                pack(self.printer_box, data_row(icon("printer-symbolic", 16), wrap_label(line, "control-label")))

        for box in (self.disks_box, self.usb_box, self.pci_box, self.printer_box):
            box.show_all()

    def _mount(self, path: str):
        self.notice.set_text(tr(f"Mounting {path}…", f"正在挂载 {path}…"))
        self.panel.work(lambda: backend.mount_partition(path), lambda _: self.refresh(),
                        lambda err: self.notice.set_text(str(err)), commit=True)

    def _unmount(self, path: str, power_off: bool):
        self.notice.set_text(tr(f"Unmounting {path}…", f"正在卸载 {path}…"))
        self.panel.work(lambda: backend.unmount_partition(path, power_off=power_off), lambda _: self.refresh(),
                        lambda err: self.notice.set_text(str(err)), commit=True)
