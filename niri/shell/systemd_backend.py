"""Unified systemd user & system service inspector and safe controller."""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from i18n import tr
import polkit_helper

ENV = dict(os.environ, LC_ALL="C")


def _systemctl(scope: str, args: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess:
    if not shutil.which("systemctl"):
        raise RuntimeError(tr("systemctl is unavailable", "systemctl 不可用"))
    prefix = ["systemctl", "--user"] if scope == "user" else ["systemctl"]
    return subprocess.run([*prefix, *args], capture_output=True, text=True, env=ENV, timeout=timeout)


def list_units(scope: str = "user", *, query: str = "", state_filter: str = "all", limit: int = 80) -> list[dict]:
    """List systemd .service units for ``user`` or ``system`` scope."""
    if scope not in ("user", "system"):
        raise ValueError("scope must be user or system")
    res = _systemctl(scope, ["list-units", "--type=service", "--all", "--output=json", "--no-pager"])
    units_raw = []
    if res.returncode == 0 and res.stdout.strip():
        try:
            units_raw = json.loads(res.stdout)
        except ValueError:
            units_raw = []

    # Map enabled/disabled unit-file state
    uf_res = _systemctl(scope, ["list-unit-files", "--type=service", "--output=json", "--no-pager"])
    file_states: dict[str, str] = {}
    if uf_res.returncode == 0 and uf_res.stdout.strip():
        try:
            for item in json.loads(uf_res.stdout):
                name = item.get("unit_file") or ""
                if name:
                    file_states[name] = item.get("state") or ""
        except ValueError:
            pass

    needle = query.strip().casefold()
    items = []
    for entry in units_raw:
        unit = str(entry.get("unit") or "")
        if not unit:
            continue
        active = str(entry.get("active") or "unknown")
        sub = str(entry.get("sub") or "")
        desc = str(entry.get("description") or "")
        enabled = file_states.get(unit, "")
        if state_filter == "active" and active != "active":
            continue
        if state_filter == "failed" and active != "failed":
            continue
        if state_filter == "inactive" and active not in ("inactive", "deactivating"):
            continue
        if needle and needle not in unit.casefold() and needle not in desc.casefold():
            continue
        items.append({
            "unit": unit, "scope": scope, "active": active, "sub": sub,
            "enabled": enabled, "description": desc,
        })

    items.sort(key=lambda x: (0 if x["active"] == "failed" else (1 if x["active"] == "active" else 2), x["unit"].casefold()))
    return items[:limit]


def control_unit(scope: str, unit: str, action: str) -> str:
    """Start, stop, restart, enable or disable a user or system unit."""
    if action not in ("start", "stop", "restart", "enable", "disable"):
        raise ValueError(tr("Unsupported unit action", "不支持的服务动作"))
    if scope == "system":
        return polkit_helper.systemctl_system(action, unit)
    res = _systemctl("user", [action, "--", unit], timeout=15)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or tr("User service action failed", "用户服务操作失败"))
    return res.stdout.strip()
