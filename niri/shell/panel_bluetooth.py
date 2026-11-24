"""Native BlueZ D-Bus Bluetooth Center: scan, pair, connect, trust & battery."""
from __future__ import annotations

import shutil

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

import bluetooth_backend as backend
from bluetooth_controls import BluetoothPolicyControls
from control_widgets import (
    card_grid,
    data_row,
    grid_add,
    icon,
    inline_confirm_bar,
    nyx_guide_banner,
    pack,
    setting_row,
    status_badge,
    style,
    wrap_label,
)
from i18n import tr


class BluetoothPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.busy = False
        self.adapter_path = None
        self._guard = False
        self._scan_timer = None
        self._poll_timer = None

        pack(self, nyx_guide_banner(
            "bluetooth",
            tr("Powered directly by BlueZ D-Bus: scan, pair, connect, check battery levels and configure boot AutoEnable.",
               "直连系统 BlueZ 总线：支持原机扫描、配对、连接、耳机与键鼠电量读取及开机自启策略，无需额外工具。"),
        ))

        self.notice = pack(self, wrap_label("", "hint"))
        self.notice.set_no_show_all(True)

        # Adapter bar
        adapter_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(adapter_card, wrap_label(tr("BLUETOOTH ADAPTER", "蓝牙适配器"), "section-title"))
        self.power_switch = Gtk.Switch()
        self.power_switch.connect("state-set", self._on_power_toggle)
        self.adapter_title = tr("Bluetooth power", "蓝牙开关")
        pack(adapter_card, setting_row(self.adapter_title, self.power_switch,
                                       tr("Enable adapter to connect paired devices or discover new ones",
                                          "开启后即可连接已配对设备或扫描周围新设备")))
        btn_row = pack(adapter_card, Gtk.Box(spacing=8))
        self.scan_btn = style(Gtk.Button(label=tr("Scan nearby devices (15s)", "扫描附近设备（15 秒）")), "accent-button")
        self.scan_btn.connect("clicked", lambda _: self._toggle_scan())
        refresh_btn = Gtk.Button(label=tr("Refresh", "刷新"))
        refresh_btn.connect("clicked", lambda _: self.refresh())
        pack(btn_row, self.scan_btn, True)
        pack(btn_row, refresh_btn)
        if shutil.which("blueman-manager"):
            adv = style(Gtk.Button(label=tr("Blueman…", "高级蓝牙管理器…")), "small-button")
            adv.connect("clicked", lambda _: self.panel.launch_external(["blueman-manager"]))
            pack(btn_row, adv)
        self.confirm_slot = pack(adapter_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        self.confirm_slot.set_no_show_all(True)
        pack(self, adapter_card)

        wide = getattr(panel, "panel_width", 1200) >= 1020
        grid = pack(self, card_grid(wide, 12))

        paired_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(paired_card, wrap_label(tr("PAIRED DEVICES", "已配对设备"), "section-title"))
        self.paired_box = pack(paired_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        grid_add(grid, paired_card)

        found_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(found_card, wrap_label(tr("NEARBY DEVICES", "发现的新设备"), "section-title"))
        self.found_box = pack(found_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        grid_add(grid, found_card)

        pack(self, BluetoothPolicyControls(panel))
        self._discovering = False
        self.connect("destroy", lambda *_: self.suspend())

    def _set_notice(self, message: str):
        self.notice.set_text(message)
        self.notice.set_visible(bool(message))

    def _clear_confirm(self):
        for child in self.confirm_slot.get_children():
            child.destroy()
        self.confirm_slot.hide()

    def suspend(self):
        for attr in ("_scan_timer", "_poll_timer"):
            src = getattr(self, attr, None)
            setattr(self, attr, None)
            if src is not None:
                GLib.source_remove(src)
        if self._discovering and self.adapter_path:
            self._discovering = False
            path = self.adapter_path
            self.panel.work(lambda: backend.set_discovery(path, False), commit=False)

    def refresh(self):
        if self.busy:
            return
        self.busy = True

        def done(state):
            self.busy = False
            self._render(state)

        def failed(err):
            self.busy = False
            self._set_notice(str(err))

        self.panel.work(backend.read_state, done, failed)

    def _render(self, state: dict):
        adapter = state.get("adapter")
        self.adapter_path = adapter["path"] if adapter else None
        powered = bool(adapter and adapter.get("powered"))
        self._discovering = bool(adapter and adapter.get("discovering"))
        self._guard = True
        self.power_switch.set_sensitive(adapter is not None)
        self.power_switch.set_active(powered)
        self.power_switch.set_state(powered)
        self._guard = False
        self.scan_btn.set_sensitive(powered)
        self.scan_btn.set_label(
            tr("Stop scanning", "停止扫描") if self._discovering else tr("Scan nearby devices (15s)", "扫描附近设备（15 秒）")
        )
        if not adapter:
            self._set_notice(state.get("error") or tr("No Bluetooth adapter detected.", "未检测到蓝牙适配器。"))
        else:
            self._set_notice("")

        for container in (self.paired_box, self.found_box):
            for child in container.get_children():
                child.destroy()

        devices = state.get("devices") or []
        paired = [d for d in devices if d["paired"]]
        nearby = [d for d in devices if not d["paired"]]

        if not paired:
            pack(self.paired_box, wrap_label(tr("No paired Bluetooth devices yet.", "还没有已配对的蓝牙设备。"), "hint"))
        for dev in paired:
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            info._row_expand = True
            pack(info, wrap_label(dev["name"], "control-label"))
            meta = [dev["address"]]
            if dev.get("battery") is not None:
                meta.append(tr(f"Battery {dev['battery']}%", f"电量 {dev['battery']}%"))
            if dev.get("trusted"):
                meta.append(tr("Trusted", "已信任"))
            pack(info, wrap_label(" · ".join(meta), "hint"))

            badges = Gtk.Box(spacing=6)
            if dev["connected"]:
                pack(badges, status_badge(tr("Connected", "已连接"), "ok"))
            conn_btn = style(Gtk.Button(label=tr("Disconnect", "断开") if dev["connected"] else tr("Connect", "连接")), "small-button")
            conn_btn.connect("clicked", lambda _b, d=dev: self._connect(d["path"], not d["connected"]))
            trust_btn = style(Gtk.Button(label=tr("Untrust", "取消信任") if dev["trusted"] else tr("Trust", "信任")), "small-button")
            trust_btn.connect("clicked", lambda _b, d=dev: self._trust(d["path"], not d["trusted"]))
            rem_btn = style(Gtk.Button(label="×"), "flat")
            rem_btn.set_tooltip_text(tr("Remove device", "移除设备"))
            rem_btn.connect("clicked", lambda _b, d=dev: self._ask_remove(d))
            pack(badges, conn_btn)
            pack(badges, trust_btn)
            pack(badges, rem_btn)
            pack(self.paired_box, data_row(icon("bluetooth-active-symbolic", 18), info, badges))

        if not nearby:
            pack(self.found_box, wrap_label(
                tr("Scanning… put your device into pairing mode.", "正在扫描周围蓝牙设备，请将设备置于配对模式…")
                if self._discovering else tr("Click Scan to discover nearby devices.", "点击「扫描附近设备」以发现可配对设备。"),
                "hint",
            ))
        for dev in nearby[:15]:
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            info._row_expand = True
            pack(info, wrap_label(dev["name"], "control-label"))
            sub = dev["address"] + (f" · RSSI {dev['rssi']}" if dev.get("rssi") is not None else "")
            pack(info, wrap_label(sub, "hint"))
            pair_btn = style(Gtk.Button(label=tr("Pair & connect", "配对并连接")), "small-button")
            pair_btn.connect("clicked", lambda _b, d=dev: self._pair(d["path"]))
            pack(self.found_box, data_row(icon("bluetooth-active-symbolic", 16), info, pair_btn))

        self.paired_box.show_all()
        self.found_box.show_all()

    def _on_power_toggle(self, _switch, state):
        if self._guard or not self.adapter_path:
            return False
        path = self.adapter_path
        self.panel.work(
            lambda: backend.set_power(path, bool(state)),
            lambda _: self.refresh(),
            lambda err: (self._set_notice(str(err)), self.refresh()),
            commit=True,
        )
        return True

    def _toggle_scan(self):
        if not self.adapter_path:
            return
        path = self.adapter_path
        target = not self._discovering
        if not target:
            self.suspend()
            self.refresh()
            return
        self.panel.work(
            lambda: backend.set_discovery(path, True),
            lambda _: self._start_scan_timers(),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )

    def _start_scan_timers(self):
        self._discovering = True
        self.refresh()
        if self._poll_timer is None:
            self._poll_timer = GLib.timeout_add_seconds(3, self._scan_poll)
        if self._scan_timer is not None:
            GLib.source_remove(self._scan_timer)
        self._scan_timer = GLib.timeout_add_seconds(15, self._auto_stop_scan)

    def _scan_poll(self):
        if not self._discovering or not self.panel.alive:
            self._poll_timer = None
            return GLib.SOURCE_REMOVE
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def _auto_stop_scan(self):
        self._scan_timer = None
        self.suspend()
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _pair(self, path: str):
        self._set_notice(tr("Pairing device…", "正在配对设备…"))
        def op():
            backend.pair_device(path)
            backend.set_trusted(path, True)
            backend.connect_device(path, True)
        self.panel.work(op, lambda _: self.refresh(), lambda err: self._set_notice(str(err)), commit=True)

    def _connect(self, path: str, enable: bool):
        self._set_notice(tr("Connecting…" if enable else "Disconnecting…", "正在连接…" if enable else "正在断开…"))
        self.panel.work(lambda: backend.connect_device(path, enable), lambda _: self.refresh(),
                        lambda err: self._set_notice(str(err)), commit=True)

    def _trust(self, path: str, trusted: bool):
        self.panel.work(lambda: backend.set_trusted(path, trusted), lambda _: self.refresh(),
                        lambda err: self._set_notice(str(err)), commit=True)

    def _ask_remove(self, dev: dict):
        self._clear_confirm()
        bar, cancel = inline_confirm_bar(
            tr(f"Remove paired device “{dev['name']}”?", f"确认移除已配对设备“{dev['name']}”？"),
            tr("Remove", "确认移除"),
            lambda: self._do_remove(dev["path"]),
            self._clear_confirm,
        )
        self.confirm_slot.add(bar)
        self.confirm_slot.set_no_show_all(False)
        self.confirm_slot.show_all()
        self.confirm_slot.set_no_show_all(True)
        cancel.grab_focus()

    def _do_remove(self, device_path: str):
        self._clear_confirm()
        adapter = self.adapter_path
        self.panel.work(lambda: backend.remove_device(adapter, device_path), lambda _: self.refresh(),
                        lambda err: self._set_notice(str(err)), commit=True)
