# 壁纸播放集、分级与显示方式

控制中心 → 壁纸为单一页面，不再分成“资源库 / 播放集 / 播放设置”子页：宽屏左侧为资源库，右侧为设置区（含播放集），中间可拖动分隔；窄屏改为上下排列。同页滚动即可到达全部内容：靠前是所选预览、显示方式与分级筛选下拉，文件目录、声音和播放集在下方。资源库的网格和列表共享搜索、分级过滤及所选条目；切换视图不会应用壁纸。当前壁纸区块可刷新。

## 具名播放集

最多 16 个播放集，每个最多 1000 项。名称为 1–64 个汉字、字母、数字、空格或 `_-.()`，去除首尾空格；名称不能重复。输入名称后可新建、重命名、复制或删除；至少保留一个播放集，也可清空。下拉框切换当前编辑的播放集，在同一面板内保留各份草稿。**点“保存播放集”后，选中的播放集成为当前生效的播放集，并保存整个播放集工作区。** 关闭面板前请保存。

从资源库加入所选，或用当前筛选结果替换内容；可移出库中所选、移除编辑器中的单条、清空。条目列表选中一行后，可上移、下移、置顶、按名称或路径排序、启用/禁用、设置 1–100 的随机权重。权重越高，随机候选的概率越大；有其他可用项时不立即重复当前壁纸。禁用条目和被分级过滤的条目不参与手动上一条/下一条或自动轮播。

循环方式有顺序、按权重随机、洗牌不重复。洗牌的一轮内每个合格条目只出现一次，走完再洗；剩余顺序随成功切换原子保存。上一条按列表逆序移动。编辑条目或循环方式会重新开始洗牌周期；仅保存声音或未修改的播放集不会倒退周期。

定时最小 **1 秒**，最大 **10800 秒（180 分钟）**；UI 可选秒或分钟，持久化为秒。一次切换完成后才开始下一段间隔，不重叠启动渲染器。视频“播完切换”使用 mpv 的真实 EOF 并保留最后一帧；静态图片无播放结束事件，通常无限运行的场景和网页请使用定时方式。空集或全部禁用/过滤时服务保持空闲，不报错。

调度由 `selandia-niri@wallpaper.service` 的 `wallpaper.py run` 常驻执行，与 GTK 面板生命周期无关。手动切换和后台轮播复用 `activate()` 的事务：先校验/准备，写持久意图，原子保存，新渲染器就绪后交接；失败恢复偏好并重放原选择。强杀（SIGKILL）后启动恢复未提交事务。启用“跟随壁纸配色”时仍走原有 `theme-reload` 路径。

## 分级来源和筛选

分类与单选筛选行为参考 [DSH Wallpaper Engine 的实现](https://github.com/elysia395/dsh-wallpaper-engine/blob/c65821172eecfe5739b28d5f30261f0ef9e679ed/src/picker-model.js)。

分级来自作者元数据，不做联网画面识别。Wallpaper Engine 项目目录会读取 `project.json` 的 `contentrating` 字段，兼容 Everyone / G / General、PG13 / PG-13 / Questionable、Mature / Adult / 18+ / R18 等拼写；字段缺失或无法识别时归为**未分级**。没有项目元数据的本地独立图片／视频默认为 Everyone，并继续兼容旧版本保存的本地单文件手动标签（`ratings` 字段）；这些旧标签不会覆盖 WE 项目自身的分级，UI 也不再提供手动分级编辑。原项目文件只读，绝不回写 `project.json`。

同一三合一页面的设置区提供单选分级下拉：全部、Everyone、PG13、Mature、未分级。它一次只选一个分类，不是年龄上限；默认 Everyone。保存后同步用于资源库网格／列表、应用以及播放集上一条／下一条和自动轮播；筛选切换不会打断当前正在播放的壁纸，下一次切换才按新筛选挑选合格条目。

Mature 从未启用变为启用（选择 Mature，或选择包含 Mature 的“全部”）时必须明确确认；取消确认不保存，保持原来的已保存筛选。确认偏好可跨重启保持。本实现使用确认对话框，不收集或保存口令，因此没有明文口令、口令 hash 或钥匙环条目。直接编辑本机 JSON 不是身份验证机制。

旧版本保存的混合过滤继续以“已保存筛选”的形式保留，只有用户主动选择新的筛选项并保存后才被替换。保存格式中 `rating_filter` 扩展为 `everyone`、`questionable`、`mature`、`unrated` 四个布尔值，其中 `questionable` 是 PG13 的保存标识；选择“全部”即四个分类都启用。

分级过滤同时作用于列表、网格、使用筛选结果的批量操作及服务端轮播候选；直接应用被过滤掉的条目也会拒绝。改变筛选不会强行清除当前用户已应用的选择，下一次切换仅选合格条目。

## 显示模式与过渡

| 设置 | swaybg / 静态兜底 | mpvpaper / 视频 | linux-wallpaperengine / 场景、网页 |
| --- | --- | --- | --- |
| fill 填充 | `-m fill`，保持比例裁切铺满 | `panscan=1 keepaspect=yes video-unscaled=no` | 每个输出 `--scaling fill --clamp border` |
| cover 覆盖 | 与 fill 等价；swaybg 没有 cover 参数 | 与 fill 等价 | 与 fill 等价 |
| stretch 拉伸 | `-m stretch` | `keepaspect=no panscan=0` | `--scaling stretch --clamp border` |
| fit 完整显示 | `-m fit`，允许黑边 | `panscan=0 keepaspect=yes video-unscaled=no` | `--scaling fit --clamp border` |
| center 居中 | `-m center`，原尺寸 | `video-unscaled=yes panscan=0 keepaspect=yes` | 无等价模式，使用 fit，并在 UI 提示 |
| tile 平铺 | `-m tile`，原尺寸重复 | 不支持，使用 fit，并在 UI 提示 | 无等价模式，使用 fit，并在 UI 提示 |

网页自行决定 DOM 布局，后端缩放参数可能不影响网页内容；UI 明确说明。所有静态预览和兜底遵循同一个显示模式。后端参数核对来自本机 `swaybg --help`、`linux-wallpaperengine --help`，以及 [linux-wallpaperengine 参数解析](https://github.com/Almamu/linux-wallpaperengine/blob/master/src/WallpaperEngine/Application/ApplicationContext.cpp)。

“瞬间切换”为默认；“淡入淡出”时长 0.1–10 秒。**真实淡入淡出只适用于两张静态图片或静态模式之间**：服务创建不接收输入的临时背景图层，等待新 swaybg 就绪后按时间淡出旧画面，并等待回收图层进程。视频、场景、网页实时后端没有原生跨播放器淡入淡出接口，使用瞬间切换，UI 和切换结果均明确提示；从实时壁纸切向静态也使用瞬间切换。不会把静态替代图伪装成动态交叉淡化。

无音频服务时保留静音播放保护；有音频服务时默认有声音，静音/音量仅实时修改用户编辑的流字段，不重播，不覆盖其他混音器的后续调整。

## 持久化、兼容和排查

状态在 `~/.local/state/selandia-niri/wallpaper.json`（或 `$XDG_STATE_HOME/selandia-niri/wallpaper.json`）。`playlists` 为版本 1 的具名集合，含 `active` 和 `lists`；每份含 `id/name/settings`，条目含 `path/mode/enabled/weight`，轮播含 `order/trigger/seconds/cycle`。`ratings` 按规范化绝对路径保留旧版本的本地手动标签，仅为兼容旧版本，UI 不再编辑；`rating_filter` 保存 everyone/questionable/mature/unrated 四个筛选布尔值（questionable 即 PG13），`display` 保存模式、过渡和时长。WE 项目分级每次从作者元数据读取，不写入状态文件。选择、声音、目录、assets 分开校验，损坏的新播放集或分级字段不会清除它们。

旧扁平 `playlist` 在读取时无损迁入 Default；原先分钟转换为秒。坏的新结构回退到仍有效的旧播放集；仅明确保存才写入迁移结果。为支持旧版本回滚，`playlist` 仍写兼容投影：只包含启用且分级合格的条目、顺序/随机、分钟；精确秒数、权重、禁用项、完整具名集合和洗牌状态保存在 `playlists`。旧版本不能操作新功能，回滚前保留完整状态备份，避免随后用旧版本保存覆盖新集合。JSON 限 2 MB，过大写入在替换前拒绝。

服务使用同用户、权限 0600、按 Niri 会话区分的 Unix socket 接收显式操作，GTK 不负责定时轮播。日志为 JSON，含事件、条目、具名播放集 ID/名称、顺序、触发、秒数、分级、权重和警告：

```bash
journalctl --user -u selandia-niri@wallpaper.service -f
```

隔离贯通验收：

```bash
dbus-run-session -- python3 -B tools/smoke.py --playlist-controls-probe-only
```

探针仅在 `/tmp` 私有配置、状态、缓存、运行目录和嵌套 Niri 中运行，覆盖旧格式迁移、两个不重复洗牌周期、隐藏 Mature、真实淡入淡出像素、强杀恢复、视频 EOF、空集及宽窄 GTK 截图；不对正式 Niri 执行重启。完整检查用 `./check.sh`。
