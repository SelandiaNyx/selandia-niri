"""Documentation must not rot: relative links and referenced artifacts resolve.

The audit documents and the README carry 70+ relative links to evidence and
configuration, and nothing checked them. This test keeps that true as files move,
and it keeps the handover documents pointing at existing artifacts.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [ROOT / "README.md", ROOT / "VALIDATION.md"] + sorted((ROOT / ".validation").glob("*.md"))
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def relative_links(document):
    for match in LINK.finditer(document.read_text()):
        target = match.group(1).split("#")[0].strip()
        if not target or "://" in target or target.startswith(("mailto:", "#")):
            continue
        yield target


class DocumentationLinkTests(unittest.TestCase):
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
        names = {document.name for document in DOCUMENTS}
        for required in ("PROJECT_AUDIT.md", "FIXES.md"):
            self.assertIn(required, names)
        summary = ROOT / ".validation/fix-summary.json"
        self.assertTrue(summary.is_file())
        self.assertIn("verification_limits", summary.read_text())

    def test_fix_report_names_every_audit_item(self):
        report = (ROOT / ".validation/FIXES.md").read_text()
        for item in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
            self.assertIn(f"## {item} · ", report, f"{item} has no section in the fix report")


if __name__ == "__main__":
    unittest.main()
