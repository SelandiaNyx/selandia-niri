"""Ratchet test preventing new legacy 'English · 中文' literals in niri/shell."""
import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "niri/shell"
sys.path.insert(0, str(SHELL))

import audio_backend
import brightness
import display_backend
import i18n

CJK = re.compile(r"[\u3400-\u9fff]")
RATCHET_CEILING = 169
MIGRATED_MODULES = ("audio_backend.py", "brightness.py", "display_backend.py")


def legacy_bilingual_literals(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, text) for string constants with English/Chinese across ' · '."""
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and " · " in node.value:
            parts = node.value.split(" · ", 1)
            if len(parts) == 2 and bool(CJK.search(parts[0])) != bool(CJK.search(parts[1])):
                found.append((node.lineno, node.value))
    return found


class I18nRatchetTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(None)

    def test_migrated_backends_have_zero_legacy_bilingual_literals(self):
        for name in MIGRATED_MODULES:
            with self.subTest(module=name):
                self.assertEqual(legacy_bilingual_literals(SHELL / name), [])

    def test_shell_legacy_bilingual_literal_count_never_increases(self):
        total = 0
        for path in sorted(SHELL.glob("*.py")):
            if path.name == "i18n.py":
                continue
            total += len(legacy_bilingual_literals(path))
        self.assertLessEqual(
            total, RATCHET_CEILING,
            f"Legacy 'English · 中文' count increased to {total} (ceiling {RATCHET_CEILING}); use tr(en, zh).",
        )

    def test_migrated_backends_switch_cleanly_between_english_and_chinese(self):
        i18n.set_language("en_US")
        self.assertEqual(audio_backend._description({"name": "analog-output-headphones"}), "Headphones")
        with self.assertRaisesRegex(ValueError, "^Brightness must be 0–100%$"):
            brightness.set_percent("ddc:1", 200)
        with self.assertRaisesRegex(ValueError, "^Incomplete display settings$"):
            display_backend.validate_settings({})

        i18n.set_language("zh_CN")
        self.assertEqual(audio_backend._description({"name": "analog-output-headphones"}), "耳机")
        with self.assertRaisesRegex(ValueError, "^亮度必须在 0–100% 范围内$"):
            brightness.set_percent("ddc:1", 200)
        with self.assertRaisesRegex(ValueError, "^屏幕设置不完整$"):
            display_backend.validate_settings({})


if __name__ == "__main__":
    unittest.main()
