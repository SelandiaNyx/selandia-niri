#!/usr/bin/env python3
"""Run a short nested desktop smoke test on a private D-Bus, never on the host display.

Usage: python3 tools/smoke.py (always starts an owned private session bus)
Output: .validation/{niri,eww,notifications,wallpaper,terminal,anyrun}.log
"""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import select
import signal
import shutil
import sys
import tempfile
import threading
import time
from unittest.mock import patch

# Individual daemon calls use 3–12s deadlines. Full UI probes need 20–180s
# for mapping/animation/screenshots; review needs 330s for three real 60s
# playlist intervals. See docs/MAINTENANCE.md for the explicit budget table.
ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / ".validation"
sys.path.insert(0, str(ROOT / "niri/shell"))
import lock_session
import session_identity


def prepare_preview(root, temporary, environment):
    """Give every component its own source/config tree, including generated CSS.

    Merely isolating state is insufficient: theme generation writes beside its script.
    Seed only appearance/language preferences, never account data or undo journals.
    """
    temporary = Path(temporary)
    config = temporary / "config"
    base = config / "niri"
    shutil.copytree(Path(root) / "niri", base, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    state = Path(environment.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri"
    target = temporary / "selandia-niri"
    target.mkdir()
    for name in ("appearance.json", "language.json"):
        source = state / name
        if source.is_file() and not source.is_symlink():
            shutil.copy2(source, target / name)
    env = dict(environment, XDG_CONFIG_HOME=str(config), XDG_STATE_HOME=str(temporary),
               XDG_CACHE_HOME=str(temporary / "cache"),
               GSETTINGS_BACKEND="memory", PYTHONDONTWRITEBYTECODE="1")
    runtime = temporary / "runtime"
    runtime.mkdir(mode=0o700)
    display = environment.get("WAYLAND_DISPLAY")
    if display and not Path(display).is_absolute():
        outer_runtime = environment.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        env["WAYLAND_DISPLAY"] = str(Path(outer_runtime) / display)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["DBUS_SYSTEM_BUS_ADDRESS"] = "unix:path=" + str(runtime / "no-system-bus")
    return base, env


def position_preview(process, preview, environment, *, resize=False):
    """Keep only our still-owned /tmp compositor window visible on a Niri host.

    Host IPC is used only for positioning this child. All component operations
    and screenshots continue to use the private compositor and D-Bus.
    """
    preview = Path(preview)
    if (process.poll() is not None or preview.is_symlink() or
            not preview.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) or
            not preview.parent.parent.parent.name.startswith("selandia-smoke-") or
            preview.parts[-3:] != ("config", "niri", "preview.kdl") or
            process.args != ["niri", "--config", str(preview)]):
        return False
    socket = environment.get("SELANDIA_PROBE_HOST_SOCKET") or environment.get("NIRI_SOCKET")
    if not socket:
        return False
    host = dict(environment, NIRI_SOCKET=socket)
    try:
        result = subprocess.run(["niri", "msg", "--json", "windows"], env=host,
                                capture_output=True, text=True, check=True, timeout=3)
        windows = json.loads(result.stdout)
        if not isinstance(windows, list):
            return False
        window = next((item for item in windows if isinstance(item, dict) and item.get("pid") == process.pid), None)
        if not window:
            return False
        identifier = str(window["id"])
        actions = []
        if not window.get("is_floating"):
            actions.append(["toggle-window-floating", "--id", identifier])
        if resize:
            actions.extend([[f"set-window-{dimension}", "--id", identifier, value]
                            for dimension, value in (("width", "1600"), ("height", "1000"))])
        actions.append(["move-floating-window", "--id", identifier, "--x", "0", "--y", "0"])
        for action in actions:
            if process.poll() is not None:
                return False
            subprocess.run(["niri", "msg", "action", *action], env=host,
                           capture_output=True, check=True, timeout=3)
        return True
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    processes, handles = [], []
    expected_exits = set()
    locker_record = None
    visibility_stop = threading.Event()
    visibility_thread = None
    isolated_state = tempfile.TemporaryDirectory(prefix="selandia-smoke-")

    def start(name, command, env=None):
        out = (ARTIFACTS / f"{name}.log").open("w")
        handles.append(out)
        process = subprocess.Popen(command, env=env, stdout=out, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    try:
        # Own the bus even when the caller forgot dbus-run-session. Activation
        # environment updates and notifications must never reach the host bus.
        bus_path = Path(isolated_state.name) / "session-bus"
        address = "unix:path=" + str(bus_path)
        bus = start("dbus", ["dbus-daemon", "--session", "--nofork", "--address=" + address])
        deadline = time.monotonic() + 5
        while not bus_path.exists():
            if bus.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Private session bus did not become ready")
            time.sleep(.02)
        base, preview_env = prepare_preview(ROOT, isolated_state.name,
                                            dict(os.environ, DBUS_SESSION_BUS_ADDRESS=address))
        compositor = start("niri", ["niri", "--config", str(base / "preview.kdl")], preview_env)
        if os.environ.get("SELANDIA_PROBE_HOST_SOCKET") or os.environ.get("NIRI_SOCKET"):
            def visible():
                resized = False
                while not visibility_stop.is_set() and compositor.poll() is None:
                    resized = position_preview(compositor, base / "preview.kdl", os.environ, resize=not resized) or resized
                    visibility_stop.wait(1 if resized else .1)
            visibility_thread = threading.Thread(target=visible, name="private-preview-visibility", daemon=True)
            visibility_thread.start()
        runtime = Path(preview_env["XDG_RUNTIME_DIR"])
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
        env = dict(preview_env, NIRI_SOCKET=str(socket), WAYLAND_DISPLAY=display,
                   QT_QPA_PLATFORM="wayland", GDK_BACKEND="wayland",
                   XDG_CURRENT_DESKTOP="niri", NO_AT_BRIDGE="1", GTK_A11Y="none",
                   PYTHONDONTWRITEBYTECODE="1")
        env.pop("DISPLAY", None)
        # This command updates only the bus owned above.
        subprocess.run(["dbus-update-activation-environment", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP",
                        "NIRI_SOCKET", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "GSETTINGS_BACKEND"],
                       env=env, check=True, timeout=5)

        def msg(*args):
            return subprocess.check_output(["niri", "msg", *args], env=env, text=True, timeout=5)

        def panel_window_present(pid):
            """Settings windows are ordinary windows, not layer-shell surfaces."""
            try:
                windows = json.loads(msg("--json", "windows"))
            except (subprocess.SubprocessError, ValueError):
                return False
            return any(isinstance(item, dict) and item.get("pid") == pid for item in windows)

        def verify_lock():
            nonlocal locker_record
            identity = str((runtime / display).resolve())
            key = hashlib.sha256(identity.encode()).hexdigest()[:20]
            record_path = runtime / f"selandia-lock-{key}.json"
            command = ["python3", "-B", str(base / "shell/lock_session.py")]
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

        if sys.argv[1:] == ["--maximize-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/maximize_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=120)
            return

        if sys.argv[1:] == ["--panel-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/panel_probe.py")],
                           env=env, check=True, timeout=75)
            return
        if sys.argv[1:] == ["--daily-logic-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/daily_logic_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=75)
            return
        if sys.argv[1:] == ["--daily-ui-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/daily_ui_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=170)
            return
        if sys.argv[1:] == ["--event-feeds-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/event_feeds_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=45)
            return
        if sys.argv[1:] == ["--notification-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/notification_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=60)
            return
        if sys.argv[1:] == ["--calendar-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/calendar_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=45)
            return
        if sys.argv[1:] == ["--popup-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/popup_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=60)
            return

        if sys.argv[1:] == ["--power-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/power_menu_probe.py"), str(ARTIFACTS)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=30)
            return

        if sys.argv[1:] == ["--font-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/font_dialog_probe.py"),
                            str(ARTIFACTS / "font-dialog.png")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=20)
            return

        if sys.argv[1:] == ["--wallpaper-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/wallpaper_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=30)
            return

        if sys.argv[1:] == ["--wallpaper-engine-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/wallpaper_engine_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=50)
            return

        if sys.argv[1:] == ["--rust-apps-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/rust_apps_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=180)
            return
        if sys.argv[1:] == ["--bar-island-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/bar_island_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=180)
            return

        if sys.argv[1:] == ["--playlist-controls-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/playlist_controls_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=120)
            return

        if sys.argv[1:] == ["--playlist-render-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/playlist_render_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=30)
            return

        if sys.argv[1:] == ["--visual-defects-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/visual_defects_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=180)
            return

        if sys.argv[1:] == ["--review-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/review_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=330)
            return

        if sys.argv[1:] == ["--wallpaper-audio-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/wallpaper_audio_probe.py")],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=150)
            return

        if sys.argv[1:] == ["--controls-layout-probe-only"]:
            subprocess.run(["python3", "-B", str(ROOT / "tools/controls_layout_probe.py"), str(compositor.pid)],
                           env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=60)
            return

        # Probe the real nested sockets against a supplied manager PID; never
        # query or change the host user's activation environment here.
        def manager(pid):
            return lambda *args, **kwargs: subprocess.CompletedProcess(
                args, 0, f"ActiveState=active\nMainPID={pid}\n", "")

        if not session_identity.owns_session(environment=env, run=manager(compositor.pid)):
            raise RuntimeError("Nested compositor socket credentials were not recognized")
        if session_identity.owns_session(environment=env, run=manager(compositor.pid + 1)):
            raise RuntimeError("Nested compositor accepted a different service PID")
        print("PASS session identity: real IPC/Wayland peer PID matches only the supplied compositor PID")

        for component in ("wallpaper", "notifications"):
            start(component, [str(base / "scripts/components"), component], env)
        subprocess.run(["gdbus", "wait", "--session", "--timeout", "10", "org.erikreider.swaync.cc"],
                       env=env, check=True, timeout=12)
        bar = start("eww", [str(base / "scripts/components"), "waybar"], env)
        start("terminal", ["alacritty", "--config-file", str(base / "theme/alacritty.toml"), "--title", "Niri · Preview", "--command", "sh", "-c",
                           "printf '\\n  SELANDIA / GLASS\\n\\n  Rust components\\n'; sleep 160"], env)
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
                # Niri posts a notification after every screenshot. Silence only
                # this private bus so later captures cannot contain its preview.
                subprocess.run(["swaync-client", "--skip-wait", "--dnd-on"], env=env,
                               timeout=5, check=True, stdout=subprocess.DEVNULL)
                subprocess.run(["swaync-client", "--skip-wait", "--close-panel"], env=env,
                               timeout=5, check=True, stdout=subprocess.DEVNULL)
                subprocess.run(["swaync-client", "--skip-wait", "--hide-all"], env=env,
                               timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["python3", "-B", str(base / "shell/island.py"), "dismiss"],
                               env=env, timeout=5, check=True, stdout=subprocess.DEVNULL)
                time.sleep(.4)
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
        # --hide-all dismisses popups, not the centre's layer surface. Close it
        # explicitly so it cannot cover the launcher or native font chooser.
        subprocess.run(["swaync-client", "--skip-wait", "--close-panel"], env=env,
                       check=True, timeout=5, stdout=subprocess.DEVNULL)
        subprocess.run(["swaync-client", "--skip-wait", "--hide-all"], env=env, check=False, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # The overview keeps its own name: the "desktop" settings page below must
        # not overwrite the evidence for the desktop itself.
        screenshot("desktop-overview.png")
        launcher = start("anyrun", ["anyrun", "--config-dir", str(base / "anyrun")], env)
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
        from navigation_catalog import PAGE_KEYS
        setting_modes = tuple('control' if page == 'quick' else page for page in PAGE_KEYS)
        for mode in (*setting_modes, "shortcuts", "ai", "calendar"):
            # Every settings page opens as the same ordinary Control Center
            # window; only shortcuts/AI/calendar are layer-shell surfaces.
            normal = mode in setting_modes
            command = ["python3", "-B", str(base / "shell/panel.py"), mode]
            panel = start('notifications-settings' if mode == 'notifications' else mode, command, env)
            for _ in range(80):
                if panel.poll() is not None:
                    raise RuntimeError(f"{mode} panel exited; see its log")
                if (panel_window_present(panel.pid) if normal
                        else f"selandia-{mode}" in msg("layers")):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError(f"{mode} window did not appear")
            # CPU/network need a second sample before showing a real rate.
            time.sleep(3 if mode == "system" else 1)
            screenshot('notifications-settings.png' if mode == 'notifications' else f"{mode}.png")
            if mode == "shortcuts":
                # Exercise the live search path when the Wayland test input tool exists.
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
            if normal:
                for _ in range(40):
                    if not panel_window_present(panel.pid):
                        break
                    time.sleep(.05)
                else:
                    raise RuntimeError(f"{mode} window remained after closing")
            elif f"selandia-{mode}" in msg("layers"):
                raise RuntimeError(f"{mode} panel layer remained after closing")
        # The power submenu is a native surface now. The probe captures the action
        # list, the confirmation and the Stay-awake annotation, so a regression
        # back to a dmenu (with its search field) is visible in the artifacts.
        subprocess.run(["python3", "-B", str(ROOT / "tools/power_menu_probe.py"), str(ARTIFACTS)],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=30)
        media_service.terminate()
        media_service.wait(timeout=5)
        expected_exits.add(media_service.pid)
        subprocess.run(["python3", "-B", str(ROOT / "tools/media_probe.py")],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=20)
        if (ROOT / "tools/panel_probe.py").exists():
            subprocess.run(["python3", "-B", str(ROOT / "tools/panel_probe.py")],
                           env=env, check=True, timeout=75)
        subprocess.run(["python3", "-B", str(ROOT / "tools/font_dialog_probe.py"),
                        str(ARTIFACTS / "font-dialog.png")],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=20)
        subprocess.run(["python3", "-B", str(ROOT / "tools/display_probe.py")],
                       env=dict(env, SELANDIA_PRIVATE_PROBE="1"), check=True, timeout=30)
        import reload_components
        restart_number = 0
        def private_manager(arguments, *, timeout=5):
            nonlocal bar, restart_number
            if arguments[:2] == ["systemctl", "--user"]:
                if arguments[-1] not in ("selandia-niri@waybar.service", "selandia-niri@notifications.service"):
                    raise RuntimeError("Smoke refuses an unrelated unit")
                if "show" in arguments:
                    if "--property=UnitFileState" in arguments:
                        return "static"
                    return "active" if bar.poll() is None else "failed"
                if arguments[-1] != "selandia-niri@waybar.service":
                    raise RuntimeError("Smoke refuses notification service mutation")
                if "reset-failed" in arguments:
                    return ""
                if "restart" not in arguments:
                    raise RuntimeError("Smoke refuses a signal reload")
                previous = bar
                previous.terminate()
                previous.wait(timeout=5)
                expected_exits.add(previous.pid)
                restart_number += 1
                name = f"eww-restart-{restart_number}"
                bar = start(name, [str(base / "scripts/components"), "waybar"], env)
                for _ in range(130):
                    if bar.poll() is not None:
                        raise RuntimeError("Eww exited during managed restart")
                    info = Path(env['XDG_RUNTIME_DIR'])/'selandia-eww-runtime.json'
                    if info.exists() and json.loads(info.read_text()).get('ready'):
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError("Eww did not become ready after managed restart")
                if Path(f"/proc/{previous.pid}").exists():
                    raise RuntimeError("Previous private Eww was not reaped")
                return ""
            result = subprocess.run(arguments, env=env, capture_output=True, text=True, timeout=timeout)
            if result.returncode:
                raise RuntimeError(result.stderr or result.stdout)
            return result.stdout.strip()

        with patch.object(reload_components, "run", side_effect=private_manager):
            for _ in range(6):
                reload_components.reload_components(base=base)
                time.sleep(.3)
                for children in Path(f"/proc/{bar.pid}/task").glob("*/children"):
                    try:
                        pids = children.read_text().split()
                    except FileNotFoundError:
                        continue
                    for pid in pids:
                        try:
                            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                        except FileNotFoundError:
                            continue
                        if state == "Z":
                            raise RuntimeError("Eww has an unreaped child after managed restart")
        if "selandia-island" not in msg("layers"):
            raise RuntimeError("Eww disappeared after repeated theme reload")
        for process in processes:
            if process.pid not in expected_exits and process.poll() is not None:
                raise RuntimeError(f"Component stopped unexpectedly: {process.args}")
        # Verify the real locker acquires the nested session lock. No passwords are sent.
        verify_lock()
        print("PASS: Niri native glass theme, terminal, Eww, SwayNC, wallpaper, Anyrun, Control Center, shortcut library, AI sidebar, native power menu and Swaylock readiness; panel toggles, search, layout actions and screenshots.")
        print("Artifacts:", ARTIFACTS)
    finally:
        visibility_stop.set()
        if visibility_thread:
            visibility_thread.join(timeout=15)
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for handle in handles:
            handle.close()
        if locker_record and lock_session.confirmed(locker_record, locker_record["display"]):
            os.kill(locker_record["pid"], signal.SIGTERM)
        isolated_state.cleanup()


if __name__ == "__main__":
    main()
