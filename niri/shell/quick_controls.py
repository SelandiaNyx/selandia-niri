"""Compact overview: connectivity, independent media, sliders and clear actions."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from control_widgets import icon, icon_button, pack, style, text
from media_controls import MediaControls
from i18n import tr


def build_overview(panel):
    body = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "quick-overview")
    hero = Gtk.Grid(column_spacing=12, row_spacing=10, column_homogeneous=True)
    pack(body, hero)
    panel.tiles = {}
    panel.tile_groups = {}
    panel.updating_tiles = False

    def tile(key, title, image, callback, details=None):
        group = style(Gtk.Box(), "quick-tile")
        toggle = style(Gtk.ToggleButton(), "quick-toggle")
        toggle.set_tooltip_text(title)
        toggle.get_accessible().set_name(title)
        inner = Gtk.Box(spacing=10)
        toggle.add(inner)
        badge = style(Gtk.Box(), "quick-icon")
        badge.set_valign(Gtk.Align.CENTER)
        pack(badge, icon(image, 20))
        pack(inner, badge)
        labels = pack(inner, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3), True)
        pack(labels, text(title, "quick-title", 12))
        state = pack(labels, text(tr("Checking…", "检测中…"), "quick-state", 14))
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
            disclosure, _ = icon_button("pan-end-symbolic", tr(f"{title} details", f"{title}详情"),
                                         lambda: panel.show_connection_details(key, disclosure), "quick-disclosure")
            pack(group, disclosure)
        panel.tiles[key] = (toggle, state)
        panel.tile_groups[key] = group
        return group

    hero.attach(tile("wifi", tr("Wi-Fi", "无线网络"), "network-wireless-symbolic", panel.toggle_wifi,
                     lambda: panel.desktop("launch", "network")), 0, 0, 1, 1)
    hero.attach(tile("bluetooth", tr("Bluetooth", "蓝牙"), "bluetooth-active-symbolic", panel.toggle_bluetooth,
                     lambda: panel.desktop("launch", "bluetooth")), 0, 1, 1, 1)
    panel.media_controls = MediaControls(panel)
    hero.attach(panel.media_controls, 1, 0, 1, 2)
    toggles = pack(body, Gtk.Box(spacing=12))
    pack(toggles, tile("dnd", tr("Do Not Disturb", "勿扰模式"), "notifications-disabled-symbolic", panel.toggle_dnd), True)
    pack(toggles, tile("idle", tr("Stay awake", "保持唤醒"), "display-brightness-symbolic", panel.toggle_idle), True)

    sliders = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "quick-slider-card")
    pack(body, sliders)
    panel.scales, panel.scale_values, panel.mute_buttons = {}, {}, {}

    def slider(parent, key, title, image, device=None, details=None):
        group = pack(parent, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3))
        heading = pack(group, Gtk.Box(spacing=6))
        pack(heading, text(title, "quick-slider-label"), True)
        panel.scale_values[key] = pack(heading, text("—", "quick-slider-value", 7))
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
        if details:
            more, _ = icon_button("pan-end-symbolic", tr(f"{title} settings", f"{title}设置"), details, "quick-disclosure")
            pack(row, more)

    slider(sliders, "volume", tr("Volume", "音量"), "audio-volume-high-symbolic", "@DEFAULT_AUDIO_SINK@",
           lambda: panel.select_control_tab("sound"))
    slider(sliders, "brightness", tr("Brightness", "亮度"), "display-brightness-symbolic", details=lambda: panel.select_control_tab("displays"))
    panel.brightness_summary = pack(sliders, text(tr("Detecting display", "正在检测屏幕"), "quick-slider-caption", 42))

    details = style(Gtk.ToggleButton(label=tr("⌄  More controls", "⌄  更多控制")), "quick-details")
    panel.quick_details_button = details
    panel.quick_details_revealer = Gtk.Revealer()
    panel.quick_details_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
    panel.quick_details_revealer.set_transition_duration(180)
    def toggle_details(widget):
        expanded = widget.get_active()
        panel.quick_details_revealer.set_reveal_child(expanded)
        widget.set_label(tr("⌃  Fewer controls", "⌃  收起") if expanded else tr("⌄  More controls", "⌄  更多控制"))
    details.connect("toggled", toggle_details)
    extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    extra.set_margin_top(10)
    panel.quick_details_revealer.add(extra)
    pack(body, details)
    pack(body, panel.quick_details_revealer)
    pack(extra, text(tr("Brightness target", "调节亮度的屏幕"), "quick-slider-label"))
    panel.brightness_combo = panel.audio_combo()
    panel.brightness_combo.set_sensitive(False)
    panel.brightness_combo.connect("changed", panel.brightness_selected)
    pack(extra, panel.brightness_combo)
    panel.backlight_note = pack(extra, panel.compact_label())
    slider(extra, "microphone", tr("Microphone", "麦克风"), "audio-input-microphone-symbolic", "@DEFAULT_AUDIO_SOURCE@")
    pack(extra, text(tr("Power profile", "电源模式"), "quick-slider-label"))
    panel.profile_combo = Gtk.ComboBoxText()
    panel.profile_combo.set_sensitive(False)
    panel.profile_combo.connect("changed", panel.profile_changed)
    pack(extra, panel.profile_combo)
    panel.profile_note = pack(extra, panel.compact_label(tr("Checking…", "正在检测…")))
    utility = pack(extra, Gtk.Box(spacing=8))
    for title, name, callback in [
        (tr("Shortcuts", "快捷键"), "input-keyboard-symbolic", lambda: panel.desktop("shortcuts")),
        (tr("AI sidebar", "AI 侧栏"), "system-search-symbolic", lambda: panel.desktop("ai")),
        (tr("Refresh", "刷新"), "view-refresh-symbolic", panel.refresh_control),
    ]:
        item, _ = icon_button(name, title, callback, "quick-utility", title)
        pack(utility, item, True)

    footer = pack(body, style(Gtk.Box(spacing=8), "quick-footer"))
    for title, name, callback in [
        (tr("Screenshot", "截图"), "camera-photo-symbolic", lambda: panel.launch(["niri", "msg", "action", "screenshot"])),
        (tr("Notifications", "通知"), "preferences-system-notifications-symbolic", lambda: panel.launch(["swaync-client", "--skip-wait", "-t"])),
        (tr("Lock", "锁屏"), "system-lock-screen-symbolic", lambda: panel.desktop("lock")),
        (tr("Power", "电源"), "system-shutdown-symbolic", lambda: panel.desktop("power")),
    ]:
        item, _ = icon_button(name, title, callback, "quick-utility", title)
        pack(footer, item, True)
        if name == "preferences-system-notifications-symbolic":
            panel.notification_button = item
        if name == "system-shutdown-symbolic":
            panel.power_button = item
            item.get_style_context().add_class("power-button")
    return body
