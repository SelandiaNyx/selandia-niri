# Validation · 验证记录

Arch Linux · Niri 26.04 (8ed0da4).

## 2026-10-05：A1–A8 自检问题整改

按 [.validation/PROJECT_AUDIT.md](.validation/PROJECT_AUDIT.md) 的交接要求完成 A1–A8 与测试覆盖缺口，逐项实现、测试与未验证项见 [.validation/FIXES.md](.validation/FIXES.md)，本轮实测数据见 [.validation/fix-summary.json](.validation/fix-summary.json)。

- **490 项单元测试通过**（1 项按设计跳过）：[完整日志](.validation/fix-unit.log)。新增或重写的覆盖包括锁屏就绪协议与启动器选择、面板提交任务生命周期、读取期间冻结草稿、统一睡眠入口、快捷键单语言与 Fuzzel placeholder、符号图标在 100%/150%/200% 的透明渲染、状态栏宽/紧凑布局与合法 GTK CSS、界面字号 px→pt 换算、界面文案语言矩阵、状态栏日志归因。
- **`./check.sh --config` 通过**：[日志](.validation/fix-check.log)（Niri 配置、Fuzzel 配置、JSON、Shell/Python 语法、GTK 3/4 样式）。
- **完整 `./check.sh` 在本沙箱不可用**：[日志](.validation/fix-check-full.log)。唯一失败原因是无法连接用户 systemd（`Failed to connect to user scope bus via local transport`），因此组件状态、`selandia-lock@.service` 的真实 cgroup 生命周期以及嵌套 Niri 冒烟测试（本沙箱嵌套 Niri 启动即 `PermissionDenied`）均**未在本环境验证**，已在 FIXES.md 与 fix-summary.json 的 `verification_limits` 中明确列出。
- 未执行真实睡眠、未杀主桌面锁屏、未改动音频枚举、三个真实输出设备或用户偏好；未修改 `/usr/share/icons`。用户自定义 GTK CSS（含 `@import 'colors.css'`）保持原样，浅色整机一致性仍需在私有配置副本中单独核验。

## 2026-10-04：闲置后无信号调查与电源逻辑修正

此前的界面及嵌套桌面测试**没有验证本机长时间闲置后的真实睡眠/硬件唤醒**，不能据此认定电源与锁屏完整正常。本次调查记录和时间线见 [power-incident.md](.validation/power-incident.md)。最相近的 10 月 3 日凌晨记录中，后台日志整夜持续、没有挂起入口，Niri 记录 DP-6 断连及 DRM page-flip 错误；尚未确认这就是用户所指事件，也未确定显示器、连接链路、驱动或合成器中的责任。

已修复：全部计时关闭被误标“保持唤醒”；从全部关闭重新开启计时不能启动服务；服务应用失败未回滚；不同 Wayland 会话的 swaylock 被当作当前桌面已锁定。新增真实 logind 抑制锁及准确状态显示，以及锁屏时可用的电源键短按 / Super+Ctrl+F12 亮屏请求。

验证：**372 项单元测试通过**（[日志](.validation/power-final-unit.log)）；**52 项 GTK 交互测试通过**（[日志](.validation/settings-panel.log)）。独立 Niri 中实际确认了新的锁屏就绪握手、显示会话/PID 身份和重复锁屏复用（[日志](.validation/power-lock-probe.log)）。没有主动对主机执行锁屏、息屏、挂起或休眠试验。

当前主机三项计时仍为用户保存的 0，未重新启用；已启用本次 Niri 会话的保持唤醒保护，并通过 logind 确认 `Selandia Niri` 持有 `sleep:idle` 的 `block` 抑制锁，服务随 Niri 目标和图形会话结束。该保护不等于修复显示器恢复故障，管理员操作也可绕过。

## 2026-10-04：最终集成验证

- **345 项单元测试通过**：[完整日志](.validation/settings-final-unit.log)。包含配置部署保护、控制脚本生命周期、三个语言范围、原生输入与窗口配置、音频、屏幕回滚，以及 BlueZ 启动策略的备份和认证取消处理。
- **47 项真实 GTK 交互测试通过**：检查下拉框内部按钮、动态添加的输入框、聚焦后的数字框及滑块滚轮事件；选择后显式应用；切换语言重建窗口并保留当前分类；蓝牙启动设置等待明确应用且认证失败可重试。
- **4 项真实 MPRIS 集成检查通过**，所有 16 个设置分类完成中文界面渲染。字体对比度、显示配置确认/回滚及独立超时恢复、连续六次状态栏与通知重载、锁屏就绪均通过：[隔离桌面日志](.validation/settings-final-smoke.log)。
- 主机会话完成桌面重载及完整 `check.sh` 自检：[最终自检日志](.validation/settings-final-check.log)。状态栏与通知使用新生成的单语言配置，时钟选择已安装的对应语言区域。
- 只读核对确认音频仍为 **3 个输出**：HDMI、XIBERIA S21 MAX USB 设备、主板模拟输出。保留其他 AI 修改后的音频配置，没有更改设备枚举、配置档案或默认路由。
- 按用户要求将 `/etc/bluetooth/main.conf` 的 `[Policy] AutoEnable` 设为 `false`，备份为 `/etc/bluetooth/main.conf.selandia-20261003T140704536924Z`。10 月 4 日的新会话中 BlueZ 控制器仍为关闭状态。设置过程未重启蓝牙服务。

主机的分辨率、输入设置、默认应用、用户/系统语言、时区和睡眠计时未被测试改动；相关写入使用临时配置、模拟调用或独立合成器验证。打印机、分区管理、防火墙、账户管理和复杂网络设置仍通过明确标识的专用工具入口处理，不能视为完整实现全部 Plasma 设置。

界面预览：[总览](.validation/control.png)、[语言与地区](.validation/language.png)、[网络与蓝牙](.validation/network.png)。

## 2026-10-03：分类设置与语言切换

控制中心改为目标 960×820 逻辑像素、按屏幕缩小的双栏窗口，左侧搜索 16 个分类，右侧显示详细设置。界面一次显示中文或英文；语言页分别管理界面、终端与用户会话、系统默认语言。输入与窗口设置使用原生 Niri 配置；默认应用、电源计时、时区/时间同步、启动项、桌面服务、已保存网络连接提供原生操作。打印机、分区、防火墙、完整账户管理和复杂网络配置仍使用明确标识的独立工具入口。

本轮设置后端与标签生成的专项检查已完成 **36 项单元测试**：13 项系统设置、21 项系统监控、2 项单语言组件生成。日志：[settings-review-unit.log](.validation/settings-review-unit.log)。新增覆盖包括：

- 电源计时范围与先锁屏再睡眠、保留原始配置、保存后仅重启已运行的空闲服务。
- 服务操作限制于本桌面的用户单元，正确区分目标启动的静态服务与已屏蔽服务。
- 时区与网络时间的交互认证参数、默认应用 MIME 类型、网络连接 UUID 校验，以及中文和转义后的连接名。
- 启动项仅用于 Niri，保留原应用文件；注释中的托管标记不能授权覆盖文件，符号链接及非托管项目拒绝修改。
- 状态栏与通知只替换已有界面标签；保留执行命令、格式占位符、硬件名称及源配置模板。监控提示切换语言时保留用户数据。

这些测试使用临时文件和模拟系统调用，没有修改主机默认应用、网络连接、时区、语言或空闲行为。下方结果属于较早版本，不能作为此次 16 类窗口的集成验证结果。最新整体验证由本轮单独的运行日志记录。

滚轮策略为：未展开的下拉框、数值框与滑块上的滚动转发到页面，聚焦后仍不改变数值；拖动、方向键、展开后的选项菜单保留正常操作。异步读取或保存期间表单暂时禁用，避免新输入被迟到的结果覆盖。真实 GTK 事件及完整桌面渲染需要以本轮面板与冒烟日志为准。

## 历史结果（2026-10-02 及以前）

## Control Center redesign · 控制中心重构

The compact overview and selected-player music controls passed **212 unit tests, 29 real GTK interaction tests and 4 real MPRIS D-Bus integration checks**. Full `check.sh` and private desktop smoke pass. All five settings pages, font chooser, native display rollback and six repeated bar reloads remain covered.

紧凑总览与明确音源的音乐控件通过 **212 项单元测试、29 项真实 GTK 交互测试，以及 4 项真实 MPRIS D-Bus 集成检查**。完整 `check.sh` 和隔离桌面冒烟通过；五个设置页面、字体选择器、原生屏幕回滚及连续六次状态栏重载也继续通过。

- Single-track playback with no previous/next support can pause and resume through explicit methods. / 单曲且不能前后切歌时，可以通过明确的方法暂停和继续播放。
- GUI source selection, stale asynchronous reads, action failures and retry are exercised. / 已验证界面音源选择、过期异步读取、操作失败与重试。
- Player instance ownership is checked before every command; disappearing/restarted players cannot redirect it. / 每次操作检查播放器实例，关闭或重启不会使命令误发给其他播放器。
- At the default font and a 480×760 logical viewport, primary controls and footer fit without scrolling. A smaller real preview keeps the window within the screen and displays media, volume and brightness first; further controls scroll. / 默认字体和 480×760 逻辑视口下，主要控件及底部操作无需滚动；更小的真实预览中面板保持在屏幕内，优先显示音乐、音量及亮度，其余控件可滚动查看。

Read-only host inspection found Chromium reporting Playing while its browser integration reported Paused. The new backend reads each player's metadata and status together and pins actions to the selected instance. All playback mutations in validation used private fake players; the user's real music was not paused or resumed. Screenshots use a clearly named single-track test player and preserve the user's generated theme.

只读检查发现 Chromium 报告正在播放，而浏览器集成报告已暂停。新后端一起读取每个播放器的元数据与状态，并将操作固定到所选实例。验证中的播放状态变更均针对隔离的模拟播放器，没有暂停或继续用户的实际音乐。截图使用明确标注的单曲测试播放器，并保留用户生成的主题。

[Overview preview · 总览预览](.validation/control.png) · [Appearance preview · 外观预览](.validation/appearance.png)

Logs / 日志：`.validation/control-redesign-unit.log`、`.validation/control-redesign-smoke.log`、`.validation/control-redesign-check.log`。Design references / 设计参考：[Apple Control Center](https://support.apple.com/en-in/guide/mac-help/mchl50f94f8f/26/mac/26)、[GNOME Quick Settings](https://gjs.guide/extensions/topics/quick-settings.html)、[Noctalia](https://docs.noctalia.dev/noctalia/control-center/)。

## Display and brightness fixes · 屏幕与亮度修复

This revision addresses external-monitor brightness, Control Center focus, font-dialog contrast, native display configuration and the status bar disappearing after repeated appearance changes. Integration checks passed. Waybar and notifications were recovered in the current session, followed by a successful full `check.sh`; earlier results below are historical.

本轮修复外接屏幕亮度、控制中心焦点、字体对话框对比度、原生屏幕设置，以及多次应用外观后状态栏消失的问题。集成验证已通过，已恢复当前会话中的状态栏和通知服务，随后完整 `check.sh` 通过；下方旧记录保留作为历史结果。

| Check · 检查 | Current result · 当前结果 |
| --- | --- |
| Full unit suite · 完整单元测试 | **190 passed / 190 项通过** |
| Real GTK interactions · 真实 GTK 交互 | **23 passed / 23 项通过**; separate native font chooser contrast and selection probe also passes / 独立字体对话框对比度与选择测试亦通过 |
| Full `check.sh` · 完整配置及依赖自检 | **PASS / 通过**, including managed session services / 包含托管会话服务 |
| Private desktop smoke and screenshots · 隔离桌面冒烟及截图检查 | **PASS / 通过**, five Control Center pages and font dialog / 五个控制中心页面及字体对话框 |
| Native display transaction · 原生屏幕事务 | **PASS / 通过**, actual nested Niri apply, persist, revert and watchdog timeout / 实际嵌套 Niri 应用、保存、恢复和计时回滚 |
| Repeated theme reload · 连续主题重载 | **6 consecutive reloads passed / 连续 6 次通过**, Waybar remains visible / 状态栏保持显示 |
| Isolated brightness tests · 隔离亮度测试 | **16 passed / 16 项通过** |
| Real DDC/CI read/write · 实际 DDC/CI 读写 | P275MV PLUS · DP-6 · I²C 29 · **100%**, verified write at the existing value / 按当前值写入并验证成功 |

Brightness tests cover exact DRM-to-I²C selection, real VCP ranges, legitimate zero brightness, cache isolation, missing tools/module/permissions, unplugging, monitor replacement and bus changes before writes, failed requests/timeouts, built-in backlight and focused-output keyboard selection. Unit tests use fake devices. The real backend returned `current=100`, `maximum=100`, `available=true`; `ddcutil --noconfig --bus 29 --verify setvcp 10 100` then succeeded, preserving the existing brightness.

亮度测试覆盖 DRM 接口与 I²C 总线准确匹配、真实 VCP 范围、零亮度、缓存隔离、依赖/模块/权限缺失、拔屏、更换屏幕、写入前总线变化、请求失败与超时、内置背光及按聚焦屏幕选择亮度键目标。单元测试使用模拟设备。实际后端返回 `current=100`、`maximum=100`、`available=true`；随后成功执行上述带验证的写入命令，保持原有亮度。

The Screen page writes validated Niri output rules before existing defaults, because Niri uses the first matching rule. The implementation includes 15-second keep/revert with a detached rollback watchdog. The installed Niri 26.04 rejects `max-bpc`; the UI disables bit-depth selection and explains the limit. Supporting builds can set a maximum, which does not certify actual link depth.

屏幕页写入并校验原生 Niri 输出规则，将其放在默认配置之前，因为 Niri 使用首个匹配规则。实现包含 15 秒保留/恢复及独立回滚计时器。当前 Niri 26.04 不接受 `max-bpc`，因此界面禁用位深选项并说明原因；支持该功能的版本可设置位深上限，但不能据此认定实际链路位深。

The 26 display regression tests include validation against the installed Niri parser and rollback after the parent process exits. A disposable compositor separately verified actual scale changes, persistence and rollback; the host monitor remained at 3840×2160@160 Hz, 150% scale. GTK checks cover on-demand keyboard mode, visible confirmation controls, timeout handling and coalesced brightness writes. The native font chooser passed text contrast ≥4.5:1, visible action labels and selection roundtrip checks; its screenshot was captured after mapping and focusing the real dialog.

26 项屏幕回归测试包含当前 Niri 解析器校验，以及父进程退出后的自动回滚。独立嵌套合成器另行验证实际缩放切换、持久化和恢复；主机显示器保持 3840×2160@160 Hz、150% 缩放。GTK 测试覆盖按需键盘焦点、可见的确认控件、超时处理及亮度写入合并。原生字体选择器通过文字对比度 ≥4.5:1、操作标签可见性和字体选择回传检查；截图在实际对话框映射并聚焦后生成。

New previews inspected / 已检查的新预览：[displays.png](.validation/displays.png)、[font-dialog.png](.validation/font-dialog.png)。

Current run logs / 本轮日志：`.validation/recovery-unit.log`、`.validation/recovery-smoke.log`、`.validation/recovery-check.log`、`.validation/font-probe.log`、`.validation/display-probe.log`。

## Earlier validation · 历史验证

The following results were recorded on 2026-10-01, before the current fixes.

以下结果记录于 2026-10-01，早于本轮修复。

The rebuilt desktop passed configuration, dependency, automated behavior, and nested rendering checks. No package installation or hardware toggling was performed during validation. Existing configuration links already point at this workspace; bar/notification/wallpaper processes load changed styles when reloaded with **Super+Ctrl+R**.

重建后的桌面已通过配置、依赖、自动化行为及嵌套显示检查。验证过程没有安装软件包或切换硬件状态。已有配置软链接指向本工作区；状态栏、通知及壁纸进程可通过 **Super+Ctrl+R** 重载新样式。

Installer repair, 2026-10-01 16:37 CST: corrected the missing-file/user-edit distinction. All **38 unit tests** pass (25 deployment/setup + 13 shell-data tests). Re-ran the real `./install.sh` successfully, restored the missing portal symlink, and verified every managed target against the manifest. No packages were changed. The GTK import-only check now skips accessibility-bus initialization within that check process.

安装修复，2026-10-01 16:37 CST：修正“文件缺失”与“用户修改”的判断。**38 项单元测试**通过（25 项部署/安装、13 项面板数据测试）。实际重新运行 `./install.sh` 成功，恢复了缺失的 portal 软链接，并核对全部受管理目标与安装记录一致；未修改软件包。GTK 导入检查仅在自身进程内跳过无障碍总线初始化。

Controller revision, 2026-10-01: **77 unit tests pass** (39 controller + 25 deployment + 13 shell-data tests). Covers the bilingual terminal menu, legacy entrypoint, full-upgrade routing, missing package/file repair, damaged Python bootstrap, read-only previews, non-interactive uninstall confirmation, concurrent-operation locking, edit protection, missing-target restoration and rollback, and service-stop failure handling. Package operations and deployment in controller tests use temporary directories and fake tools; backend file operations use temporary configuration trees. On this machine, all four lifecycle dry runs, `control.sh status`, and the full `check.sh` passed. No real package update or uninstall was performed for this revision.

控制脚本改版，2026-10-01：**77 项单元测试通过**（39 项控制脚本、25 项部署、13 项面板数据）。覆盖双语终端菜单、旧入口兼容、完整更新、缺失软件与文件修复、Python 损坏恢复、只读预演、非交互卸载确认、并发锁、修改保护、缺失目标恢复及回滚、服务停止失败处理。控制脚本测试使用临时目录和模拟外部工具；部署后端在临时配置目录中实际操作文件。本机四种管理操作预演、`control.sh status` 和完整 `check.sh` 均通过；本轮未实际更新或卸载软件及配置。

Desktop settings revision, 2026-10-01: **136 unit tests and 18 real GTK interaction tests pass**. New coverage includes CPU/memory/network parsing, counter resets/interface changes, GPU fallback, all three appearance presets, atomic appearance rollback and saved-preference restoration, audio device/profile/port parsing, safe command arguments and partial stream-move failures, controller terminal actions, four-page navigation, font fallback and asynchronous sound/theme controls. GTK mutation tests mock audio and appearance writes; real rendering reads current device state. Niri/Fuzzel, GTK 3/4 CSS, Kitty and shell/Python checks pass. The private desktop rendered all four Control Center pages, launcher, bar, notifications, AI/shortcuts and lock screen; screenshots were inspected. The verified Waybar/notification components were then reloaded in the current session. No package update, recording, hardware profile change or real audio routing change was performed.

桌面设置扩展，2026-10-01：**136 项单元测试及 18 项真实 GTK 交互测试通过**。新增覆盖 CPU/内存/网速解析、计数器重置和网卡变化、GPU 回退、三种主题、外观原子替换及失败回滚、已保存偏好恢复、声音设备/端口/配置解析、命令参数及音频流部分迁移失败、控制脚本终端入口、四页面切换、字体回退和异步声音/外观操作。GTK 操作测试模拟声音及外观写入，实际显示仅读取设备状态。Niri/Fuzzel、GTK 3/4 CSS、Kitty 和脚本校验通过。隔离桌面成功渲染所有控制中心页面及其他组件，已检查截图；随后在当前会话重载状态栏和通知组件。本轮没有更新软件包、录音或更改真实硬件配置/音频路由。

## Earlier passed checks · 历史已通过检查

- **Configuration:** real and preview KDL accepted by `niri validate`; Fuzzel's native configuration checker; Waybar/SwayNC JSON; Bash syntax and ShellCheck; Python compilation; GTK3/PyGObject/GtkLayerShell and SVG loader checks.
- **Theme:** GTK3 panel/Waybar CSS and GTK4 SwayNC CSS parse; Kitty config loads; SVG wallpaper renders. Actual screenshots checked for rounded blur boundaries, notification backgrounds, launcher layout, readable panels and shortcut window height.
- **136 unit tests:** 41 controller, 25 deployment, 13 shortcut/AI transport, 20 monitoring, 17 appearance, 13 audio and 7 desktop action tests. Includes backup restoration, repeat install, interruption rollback, foreign-edit refusal, missing backup handling, deployment locking, package-manager routing, complete default shortcut coverage, comment parsing, environment-only credentials, malformed-key sanitization, provider failures, response parsing and model discovery.
- **18 GTK interaction tests:** successful asynchronous chat/history, search/IME behavior, Control Center tabs, metrics, unavailable readings, display information, appearance apply/reset/failure/font fallback, audio device/port/volume/routing/profile controls. Provider calls and mutations are mocked; GTK widgets and asynchronous callbacks are real.
- **Nested desktop smoke:** private D-Bus and temporary state; Niri, dedicated Kitty, Waybar, SwayNC, Fuzzel, wallpaper, Control Center, shortcut guide and AI sidebar render. Each panel opens and toggles closed; shortcut search works. Swaylock reports lock readiness. Processes are cleaned up on completion/failure.
- **Runtime dependencies:** full `check.sh` passes on this machine. The installer dry run reports all required packages present, so setup currently needs no package update. Bluetooth uses BlueZ D-Bus directly.

- **配置：** 正式和预览 KDL、Fuzzel 原生校验、JSON、Bash/ShellCheck、Python 编译、GTK/GI/LayerShell/SVG 依赖均通过。
- **主题：** CSS、Kitty 和 SVG 解析通过；实际检查了模糊圆角、通知背景、启动器布局、面板可读性及快捷键窗口高度。
- **136 项单元测试：** 包含 41 项控制脚本、25 项部署、13 项快捷键/AI、20 项监控、17 项外观、13 项声音和 7 项桌面入口测试。
- **18 项 GTK 交互测试：** 覆盖异步对话、搜索/输入法、控制中心页面切换、仪表读数、屏幕信息、主题应用/恢复/失败/字体回退，以及声音设备、端口、音量、路由和配置操作。写入及外部调用被模拟，控件和异步回调实际运行。
- **嵌套桌面：** 所有界面成功显示，面板可开关，搜索可用，锁屏返回就绪；测试使用独立 D-Bus 和临时状态，结束后清理进程。
- **运行依赖：** 本机完整自检通过，安装预演显示必需依赖齐全。蓝牙直接使用 BlueZ D-Bus。

## Earlier previews · 历史预览

Generated by `tools/smoke.py` / 由冒烟测试生成：

| Surface · 界面 | Screenshot · 截图 |
| --- | --- |
| Notifications and desktop · 通知及桌面 | [desktop.png](.validation/desktop.png) |
| Launcher · 启动器 | [launcher.png](.validation/launcher.png) |
| Control Center · 控制中心 | [control.png](.validation/control.png) |
| Live system monitor · 实时系统监控 | [system.png](.validation/system.png) |
| Sound devices · 声音设备 | [sound.png](.validation/sound.png) |
| Appearance and fonts · 外观与字体 | [appearance.png](.validation/appearance.png) |
| Shortcut guide · 快捷键指南 | [shortcuts.png](.validation/shortcuts.png) |
| Filtered shortcuts · 快捷键搜索 | [shortcuts-search.png](.validation/shortcuts-search.png) |
| AI sidebar · AI 侧栏 | [ai.png](.validation/ai.png) |

Logs for the 2026-10-01 desktop-settings run: `.validation/desktop-settings-tests.log`, `.validation/desktop-settings-smoke.log`, `.validation/desktop-settings-check.log`. Earlier validation logs remain alongside them. That private session produced expected portal/user-systemd teardown messages. Its bundled panel logs contained no exceptions or critical errors.

2026-10-01 桌面设置验证日志为 `.validation/desktop-settings-tests.log`、`.validation/desktop-settings-smoke.log`、`.validation/desktop-settings-check.log`，保留更早的验证记录。该隔离会话产生了预期的 portal/用户 systemd 退出信息；当次本项目面板日志没有异常或严重错误。

## Practical limits · 实测边界

No live AI account/model request was made, and Codex sign-in was not altered. Configure your provider/model before chat. Actual Chinese input across applications, hardware toggles, suspend/resume, PAM unlock and screen-sharing require normal-session testing. The IME automated check validates event ordering, not a real Fcitx candidate session.

没有调用真实 AI 账号或模型，也没有更改 Codex 登录；聊天前请配置服务及模型。跨应用中文输入、硬件切换、睡眠唤醒、PAM 解锁和屏幕共享仍需在正式会话中体验。输入法自动测试验证事件处理顺序，并非真实 Fcitx 候选词会话。

This desktop has no laptop backlight, but its external P275MV PLUS supports DDC/CI brightness and was successfully read by the new backend. It has no power-profiles service, so that control remains unavailable. Native wallpaper blur is used on supported desktop layers and Kitty. Notification cards use the matching translucent style without forced layer blur, avoiding SwayNC's invisible-margin artifacts. Apple's optical refraction is not implemented.

本机没有笔记本背光，但外接 P275MV PLUS 支持 DDC/CI，新后端已成功读取亮度。本机没有电源模式服务，对应控件仍显示不可用。支持的桌面层及 Kitty 使用原生壁纸模糊；通知卡片使用一致的半透明样式，避免强制层模糊引起的 SwayNC 边距伪影。未实现 Apple 的光学折射。

This machine exposes Intel GPU temperatures but no readable utilization counter; GPU utilization correctly displays `—`. CPU, RAM, disk and network readings were observed in the real preview. Audio device discovery was checked against the running PipeWire server; profile switching and stream migration are covered by mocked tests, without changing the user's sound. Appearance generation and parsing were tested for all palettes; actual theme preferences were not overwritten during validation.

本机 Intel GPU 提供温度但未暴露可读取的占用计数，GPU 占用正确显示 `—`；实际预览中已观察到 CPU、内存、磁盘和网速读数。声音设备发现连接实际 PipeWire 服务验证；配置切换和音频流迁移使用模拟测试，未改变用户声音设置。所有配色均验证生成及解析；验证没有覆盖用户的真实外观偏好。

## Reproduce · 复查

```bash
./control.sh repair --dry-run
./control.sh update --dry-run
./control.sh uninstall --dry-run
./control.sh status
./control.sh check
python3 -B -m unittest discover -s tests -v
# Opens a temporary nested desktop / 打开临时嵌套桌面：
dbus-run-session -- python3 tools/smoke.py
```
