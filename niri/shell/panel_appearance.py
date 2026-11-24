"""Appearance & Eye-Care page 2.0: visual preset grid, eye-care warmth & Gemini mascot skins."""
from __future__ import annotations

import subprocess

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GLib, Gtk

from control_widgets import (
    StickyActionBar,
    card_grid,
    grid_add,
    nyx_guide_banner,
    pack,
    setting_row,
    style,
    wrap_label,
)
from i18n import tr, tr_legacy
from page_host import PageEntry
from panel_motion import animations_enabled, configure_stack
from panel_support import DESKTOP, box, capture, label, scroller


class AppearancePage:
    def _build_appearance(self):
        from appearance import DEFAULTS, EYE_CARE_MODES, MASCOT_SKINS, PRESETS, load_settings, preset_label
        self.appearance_busy = True
        self._appearance_guard = False
        self._saved_appearance = dict(DEFAULTS)

        wrapper = box(spacing=10)
        body = box(spacing=12)
        self.appearance_body = body

        pack(body, nyx_guide_banner(
            "appearance",
            tr("Pick an anime MD3 theme, switch between 4 Gemini cat-girl forms, and tune eye-care warmth & typography.",
               "点击卡片即可切换二次元 MD3 主题，支持 4 种 Gemini 猫娘立绘形态与三档护眼暖色模式，选完点击底栏「应用设置」生效。"),
        ))

        wide = getattr(self, "panel_width", 1200) >= 1040
        grid = pack(body, card_grid(wide, 12))

        # Left column: Visual Preset Grid + Mode & Eye Care
        theme = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(theme, label(tr("ANIME & MD3 THEMES", "动漫主题与护眼模式"), "section-title"))

        mode_row = pack(theme, Gtk.Box(spacing=8))
        self.color_mode_combo = Gtk.ComboBoxText()
        self.color_mode_combo.append("dark", tr("Dark mode", "深色护眼"))
        self.color_mode_combo.append("light", tr("Light paper", "浅色柔纸"))
        pack(mode_row, self.color_mode_combo, True)

        self.eye_care_combo = Gtk.ComboBoxText()
        for key, (en, zh) in EYE_CARE_MODES.items():
            self.eye_care_combo.append(key, tr(en, zh))
        pack(mode_row, self.eye_care_combo, True)

        # Keep theme_combo synced for compatibility while showing the visual card grid.
        self.theme_combo = Gtk.ComboBoxText()
        for key in PRESETS:
            self.theme_combo.append(key, preset_label(key))
        self.theme_combo.set_no_show_all(True)
        self.theme_combo.hide()
        pack(theme, self.theme_combo)

        # Visual clickable preset cards (compact 2-col FlowBox)
        self.preset_buttons = {}
        preset_flow = Gtk.FlowBox()
        preset_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        preset_flow.set_min_children_per_line(2)
        preset_flow.set_max_children_per_line(3 if wide else 2)
        preset_flow.set_column_spacing(6)
        preset_flow.set_row_spacing(6)
        for key in PRESETS:
            btn = style(Gtk.ToggleButton(), "preset-card")
            inner = Gtk.Box(spacing=6)
            dot = Gtk.Box()
            dot.set_size_request(14, 14)
            dot.set_valign(Gtk.Align.CENTER)
            prov = Gtk.CssProvider()
            p_accent = PRESETS[key]["accent"]
            p_sec = PRESETS[key]["secondary"]
            prov.load_from_data(
                f"box {{ background-image: linear-gradient(135deg, {p_accent}, {p_sec}); border-radius: 999px; }}".encode()
            )
            dot.get_style_context().add_provider(prov, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            pack(inner, dot)
            pack(inner, Gtk.Label(label=preset_label(key), xalign=0), True)
            btn.add(inner)
            btn.connect("toggled", self._on_preset_card_toggled, key)
            self.preset_buttons[key] = btn
            preset_flow.add(btn)
        pack(theme, preset_flow)

        swatch_row = pack(theme, box(False, 8, "palette-preview"))
        self.palette_swatches = []
        for _ in range(5):
            chip = box(css="palette-swatch")
            chip.set_size_request(30, 18)
            provider = Gtk.CssProvider()
            chip.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            pack(swatch_row, chip)
            self.palette_swatches.append(provider)

        self.theme_combo.connect("changed", self._on_appearance_changed)
        self.color_mode_combo.connect("changed", self._on_appearance_changed)
        self.eye_care_combo.connect("changed", self._on_appearance_changed)

        self.wallpaper_colors_check = Gtk.CheckButton(label=tr("Follow wallpaper colors", "主题配色跟随当前壁纸"))
        pack(theme, self.wallpaper_colors_check)
        self.wallpaper_colors_check.connect("toggled", self._on_wallpaper_color_toggled)
        grid_add(grid, theme)

        # Right column: Mascot Skin + Surface/Motion + Fonts
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        mascot_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(mascot_card, label(tr("GEMINI MASCOT & SURFACE", "看板娘形态与表面质感"), "section-title"))
        self.mascot_combo = Gtk.ComboBoxText()
        for key, (en, zh) in MASCOT_SKINS.items():
            self.mascot_combo.append(key, tr(en, zh))
        self.mascot_combo.connect("changed", self._on_mascot_changed)
        pack(mascot_card, setting_row(tr("Gemini mascot form", "Gemini 猫娘立绘形态"), self.mascot_combo,
                                      tr("Updates sidebar artwork and launcher avatar immediately", "切换侧栏立绘与顶栏头像形态")))

        self.reduced_motion_check = Gtk.CheckButton(label=tr("Reduce motion & transitions", "减少动态与过渡效果"))
        self.reduced_motion_check.connect("toggled", self._on_appearance_changed)
        pack(mascot_card, self.reduced_motion_check)

        opacity_row = pack(mascot_card, box(False, 6))
        pack(opacity_row, label(tr("Surface opacity", "面板不透明度"), "control-label"), True)
        self.opacity_value = pack(opacity_row, label("", "value"))
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 20, 100, 1)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.connect("value-changed", self._on_opacity_changed)
        pack(mascot_card, self.opacity_scale)
        pack(mascot_card, wrap_label(tr("Recommended 90–100% for crisp eye-care legibility.",
                                        "建议保持 90–100% 以获得最清晰护眼的文字对比度。"), "hint"))
        pack(right, mascot_card)

        fonts = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(fonts, label(tr("TYPOGRAPHY", "字体与清晰度"), "section-title"))
        self.font_buttons = {}
        self.font_sizes = {}
        for key, title, minimum, maximum, unit in [
            ("font", tr("Interface font", "界面字体"), 9, 20, "px"),
            ("mono_font", tr("Terminal monospace", "终端等宽字体"), 8, 24, "pt"),
        ]:
            chooser = Gtk.FontButton()
            chooser.set_show_style(False)
            chooser.set_show_size(False)
            chooser.set_use_font(False)
            chooser.set_use_size(False)
            chooser.set_title(title)
            chooser.connect("font-set", self._on_appearance_changed)
            self.font_buttons[key] = chooser
            pack(fonts, setting_row(title, chooser))
            size_spin = Gtk.SpinButton.new_with_range(minimum, maximum, 0.5)
            size_spin.set_digits(1)
            size_spin.connect("value-changed", self._on_appearance_changed)
            self.font_sizes[key] = size_spin
            pack(fonts, setting_row(tr(f"{title} size ({unit})", f"{title}字号（{unit}）"), size_spin))
        pack(right, fonts)
        grid_add(grid, right)

        pack(wrapper, scroller(body), True)
        self.appearance_bar = StickyActionBar(
            on_apply=self.apply_appearance,
            on_discard=lambda: self.populate_appearance(self._saved_appearance),
            on_defaults=lambda: self.apply_appearance(reset=True),
            apply_label=tr("Apply appearance", "应用外观设置"),
        )
        self.appearance_apply = self.appearance_bar.apply_btn
        self.appearance_reset = self.appearance_bar.defaults_btn
        pack(wrapper, self.appearance_bar)

        self.populate_appearance(DEFAULTS)

        def loaded(settings):
            self._saved_appearance = dict(settings)
            self.populate_appearance(settings)
            self.apply_local_appearance(settings)
            self.appearance_busy = False

        def failed(error):
            self.appearance_busy = False
            self.feedback(tr("Could not load appearance: ", "无法加载外观设置：") + str(error), True)

        self.work(load_settings, loaded, failed)
        return PageEntry(body, wrapper)

    def _on_preset_card_toggled(self, btn, key):
        if self._appearance_guard or not btn.get_active():
            return
        self.theme_combo.set_active_id(key)

    def _on_wallpaper_color_toggled(self, check):
        self.theme_combo.set_sensitive(not check.get_active())
        self._on_appearance_changed()

    def _on_mascot_changed(self, *_):
        if self._appearance_guard:
            return
        skin = self.mascot_combo.get_active_id() or "gemini"
        if getattr(self, "navigation", None) is not None:
            self.navigation.refresh_mascot(skin)
        self._on_appearance_changed()

    def _on_opacity_changed(self, scale):
        self.opacity_value.set_text(f"{scale.get_value():.0f}%")
        self._on_appearance_changed()

    def _on_appearance_changed(self, *_):
        if self._appearance_guard:
            return
        self._sync_preset_cards()
        self._refresh_palette_preview()
        bar = getattr(self, "appearance_bar", None)
        if bar is not None:
            bar.set_dirty(self.draft_appearance() != {k: self._saved_appearance.get(k) for k in self.draft_appearance()})

    def _sync_preset_cards(self):
        active = self.theme_combo.get_active_id()
        prev = self._appearance_guard
        self._appearance_guard = True
        for key, btn in getattr(self, "preset_buttons", {}).items():
            on = key == active
            btn.set_active(on)
            ctx = btn.get_style_context()
            (ctx.add_class if on else ctx.remove_class)("active")
        self._appearance_guard = prev

    def populate_appearance(self, settings):
        self._appearance_guard = True
        self.wallpaper_colors_check.set_active(settings.get("wallpaper_colors", False))
        self.color_mode_combo.set_active_id(settings.get("color_mode", "dark"))
        self.eye_care_combo.set_active_id(settings.get("eye_care", "comfort"))
        self.mascot_combo.set_active_id(settings.get("mascot", "gemini"))
        self.reduced_motion_check.set_active(settings.get("reduced_motion", False))
        self.theme_combo.set_active_id(settings["preset"])
        self.theme_combo.set_sensitive(not self.wallpaper_colors_check.get_active())
        self.opacity_scale.set_value(settings["opacity"] * 100)
        self.opacity_value.set_text(f"{settings['opacity'] * 100:.0f}%")
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
        self._appearance_guard = False
        self._sync_preset_cards()
        self._refresh_palette_preview()
        if getattr(self, "appearance_bar", None) is not None:
            self.appearance_bar.set_dirty(False)

    def _refresh_palette_preview(self):
        swatches = getattr(self, "palette_swatches", None)
        if not swatches:
            return
        from appearance import DEFAULTS, palette
        preset = self.theme_combo.get_active_id() or DEFAULTS["preset"]
        mode = self.color_mode_combo.get_active_id() or "dark"
        eye_care = self.eye_care_combo.get_active_id() or "comfort"
        req = {
            "preset": preset, "color_mode": mode, "eye_care": eye_care,
            "wallpaper_colors": self.wallpaper_colors_check.get_active(),
            "wallpaper_seed": self._saved_appearance.get("wallpaper_seed"),
        }
        colors = palette(req)
        keys = ("background", "surface_raised", "accent", "secondary", "ink")
        for provider, key in zip(swatches, keys):
            color = colors.get(key, "#9da8ff")
            provider.load_from_data(
                f"box.palette-swatch {{ background-color: {color}; border-radius: 999px; "
                f"border: 1px solid rgba(255, 255, 255, 0.25); }}".encode()
            )

    def draft_appearance(self):
        return {
            "wallpaper_colors": self.wallpaper_colors_check.get_active(),
            "color_mode": self.color_mode_combo.get_active_id(),
            "eye_care": self.eye_care_combo.get_active_id() or "comfort",
            "mascot": self.mascot_combo.get_active_id() or "gemini",
            "reduced_motion": self.reduced_motion_check.get_active(),
            "preset": self.theme_combo.get_active_id(),
            "font": self.font_buttons["font"].get_font_desc().get_family(),
            "font_size": self.font_sizes["font"].get_value(),
            "mono_font": self.font_buttons["mono_font"].get_font_desc().get_family(),
            "mono_size": self.font_sizes["mono_font"].get_value(),
            "opacity": round(self.opacity_scale.get_value() / 100, 2),
        }

    def apply_local_appearance(self, settings):
        self.reduced_motion = settings.get("reduced_motion", False)
        self.get_settings().set_property("gtk-application-prefer-dark-theme", settings.get("color_mode", "dark") == "dark")
        configure_stack(self.control_stack, enabled=lambda: not self.reduced_motion)
        revealer = getattr(self, "quick_details_revealer", None)
        if revealer is not None:
            revealer.set_transition_duration(
                160 if animations_enabled(self.surface, not self.reduced_motion) else 0)
        context = self.get_style_context()
        (context.add_class if not animations_enabled(self.surface, not self.reduced_motion)
         else context.remove_class)("reduce-motion")
        if getattr(self, "navigation", None) is not None:
            self.navigation.refresh_mascot(settings.get("mascot", "gemini"))
        if hasattr(self, "refresh_header_avatar"):
            self.refresh_header_avatar(settings.get("mascot", "gemini"))

    def apply_appearance(self, reset=False):
        if self.appearance_busy:
            return
        from appearance import apply_settings, restore_defaults
        from application_theme import apply_mode
        settings = self.draft_appearance()
        self.appearance_busy = True
        if self.appearance_apply:
            self.appearance_apply.set_sensitive(False)
        self.feedback(tr("Applying appearance & eye-care theme…", "正在应用外观与护眼主题…"))

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
            if self.appearance_apply:
                self.appearance_apply.set_sensitive(True)
            self._saved_appearance = dict(settings)
            self.populate_appearance(settings)
            self.apply_local_appearance(settings)
            try:
                self.get_application().reload_theme()
            except (GLib.Error, OSError) as error:
                reload_error = str(error)
            if reload_error:
                self.feedback(tr("Saved with issues: ", "已保存，部分设置未生效：") + reload_error, True)
            else:
                self.feedback(tr("Appearance synced across desktop, bar & applications.",
                                 "外观与护眼配色已同步至桌面、顶栏与系统应用。"))

        def failed(error):
            self.appearance_busy = False
            if self.appearance_apply:
                self.appearance_apply.set_sensitive(True)
            self.feedback(tr("Could not apply appearance: ", "无法应用外观：") + str(error), True)

        self.work(apply, done, failed, commit=True)
