"""Appearance page: palette drafts, previews and transactional apply.

Mixed into ``panel.Panel``; methods rely on the panel's shared state
(``self.work``, ``self.feedback`` and the widgets built in ``__init__``).
"""
from __future__ import annotations

import subprocess

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk

from i18n import tr, tr_legacy
from page_host import PageEntry
from panel_motion import animations_enabled
from panel_motion import configure_stack
from panel_support import DESKTOP, box, button, capture, label, pack, scroller


class AppearancePage:
    def _build_appearance(self):
        from appearance import DEFAULTS, PRESETS, load_settings, preset_label
        self.appearance_busy = True
        body = box(spacing=12)
        self.appearance_body = body
        theme = self.card(body, tr("COLOR & THEME", "主题与配色"))
        pack(theme, label(tr("Apps & desktop", "应用与桌面"), "control-label"))
        self.color_mode_combo = Gtk.ComboBoxText()
        self.color_mode_combo.append("dark", tr_legacy("深色 · Dark"))
        self.color_mode_combo.append("light", tr_legacy("浅色 · Light"))
        pack(theme, self.color_mode_combo)
        self.theme_combo = Gtk.ComboBoxText()
        for key in PRESETS:
            self.theme_combo.append(key, preset_label(key))
        pack(theme, self.theme_combo)
        swatch_row = pack(theme, box(False, 8, "palette-preview"))
        self.palette_swatches = []
        for _ in range(5):
            chip = box(css="palette-swatch")
            chip.set_size_request(28, 18)
            provider = Gtk.CssProvider()
            chip.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            pack(swatch_row, chip)
            self.palette_swatches.append(provider)
        self.theme_combo.connect("changed", lambda *_: self._refresh_palette_preview())
        self.color_mode_combo.connect("changed", lambda *_: self._refresh_palette_preview())
        self.wallpaper_colors_check = Gtk.CheckButton(label=tr("Follow wallpaper colors", "主题配色跟随当前壁纸"))
        pack(theme, self.wallpaper_colors_check)
        self.wallpaper_colors_check.connect("toggled", lambda check: self.theme_combo.set_sensitive(not check.get_active()))
        pack(theme, self.compact_label(tr("Uses the image or project preview; keeps your chosen light/dark mode.", "根据图片或项目预览图取色；保留所选明暗模式。")))
        pack(theme, self.compact_label(tr_legacy("统一桌面配色，并同步 GTK / Qt 应用的明暗模式。\nShared desktop palette and matching GTK / Qt light or dark mode.")))
        self.reduced_motion_check = Gtk.CheckButton(label=tr_legacy("减少动态效果 · Reduce motion"))
        pack(theme, self.reduced_motion_check)
        opacity_row = pack(theme, box(False, 6))
        pack(opacity_row, label(tr_legacy("Surface opacity · 面板不透明度"), "control-label"), True)
        self.opacity_value = pack(opacity_row, label("", "value"))
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 1)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.connect("value-changed", lambda scale: self.opacity_value.set_text(f"{scale.get_value():.0f}%"))
        pack(theme, self.opacity_scale)
        pack(theme, self.compact_label(tr("20–100%. Below 40%, text edges and separators are strengthened; readability still depends on the wallpaper.",
                                         "可调 20–100%。低于 40% 会加强文字边缘和分隔线；可读性仍取决于壁纸。")))
        fonts = self.card(body, tr_legacy("FONTS  /  字体"))
        self.font_buttons = {}
        self.font_sizes = {}
        for key, title, minimum, maximum, unit in [
            ("font", tr_legacy("Interface · 界面字体"), 9, 20, "px"),
            ("mono_font", tr_legacy("Terminal · 终端字体"), 8, 24, "pt"),
        ]:
            pack(fonts, label(title, "control-label"))
            chooser = Gtk.FontButton()
            chooser.set_show_style(False)
            chooser.set_show_size(False)
            chooser.set_use_font(False)
            chooser.set_use_size(False)
            chooser.set_title(title)
            self.font_buttons[key] = pack(fonts, chooser)
            row = pack(fonts, box(False, 8))
            pack(row, label(tr(f"Size ({unit})", f"字号 ({unit})"), "hint"), True)
            size = Gtk.SpinButton.new_with_range(minimum, maximum, 0.5)
            size.set_digits(1)
            self.font_sizes[key] = pack(row, size)
        pack(fonts, self.compact_label(tr_legacy("Applies to this desktop's components. Existing terminals use the new font when reopened.\n应用于本桌面组件；已有终端重新打开后使用新字体。")))
        actions = pack(body, box(False, 8))
        self.appearance_apply = pack(actions, button(tr_legacy("Apply · 应用设置"), self.apply_appearance, "accent-button"), True)
        self.appearance_reset = pack(actions, button(tr_legacy("Defaults · 恢复默认"), lambda: self.apply_appearance(reset=True)), True)
        pack(body, self.compact_label(tr_legacy("Preferences are saved locally when you Apply.\n偏好保存在本地，选好主题与字体后点击应用。")))
        self.populate_appearance(DEFAULTS)
        body.set_sensitive(False)

        def loaded(settings):
            self.populate_appearance(settings)
            self.apply_local_appearance(settings)
            self.appearance_busy = False
            body.set_sensitive(True)

        def failed(error):
            self.appearance_busy = False
            body.set_sensitive(True)
            self.feedback(tr("Could not load appearance: ", "无法加载外观设置：") + str(error), True)
        self.work(load_settings, loaded, failed)
        return PageEntry(body, scroller(body))

    def populate_appearance(self, settings):
        self.wallpaper_colors_check.set_active(settings.get("wallpaper_colors", False))
        self.color_mode_combo.set_active_id(settings.get("color_mode", "dark"))
        self.reduced_motion_check.set_active(settings.get("reduced_motion", False))
        self.theme_combo.set_active_id(settings["preset"])
        self._refresh_palette_preview()
        self.opacity_scale.set_value(settings["opacity"] * 100)
        installed = getattr(self, "_installed_fonts", None)
        if installed is None:
            installed = {family.get_name() for family in self.get_pango_context().list_families()}
            self._installed_fonts = installed
        for key, size_key in [("font", "font_size"), ("mono_font", "mono_size")]:
            requested = settings[key]
            fallbacks = ("Noto Sans CJK SC", "Noto Sans", "Sans") if key == "font" else ("JetBrainsMono Nerd Font", "Monospace")
            selected = requested if requested in installed else next((name for name in fallbacks if name in installed), fallbacks[-1])
            self.font_buttons[key].set_font(f"{selected} {settings[size_key]}")
            self.font_buttons[key].set_tooltip_text(
                None if selected == requested else tr(f"{requested} is unavailable; using {selected}", f"未安装 {requested}；已选择 {selected}"))
            self.font_sizes[key].set_value(settings[size_key])

    def _refresh_palette_preview(self):
        swatches = getattr(self, "palette_swatches", None)
        if not swatches:
            return
        from appearance import DEFAULTS, palette
        preset = self.theme_combo.get_active_id() or DEFAULTS["preset"]
        mode = self.color_mode_combo.get_active_id() or "dark"
        colors = palette({"preset": preset, "color_mode": mode})
        keys = ("background", "surface_raised", "accent", "secondary", "ink")
        for provider, key in zip(swatches, keys):
            color = colors.get(key, "#5ee7ff")
            provider.load_from_data(
                f"box.palette-swatch {{ background-color: {color}; border-radius: 999px; "
                f"border: 1px solid rgba(255, 255, 255, 0.25); }}".encode()
            )

    def draft_appearance(self):
        return {
            "wallpaper_colors": self.wallpaper_colors_check.get_active(),
            "color_mode": self.color_mode_combo.get_active_id(),
            "reduced_motion": self.reduced_motion_check.get_active(),
            "preset": self.theme_combo.get_active_id(),
            "font": self.font_buttons["font"].get_font_desc().get_family(),
            "font_size": self.font_sizes["font"].get_value(),
            "mono_font": self.font_buttons["mono_font"].get_font_desc().get_family(),
            "mono_size": self.font_sizes["mono_font"].get_value(),
            "opacity": self.opacity_scale.get_value() / 100,
        }

    def apply_local_appearance(self, settings):
        self.reduced_motion = settings.get("reduced_motion", False)
        self.get_settings().set_property("gtk-application-prefer-dark-theme", settings.get("color_mode", "dark") == "dark")
        configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
        revealer = getattr(self, "quick_details_revealer", None)
        if revealer is not None:
            revealer.set_transition_duration(
                180 if animations_enabled(self.surface, not self.reduced_motion) else 0)
        context = self.get_style_context()
        (context.add_class if not animations_enabled(self.surface, not self.reduced_motion)
         else context.remove_class)("reduce-motion")

    def apply_appearance(self, reset=False):
        if self.appearance_busy:
            return
        from appearance import apply_settings, restore_defaults
        from application_theme import apply_mode
        settings = self.draft_appearance()
        self.appearance_busy = True
        self.appearance_body.set_sensitive(False)
        self.feedback(tr_legacy("Applying appearance… · 正在应用外观…"))

        def apply():
            from wallpaper import with_wallpaper_colors
            result = restore_defaults() if reset else apply_settings(with_wallpaper_colors(settings))
            errors = []
            try:
                report = apply_mode(result)
                errors.extend(report.get("warnings", []))
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(tr("Application theme: ", "应用主题：") + str(error))
            try:
                capture([DESKTOP, "theme-reload"], timeout=20)
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                errors.append(str(error))
            return result, "; ".join(errors) or None

        def done(result):
            settings, reload_error = result
            self.appearance_busy = False
            self.appearance_body.set_sensitive(True)
            self.populate_appearance(settings)
            self.apply_local_appearance(settings)
            try:
                self.get_application().reload_theme()
            except (GLib.Error, OSError) as error:
                reload_error = str(error)
            if reload_error:
                self.feedback(tr("Saved with issues: ", "已保存，部分设置未生效：") + reload_error, True)
            else:
                self.feedback(tr_legacy("外观已同步；部分应用需重新打开。\nAppearance synced; some apps need reopening."))

        def failed(error):
            self.appearance_busy = False
            self.appearance_body.set_sensitive(True)
            self.feedback(tr("Could not apply appearance: ", "无法应用外观：") + str(error), True)
        self.work(apply, done, failed, commit=True)
