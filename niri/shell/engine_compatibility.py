"""Optional local engine library; accept only the exact tested base package ABI."""
import hashlib
import json
import os
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path("/opt/linux-wallpaperengine/linux-wallpaperengine")
LIBRARY = Path("/opt/linux-wallpaperengine/liblinux-wallpaperengine-lib.so")
LOCAL_NAME = "liblinux-wallpaperengine-lib.so"


def fingerprint(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def directory():
    # Private probes can use their staged build; portable exports carry no
    # machine-specific binary or absolute override in their source configuration.
    return Path(os.environ.get("SELANDIA_ENGINE_COMPAT_DIR", str(ROOT / ".local/wallpaper-engine")))


def compatible_directory():
    target = directory()
    manifest = target / "compatibility.json"
    try:
        if target.is_symlink() or manifest.is_symlink() or manifest.stat().st_size > 4096:
            return None
        value = json.loads(manifest.read_text())
        if value.get("version") != 1 or value.get("architecture") != platform.machine():
            return None
        for path, key in ((BINARY, "base_binary_sha256"), (LIBRARY, "base_library_sha256"),
                          (target / LOCAL_NAME, "patched_library_sha256")):
            if path.is_symlink() or fingerprint(path) != value.get(key):
                return None
        return target.resolve()
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def environment(environment):
    target = compatible_directory()
    if target is None:
        return dict(environment)
    libraries = [str(target), str(BINARY.parent), str(BINARY.parent / "lib"), str(BINARY.parent / "lib64")]
    existing = environment.get("LD_LIBRARY_PATH")
    if existing:
        libraries.append(existing)
    return dict(environment, LD_LIBRARY_PATH=":".join(libraries))
