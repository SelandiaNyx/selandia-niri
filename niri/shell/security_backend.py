"""Native UFW firewall, account/group identity, hostname, and security runtime state."""
from __future__ import annotations

import grp
import os
import platform
import pwd
import re
import shutil
import subprocess

from i18n import tr
import polkit_helper

ENV = dict(os.environ, LC_ALL="C")
_RULE_LINE_RE = re.compile(r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)(?:\s+(IN|OUT|FWD))?(?:\s+(.*))?$")


def _parse_ufw_status(text: str) -> dict:
    active = False
    default_in = ""
    default_out = ""
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Status:"):
            active = "active" in line.lower() and "inactive" not in line.lower()
        elif line.startswith("Default:"):
            m_in = re.search(r"(\w+)\s*\(incoming\)", line)
            m_out = re.search(r"(\w+)\s*\(outgoing\)", line)
            if m_in:
                default_in = m_in.group(1)
            if m_out:
                default_out = m_out.group(1)
        else:
            m = _RULE_LINE_RE.match(line)
            if m:
                rules.append({
                    "num": m.group(1),
                    "to": m.group(2).strip(),
                    "action": m.group(3).strip(),
                    "direction": (m.group(4) or "IN").strip(),
                    "source": (m.group(5) or "Anywhere").strip(),
                })
    return {"active": active, "default_in": default_in, "default_out": default_out, "rules": rules}


def read_ufw(*, privileged: bool = False) -> dict:
    """Inspect UFW firewall state. Uses unprivileged check first; optional pkexec reads rules."""
    if not shutil.which("ufw"):
        return {"installed": False, "active": False, "needs_auth": False, "default_in": "", "default_out": "", "rules": [], "service_enabled": False}
    svc_active = False
    svc_enabled = False
    if shutil.which("systemctl"):
        r1 = subprocess.run(["systemctl", "is-active", "ufw.service"], capture_output=True, text=True, env=ENV, timeout=4)
        svc_active = r1.stdout.strip() == "active"
        r2 = subprocess.run(["systemctl", "is-enabled", "ufw.service"], capture_output=True, text=True, env=ENV, timeout=4)
        svc_enabled = r2.stdout.strip() == "enabled"

    if privileged:
        verbose = polkit_helper.ufw_command(["status", "verbose"])
        numbered = polkit_helper.ufw_command(["status", "numbered"])
        parsed = _parse_ufw_status(verbose + "\n" + numbered)
        return {"installed": True, "needs_auth": False, "service_enabled": svc_enabled, **parsed}

    # Unprivileged check (works if user has permission or ufw allows reading)
    try:
        res = subprocess.run(["ufw", "status", "numbered"], capture_output=True, text=True, env=ENV, timeout=4)
        if res.returncode == 0:
            parsed = _parse_ufw_status(res.stdout)
            return {"installed": True, "needs_auth": False, "service_enabled": svc_enabled, **parsed}
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "installed": True, "active": svc_active, "needs_auth": True,
        "default_in": "", "default_out": "", "rules": [], "service_enabled": svc_enabled,
    }


def set_ufw_enabled(enabled: bool) -> str:
    return polkit_helper.ufw_command(["enable" if enabled else "disable"])


def set_ufw_default(direction: str, policy: str) -> str:
    return polkit_helper.ufw_command(["default", policy, direction])


def add_ufw_rule(action: str, port_spec: str) -> str:
    return polkit_helper.ufw_command([action, port_spec])


def delete_ufw_rule(rule_num: str) -> str:
    return polkit_helper.ufw_command(["delete", str(rule_num)])


def read_account_state() -> dict:
    """Read current user account, privilege groups, hostname, and security daemons."""
    uid = os.getuid()
    pw = pwd.getpwuid(uid)
    user = pw.pw_name
    groups = sorted({g.gr_name for g in grp.getgrall() if user in g.gr_mem or g.gr_gid == pw.pw_gid})
    polkit_running = False
    keyring_running = False
    if shutil.which("pgrep"):
        polkit_running = subprocess.run(["pgrep", "-f", "polkit"], capture_output=True, timeout=3).returncode == 0
        keyring_running = subprocess.run(["pgrep", "-x", "gnome-keyring-daemon"], capture_output=True, timeout=3).returncode == 0
    return {
        "user": user,
        "full_name": (pw.pw_gecos.split(",", 1)[0] or user).strip(),
        "uid": uid,
        "shell": pw.pw_shell,
        "home": pw.pw_dir,
        "hostname": platform.node(),
        "groups": groups,
        "is_admin": "wheel" in groups or "sudo" in groups or uid == 0,
        "polkit_running": polkit_running,
        "keyring_running": keyring_running,
        "pkexec_available": polkit_helper.available(),
    }


def rename_hostname(new_name: str) -> str:
    return polkit_helper.set_hostname(new_name)
