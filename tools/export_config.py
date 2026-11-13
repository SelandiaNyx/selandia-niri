#!/usr/bin/env python3
"""Export a hardware-neutral checkout without logs, history or user state."""
import argparse
import datetime
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from deploy import REQUIRED_SOURCES


def stage(destination, root=ROOT):
    root, destination = Path(root), Path(destination)
    files = set(REQUIRED_SOURCES) | {"tools/deploy.py", "docs/INSTALL.md", "docs/MAINTENANCE.md", "docs/CONTROL_CENTER.md", "docs/WALLPAPERS.md", "docs/RESUME_DIAGNOSTICS.md", "docs/RUST_COMPONENTS.md", "docs/EMERGENCY_COMPONENTS.md", "docs/GPU_MONITORING.md", "docs/DAILY_USE.md"}
    for directory, pattern in (("tools", "*.py"), ("tools", "*.c"), ("tests", "*.py")):
        files.update(str(path.relative_to(root)) for path in (root / directory).glob(pattern))
    for relative in sorted(files):
        source = root / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or linked source: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    # These files are user-/hardware-generated. Never ship the source machine's
    # output names, monitor serials, sleep timers or local command overrides.
    for relative in ("conf/outputs.kdl", "monitor.kdl",
                     "conf/local.kdl", "conf/desktop-settings.kdl", "conf/language.kdl"):
        (destination / "niri" / relative).write_text("// Portable defaults; configure this computer in the Control Center.\n")
    (destination / "niri/swayidle/config").write_text("# Automatic idle actions are disabled until explicitly configured.\n")
    # The guide becomes the root README; its ../ links must move with it.
    guide = (root / "docs/INSTALL.md").read_text().replace("](../", "](")
    (destination / "README.md").write_text(guide)
    (destination / "PORTABLE").write_text("Exported runtime and test sources; historical machine-specific audit evidence omitted.\n")
    (destination / "VALIDATION.md").write_text(
        "# 安装与验证\n\n此压缩包由 tools/export_config.py 从运行配置中生成。"
        "它清除了屏幕标识、手动本机覆盖、会话语言覆盖和空闲计时器，重新生成默认主题，"
        "不包含原机器的运行日志、截图、账户、壁纸收藏、状态数据库或 Git 历史。\n\n"
        "在目标 Arch Linux 电脑上以普通用户运行 ./control.sh install；"
        "安装后执行 ./check.sh 检查依赖、配置与实际会话。"
        "python3 -B -m unittest discover -s tests 可独立运行隔离测试；"
        "需要原机器历史截图数据的审计测试会跳过。"
        "无显示服务器时 GTK 图标渲染测试会明确跳过；须在隔离图形环境补验，不能把跳过视为渲染通过。"
        "真实显示器、睡眠唤醒和动态壁纸需要在目标硬件上验证。\n\n"
        "可选 AUR 壁纸依赖及当前版本的 Web／音频兼容修补见 [安装指南](docs/INSTALL.md)。"
        "安装命令：`paru -S --needed mpvpaper linux-wallpaperengine-git`"
        "（或 yay）。sudo 密码须在用户自己的终端输入；安装后重新扫描壁纸库。"
        "nvidia-smi 仅为 NVIDIA 硬件可选指标，Intel/AMD 不需要安装 NVIDIA 软件。\n\n"
        "本版本包含分段玻璃顶栏与九套深浅配色；壁纸声音默认开启并支持音量／静音，无音频服务时继续静音画面。"
        "AI 侧栏支持 Ollama 和四类兼容 API 的多配置及本机历史，密钥仅从环境变量读取。"
        "本机编译的兼容后端库和聊天记录均不随包导出；新电脑按安装指南构建适合自己的修补后端。\n")
    with (destination / "VALIDATION.md").open("a") as document:
        document.write("\n应用音量内嵌声音页，壁纸支持大图网格／列表与不重播的实时音量／静音；"
                       "系统详情按真实读数显示，控制中心随逻辑屏幕尺寸调整。"
                       "显式壁纸音频失败会报告并恢复设置，不覆盖其他混音器的未修改字段。\n\n"
                       "分享包只在完整写入及同步后发布，同一内容可生成逐字节相同的包；"
                       "中断留下的隐藏 .partial 文件不是有效分享包。"
                       "维护和故障恢复见 [维护指南](docs/MAINTENANCE.md)。\n")
    with (destination / "VALIDATION.md").open("a") as document:
        document.write("\n不透明度范围 20–100%；壁纸页为网格／列表、当前壁纸与常驻播放集，"
                       "支持具名播放集、顺序／权重随机／洗牌、1 秒–180 分钟定时／视频播完切换，空集不轮播。"
                       "播放集、分级与显示偏好不随包导出；目标机器先创建并明确保存。六种显示模式与静态淡入淡出限制见 docs/WALLPAPERS.md。"
                       "系统信息含 25 类字段，支持选择及与屏幕一致的纯文本复制，不依赖 fastfetch/lspci。"
                       "隔离验收：`dbus-run-session -- python3 -B tools/smoke.py --review-probe-only`。\n")
    with (destination / "VALIDATION.md").open("a") as document:
        document.write("\n选中／勾选状态保持圆角；顶栏胶囊统一跟随不透明度，透明空隙不叠加原生噪点与饱和度滤镜。"
                       "低透明度文字使用无模糊描边；壁纸资源库单层滚动，宽窄屏至少显示两行。"
                       "像素与布局验收：`dbus-run-session -- python3 -B tools/smoke.py --visual-defects-probe-only`，"
                       "方法见 [控制中心视觉回归](docs/CONTROL_CENTER.md)。\n")
    with (destination / "VALIDATION.md").open("a") as document:
        document.write("\n顶栏/灵动岛 Eww、启动器 Anyrun、终端 Alacritty 为必需组件，共用外观主题生成器。"
                       "Waybar 和 Kitty 已移除；缺少必需组件时应先安装再部署。离线恢复方法见 "
                       "[应急组件](docs/EMERGENCY_COMPONENTS.md)。"
                       "本机仍须实测媒体/通知、透明度/穿透、PAM 与休眠唤醒，不随包携带原机证据。\n")
    with (destination / "VALIDATION.md").open("a") as document:
        document.write("\n当前含18个设置页、通知搜索与分批显示、独立草稿保留及有界读取队列；"
                       "使用与资源边界见 [日常操作](docs/DAILY_USE.md)。"
                       "Intel i915/Xe 按需显示可读DRM客户端的最忙引擎占比，首样本和休眠状态不伪造0%；"
                       "接口覆盖范围见 [显卡监控](docs/GPU_MONITORING.md)。\n")
    with tempfile.TemporaryDirectory(prefix="selandia-export-state-") as private:
        # Generate from the copied module: never touch the running checkout or
        # seed defaults from the exporting user's preferences.
        env = dict(os.environ, XDG_STATE_HOME=private, XDG_CONFIG_HOME=private,
                   XDG_CACHE_HOME=private, PYTHONDONTWRITEBYTECODE="1", LC_ALL="C.UTF-8")
        subprocess.run([sys.executable, "-B", "-c",
                        "import appearance,ui_assets,display_backend; appearance.restore_defaults(); "
                        "ui_assets.write(layout='compact'); "
                        "(display_backend.BASE / display_backend.GENERATED).write_text(display_backend.render_settings({}))"],
                       cwd=destination / "niri/shell", env=env, check=True, timeout=15)
    manifest = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(destination)}")
    (destination / "SHA256SUMS").write_text("\n".join(manifest) + "\n")


def export(destination):
    destination = Path(destination).absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    with tempfile.TemporaryDirectory(prefix="selandia-export-") as temporary:
        checkout = Path(temporary) / "selandia-niri"
        stage(checkout)
        if shutil.which("niri"):
            subprocess.run(["niri", "validate", "-c", str(checkout / "niri/config.kdl")], check=True, timeout=5)
        fd, partial = tempfile.mkstemp(prefix=".selandia-export-", suffix=".partial", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                # Honor the caller's umask without changing process-wide state.
                try:
                    mask = next(int(line.split()[1], 8) for line in Path("/proc/self/status").read_text().splitlines()
                                if line.startswith("Umask:"))
                except (OSError, ValueError, StopIteration):
                    mask = 0o077
                os.fchmod(stream.fileno(), 0o666 & ~mask)
                # Neither the destination name nor wall-clock time belongs in
                # the gzip header: identical portable contents give identical bytes.
                with gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w") as archive:
                        def metadata(info):
                            info.uid = info.gid = 0
                            info.uname = info.gname = ""
                            info.mtime = 0
                            return info
                        archive.add(checkout, arcname="selandia-niri", filter=metadata)
                stream.flush()
                os.fsync(stream.fileno())
            # Same-directory hard linking publishes the complete archive without
            # overwriting an export that another process just created.
            os.link(partial, destination)
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(partial).unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", default=str(ROOT / "dist" /
        ("selandia-niri-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".tar.gz")))
    args = parser.parse_args()
    try:
        print(export(args.destination))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")
