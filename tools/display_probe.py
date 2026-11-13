#!/usr/bin/env python3
"""Exercise native output persistence on a disposable nested Niri compositor.

Run from tools/smoke.py with SELANDIA_PRIVATE_PROBE=1. Only the compositor
created here receives IPC changes. Configuration and state live in /tmp.
"""
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "niri/shell"))
import display_backend as backend


def until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Private display state did not converge")


def main():
    if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1":
        raise RuntimeError("Run this probe through the isolated desktop smoke test")
    if not os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("NIRI_SOCKET"):
        raise RuntimeError("The probe requires smoke.py's private Wayland session")
    original_socket = os.environ["NIRI_SOCKET"]
    with tempfile.TemporaryDirectory(prefix="selandia-display-probe-") as temporary:
        root = Path(temporary)
        base = root / "niri"
        state = root / "state"
        (base / "conf").mkdir(parents=True)
        target = base / backend.GENERATED
        target.write_text(backend.render_settings({}))
        config = base / "config.kdl"
        # There are no startup commands, hotkeys, service actions, or host files.
        config.write_text('include "conf/display-settings.kdl"\noutput "winit" { scale 1.0; }\n')
        log_path = ROOT / ".validation/display-probe.log"
        log_path.parent.mkdir(exist_ok=True)
        with log_path.open("w") as log:
            private_socket = None
            compositor = subprocess.Popen(["niri", "--config", str(config)],
                                          stdout=log, stderr=subprocess.STDOUT)
            try:
                runtime = Path(os.environ["XDG_RUNTIME_DIR"])
                sockets = []

                def ready():
                    nonlocal sockets
                    if compositor.poll() is not None:
                        raise AssertionError(f"Private Niri exited; see {log_path}")
                    sockets = list(runtime.glob(f"niri.*.{compositor.pid}.sock"))
                    return bool(sockets)

                until(ready, timeout=8)
                private_socket = str(sockets[0])
                if private_socket == original_socket:
                    raise AssertionError("Display test isolation failed")
                with patch.dict(os.environ, {"NIRI_SOCKET": private_socket,
                                             "XDG_STATE_HOME": str(state)}), \
                        patch.object(backend, "BASE", base):
                    outputs = backend.read_outputs()
                    if len(outputs) != 1 or outputs[0]["name"] != "winit":
                        raise AssertionError(f"Expected one private winit output, got {outputs}")
                    output = outputs[0]
                    current = output["current"]
                    if not current:
                        raise AssertionError("Private output is not active")

                    def values_for(scale):
                        # A scale change resizes the nested winit output, so the
                        # reported mode list/current mode can change between
                        # applies. Re-read it instead of reusing stale values.
                        current = backend.read_outputs()[0]["current"]
                        if not current:
                            raise AssertionError("Private output lost its active mode")
                        return {**current, "max_bpc": None, "vrr": False, "scale": scale}

                    def has_scale(scale):
                        actual = backend.read_outputs()[0]["current"]
                        return actual is not None and math.isclose(actual["scale"], scale, abs_tol=1 / 120)

                    token = backend.begin_apply(output["name"], values_for(1.25))
                    until(lambda: has_scale(1.25))
                    if not backend.confirm(token):
                        raise AssertionError("Private display preview could not be confirmed")
                    if backend.read_state()["saved"][output["name"]]["scale"] != 1.25:
                        raise AssertionError("Confirmed scale was not persisted")
                    confirmed_contents = target.read_text()
                    print("PASS display: actual Niri reload applies scale; confirmation persists it")

                    token = backend.begin_apply(output["name"], values_for(1.5))
                    until(lambda: has_scale(1.5))
                    if not backend.revert(token):
                        raise AssertionError("Private display preview could not be reverted")
                    until(lambda: has_scale(1.25))
                    if target.read_text() != confirmed_contents:
                        raise AssertionError("Revert did not restore the previous configuration")
                    print("PASS display: explicit revert restores actual scale and configuration")

                    # Use the real independent helper with a shorter test deadline.
                    # The product constant remains fifteen seconds.
                    with patch.object(backend, "CONFIRM_SECONDS", 1.5):
                        token = backend.begin_apply(output["name"], values_for(1.75))
                    until(lambda: has_scale(1.75), timeout=1)
                    until(lambda: has_scale(1.25), timeout=5)
                    until(lambda: not (backend._state_dir() / "pending.json").exists())
                    if backend.confirm(token) or target.read_text() != confirmed_contents:
                        raise AssertionError("Expired preview was retained")
                    print("PASS display: detached watchdog restores actual scale without panel callbacks")

                    # Reload from disk to prove the kept configuration survives later reloads.
                    backend._run("msg", "action", "load-config-file")
                    until(lambda: has_scale(1.25))
                    print("PASS display: confirmed scale survives a subsequent config reload")
            finally:
                if private_socket and private_socket != original_socket:
                    with patch.dict(os.environ, {"NIRI_SOCKET": private_socket,
                                                 "XDG_STATE_HOME": str(state)}), \
                            patch.object(backend, "BASE", base):
                        pending = backend._read_json(backend._state_dir() / "pending.json")
                        if pending:
                            try:
                                backend.revert(pending["token"])
                            except (OSError, RuntimeError):
                                pass
                compositor.terminate()
                try:
                    compositor.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    compositor.kill()
                    compositor.wait(timeout=2)


if __name__ == "__main__":
    main()
