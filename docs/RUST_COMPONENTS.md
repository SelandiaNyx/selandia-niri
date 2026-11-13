# Rust 组件与仍需保留的部件

2026-10-11 用户确认基本可用，并明确要求删除已经完成替代的软件。本轮按这一授权移除旧组件；此前“10 次登录、7 天观察”的保留建议不再作为删除条件，也不声称这些观察已完成。按稳定可用取舍，不为语言强行换软件。

| 组件 | 当前行为 | 取舍与移除条件 |
|---|---|---|
| Waybar（C++） | 已移除；Eww（Rust）负责三段顶栏、灵动岛 | 旧配置与生成分支已删；版本与签名包保存用于离线恢复 |
| Kitty（Python/C，含 Go 工具） | 已移除；Alacritty（Rust）负责终端 | kitty-shell-integration、kitty-terminfo 一并移除，没有其他软件必需依赖 |
| Fuzzel（C） | Anyrun（Rust）负责应用启动；Fuzzel 仅提供 dmenu | Anyrun 不提供现有剪贴板/确认所需的 stdin/stdout 协议，保留；替代需通过选择、取消、字面参数测试 |
| SwayNC（Vala/C） | 通知、历史、勿扰、控制中心 | Eww 显示通知摘要，不承担完整通知服务器；完整替代需要 DBus 通知协议、历史、动作、勿扰覆盖 |
| SwayBG（C） | 静态壁纸与视频/场景退出时的兜底 | 壁纸服务依赖稳定的 layer-shell 背景客户端；完整替代需六种显示模式及故障兜底实测 |
| SwayIdle（C） | 空闲、锁屏、DPMS | 与 sleep-lock 路径保持现有实现；替代需真实睡眠前锁屏、空闲与恢复验证 |
| SwayLock（C） | 会话锁、PAM 解锁 | 保留安全边界；替代需真实 session-lock 就绪、PAM、重复请求与崩溃策略验证 |
| mpvpaper / linux-wallpaperengine | 视频/场景/Web 后端 | 未被替代，继续按可选与实验性依赖声明 |

新入口为 `niri/scripts/desktop launcher`、`launch terminal`、`calendar`。点击时间仅打开日历；右侧控制中心按钮不变。顶栏单元仍叫 `selandia-niri@waybar.service`，仅为已部署服务名称兼容，内部只启动 Eww，自动失败由 systemd 重启并记录 `eww-failed`，不执行已删除程序。

Eww、Anyrun 与 Alacritty 使用同一个 `appearance.py` 生成器。生成范围不再包含 Waybar/Kitty；Fuzzel 生成只服务 dmenu，不提供旧应用启动入口。`components.json` 中历史 waybar/fuzzel/kitty 值按字段迁移为 eww/anyrun/alacritty，不改变壁纸、声音或外观偏好。

已安装 Rust 上游版本沿用上一轮实测：Eww 0.6.0、Anyrun 26.6.1（anyrun-provider 随包）、Alacritty 0.17.0。清理操作没有更换这些版本。安装命令与离线恢复见 [安装](INSTALL.md)、[恢复](EMERGENCY_COMPONENTS.md)。
