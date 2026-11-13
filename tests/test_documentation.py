"""Documentation must not rot: relative links and referenced artifacts resolve.

The audit documents and the README carry 70+ relative links to evidence and
configuration, and nothing checked them. This test keeps that true as files move,
and it keeps the handover documents pointing at existing artifacts.
"""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [ROOT / "README.md", ROOT / "VALIDATION.md"] + sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / ".validation").glob("*.md"))
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def relative_links(document):
    for match in LINK.finditer(document.read_text()):
        target = match.group(1).split("#")[0].strip()
        if not target or "://" in target or target.startswith(("mailto:", "#")):
            continue
        yield target


class DocumentationLinkTests(unittest.TestCase):
    def test_wallpaper_install_guides_name_aur_packages_and_hardware_limits(self):
        for document in (ROOT / "README.md", ROOT / "docs/INSTALL.md"):
            with self.subTest(document=document.name):
                text = document.read_text()
                for required in ("paru -S --needed mpvpaper linux-wallpaperengine-git",
                                 "yay -S --needed mpvpaper linux-wallpaperengine-git",
                                 "sudo", "assets", "nvidia-smi", "Intel/AMD", "实验性"):
                    self.assertIn(required, text)

    def test_wallpaper_guide_documents_units_migration_ratings_and_backend_limits(self):
        guide=(ROOT / "docs/WALLPAPERS.md").read_text()
        for phrase in ("16 个播放集", "1 秒", "10800 秒", "Everyone", "Questionable", "Mature", "不收集或保存口令",
                       "playlists", "兼容投影", "洗牌", "不支持", "SIGKILL", "--playlist-controls-probe-only"):
            self.assertIn(phrase,guide)

    def test_every_relative_link_resolves(self):
        broken = []
        for document in DOCUMENTS:
            for target in relative_links(document):
                if not (document.parent / target).exists():
                    broken.append(f"{document.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [], "documentation links point at missing files")

    def test_the_documents_exist_and_are_not_empty(self):
        for document in DOCUMENTS:
            with self.subTest(document=document.name):
                self.assertTrue(document.is_file())
                self.assertGreater(len(document.read_text().strip()), 200)

    def test_the_audit_set_is_complete(self):
        if (ROOT / "PORTABLE").is_file():
            self.skipTest("Portable exports omit the original machine's audit artifacts")
        names = {document.name for document in DOCUMENTS}
        for required in ("PROJECT_AUDIT.md", "FIXES.md"):
            self.assertIn(required, names)
        summary = ROOT / ".validation/fix-summary.json"
        self.assertTrue(summary.is_file())
        self.assertIn("verification_limits", summary.read_text())

    def test_fix_report_names_every_audit_item(self):
        if (ROOT / "PORTABLE").is_file():
            self.skipTest("Portable exports omit the original machine's audit artifacts")
        report = (ROOT / ".validation/FIXES.md").read_text()
        for item in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
            self.assertIn(f"## {item} · ", report, f"{item} has no section in the fix report")

    def test_current_settings_catalogue_matches_the_runtime_pages(self):
        if (ROOT / "PORTABLE").is_file():
            self.skipTest("Portable README is the installation guide, without the source feature catalogue")
        tree = ast.parse((ROOT / "niri/shell/navigation_catalog.py").read_text())
        pages = next(ast.literal_eval(node.value) for node in tree.body
                     if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "PAGES"
                                                             for target in node.targets))
        readme = (ROOT / "README.md").read_text()
        table = readme.split("| 分类 | 功能 |", 1)[1].split("\n\n", 1)[0]
        categories = [line.split("|")[1].strip() for line in table.splitlines()
                      if line.startswith("|") and "---" not in line]
        self.assertEqual(categories, [page[2] for page in pages])
        self.assertIn("F1** 或点击标题栏的 **? 帮助按钮", readme)
        self.assertNotIn("**F1 / ?**", readme)

    def test_current_validation_record_distinguishes_evidence_and_limits(self):
        if (ROOT / "PORTABLE").is_file():
            self.skipTest("Portable exports include checksums and target-machine validation instructions")
        current = (ROOT / "VALIDATION.md").read_text().split("## 2026-10-05", 1)[0]
        for requirement in ("2026-10-09", "分享包", "源码", "无显示服务器", "未执行真实睡眠"):
            self.assertIn(requirement, current)
        data = json.loads((ROOT / ".validation/p2p3-20261009/summary.json").read_text())
        self.assertEqual(data["date"], "2026-10-09")
        self.assertTrue(data["environment"])
        self.assertGreaterEqual(len(data["verification_limits"]), 3)


if __name__ == "__main__":
    unittest.main()
