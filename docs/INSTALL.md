# Selandia Niri：安装、分享与壁纸

面向 Arch Linux 与 Niri 26.04+ 的用户级桌面配置。使用 pacman 管理依赖，遵循 XDG 路径，通过 systemd 用户服务管理桌面组件。项目本身是配置部署脚本，不是 Arch 官方桌面环境，也没有由 pacman 管理配置文件的 PKGBUILD。

## 安装到另一台电脑

请分享 `./control.sh export` 生成的 `dist/selandia-niri-*.tar.gz`，不要直接打包整份工作目录。导出只读取源配置，不改变当前桌面；会清除三个屏幕配置文件中的本机参数、`conf/local.kdl`、生成的输入／窗口与语言覆盖，以及空闲计时器，并重新生成默认主题。不打包 Git 历史、调试截图、运行日志、AI 账号、用户状态、已下载壁纸或旧备份。自行写入其他源文件的个人命令，仍应在分享前检查。

收件人在一个准备长期保留的目录解压，以自己的普通用户运行：

```bash
./control.sh install
```

依赖需要安装时执行完整 Arch 升级 `pacman -Syu`，避免部分升级。脚本不会设置分区、驱动、引导器或登录管理器；现有 Arch 系统需要已经可以使用图形会话。安装后注销并选择 Niri；也可从 TTY 启动 `niri-session`。在控制中心设置本机屏幕、输入设备和语言。项目不启动自动睡眠计时器。

## 文件位置

| 内容 | 默认位置 |
| --- | --- |
| Niri 配置入口 | `~/.config/niri/config.kdl` |
| 实际配置及脚本 | 解压目录中的 `niri/`；`~/.config/niri` 是指向它的软链接 |
| 桌面用户服务 | `~/.config/systemd/user/selandia-niri*`、`selandia-lock*` |
| Portal 选择 | `~/.config/xdg-desktop-portal/niri-portals.conf` |
| 偏好、部署清单、回滚备份 | `~/.local/state/selandia-niri/` |
| 壁纸预览缓存 | `~/.cache/selandia-niri/wallpapers/` |

支持 `XDG_CONFIG_HOME`、`XDG_STATE_HOME`、`XDG_CACHE_HOME`。主题设置会同步受管理的 GTK／Qt 应用外观，并在状态目录记录原设置用于卸载恢复。请保留解压目录及路径；它不是安装后可以删除的临时文件夹。

```bash
./control.sh update                 # 完整更新 Arch 软件包并应用本地配置
./control.sh repair                 # 补齐软件及缺失文件，修复部署链接
./control.sh uninstall              # 恢复备份，保留软件包和用户数据
./control.sh export                 # 重新生成可分享的配置包
./control.sh check                  # 配置、依赖、测试及会话检查
sha256sum -c SHA256SUMS             # 首次安装前校验导出包内文件
```

`update` 不下载本项目新版本。卸载不是软件包清理器。修改保护会拒绝覆盖被其他配置替换或编辑的托管目标；发生冲突时应先比较文件，不要直接删除个人改动。

安装、更新与修复先在临时副本中恢复偏好并校验，成功后提交。控制中心新增的自启动项和服务屏蔽记录原状态，卸载时恢复；之后被手工修改的条目保留并在预览中列出。旧版本没有原状态记录的条目也会保留，需用户比较后自行处理。

## 电源保证与测试条件

本项目菜单或自动计时发起睡眠前必须确认锁屏；外部睡眠只通过 swayidle 的 `before-sleep` 延迟，受 logind 的 `InhibitDelayMaxSec` 限制。慢锁屏或失败无法撤销外部请求。“保持唤醒”取得高层 `idle:sleep` 抑制锁；合盖可能因默认的 `LidSwitchIgnoreInhibited=yes` 忽略它。若需要合盖遵守此锁，应由管理员检查 logind 策略；安装器不会修改系统策略，也不保证外部睡眠无限等待锁屏。

External sleep uses the bounded `InhibitDelayMaxSec` delay; slow or failed locking cannot cancel an external request. Lid closure may ignore high-level inhibitors with `LidSwitchIgnoreInhibited=yes`. The installer does not change logind settings. See the [swayidle manual](https://man.archlinux.org/man/swayidle.1.en) and [logind manual](https://man.archlinux.org/man/logind.conf.5.en).

`python3 -B -m unittest discover -s tests -v` 可单独运行测试。无显示服务器时，GTK 图标渲染测试会说明原因并跳过；这不算已验证图形渲染。图形测试需要可连接的显示服务器。完整图形验证使用私有 D-Bus、临时配置与嵌套 Niri 运行 `tools/smoke.py`，不得把测试环境指向正式会话。分享包内的 `SHA256SUMS` 对应包内文件；原项目本轮结果见 `VALIDATION.md`，历史硬件证据不会被打包。

## Wallpaper Engine 与主题配色

控制中心 → 壁纸（或按 `Super+Ctrl+T`）：自动读取 Steam 的 `libraryfolders.vdf`，扫描已挂载库中的 `steamapps/workshop/content/431960`、`projects/myprojects`、`projects/defaultprojects`。也可添加下载目录，或选择单个图片、视频、`project.json`。选中仅预览，点击应用才更换壁纸。

| 类型 | 行为及依赖 |
| --- | --- |
| 图片、项目预览图 | 使用已有的 swaybg，支持静态应用 |
| 视频 | 需要可选 AUR 软件包 `mpvpaper`；默认静音、循环播放 |
| Scene 场景 | 需要可选 AUR 软件包 `linux-wallpaperengine-git` 及正版 Wallpaper Engine 的 `assets`；实验性兼容，默认静音、30 FPS |
| Web 网页 | 使用 `linux-wallpaperengine-git` 与正版 `assets`；实验性兼容，点击“播放网页壁纸”才执行项目网页脚本；依赖 CEF |
| Application／未知项目 | 不执行程序；有预览图时可以设为静态壁纸 |

`packages.txt` 的普通行声明必需的官方仓库包；`# optional`、`# optional-experimental` 与 `# hardware-optional` 注释声明可选依赖、来源和用途。AUR 包不会被交给 pacman 的必需包事务，实验性后端也不默认启用。安装器不下载 Steam 付费资源。

在自己的终端运行以下完整命令（`paru` 与 `yay` 二选一）：

```bash
paru -S --needed mpvpaper linux-wallpaperengine-git
# 或：
yay -S --needed mpvpaper linux-wallpaperengine-git
```

请在该终端检查 AUR 构建内容、确认安装，并输入 sudo 密码；不要把密码写入配置或聊天。构建可能下载 CEF 及子模块。安装完运行 `pacman -Q mpvpaper linux-wallpaperengine-git` 和 `command -v mpvpaper linux-wallpaperengine` 核实，再在壁纸页点“重新扫描”。也可运行 `python3 -B niri/shell/wallpaper.py dependencies` 查看只读依赖状态和准确安装指引。壁纸页缺后端时保留静态预览，并提供可选择复制的同样指引。

场景/Web 还需正版 Wallpaper Engine 的 `assets` 目录；自动检测失败时，在 Steam 的 Wallpaper Engine → 管理 → 浏览本地文件找到它，填入“场景/网页播放资源”。安装后端不等于每个场景或网页都兼容。Web 只有显式应用才执行网页脚本，Application 项目仍不执行。

**当前 AUR 版本的 Web 兼容修补（r627.b016d7d1）**：原版存在 [CEF 加载顺序问题 #628](https://github.com/Almamu/linux-wallpaperengine/issues/628) 和 [Web 黑屏问题 #629](https://github.com/Almamu/linux-wallpaperengine/issues/629)。项目只在 Web 子进程中设置已有 CEF 库的加载顺序，并传入原生 Wayland 参数；不会改系统环境。黑屏问题需要重新构建后端，[tools/wallpaper_engine_compat.py](../tools/wallpaper_engine_compat.py) 应用与 [上游 PR #639](https://github.com/Almamu/linux-wallpaperengine/pull/639) 相同的纹理修补，同时采用 [上游问题 #680](https://github.com/Almamu/linux-wallpaperengine/issues/680) 的帧率上限和引用计数退出修补，重复运行不改文件，遇到不同源码会拒绝。上游未来合并后无需本地修补。

仅在该旧版本复现 Web 黑屏时，在项目根目录打开终端执行：

```bash
project_dir=$PWD
compat_dir=$(mktemp -d /tmp/selandia-engine-compat-XXXXXX)
cd "$compat_dir"
paru -G linux-wallpaperengine-git
cd linux-wallpaperengine-git
# 先阅读 PKGBUILD；首次构建缺工具时由 makepkg -s 提示安装，密码只在此终端输入。
makepkg --nobuild --holdver -s
python3 -B "$project_dir/tools/wallpaper_engine_compat.py" "$PWD/src/linux-wallpaperengine-git"
sed -i 's/^pkgrel=1$/pkgrel=2/' PKGBUILD
makepkg --noextract --holdver --install
```

这是本地修补的软件包，后续 AUR 更新可能覆盖修补；先检查上游是否已修复，再决定是否重建。构建、安装后端不会自动切换现有壁纸或重启桌面服务。项目默认发声，以显式音量／静音设置替代上游自动静音探测；没有音频服务时静音播放并关闭可能一直等待的音频处理。

`ffmpeg` 是官方仓库的可选视频缩略图工具；缺失时使用 `sudo pacman -S --needed ffmpeg`。`nvidia-smi` 属于 NVIDIA 硬件可选指标（Arch 包 `nvidia-utils`），Intel/AMD 电脑不需要为该指标安装 NVIDIA 软件。已有的亮度工具无需重复安装。

视频没有项目预览图时，用可选的 `ffmpeg` 提取首帧。不同场景的效果、资源占用和兼容性需要在实际硬件上验证。

原库未挂载或播放器退出时使用已缓存的静态图；缓存也不存在时使用内置壁纸。当前一项选择用于全部活动屏幕；单屏不同壁纸、自动轮换、场景属性编辑尚未提供。壁纸服务沿用 `selandia-niri@wallpaper.service`，随 Niri 会话结束。

在外观页勾选“主题配色跟随当前壁纸”并应用，随后更换壁纸会更新状态栏、控制中心、AI 侧栏、启动器、通知、锁屏与 Alacritty 的配色。取色来自图片或项目预览图，视频使用预览或首帧；不逐帧追踪动画。保留深浅模式和字体，按明暗模式生成可读文本颜色。取消勾选后恢复手动主题。GTK／Qt 应用继续同步明暗模式，第三方应用的自定义主题不保证接受壁纸强调色。

命令行同样可用：

```bash
python3 -B niri/shell/wallpaper.py list
python3 -B niri/shell/wallpaper.py add-folder '/路径/431960'
python3 -B niri/shell/wallpaper.py set '/路径/项目' --preview
python3 -B niri/shell/wallpaper.py set '/路径/项目' --assets '/路径/wallpaper_engine/assets'
```

技术依据：[XDG 目录规范](https://specifications.freedesktop.org/basedir/latest/)、[pacman 手册](https://man.archlinux.org/man/pacman.8.en)、[Wallpaper Engine 官方 Linux 说明](https://help.wallpaperengine.io/zh/functionality/linuxmacos.html)、[mpvpaper](https://github.com/GhostNaN/mpvpaper)、[Linux Wallpaper Engine](https://github.com/Almamu/linux-wallpaperengine)。

## 分段玻璃主题与 AI 聊天

“设置 → 外观”提供九套深浅配色：冰川、暮紫、石墨、极光、深海、蔷薇、琥珀、林间、珍珠。取消“主题配色跟随当前壁纸”后可切换预设；默认 78% 不透明度即可显示通透玻璃质感（可在 20%–100% 间调节）。顶栏每个组件是独立胶囊。面板与启动器使用 Niri 原生模糊；Eww 三个有界图层保持胶囊外透明，以统一生成的 CSS 高光与渐变呈现玻璃材质。所有覆盖仍由外观生成器产生。

Super+A 打开聊天。顶部可切换本地 Ollama、中转站、Google Gemini、DeepSeek、OpenAI API，并可新增配置；⚙ 中填写名称、provider、base URL、模型及密钥**环境变量名**后保存。模型支持手填与查询。新对话保留旧历史，删除仅移除当前对话；旧对话保留原连接快照。配置和对话在 `${XDG_STATE_HOME:-~/.local/state}/selandia-niri/ai-workspace.json`，0600 权限，分享包不包含它，也不会导入原机器的聊天记录。

远程地址须 HTTPS。Ollama 使用 `http://localhost:11434`；Google 兼容地址为 `https://generativelanguage.googleapis.com/v1beta/openai`；DeepSeek 为 `https://api.deepseek.com`；OpenAI 为 `https://api.openai.com/v1`；中转站按提供方要求填写。模型需支持文本 Chat Completions。API 密钥不会写入设置；关闭已打开的侧栏后，在自己的终端用 `read -rsp 'API key: ' GEMINI_API_KEY` 等命令读入密钥，`export GEMINI_API_KEY`，再执行 `"${XDG_CONFIG_HOME:-$HOME/.config}/niri/scripts/desktop" ai`。其他连接使用各自的环境变量名。打开侧栏或切换配置不联网，发送和查询模型才联网。

## 壁纸声音与引擎音频兼容

“设置 → 壁纸”提供音量与静音，默认开启、50% 音量，点**保存声音**实时应用到壁纸音频流，不重播画面。静音与音量独立更新，不覆盖用户在其他混音器里修改的另一项。仅音频服务出现／消失、需要改变播放器启动参数时重启该壁纸；检测超时／不可用时继续静音画面并停用可能等待的音频处理。服务恢复后再保存声音即可。它不会调节系统主音量或其他应用。没有音轨的壁纸不会产生声音。Web 音量通过所属 CEF 音频流管理；脚本或素材依赖不被 Linux 后端支持的项目仍可能无法完整运行。

壁纸页默认大图网格，可切换缩略图列表，选择／搜索保持一致，仍需点击应用才更换壁纸。“声音”页顶部直接调节应用播放与录音流，无需外部混音器；“高级混音器”保留更复杂的路由入口。流退出后自动移除，无支持的读数显示不可用。

控制中心按显示器逻辑尺寸放大，最大 1600×1120，窄屏使用上下导航。系统页新增 CPU／内存／分区／GPU 驱动及前八个进程详情。首次速率采样和缺失读数不显示虚构的 0；远程挂载容量不查询。本机 Intel 显卡无需安装 NVIDIA 指标软件。

当前审阅补丁除了 Web 纹理、帧率与 CEF 引用生命周期，还修正 FFmpeg 新版声道 API 下单声道转双声道缓冲分配错误、音频复制长度返回值，以及本地 Web 媒体响应长度（原版相对路径音频会报格式错误）。按上文流程取得 AUR 源码后，用**本版本**的 `tools/wallpaper_engine_compat.py` 对源码执行修补，然后重新构建软件包；sudo 安装需要用户在终端输入密码。补丁在任何源码片段不匹配时拒绝修改，并可重复执行。

本机可使用免 sudo 的项目本地兼容库 `.local/wallpaper-engine/`，只包含本机编译的 `liblinux-wallpaperengine-lib.so` 和 `compatibility.json`。加载前核验已安装 `/opt/linux-wallpaperengine` 的主程序、原库与本地库的哈希和架构，仅对场景／Web 子进程设置库搜索路径。包升级导致哈希变化时停用旧库，需重新构建；新电脑不要复制该目录，应安装适合本机的修补后端。分享包自动排除此本地二进制目录。

## 本轮更新回滚

日常使用、状态文件、完整验证和中断恢复见 [维护指南](../docs/MAINTENANCE.md)。发布前再次核对文件是否被编辑；回滚前先校验全部备份。分享包在完整写入后才发布，同一内容可生成逐字节相同的压缩包。

经过隔离验证的发布使用 `tools/live_update.py` 先持久备份，再原子替换文件并重载受管理的顶栏、通知和实时壁纸。Niri 合成器保持运行。重载失败会恢复原文件和偏好，再加载原组件；被强杀时保留发布记录供恢复。回滚前检查后续编辑，发生冲突时保留文件并报告。具体发布记录和回滚命令见项目 `VALIDATION.md`；已有 AI／快捷键／设置面板关闭后重开可加载新的界面代码。

顶栏由 systemd 托管 Eww；外观应用可短暂刷新顶栏，只重载通知 CSS，不重启 Niri。手动重启先清除失败计数，禁用的组件保持禁用。

## 播放集、透明度与系统信息

安装后壁纸页提供“当前壁纸”、网格／列表与播放集。加入／移出所选资源或使用筛选结果，再点“保存播放集”；上一条／下一条切换已保存条目。可选顺序／随机，以及 1–180 分钟定时切换／视频播完切换。轮播在 `selandia-niri@wallpaper.service` 内执行，关闭控制中心仍持续，配置保存在用户状态目录 `wallpaper.json`。默认关闭，分享包不带原机器的播放集或私人路径；新电脑自行创建。静态图片及无限运行的场景／网页没有播放结束信号，请用定时模式。详情和日志命令见 [维护指南](../docs/MAINTENANCE.md)。

外观不透明度范围 20–100%，低于 40% 强化文字与边缘；调整后明确应用，关闭重开仍保持。系统页单栏信息支持鼠标选择与“复制系统信息”，缺少 fastfetch/lspci 也可显示大部分字段，读不到的项目明确显示不可用；复制需要必需依赖 wl-clipboard。

控制中心支持 20–100% 透明度；所有顶栏胶囊和强调状态随同一设置变化，空隙保留原始壁纸颜色。低透明度使用锐利文字描边与无噪点面板图层。壁纸页为单一页面：宽屏左资源库、右设置区（含播放集），窄屏上下排列，列表至少显示两行；同一份选择、搜索和播放集草稿不会因布局或滚动而应用或丢弃。验收说明见 [视觉回归维护](../docs/CONTROL_CENTER.md)。

## 壁纸播放集偏好

静态淡入淡出的必需依赖 `python-cairo` 已列入 packages.txt；安装流程会安装此依赖。安装后从控制中心的壁纸页创建并保存具名播放集；轮播默认关闭。播放集、筛选项（全部／Everyone／PG13／Mature／未分级）、秒级定时和显示模式是本机偏好，不随分享包导出；分级本身读取 Wallpaper Engine 项目 `project.json` 中的作者元数据，没有项目元数据的本地独立图片／视频默认 Everyone，不联网识别画面。旧扁平配置自动迁移，详细能力与不支持的模式/过渡见 [壁纸播放集指南](../docs/WALLPAPERS.md)。新后端代码需要一次受 systemd 管理的壁纸组件重启，之后手动切换通过常驻事务交接，不重启 Niri。

## 首选 Rust 组件

官方包 `alacritty`、`rust`、`gtk4-layer-shell` 随必需依赖安装。必需 AUR 为 `eww`、`anyrun`（含 anyrun-provider）。交互安装需要用户在当前终端输入 sudo 密码；非交互安装打印完整命令并停止部署。Fuzzel 保留用于 dmenu。详见 [组件清单](../docs/RUST_COMPONENTS.md)。

## 已替代组件清理后的依赖

Eww 与 Anyrun 是必需 AUR 依赖（`paru -S --needed eww anyrun` 或 `yay -S --needed eww anyrun`，安装提示时需用户输入 sudo 密码）；Alacritty 是必需官方仓库依赖。Anyrun 必须同时提供 `anyrun-provider`。缺少必需 AUR 时停止部署，不能把空白顶栏作为成功。Waybar 与 Kitty 不再声明、安装或导出。Fuzzel 仍必需，用于剪贴板和确认菜单，应用启动统一走 Anyrun。通知/壁纸/空闲/锁屏保留的理由见 [组件清单](../docs/RUST_COMPONENTS.md)，离线包与源码恢复见 [恢复方法](../docs/EMERGENCY_COMPONENTS.md)。
