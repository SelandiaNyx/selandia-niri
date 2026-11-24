"""Searchable categories for the Niri desktop settings window."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango
from control_widgets import icon, pack, style
from i18n import tr
from navigation_catalog import GROUP_LABELS, PAGES, PAGE_KEYS  # re-exported API


class SettingsNavigation(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.panel = panel
        self.rows = {}
        self.syncing = False
        self._reveal_source = None
        self._reveal_pending = False
        self._disposed = False
        style(self, "settings-sidebar")
        # MD3 Navigation Drawer width: generous room for English & Chinese labels.
        self.set_size_request(224, -1)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(tr("Search settings", "搜索设置"))
        self.search.set_tooltip_text(tr("Search names and functions · Ctrl+F", "按名称或功能搜索 · Ctrl+F"))
        pack(self, self.search)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        style(self.list, "settings-navigation")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.add(self.list)
        self.scroll = scroll
        pack(self, scroll, True)
        previous = None
        for key, english, chinese, glyph, group, keywords in PAGES:
            if group != previous:
                heading = Gtk.ListBoxRow()
                heading.is_header = True
                style(heading, "nav-group-row")
                heading.set_selectable(False)
                heading.set_activatable(False)
                english_group, chinese_group = GROUP_LABELS.get(group, (group, group))
                group_label = Gtk.Label(label="✦  " + tr(english_group, chinese_group), xalign=0)
                group_label.get_style_context().add_class("nav-group")
                heading.add(group_label)
                self.list.add(heading)
                previous = group
            row = Gtk.ListBoxRow()
            row.key = key
            row.search_text = " ".join((english, chinese, keywords)).casefold()
            row.group = group
            content = Gtk.Box(spacing=10)
            pack(content, icon(glyph, 18))
            label = Gtk.Label(label=tr(english, chinese), xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.NONE)
            label.set_line_wrap(True)
            label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            # Keep requested width comfortably inside the 224 px navigation drawer.
            label.set_max_width_chars(18)
            pack(content, label, True)
            row.add(content)
            row.set_tooltip_text(tr(english, chinese))
            self.rows[key] = row
            self.list.add(row)
            previous = group
        self.empty = Gtk.Label(label=tr("No matching settings", "没有匹配的设置"))
        self.empty.set_line_wrap(True)
        self.empty.set_no_show_all(True)
        pack(self, self.empty)
        self.mascot_box = Gtk.Box()
        style(self.mascot_box, "nav-mascot")
        self.mascot_box.set_can_focus(False)
        pack(self, self.mascot_box)
        self.list.set_filter_func(self.matches)
        self.search.connect("search-changed", self.filter)
        self.search.connect("activate", self.search_activate)
        self.search.connect("stop-search", lambda _: self.search.set_text(""))
        self.search.connect("key-press-event", self._on_search_key)
        self.list.connect("row-selected", self.selected)
        self.list.connect("size-allocate", self._on_list_allocate)
        self.connect("destroy", self.dispose)

    def _on_search_key(self, _entry, event):
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            target = self.rows.get(self.panel.control_stack.get_visible_child_name())
            if target is None or not self.matches(target):
                target = next((row for row in self.rows.values() if self.matches(row)), None)
            if target is not None:
                self.panel.select_control_tab(target.key, focus=True)
            return True
        return False

    def matches(self, row):
        if getattr(row, "is_header", False):
            return not self.search.get_text().strip()
        terms = self.search.get_text().casefold().split()
        return all(term in row.search_text for term in terms)

    def filter(self, *_):
        self.list.invalidate_filter()
        self.empty.set_visible(not any(self.matches(row) for row in self.rows.values()))

    def search_activate(self, *_):
        target = next((row for row in self.rows.values() if self.matches(row)), None)
        if target:
            self.panel.select_control_tab(target.key, focus=True)

    def selected(self, _list, row):
        if row and not self.syncing and not getattr(row, "is_header", False):
            self.panel.select_control_tab(row.key)

    def select(self, key, focus=False):
        row = self.rows.get(key)
        if row is None:
            return
        if not self.matches(row):
            self.search.set_text("")
            self.filter()
        self.syncing = True
        self.list.select_row(row)
        self.syncing = False
        self._reveal_pending = True
        self.schedule_reveal()
        if focus:
            row.grab_focus()

    def _on_list_allocate(self, *_):
        if self._reveal_pending:
            self.schedule_reveal()

    def schedule_reveal(self):
        if not self._disposed and self._reveal_source is None:
            self._reveal_source = GLib.idle_add(self.reveal_selected)

    def reveal_selected(self):
        self._reveal_source = None
        if self._disposed:
            return GLib.SOURCE_REMOVE
        row = self.list.get_selected_row()
        if row is None:
            self._reveal_pending = False
            return GLib.SOURCE_REMOVE
        adjustment = self.scroll.get_vadjustment()
        allocation = row.get_allocation()
        if row.get_mapped() and allocation.height > 0 and adjustment.get_page_size() > 0:
            adjustment.clamp_page(allocation.y, allocation.y + allocation.height)
            self._reveal_pending = False
        return GLib.SOURCE_REMOVE

    def dispose(self, *_):
        self._disposed = True
        self._reveal_pending = False
        if self._reveal_source is not None:
            GLib.source_remove(self._reveal_source)
            self._reveal_source = None

    def focus_current(self):
        self.select(self.panel.control_stack.get_visible_child_name(), focus=True)
