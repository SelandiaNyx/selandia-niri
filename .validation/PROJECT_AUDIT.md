# Niri 项目自检与交接指令

> **2026-10-05 后续工作**：A1–A8 与文档列出的测试覆盖缺口已按本文要求处理，逐项实现、测试与证据见 [FIXES.md](FIXES.md)，实测数据见 [fix-summary.json](fix-summary.json)。本轮改动后 521 项单元测试与 `./check.sh --config` 通过；A1 的真实 cgroup 生命周期、A3/A4/A5 的合成器截图以及浅色整机一致性仍列为**未验证**（原因见 FIXES.md 与 fix-summary.json 的 `verification_limits`）。以下原文保留，作为整改前的记录。

检查于 2026-10-04，2026-10-05 整理。结论：**基础功能通过自动检查，但不能认定资源渲染、统一风格和交互细节完全正确。** 以下审查问题没有直接修复；之后为用户卸载 Plasma 所作的 Qt 依赖迁移另行记录。

2026-10-05 补验：Plasma 已移除，Qt 主题切换为独立 qt6ct。最新 **375 项单元测试、52 项 GTK 交互和完整独立 Niri 冒烟测试通过**，见 [plasma-final-unit.log](plasma-final-unit.log)、[plasma-final-smoke.log](plasma-final-smoke.log)、[plasma-final-check.log](plasma-final-check.log)。补拍并查看了 [通知中心](audit-notifications.png)，主体卡片、开关和按钮可辨认；第三方时间文字仍出现英文 Now，单语言验收应包含这些细节。卸载明细和影响见 [PLASMA_REMOVAL.md](PLASMA_REMOVAL.md)。这些通过结果不消除 A1–A8。

## 已验证的范围

| 检查 | 结果与证据 |
| --- | --- |
| 配置、依赖、正式 Niri 会话 | `./check.sh` 通过，见 [audit-check.log](audit-check.log) |
| 原有单元测试 | 372 项通过，见 [audit-unit.log](audit-unit.log)；XKB 错误输出来自刻意测试不存在的布局，不是现有布局故障 |
| 独立 Niri 会话 | 16 类设置、启动器、快捷键、AI 侧栏均打开、关闭并生成截图；见 [audit-smoke.log](audit-smoke.log) |
| GTK 交互 | 52 项通过，含下拉框滚轮保护、按需键盘焦点、语言重建、播放控制与字体对话框 |
| 媒体 | 4 项独立 MPRIS 检查通过，含单曲暂停/播放、指定播放器和过期实例保护；没有控制真实播放器 |
| 屏幕配置 | 私有合成器内实际应用、确认、回滚和脱离面板后的超时恢复通过；没有改真实显示器模式 |
| 状态栏 | 连续 6 次重载后仍存活且有 Wayland 图层；这不代表内容没有裁切，见 A3 |
| 锁屏 | 私有合成器内 ready 握手及重复调用复用成功；未验证主桌面 PAM 解锁、整夜息屏或硬件睡眠唤醒 |
| 资源 | 31 种 symbolic 图标可查找到，字体可匹配，未发现失效的 niri 内部软链接；一个图标仍渲染错误，见 A4 |
| 附加布局测量 | 16 页面 × 4 组画布/语言/主题/字号，共 64 项；见 [audit-layout.json](audit-layout.json)。960×600 中文深色 16px、960×820 英文浅色 12px、960×820 英文深色 20px、768×600 中文深色 16px 的面板画布未因内容被撑宽。允许纵向滚动，不代表所有主要操作首屏可见 |

浅色模式确实存在，字体选择器的文字及按钮对比度检查也通过。当前主要视觉方向一致，但下面的图标、字号和语言问题影响完整体验。Inter 未安装时回退到 Noto Sans，文字能够显示；若要求完全还原指定字体，需要将 Inter 纳入安装依赖或选用保证存在的字体。

## A1 · P1：锁屏进程会随触发它的服务结束

位置：`niri/shell/lock_session.py:83`、`systemd/selandia-niri@.service.in:8`、`niri/scripts/components:43`、`niri/shell/sleep_guard.py:91`。

`start_new_session=True` 只创建进程会话，未隔离 systemd cgroup。实际 idle/sleep-lock 服务为 `KillMode=control-group`；假锁屏测试确认父子 cgroup 相同。停止这些服务会同时结束由它们启动的锁屏客户端，存在会话继续锁定、却失去解锁界面的风险。**没有在主桌面复现永久黑屏，也不能据此认定之前无信号事件的原因。**

交给其他 AI：为锁屏客户端建立按 Wayland display 区分的独立用户 service/scope，保留 ready-fd、PID/start-time/display 身份确认与互斥。不能仅将共享模板改成 KillMode=process/none，也不能杀锁屏来恢复。私有 Niri 中验证由 idle、sleep-lock 各自触发锁屏后，重启触发服务不会结束锁屏；重复请求复用正确实例；锁屏未 ready 时禁止睡眠。

完整协议依据及验收：[audit-lifecycle.md](audit-lifecycle.md)。

## A2 · P1：关闭面板可能中断设置提交或回滚

位置：`niri/shell/panel.py:222`、`323`、`344`。

所有后台任务使用守护线程，关闭窗口直接退出应用。调用真实 work/on_destroy 方法的隔离探针中，两阶段写入只完成第一阶段，第二阶段及 finally 都没有执行。没有修改或破坏真实用户配置。

交给其他 AI：将有副作用任务改为应用级管理；关闭只隐藏或解除界面订阅，待提交/回滚完成再退出。通过任务计数和 hold/release 或独立 worker 管理生命周期；只读任务可以取消。不要让结束回调访问已销毁的控件。为 ×、Esc、重复快捷键和语言重建添加慢速写入/失败回滚测试，结果必须是完整旧状态或完整新状态。

位置、脚本、实际结果：[audit-interactions.md](audit-interactions.md)、[audit-interactions.py](audit-interactions.py)、[audit-interactions.log](audit-interactions.log)。

## A3 · P2：窄屏/较大字号下状态栏右端被裁切

位置：`niri/waybar/config.jsonc:9`、`34`、`43`、`69`，`niri/waybar/style.css:28`、`43`、`69`，`niri/shell/appearance.py:241`。应修改生成来源，不能只改 `niri/theme/waybar.jsonc`。

复现：嵌套输出 1600×1000、150% 缩放，约 1067 逻辑像素宽，当前 16px 字体。十个工作区、时间和全部右侧模块一起显示，控制中心按钮被裁掉。截图见 [control.png](control.png)、[sound.png](sound.png)。[waybar.log](waybar.log) 记录栏宽会随网速文本从 1031 增至 1091，而扣除两侧 18px 后可用宽度约 1031。

交给其他 AI：按输出逻辑宽度和字号生成宽/紧凑两种布局；优先保留启动器、当前/有窗口工作区、声音、通知、控制中心；紧凑模式缩短日期、隐藏空工作区和窗口标题，将完整网速/监控移入 tooltip 或收纳区。约束网速文本最大宽度，避免采样数字变化推动模块。不要用整体缩小字体掩盖问题。宽度变化或输出热插拔要重新选择布局。

验收：1920×1080@150%、2560×1440@200%、3840×2160@150%，12/16/20px，网速 0B/s 至 GB/s、多个托盘图标时，右端按钮完整可点、模块不重叠、不超出输出；仍通过连续重载测试。允许约定紧凑显示，但详细数据必须可达。

## A4 · P2：键盘图标在分数缩放下成为实心方块

位置：`niri/shell/settings_navigation.py:13`、`niri/shell/control_widgets.py:24`。

150% 实际截图和独立 GTK 加载均复现。Breeze 2× 所选键盘 SVG 导出为 44×44 的全不透明矩形，Adwaita 对照正常；“能找到图标文件”的检查没覆盖渲染结果。

交给其他 AI：为面板提供经过验证的局部 symbolic SVG 或明确的图标来源，至少修复键盘图标；不要修改 `/usr/share/icons` 或切换整个系统主题。验证 100%/150%/200%、深浅模式、选中与未选中，轮廓和按键清楚、背景透明。

完整资源证据：[audit-resources.md](audit-resources.md)。

## A5 · P2：单语言界面仍有遗漏，快捷键说明还丢失目标信息

位置：`niri/fuzzel/fuzzel.ini:5`、`niri/shell/appearance.py:333`、`niri/scripts/desktop:74`、`niri/shell/ui_assets.py:12`、`niri/shell/shortcuts.py:110`、`niri/shell/i18n.py:83`。

启动器 placeholder 固定为双语。117 条快捷键中，英文有 18 条含中文，中文有 46 条复合说明残留；英文 Super+1 与 Super+PageUp 都变成 Go to workspace，目标或方向缺失。播放器标题、硬件名等用户数据不应被当成界面翻译缺陷。

交给其他 AI：让 Fuzzel 根据界面语言生成/覆盖 placeholder，语言切换即可生效，主题重新生成不回退为双语；剪贴板、电源 dmenu 使用各自文案。快捷键改用结构化字段和完整 tr 模板生成，明确保留目标工作区、方向、跟随行为、截图保存/剪贴板差异；显示和双语搜索索引分开。不要扩大通用字符串拆分规则去改用户数据。

验收：中英文各检查全部 117 条说明及各类 Fuzzel 菜单，界面不并列两种语言，动作信息完整，双语搜索仍有效；应用主题和重新登录后保持一致。

## A6 · P2：保持唤醒时点击睡眠，先锁屏却没有失败说明

位置：`niri/scripts/desktop:105`、`109`；自动入口 `niri/shell/system_settings.py:137`。

隔离命令测试确认顺序为锁屏后 systemctl suspend，命令失败时无通知。启用本项目阻止睡眠功能时，用户可能只看到锁屏，不知道睡眠被拒绝。

交给其他 AI：统一可测试的睡眠入口；锁屏前确认 sleep_guard 的真实抑制状态，若保护开启则说明原因并终止动作。不得暗中关闭守卫或忽略 inhibitor。允许睡眠时仍须锁屏 ready 后请求，捕获睡眠失败并提供可见反馈。覆盖 guard 开启、锁屏失败、睡眠请求失败和成功四种情形。详见 [audit-lifecycle.md](audit-lifecycle.md)。

## A7 · P2：重新读取期间的新编辑会被旧结果覆盖

位置：`niri/shell/desktop_controls.py:110`。

真实 refresh 方法配合延迟替身复现：读取期间表单和应用按钮仍可操作；刚输入 20，迟到的 populate 又改回 16。

交给其他 AI：读取期间冻结表单及应用/默认按钮，或用草稿版本号忽略旧结果；正确恢复原本的可操作状态，不能重新启用自定义 XKB 等原本受限制的控件。两个页面的读取成功和失败均测试，不得静默覆盖新草稿。详见 [audit-interactions.md](audit-interactions.md)。

## A8 · P2：界面字号的 px/pt 语义不统一

位置：`niri/shell/panel.py:1101`、`niri/shell/appearance.py:194`、`334`，`niri/shell/application_theme.py` 的字体生成部分（Plasma 移除迁移后行号可能变化）。

UI 明确标注界面字号 px，面板确实用 CSS px，但相同数字被写为 GTK/Qt 的 pt，Fuzzel Fontconfig size 又额外加 1。基础文本在不同组件中的尺度不等价；这是配置语义确认，尚未逐应用、逐 DPI 完成视觉测量。

交给其他 AI：保留一个规范单位，明确每个后端的转换层和设计层级；不要将界面逻辑 px 直接当作 pointSize，避免重复应用 DPI/缩放。终端独立 pt 语义保持不变。为 12/16/20px、100%/150%/200% 补配置语义和实际字体度量测试。详见 [audit-resources.md](audit-resources.md)。

## 测试覆盖需要补强的地方

- `tools/smoke.py:131` 截图前总是隐藏通知中心，`desktop.png` 又在第 175 行被“窗口与工作区”页面覆盖，不能拿这个文件证明通知中心视觉正确。给通知中心保留独立截图入口和唯一名称。
- `waybar.log` 在频繁重载时出现 Glib::DispatchNotifier CRITICAL，虽然栏最终存活。应定位具体触发模块/子进程，补存活、图层、布局和日志检查；不能仅过滤错误字符串来让测试通过。当前没有足够证据直接归因于项目代码或某个上游版本。
- 扩充实际控件状态覆盖：明/暗 × 中/英 × 常见缩放，包含展开菜单、错误、空内容、禁用和长文字。现有测试对正常状态的覆盖比失败/关闭时序更完整。
- 不要把媒体测试用双语曲名、模拟配置与临时 state 当成真实用户设置错误。私有测试的 portal/systemd 总线退出警告亦不等同于正式会话损坏。
- 2026-10-05 当前 GTK 3/4 用户 CSS 含 `@import 'colors.css'`，其文件定义了 Breeze 暗色变量。主题同步已明确报告自定义 CSS 可能覆盖外观，原文件按用户修改予以保留。切换浅色的整机一致性还应在私有配置副本中检查这些覆盖；不能凭面板自身的浅色截图认定所有应用都一致，也不要未经核对删掉用户 CSS。

## 可直接复制给修改者的范围要求

> 按 A1、A2 优先，再处理 A3–A8。每项单独提交实现和对应的复现/回归证据。只围绕 Arch + Niri；保留已由其他 AI 调整好的音频枚举及三个真实输出设备。不要通过运行真实睡眠、杀主桌面锁屏、更换音频配置或重置用户偏好验证问题。不要修改生成文件来代替修复生成器。Plasma 卸载所需的 qt6ct 迁移已单独处理，不要重新引入 plasma-integration。任何只能通过硬件或 PAM 验证的结论明确列为未验证。
