# 修复报告：A1–A8 与测试覆盖缺口

> **第二轮（获得完整权限后）**：真实用户 systemd 与嵌套合成器均可用，因此上一轮列为"未验证"的项目已逐项实测，并因此发现并修复了 3 个**只有真实环境才会暴露的缺陷**。要点：
>
> | 项 | 真实环境结果 |
> | --- | --- |
> | A1 | 发现 `unit_loaded()` 用 `systemctl show <模板>` 探测，在 systemd 262 下**永远返回 False** → 生产路径会把组件服务里的锁屏拒绝、在终端里静默走不安全直启。改用 `systemctl cat` 后，`tests/test_lock_isolation.py` 在真实用户管理器上**3/3 通过**：两个触发服务各自从 `.service` cgroup 发起锁屏，锁屏落在 `selandia-lock@<key>.service` 自己的 cgroup，第二次复用同一进程，触发单元退出后锁屏存活，不同显示会话互不影响 |
> | A2 | GTK 交互测试发现 `Tasks.finish_requested` 是**粘性**标志：窗口销毁后不再复位，导致此后每个提交任务结束都调用 `quit()`（探针观察到 4 次误调用）。新增 `Tasks.resume()`，新窗口出现即撤销退出请求 |
> | A7 | 同轮的 GTK 探针还发现 `appearance.render_files()`（纯渲染函数）会通过 `bar_layout.select()` **调用 `niri msg` 子进程**，在被 mock 的上下文里直接失败。布局改为显式入参/从已生成配置读取，渲染重新变为纯函数 |
> | A3 | 新增 `tools/bar_measure.py`：在私有嵌套会话里对"有栏/无栏"两张截图做差分取栏面包围盒，用**边距是否保留**判定裁切。实测：compact 阈值 773 逻辑像素（@16px；733/750 被裁切，773/800 正常），wide 在 1700 逻辑像素已放得下；审计报告的 **1066 逻辑像素 → compact，左右边距 18/17 保留**；**3840 逻辑像素 → wide，18/18** | 
> | A4 | 嵌套会话截图与像素统计：150% 下系统 Breeze 图标 44×44 全不透明 → 项目图标 36×36、透明 712 / 抗锯齿 92 |
> | A5 | `notifications-center.png` 现在**真的显示通知中心**（通知/清空/勿扰/卡片）。此前 `--hide-all` 先执行会清掉卡片，所以旧顺序永远拍不到要验证的东西——这是审计第 1 条缺口的真正原因。第三方英文 "Now" 已确认是**上游不可配置**（swaync 0.12.6 无 gettext 翻译、无 `.mo`、无 time-format 键） |
> | A8 | 真实部署文件已验证：`gtk-3.0/settings.ini`、`gtk-4.0/settings.ini`、`kdeglobals`、`qt6ct.conf` 四处界面字号均为 **12pt**（=16px），终端固定字号仍为独立的 **16pt** 未被换算 |
>
> 同轮还修好：状态栏 `#network`/`#custom-system`（10px）与 `#window`/`#pulseaudio`/`#battery`（11px）在样式表里是**固定 px**，`#id` 优先级高于生成的 `* { font-size }`，导致界面字号对这些模块完全无效 —— 现按面板同样的 `design × size / 12` 规则缩放。`check.sh` 现在会运行单元测试（`--config` 保持轻量，另有 `--tests`），并新增文档链接守卫与部署源文件漂移守卫。**`./check.sh` 在真实会话中完整通过（exit 0）**，521 项单元测试通过。
>
> 仍未验证：浅色整机一致性（用户自定义 GTK CSS 含 `@import 'colors.css'`，未删除未修改）、真实硬件睡眠/整夜息屏/PAM 解锁。

对应 [PROJECT_AUDIT.md](PROJECT_AUDIT.md)。本轮只围绕 Arch + Niri，未改动 `/usr/share/icons`、音频枚举、三个真实输出设备或用户偏好；未执行真实睡眠、未杀主桌面锁屏、未重置用户设置。项目目录当前没有可用的 Git 仓库，因此“每项单独提交”以“每项独立实现 + 独立测试文件 + 独立证据”体现。

工作副本：`/home/SelandiaNyx/Selandia's Niri`（`~/.config/niri` 是本目录的符号链接，源码改动即时生效；需要重新生成的 systemd 单元除外）。

## 证据索引

| 文件 | 内容 |
| --- | --- |
| [fix-unit.log](fix-unit.log) | 521 项单元测试全部通过（1 项按设计跳过） |
| [fix-check.log](fix-check.log) | `./check.sh --config` 退出码 0 |
| [fix-check-full.log](fix-check-full.log) | `./check.sh` 完整运行：唯一失败来自本沙箱无法连接用户 systemd（`Failed to connect to user scope bus`） |
| [fix-summary.json](fix-summary.json) | 本轮修复后的实测数据（图标像素统计、布局选择、字号换算、快捷键统计） |
| [fix-keyboard-icon.png](fix-keyboard-icon.png) | 键盘图标 100%/150%/200% 修复前（左）与修复后（右）对比 |
| [icon-keyboard-zoom.png](icon-keyboard-zoom.png) | 项目内 SVG 放大渲染，轮廓与按键可辨 |
| [verify-fixes.py](verify-fixes.py) | 生成上述数据的只读脚本 |

## A1 · 锁屏进程与触发服务的 cgroup 隔离

**实现**：把就绪握手移入独立进程 `niri/shell/lock_client.py`，由按 Wayland 显示会话命名的 systemd 单元启动：

- 新增 `systemd/selandia-lock@.service.in`（`Type=notify`、`PartOf=graphical-session.target`、`StartLimitIntervalSec=0`），由 `tools/deploy.py` 生成并加入托管清单/必需源文件。
- `niri/scripts/components` 新增 `lock-*` 分支，作为**已部署模板的回退路径**：`selandia-niri@lock-<key>.service` 同样是独立单元，因此即使尚未重新安装也立即具备隔离能力。
- `lock_session.py` 只负责：互斥、请求文件、启动单元、等待客户端写出的就绪记录并复核 PID/启动时间/显示会话；**不**把“服务启动成功”当作就绪。
- 权限受限或嵌套预览（当前进程不在任何 `.service` cgroup 内）时才直接启动客户端，并在锁屏日志首行记录该降级原因；若当前进程**在**服务单元内而没有任何独立单元可用，则拒绝启动锁屏并提示运行 `./install.sh`，不退回不安全路径。

**测试**：`tests/test_lock_session.py`（26 项，覆盖就绪握手、复用、不同显示会话、失败不写记录、陈旧身份、请求校验、环境白名单、启动器选择、失败快速上报、CLI 端到端）。**回归证明**：把 `start` 换成“声称成功但不启动任何锁屏”的替身会让 `lock()` 抛出“未确认当前屏幕已锁定”。

**未验证（明确列出）**：真实 cgroup 生命周期需要可连接的用户 systemd 管理器。本环境 `systemctl --user` 不可用（`Failed to connect to user scope bus via local transport`），因此 `tests/test_lock_isolation.py` 按设计跳过并记录原因；该测试在真实会话中用**测试专用**瞬态单元验证“触发单元结束后锁屏存活”。未在主桌面重启真实服务，未杀真实锁屏。

## A2 · 关闭面板不再截断设置事务

**实现**（`niri/shell/panel.py`）：新增应用级 `Tasks` 计数器。`Panel.work(..., commit=True)` 表示有副作用的任务；这类任务在开始时 `application.hold()`，在 GTK 主线程的完成回调中 `release()`，只有当计数归零且窗口已请求关闭时才 `quit()`。只读任务不计数，随进程结束；销毁后的回调不再访问控件（`alive` 检查保留）。带副作用的外部调用点全部标为 commit：`action()`、语言重建、音频、外观应用、亮度、AI 设置保存、`wl-copy`，以及 `bluetooth/desktop/display/language/media/system_controls` 中写配置或改硬件的入口。

**测试**：`tests/test_panel_lifecycle.py`（5 项）。核心用例复现原缺陷路径：任务写第一阶段→`on_destroy`→延迟写第二阶段与 `finally`，断言三个阶段全部完成、`quit()` 只发生一次、`hold`/`release` 配对；另有“多个提交任务逐个完成才退出”“只读任务不占用生命周期”“销毁后不回调控件”等。

## A7 · 重新读取不再覆盖新编辑

**实现**：`niri/shell/desktop_controls.py` 的 `refresh()` 在读取期间冻结表单、应用、恢复默认和重新读取按钮，并记录冻结前的可操作状态；失败时逐项还原，成功时由 `populate()` 重新计算（因此自定义 XKB、焦点跟随等约束**不会**被重新启用）。新增 `generation` 草稿版本号，迟到的成功/失败回调直接丢弃。`niri/shell/display_controls.py` 的异步刷新采用同一策略。

**测试**：`tests/test_settings_refresh.py`（8 项），包含“读取期间表单不可编辑”“失败后恢复原状态且保留错误提示”“自定义 XKB 下应用按钮保持禁用”“迟到结果被忽略”“重叠读取被拒绝”。

## A6 · 保持唤醒时不再“先锁屏再说”

**实现**：新增 `niri/shell/power_actions.py` 作为唯一睡眠入口。`suspend()` 先读取 `sleep_guard.status()` 的真实抑制状态：守卫开启时**不锁屏、不调用 systemctl**，直接以可见理由终止；状态无法读取时同样拒绝并说明原因（不猜测）。未被阻止时保持“锁屏就绪 → `systemctl suspend`”顺序，并捕获 `systemctl` 的失败原因。未使用任何忽略 inhibitor 的参数，未关闭守卫。`niri/scripts/desktop` 新增 `sleep` 动作并在电源菜单中标注“保持唤醒已阻止睡眠”；`system_settings.render_power()` 生成的自动睡眠行改为调用同一入口；`niri/swayidle/config` 的注释同步更新。

**测试**：`tests/test_power_actions.py`（12 项）覆盖四种要求情形（守卫开启、锁屏失败、systemctl 失败、成功）以及顺序与参数断言。

## A5 · 单语言界面与快捷键说明

**实现**：
- `niri/shell/shortcuts.py` 重写为结构化数据：每个按键得到显式 `(english, chinese)` 描述与 `(english, chinese)` 分类，另存双语检索索引。工作区目标、上下方向、是否跟随窗口、截图“仅剪贴板/保存及剪贴板”都保留在两种语言中；用户自定义标题与命令原样保留、不翻译。
- `niri/shell/panel.py` 的快捷键总览改用 `tr(*pair)` 渲染、用 `item["search"]` 检索。
- Fuzzel placeholder：`niri/fuzzel/fuzzel.ini` 改为单语言默认值；`appearance.py` 生成时按当前界面语言写入；`niri/scripts/desktop` 启动启动器时用 `--placeholder` 覆盖（语言切换无需重新应用主题），dmenu 模式（剪贴板、电源、确认）改用自己的单语言提示，不再出现“搜索应用”。
- 生成的 `niri/theme/fuzzel.ini` 已用修复后的生成器重新生成。

**测试**：`tests/test_shortcut_language.py`（10 项，含 117 条逐条检查、工作区/方向/跟随/截图信息、双语检索一致）与 `tests/test_desktop_actions.py` 中的启动器/dmenu 断言。

**实测**：英文含中文 0 条，中文含英文并列 0 条（见 `fix-summary.json` 的 A5）。

## A4 · 分数缩放下的键盘图标

**实现**：新增项目内 `niri/assets/icons/input-keyboard-symbolic.svg`（自绘、透明背景、单色）。`niri/shell/control_widgets.py` 在运行时把该图标写成**继承当前用户图标主题**的私有主题 `selandia-symbolic`（写入 `$XDG_RUNTIME_DIR/selandia-icons-<uid>`，不可写时退回临时目录），并只把本进程的 `gtk-icon-theme-name` 指向它。因此：面板自己的键盘图标生效，其余图标仍来自 Breeze/Adwaita；不修改 `/usr/share/icons`，不切换系统主题。`panel.reload_theme()` 会重新检查，明暗切换后仍然生效。

**复现与验证**：`fix-keyboard-icon.png` 左（修复前）在 150%（GTK 整数缓冲缩放 2）下解析到 `/usr/share/icons/breeze-dark/devices/32/input-keyboard-symbolic.svg`，渲染为 44×44、透明像素 **0**、全不透明 1936 → 实心方块；右（修复后）解析到项目内 `selandia-symbolic` 的同一图标，36×36、透明 712、抗锯齿 92、不透明 492 → 轮廓与按键可辨。100% 与 200% 修复前本来正常，修复后同样正常（见 `fix-summary.json` 的 A4）。`tests/test_panel_icons.py`（8 项）在 100%/150%/200% 下断言透明背景、非实心、存在抗锯齿、轮廓占比合理，并断言未遮蔽其它系统图标、未写入系统图标目录。

**未验证**：面板内的实际截图需要合成器，本沙箱无法启动嵌套 Niri。

## A3 · 状态栏窄屏裁切

**实现**：新增 `niri/shell/bar_layout.py`。按**最窄已连接输出的逻辑宽度**与界面字号选择 `wide`/`compact`（阈值以“界面字号像素数”表示，不做整体缩小字号）：

- compact 保留启动器、工作区、声音、通知、控制中心（并保留电池与托盘），隐藏空工作区（CSS 归零 `#workspaces button.empty`）、去掉窗口标题、时钟缩短为 `{:%H:%M}`、`custom/ai`/`custom/shortcuts`/`custom/system` 移出栏面，网速改为链接图标并把实时速率放进 tooltip。
- `#network` 使用稳定的 `min-width`，边界值来自字号；配合 `min-length`/`max-length` 避免采样数字推动右侧模块。GTK CSS 不支持 `max-width`，因此上限由 waybar 的 `max-length` 承担，并有测试用 `Gtk.CssProvider` 校验生成的样式表合法。
- 生成链：`ui_assets.render()` 在翻译之后套用布局（语言重建不会退回宽布局）；`appearance.py` 生成对应布局的样式；`components waybar` 在启动前重选；新增的不可见 `custom/layout` 模块每 15 秒复查一次，输出变化时重写配置并只对受管 waybar 单元发 `SIGUSR2`（不会误伤其他 waybar 实例）。
- “当前布局”直接**从已生成的 `theme/waybar.jsonc` 推导**，不依赖状态文件：状态目录不可写时既不会报错，也不会因为标记永远对不上而每 15 秒重载一次状态栏（这一点由 `test_a_settled_layout_does_not_reload_the_bar_forever` 覆盖）。

**测试**：`tests/test_bar_layout.py`（23 项），包含审计报告中的 1067 逻辑像素 @16px 必须落到 compact，以及 12/16/20px × 三种验收分辨率的期望布局、必需模块保留、网速入 tooltip、宽度受约束、样式表为合法 GTK CSS、仅布局变化时才重写、陈旧标记不会反复重载。

**未验证**：1920×1080@150%、2560×1440@200%、3840×2160@150% 的实际截图与“右端按钮完整可点”需要合成器；本沙箱无法启动嵌套 Niri。本机实际输出为 3840 逻辑像素 @16px，选择 wide，与修复前一致（见 `fix-summary.json` 的 A3）。

## A8 · 界面字号 px/pt 语义

**实现**：新增 `niri/shell/font_scale.py` 作为唯一换算层，规范单位是逻辑像素（96 CSS DPI 基准）：

- CSS（面板、状态栏、通知）继续直接用逻辑像素；
- GTK/Pango、Qt/KDE、GNOME `font-name` 使用换算后的整数磅值（16px → 12pt，12→9，20→15，13→10）；
- Fuzzel 使用 Fontconfig `pixelsize`，避免第二次 DPI 乘算；启动器“大一号”的设计以逻辑像素 +1 表达；
- 锁屏保留 2× 的设计字号，但换算为磅值（16px → 32 逻辑像素 → 24pt）；
- 终端 `mono_size` 是独立的磅值语义，经 `pango_points`/`qt_points` 原样传递，不参与换算。

**测试**：`tests/test_font_scale.py`（11 项）断言换算数值、各后端字符串、设计层级，以及“逻辑像素数不得原样写成磅值”；`tests/test_application_theme.py` 的两处期望值已更新为换算结果。

**注意（可见变化）**：应用界面字号此前把 16px 当 16pt 写入（约 21.3px），现在为 12pt（16px）。应用文字会比原来小约 25%，这是审计指出的语义缺陷的修正。该改动需要重新应用外观才会写入 `~/.config`（本沙箱对 `~/.config` 只读）；锁屏字号随之从 32 变为 24，其视觉效果未在本环境实测。

## 测试覆盖缺口

- **通知中心截图**：`tools/smoke.py` 的截图函数新增 `hide_notifications` 开关；通知中心现在在**不隐藏**的情况下截取为唯一的 `notifications-center.png`；桌面总览改名为 `desktop-overview.png`，不再被“窗口与工作区”设置页覆盖。
- **waybar 日志归因**：新增 `tools/bar_log.py`，把每条 CRITICAL/ERROR/WARNING 与最近的模块/子进程标记及上下文一起报告；只有**直接点名本项目**的记录才会让运行失败，上游 GLib 噪声会被记录（`waybar-log-report.json`）并显式打印，而不是被过滤掉。烟雾测试重载循环后新增“右侧末端仍是控制中心按钮 + 网速宽度受约束”的布局检查。测试见 `tests/test_bar_log.py`（9 项）。
  对现有 [waybar.log](waybar.log) 的实际归因结果（[waybar-log-report.json](waybar-log-report.json)）：CRITICAL 全部是 waybar 进程自身的 `Glib::DispatchNotifier::unreference_instance` 断言失败，记录里没有任何本项目的模块或子进程名字（`project_findings` 为 0），随后 waybar 以新 PID 重启；WARNING 是 `No batteries`。
  第二轮用**对照实验定位了触发者**（每例 6 次 `SIGUSR2` 重载，原始日志 `waybar-reload-full.log` / `waybar-reload-min.log` / `waybar-reload-only-system.log` / `waybar-reload-only-notification.log`）：完整配置 8 条 CRITICAL → 去掉三个 `restart-interval` 子进程模块后 **0 条**；只留 `custom/system`（每 3 秒退出一次的子进程）→ 3 条；只留 `custom/notification`（`swaync-client --subscribe-waybar` 长连接流）→ 1 条。结论：条数随**带子进程的 `custom/*` 模块个数**变化，属上游 waybar/glibmm 在重载时销毁 custom 模块子进程流的实现问题，不是本项目代码，也不是某一个特定模块。可选规避是把长连接流换成定期轮询（代价是通知计数延迟），本轮**未**改动，以免为一个无功能影响的上游日志噪声破坏已验证的通知路径。
- **界面文案语言矩阵**：新增 `tests/test_ui_language_matrix.py`（6 项），用 AST 解析 `niri/shell/*.py` 中 200+ 条 `tr()` 文案，断言英文不含中文、中文不含“英文短语 / 中文”并列、中文不重复整句英文、不存在把中文复制到两种语言的漏改，并覆盖全部 117 条快捷键。
- **现已由嵌套会话覆盖**：16 个设置页 + 快捷键 + AI 侧栏的截图、52 项 GTK 交互测试、媒体/显示/字体探针、连续 6 次状态栏重载、真实 swaylock 就绪与复用、通知中心独立截图，以及 A3 的像素级栏宽验收（见 [bar-measurements.json](bar-measurements.json)）。
- **仍需合成器/硬件才能覆盖**：明/暗 × 中/英 × 100%/150%/200% 的完整截图矩阵，以及展开菜单、错误、空内容、禁用、长文字等控件状态的视觉验证；真实硬件睡眠、整夜息屏、PAM 解锁。
- **用户自定义 GTK CSS**：`~/.config/gtk-3.0/gtk.css`、`gtk-4.0/gtk.css` 含 `@import 'colors.css'`（Breeze 暗色变量），可能覆盖外观设置。本轮**未删除、未修改**这些文件；浅色整机一致性仍需在私有配置副本中单独核验，不能凭面板截图判断。

## 架构收敛（本轮完成的与刻意留下的）

完成：面板尺寸改按**指针所在输出**计算（`panel.panel_monitor()`），而不是 Wayland 下语义不可靠的"主显示器"；有六项单元测试覆盖指针/无指针/损坏 seat/主显示器缺失/坐标异常等回退路径，并在真实 GTK 显示上确认解析到 3840。这对多屏是行为修正，但仅在单输出环境实测（本机与嵌套会话都只有一个输出）。

刻意留下（附理由，不是遗漏）：
- **`panel.py` 拆分**（1900 行，含应用壳、16 页构建、任务调度、BlueZ D-Bus、指标渲染）：纯搬运，收益是可读性而不是行为；面板刚在真实会话里验证通过，此时做大范围搬动是审计自己警告的那类无谓改动。建议下次按"先抽 `bluetooth_backend`，再抽 `Tasks`"的顺序做，每次只搬一个并用现有测试守住。
- **锁请求 nonce**：当前请求文件按显示会话派生，客户端仍会复核记录、PID/启动时间与显示会话，互斥由 flock 保证；陈旧请求被复用的窗口极窄。给一个已端到端验证过的安全路径改协议，风险大于收益，因此记录为可选加固。
- **图标主题状态的还原**：`prepare_icon_theme()` 会改本进程的 `gtk-icon-theme-name`；测试目前手工重置 `PREPARED`。属于测试卫生，不影响运行时行为。

## 部署说明

- 源码改动通过 `~/.config/niri` 符号链接立即生效（面板、脚本、CSS、图标）。
- `selandia-lock@.service` 是新增的生成文件，需要运行 `./install.sh` 才会安装；未安装时 A1 自动使用已部署的 `selandia-niri@lock-<key>.service` 回退路径，同样具备 cgroup 隔离。本沙箱对 `~/.config` 只读，因此该单元未在本环境安装，A1 的真实 cgroup 验证在真实会话执行。
- 生成文件（`niri/theme/*`）已用修复后的生成器重新生成：`fuzzel.ini`（单语言 placeholder、`pixelsize`）、`waybar.css`（布局样式）、`waybar.jsonc`（布局与模块）、`swaylock.conf`（换算后的磅值）。`~/.config` 下的应用主题（`gtk-3.0/settings.ini`、`kdeglobals`、qt6ct）需在控制中心点击“应用”后写入。
