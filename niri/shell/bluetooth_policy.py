#!/usr/bin/env python3
"""BlueZ boot power policy. The privileged entry only edits one fixed file.

Changing the policy does not restart BlueZ, disconnect devices, or alter audio
profiles. BlueZ reads it at its next start. Current power is controlled over D-Bus.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

CONFIG = Path("/etc/bluetooth/main.conf")
SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*(?:[#;].*)?$")
OPTION = re.compile(r"^(\s*)AutoEnable\s*=\s*(true|false)\s*$", re.IGNORECASE)


def policy_lines(source):
    lines = source.splitlines(keepends=True)
    section = None
    section_start = None
    section_end = len(lines)
    options = []
    for index, line in enumerate(lines):
        match = SECTION.match(line.strip())
        if match:
            if section == "Policy":
                section_end = index
            section = match[1]
            if section == "Policy":
                if section_start is not None:
                    raise ValueError("Duplicate BlueZ [Policy] section")
                section_start = index
        if section == "Policy" and re.match(r"\s*AutoEnable\s*=", line, re.IGNORECASE):
            option = OPTION.match(line.rstrip("\r\n"))
            if not option:
                raise ValueError("Invalid BlueZ AutoEnable value")
            options.append((index, option[2].lower() == "true"))
    if len(options) > 1:
        raise ValueError("Duplicate BlueZ AutoEnable setting")
    return lines, section_start, section_end, options


def render_policy(source, enabled):
    if type(enabled) is not bool:
        raise ValueError("AutoEnable must be a boolean")
    lines, start, end, options = policy_lines(source)
    value = "AutoEnable=" + str(enabled).lower() + "\n"
    if options:
        lines[options[0][0]] = value
    elif start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.extend(["\n[Policy]\n", value])
    else:
        if end and not lines[end - 1].endswith("\n"):
            lines[end - 1] += "\n"
        lines.insert(end, value)
    return "".join(lines)


def read_state(*, path=CONFIG):
    path = Path(path)
    source = path.read_text() if path.exists() else ""
    _lines, _start, _end, options = policy_lines(source)
    return {"auto_enable": options[0][1] if options else True,
            "configured": bool(options), "path": str(path)}


def write_policy(enabled, *, path=CONFIG):
    """Atomic update with a timestamped backup; test paths are not exposed by CLI."""
    path = Path(path)
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError("Refusing non-regular BlueZ configuration")
    previous = path.read_text() if path.exists() else ""
    rendered = render_policy(previous, enabled)
    if rendered == previous:
        return None
    metadata = path.stat() if path.exists() else None
    if not path.parent.is_dir():
        raise FileNotFoundError(str(path.parent))
    backup = None
    if metadata:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(path.name + ".selandia-" + timestamp)
        # Exclusive creation prevents an existing path from being overwritten.
        with backup.open("xb") as destination:
            destination.write(path.read_bytes())
        shutil.copystat(path, backup)
    descriptor, name = tempfile.mkstemp(prefix=".selandia-bluez-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode) if metadata else 0o644)
            if metadata and os.geteuid() == 0:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return str(backup) if backup else None


def apply_auto_enable(enabled):
    if type(enabled) is not bool:
        raise ValueError("AutoEnable must be a boolean")
    result = subprocess.run(["pkexec", "/usr/bin/python3", "-I", str(Path(__file__).resolve()),
                             "admin", "on" if enabled else "off"],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or "BlueZ policy update cancelled")
    return read_state()


def main():
    args = sys.argv[1:]
    if args == ["status"]:
        import json
        print(json.dumps(read_state()))
    elif len(args) == 2 and args[0] == "admin" and args[1] in ("on", "off"):
        if os.geteuid() != 0:
            raise PermissionError("Administrator authentication required")
        backup = write_policy(args[1] == "on")
        print(backup or "unchanged")
    elif len(args) == 2 and args[0] == "apply" and args[1] in ("on", "off"):
        print(apply_auto_enable(args[1] == "on"))
    else:
        raise ValueError("Usage: bluetooth_policy.py status | apply on|off")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
