#!/usr/bin/env python3
"""Generate single-language labels for desktop components without changing commands."""
import json
from pathlib import Path
import sys

from appearance import BASE, _commit, _lock, load_settings, notification_config, preferences_path
from i18n import tr


def render(*, base=BASE, layout=None, settings=None):
    """Return the generated SwayNC JSON.

    ``settings`` lets private generation pass the current appearance values
    together with a private base; when omitted, the live preferences are read
    through ``load_settings()``.  Spatial clearance and all nonvisual fields
    come from appearance.notification_config(), the single owner of the copied
    base config.
    """
    base = Path(base)
    notification = notification_config(settings if settings is not None else load_settings(), base=base)
    notification["widget-config"]["title"].update(text=tr("Notifications", "通知"), **{"button-text": tr("Clear", "清空")})
    notification["widget-config"]["dnd"]["text"] = tr("Do not disturb", "勿扰")
    notification["text-empty"] = tr("All caught up", "暂无通知")
    return {"swaync.json": notification}


def write(*, base=BASE, layout=None, state_path=None):
    base = Path(base)
    state_path = Path(state_path or preferences_path())
    (base / "theme").mkdir(parents=True, exist_ok=True)
    with _lock(state_path):
        settings = load_settings(state_path=state_path)
        files = {base / "theme" / name: (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
                 for name, value in render(base=base, layout=layout, settings=settings).items()}
        _commit(files)


if __name__ == "__main__":
    try:
        write()
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
