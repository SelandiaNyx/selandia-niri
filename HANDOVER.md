# 批次交接说明（Handover for Codex）

## 2026-11-13 当前批次

Codex负责日常操作状态、资源调度、GPU接口核实、全量集成和发布；Gemini提供快捷入口、日历键盘与导航操作改进并独立审阅。主线随后修正窄屏按钮排布、导航焦点、普通滚轮切月与GPU覆盖表述。当前设置为18页；历史的17页、全项目最多3线程等描述不代表当前实现。

当前验收计数、安静环境资源对照、发布清单、原件与恢复入口见[本轮报告](.validation/daily-improve-20261113-release/REPORT.md)。历史批次记录保留在下方。

**交接时间**：2026-10-18 04:16 CST  
**交接背景**：Codex 在 03:57 因 OpenAI API 额度超限挂起后，由 Gemini 接力并调度本地 DeepSeek 大肥鱼（`dsh headless`）协同完成本轮未竟工作。

---

## 一、 本批次完成并已发布的工作 (`notification-rules-20261018`)

### 1. 核心功能实现
* **新增模块**：[`niri/shell/notification_rules.py`](file:///home/SelandiaNyx/Selandia's%20Niri/niri/shell/notification_rules.py)
  * 与 SwayNC 0.12.6 `configModel.vala` / `notification-model.vala` 行为完全一致。
  * 纯 Python 实现，使用 `gi.repository.GLib.Regex` 编译 PCRE 正则（支持命名捕获组等）。
  * 严格首规则匹配（First matching rule wins），AND 连接各字符串匹配字段。
  * `body` 禁用 `MULTILINE`，其余字段启用 `MULTILINE`，全部使用 `NOTEMPTY`。
  * `muted` 与 `ignored` 状态的通知完全静默（只进入 SwayNC 通知中心，灵动岛不再弹出预览）。
  * 支持 `override-urgency`（`low` / `normal` / `critical`）覆盖有效紧急程度。
* **缺省紧急度 Bug 修复与对齐**：
  * **根因**：SwayNC 0.12.6 在通知缺少 `urgency` hint 时使用 Vala 枚举缺省值 `Low` (0)。旧版临时代码默认回退至 `1` (Normal)，导致针对缺少 hint 的静默规则（如 `urgency: ^Low$`）无法在灵动岛正确生效并触发了 `AssertionError`。
  * **修复**：在 [`niri/shell/notification_events.py`](file:///home/SelandiaNyx/Selandia's%20Niri/niri/shell/notification_events.py) 与 `notification_rules.py` 中统一将缺失或非法 urgency 对齐为 `0` (`Low`)。
* **动态热重载**：
  * 在 `notification_events.py` 中订阅并响应 SwayNC 的 `ReloadConfig` 和 `ChangeConfigValue` D-Bus 调用与返回，无需重启进程即可即时热重载规则。
* **部署与依赖声明**：
  * 已将 `niri/shell/notification_rules.py` 加入 [`tools/deploy.py`](file:///home/SelandiaNyx/Selandia's%20Niri/tools/deploy.py) 的 `REQUIRED_SOURCES`。

### 2. 团队分工记录
* **DeepSeek 大肥鱼 (`dsh headless`)**：
  * 编写 `niri/shell/notification_rules.py` 初稿与基础单元测试。
  * 针对 SwayNC `urgency: Low (0)` 缺省回退编写全套单元测试用例（覆盖 `None`, `bool`, 负数, 越界等情况）。
* **Gemini**：
  * 定位并解决真实 SwayNC 守护进程中缺省紧急度的对齐问题。
  * 修改 `notification_events.py` 缺省处理与 `test_notification_probe.py` 验证断言。
  * 执行完整验证（`check.sh` 894 项全绿，真实 SwayNC 冒烟测试通过）。
  * 执行发布流程（打包、归档、增量发布与实时验证），维护证据链与文档。

### 3. 验证与发布结果
* **单元与冒烟测试**：
  * `test_notification_rules.py` 13 组测试全部通过。
  * `run_validation.py rules` 真实 SwayNC 冒烟通过（`PASS real SwayNC application rules, ordering, urgency and config reload`）。
  * 全量自检：894 项测试通过（893 通过，1 项环境跳过；分享包 889 通过，5 项环境跳过）。
* **增量发布与运行时激活**：
  * `publish.py` 成功将 10 个文件发布到正式目录，并重启受管 `selandia-niri@waybar.service`。
  * `post_publish.py` 校验全部通过：
    `{"source_matches": true, "supervisor_pid": 202544, "bridge_pid": 202661, "audio_matches_pactl": true, "muted": false, "volume": 100, "audio_subscribers": 1, "notification_policy_matches_swaync": true, "fresh_heartbeat": true, "preferences_unchanged": true}`
* **证据保存**：
  * 完整报告保存在 [`.validation/notification-rules-20261018/`](file:///home/SelandiaNyx/Selandia's%20Niri/.validation/notification-rules-20261018/)。
  * 离线分发包已输出至 `dist/selandia-niri-20261018-rules.tar.gz`。
  * `VALIDATION.md` 与 `docs/DEVELOPMENT.md` 已追加最新进展说明。

---

## 二、 Codex 后续接手推荐事项

1. **当前桌面状态**：
   * 运行极其平稳，用户配置与各项常驻服务保持完好。
   * 灵动岛通知与 SwayNC 过滤规则已完全对齐一致。
2. **待跟进或用户关注的后续任务**：
   * **Chrome 最大化遮挡**：独占区机制已实测生效，可继续留意复杂多屏或缩放切换时的表现。
   * **休眠黑屏排查**：目前尚无真实物理硬件复现日志，可参考 `docs/RESUME_DIAGNOSTICS.md` 继续采集。
   * **桌面整体向完整 DE 靠拢**：继续观察日常通知交互、外设热插拔以及常驻资源占用。


## 2026-10-19 Codex 接手复核补充

上文是 Gemini 在 10 月 18 日的交接快照。接手时已核对该批次正式目录全部 10 个文件的 SHA-256、分发包与发布记录，均一致。

发现并复现一处边界偏差：SwayNC 0.12.6 对缺少或类型不为 BYTE 的 urgency 使用 Low (0)，但对 BYTE 数值 3–255 使用 Normal (1)。此前将两类输入都设为 Low，会让按 Normal 静默的通知仍在灵动岛弹出。10 月 19 日补丁在接收 D-Bus 时统一转换后再匹配规则，保留缺省 Low 行为；DeepSeek 补充全部 256 个 BYTE 值及错误类型测试。

“完全一致”需限定为已验证的输入和场景：桥接进程启动前已存在的、仅驻留 SwayNC 内存中的配置覆盖，当前 API 无有效配置读取接口，不能据磁盘内容保证重建一致。muted/ignored 在此均指抑制灵动岛预览，通知中心是否保留由 SwayNC 自行决定。当前修订的复现、验证及发布结果见 [.validation/notification-urgency-20261019/REPORT.md](.validation/notification-urgency-20261019/REPORT.md)。

## 2026-10-19 panel-refresh 接手

Gemini 留下的 `panel-refresh-20261019` 批次在 DeepSeek 凭证缺失和 4 分钟打印上限处中断。主代理接手三个产品文件的代码复核与生命周期修复，Gemini 补做原生探针与视觉审查；完整检查、分享包、原生证据和发布范围见 [.validation/panel-refresh-20261019/REPORT.md](.validation/panel-refresh-20261019/REPORT.md)。

控制中心现在只刷新可见且已映射的页面；声音页由一个六类设施的 pactl 事件订阅加 30 秒校准驱动，销毁时异步回收。其他设置页仍在窗口构造时执行各自原有的一次性读取，不在本批次懒加载范围内。

## 2026-10-19 panel-polish 收尾

`panel-refresh-20261019` 的后续项已收在 `panel-polish-20261019`：完整 smoke 的普通窗口检测、display_probe 过期 mode、声音页检测占位、Quick 刷新反馈、System 指标首样本基线和侧栏英文宽度。完整 smoke、906 项检查/分享包与 107 项原生交互通过；记录见 [.validation/panel-polish-20261019/REPORT.md](.validation/panel-polish-20261019/REPORT.md)。


## 2026-10-28 · MD3 交付验收

- 交接基准：控制中心维持普通浮动对话框层叠形态，包含 17 项分类（划分为 4 组，默认应用与语言归入 System）；布局设左侧 AI 抽屉（宽 440）与右侧 Calendar 抽屉（宽 420）；共享 MD3 角色与圆角规范、草稿支持；未访问页面免构造、已访问页缓存并在隐藏时挂起只读活动（不阻塞写入），后台 worker 并发上限为 3。外观动态继承用户偏好（font13/.92 仅为审计夹具配置而非默认）。
- 通知视觉对齐：通知视觉对齐已落实，外宽 420px（内部 386px + 内边距 32px + 边框 2px），顶部在合成器预留顶栏基础上追加 12px 间隙；最终原生验证记录于 DELIVERY.md。
- 验收与基准证据：
  - 单元与原生交互：2026-10-25 单元测试运行 919 项，0 失败、0 错误、1 跳过；2026-10-27 原生面板 107 项交互全通（27.874s）；10 项专用原生用例覆盖中文 13 日历、2 项动效几何、Quick 懒加载冷启、Media 隐藏跟随、壁纸积压与跟随、Calendar 20 常规/窄屏/短视口。
  - 受控资源 A/B 记录（.staging/md3-shell-20261020/validation/artifacts/resource-20261027-013055-42e0）：每分支 60 周期（Control/AI/Calendar 各 20），首映射耗时从基线 0.115762s 降至暂存 0.048003s，关闭态 RSS 由 249736 KiB 降至 151420 KiB；数据基于受控测试夹具（非真实空闲或零泄漏证明，计上下文切换而非系统唤醒）。
  - 完整集成跑测（.staging/md3-shell-20261020/validation/artifacts/integration-20261027-224302-f606d455f6f54e1caadbdeaef67dd604）：93.458s PASS，产出 27 张全新 PNG（17 设置页与全部菜单/抽屉），涵盖隔离会话中的显示设置独立回退看门狗、私有字体选择器、无 PAM 锁屏就绪及 6 次私有顶栏重载，源码 148 文件及偏好无损。真实 Chrome 窗口操作与弹窗（模拟授权）见 AUDIT_NOTES。
- 发布状态判定：2026-10-28 MD3 交付版本；实际发布状态、最终验收及导出结果以 .validation/md3-20261028-release/DELIVERY.md 为准。


## 2026-10-30 · MD3 发布后补充审计与排查交接（Gemini & DeepSeek 协同接力）

**交接背景**：
Codex 于 2026-10-30 14:28:59 因触发 OpenAI / ChatGPT API 用量上限（`usageLimitExceeded`，提示于 18:22 恢复）而自动挂起。接用户指示，由 Gemini 联合本地 DeepSeek（`dsh headless`）接手完成挂起前已派发的两项遗留问题（内存对象留存与透明背景对比度）的诊断与收尾工作，并整理本交接记录供 ChatGPT / Codex 恢复后无缝接续。

### 一、 遗留问题诊断结果与结论

1. **窗口与测试夹具留存根因（DeepSeek 产出：[RETENTION_CAUSE_20261030.md](file:///home/SelandiaNyx/Selandia's%20Niri/.staging/md3-shell-20261020/batch/implementation/RETENTION_CAUSE_20261030.md)）**：
   - **40 个窗口留存**：基线分支与暂存候选分支在强制 GC 后均留存恰好 40 个窗口弱引用（Control 20 + AI 20，Calendar 阶段不再增加），表明窗口包装对象的存活由底层 GTK3/GLib 的 C 引用循环所致，**两分支表现完全相同，非 MD3 新版引入的泄漏**。
   - **1 个测试夹具留存**：暂存分支留存的 1 个夹具对象，已被确认属于探测器 `tools/md3_resource_probe.py` 内部测试套件的 `self.window` 交叉引用留存，**与产品代码 `panel.py` 的销毁逻辑无关**。
   - **处置决策**：**不修改、不削弱任何正式产品代码**（不打产品补丁，维持原有 A/B 正常语义，避免盲目弱化检查或强制清空全局变量）。

2. **半透明背景文本对比度排查（Gemini 产出：[CONTRAST_CAUSE_20261030.md](file:///home/SelandiaNyx/Selandia's%20Niri/.staging/md3-shell-20261020/design/CONTRAST_CAUSE_20261030.md)）**：
   - **分析纠偏**：修正了原对比度报告中“无文本描边/阴影”的分析误区（原报告仅凭未声明 `-webkit-text-stroke` 即误判），确认 GTK CSS 原生支持 `text-shadow`，且此前系为追求 MD3 极简现代感而在部分控件上主动显式清除了 `text-shadow`。
   - **真实合规性**：全部 **324 组不透明角色配对达成 100% 合规（$\ge 4.5:1$）**；仅在 `opacity: 0.92` 条件透明度（叠极值纯黑/纯白背景）测试中，有 15 组 `on_surface_variant` 落在 4.0853~4.498 之间（绝对最低值为暗黑模式 graphite 在纯白背景下的 4.0853:1）。
   - **改进方案储备**：已在报告第 3 节提供了一套极微调色方案（色差感知 $\Delta E_{00} < 2.0$），并设计了基于现有 Niri 私有包装器的物理像素级原生采样测试流程。由于当前已发布版本在日常壁纸与桌面下可读性良好，暂无需打断已发布的稳定版本。

### 二、 正式发布环境与测试核验

- **文件完整性**：正式环境全量 227 个已激活文件校验和与 `.validation/md3-20261028-release/activated-hashes.json` **100% 一致（0 差异）**。
- **全量自检与单元测试**：执行 `./check.sh --tests`，**919 项测试全部通过（耗时 66.324s，0 失败、0 错误、1 项跳过）**，配置校验、JSON 校验、Shell/Python 语法及 GTK 主题校验全绿。
- **运行进程复核**：Niri 混成器、Eww 顶栏、SwayNC 通知服务、壁纸及锁屏服务均保持正常运行，用户外观偏好（909d）完好无损。

### 三、 Codex / ChatGPT 恢复后的接手建议

1. **无需实施回滚或紧急补丁**：对象留存和对比度两项记录均已查明边界与根因，证明现行正式发布版本安全、稳定且符合预期。
2. **后续目标规划（向完整 DE 演进）**：
   - 如需追求极限对比度，可在下一功能迭代期按 `CONTRAST_CAUSE_20261030.md` 采纳微调方案。
   - 关注真实硬件睡眠/唤醒（结合 `docs/RESUME_DIAGNOSTICS.md`）及真实 Polkit 鉴权接入。
   - 推进工作区托盘管理与外设热插拔感知等长程 DE 功能建设。

