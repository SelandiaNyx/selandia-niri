# 资源、主题与语言只读审查

检查时间：2026-10-04 19:02–19:10（Asia/Shanghai）。整理时间：2026-10-05。

本次只读取项目及系统资源，使用 `/tmp` 导出图标检查图片；没有修改源码、用户配置、主题选择或声音设备。下列路径及行号对应审查时源码。

## 已通过的资源检查

- 源码使用的 31 种 `*-symbolic` 图标，在 Adwaita、Breeze、Breeze Dark 三个图标主题中均可找到；`Gtk.IconInfo.is_symbolic()` 均为真。因此“找到资源”不等于“渲染正确”，见问题 1。
- 当前字体 `JetBrainsMonoNL Nerd Font Mono`、备用 `Noto Sans`、`Noto Sans CJK SC`、`JetBrainsMono Nerd Font` 均可由 `fc-match` 匹配到实际字体文件。
- 默认配置中的 `Inter` 当前没有安装，`fc-match Inter` 回退至 `Noto Sans`。已有回退，因此不属于文字无法显示的问题；若默认设计明确要求 Inter，应将它加入 Arch 依赖清单，或直接把默认字体改为保证安装的字体。
- `find -L niri -type l` 没有报告失效符号链接。
- 当前 GTK 设置使用 `Breeze-Dark` 和 `breeze-dark`。卸载 Plasma 时保留 Breeze 可维持这部分资源；下述面板图标修复不应依赖更改整个系统主题。

## 问题 1：150% 缩放下“键盘与鼠标”图标成为实心方块

优先级：P2，已实际复现。

位置：

- `niri/shell/settings_navigation.py:13`：`input-keyboard-symbolic`。
- `niri/shell/control_widgets.py:24`：`Gtk.Image.new_from_icon_name()`，跟随系统图标主题，设置像素尺寸为 18。
- 系统命中的问题资源：`/usr/share/icons/breeze-dark/devices/32/input-keyboard-symbolic.svg`；Breeze 浅色同尺寸资源也有同样表现。

证据：root 当次新生成的 `.validation/control.png` 中侧栏“键盘与鼠标”左侧为实心灰方块。独立调用 `Gtk.IconTheme.lookup_icon_for_scale('input-keyboard-symbolic', 18, 2, Gtk.IconLookupFlags.FORCE_SYMBOLIC)`，再调用 `load_symbolic()`，结果如下：

| 图标主题 | lookup scale | 输出尺寸 | 全透明像素数 | 全不透明像素数 |
| --- | --- | --- | --- | --- |
| breeze-dark | 1 | 22×22 | 375 | 101 |
| breeze-dark | 2 | 44×44 | 0 | 1936 |
| breeze | 2 | 44×44 | 0 | 1936 |
| Adwaita | 1 | 18×18 | 96 | 87 |
| Adwaita | 2 | 36×36 | 475 | 566 |

2× 的 Breeze 图像全部像素不透明，独立导出图片也确认是方块；1× 和 Adwaita 对照正常。GTK 在分数缩放时使用整数缓冲缩放，和 150% 实际截图现象一致。这里已证实资源选择/渲染组合有问题，尚未把原因归咎于某个上游库的具体缺陷。

导出图片原位于 `/tmp/audit-breeze-dark-keyboard-2.png` 等。2026-10-05 整理时 `/tmp` 原图已不存在，未伪造或重新生成图像；保留上述当时工具结果和实际截图记录。若 `.validation/control.png` 后续被重跑覆盖，应重新按以下验收步骤取图。

给其他 AI 的修改指令：

> 在 `control_widgets.py`/`settings_navigation.py` 为面板建立可预测的 symbolic 图标加载策略，至少修复键盘图标。可为该图标提供已验证的项目内 SVG，或仅在面板内显式选择经验证的图标资源；不要修改 `/usr/share/icons`，不要为了一个图标切换整个系统的 Breeze 主题。保证选中、未选中和暗/亮背景中的前景色正确。不能只把 `lookup_icon` 成功当作验收通过。

验收：100%、150%、200% 缩放，深浅模式下键盘轮廓和按键均可辨认；图标在 1×/2× 渲染中含透明背景，不能是全实心矩形；其余侧栏图标、GTK/Qt 应用主题保持正常。

## 问题 2：Fuzzel 启动器仍同时显示中英文

优先级：P2，源码及实际生成文件已确认。

位置：

- `niri/fuzzel/fuzzel.ini:5`：`placeholder=Search applications · 搜索应用`。
- `niri/shell/appearance.py:333`：读取模板；334–339 行只替换字号、行高和颜色，保留双语 placeholder。
- `niri/theme/fuzzel.ini:5`：当时生成配置仍为上述双语。
- `niri/scripts/desktop:74`：直接启动 Fuzzel，不覆盖 placeholder。
- `niri/shell/ui_assets.py:12`：仅生成 Waybar/SwayNC 的单语言文本，没有处理 Fuzzel。

给其他 AI 的修改指令：

> 将 Fuzzel placeholder 纳入既有界面语言机制。应用启动器按 `resolve_ui_language()` 选择单一的 `Search applications` 或 `搜索应用`；界面语言切换后无需重新应用主题即可生效。可在启动脚本传明确 placeholder，或让 `ui_assets` 参与生成，但要避免外观重新生成后恢复成双语。Fuzzel 的剪贴板、电源、确认等 dmenu 模式不应显示“搜索应用”占位文案，应使用对应动作的单语言提示。

验收：中文/英文分别打开启动器、剪贴板、电源菜单，均只显示所选语言的界面文案；执行外观应用及重登录后仍一致。不要翻译应用名称、文件名或用户剪贴板数据。

## 问题 3：快捷键说明的复合文案没有完成单语言转换

优先级：P2，直接执行当前翻译函数复现。

位置：`niri/shell/shortcuts.py:110` 附近截图说明及工作区说明；`shortcuts.py:122` 至 127 行方向/对象说明；`niri/shell/i18n.py:83` 的 `tr_legacy()`；`niri/shell/panel.py:1486` 附近渲染描述。

对 117 条实际快捷键分别应用英文、中文和 `tr_legacy()`：英文至少 18 条、中文至少 46 条仍包含成对翻译。示例：`Super+Left` 在两种语言下均为 `Focus / 聚焦 · Column / 列 · Left / 左`。`tr_legacy()` 只处理单个分隔符，无法可靠处理多段拼接；工作区描述选择英文时还可能丢失目标/是否跟随等后缀信息。

给其他 AI 的修改指令：

> 把 `shortcuts.describe()` 的内置动作、方向、对象、截图保存方式、工作区目标和跟随行为改为结构化数据或完整 `tr(english, chinese)` 句子。不要通过对任意字符串全局拆斜线/中点进行翻译，用户自定义名称及命令应原样保留。搜索仍应支持两种语言的关键字。

验收：逐条渲染 117 条快捷键的中/英文版本；英文内置说明不含中文，中文内置说明不包含重复的英文翻译；截图保存与剪贴板区别、目标工作区、是否跟随窗口均保留；中英文搜索仍可找到方向和移动命令。

## 问题 4：界面字号 px 被直接作为应用和启动器 pt 使用

优先级：P2，配置语义已确认；最终视觉大小需由实际应用截图补充验证。

位置：

- `niri/shell/panel.py:1101`：界面字号明确标注为 px；终端字号单独标注 pt。
- `niri/shell/appearance.py:194`：面板 CSS 使用 `{size}px`。
- `niri/shell/application_theme.py:227`、236、247：相同数值直接写入 GTK/Pango 字体描述、Qt pointSize 和桌面字体设置。
- `niri/shell/appearance.py:334`：Fuzzel 使用 Fontconfig `:size={size+1}`，不是 `:pixelsize=`。

例如选择界面 16 px，面板为 16 px，而应用字体被写为 16 pt；96 DPI 下 16 pt 对应约 21.33 px。启动器另加 1 后成为 17 pt，约 22.67 px。层级字号差异可以有意设计，但 px/pt 的未换算不能解释为同一界面字号的一致应用。

给其他 AI 的修改指令：

> 保留界面字号的规范单位（当前是逻辑 px），把每个目标的 px/pt 换算写在明确的转换层；GTK 可选择明确的像素字体描述或正确的点数换算，Qt 使用正确 pointSize/pixelSize，Fuzzel 使用匹配的 pixelsize 与 DPI/缩放策略。不要改变独立的终端 pt 语义。补充单元测试验证数值含义，而不只是断言所有目标保存相同数字。

验收：12、16、20 px 在 100%/150%/200% 缩放下，面板、普通 GTK/Qt 应用、启动器的基础文本比例符合设计；不会因换算重复放大，字号 UI 单位与实际配置语义一致。

## 检查边界

本报告不代表全部页面无视觉缺陷；页面渲染、布局溢出、实际硬件操作及完整 smoke 结果由主审查汇总。资源检查期间没有真实调节音量、切换声音设备、改变显示模式、暂停播放器、锁定当前会话或触发睡眠。Plasma 卸载是另一个明确授权任务，由主代理执行，本报告没有执行卸载。
