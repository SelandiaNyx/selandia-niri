"""Sound page: devices, ports, profiles, streams and the live level tick.

Mixed into ``panel.Panel``; methods rely on the panel's shared state
(``self.work``, ``self.feedback`` and the widgets built in ``__init__``).
"""
from __future__ import annotations

import threading
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, Pango

from i18n import tr, tr_legacy
from page_host import PageEntry
from panel_support import box, button, label, pack, scroller


class AudioPage:
    @staticmethod
    def audio_placeholder(combo, text):
        """Show what the disabled combo is waiting for instead of a blank row."""
        combo.append("", tr_legacy(text))
        combo.set_active(0)

    def audio_combo(self):
        combo = Gtk.ComboBoxText()
        combo._audio_rows = ()
        for renderer in combo.get_cells():
            if isinstance(renderer, Gtk.CellRendererText):
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                renderer.set_property("max-width-chars", 25)
        combo.connect("notify::popup-shown", self.audio_popup_changed)
        return combo

    def audio_popup_changed(self, combo, _property):
        if combo.get_property("popup-shown") or not self.alive:
            return
        # GTK can still be dispatching the selection event as the popup closes.
        # Apply the latest snapshot on the next loop turn, after that selection.
        def finish():
            self.pending.discard(source)
            if self.alive and self.audio_deferred_state is not None:
                state = self.audio_deferred_state
                self.audio_deferred_state = None
                self.apply_audio(state)
            return GLib.SOURCE_REMOVE
        source = GLib.idle_add(finish)
        self.pending.add(source)

    @staticmethod
    def audio_set_choices(combo, rows, preferred=None, fallback=None):
        rows = tuple(rows)
        selected = preferred if preferred is not None else combo.get_active_id()
        names = {name for name, _title in rows}
        if selected not in names:
            selected = fallback if fallback in names else (rows[0][0] if rows else None)
        if combo._audio_rows != rows:
            combo.remove_all()
            for name, title in rows:
                combo.append(name, title)
            combo._audio_rows = rows
        if combo.get_active_id() != selected:
            if selected is None:
                combo.set_active(-1)
            else:
                combo.set_active_id(selected)
        combo.set_sensitive(bool(rows))

    @staticmethod
    def audio_device_title(device):
        title = device.get("description") or device["name"]
        if device.get("availability") == "unavailable":
            title += tr(" · Disconnected", " · 未连接")
        elif device.get("kind") == "monitor":
            title += tr(" · Monitor", " · 回录")
        elif device.get("kind") == "virtual":
            title += tr(" · Virtual", " · 虚拟")
        elif device.get("kind") == "pro":
            title += tr(" · Pro channel", " · 专业通道")
        return title

    def _build_sound(self):
        self.audio_state = {}
        self.audio_busy = False
        self.audio_loading = False
        self.audio_updating = False
        self.audio_generation = 0
        self.audio_timers = {}
        self.audio_dragging = set()
        self.audio_profile_dirty = False
        self.audio_deferred_state = None
        self.audio_devices = {}
        self.audio_ports = {}
        self.audio_volumes = {}
        self.audio_values = {}
        self.audio_mutes = {}
        self.audio_device_apply = {}
        self.audio_port_apply = {}
        self.audio_device_notes = {}
        self.audio_port_devices = {}
        self.audio_port_rows = {}
        body = box(spacing=12)
        self.audio_status = pack(body, self.compact_label(tr_legacy("Reading audio devices… · 读取音频设备…")))
        # The connected status is normally two lines; reserve that height so the
        # cards below do not jump when the first read replaces the placeholder.
        self.audio_status.set_lines(2)
        from application_audio import ApplicationAudioControls
        self.application_audio = pack(body, ApplicationAudioControls(self))
        self.audio_advanced = Gtk.CheckButton.new_with_label(tr_legacy("显示高级通道 · Show all audio channels"))
        self.audio_advanced.set_tooltip_text(tr_legacy("包括未连接接口、专业通道、虚拟设备与回录通道。\nIncludes disconnected ports, Pro Audio, virtual and monitor channels."))
        self.audio_advanced.connect("toggled", self.audio_advanced_changed)
        pack(body, self.audio_advanced)
        self.audio_controls = pack(body, box(spacing=12))
        for kind, heading in [("sink", tr_legacy("OUTPUT  /  输出设备")), ("source", tr_legacy("INPUT  /  输入设备"))]:
            card = self.card(self.audio_controls, heading)
            combo = self.audio_combo()
            self.audio_placeholder(combo, "Detecting audio devices… · 正在检测音频设备…")
            self.audio_devices[kind] = pack(card, combo)
            combo.connect("changed", self.audio_device_changed, kind)
            selection = pack(card, box(False, 8))
            self.audio_device_notes[kind] = pack(selection, self.compact_label(), True)
            self.audio_device_apply[kind] = pack(selection, button(tr_legacy("使用 · Use"),
                lambda k=kind: self.audio_use_device(k), "small-button", tr_legacy("设为默认设备 · Use as default")))
            row = pack(card, box(False, 8))
            self.audio_values[kind] = pack(row, label("—", "value"), True)
            self.audio_mutes[kind] = pack(row, button(tr_legacy("Mute · 静音"), lambda k=kind: self.audio_toggle_mute(k), "small-button"))
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
            scale.set_draw_value(False)
            scale.connect("value-changed", self.audio_volume_changed, kind)
            scale.connect("button-press-event", lambda _w, _e, k=kind: self.audio_dragging.add(k) or False)
            scale.connect("button-release-event", lambda _w, _e, k=kind: self.audio_dragging.discard(k) or False)
            scale.connect("focus-out-event", lambda _w, _e, k=kind: self.audio_dragging.discard(k) or False)
            self.audio_volumes[kind] = pack(card, scale)
            port_row = pack(card, box(spacing=6))
            port_row.set_no_show_all(True)
            self.audio_port_rows[kind] = port_row
            pack(port_row, label(tr_legacy("Port · 接口"), "hint"))
            ports = self.audio_combo()
            self.audio_ports[kind] = pack(port_row, ports)
            ports.connect("changed", self.audio_port_changed, kind)
            self.audio_port_apply[kind] = pack(port_row, button(tr_legacy("应用接口 · Apply port"),
                lambda k=kind: self.audio_apply_port(k), "small-button"))
            for child in port_row.get_children():
                child.show_all()
            pack(card, button(tr_legacy("Route active apps here · 将运行中的应用切换至此"),
                              lambda k=kind: self.audio_move_streams(k), "small-button"))
        profiles = self.card(self.audio_controls, tr_legacy("DEVICE PROFILE  /  声卡模式"))
        self.audio_card_combo = self.audio_combo()
        self.audio_profile_combo = self.audio_combo()
        self.audio_placeholder(self.audio_card_combo, "Detecting sound cards… · 正在检测声卡…")
        self.audio_placeholder(self.audio_profile_combo, "Detecting profiles… · 正在检测配置…")
        pack(profiles, self.audio_card_combo)
        pack(profiles, self.audio_profile_combo)
        self.audio_card_combo.connect("changed", self.audio_card_changed)
        self.audio_profile_combo.connect("changed", self.audio_profile_changed)
        self.audio_profile_apply = pack(profiles, button(tr_legacy("Apply profile · 应用设备配置"), self.audio_apply_profile))
        self.audio_profile_recommend = pack(profiles, button(tr_legacy("使用推荐桌面模式 · Use desktop profile"),
            self.audio_apply_recommended_profile, "accent-button"))
        self.audio_profile_recommend.set_no_show_all(True)
        self.audio_profile_note = pack(profiles, self.compact_label())
        pack(profiles, self.compact_label(tr_legacy("模式决定模拟、数字或蓝牙连接；Off 会关闭该声卡。\nProfiles select analog, digital or Bluetooth modes; Off disables the card.")))
        pack(body, self.compact_label(tr_legacy("选择后点击「设为默认」或「应用接口」。音量和静音控制当前所选设备。\nConfirm device and port changes with the buttons. Volume and mute affect the selected device.")))
        pack(body, button(tr("Advanced mixer", "高级混音器"),
                          lambda: self.desktop("launch", "audio"), "accent-button"))
        self.audio_refresh_button = pack(body, button(tr_legacy("Refresh audio devices · 刷新音频设备"), self.refresh_audio))
        self.audio_controls.set_sensitive(False)
        self.audio_changes = None
        self.audio_refresh_at = 0
        return PageEntry(body, scroller(body))

    def start_audio_tick(self):
        if self.audio_tick_source is None and self.alive:
            self.audio_tick_source = GLib.timeout_add(250, self.tick_audio)
            self.pending.add(self.audio_tick_source)

    def stop_audio_tick(self):
        source = self.audio_tick_source
        self.audio_tick_source = None
        if source is not None:
            self.pending.discard(source)
            GLib.source_remove(source)

    def tick_audio(self):
        if not self.alive:
            return GLib.SOURCE_REMOVE
        # A read or a committing audio action already owns the next refresh.
        # Keeping pending events through both is refresh_audio's job, so this
        # 250 ms tick must not call into it repeatedly while they are busy.
        if (not self.page_visible('sound') or self.audio_loading
                or self.audio_busy):
            return GLib.SOURCE_CONTINUE
        if (self.audio_changes is None
                or self.audio_changes.changed.is_set()
                or time.monotonic() >= self.audio_refresh_at):
            self.refresh_audio()
        return GLib.SOURCE_CONTINUE

    def audio_advanced_changed(self, _check):
        self.audio_generation += 1
        self.audio_deferred_state = None
        self.refresh_audio()

    def refresh_audio(self):
        if not self.alive:
            return GLib.SOURCE_REMOVE
        if not self.page_visible('sound'):
            return GLib.SOURCE_CONTINUE
        if self.audio_loading or self.audio_busy:
            return GLib.SOURCE_CONTINUE
        if self.audio_changes is None:
            from audio_events import AudioChanges
            self.audio_changes = AudioChanges(threading.Event(), facilities=(
                'sink', 'source', 'server', 'card', 'sink-input', 'source-output'))
            self.audio_changes.thread.start()
        self.audio_changes.changed.clear()
        self.audio_refresh_at = time.monotonic() + 30
        from audio_backend import read_state
        self.audio_loading = True
        refresh_button = getattr(self, 'audio_refresh_button', None)
        if refresh_button is not None:
            refresh_button.set_sensitive(False)
        generation = self.audio_generation
        advanced = self.audio_advanced.get_active()

        def done(state):
            self.audio_loading = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            if generation == self.audio_generation and not self.audio_busy:
                self.apply_audio(state)
            elif not self.audio_busy:
                self.refresh_audio()

        def failed(error):
            self.audio_loading = False
            if refresh_button is not None:
                refresh_button.set_sensitive(True)
            if generation == self.audio_generation and not self.audio_busy:
                self.audio_controls.set_sensitive(False)
                message = str(error)
                lower = message.lower()
                if any(token in lower for token in ("connection refused", "connection failure", "pa_context_connect")):
                    friendly = (tr("Audio service unavailable", "音频服务不可用") + "\n" +
                                tr("Start PipeWire or reconnect to your session.", "请启动 PipeWire 或重新连接当前会话。"))
                else:
                    friendly = tr("Audio unavailable", "音频不可用") + f"\n{message}"
                self.application_audio.update([], [friendly])
                self.audio_status.set_text(friendly)
                self.audio_status.set_tooltip_text(message)
                self.audio_deferred_state = None
                self.audio_updating = True
                try:
                    # An initial failed read has finished. Do not leave a
                    # disabled selector claiming it is still detecting devices.
                    for combo in (*self.audio_devices.values(), *self.audio_ports.values(),
                                  self.audio_card_combo, self.audio_profile_combo):
                        self.audio_set_choices(combo, [("", tr("Audio unavailable", "音频不可用"))])
                finally:
                    self.audio_updating = False
            elif not self.audio_busy:
                self.refresh_audio()
        self.work(lambda: read_state(include_unavailable=advanced), done, failed)
        return GLib.SOURCE_CONTINUE

    def apply_audio(self, state):
        self.application_audio.update(state.get("streams", []), state.get("stream_errors", []))
        combos = [*self.audio_devices.values(), *self.audio_ports.values(),
                  self.audio_card_combo, self.audio_profile_combo]
        if any(combo.get_property("popup-shown") for combo in combos):
            self.audio_deferred_state = state
            return
        self.audio_state = state
        self.audio_updating = True
        try:
            for kind, collection in [("sink", "sinks"), ("source", "sources")]:
                self.audio_set_choices(self.audio_devices[kind],
                    [(device["name"], self.audio_device_title(device)) for device in state.get(collection, [])],
                    fallback=state.get(f"default_{kind}"))
                self.populate_audio_device(kind)
            prior_card = self.audio_card_combo.get_active_id()
            prior_profile = self.audio_profile_combo.get_active_id()
            cards = state.get("cards", [])
            self.audio_set_choices(self.audio_card_combo,
                [(card["name"], card.get("description") or card["name"]) for card in cards])
            preserve = self.audio_profile_dirty and prior_card == self.audio_card_combo.get_active_id()
            self.populate_audio_profiles(prior_profile if preserve else None)
        finally:
            self.audio_updating = False
        self.audio_controls.set_sensitive(True)
        hidden = state.get("hidden_counts") or {}
        count = sum(hidden.get(key, 0) for key in ("sinks", "sources"))
        details = [tr_legacy("音频已连接 · Audio connected")]
        if count and not self.audio_advanced.get_active():
            details.append(tr(f"{count} advanced channel{'s' if count != 1 else ''} hidden",
                              f"已收起 {count} 个高级通道"))
        pro_cards = state.get("pro_audio_cards") or []
        self.audio_status.set_tooltip_text(tr_legacy("Pro Audio 会暴露底层通道，可在下方声卡模式中切换至桌面模式。\nPro Audio exposes raw channels. A desktop profile can be selected below.")
                                          if pro_cards else "PipeWire / PulseAudio")
        self.audio_status.set_text("\n".join(details))

    def populate_audio_device(self, kind):
        device = self.selected_audio_device(kind)
        name = device["name"] if device else None
        default = self.audio_state.get(f"default_{kind}")
        use = self.audio_device_apply[kind]
        use.set_label("✓" if name and name == default else tr_legacy("使用 · Use"))
        use.set_sensitive(bool(device) and name != default and device.get("available", True))
        self.audio_devices[kind].set_tooltip_text(self.audio_device_title(device) if device else None)
        note = tr_legacy("默认设备 · Default") if name and name == default else tr_legacy("尚未应用 · Not applied")
        if device and device.get("availability") == "unavailable":
            note += tr("\nPort disconnected", "\n接口未连接")
        self.audio_device_notes[kind].set_text(note if device else tr_legacy("未检测到设备 · No device detected"))
        scale = self.audio_volumes[kind]
        self.audio_mutes[kind].set_sensitive(bool(device))
        volume = device.get("volume") if device else None
        scale.set_sensitive(volume is not None)
        if volume is not None:
            if kind not in self.audio_timers and kind not in self.audio_dragging:
                scale.set_value(min(volume, 100))
                self.audio_values[kind].set_text(f"{volume:.0f}%")
        else:
            self.audio_values[kind].set_text(tr_legacy("Unavailable · 不可用"))
        muted = device.get("mute", False) if device else False
        self.audio_mutes[kind].set_label(tr_legacy("Unmute · 取消静音") if muted else tr_legacy("Mute · 静音"))
        ports = self.audio_ports[kind]
        active = device.get("active_port") if device else None
        same_device = self.audio_port_devices.get(kind) == name
        rows = []
        for port in device.get("ports", []) if device else []:
            if port.get("available") not in (False, "no") or port["name"] == active or self.audio_advanced.get_active():
                title = port.get("description") or port["name"]
                if port.get("available") in (False, "no"):
                    title += tr(" · Disconnected", " · 未连接")
                rows.append((port["name"], title))
        self.audio_set_choices(ports, rows, preferred=None if same_device else active, fallback=active)
        self.audio_port_rows[kind].set_visible(bool(rows))
        self.audio_port_devices[kind] = name
        self.update_audio_port_button(kind)

    def update_audio_port_button(self, kind):
        device = self.selected_audio_device(kind)
        selected = self.audio_ports[kind].get_active_id()
        port = next((item for item in device.get("ports", []) if item["name"] == selected), None) if device else None
        active = device.get("active_port") if device else None
        self.audio_port_apply[kind].set_sensitive(bool(port) and selected != active
                                                  and port.get("available") not in (False, "no"))
        self.audio_port_apply[kind].set_label(tr_legacy("正在使用 · In use") if selected and selected == active else tr_legacy("应用接口 · Apply port"))

    def selected_audio_device(self, kind):
        selected = self.audio_devices[kind].get_active_id()
        return next((device for device in self.audio_state.get("sinks" if kind == "sink" else "sources", [])
                     if device["name"] == selected), None)

    def audio_action(self, task):
        if self.audio_busy:
            return False
        self.audio_generation += 1
        self.audio_deferred_state = None
        self.audio_busy = True
        # Keep the focused widget enabled; a busy operation must not reset the
        # keyboard position or close a combo that the user is browsing.
        self.audio_status.set_text(tr_legacy("Applying audio… · 正在应用音频设置…"))

        def done(_):
            self.audio_busy = False
            self.refresh_audio()

        def failed(error):
            self.audio_busy = False
            self.audio_status.set_text(tr("Audio change failed", "音频设置失败") + f"\n{error}")
        self.work(task, done, failed, commit=True)
        return True

    def audio_device_changed(self, combo, kind):
        if self.audio_updating or not combo.get_active_id():
            return
        prior = self.audio_timers.pop(kind, None)
        if prior:
            GLib.source_remove(prior)
            self.pending.discard(prior)
        self.audio_updating = True
        try:
            self.populate_audio_device(kind)
        finally:
            self.audio_updating = False

    def audio_use_device(self, kind):
        from audio_backend import set_default
        device = self.selected_audio_device(kind)
        if device and device.get("available", True) and device["name"] != self.audio_state.get(f"default_{kind}"):
            name = device["name"]
            self.audio_action(lambda: set_default(kind, name))

    def audio_toggle_mute(self, kind):
        from audio_backend import set_mute
        device = self.selected_audio_device(kind)
        if device:
            self.audio_action(lambda: set_mute(kind, device["name"], not device["mute"]))

    def audio_port_changed(self, combo, kind):
        if not self.audio_updating:
            self.update_audio_port_button(kind)

    def audio_apply_port(self, kind):
        from audio_backend import set_port
        device = self.selected_audio_device(kind)
        port = self.audio_ports[kind].get_active_id()
        if device and port and self.audio_port_apply[kind].get_sensitive():
            name = device["name"]
            self.audio_action(lambda: set_port(kind, name, port))

    def audio_volume_changed(self, scale, kind):
        if self.audio_updating:
            return
        from audio_backend import set_volume
        device = self.selected_audio_device(kind)
        if not device:
            return
        volume = round(scale.get_value())
        name = device["name"]
        self.audio_values[kind].set_text(f"{volume}%")
        prior = self.audio_timers.pop(kind, None)
        if prior:
            GLib.source_remove(prior)
            self.pending.discard(prior)

        def apply():
            self.pending.discard(self.audio_timers.pop(kind, None))
            if self.audio_busy or kind in self.audio_dragging:
                source = GLib.timeout_add(100, apply)
                self.audio_timers[kind] = source
                self.pending.add(source)
            else:
                self.audio_action(lambda: set_volume(kind, name, volume))
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add(180, apply)
        self.audio_timers[kind] = source
        self.pending.add(source)

    def audio_move_streams(self, kind):
        from audio_backend import move_streams
        device = self.selected_audio_device(kind)
        if device:
            self.audio_action(lambda: move_streams(kind, device["name"]))

    def selected_audio_card(self):
        return next((card for card in self.audio_state.get("cards", [])
                     if card["name"] == self.audio_card_combo.get_active_id()), None)

    def populate_audio_profiles(self, preferred=None):
        card = self.selected_audio_card()
        active = card.get("active_profile") if card else None
        rows = [(profile["name"], profile.get("description") or profile["name"])
                for profile in card.get("profiles", []) if profile.get("available") not in (False, "no")] if card else []
        self.audio_set_choices(self.audio_profile_combo, rows,
                               preferred=preferred if preferred is not None else active, fallback=active)
        self.update_audio_profile_buttons()

    def update_audio_profile_buttons(self):
        card = self.selected_audio_card()
        selected = self.audio_profile_combo.get_active_id()
        active = card.get("active_profile") if card else None
        self.audio_profile_apply.set_sensitive(bool(selected) and selected != active)
        recommendation = card.get("recommended_profile") if card else None
        recommend = active == "pro-audio" and bool(recommendation)
        self.audio_profile_recommend.set_visible(recommend)
        description = card.get("recommended_description") or recommendation if card else ""
        self.audio_profile_recommend.set_tooltip_text(description or None)
        if active == "pro-audio":
            detail = tr_legacy("专业模式会列出底层通道。桌面模式通常更适合扬声器和麦克风。\nPro Audio lists raw channels. A desktop profile simplifies speakers and microphones.")
            if recommendation:
                detail += tr("\nRecommended: ", "\n推荐：") + description
        else:
            detail = tr_legacy("切换声卡模式会改变可用设备。选择后点击应用。\nA card profile changes available devices. Select, then apply.")
        self.audio_profile_note.set_text(detail)

    def audio_card_changed(self, _combo):
        if not self.audio_updating:
            self.audio_profile_dirty = False
            self.audio_updating = True
            try:
                self.populate_audio_profiles()
            finally:
                self.audio_updating = False

    def audio_profile_changed(self, _combo):
        if not self.audio_updating:
            self.audio_profile_dirty = True
            self.update_audio_profile_buttons()

    def audio_apply_profile(self):
        from audio_backend import set_profile
        card = self.audio_card_combo.get_active_id()
        profile = self.audio_profile_combo.get_active_id()
        if card and profile and not self.audio_busy:
            self.audio_profile_dirty = False
            self.audio_action(lambda: set_profile(card, profile))

    def audio_apply_recommended_profile(self):
        from audio_backend import set_profile
        card = self.selected_audio_card()
        profile = card.get("recommended_profile") if card else None
        if profile and not self.audio_busy:
            self.audio_profile_dirty = False
            name = card["name"]
            self.audio_action(lambda: set_profile(name, profile))
