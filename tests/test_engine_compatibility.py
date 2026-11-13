"""A local backend must match the installed ABI and remain confined to its child."""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import engine_compatibility as compat


class LocalCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-engine-overlay-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binary, self.library = self.root / "installed-bin", self.root / "installed-lib"
        self.local = self.root / "local"
        self.local.mkdir()
        for path, data in ((self.binary, b"base executable"), (self.library, b"base library"), (self.local / compat.LOCAL_NAME, b"tested patched library")):
            path.write_bytes(data)
        self.manifest = {"version": 1, "architecture": platform.machine(), "base_binary_sha256": compat.fingerprint(self.binary),
                         "base_library_sha256": compat.fingerprint(self.library), "patched_library_sha256": compat.fingerprint(self.local / compat.LOCAL_NAME)}
        self.write()
        for name, value in (("BINARY", self.binary), ("LIBRARY", self.library)):
            context = patch.object(compat, name, value)
            context.start()
            self.addCleanup(context.stop)
        context = patch.dict(os.environ, SELANDIA_ENGINE_COMPAT_DIR=str(self.local))
        context.start()
        self.addCleanup(context.stop)

    def write(self):
        (self.local / "compatibility.json").write_text(json.dumps(self.manifest))

    def test_verified_overlay_is_child_only_and_preserves_existing_library_path(self):
        before = dict(os.environ)
        result = compat.environment({"LD_LIBRARY_PATH": "/existing"})
        self.assertEqual(result["LD_LIBRARY_PATH"].split(":")[0], str(self.local))
        self.assertTrue(result["LD_LIBRARY_PATH"].endswith(":/existing"))
        self.assertEqual(dict(os.environ), before)

    def test_upgraded_base_package_disables_the_stale_overlay(self):
        for path in (self.binary, self.library):
            before = path.read_bytes()
            path.write_bytes(b"upgraded")
            self.assertIsNone(compat.compatible_directory())
            self.assertEqual(compat.environment({"LD_LIBRARY_PATH": "original"}), {"LD_LIBRARY_PATH": "original"})
            path.write_bytes(before)

    def test_changed_local_library_and_wrong_architecture_are_rejected(self):
        (self.local / compat.LOCAL_NAME).write_bytes(b"unexpected binary")
        self.assertIsNone(compat.compatible_directory())
        self.manifest["architecture"] = "wrong-architecture"
        self.write()
        self.assertIsNone(compat.compatible_directory())

    def test_missing_or_malformed_metadata_does_not_block_normal_backend(self):
        for text in ("[]", "invalid json", "{}"):
            (self.local / "compatibility.json").write_text(text)
            self.assertIsNone(compat.compatible_directory())
