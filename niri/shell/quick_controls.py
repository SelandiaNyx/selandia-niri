"""Compact overview 2.0: live tiles with inline drill-down, media, sliders & eye-care."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk, Pango

from control_widgets import icon, icon_button, nyx_guide_banner, pack, style, text
from i18n import tr
from media_controls import MediaControls


def build_overview(panel):
    body = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14), "quick-overview")
    pack(body, nyx_guide_banner(
        "quick",
        tr("Master, press Ctrl+K anytime to jump straight to Wi-Fi, Bluetooth, Firewall, Processes, Docker or Night Light!",
           "主人，随时按 Ctrl+K 可直达 Wi-Fi、蓝牙、防火墙、进程管理、Docker 或护眼夜览；点击右侧小箭头即可进入详情页哦~"),
    ))

    wide_hero = panel.panel_width >= 650
    hero = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True,
                    row_homogeneous=wide_hero)
    hero.set_hexpand(True)
    hero.set_vexpand(False)
    hero.set_valign(Gtk.Align.START)
    pack(body, hero)
    panel.tiles = {}
    panel.tile_groups = {}
    panel.updating_tiles = False

    def tile(key, title, image, callback, details=None):
        group = style(Gtk.Box(), "quick-tile")
        group.set_hexpand(True)
        toggle = style(Gtk.ToggleButton(), "quick-toggle")
        toggle.set_tooltip_text(title)
        toggle.get_accessible().set_name(title)
        inner = Gtk.Box(spacing=10)
        toggle.add(inner)
        badge = style(Gtk.Box(), "quick-icon")
        badge.set_valign(Gtk.Align.CENTER)
        pack(badge, icon(image, 18))
        pack(inner, badge)
        labels = pack(inner, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), True)
        labels.set_valign(Gtk.Align.CENTER)
        title_label = pack(labels, text(title, "quick-title", 18))
        title_label.set_ellipsize(Pango.EllipsizeMode.NONE)
        title_label.set_line_wrap(True)
        title_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        state = pack(labels, text(tr("Checking…", "检测中…"), "quick-state", 20))
        toggle.set_sensitive(False)

        def changed(widget):
            if panel.updating_tiles:
                return
            context = group.get_style_context()
            (context.add_class if widget.get_active() else context.remove_class)("active")
            widget.set_sensitive(False)
            callback()

        toggle.connect("toggled", changed)
        pack(group, toggle, True)
        if details:
            action_cb = details if callable(details) else (lambda: panel.select_control_tab("network"))
            def _on_tile_button(_widget, event, cb=action_cb):
                if event.button == Gdk.BUTTON_SECONDARY:
                    cb()
                    return True
                return False
            toggle.connect("button-press-event", _on_tile_button)
            disclosure, _ = icon_button("pan-end-symbolic", tr(f"{title} settings", f"进入{title}设置"),
                                         action_cb, "quick-disclosure")
            pack(group, disclosure)
        panel.tiles[key] = (toggle, state)
        panel.tile_groups[key] = group
        return group

    # 3 equal-width columns on wide windows: 2x2 quick tiles + 1x2 Media card
    # so Media has the exact same column width as each quick tile and aligns flush.
    hero.attach(tile("wifi", tr("Wi-Fi", "无线网络"), "network-wireless-symbolic", panel.toggle_wifi,
                     lambda: panel.select_control_tab("network")), 0, 0, 1, 1)
    hero.attach(tile("bluetooth", tr("Bluetooth", "蓝牙"), "bluetooth-active-symbolic", panel.toggle_bluetooth,
                     lambda: panel.select_control_tab("bluetooth")), 1, 0, 1, 1)
    hero.attach(tile("dnd", tr("Do Not Disturb", "勿扰模式"), "notifications-disabled-symbolic", panel.toggle_dnd,
                     lambda: panel.select_control_tab("notifications")), 0, 1, 1, 1)
    hero.attach(tile("idle", tr("Stay awake", "保持唤醒"), "display-brightness-symbolic", panel.toggle_idle,
                     lambda: panel.select_control_tab("power")), 1, 1, 1, 1)

    panel.media_controls = MediaControls(panel)
    panel.media_controls.set_hexpand(True)
    if wide_hero:
        hero.attach(panel.media_controls, 2, 0, 1, 2)
    else:
        hero.attach(panel.media_controls, 0, 2, 2, 1)

    # Clickable live pulse strip -> jumps to Monitor & Processes
    pulse_btn = style(Gtk.Button(), "flat")
    pulse_btn.set_tooltip_text(tr("Open Monitor & Processes", "点击进入性能监控与进程管理"))
    pulse_btn.connect("clicked", lambda _: panel.select_control_tab("monitor"))
    pulse = style(Gtk.Box(spacing=14), "pulse-card")
    pulse_btn.add(pulse)
    pack(body, pulse_btn)
    panel.quick_pulse = {}
    for key, title in (("cpu", "CPU"), ("memory", "RAM"), ("network", "NET"), ("temp", "TEMP")):
        item = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), "pulse-item")
        item.get_style_context().add_class(f"pulse-{key}")
        pack(item, text(title, "pulse-label", 10))
        panel.quick_pulse[key] = pack(item, text("—", "pulse-value", 28))
        pack(pulse, item, True)

    sliders = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "quick-slider-card")
    pack(body, sliders)
    panel.scales, panel.scale_values, panel.mute_buttons = {}, {}, {}

    def slider(parent, key, title, image, device=None, details=None):
        group = pack(parent, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3))
        heading = pack(group, Gtk.Box(spacing=6))
        pack(heading, text(title, "quick-slider-label", 22), True)
        panel.scale_values[key] = pack(heading, text("—", "quick-slider-value", 9))
        if details:
            action, _ = icon_button("pan-end-symbolic", tr(f"{title} settings", f"{title}设置"),
                                    details, "quick-slider-action")
            pack(heading, action)
        row = pack(group, Gtk.Box(spacing=10))
        if device:
            mute, _ = icon_button(image, tr("Mute / Unmute", "静音 / 取消静音"),
                                  lambda: panel.action(["wpctl", "set-mute", device, "toggle"]), "quick-slider-icon")
            mute.set_sensitive(False)
            panel.mute_buttons[key] = mute
            pack(row, mute)
        else:
            badge = style(Gtk.Box(), "quick-slider-icon")
            pack(badge, icon(image))
            pack(row, badge)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_sensitive(False)
        scale.get_accessible().set_name(title)
        scale.connect("value-changed", panel.scale_changed, key)
        scale.connect("button-press-event", panel.scale_drag_start, key)
        scale.connect("button-release-event", panel.scale_drag_end, key)
        scale.connect("focus-out-event", panel.scale_drag_end, key)
        pack(row, scale, True)
        panel.scales[key] = scale

    slider(sliders, "volume", tr("Volume", "音量"), "audio-volume-high-symbolic", "@DEFAULT_AUDIO_SINK@",
           lambda: panel.select_control_tab("sound"))
    slider(sliders, "brightness", tr("Brightness", "亮度"), "display-brightness-symbolic",
           details=lambda: panel.select_control_tab("displays"))
    panel.brightness_summary = pack(sliders, text(tr("Detecting display", "正在检测屏幕"), "quick-slider-caption", 48))

    details = style(Gtk.ToggleButton(label=tr("⌄  More controls", "⌄  更多控制")), "quick-details")
    panel.quick_details_button = details
    panel.quick_details_revealer = Gtk.Revealer()
    panel.quick_details_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
    panel.quick_details_revealer.set_transition_duration(160)

    def toggle_details(widget):
        expanded = widget.get_active()
        panel.quick_details_revealer.set_reveal_child(expanded)
        widget.set_label(tr("⌃  Fewer controls", "⌃  收起") if expanded else tr("⌄  More controls", "⌄  更多控制"))

    details.connect("toggled", toggle_details)
    extra = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
    extra.set_margin_top(8)
    panel.quick_details_revealer.add(extra)
    pack(body, details)
    pack(body, panel.quick_details_revealer)
    pack(extra, text(tr("Brightness target", "调节亮度的屏幕"), "quick-slider-label", 28))
    panel.brightness_combo = panel.audio_combo()
    panel.brightness_combo.set_sensitive(False)
    panel.brightness_combo.connect("changed", panel.brightness_selected)
    pack(extra, panel.brightness_combo)
    panel.backlight_note = pack(extra, panel.compact_label())
    slider(extra, "microphone", tr("Microphone", "麦克风"), "audio-input-microphone-symbolic", "@DEFAULT_AUDIO_SOURCE@")
    pack(extra, text(tr("Power profile", "电源模式"), "quick-slider-label", 28))
    panel.profile_combo = Gtk.ComboBoxText()
    panel.profile_combo.set_sensitive(False)
    panel.profile_combo.connect("changed", panel.profile_changed)
    pack(extra, panel.profile_combo)
    panel.profile_note = pack(extra, panel.compact_label(tr("Checking…", "正在检测…")))
    utility = pack(extra, Gtk.Box(spacing=8))
    for title, name, callback in [
        (tr("Eye care & themes", "护眼与主题"), "preferences-desktop-appearance-symbolic", lambda: panel.select_control_tab("appearance")),
        (tr("Shortcuts", "快捷键"), "input-keyboard-symbolic", lambda: panel.launch_external([panel.desktop_script(), "shortcuts"])),
        (tr("AI sidebar", "AI 侧栏"), "system-search-symbolic", lambda: panel.launch_external([panel.desktop_script(), "ai"])),
        (tr("Refresh", "刷新"), "view-refresh-symbolic", panel.manual_refresh_control),
    ]:
        item, _ = icon_button(name, title, callback, "quick-utility", title)
        pack(utility, item, True)
        if name == "view-refresh-symbolic":
            panel.quick_refresh_button = item

    footer = pack(body, style(Gtk.Grid(column_spacing=8, row_spacing=8,
                                      column_homogeneous=True), "quick-footer"))
    for index, (title, name, callback) in enumerate([
        (tr("Screenshot", "截图"), "camera-photo-symbolic", lambda: panel.launch(["niri", "msg", "action", "screenshot"])),
        (tr("Notifications", "通知"), "preferences-system-notifications-symbolic", lambda: panel.launch_external(["swaync-client", "--skip-wait", "-t"])),
        (tr("Lock", "锁屏"), "system-lock-screen-symbolic", lambda: panel.desktop("lock")),
        (tr("Power", "电源"), "system-shutdown-symbolic", lambda: panel.desktop("power")),
    ]):
        item, _ = icon_button(name, title, callback, "quick-utility", title)
        item.set_hexpand(True)
        footer.attach(item, index % 2 if panel.panel_width < 650 else index,
                      index // 2 if panel.panel_width < 650 else 0, 1, 1)
        if name == "preferences-system-notifications-symbolic":
            panel.notification_button = item
        if name == "system-shutdown-symbolic":
            panel.power_button = item
            item.get_style_context().add_class("power-button")
    return body
