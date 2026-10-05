"""Native Niri output settings with explicit keep/revert and a backend watchdog."""
import math
import re
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

import display_backend as backend
from i18n import tr, tr_legacy


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
        self.notice = self.add_to(self, panel.compact_label(tr_legacy("Reading Niri outputs… · 正在读取屏幕…")))
        self.keep_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.keep_label = self.add_to(self.keep_box, panel.compact_label())
        row = self.add_to(self.keep_box, Gtk.Box(spacing=8))
        self.add_to(row, self.button(tr_legacy("Keep · 保留设置"), self.keep), True)
        self.add_to(row, self.button(tr_legacy("Revert · 恢复原设置"), self.revert), True)
        self.add_to(self, self.keep_box)
        self.keep_box.set_no_show_all(True)
        self.form = self.add_to(self, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12))
        card = panel.card(self.form, tr_legacy("NIRI OUTPUT  /  显示器"))
        self.output = self.add_to(card, self.combo())
        self.output.connect("changed", self.output_changed)
        self.current = self.add_to(card, panel.compact_label())
        card = panel.card(self.form, tr_legacy("MODE & SCALE  /  分辨率与缩放"))
        self.add_to(card, self.text(tr_legacy("Resolution @ Hz · 分辨率与刷新率")))
        self.mode = Gtk.ComboBoxText.new_with_entry()
        self.mode.get_child().set_placeholder_text("1920x1080@60")
        self.add_to(card, self.mode)
        self.add_to(card, panel.compact_label(tr_legacy("Choose a reported mode or type 1920x1080@60.\n可选择屏幕报告的模式，或直接输入。")))
        self.scale = self.spin(card, tr("Scale (%)", "缩放 (%)"), 50, 400, 5, 100)
        self.add_to(card, self.text(tr_legacy("Maximum bit depth · 位深上限")))
        self.depth = self.add_to(card, self.combo())
        for key, title in [("auto", tr_legacy("Automatic · 自动")), ("8", "8 bit"), ("10", "10 bit"), ("12", "12 bit"), ("16", "16 bit")]:
            self.depth.append(key, title)
        self.depth_note = self.add_to(card, panel.compact_label())
        card = panel.card(self.form, tr_legacy("LAYOUT  /  屏幕排列"))
        self.rotation = self.add_to(card, self.combo())
        for key, title in [("normal", tr_legacy("Normal · 正常")), ("90", "90°"), ("180", "180°"), ("270", "270°"),
                           ("flipped", tr("Mirror", "镜像")), ("flipped-90", tr("Mirror 90°", "镜像 90°")),
                           ("flipped-180", tr("Mirror 180°", "镜像 180°")), ("flipped-270", tr("Mirror 270°", "镜像 270°"))]:
            self.rotation.append(key, title)
        self.x = self.spin(card, tr_legacy("Position X · 横向位置"), -32768, 32768, 1, 0)
        self.y = self.spin(card, tr_legacy("Position Y · 纵向位置"), -32768, 32768, 1, 0)
        self.vrr = Gtk.CheckButton(label=tr_legacy("Variable refresh rate · 可变刷新率"))
        self.add_to(card, self.vrr)
        self.apply_button = self.add_to(self, self.button(tr_legacy("Test & apply · 测试并应用"), self.apply))
        self.apply_button.get_style_context().add_class("accent-button")
        self.add_to(self, panel.compact_label(tr_legacy("Confirm within 15 seconds; otherwise previous settings return automatically.\n15 秒内确认保留，否则自动恢复；关闭面板后计时仍然有效。")))
        self.refresh_button = self.add_to(self, self.button(tr_legacy("Refresh outputs · 刷新屏幕"), self.refresh))
        self.panel.connect("destroy", self.closed)
        self.form.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.refresh()

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
                renderer.set_property("max-width-chars", 28)
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
        # The same freeze as the settings pages: a slow read must not replace a
        # draft the user changed after it started.
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
                tr_legacy("Sets Niri max-bpc; hardware may select a lower depth.\n设置位深上限；实际位深由显卡、接口及屏幕决定。") if supported else
                tr_legacy("This Niri build does not support max-bpc. Bit depth remains automatic.\n当前 Niri 版本不支持 max-bpc，位深暂由驱动自动选择。"))
            prior = self.output.get_active_id()
            self.guard = True
            self.output.remove_all()
            for output in state["outputs"]:
                self.output.append(output["name"], output.get("description") or output["name"])
            names = [item["name"] for item in state["outputs"]]
            self.output.set_active_id(prior if prior in names else (names[0] if names else ""))
            self.guard = False
            self.form.set_sensitive(bool(names))
            self.apply_button.set_sensitive(bool(names))
            self.notice.set_text(tr_legacy("Settings are written directly to Niri.\n设置直接写入 Niri 配置，无需其他显示设置程序。") if names else tr_legacy("No Niri outputs · 未检测到屏幕"))
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
        values = dict(output.get("current") or {})
        saved = self.state.get("saved", {}).get(output["name"], {})
        if saved:
            values.update(saved)
        self.mode.remove_all()
        for mode in output.get("modes", []):
            value = mode["mode"] if isinstance(mode, dict) else mode
            self.mode.append_text(value)
        self.mode.get_child().set_text(values.get("mode") or "")
        self.scale.set_value(values.get("scale", 1) * 100)
        self.depth.set_active_id(str(values.get("max_bpc") or "auto") if self.state.get("max_bpc_supported") else "auto")
        self.rotation.set_active_id(values.get("transform") or "normal")
        self.x.set_value(values.get("x", 0))
        self.y.set_value(values.get("y", 0))
        self.vrr.set_active(bool(values.get("vrr")))
        self.vrr.set_sensitive(bool(output.get("vrr_supported")))
        actual = output.get("current") or {}
        self.current.set_text(tr("Current ", "当前 ") + f"{actual.get('mode') or '—'} / {actual.get('scale', 1) * 100:g}%")

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
        self.notice.set_text(tr_legacy("Validating and applying… · 正在校验并应用…"))

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
        scroll = self.get_ancestor(Gtk.ScrolledWindow)
        if scroll:
            scroll.get_vadjustment().set_value(0)
        self.notice.set_text(tr_legacy("Check the screen, then keep or revert.\n请检查屏幕显示，再选择保留或恢复。"))
        self.keep_label.set_text(tr("Keep these settings? ", "保留设置？") + f" {math.ceil(seconds)}s")
        self.timer = GLib.timeout_add(250, self.countdown)
        self.panel.pending.add(self.timer)

    def countdown(self):
        if not self.token or not self.panel.alive:
            return GLib.SOURCE_REMOVE
        remaining = max(0, math.ceil(self.deadline - time.monotonic()))
        self.keep_label.set_text(tr("Keep these settings? ", "保留设置？") + f" {remaining}s")
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
            self.notice.set_text(tr_legacy("Settings saved · 设置已保存") if keep and changed else tr_legacy("Previous settings restored · 已恢复原设置"))
            self.form.set_sensitive(True)
            self.apply_button.set_sensitive(True)
            self.refresh_button.set_sensitive(True)
            self.refresh()
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
        # The separate watchdog restores unconfirmed settings even if this
        # process exits before a worker callback, or the panel is killed.
        self.token = None
