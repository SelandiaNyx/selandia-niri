"""PipeWire/PulseAudio controls via pactl; callers run these off the GTK thread."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import subprocess


def _run(*arguments):
    try:
        result = subprocess.run(["pactl", *arguments], capture_output=True, text=True,
                                timeout=6, env=dict(os.environ, LC_ALL="C.UTF-8"))
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Audio service unavailable · 音频服务不可用: {error}") from error
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-500:]
                           or "Audio command failed · 音频操作失败")
    return result.stdout.strip()


def _list(kind):
    try:
        result = json.loads(_run("--format=json", "list", kind))
    except ValueError as error:
        raise RuntimeError("Invalid audio service response · 音频服务返回无效数据") from error
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise RuntimeError("Invalid audio device list · 音频设备列表无效")
    return result


def _name(value):
    if not isinstance(value, str) or not value or value.startswith("-") or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid device identifier · 设备标识无效")
    return value


def _kind(value):
    if value not in ("sink", "source"):
        raise ValueError("Unknown audio device type · 音频设备类型无效")
    return value


def _description(item):
    properties = item.get("properties") or {}
    for value in (item.get("description"), properties.get("device.description"),
                  properties.get("node.description")):
        if isinstance(value, str) and value and value != "(null)":
            return value
    name = item.get("name") or "Unknown device · 未知设备"
    labels = {
        "off": "Off · 关闭声卡", "pro-audio": "Pro Audio · 专业音频",
        "analog-output-headphones": "Headphones · 耳机", "analog-output-speaker": "Speakers · 扬声器",
        "analog-output-lineout": "Line out · 音频输出", "analog-input-mic": "Microphone · 麦克风",
        "analog-input-front-mic": "Front microphone · 前置麦克风", "analog-input-rear-mic": "Rear microphone · 后置麦克风",
        "analog-input-linein": "Line in · 音频输入", "iec958-stereo-output": "S/PDIF output · 数字音频输出",
        "a2dp-sink": "Bluetooth stereo · 蓝牙立体声", "headset-head-unit": "Headset call mode · 耳麦通话模式",
    }
    if name in labels:
        return labels[name]
    modes = {"analog-stereo": "Analog stereo · 模拟立体声", "hdmi-stereo": "HDMI stereo · HDMI 立体声",
             "iec958-stereo": "Digital stereo · 数字立体声", "analog-surround-51": "Surround 5.1 · 5.1 环绕声",
             "analog-surround-71": "Surround 7.1 · 7.1 环绕声"}
    parts = name.split("+")
    if all(part.startswith(("output:", "input:")) and part.split(":", 1)[1] in modes for part in parts):
        return " + ".join(modes[part.split(":", 1)[1]] + (" (Out/出)" if part.startswith("output:") else " (In/入)")
                          for part in parts)
    return name


def _available(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() not in ("no", "false", "not available", "unavailable", "0")


def _availability(value):
    if not _available(value):
        return "unavailable"
    if value is True or str(value).lower() in ("yes", "true", "available", "1"):
        return "available"
    return "unknown"


def _entries(raw):
    if isinstance(raw, dict):
        return [dict(value, name=key) for key, value in raw.items() if isinstance(value, dict)]
    return [value for value in raw if isinstance(value, dict)] if isinstance(raw, list) else []


def _choices(raw):
    return [{"name": entry["name"], "description": _description(entry),
             "available": _available(entry.get("available", entry.get("availability"))),
             "availability": _availability(entry.get("available", entry.get("availability")))}
            for entry in _entries(raw) if isinstance(entry.get("name"), str)]


def _active(value):
    return value.get("name", "") if isinstance(value, dict) else (value or "")


def _volume(raw):
    channels = raw.values() if isinstance(raw, dict) else []
    values = []
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        try:
            if "value_percent" in channel:
                value = float(str(channel["value_percent"]).rstrip("%"))
            else:
                value = float(channel["value"]) / 65536 * 100
            if math.isfinite(value) and value >= 0:
                values.append(value)
        except (KeyError, TypeError, ValueError):
            continue
    # Missing channel data is not silence. Keep unavailable distinct from 0%.
    return round(sum(values) / len(values), 1) if values else None


def _device(item, default=""):
    properties = item.get("properties") or {}
    ports = _choices(item.get("ports"))
    active_port = _active(item.get("active_port"))
    active = next((port for port in ports if port["name"] == active_port), None)
    # SUSPENDED means idle, not unplugged. Unknown jack detection is also usable.
    if active:
        availability = active["availability"]
    elif ports and all(port["availability"] == "unavailable" for port in ports):
        availability = "unavailable"
    elif any(port["availability"] == "available" for port in ports):
        availability = "available"
    else:
        availability = "unknown"
    pro = str(properties.get("device.profile.pro", "")).lower() in ("true", "1")
    virtual = (str(properties.get("node.virtual", "")).lower() in ("true", "1")
               or properties.get("device.class") in ("filter", "abstract", "virtual")
               or properties.get("factory.name") == "support.null-audio-sink"
               or item["name"] == "auto_null")
    kind = "monitor" if _is_monitor(item) else "virtual" if virtual else "pro" if pro else "hardware"
    description = _description(item)
    if kind == "pro":
        # Raw Pro Audio nodes often share the same card description. The nick
        # and PCM number make the advanced inventory distinguishable.
        nick = properties.get("node.nick") or properties.get("alsa.name")
        if isinstance(nick, str) and nick and nick != "(null)":
            description = nick
        pcm = properties.get("alsa.device")
        if pcm is not None:
            description += f" · PCM {pcm}"
    reason = {
        "monitor": "Playback monitor, not a microphone · 播放监听源，并非麦克风",
        "virtual": "Virtual audio route · 虚拟音频通道",
        "pro": "Raw Pro Audio endpoint; jack status may be unknown · 专业音频原始通道，插孔状态可能未知",
        "hardware": "",
    }[kind]
    if availability == "unavailable":
        reason = "Active port is disconnected · 当前端口未连接" if active else "All ports are disconnected · 所有端口均未连接"
    return {"name": item["name"], "description": description,
            "volume": _volume(item.get("volume")), "mute": bool(item.get("mute", False)),
            "ports": ports, "active_port": active_port,
            "kind": kind, "availability": availability, "available": availability != "unavailable",
            "state": str(item.get("state", "")), "is_default": item["name"] == default,
            "card": properties.get("device.name", ""), "reason": reason,
            "advanced": kind != "hardware" or availability == "unavailable"}


def _is_monitor(item):
    monitored = item.get("monitor_of_sink")
    return (monitored not in (None, "", 4294967295, "4294967295", "n/a")
            or (item.get("properties") or {}).get("device.class") == "monitor"
            or str(item.get("name", "")).endswith(".monitor"))


def _card(item):
    normal = [profile for profile in _entries(item.get("profiles"))
              if profile.get("name") not in (None, "off", "pro-audio")
              and _available(profile.get("available", profile.get("availability")))]
    def priority(profile):
        try:
            return int(profile.get("priority", 0))
        except (TypeError, ValueError):
            return 0
    recommendation = max(normal, key=priority) if normal else None
    return {"name": item["name"], "description": _description(item),
            "profiles": _choices(item.get("profiles")),
            "active_profile": _active(item.get("active_profile")),
            "recommended_profile": recommendation["name"] if recommendation else "",
            "recommended_description": _description(recommendation) if recommendation else ""}


def read_state(include_unavailable=False):
    """Inspect audio without changing profiles or routes.

    Normal view omits disconnected and advanced routes. Defaults and actively
    used endpoints stay visible. The advanced view exposes the whole inventory,
    including virtual devices and playback monitors, with explicit labels.
    Raw Pro Audio endpoints have no reliable jack status; they are never called
    disconnected merely because Pro Audio created them or they are suspended.
    """
    with ThreadPoolExecutor(max_workers=5) as executor:
        pending = {kind: executor.submit(_list, kind) for kind in ("sinks", "sources", "cards")}
        defaults = {kind: executor.submit(_run, f"get-default-{kind}") for kind in ("sink", "source")}
        result = {kind: task.result() for kind, task in pending.items()}
        result["cards"] = [_card(item) for item in result["cards"] if item.get("name")]
        for kind, task in defaults.items():
            # A machine with no input or output may not expose a default.
            try:
                result[f"default_{kind}"] = task.result()
            except RuntimeError:
                result[f"default_{kind}"] = ""
    result["hidden_counts"] = {}
    for plural, kind in (("sinks", "sink"), ("sources", "source")):
        devices = [_device(item, result[f"default_{kind}"]) for item in result[plural] if item.get("name")]
        def visible(device):
            # An output monitor runs whenever its output plays; that alone must
            # not make it appear as a physical recording device in normal view.
            return (not device["advanced"] or device["is_default"]
                    or (device["kind"] != "monitor" and device["state"] == "RUNNING"))
        normal = [device for device in devices if visible(device)]
        result["hidden_counts"][plural] = len(devices) - len(normal)
        result[plural] = devices if include_unavailable else normal
    result["pro_audio_cards"] = [card for card in result["cards"] if card["active_profile"] == "pro-audio"]
    return result


def set_default(kind, name):
    return _run(f"set-default-{_kind(kind)}", _name(name))


def set_volume(kind, name, percent):
    value = float(percent)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("Volume must be 0–100% · 音量范围为 0–100%")
    return _run(f"set-{_kind(kind)}-volume", _name(name), f"{value:.0f}%")


def set_mute(kind, name, muted):
    if not isinstance(muted, bool):
        raise ValueError("Mute must be true or false · 静音状态必须是布尔值")
    return _run(f"set-{_kind(kind)}-mute", _name(name), "1" if muted else "0")


def set_port(kind, name, port):
    return _run(f"set-{_kind(kind)}-port", _name(name), _name(port))


def set_profile(card, profile):
    return _run("set-card-profile", _name(card), _name(profile))


def move_streams(kind, name):
    """Explicitly route currently running applications to the selected device."""
    _kind(kind)
    _name(name)
    stream_type = "sink-input" if kind == "sink" else "source-output"
    streams = _list(stream_type + "s")
    moved = 0
    failures = []
    for stream in streams:
        index = stream.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            continue
        try:
            _run(f"move-{stream_type}", str(index), name)
            moved += 1
        except RuntimeError as error:
            failures.append(str(error))
    if failures:
        raise RuntimeError(f"Moved {moved} streams; some apps could not move · 已移动 {moved} 路，部分应用切换失败: "
                           + failures[0])
    return moved
