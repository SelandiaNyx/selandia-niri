# Plasma 卸载记录

2026-10-05，用户明确要求卸载 Plasma。

## 结果

- 已移除 51 个 Plasma 包，合计 297.61 MiB，包括 plasma-meta、plasma-desktop、plasma-workspace、KWin、PowerDevil、Plasma 登录管理器及 KDE portal。使用精确列表的 `pacman -R`，没有递归删除其他依赖或清理用户文件。
- 已安装 qt6ct 0.11-8。卸载前后包差异严格等于计划的 51 个移除项和 qt6ct 这 1 个新增项；项目 `packages.txt` 的 44 个依赖全部存在。
- `/usr/share/wayland-sessions` 现在仅有 niri.desktop；SDDM 继续运行并保持启用。没有重启、退出当前 Niri 或重启显示管理器。
- 保留 Ark、Konsole 等现有 KDE 应用。Breeze 主题/图标/光标、Polkit KDE 权限代理、kwallet-pam、print-manager、plasma-firewall 以及它们需要的库保留，因此仍能看见个别名字带 plasma 的工具或库；这些不是 Plasma 桌面会话。
- SDDM astronaut 主题文件与 Qt SVG、虚拟键盘、视频插件均保留。关键保留组件已标记为主动安装，防止后续孤立依赖清理误删。

完整证据：[移除列表](plasma-remove-targets.txt)、[预演](plasma-removal-dry-run.log)、[实际包差异](plasma-removal-result.json)、[包管理日志](plasma-removal.log)、[卸载前包列表](plasma-installed-before.txt)。

## 为避免重新安装 Plasma 的必要项目改动

- `packages.txt`：以 qt6ct 替换 plasma-integration。后者经 KDE portal 依赖完整 plasma-workspace，不能作为 Niri 的独立主题依赖保留。
- `niri/config.kdl`：QT_QPA_PLATFORMTHEME 改为 qt6ct，清除 Plasma 菜单前缀。
- `niri/scripts/start-session`：同步新会话环境，并清理 systemd/D-Bus 中的旧菜单前缀。当前会话已同步，新启动的应用使用 qt6ct；现有使用旧插件的应用可在方便时重新打开。
- `niri/shell/application_theme.py`：生成独立 qt6ct 配置和 22 个 Qt 调色板角色，保留 KDE 应用自身的 kdeglobals。新文件沿用逐项备份、恢复及保留用户修改的机制，旧备份可以迁移。
- `check.sh`：检查 qt6ct 依赖；README 与主题测试已更新。

原项目文件副本在 `plasma-migration-backup/`；真实主题配置的原值记录在 `~/.local/state/selandia-niri/application-theme.json`。没有重置用户的字体、主题偏好、音频设备或蓝牙配置。

## 验证

- 375 项单元测试通过，其中应用主题 27 项，包含旧备份迁移、回滚和保留用户编辑。
- 真实 Qt6 插件在私有配置下验证深浅配色、图标、字体，运行中的控件也能重新读取配色。见 [Qt6 插件验证](plasma-qt6ct-native.json)、[动态刷新验证](plasma-qt6ct-reload.json)。
- 真实用户配置的只读 offscreen Qt6 检查：qt6ct-style、Breeze Dark、JetBrainsMonoNL Nerd Font Mono 16，窗口色 #202326、文字色 #fcfcfc。
- 完整 check.sh 通过，pacman -Dk 未发现依赖数据库错误；当前 Niri、Waybar、通知、Polkit 代理及 SDDM 正常。
- 卸载后的独立 Niri 冒烟测试通过，包括 52 项 GTK 交互、4 项 MPRIS 检查、屏幕事务回滚、6 次栏重载及私有锁屏 ready。未测试真正重新登录或物理睡眠唤醒。

## 功能影响与边界

“用户账户”外部设置模块属于已卸载的 plasma-workspace，控制中心会将该入口标为未安装；“修改当前账户密码”仍可用。打印机和防火墙入口保留。若以后补独立用户管理入口，应选不依赖 Plasma 桌面的实现，而不是为了恢复这个按钮重新安装 plasma-workspace。

现有自定义 GTK CSS 包含外部颜色导入，已保留并给出覆盖提示。项目审查中的 A1–A8 也未趁卸载修改，仍应按 [PROJECT_AUDIT.md](PROJECT_AUDIT.md) 交给后续修改者处理。

卸载策略采用 [Arch pacman 手册](https://man.archlinux.org/man/pacman.8.en) 所述精确包移除及显式安装标记；没有使用跳过依赖检查或递归级联强制删除。
