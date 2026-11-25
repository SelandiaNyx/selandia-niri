#!/usr/bin/env python3
"""Reversible Niri-scoped suppression for redundant third-party tray applets.

Because Selandia Niri natively controls NetworkManager (top bar + Control Center)
and BlueZ (top bar + Control Center + native BlueZ Agent1 inside polkit_agent.py),
``blueman-applet`` (~127 MiB) and ``nm-applet`` (~52 MiB) are redundant inside
Niri.  We write reversible ``NotShowIn=niri;`` XDG autostart overrides recorded
through ``session_settings`` so other desktops (KDE/GNOME/etc.) remain untouched
and ``./control.sh uninstall`` restores everything cleanly.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_settings

REDUNDANT_AUTOSTART = {
    "blueman.desktop": (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Blueman Applet\n"
        "Exec=blueman-applet\n"
        "NotShowIn=niri;\n"
        "X-Selandia-Niri-Managed=true\n"
    ),
    "nm-applet.desktop": (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=NetworkManager Applet\n"
        "Exec=nm-applet\n"
        "NotShowIn=KDE;GNOME;niri;\n"
        "X-Selandia-Niri-Managed=true\n"
    ),
}


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).absolute()


def ensure(*, home: Path | None = None, state_path: Path | None = None) -> list[str]:
    """Install Niri-only autostart shadows for redundant tray applets."""
    root = Path(home or config_home()).absolute()
    desired = {}
    to_write: dict[Path, bytes] = {}
    for filename, content in REDUNDANT_AUTOSTART.items():
        rel = f"autostart/{filename}"
        target = root / rel
        payload = content.encode("utf-8")
        # Never overwrite an unrelated pre-existing custom user override.
        if target.exists() and not target.is_symlink():
            try:
                existing = target.read_text(errors="ignore")
            except OSError:
                continue
            if "X-Selandia-Niri-Managed=true" not in existing:
                continue
            if existing == content:
                continue
        elif target.is_symlink():
            continue
        import base64
        desired[rel] = {"bytes": base64.b64encode(payload).decode(), "mode": 0o644}
        to_write[target] = payload

    if not desired:
        return []

    written: list[str] = []
    try:
        with session_settings.record_changes(root, desired, state_path=state_path):
            for target, payload in to_write.items():
                session_settings.write_value(
                    target,
                    {"bytes": __import__("base64").b64encode(payload).decode(), "mode": 0o644},
                )
                written.append(target.name)
    except RuntimeError:
        # Respect user edits if session_settings detects manual modification.
        return []
    return written


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["ensure"]):
        print("Usage: session_cleanup.py [ensure]", file=sys.stderr)
        return 2
    ensure()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
