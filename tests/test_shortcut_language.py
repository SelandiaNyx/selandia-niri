"""Every shortcut renders as one language, with its action detail intact (A5).

Descriptions come from the real bindings in ``conf/binds.kdl``. The check is
script-based: built-in English text must not contain Chinese characters, Chinese
text must not repeat an English word, and workspace targets, directions, follow
behaviour and the screenshot save mode must survive in both languages.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import shortcuts

CJK = re.compile(r"[\u3400-\u9fff]")
# Words that legitimately stay Latin in an otherwise Chinese sentence.
KEEP_LATIN = {"Codex", "Niri", "XKB", "API", "Super", "Ctrl", "Print", "Shift", "Alt"}


class ShortcutLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = shortcuts.load_shortcuts()
        cls.by_key = {row["keys"]: row for row in cls.rows}

    def test_the_whole_binding_set_is_covered(self):
        self.assertGreater(len(self.rows), 100)
        self.assertFalse([row for row in self.rows if not row["description"][0] or not row["description"][1]])

    def test_english_text_never_contains_chinese(self):
        mixed = [row["keys"] for row in self.rows if CJK.search(row["description"][0])]
        self.assertEqual(mixed, [], "English descriptions still contain Chinese")

    def test_chinese_text_never_repeats_the_english_wording(self):
        leaked = []
        for row in self.rows:
            english, chinese = row["description"]
            for word in re.findall(r"[A-Za-z][A-Za-z+]{3,}", english):
                if word not in KEEP_LATIN and word in chinese:
                    leaked.append((row["keys"], word))
            if " / " in chinese or " / " in row["category"][1]:
                leaked.append((row["keys"], "legacy slash pair"))
        self.assertEqual(leaked, [], "Chinese descriptions still repeat English text")

    def test_categories_are_single_language_pairs(self):
        for row in self.rows:
            self.assertEqual(len(row["category"]), 2)
            self.assertFalse(CJK.search(row["category"][0]))
            self.assertNotEqual(row["category"], ("Custom", "自定义"),
                                "a documented binding must not fall through to Custom")

    def test_workspace_target_and_direction_survive(self):
        number = self.by_key["Super+1"]["description"]
        self.assertIn("workspace 1", number[0])
        self.assertIn("工作区 1", number[1])
        previous = self.by_key["Super+PageUp"]["description"]
        self.assertIn("previous workspace", previous[0])
        self.assertIn("上一个工作区", previous[1])

    def test_follow_behaviour_survives(self):
        follows = self.by_key["Super+Shift+1"]["description"]
        self.assertIn("window follows", follows[0])
        self.assertIn("窗口跟随", follows[1])
        # The focus=false variant is configurable rather than bound by default.
        stays = shortcuts.describe('move-window-to-workspace "1" focus=false;', "")
        self.assertIn("focus stays", stays[0])
        self.assertIn("焦点留在原处", stays[1])

    def test_screenshot_save_mode_is_not_lost(self):
        clipboard = self.by_key["Print"]["description"]
        self.assertIn("clipboard only", clipboard[0])
        self.assertIn("仅剪贴板", clipboard[1])
        saved = self.by_key["Ctrl+Print"]["description"]
        self.assertIn("save and clipboard", saved[0])
        self.assertIn("保存及剪贴板", saved[1])

    def test_direction_and_object_are_translated_not_dropped(self):
        row = self.by_key["Super+Left"]["description"]
        self.assertEqual(row[0], "Focus · Column · Left")
        self.assertEqual(row[1], "聚焦 · 列 · 左")

    def test_the_search_index_still_answers_both_languages(self):
        chinese = [row["keys"] for row in self.rows if "工作区" in row["search"]]
        english = [row["keys"] for row in self.rows if "workspace" in row["search"]]
        self.assertTrue(chinese)
        self.assertEqual(chinese, english, "the bilingual index must match the same bindings")

    def test_a_chinese_query_finds_a_binding_rendered_in_english(self):
        matches = [row for row in self.rows if "截图" in row["search"]]
        self.assertTrue(matches)
        for row in matches:
            self.assertNotIn("截图", row["description"][0])


if __name__ == "__main__":
    unittest.main()
