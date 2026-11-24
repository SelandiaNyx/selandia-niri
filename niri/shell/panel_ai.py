"""AI sidebar: profiles, chats, model discovery and cancellable requests.

Mixed into ``panel.Panel``; methods rely on the panel's shared state
(``self.work``, ``self.feedback`` and the widgets built in ``__init__``).
"""
from __future__ import annotations

import re
import subprocess
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gdk, Gtk

from i18n import tr, tr_legacy
from panel_support import box, button, label, pack, scroller

_CODE_FENCE_RE = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.DOTALL)


def _split_markdown_blocks(text: str) -> list[tuple[str, str, str]]:
    """Split text into ('text', '', chunk) and ('code', lang, code) blocks."""
    blocks: list[tuple[str, str, str]] = []
    pos = 0
    for match in _CODE_FENCE_RE.finditer(text):
        before = text[pos:match.start()].strip()
        if before:
            blocks.append(("text", "", before))
        blocks.append(("code", match.group(1).strip() or "code", match.group(2).rstrip("\n")))
        pos = match.end()
    tail = text[pos:].strip()
    if tail or not blocks:
        blocks.append(("text", "", tail if blocks else text))
    return blocks


class AiPage:
    def build_ai(self):
        import ai_store
        self.ai_request = None
        self.messages = []
        self.last_reply = ""
        self.ai_busy = False
        self.ai_saving = False
        self.model_generation = 0
        self.ai_refreshing = False
        settings_error = None
        try:
            self.workspace = ai_store.load()
        except (OSError, ValueError) as error:
            self.workspace = ai_store.defaults()
            settings_error = str(error)
        self.settings = dict(ai_store.profile(self.workspace)["settings"])
        toolbar = pack(self.content, box(False, 8))
        self.profile_choices = pack(toolbar, Gtk.ComboBoxText(), True)
        self.add_profile_button = pack(toolbar, button("+", self.add_ai_profile, tooltip=tr("Add connection", "新增连接配置")))
        pack(toolbar, button("⚙", self.toggle_settings, tooltip=tr_legacy("Connection settings · 连接设置")))
        history_row = pack(self.content, box(False, 8))
        self.conversation_choices = pack(history_row, Gtk.ComboBoxText(), True)
        self.new_chat_button = pack(history_row, button(tr("New chat", "新对话"), self.new_ai_chat))
        self.settings_box = box(spacing=8, css="card")
        self.settings_container = pack(self.content, scroller(self.settings_box))
        settings_height = min(340, max(120, self.available_height - 410))
        self.settings_container.set_min_content_height(settings_height)
        self.settings_container.set_max_content_height(settings_height)
        self.settings_container.set_propagate_natural_height(True)
        self.settings_container.set_no_show_all(True)
        pack(self.settings_box, label(tr_legacy("CONNECTION  /  连接设置"), "section-title"))
        pack(self.settings_box, label(tr("Connection name", "配置名称"), "hint"))
        self.profile_name = pack(self.settings_box, Gtk.Entry())
        self.profile_name.set_text(ai_store.profile(self.workspace)["name"])
        self.provider = Gtk.ComboBoxText()
        self.provider.append("ollama", tr_legacy("Ollama · 本地模型"))
        self.provider.append("openai-compatible", tr_legacy("OpenAI-compatible API · 兼容 API"))
        self.provider.set_active_id(self.settings.get("provider", "ollama"))
        pack(self.settings_box, self.provider)
        self.setting_entries = {}
        for key, title, fallback in [
            ("endpoint", tr_legacy("Server URL · 服务地址"), "http://127.0.0.1:11434"),
            ("model", tr_legacy("Model · 模型"), ""),
            ("api_key_env", tr_legacy("API key environment variable · 密钥环境变量名"), "OPENAI_API_KEY"),
        ]:
            pack(self.settings_box, label(title, "hint"))
            entry = Gtk.Entry()
            entry.set_text(str(self.settings.get(key, fallback)))
            entry.set_placeholder_text(fallback)
            pack(self.settings_box, entry)
            self.setting_entries[key] = entry
            entry.connect("changed", self.settings_edited)
            if key == "endpoint":
                pack(self.settings_box, label(tr_legacy("API base example · API 基地址示例: https://api.openai.com/v1"), "hint", wrap=True))
        self.provider.connect("changed", self.settings_edited)
        pack(self.settings_box, label(tr("Enter the environment variable name, never the key. After exporting keys, close this sidebar and run the command below from that terminal.",
                                        "只填环境变量名，不填密钥。设置环境变量后，关闭侧栏，再从该终端运行下方命令。"), "hint", wrap=True))
        pack(self.settings_box, label("~/.config/niri/scripts/desktop ai", "hint", localize=False)).set_selectable(True)
        settings_actions = pack(self.settings_box, box(False, 8))
        pack(settings_actions, button(tr_legacy("Find models · 查找模型"), self.find_models), True)
        pack(settings_actions, button(tr_legacy("Save · 保存"), self.save_ai_settings, "accent-button"), True)
        self.model_choices = Gtk.ComboBoxText()
        self.model_choices.set_no_show_all(True)
        self.model_choices.connect("changed", lambda combo: self.setting_entries["model"].set_text(combo.get_active_text() or ""))
        pack(self.settings_box, self.model_choices)
        self.provider_status = pack(self.content, label("", "provider-status", wrap=True))
        self.update_provider_status()
        self.chat_body = box(spacing=12)
        self.chat_scroll = pack(self.content, scroller(self.chat_body), True)
        self.welcome = None
        self._build_welcome()
        self.chat_scroll.get_vadjustment().connect("changed", self.scroll_chat)
        composer = pack(self.content, box(spacing=8, css="composer"))
        self.input = Gtk.TextView()
        self.input.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input.set_left_margin(10)
        self.input.set_right_margin(10)
        self.input.set_top_margin(10)
        self.input.set_bottom_margin(10)
        self.input.connect("key-press-event", self.input_key)
        input_scroll = scroller(self.input)
        input_scroll.set_min_content_height(82)
        input_scroll.set_max_content_height(150)
        pack(composer, input_scroll)
        composer_actions = pack(composer, box(False, 8))
        self.clear_button = pack(composer_actions, button(tr("Delete chat", "删除对话"), self.clear_chat))
        self.copy_button = pack(composer_actions, button(tr_legacy("Copy · 复制"), self.copy_reply))
        self.copy_button.set_sensitive(False)
        self.send_button = pack(composer_actions, button(tr_legacy("Send  ↗  发送"), self.send_chat, "accent-button"), True)
        self.stop_button = pack(composer_actions, button(tr("Stop", "停止"), self.stop_chat,
                                                       "accent-button", tooltip="Ctrl+."), True)
        self.stop_button.set_no_show_all(True)
        pack(composer, label(tr_legacy("Enter to send · 回车发送   /   Shift+Enter for newline · 换行"), "hint"))
        self.update_ai_workspace(self.workspace)
        self.profile_choices.connect("changed", self.choose_ai_profile)
        self.conversation_choices.connect("changed", self.choose_ai_chat)
        GLib.idle_add(self.input.grab_focus)
        if settings_error:
            self.feedback(settings_error, True)

    def _build_welcome(self):
        if self.welcome is not None:
            return
        self.welcome = self.card(self.chat_body)
        pack(self.welcome, label("✦", "welcome-icon"))
        pack(self.welcome, label(tr("Start with an idea.", "从一个想法开始。"), "welcome-title"))
        pack(self.welcome, label(tr("Ask, draft, debug, or explore. Connect Ollama locally or configure an API endpoint.",
                                    "提问、写作、调试或探索。连接本地 Ollama，或配置兼容 API 服务（支持流式输出与代码块复制）。"), "welcome-copy", wrap=True))
        pack(self.welcome, label(tr("Conversations are saved locally. Each keeps its own connection; only Send contacts that provider. API keys are never saved.",
                                   "对话保存在本机，每个对话保留自己的连接；点击发送才会联系该服务。密钥不会保存。"), "hint", wrap=True))
        self.welcome.show_all()

    def scroll_chat(self, adjustment):
        adjustment.set_value(max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size()))

    def toggle_settings(self):
        visible = not self.settings_container.get_visible()
        if visible:
            self.settings_container.set_no_show_all(False)
            self.settings_container.show_all()
            self.settings_container.set_no_show_all(True)
        else:
            self.settings_container.hide()

    def draft_settings(self):
        import ai_store
        settings = dict(ai_store.profile(self.workspace)["settings"])
        settings.update({key: entry.get_text().strip() for key, entry in self.setting_entries.items()})
        settings["provider"] = self.provider.get_active_id() or "ollama"
        return settings

    def settings_edited(self, *_):
        self.model_generation += 1

    def save_ai_settings(self):
        if self.ai_busy or self.ai_saving:
            self.feedback(tr("Wait for the current request.", "请等待当前请求完成。"), True)
            return
        import ai_store
        from ai_backend import validate_settings
        try:
            settings = validate_settings(self.draft_settings())
        except ValueError as error:
            self.feedback(str(error), True)
            return
        def saved():
            self.settings_container.hide()
            self.feedback(tr("Connection saved; previous conversations remain in history.", "连接已保存；原对话仍保留在历史中。"))
        identifier, name = self.workspace["active_profile"], self.profile_name.get_text().strip()
        self.ai_commit(lambda: ai_store.save_profile(identifier, name, settings), after=saved)

    def set_ai_sensitive(self, sensitive):
        for widget in (self.settings_box, self.send_button, self.clear_button, self.profile_choices,
                       self.conversation_choices, self.add_profile_button, self.new_chat_button):
            widget.set_sensitive(sensitive)

    def ai_commit(self, task, *, after=None, clear_input=False):
        if self.ai_busy or self.ai_saving:
            return
        self.ai_saving = True
        self.model_generation += 1
        self.set_ai_sensitive(False)
        def reset():
            self.ai_saving = False
            self.set_ai_sensitive(True)
        def done(value):
            reset()
            if clear_input:
                self.input.get_buffer().set_text("")
            self.update_ai_workspace(value)
            if after:
                after()
        def failed(error):
            reset()
            self.update_ai_workspace(self.workspace)
            self.feedback(error, True)
        self.work(task, done, failed, commit=True)

    def update_ai_workspace(self, value):
        import ai_store
        self.workspace = value
        self.ai_refreshing = True
        selected = ai_store.profile(value)
        self.profile_choices.remove_all()
        for profile in value["profiles"]:
            self.profile_choices.append(profile["id"], profile["name"])
        self.profile_choices.set_active_id(selected["id"])
        self.profile_name.set_text(selected["name"])
        self.provider.set_active_id(selected["settings"]["provider"])
        for key, entry in self.setting_entries.items():
            entry.set_text(selected["settings"][key])
        self.conversation_choices.remove_all()
        self.conversation_choices.append("new", tr("New conversation", "新对话"))
        for conversation in value["conversations"]:
            if conversation["profile_id"] == selected["id"]:
                title = conversation["title"][:36]
                if conversation["settings"] != selected["settings"]:
                    title += tr(" · earlier connection", " · 较早连接")
                self.conversation_choices.append(conversation["id"], title)
        conversation = ai_store.current_chat(value)
        self.conversation_choices.set_active_id(conversation["id"] if conversation else "new")
        self.settings = dict(conversation["settings"] if conversation else selected["settings"])
        self.messages = [dict(message) for message in conversation["messages"]] if conversation else []
        self.last_reply = next((m["content"] for m in reversed(self.messages) if m["role"] == "assistant"), "")
        self.copy_button.set_sensitive(bool(self.last_reply))
        if self.messages:
            for child in self.chat_body.get_children():
                child.destroy()
            self.welcome = None
            for message in self.messages:
                self.add_message(message["role"], message["content"])
        else:
            for child in self.chat_body.get_children():
                child.destroy()
            self.welcome = None
            self._build_welcome()
        self.update_provider_status()
        self.ai_refreshing = False

    def choose_ai_profile(self, combo):
        if self.ai_refreshing or self.ai_busy or self.ai_saving:
            return
        import ai_store
        identifier = combo.get_active_id()
        if identifier and identifier != self.workspace["active_profile"]:
            self.ai_commit(lambda: ai_store.select_profile(identifier))

    def choose_ai_chat(self, combo):
        if self.ai_refreshing or self.ai_busy or self.ai_saving:
            return
        import ai_store
        identifier = combo.get_active_id()
        if identifier:
            self.ai_commit(ai_store.new_chat if identifier == "new" else lambda: ai_store.select_chat(identifier))

    def add_ai_profile(self):
        import ai_store
        self.ai_commit(ai_store.add_profile, after=lambda: self.toggle_settings() if not self.settings_container.get_visible() else None)

    def new_ai_chat(self):
        import ai_store
        self.ai_commit(ai_store.new_chat)

    def update_provider_status(self):
        provider = tr_legacy("LOCAL · 本地") if self.settings.get("provider") == "ollama" else tr_legacy("API · 接口")
        model = self.settings.get("model") or tr_legacy("Choose a model in settings · 请在设置中选择模型")
        self.provider_status.set_text(f"●  {provider}  /  {model}")

    def find_models(self):
        if self.ai_busy or self.ai_saving:
            return
        from ai_backend import discover_models
        settings = self.draft_settings()
        self.model_generation += 1
        generation = self.model_generation
        self.feedback(tr_legacy("Looking for models… · 正在查找模型…"))

        def current():
            return generation == self.model_generation and settings == self.draft_settings()

        def found(models):
            if not current():
                return
            self.model_choices.remove_all()
            for model in models:
                self.model_choices.append_text(model)
            self.model_choices.set_visible(bool(models))
            if models:
                self.model_choices.set_active(0)
            self.feedback(tr(f"Found {len(models)} models", f"找到 {len(models)} 个模型") if models else tr_legacy("No models found. Check the server and install a model.\n未找到模型，请检查服务并安装模型。"), not bool(models))

        def failed(error):
            if current():
                self.feedback(error, True)
        self.work(lambda: discover_models(settings), found, failed)

    def input_key(self, widget, event):
        # Let Chinese and other IMEs confirm composition before Enter sends a chat.
        if widget.im_context_filter_keypress(event):
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not event.state & Gdk.ModifierType.SHIFT_MASK:
            self.send_chat()
            return True
        return False

    def _copy_snippet(self, snippet: str):
        self.work(lambda: subprocess.run(["wl-copy"], input=snippet, capture_output=True,
                                         text=True, check=True, timeout=5),
                  lambda _: self.feedback(tr("Code copied", "代码已复制")), commit=True)

    def add_message(self, role, text, *, streaming=False):
        if self.welcome:
            self.welcome.destroy()
            self.welcome = None
        bubble = pack(self.chat_body, box(spacing=6, css="message"))
        bubble.get_style_context().add_class("user-message" if role == "user" else "assistant-message")
        pack(bubble, label(tr("You", "你") if role == "user" else tr("Assistant", "助手"), "message-role"))
        primary_label = None
        blocks = [("text", "", text)] if streaming or role == "user" or "```" not in text else _split_markdown_blocks(text)
        for kind, lang, chunk in blocks:
            if kind == "code":
                code_card = pack(bubble, box(spacing=6, css="code-block"))
                code_head = pack(code_card, box(False, 8))
                pack(code_head, label(lang.upper(), "hint", localize=False), True)
                pack(code_head, button(tr("Copy", "复制"), lambda c=chunk: self._copy_snippet(c), "small-button"))
                code_lbl = pack(code_card, label(chunk, "code-text", wrap=True, localize=False))
                code_lbl.set_selectable(True)
                code_lbl.set_max_width_chars(44)
                if primary_label is None:
                    primary_label = code_lbl
            else:
                content = pack(bubble, label(chunk, "message-text", wrap=True, localize=False))
                content.set_selectable(True)
                content.set_max_width_chars(40)
                if primary_label is None:
                    primary_label = content
        bubble.show_all()
        return primary_label

    def stop_chat(self):
        request = self.ai_request
        if not self.ai_busy or not request:
            return
        if request.cancel() or request.cancelled:
            self.stop_button.set_sensitive(False)
            self.feedback(tr("Stopping…", "正在停止…"))
        else:
            self.feedback(tr("Saving reply…", "正在保存回复…"))

    def send_chat(self):
        if self.ai_busy or self.ai_saving:
            return
        buffer = self.input.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if not text:
            return
        if not self.settings.get("model"):
            self.feedback(tr_legacy("Choose a model in connection settings first.\n请先在连接设置中选择模型。"), True)
            if not self.settings_container.get_visible():
                self.toggle_settings()
            return
        from ai_backend import ChatRequest
        self.ai_busy = True
        self.model_generation += 1
        self.set_ai_sensitive(False)
        self.send_button.set_no_show_all(True)
        self.send_button.hide()
        self.stop_button.set_no_show_all(False)
        self.stop_button.show()
        self.stop_button.set_sensitive(True)
        self.send_button.set_label(tr_legacy("Thinking… · 思考中…"))
        self.messages.append({"role": "user", "content": text})
        self.add_message("user", text)
        buffer.set_text("")
        self.feedback(tr("Streaming reply…", "正在流式接收回复…"))
        pending = self.add_message("assistant", "•••", streaming=True)
        snapshot = [dict(message) for message in self.messages]
        settings = dict(self.settings)
        stream_buf = []
        stream_lock = threading.Lock()
        stream_scheduled = [False]

        def flush_stream():
            with stream_lock:
                stream_scheduled[0] = False
                full = "".join(stream_buf)
            if self.alive and self.ai_request is request and full:
                pending.set_text(full)
            return GLib.SOURCE_REMOVE

        def on_chunk(delta):
            with stream_lock:
                stream_buf.append(delta)
                if not stream_scheduled[0]:
                    stream_scheduled[0] = True
                    GLib.timeout_add(50, flush_stream)

        request = ChatRequest(snapshot, settings, on_chunk=on_chunk)
        self.ai_request = request
        import ai_store
        profile_id = self.workspace["active_profile"]
        conversation = ai_store.current_chat(self.workspace)
        chat_id = conversation["id"] if conversation else None
        before = snapshot[:-1]

        def reset():
            self.ai_busy = False
            self.ai_request = None
            self.stop_button.set_sensitive(False)
            self.stop_button.hide()
            self.stop_button.set_no_show_all(True)
            self.send_button.set_no_show_all(False)
            self.send_button.show()
            self.set_ai_sensitive(True)
            self.send_button.set_label(tr_legacy("Send  ↗  发送"))

        def replied(result):
            if self.ai_request is not request:
                return
            reset()
            self.update_ai_workspace(result)
            self.feedback("")

        def failed(error):
            if self.ai_request is not request:
                return
            reset()
            # work() converts exceptions to display text. Request state retains
            # the cancellation outcome without parsing translated messages.
            if request.cancelled:
                self.update_ai_workspace(self.workspace)
                if not buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
                    buffer.set_text(text)
                self.feedback(tr("Generation stopped", "已停止生成"))
            else:
                pending.set_text(tr_legacy("Could not reach the model · 无法获取模型回复"))
                self.messages.pop()
                if not buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
                    buffer.set_text(text)
                self.feedback(error, True)

        def request_and_save():
            response = request.run()
            return request.commit(lambda: ai_store.append_turn(profile_id, chat_id, settings, before, text, response))
        self.work(request_and_save, replied, failed, commit=True)

    def clear_chat(self):
        if self.ai_busy or self.ai_saving:
            return
        import ai_store
        self.ai_commit(ai_store.delete_chat, after=lambda: self.feedback(tr("Conversation deleted", "对话已删除")))

    def copy_reply(self):
        if self.last_reply:
            # wl-copy retains clipboard ownership after the sidebar closes.
            response = self.last_reply
            self.work(lambda: subprocess.run(["wl-copy"], input=response, capture_output=True,
                                              text=True, check=True, timeout=5),
                      lambda _: self.feedback(tr_legacy("Copied · 已复制")), commit=True)
