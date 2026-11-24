"""Native Network Center: Wi-Fi scan/connect, active IP/DNS, saved profiles & hotspot."""
from __future__ import annotations

import shutil

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

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
import network_backend as backend


class NetworkPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.busy = False
        self.loaded = False
        self._guard = False
        self._connect_ssid = None

        pack(self, nyx_guide_banner(
            "network",
            tr("Scan and join Wi-Fi, manage saved Ethernet/VPN profiles, or start a personal hotspot right here.",
               "在这里直接扫描并连接 Wi-Fi、查看当前 IP 与 DNS、管理已保存连接/VPN 或一键开启热点。"),
            skin=None,
        ))

        self.notice = pack(self, wrap_label("", "hint"))
        self.notice.set_no_show_all(True)

        wide = getattr(panel, "panel_width", 1200) >= 1020
        grid = pack(self, card_grid(wide, 12))

        # Left column: Wi-Fi controls + scanned networks
        wifi_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(wifi_card, wrap_label(tr("WI-FI & HOTSPOT", "无线网络与热点"), "section-title"))
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.connect("state-set", self._on_wifi_toggle)
        pack(wifi_card, setting_row(tr("Wi-Fi radio", "Wi-Fi 开关"), self.wifi_switch,
                                    tr("Scan nearby access points and connect directly", "开启后可扫描附近无线网络并直接输入密码连接")))

        ctrl_row = pack(wifi_card, Gtk.Box(spacing=8))
        self.scan_btn = style(Gtk.Button(label=tr("Scan Wi-Fi", "扫描附近网络")), "accent-button")
        self.scan_btn.connect("clicked", lambda _: self.refresh(rescan=True))
        self.hotspot_btn = Gtk.Button(label=tr("Start hotspot", "开启个人热点"))
        self.hotspot_btn.connect("clicked", self._on_hotspot)
        pack(ctrl_row, self.scan_btn, True)
        pack(ctrl_row, self.hotspot_btn, True)

        # Inline password bar (shown only when joining a secured AP)
        self.pw_box = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "data-row")
        self.pw_title = pack(self.pw_box, wrap_label("", "control-label"))
        pw_row = pack(self.pw_box, Gtk.Box(spacing=8))
        self.pw_entry = pack(pw_row, Gtk.Entry(), True)
        self.pw_entry.set_visibility(False)
        self.pw_entry.set_placeholder_text(tr("Wi-Fi password", "请输入 Wi-Fi 密码"))
        self.pw_entry.connect("activate", lambda _: self._submit_wifi_join())
        cancel_pw = Gtk.Button(label=tr("Cancel", "取消"))
        cancel_pw.connect("clicked", lambda _: self._hide_pw())
        join_pw = style(Gtk.Button(label=tr("Connect", "连接")), "accent-button")
        join_pw.connect("clicked", lambda _: self._submit_wifi_join())
        pack(pw_row, cancel_pw)
        pack(pw_row, join_pw)
        self.pw_box.set_no_show_all(True)
        pack(wifi_card, self.pw_box)

        self.ap_list = pack(wifi_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        grid_add(grid, wifi_card)

        # Right column: Active interfaces + Saved profiles
        right_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        active_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        hdr = pack(active_card, Gtk.Box(spacing=8))
        pack(hdr, wrap_label(tr("ACTIVE CONNECTIONS", "当前活动连接"), "section-title"), True)
        refresh_btn = style(Gtk.Button(label=tr("Refresh", "刷新")), "small-button")
        refresh_btn.connect("clicked", lambda _: self.refresh(rescan=False))
        pack(hdr, refresh_btn)
        self.active_box = pack(active_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        pack(right_col, active_card)

        prof_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(prof_card, wrap_label(tr("SAVED PROFILES & VPN", "已保存配置与 VPN"), "section-title"))
        self.confirm_slot = pack(prof_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        self.confirm_slot.set_no_show_all(True)
        self.profile_box = pack(prof_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        if shutil.which("nm-connection-editor"):
            adv = style(Gtk.Button(label=tr("Advanced IP / VPN editor…", "高级 IP / DNS / VPN 编辑器…")), "small-button")
            adv.connect("clicked", lambda _: self.panel.launch_external(["nm-connection-editor"]))
            pack(prof_card, adv)
        pack(right_col, prof_card)
        grid_add(grid, right_col)

        self._hotspot_active = False

    def _set_notice(self, message: str):
        self.notice.set_text(message)
        self.notice.set_visible(bool(message))

    def _hide_pw(self):
        self._connect_ssid = None
        self.pw_entry.set_text("")
        self.pw_box.hide()

    def _clear_confirm(self):
        for child in self.confirm_slot.get_children():
            child.destroy()
        self.confirm_slot.hide()

    def refresh(self, *, rescan: bool = False):
        if self.busy:
            return
        self.busy = True
        self.scan_btn.set_sensitive(False)
        self._set_notice(tr("Scanning Wi-Fi networks…", "正在扫描无线网络…") if rescan else tr("Reading network state…", "正在读取网络状态…"))

        def done(state):
            self.busy = False
            self.loaded = True
            self.scan_btn.set_sensitive(state.get("wifi_enabled", False))
            self._set_notice("" if state.get("available") else tr("NetworkManager is unavailable.", "NetworkManager 不可用。"))
            self._render(state)

        def failed(err):
            self.busy = False
            self.scan_btn.set_sensitive(True)
            self._set_notice(str(err))

        self.panel.work(lambda: backend.read_state(rescan=rescan), done, failed)

    def _render(self, state: dict):
        self._guard = True
        wifi_on = bool(state.get("wifi_enabled"))
        self.wifi_switch.set_active(wifi_on)
        self.wifi_switch.set_state(wifi_on)
        self._guard = False
        self._hotspot_active = bool(state.get("hotspot_active"))
        self.hotspot_btn.set_label(tr("Stop hotspot", "关闭个人热点") if self._hotspot_active else tr("Start hotspot", "开启个人热点"))
        self.hotspot_btn.set_sensitive(wifi_on)

        # Active devices
        for child in self.active_box.get_children():
            child.destroy()
        actives = state.get("active") or []
        if not actives:
            pack(self.active_box, wrap_label(tr("No active network interface.", "当前没有活动网络连接。"), "hint"))
        for dev in actives:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col._row_expand = True
            pack(col, wrap_label(f"{dev['connection']}  ({dev['device']})", "control-label"))
            details = [part for part in (
                f"IP: {dev['ip4']}" if dev.get("ip4") else "",
                f"GW: {dev['gateway']}" if dev.get("gateway") else "",
                f"DNS: {', '.join(dev['dns'][:2])}" if dev.get("dns") else "",
            ) if part]
            pack(col, wrap_label(" · ".join(details) or dev.get("type", ""), "hint"))
            pack(self.active_box, data_row(
                icon("network-wired-symbolic" if dev["type"] == "ethernet" else "network-wireless-symbolic", 18),
                col,
                status_badge(tr("Connected", "已连接"), "ok"),
            ))
        self.active_box.show_all()

        # Wi-Fi AP list
        for child in self.ap_list.get_children():
            child.destroy()
        if not wifi_on:
            pack(self.ap_list, wrap_label(tr("Wi-Fi is turned off. Enable the switch above to scan nearby networks.",
                                             "Wi-Fi 已关闭，打开上方开关即可扫描周围网络。"), "hint"))
        else:
            aps = state.get("aps") or []
            if not aps:
                pack(self.ap_list, wrap_label(tr("No Wi-Fi networks found. Click Scan Wi-Fi to refresh.",
                                                 "暂未发现无线网络，点击「扫描附近网络」刷新。"), "hint"))
            for ap in aps[:18]:
                info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                info._row_expand = True
                pack(info, wrap_label(ap["ssid"], "control-label"))
                sub = f"{ap['signal']}% · {ap['security']}" + (f" · {ap['freq']}" if ap.get("freq") else "")
                pack(info, wrap_label(sub, "hint"))
                if ap["in_use"]:
                    action = status_badge(tr("Active", "当前连接"), "ok")
                else:
                    action = style(Gtk.Button(label=tr("Connect", "连接")), "small-button")
                    action.connect("clicked", lambda _b, item=ap: self._on_join_ap(item))
                pack(self.ap_list, data_row(
                    icon("network-wireless-symbolic", 16), info, action,
                ))
        self.ap_list.show_all()

        # Saved profiles
        for child in self.profile_box.get_children():
            child.destroy()
        profiles = state.get("profiles") or []
        if not profiles:
            pack(self.profile_box, wrap_label(tr("No saved network profiles.", "没有已保存的网络配置。"), "hint"))
        for prof in profiles[:14]:
            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            info._row_expand = True
            pack(info, wrap_label(prof["name"], "control-label"))
            sub = f"{prof['type']}" + (f" · {prof['device']}" if prof["active"] else "")
            pack(info, wrap_label(sub, "hint"))
            toggle = style(Gtk.Button(label=tr("Disconnect", "断开") if prof["active"] else tr("Connect", "连接")), "small-button")
            toggle.connect("clicked", lambda _b, p=prof: self._toggle_profile(p["id"], not p["active"]))
            forget = style(Gtk.Button(label="×"), "flat")
            forget.set_tooltip_text(tr("Forget connection", "忘记此网络"))
            forget.connect("clicked", lambda _b, p=prof: self._ask_forget(p))
            pack(self.profile_box, data_row(info, toggle, forget))
        self.profile_box.show_all()

    def _on_wifi_toggle(self, switch, state):
        if self._guard:
            return False
        self._set_notice(tr("Updating Wi-Fi radio…", "正在切换 Wi-Fi 开关…"))
        self.panel.work(
            lambda: backend.set_wifi_radio(bool(state)),
            lambda _: self.refresh(rescan=bool(state)),
            lambda err: (self._set_notice(str(err)), self.refresh()),
            commit=True,
        )
        return True

    def _on_join_ap(self, ap: dict):
        if ap["secured"]:
            self._connect_ssid = ap["ssid"]
            self.pw_title.set_text(tr(f"Join “{ap['ssid']}”", f"连接“{ap['ssid']}”"))
            self.pw_entry.set_text("")
            self.pw_box.set_no_show_all(False)
            self.pw_box.show_all()
            self.pw_box.set_no_show_all(True)
            GLib.idle_add(self.pw_entry.grab_focus)
        else:
            self._run_connect(ap["ssid"], "")

    def _submit_wifi_join(self):
        if not self._connect_ssid:
            return
        ssid, pw = self._connect_ssid, self.pw_entry.get_text()
        self._hide_pw()
        self._run_connect(ssid, pw)

    def _run_connect(self, ssid: str, password: str):
        self._set_notice(tr(f"Connecting to {ssid}…", f"正在连接 {ssid}…"))
        self.panel.work(
            lambda: backend.connect_wifi(ssid, password),
            lambda _: (self.panel.feedback(tr(f"Connected to {ssid}", f"已连接到 {ssid}")), self.refresh()),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )

    def _toggle_profile(self, uuid: str, enable: bool):
        self._set_notice(tr("Updating connection…", "正在切换连接状态…"))
        self.panel.work(
            lambda: backend.activate_profile(uuid, enable),
            lambda _: self.refresh(),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )

    def _ask_forget(self, prof: dict):
        self._clear_confirm()
        bar, cancel = inline_confirm_bar(
            tr(f"Forget saved profile “{prof['name']}”?", f"确认忘记已保存的网络“{prof['name']}”？"),
            tr("Forget", "确认忘记"),
            lambda: self._do_forget(prof["id"]),
            self._clear_confirm,
        )
        self.confirm_slot.add(bar)
        self.confirm_slot.set_no_show_all(False)
        self.confirm_slot.show_all()
        self.confirm_slot.set_no_show_all(True)
        cancel.grab_focus()

    def _do_forget(self, uuid: str):
        self._clear_confirm()
        self.panel.work(
            lambda: backend.forget_profile(uuid),
            lambda _: self.refresh(),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )

    def _on_hotspot(self, *_):
        target = not self._hotspot_active
        self._set_notice(tr("Updating hotspot…", "正在切换个人热点…"))
        self.panel.work(
            lambda: backend.toggle_hotspot(target),
            lambda _: self.refresh(),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )
