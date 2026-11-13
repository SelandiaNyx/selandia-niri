"""Wallpaper library card; selection never changes the desktop until Apply."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango, GLib, GdkPixbuf

from control_widgets import pack, style
from i18n import tr
from system_controls import text, button
import wallpaper as backend
from wallpaper_preferences import Preferences
import wallpaper_options


class WallpaperControls(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.panel = panel
        self.busy = self.loaded = False
        self._page_visible = False
        self._current_refresh_pending = False
        self._selected_preview_pending = False
        self._folder_refresh_pending = False
        self.selected = None
        self.serial = 0
        self.catalog = {}
        self.items = {}
        self.thumbnail_queue = []
        self.thumbnail_running = 0
        self.thumbnail_source = None
        self.generation = 0
        self.selecting = False
        narrow = panel.panel_width < 650
        self.current_preview_size = (64, 36) if narrow else (96, 54)
        self.library = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.playback = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.playlist_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        pack(self.details, self.playback)
        pack(self.details, self.playlist_page)

        self.details_scroll = Gtk.ScrolledWindow()
        self.details_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.details_scroll.set_overlay_scrolling(False)
        self.details_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self.details_scroll.set_propagate_natural_height(False)
        self.details_scroll.set_min_content_height(64 if narrow else 88)
        self.details_scroll.add(self.details)

        orientation = Gtk.Orientation.HORIZONTAL if panel.panel_width >= 1000 else Gtk.Orientation.VERTICAL
        if orientation == Gtk.Orientation.HORIZONTAL:
            self.details.set_margin_start(12)
        self.workspace_pane = Gtk.Paned(orientation=orientation)
        self.workspace_pane.pack1(self.library, resize=True, shrink=narrow)
        self.workspace_pane.pack2(self.details_scroll, resize=True, shrink=True)

        current = pack(self, Gtk.Box(spacing=8))
        self.current_thumbnail = pack(current, Gtk.Image())
        self.current_thumbnail.set_size_request(*self.current_preview_size)
        current_text = pack(current, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), True)
        current_heading = pack(current_text, text(tr("Current wallpaper", "当前壁纸"), "section-title"))
        if narrow:
            current_heading.set_no_show_all(True)
            current_heading.hide()
        self.current_description = pack(current_text, text(tr("Reading…", "读取中…")))
        self.current_description.set_max_width_chars(18 if narrow else 32)
        self.current_description.set_line_wrap(False)
        self.current_description.set_ellipsize(Pango.EllipsizeMode.END)
        pack(current, button(tr("Refresh", "刷新"), self.refresh_current))
        pack(self, self.workspace_pane, True)
        self.current_serial = 0
        row = pack(self.playback, Gtk.Box(spacing=12))
        self.image = pack(row, Gtk.Image())
        self.image.set_size_request(128, 72)
        self.description = pack(row, text(tr("Local images and Wallpaper Engine downloads", "本地图片与 Wallpaper Engine 已下载壁纸"), "hint"), True)
        self.description.set_max_width_chars(28)
        toolbar = pack(self.library, Gtk.Box(spacing=6))
        self.search = pack(toolbar, Gtk.SearchEntry(), True)
        self.search.set_placeholder_text(tr("Search wallpapers", "搜索壁纸"))
        self.search.connect("search-changed", self.filter_changed)
        views = pack(toolbar, Gtk.Box(spacing=6))
        self.view_buttons = {}
        self.view_mode = "grid"
        for mode, title in (("grid", tr("Grid", "网格")), ("list", tr("List", "列表"))):
            toggle = pack(views, Gtk.ToggleButton(label=title))
            self.view_buttons[mode] = toggle
            toggle.connect("clicked", lambda _button, value=mode: self.set_view(value))
        self.list = Gtk.ListBox()
        style(self.list, "wallpaper-list")
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list.set_filter_func(lambda row: self.matches(row))
        self.list.connect("row-selected", self.select)
        self.grid = Gtk.FlowBox()
        style(self.grid, "wallpaper-grid")
        self.grid.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.grid.set_min_children_per_line(1)
        self.grid.set_max_children_per_line(6)
        self.grid.set_column_spacing(12)
        self.grid.set_row_spacing(12)
        self.grid.set_homogeneous(True)
        self.grid.set_filter_func(lambda child: self.matches(child))
        self.grid.connect("selected-children-changed", lambda grid: self.select(grid,
                          next(iter(grid.get_selected_children()), None)))
        self.views = Gtk.Stack()
        self.views.set_hhomogeneous(False)
        self.views.set_vhomogeneous(False)
        self.views.add_named(self.list, "list")
        self.views.add_named(self.grid, "grid")
        scroll = pack(self.library, Gtk.ScrolledWindow(), True)
        self.scroll = scroll
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_min_content_height(148)
        scroll.set_vexpand(True)
        scroll.set_propagate_natural_height(False)
        scroll.add(self.views)
        scroll.get_vadjustment().connect("value-changed", lambda *_: self.request_thumbnails())
        self.grid.connect("size-allocate", lambda *_: self.request_thumbnails())
        self.list.connect("size-allocate", lambda *_: self.request_thumbnails())
        self.grid.connect("map", lambda *_: self.request_thumbnails())
        self.list.connect("map", lambda *_: self.request_thumbnails())
        self.set_view("grid")
        actions = pack(self.playback, Gtk.Box(spacing=6))
        pack(actions, button(tr("Choose file", "选择文件"), lambda: self.choose(False)), True)
        pack(actions, button(tr("Add folder", "添加目录"), lambda: self.choose(True)), True)
        pack(actions, button(tr("Rescan", "重新扫描"), self.refresh), True)
        advanced = pack(self.playback, Gtk.Expander(label=tr("Scene/Web playback resources", "场景/网页播放资源")))
        self.assets = Gtk.Entry()
        advanced.add(self.assets)
        self.assets.set_placeholder_text(tr("Optional: Wallpaper Engine assets folder", "可选：Wallpaper Engine assets 目录"))
        self.assets.set_tooltip_text(tr("Original assets required for experimental scene/Web playback", "实验性场景/网页播放需要正版原始资源；可直接粘贴路径"))
        audio = backend.load_settings()["audio"]
        audio_row = pack(self.playback, Gtk.Box(spacing=8))
        self.audio_mute = pack(audio_row, Gtk.CheckButton(label=tr("Mute wallpaper", "静音壁纸")))
        self.audio_mute.set_active(audio["muted"])
        self.audio_volume = pack(audio_row, Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1), True)
        self.audio_volume.set_value(audio["volume"])
        self.audio_volume.set_digits(0)
        self.audio_volume.set_size_request(90, -1)
        self.audio_apply = pack(audio_row, button(tr("Save sound", "保存声音"), self.save_audio))
        self.audio_notice = pack(self.playback, text(tr("Wallpaper sound is on by default; volume applies only to wallpaper.",
                                              "壁纸声音默认开启；此音量仅影响壁纸。"), "hint"))
        apply_row = pack(self.library, Gtk.Box(spacing=8))
        self.preview_button = pack(apply_row, button(tr("Use static wallpaper", "设为静态壁纸"), lambda: self.apply("preview")), True)
        self.live_button = pack(apply_row, button(tr("Apply wallpaper", "应用壁纸"), lambda: self.apply("live")), True)
        style(self.live_button, "accent-button")
        self.notice = pack(self, text("", "hint"))
        self.installation_help = pack(self.playback, text("", "hint"))
        self.installation_help.set_selectable(True)
        self.installation_help.set_no_show_all(True)
        self.notice.set_lines(2)
        self.notice.set_ellipsize(Pango.EllipsizeMode.END)
        self.build_playlist()
        self.preferences = Preferences(self)
        self.render_playlist()
        self.availability()
        self.connect("map", lambda *_: self.refresh() if not self.loaded else None)
        self.connect("destroy", self.cleanup)
        self.refresh_current()

    def build_playlist(self):
        playlist = backend.load_settings()["playlist"]
        self.playlist_items = list(playlist["items"])
        pack(self.playlist_page, text(tr("Playlist", "播放集"), "section-title"))
        self.playlist_enabled = pack(self.playlist_page, Gtk.CheckButton(label=tr("Automatic wallpaper rotation", "自动轮播壁纸")))
        self.playlist_enabled.set_active(playlist["enabled"])
        options = pack(self.playlist_page, Gtk.Box(orientation=Gtk.Orientation.VERTICAL if self.panel.panel_width < 650 else Gtk.Orientation.HORIZONTAL, spacing=8))
        self.playlist_order = pack(options, Gtk.ComboBoxText(), True)
        for key, title in (("sequential", tr("Sequential", "顺序")), ("random", tr("Random (weighted)", "随机（按权重）")), ("shuffle", tr("Shuffle without repeats", "洗牌不重复"))):
            self.playlist_order.append(key, title)
        self.playlist_order.set_active_id(playlist["order"])
        self.playlist_trigger = pack(options, Gtk.ComboBoxText(), True)
        for key, title in (("timer", tr("Timed switching", "定时切换")), ("finished", tr("After playback ends", "播完切换"))):
            self.playlist_trigger.append(key, title)
        self.playlist_trigger.set_active_id(playlist["trigger"])
        timer = pack(self.playlist_page, Gtk.Box(spacing=8))
        pack(timer, text(tr("Interval · minimum 1 second", "间隔 · 最小 1 秒")), True)
        self.playlist_unit = pack(timer, Gtk.ComboBoxText())
        self.playlist_unit.append("seconds", tr("Seconds", "秒"))
        self.playlist_unit.append("minutes", tr("Minutes", "分钟"))
        self.playlist_unit.set_active_id("minutes")
        self.playlist_minutes = pack(timer, Gtk.SpinButton.new_with_range(1, 180, 1))
        self.playlist_minutes.set_value(playlist["minutes"])
        self.playlist_unit.connect("changed", lambda combo: self.playlist_minutes.set_range(1, 180 if combo.get_active_id() == "minutes" else 10800))
        self.playlist_minutes.set_sensitive(playlist["trigger"] == "timer")
        self.playlist_trigger.connect("changed", lambda combo: self.playlist_minutes.set_sensitive(combo.get_active_id() == "timer"))
        pack(self.playlist_page, text(tr("Videos switch at their real end. Static images and endlessly running scenes/Web pages require timed switching. Changes take effect only after Save playlist.",
                           "视频会在实际播完后切换。静态图片和无限运行的场景/网页请用定时切换；修改仅在保存播放集后生效。"), "hint"))
        self.playlist_summary = pack(self.playlist_page, text("", "hint"))
        self.playlist_summary.set_max_width_chars(50)
        self.playlist_summary.set_selectable(True)
        self.playlist_buttons = []
        for actions in (
            ((tr("Add selected", "加入所选"), self.playlist_add),
             (tr("Remove selected", "移出所选"), self.playlist_remove)),
            ((tr("Use filtered library", "使用筛选结果"), self.playlist_filtered),
             (tr("Clear playlist", "清空播放集"), self.playlist_clear)),
            ((tr("Previous", "上一条"), lambda: self.playlist_step(-1)),
             (tr("Next", "下一条"), lambda: self.playlist_step(1))),
        ):
            row = pack(self.playlist_page, Gtk.Box(spacing=8))
            for title, action in actions:
                self.playlist_buttons.append(pack(row, button(title, action), True))
        self.playlist_save = pack(self.playlist_page, button(tr("Save playlist", "保存播放集"), self.save_playlist))
        self.playlist_buttons.append(self.playlist_save)
        self.render_playlist()

    def render_playlist(self):
        titles = [self.items[item["path"]]["item"]["title"] if item["path"] in self.items else
                  backend.Path(item["path"]).name for item in self.playlist_items]
        self.playlist_summary.set_text(tr(f"{len(titles)} entries", f"{len(titles)} 项") +
                                       ("\n" + " · ".join(titles[:3]) if titles else "\n" + tr("Empty: rotation is idle.", "为空时不轮播。")))
        if getattr(self, "preferences", None): self.preferences.render()

    def playlist_entry(self, item):
        capabilities = self.catalog.get("backends", {})
        live = item["type"] == "image" or (item["type"] == "video" and capabilities.get("mpvpaper")) or (
            item["type"] in ("scene", "web") and capabilities.get("linux-wallpaperengine"))
        return {"path": item["path"], "mode": "live" if live else "preview", "enabled": True, "weight": 1}

    def playlist_add(self):
        if self.selected and not self.busy:
            entry = self.playlist_entry(self.selected)
            if not any(item["path"] == entry["path"] for item in self.playlist_items):
                self.playlist_items.append(entry)
            self.render_playlist()

    def playlist_remove(self):
        if self.selected and not self.busy:
            self.playlist_items = [item for item in self.playlist_items if item["path"] != self.selected["path"]]
            self.render_playlist()

    def playlist_filtered(self):
        if not self.busy:
            query = self.search.get_text().casefold()
            self.playlist_items = [self.playlist_entry(entry["item"]) for entry in self.items.values()
                                   if self.matches(entry["list"])]
            self.render_playlist()

    def playlist_clear(self):
        if not self.busy:
            self.playlist_items = []
            self.render_playlist()

    def save_playlist(self):
        if self.busy:
            return
        self.preferences.store()
        value = self.preferences.snapshot()
        registry = backend.wallpaper_playlist.with_current(self.preferences.registry, value)
        expected_registry = self.preferences.saved_registry
        self.busy = True
        self.availability()
        def done(playlist):
            self.preferences.registry = registry
            self.preferences.saved_registry = registry
            self.busy = False
            self.availability()
            self.notice.set_text(tr("Playlist saved; rotation continues after closing this panel.", "播放集已保存；关闭面板后仍会自动轮播。"))
            self.refresh_current()
        self.panel.work(lambda: backend.configure_playlist(value, registry=registry, expected_registry=expected_registry), done, self.failed, commit=True)

    def playlist_step(self, direction):
        if self.busy:
            return
        self.busy = True
        self.availability()
        def done(result):
            self.busy = False
            self.availability()
            self.notice.set_text(tr("Wallpaper changed.", "壁纸已切换。") if result else tr("Playlist is empty.", "播放集为空。"))
            if result:
                self.panel.get_application().reload_theme()
            self.refresh_current()
        self.panel.work(lambda: backend.playlist_step(direction), done, self.failed, commit=True)

    def refresh_current(self, *, force=False):
        if not force and not getattr(self, "_page_visible", False):
            self._current_refresh_pending = True
            return
        self._current_refresh_pending = False
        self.current_serial += 1
        serial = self.current_serial
        def read():
            selection = backend.load_settings()["selection"]
            if not selection:
                return None, backend.pixbuf(backend.current_image(), *self.current_preview_size)
            try:
                item = backend.describe(selection["path"])
                image = backend.pixbuf(backend.preview_image(item), *self.current_preview_size)
            except (OSError, ValueError, backend.subprocess.SubprocessError):
                item = {"title": backend.Path(selection["path"]).name, "type": "unavailable"}
                image = backend.pixbuf(backend.current_image(), *self.current_preview_size)
            return (item, selection["mode"]), image
        def done(result):
            if serial != self.current_serial:
                return
            info, image = result
            self.current_thumbnail.set_from_pixbuf(image)
            if not info:
                self.current_description.set_text(tr("Default wallpaper · static", "默认壁纸 · 静态"))
            else:
                item, mode = info
                kinds = {"image": tr("Image", "图片"), "video": tr("Video", "视频"),
                         "scene": tr("Scene", "场景"), "web": tr("Web", "网页")}
                self.current_description.set_text(item["title"] + "\n" + kinds.get(item["type"], tr("Unavailable", "不可用")) +
                    " · " + (tr("Live mode", "实时模式 (live)") if mode == "live" else tr("Static (preview)", "静态 (preview)")))
            self.current_description.set_tooltip_text(self.current_description.get_text())
            if self.panel.panel_width < 650:
                self.current_description.set_text(self.current_description.get_text().replace("\n", " · "))
        self.panel.work(read, done, lambda error: self.current_description.set_text(tr("Unavailable", "不可用") + "\n" + str(error)))

    def suspend(self):
        """Stop page-local thumbnail work without discarding drafts or catalog."""
        self._page_visible = False
        self._thumbnail_suspended = True
        if self.thumbnail_source is not None:
            if self.thumbnail_source in self.panel.pending:
                GLib.source_remove(self.thumbnail_source)
            self.panel.pending.discard(self.thumbnail_source)
            self.thumbnail_source = None
        for entry in self.thumbnail_queue:
            if not entry["loaded"]:
                entry["queued"] = False
        self.generation += 1
        self.thumbnail_queue.clear()

    def resume(self):
        self._page_visible = True
        self._thumbnail_suspended = False
        if self._current_refresh_pending:
            self.refresh_current(force=True)
        if self._selected_preview_pending and self.selected is not None:
            self._selected_preview_pending = False
            self._load_selected_preview(self.selected, self.serial)
        if self._folder_refresh_pending or not self.loaded:
            self._folder_refresh_pending = False
            self.refresh()
        if self.loaded:
            self.request_thumbnails()

    def cleanup(self, *_):
        self.suspend()
        self.current_serial += 1

    def set_view(self, mode):
        if getattr(self, "changing_view", False):
            return
        self.changing_view = True
        self.view_mode = mode
        try:
            for value, toggle in self.view_buttons.items():
                toggle.set_active(value == mode)
            self.views.set_visible_child_name(mode)
        finally:
            self.changing_view = False
        self.request_thumbnails()

    def matches(self, widget):
        preferences = getattr(self, "preferences", None)
        settings = {"ratings": preferences.ratings, "rating_filter": preferences.filters} if preferences else {}
        return (self.search.get_text().casefold() in widget.search_text and
                wallpaper_options.allowed(settings, widget.item["path"], item=widget.item))

    def filter_changed(self, *_):
        self.list.invalidate_filter()
        self.grid.invalidate_filter()
        if self.selected and self.selected["path"] in self.items and not self.matches(self.items[self.selected["path"]]["list"]):
            self.select(self.list, None)
        self.request_thumbnails()

    def request_thumbnails(self):
        if getattr(self, "_thumbnail_suspended", False):
            return
        if self.thumbnail_source is not None:
            return
        def queue_visible():
            self.panel.pending.discard(self.thumbnail_source)
            self.thumbnail_source = None
            adjustment = self.scroll.get_vadjustment()
            top = adjustment.get_value()
            bottom = top + max(adjustment.get_page_size(), 180) + 170
            for entry in self.items.values():
                widget = entry[self.view_mode]
                allocation = widget.get_allocation()
                if (not entry["loaded"] and not entry["queued"] and widget.get_mapped() and
                        allocation.height > 8 and allocation.y + allocation.height >= top - 170 and allocation.y <= bottom):
                    entry["queued"] = True
                    self.thumbnail_queue.append(entry)
            self.load_thumbnails()
            return GLib.SOURCE_REMOVE
        self.thumbnail_source = GLib.idle_add(queue_visible)
        self.panel.pending.add(self.thumbnail_source)

    def load_thumbnails(self):
        while self.thumbnail_queue and self.thumbnail_running < 3:
            entry = self.thumbnail_queue.pop(0)
            entry["generating"] = True
            self.thumbnail_running += 1
            generation = self.generation
            def finish(image, entry=entry, generation=generation, item=entry["item"]):
                self.thumbnail_running -= 1
                entry["generating"] = False
                valid = (self.generation == generation and entry["item"] is item and
                         self.items.get(item["path"]) is entry)
                entry["queued"] = False
                if valid:
                    entry["loaded"] = True
                    if image is None:
                        entry["grid_image"].set_from_icon_name("image-missing-symbolic", Gtk.IconSize.DIALOG)
                        entry["list_image"].set_from_icon_name("image-missing-symbolic", Gtk.IconSize.DIALOG)
                        entry["grid"].set_tooltip_text(entry["item"]["path"] + "\n" + tr("Preview unavailable", "预览不可用"))
                    else:
                        entry["grid_image"].set_from_pixbuf(image)
                        scale = min(96 / image.get_width(), 54 / image.get_height())
                        entry["list_image"].set_from_pixbuf(image.scale_simple(max(1, round(image.get_width() * scale)),
                                                             max(1, round(image.get_height() * scale)), GdkPixbuf.InterpType.BILINEAR))
                elif not getattr(self, "_thumbnail_suspended", False):
                    # A cancelled in-flight item must become schedulable again.
                    self.request_thumbnails()
                self.load_thumbnails()
            self.panel.work(lambda entry=entry: backend.pixbuf(backend.preview_image(entry["item"]), 224, 126),
                            finish, lambda _error, finish=finish: finish(None))

    def availability(self):
        item = self.selected
        capabilities = self.catalog.get("backends", {})
        kind = item["type"] if item else ""
        can_live = kind == "image" or (kind == "video" and capabilities.get("mpvpaper")) or (
            kind in ("scene", "web") and capabilities.get("linux-wallpaperengine"))
        self.live_button.set_sensitive(bool(can_live) and not self.busy)
        self.audio_apply.set_sensitive(not self.busy)
        self.preview_button.set_sensitive(bool(item and (item["preview"] or kind in ("image", "video"))) and not self.busy)
        for widget in self.playlist_buttons:
            widget.set_sensitive(not self.busy)
        if getattr(self, "preferences", None):
            self.preferences.names.set_sensitive(not self.busy)
            self.preferences.entries.set_sensitive(not self.busy)
            self.preferences.update_notice()
        program = "mpvpaper" if kind == "video" else "linux-wallpaperengine" if kind in ("scene", "web") else None
        hint = backend.installation_hint(program) if program and not capabilities.get(program) else ""
        if kind == "video" and not item["preview"] and not capabilities.get("ffmpeg", True):
            hint += ("\n\n" if hint else "") + backend.installation_hint("ffmpeg")
        self.installation_help.set_text(hint)
        self.installation_help.set_visible(bool(hint))
        self.live_button.set_tooltip_text(hint or None)
        self.live_button.set_label(tr("Play Web wallpaper (experimental)", "播放网页壁纸（实验性）") if kind == "web"
                                   else tr("Apply wallpaper", "应用壁纸"))

    def refresh(self):
        if not getattr(self, "_page_visible", False):
            self._folder_refresh_pending = True
            return
        if self.busy:
            return
        self.busy = True
        self.availability()
        self.notice.set_text(tr("Reading local library…", "正在读取本地资源库…"))
        def done(catalog):
            selected = self.selected["path"] if self.selected else None
            self.generation += 1
            self.thumbnail_queue.clear()
            self.loaded, self.busy = True, False
            self.catalog = catalog
            self.assets.set_text(catalog["assets"])
            for child in self.list.get_children():
                self.list.remove(child)
                child.destroy()
            for child in self.grid.get_children():
                self.grid.remove(child)
                child.destroy()
            self.items.clear()
            for item in catalog["items"]:
                self.add_item(item)
            self.list.show_all()
            self.grid.show_all()
            self.set_view(self.view_mode)
            if selected in self.items:
                self.list.select_row(self.items[selected]["list"])
            elif self.selected:
                self.select(self.list, None)
            self.request_thumbnails()
            notes = [tr(f"{len(catalog['items'])} wallpapers", f"{len(catalog['items'])} 张壁纸")]
            if catalog["missing"]:
                notes.append(tr("Some Steam libraries are not mounted.", "部分 Steam 库尚未挂载。"))
            if not catalog["items"]:
                notes.append(tr("Add the 431960 folder, a project folder, or an image directory.", "可添加 431960 目录、单个项目目录或图片目录。"))
            if catalog["limited"]:
                notes.append(tr("Showing the first 1000 items; choose a smaller folder.", "最多显示 1000 项，请缩小目录范围。"))
            if catalog["errors"]:
                notes.append(tr("Some metadata could not be read.", "部分项目元数据无法读取。"))
            self.notice.set_text("\n".join(notes))
            self.availability()
            self.render_playlist()
            self.refresh_current()
        self.panel.work(backend.discover, done, self.failed)
        if not self.loaded:
            def preview(image):
                if self.selected is None:
                    self.image.set_from_pixbuf(image)
            self.panel.work(lambda: backend.pixbuf(backend.current_image(), 128, 72), preview, lambda _: None)

    def add_item(self, item):
        if item["path"] in self.items:
            entry = self.items[item["path"]]
            if entry["item"] == item:
                return entry["list"]
            del self.items[item["path"]]
            self.thumbnail_queue = [queued for queued in self.thumbnail_queue if queued is not entry]
            for mode in ("list", "grid"):
                getattr(self, mode).remove(entry[mode])
                entry[mode].destroy()
        row = Gtk.ListBoxRow()
        row.item = item
        row.search_text = (item["title"] + " " + item["type"]).casefold()
        label = Gtk.Label(label=item["title"], xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(32)
        for side in ("start", "end", "top", "bottom"):
            getattr(label, "set_margin_" + side)(8)
        content = Gtk.Box(spacing=12)
        list_image = pack(content, Gtk.Image())
        list_image.set_size_request(96, 54)
        pack(content, label, True)
        row.add(content)
        row.set_tooltip_text(item["path"])
        self.list.add(row)
        child = Gtk.FlowBoxChild()
        child.item, child.search_text = item, row.search_text
        style(child, "wallpaper-tile")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        grid_image = pack(content, Gtk.Image())
        grid_image.set_size_request(224, 126)
        title = pack(content, Gtk.Label(label=item["title"], xalign=0))
        title.set_ellipsize(Pango.EllipsizeMode.END)
        title.set_max_width_chars(24)
        child.add(content)
        child.set_tooltip_text(item["path"])
        self.grid.add(child)
        self.items[item["path"]] = dict(item=item, list=row, grid=child, list_image=list_image,
                                      grid_image=grid_image, list_label=label, grid_label=title,
                                      loaded=False, queued=False, generating=False)
        self.request_thumbnails()
        return row

    def select(self, _, row):
        if self.selecting:
            return
        self.selecting = True
        try:
            entry = self.items.get(row.item["path"]) if row else None
            self.list.select_row(entry["list"] if entry else None)
            if entry:
                self.grid.select_child(entry["grid"])
            else:
                self.grid.unselect_all()
        finally:
            self.selecting = False
        self.serial += 1
        serial = self.serial
        self.selected = row.item if row else None
        self.image.clear()
        self.availability()
        if not row:
            self._selected_preview_pending = False
            if getattr(self, "preferences", None):
                self.preferences.update_rating(None)
            return
        item = row.item
        if getattr(self, "preferences", None):
            self.preferences.update_rating(item)
        kinds = {"image": tr("Image", "图片"), "video": tr("Video · mpvpaper required", "视频 · 需要 mpvpaper"),
                 "scene": tr("Scene · experimental backend required", "场景 · 需要实验性播放后端"),
                 "web": tr("Web · experimental; playback executes this project's webpage scripts", "网页 · 实验性；播放会执行此项目自带网页脚本")}
        self.description.set_text(item["title"] + "\n" + kinds.get(item["type"], tr("Static wallpaper only", "仅支持静态壁纸")))
        if not getattr(self, "_page_visible", False):
            self._selected_preview_pending = True
            return
        self._load_selected_preview(item, serial)

    def _load_selected_preview(self, item, serial):
        def done(image):
            if self.serial == serial:
                self.image.set_from_pixbuf(image)
        def failed(_):
            if self.serial == serial:
                self.image.set_from_icon_name("image-missing-symbolic", Gtk.IconSize.DIALOG)
        self.panel.work(lambda: backend.pixbuf(backend.preview_image(item), 128, 72), done, failed)

    def failed(self, error):
        self.busy = False
        self.availability()
        self.notice.set_text(str(error))

    def save_audio(self):
        if self.busy:
            return
        audio = {"muted": self.audio_mute.get_active(), "volume": round(self.audio_volume.get_value())}
        self.busy = True
        self.availability()
        def done(result):
            self.busy = False
            self.availability()
            self.audio_notice.set_text(tr("Wallpaper sound saved.", "壁纸声音已保存。") if result["available"] else
                                       tr("Audio service unavailable: picture continues silently. Save sound again after audio recovers.",
                                          "音频服务不可用：画面继续静音播放；音频恢复后再次保存声音即可。"))
        self.panel.work(lambda: backend.set_audio(audio), done, self.failed, commit=True)

    def choose(self, folder):
        if self.busy:
            return
        dialog = Gtk.FileChooserDialog(title=tr("Choose wallpaper folder" if folder else "Choose wallpaper", "选择壁纸目录" if folder else "选择壁纸"),
                                       transient_for=self.panel,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(tr("Cancel", "取消"), Gtk.ResponseType.CANCEL, tr("Select", "选择"), Gtk.ResponseType.OK)
        dialog.set_local_only(True)
        if not folder:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(tr("Images, videos or project.json", "图片、视频或 project.json"))
            for suffix in sorted(backend.IMAGES | backend.VIDEOS):
                file_filter.add_pattern("*" + suffix)
                file_filter.add_pattern("*" + suffix.upper())
            file_filter.add_pattern("project.json")
            dialog.add_filter(file_filter)
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not path:
            return
        if folder:
            self.busy = True
            self.panel.work(lambda: backend.add_root(path), lambda _: self.folder_added(), self.failed, commit=True)
        else:
            def done(item):
                row = self.add_item(item)
                self.search.set_text("")
                self.list.show_all()
                self.grid.show_all()
                self.list.select_row(row)
            self.panel.work(lambda: backend.describe(path), done, self.failed)

    def folder_added(self):
        self.busy = False
        self.refresh()

    def apply(self, mode):
        if not self.selected or self.busy:
            return
        path, assets = self.selected["path"], self.assets.get_text().strip()
        self.busy = True
        self.availability()
        self.notice.set_text(tr("Applying wallpaper…", "正在应用壁纸…"))
        def done(result):
            self.busy = False
            self.availability()
            self.notice.set_text("\n".join(result["warnings"]) or tr("Wallpaper saved.", "壁纸已保存。"))
            self.panel.get_application().reload_theme()
            self.refresh_current()
        self.panel.work(lambda: backend.activate(path, mode, assets=assets), done, self.failed, commit=True)
