"""Every interface string must be a genuine single-language pair (audit gap).

The control centre, the panels and the desktop scripts are covered here at the
text level: all ``tr(english, chinese)`` literals in the shell sources are parsed
and checked, so a page cannot ship a mixed sentence in either language without a
test failing. Visual state combinations that need a compositor are listed in the
audit document instead of being asserted here.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "niri/shell"
CJK = re.compile(r"[\u3400-\u9fff]")
# Latin words that legitimately stay Latin inside a Chinese sentence.
# Commands and paths shown verbatim inside a Chinese sentence.
COMMAND_PHRASES = {"sudo locale-gen"}


def pairs(path):
    """Yield every literal ``tr(english, chinese)`` pair in one module."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "tr":
            continue
        if len(node.args) != 2:
            continue
        english, chinese = node.args
        if isinstance(english, ast.Constant) and isinstance(chinese, ast.Constant) \
                and isinstance(english.value, str) and isinstance(chinese.value, str):
            yield node.lineno, english.value, chinese.value


class InterfaceStringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = []
        for path in sorted(SHELL.glob("*.py")):
            for line, english, chinese in pairs(path):
                cls.entries.append((path.name, line, english, chinese))
        if len(cls.entries) < 200:
            raise AssertionError("the interface catalogue looks incomplete: " + str(len(cls.entries)))

    def test_every_pair_has_both_languages(self):
        for name, line, english, chinese in self.entries:
            with self.subTest(module=name, line=line):
                self.assertTrue(english.strip(), f"{name}:{line} has no English text")
                self.assertTrue(chinese.strip(), f"{name}:{line} has no Chinese text")

    def test_english_text_never_contains_chinese(self):
        broken = [(name, line, english) for name, line, english, _ in self.entries if CJK.search(english)]
        self.assertEqual(broken, [], "English interface text still contains Chinese")

    def test_chinese_text_never_carries_a_legacy_bilingual_pair(self):
        # The defect signature is "English phrase / 中文" inside one string; a
        # slash between two Chinese phrases or between key names is legitimate.
        broken = []
        for name, line, _english, chinese in self.entries:
            if re.search(r"[A-Za-z][A-Za-z ]* / [\u3400-\u9fff]", chinese):
                broken.append((name, line, chinese))
        self.assertEqual(broken, [], "Chinese interface text still contains an English/Chinese pair")

    def test_chinese_text_does_not_repeat_an_english_sentence(self):
        # Single product names (Niri, BlueZ, PipeWire …) stay Latin by design;
        # a run of English words in a Chinese sentence is the real defect.
        broken = []
        for name, line, _english, chinese in self.entries:
            for phrase in re.findall(r"[A-Za-z@][A-Za-z0-9@._+-]{1,}(?: [A-Za-z0-9@._+-]{2,})+", chinese):
                if phrase in COMMAND_PHRASES:
                    continue
                broken.append((name, line, phrase))
        self.assertEqual(broken, [], "Chinese interface text repeats an English sentence")

    def test_no_pair_is_an_untouched_copy_with_script_only_on_one_side(self):
        # A pair may legitimately be identical (a name, a key, a symbol), but a
        # CJK-only Chinese side next to identical text would hide a missed copy.
        for name, line, english, chinese in self.entries:
            if english == chinese:
                with self.subTest(module=name, line=line):
                    self.assertFalse(CJK.search(english),
                                     f"{name}:{line} copies Chinese into both languages")

    def test_screencast_and_shortcut_helpers_are_covered(self):
        # The shortcut descriptions are structured pairs rather than tr() calls.
        sys.path.insert(0, str(SHELL))
        import shortcuts
        rows = shortcuts.load_shortcuts()
        self.assertGreater(len(rows), 100)
        for row in rows:
            with self.subTest(keys=row["keys"]):
                self.assertFalse(CJK.search(row["description"][0]))
                self.assertTrue(row["description"][1])


if __name__ == "__main__":
    unittest.main()
