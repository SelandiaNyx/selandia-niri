"""Only the compositor owned by niri.service may export session environment."""
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys


def peer(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(path))
        return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))


def owns_session(*, environment=None, run=subprocess.run, credentials=peer):
    environment = os.environ if environment is None else environment
    ipc, display, runtime = (environment.get(key) for key in ("NIRI_SOCKET", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"))
    if not ipc or not display or not runtime or not Path(ipc).is_absolute() or not Path(runtime).is_absolute():
        return False
    try:
        result = run(["systemctl", "--user", "show", "niri.service", "--property=ActiveState,MainPID"],
                     capture_output=True, text=True, timeout=3)
        if result.returncode:
            return False
        unit = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        pid = int(unit.get("MainPID", "0"))
        if unit.get("ActiveState") not in ("active", "activating") or pid <= 0:
            return False
        wayland = Path(display) if Path(display).is_absolute() else Path(runtime) / display
        return all(owner == pid and uid == os.getuid() for owner, uid, _gid in
                   (credentials(ipc), credentials(wayland)))
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


if __name__ == "__main__":
    sys.exit(0 if owns_session() else 1)
