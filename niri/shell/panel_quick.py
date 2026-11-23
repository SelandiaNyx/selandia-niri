"""Quick controls: connectivity tiles, brightness, scale and power profile.

Mixed into ``panel.Panel``; methods rely on the panel's shared state
(``self.work``, ``self.feedback`` and the widgets built in ``__init__``).
"""
from __future__ import annotations

import re

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib

from i18n import tr, tr_legacy
from panel_support import DESKTOP, bluetooth_state, power_runtime_state, probe, set_bluetooth


class QuickControlsPage:
    def refresh_control(self):
        if not self.alive or self.mode != "control":
            return GLib.SOURCE_REMOVE
        if not self.page_visible('quick'):
            return GLib.SOURCE_CONTINUE
        if self.refreshing:
            return GLib.SOURCE_CONTINUE
        self.refreshing = True

        def read():
            import concurrent.futures
            import brightness
            queries = {
                "wifi": ["nmcli", "radio", "wifi"],
                "dnd": ["swaync-client", "--skip-wait", "-D"],
                "notifications": ["swaync-client", "--skip-wait", "-c"],
                "volume": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                "microphone": ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                "profiles": ["powerprofilesctl", "list"],
            }
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                tasks = {key: executor.submit(probe, value) for key, value in queries.items()}
                tasks["bluetooth"] = executor.submit(bluetooth_state)
                tasks["power_runtime"] = executor.submit(power_runtime_state)
                tasks["brightness"] = executor.submit(brightness.read_state)
                if getattr(self, "quick_sampler", None) is not None:
                    tasks["quick_metrics"] = executor.submit(self.quick_sampler.sample)
                results = {key: value.result() for key, value in tasks.items()}
            active = re.search(r"^\s*\*\s*(power-saver|balanced|performance):", results.get("profiles") or "", re.MULTILINE)
            results["profile"] = active.group(1) if active else None
            return results
        self.work(read, self.apply_control, self.control_error)
        return GLib.SOURCE_CONTINUE

    def control_error(self, error):
        self.refreshing = False
        self.finish_manual_control_refresh()
        self.feedback(error, True)

    def finish_manual_control_refresh(self):
        if self.manual_control_refresh:
            self.manual_control_refresh = False
            button = getattr(self, 'quick_refresh_button', None)
            if button is not None:
                button.set_sensitive(True)

    def manual_refresh_control(self):
        """Give the explicit Quick refresh click an immediate disabled state."""
        if not self.alive or self.mode != "control" or self.refreshing:
            return
        self.manual_control_refresh = True
        button = getattr(self, 'quick_refresh_button', None)
        if button is not None:
            button.set_sensitive(False)
        self.refresh_control()
        if not self.refreshing:
            self.finish_manual_control_refresh()

    def set_tile(self, key, available, active, state):
        tile, text = self.tiles[key]
        self.updating_tiles = True
        tile.set_active(active and available)
        self.updating_tiles = False
        tile.set_sensitive(available)
        text.set_text(state)
        tile.set_tooltip_text(state)
        context = self.tile_groups[key].get_style_context()
        (context.add_class if active and available else context.remove_class)("active")

    def apply_quick_metrics(self, data):
        labels = getattr(self, "quick_pulse", None)
        if not data or not labels:
            return
        from metrics import format_rate
        cpu = data.get("cpu_percent")
        memory = (data.get("memory") or {}).get("percent")
        network = data.get("network") or {}
        down, up = network.get("down_bps"), network.get("up_bps")
        temperatures = [item for item in (data.get("temperatures") or [])
                        if item.get("celsius") is not None]
        hottest = max(temperatures, key=lambda item: item["celsius"]) if temperatures else None
        labels["cpu"].set_text(f"{cpu:.0f}%" if cpu is not None else "—")
        labels["memory"].set_text(f"{memory:.0f}%" if memory is not None else "—")
        labels["network"].set_text(f"↓{format_rate(down)} ↑{format_rate(up)}"
                                   if down is not None or up is not None else "—")
        labels["temp"].set_text(f"{hottest['celsius']:.0f}°C" if hottest else "—")

    def apply_control(self, state):
        self.refreshing = False
        self.finish_manual_control_refresh()
        self.state = state
        self.apply_quick_metrics(state.get("quick_metrics"))
        wifi = state["wifi"]
        self.set_tile("wifi", wifi in ("enabled", "disabled"), wifi == "enabled",
                      {"enabled": tr_legacy("Enabled · 已开启"), "disabled": tr_legacy("Off · 已关闭")}.get(wifi, tr_legacy("Unavailable · 不可用")))
        bluetooth = state["bluetooth"] or {}
        bt_available = bool(bluetooth.get("path"))
        bt_on = bluetooth.get("powered", False)
        self.set_tile("bluetooth", bt_available, bt_on,
                      (tr_legacy("Enabled · 已开启") if bt_on else tr_legacy("Off · 已关闭")) if bt_available else tr_legacy("No adapter · 无适配器"))
        self.tiles["bluetooth"][0].set_tooltip_text(str(bluetooth.get("name", tr_legacy("No Bluetooth controller · 未检测到蓝牙控制器"))))
        dnd = (state["dnd"] or "").lower()
        self.set_tile("dnd", dnd in ("true", "false"), dnd == "true",
                      {"true": tr_legacy("Quiet · 已静音"), "false": tr_legacy("All notifications · 接收通知")}.get(dnd, tr_legacy("Unavailable · 不可用")))
        count = state["notifications"]
        self.notification_button.set_tooltip_text(tr(f"Notifications {count}", f"通知 {count}") if count and count.isdigit() else tr("Notifications", "通知"))
        self.notification_button.get_child().get_children()[-1].set_text(
            tr(f"Notifications {min(int(count), 99)}", f"通知 {min(int(count), 99)}") if count and count.isdigit() and int(count) else tr("Notifications", "通知"))
        self.notification_button.set_sensitive(count is not None)
        power = state.get("power_runtime") or {}
        self.set_tile("idle", power.get("available", False), power.get("awake", False),
                      power.get("label", tr("Unavailable", "不可用")))
        self.tiles["idle"][0].set_tooltip_text(power.get("detail", ""))
        self.updating_scales = True
        for key in ("volume", "microphone"):
            raw = state[key] or ""
            match = re.search(r"Volume:\s*([\d.]+)", raw)
            self.scales[key].set_sensitive(bool(match))
            self.mute_buttons[key].set_sensitive(bool(match))
            if match:
                value = round(float(match.group(1)) * 100)
                if key not in self.scale_timers and key not in self.dragging_scales:
                    self.scales[key].set_value(min(value, 100))
                self.scale_values[key].set_text(f"{value}%")
                self.mute_buttons[key].set_tooltip_text(tr_legacy("Unmute · 取消静音") if "MUTED" in raw else tr_legacy("Mute · 静音"))
                context = self.mute_buttons[key].get_style_context()
                (context.add_class if "MUTED" in raw else context.remove_class)("muted")
            else:
                # The value column is deliberately narrow; "Unavailable" would
                # ellipsize in English. Use the same compact fallback as N/A.
                self.scale_values[key].set_text(tr("N/A", "不可用"))
        self.apply_brightness(state.get("brightness") or {})
        profiles_raw = state.get("profiles") or ""
        profile = state.get("profile")
        if profile is None and profiles_raw:
            active = re.search(r"^\s*\*\s*(power-saver|balanced|performance):", profiles_raw, re.MULTILINE)
            profile = active.group(1) if active else None
        available_profiles = re.findall(r"^\s*\*?\s*(power-saver|balanced|performance):", profiles_raw, re.MULTILINE)
        self.profile_combo.remove_all()
        for name, title in [("power-saver", tr_legacy("Power saver · 节能")), ("balanced", tr_legacy("Balanced · 平衡")),
                            ("performance", tr_legacy("Performance · 性能"))]:
            if name in available_profiles:
                self.profile_combo.append(name, title)
        self.profile_combo.set_sensitive(bool(available_profiles))
        if profile in available_profiles:
            self.profile_combo.set_active_id(profile)
        self.profile_note.set_text("" if available_profiles else tr_legacy("Power profiles unavailable on this system.\n此系统未提供电源模式服务。"))
        self.updating_scales = False

    def apply_brightness(self, state):
        if self.brightness_busy or "brightness" in self.scale_timers or "brightness" in self.dragging_scales:
            return
        selected = self.brightness_combo.get_active_id()
        self.brightness_devices = {device["id"]: device for device in state.get("devices", [])}
        updating = self.updating_scales
        self.updating_scales = True
        self.brightness_combo.remove_all()
        for identifier, device in self.brightness_devices.items():
            self.brightness_combo.append(identifier, device["label"])
        if selected not in self.brightness_devices:
            selected = next(iter(self.brightness_devices), None)
        if selected:
            self.brightness_combo.set_active_id(selected)
        self.brightness_combo.set_sensitive(bool(self.brightness_devices))
        self.updating_scales = updating
        self.show_brightness(state.get("reason", ""))

    def show_brightness(self, reason=""):
        device = self.brightness_devices.get(self.brightness_combo.get_active_id(), {})
        available = device.get("available", False) and device.get("percent") is not None
        self.scales["brightness"].set_sensitive(available)
        updating = self.updating_scales
        self.updating_scales = True
        if available:
            self.scales["brightness"].set_value(device["percent"])
            self.scale_values["brightness"].set_text(f'{device["percent"]:g}%')
        else:
            self.scale_values["brightness"].set_text("—")
        self.updating_scales = updating
        self.backlight_note.set_text(
            (tr_legacy("DDC/CI · Monitor brightness / 显示器硬件亮度") if device.get("backend") == "ddc" else "")
            if available else (device.get("reason") or reason or tr_legacy("No brightness device · 未检测到可调亮度设备")))
        self.brightness_summary.set_text(device.get("label", tr_legacy("无可调亮度设备 · Unavailable")) if available
                                         else tr_legacy("亮度不可用 · 在更多控制中查看原因"))
        self.brightness_summary.set_tooltip_text(self.backlight_note.get_text())

    def brightness_selected(self, _combo):
        if self.updating_scales:
            return
        source = self.scale_timers.pop("brightness", None)
        if source:
            GLib.source_remove(source)
            self.pending.discard(source)
        self.show_brightness()

    def set_brightness(self, value):
        identifier = self.brightness_combo.get_active_id()
        if not identifier:
            return
        self.brightness_target = (identifier, value)
        if not self.brightness_busy:
            self.write_brightness()

    def write_brightness(self):
        identifier, value = self.brightness_target
        self.brightness_target = None
        self.brightness_busy = True
        self.brightness_combo.set_sensitive(False)
        self.backlight_note.set_text(tr_legacy("Applying brightness… · 正在调整硬件亮度…"))

        def done(device):
            self.brightness_busy = False
            self.brightness_devices[identifier] = device
            if self.brightness_target:
                self.write_brightness()
                return
            self.brightness_combo.set_sensitive(True)
            if "brightness" not in self.scale_timers and "brightness" not in self.dragging_scales:
                self.show_brightness()

        def failed(error):
            self.brightness_busy = False
            self.brightness_target = None
            self.brightness_combo.set_sensitive(True)
            self.backlight_note.set_text(error)
            self.feedback(error, True)
        import brightness
        self.work(lambda: brightness.set_percent(identifier, value), done, failed, commit=True)

    def toggle_wifi(self):
        self.action(["nmcli", "radio", "wifi", "off" if self.state.get("wifi") == "enabled" else "on"])

    def toggle_bluetooth(self):
        adapter = self.state.get("bluetooth") or {}
        if adapter.get("path"):
            self.action(lambda: set_bluetooth(adapter["path"], not adapter["powered"]))

    def toggle_dnd(self):
        self.action(["swaync-client", "--skip-wait", "-d"])

    def toggle_idle(self):
        self.action([DESKTOP, "idle-toggle"])

    def scale_drag_start(self, _scale, _event, key):
        self.dragging_scales.add(key)
        return False

    def scale_drag_end(self, _scale, _event, key):
        was_dragging = key in self.dragging_scales
        self.dragging_scales.discard(key)
        if key == "brightness" and was_dragging:
            self.scale_changed(_scale, key)
        return False

    def scale_changed(self, scale, key):
        if self.updating_scales:
            return
        value = round(scale.get_value())
        self.scale_values[key].set_text(f"{value}%")
        old = self.scale_timers.pop(key, None)
        if old:
            GLib.source_remove(old)
            self.pending.discard(old)

        def apply():
            source = self.scale_timers.pop(key, None)
            self.pending.discard(source)
            if key == "brightness":
                if key not in self.dragging_scales:
                    self.set_brightness(value)
            else:
                command = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@" if key == "volume" else "@DEFAULT_AUDIO_SOURCE@", f"{value}%"]
                self.action(command)
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add(180, apply)
        self.scale_timers[key] = source
        self.pending.add(source)

    def profile_changed(self, combo):
        if not self.updating_scales and combo.get_active_id():
            self.action(["powerprofilesctl", "set", combo.get_active_id()])
