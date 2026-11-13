"""Exercise the reviewed source patch without downloads, installation or GPUs."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import wallpaper_engine_compat as compat


class EngineCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="engine-patch-")
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name)
        self.target = self.source / compat.RELATIVE
        self.target.parent.mkdir(parents=True)
        self.web = self.source / compat.WEB_RELATIVE
        self.web.parent.mkdir(parents=True)
        self.web.write_text("// unrelated source\n" + compat.FPS_OLD + compat.STOP_OLD + "\n")
        self.audio = self.source / compat.AUDIO_RELATIVE
        self.audio.parent.mkdir(parents=True)
        self.audio.write_text(compat.CHANNELS_OLD + "\n" + compat.SIZE_OLD + "\n")
        self.media = self.source / compat.MEDIA_RELATIVE
        self.media.write_text(compat.LENGTH_OLD + "\n")

    def test_reviewed_texture_fix_is_idempotent_and_preserves_other_source(self):
        before = "// unrelated source\n" + compat.OLD + "\n"
        self.target.write_text(before)
        self.assertTrue(compat.apply(self.source))
        self.assertEqual(self.target.read_text(), before.replace(compat.OLD, compat.NEW))
        self.assertIn(compat.FPS_NEW, self.web.read_text())
        self.assertNotIn(compat.STOP_OLD, self.web.read_text())
        self.assertIn(compat.CHANNELS_NEW, self.audio.read_text())
        self.assertIn(compat.SIZE_NEW, self.audio.read_text())
        self.assertIn(compat.LENGTH_NEW, self.media.read_text())
        metadata = self.target.stat()
        self.assertFalse(compat.apply(self.source))
        self.assertEqual(self.target.stat().st_mtime_ns, metadata.st_mtime_ns)

    def test_changed_source_and_duplicate_matches_are_rejected_without_writes(self):
        for source in ("different renderer revision", compat.OLD + "\n" + compat.OLD):
            with self.subTest(source=source):
                self.target.write_text(source)
                with self.assertRaises(ValueError):
                    compat.apply(self.source)
                self.assertEqual(self.target.read_text(), source)

    def test_installed_and_linked_sources_are_rejected(self):
        with self.assertRaises(ValueError):
            compat.apply("/opt/linux-wallpaperengine")
        outside = self.source / "untouched.cpp"
        outside.write_text(compat.OLD)
        self.target.symlink_to(outside)
        with self.assertRaises(ValueError):
            compat.apply(self.source)
        self.assertEqual(outside.read_text(), compat.OLD)

    def test_mismatch_in_second_file_leaves_first_file_untouched(self):
        self.target.write_text(compat.OLD)
        self.web.write_text("different Web renderer")
        with self.assertRaises(ValueError):
            compat.apply(self.source)
        self.assertEqual(self.target.read_text(), compat.OLD)
        self.assertEqual(self.web.read_text(), "different Web renderer")

    def test_audio_mismatch_refuses_all_web_and_audio_mutations(self):
        self.target.write_text(compat.OLD)
        self.audio.write_text("different audio revision")
        before = self.web.read_text()
        with self.assertRaises(ValueError):
            compat.apply(self.source)
        self.assertEqual(self.target.read_text(), compat.OLD)
        self.assertEqual(self.web.read_text(), before)

    def test_media_source_mismatch_preserves_all_previous_hunks(self):
        self.target.write_text(compat.OLD)
        self.media.write_text("different media handler")
        before = {path: path.read_bytes() for path in (self.target, self.web, self.audio, self.media)}
        with self.assertRaises(ValueError):
            compat.apply(self.source)
        self.assertEqual(before, {path: path.read_bytes() for path in before})


if __name__ == "__main__":
    unittest.main()
