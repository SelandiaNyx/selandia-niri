# Selandia Glass · 澄澈桌面

A complete **Niri 26.04+** desktop for Arch Linux: native frosted glass, a floating status bar, a spotlight launcher, a searchable shortcut library, an AI sidebar, and a hardware-aware Control Center. Choose Chinese or English in Language & region; the interface displays one language at a time.

面向 Arch Linux 的完整 **Niri 26.04+** 桌面：原生毛玻璃、悬浮状态栏、聚焦式启动器、可搜索快捷键库、AI 侧栏，以及能识别硬件状态的控制中心。在“语言与地区”中切换中文或英文，界面一次只显示一种语言。

This directory contains the Niri configuration and its supporting scripts. Desktop settings use Niri's configuration and IPC, Arch packages, Linux hardware interfaces and the current PipeWire session.

本目录存放 Niri 配置及配套脚本。桌面设置围绕 Niri 配置与 IPC、Arch 软件包、Linux 硬件接口及当前 PipeWire 会话实现。

The visual language takes inspiration from Apple's Liquid Glass: translucent charcoal, pearl highlights, cyan/violet gradients, rounded surfaces, and soft shadows. Niri's native **wallpaper blur** is real; Apple's proprietary optical refraction is not reproduced. [Niri background effects](https://niri-wm.github.io/niri/Window-Effects.html) explain the efficient `xray` mode used here.

视觉灵感来自 Apple Liquid Glass：半透明深色、珍珠高光、蓝紫渐变、圆角和柔和阴影。这里使用真正的 Niri **壁纸背景模糊**；并未复刻 Apple 的专有光学折射。[Niri 官方说明](https://niri-wm.github.io/niri/Window-Effects.html)介绍了本项目采用的高效 `xray` 模式。

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
- `~/.config/xdg-desktop-portal/niri-portals.conf`

## Everyday controls · 日常操作

`Super` means the Windows / Meta key / `Super` 即 Windows / Meta 键。

| Shortcut · 快捷键 | Action · 操作 |
| --- | --- |
| **Super+Space** | App launcher · 应用启动器 |
| **Super+/** | Search all shortcuts · 搜索全部快捷键 |
| **Super+I** | Toggle Control Center · 开关控制中心 |
| **Super+A** | Toggle AI sidebar · 开关 AI 侧栏 |
| **Super+Shift+A** | Codex floating terminal sidebar · Codex 浮动终端侧栏 |
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

**Super+I** 或状态栏齿轮打开桌面设置。左侧为可搜索的分类导航，右侧显示详细设置；窗口目标尺寸为 **960×820 个逻辑像素**，并按当前屏幕可用区域缩小。总览保留音乐、网络、音量、亮度等快捷操作，其余设置分成 16 类。点击别的应用即可继续工作，设置窗口可以保持打开。

分类与搜索借鉴 [KDE 系统设置](https://docs.kde.org/trunk_kf6/en/systemsettings/systemsettings/general.html)，总览保留 [Apple 控制中心](https://support.apple.com/en-in/guide/mac-help/mchl50f94f8f/26/mac/26)、[GNOME Quick Settings](https://gjs.guide/extensions/topics/quick-settings.html) 和 [Noctalia](https://docs.noctalia.dev/noctalia/control-center/) 中清楚区分开关与详细设置的做法。本项目仍使用原生 GTK，并围绕 Niri、Arch、当前硬件与服务实现。

面板有 180 ms 淡入淡出、页面交叉渐变和展开动画；**外观 → 减少动态效果**可关闭动效，也遵循 GTK 辅助功能设置。**Ctrl+F** 搜索设置，中英文关键词都可搜索；**Ctrl+1…9** 选择前九类，**Ctrl+Tab / Ctrl+Shift+Tab** 循环切页，**Tab / Shift+Tab** 移动焦点。**F1 / ?** 打开键盘说明。**Esc** 先处理弹出内容或清空搜索，再返回总览、收起更多控制、关闭窗口。

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
| 窗口与工作区 | 间距、默认列宽、居中、边框/焦点环、鼠标焦点、工作区切换行为、光标大小 |
| 默认应用 | 浏览器、邮件、文件管理器、文本、PDF、图片与视频文件关联 |
| 语言与地区 | 独立选择界面语言、终端与用户会话语言、系统默认语言 |
| 电源与锁屏 | 自动锁屏、息屏和睡眠定时；立即锁屏及会话电源操作 |
| 日期与时间 | 时区选择与网络时间同步 |
| 开机启动 | 添加已安装应用，仅在下次登录 Niri 时启动；单独启用或停用 |
| 桌面服务 | 持久开关剪贴板历史、通知和状态栏；清空剪贴板历史 |
| 账户与安全 | 修改当前账户密码，以及已安装的账户、防火墙、密码库工具 |
| 系统与维护 | CPU/内存/GPU/磁盘/网速/传感器监控，Arch 更新、依赖修复、配置自检 |

键盘、鼠标和窗口设置写入 `niri/conf/desktop-settings.kdl`，先校验完整 Niri 配置再保存。该文件最后加载，以覆盖对应的普通输入和布局值；屏幕规则则使用首个匹配项，因此 `display-settings.kdl` 仍最先加载。手动改过的托管配置会提示冲突；控制中心不会覆盖它。

默认应用直接修改 MIME 关联；定时电源设置生成 `niri/swayidle/managed.conf`，保留原始 `swayidle/config`。`0` 分钟表示关闭对应计时器；自动睡眠要求先锁屏。保持唤醒期间保存新计时不会擅自恢复计时服务。启动项写入当前用户的 `autostart/selandia-niri-*.desktop`，仅针对 Niri；本页只管理自己创建的项目。服务开关使用本配置的用户服务，停用后主题重载不会再次启动它。

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

Sound uses PipeWire's PulseAudio interface through `pactl` (`libpulse`). Device selection is staged; click **Use device** or **Apply port** to confirm. Browsing with arrow keys does not change routing; **Route active apps here** explicitly moves existing playback/recording streams. Profiles require **Apply profile** and may change which devices exist; Off disables that card. Unavailable ports/profiles are excluded. **Full mixer & app volumes** opens `pavucontrol-qt` or `pavucontrol` for per-application volume, routing and channel controls. Normal panel sliders use 0–100%; changing a hardware profile or unplugging a device refreshes the list. No microphone recording is performed by monitoring. Command reference: [pactl manual](https://man.archlinux.org/man/pactl.1.en).

声音通过 `pactl`（`libpulse`）连接 PipeWire 的 PulseAudio 接口。选择设备或端口后需点击**设为默认**或**应用接口**，方向键浏览不会改变音频路由；**将运行中的应用切换至此**会明确迁移现有播放/录音流。配置档案需点击**应用设备配置**，切换后设备列表可能变化；Off 会关闭该声卡。不可用的端口和配置不提供选择。**完整混音器与应用音量**打开 `pavucontrol-qt` 或 `pavucontrol`，用于逐应用音量、路由和声道调整。面板滑块范围为 0–100%；硬件配置或设备插拔后列表会刷新。监控本身不录制麦克风。

The normal audio list hides disconnected, virtual, monitor and unused raw Pro Audio channels. Default devices and active non-monitor routes remain visible; “Suspended” alone never means disconnected. **Show all audio channels** exposes the full inventory with labels. **Use desktop profile** offers a real available non-Pro profile for the selected card; applying it is explicit and can change its devices. Opening the panel never switches profiles automatically. Refreshes retain selection, keyboard focus and open menus.

普通声音列表隐藏未连接、虚拟、回录和未使用的 Pro Audio 底层通道，保留默认设备与正在使用的非回录通道；不会将“暂停 / Suspended”误判为断开。**显示高级通道**可查看带分类标签的完整列表。选中 Pro Audio 声卡时，**使用推荐桌面模式**提供该卡实际可用的普通模式，需明确点击应用，切换后设备可能变化。打开面板不会自动改声卡模式；刷新保留选择、键盘焦点和展开的菜单。

**Screen** edits Niri settings directly. Choose a connected display and a reported mode, or type a mode such as `1920x1080@60` (`1920*1080@60Hz` also works), then set **Scale** to `100%`. Refresh rates must match the screen's reported modes; for example, choose `59.94` if `60` is not listed. Position, rotation and supported variable refresh rate are available in the same page. Click **Test & apply**, then **Keep** within 15 seconds. **Revert** or timeout restores the previous settings. An independent watchdog keeps the timeout active even if the panel closes or exits.

**屏幕**页直接修改 Niri 配置。选择已连接屏幕及其报告的模式，或输入 `1920x1080@60`（也支持 `1920*1080@60Hz`），再将**缩放**设置为 `100%`。刷新率需匹配显示器报告的模式，例如列表仅有 `59.94` 时请选择该值。位置、旋转和硬件支持的可变刷新率也可在此设置。点击**测试并应用**，在 15 秒内点击**保留设置**；点击**恢复原设置**或超时会恢复原配置。独立后台计时器确保面板关闭或退出后，仍会在超时时自动恢复。

The page writes `niri/conf/display-settings.kdl`, validates the complete Niri configuration, and reloads it. Saved preferences live in `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/display/`. Niri uses the **first matching output rule**, so this generated file is included before `conf/outputs.kdl` and the existing `monitor.kdl`. Hand-edited generated settings are preserved and reported as a conflict.

屏幕页写入 `niri/conf/display-settings.kdl`，校验完整 Niri 配置后重载。偏好记录位于 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/display/`。Niri 采用**首个匹配的屏幕规则**，因此生成文件在 `conf/outputs.kdl` 和已有 `monitor.kdl` 之前加载。手动修改生成文件后，面板会保留改动并提示冲突。

**Bit depth depends on the installed Niri build.** This machine's Niri 26.04 parser does not accept `max-bpc`, so the selector is disabled and the driver chooses automatically. A supporting build enables the setting after a parser capability check. `max-bpc 10` is an **upper limit**, not a guarantee of an actual 10-bit link; the GPU, connection and monitor also determine the result.

**位深取决于当前 Niri 版本支持。** 本机 Niri 26.04 解析器不接受 `max-bpc`，因此禁用该选项，由驱动自动选择。支持该配置的版本通过解析能力检查后会启用设置。`max-bpc 10` 表示**位深上限**，不保证链路实际运行在 10 bit；还取决于显卡、接口及显示器。

Maintenance buttons launch the existing controller in a terminal that stays open to show results. **Update performs a full Arch upgrade and asks for pacman's confirmation**. Opening the panel performs no package update.

维护按钮在终端打开现有控制脚本，并保留窗口供查看结果。**系统更新执行完整 Arch 升级，由 pacman 显示事务供确认**。打开控制中心不会自动更新软件包。

Appearance applies consistently to Niri's accent colors, panels, bar, launcher, notifications, scoped Kitty and lock screen. Click **Apply** to save; **Defaults** restores the bundled design. The font dialog has contrasting backgrounds, selection states and visible confirmation buttons. Generated files are in `niri/theme/`; preferences are in `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/appearance.json`. Install/update/repair restore saved preferences before validation. Dark and light modes also synchronize GTK/portal preferences and KDE/Qt Breeze colors, fonts and icons. Original application settings are journaled in `application-theme.json` next to the appearance preferences and restored on uninstall, preserving later user edits. Recognized old Matugen GTK color overrides are backed up and disabled; unrelated custom CSS is preserved and reported. New terminals use the changed font; reopen any already-open AI/shortcut panels to reload their style. If a saved font is not installed, the chooser selects an available fallback.

外观设置统一应用于 Niri 强调色、面板、状态栏、启动器、通知、专用 Kitty 和锁屏。点击**应用设置**保存，**恢复默认**还原内置设计。字体对话框区分背景、选中项与确认按钮，便于识别和操作。生成文件位于 `niri/theme/`，偏好保存在 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/appearance.json`。安装/更新/修复在校验前恢复已保存偏好。深色与浅色模式同时同步 GTK/portal 偏好，以及 KDE/Qt Breeze 配色、字体和图标。原应用设置备份在外观偏好旁的 `application-theme.json`，卸载时恢复，并保留后续手工修改。能明确识别的旧 Matugen GTK 配色覆盖会备份并停用，其他自定义 CSS 保留并提示。已有终端需重新打开；已打开的 AI/快捷键面板也需重新打开以加载新样式。保存的字体未安装时，选择器会回退至可用字体。

Theme application hot-reloads Waybar and notification styles without repeatedly restarting their services. Reloads are serialized with theme writes, validate CSS first, and recover stopped/failed managed services. If the bar disappeared after an earlier update, use **Super+Ctrl+R** or `./niri/scripts/desktop theme-reload` to restore it. Any remaining component error appears in the panel.

应用外观会热重载 Waybar 和通知样式，避免连续重启服务触发启动频率限制。重载与主题写入串行执行，先校验 CSS，并恢复已停止或失败的托管服务。如果状态栏因旧版本多次更新而消失，可按 **Super+Ctrl+R**，或运行 `./niri/scripts/desktop theme-reload` 恢复；仍有组件失败时，控制中心会显示具体错误。

**Brightness** uses `brightnessctl` for built-in Linux backlights and `ddcutil` for external monitors. Select the screen in **Overview → More controls** before moving its slider. Keyboard brightness keys follow Niri's focused output, with a built-in/sole-device fallback; ambiguous multiple-monitor selection asks you to use the selector. DDC reads are cached for 5 seconds and writes are verified. The P275MV PLUS on DP-6 was successfully queried at 100% through DDC/CI. Enable **DDC/CI** in your monitor's menu if unavailable; errors distinguish unsupported hardware, missing packages, the `i2c-dev` module and I²C access permissions. See [ddcutil permissions](https://www.ddcutil.com/i2c_permissions/) and [brightness value format](https://www.ddcutil.com/command_getvcp/).

**亮度**对内置 Linux 背光使用 `brightnessctl`，对外接屏幕使用 `ddcutil`。先在**总览 → 更多控制**中选择屏幕，再调整亮度。键盘亮度键跟随 Niri 当前聚焦屏幕，必要时回退至内置背光或唯一设备；多个屏幕无法明确匹配时，会提示使用选择器。DDC 读数缓存 5 秒，写入后验证。已通过 DDC/CI 成功读取 DP-6 上 P275MV PLUS 的当前亮度 100%。不可用时请先检查屏幕菜单中的 **DDC/CI**；面板会区分硬件不支持、软件缺失、`i2c-dev` 模块及 I²C 访问权限问题。相关权限和数据格式见上述 ddcutil 官方文档。

Other controls follow hardware/services. Bluetooth needs BlueZ and a controller; Wi-Fi needs NetworkManager. Profiles need optional `power-profiles-daemon`. Unsupported controls are disabled or report an error. The installer does not replace your existing network/power service policy.

其他控件依据硬件及服务状态显示。蓝牙需要 BlueZ 和控制器；Wi-Fi 需要 NetworkManager。电源模式依赖可选的 `power-profiles-daemon`。不支持的控件会禁用或提示原因。安装程序不替换已有网络和电源服务策略。

The default idle timers lock after 5 minutes and turn displays off after 10; edit these in Power & locking. Keep awake pauses that timer; suspend still waits for a ready lock screen. Logout/reboot/shutdown require confirmation in the power menu.

默认空闲 5 分钟锁屏、10 分钟息屏，默认不自动睡眠，可在“电源与锁屏”中修改。全部计时为 0 时显示“计时已关闭”，不表示系统睡眠已经被禁止。

“保持唤醒”会暂停 Niri 计时，并取得实际的 logind `idle:sleep` 阻止型抑制锁；确认取得后才显示“已阻止睡眠”。它只持续到关闭开关或退出本次 Niri 会话，管理员可绕过，也不能修复显示器或驱动故障。关闭开关恢复已配置的计时；计时全部为 0 则继续保持关闭。保存计时失败会回滚，并提示运行服务是否成功恢复。电源页可查看实际服务状态与配置是否一致。

锁屏按 Wayland 显示会话分别确认 `swaylock --ready-fd` 就绪，并核对进程 PID、启动时间及显示会话。其他会话或未经确认的锁屏进程不能作为当前屏幕已锁定的证据；锁屏确认失败时不执行后续睡眠。电源菜单的注销、重启及关机需要确认。

## AI sidebar · AI 侧栏

**Super+A** opens actual text chat with provider settings, model discovery, multiline input, clearing, and reply copying. Conversations remain in memory and disappear when closed or when you save a different connection. Requests contain only the conversation you enter. Opening the sidebar sends nothing; model discovery contacts the configured server when requested. No model/account is installed automatically.

**Super+A** 打开可实际对话的面板，支持服务设置、模型发现、多行输入、清空及复制回复。对话仅保留在内存，关闭或保存不同连接时清除；请求只包含你输入的会话。打开侧栏不发送数据；手动查询模型才连接服务。不自动安装模型或账号。

| Provider · 服务 | Endpoint example · 地址示例 | Setup · 设置 |
| --- | --- | --- |
| Ollama | `http://localhost:11434` | Start the server, install a model, then select its exact name · 启动服务、安装模型，再选择准确名称 |
| OpenAI-compatible | `http://localhost:1234/v1` or your HTTPS `/v1` base | Text model supporting `/chat/completions` · 使用支持该接口的文本聊天模型 |

For authenticated servers, the **API key environment variable** field takes a name such as `AI_API_KEY`, never the secret itself. Export it in the desktop startup environment and log in again, or open `niri/scripts/desktop ai` from a terminal where it is set. Non-secret settings use `~/.local/state/selandia-niri/ai.json` (respects `XDG_STATE_HOME`). Remote servers require HTTPS; loopback HTTP works. Requests run off the UI thread with a timeout. Tool calling, attachments, and streaming are outside this small text client's scope.

需要认证时，**API key environment variable** 字段填写 `AI_API_KEY` 之类的变量名，而非密钥。可在桌面启动环境导出变量后重新登录，或在已设置变量的终端执行 `niri/scripts/desktop ai`。非敏感设置保存在 `~/.local/state/selandia-niri/ai.json`（支持 `XDG_STATE_HOME`）。远程服务要求 HTTPS，本地回环支持 HTTP。请求在后台线程运行并有超时限制。此轻量客户端不包含工具调用、附件和流式输出。

**Codex** opens the installed CLI in a themed floating Kitty window on the right, using your normal sign-in, settings, and approval behavior. **ChatGPT** opens the web app in your browser. These are launch integrations: built-in chat does not reuse a ChatGPT subscription or extract Codex credentials. See [Codex CLI](https://learn.chatgpt.com/docs/codex/cli), [Ollama chat](https://docs.ollama.com/api/chat), and the [Chat Completions schema](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

**Codex** 在右侧带主题的 Kitty 浮动窗口中打开已安装 CLI，沿用现有登录、配置和审批行为。**ChatGPT** 通过浏览器打开网页。这些是启动集成；内置聊天不复用 ChatGPT 订阅或提取 Codex 凭据。用法见上述官方文档。

## Customize · 自定义

| File · 文件 | Purpose · 内容 |
| --- | --- |
| `niri/conf/appearance.kdl` | Blur, gradients, spacing, animation · 模糊、渐变、间距、动画 |
| `niri/conf/outputs.kdl` | Displays, scale, mode · 显示器、缩放、模式 |
| `niri/conf/display-settings.kdl` | Screen page's generated output rules, loaded first · 屏幕页生成并优先加载的输出配置 |
| `niri/conf/desktop-settings.kdl` | 控制中心生成的输入及布局配置，最后加载 |
| `niri/conf/language.kdl` | 当前用户会话语言配置，最后加载 |
| `niri/shell/system_settings.py`, `system_controls.py` | 默认应用、电源、时间、服务、启动项和网络设置 |
| `niri/shell/language_settings.py`, `language_controls.py`, `i18n.py` | 语言范围、恢复记录及单语言标签 |
| `niri/shell/settings_navigation.py`, `scroll_guard.py` | 分类搜索与滚轮防误操作 |
| `niri/shell/ui_assets.py` | 生成单语言状态栏及通知标签，保留命令和格式占位符 |
| `niri/conf/input.kdl` | Keyboard, pointer, touchpad · 键盘、鼠标、触摸板 |
| `niri/conf/binds.kdl` | Shortcuts and guide source · 快捷键及指南来源 |
| `niri/conf/local.kdl` | Personal overrides · 个人覆盖项 |
| `niri/waybar/`, `niri/fuzzel/`, `niri/swaync/` | Bar, launcher, notifications · 状态栏、启动器、通知 |
| `niri/shell/style.css`, `panel.py` | Native panel style and behavior · 原生面板样式和功能 |
| `niri/shell/metrics.py`, `audio_backend.py` | Read-only system metrics and audio device control · 系统监控与声音设备控制 |
| `niri/shell/display_backend.py`, `display_controls.py`, `brightness.py` | Native display configuration, timed rollback and hardware brightness · 原生屏幕配置、限时回滚与硬件亮度 |
| `niri/shell/control_center.css`, `quick_controls.py`, `media_controls.py` | Compact overview and media widgets · 紧凑总览及音乐控件 |
| `niri/shell/media_backend.py` | Selected-player MPRIS controls · 明确音源的 MPRIS 音乐控制 |
| `niri/shell/appearance.py`, `niri/theme/` | Appearance generator and generated component settings · 外观生成器及组件生成配置 |
| `niri/shell/reload_components.py` | Serialized component hot reload and service recovery · 组件串行热重载及服务恢复 |
| `niri/kitty/kitty.conf` | Dedicated terminal theme · 独立终端主题 |
| `niri/assets/selandia-glass.svg` | Original wallpaper · 原创壁纸 |
| `niri/scripts/desktop` | Applications and actions · 应用选择与操作 |

The existing P275MV PLUS 4K / 1.5× default remains in `outputs.kdl`; settings saved by **Control Center → Screen** take precedence. Other displays use automatic selection until configured. Keep personal static defaults in `outputs.kdl` or `monitor.kdl`, and remember that Niri uses the first matching output rule. Let the Screen page manage `conf/display-settings.kdl`.

`outputs.kdl` 保留原 P275MV PLUS 的 4K / 1.5 倍缩放默认规则；通过**控制中心 → 屏幕**保存的设置优先。其他屏幕在未配置前自动选择模式。个人静态默认规则可放在 `outputs.kdl` 或 `monitor.kdl`，注意 Niri 采用首个匹配规则。`conf/display-settings.kdl` 交由屏幕页管理。

The bundled wallpaper is default unless you previously chose one using the picker. Use **Super+Ctrl+T** to change it. Desktop components and GTK/Qt apps share the selected light/dark mode. Applications with their own theme override may require selecting “Follow system” or reopening. Fcitx5 settings are preserved.

默认使用内置壁纸；若先前通过选择器设置过图片，则保留该选择。用 **Super+Ctrl+T** 更换。桌面组件与 GTK/Qt 应用同步明暗模式；有独立主题设置的应用可能需要选择“跟随系统”或重新打开。保留 Fcitx5 设置。

## Verification · 验证

```bash
./check.sh --config
python3 -B -m unittest discover -s tests -v
# Opens a temporary nested window / 打开临时嵌套窗口：
dbus-run-session -- python3 -B tools/smoke.py
```

The smoke test uses a private D-Bus and temporary state, renders every surface, exercises panel toggles/search, saves screenshots in `.validation/`, and checks Swaylock readiness. It sends no live AI request and changes no hardware toggles. Results and limits: [VALIDATION.md](VALIDATION.md).

冒烟测试使用独立 D-Bus 和临时状态，显示所有组件、测试面板开关/搜索、保存截图至 `.validation/`，并检查 Swaylock 就绪。不会发送真实 AI 请求或切换硬件状态。结果及限制见 [VALIDATION.md](VALIDATION.md)。

- **Panel / 面板：** run `python3 -B niri/shell/panel.py control` in a Wayland terminal; requires GTK3, PyGObject, gtk-layer-shell / 在 Wayland 终端直接运行并检查依赖。
- **Services / 服务：** enter with `niri-session`; inspect `systemctl --user status selandia-niri.target` and `journalctl --user -u selandia-niri@waybar.service` / 使用正式会话并检查日志。
- **Blur / 模糊：** `niri validate -c niri/config.kdl`; requires 26.04+ / 需要 26.04 或更新版本。
- **AI：** select an installed model and correct server base (`/v1` for compatible servers) / 选择已安装模型和正确基础地址。
- **Input/sharing / 输入与共享：** Fcitx5 uses existing settings; sharing needs PipeWire and Niri's GNOME portal / 沿用已有输入法；共享需要 PipeWire 和对应 GNOME portal。

For layout preview, run `niri --config niri/preview.kdl`: Mod becomes Alt, and Alt+Shift+Escape exits. Service actions belong to a real Niri login; use the isolated smoke test for full UI previews.

布局预览可运行 `niri --config niri/preview.kdl`：Mod 为 Alt，Alt+Shift+Escape 退出。服务操作用于正式登录；完整界面预览请使用隔离冒烟测试。
