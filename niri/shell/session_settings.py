"""Undo records for autostart entries and persistent component masks we change."""
from contextlib import contextmanager
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

UNITS = {"selandia-niri@" + component + ".service" for component in
         ("clipboard-text", "clipboard-image", "notifications", "waybar")}
JOURNAL = "session-settings-backup.json"


def journal_path():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "selandia-niri" / JOURNAL


def managed_relative(relative):
    parts = Path(relative).parts
    return (len(parts) == 2 and parts[0] == "autostart" and
            parts[1].startswith("selandia-niri-") and parts[1].endswith(".desktop") and
            not any(char in parts[1] for char in ("\x00", "\r", "\n")) or
            len(parts) == 3 and parts[:2] == ("systemd", "user") and parts[2] in UNITS)


def checked_path(home, relative):
    path = home / relative
    for parent in path.parents:
        if parent == home:
            break
        if parent.is_symlink():
            raise RuntimeError("Managed session directory was replaced: " + str(parent))
    return path


def read_value(path):
    if path.is_symlink():
        return {"link": os.readlink(path)}
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError("Not a regular managed session file: " + str(path))
    return {"bytes": base64.b64encode(path.read_bytes()).decode(),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def write_value(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".selandia-session-", dir=path.parent)
    try:
        if value is not None and "bytes" in value:
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), value["mode"])
                stream.write(base64.b64decode(value["bytes"], validate=True))
                stream.flush()
                os.fsync(stream.fileno())
        else:
            os.close(descriptor)
            Path(name).unlink()
            if value is not None:
                Path(name).symlink_to(value["link"])
        if value is None:
            path.unlink(missing_ok=True)
        else:
            os.replace(name, path)
        descriptor = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(name).unlink(missing_ok=True)


def load(home, state_path=None):
    home, path = Path(home).absolute(), Path(state_path or journal_path())
    if path.is_symlink():
        raise RuntimeError("Session settings backup is a symbolic link")
    if not path.exists():
        return {"version": 1, "config_home": str(home), "files": {}}
    data = json.loads(path.read_text())
    if (data.get("version") != 1 or data.get("config_home") != str(home) or
            not isinstance(data.get("files"), dict)):
        raise RuntimeError("Invalid session settings backup")
    for relative, record in data["files"].items():
        if not managed_relative(relative) or not isinstance(record, dict):
            raise RuntimeError("Invalid managed session path")
        checked_path(home, relative)
        for key in ("before", "applied", "pending"):
            if key not in record:
                if key != "pending":
                    raise RuntimeError("Incomplete session settings backup")
                continue
            value = record[key]
            if value is not None:
                if set(value) == {"link"}:
                    if not isinstance(value["link"], str):
                        raise RuntimeError("Invalid saved symbolic link")
                elif set(value) == {"bytes", "mode"}:
                    base64.b64decode(value["bytes"], validate=True)
                    if type(value["mode"]) is not int or not 0 <= value["mode"] <= 0o7777:
                        raise RuntimeError("Invalid saved file permissions")
                else:
                    raise RuntimeError("Invalid saved session file")
    return data


def save(path, data):
    if data["files"]:
        contents = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
        write_value(path, {"bytes": base64.b64encode(contents).decode(), "mode": 0o600})
    elif path.exists():
        write_value(path, None)


@contextmanager
def record_changes(home, desired, *, state_path=None):
    home, path = Path(home).absolute(), Path(state_path or journal_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(home, path)
        for relative, value in desired.items():
            if not managed_relative(relative):
                raise RuntimeError("Not a managed session path")
            current = read_value(checked_path(home, relative))
            old = data["files"].get(relative)
            if old and current not in (old["before"], old["applied"], old.get("pending", old["applied"])):
                raise RuntimeError("Preserving edited session settings: " + relative)
            data["files"][relative] = {"before": old["before"] if old else current,
                                       "applied": old["applied"] if old else current, "pending": value}
        save(path, data)
        yield
        for relative in desired:
            record = data["files"][relative]
            record["applied"] = read_value(checked_path(home, relative))
            record.pop("pending", None)
            if record["before"] == record["applied"]:
                del data["files"][relative]
        save(path, data)


def restoration_plan(home, state_path=None):
    home = Path(home).absolute()
    data = load(home, state_path)
    restore, preserve = [], []
    for relative, record in data["files"].items():
        current = read_value(checked_path(home, relative))
        if current in (record["before"], record["applied"], record.get("pending", record["applied"])):
            restore.append(relative)
        else:
            preserve.append(relative)
    # Older versions have no original-state records; do not guess ownership.
    preserve.extend(str(path.relative_to(home)) for path in sorted((home / "autostart").glob("selandia-niri-*.desktop"))
                    if str(path.relative_to(home)) not in data["files"])
    preserve.extend("systemd/user/" + unit for unit in sorted(UNITS)
                    if (home / "systemd/user" / unit).is_symlink() and
                    "systemd/user/" + unit not in data["files"])
    return data, restore, preserve


def restore(home, state_path=None):
    home, path = Path(home).absolute(), Path(state_path or journal_path())
    data, restored, preserved = restoration_plan(home, path)
    for relative in restored:
        record = data["files"][relative]
        if read_value(home / relative) != record["before"]:
            write_value(home / relative, record["before"])
        del data["files"][relative]
        save(path, data)
    return {"restored": restored, "preserved": preserved}
