"""Small, explicit translations for this desktop's own interface text.

Device names, file paths, media metadata and chat messages are never translated.
The legacy helper is only for existing, UI-owned bilingual labels.
"""
from __future__ import annotations

import os
import re
import sys

_language_override = None
_CJK = re.compile(r"[\u3400-\u9fff]")


def get_language():
    try:
        from language_settings import resolve_ui_language
        return resolve_ui_language(_language_override)
    except (ImportError, OSError, ValueError):
        code = _language_override
        if not code or code == "system":
            code = os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG", "en_US")
        return "zh_CN" if str(code).lower().startswith("zh") else "en_US"


def set_language(code=None):
    """Change this process's language; persistence belongs to language_settings."""
    global _language_override
    if code not in (None, "system", "zh_CN", "en_US"):
        raise ValueError("Unsupported interface language")
    _language_override = code


def tr(english, chinese):
    return chinese if get_language() == "zh_CN" else english


# These phrases are not parallel translations, or have shortcuts/units that
# must remain visible in either language. Keep their meaning explicit.
_CATALOG = {
    "控制中心": ("Control Center", "控制中心"),
    "Control Center": ("Control Center", "控制中心"),
    "Keyboard Atlas": ("Keyboard shortcuts", "键盘快捷键"),
    "Intelligence": ("AI assistant", "AI 助手"),
    "控制中心  ·  Your desktop, at a touch": ("Your desktop, at a touch", "常用操作，触手可及"),
    "快捷键总览  ·  Find your next move": ("Find your next move", "快速查找按键与操作"),
    "AI 侧边栏  ·  A little room to think": ("A little room to think", "随时提问与思考"),
    "总览": ("Overview", "总览"), "声音": ("Sound", "声音"),
    "系统": ("System", "系统"), "屏幕": ("Displays", "屏幕"),
    "外观": ("Appearance", "外观"),
    "Ctrl + 1…5  切换页面 · Select page": ("Ctrl + 1…5  Select page", "Ctrl + 1…5  切换页面"),
    "Ctrl + Tab  下一页 · Next page": ("Ctrl + Tab  Next page", "Ctrl + Tab  下一页"),
    "Tab / Shift + Tab  移动焦点 · Move focus": ("Tab / Shift + Tab  Move focus", "Tab / Shift + Tab  移动焦点"),
    "Space / Enter  激活 · Activate": ("Space / Enter  Activate", "空格 / Enter  激活"),
    "← →  调节滑块 · Adjust slider": ("← →  Adjust slider", "← →  调节滑块"),
    "Esc  返回总览，再关闭 · Back, then close": ("Esc  Back, then close", "Esc  返回总览，再关闭"),
    "Close · 关闭  Esc": ("Close  Esc", "关闭  Esc"),
    "Keyboard help · 键盘操作  F1": ("Keyboard help  F1", "键盘操作  F1"),
    "2 s · 每两秒": ("Every 2 seconds", "每两秒"),
    "LIVE / 实时": ("LIVE", "实时"),
    "检测中…": ("Checking…", "检测中…"),
    "没有正在播放的音乐": ("Not playing", "没有正在播放的音乐"),
    "打开播放器开始聆听": ("Open a player to listen", "打开播放器开始聆听"),
    "等待播放器响应…": ("Waiting for player…", "等待播放器响应…"),
    "从一个想法开始。": ("Start with an idea.", "从一个想法开始。"),
    "Send  ↗  发送": ("Send  ↗", "发送  ↗"),
    "Mod = Super / Windows  ·  Esc = Close / 关闭": ("Mod = Super / Windows  ·  Esc = Close", "Mod = Super / Windows  ·  Esc = 关闭"),
    "Enter to send · 回车发送   /   Shift+Enter for newline · 换行": ("Enter to send  /  Shift+Enter for newline", "Enter 发送  /  Shift+Enter 换行"),
    "Search keys or actions…  搜索按键或功能…": ("Search keys or actions…", "搜索按键或功能…"),
    "静音 / 取消静音 · Mute / Unmute": ("Mute / Unmute", "静音 / 取消静音"),
    "亮度不可用 · 在更多控制中查看原因": ("Brightness unavailable; see More controls", "亮度不可用，在更多控制中查看原因"),
    "DDC/CI · Monitor brightness / 显示器硬件亮度": ("DDC/CI · Monitor brightness", "DDC/CI · 显示器硬件亮度"),
    "API base example · API 基地址示例: https://api.openai.com/v1": ("API base example: https://api.openai.com/v1", "API 基地址示例：https://api.openai.com/v1"),
    "Ollama · 本地模型": ("Ollama · Local models", "Ollama · 本地模型"),
    "OpenAI-compatible API · 兼容 API": ("OpenAI-compatible API", "OpenAI 兼容 API"),
    "CPU · 处理器": ("CPU", "CPU 处理器"),
    "RAM · 内存": ("Memory", "内存"),
    "GPU · 显卡": ("GPU", "GPU 显卡"),
}


def tr_legacy(value):
    """Select one language from a known, UI-owned legacy bilingual label.

    Prefer ``tr`` for new strings and formatted messages. This helper does not
    recursively inspect or translate arbitrary data after a diagnostic prefix.
    """
    if not isinstance(value, str) or not value:
        return value
    if value in _CATALOG:
        return tr(*_CATALOG[value])
    # Complete translations on separate lines are common in help paragraphs.
    if value.count("\n") == 1 and " · " not in value and "  /  " not in value:
        first, second = value.split("\n")
        if first.strip() and second.strip() and bool(_CJK.search(first)) != bool(_CJK.search(second)):
            english, chinese = (second, first) if _CJK.search(first) else (first, second)
            return tr(english, chinese)
    # Preserve any appended detail verbatim, including paths and user names.
    # A colon/newline can delimit error detail after the bilingual prefix.
    for separator in (" · ", "  /  "):
        if value.count(separator) != 1:
            continue
        first, second = value.split(separator, 1)
        tail = ""
        second_head = re.split(r"(: |：|\n)", second, maxsplit=1)
        if len(second_head) == 3:
            second, delimiter, detail = second_head
            tail = delimiter + detail
        if not first.strip() or not second.strip() or bool(_CJK.search(first)) == bool(_CJK.search(second)):
            continue
        english, chinese = (second, first) if _CJK.search(first) else (first, second)
        return tr(english.strip(), chinese.strip()) + tail
    return value


if __name__ == "__main__":
    if sys.argv[1:] == ["language"]:
        print(get_language())
    else:
        raise SystemExit("Usage: i18n.py language")
