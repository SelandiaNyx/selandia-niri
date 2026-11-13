#!/usr/bin/env bash
# Compatibility entrypoint; the unified controller lives in control.sh.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
arguments=()
has_action=false
explicit_packages=false
skip_packages=false
uninstall=false
for argument in "$@"; do
    case "$argument" in
        --packages) explicit_packages=true ;;
        --no-packages) skip_packages=true; arguments+=("$argument") ;;
        --uninstall) uninstall=true; has_action=true; arguments+=(uninstall) ;;
        install|update|repair|uninstall|status|check|export)
            has_action=true
            [[ "$argument" != uninstall ]] || uninstall=true
            arguments+=("$argument")
            ;;
        *) arguments+=("$argument") ;;
    esac
done
if "$explicit_packages" && { "$skip_packages" || "$uninstall"; }; then
    language=${LC_ALL:-${LC_MESSAGES:-${LANG:-en_US}}}
    if [[ -f "$root/niri/shell/i18n.py" ]] && command -v python3 >/dev/null; then
        selected=$(python3 -B "$root/niri/shell/i18n.py" language 2>/dev/null) && language=$selected
    fi
    if [[ "$language" == zh* ]]; then
        printf '%s\n' '参数冲突：--packages 不能与 --no-packages 或 uninstall 同时使用。' >&2
    else
        printf '%s\n' 'Conflicting options: --packages cannot accompany --no-packages or uninstall.' >&2
    fi
    exit 2
fi
if ! "$has_action"; then arguments=(install "${arguments[@]}"); fi
exec "$root/control.sh" "${arguments[@]}"
