"""Two-layer eye-care night light controller (theme warmth + Wayland gamma)."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from i18n import tr

DEFAULTS = {
    "enabled": False,
    "kelvin": 4200,
    "schedule": False,
    "start_hour": 21,
    "end_hour": 7,
}
GAMMA_BACKENDS = ("wlsunset", "gammastep", "hyprsunset")


def state_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/night-light.json"


def detect_backend() -> str | None:
    for binary in GAMMA_BACKENDS:
        if shutil.which(binary):
            return binary
    return None


def validate(data: dict) -> dict:
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        if isinstance(data.get("enabled"), bool):
            out["enabled"] = data["enabled"]
        try:
            out["kelvin"] = max(2700, min(6500, int(round(float(data.get("kelvin", out["kelvin"]))))))
        except (TypeError, ValueError):
            pass
        if isinstance(data.get("schedule"), bool):
            out["schedule"] = data["schedule"]
        for key in ("start_hour", "end_hour"):
            try:
                out[key] = max(0, min(23, int(data.get(key, out[key]))))
            except (TypeError, ValueError):
                pass
    return out


def load_settings(*, path: Path | None = None) -> dict:
    target = Path(path or state_path())
    try:
        return validate(json.loads(target.read_text()))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def save_settings(data: dict, *, path: Path | None = None) -> dict:
    values = validate(data)
    target = Path(path or state_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(values, indent=2) + "\n")
    os.replace(tmp, target)
    return values


def _stop_gamma() -> None:
    for name in GAMMA_BACKENDS:
        if shutil.which("pkill"):
            subprocess.run(["pkill", "-x", name], capture_output=True, timeout=3)


def apply_gamma(settings: dict) -> tuple[bool, str]:
    """Start or stop a detected Wayland gamma daemon; returns (hardware_active, message)."""
    values = validate(settings)
    backend = detect_backend()
    _stop_gamma()
    if not values["enabled"]:
        return False, tr("Hardware night light off", "硬件色温夜览已关闭")
    if backend is None:
        cmd = "pacman -S wlsunset"
        return False, tr(
            f"Install wlsunset ({cmd}) for screen-wide hardware Kelvin control; theme eye-care warmth is active.",
            f"安装 wlsunset（{cmd}）即可开启全屏硬件色温调节；主题护眼暖光已生效。",
        )
    kelvin = str(values["kelvin"])
    if backend == "wlsunset":
        argv = ["wlsunset", "-T", "6500", "-t", kelvin]
        if not values["schedule"]:
            argv = ["wlsunset", "-T", str(min(6500, values["kelvin"] + 1)), "-t", kelvin]
    elif backend == "gammastep":
        argv = ["gammastep", "-O", kelvin]
    else:
        argv = ["hyprsunset", "-t", kelvin]
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, tr(f"Active via {backend} ({kelvin}K)", f"已通过 {backend} 生效（{kelvin}K）")
