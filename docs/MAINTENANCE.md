# 维护与故障恢复

本项目的配置通过软链接生效。修改项目中的 `niri/` 等同于修改已部署配置，因此应先在临时副本开发和验证，再按明确的文件清单发布。不要为应用主题或更新面板重启 Niri 合成器。

## 文件与状态

| 内容 | 默认位置 | 说明 |
| --- | --- | --- |
| 生效配置 | `~/.config/niri/config.kdl` | 指向项目的 `niri/config.kdl`；非默认 XDG 路径以部署记录为准 |
| 安装及恢复记录 | `~/.local/state/selandia-niri/install.json` | 保留原配置及受管理文件的记录 |
| 用户偏好与聊天记录 | `~/.local/state/selandia-niri/` | 不导出；API 密钥只从指定环境变量读取 |
| 临时壁纸进程记录 | `$XDG_RUNTIME_DIR/selandia-wallpaper-renderer.json` | 校验 PID、启动时间、父进程和进程组；过期记录无效 |
| 验证证据与发布备份 | 项目 `.validation/` | 日期对应独立批次；删除前先确认不再需要回滚 |
| 分享包 | 项目 `dist/` | 重新生成的通用默认配置，不含个人状态或本机兼容二进制库 |

目录名可包含空格和引号。运行命令前进入项目目录；不要对安装脚本整体使用 sudo。安装、更新、修复只把必需的软件纳入 pacman 事务；AUR 壁纸后端和其他可选依赖见 [安装指南](INSTALL.md)。

## 功能的正常行为

- 灵动岛只在 SwayNC 可用且允许弹出时展示通知预览，按通知 ID 同步关闭和替换。监听连接断开会撤下旧预览并退避重连；不会为监听而自动启动通知服务。修改 `notification_events.py`、`notification_policy.py` 或 `island.py` 后只需重启受管顶栏 `selandia-niri@waybar.service`。隔离回归入口为 `tools/smoke.py --notification-probe-only`。
- 应用音量按播放／录音流列出。调整立即生效；同一程序有多个流时分别显示。外部混音器保留为高级路由和声道入口。
- 壁纸列表和网格共享搜索与选择。网格缩略图为 224×126 逻辑像素，按可见区域加载；选择后仍需明确应用。
- 壁纸静音和音量只改变用户明确修改的字段，不重播。音频服务可用性变化才需要重新启动壁纸组件；无服务时继续显示静音画面。
- 显式音频操作失败时恢复保存的偏好，并尝试恢复本次触及的实际混音状态。若音频服务已断开、恢复也失败，会明确报告；画面不会因此被停止。后台只初始化新音频流一次。
- 系统读数缺失和首次速率采样显示不可用。真实零值（例如禁用 swap）与缺失值有区别。NVIDIA 指标按硬件可选，Intel/AMD 不需要安装 NVIDIA 软件。
- 控制中心按屏幕逻辑尺寸布局，最大 1600×1120；窄屏使用上下导航。HiDPI 缩放后应以逻辑尺寸判断宽度。
- 控制中心使用普通浮动窗口，授权、文件选择和其他应用的对话框遵循合成器正常层级。更新窗口代码后先保存草稿，再关闭并重开控制中心；无需重启桌面。不要为它恢复 OVERLAY 图层，否则普通弹窗会再次被遮挡。隔离回归入口为 `tools/smoke.py --popup-probe-only`。

场景／Web 后端仍属实验性；通过样例验证不能代表所有创意工坊项目、脚本或编码格式都兼容。真实 AI 服务需要用户提供有效端点、模型及密钥环境变量；自动化验证只请求回环测试服务器。

## 检查与交付

```bash
timeout --kill-after=2s 240s ./check.sh
timeout --kill-after=2s 180s python3 -B tools/run_tests.py discover -s tests -v
timeout --kill-after=2s 180s dbus-run-session -- python3 -B tools/smoke.py
timeout --kill-after=2s 180s dbus-run-session -- python3 -B tools/smoke.py --wallpaper-audio-probe-only
timeout --kill-after=2s 30s ./control.sh export
```

冒烟使用配置、状态、缓存及运行目录副本，内存 GSettings 和独立 D-Bus。Niri 宿主下只把自己创建的嵌套测试窗口悬浮并保持可见，避免被滚出屏幕后测试超时；不操作用户窗口。需额外宿主套接字时可传 `SELANDIA_PROBE_HOST_SOCKET`，测试组件仍连接私有套接字。非 Niri 宿主不进行此定位。

发布先校验原文件及全部载荷，持久保存回滚记录，再逐文件原子替换。发布准备后发生的手动编辑会使发布停止。失败时恢复文件；若进程被强杀，记录仍保留。回滚也先校验全部备份和编辑冲突，防止还原一半才发现损坏。相同分享内容生成相同压缩包字节，只有完整包才以 `.tar.gz` 正式名称出现；强杀遗留的隐藏 `.partial` 不是有效分享包，不要分发。

托管组件使用 systemd。顶栏更新不发送 `SIGUSR2`；重启完整 Waybar 服务，由管理器回收子进程。禁用的组件不自动启用。组件就绪要求 PID 持续稳定，不能把反复崩溃又拉起算作成功。

## 恢复

安装／卸载中断后，重新运行控制脚本会先恢复持久事务。卸载恢复项目接管前的配置，保护后续手动修改，并保留软件包、用户数据与归档；不要直接删除状态目录来“清理”安装。

增量发布的回滚按最新批次先执行。具体批次路径与结果见 [验证记录](../VALIDATION.md)：

```bash
python3 -B tools/live_update.py rollback --journal .validation/具体批次/release
```

恢复文件后，关闭并重开面板加载恢复的代码。需要恢复运行组件时按该批次报告中的流程操作；`--reload` 会重载受管理组件，应先确认对应范围。发生后续编辑冲突时停止回滚并保留备份，不强行覆盖。真实睡眠、合盖、显示器热插拔与所有 API／创意工坊项目不由隔离冒烟代替。

## 播放集与信息复制

壁纸页的“当前壁纸”可刷新；网格／列表只改变资源库视图。播放集编辑需点“保存播放集”，启用后由 `selandia-niri@wallpaper.service` 运行 `wallpaper.py run` 调度，关闭面板不停止。顺序／权重随机／洗牌和定时／播完切换保存在 `wallpaper.json` 的 `playlists` 具名集合，定时范围 1 秒–180 分钟，默认未启用；`playlist` 保留旧版本兼容投影。未知字段或非法值回退安全默认，不会丢弃有效的声音／选择偏好。上一条按配置列表逆序，随机下一条在有其他条目时不重复当前项。手动选择、设置变更或服务重启会重新开始计时。

播完切换检测视频的实际 EOF，停止无限循环并保留最后一帧，直到下一条就绪；场景／网页通常无限运行，静态图片无结束事件，需使用定时模式。空播放集保持当前壁纸。自动切换复用 `activate()` 原子写、失败恢复和取色重载；候选失败时跳过，全部失败至少等待 30 秒再试。新候选前有缓存静态画面兜底，旧渲染器在新候选确认就绪后才回收；所有自建子进程均等待回收。`wallpaper-transition.json` 保留中断事务，服务下次启动先恢复未提交选择，不覆盖中断后的手动编辑。

排查自动轮播：

```bash
timeout --kill-after=2s 15s journalctl --user -u selandia-niri@wallpaper.service -f
timeout --kill-after=2s 420s dbus-run-session -- python3 -B tools/smoke.py --review-probe-only
```

日志含 `wallpaper_playlist` 事件、时间、条目、顺序和触发方式。隔离验收会耗时约四分钟，实际观察至少三次一分钟随机切换，再比较视频播完与定时循环。

系统页顶部的单栏信息支持鼠标选择和“复制系统信息”；复制内容与屏幕标签相同。优先读取 `/proc`、`/sys`、`/etc`、软件包数据库及 Niri IPC，无 fastfetch/lspci 也可用；缺项明确显示不可用。不透明度可调 20–100%，低于 40% 加强文字边缘／描边／分隔线，不抬高可调下限。

控制中心的圆角、胶囊透明空隙、不透明度、文字像素与壁纸两行布局验收见 [视觉回归维护](CONTROL_CENTER.md)。壁纸页为单一页面：宽屏左侧资源库、右侧设置区（含播放集），中间分隔可拖动，窄屏上下排列，避免内外两层垂直滚动。

多播放集、分级来源与确认、显示参数映射、事务和常驻 IPC 排查见 [壁纸播放集指南](WALLPAPERS.md)。切换及恢复日志包含条目和播放集 ID，可用 `journalctl --user -u selandia-niri@wallpaper.service -f` 查看。

## 持久暂存与清理

长期工作放在项目 `.staging/<批次>/project/`，不以 `/tmp` 作为唯一副本；运行时配置与嵌套会话仍在 `/tmp` 隔离。发布前把已验证的源码、分享包和校验清单保存到 `.validation/<批次>/verified-update.tar.gz`。发布完成、正式树与产物校验相符且回滚备份可用后，才手动删除对应 `.staging` 批次；未发布或中断的批次不得自动清理。`.staging/` 已忽略且不进入分享包。

## Rust 顶栏与回滚

Waybar/Kitty 已按用户确认移除，不再提供旧组件切换入口；离线恢复见 [恢复方法](EMERGENCY_COMPONENTS.md)。systemd 服务名称仍为 `selandia-niri@waybar.service`，Eww 前台进程由它托管，不重启 Niri。启动器／终端选择、Rust 输入库缓存与维护取舍见 [Rust 组件](RUST_COMPONENTS.md)。安装器区分必需 Rust AUR 与可选壁纸 AUR；必需依赖缺失时停止部署。

### 自检隔离与正式应急演练

`./check.sh` 保留正式显示器/服务的只读检查，但单元测试在私有 D-Bus、XDG state/cache/config/runtime 和音频端点运行。单独跑测试推荐 `python3 -B tools/run_tests.py discover -s tests`。壁纸 IPC 套接字还按显示会话及真实状态目录共同命名，临时状态副本不会命中正式常驻服务。不要把正式运行时环境直接交给临时测试脚本。

2026-10-11 正式演练：Eww 被强杀、运行时配置损坏、事件桥被强杀分别自动回退约 0.22 / 1.29 / 1.29 秒；每次再用全套应急命令验证 Waybar/Fuzzel/Kitty、通知、壁纸和锁屏服务，最后恢复日常 Rust 组件。独立锁屏 unit readiness 与用户真实 PAM 解锁均通过。新证据在 `.validation/resume-rust-20261011/live/`，本机真实系统挂起仍未复现。截图会触发 Niri 通知，像素比较须避开遮挡；临时 DND 必须在 finally 恢复原值，不能清空用户通知历史。

## 守护进程探测必须有截止时间

2026-10-11 的一次工具调用阻塞了 69 分钟：沙箱里执行 `swaync-client --help | head -45`，受限 socket／D-Bus 使客户端停在 `poll()`（状态 Sl，wchan 为 poll_schedule_timeout），没有退出；`head` 等不到 EOF，整条管道也不会结束。用户结束该客户端后，11:38:26 工具调用才完成。根因是无界客户端等待，不是模型或批准门。`--help` 也不能被当作一定不连接守护进程。

- 在沙箱探测 `swaync-client`、`nmcli`、`bluetoothctl`、`busctl`、`pactl`、`wpctl`、`niri msg`、`dbus-send`、`gdbus`、`systemctl` 等，一律为生产者加 `timeout`；默认 5 秒，单次探测不超过 15 秒。加 `--kill-after=2s`，防止忽略 SIGTERM 后仍无限等待。Python 同步子进程必须提供 `timeout=`，清理子进程的 `wait()` 也要有界。超时是失败证据，不能当作功能不存在或检查通过。
- 不靠管道／`head`／`grep` 截短输出来限制等待；先有界地捕获输出与退出码，再截取。需要真实行为时，通过已经受管的服务入口，或在私有总线和临时状态中复现；沙箱里不直接连接正式系统总线。权限失败不重复重试。
- 命令在调用前写清上限；长跑验收必须同时说明原因。整套测试约 50 秒，允许 180 秒；完整自检含测试与只读检查，允许 240 秒；完整 GTK 冒烟约 90 秒，允许 180 秒。编译虚拟指针／安装配置校验允许 30 秒；宽度测量允许 25–35 秒，因其要等待映射、截图与像素比较。专项 UI 探测保留各自 20–180 秒上限；三次一分钟轮播专项允许 330 秒子进程／420 秒总预算。这些上限不放宽每次客户端调用的 3–10 秒限制。

先捕获，再展示（此例只对私有测试守护进程执行；真正受限的沙箱可能在 5 秒后失败，这是有效结果）：

```bash
probe_log=$(mktemp /tmp/selandia-daemon-probe.XXXXXX)
probe_status=0
timeout --kill-after=2s 5s swaync-client --help >"$probe_log" 2>&1 || probe_status=$?
head -45 "$probe_log"
printf 'probe exit=%s; log=%s\n' "$probe_status" "$probe_log"
```

退出 124 表示截止时间到达，137 可表示强制 KILL；保留原日志与退出码，不静默归零。长期录制真实挂起信号仅由用户在正式终端运行，见 [休眠采集](RESUME_DIAGNOSTICS.md)：监听总预算 1 小时，连接系统总线本身最多 5 秒，每条快照命令最多 8 秒。后台组件由 systemd 托管，其常驻监听不是一次性探测。

工作持续使用项目内 `.staging/`，发布前关键产物另存 `.validation/`；不要因为等待命令而让 `/tmp` 成为唯一副本。

点击右侧时间打开独立日历；该面板使用原生 GTK 按钮网格，不依赖额外程序。日历支持月份导航、周编号与“今天”，再次点击时间或 Esc 关闭。

顶栏当前软件名由 `island.py` 的后台采样更新，仅显示数据，不执行应用名或窗口标题。紧凑胶囊高度在 `bar_backend.py` 使用 Pango 测量，椭圆样式只在 `appearance.py` 生成，Rust 输入轮廓对应半高圆角。不要手改 `niri/theme/eww.css`。验证与发布使用持久 `.staging/bar-capsules-20261011`；发布前保存 `.validation/bar-capsules-20261011/release` 备份，失败恢复整批。只重启托管 Eww，不重启 Niri、不重启其它组件。

## 顶栏事件缓存与日历（2026-10-13）

`niri_events.py` 直接连接 `NIRI_SOCKET`；一次性请求有总截止时间和消息大小上限，常驻流断线后按 1–8 秒退避重连并清空旧状态。它保留最新窗口/工作区状态，不堆积事件队列。新增协议事件默认忽略。工作区按钮通过稳定 ID 定位，重新排序后不会跳到同序号的另一工作区。

Eww 的界面流排除监督心跳，状态文件仍每两秒刷新。动画阶段 40 ms 采样；静止时最多 250 ms，本地显示/关闭请求可立即唤醒。`bar_backend.py` 保留两秒一次的输出检查以覆盖热插拔，但直接使用 socket，不启动 niri 客户端。改变这些周期时运行顶栏专项探针，尤其检查减少动画、心跳故障恢复、焦点与重排工作区。

日历复制所选日期为 `YYYY-MM-DD`。`calendar_widget.py` 的月份和星期标签随应用语言切换，无需改变系统 locale。周一为首列，显示 ISO 周号；方向键移动一天／一周，Page Up/Down 换月，Ctrl+Page Up/Down 换年。月底与闰年自动限制为有效日期；今天与选中日期独立标记。样式同时维护基础 `style.css` 和 `appearance.py` 主题生成器，避免生成主题覆盖选中状态。

顶栏音量使用 `audio_events.py` 的单个 `pactl subscribe` 子进程，只响应 sink/server 变化；媒体使用 `media_events.py` 的专用 D-Bus 连接，响应播放器名称变化、属性变化和 Seeked。信号只置位合并标记，后台读取最多每 200 ms 发起一次，读途中发生的事件不会丢失；无信号时每 30 秒校准。媒体进度每秒由 Position、Rate 和单调时钟计算，不为进度单独查询播放器。断线自动退避重连，退出回收音频子进程和专用连接，不关闭媒体后端的共享连接。打开的控制中心播放器保持原有刷新周期。

修改这些监听模块或 `island.py` 后，完成 `tools/event_feeds_probe.py`、原生日历与顶栏回归，再重启受管 `selandia-niri@waybar.service`。只重开控制中心不能替换常驻顶栏代码。新增模块必须登记到 `tools/deploy.py` 的 `REQUIRED_SOURCES`，确保安装和分享包完整。

## 顶栏预留区与独占区（2026-10-13）

顶栏不再写 `layout.struts`：`appearance.py` 生成 `theme/theme.kdl` 时把 `struts.top` 设为 0，改由灵动岛图层在运行时声明 layer-shell 独占区，取值为 `reserved_height(font_size) - 12`（16px 字体为 55，加 12px 外边距共 67px）。左右胶囊保持 monitor-relative（exclusive_zone `-1`），所以灵动岛展开不会挤动下方窗口或改变工作区高度。Rust 输入库 `niri/eww/input_region.rs` 负责调用 `gtk_layer_set_exclusive_zone`，值由 `bar_backend.py` 通过 `SELANDIA_EWW_EXCLUSIVE_ZONE` 注入；`eww_input.py` 的库缓存键包含源码、rustc 版本与机器架构，改完源码第一次启动会重新编译。

修改 `niri/shell/bar_backend.py`、`niri/shell/eww_input.py` 或 `niri/eww/input_region.rs` 后必须重启受管 Eww（`systemctl --user restart selandia-niri@waybar.service`），否则顶栏按旧代码继续运行、不再预留空间，窗口会被顶栏覆盖；不需要为此外重启 Niri 合成器。重启后核对三处：`/run/user/$UID/selandia-eww-*/geometry/{island,left,right}.json` 的 `exclusive_zone`（岛为“预留 − 12”、两侧为 `-1`）、窗口可用高度比输出高度小预留值（`niri msg --json windows`），以及 `.validation/wallpaper-unified-20261013/live/verify-live-maximize.py` 的实时复核记录。不要同时恢复 `struts.top`，那会造成双重留白。

同一窗口的连续标题更新最多每秒显示一次，焦点切换立即更新，避免终端进度标题使整份 Eww 状态持续重算。没有媒体封面时，隐藏图像仅加载 1×1 透明 SVG，占位图标仍由主题提供；不要把带滤镜的 4K 壁纸当作图标占位资源。
