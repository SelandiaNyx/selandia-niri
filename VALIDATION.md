## 2026-10-19 · 控制中心打磨、完整 smoke 与首样本指标

补齐全量 smoke：设置页自 2026-10-15 起是普通 Control Center 窗口，探针改为按 PID 检测；display_probe 在缩放后重新读取当前 mode，完整隔离 smoke 恢复通过。声音页首次进入显示“正在检测…”下拉占位，Quick 手动刷新按钮在请求期间禁用，System 页进入时建立指标基线并 50ms 后首采，侧栏宽度从 190 调整到 215px。新增标题栏时钟、prime 首样本和 Quick 音量 `N/A` 回归。

906 项完整检查（905 通过、1 项环境跳过）、906 项分享包检查（901 通过、5 项环境跳过）、107 项原生 GTK 交互以及完整隔离 smoke 均通过；`control.png`、`sound.png`、`system.png` 为当前渲染证据。真实热插拔、多屏缩放切换与长期运行仍需正式会话观察。记录见 [打磨批次](.validation/panel-polish-20261019/REPORT.md)。

## 2026-10-19 · 控制中心可见页刷新与音频事件订阅

控制中心不再让所有页面后台轮询：只有当前可见且已映射的页面读取主机。quick 页刷新总览与媒体，sound 页刷新音频，system 页刷新系统信息与指标；隐藏页和未映射窗口不产生新的读取。声音页使用一个覆盖 sink、source、server、card、sink-input、source-output 的 `pactl subscribe` 订阅，事件到达才刷新，另保留 30 秒校准读取；读取或音频操作进行中的事件保留到下一次读取。面板销毁时关闭监听并异步回收子进程，不阻塞 GTK，也不截断提交中的设置事务。

复核同时修复了页面门控造成的标题栏时钟冻结、系统信息隐藏读取，以及未启动监听线程的 join 异常。904 项完整检查（903 通过、1 项环境跳过）、904 项分享包检查（899 通过、5 项环境跳过）和 106 项原生 GTK 交互通过；真实热插拔、多屏缩放切换与长期运行仍需正式会话观察。验证与发布记录见 [控制中心刷新记录](.validation/panel-refresh-20261019/REPORT.md)。

## 2026-10-19 · Gemini 交接复核与通知紧急度边界

已核对前一批次 10 个正式文件及分发包。隔离真实 SwayNC 复现 urgency BYTE=3 被守护进程静默而灵动岛仍预览的问题；接收端现在区分缺失／错误类型（Low）与越界 BYTE（Normal），规则匹配和超时策略共用转换结果。DeepSeek 补充全部 256 个 BYTE 值和错误类型单元测试；原生验证覆盖缺失值、布尔／整型／字符串，以及 0、1、2、3、255。

验证和发布结果见 [交接复核记录](.validation/notification-urgency-20261019/REPORT.md)。SwayNC 在桥接进程启动前的纯内存配置覆盖无法从磁盘重建，当前支持已观察到的配置重载及服务重启，不将未覆盖场景标为完全一致。

## 2026-10-18 · SwayNC 通知可见性规则与灵动岛一致性

灵动岛同步支持 SwayNC 的 `notification-visibility` 规则：按配置顺序采用第一条匹配规则，支持 app-name、summary、body、urgency 及 desktop-entry、category、sound-name、sound-file 等字段的精确正则匹配。未提供 urgency hint 时对齐 SwayNC 缺省为 Low (0)。设为 muted 或 ignored 的应用通知不在灵动岛弹出预览，通知中心是否保留由 SwayNC 决定；支持 override-urgency 覆盖有效紧急程度。

在隔离会话中复现旧版静默通知仍弹出灵动岛的问题；使用真实 SwayNC 守护进程和独立 D-Bus 验证规则匹配顺序、紧急级别覆盖、长文本匹配、缺失提示缺省值与运行时配置重载（ReloadConfig / ChangeConfigValue）。完整检查、单元测试、冒烟验证与发布回滚见 [批次记录](.validation/notification-rules-20261018/REPORT.md)。

## 2026-10-18 · 音量／亮度单一提示与静音状态

快捷键优先使用灵动岛，发送失败才回退通知；麦克风保留单独标识的通知。音量采样同步静音状态，静音变化即使不改变音量数值也能触发反馈，顶栏图标同步更新。灵动岛显示百分比或“已静音”，窄屏长标签换行。

使用隔离命令、私有 socket 与音频夹具验证，不操作实际硬件。旧版测试复现重复通知及灵动岛不存在时仍报告成功；新版覆盖回退、失败、静音／取消静音、空闲查询次数和原生顶栏布局。完整检查、界面证据、发布与回滚信息见 [批次记录](.validation/osd-feedback-20261018/REPORT.md)。

## 2026-10-16 · 通知勿扰与预览生命周期

隔离会话复现旧版勿扰仍显示灵动岛、关闭通知后预览残留。现在订阅 SwayNC 策略，按成功返回的通知 ID 处理替换／关闭；通知中心打开、策略不可用或服务退出时撤下预览，服务恢复后自动同步，结束勿扰不重放旧通知。紧急通知及官方绕过提示遵循 SwayNC 的行为，短时预览服从请求时长，紧凑预览最多 8 秒。

真实 SwayNC 与实际 island 进程覆盖勿扰、抑制、紧急／显式绕过、中心打开、替换、清空、过期、服务退出／重启及 ID 重用；另核对不相关信号不改变预览。源码、测试、分享包、发布范围与回滚记录见 [批次记录](.validation/notification-policy-20261015/REPORT.md)。自定义 SwayNC 的应用可见性规则尚未纳入此批次同步范围。

## 2026-10-15 · 控制中心遮挡对话框

控制中心改为普通浮动窗口，保留圆角、玻璃阴影与随不透明度调整的降噪；日历和 AI 侧栏保持原图层。隔离 Niri 中旧版的两种独立对话框均完全被遮挡、实际点击未送达；修复后显示像素、焦点、输入框焦点和实际指针点击均通过。测试使用授权样式夹具，不触发真实系统授权；另验证应用实际的文件／目录／字体选择与 Mature 分级确认，取消后保留当前页和未保存草稿。

完整检查 842 项（841 通过、1 项环境跳过），原生 GTK 交互 101 项通过，壁纸页宽窄屏与中英文四组布局通过。DeepSeek 补充控制中心说明。发布记录、对比截图、分享包验证和回滚入口见 [批次记录](.validation/panel-dialogs-20261015/REPORT.md)。已打开的控制中心需保存草稿后重新打开；不重启合成器或桌面组件。

## 2026-10-15 · 顶栏音量／媒体事件与日历语言

顶栏订阅音量和 MPRIS 变化，合并突发事件并保留 30 秒校准与断线重连；媒体进度本地计算。真实隔离顶栏连续播放 3 秒无新增音量或播放器属性读取，音量、Seeked、暂停、换曲和播放器退出更新正常，停止后监听子进程已回收。原生 GTK 日历跟随应用中英文，支持方向键、翻月／年、ISO 周数、月底／闰年与日期复制；修正生成主题覆盖选中日期的问题。

完整检查 842 项（841 通过、1 项环境跳过），GTK 交互 101 项通过；中英文各有宽屏深色与窄屏浅色截图，六周日期完整可见。Chrome 最大化避让保持通过。旧顶栏像素探针的背景夹具改为忽略独占区，避免把背景位移误判为顶栏变宽；Chrome 探针明确优先导入隔离目录，主题生成不会写回源码树。发布、分享包与常驻实测结果见 [批次记录](.validation/event-feeds-20261014/REPORT.md)。

## 2026-10-14 · Wallpaper Engine 项目分级

分级改为读取壁纸 `project.json` 的 `contentrating`，支持 Everyone、PG13、Mature 与未分级；提供与 DSH 插件一致的单选分类及“全部”。项目元数据优先于旧的本地标签，界面删除手动设置分级。网格、列表、应用与轮播共用过滤规则，保留旧混合偏好和 Mature 启用确认；项目文件只读。

完整检查共 828 项（827 项通过、1 项环境跳过），原生 GTK 交互 98 项通过；私有常驻服务验证作者分级过滤、两轮洗牌、淡入淡出、崩溃恢复、视频 EOF 与四组宽窄屏／中英文布局。只读扫描现有 480 个 WE 项目无错误。见 [本批次记录](.validation/rating-source-20261014/REPORT.md)。

## 2026-10-13 · 壁纸三合一与顶栏独占区（Chrome 最大化避让）

壁纸控制中心的资源库、播放集与播放设置合并为同一页：宽屏左库右设置、中轴可鼠标拖动，窄屏上下堆叠；缩放方式、年龄分级与播放集同页可达，草稿、显式保存与分级确认语义不变。Chrome 点击标题栏“最大化”不再被顶栏遮挡：顶栏从 `layout.struts` 改为由灵动岛图层声明 layer-shell 独占区（`reserved_height(font_size)`，16px 字体为 67px），侧边胶囊保持 monitor-relative（exclusive_zone `-1`）；生成的 `niri/theme/theme.kdl` 中 `struts.top` 归零，避免与独占区重复留白。

隔离验证：817 项单元测试通过（分享包 817 项、5 项按环境跳过），完整 GTK 冒烟与面板探针各 97 项；`tools/maximize_probe.py` 用真实 Chrome 点击标题栏按钮，覆盖客户端最大化位于顶栏下方、灵动岛展开不改变窗口几何、还原/最大化按钮指针点击与全屏覆盖；本次续做复跑隔离探针仍通过（[日志](.validation/wallpaper-unified-20261013/live/isolated-maximize-rerun.log)）。发布为 20 个文件的原子增量，合成器与其它组件 PID 未变。

独占区只在托管 Eww 顶栏重启后对正式会话生效，因此本次续做在正式会话重启 `selandia-niri@waybar.service` 并实测：岛 `exclusive_zone=55`、左右胶囊 `-1`；顶栏预留恢复后平铺列高 2128 → 2061，真实 Chrome 客户端最大化窗口为 3840×2093（= 输出高 2160 − 预留 67），灵动岛展开时该窗口尺寸不变（[实时记录](.validation/wallpaper-unified-20261013/live/live-maximize.json)）。批次报告见 [REPORT.md](.validation/wallpaper-unified-20261013/REPORT.md)。

## 2026-10-13 · AI 请求停止

AI 侧栏增加等待期间的停止按钮和 Ctrl+.；本地请求在短生命周期子进程中执行，传输与等待共用 120 秒截止时间。取消成功后回收子进程，不写入半轮历史；保留新草稿，输入框空白时恢复原问题。取消与保存采用单次状态转换，已开始保存时继续完成，关闭侧栏时的后台保存行为保持原样。

13 项新增后台测试覆盖真实回环 HTTP 的延迟响应头/响应体、阻塞的历史写入、总截止时间、进程回收、取消/保存竞争与环境变量凭据。原生 GTK 增加历史保留、新草稿和保存竞争三项，并覆盖中英文及停止快捷键。完整日志、界面截图、首次失败记录和发布回滚信息见 [.validation/ai-cancel-20261013/REPORT.md](.validation/ai-cancel-20261013/REPORT.md)。服务端是否同步终止计算由服务实现决定。

## 2026-10-13 · 顶栏事件流与日历

顶栏改用 Niri 的常驻事件流更新窗口与工作区，显示器查询直接访问 IPC，取消每秒约 3.5 次 `niri msg` 子进程启动。事件断开后清空过期状态，重连重新接收完整快照；未知事件不会中断兼容性。空闲轮询从 25 次/秒降至最多 4 次/秒，动画保持原频率；本地操作通过 socket 立即唤醒。监督心跳仅更新私有状态文件，不再触发 Eww 无变化重绘。媒体和音量仍按秒读取，尚未完全事件化。

修复工作区重排后点击跳错：使用稳定 ID 的原生 IPC 动作，不把 ID 当成显示序号。日历加入玻璃主题样式和“复制日期”，复制所选 ISO 日期到剪贴板，保留今天与键盘导航。

本轮在 `.staging/de-polish-20261013/project` 完成并隔离验证。完整检查、图形证据、前后开销采样及发布回滚日志见 [.validation/de-polish-20261013](.validation/de-polish-20261013)。总目标仍在推进；已知下一步和验证边界见 [桌面完善进度](docs/DEVELOPMENT.md)。

## 2026-10-11 · 当前软件显示与紧凑椭圆顶栏

新增左侧当前软件名与标题提示，普通文本处理、空窗口和查询失败的双语默认提示。两侧胶囊高度匹配收起的灵动岛，保留现有横向尺寸；选中/悬停/按下仍是椭圆，Rust 输入区域同步。右侧时间继续打开独立日历。

[新证据目录](.validation/bar-capsules-20261011) 包含完整检查、隔离冒烟、800/1600 宽度 × 12/16/20px 字体 × 20%/100% alpha 的原生分配与像素证据，以及两个真实 GTK 软件焦点切换。发布采用持久备份的增量事务，只重启托管 Eww；以 compositor PID/启动标识与其它组件 PID 证明范围。

## 2026-10-11 · 已替代组件删除与时间点击日历

按用户确认删除 Waybar、Kitty 及两个附属包；不推断长期观察门槛已达成。清理安装/导出声明、主题生成、旧启动入口与专用探针，保留仍承担日常功能的非 Rust 组件。加入旧偏好迁移、必需依赖报错、文件删除/恢复与删除中 SIGKILL 恢复测试。独立日历复用 GTK 控件，右侧时间不再打开控制中心。

本轮验证、系统包状态与发布日志见 [新证据目录](.validation/rust-prune-20261011)。不重启 Niri；只重启托管 Eww 顶栏以应用点击动作。休眠问题沿用此前“未能复现”的结论，不以本轮软件清理声称解决。

## 2026-10-11 守护进程探测超时

现场结论：沙箱里的 `swaync-client --help | head -45` 因客户端受限 socket／D-Bus 的无界 poll 等待而卡住 69 分钟；结束客户端后 11:38:26 管道才完成，不是模型或批准门。维护规则见 [维护指南](docs/MAINTENANCE.md#守护进程探测必须有截止时间)。

`check.sh` 的一次性会话检查增加 3–15 秒截止时间和 2 秒强杀兜底；所有 `tools/*.py` 同步 subprocess 调用均有超时。测试全进程组上限 180 秒，真实挂起记录器的系统总线连接上限 5 秒；长期记录总预算 1 小时且仅由用户在正式终端执行。编译／UI／一分钟轮播等较长预算的理由已在维护文档明确。

新增 5 项回归通过：静态遗漏检查、真实阻塞子进程及无泄漏、忽略 SIGTERM 的强杀兜底、私有测试全进程组截止时间、系统总线连接成功／失败／超时。暂存完整 `./check.sh` 退出 0，830 项测试（1 项跳过）；完整隔离 GTK 冒烟退出 0（83.52 秒），含六次托管应急顶栏重启及原生锁屏就绪。

第一遍暂存检查因缺历史审计附件失败，补齐原件后通过；冒烟曾遇到不存在音频端点的 Waybar 重连错误、嵌套截图尺寸变化，已分别补私有空音频输出并重新验证。失败日志保留，不将其改写成通过。此批次不改 `niri/`、不重载／重启正式组件。关键副本继续在 `.staging/`，证据和发布前原文件在 [.validation/daemon-timeouts-20261011](.validation/daemon-timeouts-20261011)。

# Validation · 验证记录

## 2026-11-13：日常操作、资源调度与显卡监控

候选完成 1015 项完整检查（1014 通过、1 项环境跳过）、107 项原生 GTK 交互、18 个设置页×8种配置的144张渲染检查；另以420×580、16px字体验证日历普通滚动与Ctrl切月、8项原生草稿／历史操作，以及12组顶栏布局。所有预览均使用独立桌面、D-Bus与状态目录。短日历不要求整月首屏显示，要求末周可滚动到且操作按钮保持可达。

GPU接口覆盖范围、静态缓存与线程限制见[日常操作](docs/DAILY_USE.md)和[显卡监控](docs/GPU_MONITORING.md)。资源对照、源文件哈希、失败记录、激活状态与用户偏好保护见[本轮记录](.validation/daily-improve-20261113-release/REPORT.md)。真实物理休眠／唤醒与NVIDIA硬件未在本轮验证。

## 2026-10-11：屏幕唤醒排查

结论：未能复现，尚不能宣称已修复。上一启动使用 Intel i915/xe，存在 475 次 DRM Page flip busy、DP-6 断连和 missing surface；未记录 PM suspend entry/exit 或 systemd-suspend 执行，不能证明真实系统挂起。保留原始 journal 与事件时间线于 `.validation/resume-rust-20261011/`，新增只读持久采集器和自动化测试。具体命令与时机见 [恢复诊断](docs/RESUME_DIAGNOSTICS.md)。之前的隔离锁屏 readiness 不涵盖物理挂起/唤醒。

## 2026-10-10：壁纸精细播放集、分级与显示方式

最初在 `/tmp/selandia-playlist-controls-72xru4bo/project` 实施，重启后由项目内持久备份恢复；收尾在 `.staging/wallpaper-controls-20261011/project/` 重新验证与发布：具名集合兼容迁移、草稿精细编辑、权重随机与持久洗牌、1 秒–180 分钟定时、分级确认/过滤、六种显示模式及真实静态淡入淡出。所有切换由常驻服务事务交接，音频实时控制保留；新文案使用 `tr()`，旧标签保持 `tr_legacy()`。

证据位于 `.validation/wallpaper-controls-20261010/` 的新目录：单元测试、真实 GTK 交互、嵌套服务、淡入淡出像素、SIGKILL 恢复、视频 EOF、宽窄布局、完整检查与三份分享包。最终计数和发布后验证见该目录 REPORT.md。动态后端不支持交叉淡化、部分显示模式采用明确提示的最接近行为，详见 [壁纸播放集指南](docs/WALLPAPERS.md)。正式应用只增量更新面板并重启受管理的壁纸组件，保留 Niri 合成器身份及用户偏好，不自动启用轮播。

## 2026-10-10：五项控制中心视觉回归

先在 `/tmp/selandia-visual-fixes-k9fxk2kc/project` 复现并修改。显式声明所有选中／勾选／按下状态圆角，图形探针完整加载应用样式。Waybar 背景透明规则保留唯一真源，生成器统一所有胶囊与强调状态的 alpha；同时关闭其原生图层噪点和饱和度偏移，避免透明空隙仍被染色。低透明度面板使用无噪点图层和无模糊 1px 文字描边，保留用户 alpha，检查动画最终 widget opacity 为 1。壁纸页分为资源库、播放集和播放设置，移除外层滚动，宽窄屏量测实际裁剪范围后至少两行完整可见。

新增真实 GTK 四角像素、13 个胶囊及 5 类状态的 20／100% 背景对比、字形参考与软阴影外溢统计、原生 Waybar 高细节壁纸空隙对比、20／25／30% 面板截图，以及宽窄屏可见行数断言。新文案均走 `tr()`，旧文案保持 `tr_legacy()`。源码、测试、完整检查和隔离冒烟的证据放在 `.validation/visual-defects-20261010/`；最终结果和回滚方式见其中 `REPORT.md`，维护方法见 [控制中心视觉回归](docs/CONTROL_CENTER.md)。


## 2026-10-10：YG 复核四项修正

先在 `/tmp/selandia-review-fixes-aicvvl2z/project` 实施。不透明度前后端同步支持 20–100%，低于 40% 增强文字／描边／分隔线；壁纸视图按钮为“网格／列表”。新增当前壁纸与持久播放集，调度在 `wallpaper.py run` 常驻服务，复用原子切换、失败回滚和主题取色路径；涵盖 SIGKILL 中断记录恢复、并发手动选择优先、空集与失败退避。系统页提供 25 类可选中／复制的单栏信息，不依赖 fastfetch/lspci，缺项不可用。

完整检查、单元测试、隔离冒烟，以及真实 20% 应用重开、剪贴板对比、三次一分钟随机轮播／视频 EOF 区别的日志与截图保存在 `.validation/review-fixes-20261010/`。验收说明与行号见该目录 `REPORT.md`。配置和测试不操作正式 Niri 服务；发布保留用户外观偏好，轮播默认关闭，不自动接管用户壁纸播放集。所有新界面文案使用 `tr()`，旧标签保留 `tr_legacy()`。


## 2026-10-10：最终复核与故障路径补齐

本轮重新复核源码、配置、脚本、依赖、systemd／portal、安装与卸载事务、文档和分享包；既有审计记录保留，不以旧测试结果代替当前验证。在 `/tmp/selandia-final-form-vs4pjn42/project` 修改，正式发布继续使用持久回滚记录，不重启 Niri 合成器。

补齐发布准备后编辑保护、载荷／备份批量预校验、组件 PID 稳定性检查，以及导出中断和竞争发布保护。相同分享内容去除 gzip 文件名与时间后可逐字节复现。新增真实 SIGKILL、损坏备份、并发文件出现与持续替换进程的自动化回归。

壁纸音频显式调用不再吞掉命令失败：失败恢复偏好和本次触及的实际声道／静音状态，过期或被复用的流不回写。后台保持尽力初始化、不停止画面。系统指标拒绝负数内存计数，缺失温度不会使顶栏提示崩溃；NVIDIA 详细读数按 PCI 地址对应驱动信息，未在 Intel 主机安装 NVIDIA 软件。

隔离冒烟的可见性保护纳入项目，不依赖临时补救脚本；只操作测试自身的嵌套窗口，运行目录也独立。维护约定见 [维护指南](docs/MAINTENANCE.md)。当前完整检查、单元测试、真实图形／音频测试、三份分享包及发布后复验保存在 `.validation/final-form-20261010/`；结果以该目录最终记录为准。无显示服务器与私有 systemd cgroup 的跳过项单列，未执行真实睡眠、合盖或硬件唤醒。


## 2026-10-09：应用音量、壁纸网格与连续播放、系统详情和面板尺寸

本轮先在 `/tmp/selandia-controls-volume-8utwjc5b/project` 修改。声音页内嵌播放／录音流控制，验证后台线程、滑块合并、只读刷新、流退出／ID 复用、不可用读数及另一应用不受影响。壁纸列表／网格覆盖大图、选择／搜索同步、重扫元数据及 1000 项库最多三个并发缩略图任务。系统数据用隔离 proc/sys 样本覆盖拓扑、频率、分区、PCI／驱动、进程初次采样和 PID 复用，缺失保持不可用。

私有 PipeWire/Pulse 空接收器实测视频、场景和 Web：同一主管／渲染器 PID 与启动时间下，50% → 25% → 静音均生效；外部混音器的另一项调整不被覆盖；无音频服务仍可显示画面。两个播放应用、一个录音应用各自独立调节，客户端保持运行。宽窄屏使用实际生成的玻璃样式和嵌套 Niri 截图，另覆盖 4K／150% 尺寸计算与小屏快捷键分支。

完整检查、单元测试、隔离冒烟、GTK、音频、宽窄屏及三份分享包结果见[本轮记录](.validation/controls-volume-20261009/summary.json)。升级仅替换已验证文件；动态壁纸主管需一次受 systemd 托管的重启以建立带启动时间的运行记录，此后声音改动不重播。设置面板重开加载新界面；Niri 合成器保持运行。备份位于 `.validation/controls-volume-20261009/release/`，回滚本轮先运行：

```bash
python3 -B tools/live_update.py rollback --journal .validation/controls-volume-20261009/release --reload
```

回滚后关闭／重开设置面板；若继续回滚旧轮次，按本轮 → Waybar 补修 → 玻璃／AI 原更新的顺序。后续手动修改冲突仍会保留并报告。

Arch Linux · Niri 26.04 (8ed0da4).

## 2026-10-09：Waybar 信号重载的僵尸子进程

正式 Waybar PID 1644 的七个僵尸归属于它自身（后续只读复查增长至十个）；`live_update.py` 使用等待退出的 `subprocess.run` 调用服务管理器，没有直接 fork Waybar。私有 D-Bus 与嵌套 Niri 中，原 `SIGUSR2` 重载路径连续 24 次复现僵尸累积（首次 39 个，最终带面板探针复测 13 个）；通过私有监督器执行新代码的 12 次托管重启后，每次旧主进程都已回收、新顶栏僵尸数均为 0。探针采用子进程收养及显式等待，回收自己的复现进程，不操作正式服务。

主题应用改由 systemd 重启完整 Waybar 服务，保留通知 CSS 重载与禁用组件保护；重启前清除自动失败计数。布局监测运行在 Waybar 子进程中，因此只提交 `--no-block` 重启，避免等待自己被停止。`niri/` 下修改 `shell/reload_components.py` 与 `shell/bar_layout.py`（两处发送重载信号的实现），以及 `waybar/config.jsonc` 与由模板生成的 `theme/waybar.jsonc`（点击入口改用 Niri spawn，让新打开的面板独立于顶栏服务，重启不关闭面板）。这些运行路径必须在 `niri/` 中修改；不改变 Niri 合成器配置或重启它。新增失败／超时／服务未就绪与面板启动归属单元测试；完整冒烟改为验证实际重载函数的六次隔离重启、旧进程回收和新顶栏零僵尸。专用探针实际打开 AI 与设置面板，验证它们在十二次顶栏重启后仍运行。

完整检查、单元测试、隔离冒烟、三份分享包与发布后的实际进程结果见 [本轮记录](.validation/waybar-reap-20261009/summary.json)。本轮持久备份为 `.validation/waybar-reap-20261009/release/`。若要回滚本次补修，运行：

```bash
python3 -B tools/live_update.py rollback --journal .validation/waybar-reap-20261009/release
```

回滚文件后，下一次应用主题会加载恢复后的重载逻辑；无需重启合成器。若还要回滚下方的玻璃／声音／AI 更新，必须先回滚本次补修，再执行下方原更新的回滚命令，以保留两轮之间的文件冲突保护。

## 2026-10-09：分段玻璃、壁纸声音与多配置 AI

本轮先在 `/tmp/selandia-glass-ai-oeno110g/project` 修改，使用私有 D-Bus、内存 GSettings、独立 XDG 目录和嵌套 Niri 验证。九套主题均覆盖深浅模式；胶囊间距重新按最大文本、声音／电池／托盘占位和十个工作区测量，保留溢出负例。新的真实像素标定在 [顶栏数据](.validation/bar-measurements.json)。

音频使用独立 PipeWire／Pulse 空输出与只管理软件连接的 WirePlumber policy 配置，未连接正式音频服务或加载硬件监视器。视频、单声道场景与本地 Web 各测试发声、降音量和静音；采样及结果在 [音频记录](.validation/glass-ai-20261009/audio/results.json)。场景单声道测试复现原库缓冲越界，修补按输出声道分配，并正确返回复制长度；项目本地库只对已核验的系统后端 ABI 生效。

AI 五种配置使用真实回环 HTTP 服务器验证各自的请求格式、鉴权环境变量和隔离历史，没有使用用户 API 密钥或付费服务。持久记录覆盖关闭／重开、切换配置与会话、修改端点后保留旧连接、失败写入、并发和 SIGKILL。发布回滚覆盖重载失败、后续用户编辑保护与发布中 SIGKILL。

完整校验、单元测试、真实 GTK 交互、嵌套桌面截图、三份分享包及实际增量发布结果见 [本轮记录](.validation/glass-ai-20261009/summary.json)。完整检查与单元测试中的 systemd cgroup 跳过项单列；不会把无显示环境的跳过视为图形验证通过。

发布前说明可见变化，保留 Niri 合成器及用户字体；让玻璃透光所需的不透明度调整与原偏好一同记录。只重载受管理的顶栏／通知和实时壁纸；已打开面板重开后加载新界面。持久备份位于 `.validation/glass-ai-20261009/release/`。在项目目录回滚本轮：

```bash
python3 -B tools/live_update.py rollback --journal .validation/glass-ai-20261009/release --reload
```

此命令在发现发布后手工编辑冲突时拒绝覆盖；原备份仍保留。当前有效配置是 `/home/SelandiaNyx/.config/niri/config.kdl`，解析到 `/home/SelandiaNyx/Selandia's Niri/niri/config.kdl`；项目位于 `/home/SelandiaNyx/Selandia's Niri`。

## 2026-10-09：可选壁纸依赖与安装指引

本轮在 `/tmp` 副本修改与验证，使用私有 D-Bus、内存 GSettings 和独立 Niri；不重启、重载或操作正式会话服务。实际安装由交互式终端完成，用户在该终端确认并输入 sudo 密码；包版本为 `mpvpaper 1.9-1`、`linux-wallpaperengine-git r627.b016d7d1-2（本地上游兼容修补）`。本机检测到 Intel Arc B580 和 Intel 核显，没有 NVIDIA 显卡，未安装 NVIDIA 软件；`ffmpeg`、`brightnessctl`、`ddcutil` 已具备。

原版 AUR 后端复现 CEF 启动失败与 Web 黑屏／卡帧；本地包采用上游 PR #639 与问题 #680 的纹理、帧率及退出修补，原版和修补版对照日志均保留。新增可选依赖声明与准确安装命令；缺后端时保持静态预览；重新扫描后更新可用状态；实验性 Web 播放显式应用。区分“缺视频缩略图工具”和“场景/Web 没有有效预览图”。本轮源码、分享包、真实视频/场景/Web 播放与完整验证结果见 [本轮记录](.validation/dependencies-20261009/summary.json)。无显示服务器和私有 systemd 环境的跳过项单独记录；未执行真实睡眠、合盖或硬件唤醒。

## 2026-10-09：P2 / P3 修复与当前版本验证

本轮验证在 `/tmp` 配置副本、私有 D-Bus、内存 GSettings 和嵌套 Niri 中进行，不重启或重载正式会话服务。源码验证与分享包验证分别记录在 [本轮记录](.validation/p2p3-20261009/summary.json)；历史段落的日期和测试数量保留，不代表当前版本。

无显示服务器时，GTK 图标测试明确跳过并说明原因；有显示环境的单元测试与隔离冒烟验证图形行为。当前完整检查、单元测试、隔离冒烟和三份分享包的最终结果见本轮记录，包含源码指纹、压缩包及包内文件校验值、测试数量和跳过项。

本轮源码结果：`./check.sh` exit 0（[日志](.validation/p2p3-20261009/full-check.log)）；独立单元测试 **624 项，OK (skipped=1)**（[日志](.validation/p2p3-20261009/unit.log)）；无显示环境 **616 项，OK (skipped=2)**（[日志](.validation/p2p3-20261009/headless.log)）；完整隔离冒烟通过，含 **65 项 GTK 交互**、实际显示确认/回滚、六次隔离组件重载、真实锁屏就绪，以及新增的会话身份和状态栏测量检查（[日志](.validation/p2p3-20261009/smoke.log)）。完整检查因没有正式会话 IPC，按设计跳过正式会话服务检查；源码单元跳过真实 systemd 锁屏 cgroup 测试，无显示环境另跳过 GTK 图标测试。

三份分享包各自通过内部 SHA256SUMS、配置检查、**621 项单元测试（skipped=6）**及“安装 → 首次显示设置 → 确认／手动回滚／超时回滚”贯通验证。包内省略历史截图和原机器审计记录，因此另外跳过对应证据测试；三份包的文件清单和内容指纹一致。压缩包 SHA256 与各自测试日志列在本轮记录中。

覆盖并发编辑、恢复中断与真实 SIGKILL、项目移动后语言恢复、自启动及服务屏蔽卸载、嵌套会话身份、壁纸服务恢复、状态栏测量隔离、无显示环境和兼容导出入口。外部睡眠受 logind 等待上限及合盖策略限制；未执行真实睡眠、合盖、硬件唤醒或正式会话服务操作，私有环境也不验证正式 systemd 锁屏 cgroup 生命周期。

## 2026-10-05：电源子菜单改为原生窗口 + 启动项移除

**电源子菜单不再使用 `fuzzel --dmenu`。** 旧菜单的输入框对五个固定条目毫无用处，却能让误输入静默筛选列表——输入一个 `r` 再按回车就会重启。现在 `niri/scripts/desktop power` 打开 [niri/shell/power_menu.py](niri/shell/power_menu.py)：一个 layer-shell 原生窗口，五个固定按钮，界面中**没有任何文本输入**；注销、重启、关机在同一窗口内二次确认后才由脚本执行，菜单只输出动作标识，未知输出返回 2，锁屏与睡眠仍走 `power_actions.py`，与自动计时共用同一入口。Esc、关闭按钮或失去焦点都会关闭菜单。

**开机启动页可以移除托管启动项。** 每个条目现在是“启用/停用 + 移除”，移除前必须在该条目内二次确认；后端 `remove_startup()` 只删除本页创建的 `autostart/selandia-niri-*.desktop`，并拒绝符号链接、非托管文件、路径穿越和已不存在的条目，删除失败会报错而不是假称成功。

- **`./check.sh` 完整通过（exit 0）**：[日志](.validation/power-menu-check.log)（539 项单元测试与实时会话组件检查；Niri/Fuzzel 配置、JSON、Shell 与 Python 语法、GTK 3/4 样式全部通过）。
- **539 项单元测试通过**（上一轮 521 项）：[日志](.validation/power-menu-unit.log)。新增覆盖见 [tests/test_power_menu.py](tests/test_power_menu.py)（动作清单、确认门、保持唤醒标注、脚本分派标识一致）、[tests/test_system_settings.py](tests/test_system_settings.py)（移除校验、只删托管项、失败上报）与 [tests/test_desktop_actions.py](tests/test_desktop_actions.py)（电源分派、取消与未知输出）。
- **57 项真实 GTK 交互测试通过**（上一轮 52 项），完整嵌套冒烟通过：[日志](.validation/power-menu-smoke.log)。新增 5 项覆盖窗口内没有任何 `Gtk.Entry`、重启必须先确认、取消不产生动作、锁屏/睡眠无需确认、保持唤醒标注只来自已确认的抑制锁，以及启动项移除的二次确认。
- **证据**：[电源子菜单](.validation/power-menu.png)、[二次确认](.validation/power-menu-confirm.png)、[保持唤醒标注](.validation/power-menu-stay-awake.png)、[开机启动页](.validation/startup.png)；三种菜单状态由新增的 [tools/power_menu_probe.py](tools/power_menu_probe.py) 在隔离会话中截图。
- **未验证**：真实的注销、重启、关机与实际睡眠。探针只验证窗口报告的选择，不执行任何会话操作；主机的 `autostart` 目录没有被真实删除过（单元测试与交互测试都使用临时目录和模拟后端）。

## 2026-10-05：A1–A8 自检问题整改（第二轮：真实环境实测）

获得完整权限后，真实用户 systemd 与嵌套合成器均可用，上一轮"未验证"的项目已逐项实测，并发现 3 个只在真实环境暴露的缺陷（锁屏单元探测永远失败、渲染函数调用子进程、退出请求粘性）。逐项结果与实测数据见 [.validation/FIXES.md](.validation/FIXES.md) 与 [.validation/bar-measurements.json](.validation/bar-measurements.json)。

- **`./check.sh` 完整通过（exit 0）**：[日志](.validation/fix-check-full.log)。现在包含单元测试（521 项）与实时会话组件检查。
- **锁屏 cgroup 隔离在真实用户管理器上 3/3 通过**：[日志](.validation/fix-lock-isolation.log)。用测试专用瞬态单元模拟 idle/sleep-lock，未触碰真实桌面锁屏。
- **完整嵌套会话冒烟通过**：[日志](.validation/fix-smoke.log)，含 52 项 GTK 交互测试、媒体/显示/字体探针、连续 6 次重载、真实 swaylock 就绪与复用。
- **A3 像素级验收实测**：1066 逻辑像素 → compact（边距 18/17 保留，不裁切）；3840 逻辑像素 → wide（18/18）。compact 阈值 773 逻辑像素 @16px。见 [bar-measurements.json](.validation/bar-measurements.json) 与 [bar-measure-before/after 截图](.validation/bar-measure-after.png)。
- 未验证：浅色整机一致性、真实硬件睡眠/整夜息屏/PAM 解锁。

## 2026-10-05：A1–A8 自检问题整改

按 [.validation/PROJECT_AUDIT.md](.validation/PROJECT_AUDIT.md) 的交接要求完成 A1–A8 与测试覆盖缺口，逐项实现、测试与未验证项见 [.validation/FIXES.md](.validation/FIXES.md)，本轮实测数据见 [.validation/fix-summary.json](.validation/fix-summary.json)。

- **521 项单元测试通过**（1 项按设计跳过）：[完整日志](.validation/fix-unit.log)。新增或重写的覆盖包括锁屏就绪协议与启动器选择、面板提交任务生命周期、读取期间冻结草稿、统一睡眠入口、快捷键单语言与 Fuzzel placeholder、符号图标在 100%/150%/200% 的透明渲染、状态栏宽/紧凑布局与合法 GTK CSS、界面字号 px→pt 换算、界面文案语言矩阵、状态栏日志归因。
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


## 2026-10-11 Rust 组件与灵动岛验收

持久源码位于 `.staging/resume-rust-20261011/project`，新证据目录为 `.validation/resume-rust-20261011/`。发布前完整 check.sh 为 0；单元测试 823 项、跳过 1 项；隔离完整冒烟含 94 项真实 GTK 交互和 6 次托管 Waybar 重启。

原生 Eww 在 800 / 1600 逻辑像素、20% / 100% 不透明度四组通过：时间实际分配在右半屏、中心偏差 0、收起宽 96、展开宽 176 / 460，动画途中有中间宽度，旁侧位置不变；收回高度 46。每个胶囊有底色像素变化，空隙与测试壁纸像素一致；虚拟鼠标实际点击空隙/圆角传递到下层，胶囊内不穿透。真实 GTK 媒体按钮点击触发私有 MPRIS 的 Next/Previous/Pause/Play；进度 25%、本地封面可见。独立 PipeWire 验证外部音量事件 61%、控制 44%、刷新保留 37%。Anyrun 和 Alacritty 原生界面可见。

正式增量发布和三种故障演练使用持久回滚日志，只重启托管顶栏，不重启 Niri；正式日志另存 `live/`。实际登录 10 次和无故障 7 日是后续稳定观察门槛，本轮不能把组件重启和隔离测试算成登录，因此继续保留全部应急配置及软件包。非 Rust 日常依赖、移除条件和离线切换命令见 `docs/EMERGENCY_COMPONENTS.md`。

休眠黑屏仍为“未能复现、尚未定位”，详见 `docs/RESUME_DIAGNOSTICS.md`；真实挂起/PAM 的硬件结论不能用隔离验收代替。

### 正式发布、演练与隔离遗漏修正

Rust 增量批次已发布 51 个文件，持久回滚日志为 `.validation/resume-rust-20261011/release/journal.json`；发布未更改壁纸、通知、sleep-lock 的 PID，也未重启 Niri。真实 3840 像素会话时间 x=3444，岛宽 96→613。正式 13 个胶囊在 20% / 100% 下均有底色变化，最小 RGB 通道差 39；3 个无遮挡壁纸点逐字节相同。同一时钟前缀的 120 个高亮字芯像素在 20% 下全部保留，此指标不代表所有字体或 MTF。原生窄/宽测试另验证圆角鼠标穿透。受控 MPRIS 在正式总线验证事件、封面、25% 进度及四个定向动作，不控制用户播放器；真实 GTK 鼠标点击覆盖在私有会话。

三类正式故障注入和全套应急恢复已通过；用户实际 PAM 解锁成功。证据分别为 live/drills-result.json、live/lock-result.json、live/pixel-result.json。稳定门槛仍未满足，保留旧组件。

一次直接正式自检暴露旧壁纸单元测试未隔离运行时 socket，误把临时壁纸切换送入正式服务。原 wallpaper.json 和 appearance.json 已逐字节恢复，使用缓存覆盖后恢复托管壁纸服务；Niri 未重启。修正：单元测试私有环境/总线、壁纸 IPC 增加状态目录命名空间、旧 fixture 明确隔离 runtime，并添加同显示/不同状态无法触达服务的回归。失败记录保留为 formal-check-tail.log；恢复证据为 live/test-isolation-recovery-result.json，不能把这次失败写成通过。修正后重新运行完整检查、单元测试、隔离冒烟与壁纸强杀/轮播验收，最终结果见新隔离修正批次日志。

最终发布后验收：正式 `./check.sh` 为 0（825 项单元，1 项明确跳过），完整日志 formal-final-check.log；最终生产副本的 check/unit/smoke 均为 0，日志位于 postpublish-final/。三份最终 dist 内容逐字节相同，SHA256 为 f7d463bd34403c675b21feb7801246c2d44f6ea5ea6ce68c1cf3bfacee3c3291，每包 204 个校验条目。原外观/壁纸偏好逐字节一致，Niri 始终 PID 1125 / start 1025，当前 Eww 托管进程没有僵尸直接子进程。

## 2026-10-28 MD3 架构与集成验收

### 1. 架构实现与规格

- **控制中心层叠与布局**：采用普通浮动对话框层叠形态，提供 17 项分类入口并归纳为 4 组（默认应用与语言合并入 System 模块）；左侧展开 AI 抽屉（宽 440px），右侧展开 Calendar 抽屉（宽 420px）。
- **组件与生命周期规范**：共享 MD3 语义角色与圆角弧度，支持未提交表单草稿保存；页面实施按需懒加载构造并常驻缓存，面板隐藏期间严格挂起只读活动（写入通道不受影响）；后台 worker 线程池并发上限限定为 3。动态承接用户偏好，font13/.92 仅为审计 profile 而非系统默认值。
- **通知视觉对齐**：通知视觉对齐已落实，外宽 420px（内部 386px + 内边距 32px + 边框 2px），顶部除合成器预留顶栏外追加 12px 间隙；最终原生验证记录于 DELIVERY.md。

### 2. 测试与原生交互证据

- **单元测试**：2026-10-25 单元测试运行 919 项，0 失败、0 错误、1 跳过。
- **原生面板交互**：2026-10-27 原生面板 107 项交互测试全通（耗时 27.874s）。
- **专用原生用例**：10 项专用原生用例全面覆盖中文 13 日历、2 项动效几何、Quick 懒加载冷启动、Media 隐藏跟随、壁纸积压与跟随、Calendar 20 常规/窄屏/短视口。

### 3. 受控资源 A/B 基准测量

- **基准产物**：.staging/md3-shell-20261020/validation/artifacts/resource-20261027-013055-42e0/。
- **测试循环**：每分支执行 60 周期（Control / AI / Calendar 各 20 周期）。
- **性能与开销对比**：
  - 首映射耗时：基线 0.115762s vs 暂存 0.048003s。
  - 最终关闭态 RSS：基线 249736 KiB vs 暂存 151420 KiB。
  - 测试基于受控夹具（非真实空闲或零泄漏绝对证明，度量指标为上下文切换而非系统唤醒）。

### 4. 全量集成套件验收

- **集成产物**：.staging/md3-shell-20261020/validation/artifacts/integration-20261027-224302-f606d455f6f54e1caadbdeaef67dd604/。
- **运行结果**：93.458s PASS，产出 27 张全新 PNG 截图，覆盖 17 项设置页面及全部菜单/抽屉。
- **环境与看门狗验证**：完成隔离会话中的显示设置独立回退看门狗、私有字体选择器、无 PAM 锁屏就绪、6 次私有顶栏重载；源码 148 文件及用户偏好保持无损。
- **窗口与真实应用交互**：真实 Chrome 窗口最大化/标题栏恢复/全屏以及弹窗（通过模拟授权验证，非真实 Polkit）均符合 AUDIT_NOTES 记录。

### 5. 发布状态

2026-10-28 MD3 交付版本；实际发布状态、最终验收及导出结果以 .validation/md3-20261028-release/DELIVERY.md 为准。
