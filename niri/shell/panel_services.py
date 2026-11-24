"""Unified Services page: Desktop managed services + systemd user & system units."""
from __future__ import annotations

import subprocess

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from control_widgets import (
    data_row,
    inline_confirm_bar,
    nyx_guide_banner,
    pack,
    status_badge,
    style,
    wrap_label,
)
from i18n import tr
import system_settings as desktop_backend
import systemd_backend as sysd


class ServicesPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.scope = "desktop"
        self.state_filter = "all"
        self.busy = False
        self._search_timer = None

        pack(self, nyx_guide_banner(
            "services",
            tr("Control Selandia desktop daemons, user systemd services, and system-wide units (Polkit authenticated).",
               "统一管理桌面常驻服务、当前用户的 systemd 单元以及系统级服务（系统服务修改自动唤起 Polkit 鉴权）。"),
            skin="engineer",
        ))

        # Top subtabs
        tabs = style(Gtk.Box(spacing=6), "md3-subtabs")
        self._tab_buttons = {}
        for key, label_text in (
            ("desktop", tr("Desktop services", "桌面托管服务")),
            ("user", tr("User systemd", "用户服务 (--user)")),
            ("system", tr("System systemd", "系统服务 (root)")),
        ):
            btn = Gtk.ToggleButton(label=label_text)
            btn.connect("toggled", self._on_tab, key)
            pack(tabs, btn, True)
            self._tab_buttons[key] = btn
        pack(self, tabs)

        self.notice = pack(self, wrap_label("", "hint"))
        self.notice.set_no_show_all(True)

        # Filter toolbar (used for user/system systemd tabs)
        self.toolbar = pack(self, Gtk.Box(spacing=8))
        self.search = pack(self.toolbar, Gtk.SearchEntry(), True)
        self.search.set_placeholder_text(tr("Filter units by name or description…", "按服务名或描述筛选…"))
        self.search.connect("search-changed", self._on_search)
        self.state_combo = Gtk.ComboBoxText()
        for k, t in (("all", tr("All states", "全部状态")), ("active", tr("Running", "运行中")),
                     ("failed", tr("Failed", "异常失败")), ("inactive", tr("Stopped", "已停止"))):
            self.state_combo.append(k, t)
        self.state_combo.set_active_id("all")
        self.state_combo.connect("changed", lambda _: self.refresh())
        pack(self.toolbar, self.state_combo)
        ref_btn = style(Gtk.Button(label=tr("Refresh", "刷新")), "small-button")
        ref_btn.connect("clicked", lambda _: self.refresh())
        pack(self.toolbar, ref_btn)

        self.confirm_slot = pack(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        self.confirm_slot.set_no_show_all(True)

        self.card_box = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(self, self.card_box)

        self._tab_buttons["desktop"].set_active(True)

    def _set_notice(self, text: str):
        self.notice.set_text(text)
        self.notice.set_visible(bool(text))

    def _clear_confirm(self):
        for child in self.confirm_slot.get_children():
            child.destroy()
        self.confirm_slot.hide()

    def _on_tab(self, btn, key):
        if not btn.get_active():
            return
        for other_key, other in self._tab_buttons.items():
            if other_key != key and other.get_active():
                other.set_active(False)
        self.scope = key
        self.toolbar.set_visible(key != "desktop")
        self._clear_confirm()
        self.refresh()

    def _on_search(self, *_):
        if self._search_timer is not None:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(150, self._run_search)

    def _run_search(self):
        self._search_timer = None
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        scope = self.scope
        query = self.search.get_text().strip()
        flt = self.state_combo.get_active_id() or "all"
        self._set_notice(tr("Loading services…", "正在读取服务状态…"))

        if scope == "desktop":
            self.panel.work(desktop_backend.service_state, self._render_desktop, self._failed)
        else:
            self.panel.work(lambda: sysd.list_units(scope, query=query, state_filter=flt),
                            lambda items: self._render_systemd(scope, items), self._failed)

    def _failed(self, err):
        self.busy = False
        self._set_notice(str(err))

    def _render_desktop(self, state: dict):
        self.busy = False
        self._set_notice("")
        for child in self.card_box.get_children():
            child.destroy()
        pack(self.card_box, wrap_label(tr("SELANDIA DESKTOP SERVICES", "桌面托管常驻服务"), "section-title"))
        names = {
            "clipboard": (tr("Clipboard history (cliphist)", "剪贴板历史守护"), tr("Stores text and image history across copies", "后台记录文本与图片剪贴板历史")),
            "notifications": (tr("Notification daemon (SwayNC)", "通知中心服务（SwayNC）"), tr("Manages toast alerts and notification drawer", "接管桌面弹窗与右侧通知抽屉")),
            "bar": (tr("Top status bar & island (Eww)", "三段顶栏与灵动岛（Eww）"), tr("Workspace capsules, telemetry and media island", "工作区胶囊、监控与居中灵动岛")),
        }
        for key, (title, sub) in names.items():
            info = state.get(key) or {}
            enabled = bool(info.get("enabled", True))
            active = bool(info.get("active", False))
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col._row_expand = True
            pack(col, wrap_label(title, "control-label"))
            pack(col, wrap_label(sub, "hint"))
            badge = status_badge(tr("Running", "运行中") if active else tr("Stopped", "已停止"), "ok" if active else "warn")
            sw = Gtk.Switch()
            sw.set_active(enabled)
            sw.set_state(enabled)
            sw.set_valign(Gtk.Align.CENTER)
            sw.connect("state-set", lambda _s, val, k=key: self._toggle_desktop(k, bool(val)))
            pack(self.card_box, data_row(col, badge, sw))

        # Inline clipboard clear (no window destruction!)
        clip_row = Gtk.Box(spacing=8)
        clear_btn = style(Gtk.Button(label=tr("Clear clipboard history…", "清空剪贴板历史…")), "small-button")
        clear_btn.connect("clicked", lambda _: self._ask_clear_clipboard())
        ref_btn = style(Gtk.Button(label=tr("Refresh", "刷新")), "small-button")
        ref_btn.connect("clicked", lambda _: self.refresh())
        pack(clip_row, clear_btn)
        pack(clip_row, ref_btn)
        pack(self.card_box, clip_row)
        self.card_box.show_all()

    def _toggle_desktop(self, key: str, enabled: bool):
        self._set_notice(tr("Applying desktop service change…", "正在切换桌面服务状态…"))
        self.panel.work(lambda: desktop_backend.set_service(key, enabled),
                        lambda _: self.refresh(), lambda err: self._set_notice(str(err)), commit=True)
        return True

    def _ask_clear_clipboard(self):
        self._clear_confirm()
        bar, cancel = inline_confirm_bar(
            tr("Delete all saved clipboard text and images?", "确认清空所有已保存的剪贴板文本和图片历史？"),
            tr("Clear clipboard", "确认清空"),
            self._do_clear_clipboard,
            self._clear_confirm,
        )
        self.confirm_slot.add(bar)
        self.confirm_slot.set_no_show_all(False)
        self.confirm_slot.show_all()
        self.confirm_slot.set_no_show_all(True)
        cancel.grab_focus()

    def _do_clear_clipboard(self):
        self._clear_confirm()
        def op():
            subprocess.run(["cliphist", "wipe"], capture_output=True, timeout=5, check=True)
        self.panel.work(op, lambda _: self.panel.feedback(tr("Clipboard history cleared", "剪贴板历史已清空")),
                        lambda err: self._set_notice(str(err)), commit=True)

    def _render_systemd(self, scope: str, units: list[dict]):
        self.busy = False
        self._set_notice("")
        for child in self.card_box.get_children():
            child.destroy()
        heading = tr("USER SYSTEMD UNITS", "当前用户服务单元") if scope == "user" else tr("SYSTEM-WIDE UNITS", "系统级服务单元")
        pack(self.card_box, wrap_label(f"{heading} ({len(units)})", "section-title"))
        if not units:
            pack(self.card_box, wrap_label(tr("No matching systemd services.", "没有匹配的 systemd 服务。"), "hint"))
        for item in units:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col._row_expand = True
            pack(col, wrap_label(item["unit"], "control-label"))
            sub = item["description"] or item["sub"]
            if item["enabled"]:
                sub = f"[{item['enabled']}] {sub}"
            pack(col, wrap_label(sub, "hint"))

            kind = "ok" if item["active"] == "active" else ("err" if item["active"] == "failed" else "")
            badge = status_badge(item["active"], kind)
            acts = Gtk.Box(spacing=4)
            toggle_act = "stop" if item["active"] == "active" else "start"
            tbtn = style(Gtk.Button(label=tr("Stop", "停止") if toggle_act == "stop" else tr("Start", "启动")), "small-button")
            tbtn.connect("clicked", lambda _b, u=item["unit"], a=toggle_act, sc=scope: self._unit_op(sc, u, a))
            rbtn = style(Gtk.Button(label=tr("Restart", "重启")), "small-button")
            rbtn.connect("clicked", lambda _b, u=item["unit"], sc=scope: self._unit_op(sc, u, "restart"))
            lbtn = style(Gtk.Button(label=tr("Logs", "日志")), "flat")
            lbtn.set_tooltip_text(tr("Inspect journal logs for this unit", "查看该服务的日志"))
            lbtn.connect("clicked", lambda _b, u=item["unit"], sc=scope: self.panel.open_unit_logs(sc, u))
            pack(acts, badge)
            pack(acts, tbtn)
            pack(acts, rbtn)
            pack(acts, lbtn)
            pack(self.card_box, data_row(col, acts))
        self.card_box.show_all()

    def _unit_op(self, scope: str, unit: str, action: str):
        self._set_notice(tr(f"Running {action} on {unit}…", f"正在对 {unit} 执行 {action}…"))
        self.panel.work(
            lambda: sysd.control_unit(scope, unit, action),
            lambda _: (self.panel.feedback(tr(f"{unit}: {action} completed", f"{unit} 已完成 {action}")), self.refresh()),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )
