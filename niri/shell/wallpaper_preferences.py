"""Playlist drafts, display options and explicit rating confirmation in GTK."""
from copy import deepcopy
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Pango
from control_widgets import pack
from system_controls import text, button
from i18n import tr
import wallpaper as backend
import wallpaper_playlist as policy
import wallpaper_options as options


class Preferences:
    def __init__(self, owner):
        self.owner = owner
        settings = backend.load_settings()
        self.registry = deepcopy(settings['playlists'])
        self.saved_registry = deepcopy(self.registry)
        self.ratings, self.filters = settings['ratings'], settings['rating_filter']
        self.loading = False
        self.selected_index = 0
        self.build_names()
        self.build_editor()
        self.build_playback(settings)
        self.load_names()

    def build_names(self):
        owner = self.owner
        row = Gtk.Box(spacing=8)
        owner.playlist_page.pack_start(row, False, False, 0)
        owner.playlist_page.reorder_child(row, 0)
        self.names = pack(row, Gtk.ComboBoxText(), True)
        self.names.connect('changed', self.switch)
        self.name_entry = pack(owner.playlist_page, Gtk.Entry())
        owner.playlist_page.reorder_child(self.name_entry, 1)
        self.name_entry.set_max_length(64)
        self.name_entry.set_placeholder_text(tr('Playlist name (1–64 characters)', '播放集名称（1–64 字）'))
        self.name_entry.set_tooltip_text(tr('Letters, numbers, spaces and _-.(); Save applies all playlist edits.', '允许汉字、字母、数字、空格和 _-.()；保存后应用所有播放集修改。'))
        row = pack(owner.playlist_page, Gtk.Box(spacing=6))
        owner.playlist_page.reorder_child(row, 2)
        for action, title in (('create', tr('New', '新建')), ('rename', tr('Rename', '重命名')),
                              ('duplicate', tr('Copy', '复制')), ('delete', tr('Delete', '删除'))):
            owner.playlist_buttons.append(pack(row, button(title, lambda value=action: self.manage(value)), True))
        pack(owner.playlist_page, text(tr('The selected playlist becomes active after Save. Unsaved drafts are retained when switching within this panel.',
                                        '保存后，所选播放集成为当前生效的播放集；在本面板内切换会保留未保存草稿。'), 'hint'))

    def snapshot(self):
        owner = self.owner
        seconds = owner.playlist_minutes.get_value_as_int() * (60 if owner.playlist_unit.get_active_id() == 'minutes' else 1)
        old = policy.current(self.registry)['settings']
        result = {**old, 'enabled': owner.playlist_enabled.get_active(), 'items': deepcopy(owner.playlist_items),
                  'order': owner.playlist_order.get_active_id(), 'trigger': owner.playlist_trigger.get_active_id(), 'seconds': seconds}
        if any(result[key] != old[key] for key in ('items', 'order')): result['cycle'] = []
        return policy.validate(result, backend.clean_path)

    def store(self):
        policy.current(self.registry)['settings'] = self.snapshot()

    @staticmethod
    def profile_title(entry):
        return tr('Default', '默认') if entry['id'] == 'default' and entry['name'] == 'Default' else entry['name']

    def load_names(self):
        self.loading = True
        self.names.remove_all()
        for entry in self.registry['lists']: self.names.append(entry['id'], self.profile_title(entry))
        self.names.set_active_id(self.registry['active'])
        self.name_entry.set_text(self.profile_title(policy.current(self.registry)))
        self.loading = False
        self.load_current()

    def load_current(self):
        value = policy.current(self.registry)['settings']
        owner = self.owner
        owner.playlist_items = deepcopy(value['items'])
        owner.playlist_enabled.set_active(value['enabled'])
        owner.playlist_order.set_active_id(value['order'])
        owner.playlist_trigger.set_active_id(value['trigger'])
        owner.playlist_unit.set_active_id('minutes' if value['seconds'] % 60 == 0 else 'seconds')
        owner.playlist_minutes.set_value(value['seconds'] // 60 if value['seconds'] % 60 == 0 else value['seconds'])
        self.name_entry.set_text(self.profile_title(policy.current(self.registry)))
        owner.render_playlist()

    def switch(self, combo):
        if self.loading or not combo.get_active_id(): return
        if self.owner.busy:
            self.loading = True; combo.set_active_id(self.registry['active']); self.loading = False
            return
        self.store()
        self.registry = policy.manage(self.registry, 'select', identifier=combo.get_active_id())
        self.load_current()

    def manage(self, action):
        if self.owner.busy: return
        try:
            self.store()
            self.registry = policy.manage(self.registry, action, title=self.name_entry.get_text())
            self.load_names()
            self.owner.notice.set_text(tr('Playlist draft updated. Save to apply.', '播放集草稿已更新，请保存以应用。'))
        except ValueError as error:
            self.owner.notice.set_text(str(error))

    def build_editor(self):
        owner = self.owner
        self.entries = pack(owner.playlist_page, Gtk.ListBox())
        self.entries.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.entries.connect('row-selected', self.select_entry)
        row = pack(owner.playlist_page, Gtk.Box(spacing=8))
        self.entry_enabled = pack(row, Gtk.CheckButton(label=tr('Entry enabled', '启用此条目')))
        self.entry_enabled.connect('toggled', lambda widget: self.edit('enabled', widget.get_active(), redraw=False))
        pack(row, text(tr('Weight (1–100)', '权重（1–100）')), True)
        self.weight = pack(row, Gtk.SpinButton.new_with_range(1, 100, 1))
        self.weight.connect('value-changed', lambda widget: self.edit('weight', widget.get_value_as_int(), redraw=False))
        for actions in ((('up', tr('Up', '上移')), ('down', tr('Down', '下移')), ('top', tr('First', '置顶'))),
                        (('sort-name', tr('Sort by name', '按名称排序')), ('sort-path', tr('Sort by path', '按路径排序')), ('remove', tr('Remove entry', '移除此条')))):
            row = pack(owner.playlist_page, Gtk.Box(spacing=6))
            for action, title in actions: owner.playlist_buttons.append(pack(row, button(title, lambda value=action: self.edit(value)), True))

        # Controls precede long lists; keep one vertical page scroller.
        owner.playlist_page.reorder_child(self.entries, -1)

    def select_entry(self, _list, row):
        if self.loading: return
        self.selected_index = row.get_index() if row else 0
        value = self.owner.playlist_items[self.selected_index] if row else None
        self.loading = True
        self.entry_enabled.set_sensitive(value is not None and not self.owner.busy)
        self.weight.set_sensitive(value is not None and not self.owner.busy)
        self.entry_enabled.set_active(value.get('enabled', True) if value else False)
        self.weight.set_value(value.get('weight', 1) if value else 1)
        self.loading = False

    def render(self):
        index = self.selected_index
        self.loading = True
        for row in self.entries.get_children(): row.destroy()
        for item in self.owner.playlist_items:
            label = text(('✓ ' if item.get('enabled', True) else '− ') + self.title(item) + ' · ' + str(item.get('weight', 1)))
            label.set_line_wrap(False); label.set_max_width_chars(28); label.set_ellipsize(Pango.EllipsizeMode.END)
            row = Gtk.ListBoxRow(); row.add(label); row.set_tooltip_text(item['path']); self.entries.add(row)
        self.entries.show_all()
        self.loading = False
        self.entries.select_row(self.entries.get_row_at_index(min(index, len(self.owner.playlist_items) - 1)))

    def title(self, item):
        entry = self.owner.items.get(item['path'])
        return entry['item']['title'] if entry else backend.Path(item['path']).name

    def edit(self, action, value=None, redraw=True):
        if self.loading or self.owner.busy: return
        index = self.selected_index
        self.owner.playlist_items = policy.edit(self.owner.playlist_items, action, index, value=value, title=self.title)
        if action == 'up': self.selected_index = max(0, index - 1)
        elif action == 'down': self.selected_index = min(len(self.owner.playlist_items) - 1, index + 1)
        elif action == 'top': self.selected_index = 0
        if redraw: self.owner.render_playlist()
        else:
            row = self.entries.get_row_at_index(index)
            if row:
                item = self.owner.playlist_items[index]
                row.get_child().set_text(('✓ ' if item.get('enabled', True) else '− ') + self.title(item) + ' · ' + str(item.get('weight', 1)))

    def build_playback(self, settings):
        owner = self.owner
        display_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pack(display_box, text(tr('Display mode and transitions', '显示模式与过渡'), 'section-title'))
        row = pack(display_box, Gtk.Box(spacing=8))
        self.display = pack(row, Gtk.ComboBoxText(), True)
        for mode, title in zip(options.MODES, (tr('Fill', '填充'), tr('Cover', '覆盖'), tr('Stretch', '拉伸'), tr('Fit', '完整显示'), tr('Center', '居中'), tr('Tile', '平铺'))):
            self.display.append(mode, title)
        self.display.set_active_id(settings['display']['mode'])
        self.transition = pack(row, Gtk.ComboBoxText(), True)
        for mode, title in (('instant', tr('Instant', '瞬间切换')), ('fade', tr('Crossfade', '淡入淡出'))): self.transition.append(mode, title)
        self.transition.set_active_id(settings['display']['transition'])
        row = pack(display_box, Gtk.Box(spacing=8))
        pack(row, text(tr('Fade duration (seconds, 0.1–10)', '过渡时长（秒，0.1–10）')), True)
        self.duration = pack(row, Gtk.SpinButton.new_with_range(.1, 10, .1)); self.duration.set_digits(1)
        self.duration.set_value(settings['display']['duration'])
        owner.playlist_buttons.append(pack(display_box, button(tr('Save display settings', '保存显示设置'), self.save_display)))
        self.capabilities = pack(display_box, text('', 'hint'))
        self.capabilities.set_max_width_chars(35)
        for widget in (self.display, self.transition, self.duration): widget.connect('changed' if isinstance(widget, Gtk.ComboBoxText) else 'value-changed', lambda *_: self.update_notice())

        rating_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pack(rating_box, text(tr('Age ratings', '年龄分级'), 'section-title'))
        self.rating_filter = pack(rating_box, Gtk.ComboBoxText())
        for key, title in (('all', tr('All ratings', '全部')),
                           ('everyone', tr('Everyone · All ages', 'Everyone · 全年龄')),
                           ('pg13', tr('PG13 · Teens', 'PG13 · 青少年')),
                           ('mature', tr('Mature · Adults', 'Mature · 成人')),
                           ('unrated', tr('Unrated', '未分级'))):
            self.rating_filter.append(key, title)
        initial_choice = options.filter_choice(self.filters)
        if initial_choice == 'custom':
            self.rating_filter.append('custom', tr('Saved filter', '已保存筛选'))
        self.rating_filter.set_active_id(initial_choice)
        self.rating_summary = pack(rating_box, text('', 'hint'))
        self.rating_summary.set_max_width_chars(35)
        owner.playlist_buttons.append(pack(rating_box, button(tr('Save age filter', '保存分级过滤'), self.save_filter)))

        owner.playback.pack_start(display_box, False, False, 0)
        owner.playback.reorder_child(display_box, 1)
        owner.playback.pack_start(rating_box, False, False, 0)
        owner.playback.reorder_child(rating_box, 2)
        self.update_rating(self.owner.selected)
        self.update_notice()

    def update_rating(self, item=None):
        if not item:
            self.rating_summary.set_text(tr('Wallpaper Engine original ratings are read automatically.',
                                            '自动读取 Wallpaper Engine 原有分级。'))
            return
        settings = {'ratings': self.ratings, 'rating_filter': self.filters}
        info = options.rating_info(settings, item['path'], item=item)
        names = {
            'everyone': tr('Everyone', 'Everyone'),
            'questionable': tr('PG-13 / Questionable', 'PG13 / Questionable'),
            'mature': tr('Mature', 'Mature'),
            'unrated': tr('Unrated', '未分级'),
        }
        rating_name = names.get(info.get('rating'), info.get('rating', tr('Unrated', '未分级')))
        source = info.get('source')
        if source == 'project':
            source_name = tr('Wallpaper Engine project', 'Wallpaper Engine 项目')
        elif source == 'local-label':
            source_name = tr('saved local label', '已保存的本地标签')
        else:
            source_name = tr('local file', '本地文件')
        self.rating_summary.set_text(tr(f'Rating: {rating_name} ({source_name})',
                                        f'分级：{rating_name}（来源：{source_name}）'))

    def display_value(self):
        return {'mode': self.display.get_active_id(), 'transition': self.transition.get_active_id(), 'duration': self.duration.get_value()}

    def update_notice(self):
        item = self.owner.selected or {'type': 'image'}
        value = options.notices(item, 'live', self.display_value())
        value.append(tr('Fade works between static wallpapers. Video, scene and Web backends switch instantly.', '淡入淡出适用于静态壁纸之间；视频、场景和网页后端使用瞬间切换。'))
        self.capabilities.set_text('\n'.join(value))

    def confirm(self, message):
        dialog = Gtk.MessageDialog(transient_for=self.owner.panel, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.NONE, text=message)
        dialog.add_buttons(tr('Cancel', '取消'), Gtk.ResponseType.CANCEL, tr('Confirm', '确认'), Gtk.ResponseType.OK)
        response = dialog.run(); dialog.destroy()
        return response == Gtk.ResponseType.OK

    def commit(self, function, done):
        if self.owner.busy: return
        self.owner.busy = True; self.owner.availability()
        def finish(value):
            self.owner.busy = False; done(value); self.owner.availability()
            self.owner.notice.set_text(tr('Wallpaper preferences saved.', '壁纸偏好已保存。'))
        self.owner.panel.work(function, finish, self.owner.failed, commit=True)

    def save_display(self):
        value = self.display_value()
        self.commit(lambda: backend.configure_display(value), lambda _: self.owner.refresh_current())

    def save_filter(self):
        choice = self.rating_filter.get_active_id()
        if choice and choice != 'custom':
            value = options.filter_value(choice)
        else:
            value = dict(self.filters)
        confirmation = False
        if value.get('mature') and not self.filters.get('mature'):
            confirmation = self.confirm(tr('Show Mature content in the library and allow it in wallpaper rotation?', '显示 Mature 内容，并允许播放集轮播这些壁纸？'))
            if not confirmation:
                saved_choice = options.filter_choice(self.filters)
                self.rating_filter.set_active_id(saved_choice)
                return
        def done(result):
            self.filters = result
            self.owner.filter_changed()
        self.commit(lambda: backend.configure_rating_filter(value, confirm_mature=confirmation), done)

