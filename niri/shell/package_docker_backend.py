"""Arch package maintenance (pacman/paru read-only + cache clean) & Docker control."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from i18n import tr
import polkit_helper

ENV = dict(os.environ, LC_ALL="C")
_CONTAINER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _capture(argv: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
    if not shutil.which(argv[0]):
        return 127, "", ""
    try:
        res = subprocess.run(argv, capture_output=True, text=True, env=ENV, timeout=timeout)
        return res.returncode, res.stdout, res.stderr
    except (OSError, subprocess.SubprocessError) as err:
        return 1, "", str(err)


def read_package_state(*, check_updates: bool = False) -> dict:
    """Read local Arch package stats, orphan list, cache size, and optional pending updates."""
    local_db = Path("/var/lib/pacman/local")
    installed_count = 0
    if local_db.is_dir():
        try:
            installed_count = sum(1 for entry in os.scandir(local_db) if entry.is_dir())
        except OSError:
            pass

    orphans = []
    if shutil.which("pacman"):
        code, out, _ = _capture(["pacman", "-Qtdq"], timeout=8)
        if code == 0 and out.strip():
            orphans = [line.strip() for line in out.splitlines() if line.strip()]

    cache_dir = Path("/var/cache/pacman/pkg")
    cache_bytes = 0
    cache_files = 0
    if cache_dir.is_dir():
        try:
            for entry in os.scandir(cache_dir):
                if entry.is_file(follow_symlinks=False):
                    cache_bytes += entry.stat(follow_symlinks=False).st_size
                    cache_files += 1
        except OSError:
            pass

    updates = []
    aur_updates = []
    if check_updates:
        if shutil.which("checkupdates"):
            code, out, _ = _capture(["checkupdates"], timeout=25)
            if code == 0:
                updates = [line.strip() for line in out.splitlines() if line.strip()]
        elif shutil.which("pacman"):
            code, out, _ = _capture(["pacman", "-Qu"], timeout=12)
            if code == 0:
                updates = [line.strip() for line in out.splitlines() if line.strip()]
        helper = shutil.which("paru") or shutil.which("yay")
        if helper:
            code, out, _ = _capture([helper, "-Qua"], timeout=25)
            if code == 0:
                aur_updates = [line.strip() for line in out.splitlines() if line.strip()]

    return {
        "pacman_available": bool(shutil.which("pacman")),
        "aur_helper": "paru" if shutil.which("paru") else ("yay" if shutil.which("yay") else ""),
        "installed_count": installed_count,
        "orphans": orphans,
        "cache_bytes": cache_bytes,
        "cache_files": cache_files,
        "updates": updates,
        "aur_updates": aur_updates,
        "updates_checked": check_updates,
    }


def clean_cache() -> str:
    return polkit_helper.clean_pacman_cache()


def read_docker_state() -> dict:
    if not shutil.which("docker"):
        return {"installed": False, "running": False, "containers": [], "error": ""}
    code, out, err = _capture(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=8)
    if code != 0:
        # Daemon stopped or user not in docker group
        return {"installed": True, "running": False, "containers": [], "error": (err or out).strip()[:200]}
    containers = []
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        state = str(obj.get("State") or "").lower()
        containers.append({
            "id": str(obj.get("ID") or ""),
            "name": str(obj.get("Names") or ""),
            "image": str(obj.get("Image") or ""),
            "state": state,
            "status": str(obj.get("Status") or ""),
            "ports": str(obj.get("Ports") or ""),
        })
    containers.sort(key=lambda c: (c["state"] != "running", c["name"].casefold()))
    return {"installed": True, "running": True, "containers": containers, "error": ""}


def control_container(name: str, action: str) -> str:
    if action not in ("start", "stop", "restart"):
        raise ValueError(tr("Unsupported container action", "不支持的容器操作"))
    if not _CONTAINER_RE.fullmatch(name):
        raise ValueError(tr("Invalid container identifier", "无效的容器名称"))
    code, out, err = _capture(["docker", action, name], timeout=25)
    if code != 0:
        raise RuntimeError((err or out).strip() or tr("Docker action failed", "Docker 操作失败"))
    return out.strip()


def start_docker_daemon() -> str:
    return polkit_helper.systemctl_system("start", "docker.service")
