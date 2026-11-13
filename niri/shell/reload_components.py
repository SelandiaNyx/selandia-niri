#!/usr/bin/env python3
"""Reload styling and let systemd own the bar's complete process lifecycle."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from appearance import BASE, _lock, preferences_path
from i18n import tr


def run(arguments: list[str], *, timeout: float = 5) -> str:
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                           or tr("Command failed: ", "命令失败：") + " ".join(arguments))
    return result.stdout.strip()


def service(component: str, *arguments: str) -> str:
    return run(["systemctl", "--user", *arguments, f"selandia-niri@{component}.service"])


def active(component: str) -> bool:
    return service(component, "show", "--property=ActiveState", "--value") == "active"


def masked(component: str) -> bool:
    return service(component, "show", "--property=UnitFileState", "--value") in ("masked", "masked-runtime")


def recover(component: str):
    # A manual recovery must clear start-limit-hit left by earlier releases.
    service(component, "reset-failed")
    service(component, "start")
    if not active(component):
        raise RuntimeError(f"{component}: " + tr("Service did not start", "服务未能启动"))


def validate_css(base: Path):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    for component in ("eww", "swaync"):
        path = base / "theme" / f"{component}.css"
        if not path.is_file():
            path = base / component / "style.css"
        provider = Gtk.CssProvider()
        provider.load_from_path(str(path))


def reload_components(*, full: bool = False, base: Path = BASE):
    # Use the writer's stable lock: a second Apply cannot replace half a theme
    # while CSS is checked or while a previous reload is still in progress.
    with _lock(preferences_path()):
        validate_css(base)
        failures = []
        try:
            if not masked("notifications"):
                if not active("notifications"):
                    recover("notifications")
                # No client call until the managed daemon owns its bus name. This
                # prevents D-Bus from activating a daemon with an unrelated config.
                run(["gdbus", "wait", "--session", "--timeout", "3", "org.erikreider.swaync.cc"])
                if full:
                    run(["swaync-client", "--skip-wait", "--reload-config"])
                run(["swaync-client", "--skip-wait", "--reload-css"])
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(tr("Notifications: ", "通知：") + str(error))
        try:
            if not masked("waybar"):
                if active("waybar"):
                    # Compatibility unit name: this service now runs only Eww.
                    # systemd owns and reaps its complete process group.
                    service("waybar", "reset-failed")
                    service("waybar", "restart")
                    if not active("waybar"):
                        raise RuntimeError("waybar: " + tr("Service did not start", "服务未能启动"))
                else:
                    recover("waybar")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            failures.append(tr("Status bar: ", "状态栏：") + str(error))
        if full:
            try:
                service("wallpaper", "reset-failed")
                service("wallpaper", "restart")
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                failures.append(tr("Wallpaper: ", "壁纸：") + str(error))
        if failures:
            raise RuntimeError("\n".join(failures))


def main() -> int:
    if sys.argv[1:] not in (["theme"], ["all"]):
        print(tr("Usage: ", "用法：") + "reload_components.py {theme|all}", file=sys.stderr)
        return 2
    try:
        reload_components(full=sys.argv[1] == "all")
    except Exception as error:
        print(tr("Reload failed: ", "重载失败：") + str(error), file=sys.stderr)
        return 1
    print(tr("Desktop reloaded", "桌面已重载"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
