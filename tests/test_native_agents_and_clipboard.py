"""Unit tests for Tier-1 native replacements: Polkit/BlueZ agent, visual clipboard & autostart cleanup."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))

import clipboard_menu
import polkit_agent
import session_cleanup
import session_settings


class NativePolkitAndBluezAgentTests(unittest.TestCase):
    def test_dbus_introspection_xml_parses_cleanly(self):
        pk_node = Gio.DBusNodeInfo.new_for_xml(polkit_agent.POLKIT_AGENT_XML)
        self.assertEqual(pk_node.interfaces[0].name, "org.freedesktop.PolicyKit1.AuthenticationAgent")
        pk_methods = {m.name for m in pk_node.interfaces[0].methods}
        self.assertEqual(pk_methods, {"BeginAuthentication", "CancelAuthentication"})

        bz_node = Gio.DBusNodeInfo.new_for_xml(polkit_agent.BLUEZ_AGENT_XML)
        self.assertEqual(bz_node.interfaces[0].name, "org.bluez.Agent1")
        bz_methods = {m.name for m in bz_node.interfaces[0].methods}
        self.assertTrue({"RequestConfirmation", "RequestPinCode", "RequestPasskey", "Cancel"}.issubset(bz_methods))

    def test_parse_identities_prioritizes_current_user_and_resolves_names(self):
        uid = os.getuid()
        items = polkit_agent.parse_identities([
            ("unix-user", {"uid": 0}),
            ("unix-user", {"uid": uid}),
        ])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["uid"], uid)
        self.assertEqual(items[1]["uid"], 0)
        self.assertIsNotNone(items[0]["identity"])

    def test_format_passkey_zero_pads_and_groups(self):
        self.assertEqual(polkit_agent.format_passkey(42), "000 042")
        self.assertEqual(polkit_agent.format_passkey(482910), "482 910")


class NativeClipboardManagerTests(unittest.TestCase):
    def test_parse_entries_detects_text_and_binary_images(self):
        sample = (
            "101\tHello Selandia Niri\n"
            "102\t[[ binary data 48 KiB png 1920x1080 ]]\n"
            "103\thttps://archlinux.org/\n"
            "104\t[[ binary data 12 KiB jpeg 640x480 ]]\n"
        )
        entries = clipboard_menu.parse_entries(sample)
        self.assertEqual(len(entries), 4)
        self.assertFalse(entries[0]["is_image"])
        self.assertEqual(entries[0]["id"], "101")
        self.assertTrue(entries[1]["is_image"])
        self.assertFalse(entries[2]["is_image"])
        self.assertTrue(entries[3]["is_image"])


class ReversibleSessionCleanupTests(unittest.TestCase):
    def test_niri_autostart_shadows_are_created_and_cleanly_restored(self):
        with tempfile.TemporaryDirectory(prefix="selandia-cleanup-") as tmp:
            root = Path(tmp)
            cfg = root / "config"
            state = root / "state/session-settings-backup.json"
            written = session_cleanup.ensure(home=cfg, state_path=state)
            self.assertEqual(sorted(written), ["blueman.desktop", "nm-applet.desktop"])
            self.assertIn("NotShowIn=niri;", (cfg / "autostart/blueman.desktop").read_text())
            self.assertIn("NotShowIn=KDE;GNOME;niri;", (cfg / "autostart/nm-applet.desktop").read_text())

            # Idempotent second run writes nothing.
            self.assertEqual(session_cleanup.ensure(home=cfg, state_path=state), [])

            # Uninstall restore removes both shadows cleanly.
            restored = session_settings.restore(cfg, state_path=state)
            self.assertEqual(len(restored["restored"]), 2)
            self.assertFalse((cfg / "autostart/blueman.desktop").exists())
            self.assertFalse((cfg / "autostart/nm-applet.desktop").exists())

    def test_preexisting_user_custom_autostart_is_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="selandia-cleanup-custom-") as tmp:
            root = Path(tmp)
            cfg = root / "config"
            state = root / "state/session-settings-backup.json"
            custom = cfg / "autostart/nm-applet.desktop"
            custom.parent.mkdir(parents=True)
            custom.write_text("[Desktop Entry]\nName=Custom NM\n")
            written = session_cleanup.ensure(home=cfg, state_path=state)
            self.assertEqual(written, ["blueman.desktop"])
            self.assertEqual(custom.read_text(), "[Desktop Entry]\nName=Custom NM\n")


if __name__ == "__main__":
    unittest.main()
