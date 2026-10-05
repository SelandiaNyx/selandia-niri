#!/usr/bin/env python3
"""User interface and Arch session language settings, without import-time changes.

System locale changes are a separate, explicit, authenticated operation. Managed
user files are journaled so uninstall can restore them without erasing later edits.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parent.parent
UI_LANGUAGES = ("system", "zh_CN", "en_US")
LOCALE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,79}\Z")
OVERRIDES = ("LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_NUMERIC", "LC_TIME", "LC_COLLATE",
             "LC_MONETARY", "LC_MESSAGES", "LC_PAPER", "LC_NAME", "LC_ADDRESS",
             "LC_TELEPHONE", "LC_MEASUREMENT", "LC_IDENTIFICATION")
DEFAULTS = {"ui_language": "system", "session_locale": ""}


def preferences_path():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/language.json"


def read_preferences(*, state_path=None):
    try:
        value = json.loads(Path(state_path or preferences_path()).read_text())
        if (not isinstance(value, dict) or set(value) - set(DEFAULTS)
                or value.get("ui_language", "system") not in UI_LANGUAGES
                or not isinstance(value.get("session_locale", ""), str)
                or value.get("session_locale") and not LOCALE_RE.fullmatch(value["session_locale"])):
            raise ValueError("Invalid language preferences")
        return {**DEFAULTS, **value}
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def resolve_ui_language(code=None, *, state_path=None):
    preferences = read_preferences(state_path=state_path)
    code = code or preferences["ui_language"]
    if code == "system":
        code = preferences["session_locale"] or next(
            (os.environ[key] for key in ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(key)), "en_US")
    return "zh_CN" if str(code).lower().startswith("zh") else "en_US"


def _message(english, chinese):
    return chinese if resolve_ui_language() == "zh_CN" else english


def _read(path):
    path = Path(path)
    if path.is_symlink() or path.exists() and not path.is_file():
        raise OSError(_message("Refusing a non-regular settings file: ", "不能写入非普通配置文件：") + str(path))
    return path.read_text() if path.exists() else None


def _write(path, value, *, mode=0o600):
    path = Path(path)
    _read(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if value is None:
        if path.exists():
            path.unlink()
        return
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


@contextmanager
def _lock(state_path):
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(".lock")
    _read(lock_path)
    with lock_path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def save_ui_language(code, *, state_path=None):
    if code not in UI_LANGUAGES:
        raise ValueError(_message("Choose a supported interface language.", "请选择支持的界面语言。"))
    state_path = Path(state_path or preferences_path())
    with _lock(state_path):
        values = read_preferences(state_path=state_path)
        values["ui_language"] = code
        _write(state_path, _json(values))
    return values


def _run(argv, *, timeout=10):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, "LC_ALL": "C.UTF-8"})
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"{argv[0]} exited {result.returncode}")
    return result.stdout.strip()


def available_locales():
    return sorted({line.strip() for line in _run(["locale", "-a"]).splitlines()
                   if LOCALE_RE.fullmatch(line.strip())}, key=str.casefold)


def _locale_key(value):
    return value.lower().replace("-", "")


def validate_locale(value, *, locales=None):
    if not isinstance(value, str) or not LOCALE_RE.fullmatch(value):
        raise ValueError(_message("Invalid locale name.", "语言区域名称无效。"))
    installed = available_locales() if locales is None else locales
    match = next((locale for locale in installed if _locale_key(locale) == _locale_key(value)), None)
    if match is None:
        raise ValueError(_message("This locale has not been generated. Enable it in /etc/locale.gen, then run sudo locale-gen.",
                                  "此语言区域尚未生成。请在 /etc/locale.gen 中启用后运行 sudo locale-gen。"))
    # Standard UTF-8 spelling is accepted by glibc, even though locale -a uses utf8.
    return re.sub(r"\.utf-?8(?=@|$)", ".UTF-8", match, flags=re.IGNORECASE)


def read_system_locale(*, path=Path("/etc/locale.conf")):
    try:
        for line in Path(path).read_text().splitlines():
            fields = shlex.split(line, comments=True)
            if len(fields) == 1 and fields[0].startswith("LANG="):
                value = fields[0][5:]
                if LOCALE_RE.fullmatch(value):
                    return value
    except (OSError, ValueError):
        pass
    return "C.UTF-8"


def read_state(*, state_path=None, system_path=Path("/etc/locale.conf")):
    preferences = read_preferences(state_path=state_path)
    locales = available_locales()
    keys = {_locale_key(item) for item in locales}
    return {"preferences": preferences, "ui_language": resolve_ui_language(state_path=state_path),
            "locales": locales, "session_locale": preferences["session_locale"] or os.environ.get("LANG", "C.UTF-8"),
            "system_locale": read_system_locale(path=system_path),
            "overrides": {key: os.environ[key] for key in OVERRIDES if os.environ.get(key)},
            "missing_common": [item for item in ("zh_CN.UTF-8", "en_US.UTF-8") if _locale_key(item) not in keys]}


def _paths(config_home=None, niri_home=None):
    config = Path(config_home or os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).absolute()
    return {"environment": config / "environment.d/90-selandia-language.conf",
            "niri": Path(niri_home or BASE).absolute() / "conf/language.kdl"}


def _journal(path, paths):
    source = _read(path)
    if source is None:
        return {"version": 1, "files": {}}
    data = json.loads(source)
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("files"), dict):
        raise ValueError(_message("Invalid language backup", "语言设置备份无效"))
    for key, record in data["files"].items():
        if (key not in paths or not isinstance(record, dict) or record.get("path") != str(paths[key])
                or not isinstance(record.get("before"), (str, type(None)))
                or not isinstance(record.get("applied"), str)
                or "pending" in record and not isinstance(record["pending"], str)):
            raise ValueError(_message("Invalid language backup", "语言设置备份无效"))
    return data


def _managed_versions(record):
    versions = (record["applied"],)
    if "pending" in record:
        # The durable journal is written before either settings file. A process
        # interruption may leave the original file untouched on the first apply.
        versions += (record["pending"], record["before"])
    return versions


def session_environment(locale=None, *, state_path=None, environ=None):
    environment = dict(os.environ if environ is None else environ)
    locale = locale or read_preferences(state_path=state_path)["session_locale"]
    if not locale:
        return environment
    if not LOCALE_RE.fullmatch(locale):
        raise ValueError(_message("Invalid session locale", "会话语言区域无效"))
    for key in OVERRIDES:
        environment.pop(key, None)
    environment["LANG"] = locale
    return environment


def sync_session(locale=None, *, state_path=None):
    """Update future systemd/DBus launches; running processes keep their environment."""
    locale = locale or read_preferences(state_path=state_path)["session_locale"]
    if not locale:
        return {"locale": "", "warnings": []}
    locale = validate_locale(locale)
    warnings = []
    for command in (["systemctl", "--user", "unset-environment", *OVERRIDES],
                    ["systemctl", "--user", "set-environment", "LANG=" + locale],
                    # DBus has no unset API. Empty category values fall back to LANG.
                    ["dbus-update-activation-environment", "LANG=" + locale, *(key + "=" for key in OVERRIDES)]):
        try:
            _run(command)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            warnings.append(str(error))
    return {"locale": locale, "warnings": warnings}


def apply_session_locale(locale, *, config_home=None, niri_home=None, state_path=None, notify=True):
    locale = validate_locale(locale)
    state_path = Path(state_path or preferences_path())
    journal_path = state_path.with_name("language-backup.json")
    paths = _paths(config_home, niri_home)
    desired = {
        "environment": "# Managed by Selandia Niri language settings.\nLANG=" + locale + "\n",
        "niri": "// Managed by Selandia Niri language settings.\nenvironment {\n    LANG " + json.dumps(locale)
                + "\n" + "".join(f"    {key} null\n" for key in OVERRIDES) + "}\n",
    }
    with _lock(state_path):
        data = _journal(journal_path, paths)
        originals = {key: _read(path) for key, path in paths.items()}
        previous_preferences = _read(state_path)
        previous_journal = _read(journal_path)
        for key, path in paths.items():
            old = data["files"].get(key)
            if old and originals[key] is not None and originals[key] not in _managed_versions(old):
                raise RuntimeError(_message("A managed language file was edited; keep your changes or restore it before applying: ",
                                            "语言配置已被手动修改，请处理改动后再应用：") + str(path))
            data["files"][key] = {"path": str(path), "before": old["before"] if old else originals[key],
                                  "applied": old["applied"] if old else desired[key], "pending": desired[key]}
        try:
            _write(journal_path, _json(data))
            for key, path in paths.items():
                _write(path, desired[key], mode=0o644)
            preferences = read_preferences(state_path=state_path)
            preferences["session_locale"] = locale
            _write(state_path, _json(preferences))
            for key in paths:
                data["files"][key]["applied"] = data["files"][key].pop("pending")
            _write(journal_path, _json(data))
        except Exception:
            for key, path in paths.items():
                _write(path, originals[key], mode=0o644)
            _write(state_path, previous_preferences)
            _write(journal_path, previous_journal)
            raise
    result = sync_session(locale, state_path=state_path) if notify else {"locale": locale, "warnings": []}
    result["preferences"] = preferences
    return result


def restore(*, config_home=None, niri_home=None, state_path=None):
    """Restore owned user files. Never revert the explicitly chosen system locale."""
    state_path = Path(state_path or preferences_path())
    journal_path = state_path.with_name("language-backup.json")
    paths = _paths(config_home, niri_home)
    conflicts = []
    restored = []
    with _lock(state_path):
        data = _journal(journal_path, paths)
        for key, record in list(data["files"].items()):
            path = paths[key]
            if _read(path) not in _managed_versions(record):
                conflicts.append(str(path))
                continue
            _write(path, record["before"], mode=0o644)
            restored.append(str(path))
            del data["files"][key]
        if not conflicts:
            values = read_preferences(state_path=state_path)
            values["session_locale"] = ""
            if state_path.exists():
                _write(state_path, _json(values))
            _write(journal_path, None)
        else:
            _write(journal_path, _json(data))
    return {"restored": restored, "conflicts": conflicts}


def apply_system_locale(locale):
    locale = validate_locale(locale)
    # One fixed program and validated argument; no shell, scripts, keymap changes,
    # or implicit locale generation. Polkit presents authentication to the user.
    _run(["pkexec", "/usr/bin/localectl", "set-locale", "LANG=" + locale], timeout=120)
    return {"locale": locale, "requires_login": True}


def restore_saved(**options):
    locale = read_preferences(state_path=options.get("state_path"))["session_locale"]
    if not locale:
        return {"locale": "", "warnings": []}
    return apply_session_locale(locale, **options)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ["status"]:
        result = read_state()
    elif args == ["sync-session"]:
        result = sync_session()
    elif args == ["restore"]:
        result = restore()
    elif args == ["restore-saved"]:
        result = restore_saved()
    elif len(args) == 2 and args[0] == "session":
        result = apply_session_locale(args[1])
    elif len(args) == 2 and args[0] == "ui":
        result = save_ui_language(args[1])
    elif len(args) >= 2 and args[0] == "exec":
        os.execvpe(args[1], args[1:], session_environment())
        return 0
    else:
        print("Usage: language_settings.py status|sync-session|restore|restore-saved|session LOCALE|ui LANGUAGE|exec PROGRAM [ARGS…]", file=sys.stderr)
        return 2
    print(_json(result), end="")
    return 1 if result.get("conflicts") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
