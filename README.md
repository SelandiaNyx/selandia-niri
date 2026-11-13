# Selandia Glass · 澄澈桌面

2026-11-13：完善设置草稿、通知历史搜索与安全删除、窄屏导航和日历滚动；后台读取按可见页调度，Eww 减少空闲线程；Intel i915/Xe 支持按需监控可读客户端引擎负载。见[日常操作与资源边界](docs/DAILY_USE.md)、[本轮验收](.validation/daily-improve-20261113-release/REPORT.md)。

新增：内嵌应用音量、壁纸列表／大图网格、不中断播放的壁纸音量／静音，以及更大的控制中心和系统详情。安装路径、支持范围及可选播放依赖见[安装与壁纸指南](docs/INSTALL.md)。

A complete **Niri 26.04+** desktop for Arch Linux: native frosted glass, a floating status bar, a spotlight launcher, a searchable shortcut library, an AI sidebar, and a hardware-aware Control Center. Choose Chinese or English in Language & region; the interface displays one language at a time.

面向 Arch Linux 的完整 **Niri 26.04+** 桌面：原生毛玻璃、悬浮状态栏、聚焦式启动器、可搜索快捷键库、AI 侧栏，以及能识别硬件状态的控制中心。在“语言与地区”中切换中文或英文，界面一次只显示一种语言。

This directory contains the Niri configuration and its supporting scripts. Desktop settings use Niri's configuration and IPC, Arch packages, Linux hardware interfaces and the current PipeWire session.

本目录存放 Niri 配置及配套脚本。桌面设置围绕 Niri 配置与 IPC、Arch 软件包、Linux 硬件接口及当前 PipeWire 会话实现。

The visual language incorporates Material Design 3 semantic roles, container hierarchy, and the [ii layout reference](https://ii.clsty.link/en/general/showcase/). Niri's native **wallpaper blur** is real; surface elevation and tonal containers adapt across nine color palettes while honoring dynamic user appearance preferences for fonts, color, and transparency without fixed defaults. [Niri background effects](https://niri-wm.github.io/niri/Window-Effects.html) explain the efficient `xray` mode used here. Delivery status and bounded performance measurements are recorded in .validation/md3-20261028-release/DELIVERY.md.

视觉规范引入 Material Design 3 语义角色、容器层级与 [ii 布局参考](https://ii.clsty.link/en/general/showcase/)。这里使用真正的 Niri **壁纸背景模糊**；表面高度与容器色调适配九套调色板，并动态遵循用户现有的字体、颜色与透明度外观偏好，而非引入固定默认。[Niri 官方说明](https://niri-wm.github.io/niri/Window-Effects.html)介绍了本项目采用的高效 `xray` 模式。交付状态与受控性能测量记录于 .validation/md3-20261028-release/DELIVERY.md。

## Desktop controller · 桌面控制脚本

Open a terminal in this directory and run / 在本目录打开终端并运行：

```bash
./control.sh
```

Choose an action in the terminal menu, or use a command below. Without a terminal, no arguments display help without making changes. Run as your desktop user; only package operations request `sudo` and pacman's transaction confirmation.

在终端菜单中选择操作，或直接使用下列命令。非终端环境下，无参数只显示帮助。请以桌面用户运行，不要 sudo 整个脚本；仅软件包操作请求 sudo，并由 pacman 显示事务供确认。

| Command · 命令 | Behavior · 行为 |
| --- | --- |
| `./control.sh install` | Install missing dependencies, validate, back up and deploy · 补齐依赖、校验、备份并部署 |
| `./control.sh update` | Full Arch package upgrade, then validate and apply this directory's configuration · 完整更新 Arch 软件包，校验并应用本目录的配置 |
| `./control.sh repair` | Restore missing dependencies, reinstall packages with missing files, and rebuild missing managed links/files · 补齐依赖、重装缺文件的软件包、恢复缺失的托管链接和文件 |
| `./control.sh uninstall` | Preview and confirm, stop desktop services, then restore original configuration · 预览并确认，停止桌面服务，恢复原配置 |
| `./control.sh status` | Read-only package/file/deployment inspection; exit 1 if something needs attention · 只读检查依赖、文件和部署，有异常时返回 1 |
| `./control.sh check` | Full configuration and session diagnostics · 完整配置及会话自检 |
| `./control.sh export` | Export hardware-neutral defaults into `dist/` · 在 `dist/` 导出适合分享的默认配置 |

**Update uses the files already in this directory; it does not download new project releases.** It always runs `sudo pacman -Syu --needed` for the required packages, which also updates the rest of Arch. Install/repair run a full package upgrade only when dependencies need installation or reinstallation. An existing `pavucontrol-qt` satisfies the mixer requirement.

**更新应用的是本目录已有文件，不会自动下载项目新版本。** `update` 始终执行 `sudo pacman -Syu --needed`，包含整个 Arch 系统的软件包更新；安装/修复仅在依赖需要安装或重装时执行完整更新。已有 `pavucontrol-qt` 可满足音量混音器依赖。

Repair uses `pacman -Qk` to find **missing packaged files**; it is not a content-integrity or whole-system recovery tool. Affected packages are reinstalled without `--needed`, so missing files in a current-version package are restored. Source: [pacman manual](https://man.archlinux.org/man/pacman.8.en).

修复通过 `pacman -Qk` 检查**软件包文件是否缺失**，不校验所有文件内容，也不是全系统恢复工具。重装缺文件的软件包时不使用 `--needed`，因此即使已安装版本为最新，也会恢复其缺失文件。命令含义见上述 pacman 官方手册。

Save your work, log out, and choose **Niri** at the login screen. From a TTY, use `niri-session`. Existing Niri users can press **Super+Ctrl+R** to reload the bar, notifications, and wallpaper; close/reopen panels to load their new code. The installer does not log you out or change your default session.

保存工作后注销，在登录界面选择 **Niri**；TTY 中可执行 `niri-session`。已有 Niri 用户可按 **Super+Ctrl+R** 重载状态栏、通知和壁纸；面板关闭再打开即可加载新代码。安装脚本不会自动注销或更改默认会话。

```bash
./control.sh repair --dry-run      # Preview recovery / 预览修复方案
./control.sh update --no-packages  # Apply local configuration only / 仅更新本地配置
./control.sh uninstall --dry-run   # Preview restored files / 预览卸载和恢复路径
./control.sh uninstall --yes       # Explicit non-interactive confirmation / 明确确认非交互卸载
```

`--dry-run` works with all four lifecycle commands and changes no packages, files or services. `--no-packages` works with install/update/repair. `--yes` confirms configuration removal only; it does not bypass pacman's confirmation. The original `./install.sh` remains an install shortcut and accepts legacy `--packages`, `--no-packages`, `--dry-run`, and `--uninstall` options, as well as the new commands.

四个管理操作均支持 `--dry-run`，不会修改软件包、文件或服务。安装/更新/修复支持 `--no-packages`。`--yes` 仅确认配置卸载，不跳过 pacman 的确认。旧 `./install.sh` 仍直接安装，兼容原 `--packages`、`--no-packages`、`--dry-run`、`--uninstall` 参数，也接受新操作命令。

Configuration is symlinked to this directory. **Keep the directory in place**, or rerun setup after moving it. Backups and the deployment manifest live in `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/`. Failed file replacements roll back; all deployment operations refuse to overwrite managed targets replaced or edited by another configuration. Uninstall retains packages, user data and this project directory; file rollback does not undo a completed pacman transaction.

Repair restores missing managed files while preserving the original backup. Uninstall can restore originals even if installed targets are missing. Missing project source files must be recovered first for install/update/repair. Source and edit checks run before package changes when Python works; recovery of a missing or damaged Python runtime installs dependencies first and then checks. Concurrent controller operations are blocked by a lock.

配置以软链接指向本目录。**请保留目录及其路径**；移动后需重新安装。备份和部署记录位于 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/`。文件替换失败会回滚；所有部署操作都拒绝覆盖已被其他配置替换或修改的托管目标。卸载保留软件包、用户数据和项目目录；文件回滚不会撤销已完成的 pacman 事务。

修复会恢复缺失的托管文件，并保留原始备份。卸载也允许已安装目标缺失，仍会恢复其原配置。若本项目源文件被删除，安装/更新/修复前需先恢复项目目录。Python 正常时先检查源文件与配置冲突，再修改软件包；Python 缺失或运行依赖损坏时先补依赖，再检查。并发管理操作通过锁阻止。

Managed destinations / 管理的路径（支持 `XDG_CONFIG_HOME`）：

- `~/.config/niri`
- `~/.config/systemd/user/selandia-niri.target`
- `~/.config/systemd/user/selandia-niri@.service`
- `~/.config/systemd/user/selandia-lock@.service`
- `~/.config/xdg-desktop-portal/niri-portals.conf`

## Everyday controls · 日常操作

`Super` means the Windows / Meta key / `Super` 即 Windows / Meta 键。

| Shortcut · 快捷键 | Action · 操作 |
| --- | --- |
| **Super+Space** | App launcher · 应用启动器 |
| **Super+/** | Search all shortcuts · 搜索全部快捷键 |
| **Super+I** | Toggle Control Center · 开关控制中心 |
| **Super+A** | Toggle AI sidebar · 开关 AI 侧栏 |
| Super+N | Notifications · 通知中心 |
| Super+Return / T | Glass terminal · 玻璃风格终端 |
| Super+E / W / C | Files / browser / editor · 文件 / 浏览器 / 编辑器 |
| Super+Q / L | Close window / lock · 关闭窗口 / 锁屏 |
| Super+Tab | Workspace overview · 工作区总览 |
| Super+arrows | Focus columns / windows · 聚焦列 / 窗口 |
| Super+Shift+arrows | Move columns / windows · 移动列 / 窗口 |
| Super+Alt+arrows | Focus another display · 聚焦其他显示器 |
| Super+Alt+Shift+arrows | Move window across displays · 跨显示器移动窗口 |
| Super+1…9, 0 | Workspaces 1–10 · 工作区 1–10 |
| Super+Alt+number | Move window, stay here · 移动窗口，焦点留在原处 |
| Super+Shift+number | Move window and follow · 移动窗口并跟随 |
| Super+PageUp / PageDown | Previous / next workspace · 上 / 下工作区 |
| Super+R / Shift+R | Next / previous column width · 切换列宽 |
| Super+D / F | Maximize column / fullscreen · 最大化列 / 全屏 |
| Super+[ / ] | Merge or detach window · 合并或拆出窗口 |
| Super+Ctrl+Tab | Column tabs · 标签页列 |
| Super+Alt+Space | Toggle floating · 切换浮动 |
| Super+Shift+Space | Focus floating / tiled layer · 切换浮动 / 平铺焦点 |
| Super+V / Shift+V | Clipboard / confirm clear · 剪贴板 / 确认清空 |
| Super+Shift+S | Interactive screenshot · 交互截图 |
| Print / Ctrl+Print / Alt+Print | Screen to clipboard / save screen / save window · 屏幕至剪贴板 / 保存屏幕 / 保存窗口 |
| Super+Ctrl+I | Keep awake · 保持唤醒 |
| 电源键短按 / Super+Ctrl+F12 | 请求恢复显示输出，锁屏时也可使用；不是系统挂起后的硬件唤醒保证 |
| Super+Ctrl+T | Wallpaper picker · 壁纸选择 |
| Super+Ctrl+R | Validate and reload desktop · 校验并重载桌面 |
| Brightness up / down | Adjust the focused display's hardware brightness · 调整当前聚焦屏幕的硬件亮度 |
| Super+J | Show / hide bar · 显示 / 隐藏状态栏 |
| Ctrl+Alt+Delete | Power menu · 电源菜单 |
| Super+Shift+/ | Native shortcut overlay · 原生快捷键提示 |
| Super+Shift+Escape | Niri exit confirmation · Niri 退出确认 |

The shortcut library reads `conf/binds.kdl` and `conf/local.kdl` when opened, including aliases hidden from Niri's native overlay. Search by key, English/Chinese action, or category. Escape or the same shortcut closes a panel. Mouse move/resize gestures are included. Additional custom include files must be merged into `binds.kdl` or documented separately.

快捷键库每次打开时读取 `conf/binds.kdl` 和 `conf/local.kdl`，包含原生提示隐藏的别名。可按按键、中英文操作或分类搜索。按 Escape 或再次按面板快捷键可关闭。也包含鼠标移动/缩放手势；额外的自定义 include 文件需并入 `binds.kdl` 或另行记录。

## 桌面设置

**Super+I** 或状态栏齿轮在当前屏幕中央打开桌面设置；AI 侧栏固定在屏幕左侧。左侧为可搜索的分类导航，右侧显示详细设置；窗口按当前屏幕可用逻辑尺寸调整，最大 **1600×1120 个逻辑像素**，窄屏使用上下导航。总览保留音乐、网络、音量、亮度等快捷操作，其余设置分成 16 类。点击别的应用即可继续工作，设置窗口可以保持打开。导航和内容使用预留空间的细滚动条，悬停不会放大或遮住选项。

分类与搜索借鉴 [KDE 系统设置](https://docs.kde.org/trunk_kf6/en/systemsettings/systemsettings/general.html)，总览保留 [Apple 控制中心](https://support.apple.com/en-in/guide/mac-help/mchl50f94f8f/26/mac/26)、[GNOME Quick Settings](https://gjs.guide/extensions/topics/quick-settings.html) 和 [Noctalia](https://docs.noctalia.dev/noctalia/control-center/) 中清楚区分开关与详细设置的做法。本项目仍使用原生 GTK，并围绕 Niri、Arch、当前硬件与服务实现。

面板有 180 ms 淡入淡出、页面交叉渐变和展开动画；**外观 → 减少动态效果**可关闭动效，也遵循 GTK 辅助功能设置。**Ctrl+F** 搜索设置，中英文关键词都可搜索；**Ctrl+1…9** 选择前九类，**Ctrl+Tab / Ctrl+Shift+Tab** 循环切页，**Tab / Shift+Tab** 移动焦点。按 **F1** 或点击标题栏的 **? 帮助按钮**打开键盘说明。**Esc** 先处理弹出内容或清空搜索，再返回总览、收起更多控制、关闭窗口。

滚轮经过未展开的下拉框、数值框或滑块时只滚动页面，聚焦也不会改变这一规则。滑块使用拖动或方向键调节；下拉列表展开后可正常滚动选项。设备、配置、默认应用等选择项需点击相应的**应用**按钮才生效。正在异步读取或保存的设置表单会暂时禁用，避免迟到的读取结果覆盖新输入。

| 分类 | 功能 |
| --- | --- |
| 总览 | 无线与蓝牙开关、勿扰、保持唤醒、指定播放器、输入/输出音量、硬件亮度 |
| 声音 | 输入/输出设备、音量与静音、端口、声卡配置、现有应用路由、完整混音器入口 |
| 屏幕 | Niri 原生分辨率、刷新率、缩放、排列、旋转、VRR；受支持的位深上限；限时预览与回滚 |
| 键盘与鼠标 | 键盘布局/变体/选项、重复速率、鼠标与触摸板速度、自然滚动、轻触点击、左右手 |
| 网络与蓝牙 | 已保存连接的连接/断开、蓝牙开机策略；高级网络和设备配对工具 |
| 其他设备 | 打印机、磁盘、Fcitx5 输入法工具入口；未安装时提供对应安装操作 |
| 外观 | 深浅色、GTK/Qt 应用外观同步、配色、字体/字号、透明度、减少动态效果 |
| 壁纸 | 图片与 Wallpaper Engine 项目扫描、显式应用、视频/场景可选后端及壁纸取色 |
| 窗口与工作区 | 间距、默认列宽、居中、边框/焦点环、鼠标焦点、工作区切换行为、光标大小 |
| 默认应用 | 浏览器、邮件、文件管理器、文本、PDF、图片与视频文件关联 |
| 语言与地区 | 独立选择界面语言、终端与用户会话语言、系统默认语言 |
| 电源与锁屏 | 自动锁屏、息屏和睡眠定时；立即锁屏及会话电源操作 |
| 日期与时间 | 时区选择与网络时间同步 |
| 开机启动 | 添加已安装应用，仅在下次登录 Niri 时启动；单独启用、停用或移除 |
| 桌面服务 | 持久开关剪贴板历史、通知和状态栏；清空剪贴板历史 |
| 通知 | 历史通知记录、上限条数、过期时间自动清理、清空记录与系统通知服务配置 |
| 账户与安全 | 修改当前账户密码，以及已安装的账户、防火墙、密码库工具 |
| 系统与维护 | CPU/内存/GPU/磁盘/网速/传感器监控，Arch 更新、依赖修复、配置自检 |

键盘、鼠标和窗口设置写入 `niri/conf/desktop-settings.kdl`，先校验完整 Niri 配置再保存。该文件最后加载，以覆盖对应的普通输入和布局值；屏幕规则则使用首个匹配项，因此 `display-settings.kdl` 仍最先加载。手动改过的托管配置会提示冲突；控制中心不会覆盖它。

默认应用直接修改 MIME 关联；定时电源设置生成 `niri/swayidle/managed.conf`，保留原始 `swayidle/config`。`0` 分钟表示关闭对应计时器；自动睡眠要求先锁屏。保持唤醒期间保存新计时不会擅自恢复计时服务。启动项写入当前用户的 `autostart/selandia-niri-*.desktop`，仅针对 Niri；本页仅修改自己创建的项目，移除前需在该条目上二次确认，且只删除本页创建的文件。“已有自启动项”另外展示用户及系统的有效 XDG 自启动配置、启用状态与文件来源，用户同名覆盖优先；不修改这些原始文件。服务开关使用本配置的用户服务，停用后主题重载不会再次启动它。新增自启动项及服务屏蔽记录原状态，卸载时恢复；之后手工修改的条目及旧版本没有原状态记录的条目保留，并在卸载预览中列出。

蓝牙的**当前开关**位于总览，**开机自动启用**位于网络与蓝牙。后者修改 BlueZ 的系统策略，需要管理员认证；关闭后避免 BlueZ 在开机时主动开启适配器。该操作保留当前连接状态，重启后生效；要立即关闭蓝牙，使用总览开关。

启动策略写入 `/etc/bluetooth/main.conf`，原文件保留带时间戳的 `.selandia-*` 备份。卸载桌面配置不会撤销你明确选择的系统蓝牙策略；可以在卸载前通过该开关重新调整。

打印机、分区管理、防火墙、完整账户管理、蓝牙配对，以及新建 Wi-Fi/VPN 或详细 IP/DNS 配置仍由独立专用工具处理。界面会说明这些入口会另开窗口，仅在工具及对应模块存在时启用；缺少可安装工具时提供安装按钮。不会将 KWin 的屏幕、快捷键或桌面设置冒充 Niri 设置，也不会承诺覆盖所有 Plasma 设置功能。

### 语言切换

**语言与地区**提供三个独立的应用按钮：

- **界面语言**：简体中文、英文或跟随会话语言。更新控制中心、桌面菜单、状态栏提示与通知标签；设备名、歌曲、文件路径和聊天内容保持原文。
- **终端与用户会话**：从已生成的 locale 中选择，保存当前用户的 `LANG`，为从 Niri 启动的新应用和终端生效。已有应用需重新打开，完整会话建议注销后重新登录。会清除与该选择冲突的继承语言覆盖项，不永久设置 `LC_ALL`。
- **系统默认语言**：通过 `localectl` 设置后续登录的系统默认值，需要管理员认证。个人语言设置仍优先；键盘布局由输入设置单独管理。

界面偏好保存在 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/language.json`。用户会话生成 `environment.d/90-selandia-language.conf` 和 `niri/conf/language.kdl`，原文件有备份且卸载时保留后续手动改动。卸载不会撤销你明确选择的系统默认语言。可用语言来自 `locale -a`；缺少语言时，在 `/etc/locale.gen` 启用对应 UTF-8 条目，执行 `sudo locale-gen` 后刷新列表。参考 [locale.conf 说明](https://www.freedesktop.org/software/systemd/man/251/locale.conf.html)。

Music controls select a specific MPRIS player. **Automatic** follows a playing instance; the source menu can pin an application explicitly. The displayed track, playback state and actions all belong to that same instance. Pause uses an explicit `Pause` method, independently of previous/next availability. Buttons follow the player's reported capabilities; a one-track queue can still pause when track navigation is unavailable. Artwork already supplied as a local file is displayed; otherwise a music icon is used. No player is started and no media is played merely by opening the panel.

音乐控件通过 MPRIS 选择明确的播放器。**自动**优先跟随正在播放的实例，也可以在音源菜单中指定应用。歌曲信息、播放状态和操作始终对应同一实例；暂停使用明确的 `Pause` 方法，不依赖上一首/下一首是否可用。按钮遵循播放器报告的能力，单曲队列即使无法切歌也能暂停。播放器提供本地封面时显示封面，否则使用音乐图标；打开面板不会启动播放器或自动播放。

The status bar shows CPU/RAM percentages and live download/upload speeds, sampled every **2 seconds**. A GPU percentage appears when a supported usage counter is available. Hover for storage, swap, load, temperatures and uptime; open System for detailed meters and all sensors. The System page reports one active/default-route network interface to avoid counting bridged or VPN traffic twice. CPU/network need a second sample; `—` means warming up or unavailable. AMD sysfs and optional NVIDIA tooling provide GPU usage; Intel usage may be unavailable when its driver exposes no unprivileged busy counter. No extra monitoring daemon or privileged GPU profiler is installed.

状态栏每 **2 秒**显示 CPU/内存占用和实时上下行速率；驱动支持时同时显示 GPU 占用。悬停可查看磁盘、交换空间、负载、温度和运行时间；系统页提供详细仪表及完整传感器列表。系统页网速跟踪一个活动/默认路由接口，避免桥接或 VPN 流量重复计算。CPU/网速需采样两次；`—` 表示采样中或不可用。AMD sysfs 和可选 NVIDIA 工具支持 GPU 占用；Intel 驱动未提供普通用户可读计数器时显示不可用。不安装额外监控守护进程或需提权的 GPU 分析器。

Sound uses PipeWire's PulseAudio interface through `pactl` (`libpulse`). Device selection is staged; click **Use device** or **Apply port** to confirm. Browsing with arrow keys does not change routing; **Route active apps here** explicitly moves existing playback/recording streams. Profiles require **Apply profile** and may change which devices exist; Off disables that card. Unavailable ports/profiles are excluded. **App volumes** embeds live playback/recording sliders and mute buttons. **Advanced mixer** opens `pavucontrol-qt` or `pavucontrol` for additional routing and channel controls. Normal panel sliders use 0–100%; changing a hardware profile or unplugging a device refreshes the list. No microphone recording is performed by monitoring. Command reference: [pactl manual](https://man.archlinux.org/man/pactl.1.en).

声音通过 `pactl`（`libpulse`）连接 PipeWire 的 PulseAudio 接口。选择设备或端口后需点击**设为默认**或**应用接口**，方向键浏览不会改变音频路由；**将运行中的应用切换至此**会明确迁移现有播放/录音流。配置档案需点击**应用设备配置**，切换后设备列表可能变化；Off 会关闭该声卡。不可用的端口和配置不提供选择。**应用音量**在声音页内嵌播放／录音流滑块及静音按钮；**高级混音器**打开 `pavucontrol-qt` 或 `pavucontrol`，用于更多路由和声道调整。面板滑块范围为 0–100%；硬件配置或设备插拔后列表会刷新。监控本身不录制麦克风。

The normal audio list hides disconnected, virtual, monitor and unused raw Pro Audio channels. Default devices and active non-monitor routes remain visible; “Suspended” alone never means disconnected. **Show all audio channels** exposes the full inventory with labels. **Use desktop profile** offers a real available non-Pro profile for the selected card; applying it is explicit and can change its devices. Opening the panel never switches profiles automatically. Refreshes retain selection, keyboard focus and open menus.

普通声音列表隐藏未连接、虚拟、回录和未使用的 Pro Audio 底层通道，保留默认设备与正在使用的非回录通道；不会将“暂停 / Suspended”误判为断开。**显示高级通道**可查看带分类标签的完整列表。选中 Pro Audio 声卡时，**使用推荐桌面模式**提供该卡实际可用的普通模式，需明确点击应用，切换后设备可能变化。打开面板不会自动改声卡模式；刷新保留选择、键盘焦点和展开的菜单。

**Screen** edits Niri settings directly. Choose a connected display and a reported mode, or type a mode such as `1920x1080@60` (`1920*1080@60Hz` also works), then set **Scale** to `100%`. Refresh rates must match the screen's reported modes; for example, choose `59.94` if `60` is not listed. Position, rotation and supported variable refresh rate are available in the same page. Click **Test & apply**, then **Keep** within 15 seconds. **Revert** or timeout restores the previous settings. An independent watchdog keeps the timeout active even if the panel closes or exits.

**屏幕**页直接修改 Niri 配置。选择已连接屏幕及其报告的模式，或输入 `1920x1080@60`（也支持 `1920*1080@60Hz`），再将**缩放**设置为 `100%`。刷新率需匹配显示器报告的模式，例如列表仅有 `59.94` 时请选择该值。位置、旋转和硬件支持的可变刷新率也可在此设置。点击**测试并应用**，在 15 秒内点击**保留设置**；点击**恢复原设置**或超时会恢复原配置。独立后台计时器确保面板关闭或退出后，仍会在超时时自动恢复。

The page writes `niri/conf/display-settings.kdl`, validates the complete Niri configuration, and reloads it. Saved preferences live in `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/display/`. Niri uses the **first matching output rule**, so this generated file is included before `conf/outputs.kdl` and the existing `monitor.kdl`. Hand-edited generated settings are preserved and reported as a conflict.

屏幕页写入 `niri/conf/display-settings.kdl`，校验完整 Niri 配置后重载。偏好记录位于 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/display/`。Niri 采用**首个匹配的屏幕规则**，因此生成文件在 `conf/outputs.kdl` 和已有 `monitor.kdl` 之前加载。手动修改生成文件后，面板会保留改动并提示冲突。

**Interface size has one unit.** The interface font size is a logical pixel value: panel, bar and notification CSS use it directly, GTK/Qt/KDE and the GNOME font name receive the matching point size (16 px → 12 pt at 96 DPI), Fuzzel is pinned with Fontconfig `pixelsize` so no DPI is applied twice, and the terminal keeps its own independent point size. Applying appearance therefore changes GTK/Qt application text to the size the interface actually shows.

**The status bar adapts to the output.** The bar selects a wide or compact module set by *measuring* the worst-case width of every module with Pango at the interface font size (`niri/shell/bar_fit.py`) and comparing it with the narrowest connected output's logical width; the requirement is verified against a real bar by `tools/bar_measure.py`. Its module font sizes scale from the same 12px design base as the panel. Compact keeps the launcher, workspaces, sound, notifications and control centre, shortens the clock to a time, hides empty workspaces, drops the window title and moves the live network rate and monitor figures into tooltips. A bounded network width stops changing rates from pushing the right-hand modules off the output. A hidden `custom/layout` module re-checks every 15 seconds, so an output change is picked up without a new daemon.

**Bit depth depends on the installed Niri build.** This machine's Niri 26.04 parser does not accept `max-bpc`, so the selector is disabled and the driver chooses automatically. A supporting build enables the setting after a parser capability check. `max-bpc 10` is an **upper limit**, not a guarantee of an actual 10-bit link; the GPU, connection and monitor also determine the result.

**位深取决于当前 Niri 版本支持。** 本机 Niri 26.04 解析器不接受 `max-bpc`，因此禁用该选项，由驱动自动选择。支持该配置的版本通过解析能力检查后会启用设置。`max-bpc 10` 表示**位深上限**，不保证链路实际运行在 10 bit；还取决于显卡、接口及显示器。

Maintenance buttons launch the existing controller in a terminal that stays open to show results. **Update performs a full Arch upgrade and asks for pacman's confirmation**. Opening the panel performs no package update.

维护按钮在终端打开现有控制脚本，并保留窗口供查看结果。**系统更新执行完整 Arch 升级，由 pacman 显示事务供确认**。打开控制中心不会自动更新软件包。

The Eww bar uses three bounded layer surfaces and one glass pill per component. Panels, calendar, notifications, launcher and AI share the appearance generator. Nine palettes offer light/dark modes. Surface opacity is adjustable from 20–100%; below 40%, crisp text outlines preserve contrast. Click the right-hand clock to open the calendar.

Eww 顶栏使用三个有界图层，各组件独立成胶囊；面板、日历、通知、启动器与 AI 共用外观生成器。九套配色支持深浅模式，不透明度可调 20%–100%，低于 40% 使用清晰描边提高对比度。点击右侧时间打开日历。

Appearance applies consistently to Niri's accent colors, panels, bar, launcher, notifications, Alacritty and lock screen. Click **Apply** to save; **Defaults** restores the bundled design. The font dialog has contrasting backgrounds, selection states and visible confirmation buttons. Generated files are in `niri/theme/`; preferences are in `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/appearance.json`. Install/update/repair restore saved preferences before validation. Dark and light modes also synchronize GTK/portal preferences, standalone qt6ct settings and KDE application Breeze colors, fonts and icons. Qt 6 uses qt6ct without requiring the Plasma desktop. Original application settings are journaled in `application-theme.json` next to the appearance preferences and restored on uninstall, preserving later user edits. Recognized old Matugen overrides and Plasma-generated Breeze palette imports are backed up and disabled; unrelated custom CSS and colors.css files are preserved. New terminals use the changed font; reopen any already-open AI/shortcut panels to reload their style. If a saved font is not installed, the chooser selects an available fallback.

外观设置统一应用于 Niri 强调色、面板、状态栏、启动器、通知、Alacritty 和锁屏。点击**应用设置**保存，**恢复默认**还原内置设计。字体对话框区分背景、选中项与确认按钮，便于识别和操作。生成文件位于 `niri/theme/`，偏好保存在 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/appearance.json`。安装/更新/修复先在临时副本恢复已保存偏好并校验，成功后提交。深色与浅色模式同时同步 GTK/portal 偏好，以及 qt6ct 和 KDE 应用的 Breeze 配色、字体和图标。Qt 6 使用独立的 qt6ct 平台插件，不依赖 Plasma 桌面；安装/修复不会引入 plasma-integration。原应用设置备份在外观偏好旁的 `application-theme.json`，卸载时恢复，并保留后续手工修改。能明确识别的旧 Matugen 配色覆盖与 Plasma 生成的 Breeze 配色导入会备份并停用，避免浅色应用继续使用旧深色配色；其他自定义 CSS 和 colors.css 文件保持原样。已有终端需重新打开；已打开的 AI/快捷键面板也需重新打开以加载新样式。保存的字体未安装时，选择器会回退至可用字体。

Theme application reloads notification CSS and restarts the managed Eww service. Reloads are serialized with theme writes and validate CSS first; stopped or failed services can recover through Super+Ctrl+R. Niri remains running.

Eww 根据显示器宽度选择布局。外观应用先校验 CSS，再重载通知样式并重启托管 Eww 服务；主题写入与重载串行，不重启 Niri。可按 Super+Ctrl+R 恢复已停止或失败的桌面组件。

**Brightness** uses `brightnessctl` for built-in Linux backlights and `ddcutil` for external monitors. Select the screen in **Overview → More controls** before moving its slider. Keyboard brightness keys follow Niri's focused output, with a built-in/sole-device fallback; ambiguous multiple-monitor selection asks you to use the selector. DDC reads are cached for 5 seconds and writes are verified. The P275MV PLUS on DP-6 was successfully queried at 100% through DDC/CI. Enable **DDC/CI** in your monitor's menu if unavailable; errors distinguish unsupported hardware, missing packages, the `i2c-dev` module and I²C access permissions. See [ddcutil permissions](https://www.ddcutil.com/i2c_permissions/) and [brightness value format](https://www.ddcutil.com/command_getvcp/).

**亮度**对内置 Linux 背光使用 `brightnessctl`，对外接屏幕使用 `ddcutil`。先在**总览 → 更多控制**中选择屏幕，再调整亮度。键盘亮度键跟随 Niri 当前聚焦屏幕，必要时回退至内置背光或唯一设备；多个屏幕无法明确匹配时，会提示使用选择器。DDC 读数缓存 5 秒，写入后验证。已通过 DDC/CI 成功读取 DP-6 上 P275MV PLUS 的当前亮度 100%。不可用时请先检查屏幕菜单中的 **DDC/CI**；面板会区分硬件不支持、软件缺失、`i2c-dev` 模块及 I²C 访问权限问题。相关权限和数据格式见上述 ddcutil 官方文档。

Other controls follow hardware/services. Bluetooth needs BlueZ and a controller; Wi-Fi needs NetworkManager. Profiles need optional `power-profiles-daemon`. Unsupported controls are disabled or report an error. The installer does not replace your existing network/power service policy.

其他控件依据硬件及服务状态显示。蓝牙需要 BlueZ 和控制器；Wi-Fi 需要 NetworkManager。电源模式依赖可选的 `power-profiles-daemon`。不支持的控件会禁用或提示原因。安装程序不替换已有网络和电源服务策略。

The default idle timers lock after 5 minutes and turn displays off after 10; edit these in Power & locking. Keep awake pauses those timers. Suspend requests from this project's menu or timer wait for a confirmed lock screen and stop if locking fails. The power submenu (the Power button, the Power & locking page, and Ctrl+Alt+Delete) is a native window with five fixed buttons and no search field at all: logout, reboot and shutdown confirm inside it, so a stray keystroke can no longer filter the list and pick one of them.

External sleep requests use swayidle's `before-sleep` delay, bounded by logind's `InhibitDelayMaxSec`; slow or failed locking cannot cancel an external request. Stay awake's `idle:sleep` inhibitor applies to requests that honor high-level inhibitors. Lid closure can bypass it when `LidSwitchIgnoreInhibited=yes` (the logind default). Administrator bypasses and other programs' power policies are outside this project's guarantee. If lid closure must honor Stay awake, an administrator can review `LidSwitchIgnoreInhibited=no`; this does not make external sleep wait indefinitely for a lock. The installer does not change logind settings. See the [swayidle manual](https://man.archlinux.org/man/swayidle.1.en) and [logind manual](https://man.archlinux.org/man/logind.conf.5.en).

默认空闲 5 分钟锁屏、10 分钟息屏，默认不自动睡眠，可在“电源与锁屏”中修改。全部计时为 0 时显示“计时已关闭”，不表示系统睡眠已经被禁止。

“保持唤醒”会暂停 Niri 计时，并取得实际的 logind `idle:sleep` 阻止型抑制锁；确认取得后才显示“已阻止睡眠”。它适用于遵守高层抑制锁的请求，只持续到关闭开关或退出本次 Niri 会话。管理员可绕过，合盖也可能因 `LidSwitchIgnoreInhibited=yes`（logind 默认值）而忽略此锁；它不能修复显示器或驱动故障。关闭开关恢复已配置的计时；计时全部为 0 则继续保持关闭。保存计时失败会回滚，并提示运行服务是否成功恢复。电源页可查看实际服务状态与配置是否一致。

锁屏按 Wayland 显示会话分别确认 `swaylock --ready-fd` 就绪，并核对进程 PID、启动时间及显示会话。其他会话或未经确认的锁屏进程不能作为当前屏幕已锁定的证据；本项目菜单和自动计时发起的睡眠，在锁屏确认失败时停止。外部睡眠只通过 swayidle 的 `before-sleep` 延迟等待，受 `InhibitDelayMaxSec` 上限约束，慢锁屏或失败无法撤销外部请求。需要合盖遵守“保持唤醒”时，应由管理员检查 `LidSwitchIgnoreInhibited=no`，这仍不保证外部睡眠无限等待锁屏。安装器不会修改 logind 策略。电源子菜单（总览的电源按钮、电源与锁屏页、Ctrl+Alt+Delete）是原生窗口，只有五个固定按钮，完全没有搜索框；注销、重启及关机在窗内二次确认后才执行，不会因为误输入而被筛选选中。

每个 Wayland 显示会话对应一个独立单元 `selandia-lock@<会话>.service`（`./install.sh` 安装；未安装时回退到 `selandia-niri@lock-<会话>.service`）。锁屏客户端因此不属于触发它的 `idle`、`sleep-lock` 或终端，重启这些服务不会结束已确认的锁屏；本项目的任何流程都不会通过结束锁屏来“恢复”。

“保持唤醒”开启时，电源菜单的睡眠项会标注“保持唤醒已阻止睡眠”，选择后先说明原因并直接终止，不锁屏、也不发出睡眠请求；未被阻止时才按“锁屏就绪 → 请求睡眠”的顺序执行，睡眠请求失败会有可见提示。菜单与自动计时共用同一入口。

## Wallpaper playback · 壁纸播放

图片使用必需包 `swaybg`；视频需要可选 AUR 包 `mpvpaper`；Scene 场景和 Web 网页需要可选、实验性的 `linux-wallpaperengine-git` 与正版 Wallpaper Engine `assets`。这些依赖在 [packages.txt](packages.txt) 按“必需 / 可选 / AUR / 实验性 / 硬件可选”声明，安装器的 pacman 事务只读取普通的必需包行。

```bash
paru -S --needed mpvpaper linux-wallpaperengine-git
# 或：yay -S --needed mpvpaper linux-wallpaperengine-git
pacman -Q mpvpaper linux-wallpaperengine-git
command -v mpvpaper linux-wallpaperengine
```

请在自己的终端检查构建内容、确认并输入 sudo 密码，安装后在壁纸页点“重新扫描”。缺播放器时，界面会显示可复制的准确命令，静态预览仍可用。场景/Web 的资源路径可在 Steam → Wallpaper Engine → 管理 → 浏览本地文件中找到；详情见 [安装指南](docs/INSTALL.md)。Web 标为实验性，点击“播放网页壁纸”才执行所选项目的网页脚本；Application 项目仍仅支持静态预览。

当前 `linux-wallpaperengine-git r627.b016d7d1` 原版还有 Web 黑屏缺陷，需要 [安装指南中的兼容修补](docs/INSTALL.md)；仅安装原版包不能证明 Web 可播放。项目提供上游同等的纹理、帧率和退出修补工具，并将 CEF 加载顺序与 Wayland 参数限制在 Web 子进程内。

`ffmpeg` 为官方仓库可选缩略图工具；`nvidia-smi`／`nvidia-utils` 仅适用于 NVIDIA 硬件指标，Intel/AMD 不需要；本机 Intel Arc B580 与 Intel 核显无需安装它。视频、场景和网页的实际兼容性仍取决于播放器、资源和驱动。

壁纸库默认显示 224×126 逻辑像素缩略图的网格，也可切换带缩略图的列表；搜索和选择在两种视图间保持一致。预览按可见区域加载，最多并发三个解码任务。选中不会更换桌面，仍需点击应用。

视频、场景及 Web 壁纸默认开启声音，初始音量 50%。在“设置 → 壁纸”调节音量／静音后点**保存声音**，对所属播放器／CEF 音频流实时生效，保留播放器进程和播放进度。只改静音不会重设在混音器中调过的音量；只改音量也不会覆盖外部静音。新出现的壁纸音频流仅初始化一次。只有音频服务可用性变化、需要改变启动参数时才重启壁纸，重启失败恢复原设置。音频服务探测最多等待 1.5 秒；无服务时继续静音播放并停用引擎的音频探测／录音，音频恢复后再点保存声音。不会修改系统主音量或其他应用的声音。没有音轨的壁纸仍然无声。

本机引擎另需修补 FFmpeg 单声道转双声道的输出缓冲分配问题。可重建修补的软件包，或使用 `.local/wallpaper-engine/` 的项目本地兼容库；本地库只注入壁纸子进程，并核验已安装可执行文件、原库及新库的 SHA256 与架构。软件包升级后不再加载不匹配的本地库；分享包不携带本机编译库。修补与构建方法见 [安装指南](docs/INSTALL.md)。

## AI sidebar · AI 侧栏

**Super+A** opens a configurable text chat sidebar. Five starter connections coexist: Ollama, a relay, Google Gemini, DeepSeek and OpenAI API. Choose a connection, open ⚙, enter its name, provider, base URL, model and key environment variable, then save. You can discover models or enter an exact model name. The + button adds another connection.

**Super+A** 打开可配置的聊天侧栏。内置本地 Ollama、中转站、Google Gemini、DeepSeek 与 OpenAI API 五套独立配置；在顶部切换，点 ⚙ 填配置名称、provider、base URL、模型及密钥环境变量名后保存。模型可查询或手填，+ 可新增配置。

| 配置 | base URL | 密钥环境变量示例 |
| --- | --- | --- |
| Ollama | `http://localhost:11434` | 本地通常留空；启动服务并安装模型 |
| 中转站 | 填该站提供的 HTTPS API 基地址，通常以 `/v1` 结尾 | `RELAY_API_KEY` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` |
| DeepSeek | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| OpenAI API | `https://api.openai.com/v1` | `OPENAI_API_KEY` |

接口遵循官方 [Gemini 兼容接口](https://ai.google.dev/gemini-api/docs/openai)、[DeepSeek API](https://api-docs.deepseek.com/en/)、[OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat) 与 [Ollama chat](https://docs.ollama.com/api/chat)。使用支持文本聊天的模型；ChatGPT 网页订阅与 API 密钥分别配置。

密钥字段只接受环境变量名，**不接受或保存密钥本身**。先关闭已经打开的 AI 侧栏，再在自己的终端设置所需变量并启动侧栏。例如以下命令不把密钥文字写进命令历史或配置文件：

```bash
read -rsp 'Gemini API key: ' GEMINI_API_KEY; printf '\n'
export GEMINI_API_KEY
"${XDG_CONFIG_HOME:-$HOME/.config}/niri/scripts/desktop" ai
```

其他连接可以同样设置各自的变量后，从该终端打开侧栏。变量随启动环境继承；在另一个终端 export 不会改变已经运行的侧栏。密钥未设置时界面会说明缺少哪个环境变量。

对话下拉框切换历史，**新对话**保留旧记录，**删除对话**只删除当前记录；回复可以复制。每个对话保留自己的连接快照，修改服务地址或模型后默认开启新对话，旧历史标注“较早连接”，不会自动发给新服务。关闭侧栏后记录仍在；回复过程中关闭侧栏，后台请求完成后仍会保存该轮。请求失败不会写入半轮对话。

While waiting, click **Stop** or press **Ctrl+.** to cancel the local request. The interrupted turn is discarded and the submitted prompt is restored unless you have typed a new draft. A reply already being saved finishes saving.

等待回复时，点击**停止**或按 **Ctrl+.** 可中止本地请求。该轮不会写入历史；输入框没有新草稿时恢复已发送的问题。已经开始保存的完整回复会正常保存。停止会断开本地请求，服务端是否同时终止计算取决于服务实现。

Profiles and conversations are stored locally with mode 0600 in `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/ai-workspace.json`; legacy `ai.json` is imported without changing the original. Opening or switching the sidebar sends no network request. Only Send/model discovery contacts the chosen server. Remote servers require HTTPS; local loopback HTTP works. This text client does not include streaming, attachments or tool execution.

配置和对话仅保存在上述本机文件（0600 权限），不随分享包导出；旧 `ai.json` 兼容读取并保留原文件。最多 24 套配置、200 个对话，总记录上限 8 MiB；达到上限时明确报错，旧记录保留。打开或切换侧栏不联网，仅发送或查询模型时连接所选服务；远程必须 HTTPS，本地回环可用 HTTP。本轮已移除 CLI 和网页聊天的启动按钮、快捷键与命令别名。

## Customize · 自定义

| File · 文件 | Purpose · 内容 |
| --- | --- |
| `niri/conf/appearance.kdl` | Blur, gradients, spacing, animation · 模糊、渐变、间距、动画 |
| `niri/conf/outputs.kdl` | Displays, scale, mode · 显示器、缩放、模式 |
| `niri/conf/display-settings.kdl` | Screen page's generated output rules, loaded first · 屏幕页生成并优先加载的输出配置 |
| `niri/conf/desktop-settings.kdl` | 控制中心生成的输入及布局配置，最后加载 |
| `niri/conf/language.kdl` | 当前用户会话语言配置，最后加载 |
| `niri/shell/system_settings.py`, `system_controls.py` | 默认应用、电源、时间、服务、启动项和网络设置 |
| `niri/shell/power_menu.py` | Native power submenu: fixed actions, confirmed endings, no search field · 原生电源子菜单：固定操作、二次确认、无搜索框 |
| `niri/shell/language_settings.py`, `language_controls.py`, `i18n.py` | 语言范围、恢复记录及单语言标签 |
| `niri/shell/settings_navigation.py`, `scroll_guard.py` | 分类搜索与滚轮防误操作 |
| `niri/shell/ui_assets.py` | 生成单语言状态栏及通知标签，保留命令和格式占位符 |
| `niri/conf/input.kdl` | Keyboard, pointer, touchpad · 键盘、鼠标、触摸板 |
| `niri/conf/binds.kdl` | Shortcuts and guide source · 快捷键及指南来源 |
| `niri/conf/local.kdl` | Personal overrides · 个人覆盖项 |
| `niri/eww/`, `niri/anyrun/`, `niri/swaync/` | Eww bar, Anyrun launcher, notifications · 顶栏、启动器、通知 |
| `niri/shell/style.css`, `panel.py` | Native panel style and behavior · 原生面板样式和功能 |
| `niri/shell/metrics.py`, `audio_backend.py` | Read-only system metrics and audio device control · 系统监控与声音设备控制 |
| `niri/shell/display_backend.py`, `display_controls.py`, `brightness.py` | Native display configuration, timed rollback and hardware brightness · 原生屏幕配置、限时回滚与硬件亮度 |
| `niri/shell/control_center.css`, `quick_controls.py`, `media_controls.py` | Compact overview and media widgets · 紧凑总览及音乐控件 |
| `niri/shell/media_backend.py` | Selected-player MPRIS controls · 明确音源的 MPRIS 音乐控制 |
| `niri/shell/appearance.py`, `niri/theme/` | Appearance generator and generated component settings · 外观生成器及组件生成配置 |
| `niri/shell/wallpaper.py`, `wallpaper_controls.py` | Local Wallpaper Engine library, optional playback and wallpaper colors · 本地 Wallpaper Engine 资源库、可选动态播放与壁纸取色 |
| `tools/export_config.py`, `docs/INSTALL.md` | Portable share package and installation paths · 可分享配置包及安装路径指南 |
| `niri/shell/reload_components.py` | Serialized component hot reload and service recovery · 组件串行热重载及服务恢复 |
| `niri/theme/alacritty.toml` | Alacritty terminal theme · 终端主题 |
| `niri/assets/selandia-glass.svg` | Original wallpaper · 原创壁纸 |
| `niri/scripts/desktop` | Applications and actions · 应用选择与操作 |

The existing P275MV PLUS 4K / 1.5× default remains in `outputs.kdl`; settings saved by **Control Center → Screen** take precedence. Other displays use automatic selection until configured. Keep personal static defaults in `outputs.kdl` or `monitor.kdl`, and remember that Niri uses the first matching output rule. Let the Screen page manage `conf/display-settings.kdl`.

`outputs.kdl` 保留原 P275MV PLUS 的 4K / 1.5 倍缩放默认规则；通过**控制中心 → 屏幕**保存的设置优先。其他屏幕在未配置前自动选择模式。个人静态默认规则可放在 `outputs.kdl` 或 `monitor.kdl`，注意 Niri 采用首个匹配规则。`conf/display-settings.kdl` 交由屏幕页管理。

The bundled wallpaper is default unless you previously chose one using the picker. Use **Super+Ctrl+T** to change it. Desktop components and GTK/Qt apps share the selected light/dark mode. Applications with their own theme override may require selecting “Follow system” or reopening. Fcitx5 settings are preserved.

默认使用内置壁纸；若先前设置过图片，则保留该选择。用 **Super+Ctrl+T** 打开壁纸资源库。外观页提供可选的“主题配色跟随当前壁纸”，并保留所选明暗模式。桌面组件与 GTK/Qt 应用同步明暗模式；有独立主题设置的应用可能需要选择“跟随系统”或重新打开。保留 Fcitx5 设置。

“声音”页顶部内嵌**应用音量**：播放和录音流分别显示应用名、滑块与静音，实时生效。每两秒只读刷新，拖动时保留当前控件；已退出或被复用的流不会误调其他应用。多个音频流分别显示，支持高级外部混音器入口。

“系统与维护”提供发行版／内核、CPU 型号与物理核／线程／当前频率、内存及 swap 明细、挂载分区、GPU 型号与驱动、全部温度传感器、运行时间、负载和 CPU／驻留内存排序的前八个进程。取不到的读数显示“不可用”或“—”，采样首轮的速率也不伪造为 0；网络文件系统保留条目但不查询容量，以避免挂起。NVIDIA 指标按硬件可选，Intel／AMD 无需 `nvidia-smi`。Intel i915／Xe 支持按需采样可读 DRM 客户端的最忙引擎占比，明确标注覆盖范围，不能当作整卡总利用率；详见 [显卡监控说明](docs/GPU_MONITORING.md)。

当前导航有 **18 个设置页**。通知历史支持本地搜索、分批显示、精确单条删除及清空确认；默认应用、服务、通知和时间设置保留独立草稿。读取任务、媒体事件与硬件采样的资源调度边界见 [日常操作与资源调度](docs/DAILY_USE.md)。

控制中心按屏幕**逻辑尺寸**放大，最大 1600×1120；3840×2160 在 150% 缩放下为 1536×1120。窄屏改用上下导航，宽屏系统指标四列、详细卡片两列，内容超出时滚动。

壁纸音频显式调整失败会显示错误、恢复偏好并尝试恢复实际混音状态；不重播，也不覆盖未修改的音量或静音字段。日常维护与故障恢复见 [维护指南](docs/MAINTENANCE.md)。

## Verification · 验证

```bash
./check.sh --config
python3 -B -m unittest discover -s tests -v
# Opens a temporary nested window / 打开临时嵌套窗口：
dbus-run-session -- python3 -B tools/smoke.py
```

The smoke test uses a private D-Bus, a copied configuration tree, temporary state/cache and in-memory GSettings, renders every surface, exercises panel toggles/search, saves screenshots in `.validation/`, and checks Swaylock readiness. It sends no live AI request and changes no hardware toggles. Results and limits: [VALIDATION.md](VALIDATION.md).

冒烟测试使用独立 D-Bus、配置副本、临时状态/缓存和内存 GSettings，状态栏重生成不会写入正式配置；显示所有组件、测试面板开关/搜索、保存截图至 `.validation/`，并检查 Swaylock 就绪。不会发送真实 AI 请求或切换硬件状态。结果及限制见 [VALIDATION.md](VALIDATION.md)。

- **Panel / 面板：** run `python3 -B niri/shell/panel.py control` in a Wayland terminal; requires GTK3, PyGObject, gtk-layer-shell / 在 Wayland 终端直接运行并检查依赖。
- **Services / 服务：** enter with `niri-session`; inspect `systemctl --user status selandia-niri.target` and `journalctl --user -u selandia-niri@waybar.service` / 使用正式会话并检查日志。
- **Blur / 模糊：** `niri validate -c niri/config.kdl`; requires 26.04+ / 需要 26.04 或更新版本。
- **AI：** select an installed model and correct server base (`/v1` for compatible servers) / 选择已安装模型和正确基础地址。
- **Input/sharing / 输入与共享：** Fcitx5 uses existing settings; sharing needs PipeWire and Niri's GNOME portal / 沿用已有输入法；共享需要 PipeWire 和对应 GNOME portal。

For layout preview, run `niri --config niri/preview.kdl`: Mod becomes Alt, and Alt+Shift+Escape exits. Service actions belong to a real Niri login; use the isolated smoke test for full UI previews.

布局预览可运行 `niri --config niri/preview.kdl`：Mod 为 Alt，Alt+Shift+Escape 退出。服务操作用于正式登录；完整界面预览请使用隔离冒烟测试。

Fcitx5 的输入法进程与配置工具是两个入口。系统包的 `/etc/xdg/autostart/org.fcitx.Fcitx5.desktop` 可由 Niri 会话自动启动输入法，不需要在本项目再添加一份启动项。输入法进程本身带有 `NoDisplay=true`，不会出现在启动器；配置工具可搜索“Fcitx 5 配置”，也可从**键盘与鼠标 → 输入法 → 配置 Fcitx 5 输入法**打开。

电源子菜单短暂独占键盘焦点，避免 Niri 的鼠标跟随焦点使菜单在指针经过前台窗口时关闭；按 Esc 或点击关闭按钮退出。控制中心仍使用按需键盘焦点。关机、重启和注销仍需二次确认。

## Playlists and copyable inventory · 播放集与可复制系统信息

The wallpaper page shows the current wallpaper, its thumbnail, type and live/static mode, with an explicit refresh. “Grid” / “List” share the same library selection. Add/remove selected entries or use the filtered library, then **Save playlist**. Previous/Next act immediately on the saved playlist. Automatic rotation runs in the wallpaper service after this panel closes: sequential or random, every **1–180 minutes**, or at a video's actual end. Random avoids immediate repeats when alternatives exist; Previous follows the configured list backwards. Settings survive service/session restarts. Empty playlists stay idle. Static images and endlessly running scene/Web projects have no end event: use timed switching. Failed entries are logged and skipped; the previous renderer stays until its replacement is ready. Wallpaper color following uses the same theme reload as a manual switch.

壁纸页展示**当前壁纸**的缩略图、标题、类型与 live/preview 模式，可一键刷新。“网格／列表”共享选择；可加入／移出所选壁纸或使用当前筛选结果，修改后点**保存播放集**。上一条／下一条立即切换已保存播放集；自动轮播由常驻壁纸服务执行，关闭面板后继续运行。可选顺序／按权重随机／洗牌不重复、**1 秒–180 分钟定时切换**／视频实际**播完切换**；有其他条目时随机避免连续重复，上一条按列表逆序。配置跨会话保持，空播放集不轮播。静态图片和无限运行的场景／网页没有结束事件，请用定时切换。失败条目会记录并跳过，新渲染器就绪前保留原画面；跟随壁纸配色沿用手动切换的主题重载路径。

System information now presents a selectable, single-column inventory and **Copy system information** copies exactly that text. It includes host/model/mainboard, distribution/kernel/architecture, uptime, shell/desktop/terminal, CPU topology/frequency, GPU/driver, memory/swap/root storage, displays, theme/icons/font, package count, local IP, locale and timezone. It reads proc/sys/etc and native Niri IPC, without requiring fastfetch or lspci; unavailable values are explicit. Live monitoring remains below it.

系统页顶部为可鼠标选择的单栏键值信息，**复制系统信息**复制屏幕上同一份纯文本。覆盖主机／DMI 机型与主板、发行版／内核／架构、运行时间、Shell／Niri 版本／终端、CPU 核数／线程／频率、GPU／驱动、内存／交换／根分区、屏幕分辨率与刷新率、主题／图标／字体、包数量、本地 IP、语言和时区。不依赖 fastfetch 或 lspci；取不到的项显示“不可用”，窄屏自动换行。

## 控制中心视觉与壁纸布局

选中、勾选与按下仍保持圆角。顶栏空隙透出原壁纸，每个胶囊（含控制中心与强调／悬停状态）一起跟随 20–100% 不透明度；低于 40% 使用无模糊描边和无噪点面板图层，不抬高用户选择的表面 alpha。壁纸页顶部保留当前壁纸与刷新，其下为同一页内的左资源库、右设置区（含播放集），中间分隔可拖动，窄屏改为上下排列；设置区靠前是所选预览、显示方式与年龄分级，文件目录、声音和播放集在同页下方滚动可达，没有子页切换。资源库单层滚动，宽窄屏至少显示两行。

Selected, checked and pressed controls keep their rounded corners. All bar pills follow the same 20–100% opacity. Below 40%, crisp text outlines and noise-free panel layers preserve legibility without raising surface opacity. The wallpaper page keeps one scrollable page — library beside settings and playlists on wide screens, stacked on narrow ones — with a draggable divider and no subpage switching, reserving space for at least two complete list rows. See [visual regression maintenance](docs/CONTROL_CENTER.md) for pixel and layout checks.

壁纸支持多个具名播放集、条目排序/启用/权重、洗牌不重复与秒级定时；Everyone / Questionable / Mature 分级及明确显示确认，六种显示模式与静态淡入淡出。操作、后端限制和旧格式迁移见 [壁纸播放集指南](docs/WALLPAPERS.md)。

真实挂起后黑屏尚未复现/定位，隔离锁屏通过不等于硬件恢复正常。证据与下一次操作见 [恢复诊断](docs/RESUME_DIAGNOSTICS.md)。

## Rust 组件与灵动岛

默认顶栏为 Eww：左侧启动器／工作区／当前软件，居中灵动岛，时间与状态项在右侧。应用启动器为 Anyrun，终端为 Alacritty；Waybar／Kitty 已按用户确认移除，Fuzzel 仅用于 dmenu。全部主题由现有外观生成器统一生成，20–100% 不透明度与减少动态效果继续有效。安装、组件取舍及回滚见 [Rust 组件指南](docs/RUST_COMPONENTS.md)。休眠黑屏尚未能复现或定位，不用隔离测试代替硬件结论。

旧组件已按本次明确授权清理；历史故障演练与 PAM 解锁记录保留。离线恢复本地签名包与源码的方法见恢复文档。残留非 Rust 部件和移除条件见 [应急组件](docs/EMERGENCY_COMPONENTS.md)。`./check.sh` 的单元阶段由 `tools/run_tests.py` 创建私有总线、状态和运行目录，测试不能使用正式壁纸服务。

## 2026-10-11 · 已替代组件清理

用户确认日常组件基本可用后，移除 Waybar、Kitty（含 kitty-shell-integration、kitty-terminfo）及其配置、主题生成分支、启动入口和专用测试。日常顶栏 Eww、应用启动器 Anyrun（含 provider）、终端 Alacritty 现在是必需依赖；缺依赖时安装器停止部署并显示确切命令，不再静默降级。Fuzzel 仍负责剪贴板与确认菜单；通知、静态壁纸、空闲和锁屏服务保持稳定。点击右侧时间打开独立日历，时间设置仍在控制中心。

`selandia-niri@waybar.service` 只是兼容单元名称，运行 Eww；不需要 Waybar 软件包。清单见 [Rust 组件](docs/RUST_COMPONENTS.md)，离线恢复见 [恢复方法](docs/EMERGENCY_COMPONENTS.md)。

## 2026-10-11 · 当前软件与紧凑顶栏

Eww 左侧恢复当前软件显示：优先采用已安装 `.desktop` 的软件名，无法匹配时显示 app_id 的末段；XWayland 无 app_id 时显示窗口标题。随焦点轮询刷新，悬停显示完整标题；长名称在现有左侧空间里截断，无窗口时显示“桌面”。新标签仍支持中英文，软件名与标题作为普通文本处理。

灵动岛以外的胶囊采用紧凑椭圆轮廓，高度与收起的灵动岛一致。现有按钮横向内边距、三段布局、居中岛与右侧时间保持；点击时间仍打开日历。字体、透明度和减少动态效果继续由统一外观生成器控制。

## 2026-10-28 · MD3 交付验收

- 架构实现：控制中心维持普通浮动对话框层叠形态，17 项分类划分为 4 组（默认应用与语言归入 System），左侧为 AI 抽屉（宽 440）、右侧为 Calendar 抽屉（宽 420）；共享 MD3 角色与圆角规范、草稿支持、未访问页面按需懒加载缓存、隐藏期间挂起只读活动，后台 worker 线程池上限为 3。外观动态继承用户偏好（font13/.92 仅为审计配置，非系统默认）。
- 通知视觉对齐：通知视觉对齐已落实，外宽 420px（内部 386px + 内边距 32px + 边框 2px），顶部除合成器预留顶栏外追加 12px 间隙；最终原生验证记录于 DELIVERY.md。
- 验收证据：
  - 单元测试（2026-10-25）运行 919 项，0 失败、0 错误、1 跳过；原生面板交互 107 项（2026-10-27）全绿通过（27.874s）；10 项专用原生用例覆盖当前中文 font13 日历、2 项动效几何、Quick 懒加载冷启、Media 隐藏跟随、壁纸积压/跟随及 Calendar font20 常规/窄屏/短视口。
  - 受控资源 A/B 基准（.staging/md3-shell-20261020/validation/artifacts/resource-20261027-013055-42e0）：每分支 60 轮（Control/AI/Calendar 各 20 轮），首映射耗时基线 0.115762s vs 暂存 0.048003s；最终关闭 RSS 为 249736 KiB vs 151420 KiB；测量基于受控夹具（非真实空闲或零泄漏证明，指标为上下文切换而非系统唤醒）。
  - 全量集成（.staging/md3-shell-20261020/validation/artifacts/integration-20261027-224302-f606d455f6f54e1caadbdeaef67dd604）：总历时 93.458s PASS，产出 27 张全新 PNG 截图，覆盖 17 项设置与全部菜单/抽屉；包含隔离会话中的显示设置独立回退看门狗、私有字体选择器、锁屏就绪（无 PAM）、6 次私有顶栏重载；源码 148 项与用户偏好保持未修改。真实 Chrome 最大化/标题栏恢复/全屏与弹窗（通过模拟授权，非真实 Polkit）详见 AUDIT_NOTES。
- 发布状态：2026-10-28 MD3 交付版本；实际发布状态、最终验收及导出结果以 .validation/md3-20261028-release/DELIVERY.md 为准。
