"""Native language preferences: interface, user session, and system are explicit."""
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

import language_settings as backend
from i18n import tr, set_language


class LanguageSettings(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.panel = panel
        self.busy = False
        self.state = {}
        self.notice = self.add(self, panel.compact_label(tr("Reading language settings…", "正在读取语言设置…")))
        self.form = self.add(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14))

        card = panel.card(self.form, tr("Interface language", "界面语言"))
        self.add(card, panel.compact_label(tr(
            "Use one language throughout the control center and desktop controls.",
            "为控制中心和桌面组件选择统一的界面语言。")))
        self.ui = self.add(card, self.combo())
        self.ui.append("system", tr("Follow session language", "跟随会话语言"))
        self.ui.append("zh_CN", "简体中文")
        self.ui.append("en_US", "English")
        self.ui.set_active_id(backend.read_preferences()["ui_language"])
        self.ui_apply = self.add(card, self.button(tr("Apply interface language", "应用界面语言"), self.apply_ui))
        self.ui_apply.get_style_context().add_class("accent-button")

        card = panel.card(self.form, tr("Terminal and user session", "终端与用户会话"))
        self.session_current = self.add(card, panel.compact_label())
        self.session = self.add(card, self.combo())
        self.session_apply = self.add(card, self.button(tr("Apply to this user", "应用到当前用户"), self.apply_session))
        self.add(card, panel.compact_label(tr(
            "New terminals and applications opened from Niri use this language. Reopen existing applications; sign out and back in for the complete session.",
            "从 Niri 启动的新终端和应用将使用此语言。已有应用需要重新打开；完整会话请注销后重新登录。")))
        self.override_note = self.add(card, panel.compact_label())
        self.override_note.set_no_show_all(True)

        card = panel.card(self.form, tr("System default", "系统默认语言"))
        self.system_current = self.add(card, panel.compact_label())
        self.system = self.add(card, self.combo())
        self.system_apply = self.add(card, self.button(tr("Apply system-wide…", "应用到整个系统…"), self.apply_system))
        self.add(card, panel.compact_label(tr(
            "Requires administrator authentication. Changes the default for future logins of all users; individual user settings take priority. Keyboard layout is configured separately.",
            "需要管理员认证。更改所有用户今后登录时的默认语言；个人设置仍优先。键盘布局在输入设置中单独配置。")))

        card = panel.card(self.form, tr("Available locales", "可用语言区域"))
        self.locale_note = self.add(card, panel.compact_label())
        self.add(card, panel.compact_label(tr(
            "Only generated locales can be selected. To add one, enable its UTF-8 entry in /etc/locale.gen and run sudo locale-gen, then refresh this page.",
            "只能选择已生成的语言区域。如需添加，请在 /etc/locale.gen 中启用对应 UTF-8 条目并运行 sudo locale-gen，然后刷新本页。")))
        self.refresh_button = self.add(self, self.button(tr("Refresh languages", "刷新语言列表"), self.refresh))
        self.form.set_sensitive(False)
        self.refresh()

    @staticmethod
    def add(parent, child):
        parent.pack_start(child, False, False, 0)
        return child

    @staticmethod
    def combo():
        combo = Gtk.ComboBoxText()
        combo.set_hexpand(True)
        for renderer in combo.get_cells():
            if isinstance(renderer, Gtk.CellRendererText):
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                renderer.set_property("max-width-chars", 36)
        return combo

    @staticmethod
    def button(title, callback):
        button = Gtk.Button(label=title)
        button.connect("clicked", lambda _: callback())
        return button

    def _work(self, task, complete):
        if self.busy:
            return
        self.busy = True
        self.form.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.notice.set_text(tr("Applying…", "正在应用…"))

        def done(result):
            self.busy = False
            self.form.set_sensitive(True)
            self.refresh_button.set_sensitive(True)
            complete(result)

        def failed(error):
            self.busy = False
            self.form.set_sensitive(True)
            self.refresh_button.set_sensitive(True)
            self.notice.set_text(tr("Could not apply language settings: ", "无法应用语言设置：") + str(error))

        self.panel.work(task, done, failed, commit=True)

    def refresh(self):
        def done(state):
            self.state = state
            locales = state["locales"]
            values = [backend.validate_locale(item, locales=locales) for item in locales]
            for combo, selected in ((self.session, state["session_locale"]), (self.system, state["system_locale"])):
                draft = combo.get_active_id()
                combo.remove_all()
                for value in values:
                    title = value
                    if value.startswith("zh_CN."):
                        title = tr("Chinese (China)", "中文（中国）") + " — " + value
                    elif value.startswith("en_US."):
                        title = tr("English (United States)", "英语（美国）") + " — " + value
                    combo.append(value, title)
                matching = next((value for value in values if backend._locale_key(value) == backend._locale_key(selected)), None)
                combo.set_active_id(draft if draft in values else matching or (values[0] if values else ""))
            self.session_current.set_text(tr("Current user default: ", "当前用户默认：") + state["session_locale"])
            self.system_current.set_text(tr("Current system default: ", "当前系统默认：") + state["system_locale"])
            self.session_apply.set_sensitive(bool(values))
            self.system_apply.set_sensitive(bool(values))
            self.ui.set_active_id(state["preferences"]["ui_language"])
            overrides = state.get("overrides", {})
            self.override_note.set_visible(bool(overrides))
            self.override_note.set_text(tr("Applying a user language clears inherited locale overrides for new applications: ",
                                          "应用用户语言会为新应用清除继承的语言覆盖项：") + ", ".join(overrides))
            missing = state.get("missing_common", [])
            self.locale_note.set_text((tr("Not generated: ", "尚未生成：") + ", ".join(missing)) if missing else
                                      tr("Chinese and English UTF-8 locales are available.", "中文和英文 UTF-8 语言区域均已就绪。"))
            self.notice.set_text(tr("Choose the scope, then apply your changes.", "选择更改范围后，点击对应的应用按钮。"))
        self._work(backend.read_state, done)

    def apply_ui(self):
        code = self.ui.get_active_id()
        if not code:
            return

        def done(preferences):
            set_language(preferences["ui_language"])
            self.notice.set_text(tr("Interface language updated.", "界面语言已更新。"))
            callback = getattr(self.panel, "language_changed", None)
            if callback:
                callback()
        self._work(lambda: backend.save_ui_language(code), done)

    def apply_session(self):
        locale = self.session.get_active_id()
        if not locale:
            return

        def done(result):
            self.session_current.set_text(tr("Current user default: ", "当前用户默认：") + result["locale"])
            self.notice.set_text(tr("Saved. Reopen terminals and applications to use the new language.",
                                    "已保存。重新打开终端和应用后将使用新语言。") +
                                 ("\n" + tr("Some session services could not be refreshed; sign out and back in. ",
                                             "部分会话服务未能刷新，请注销后重新登录。") + "\n".join(result["warnings"])
                                  if result.get("warnings") else ""))
            if result.get("preferences", {}).get("ui_language") == "system":
                set_language("system")
                callback = getattr(self.panel, "language_changed", None)
                if callback:
                    callback()
        self._work(lambda: backend.apply_session_locale(locale), done)

    def apply_system(self):
        locale = self.system.get_active_id()
        if not locale:
            return

        def done(result):
            self.system_current.set_text(tr("Current system default: ", "当前系统默认：") + result["locale"])
            self.notice.set_text(tr("System default saved. It takes effect at the next login.", "系统默认语言已保存，将在下次登录时生效。"))
        self._work(lambda: backend.apply_system_locale(locale), done)
