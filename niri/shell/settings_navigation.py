"""Searchable categories for the Niri desktop settings window."""
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango
from control_widgets import icon, pack, style
from i18n import tr

# Search accepts both languages; each label renders only the chosen language.
PAGES = (
    ("quick", "Overview", "总览", "view-grid-symbolic", "常用", "wifi bluetooth brightness volume 快捷 网络 蓝牙 亮度 音量"),
    ("sound", "Sound", "声音", "audio-volume-high-symbolic", "设备", "audio microphone speaker profile 音频 麦克风 扬声器 声卡"),
    ("displays", "Displays", "屏幕", "video-display-symbolic", "设备", "resolution refresh scale hdr 分辨率 刷新 缩放 位深"),
    ("input", "Keyboard & mouse", "键盘与鼠标", "input-keyboard-symbolic", "设备", "touchpad pointer keyboard repeat 输入 触摸板 指针 重复"),
    ("network", "Connections", "网络与蓝牙", "network-wireless-symbolic", "设备", "wifi ethernet vpn dns bluetooth 无线 有线 连接 蓝牙"),
    ("hardware", "Other devices", "其他设备", "printer-symbolic", "设备", "printer disk storage input method 打印机 磁盘 分区 输入法"),
    ("appearance", "Appearance", "外观", "preferences-desktop-appearance-symbolic", "个性化", "theme font dark light transparency 主题 字体 深色 浅色 透明度"),
    ("desktop", "Windows & workspace", "窗口与工作区", "focus-windows-symbolic", "个性化", "layout gaps focus cursor 布局 间距 焦点 光标 动画"),
    ("applications", "Default applications", "默认应用", "preferences-desktop-apps-symbolic", "个性化", "browser mail files pdf mime 浏览器 邮件 文件关联"),
    ("language", "Language & region", "语言与地区", "preferences-desktop-locale-symbolic", "个性化", "locale terminal lang chinese english 中文 英文 终端 语言 地区"),
    ("power", "Power & locking", "电源与锁屏", "system-shutdown-symbolic", "系统", "idle lock suspend sleep 节能 空闲 睡眠 息屏 锁屏"),
    ("time", "Date & time", "日期与时间", "preferences-system-time-symbolic", "系统", "clock timezone ntp 时钟 时区 同步"),
    ("startup", "Startup applications", "开机启动", "system-run-symbolic", "系统", "autostart login startup 自动启动 登录"),
    ("services", "Desktop services", "桌面服务", "preferences-system-symbolic", "系统", "clipboard notifications bar privacy 剪贴板 通知 状态栏 隐私"),
    ("security", "Accounts & security", "账户与安全", "security-high-symbolic", "系统", "user firewall password keyring 用户 防火墙 密码 密钥"),
    ("system", "System & maintenance", "系统与维护", "applications-system-symbolic", "系统", "update repair cpu memory monitor diagnostics 更新 修复 监控 内存 自检"),
)
PAGE_KEYS = tuple(item[0] for item in PAGES)


class SettingsNavigation(Gtk.Box):
    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.panel = panel
        self.rows = {}
        self.syncing = False
        style(self, "settings-sidebar")
        self.set_size_request(190, -1)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(tr("Search settings", "搜索设置"))
        self.search.set_tooltip_text(tr("Search names and functions · Ctrl+F", "按名称或功能搜索 · Ctrl+F"))
        pack(self, self.search)
        self.list = Gtk.ListBox()
        self.list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        style(self.list, "settings-navigation")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.list)
        pack(self, scroll, True)
        previous = None
        for key, english, chinese, glyph, group, keywords in PAGES:
            row = Gtk.ListBoxRow()
            row.key = key
            row.search_text = " ".join((english, chinese, keywords)).casefold()
            row.group = group
            content = Gtk.Box(spacing=9)
            pack(content, icon(glyph, 18))
            label = Gtk.Label(label=tr(english, chinese), xalign=0)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(20)
            pack(content, label, True)
            row.add(content)
            row.set_tooltip_text(tr(english, chinese))
            self.rows[key] = row
            self.list.add(row)
            previous = group
        self.empty = Gtk.Label(label=tr("No matching settings", "没有匹配的设置"))
        self.empty.set_line_wrap(True)
        self.empty.set_no_show_all(True)
        pack(self, self.empty)
        self.list.set_filter_func(self.matches)
        self.search.connect("search-changed", self.filter)
        self.search.connect("activate", self.search_activate)
        self.list.connect("row-selected", self.selected)

    def matches(self, row):
        terms = self.search.get_text().casefold().split()
        return all(term in row.search_text for term in terms)

    def filter(self, *_):
        self.list.invalidate_filter()
        self.empty.set_visible(not any(self.matches(row) for row in self.rows.values()))

    def search_activate(self, *_):
        target = next((row for row in self.rows.values() if self.matches(row)), None)
        if target:
            self.panel.select_control_tab(target.key, focus=True)

    def selected(self, _list, row):
        if row and not self.syncing:
            self.panel.select_control_tab(row.key)

    def select(self, key, focus=False):
        row = self.rows.get(key)
        if row is None:
            return
        self.syncing = True
        self.list.select_row(row)
        self.syncing = False
        if focus:
            if not self.matches(row):
                self.search.set_text("")
            row.grab_focus()

    def focus_current(self):
        self.select(self.panel.control_stack.get_visible_child_name(), focus=True)
