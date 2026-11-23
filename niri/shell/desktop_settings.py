"""Validated native input and window preferences, kept in a separate Niri include.

Only explicitly saved groups are overridden. Original configuration files stay
untouched, including custom pointing-device options that Niri cannot merge.
"""
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

BASE = Path(__file__).resolve().parent.parent
GENERATED = Path("conf/desktop-settings.kdl")
HEADER = "// Managed by Selandia native desktop settings.\n"
DEFAULTS = {
    "keyboard_layout": "us", "keyboard_variant": "", "keyboard_options": "",
    "keyboard_repeat_delay": 250, "keyboard_repeat_rate": 40, "keyboard_numlock": True,
    "keyboard_track_layout": "global", "mouse_accel_speed": 0.0,
    "mouse_accel_profile": "flat", "mouse_natural_scroll": False,
    "mouse_left_handed": False, "mouse_scroll_factor": 1.0,
    "touchpad_accel_speed": 0.0, "touchpad_accel_profile": "adaptive",
    "touchpad_natural_scroll": True, "touchpad_tap": True, "touchpad_dwt": True,
    "touchpad_left_handed": False, "touchpad_disabled_on_external_mouse": False,
    "touchpad_scroll_method": "two-finger", "touchpad_scroll_factor": 1.0,
    "gaps": 16, "column_width": 0.5, "column_center": "on-overflow",
    "always_center_single_column": True, "empty_workspace_above_first": False,
    "focus_ring": True, "focus_ring_width": 2, "border": False, "border_width": 2,
    "default_column_display": "normal", "focus_follows_mouse": False,
    "workspace_auto_back_and_forth": True, "cursor_size": 24, "cursor_hide_when_typing": True,
}
GROUPS = {
    "input": {key for key in DEFAULTS if key.startswith(("keyboard_", "mouse_", "touchpad_"))},
    "desktop": {key for key in DEFAULTS if not key.startswith(("keyboard_", "mouse_", "touchpad_"))},
}
RANGES = {"keyboard_repeat_delay": (100, 2000), "keyboard_repeat_rate": (1, 100),
          "mouse_accel_speed": (-1, 1), "touchpad_accel_speed": (-1, 1),
          "mouse_scroll_factor": (0.1, 5), "touchpad_scroll_factor": (0.1, 5),
          "gaps": (0, 64), "column_width": (0.2, 1), "focus_ring_width": (1, 12),
          "border_width": (1, 12), "cursor_size": (16, 96)}
CHOICES = {"keyboard_track_layout": ("global", "window"),
           "mouse_accel_profile": ("flat", "adaptive"), "touchpad_accel_profile": ("flat", "adaptive"),
           "touchpad_scroll_method": ("two-finger", "edge"),
           "column_center": ("never", "on-overflow", "always"),
           "default_column_display": ("normal", "tabbed")}


def _state_path():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/desktop-settings.json"


def _error(english, chinese):
    try:
        from i18n import tr
        return tr(english, chinese)
    except ImportError:
        return english


def validate_settings(group, values):
    if group not in GROUPS or not isinstance(values, dict) or set(values) != GROUPS[group]:
        raise ValueError(_error("Incomplete desktop settings", "桌面设置不完整"))
    result = dict(values)
    for key, value in values.items():
        default = DEFAULTS[key]
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif key in RANGES:
            valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and RANGES[key][0] <= value <= RANGES[key][1]
                     and (not isinstance(default, int) or int(value) == value))
            if valid:
                result[key] = int(value) if isinstance(default, int) else round(float(value), 3)
        elif key in CHOICES:
            valid = value in CHOICES[key]
        else:
            valid = isinstance(value, str) and len(value) <= 240 and bool(re.fullmatch(r"[A-Za-z0-9_,:+.-]*", value))
            if key == "keyboard_layout":
                valid = valid and bool(value) and all(value.split(","))
        if not valid:
            raise ValueError(f"{_error('Invalid value', '设置值无效')}: {key}")
    if group == "input":
        if len(values["keyboard_variant"].split(",")) > len(values["keyboard_layout"].split(",")):
            raise ValueError(_error("Each keyboard variant needs a corresponding layout", "每个键盘变体都需要对应的布局"))
    return result


_KDL_TOKEN = re.compile(r'(?P<block>/\*.*?\*/)|(?P<comment>//[^\n]*)|(?P<raw>r(?P<hash>\#*)".*?"(?P=hash))|(?P<string>"(?:\\.|[^"\\])*")|(?P<newline>\n)|(?P<space>[^\S\n]+)|(?P<symbol>[{};])|(?P<word>[^\s{};]+)', re.S)


def _nodes(contents):
    """Read Niri nodes without interpreting their arguments; retain unknown nodes.

    This scanner handles comments, quoted/raw strings and nested blocks. It is
    deliberately not a KDL validator: the installed Niri parser validates writes.
    """
    tokens = [(match.lastgroup, match.group()) for match in _KDL_TOKEN.finditer(contents)
              if match.lastgroup not in ("space", "block", "comment")]
    index = 0

    def parse():
        nonlocal index
        nodes = []
        while index < len(tokens):
            while index < len(tokens) and tokens[index][1] in ("\n", ";"):
                index += 1
            if index >= len(tokens):
                break
            if tokens[index][1] == "}":
                index += 1
                break
            head = []
            while index < len(tokens) and tokens[index][1] not in ("\n", ";", "{", "}"):
                head.append(tokens[index][1])
                index += 1
            children = None
            if index < len(tokens) and tokens[index][1] == "{":
                index += 1
                children = parse()
            if head:
                disabled = head[0] == "/-" or head[0].startswith("/-")
                if not disabled:
                    nodes.append({"name": head[0], "head": head, "children": children})
            elif index < len(tokens) and tokens[index][1] not in ("}", "\n", ";"):
                index += 1
        return nodes
    return parse()


def _render_node(node, indent=0):
    padding = " " * indent
    text = padding + " ".join(node["head"])
    if node["children"] is not None:
        text += " {\n" + "".join(_render_node(child, indent + 4) for child in node["children"]) + padding + "}"
    return text + "\n"


def _value(node, default=None):
    args = node["head"][1:]
    if not args:
        return True
    value = args[0]
    if value in ("true", "false"):
        return value == "true"
    try:
        return json.loads(value)
    except ValueError:
        return default


def _configuration_nodes(base):
    active = set()
    generated = (base / GENERATED).resolve()

    def visit(path):
        path = path.resolve()
        if path == generated:
            return []
        if path in active:
            raise RuntimeError(_error("Circular Niri include", "Niri 配置存在循环引用"))
        active.add(path)
        result = []
        try:
            nodes = _nodes(path.read_text())
            for node in nodes:
                if node["name"] == "include":
                    raw = next((part for part in node["head"][1:] if part.startswith('"')), None)
                    if raw is None:
                        raise RuntimeError(_error("Unsupported include path", "无法读取配置引用路径"))
                    target = Path(os.path.expanduser(json.loads(raw)))
                    if not target.is_absolute():
                        target = path.parent / target
                    if target.exists() or "optional=true" not in node["head"]:
                        result.extend(visit(target))
                else:
                    result.append(node)
            return result
        finally:
            active.remove(path)
    return visit(base / "config.kdl")


def _source(base):
    settings = dict(DEFAULTS)
    retained = {"mouse": [], "touchpad": [], "keyboard": [], "xkb": []}
    for node in _configuration_nodes(base):
        if node["name"] == "input":
            for item in node["children"] or []:
                name = item["name"]
                if name in ("mouse", "touchpad"):
                    retained[name] = item["children"] or []
                    for key in GROUPS["input"]:
                        if key.startswith(name + "_"):
                            # These sections replace, rather than merge, upstream.
                            settings[key] = DEFAULTS[key]
                    for child in item["children"] or []:
                        key = name + "_" + child["name"].replace("-", "_")
                        if key in settings:
                            settings[key] = _value(child, settings[key])
                elif name == "keyboard":
                    for child in item["children"] or []:
                        if child["name"] == "xkb":
                            retained["xkb"] = child["children"] or []
                            for xkb in child["children"] or []:
                                key = "keyboard_" + xkb["name"]
                                if key in settings:
                                    settings[key] = _value(xkb, settings[key])
                        else:
                            retained["keyboard"] = [old for old in retained["keyboard"] if old["name"] != child["name"]] + [child]
                            key = "keyboard_" + child["name"].replace("-", "_")
                            if key in settings:
                                settings[key] = _value(child, settings[key])
                elif name == "focus-follows-mouse":
                    settings["focus_follows_mouse"] = _value(item, True) is not False
                elif name == "workspace-auto-back-and-forth":
                    settings["workspace_auto_back_and_forth"] = _value(item, True) is not False
        elif node["name"] == "layout":
            for child in node["children"] or []:
                name = child["name"]
                if name in ("focus-ring", "border"):
                    key = name.replace("-", "_")
                    for part in child["children"] or []:
                        if part["name"] in ("on", "off"):
                            settings[key] = part["name"] == "on"
                        elif part["name"] == "width":
                            settings[key + "_width"] = _value(part, settings[key + "_width"])
                elif name == "default-column-width":
                    width = next((item for item in child["children"] or [] if item["name"] == "proportion"), None)
                    if width:
                        settings["column_width"] = _value(width, 0.5)
                else:
                    key = {"center-focused-column": "column_center"}.get(name, name.replace("-", "_"))
                    if key in GROUPS["desktop"]:
                        settings[key] = _value(child, settings[key])
        elif node["name"] == "cursor":
            for child in node["children"] or []:
                key = {"xcursor-size": "cursor_size", "hide-when-typing": "cursor_hide_when_typing"}.get(child["name"])
                if key:
                    settings[key] = _value(child, settings[key])
    return settings, retained


def _saved(path):
    try:
        saved = json.loads(path.read_text())
    except FileNotFoundError:
        return {"version": 1, "groups": {}, "hash": None}
    if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(saved.get("groups"), dict):
        raise RuntimeError(_error("Invalid saved desktop settings", "保存的桌面设置无效"))
    for group, values in saved["groups"].items():
        validate_settings(group, values)
    return saved


def read_state(*, base=None, state_path=None):
    base, state_path = Path(base or BASE), Path(state_path or _state_path())
    settings, retained = _source(base)
    focus_from_source = settings["focus_follows_mouse"]
    saved = _saved(state_path)
    for values in saved["groups"].values():
        settings.update(values)
    custom_keymap = any(node["name"] == "file" for node in retained["xkb"])
    return {"settings": settings, "configured": list(saved["groups"]), "path": str(base / GENERATED),
            "custom_keymap": custom_keymap, "focus_from_source": focus_from_source}


def _literal(value):
    return json.dumps(value, ensure_ascii=False)


def render_settings(groups, retained=None):
    retained = retained or {"keyboard": [], "xkb": [], "mouse": [], "touchpad": []}
    lines = [HEADER]
    for group, values in groups.items():
        validate_settings(group, values)
    if "input" in groups:
        values = groups["input"]
        lines.extend(["input {", "    keyboard {", "        xkb {"])
        for key in ("layout", "variant", "options"):
            lines.append(f"            {key} {_literal(values['keyboard_' + key])}")
        for node in retained["xkb"]:
            if node["name"] not in ("layout", "variant", "options"):
                lines.append(_render_node(node, 12).rstrip())
        lines.append("        }")
        managed = {"repeat-delay", "repeat-rate", "numlock", "track-layout"}
        for key in sorted(managed):
            lines.append(f"        {key} {_literal(values['keyboard_' + key.replace('-', '_')])}")
        for node in retained["keyboard"]:
            if node["name"] not in managed:
                lines.append(_render_node(node, 8).rstrip())
        lines.append("    }")
        for kind in ("mouse", "touchpad"):
            lines.append(f"    {kind} {{")
            managed = {key.removeprefix(kind + "_").replace("_", "-") for key in values if key.startswith(kind + "_")}
            for key in sorted(managed):
                value = values[kind + '_' + key.replace('-', '_')]
                if isinstance(value, bool):
                    if value:
                        lines.append(f"        {key}")
                else:
                    lines.append(f"        {key} {_literal(value)}")
            for node in retained[kind]:
                if node["name"] not in managed:
                    lines.append(_render_node(node, 8).rstrip())
            lines.append("    }")
        lines.extend(["}", ""])
    if "desktop" in groups:
        values = groups["desktop"]
        lines.append("input {")
        if values["focus_follows_mouse"]:
            lines.append('    focus-follows-mouse max-scroll-amount="0%"')
        lines.extend([f"    workspace-auto-back-and-forth {_literal(values['workspace_auto_back_and_forth'])}", "}", "layout {"])
        for key in ("gaps", "always_center_single_column", "empty_workspace_above_first", "default_column_display"):
            lines.append(f"    {key.replace('_', '-')} {_literal(values[key])}")
        lines.extend([f"    center-focused-column {_literal(values['column_center'])}",
                      f"    default-column-width {{ proportion {values['column_width']}; }}"])
        for key in ("focus_ring", "border"):
            lines.append(f"    {key.replace('_', '-')} {{ {'on' if values[key] else 'off'}; width {values[key + '_width']}; }}")
        lines.extend(["}", "cursor {", f"    xcursor-size {values['cursor_size']}",
                      f"    hide-when-typing {_literal(values['cursor_hide_when_typing'])}", "}", ""])
    # A file accepts one input node; both pages share that node.
    nodes = _nodes("\n".join(lines))
    input_nodes = [node for node in nodes if node["name"] == "input"]
    if len(input_nodes) > 1:
        input_nodes[0]["children"].extend(input_nodes[1]["children"])
        nodes.remove(input_nodes[1])
    return HEADER + "\n" + "".join(_render_node(node) for node in nodes)


def _run(*args):
    try:
        result = subprocess.run(["niri", *args], text=True, capture_output=True, timeout=12)
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(str(error)) from error
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[-2000:])
    return result.stdout


def _validate_keymap(values, retained):
    # Niri's config parser checks KDL syntax; libxkbcommon checks actual layouts.
    if any(node["name"] == "file" for node in retained["xkb"]):
        raise ValueError(_error("A custom XKB file controls this keyboard. Remove its file setting before editing layouts here.",
                                "键盘由自定义 XKB 文件控制，请先移除 file 设置后再修改布局。"))
    class Names(ctypes.Structure):
        _fields_ = [(name, ctypes.c_char_p) for name in ("rules", "model", "layout", "variant", "options")]
    lib = ctypes.CDLL("libxkbcommon.so.0")
    lib.xkb_context_new.argtypes, lib.xkb_context_new.restype = [ctypes.c_int], ctypes.c_void_p
    lib.xkb_context_unref.argtypes = [ctypes.c_void_p]
    lib.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.POINTER(Names), ctypes.c_int]
    lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    lib.xkb_keymap_unref.argtypes = [ctypes.c_void_p]
    extras = {node["name"]: _value(node, "") for node in retained["xkb"]}
    names = Names(*[(extras.get(key, "") if key in ("model", "rules") else values["keyboard_" + key]).encode() or None
                    for key in ("rules", "model", "layout", "variant", "options")])
    context = lib.xkb_context_new(0)
    if not context:
        raise RuntimeError(_error("Cannot validate keyboard layout", "无法校验键盘布局"))
    try:
        keymap = lib.xkb_keymap_new_from_names(context, ctypes.byref(names), 0)
        if not keymap:
            raise ValueError(_error("Keyboard layout or variant is not installed", "键盘布局或变体未安装"))
        lib.xkb_keymap_unref(keymap)
    finally:
        lib.xkb_context_unref(context)


UNCHECKED = object()


def _identity(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError(_error("Settings path was replaced", "设置路径已被替换"))
    return (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns,
            info.st_ctime_ns, hashlib.sha256(path.read_bytes()).hexdigest())


def _atomic(path, text, *, expected=UNCHECKED, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(_error("Settings path was replaced", "设置路径已被替换"))
    handle, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not UNCHECKED and _identity(path) != expected:
            raise RuntimeError(_error("Settings changed during validation; edits preserved", "设置在校验期间发生变化，已保留改动"))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _commit(group, values, base, state_path):
    target = base / GENERATED
    with _lock(state_path):
        if target.is_symlink() or state_path.is_symlink():
            raise RuntimeError(_error("Settings path was replaced", "设置路径已被替换"))
        old = target.read_text() if target.exists() else ""
        original_target, original_state = _identity(target), _identity(state_path)
        if original_target is not None and _digest(old) != original_target[-1]:
            raise RuntimeError(_error("Settings changed while reading; edits preserved", "读取设置时发生变化，已保留改动"))
        saved = _saved(state_path)
        if saved.get("hash"):
            if _digest(old) != saved["hash"]:
                raise RuntimeError(_error("Generated settings were edited manually; edits preserved", "生成的设置已被手动修改，已保留改动"))
        elif any(line.strip() and not line.lstrip().startswith("//") for line in old.splitlines()):
            raise RuntimeError(_error("Existing desktop settings are not managed; edits preserved", "已有桌面设置不受面板管理，已保留改动"))
        source, retained = _source(base)
        if values is not None:
            if group == "desktop" and source["focus_follows_mouse"] and not values["focus_follows_mouse"]:
                raise ValueError(_error("Focus follows mouse is enabled in your original input config. Remove that rule there to disable it; Niri cannot unset it from an include.",
                                        "原输入配置启用了焦点跟随鼠标。请在那里移除该条目后关闭；Niri 无法通过后续引用取消该设置。"))
            if group == "input":
                _validate_keymap(values, retained)
            saved["groups"][group] = values
        else:
            saved["groups"].pop(group, None)
        contents = render_settings(saved["groups"], retained)
        main = (base / "config.kdl").read_text()
        nodes = _nodes(main)
        positions = [index for index, node in enumerate(nodes)
                     if node["name"] == "include" and f'"{GENERATED}"' in node["head"]]
        following = nodes[positions[-1] + 1:] if positions else nodes
        if len(positions) != 1 or any(node["name"] != "include" or '"conf/language.kdl"' not in node["head"] for node in following):
            raise RuntimeError(_error("Desktop settings include must be last in config.kdl", "桌面设置引用必须位于 config.kdl 末尾"))
        with tempfile.TemporaryDirectory(prefix="selandia-desktop-") as temporary:
            stage = Path(temporary) / "niri"
            for kdl_file in base.rglob("*.kdl"):
                if kdl_file.is_file():
                    dest = stage / kdl_file.relative_to(base)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(kdl_file, dest)
            (stage / GENERATED).parent.mkdir(parents=True, exist_ok=True)
            (stage / GENERATED).write_text(contents)
            _run("validate", "--config", str(stage / "config.kdl"))
        if _identity(target) != original_target or _identity(state_path) != original_state:
            raise RuntimeError(_error("Settings changed during validation; edits preserved", "设置在校验期间发生变化，已保留改动"))
        # Write a recovery copy before replacing the include atomically.
        _atomic(state_path.with_suffix(".backup.kdl"), old)
        installed = None
        try:
            _atomic(target, contents, expected=original_target)
            installed = _identity(target)
            if os.environ.get("NIRI_SOCKET"):
                _run("msg", "action", "load-config-file")
            saved["hash"] = _digest(contents)
            if _identity(target) != installed:
                raise RuntimeError(_error("Settings changed during reload; edits preserved", "设置在重载期间发生变化，已保留改动"))
            _atomic(state_path, json.dumps(saved, indent=2, ensure_ascii=False) + "\n", expected=original_state)
        except Exception:
            if installed is not None and _identity(target) == installed:
                if original_target is None:
                    target.unlink()
                else:
                    _atomic(target, old, expected=installed, mode=stat.S_IMODE(original_target[2]))
            if os.environ.get("NIRI_SOCKET"):
                try:
                    _run("msg", "action", "load-config-file")
                except RuntimeError:
                    pass
            raise
    return read_state(base=base, state_path=state_path)


def apply_settings(group, values, *, base=None, state_path=None):
    values = validate_settings(group, values)
    return _commit(group, values, Path(base or BASE), Path(state_path or _state_path()))


def restore_defaults(group, *, base=None, state_path=None):
    if group not in GROUPS:
        raise ValueError("Unknown settings group")
    return _commit(group, None, Path(base or BASE), Path(state_path or _state_path()))
