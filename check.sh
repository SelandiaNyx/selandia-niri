#!/usr/bin/env bash
set -u
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
check_language=${LC_ALL:-${LC_MESSAGES:-${LANG:-en_US}}}
if [[ -f "$root/niri/shell/i18n.py" ]] && command -v python3 >/dev/null; then
    selected=$(timeout --kill-after=2s 3s python3 -B "$root/niri/shell/i18n.py" language 2>/dev/null) && check_language=$selected
fi
tr() { if [[ "$check_language" == zh* ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
if ! command -v timeout >/dev/null; then
    printf '%s\n' "$(tr 'Missing timeout (coreutils)' '缺少 timeout（coreutils）')" >&2
    exit 1
fi
mode=${1:-all}
if [[ "$#" -gt 1 || ( "$mode" != all && "$mode" != --config && "$mode" != --tests ) ]]; then
    printf '%s\n' "$(tr 'Usage: ./check.sh [--config|--tests]' '用法：./check.sh [--config|--tests]')" >&2
    exit 2
fi
failed=0

# The project's own test suite is part of the self-check; --config stays fast
# because the installer and the smoke test call it on every run.
run_tests() {
    printf '\n%s\n' "$(tr 'Unit tests' '单元测试')"
    if ! command -v python3 >/dev/null; then
        printf '%s\n' "$(tr 'Missing Python 3' '缺少 Python 3')" >&2
        return 1
    fi
    # The suite takes ~50s; 180s bounds the entire private process group.
    ( cd -- "$root" && timeout --kill-after=2s 180s python3 -B tools/run_tests.py discover -s tests )
}
printf '\n%s\n' "$(tr 'Configuration validation' '配置校验')"
if command -v "${NIRI_BIN:-niri}" >/dev/null; then
    timeout --kill-after=2s 5s "${NIRI_BIN:-niri}" validate -c "$root/niri/config.kdl" || failed=1
    timeout --kill-after=2s 5s "${NIRI_BIN:-niri}" validate -c "$root/niri/preview.kdl" || failed=1
else
    printf '%s\n' "$(tr 'Missing niri; run ./install.sh.' '缺少 niri；请运行 ./install.sh。')"
    failed=1
fi
if command -v fuzzel >/dev/null; then
    timeout --kill-after=2s 5s fuzzel --check-config --config "$root/niri/fuzzel/fuzzel.ini" || failed=1
    timeout --kill-after=2s 5s fuzzel --check-config --config "$root/niri/theme/fuzzel.ini" || failed=1
else
    printf '%s\n' "$(tr 'Missing fuzzel' '缺少 fuzzel')"
    failed=1
fi
if command -v python3 >/dev/null; then
    timeout --kill-after=2s 15s python3 -B - "$root" "$check_language" <<'PY' || failed=1
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
def tr(english, chinese):
    return chinese if sys.argv[2].startswith("zh") else english

for path in sorted((root / "niri").rglob("*.json")):
    json.loads(path.read_text())
    print(tr("JSON OK:", "JSON 校验通过："), path.relative_to(root))

shells = sorted(root.glob("*.sh"))
shells += [path for path in sorted((root / "niri/scripts").glob("*"))
           if path.is_file() and (lines := path.read_text().splitlines()) and "bash" in lines[0]]
for path in shells:
    subprocess.run(["bash", "-n", str(path)], check=True, timeout=5)
if shutil.which("shellcheck"):
    subprocess.run(["shellcheck", "--severity=warning", *map(str, shells)], check=True, timeout=15)
else:
    print(tr("Optional shellcheck absent; bash syntax checked.", "未安装可选 shellcheck；已检查 Bash 语法。"))
print(tr("Shell syntax OK: {} files", "Shell 语法检查通过：{} 个文件").format(len(shells)))

python_files = sorted(path for directory in ("tools", "tests", "niri/shell")
                      for path in (root / directory).rglob("*.py"))
# Explicit destinations keep __pycache__ out of the live linked configuration.
with tempfile.TemporaryDirectory(prefix="selandia-check-") as temporary:
    for index, path in enumerate(python_files):
        py_compile.compile(str(path), cfile=str(Path(temporary) / f"{index}.pyc"), doraise=True)
print(tr("Python syntax OK: {} files", "Python 语法检查通过：{} 个文件").format(len(python_files)))

# This import probe creates no UI and does not need an accessibility connection.
# Scope the override to this short process; desktop accessibility remains enabled.
import os
os.environ["NO_AT_BRIDGE"] = "1"
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gtk, GtkLayerShell
import cairo
assert callable(cairo.Region), tr("Static crossfade requires python-cairo", "静态淡入淡出需要 python-cairo")
assert Gtk.MAJOR_VERSION == 3
assert any("svg" in item.get_extensions() for item in GdkPixbuf.Pixbuf.get_formats()), tr("SVG wallpaper support requires librsvg", "SVG 壁纸支持需要 librsvg")
print(tr("GTK 3 + GtkLayerShell + SVG support OK", "GTK 3、GtkLayerShell 及 SVG 壁纸依赖正常"))
for filename in ("shell/style.css", "theme/panel.css", "shell/control_center.css", "theme/eww.css"):
    Gtk.CssProvider().load_from_path(str(root / "niri" / filename))
subprocess.run([sys.executable, "-B", "-c",
                "import gi,sys; gi.require_version('Gtk','4.0'); from gi.repository import Gtk; "
                "errs=[];\n"
                "for path in sys.argv[1:]:\n"
                "    pr=Gtk.CssProvider()\n"
                "    pr.connect('parsing-error', lambda _p,_s,e,f=path: errs.append(f'{f}: {e.message}'))\n"
                "    pr.load_from_path(path)\n"
                "if errs: sys.exit('\\n'.join(errs))",
                str(root / "niri/theme/swaync.css"), str(root / "niri/theme/anyrun.css")], check=True, timeout=5)
import tomllib
tomllib.loads((root / "niri/theme/alacritty.toml").read_text())
print(tr("Theme CSS OK: GTK 3 + GTK 4", "GTK 3 与 GTK 4 主题样式校验通过"))
PY
else
    printf '%s\n' "$(tr 'Missing Python 3' '缺少 Python 3')"
    failed=1
fi
if [[ "$mode" == --tests ]]; then
    run_tests || failed=1
    exit "$failed"
fi
if [[ "$mode" == --config ]]; then
    exit "$failed"
fi

printf '\n%s\n' "$(tr 'Runtime dependencies' '运行依赖')"
for cmd in eww anyrun anyrun-provider alacritty rustc; do
    if command -v "$cmd" >/dev/null; then
        printf '  %s %s\n' "$(tr 'Rust component available:' 'Rust 组件可用：')" "$cmd"
    else
        printf '  %s %s\n' "$(tr 'Required Rust component missing:' '缺少必需 Rust 组件：')" "$cmd"
        failed=1
    fi
done
for cmd in niri xwayland-satellite fuzzel swaync swaync-client swaybg swayidle swaylock wl-copy wl-paste cliphist notify-send brightnessctl ddcutil playerctl wpctl pactl nmcli nm-applet nm-connection-editor blueman-manager fcitx5 gdbus flock xdg-open systemd-inhibit qt6ct; do
    if command -v "$cmd" >/dev/null; then
        printf '  %s  %s\n' "$(tr 'OK' '正常')" "$cmd"
    else
        printf '  %s  %s\n' "$(tr 'Missing' '缺少')" "$cmd"
        failed=1
    fi
done
if command -v pavucontrol >/dev/null || command -v pavucontrol-qt >/dev/null; then
    printf '  %s\n' "$(tr 'OK  audio mixer' '正常  音频混音器')"
else
    printf '  %s\n' "$(tr 'Missing  pavucontrol (or pavucontrol-qt)' '缺少  pavucontrol（或 pavucontrol-qt）')"
    failed=1
fi
if command -v pacman >/dev/null; then
    for pkg in xdg-desktop-portal-gnome xdg-desktop-portal-gtk polkit-kde-agent gnome-keyring fcitx5-gtk fcitx5-qt; do
        timeout --kill-after=2s 5s pacman -Q "$pkg" || failed=1
    done
fi
if ! command -v powerprofilesctl >/dev/null; then
    printf '  %s\n' "$(tr 'Optional power profiles unavailable (power-profiles-daemon).' '可选硬件电源模式不可用（power-profiles-daemon）。')"
fi
printf '\n%s\n' "$(tr 'Optional wallpaper dependencies (missing ones do not fail the core check)' '可选壁纸依赖（缺失不判定核心检查失败）')"
timeout --kill-after=2s 5s python3 -B "$root/niri/shell/wallpaper.py" dependencies || failed=1
printf '  %s\n' "$(tr 'AI: configure a provider in the sidebar; no AI account/model is installed automatically.' 'AI：在侧栏配置服务，不自动安装账号或模型。')"

run_tests || failed=1

printf '\n%s\n' "$(tr 'Current Niri session' '当前 Niri 会话')"
if [[ -n "${NIRI_SOCKET:-}" ]]; then
    timeout --kill-after=2s 5s "${NIRI_BIN:-niri}" msg outputs || failed=1
    timeout --kill-after=2s 5s systemctl --user --no-pager --full status selandia-niri.target || failed=1
    for component in waybar notifications wallpaper sleep-lock clipboard-text clipboard-image polkit; do
        case "$component" in
            waybar|notifications|clipboard-text|clipboard-image)
                unit_state=$(timeout --kill-after=2s 5s systemctl --user show --property=UnitFileState --value "selandia-niri@$component.service") || failed=1
                if [[ "$unit_state" == masked || "$unit_state" == masked-runtime ]]; then
                    printf '%s%s\n' "$(tr 'Disabled in settings: ' '已在设置中禁用：')" "$component"
                    continue
                fi
                ;;
        esac
        if ! timeout --kill-after=2s 5s systemctl --user is-active --quiet "selandia-niri@$component.service"; then
            printf '%s%s (journalctl --user -u selandia-niri@%s.service)\n' "$(tr 'Component inactive: ' '组件未运行：')" "$component" "$component"
            failed=1
        fi
    done
    # Empty timer configuration is normal; only a confirmed inhibitor means awake.
    timeout --kill-after=2s 15s python3 -B - "$root" <<'PY' || failed=1
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / "niri/shell"))
import sleep_guard
state = sleep_guard.status()
print(state["label"] + ": " + state["detail"])
raise SystemExit(0 if state["available"] and not state["error"] else 1)
PY
else
    printf '%s\n' "$(tr 'Outside Niri; skipped display and session service checks.' '当前不在 Niri 中，跳过显示器及会话服务检查。')"
fi
exit "$failed"
