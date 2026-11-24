"""Native Niri Displays 2.0: drag-arrange canvas, scale presets, DDC & eye-care night light."""
from __future__ import annotations

import math
import re
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

from control_widgets import card_grid, grid_add, nyx_guide_banner, pack, setting_row, style, wrap_label
import display_backend as backend
from display_canvas import DisplayArrangeCanvas
from i18n import tr, tr_legacy
import night_light


class DisplaySettings(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self.state = {"outputs": [], "saved": {}}
        self.loading = False
        self.busy = False
        self.frozen = {}
        self.token = None
        self.timer = None
        self.guard = False
        self._nl_guard = False

        pack(self, nyx_guide_banner(
            "displays",
            tr("Drag monitors directly on the canvas to arrange multi-screen positions, pick quick scale steps, and configure eye-care night light.",
               "在上方画布直接拖动显示器即可排列多屏位置；支持快捷缩放挡位、VRR 与护眼色温夜览，修改后 15 秒未确认自动安全回滚。"),
        ))

        self.notice = self.add_to(self, wrap_label(tr("Reading Niri outputs…", "正在读取屏幕…"), "hint"))
        self.keep_box = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "inline-confirm")
        self.keep_label = self.add_to(self.keep_box, wrap_label("", "control-label"))
        row = self.add_to(self.keep_box, Gtk.Box(spacing=8))
        self.keep_btn = self.add_to(row, self.button(tr("Keep settings", "保留设置"), self.keep), True)
        self.revert_btn = self.add_to(row, self.button(tr("Revert now (Esc)", "立即恢复原设置"), self.revert), True)
        self.add_to(self, self.keep_box)
        self.keep_box.set_no_show_all(True)

        self.form = self.add_to(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12))

        # Top card: Interactive multi-monitor arrangement canvas + output selector
        arr_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "card")
        pack(arr_card, wrap_label(tr("MONITOR ARRANGEMENT", "显示器布局与选择"), "section-title"))
        self.canvas = DisplayArrangeCanvas(on_select=self._canvas_select, on_move=self._canvas_move)
        pack(arr_card, self.canvas)
        sel_row = pack(arr_card, Gtk.Box(spacing=10))
        self.output = pack(sel_row, self.combo(), True)
        self.output.connect("changed", self.output_changed)
        self.current = pack(sel_row, wrap_label("", "hint"))
        pack(self.form, arr_card)

        wide = getattr(panel, "panel_width", 1200) >= 1020
        grid = pack(self.form, card_grid(wide, 12))

        # Left card: Mode, Scale presets, VRR & Position
        mode_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(mode_card, wrap_label(tr("MODE, SCALE & LAYOUT", "分辨率、缩放与位置"), "section-title"))
        pack(mode_card, self.text(tr("Resolution @ Hz", "分辨率与刷新率")))
        self.mode = Gtk.ComboBoxText.new_with_entry()
        self.mode.get_child().set_placeholder_text("3840x2160@160")
        pack(mode_card, self.mode)

        scale_presets = pack(mode_card, Gtk.Box(spacing=4))
        for pct in (100, 125, 150, 175, 200):
            pbtn = style(Gtk.Button(label=f"{pct}%"), "small-button")
            pbtn.connect("clicked", lambda _b, v=pct: self.scale.set_value(v))
            pack(scale_presets, pbtn, True)
        self.scale = self.spin(mode_card, tr("Scale (%)", "精确缩放 (%)"), 50, 400, 5, 100)

        pack(mode_card, self.text(tr("Maximum bit depth", "位深上限")))
        self.depth = pack(mode_card, self.combo())
        for key, title in [("auto", tr("Automatic", "自动")), ("8", "8 bit"), ("10", "10 bit"), ("12", "12 bit"), ("16", "16 bit")]:
            self.depth.append(key, title)
        self.depth_note = pack(mode_card, wrap_label("", "hint"))

        pack(mode_card, self.text(tr("Rotation & mirror", "旋转与镜像")))
        self.rotation = pack(mode_card, self.combo())
        for key, title in [("normal", tr("Normal", "正常")), ("90", "90°"), ("180", "180°"), ("270", "270°"),
                           ("flipped", tr("Mirror", "镜像")), ("flipped-90", tr("Mirror 90°", "镜像 90°")),
                           ("flipped-180", tr("Mirror 180°", "镜像 180°")), ("flipped-270", tr("Mirror 270°", "镜像 270°"))]:
            self.rotation.append(key, title)
        pos_row = pack(mode_card, Gtk.Box(spacing=10))
        self.x = self.spin(pos_row, "X", -32768, 32768, 1, 0)
        self.y = self.spin(pos_row, "Y", -32768, 32768, 1, 0)
        self.x.connect("value-changed", self._pos_spin_changed)
        self.y.connect("value-changed", self._pos_spin_changed)
        self.vrr = Gtk.CheckButton(label=tr("Variable refresh rate (VRR)", "可变刷新率（VRR）"))
        pack(mode_card, self.vrr)
        grid_add(grid, mode_card)

        # Right card: Eye-Care Night Light (Kelvin + Theme warmth bridge)
        nl_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card")
        pack(nl_card, wrap_label(tr("EYE-CARE NIGHT LIGHT", "护眼色温与夜览"), "section-title"))
        self.nl_switch = Gtk.Switch()
        self.nl_switch.connect("state-set", self._on_nl_change)
        pack(nl_card, setting_row(tr("Hardware night light", "硬件全屏暖光夜览"), self.nl_switch,
                                  tr("Reduces blue light across all windows via Wayland gamma", "通过 Wayland 伽马色温降低全屏蓝光")))

        krow = pack(nl_card, Gtk.Box(spacing=8))
        pack(krow, wrap_label(tr("Color temperature", "护眼色温"), "control-label"), True)
        self.nl_kelvin_label = pack(krow, wrap_label("4200K", "value"))
        self.nl_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 2700, 6500, 100)
        self.nl_scale.set_draw_value(False)
        self.nl_scale.connect("value-changed", self._on_nl_scale)
        pack(nl_card, self.nl_scale)

        self.nl_schedule = Gtk.CheckButton(label=tr("Automatic sunset-to-sunrise schedule", "夜间自动启停（日落至日出）"))
        pack(nl_card, self.nl_schedule)
        self.nl_status = pack(nl_card, wrap_label("", "hint"))
        nl_btns = pack(nl_card, Gtk.Box(spacing=8))
        nl_apply = style(Gtk.Button(label=tr("Apply night light", "应用夜览色温")), "small-button")
        nl_apply.connect("clicked", lambda _: self._save_night_light())
        nl_theme = style(Gtk.Button(label=tr("Theme eye-care mode…", "主题护眼档位…")), "small-button")
        nl_theme.connect("clicked", lambda _: self.panel.select_control_tab("appearance"))
        pack(nl_btns, nl_apply, True)
        pack(nl_btns, nl_theme, True)
        grid_add(grid, nl_card)

        actions = pack(self, Gtk.Box(spacing=8))
        self.apply_button = pack(actions, self.button(tr("Test & apply display (15s safety)", "测试并应用屏幕设置（15 秒确认）"), self.apply), True)
        self.apply_button.get_style_context().add_class("accent-button")
        self.refresh_button = pack(actions, self.button(tr("Refresh outputs", "刷新屏幕"), self.refresh))

        self.panel.connect("destroy", self.closed)
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self._load_night_light()
        self.refresh()

    def _load_night_light(self):
        cfg = night_light.load_settings()
        self._nl_guard = True
        self.nl_switch.set_active(cfg["enabled"])
        self.nl_switch.set_state(cfg["enabled"])
        self.nl_scale.set_value(cfg["kelvin"])
        self.nl_kelvin_label.set_text(f"{cfg['kelvin']}K")
        self.nl_schedule.set_active(cfg["schedule"])
        self._nl_guard = False
        b = night_light.detect_backend()
        if b:
            self.nl_status.set_text(tr(f"Wayland gamma backend ready: {b}", f"硬件色温引擎就绪：{b}"))
        else:
            cmd = "pacman -S wlsunset"
            self.nl_status.set_text(
                tr(f"Tip: install wlsunset ({cmd}) for hardware Kelvin gamma; theme-level eye care is already active in Appearance.",
                   f"提示：安装 wlsunset（{cmd}）可启用全屏硬件色温；主题级护眼暖色已在「外观与护眼」生效。")
            )

    def _on_nl_scale(self, scale):
        self.nl_kelvin_label.set_text(f"{int(round(scale.get_value()))}K")

    def _on_nl_change(self, _sw, state):
        if self._nl_guard:
            return False
        self.nl_switch.set_state(bool(state))
        self._save_night_light(enabled_override=bool(state))
        return True

    def _save_night_light(self, enabled_override=None):
        data = {
            "enabled": self.nl_switch.get_active() if enabled_override is None else bool(enabled_override),
            "kelvin": int(round(self.nl_scale.get_value())),
            "schedule": self.nl_schedule.get_active(),
        }
        def op():
            saved = night_light.save_settings(data)
            _ok, msg = night_light.apply_gamma(saved)
            return msg
        self.panel.work(op, lambda msg: self.nl_status.set_text(msg),
                        lambda err: self.nl_status.set_text(str(err)), commit=True)

    def _canvas_select(self, name: str):
        self.output.set_active_id(name)

    def _canvas_move(self, name: str, x: int, y: int):
        if self.output.get_active_id() == name:
            self.guard = True
            self.x.set_value(x)
            self.y.set_value(y)
            self.guard = False

    def _pos_spin_changed(self, *_):
        if self.guard:
            return
        name = self.output.get_active_id()
        if name:
            self.canvas.update_position(name, int(self.x.get_value()), int(self.y.get_value()))

    @staticmethod
    def add_to(parent, widget, expand=False):
        parent.pack_start(widget, expand, expand, 0)
        return widget

    @staticmethod
    def text(value):
        return Gtk.Label(label=value, xalign=0)

    @staticmethod
    def combo():
        combo = Gtk.ComboBoxText()
        for renderer in combo.get_cells():
            if isinstance(renderer, Gtk.CellRendererText):
                renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
                renderer.set_property("max-width-chars", 32)
        return combo

    @staticmethod
    def button(title, callback):
        button = Gtk.Button(label=title)
        button.connect("clicked", lambda _: callback())
        return button

    def spin(self, parent, title, low, high, step, value):
        row = self.add_to(parent, Gtk.Box(spacing=8))
        self.add_to(row, self.text(title), True)
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_value(value)
        spin.set_width_chars(6)
        self.add_to(row, spin)
        return spin

    def refresh(self):
        if self.loading or self.busy or self.token:
            return
        self.loading = True
        self.refresh_button.set_sensitive(False)
        self.frozen = {widget: widget.get_sensitive() for widget in (self.form, self.apply_button)}
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)

        def done(state):
            self.loading = False
            self.frozen = {}
            self.refresh_button.set_sensitive(True)
            self.state = state
            supported = state.get("max_bpc_supported", False)
            self.depth.set_sensitive(supported)
            self.depth_note.set_text(
                tr("Sets Niri max-bpc; hardware may select a lower depth.", "设置位深上限；实际位深由显卡、接口与屏幕共同决定。") if supported else
                tr("Current Niri build does not expose max-bpc.", "当前 Niri 版本不支持 max-bpc，位深保持自动。"))
            prior = self.output.get_active_id()
            self.guard = True
            self.output.remove_all()
            canvas_items = []
            for output in state["outputs"]:
                self.output.append(output["name"], output.get("description") or output["name"])
                cur = output.get("current") or {}
                mode_str = str(cur.get("mode") or "1920x1080@60")
                w, h = 1920, 1080
                m = re.match(r"(\d+)x(\d+)", mode_str)
                if m:
                    w, h = int(m.group(1)), int(m.group(2))
                sc = float(cur.get("scale") or 1.0)
                canvas_items.append({
                    "name": output["name"], "x": int(cur.get("x") or 0), "y": int(cur.get("y") or 0),
                    "width": round(w / max(0.5, sc)), "height": round(h / max(0.5, sc)),
                    "mode": mode_str, "scale": sc,
                })
            names = [item["name"] for item in state["outputs"]]
            chosen = prior if prior in names else (names[0] if names else "")
            self.output.set_active_id(chosen)
            self.canvas.set_outputs(canvas_items, chosen)
            self.guard = False
            self.form.set_sensitive(bool(names))
            self.apply_button.set_sensitive(bool(names))
            self.notice.set_text("" if names else tr("No Niri outputs detected.", "未检测到 Niri 显示器。"))
            self.output_changed()
            pending = state.get("pending")
            if pending:
                self.wait_for_confirmation(pending["token"], max(0, pending["deadline"] - time.time()))

        def failed(error):
            self.loading = False
            self.refresh_button.set_sensitive(True)
            for widget, sensitive in self.frozen.items():
                widget.set_sensitive(sensitive)
            self.frozen = {}
            self.form.set_sensitive(False)
            self.apply_button.set_sensitive(False)
            self.notice.set_text(tr("Cannot read outputs: ", "无法读取屏幕：") + str(error))
        self.panel.work(backend.read_state, done, failed)

    def output_changed(self, *_):
        if self.guard:
            return
        output = next((item for item in self.state["outputs"] if item["name"] == self.output.get_active_id()), None)
        if not output:
            return
        self.canvas.selected = output["name"]
        self.canvas.queue_draw()
        values = dict(output.get("current") or {})
        saved = self.state.get("saved", {}).get(output["name"], {})
        if saved:
            values.update(saved)
        self.mode.remove_all()
        for mode in output.get("modes", []):
            value = mode["mode"] if isinstance(mode, dict) else mode
            self.mode.append_text(value)
        self.mode.get_child().set_text(values.get("mode") or "")
        self.guard = True
        self.scale.set_value(values.get("scale", 1) * 100)
        self.depth.set_active_id(str(values.get("max_bpc") or "auto") if self.state.get("max_bpc_supported") else "auto")
        self.rotation.set_active_id(values.get("transform") or "normal")
        self.x.set_value(values.get("x", 0))
        self.y.set_value(values.get("y", 0))
        self.vrr.set_active(bool(values.get("vrr")))
        self.vrr.set_sensitive(bool(output.get("vrr_supported")))
        self.guard = False
        actual = output.get("current") or {}
        self.current.set_text(tr("Current: ", "当前：") + f"{actual.get('mode') or '—'} · {actual.get('scale', 1) * 100:g}%")

    def draft(self):
        mode = self.mode.get_child().get_text().strip().replace("*", "x").replace("×", "x")
        mode = re.sub(r"\s*hz\s*$", "", mode, flags=re.IGNORECASE)
        return {"mode": mode, "scale": self.scale.get_value() / 100,
                "max_bpc": None if self.depth.get_active_id() == "auto" else int(self.depth.get_active_id()),
                "transform": self.rotation.get_active_id(), "x": int(self.x.get_value()),
                "y": int(self.y.get_value()), "vrr": self.vrr.get_active()}

    def apply(self):
        if self.busy or self.token or self.loading:
            return
        name = self.output.get_active_id()
        if not name:
            return
        try:
            values = self.draft()
        except (TypeError, ValueError) as error:
            self.notice.set_text(str(error))
            return
        self.busy = True
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.notice.set_text(tr("Validating and applying display settings…", "正在校验并应用屏幕设置…"))

        def done(token):
            self.busy = False
            self.wait_for_confirmation(token, 15)

        def failed(error):
            self.busy = False
            self.form.set_sensitive(True)
            self.apply_button.set_sensitive(True)
            self.refresh_button.set_sensitive(True)
            self.notice.set_text(tr("Could not apply: ", "无法应用：") + str(error))
        self.panel.work(lambda: backend.begin_apply(name, values), done, failed, commit=True)

    def wait_for_confirmation(self, token, seconds):
        self.token = token
        self.deadline = time.monotonic() + seconds
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.refresh_button.set_sensitive(False)
        self.keep_box.set_no_show_all(False)
        self.keep_box.show_all()
        self.keep_box.set_no_show_all(True)
        # Blind-safe recovery: default focus goes straight to Revert.
        GLib.idle_add(self.revert_btn.grab_focus)
        scroll = self.get_ancestor(Gtk.ScrolledWindow)
        if scroll:
            scroll.get_vadjustment().set_value(0)
        self.notice.set_text(tr("Check the screen, then keep or revert.", "请检查屏幕显示，确认保留或立即恢复。"))
        self.keep_label.set_text(tr("Keep these settings? ", "保留当前屏幕设置？") + f" {math.ceil(seconds)}s")
        self.timer = GLib.timeout_add(250, self.countdown)
        self.panel.pending.add(self.timer)

    def countdown(self):
        if not self.token or not self.panel.alive:
            return GLib.SOURCE_REMOVE
        remaining = max(0, math.ceil(self.deadline - time.monotonic()))
        self.keep_label.set_text(tr("Keep these settings? ", "保留当前屏幕设置？") + f" {remaining}s")
        if remaining == 0:
            self.panel.pending.discard(self.timer)
            self.timer = None
            self.revert()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def stop_timer(self):
        if self.timer:
            self.panel.pending.discard(self.timer)
            GLib.source_remove(self.timer)
            self.timer = None

    def finish(self, keep):
        if not self.token or self.busy:
            return
        token = self.token
        self.busy = True
        self.keep_box.set_sensitive(False)

        def done(changed):
            self.stop_timer()
            self.token = None
            self.busy = False
            self.keep_box.hide()
            self.keep_box.set_sensitive(True)
            self.notice.set_text(tr("Display settings saved.", "屏幕设置已保存。") if keep and changed else tr("Previous display settings restored.", "已恢复原屏幕设置。"))
            self.form.set_sensitive(True)
            self.apply_button.set_sensitive(True)
            self.refresh_button.set_sensitive(True)
            self.refresh()
            if hasattr(self.panel, "refresh_system_info"):
                self.panel.refresh_system_info()

        def failed(error):
            self.busy = False
            self.keep_box.set_sensitive(True)
            self.notice.set_text(tr("Display operation failed: ", "屏幕操作失败：") + str(error))
        self.panel.work(lambda: backend.confirm(token) if keep else backend.revert(token), done, failed, commit=True)

    def keep(self):
        self.finish(True)

    def revert(self):
        self.finish(False)

    def closed(self, *_):
        self.token = None
