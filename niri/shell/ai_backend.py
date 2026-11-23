"""Small chat transport. Credentials are read only from environment variables."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib import error, parse, request

DEFAULTS = {
    "provider": "ollama",
    "endpoint": "http://localhost:11434",
    "model": "",
    "api_key_env": "",
}
MAX_RESPONSE = 4 * 1024 * 1024
CHAT_REQUEST_TIMEOUT = 120
CANCEL_POLL_INTERVAL = 0.1
REAP_TIMEOUT = 2.0
WORKER_FLAG = "--chat-worker"
UNKNOWN_ERROR = "Chat request failed / 聊天请求失败"
TIMEOUT_ERROR = "AI request timed out / AI 请求超时"
INVALID_REPLY = "AI worker returned an invalid reply / AI 工作进程回复无效"


def settings_path():
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "selandia-niri/ai.json"


def validate_settings(settings, require_model=False):
    result = {key: str(settings.get(key, value)).strip() for key, value in DEFAULTS.items()}
    if result["provider"] not in ("ollama", "openai-compatible"):
        raise ValueError("Choose Ollama or OpenAI-compatible / 请选择服务类型")
    url = parse.urlsplit(result["endpoint"])
    try:
        loopback = ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        loopback = url.hostname == "localhost"
    if url.scheme not in ("http", "https") or not url.hostname:
        raise ValueError("Enter an http(s) server URL / 请输入有效服务地址")
    if url.scheme == "http" and not loopback:
        raise ValueError("Remote servers need HTTPS / 远程服务请使用 HTTPS")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("URL must not contain credentials, query or fragment / 地址不能含密码或查询参数")
    try:
        url.port
    except ValueError as exc:
        raise ValueError("Invalid server port / 服务端口无效") from exc
    result["endpoint"] = result["endpoint"].rstrip("/")
    if result["api_key_env"] and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", result["api_key_env"]):
        raise ValueError("Enter an environment variable name, not a key / 请填写环境变量名，而非密钥")
    if require_model and not result["model"]:
        raise ValueError("Choose a model in Settings first / 请先在设置中选择模型")
    return result


def load_settings():
    workspace = settings_path().with_name("ai-workspace.json")
    if workspace.exists():
        import ai_store
        return dict(ai_store.profile(ai_store.load())["settings"])
    path = settings_path()
    if not path.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("settings must be an object")
        return validate_settings(data)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read AI settings / AI 设置读取失败: {path}") from exc


def save_settings(settings):
    result = validate_settings(settings)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".ai-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A configured bearer token must never follow a cross-host redirect.
        return None


def _request(settings, suffix, payload=None, timeout=120):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    key_name = settings["api_key_env"]
    if key_name:
        key = os.environ.get(key_name, "")
        if not key:
            raise ValueError(f"Environment variable is unset / 环境变量未设置: {key_name}")
        if not key.isascii() or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ValueError("API key contains invalid characters / 密钥含无效字符，请检查环境变量")
        headers["Authorization"] = f"Bearer {key}"
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = request.Request(settings["endpoint"] + suffix, data=body, headers=headers)
    try:
        with request.build_opener(NoRedirect).open(req, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("Response too large / 服务响应过大")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object / 服务响应格式无效")
        if result.get("error"):
            # Do not echo arbitrary provider messages which may contain request data.
            raise ValueError("Provider returned an error; check model and server / 服务报错，请检查模型和服务")
        return result
    except error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ValueError(f"Server HTTP {code}; check endpoint, model and credentials / 请检查地址、模型和认证") from None
    except (error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("Cannot reach AI server or request timed out / 无法连接 AI 服务或请求超时") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Server did not return valid JSON / 服务未返回有效 JSON") from exc


def chat(messages, settings):
    settings = validate_settings(settings, require_model=True)
    clean = []
    for message in messages:
        if message.get("role") not in ("user", "assistant", "system") or not isinstance(message.get("content"), str):
            raise ValueError("Invalid chat message / 聊天消息无效")
        clean.append({"role": message["role"], "content": message["content"]})
    if not clean:
        raise ValueError("Write a message first / 请先输入消息")
    payload = {"model": settings["model"], "messages": clean, "stream": False}
    ollama = settings["provider"] == "ollama"
    data = _request(settings, "/api/chat" if ollama else "/chat/completions", payload)
    try:
        content = data["message"]["content"] if ollama else data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
        return content
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("No text answer returned; choose a text chat model / 未收到文本回复，请选择文本聊天模型") from None


def discover_models(settings):
    settings = validate_settings(settings)
    ollama = settings["provider"] == "ollama"
    data = _request(settings, "/api/tags" if ollama else "/models", timeout=10)
    try:
        models = data["models"] if ollama else data["data"]
        key = "name" if ollama else "id"
        return sorted({item[key] for item in models if isinstance(item.get(key), str)})
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Cannot read model list / 无法读取模型列表") from None


class Cancelled(Exception):
    """A chat request was cancelled before its reply was committed."""


_PENDING = "pending"
_RUNNING = "running"
_DONE = "done"
_COMMITTED = "committed"
_CANCELLED = "cancelled"
_FAILED = "failed"


class ChatRequest:
    """One cancellable chat turn, run in a short-lived worker process.

    ``run`` and ``commit`` are called from a background thread. ``cancel`` is
    called from the GTK thread: it only flips state under a short lock and
    returns immediately, while ``run`` polls and reaps the worker.
    """

    def __init__(self, messages, settings):
        self.messages = copy.deepcopy(list(messages))
        self.settings = copy.deepcopy(dict(settings))
        self._lock = threading.Lock()
        self._state = _PENDING
        self._cancelled = False
        self._process = None
        self._reply = None

    @property
    def cancelled(self):
        return self._cancelled

    def run(self):
        """Background thread: run the configured ``chat`` in a worker process."""
        with self._lock:
            if self._state != _PENDING or self._cancelled:
                raise Cancelled("Chat request cancelled / 聊天请求已取消")
            self._state = _RUNNING
        try:
            reply = self._run_worker()
        except Cancelled:
            with self._lock:
                self._cancelled = True
                self._state = _CANCELLED
            raise
        except BaseException:
            with self._lock:
                if self._cancelled:
                    self._state = _CANCELLED
                    raise Cancelled("Chat request cancelled / 聊天请求已取消") from None
                self._state = _FAILED
            raise
        with self._lock:
            if self._state == _CANCELLED or self._cancelled:
                self._cancelled = True
                self._state = _CANCELLED
                raise Cancelled("Chat request cancelled / 聊天请求已取消")
            self._reply = reply
            self._state = _DONE
        return reply

    def cancel(self):
        """GTK thread: accept cancellation before commit started. Returns bool."""
        with self._lock:
            if self._cancelled or self._state in (_COMMITTED, _FAILED):
                return False
            self._cancelled = True
            self._state = _CANCELLED
            return True

    def commit(self, callback):
        """Background thread: run the saving callback once run has finished."""
        with self._lock:
            if self._cancelled or self._state == _CANCELLED:
                raise Cancelled("Chat request cancelled / 聊天请求已取消")
            if self._state != _DONE:
                raise RuntimeError("Chat request is not ready to commit / 聊天请求尚未完成")
            self._state = _COMMITTED
        # The callback saves the reply and runs without the state lock, so a
        # cancel arriving now returns False immediately and never kills it.
        return callback()

    def _run_worker(self):
        deadline = time.monotonic() + CHAT_REQUEST_TIMEOUT
        payload = json.dumps({"messages": self.messages, "settings": self.settings}, ensure_ascii=False).encode()
        try:
            process = subprocess.Popen(
                [sys.executable, "-B", str(Path(__file__).resolve()), WORKER_FLAG],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
        except OSError as exc:
            raise ValueError("Cannot start the AI worker / 无法启动 AI 工作进程") from exc
        with self._lock:
            cancelled = self._cancelled
            if not cancelled:
                self._process = process
        if cancelled:
            self._reap(process)
            raise Cancelled("Chat request cancelled / 聊天请求已取消")
        try:
            stdout = self._wait(process, payload, deadline)
        finally:
            self._reap(process)
            with self._lock:
                self._process = None
        return self._reply_from(stdout)

    def _wait(self, process, payload, deadline):
        # communicate applies its timeout while writing stdin too: even a
        # worker stalled before reading a large history remains cancellable.
        while True:
            if self._cancelled:
                raise Cancelled("Chat request cancelled / 聊天请求已取消")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(TIMEOUT_ERROR)
            try:
                stdout, _ = process.communicate(input=payload, timeout=min(CANCEL_POLL_INTERVAL, remaining))
            except subprocess.TimeoutExpired:
                payload = None
                continue
            return stdout

    @classmethod
    def _reap(cls, process):
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.wait(timeout=REAP_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=REAP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass

    @staticmethod
    def _reply_from(stdout):
        try:
            message = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError, AttributeError):
            raise ValueError(INVALID_REPLY) from None
        if not isinstance(message, dict):
            raise ValueError(INVALID_REPLY)
        if message.get("error"):
            raise ValueError(str(message["error"]))
        reply = message.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError(INVALID_REPLY)
        return reply


def _emit_worker(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _chat_worker():
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        messages, settings = request["messages"], request["settings"]
    except (UnicodeError, ValueError, KeyError, TypeError):
        _emit_worker({"error": "Invalid worker request / 工作进程请求无效"})
        return
    try:
        reply = chat(messages, settings)
    except ValueError as exc:
        # chat/validate_settings only raise curated, credential-free messages.
        _emit_worker({"error": str(exc)})
    except BaseException:
        # Never leak an unknown traceback (it could contain request data).
        _emit_worker({"error": UNKNOWN_ERROR})
    else:
        _emit_worker({"reply": reply})


if __name__ == "__main__" and WORKER_FLAG in sys.argv[1:]:
    _chat_worker()
