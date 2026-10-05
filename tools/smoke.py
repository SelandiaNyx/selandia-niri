#!/usr/bin/env python3
"""Run a short nested desktop smoke test on a private D-Bus, never on the host display.

Usage: dbus-run-session -- python3 tools/smoke.py
Output: .validation/{niri,waybar,notifications,wallpaper,terminal,fuzzel}.log
"""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import select
import signal
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".validation"
sys.path.insert(0, str(ROOT / "niri/shell"))
import lock_session


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    processes, handles = [], []
    expected_exits = set()
    locker_record = None
    isolated_state = tempfile.TemporaryDirectory(prefix="selandia-smoke-")

    def start(name, command, env=None):
        out = (ARTIFACTS / f"{name}.log").open("w")
        handles.append(out)
        process = subprocess.Popen(command, env=env, stdout=out, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    try:
        compositor = start("niri", ["niri", "--config", str(ROOT / "niri/preview.kdl")])
        # On a Niri host, resize only the new test window, identified by its PID.
        # This makes screenshots useful on scrollable layouts without touching user windows.
        if os.environ.get("NIRI_SOCKET"):
            for _ in range(40):
                try:
                    host_windows = json.loads(subprocess.check_output(
                        ["niri", "msg", "--json", "windows"], text=True, timeout=3))
                    window = next((item for item in host_windows if item.get("pid") == compositor.pid), None)
                    if window:
                        wid = str(window["id"])
                        if not window.get("is_floating"):
                            subprocess.run(["niri", "msg", "action", "toggle-window-floating", "--id", wid], check=True, timeout=3, stdout=subprocess.DEVNULL)
                        for dimension, value in (("width", "1600"), ("height", "1000")):
                            subprocess.run(["niri", "msg", "action", f"set-window-{dimension}", "--id", wid, value], check=True, timeout=3, stdout=subprocess.DEVNULL)
                        break
                except (subprocess.SubprocessError, ValueError, OSError):
                    break
                time.sleep(.1)
        runtime = Path(os.environ["XDG_RUNTIME_DIR"])
        for _ in range(100):
            sockets = list(runtime.glob(f"niri.*.{compositor.pid}.sock"))
            if sockets:
                break
            if compositor.poll() is not None:
                raise RuntimeError("Niri 启动失败，请查看 .validation/niri.log")
            time.sleep(.1)
        else:
            raise RuntimeError("等待 Niri IPC 超时")
        socket = sockets[0]
        display = socket.name[len("niri."):].rsplit(".", 2)[0]
        env = dict(os.environ, NIRI_SOCKET=str(socket), WAYLAND_DISPLAY=display,
                   QT_QPA_PLATFORM="wayland", GDK_BACKEND="wayland",
                   XDG_CURRENT_DESKTOP="niri", NO_AT_BRIDGE="1", GTK_A11Y="none",
                   XDG_STATE_HOME=isolated_state.name, PYTHONDONTWRITEBYTECODE="1")
        env.pop("DISPLAY", None)
        # This command updates only the private dbus-run-session bus.
        subprocess.run(["dbus-update-activation-environment", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"],
                       env=env, check=True, timeout=5)

        def msg(*args):
            return subprocess.check_output(["niri", "msg", *args], env=env, text=True, timeout=5)

        def verify_lock():
            nonlocal locker_record
            identity = str((runtime / display).resolve())
            key = hashlib.sha256(identity.encode()).hexdigest()[:20]
            record_path = runtime / f"selandia-lock-{key}.json"
            command = ["python3", "-B", str(ROOT / "niri/shell/lock_session.py")]
            subprocess.run(command, env=env, check=True, timeout=15)
            locker_record = json.loads(record_path.read_text())
            if not lock_session.confirmed(locker_record, identity):
                raise RuntimeError("Current preview lock identity was not confirmed")
            subprocess.run(command, env=env, check=True, timeout=5)
            if json.loads(record_path.read_text()) != locker_record:
                raise RuntimeError("Repeated locking did not reuse the confirmed preview lock")
            print("PASS lock: real Wayland readiness, correct display and PID identity, repeated lock reuses confirmed client")

        if sys.argv[1:] == ["--lock-probe-only"]:
            verify_lock()
            return

        if sys.argv[1:] == ["--panel-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/panel_probe.py")],
                           env=env, check=True, timeout=30)
            return

        if sys.argv[1:] == ["--font-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/font_dialog_probe.py"),
                            str(ARTIFACTS / "font-dialog.png")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=20)
            return

        for component in ("wallpaper", "notifications"):
            start(component, [str(ROOT / "niri/scripts/components"), component], env)
        subprocess.run(["gdbus", "wait", "--session", "--timeout", "10", "org.erikreider.swaync.cc"],
                       env=env, check=True, timeout=12)
        waybar = start("waybar", [str(ROOT / "niri/scripts/components"), "waybar"], env)
        start("terminal", ["kitty", "--config", str(ROOT / "niri/kitty/kitty.conf"), "--title", "Niri · Preview", "sh", "-c",
                           "printf '\\n  SELANDIA / GLASS\\n\\n  A little clarity. A little atmosphere.\\n\\n  Super + Space   Applications\\n  Super + /       Shortcut library\\n  Super + I       Control Center\\n  Super + A       AI sidebar\\n'; sleep 120"], env)
        time.sleep(2)
        windows = json.loads(msg("--json", "windows"))
        if not windows:
            raise RuntimeError("终端未在嵌套 Niri 中出现")
        msg("action", "switch-preset-column-width")
        msg("action", "toggle-window-floating")
        msg("action", "toggle-window-floating")
        subprocess.run(["notify-send", "Niri 已就绪", "通知、状态栏与窗口布局运行测试"], env=env, check=True, timeout=5)
        # Only this private session's notification daemon receives the request.
        subprocess.run(["swaync-client", "-t"], env=env, check=True, timeout=5)
        time.sleep(1)
        def screenshot(name, *, hide_notifications=True):
            if hide_notifications:
                subprocess.run(["swaync-client", "--skip-wait", "--hide-all"], env=env,
                               timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(.2)
            path = ARTIFACTS / name
            previous = path.stat().st_mtime_ns if path.exists() else None
            msg("action", "screenshot-screen", "--path", str(path), "--show-pointer", "false")
            for _ in range(50):
                if path.exists() and path.stat().st_mtime_ns != previous and path.stat().st_size:
                    return
                time.sleep(.1)
            raise RuntimeError(f"截图未写入：{path}")

        # The notification centre is captured FIRST, with the panel the step
        # above just opened still visible: --hide-all dismisses the cards, so a
        # capture taken after it cannot show the thing being verified. It keeps a
        # unique name that no settings page overwrites.
        screenshot("notifications-center.png", hide_notifications=False)
        subprocess.run(["swaync-client", "--skip-wait", "--hide-all"], env=env, check=False, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The overview keeps its own name: the "desktop" settings page below must
        # not overwrite the evidence for the desktop itself.
        screenshot("desktop-overview.png")
        launcher = start("fuzzel", ["fuzzel", "--config", str(ROOT / "niri/theme/fuzzel.ini")], env)
        time.sleep(1)
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(f"测试进程提前退出（{process.args}），查看对应日志")
        screenshot("launcher.png")
        launcher.terminate()
        launcher.wait(timeout=5)
        expected_exits.add(launcher.pid)
        media_service = start("media-fixture", ["python3", "-B", str(ROOT / "tools/media_probe.py"), "--serve"],
                              dict(env, SELANDIA_PRIVATE_PROBE="1"))
        subprocess.run(["gdbus", "wait", "--session", "--timeout", "5", "org.mpris.MediaPlayer2.SelandiaTest"],
                       env=env, check=True, timeout=7)
        setting_modes = ("control", "sound", "displays", "input", "network", "hardware",
                         "appearance", "desktop", "applications", "language", "power", "time",
                         "startup", "services", "security", "system")
        for mode in (*setting_modes, "shortcuts", "ai"):
            layer = "control" if mode in setting_modes else mode
            command = ["python3", "-B", str(ROOT / "niri/shell/panel.py"), mode]
            panel = start(mode, command, env)
            for _ in range(80):
                if panel.poll() is not None:
                    raise RuntimeError(f"{mode} panel exited; see its log")
                if f"selandia-{layer}" in msg("layers"):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError(f"{mode} layer did not appear")
            # CPU/network need a second sample before showing a real rate.
            time.sleep(3 if mode == "system" else 1)
            screenshot(f"{mode}.png")
            if mode == "shortcuts":
                # Exercise the live search path when the Wayland test input tool exists.
                import shutil
                if shutil.which("wtype"):
                    subprocess.run(["wtype", "workspace"], env=env, check=True, timeout=5)
                    time.sleep(.4)
                    screenshot("shortcuts-search.png")
            subprocess.run(command, env=env, check=True, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            panel.wait(timeout=5)
            if panel.returncode != 0:
                raise RuntimeError(f"{mode} panel toggle failed")
            expected_exits.add(panel.pid)
            if f"selandia-{layer}" in msg("layers"):
                raise RuntimeError(f"{mode} panel layer remained after closing")
        media_service.terminate()
        media_service.wait(timeout=5)
        expected_exits.add(media_service.pid)
        subprocess.run(["python3", "-B", str(ROOT / "tools/media_probe.py")],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=20)
        if (ROOT / "tools/panel_probe.py").exists():
            subprocess.run(["python3", "-B", str(ROOT / "tools/panel_probe.py")],
                           env=env, check=True, timeout=30)
        subprocess.run(["python3", "-B", str(ROOT / "tools/font_dialog_probe.py"),
                        str(ARTIFACTS / "font-dialog.png")],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=20)
        subprocess.run(["python3", "-B", str(ROOT / "tools/display_probe.py")],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=30)
        for _ in range(6):
            waybar.send_signal(signal.SIGUSR2)
            subprocess.run(["swaync-client", "--skip-wait", "--reload-css"],
                           env=env, check=True, timeout=5, stdout=subprocess.DEVNULL)
            time.sleep(.3)
            if waybar.poll() is not None:
                raise RuntimeError("Waybar exited during repeated theme reload")
        if "waybar" not in msg("layers"):
            raise RuntimeError("Waybar disappeared after repeated theme reload")
        # Attribute the log instead of filtering it: a finding that names this
        # project fails the run, upstream noise is recorded with its context.
        import bar_log
        report = bar_log.analyse((ARTIFACTS / "waybar.log").read_text(errors="replace"))
        report["project_findings"] = bar_log.project_findings(report)
        (ARTIFACTS / "waybar-log-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        if report["project_findings"]:
            raise RuntimeError("Waybar log names this project: "
                               + json.dumps(report["project_findings"][:3], ensure_ascii=False))
        if report["findings"]:
            print("WARN: bar log has " + str(len(report["findings"])) + " finding(s) not attributable to this "
                  "project; context recorded in waybar-log-report.json")
        # The right-hand end must keep the control-centre button and the network
        # module must have a bounded width, whatever layout was selected.
        configuration = json.loads((ROOT / "niri/theme/waybar.jsonc").read_text())
        modules = configuration["modules-left"] + configuration["modules-right"]
        if modules[-1] != "custom/control":
            raise RuntimeError("status bar does not end with the control-centre button: " + repr(modules[-3:]))
        if not configuration["network"].get("min-length"):
            raise RuntimeError("network rate width is not bounded; sampling can push modules off the bar")
        print("PASS: six consecutive Waybar and notification CSS reloads; bar remains visible, "
              "log attributed and right-hand layout bounded")
        for process in processes:
            if process.pid not in expected_exits and process.poll() is not None:
                raise RuntimeError(f"Component stopped unexpectedly: {process.args}")
        # Verify the real locker acquires the nested session lock. No passwords are sent.
        verify_lock()
        print("PASS: Niri native glass theme, terminal, Waybar, SwayNC, wallpaper, Fuzzel, Control Center, shortcut library, AI sidebar and Swaylock readiness; panel toggles, search, layout actions and screenshots.")
        print("Artifacts:", ARTIFACTS)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()
        if locker_record and lock_session.confirmed(locker_record, locker_record["display"]):
            os.kill(locker_record["pid"], signal.SIGTERM)
        isolated_state.cleanup()


if __name__ == "__main__":
    main()
