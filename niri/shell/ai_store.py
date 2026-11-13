"""Private, atomic AI profiles and conversations; credentials stay in the environment."""
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid

import ai_backend

MAX_BYTES = 8 * 1024 * 1024
TEMPLATES = (
    ("ollama", "Ollama", "ollama", "http://localhost:11434", ""),
    ("relay", "Relay / 中转站", "openai-compatible", "https://example.invalid/v1", "RELAY_API_KEY"),
    ("google", "Google Gemini", "openai-compatible", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    ("deepseek", "DeepSeek", "openai-compatible", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    ("openai", "OpenAI API", "openai-compatible", "https://api.openai.com/v1", "OPENAI_API_KEY"),
)


def path():
    return ai_backend.settings_path().with_name("ai-workspace.json")


def defaults(legacy=None):
    profiles = [{"id": identifier, "name": name,
                 "settings": dict(ai_backend.DEFAULTS, provider=provider, endpoint=endpoint, api_key_env=key)}
                for identifier, name, provider, endpoint, key in TEMPLATES]
    active = "ollama"
    if legacy and legacy != ai_backend.DEFAULTS:
        settings = ai_backend.validate_settings(legacy)
        if settings["provider"] == "ollama":
            profiles[0]["settings"] = settings
        else:
            active = "imported"
            profiles.insert(0, {"id": active, "name": "Imported / 已有连接", "settings": settings})
    return {"version": 1, "profiles": profiles, "conversations": [], "active_profile": active, "active_chats": {}}


def _string(value, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(char) < 32 for char in value):
        raise ValueError("Invalid AI profile or conversation name / AI 配置或对话名称无效")
    return value


def _settings(value):
    if not isinstance(value, dict) or set(value) - set(ai_backend.DEFAULTS) or any(not isinstance(v, str) for v in value.values()):
        raise ValueError("Only connection fields and key environment names may be saved / 仅可保存连接字段及密钥环境变量名")
    return ai_backend.validate_settings(value)


def validate(value):
    if not isinstance(value, dict) or value.get("version") != 1 or set(value) != {"version", "profiles", "conversations", "active_profile", "active_chats"}:
        raise ValueError("Invalid AI workspace / AI 工作区无效")
    profiles, conversations = value["profiles"], value["conversations"]
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 24 or not isinstance(conversations, list) or len(conversations) > 200:
        raise ValueError("AI workspace limit: 24 profiles, 200 conversations / 最多 24 套配置、200 个对话")
    ids, chats = set(), set()
    result = deepcopy(value)
    for profile in result["profiles"]:
        if not isinstance(profile, dict) or set(profile) != {"id", "name", "settings"}:
            raise ValueError("Invalid AI profile / AI 配置无效")
        identifier = _string(profile["id"])
        if identifier in ids:
            raise ValueError("Duplicate AI profile / AI 配置重复")
        ids.add(identifier)
        _string(profile["name"])
        profile["settings"] = _settings(profile["settings"])
    for conversation in result["conversations"]:
        if not isinstance(conversation, dict) or set(conversation) != {"id", "profile_id", "settings", "title", "messages"}:
            raise ValueError("Invalid conversation / 对话无效")
        identifier = _string(conversation["id"])
        if identifier in chats or conversation["profile_id"] not in ids:
            raise ValueError("Invalid conversation owner / 对话所属配置无效")
        chats.add(identifier)
        _string(conversation["title"], 120)
        conversation["settings"] = _settings(conversation["settings"])
        messages = conversation["messages"]
        if not isinstance(messages, list) or len(messages) > 2000:
            raise ValueError("Conversation is too long / 对话过长，请新建对话")
        for message in messages:
            if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in ("user", "assistant", "system") or not isinstance(message["content"], str) or len(message["content"]) > 65536:
                raise ValueError("Invalid conversation message / 对话消息无效")
    if result["active_profile"] not in ids or not isinstance(result["active_chats"], dict):
        raise ValueError("Invalid active AI profile / 当前 AI 配置无效")
    for profile, chat in result["active_chats"].items():
        if profile not in ids or not any(c["id"] == chat and c["profile_id"] == profile for c in result["conversations"]):
            raise ValueError("Invalid active conversation / 当前对话无效")
    return result


def load():
    target = path()
    try:
        if not target.exists():
            return defaults(ai_backend.load_settings())
        if target.is_symlink() or target.stat().st_size > MAX_BYTES:
            raise ValueError("Invalid workspace file")
        return validate(json.loads(target.read_text()))
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError("Cannot read AI workspace; the original file was preserved / AI 工作区读取失败，原文件已保留") from error


@contextmanager
def _lock():
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_suffix(".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _write(value):
    value = validate(value)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("AI history storage is full; delete an old conversation / AI 历史存储已满，请删除旧对话")
    target = path()
    if target.is_symlink():
        raise ValueError("AI workspace must not be a symlink / AI 工作区不能是软链接")
    descriptor, name = tempfile.mkstemp(prefix=".ai-workspace-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)
    return value


def update(operation):
    with _lock():
        value = load()
        operation(value)
        return _write(value)


def profile(value, identifier=None):
    identifier = identifier or value["active_profile"]
    return next(p for p in value["profiles"] if p["id"] == identifier)


def current_chat(value):
    identifier = value["active_chats"].get(value["active_profile"])
    return next((c for c in value["conversations"] if c["id"] == identifier), None)


def select_profile(identifier):
    def operation(value):
        profile(value, identifier)
        value["active_profile"] = identifier
    return update(operation)


def save_profile(identifier, name, settings):
    settings, name = _settings(settings), _string(name.strip())
    def operation(value):
        selected = profile(value, identifier)
        if selected["settings"] != settings:
            # Old histories retain their connection snapshot. Never send them to
            # a new endpoint/model implicitly after editing the current profile.
            value["active_chats"].pop(identifier, None)
        selected.update(name=name, settings=settings)
    return update(operation)


def add_profile():
    def operation(value):
        identifier = uuid.uuid4().hex
        value["profiles"].append({"id": identifier, "name": "Custom / 自定义", "settings": dict(ai_backend.DEFAULTS)})
        value["active_profile"] = identifier
    return update(operation)


def new_chat():
    return update(lambda value: value["active_chats"].pop(value["active_profile"], None))


def select_chat(identifier):
    def operation(value):
        selected = next(c for c in value["conversations"] if c["id"] == identifier and c["profile_id"] == value["active_profile"])
        value["active_chats"][value["active_profile"]] = selected["id"]
    return update(operation)


def delete_chat():
    def operation(value):
        selected = current_chat(value)
        if selected:
            value["conversations"].remove(selected)
            value["active_chats"].pop(value["active_profile"], None)
    return update(operation)


def append_turn(profile_id, chat_id, settings, before, prompt, answer):
    def operation(value):
        selected = next((c for c in value["conversations"] if c["id"] == chat_id and c["profile_id"] == profile_id), None)
        if selected is None:
            if chat_id or before:
                raise ValueError("Conversation changed while waiting / 等待期间对话已变化")
            selected = {"id": uuid.uuid4().hex, "profile_id": profile_id, "settings": _settings(settings),
                        "title": " ".join(prompt.split())[:80] or "Conversation", "messages": []}
            value["conversations"].append(selected)
        if selected["messages"] != before or selected["settings"] != settings:
            raise ValueError("Conversation changed while waiting / 等待期间对话已变化")
        selected["messages"].extend(({"role": "user", "content": prompt}, {"role": "assistant", "content": answer}))
        value["active_chats"][profile_id] = selected["id"]
    return update(operation)
