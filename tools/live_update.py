#!/usr/bin/env python3
"""Publish a verified desktop update with a durable, explicit rollback journal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".desktop-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


class Update:
    def __init__(self, target, journal, *, state_path=None):
        self.target = Path(target).resolve()
        self.directory = Path(journal).absolute()
        self.journal = self.directory / "journal.json"
        self.state_path = Path(state_path).absolute() if state_path else None

    def location(self, relative):
        if relative == "@appearance":
            if self.state_path is None:
                raise ValueError("Appearance state path required")
            result = self.state_path
        else:
            relative = Path(relative)
            if relative.is_absolute() or ".." in relative.parts or str(relative) == ".":
                raise ValueError("Invalid update path")
            result = self.target / relative
            if not result.resolve().is_relative_to(self.target):
                raise ValueError("Update escapes project")
        if result.is_symlink() or result.exists() and not result.is_file():
            raise ValueError("Refusing a non-regular update target")
        return result

    def record(self, value):
        atomic(self.journal, (json.dumps(value, indent=2) + "\n").encode(), 0o600)

    def prepare(self, source, relatives, *, expected=None, appearance=None, remove=()):
        relatives, remove = list(relatives), list(remove)
        if len(set(relatives + remove)) != len(relatives + remove) or "@appearance" in relatives + remove:
            raise ValueError("Duplicate or reserved update path")
        if self.journal.exists():
            raise ValueError("Journal already exists; choose a new release or roll it back first")
        self.directory.mkdir(parents=True, exist_ok=False)
        files = []
        payloads = [(relative, (Path(source) / relative).read_bytes(), stat.S_IMODE((Path(source) / relative).stat().st_mode)) for relative in relatives]
        payloads += [(relative, None, None) for relative in remove]
        if appearance is not None:
            payloads.append(("@appearance", appearance, 0o600))
        for index, (relative, data, mode) in enumerate(payloads):
            destination = self.location(relative)
            old = destination.read_bytes() if destination.exists() else None
            if expected is not None and (relative != "@appearance" or relative in expected) and (digest(old) if old is not None else None) != expected.get(relative):
                raise ValueError("Project changed since staging: " + relative)
            old_mode = stat.S_IMODE(destination.stat().st_mode) if old is not None else None
            if old is not None:
                atomic(self.directory / f"old-{index}", old, 0o600)
            if data is not None:
                atomic(self.directory / f"new-{index}", data, 0o600)
            files.append({"relative": relative, "index": index, "old_sha256": digest(old) if old is not None else None,
                          "new_sha256": digest(data) if data is not None else None,
                          "old_mode": old_mode, "new_mode": mode})
        value = {"version": 1, "target": str(self.target), "state_path": str(self.state_path) if self.state_path else None,
                 "phase": "prepared", "files": files}
        self.record(value)  # Durable before the first production file changes.
        return value

    def read(self):
        value = json.loads(self.journal.read_text())
        if value.get("version") != 1 or value.get("target") != str(self.target) or value.get("state_path") != (str(self.state_path) if self.state_path else None):
            raise ValueError("Journal does not belong to this project/state")
        for entry in value["files"]:
            self.location(entry["relative"])
        return value

    def publish(self, activate=lambda: None):
        value = self.read()
        if value["phase"] != "prepared":
            raise ValueError("Update is not prepared")
        # Preparation can be reviewed or interrupted before publication. Check
        # the complete batch again before writing even the first live file.
        payloads = {}
        for entry in value["files"]:
            destination = self.location(entry["relative"])
            current = digest(destination.read_bytes()) if destination.exists() else None
            if current != entry["old_sha256"]:
                raise ValueError("Project changed after preparation: " + entry["relative"])
            data = (self.directory / f"new-{entry['index']}").read_bytes() if entry["new_sha256"] is not None else None
            if data is not None and digest(data) != entry["new_sha256"]:
                raise ValueError("Staged update checksum mismatch")
            payloads[entry["index"]] = data
        value["phase"] = "publishing"
        self.record(value)
        try:
            for entry in value["files"]:
                data = payloads[entry["index"]]
                destination = self.location(entry["relative"])
                if data is None:
                    destination.unlink(missing_ok=True)
                    directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                else:
                    atomic(destination, data, entry["new_mode"])
            activate()
        except BaseException:
            self.rollback(activate)
            raise
        value["phase"] = "published"
        self.record(value)
        return value

    def rollback(self, activate=lambda: None):
        value = self.read()
        # Preserve subsequent user edits, even when recovering an interrupted
        # update. Report conflicts before touching any other file.
        backups = {}
        for entry in value["files"]:
            destination = self.location(entry["relative"])
            current = digest(destination.read_bytes()) if destination.exists() else None
            if current not in (entry["old_sha256"], entry["new_sha256"]):
                raise ValueError("Rollback conflicts with later edits: " + entry["relative"])
            if entry["old_sha256"] is not None:
                data = (self.directory / f"old-{entry['index']}").read_bytes()
                if digest(data) != entry["old_sha256"]:
                    raise ValueError("Rollback backup checksum mismatch")
                backups[entry["index"]] = data
        value["phase"] = "rolling-back"
        self.record(value)
        for entry in reversed(value["files"]):
            destination = self.location(entry["relative"])
            if entry["old_sha256"] is None:
                destination.unlink(missing_ok=True)
            else:
                data = backups[entry["index"]]
                if not destination.exists() or destination.read_bytes() != data or stat.S_IMODE(destination.stat().st_mode) != entry["old_mode"]:
                    atomic(destination, data, entry["old_mode"])
        activate()
        value["phase"] = "rolled-back"
        self.record(value)
        return value


def verify_components(reloader, components, *, timeout=6):
    """A reload signal succeeding does not prove its asynchronous work succeeded."""
    deadline, ready_since, previous_pids = time.monotonic() + timeout, None, None
    while time.monotonic() < deadline:
        pids = tuple(int(reloader.service(name, "show", "--property=MainPID", "--value") or "0")
                     if reloader.active(name) else 0 for name in components)
        ready = all(pid > 0 for pid in pids)
        now = time.monotonic()
        if ready:
            ready_since = now if ready_since is None or pids != previous_pids else ready_since
            if now - ready_since >= 1.5:
                return
        else:
            ready_since = None
        previous_pids = pids
        time.sleep(.15)
    raise RuntimeError("Reloaded components did not remain ready: " + ", ".join(components))


def reload_desktop(target):
    """Reload managed components, preserving the running compositor's identity."""
    sys.path.insert(0, str(Path(target) / "niri/shell"))
    import session_identity
    import reload_components
    import wallpaper
    socket = os.environ.get("NIRI_SOCKET")
    identity = session_identity.peer(socket) if socket else None
    components = [name for name in ("waybar", "notifications") if not reload_components.masked(name)]
    reload_components.reload_components(base=Path(target) / "niri")
    selection = wallpaper.load_settings()["selection"]
    if selection and selection["mode"] == "live":
        wallpaper.restart_renderer()
        components.append("wallpaper")
    verify_components(reload_components, components)
    if socket and session_identity.peer(socket) != identity:
        raise RuntimeError("Compositor identity changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("publish", "rollback"))
    parser.add_argument("--target", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--manifest", type=Path, help="JSON list of project-relative files")
    parser.add_argument("--remove-manifest", type=Path, help="JSON list of regular files to remove, with durable backups")
    parser.add_argument("--baseline", type=Path, help="JSON relative path to SHA256 or null")
    parser.add_argument("--appearance", type=Path, help="Verified new appearance preference JSON")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/appearance.json"
    if args.action == "rollback":
        saved = json.loads((args.journal / "journal.json").read_text())
        state = state if saved.get("state_path") else None
    update = Update(args.target, args.journal, state_path=state if args.appearance or args.action == "rollback" else None)
    activate = (lambda: reload_desktop(args.target)) if args.reload else (lambda: None)
    if args.action == "publish":
        if args.source is None or args.manifest is None:
            parser.error("publish requires --source and --manifest")
        expected = json.loads(args.baseline.read_text()) if args.baseline else None
        update.prepare(args.source, json.loads(args.manifest.read_text()), expected=expected,
                       appearance=args.appearance.read_bytes() if args.appearance else None,
                       remove=json.loads(args.remove_manifest.read_text()) if args.remove_manifest else ())
        result = update.publish(activate)
    else:
        result = update.rollback(activate)
    print(json.dumps({"phase": result["phase"], "files": len(result["files"]), "journal": str(update.journal)}))


if __name__ == "__main__":
    main()
