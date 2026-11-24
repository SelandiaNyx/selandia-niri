"""Native keyboard, pointer and Niri window settings with explicit Apply."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import desktop_settings as backend
from i18n import tr


class SettingsPage(Gtk.Box):
    group = ""

    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.panel = panel
        self.fields = {}
        self.busy = False
        self.generation = 0
        self.frozen = {}
        self.settings = dict(backend.DEFAULTS)
        self.notice = self.add(self, panel.compact_label(tr("Loading settings…", "正在读取设置…")))
        self.form = self.add(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12))
        self.build()
        row = self.add(self, Gtk.Box(spacing=8))
        self.apply_button = self.add(row, self.button(tr("Apply changes", "应用更改"), self.apply), True)
        self.apply_button.get_style_context().add_class("accent-button")
        self.reset_button = self.add(row, self.button(tr("Restore defaults", "恢复默认"), self.reset))
        self.refresh_button = self.add(row, self.button(tr("Reload", "重新读取"), self.refresh))
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.refresh()

    @staticmethod
    def add(parent, widget, expand=False):
        parent.pack_start(widget, expand, expand, 0)
        return widget

    @staticmethod
    def button(title, callback):
        button = Gtk.Button(label=title)
        button.connect("clicked", lambda _: callback())
        return button

    def card(self, title):
        return self.panel.card(self.form, title)

    def row(self, parent, title):
        row = self.add(parent, Gtk.Box(spacing=16))
        label = Gtk.Label(label=title, xalign=0)
        label.set_line_wrap(True)
        label.set_max_width_chars(34)
        self.add(row, label, True)
        return row

    def check(self, parent, key, title):
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        self.add(self.row(parent, title), switch)
        self.fields[key] = switch

    def number(self, parent, key, title, step=1):
        low, high = backend.RANGES[key]
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_digits(2 if step < 1 else 0)
        spin.set_width_chars(6)
        self.add(self.row(parent, title), spin)
        self.fields[key] = spin

    def entry(self, parent, key, title, placeholder=""):
        self.add(parent, Gtk.Label(label=title, xalign=0))
        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_max_length(240)
        self.add(parent, entry)
        self.fields[key] = entry

    def choice(self, parent, key, title, choices):
        combo = Gtk.ComboBoxText()
        for value, name in choices:
            combo.append(value, name)
        self.add(self.row(parent, title), combo)
        self.fields[key] = combo

    def populate(self, state):
        self.settings = dict(state["settings"])
        for key, field in self.fields.items():
            value = self.settings[key]
            if isinstance(field, Gtk.Switch):
                field.set_active(value)
            elif isinstance(field, Gtk.SpinButton):
                field.set_value(value)
            elif isinstance(field, Gtk.ComboBoxText):
                field.set_active_id(value)
            else:
                field.set_text(value)
        self.form.set_sensitive(True)
        self.apply_button.set_sensitive(True)
        if self.group == "desktop":
            focus = self.fields["focus_follows_mouse"]
            focus.set_sensitive(not state.get("focus_from_source", False))
            focus.set_tooltip_text(tr("Enabled in the original input config. Remove its focus-follows-mouse rule there before disabling it here; Niri cannot unset it from an include.",
                                      "原输入配置启用了焦点跟随鼠标。请先在原文件移除 focus-follows-mouse；Niri 无法通过后续引用取消它。")
                                   if state.get("focus_from_source") else None)
        if self.group == "input" and state.get("custom_keymap"):
            self.notice.set_text(tr("A custom XKB file controls your keyboard; remove its file setting before applying this page.",
                                    "键盘由自定义 XKB 文件控制，应用此页前请先移除 file 配置。"))
            self.apply_button.set_sensitive(False)
        else:
            self.notice.set_text(tr("Changes are applied only when you choose Apply. Defaults returns to your configuration files.",
                                    "点击“应用更改”才会生效；恢复默认会回到原配置文件的设置。"))

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.generation += 1
        generation = self.generation
        # Freeze the draft while a read is in flight: a late result must never
        # silently replace what the user typed after the read started.
        self.frozen = {widget: widget.get_sensitive() for widget in self.frozen_widgets()}
        for widget in self.frozen:
            widget.set_sensitive(False)
        self.notice.set_text(tr("Reloading settings…", "正在重新读取设置…"))

        def done(state):
            if generation != self.generation:
                return
            self.busy = False
            self.frozen = {}
            self.refresh_button.set_sensitive(True)
            self.reset_button.set_sensitive(True)
            self.populate(state)

        def failed(error):
            if generation != self.generation:
                return
            self.busy = False
            self.restore_frozen()
            self.notice.set_text(str(error))
        self.panel.work(backend.read_state, done, failed)

    def frozen_widgets(self):
        return (self.form, self.apply_button, self.reset_button, self.refresh_button)

    def restore_frozen(self):
        """Return every control to the sensitivity it had before this read."""
        for widget, sensitive in self.frozen.items():
            widget.set_sensitive(sensitive)
        self.frozen = {}

    def draft(self):
        values = {}
        for key, field in self.fields.items():
            if isinstance(field, Gtk.Switch):
                value = field.get_active()
            elif isinstance(field, Gtk.SpinButton):
                value = field.get_value_as_int() if isinstance(backend.DEFAULTS[key], int) else field.get_value()
            elif isinstance(field, Gtk.ComboBoxText):
                value = field.get_active_id()
            else:
                value = field.get_text().strip()
            values[key] = value
        return backend.validate_settings(self.group, values)

    def apply(self):
        if self.busy:
            return
        try:
            values = self.draft()
        except ValueError as error:
            self.notice.set_text(str(error))
            return
        self.commit(lambda: backend.apply_settings(self.group, values))

    def reset(self):
        if not self.busy:
            self.commit(lambda: backend.restore_defaults(self.group))

    def commit(self, task):
        self.busy = True
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.reset_button.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.notice.set_text(tr("Validating and applying…", "正在校验并应用…"))

        def finish():
            self.busy = False
            self.form.set_sensitive(True)
            self.apply_button.set_sensitive(True)
            self.reset_button.set_sensitive(True)
            self.refresh_button.set_sensitive(True)

        def done(state):
            finish()
            self.populate(state)
            self.notice.set_text(tr("Settings applied. New column size affects newly opened windows.",
                                    "设置已应用。默认列宽仅影响新打开的窗口。") if self.group == "desktop" else
                                 tr("Input settings applied.", "输入设置已应用。"))

        def failed(error):
            finish()
            self.notice.set_text(str(error))
        self.panel.work(task, done, failed, commit=True)


class InputSettings(SettingsPage):
    group = "input"

    def build(self):
        card = self.card(tr("Input method", "输入法"))
        self.add(card, self.panel.compact_label(tr("Fcitx 5 manages input methods separately from the keyboard layout below.",
                                                  "Fcitx 5 管理输入法，下方的键盘布局设置独立生效。")))
        self.add(card, self.button(tr("Configure Fcitx 5", "配置 Fcitx 5 输入法"),
                                   lambda: (self.panel.launch_external([self.panel.desktop_script(), "launch", "input"])
                                            if hasattr(self.panel, "launch_external") else self.panel.desktop("launch", "input"))))
        card = self.card(tr("Keyboard", "键盘"))
        self.entry(card, "keyboard_layout", tr("Keyboard layouts", "键盘布局"), "us / us,de")
        self.entry(card, "keyboard_variant", tr("Layout variants", "布局变体"), " / dvorak")
        self.entry(card, "keyboard_options", tr("XKB options", "XKB 选项"), "ctrl:nocaps,grp:win_space_toggle")
        self.add(card, self.panel.compact_label(tr("Use comma-separated XKB names. ctrl:nocaps makes Caps Lock act as Ctrl; grp:win_space_toggle switches layouts with Super+Space.",
                                                  "多个 XKB 名称用逗号分隔。ctrl:nocaps 将大写锁定键改为 Ctrl；grp:win_space_toggle 使用 Super+空格切换布局。")))
        self.number(card, "keyboard_repeat_delay", tr("Repeat delay (ms)", "按键重复延迟（毫秒）"), 25)
        self.number(card, "keyboard_repeat_rate", tr("Repeat rate (per second)", "按键重复速度（次/秒）"))
        test_entry = Gtk.Entry()
        test_entry.set_placeholder_text(tr("Hold a key here to test repeat delay & rate…", "在此按住任意键测试重复延迟与速度…"))
        self.add(card, test_entry)
        self.check(card, "keyboard_numlock", tr("Num Lock at login", "登录时启用数字锁定"))
        self.choice(card, "keyboard_track_layout", tr("Remember layout", "记忆布局"),
                    [("global", tr("Globally", "全局")), ("window", tr("Per window", "每个窗口"))])
        for kind, title in (("mouse", tr("Mouse", "鼠标")), ("touchpad", tr("Touchpad", "触控板"))):
            card = self.card(title)
            self.number(card, kind + "_accel_speed", tr("Pointer speed", "指针速度"), 0.05)
            self.choice(card, kind + "_accel_profile", tr("Acceleration", "加速模式"),
                        [("flat", tr("None", "关闭")), ("adaptive", tr("Adaptive", "自适应"))])
            self.number(card, kind + "_scroll_factor", tr("Scroll speed", "滚动速度"), 0.1)
            self.check(card, kind + "_natural_scroll", tr("Natural scrolling", "自然滚动"))
            self.check(card, kind + "_left_handed", tr("Left-handed buttons", "左手按钮布局"))
            if kind == "touchpad":
                self.check(card, "touchpad_tap", tr("Tap to click", "轻触点击"))
                self.check(card, "touchpad_dwt", tr("Disable while typing", "输入时禁用"))
                self.check(card, "touchpad_disabled_on_external_mouse", tr("Disable with external mouse", "连接外部鼠标时禁用"))
                self.choice(card, "touchpad_scroll_method", tr("Scrolling method", "滚动方式"),
                            [("two-finger", tr("Two fingers", "双指")), ("edge", tr("Edge", "边缘"))])


class DesktopSettings(SettingsPage):
    group = "desktop"

    def build(self):
        card = self.card(tr("Windows & workspaces", "窗口与工作区"))
        self.number(card, "gaps", tr("Window gaps (px)", "窗口间距（像素）"))
        self.number(card, "column_width", tr("Default column proportion", "默认列宽比例"), 0.05)
        self.choice(card, "column_center", tr("Center focused column", "居中聚焦列"),
                    [("never", tr("Never", "从不")), ("on-overflow", tr("When overflowing", "超出屏幕时")), ("always", tr("Always", "始终"))])
        self.choice(card, "default_column_display", tr("New column style", "新列显示方式"),
                    [("normal", tr("Tiled", "平铺")), ("tabbed", tr("Tabbed", "标签页"))])
        self.check(card, "always_center_single_column", tr("Center a single column", "单列时居中"))
        self.check(card, "empty_workspace_above_first", tr("Empty workspace above the first", "首个工作区上方保留空工作区"))
        self.check(card, "workspace_auto_back_and_forth", tr("Switch back when selecting current workspace", "再次选择当前工作区时返回上一工作区"))
        card = self.card(tr("Borders & focus", "边框与焦点"))
        self.check(card, "focus_ring", tr("Show focus ring", "显示焦点环"))
        self.number(card, "focus_ring_width", tr("Focus ring width (px)", "焦点环宽度（像素）"))
        self.check(card, "border", tr("Show window borders", "显示窗口边框"))
        self.number(card, "border_width", tr("Border width (px)", "边框宽度（像素）"))
        self.check(card, "focus_follows_mouse", tr("Focus follows pointer", "焦点跟随鼠标"))
        card = self.card(tr("Pointer", "光标"))
        self.number(card, "cursor_size", tr("Cursor size (px)", "光标大小（像素）"), 2)
        self.check(card, "cursor_hide_when_typing", tr("Hide cursor while typing", "输入时隐藏光标"))
