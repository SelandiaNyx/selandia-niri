"""Native settings pages shared by the searchable desktop settings window."""
from pathlib import Path
import shutil

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

from i18n import tr
import system_settings as backend
from control_widgets import icon, pack, style


def text(value, css=None):
    label = Gtk.Label(label=value, xalign=0)
    label.set_line_wrap(True)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        style(label, css)
    return label


def button(title, callback):
    widget = Gtk.Button(label=title)
    widget.connect("clicked", lambda _: callback())
    return widget


def combo():
    widget = Gtk.ComboBoxText()
    widget.set_hexpand(True)
    for renderer in widget.get_cells():
        if isinstance(renderer, Gtk.CellRendererText):
            renderer.set_property("ellipsize", Pango.EllipsizeMode.END)
            renderer.set_property("max-width-chars", 25)
    return widget


class SettingsPage(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.panel = panel
        self.loaded = False
        self.busy = False
        self.notice = pack(self, text("", "hint"))
        self.connect("map", self.mapped)

    def mapped(self, *_):
        if not self.loaded:
            self.refresh()

    def set_busy(self, busy):
        self.busy = busy
        # Reads and writes are asynchronous. Freeze the form while they run so
        # a late response cannot replace edits made in the meantime.
        for child in self.get_children():
            if child is not self.notice:
                child.set_sensitive(not busy)

    def task(self, operation, done=None):
        if self.busy:
            return
        self.set_busy(True)
        self.notice.set_text(tr("Applying…", "正在应用…"))
        def success(result):
            self.set_busy(False)
            self.notice.set_text(tr("Saved.", "已保存。"))
            if done:
                done(result)
            else:
                self.refresh()
        def failure(error):
            self.set_busy(False)
            self.notice.set_text(str(error))
        self.panel.work(operation, success, failure, commit=True)

    def load(self, operation, done):
        if self.busy:
            return
        self.set_busy(True)
        self.notice.set_text(tr("Loading…", "正在读取…"))
        def success(result):
            self.set_busy(False)
            self.loaded = True
            self.notice.set_text("")
            done(result)
        def failure(error):
            self.set_busy(False)
            self.notice.set_text(str(error))
        self.panel.work(operation, success, failure)

    def card(self, title):
        card = pack(self, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "card"))
        pack(card, text(title, "section-title"))
        return card


class ApplicationsSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        self.choices = {}
        self.buttons = {}
        roles = [("browser", tr("Web browser", "网页浏览器")), ("mail", tr("Email", "邮件")),
                 ("files", tr("File manager", "文件管理器")), ("text", tr("Text files", "文本文件")),
                 ("pdf", "PDF"), ("image", tr("Images", "图片")), ("video", tr("Videos", "视频"))]
        card = self.card(tr("Default applications", "默认应用"))
        for role, title in roles:
            pack(card, text(title, "control-label"))
            row = pack(card, Gtk.Box(spacing=8))
            self.choices[role] = pack(row, combo(), True)
            self.buttons[role] = pack(row, button(tr("Apply", "应用"), lambda key=role: self.apply(key)))
        pack(self, text(tr("Only installed applications that support each file type are listed.",
                           "这里只列出已安装且支持相应文件类型的应用。"), "hint"))
        pack(self, button(tr("Refresh applications", "刷新应用列表"), self.refresh))

    def refresh(self):
        def ready(state):
            for role, value in state.items():
                widget = self.choices[role]
                widget.remove_all()
                for identifier, title in value["choices"]:
                    widget.append(identifier, title)
                widget.set_active_id(value["default"] or "")
                widget.set_sensitive(bool(value["choices"]))
                self.buttons[role].set_sensitive(bool(value["choices"]))
        self.load(backend.application_state, ready)

    def apply(self, role):
        identifier = self.choices[role].get_active_id()
        if identifier:
            self.task(lambda: backend.set_default_application(role, identifier))


class PowerSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        self.spins = {}
        runtime = self.card(tr("Current power state", "当前电源状态"))
        self.runtime_label = pack(runtime, text(tr("Checking…", "检测中…"), "section-title"))
        self.runtime_detail = pack(runtime, text("", "hint"))
        self.config_warning = pack(runtime, text("", "hint"))
        self.config_warning.set_no_show_all(True)
        self.status_refresh = pack(runtime, button(tr("Refresh status", "刷新状态"), self.refresh_status))
        card = self.card(tr("Automatic locking and sleep", "自动锁屏与睡眠"))
        for key, title in [("lock_minutes", tr("Lock screen", "锁屏")),
                           ("screen_minutes", tr("Turn off display", "息屏")),
                           ("suspend_minutes", tr("Suspend", "睡眠"))]:
            row = pack(card, Gtk.Box(spacing=12))
            pack(row, text(title), True)
            spin = Gtk.SpinButton.new_with_range(0, 240, 1)
            spin.set_width_chars(5)
            self.spins[key] = pack(row, spin)
            pack(row, text(tr("min", "分钟"), "hint"))
        pack(card, text(tr("0 disables a timeout. Automatic sleep locks the screen first.",
                           "0 表示关闭该定时动作。自动睡眠前会先锁屏。"), "hint"))
        self.scope_note = pack(card, text(tr(
            "These timeouts apply only to Niri. Disabling them does not block sleep requests from other programs.",
            "这些计时设置仅管理 Niri。将其关闭，不会阻止其他程序请求睡眠。"), "hint"))
        pack(card, button(tr("Apply timeouts", "应用超时设置"), self.apply))
        pack(self, button(tr("Lock now", "立即锁屏"), lambda: panel.desktop("lock")))
        pack(self, button(tr("Session and power actions", "注销、重启与关机"), lambda: panel.desktop("power")))
        pack(self, text(tr("Power profile and temporary stay-awake controls are in Overview.",
                           "电源性能模式和临时保持唤醒开关位于总览。"), "hint"))
        pack(self, text(tr(
            "Stay awake requests a logind idle/sleep inhibitor for this Niri session. An administrator can override it; it ends when you log out.",
            "保持唤醒会在本次 Niri 会话中申请 logind 空闲与睡眠抑制锁，注销后结束；管理员操作仍可绕过。"), "hint"))

    @staticmethod
    def read_state():
        import sleep_guard
        settings = backend.power_state()
        try:
            runtime = sleep_guard.status()
        except Exception as error:
            runtime = {"awake": False, "error": True,
                       "label": tr("Power state unavailable", "无法读取电源状态"),
                       "detail": str(error)}
        return settings, runtime

    def show_state(self, result, *, populate=False):
        settings, runtime = result
        if populate:
            for key, value in settings["settings"].items():
                self.spins[key].set_value(value)
        self.runtime_label.set_text(runtime.get("label", tr("Unavailable", "不可用")))
        self.runtime_detail.set_text(runtime.get("detail", ""))
        context = self.runtime_label.get_style_context()
        (context.add_class if runtime.get("error") else context.remove_class)("error")
        warning = ""
        if settings.get("config_error"):
            warning = tr("The timer configuration could not be read: ", "无法读取计时配置：") + settings["config_error"]
        elif settings.get("consistent") is False:
            warning = tr(
                "The timer file differs from the saved values shown below. Apply timeouts to replace it with these values.",
                "当前计时配置文件与下方保存的数值不一致。应用超时设置后会用这些数值替换计时配置。")
        self.config_warning.set_text(warning)
        self.config_warning.set_visible(bool(warning))

    def refresh(self):
        self.load(self.read_state, lambda result: self.show_state(result, populate=True))

    def refresh_status(self):
        # Refresh live service diagnostics without discarding unapplied edits.
        self.load(self.read_state, self.show_state)

    def apply(self):
        values = {key: spin.get_value_as_int() for key, spin in self.spins.items()}
        self.task(lambda: backend.save_power(values))


class TimeSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        card = self.card(tr("Time zone", "时区"))
        self.zone = Gtk.Entry()
        self.zone.set_placeholder_text("Asia/Shanghai")
        pack(card, self.zone)
        pack(card, button(tr("Apply time zone", "应用时区"), self.apply_zone))
        card = self.card(tr("Internet time", "网络时间"))
        self.ntp = Gtk.CheckButton(label=tr("Synchronize time automatically", "自动同步时间"))
        pack(card, self.ntp)
        self.sync_status = pack(card, text("", "hint"))
        self.ntp_apply = pack(card, button(tr("Apply synchronization", "应用同步设置"), self.apply_ntp))
        pack(self, text(tr("System settings may request administrator authentication.",
                           "修改系统设置时可能需要管理员验证。"), "hint"))
        pack(self, button(tr("Refresh", "刷新"), self.refresh))

    def refresh(self):
        def ready(result):
            state, zones = result
            self.zone.set_text(state["timezone"])
            completion = Gtk.EntryCompletion()
            model = Gtk.ListStore(str)
            for zone in zones:
                model.append([zone])
            completion.set_model(model)
            completion.set_text_column(0)
            completion.set_inline_completion(True)
            self.zone.set_completion(completion)
            self.ntp.set_active(state["ntp"])
            self.ntp.set_sensitive(state["can_ntp"])
            self.ntp_apply.set_sensitive(state["can_ntp"])
            self.sync_status.set_text(tr("Clock synchronized", "时钟已同步") if state["synchronized"]
                                     else tr("Clock not yet synchronized", "时钟尚未同步"))
        self.load(lambda: (backend.time_state(), backend.timezones()), ready)

    def apply_zone(self):
        zone = self.zone.get_text().strip()
        self.task(lambda: backend.set_timezone(zone))

    def apply_ntp(self):
        enabled = self.ntp.get_active()
        self.task(lambda: backend.set_ntp(enabled))


class ServicesSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        self.checks = {}
        card = self.card(tr("Desktop services", "桌面服务"))
        for key, title in [("clipboard", tr("Clipboard history", "剪贴板历史")),
                           ("notifications", tr("Notifications", "通知服务")),
                           ("bar", tr("Status bar", "状态栏"))]:
            row = pack(card, Gtk.Box(spacing=10))
            check = Gtk.CheckButton(label=title)
            self.checks[key] = pack(row, check, True)
            pack(row, button(tr("Apply", "应用"), lambda k=key: self.apply(k)))
        pack(self, text(tr("These switches persist across Niri logins. They only manage this desktop's services.",
                           "开关在下次登录 Niri 后仍然有效，仅管理本配置的桌面服务。"), "hint"))
        pack(self, button(tr("Clear clipboard history…", "清空剪贴板历史…"), lambda: panel.desktop("clipboard-clear")))
        pack(self, button(tr("Refresh services", "刷新服务状态"), self.refresh))

    def refresh(self):
        self.load(backend.service_state, lambda state: [self.checks[key].set_active(value["enabled"])
                  for key, value in state.items()])

    def apply(self, key):
        enabled = self.checks[key].get_active()
        self.task(lambda: backend.set_service(key, enabled))


class StartupSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        card = self.card(tr("Start an application with Niri", "随 Niri 启动应用"))
        self.application = pack(card, combo())
        pack(card, button(tr("Add to startup", "添加启动项"), self.add))
        self.entries = self.card(tr("Niri startup applications", "Niri 启动项"))
        pack(self, text(tr("New entries start at the next Niri login.",
                           "新增项目从下次登录 Niri 起启动。"), "hint"))
        pack(self, button(tr("Refresh", "刷新"), self.refresh))

    def refresh(self):
        def ready(state):
            current = self.application.get_active_id()
            self.application.remove_all()
            for identifier, title in state["applications"]:
                self.application.append(identifier, title)
            if current:
                self.application.set_active_id(current)
            else:
                self.application.set_active(0)
            for child in self.entries.get_children()[1:]:
                child.destroy()
            if not state["entries"]:
                pack(self.entries, text(tr("No applications added yet.", "尚未添加启动项。"), "hint"))
            for entry in state["entries"]:
                row = pack(self.entries, Gtk.Box(spacing=8))
                check = Gtk.CheckButton(label=entry["name"])
                check.set_active(entry["enabled"])
                pack(row, check, True)
                pack(row, button(tr("Apply", "应用"), lambda item=entry, toggle=check:
                     self.toggle(item["id"], toggle.get_active())))
            self.entries.show_all()
            self.panel.protect_scroll_controls(self.entries)
        self.load(backend.startup_state, ready)

    def add(self):
        identifier = self.application.get_active_id()
        if identifier:
            self.task(lambda: backend.add_startup(identifier))

    def toggle(self, identifier, enabled):
        self.task(lambda: backend.toggle_startup(identifier, enabled))


# Standalone tools handle their own device protocols. Niri settings never invoke
# KWin/Plasma-only display, shortcut, workspace, or desktop-behavior modules.
TOOLS = {
    "network": [(("Connections", "网络连接"), ("Wi-Fi, Ethernet, VPN and DNS", "无线、有线、VPN 与 DNS"),
                 [("nm-connection-editor",)], "network-manager-applet"),
                (("Bluetooth", "蓝牙设备"), ("Pair devices and manage adapters", "配对设备与管理适配器"),
                 [("blueman-manager",)], "blueman")],
    "hardware": [(("Printers", "打印机"), ("Add printers and manage print queues", "添加打印机与管理打印队列"),
                  [("system-config-printer",), ("kcmshell6", "kcm_printer_manager")], "system-config-printer"),
                 (("Disks", "磁盘"), ("Inspect disks, partitions and mount settings", "查看磁盘、分区与挂载设置"),
                  [("gnome-disks",), ("partitionmanager",)], "gnome-disk-utility"),
                 (("Input methods", "输入法"), ("Configure Fcitx5 languages and shortcuts", "配置 Fcitx5 输入语言与快捷键"),
                  [("fcitx5-config-qt",)], "fcitx5-configtool")],
    "security": [(("Firewall", "防火墙"), ("Network access rules", "网络访问规则"),
                  [("firewall-config",), ("kcmshell6", "kcm_firewall")], "firewall-config"),
                 (("Passwords and keys", "密码与密钥"), ("Manage stored credentials", "管理保存的凭据"),
                  [("seahorse",), ("kwalletmanager5",), ("kwalletmanager6",)], "seahorse"),
                 (("Users", "用户账户"), ("Accounts and passwords", "账户与密码"),
                  [("kcmshell6", "kcm_users")], None)],
}


def available_command(candidates):
    for command in candidates:
        if not shutil.which(command[0]):
            continue
        if command[0] == "kcmshell6":
            # Presence of kcmshell is not evidence that a particular module exists.
            module = command[1]
            if not ((Path("/usr/share/applications") / f"{module}.desktop").exists()
                    or any(Path("/usr/lib/qt6/plugins/plasma/kcms/systemsettings").glob(f"{module}.so"))):
                continue
        return list(command)
    return None


class ToolsSettings(SettingsPage):
    def __init__(self, panel, category):
        super().__init__(panel)
        self.loaded = True
        self.notice.set_text(tr("Specialized tools open in their own window.", "专用设置工具会在独立窗口打开。"))
        for titles, descriptions, candidates, package in TOOLS[category]:
            card = self.card(tr(*titles))
            pack(card, text(tr(*descriptions), "hint"))
            command = available_command(candidates)
            action = pack(card, button(tr("Open settings", "打开设置"), lambda argv=command: panel.launch(argv)))
            action.set_sensitive(command is not None)
            if command is None:
                pack(card, text(tr("Not installed", "未安装") + (": " + package if package else ""), "hint"))
                if package:
                    pack(card, button(tr("Install tool…", "安装工具…"), lambda name=package: panel.desktop("install-tool", name)))
        if category == "network":
            pack(self, button(tr("Wireless switches", "无线开关"), lambda: panel.select_control_tab("quick")))
        if category == "security":
            pack(self, button(tr("Change my password…", "修改当前账户密码…"), lambda: panel.desktop("password")))

    def refresh(self):
        pass


class ConnectionsSettings(ToolsSettings):
    def __init__(self, panel):
        super().__init__(panel, "network")
        from bluetooth_controls import BluetoothPolicyControls
        pack(self, BluetoothPolicyControls(panel))
        self.loaded = False
        self.profiles = []
        card = self.card(tr("Saved connections", "已保存的连接"))
        self.reorder_child(card, 1)
        self.profile = pack(card, combo())
        self.profile.connect("changed", self.selected)
        self.connection_status = pack(card, text("", "hint"))
        actions = pack(card, Gtk.Box(spacing=8))
        self.connect_button = pack(actions, button(tr("Connect", "连接"), lambda: self.activate(True)), True)
        self.disconnect_button = pack(actions, button(tr("Disconnect", "断开"), lambda: self.activate(False)), True)
        pack(card, button(tr("Refresh connections", "刷新连接"), self.refresh))
        pack(card, text(tr("Manage connections below to add Wi-Fi, VPN or edit IP and DNS settings.",
                           "通过下方网络设置添加无线网络、VPN，或编辑 IP 与 DNS。"), "hint"))

    def refresh(self):
        def ready(profiles):
            self.profiles = profiles
            prior = self.profile.get_active_id()
            self.profile.remove_all()
            for profile in profiles:
                title = profile["name"] + ("  ✓" if profile["device"] else "")
                self.profile.append(profile["id"], title)
            ids = [item["id"] for item in profiles]
            preferred = next((item["id"] for item in profiles if item["device"]), ids[0] if ids else "")
            self.profile.set_active_id(prior if prior in ids else preferred)
            self.selected()
        self.load(backend.network_state, ready)

    def selected(self, *_):
        profile = next((item for item in self.profiles if item["id"] == self.profile.get_active_id()), None)
        active = bool(profile and profile["device"])
        self.connect_button.set_sensitive(bool(profile) and not active)
        self.disconnect_button.set_sensitive(active)
        self.connection_status.set_text(
            tr("Connected via ", "已连接：") + profile["device"] if active
            else tr("Not connected", "未连接"))

    def activate(self, enabled):
        identifier = self.profile.get_active_id()
        if identifier:
            self.task(lambda: backend.activate_connection(identifier, enabled))
