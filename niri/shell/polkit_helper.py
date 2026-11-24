"""Allow-listed Polkit (pkexec) runner for privileged system control actions.

Every operation validates its arguments strictly before invoking ``pkexec`` with
an explicit argv list (never a shell). Read-only probes stay unprivileged.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

from i18n import tr

ENV = dict(os.environ, LC_ALL="C")
_UNIT_RE = re.compile(r"^[A-Za-z0-9@._:-]{1,128}$")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$")
_PORT_RE = re.compile(r"^(?:[1-9][0-9]{0,4}(?::[1-9][0-9]{0,4})?)$")
_ALLOWED_BINARIES = frozenset({"systemctl", "hostnamectl", "ufw", "paccache", "pacman"})


def available() -> bool:
    return bool(shutil.which("pkexec"))


def run_privileged(argv: list[str], *, timeout: int = 30) -> str:
    """Execute an allow-listed command through pkexec and return stdout."""
    if not argv or not isinstance(argv[0], str) or os.path.basename(argv[0]) not in _ALLOWED_BINARIES:
        raise ValueError(tr("Disallowed privileged command", "不允许的管理员命令"))
    pkexec = shutil.which("pkexec")
    if not pkexec:
        raise RuntimeError(tr("Polkit (pkexec) is not installed", "未安装 Polkit（pkexec）"))
    binary = shutil.which(argv[0]) if not os.path.isabs(argv[0]) else argv[0]
    if not binary:
        raise RuntimeError(tr(f"Command unavailable: {argv[0]}", f"命令不可用：{argv[0]}"))
    result = subprocess.run([pkexec, binary, *argv[1:]], capture_output=True, text=True, env=ENV, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-320:]
        if result.returncode in (126, 127) and ("dismissed" in detail.lower() or not detail):
            raise RuntimeError(tr("Administrator authentication was cancelled", "已取消管理员授权"))
        raise RuntimeError(detail or tr("Privileged command failed", "管理员操作执行失败"))
    return result.stdout.strip()


def systemctl_system(action: str, unit: str) -> str:
    if action not in ("start", "stop", "restart", "enable", "disable"):
        raise ValueError(tr("Unsupported systemd action", "不支持的服务操作"))
    if not _UNIT_RE.fullmatch(unit):
        raise ValueError(tr("Invalid systemd unit name", "无效的 systemd 单元名称"))
    return run_privileged(["systemctl", action, "--", unit])


def set_hostname(hostname: str) -> str:
    cleaned = hostname.strip()
    if not _HOSTNAME_RE.fullmatch(cleaned):
        raise ValueError(tr("Hostname must use letters, digits and hyphens only", "主机名仅允许字母、数字与连字符"))
    return run_privileged(["hostnamectl", "set-hostname", "--", cleaned])


def ufw_command(args: list[str]) -> str:
    """Run an allow-listed UFW management command via pkexec."""
    if not args:
        raise ValueError(tr("Empty firewall command", "防火墙指令为空"))
    head = args[0]
    if head in ("enable", "disable", "reload"):
        return run_privileged(["ufw", "--force", head])
    if head == "status" and args[1:] in ([], ["verbose"], ["numbered"]):
        return run_privileged(["ufw", *args])
    if head == "default" and len(args) == 3 and args[1] in ("allow", "deny", "reject") and args[2] in ("incoming", "outgoing"):
        return run_privileged(["ufw", "default", args[1], args[2]])
    if head in ("allow", "deny", "reject") and len(args) == 2:
        spec = args[1].strip().lower()
        if "/" in spec:
            port, proto = spec.split("/", 1)
            if proto not in ("tcp", "udp") or not _PORT_RE.fullmatch(port):
                raise ValueError(tr("Invalid port/protocol rule", "端口或协议格式无效"))
            return run_privileged(["ufw", head, f"{port}/{proto}"])
        if _PORT_RE.fullmatch(spec):
            return run_privileged(["ufw", head, spec])
        raise ValueError(tr("Invalid port specification", "端口格式无效"))
    if head == "delete" and len(args) == 2 and args[1].isdigit() and int(args[1]) >= 1:
        return run_privileged(["ufw", "--force", "delete", args[1]])
    raise ValueError(tr("Unsupported firewall operation", "不支持的防火墙操作"))


def clean_pacman_cache() -> str:
    if shutil.which("paccache"):
        return run_privileged(["paccache", "-rk2"], timeout=60)
    return run_privileged(["pacman", "-Sc", "--noconfirm"], timeout=60)
