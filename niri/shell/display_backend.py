#!/usr/bin/env python3
"""Native Niri outputs with validated persistence and a detached rollback timer.

Niri uses the FIRST matching output block. The generated include must precede
the user's output files; those files are never rewritten by this module.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

BASE = Path(__file__).resolve().parent.parent
CONFIRM_SECONDS = 15
GENERATED = Path("conf/display-settings.kdl")
HEADER = "// Managed by the native display panel. Edit monitor.kdl for manual defaults.\n// 原生屏幕面板管理；手动默认配置保留在 monitor.kdl。\n\n"
TRANSFORMS = ("normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270")
DEPTHS = (6, 8, 10, 12, 14, 16)


def _state_dir():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/display"


def _run(*arguments):
    try:
        result = subprocess.run(["niri", *arguments], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Niri unavailable · 无法连接 Niri: {error}") from error
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-1500:] or "Niri command failed · Niri 操作失败")
    return result.stdout


def _name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", name):
        raise ValueError("Invalid output connector · 屏幕接口名称无效")
    return name


def _mode(width, height, refresh):
    return f"{width}x{height}@{refresh / 1000:.3f}".rstrip("0").rstrip(".")


def _transform(value):
    aliases = {"Normal": "normal", "90": "90", "180": "180", "270": "270",
               "Flipped": "flipped", "Flipped90": "flipped-90", "Flipped180": "flipped-180", "Flipped270": "flipped-270"}
    return aliases.get(value, value if value in TRANSFORMS else "normal")


def read_outputs():
    """Return live capabilities, not settings inferred from configuration files."""
    try:
        raw = json.loads(_run("msg", "--json", "outputs"))
        if not isinstance(raw, dict):
            raise ValueError("expected an object")
        outputs = []
        for item in raw.values():
            name = _name(item["name"])
            modes, seen = [], set()
            for candidate in item.get("modes", []):
                width, height, refresh = (candidate[key] for key in ("width", "height", "refresh_rate"))
                if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in (width, height, refresh)):
                    raise ValueError("invalid mode")
                mode = _mode(width, height, refresh)
                if mode not in seen:
                    modes.append({"mode": mode, "width": width, "height": height,
                                  "refresh_rate": refresh, "is_preferred": bool(candidate.get("is_preferred"))})
                    seen.add(mode)
            index = item.get("current_mode")
            current = None
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(item.get("modes", [])):
                active = item["modes"][index]
                logical = item.get("logical") or {}
                current = {"mode": _mode(active["width"], active["height"], active["refresh_rate"]),
                           "scale": logical.get("scale", 1.0), "max_bpc": item.get("max_bpc"),
                           "transform": _transform(logical.get("transform", "normal")),
                           "x": logical.get("x", 0), "y": logical.get("y", 0), "vrr": bool(item.get("vrr_enabled"))}
            outputs.append({"name": name, "description": " ".join(str(item.get(key) or "") for key in ("make", "model")).strip() or name,
                            "modes": modes, "current": current, "vrr_supported": bool(item.get("vrr_supported"))})
        return sorted(outputs, key=lambda output: output["name"])
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise RuntimeError("Invalid Niri output response · Niri 屏幕信息无效") from error


def validate_settings(values):
    keys = {"mode", "scale", "max_bpc", "transform", "x", "y", "vrr"}
    if not isinstance(values, dict) or set(values) != keys:
        raise ValueError("Incomplete display settings · 屏幕设置不完整")
    result = dict(values)
    mode = values["mode"]
    match = re.fullmatch(r"([0-9]{2,5})[xX*×]([0-9]{2,5})(?:@([0-9]{1,4}(?:\.[0-9]{1,3})?)(?:Hz)?)?", mode.strip(), re.I) if isinstance(mode, str) else None
    if not match:
        raise ValueError("Use WIDTHxHEIGHT@Hz, e.g. 1920x1080@60 · 格式为 1920x1080@60")
    width, height = int(match[1]), int(match[2])
    refresh = float(match[3]) if match[3] else None
    if not 320 <= width <= 32768 or not 200 <= height <= 32768 or (refresh is not None and not 1 <= refresh <= 1000):
        raise ValueError("Display mode is outside supported limits · 分辨率或刷新率超出范围")
    result["mode"] = f"{width}x{height}" + (f"@{refresh:.3f}".rstrip("0").rstrip(".") if refresh is not None else "")
    scale = values["scale"]
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not 0.5 <= scale <= 4:
        raise ValueError("Scale must be 50–400% · 缩放范围为 50–400%")
    result["scale"] = round(float(scale), 3)
    depth = values["max_bpc"]
    if depth is not None and (not isinstance(depth, int) or isinstance(depth, bool) or depth not in DEPTHS):
        raise ValueError("Maximum BPC must be Auto, 6, 8, 10, 12, 14 or 16 · 最大位深无效")
    if values["transform"] not in TRANSFORMS or not isinstance(values["vrr"], bool):
        raise ValueError("Invalid rotation or VRR · 旋转或可变刷新率设置无效")
    for key in ("x", "y"):
        if isinstance(values[key], bool) or not isinstance(values[key], int) or not -65536 <= values[key] <= 65536:
            raise ValueError("Position must be an integer from −65536 to 65536 · 屏幕位置超出范围")
    return result


def render_settings(outputs):
    lines = [HEADER]
    for name in sorted(outputs):
        _name(name)
        values = validate_settings(outputs[name])
        lines.extend([f'output "{name}" {{', f'    mode "{values["mode"]}"',
                      f'    scale {values["scale"]:g}', f'    transform "{values["transform"]}"',
                      f'    position x={values["x"]} y={values["y"]}'])
        if values["max_bpc"] is not None:
            lines.append(f'    max-bpc {values["max_bpc"]}')
        if values["vrr"]:
            lines.append("    variable-refresh-rate")
        lines.extend(["}", ""])
    return "\n".join(lines)


def _read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as error:
        raise RuntimeError(f"Cannot read display state · 无法读取屏幕设置: {path}") from error


def _saved():
    data = _read_json(_state_dir() / "settings.json", {"version": 1, "outputs": {}})
    try:
        if data["version"] != 1 or not isinstance(data["outputs"], dict):
            raise ValueError("version")
        return {_name(name): validate_settings(values) for name, values in data["outputs"].items()}
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Invalid saved display settings · 已保存的屏幕设置无效") from error


def max_bpc_supported():
    """Probe the installed parser; Niri 26.04 does not yet accept max-bpc."""
    with tempfile.TemporaryDirectory(prefix="selandia-bpc-") as temporary:
        config = Path(temporary) / "config.kdl"
        config.write_text('output "probe" { max-bpc 10; }\n')
        try:
            _run("validate", "--config", str(config))
            return True
        except RuntimeError:
            return False


def read_state():
    pending = _read_json(_state_dir() / "pending.json")
    return {"outputs": read_outputs(), "saved": _saved(),
            "pending": ({key: pending[key] for key in ("token", "deadline", "output")} if pending else None),
            "max_bpc_supported": max_bpc_supported()}


def _atomic(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"Refusing a replaced settings path · 设置路径已被替换: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _write_json(path, value):
    _atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def _lock():
    directory = _state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest() if text is not None else None


def _contents(path):
    if path.is_symlink():
        raise RuntimeError(f"Refusing a replaced settings path · 设置路径已被替换: {path}")
    try:
        return path.read_text()
    except FileNotFoundError:
        return None


def _validate_config(contents):
    main = (BASE / "config.kdl").read_text()
    includes = re.findall(r'^\s*include\s+"([^"]+)"', main, re.M)
    if not includes or includes[0] != str(GENERATED):
        raise RuntimeError("Display include must be first in config.kdl · 屏幕设置必须置于配置首个 include")
    with tempfile.TemporaryDirectory(prefix="selandia-display-validate-") as temporary:
        staged = Path(temporary) / "niri"
        shutil.copytree(BASE, staged, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        (staged / GENERATED).write_text(contents)
        _run("validate", "--config", str(staged / "config.kdl"))


def _spawn_watchdog(token):
    reader, writer = os.pipe()
    try:
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "_watch", token,
                                    str(BASE), str(_state_dir()), str(writer)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   pass_fds=(writer,), start_new_session=True, close_fds=True)
        os.close(writer)
        writer = -1
        ready, _, _ = select.select([reader], [], [], 3)
        if not ready or os.read(reader, 1) != b"1":
            process.terminate()
            raise RuntimeError("Rollback timer did not start · 自动恢复计时器未能启动")
    finally:
        os.close(reader)
        if writer >= 0:
            os.close(writer)


def _restore_runtime(transaction):
    """Restore any pre-existing temporary IPC settings, too, in the same session."""
    if transaction.get("socket") != os.environ.get("NIRI_SOCKET"):
        return
    previous = transaction["previous_runtime"]
    name = transaction["output"]
    try:
        _run("msg", "action", "load-config-file")
    except RuntimeError:
        pass
    commands = [("mode", previous["mode"]), ("scale", str(previous["scale"])),
                ("transform", previous["transform"]),
                ("position", "set", "--", str(previous["x"]), str(previous["y"])),
                ("vrr", "on" if previous["vrr"] else "off")]
    if previous.get("max_bpc") in DEPTHS:
        commands.append(("max-bpc", str(previous["max_bpc"])))
    for arguments in commands:
        try:
            _run("msg", "output", name, *arguments)
        except RuntimeError:
            pass  # Restoring the original file still lets Niri reload its saved configuration.


def _rollback(transaction):
    target = BASE / GENERATED
    current = _contents(target)
    if _digest(current) == transaction["applied_hash"]:
        if transaction["previous_contents"] is None:
            # The include must remain readable during Niri's automatic reload.
            _atomic(target, render_settings({}))
        else:
            _atomic(target, transaction["previous_contents"])
        _restore_runtime(transaction)
    elif current != transaction["previous_contents"]:
        raise RuntimeError("Display file was edited during preview; edits preserved · 预览期间屏幕文件被手动修改，已保留改动")
    (_state_dir() / "pending.json").unlink(missing_ok=True)


def _finish_confirmation(transaction):
    _write_json(_state_dir() / "settings.json", {"version": 1, "outputs": transaction["new_settings"]})
    (_state_dir() / "pending.json").unlink(missing_ok=True)


def begin_apply(name, settings):
    """Apply for fifteen seconds, returning the token required to keep changes."""
    name = _name(name)
    settings = validate_settings(settings)
    outputs = {output["name"]: output for output in read_outputs()}
    if name not in outputs or outputs[name]["current"] is None:
        raise ValueError("Choose an active connected display · 请选择已连接且启用的屏幕")
    output = outputs[name]
    modes = output["modes"]
    if "@" not in settings["mode"]:
        matches = [mode for mode in modes if mode["mode"].split("@")[0] == settings["mode"]]
        if matches:
            settings["mode"] = max(matches, key=lambda mode: mode["refresh_rate"])["mode"]
    if settings["mode"] not in {mode["mode"] for mode in modes}:
        raise ValueError("This mode is not reported by the display; choose an exact listed refresh rate · 屏幕不支持该模式，请选择列表中的准确刷新率")
    if settings["vrr"] and not output["vrr_supported"]:
        raise ValueError("This display does not report VRR support · 此屏幕未报告可变刷新率支持")
    if settings["max_bpc"] is not None and not max_bpc_supported():
        raise ValueError("This Niri version does not support max-bpc; upgrade Niri first · 当前 Niri 不支持位深设置，需先升级 Niri")
    with _lock():
        pending = _read_json(_state_dir() / "pending.json")
        if pending:
            if pending.get("phase") == "confirmed":
                _finish_confirmation(pending)
            elif pending["deadline"] <= time.time():
                _rollback(pending)
            else:
                raise RuntimeError("Confirm or revert the previous preview first · 请先确认或恢复上一次屏幕预览")
        saved = _saved()
        previous = _contents(BASE / GENERATED)
        if previous not in (None, render_settings(saved)):
            raise RuntimeError("Generated display settings were edited; edits preserved · 自动生成的屏幕配置被手动修改，已保留改动")
        updated = {**saved, name: settings}
        contents = render_settings(updated)
        _validate_config(contents)
        if _contents(BASE / GENERATED) != previous:
            raise RuntimeError("Display file changed during validation · 校验期间屏幕配置已变更")
        token = uuid.uuid4().hex
        pending = {"version": 1, "token": token, "deadline": time.time() + CONFIRM_SECONDS,
                   "output": name, "previous_contents": previous, "applied_hash": _digest(contents),
                   "new_settings": updated, "previous_runtime": output["current"],
                   "socket": os.environ.get("NIRI_SOCKET"), "phase": "preview"}
        _write_json(_state_dir() / "pending.json", pending)
        try:
            _spawn_watchdog(token)
            pending["deadline"] = time.time() + CONFIRM_SECONDS
            _write_json(_state_dir() / "pending.json", pending)
            _atomic(BASE / GENERATED, contents)
            _run("msg", "action", "load-config-file")
        except BaseException:
            _rollback(pending)
            raise
        return token


def confirm(token):
    with _lock():
        pending = _read_json(_state_dir() / "pending.json")
        if not pending or pending["token"] != token:
            return False
        if pending["deadline"] <= time.time():
            _rollback(pending)
            return False
        if _digest(_contents(BASE / GENERATED)) != pending["applied_hash"]:
            raise RuntimeError("Display settings changed during preview · 预览期间屏幕配置已变更")
        pending["phase"] = "confirmed"
        _write_json(_state_dir() / "pending.json", pending)
        _finish_confirmation(pending)
        return True


def revert(token):
    with _lock():
        pending = _read_json(_state_dir() / "pending.json")
        if not pending or pending["token"] != token:
            return False
        if pending.get("phase") == "confirmed":
            _finish_confirmation(pending)
            return False
        _rollback(pending)
        return True


def _watch(token, ready_fd):
    # Tell the parent this independent process is alive before it changes a display.
    os.write(ready_fd, b"1")
    os.close(ready_fd)
    while True:
        with _lock():
            pending = _read_json(_state_dir() / "pending.json")
            if not pending or pending["token"] != token:
                return
            if pending.get("phase") == "confirmed":
                _finish_confirmation(pending)
                return
            remaining = pending["deadline"] - time.time()
            if remaining <= 0:
                try:
                    _rollback(pending)
                except RuntimeError as error:
                    _write_json(_state_dir() / "last-error.json", {"error": str(error), "token": token})
                return
        time.sleep(min(remaining, 0.25))


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "_watch":
        BASE = Path(sys.argv[3])
        state_directory = Path(sys.argv[4])
        _state_dir = lambda: state_directory
        _watch(sys.argv[2], int(sys.argv[5]))
    else:
        print(json.dumps(read_state(), ensure_ascii=False, indent=2))
