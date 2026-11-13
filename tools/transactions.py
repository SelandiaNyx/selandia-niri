"""Write-ahead undo records for the desktop's setup operations only."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid


def exists(path):
    return path.exists() or path.is_symlink()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def ensure_directory(path):
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    path.mkdir(parents=True, exist_ok=True)
    for directory in reversed(missing):
        sync_directory(directory)
        sync_directory(directory.parent)


def atomic_bytes(path, contents, mode=0o600, *, temporary=None):
    ensure_directory(path.parent)
    if temporary is None:
        descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    else:
        name = temporary
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
        sync_directory(path.parent.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def fingerprint(path):
    if not exists(path):
        return None
    if path.is_symlink():
        return {"link": os.readlink(path)}
    mode = stat.S_IMODE(path.stat().st_mode)
    if path.is_file():
        return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mode": mode}
    if not path.is_dir():
        raise RuntimeError("Unsupported setup target: " + str(path))
    digest = hashlib.sha256()
    for child in [path, *sorted(path.rglob("*"))]:
        relative = str(child.relative_to(path))
        if child.is_symlink():
            value = {"link": os.readlink(child)}
        elif child.is_file():
            value = fingerprint(child)
        elif child.is_dir():
            value = {"directory": stat.S_IMODE(child.stat().st_mode)}
        else:
            raise RuntimeError("Unsupported backup member: " + str(child))
        digest.update(json.dumps([relative, value], sort_keys=True).encode())
    return {"directory": digest.hexdigest()}


def file_value(path, *, allow_links=False):
    if allow_links and path.is_symlink():
        return {"link": os.readlink(path)}
    if path.is_symlink() or exists(path) and not path.is_file():
        raise RuntimeError("Refusing non-regular setup file: " + str(path))
    if not path.exists():
        return None
    metadata = path.stat()
    return {"bytes": base64.b64encode(path.read_bytes()).decode(),
            "mode": stat.S_IMODE(metadata.st_mode), "mtime": metadata.st_mtime_ns}


def value_fingerprint(value):
    if value is None:
        return None
    if "link" in value:
        return {"link": value["link"]}
    return {"sha256": hashlib.sha256(base64.b64decode(value["bytes"], validate=True)).hexdigest(), "mode": value["mode"]}


def write_value(path, value, *, temporary=None):
    if value is None:
        path.unlink(missing_ok=True)
        if path.parent.exists():
            sync_directory(path.parent)
    elif "link" in value:
        ensure_directory(path.parent)
        temporary = temporary or path.with_name("." + path.name + ".link")
        Path(temporary).symlink_to(value["link"])
        os.replace(temporary, path)
        sync_directory(path.parent)
    else:
        atomic_bytes(path, base64.b64decode(value["bytes"], validate=True), value["mode"], temporary=temporary)
        if "mtime" in value:
            os.utime(path, ns=(value["mtime"], value["mtime"]))


def sync_tree(path):
    if path.is_symlink():
        return
    if path.is_file():
        with path.open("rb") as stream:
            os.fsync(stream.fileno())
        return
    for child in path.iterdir():
        sync_tree(child)
    sync_directory(path)


def remove_owned(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    sync_directory(path.parent)


class Transaction:
    def __init__(self, journal, context, *, allowed, metadata=None):
        self.path = Path(journal)
        self.allowed = allowed
        if self.path.is_symlink():
            raise RuntimeError("Transaction record is a symbolic link")
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
            if (self.data.get("version") != 1 or self.data.get("context") != context
                    or self.data.get("phase") not in ("active", "committed")
                    or not isinstance(self.data.get("operations"), list)
                    or not isinstance(self.data.get("id"), str)
                    or len(self.data["id"]) != 32
                    or any(c not in "0123456789abcdef" for c in self.data["id"])):
                raise RuntimeError("Invalid setup transaction record")
            for operation in self.data["operations"]:
                self._validate(operation)
        else:
            self.data = {"version": 1, "id": uuid.uuid4().hex, "context": context,
                         "phase": "active", "operations": [], "metadata": metadata or {}}

    def _validate(self, operation):
        kind = operation.get("kind")
        names = ("source", "target") if kind == "move" else ("target",)
        if kind not in ("move", "create", "replace"):
            raise RuntimeError("Invalid setup transaction operation")
        for name in names:
            path = Path(operation[name])
            if not path.is_absolute() or ".." in path.parts or not self.allowed(path):
                raise RuntimeError("Transaction target is outside managed setup paths: " + str(path))

    def save(self):
        atomic_bytes(self.path, (json.dumps(self.data, ensure_ascii=False, indent=2) + "\n").encode())

    def record(self, operation):
        self._validate(operation)
        self.data["operations"].append(operation)
        self.save()  # Intent is durable before any target can change.

    def temporary(self, path, suffix):
        return path.with_name("." + path.name + ".selandia-" + self.data["id"] + suffix)

    def move(self, source, target):
        source, target = Path(source), Path(target)
        if not exists(source) or exists(target):
            raise RuntimeError("Backup move has unexpected source or destination")
        identity = fingerprint(source)
        sync_tree(source)
        operation = {"kind": "move", "source": str(source), "target": str(target), "identity": identity}
        self.record(operation)
        ensure_directory(target.parent)
        if self.same_filesystem(source, target):
            shutil.move(str(source), str(target))
        else:
            # Keep the complete source beside its original path until commit.
            # A cross-filesystem shutil.move can die during copy or deletion.
            copying = self.temporary(target, ".copy")
            if source.is_symlink():
                copying.symlink_to(os.readlink(source))
            elif source.is_dir():
                shutil.copytree(source, copying, symlinks=True)
            else:
                shutil.copy2(source, copying)
            sync_tree(copying)
            if fingerprint(source) != identity:
                raise RuntimeError("Source changed while preparing backup: " + str(source))
            os.replace(copying, target)
            sync_directory(target.parent)
            os.rename(source, self.temporary(source, ".hold"))
        sync_directory(source.parent)
        sync_directory(target.parent)

    @staticmethod
    def same_filesystem(source, target):
        return source.parent.stat().st_dev == target.parent.stat().st_dev

    def create_intent(self, path, spec):
        self.record({"kind": "create", "target": str(path), "spec": spec})

    def create(self, path, spec):
        if exists(path):
            raise RuntimeError("Expected an absent setup target: " + str(path))
        ensure_directory(path.parent)
        temporary = self.temporary(path, ".new")
        if "link" in spec:
            temporary.symlink_to(spec["link"])
        else:
            with temporary.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o644)
                stream.write(spec["text"].encode())
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)

    def replace(self, path, before, after):
        if fingerprint(path) != value_fingerprint(before):
            raise RuntimeError("Setup file changed during preparation: " + str(path))
        self.record({"kind": "replace", "target": str(path), "before": before, "after": after})
        write_value(path, after, temporary=self.temporary(path, ".new"))

    def rollback(self, callback=None):
        while self.data["operations"]:
            operation = self.data["operations"][-1]
            path = Path(operation["target"])
            current = fingerprint(path)
            if operation["kind"] == "replace":
                if current not in (value_fingerprint(operation["before"]), value_fingerprint(operation["after"])):
                    raise RuntimeError("Preserving a file edited after interrupted setup: " + str(path))
                self._cleanup_operation(operation, committed=False)
                if current != value_fingerprint(operation["before"]):
                    write_value(path, operation["before"], temporary=self.temporary(path, ".new"))
            elif operation["kind"] == "create":
                spec = operation["spec"]
                expected = ({"link": spec["link"]} if "link" in spec else
                            {"sha256": hashlib.sha256(spec["text"].encode()).hexdigest(), "mode": 0o644})
                if current is not None and current != expected:
                    raise RuntimeError("Preserving a target edited after interrupted setup: " + str(path))
                if current is not None:
                    path.unlink()
                    sync_directory(path.parent)
            else:
                source = Path(operation["source"])
                original = fingerprint(source)
                identity = operation["identity"]
                holding = self.temporary(source, ".hold")
                if current is None and original == identity:
                    pass  # Intent never executed, or its undo already completed.
                elif original is None and current == identity:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if exists(holding):
                        if fingerprint(holding) != identity:
                            raise RuntimeError("Backup holding file was edited")
                        os.rename(holding, source)
                        remove_owned(path)
                    else:
                        shutil.move(str(path), str(source))
                    sync_directory(source.parent)
                    sync_directory(path.parent)
                elif original == identity and current == identity:
                    remove_owned(path)  # Cross-filesystem copy completed; source not yet held.
                else:
                    raise RuntimeError("Backup move changed after interruption; preserving both paths: " + str(source))
            self._cleanup_operation(operation, committed=False)
            self.data["operations"].pop()
            self.save()  # Repeating recovery after SIGKILL is idempotent.
        if callback:
            callback(self.data["metadata"])
        self.path.unlink(missing_ok=True)
        sync_directory(self.path.parent)

    def _cleanup_operation(self, operation, *, committed):
        target = Path(operation["target"])
        for suffix in (".new", ".copy"):
            temporary = self.temporary(target, suffix)
            if exists(temporary):
                remove_owned(temporary)
        if operation["kind"] == "move" and committed:
            holding = self.temporary(Path(operation["source"]), ".hold")
            if exists(holding):
                if fingerprint(holding) != operation["identity"]:
                    raise RuntimeError("Backup holding file was edited; preserved: " + str(holding))
                remove_owned(holding)

    def commit(self):
        self.data["phase"] = "committed"
        self.save()
        self.finish()

    def finish(self):
        for operation in self.data["operations"]:
            self._cleanup_operation(operation, committed=True)
        self.path.unlink(missing_ok=True)
        sync_directory(self.path.parent)
