"""Language selection keeps translated UI separate from opaque user content."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
import i18n
import language_settings


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="selandia-i18n-")
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(os.environ, {"XDG_STATE_HOME": self.directory.name,
                                                   "LANG": "en_US.UTF-8", "LC_ALL": "", "LC_MESSAGES": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(i18n.set_language)
        i18n.set_language()

    def test_saved_ui_language_is_independent_of_terminal_locale(self):
        language_settings.save_ui_language("zh_CN")
        self.assertEqual(i18n.tr("Sound", "声音"), "声音")
        language_settings.save_ui_language("en_US")
        self.assertEqual(i18n.tr("Sound", "声音"), "Sound")

    def test_runtime_override_does_not_overwrite_saved_preference(self):
        language_settings.save_ui_language("en_US")
        i18n.set_language("zh_CN")
        self.assertEqual(i18n.get_language(), "zh_CN")
        self.assertEqual(language_settings.read_preferences()["ui_language"], "en_US")
        i18n.set_language()
        self.assertEqual(i18n.get_language(), "en_US")

    def test_system_language_and_explicit_language(self):
        with patch.dict(os.environ, {"LC_MESSAGES": "zh_CN.UTF-8"}):
            self.assertEqual(i18n.get_language(), "zh_CN")
            i18n.set_language("en_US")
            self.assertEqual(i18n.get_language(), "en_US")
        with self.assertRaises(ValueError):
            i18n.set_language("invalid")

    def test_legacy_static_labels_have_one_language(self):
        pairs = [
            ("音量 · Volume", "Volume", "音量"),
            ("OUTPUT  /  输出设备", "OUTPUT", "输出设备"),
            ("Settings saved · 设置已保存", "Settings saved", "设置已保存"),
            ("LIVE / 实时", "LIVE", "实时"),
            ("LIVE  /  实时监控", "LIVE", "实时监控"),
            ("A help sentence.\n帮助说明。", "A help sentence.", "帮助说明。"),
            ("帮助说明。\nA help sentence.", "A help sentence.", "帮助说明。"),
        ]
        for original, english, chinese in pairs:
            for language, expected in (("en_US", english), ("zh_CN", chinese)):
                with self.subTest(original=original, language=language):
                    i18n.set_language(language)
                    self.assertEqual(i18n.tr_legacy(original), expected)

    def test_legacy_keyboard_instructions_keep_keys(self):
        i18n.set_language("en_US")
        self.assertEqual(i18n.tr_legacy("Ctrl + 1…5  切换页面 · Select page"), "Ctrl + 1…5  Select page")
        i18n.set_language("zh_CN")
        self.assertEqual(i18n.tr_legacy("Close · 关闭  Esc"), "关闭  Esc")
        self.assertEqual(i18n.tr_legacy("Enter to send · 回车发送   /   Shift+Enter for newline · 换行"),
                         "Enter 发送  /  Shift+Enter 换行")

    def test_diagnostic_details_keep_cjk_filenames_and_newlines(self):
        detail = "/home/用户/音频.wav: permission denied"
        for language, prefix in (("en_US", "Audio unavailable"), ("zh_CN", "音频不可用")):
            i18n.set_language(language)
            self.assertEqual(i18n.tr_legacy("Audio unavailable · 音频不可用\n" + detail), prefix + "\n" + detail)
        i18n.set_language("en_US")
        self.assertEqual(i18n.tr_legacy("Could not apply · 无法应用: " + detail), "Could not apply: " + detail)

    def test_unknown_text_and_shared_technical_identifiers_are_unchanged(self):
        for language in ("en_US", "zh_CN"):
            i18n.set_language(language)
            for value in ("NVIDIA GPU", "/home/用户/notes.txt", "模型-local-7b", "2560x1440@144", "", None):
                self.assertEqual(i18n.tr_legacy(value), value)


if __name__ == "__main__":
    unittest.main()
