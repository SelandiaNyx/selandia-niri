"""Pure page catalog: keys, labels, groups, icons and search terms."""
from __future__ import annotations

# Search accepts both languages; each label renders only the chosen language.
PAGES = (
    ("quick", "Overview", "总览", "view-grid-symbolic", "常用", "wifi bluetooth brightness volume 快捷 网络 蓝牙 亮度 音量"),
    ("sound", "Sound", "声音", "audio-volume-high-symbolic", "设备", "audio microphone speaker profile 音频 麦克风 扬声器 声卡"),
    ("displays", "Displays", "屏幕", "video-display-symbolic", "设备", "resolution refresh scale hdr 分辨率 刷新 缩放 位深"),
    ("input", "Keyboard & mouse", "键盘与鼠标", "input-keyboard-symbolic", "设备", "touchpad pointer keyboard repeat fcitx5 input method 输入 输入法 触摸板 指针 重复"),
    ("network", "Connections", "网络与蓝牙", "network-wireless-symbolic", "设备", "wifi ethernet vpn dns bluetooth 无线 有线 连接 蓝牙"),
    ("hardware", "Other devices", "其他设备", "printer-symbolic", "设备", "printer disk storage 打印机 磁盘 分区"),
    ("appearance", "Appearance", "外观", "preferences-desktop-appearance-symbolic", "个性化", "theme palette color font dark light transparency 取色 配色 主题 字体 深色 浅色 透明度"),
    ("wallpapers", "Wallpapers", "壁纸", "image-x-generic-symbolic", "个性化", "wallpaper engine image video scene 背景 壁纸 视频 场景"),
    ("desktop", "Windows & workspace", "窗口与工作区", "focus-windows-symbolic", "个性化", "layout gaps focus cursor 布局 间距 焦点 光标 动画"),
    ("applications", "Default applications", "默认应用", "preferences-desktop-apps-symbolic", "系统", "browser mail files pdf mime 浏览器 邮件 文件关联"),
    ("language", "Language & region", "语言与地区", "preferences-desktop-locale-symbolic", "系统", "locale terminal lang chinese english 中文 英文 终端 语言 地区"),
    ("power", "Power & locking", "电源与锁屏", "system-shutdown-symbolic", "系统", "idle lock suspend sleep 节能 空闲 睡眠 息屏 锁屏"),
    ("time", "Date & time", "日期与时间", "preferences-system-time-symbolic", "系统", "clock timezone ntp 时钟 时区 同步"),
    ("startup", "Startup applications", "开机启动", "system-run-symbolic", "系统", "autostart login startup 自动启动 登录"),
    ("services", "Desktop services", "桌面服务", "preferences-system-symbolic", "系统", "clipboard notifications bar privacy 剪贴板 通知 状态栏 隐私"),
    ("notifications", "Notifications", "通知", "preferences-system-notifications-symbolic", "系统", "history timeout limit notifications 历史 记录 上限 过期 通知 勿扰"),
    ("security", "Accounts & security", "账户与安全", "security-high-symbolic", "系统", "user firewall password keyring 用户 防火墙 密码 密钥"),
    ("system", "System & maintenance", "系统与维护", "applications-system-symbolic", "系统", "update repair cpu memory monitor diagnostics 更新 修复 监控 内存 自检"),
)
PAGE_KEYS = tuple(item[0] for item in PAGES)

GROUP_LABELS = {
    "常用": ("QUICK ACCESS", "常用"),
    "设备": ("HARDWARE", "设备"),
    "个性化": ("CUSTOMIZATION", "个性化"),
    "系统": ("SYSTEM", "系统"),
}
