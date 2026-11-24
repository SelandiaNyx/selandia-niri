"""Native Security & Accounts page: UFW firewall rules, user profile & hostname."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from control_widgets import (
    card_grid,
    data_row,
    grid_add,
    inline_confirm_bar,
    nyx_guide_banner,
    pack,
    setting_row,
    status_badge,
    style,
    wrap_label,
)
from i18n import tr
import security_backend as backend


class SecurityPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.busy = False
        self._guard = False

        pack(self, nyx_guide_banner(
            "security",
            tr("Manage UFW firewall status & port rules, inspect user privileges, rename hostname, and check Polkit & Keyring.",
               "直接管理 UFW 防火墙开关与端口规则、查看当前账户权限组、修改主机名并检查 Polkit 与密钥环状态。"),
            skin="obsidian",
        ))

        self.notice = pack(self, wrap_label("", "hint"))
        self.notice.set_no_show_all(True)
        self.confirm_slot = pack(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        self.confirm_slot.set_no_show_all(True)

        wide = getattr(panel, "panel_width", 1200) >= 1020
        grid = pack(self, card_grid(wide, 12))

        # Left: UFW Firewall
        fw_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        fhdr = pack(fw_card, Gtk.Box(spacing=8))
        pack(fhdr, wrap_label(tr("UFW FIREWALL", "UFW 防火墙"), "section-title"), True)
        self.fw_badge = pack(fhdr, status_badge(tr("Checking…", "检测中…"), "info"))

        self.fw_switch = Gtk.Switch()
        self.fw_switch.connect("state-set", self._on_fw_toggle)
        pack(fw_card, setting_row(tr("Enable firewall", "启用防火墙"), self.fw_switch,
                                  tr("Requires Polkit administrator confirmation", "切换开关或增删规则时会请求管理员授权")))

        auth_row = pack(fw_card, Gtk.Box(spacing=8))
        self.unlock_btn = style(Gtk.Button(label=tr("Load detailed rules (Polkit)", "授权读取详细规则")), "small-button")
        self.unlock_btn.connect("clicked", lambda _: self.refresh(privileged=True))
        ref_btn = style(Gtk.Button(label=tr("Refresh", "刷新")), "small-button")
        ref_btn.connect("clicked", lambda _: self.refresh(privileged=False))
        pack(auth_row, self.unlock_btn, True)
        pack(auth_row, ref_btn)

        # Add rule row
        add_row = pack(fw_card, Gtk.Box(spacing=6))
        self.rule_action = Gtk.ComboBoxText()
        self.rule_action.append("allow", tr("Allow", "放行"))
        self.rule_action.append("deny", tr("Deny", "拒绝"))
        self.rule_action.set_active_id("allow")
        self.port_entry = Gtk.Entry()
        self.port_entry.set_placeholder_text(tr("Port (e.g. 22/tcp or 8080)", "端口（如 22/tcp 或 8080）"))
        add_btn = style(Gtk.Button(label=tr("Add rule", "添加规则")), "accent-button")
        add_btn.connect("clicked", lambda _: self._add_rule())
        pack(add_row, self.rule_action)
        pack(add_row, self.port_entry, True)
        pack(add_row, add_btn)

        self.fw_policy_label = pack(fw_card, wrap_label("", "hint"))
        self.rules_box = pack(fw_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))
        grid_add(grid, fw_card)

        # Right: Account, Hostname & Credentials
        acc_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(acc_card, wrap_label(tr("ACCOUNT & IDENTITY", "账户与主机安全"), "section-title"))
        self.account_box = pack(acc_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6))

        host_row = pack(acc_card, Gtk.Box(spacing=8))
        self.host_entry = pack(host_row, Gtk.Entry(), True)
        self.host_entry.set_placeholder_text(tr("Hostname", "主机名"))
        host_btn = style(Gtk.Button(label=tr("Rename host", "修改主机名")), "small-button")
        host_btn.connect("clicked", lambda _: self._rename_host())
        pack(host_row, host_btn)

        pw_btn = style(Gtk.Button(label=tr("Change account password…", "修改当前账户密码…")), "small-button")
        pw_btn.connect("clicked", lambda _: self.panel.launch_external([self.panel.desktop_script(), "password"]))
        pack(acc_card, pw_btn)
        grid_add(grid, acc_card)

    def _set_notice(self, message: str):
        self.notice.set_text(message)
        self.notice.set_visible(bool(message))

    def _clear_confirm(self):
        for child in self.confirm_slot.get_children():
            child.destroy()
        self.confirm_slot.hide()

    def refresh(self, *, privileged: bool = False):
        if self.busy:
            return
        self.busy = True
        self._set_notice(tr("Reading security and firewall state…", "正在读取防火墙与账户状态…"))

        def read():
            return backend.read_ufw(privileged=privileged), backend.read_account_state()

        self.panel.work(read, self._render, self._failed)

    def _failed(self, err):
        self.busy = False
        self._set_notice(str(err))

    def _render(self, payload):
        ufw, acc = payload
        self.busy = False
        self._set_notice("")

        self._guard = True
        self.fw_switch.set_sensitive(ufw["installed"])
        self.fw_switch.set_active(bool(ufw["active"]))
        self.fw_switch.set_state(bool(ufw["active"]))
        self._guard = False

        ctx = self.fw_badge.get_style_context()
        for cls in ("ok", "warn", "err", "info"):
            ctx.remove_class(cls)
        if not ufw["installed"]:
            self.fw_badge.set_text(tr("Not installed", "未安装"))
            ctx.add_class("warn")
        elif ufw["active"]:
            self.fw_badge.set_text(tr("Active", "已启用"))
            ctx.add_class("ok")
        else:
            self.fw_badge.set_text(tr("Inactive", "未启用"))
            ctx.add_class("warn")

        self.unlock_btn.set_visible(bool(ufw["installed"] and ufw["needs_auth"]))
        if ufw["default_in"] or ufw["default_out"]:
            self.fw_policy_label.set_text(
                tr(f"Default policy: incoming {ufw['default_in']} · outgoing {ufw['default_out']}",
                   f"默认策略：入站 {ufw['default_in']} · 出站 {ufw['default_out']}")
            )
        elif ufw["needs_auth"]:
            self.fw_policy_label.set_text(
                tr("UFW rules require administrator permission to read. Click 'Load detailed rules' above.",
                   "读取 UFW 规则列表需要管理员授权，可点击上方「授权读取详细规则」。")
            )
        else:
            self.fw_policy_label.set_text("")

        for child in self.rules_box.get_children():
            child.destroy()
        for rule in ufw["rules"]:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col._row_expand = True
            pack(col, wrap_label(f"#{rule['num']}  {rule['to']}  ({rule['direction']})", "control-label"))
            pack(col, wrap_label(f"{rule['action']} · {rule['source']}", "hint"))
            del_btn = style(Gtk.Button(label="×"), "flat")
            del_btn.set_tooltip_text(tr("Delete rule", "删除规则"))
            del_btn.connect("clicked", lambda _b, r=rule: self._ask_delete_rule(r))
            pack(self.rules_box, data_row(
                col,
                status_badge(rule["action"], "ok" if rule["action"] == "ALLOW" else "err"),
                del_btn,
            ))
        self.rules_box.show_all()

        for child in self.account_box.get_children():
            child.destroy()
        pack(self.account_box, data_row(
            wrap_label(f"{acc['full_name']} ({acc['user']} · UID {acc['uid']})", "control-label"),
            status_badge(tr("Administrator", "管理员") if acc["is_admin"] else tr("Standard", "普通用户"),
                         "ok" if acc["is_admin"] else "info"),
        ))
        pack(self.account_box, data_row(
            wrap_label(tr("Groups", "所属权限组"), "hint"),
            wrap_label(", ".join(acc["groups"]) or "—", "control-label"),
        ))
        pack(self.account_box, data_row(
            wrap_label(tr("Polkit authentication agent", "Polkit 授权代理"), "control-label"),
            status_badge(tr("Active", "运行中") if acc["polkit_running"] else tr("Offline", "未运行"),
                         "ok" if acc["polkit_running"] else "warn"),
        ))
        pack(self.account_box, data_row(
            wrap_label(tr("GNOME Keyring daemon", "密钥环守护"), "control-label"),
            status_badge(tr("Active", "运行中") if acc["keyring_running"] else tr("Offline", "未运行"),
                         "ok" if acc["keyring_running"] else "warn"),
        ))
        self.host_entry.set_text(acc["hostname"])
        self.account_box.show_all()

    def _on_fw_toggle(self, _switch, state):
        if self._guard:
            return False
        self._set_notice(tr("Updating UFW firewall…", "正在切换防火墙状态…"))
        self.panel.work(
            lambda: backend.set_ufw_enabled(bool(state)),
            lambda _: (self.panel.feedback(tr("Firewall updated", "防火墙状态已更新")), self.refresh(privileged=True)),
            lambda err: (self._set_notice(str(err)), self.refresh(privileged=False)),
            commit=True,
        )
        return True

    def _add_rule(self):
        spec = self.port_entry.get_text().strip()
        action = self.rule_action.get_active_id() or "allow"
        if not spec:
            self._set_notice(tr("Enter a port such as 22/tcp or 8080.", "请先输入端口号，如 22/tcp 或 8080。"))
            return
        self._set_notice(tr("Adding firewall rule…", "正在添加防火墙规则…"))
        self.panel.work(
            lambda: backend.add_ufw_rule(action, spec),
            lambda _: (self.port_entry.set_text(""), self.refresh(privileged=True)),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )

    def _ask_delete_rule(self, rule: dict):
        self._clear_confirm()
        bar, cancel = inline_confirm_bar(
            tr(f"Delete UFW rule #{rule['num']} ({rule['action']} {rule['to']})?",
               f"确认删除防火墙规则 #{rule['num']}（{rule['action']} {rule['to']}）？"),
            tr("Delete rule", "确认删除"),
            lambda: self._do_delete_rule(rule["num"]),
            self._clear_confirm,
        )
        self.confirm_slot.add(bar)
        self.confirm_slot.set_no_show_all(False)
        self.confirm_slot.show_all()
        self.confirm_slot.set_no_show_all(True)
        cancel.grab_focus()

    def _do_delete_rule(self, num: str):
        self._clear_confirm()
        self.panel.work(lambda: backend.delete_ufw_rule(num), lambda _: self.refresh(privileged=True),
                        lambda err: self._set_notice(str(err)), commit=True)

    def _rename_host(self):
        name = self.host_entry.get_text().strip()
        if not name:
            return
        self._set_notice(tr("Updating hostname…", "正在修改主机名…"))
        self.panel.work(
            lambda: backend.rename_hostname(name),
            lambda _: (self.panel.feedback(tr(f"Hostname changed to {name}", f"主机名已更新为 {name}")), self.refresh()),
            lambda err: self._set_notice(str(err)),
            commit=True,
        )
