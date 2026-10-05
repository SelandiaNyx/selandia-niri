"""Explicit BlueZ startup policy, separate from the current adapter power."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

import bluetooth_policy as backend
from control_widgets import pack, style
from i18n import tr


class BluetoothPolicyControls(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        style(self, "card")
        self.panel = panel
        self.loaded = self.busy = False
        self.saved = None
        title = Gtk.Label(label=tr("Bluetooth at startup", "蓝牙启动行为"), xalign=0)
        pack(self, style(title, "section-title"))
        self.enabled = pack(self, Gtk.CheckButton.new_with_label(tr(
            "Automatically turn on Bluetooth at boot", "开机自动启用蓝牙")))
        self.enabled.set_sensitive(False)
        self.enabled.connect("toggled", lambda *_: self.update_button())
        self.apply = pack(self, Gtk.Button.new_with_label(tr("Apply with authentication", "验证身份并应用")))
        self.apply.set_halign(Gtk.Align.START)
        self.apply.set_sensitive(False)
        self.apply.connect("clicked", self.save)
        self.notice = pack(self, Gtk.Label(xalign=0))
        self.notice.set_line_wrap(True)
        self.notice.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        style(self.notice, "hint")
        self.connect("map", self.mapped)

    def update_button(self):
        self.apply.set_sensitive(self.loaded and not self.busy and self.enabled.get_active() != self.saved)

    def mapped(self, *_):
        if not self.loaded and not self.busy:
            self.busy = True
            self.panel.work(backend.read_state, self.show_state, self.failed)

    def show_state(self, state):
        self.loaded, self.busy = True, False
        self.saved = state["auto_enable"]
        self.enabled.set_active(self.saved)
        self.enabled.set_sensitive(True)
        self.update_button()
        self.notice.set_text(tr(
            "BlueZ reads this at its next start. Current Bluetooth power is controlled in Overview. Paired devices stay saved.",
            "BlueZ 将在下次启动时读取此设置。当前蓝牙开关位于总览页，已配对设备会保留。"))

    def failed(self, error):
        self.busy = False
        self.enabled.set_sensitive(self.loaded)
        self.update_button()
        self.notice.set_text(str(error))

    def save(self, *_):
        if self.busy or not self.loaded:
            return
        desired = self.enabled.get_active()
        if desired == self.saved:
            return
        self.busy = True
        self.enabled.set_sensitive(False)
        self.update_button()
        self.notice.set_text(tr("Waiting for authentication…", "等待身份验证…"))
        self.panel.work(lambda: backend.apply_auto_enable(desired), self.show_state, self.failed, commit=True)
