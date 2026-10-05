#!/usr/bin/env python3
"""Generate single-language labels for desktop components without changing commands."""
import json
from pathlib import Path
import sys

from appearance import BASE, _commit
from i18n import tr
from language_settings import available_locales, _locale_key


def render(*, base=BASE, layout=None):
    base = Path(base)
    bar = json.loads((base / "waybar/config.jsonc").read_text())
    translated = {
        "custom/launcher": tr("Applications\nSuper + Space\nRight click: overview", "应用启动器\nSuper + Space\n右键：总览"),
        "pulseaudio": tr("{desc}\nVolume {volume}%\nClick: sound devices\nScroll: volume · Right click: mute",
                           "{desc}\n音量 {volume}%\n点击：声音设备\n滚动：调节音量 · 右键：静音"),
        "network": tr("{ifname}  {ipaddr}\n{essid}\nClick: system monitor\nRight click: connections",
                        "{ifname}  {ipaddr}\n{essid}\n点击：系统监控\n右键：连接设置"),
        "battery": tr("Battery {capacity}%\n{timeTo}", "电池 {capacity}%\n{timeTo}"),
        "custom/ai": tr("AI sidebar\nSuper + A", "AI 侧栏\nSuper + A"),
        "custom/shortcuts": tr("Keyboard shortcuts\nSuper + /", "快捷键大全\nSuper + /"),
        "custom/control": tr("Settings\nSuper + I", "设置\nSuper + I"),
    }
    for key, value in translated.items():
        bar[key]["tooltip-format"] = value
    # Waybar's C++ clock otherwise defaults to English even when the UI is
    # Chinese. Only select installed locales so an absent locale cannot hide it.
    preferred = tr("en_US.UTF-8", "zh_CN.UTF-8")
    try:
        installed = {_locale_key(value) for value in available_locales()}
    except (OSError, RuntimeError):
        installed = set()
    bar["clock"]["locale"] = preferred if _locale_key(preferred) in installed else "C"
    bar["network"]["tooltip-format-disconnected"] = tr("Offline", "未连接网络")
    notification = json.loads((base / "swaync/config.json").read_text())
    notification["widget-config"]["title"].update(text=tr("Notifications", "通知"), **{"button-text": tr("Clear", "清空")})
    notification["widget-config"]["dnd"]["text"] = tr("Do not disturb", "勿扰")
    notification["text-empty"] = tr("All caught up", "暂无通知")
    # The wide/compact choice is applied last so a language rebuild can never
    # bring the wider module set back onto a narrow output.
    import bar_layout
    if layout is None:
        layout = bar_layout.select(base=base)
    bar = bar_layout.build(bar, layout)
    return {"waybar.jsonc": bar, "swaync.json": notification}


def write(*, base=BASE, layout=None):
    base = Path(base)
    (base / "theme").mkdir(parents=True, exist_ok=True)
    _commit({base / "theme" / name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
             for name, value in render(base=base, layout=layout).items()})


if __name__ == "__main__":
    try:
        write()
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
