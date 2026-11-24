"""Ctrl+K Global Command & Setting Palette overlay for Control Center 2.0."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from control_widgets import icon, pack, status_badge, style
from i18n import tr
from navigation_catalog import GROUP_LABELS, PAGES, SETTING_INDEX


class CommandPalette(Gtk.EventBox):
    """Floating MD3 search overlay indexing every page, setting, and quick action."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        style(self, "command-palette-scrim")
        self.set_visible_window(True)
        self.set_above_child(False)
        self.set_no_show_all(True)
        self.connect("button-press-event", self._on_scrim_click)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)
        outer.set_margin_top(76)
        self.add(outer)

        card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "command-palette-box")
        card.set_size_request(560, -1)
        self._card = card
        outer.pack_start(card, False, False, 0)

        top = pack(card, Gtk.Box(spacing=8))
        self.entry = pack(top, Gtk.SearchEntry(), True)
        self.entry.set_placeholder_text(tr("Jump to any setting, page or action… (Ctrl+K)", "搜索任意设置项、页面或快捷动作…（Ctrl+K）"))
        self.entry.connect("search-changed", self._filter)
        self.entry.connect("activate", self._activate_selected)
        self.entry.connect("key-press-event", self._on_entry_key)
        close_btn = style(Gtk.Button(label="×"), "close-button")
        close_btn.set_tooltip_text(tr("Close (Esc)", "关闭（Esc）"))
        close_btn.connect("clicked", lambda _: self.close())
        pack(top, close_btn)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_min_content_height(120)
        scroll.set_max_content_height(420)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.connect("row-activated", self._on_row_activated)
        scroll.add(self.list)
        pack(card, scroll, True)

        self.hint = pack(card, Gtk.Label(label=tr("↑↓ Navigate · Enter Open · Esc Close", "↑↓ 选择 · Enter 直达 · Esc 关闭"), xalign=0))
        style(self.hint, "hint")

        self._items = self._build_catalog()
        self._rows: list[Gtk.ListBoxRow] = []
        self._populate()

    def _build_catalog(self) -> list[dict]:
        items = []
        page_titles = {k: tr(en, zh) for k, en, zh, *_ in PAGES}
        page_icons = {k: glyph for k, _en, _zh, glyph, *_ in PAGES}
        for key, en, zh, glyph, group, keywords in PAGES:
            g_en, g_zh = GROUP_LABELS.get(group, (group, group))
            items.append({
                "kind": "page",
                "title": tr(en, zh),
                "badge": tr(g_en, g_zh),
                "icon": glyph,
                "page": key,
                "subtab": None,
                "search": " ".join((key, en, zh, g_en, g_zh, keywords)).casefold(),
            })
        for en, zh, page_key, subtab, keywords in SETTING_INDEX:
            items.append({
                "kind": "setting",
                "title": tr(en, zh),
                "badge": page_titles.get(page_key, page_key),
                "icon": page_icons.get(page_key, "preferences-system-symbolic"),
                "page": page_key,
                "subtab": subtab,
                "search": " ".join((en, zh, page_key, str(subtab or ""), keywords)).casefold(),
            })
        return items

    def _populate(self):
        for child in self.list.get_children():
            child.destroy()
        self._rows = []
        for item in self._items:
            row = Gtk.ListBoxRow()
            row._item = item
            box = Gtk.Box(spacing=10)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            box.set_margin_start(6)
            box.set_margin_end(6)
            pack(box, icon(item["icon"], 16))
            pack(box, Gtk.Label(label=item["title"], xalign=0), True)
            pack(box, status_badge(item["badge"], "info" if item["kind"] == "page" else ""))
            row.add(box)
            self.list.add(row)
            self._rows.append(row)
        self.list.show_all()
        self.list.set_filter_func(self._matches)

    def _matches(self, row: Gtk.ListBoxRow) -> bool:
        terms = self.entry.get_text().strip().casefold().split()
        if not terms:
            return row._item["kind"] == "page"
        hay = row._item["search"]
        return all(t in hay for t in terms)

    def _filter(self, *_):
        self.list.invalidate_filter()
        for row in self._rows:
            if self._matches(row):
                self.list.select_row(row)
                break

    def _on_scrim_click(self, _widget, event):
        alloc = self._card.get_allocation()
        if not (alloc.x <= event.x <= alloc.x + alloc.width and alloc.y <= event.y <= alloc.y + alloc.height):
            self.close()
            return True
        return False

    def _on_entry_key(self, _entry, event):
        if event.keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            visible = [r for r in self._rows if self._matches(r)]
            if not visible:
                return True
            current = self.list.get_selected_row()
            idx = visible.index(current) if current in visible else -1
            step = 1 if event.keyval == Gdk.KEY_Down else -1
            target = visible[(idx + step) % len(visible)]
            self.list.select_row(target)
            return True
        return False

    def _activate_selected(self, *_):
        row = self.list.get_selected_row()
        if row is None or not self._matches(row):
            row = next((r for r in self._rows if self._matches(r)), None)
        if row is not None:
            self._jump(row._item)

    def _on_row_activated(self, _list, row):
        if row is not None:
            self._jump(row._item)

    def _jump(self, item: dict):
        self.close()
        self.panel.select_control_tab(item["page"], subtab=item.get("subtab"))

    def open(self):
        self.entry.set_text("")
        self._filter()
        self.set_no_show_all(False)
        self.show_all()
        self.set_no_show_all(True)
        GLib.idle_add(self.entry.grab_focus)

    def close(self):
        self.hide()

    def is_open(self) -> bool:
        return self.get_visible()
