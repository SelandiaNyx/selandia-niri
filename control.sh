#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

# Language selection must also work while repairing a broken Python runtime.
controller_language=${LC_ALL:-${LC_MESSAGES:-${LANG:-en_US}}}
if command -v python3 >/dev/null; then
    saved_language=$(python3 -B -c '
import json, os, pathlib
code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "en_US")
try:
    state = pathlib.Path(os.environ.get("XDG_STATE_HOME", str(pathlib.Path.home() / ".local/state"))) / "selandia-niri/language.json"
    settings = json.loads(state.read_text())
    selected = settings.get("ui_language", "system")
    if selected in ("zh_CN", "en_US"):
        code = selected
    elif selected == "system":
        code = settings.get("session_locale") or code
except (OSError, ValueError, TypeError, AttributeError):
    pass
print("zh_CN" if str(code).lower().startswith("zh") else "en_US")
' 2>/dev/null) && controller_language=$saved_language
fi
case "$controller_language" in zh*) controller_language=zh_CN ;; *) controller_language=en_US ;; esac
tr() { if [[ "$controller_language" == zh_CN ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

usage() {
    if [[ "$controller_language" == zh_CN ]]; then
        cat <<'HELP'
Selandia Glass · 桌面控制脚本
用法: ./control.sh [install|update|repair|uninstall|status|check|export] [选项]
无参数时，在终端显示交互菜单。

install     安装缺少依赖并部署配置
update      更新 Arch 软件包并部署本地配置
repair      修复缺失软件、软件包文件及配置链接
uninstall   恢复原配置、应用主题与会话语言配置，保留软件包
status      检查软件包、文件和部署状态
check       运行完整桌面自检
export      在 dist/ 导出适合分享的配置包，清除本机屏幕与个人覆盖设置

--dry-run       预演，不修改系统
--no-packages   仅处理配置，跳过软件包
--yes           确认卸载配置，仅用于 uninstall
-h, --help      显示帮助

以桌面用户运行；软件包操作会请求 sudo，并由 pacman 显示事务供确认。
安装、更新依赖执行完整 Arch 更新；修复使用 pacman -Qk 检查文件是否缺失。
配置来自本目录，请保留目录；所有操作沿用修改保护及备份机制。
安装、更新及修复会恢复保存的外观、界面语言和用户会话语言。
系统默认语言只通过控制中心中的管理员操作更改。
HELP
    else
        cat <<'HELP'
Selandia Glass · Desktop controller
Usage: ./control.sh [install|update|repair|uninstall|status|check|export] [OPTIONS]
No arguments: show an interactive menu in a terminal.

install     Install missing dependencies and deploy
update      Upgrade Arch packages and deploy local configuration
repair      Restore missing packages/files and configuration links
uninstall   Restore previous configuration, app themes and session language; retain packages
status      Inspect packages, their files, and deployment
check       Run full desktop diagnostics
export      Export portable defaults to dist/ without local hardware overrides

--dry-run       Preview operations without changes
--no-packages   Apply install/update/repair to configuration only
--yes           Confirm configuration removal (uninstall only)
-h, --help      Show this help

Run as your desktop user; package transactions request sudo and pacman's confirmation.
Package installation/update uses a full Arch upgrade. Repair checks files with pacman -Qk.
Keep this directory in place; edit protection and backups stay enabled.
Install/update/repair restore saved appearance, interface and user session language.
System-wide language only changes through the control center's administrator action.
HELP
    fi
}

choose_action() {
    local choice
    while true; do
        printf '\n%s\n' "$(tr 'Selandia Glass · Desktop management' 'Selandia Glass · 桌面管理')" \
            "$(tr '  1) Install' '  1) 安装')" \
            "$(tr '  2) Update' '  2) 更新')" \
            "$(tr '  3) Repair' '  3) 修复')" \
            "$(tr '  4) Uninstall configuration (keep packages)' '  4) 卸载配置（保留软件包）')" \
            "$(tr '  5) Status' '  5) 状态')" \
            "$(tr '  6) Check' '  6) 自检')" \
            "$(tr '  7) Export for sharing' '  7) 导出分享包')" \
            "$(tr '  0) Exit' '  0) 退出')"
        if ! read -r -p "$(tr 'Choose [0-7]: ' '请选择 [0-7]：')" choice; then exit 0; fi
        case "$choice" in
            1) action=install; return ;;
            2) action=update; return ;;
            3) action=repair; return ;;
            4) action=uninstall; return ;;
            5) action=status; return ;;
            6) action=check; return ;;
            7) action='export'; return ;;
            0|'') exit 0 ;;
            *) printf '%s\n' "$(tr 'Choose a number from 0 to 7.' '请输入 0 到 7。')" ;;
        esac
    done
}

fail() { printf '%s\n' "$*" >&2; exit 1; }
invalid() { printf '%s\n' "$*" >&2; usage >&2; exit 2; }
python_ready() {
    command -v python3 >/dev/null &&
        python3 -B -c 'import contextlib, fcntl, json, os, pathlib, shutil, subprocess, sys, tempfile' >/dev/null 2>&1
}

action=
preview=false
skip_packages=false
confirmed=false
for argument in "$@"; do
    case "$argument" in
        install|update|repair|uninstall|status|check|export)
            [[ -z "$action" ]] || invalid "$(tr 'Choose one command' '一次只能选择一个操作。')"
            action=$argument
            ;;
        --dry-run) preview=true ;;
        --no-packages) skip_packages=true ;;
        --yes) confirmed=true ;;
        --help|-h) usage; exit 0 ;;
        *) invalid "$(tr 'Unknown argument: ' '未知参数：')$argument" ;;
    esac
done
if [[ -z "$action" ]]; then
    if (($#)); then invalid "$(tr 'Specify a command before its options' '请指定操作命令。')"; fi
    if [[ -t 0 && -t 1 ]]; then choose_action; else usage; exit 0; fi
fi
if [[ "$action" == status || "$action" == check || "$action" == export ]]; then
    if "$preview" || "$skip_packages" || "$confirmed"; then invalid "$(tr 'This command takes no options' '此操作不接受选项。')"; fi
elif [[ "$action" == uninstall ]]; then
    if "$skip_packages"; then invalid "$(tr 'Uninstall already retains packages' '卸载本身就保留软件包。')"; fi
elif "$confirmed"; then
    invalid "$(tr '--yes is only for uninstall' '--yes 仅用于卸载配置。')"
fi
if [[ "$action" == check ]]; then exec "$root/check.sh"; fi
if [[ "$action" == export ]]; then exec python3 -B "$root/tools/export_config.py"; fi

controller_state=${XDG_STATE_HOME:-$HOME/.local/state}/selandia-niri
controller_config=${XDG_CONFIG_HOME:-$HOME/.config}
[[ "$controller_state" == /* && "$controller_config" == /* ]] || fail "$(tr 'XDG paths must be absolute' 'XDG 路径必须是绝对路径。')"
if [[ "$action" != status ]] && ! "$preview"; then
    [[ "$EUID" -ne 0 ]] || fail "$(tr 'Run as your desktop user, without sudo' '请以桌面用户运行，不要 sudo 整个脚本。')"
fi

# Read-only plans happen before acquiring the mutation lock or invoking sudo.
case "$action" in
    uninstall)
        python_ready || fail "$(tr 'Working Python 3 is needed to safely restore backups' '安全恢复备份需要可正常运行的 Python 3。')"
        python3 -B "$root/tools/deploy.py" dry-run-uninstall
        if [[ -e "$controller_state/application-theme.json" ]]; then
            printf '%s\n' "$(tr 'Restore managed GTK/Qt appearance settings; preserve later user edits' '恢复托管的 GTK/Qt 外观设置，保留之后的用户修改。')"
        fi
        if [[ -e "$controller_state/language-backup.json" ]]; then
            printf '%s\n' "$(tr 'Restore managed user session language settings; retain the system default' '恢复托管的用户会话语言设置，保留系统默认语言。')"
        fi
        if "$preview"; then exit 0; fi
        if [[ ! -e "$controller_state/install.json" && ! -e "$controller_state/application-theme.json" && ! -e "$controller_state/language-backup.json" && ! -e "$controller_state/session-settings-backup.json" && ! -e "$controller_state/lifecycle-transaction.json" && ! -e "$controller_state/deployment-transaction.json" ]]; then exit 0; fi
        if ! "$confirmed"; then
            [[ -t 0 ]] || fail "$(tr 'Use uninstall --yes to confirm non-interactive configuration removal' '非交互卸载请明确使用 uninstall --yes。')"
            read -r -p "$(tr 'Restore the listed paths and stop desktop components? [y/N] ' '恢复以上路径并停止桌面组件？ [y/N] ')" answer || exit 0
            case "$answer" in y|Y|yes|YES) ;; *) printf '%s\n' "$(tr 'Cancelled' '已取消。')"; exit 0 ;; esac
        fi
        ;;
    install|update|repair)
        for source in install.sh check.sh packages.txt tools/deploy.py; do
            [[ -f "$root/$source" ]] || fail "$(tr 'Missing project source: ' '项目源文件缺失：')$root/$source"
        done
        if python_ready; then
            if "$preview"; then python3 -B "$root/tools/deploy.py" dry-run
            else python3 -B "$root/tools/deploy.py" preflight; fi
        else
            if "$skip_packages"; then fail "$(tr 'Restore Python before configuration-only operations' '仅处理配置前，请先恢复 Python。')"; fi
            printf '%s\n' "$(tr 'Python is unavailable; deployment preflight will run after dependency installation.' 'Python 无法正常运行，安装依赖后将检查部署状态。')"
        fi
        ;;
esac

if [[ "$action" != status ]] && ! "$preview"; then
    command -v flock >/dev/null || fail "$(tr 'flock (util-linux) is required' '需要 util-linux 提供的 flock。')"
    mkdir -p -- "$controller_state"
    exec 9>"$controller_state/control.lock"
    flock -n 9 || fail "$(tr 'Another controller operation is running' '另一个控制操作正在运行。')"
fi
if [[ "$action" != status ]] && ! "$preview" && [[ -e "$controller_state/lifecycle-transaction.json" || -e "$controller_state/deployment-transaction.json" ]]; then
    python3 -B "$root/tools/lifecycle.py" recover
fi
if [[ "$action" == uninstall ]]; then
    exec python3 -B "$root/tools/lifecycle.py" uninstall
fi

selected=()
missing=()
damaged=()
inventory_ok=true
if ! "$skip_packages"; then
    if ! command -v pacman >/dev/null; then
        inventory_ok=false
        if [[ "$action" != status ]] && ! "$preview"; then
            fail "$(tr 'Automatic packages require Arch Linux; prepare dependencies and use --no-packages.' '自动包管理需要 Arch；请先准备依赖并使用 --no-packages。')"
        fi
        printf '%s\n' "$(tr 'Package inventory unavailable: pacman is missing' '缺少 pacman，无法检查软件包。')"
    else
        [[ -f "$root/packages.txt" ]] || fail "$(tr 'packages.txt is missing' '缺少依赖清单 packages.txt。')"
        declare -A seen=()
        while IFS= read -r package || [[ -n "$package" ]]; do
            package=${package%%#*}
            package=${package//[[:space:]]/}
            [[ -n "$package" ]] || continue
            [[ "$package" =~ ^[a-zA-Z0-9_+][a-zA-Z0-9@._+-]*$ ]] || fail "$(tr 'Invalid package name: ' '软件包名无效：')$package"
            installed=false
            if pacman -Q "$package" >/dev/null 2>&1; then
                installed=true
            elif [[ "$package" == pavucontrol ]] && pacman -Q pavucontrol-qt >/dev/null 2>&1; then
                package=pavucontrol-qt
                installed=true
            fi
            [[ -z "${seen[$package]+present}" ]] || continue
            seen[$package]=1
            selected+=("$package")
            if ! "$installed"; then
                missing+=("$package")
            elif [[ "$action" == repair || "$action" == status ]]; then
                if details=$(LC_ALL=C pacman -Qk "$package" 2>&1); then
                    :
                else
                    code=$?
                    [[ "$code" -eq 1 ]] || fail "$(tr 'Package check failed: ' '软件包检查失败：')$details"
                    damaged+=("$package")
                    printf '%s\n' "$details"
                fi
            fi
        done < "$root/packages.txt"
        ((${#selected[@]})) || fail "$(tr 'Dependency list is empty' '依赖清单为空。')"
        if ((${#missing[@]})); then printf '%s%s\n' "$(tr 'Missing packages: ' '缺少软件包：')" "${missing[*]}"; fi
        if ((${#damaged[@]})); then printf '%s%s\n' "$(tr 'Packages with missing files: ' '软件包文件缺失：')" "${damaged[*]}"; fi
        if ((${#missing[@]} == 0 && ${#damaged[@]} == 0)); then
            printf '%s\n' "$(tr 'Required packages present' '必需软件包已安装。')"
        fi
    fi
fi

if [[ "$action" == status ]]; then
    healthy=0
    if ! "$inventory_ok" || ((${#missing[@]} || ${#damaged[@]})); then healthy=1; fi
    if python_ready; then
        python3 -B "$root/tools/deploy.py" status || healthy=1
    else
        printf '%s\n' "$(tr 'Python unavailable; deployment status unavailable' 'Python 无法正常运行，无法检查部署状态。')"
        healthy=1
    fi
    exit "$healthy"
fi

transaction=()
if ! "$skip_packages" && "$inventory_ok"; then
    if [[ "$action" == update ]]; then
        transaction=(sudo pacman -Syu --needed -- "${selected[@]}")
    elif [[ "$action" == repair ]] && ((${#damaged[@]})); then
        # --needed would skip current-version packages even when their files are gone.
        transaction=(sudo pacman -Syu -- "${missing[@]}" "${damaged[@]}")
    elif ((${#missing[@]})); then
        transaction=(sudo pacman -Syu --needed -- "${missing[@]}")
    fi
fi
if ((${#transaction[@]})); then
    printf '%s' "$(tr 'Package transaction: ' '软件包事务：')"
    printf '%q ' "${transaction[@]}"
    printf '\n'
    if ! "$preview"; then
        command -v sudo >/dev/null || fail "$(tr 'sudo is required for package installation' '安装软件包需要 sudo。')"
        "${transaction[@]}" 9>&-
    fi
elif "$skip_packages"; then
    printf '%s\n' "$(tr 'Configuration only' '仅处理配置。')"
elif ! "$inventory_ok"; then
    printf '%s\n' "$(tr 'Package transaction cannot be determined without pacman' '缺少 pacman，无法确定所需的软件包事务。')"
else
    printf '%s\n' "$(tr 'No package transaction needed' '无需执行软件包事务。')"
fi
if "$preview"; then
    printf '%s\n' "$(tr 'Would restore the saved user language and generate interface labels before validation' '校验前将恢复保存的用户语言并生成界面文本。')"
    printf '%s\n' "$(tr 'Would synchronize saved application appearance after deployment' '部署后将同步保存的应用外观。')"
    printf '%s\n' "$(tr 'Preview complete; no changes made' '预演完成，未做任何修改。')"
    exit 0
fi
# AUR helpers run as the user. Never pass AUR names to pacman or retry sudo.
# Missing required AUR packages stop deployment, with an exact password-aware command.
if ! "$skip_packages" && "$inventory_ok"; then
    required_missing=()
    while IFS= read -r declaration; do
        if [[ "$declaration" =~ ^\#[[:space:]]required[[:space:]]aur[[:space:]]([a-zA-Z0-9@._+-]+)[[:space:]] ]]; then
            required_package=${BASH_REMATCH[1]}
            pacman -Q "$required_package" >/dev/null 2>&1 || required_missing+=("$required_package")
        fi
    done < "$root/packages.txt"
    if ((${#required_missing[@]})); then
        helper=paru
        command -v paru >/dev/null || helper=yay
        printf '%s\n' "$(tr 'Required Rust components; enter your sudo password in this terminal when prompted.' '必需 Rust 组件：出现 sudo 提示时，请在当前终端输入密码。')"
        printf '%q ' "$helper" -S --needed -- "${required_missing[@]}"
        printf '\n'
        if [[ -t 0 && -t 1 ]] && command -v "$helper" >/dev/null; then
            if ! "$helper" -S --needed -- "${required_missing[@]}" 9>&-; then
                fail "$(tr 'Required AUR installation incomplete; deployment stopped. Run the command above to retry.' '必需 AUR 安装未完成，已停止部署。请执行上述命令。')"
            fi
        else
            fail "$(tr 'Run the command above in your terminal; waiting for user password. Deployment stopped.' '请在自己的终端执行上述命令，待用户输入密码；已停止部署。')"
        fi
    fi
fi
python_ready || fail "$(tr 'Working Python 3 is required' '需要可正常运行的 Python 3。')"
python3 -B "$root/tools/deploy.py" preflight
python3 -B "$root/tools/lifecycle.py" install
printf '%s\n' "$(tr 'Done. In Niri, press Super+Ctrl+R to reload desktop components.' '完成。在 Niri 中按 Super+Ctrl+R 重载桌面组件。')"
