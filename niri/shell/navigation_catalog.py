"""Pure page catalog: 6 logical groups, 18 full-control modules, aliases & setting index."""
from __future__ import annotations

# Search accepts both languages; each label renders only the chosen language.
PAGES = (
    # 1. Overview
    ("quick", "Overview", "总览", "view-grid-symbolic", "总览",
     "overview quick wifi bluetooth brightness volume media dnd awake battery eye care 快捷 开关 媒体 音量 亮度 护眼 电池"),
    # 2. Connectivity
    ("network", "Network", "网络", "network-wireless-symbolic", "连接",
     "wifi ethernet vpn dns hotspot ip ssid scan connect password 无线 有线 扫描 热点 连接 代理"),
    ("bluetooth", "Bluetooth", "蓝牙", "bluetooth-active-symbolic", "连接",
     "bluetooth pair scan adapter headphones mouse battery trust autoenable 蓝牙 配对 扫描 耳机 电量 开机"),
    # 3. Devices
    ("displays", "Displays & eye care", "屏幕与夜览", "video-display-symbolic", "设备",
     "resolution refresh scale hdr vrr arrange multi monitor brightness ddc night light kelvin warm 分辨率 刷新 缩放 位深 多屏 排列 亮度 夜览 色温 护眼"),
    ("sound", "Sound", "声音", "audio-volume-high-symbolic", "设备",
     "audio microphone speaker mute mixer route overamplification profile pro audio 音频 麦克风 扬声器 静音 路由 声卡 过载"),
    ("input", "Keyboard & mouse", "键盘与鼠标", "input-keyboard-symbolic", "设备",
     "touchpad pointer keyboard repeat fcitx5 input method xkb caps numlock tap scroll 输入 输入法 触摸板 指针 重复 滚轮"),
    ("storage", "Storage & devices", "存储与外设", "drive-harddisk-symbolic", "设备",
     "disk partition mount unmount eject usb pci printer hardware nvme storage 磁盘 分区 挂载 卸载 弹出 外设 打印机 存储"),
    # 4. Personalization
    ("appearance", "Appearance & eye care", "外观与护眼", "preferences-desktop-appearance-symbolic", "个性化",
     "theme palette gemini sakura sora lavender mint mascot skin color font dark light opacity motion eye care 主题 配色 看板娘 字体 深色 浅色 透明度 动效 护眼"),
    ("wallpapers", "Wallpapers", "壁纸", "image-x-generic-symbolic", "个性化",
     "wallpaper engine image video scene playlist mpvpaper folder cache 背景 壁纸 视频 场景 播放列表 缓存"),
    ("desktop", "Windows & workspace", "窗口与工作区", "focus-windows-symbolic", "个性化",
     "niri layout gaps focus ring border cursor animation radius column workspace 布局 间距 焦点 边框 光标 动画 圆角 工作区"),
    # 5. System Ops
    ("monitor", "Monitor & processes", "监控与进程", "utilities-system-monitor-symbolic", "运维",
     "cpu memory ram gpu vram disk network speed temperature sensors process pid kill terminate top 处理器 内存 显卡 温度 传感器 进程 结束 监控"),
    ("services", "System services", "系统服务", "preferences-system-symbolic", "运维",
     "systemd user system service daemon restart enable clipboard notifications bar wallpaper 桌面服务 用户服务 系统服务 自启 剪贴板"),
    ("logs", "System logs", "系统日志", "text-x-generic-symbolic", "运维",
     "journalctl journal log error warning debug crash diagnostic copy 日志 报错 警告 诊断 排错"),
    ("packages", "Packages & containers", "软件与容器", "system-software-install-symbolic", "运维",
     "pacman paru aur update upgrade orphan cache clean docker container repair diagnose 更新 软件包 孤包 缓存 容器 修复 自检"),
    # 6. Security & Preferences
    ("security", "Security & accounts", "安全与账户", "security-high-symbolic", "安全与偏好",
     "ufw firewall port rule user group hostname sudo polkit keyring password 防火墙 端口 规则 用户 主机名 密钥 密码"),
    ("power", "Power & locking", "电源与锁屏", "system-shutdown-symbolic", "安全与偏好",
     "idle lock suspend sleep battery profile awake inhibitor poweroff reboot 节能 空闲 睡眠 息屏 锁屏 电池 保持唤醒 关机"),
    ("notifications", "Notifications", "通知", "preferences-system-notifications-symbolic", "安全与偏好",
     "dnd history timeout limit rules mute app swaync 勿扰 历史 规则 超时 通知"),
    ("preferences", "Preferences & startup", "偏好与启动", "preferences-other-symbolic", "安全与偏好",
     "default applications browser mime language locale region date time timezone ntp clock startup autostart 默认应用 浏览器 语言 地区 时区 时钟 开机启动"),
)
PAGE_KEYS = tuple(item[0] for item in PAGES)

# Backward-compatible aliases so existing CLI commands and scripts keep working.
PAGE_ALIASES: dict[str, tuple[str, str | None]] = {
    "hardware": ("storage", None),
    "system": ("monitor", None),
    "applications": ("preferences", "applications"),
    "language": ("preferences", "language"),
    "time": ("preferences", "time"),
    "startup": ("preferences", "startup"),
}

GROUP_LABELS = {
    "总览": ("OVERVIEW", "总览"),
    "连接": ("CONNECTIVITY", "网络与连接"),
    "设备": ("DEVICES", "显示、音频与外设"),
    "个性化": ("PERSONALIZATION", "外观与桌面"),
    "运维": ("SYSTEM OPS", "系统与运维"),
    "安全与偏好": ("SECURITY & PREFS", "安全与偏好"),
}

# Setting-level index powering Ctrl+K command palette & deep sidebar search.
# Tuple format: (title_en, title_zh, page_key, subtab_or_anchor, keywords)
SETTING_INDEX = (
    ("Wi-Fi Scan & Connect", "扫描与连接 Wi-Fi", "network", None, "wifi ssid scan password wireless 无线 扫描 连接 密码"),
    ("Personal Hotspot", "个人热点开关", "network", None, "hotspot ap tethering 热点 共享"),
    ("Bluetooth Pairing & Battery", "蓝牙扫描配对与电量", "bluetooth", None, "bluetooth pair scan battery headphones 蓝牙 配对 耳机 电量"),
    ("Display Arrangement & Scale", "多屏拖拽排列与缩放", "displays", None, "monitor arrange position scale resolution hz 显示器 排列 缩放 分辨率 刷新率"),
    ("Variable Refresh Rate (VRR)", "可变刷新率 VRR", "displays", None, "vrr freesync gsync 160hz 刷新率"),
    ("Night Light & Eye-Care Kelvin", "护眼色温与夜览模式", "displays", None, "night light kelvin warm wlsunset eye care 护眼 色温 夜览 暖光"),
    ("Per-App Volume & Routing", "单应用音量与输出路由", "sound", None, "app volume mute route sink stream 应用 音量 静音 路由"),
    ("Microphone & Over-Amplification", "麦克风与超 100% 音量", "sound", None, "mic microphone boost 150% overamplification 麦克风 放大 过载"),
    ("Fcitx5 Input Method", "Fcitx5 输入法配置", "input", None, "fcitx5 ime pinyin chinese input method 输入法 拼音"),
    ("Keyboard Repeat & XKB Options", "键盘重复速率与改键", "input", None, "caps ctrl xkb layout repeat numlock 键盘 重复 改键"),
    ("Mouse & Touchpad Speed", "鼠标与触控板手感", "input", None, "mouse touchpad scroll tap natural speed 鼠标 触控板 滚轮 轻触"),
    ("Disks, Mount & Safe Eject", "磁盘容量、挂载与安全弹出", "storage", None, "disk partition mount unmount eject nvme usb 磁盘 挂载 弹出 分区"),
    ("USB & PCI Hardware Devices", "USB 与 PCI 硬件外设", "storage", None, "usb pci gpu webcam printer 外设 显卡 打印机"),
    ("Theme Presets & Eye-Care Comfort", "动漫主题与护眼模式", "appearance", None, "gemini sakura sora lavender mint dark light eye care comfort warm 主题 护眼 深色 浅色"),
    ("Gemini Mascot Skin", "切换 Gemini 看板娘形态", "appearance", None, "mascot gemini antigravity engineer obsidian skin 看板娘 形象 皮肤 立绘"),
    ("Opacity, Motion & Fonts", "透明度、动效与字体字号", "appearance", None, "opacity blur motion font size 透明 动效 字体 字号"),
    ("Wallpaper Library & Playlist", "壁纸库、播放列表与缓存", "wallpapers", None, "wallpaper video scene playlist mpvpaper cache 壁纸 视频 播放列表 缓存"),
    ("Window Gaps, Borders & Animations", "Niri 窗口间距、边框与动画", "desktop", None, "gaps focus ring border animation radius cursor 间距 聚焦环 边框 动画 圆角"),
    ("Live Processes (Terminate / Kill)", "实时进程管理（搜索与结束）", "monitor", None, "process task manager pid kill terminate cpu ram 进程 结束 任务管理器"),
    ("GPU, Sensors & Telemetry", "双显监控、温度与实时速率", "monitor", None, "gpu arc intel vram sensors temp sparkline 显卡 温度 传感器 趋势"),
    ("Systemd User & System Services", "Systemd 用户与系统服务", "services", None, "systemd daemon unit start stop restart enable 服务 启停 自启"),
    ("Clear Clipboard History", "清空剪贴板历史", "services", None, "clipboard cliphist clear privacy 剪贴板 清空 隐私"),
    ("System & Service Journal Logs", "系统与服务日志（journalctl）", "logs", None, "journalctl log error warning crash 日志 报错 排错"),
    ("Arch Updates, Orphans & Pacman Cache", "Arch 更新、孤包与缓存清理", "packages", None, "pacman paru aur update orphan cache clean 更新 孤包 缓存 清理"),
    ("Docker Containers", "Docker 容器启停与状态", "packages", None, "docker container start stop restart 容器 启动 停止"),
    ("UFW Firewall & Port Rules", "UFW 防火墙开关与端口规则", "security", None, "ufw firewall port allow deny rule 防火墙 端口 规则"),
    ("User Account, Groups & Hostname", "当前用户、权限组与主机名", "security", None, "user account wheel sudo hostname password keyring 用户 账户 主机名 密码"),
    ("Power Profile, Stay Awake & Timers", "电源模式、保持唤醒与定时锁屏", "power", None, "power profile stay awake suspend lock sleep battery 电源 保持唤醒 锁屏 睡眠 电池"),
    ("Do Not Disturb & App Notification Rules", "勿扰模式、历史与应用静音规则", "notifications", None, "dnd notification history timeout rule mute 勿扰 通知 历史 静音 规则"),
    ("Default Applications", "默认应用与文件关联", "preferences", "applications", "default browser files pdf editor terminal 默认应用 浏览器 文件"),
    ("Language & Region", "界面语言与终端地区", "preferences", "language", "language locale chinese english zh en 语言 地区 中文 英文"),
    ("Date, Time & Timezone", "实时时钟、时区与 NTP 同步", "preferences", "time", "date time clock timezone ntp 时区 时钟 同步"),
    ("Startup Applications", "开机自启动管理", "preferences", "startup", "startup autostart login boot 开机 启动 自启"),
)


def resolve_route(key: str) -> tuple[str, str | None]:
    """Resolve a canonical page key or legacy alias into ``(page_key, subtab)``."""
    if key in PAGE_ALIASES:
        return PAGE_ALIASES[key]
    if key in PAGE_KEYS:
        return key, None
    return "quick", None
