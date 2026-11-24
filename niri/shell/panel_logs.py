"""Inline journalctl System & Service Log viewer with severity/unit filter & copy."""
from __future__ import annotations

import subprocess

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from control_widgets import data_row, nyx_guide_banner, pack, status_badge, style, wrap_label
from i18n import tr
import journal_backend as backend


class LogsPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.busy = False
        self.entries: list[dict] = []
        self._search_timer = None

        pack(self, nyx_guide_banner(
            "logs",
            tr("Filter live systemd journal logs by scope, severity, or unit name and copy a clean diagnostic bundle.",
               "无需打开终端即可按范围、错误级别或服务名检索 journalctl 日志，支持一键复制排错诊断包。"),
            skin="engineer",
        ))

        controls = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        row1 = pack(controls, Gtk.Box(spacing=8))
        self.scope_combo = Gtk.ComboBoxText()
        self.scope_combo.append("user", tr("User session", "用户会话"))
        self.scope_combo.append("system", tr("System boot", "本次系统启动"))
        self.scope_combo.set_active_id("user")
        self.scope_combo.connect("changed", lambda _: self.refresh())

        self.sev_combo = Gtk.ComboBoxText()
        self.sev_combo.append("err", tr("Errors only", "仅错误"))
        self.sev_combo.append("warning", tr("Warnings & errors", "警告与错误"))
        self.sev_combo.append("info", tr("All info", "全部信息"))
        self.sev_combo.set_active_id("warning")
        self.sev_combo.connect("changed", lambda _: self.refresh())

        self.unit_entry = Gtk.Entry()
        self.unit_entry.set_placeholder_text(tr("Unit (optional, e.g. niri.service)", "服务单元（可选，如 niri.service）"))
        self.unit_entry.connect("activate", lambda _: self.refresh())

        pack(row1, self.scope_combo)
        pack(row1, self.sev_combo)
        pack(row1, self.unit_entry, True)

        row2 = pack(controls, Gtk.Box(spacing=8))
        self.search = pack(row2, Gtk.SearchEntry(), True)
        self.search.set_placeholder_text(tr("Filter messages by keyword…", "按关键词过滤日志正文…"))
        self.search.connect("search-changed", self._on_search)
        refresh_btn = style(Gtk.Button(label=tr("Refresh", "刷新")), "accent-button")
        refresh_btn.connect("clicked", lambda _: self.refresh())
        copy_btn = style(Gtk.Button(label=tr("Copy diagnostic report", "复制诊断日志")), "small-button")
        copy_btn.connect("clicked", lambda _: self._copy_logs())
        pack(row2, refresh_btn)
        pack(row2, copy_btn)
        pack(self, controls)

        self.count_label = pack(self, wrap_label("", "hint"))
        self.list_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "card")
        pack(self, self.list_card)

    def inspect_unit(self, scope: str, unit: str):
        self.scope_combo.set_active_id(scope if scope in ("user", "system") else "user")
        self.sev_combo.set_active_id("info")
        self.unit_entry.set_text(unit)
        self.refresh()

    def _on_search(self, *_):
        if self._search_timer is not None:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(160, self._debounced)

    def _debounced(self):
        self._search_timer = None
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        scope = self.scope_combo.get_active_id() or "user"
        sev = self.sev_combo.get_active_id() or "warning"
        unit = self.unit_entry.get_text().strip()
        query = self.search.get_text().strip()
        self.count_label.set_text(tr("Reading journalctl…", "正在读取系统日志…"))
        self.panel.work(
            lambda: backend.read_logs(scope=scope, severity=sev, unit=unit, query=query, limit=120),
            self._render,
            self._failed,
        )

    def _failed(self, err):
        self.busy = False
        self.count_label.set_text(str(err))

    def _render(self, entries: list[dict]):
        self.busy = False
        self.entries = entries
        self.count_label.set_text(tr(f"Showing {len(entries)} recent entries (newest first)",
                                     f"显示最近 {len(entries)} 条日志（最新在前）"))
        for child in self.list_card.get_children():
            child.destroy()
        if not entries:
            pack(self.list_card, wrap_label(tr("No matching log entries. Try switching severity to All info.",
                                               "当前筛选条件下暂无报错日志，可切换为「全部信息」查看。"), "hint"))
        for item in entries[:80]:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col._row_expand = True
            hdr = pack(col, Gtk.Box(spacing=6))
            pack(hdr, status_badge(item["level"].upper(), item["level"]))
            pack(hdr, wrap_label(f"{item['time']}  ·  {item['unit']}", "hint"), True)
            msg = pack(col, wrap_label(item["message"], "spec-value"))
            msg.set_selectable(True)
            pack(self.list_card, data_row(col))
        self.list_card.show_all()

    def _copy_logs(self):
        report = backend.format_plain_report(self.entries)
        self.panel.work(
            lambda: subprocess.run(["wl-copy"], input=report, text=True, capture_output=True, timeout=5, check=True),
            lambda _: self.panel.feedback(tr("Diagnostic log report copied", "诊断日志已复制到剪贴板")),
            lambda err: self.panel.feedback(str(err), True),
            commit=True,
        )
