"""Native settings pages shared by the searchable desktop settings window."""
from pathlib import Path
import shutil

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

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
        self.state_available = False
        self.state_controls = []
        self.notice = pack(self, text("", "hint"))
        self.notice.set_no_show_all(True)
        self.notice.connect("notify::label", lambda widget, _property: widget.set_visible(bool(widget.get_text())))
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
        self.update_state_controls()

    def require_state(self, widget, available=None):
        """Keep controls that need backend state unavailable until a successful read."""
        self.state_controls.append((widget, available or (lambda: True)))
        self.update_state_controls()
        return widget

    def update_state_controls(self):
        for widget, available in self.state_controls:
            widget.set_sensitive(self.state_available and available())

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
            self.loaded = True
            self.state_available = True
            self.set_busy(False)
            self.notice.set_text("")
            done(result)
            self.update_state_controls()
        def failure(error):
            self.state_available = False
            self.set_busy(False)
            self.notice.set_text(tr("Could not read settings. Refresh to try again.",
                                    "无法读取设置，请刷新后重试。") + "\n" + str(error))
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
        self.empty_choices = {}
        self.available_choices = {}
        self.saved_defaults = {}
        roles = [("browser", tr("Web browser", "网页浏览器")), ("mail", tr("Email", "邮件")),
                 ("files", tr("File manager", "文件管理器")), ("text", tr("Text files", "文本文件")),
                 ("pdf", "PDF"), ("image", tr("Images", "图片")), ("video", tr("Videos", "视频"))]
        card = self.card(tr("Default applications", "默认应用"))
        for role, title in roles:
            pack(card, text(title, "control-label"))
            row = pack(card, Gtk.Box(spacing=8))
            self.choices[role] = pack(row, combo(), True)
            self.buttons[role] = pack(row, button(tr("Apply", "应用"), lambda key=role: self.apply(key)))
            self.require_state(self.choices[role], lambda key=role: self.available_choices.get(key, False))
            self.require_state(self.buttons[role], lambda key=role: self.available_choices.get(key, False))
            hint = pack(card, text(tr("No compatible application is installed.", "没有兼容的已安装应用。"), "hint"))
            hint.set_no_show_all(True)
            self.empty_choices[role] = hint
        pack(self, text(tr("Only installed applications that support each file type are listed.",
                           "这里只列出已安装且支持相应文件类型的应用。"), "hint"))
        pack(self, button(tr("Refresh applications", "刷新应用列表"), self.refresh))

    def refresh(self, *, applied=None):
        drafts = {role: widget.get_active_id() for role, widget in self.choices.items()
                  if role != applied and self.loaded
                  and widget.get_active_id() != self.saved_defaults.get(role)}
        def ready(state):
            for role, value in state.items():
                widget = self.choices[role]
                widget.remove_all()
                for identifier, title in value["choices"]:
                    widget.append(identifier, title)
                available = {identifier for identifier, _title in value["choices"]}
                selected = drafts.get(role)
                widget.set_active_id(selected if selected in available else value["default"] or "")
                self.saved_defaults[role] = value["default"]
                self.available_choices[role] = bool(value["choices"])
                self.empty_choices[role].set_visible(not value["choices"])
        self.load(backend.application_state, ready)

    def apply(self, role):
        identifier = self.choices[role].get_active_id()
        if identifier:
            self.task(lambda: backend.set_default_application(role, identifier),
                      lambda _: self.refresh(applied=role))


class PowerSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        self.spins = {}
        runtime = self.card(tr("Current power state", "当前电源状态"))
        self.runtime_label = pack(runtime, text(tr("Checking…", "检测中…"), "section-title"))
        self.runtime_detail = pack(runtime, text("", "hint"))
        self.battery_detail = pack(runtime, text("", "hint"))
        self.battery_detail.set_no_show_all(True)
        self.config_warning = pack(runtime, text("", "hint"))
        self.config_warning.set_no_show_all(True)
        rt_btns = pack(runtime, Gtk.Box(spacing=8))
        self.awake_toggle_btn = pack(rt_btns, button(tr("Toggle stay awake", "切换保持唤醒"), self.toggle_stay_awake))
        self.status_refresh = pack(rt_btns, button(tr("Refresh status", "刷新状态"), self.refresh_status))
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
    def _read_battery_summary() -> str:
        base = Path("/sys/class/power_supply")
        if not base.is_dir():
            return ""
        parts = []
        for dev in sorted(base.iterdir()):
            try:
                kind = (dev / "type").read_text().strip()
                if kind == "Battery":
                    cap = (dev / "capacity").read_text().strip()
                    st = (dev / "status").read_text().strip()
                    parts.append(f"{dev.name}: {cap}% ({st})")
            except OSError:
                continue
        return " · ".join(parts)

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
        runtime["battery"] = PowerSettings._read_battery_summary()
        return settings, runtime

    def show_state(self, result, *, populate=False):
        settings, runtime = result
        if populate:
            for key, value in settings["settings"].items():
                self.spins[key].set_value(value)
        self.runtime_label.set_text(runtime.get("label", tr("Unavailable", "不可用")))
        self.runtime_detail.set_text(runtime.get("detail", ""))
        bat = runtime.get("battery", "")
        self.battery_detail.set_text(tr("Battery: ", "电池状态：") + bat if bat else "")
        self.battery_detail.set_visible(bool(bat))
        self.awake_toggle_btn.set_label(
            tr("Disable stay awake", "关闭保持唤醒") if runtime.get("awake")
            else tr("Enable stay awake", "开启保持唤醒")
        )
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

    def toggle_stay_awake(self):
        import sleep_guard
        self.task(sleep_guard.toggle, lambda _res: self.refresh_status())

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
        self.saved_time = {}
        self.can_ntp = False
        card = self.card(tr("Time zone", "时区"))
        self.zone = Gtk.Entry()
        self.zone.set_placeholder_text("Asia/Shanghai")
        pack(card, self.zone)
        self.require_state(self.zone)
        self.zone_apply = self.require_state(pack(card, button(tr("Apply time zone", "应用时区"), self.apply_zone)))
        card = self.card(tr("Internet time", "网络时间"))
        self.ntp = Gtk.CheckButton(label=tr("Synchronize time automatically", "自动同步时间"))
        pack(card, self.ntp)
        self.require_state(self.ntp, lambda: self.can_ntp)
        self.sync_status = pack(card, text("", "hint"))
        self.ntp_apply = pack(card, button(tr("Apply synchronization", "应用同步设置"), self.apply_ntp))
        self.require_state(self.ntp_apply, lambda: self.can_ntp)
        pack(self, text(tr("System settings may request administrator authentication.",
                           "修改系统设置时可能需要管理员验证。"), "hint"))
        pack(self, button(tr("Refresh", "刷新"), self.refresh))

    def refresh(self, *, applied=None):
        drafts = {}
        if self.loaded:
            if applied != "timezone" and self.zone.get_text() != self.saved_time.get("timezone"):
                drafts["timezone"] = self.zone.get_text()
            if applied != "ntp" and self.ntp.get_active() != self.saved_time.get("ntp"):
                drafts["ntp"] = self.ntp.get_active()
        def ready(result):
            state, zones = result
            self.zone.set_text(drafts.get("timezone", state["timezone"]))
            completion = Gtk.EntryCompletion()
            model = Gtk.ListStore(str)
            for zone in zones:
                model.append([zone])
            completion.set_model(model)
            completion.set_text_column(0)
            completion.set_inline_completion(True)
            self.zone.set_completion(completion)
            self.ntp.set_active(drafts.get("ntp", state["ntp"]))
            self.saved_time = {key: state[key] for key in ("timezone", "ntp")}
            self.can_ntp = state["can_ntp"]
            self.sync_status.set_text(tr("Clock synchronized", "时钟已同步") if state["synchronized"]
                                     else tr("Clock not yet synchronized", "时钟尚未同步"))
        self.load(lambda: (backend.time_state(), backend.timezones()), ready)

    def apply_zone(self):
        zone = self.zone.get_text().strip()
        self.task(lambda: backend.set_timezone(zone), lambda _: self.refresh(applied="timezone"))

    def apply_ntp(self):
        enabled = self.ntp.get_active()
        self.task(lambda: backend.set_ntp(enabled), lambda _: self.refresh(applied="ntp"))


class ServicesSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        self.checks = {}
        self.saved_services = {}
        card = self.card(tr("Desktop services", "桌面服务"))
        for key, title in [("clipboard", tr("Clipboard history", "剪贴板历史")),
                           ("notifications", tr("Notifications", "通知服务")),
                           ("bar", tr("Status bar", "状态栏"))]:
            row = pack(card, Gtk.Box(spacing=10))
            check = Gtk.CheckButton(label=title)
            self.checks[key] = pack(row, check, True)
            self.require_state(check)
            self.require_state(pack(row, button(tr("Apply", "应用"), lambda k=key: self.apply(k))))
        pack(self, text(tr("These switches persist across Niri logins. They only manage this desktop's services.",
                           "开关在下次登录 Niri 后仍然有效，仅管理本配置的桌面服务。"), "hint"))
        pack(self, button(tr("Clear clipboard history…", "清空剪贴板历史…"), lambda: panel.desktop("clipboard-clear")))
        pack(self, button(tr("Refresh services", "刷新服务状态"), self.refresh))

    def refresh(self, *, applied=None):
        drafts = {key: check.get_active() for key, check in self.checks.items()
                  if key != applied and self.loaded
                  and check.get_active() != self.saved_services.get(key)}
        def ready(state):
            for key, value in state.items():
                self.checks[key].set_active(drafts.get(key, value["enabled"]))
                self.saved_services[key] = value["enabled"]
        self.load(backend.service_state, ready)

    def apply(self, key):
        enabled = self.checks[key].get_active()
        self.task(lambda: backend.set_service(key, enabled), lambda _: self.refresh(applied=key))


class StartupSettings(SettingsPage):
    def __init__(self, panel):
        super().__init__(panel)
        card = self.card(tr("Start an application with Niri", "随 Niri 启动应用"))
        self.application = pack(card, combo())
        pack(card, button(tr("Add to startup", "添加启动项"), self.add))
        self.entries = self.card(tr("Niri startup applications", "Niri 启动项"))
        self.external_entries = self.card(tr("Existing startup applications", "已有自启动项"))
        self.entry_stacks = {}
        pack(self, text(tr("New entries start at the next Niri login. Removing an entry deletes the file this page created and nothing else.",
                           "新增项目从下次登录 Niri 起启动。移除只会删除本页创建的启动文件，不影响其他配置。"), "hint"))
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
            self.entry_stacks = {}
            if not state["entries"]:
                pack(self.entries, text(tr("No applications added yet.", "尚未添加启动项。"), "hint"))
            for entry in state["entries"]:
                self.entry_stacks[entry["id"]] = self.entry_row(entry)
            self.entries.show_all()
            self.panel.protect_scroll_controls(self.entries)
            for child in self.external_entries.get_children()[1:]:
                child.destroy()
            external = state.get("external_entries", [])
            if not external:
                pack(self.external_entries, text(tr("No other startup entries found.", "未发现其他自启动项。"), "hint"))
            for entry in external:
                row = pack(self.external_entries, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4))
                pack(row, text(entry["name"], "control-label"))
                source = tr("System", "系统") if entry["source"] == "system" else tr("User", "用户")
                status = tr("Enabled", "已启用") if entry["enabled"] else tr("Disabled", "已禁用")
                pack(row, text(f"{source} · {status}", "hint"))
                path = pack(row, text(entry["path"], "hint"))
                path.set_selectable(True)
                path.set_line_wrap(True)
            pack(self.external_entries, text(tr("These existing entries are shown for reference. Their original files are preserved.",
                                                  "此处展示已有自启动项及其来源，保留原始文件。"), "hint"))
            self.external_entries.show_all()
        self.load(backend.startup_state, ready)

    def entry_row(self, entry):
        """One managed entry: toggle it, or remove it after a second confirmation.

        Removal deletes a file in the user's autostart directory, so it is never
        one click away: the row swaps into its own confirmation, and the backend
        independently refuses anything this project did not create.
        """
        stack = pack(self.entries, Gtk.Stack())
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        row = Gtk.Box(spacing=8)
        check = Gtk.CheckButton(label=entry["name"])
        check.set_active(entry["enabled"])
        pack(row, check, True)
        pack(row, button(tr("Apply", "应用"), lambda item=entry, toggle=check:
             self.toggle(item["id"], toggle.get_active())))
        pack(row, button(tr("Remove", "移除"), lambda: stack.set_visible_child_name("confirm")))
        confirm = Gtk.Box(spacing=8)
        pack(confirm, text(tr(f"Remove “{entry['name']}”?", f"移除“{entry['name']}”？"), "control-label"), True)
        pack(confirm, button(tr("Cancel", "取消"), lambda: stack.set_visible_child_name("entry")))
        pack(confirm, button(tr("Remove", "移除"), lambda item=entry: self.remove(item["id"])))
        stack.add_named(row, "entry")
        stack.add_named(confirm, "confirm")
        stack.set_visible_child_name("entry")
        return stack

    def add(self):
        identifier = self.application.get_active_id()
        if identifier:
            self.task(lambda: backend.add_startup(identifier))

    def toggle(self, identifier, enabled):
        self.task(lambda: backend.toggle_startup(identifier, enabled))

    def remove(self, identifier):
        self.task(lambda: backend.remove_startup(identifier))


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
                  [("gnome-disks",), ("partitionmanager",)], "gnome-disk-utility")],
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
        self.require_state(self.profile)
        self.require_state(self.connect_button, lambda: bool(self.selected_profile()) and not self.selected_profile()["device"])
        self.require_state(self.disconnect_button, lambda: bool(self.selected_profile()) and bool(self.selected_profile()["device"]))
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
        profile = self.selected_profile()
        active = bool(profile and profile["device"])
        self.update_state_controls()
        self.connection_status.set_text(
            tr("Connected via ", "已连接：") + profile["device"] if active
            else tr("Not connected", "未连接") if profile
            else tr("No saved connections", "没有已保存的连接"))

    def selected_profile(self):
        return next((item for item in self.profiles if item["id"] == self.profile.get_active_id()), None)

    def activate(self, enabled):
        identifier = self.profile.get_active_id()
        if identifier:
            self.task(lambda: backend.activate_connection(identifier, enabled))


class NotificationSettings(SettingsPage):
    HISTORY_PAGE_SIZE = 30

    def __init__(self, panel):
        super().__init__(panel)
        import notification_history
        self.history_module = notification_history
        self.saved_history_settings = {}
        self.history_items = []
        self.history_visible_count = self.HISTORY_PAGE_SIZE

        # 1. History Settings Card
        settings_card = self.card(tr("Notification history settings", "通知历史记录设置"))

        self.enabled_check = Gtk.CheckButton(label=tr("Record notification history", "保存通知历史记录"))
        pack(settings_card, self.enabled_check)

        pack(settings_card, text(tr("Maximum history entries", "历史条数上限"), "control-label"))
        self.limit_combo = pack(settings_card, combo())
        for count in (20, 50, 100, 200, 500, 0):
            label = tr("Unlimited", "不限制") if count == 0 else (
                tr(f"{count} entries (Default)", f"{count} 条（默认）") if count == 100 else tr(f"{count} entries", f"{count} 条")
            )
            self.limit_combo.append(str(count), label)

        pack(settings_card, text(tr("History expiration time", "历史过期时间"), "control-label"))
        self.expire_combo = pack(settings_card, combo())
        for days in (1, 3, 7, 14, 30, 0):
            label = tr("Never expire", "永久保留（不过期）") if days == 0 else (
                tr(f"{days} days (Default)", f"{days} 天（默认）") if days == 7 else tr(f"{days} days", f"{days} 天")
            )
            self.expire_combo.append(str(days), label)

        btn_box = pack(settings_card, Gtk.Box(spacing=8))
        pack(btn_box, button(tr("Apply settings", "应用设置"), self.apply_settings))
        pack(settings_card, text(tr("Notifications exceeding the limit or expiration time are cleaned up automatically.",
                                    "超出条数上限或过期时间的历史通知会在保存或接收新通知时自动清理。"), "hint"))

        # 2. Notification History Card
        self.history_card = self.card(tr("Notification history", "历史通知记录"))

        self.history_actions = pack(self.history_card, Gtk.Stack())
        self.history_actions.set_hhomogeneous(False)
        self.history_actions.set_vhomogeneous(False)
        action_row = Gtk.Box(spacing=8)
        self.clear_history_button = pack(action_row, button(tr("Clear all history…", "清空所有记录…"), self.clear_history))
        pack(action_row, button(tr("Refresh", "刷新"), self.refresh))
        self.history_actions.add_named(action_row, "actions")
        confirmation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pack(confirmation, text(tr("Delete all saved notification history? This cannot be undone.",
                                   "清空已保存的全部通知记录？此操作无法撤销。"), "control-label"))
        answers = pack(confirmation, Gtk.Box(spacing=8))
        self.cancel_history_button = pack(answers, button(tr("Cancel", "取消"), self.cancel_clear_history))
        self.cancel_history_button.connect_after("size-allocate", self.reveal_history_confirmation)
        pack(answers, button(tr("Clear all history", "清空全部记录"), self.confirm_clear_history))
        self.history_actions.add_named(confirmation, "confirm")
        self.history_actions.set_visible_child_name("actions")

        self.history_search = pack(self.history_card, Gtk.SearchEntry())
        self.history_search.set_placeholder_text(tr("Search application, title or message", "搜索应用、标题或正文"))
        self.history_search.connect("search-changed", self.history_search_changed)
        self.history_count = pack(self.history_card, text("", "hint"))
        self.history_container = pack(self.history_card, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8))
        self.history_more = pack(self.history_card, button("", self.show_more_history))
        self.history_more.set_no_show_all(True)

        # 3. Notification service controls (never destroy Control Center!)
        service_card = self.card(tr("Notification controls", "通知服务与控制"))
        svc_row = pack(service_card, Gtk.Box(spacing=8))
        open_nc = button(tr("Open notification center", "打开通知中心"),
                         lambda: (panel.launch_external if hasattr(panel, "launch_external") else panel.launch)(["swaync-client", "--skip-wait", "-t"]))
        dnd_btn = button(tr("Toggle Do Not Disturb", "切换勿扰模式"),
                         lambda: (panel.action if hasattr(panel, "action") else panel.launch)(["swaync-client", "--skip-wait", "-d"]))
        pack(svc_row, open_nc, True)
        pack(svc_row, dnd_btn, True)
        self._history_search_timer = None

    def draft_settings(self):
        expiry = float(self.expire_combo.get_active_id() or "7")
        return {"enabled": self.enabled_check.get_active(),
                "limit": int(self.limit_combo.get_active_id() or "100"),
                "expire_days": int(expiry) if expiry.is_integer() else expiry}

    def refresh(self, *, applied=False):
        draft = self.draft_settings() if self.loaded else None
        preserve = draft is not None and not applied and draft != self.saved_history_settings
        def query():
            settings = self.history_module.load_settings()
            history = self.history_module.load_history()
            return {"settings": settings, "history": history}

        def ready(state):
            cfg = state["settings"]
            self.saved_history_settings = dict(cfg)
            if not preserve:
                self.enabled_check.set_active(cfg.get("enabled", True))
                for widget, key, default in ((self.limit_combo, "limit", 100),
                                              (self.expire_combo, "expire_days", 7)):
                    value = str(cfg.get(key, default))
                    if not widget.set_active_id(value):
                        title = (tr(f"{value} entries", f"{value} 条") if key == "limit"
                                 else tr(f"{value} days", f"{value} 天"))
                        widget.append(value, title)
                        widget.set_active_id(value)

            self.history_items = state["history"]
            self.render_history()

        self.load(query, ready)

    def history_search_changed(self, *_args):
        self.history_visible_count = self.HISTORY_PAGE_SIZE
        self.render_history()

    def show_more_history(self):
        if not self.busy:
            self.history_visible_count += self.HISTORY_PAGE_SIZE
            self.render_history()

    def render_history(self):
        query = self.history_search.get_text().strip().casefold()
        matching = [item for item in self.history_items
                    if not query or query in " ".join(str(item.get(key) or "")
                                                     for key in ("app_name", "summary", "body")).casefold()]
        shown = min(self.history_visible_count, len(matching))
        self.history_count.set_text(
            tr(f"Showing {shown} of {len(matching)} matching notifications",
               f"显示 {shown} / {len(matching)} 条匹配通知") if query else
            tr(f"Showing {shown} of {len(matching)} notifications", f"显示 {shown} / {len(matching)} 条通知"))
        for child in self.history_container.get_children():
            child.destroy()
        if not matching:
            message = (tr("No matching notification history.", "没有匹配的历史通知。") if query else
                       tr("No notification history.", "暂无历史通知记录。"))
            pack(self.history_container, text(message, "hint"))
        else:
            for item in matching[:shown]:
                pack(self.history_container, self._build_history_row(item))
        self.history_container.show_all()
        remaining = len(matching) - shown
        more = min(self.HISTORY_PAGE_SIZE, remaining)
        self.history_more.set_label(tr(f"Show {more} more", f"再显示 {more} 条"))
        self.history_more.set_visible(remaining > 0)
        if hasattr(self.panel, "protect_scroll_controls"):
            self.panel.protect_scroll_controls(self.history_container)

    def apply_settings(self):
        settings = self.draft_settings()

        def op():
            return self.history_module.save_settings(settings)
        self.task(op, lambda _: self.refresh(applied=True))

    def clear_history(self):
        if not self.busy:
            self.history_actions.set_visible_child_name("confirm")
            self.cancel_history_button.grab_focus()
            GLib.idle_add(self.reveal_history_confirmation)

    def reveal_history_confirmation(self, *_args):
        if self.get_mapped() and self.history_actions.get_visible_child_name() == "confirm":
            scroll = self.get_ancestor(Gtk.ScrolledWindow)
            position = self.cancel_history_button.translate_coordinates(scroll, 0, 0) if scroll is not None else None
            if scroll is not None and position is not None:
                adjustment = scroll.get_vadjustment()
                top = adjustment.get_value() + position[1]
                adjustment.clamp_page(top - 8, top + self.cancel_history_button.get_allocated_height() + 8)
        return GLib.SOURCE_REMOVE

    def cancel_clear_history(self):
        if not self.busy:
            self.history_actions.set_visible_child_name("actions")
            self.clear_history_button.grab_focus()

    def confirm_clear_history(self):
        if self.busy or self.history_actions.get_visible_child_name() != "confirm":
            return
        def op():
            self.history_module.clear_history()
        def done(_result):
            self.history_actions.set_visible_child_name("actions")
            self.refresh()
        self.task(op, done)

    def delete_entry(self, entry_id):
        def op():
            self.history_module.delete_notification(entry_id)
        self.task(op)

    def _build_history_row(self, item):
        import datetime
        box = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), "data-row")

        header = pack(box, Gtk.Box(spacing=8))
        app_icon = item.get("icon") or "preferences-system-notifications-symbolic"
        pack(header, icon(app_icon, 16))

        app_label = Gtk.Label(label=item.get("app_name") or tr("System", "系统"), xalign=0)
        app_label.get_style_context().add_class("control-label")
        pack(header, app_label)

        if item.get("urgency") == 2:
            urgency_tag = Gtk.Label(label=tr("Critical", "紧急"), xalign=0)
            urgency_tag.get_style_context().add_class("error")
            pack(header, urgency_tag)

        ts = item.get("timestamp", 0)
        time_str = ""
        if ts > 0:
            try:
                dt = datetime.datetime.fromtimestamp(ts)
                now = datetime.datetime.now()
                diff = (now - dt).total_seconds()
                if diff < 60:
                    time_str = tr("Just now", "刚刚")
                elif diff < 3600:
                    time_str = tr(f"{int(diff // 60)}m ago", f"{int(diff // 60)} 分钟前")
                elif diff < 86400 and dt.date() == now.date():
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                time_str = ""
        if time_str:
            time_label = Gtk.Label(label=time_str, xalign=0)
            time_label.get_style_context().add_class("hint")
            pack(header, time_label, True)
        else:
            pack(header, Gtk.Box(), True)

        del_btn = button("×", lambda i=item.get("history_id") or item.get("id"): self.delete_entry(i))
        del_btn.set_tooltip_text(tr("Delete this notification", "删除此条通知"))
        pack(header, del_btn)

        summary = item.get("summary", "")
        if summary:
            summary_label = Gtk.Label(label=summary, xalign=0)
            summary_label.set_line_wrap(True)
            summary_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            pack(box, summary_label)

        body = item.get("body", "")
        if body:
            body_label = Gtk.Label(label=body, xalign=0)
            body_label.set_line_wrap(True)
            body_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body_label.get_style_context().add_class("hint")
            pack(box, body_label)

        return box
