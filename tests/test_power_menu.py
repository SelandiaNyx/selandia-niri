"""The native power submenu: fixed actions, confirmed endings, no text input.

The window itself is exercised by tools/panel_probe.py on a private session; this
suite keeps the contract that the scripted dispatcher relies on.
"""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import power_menu


class PowerMenuModelTests(unittest.TestCase):
    def test_the_menu_offers_exactly_the_session_power_actions(self):
        self.assertEqual(power_menu.ACTION_IDS,
                         ("lock", "sleep", "logout", "restart", "shutdown"))

    def test_only_session_ending_actions_ask_for_confirmation(self):
        immediate = [item for item in power_menu.ACTION_IDS if not power_menu.needs_confirmation(item)]
        self.assertEqual(immediate, ["lock", "sleep"])
        for identifier in ("logout", "restart", "shutdown"):
            with self.subTest(identifier=identifier):
                question = power_menu.confirm_question(identifier)
                self.assertIsInstance(question, tuple)
                self.assertEqual(len(question), 2)
                self.assertTrue(all(part.strip() for part in question))

    def test_unknown_actions_are_never_confirmed(self):
        for identifier in ("", "quit", None, "poweroff", "lock ", "./restart"):
            with self.subTest(identifier=identifier):
                self.assertIsNone(power_menu.confirm_question(identifier))
                self.assertFalse(power_menu.needs_confirmation(identifier))

    def test_sleep_note_requires_a_confirmed_inhibitor_not_a_read_error(self):
        self.assertTrue(power_menu.sleep_blocked(lambda: {"awake": True}))
        self.assertFalse(power_menu.sleep_blocked(lambda: {"awake": False}))
        self.assertFalse(power_menu.sleep_blocked(lambda: {}))

        def broken():
            raise RuntimeError("no user manager")

        self.assertFalse(power_menu.sleep_blocked(broken))

    def test_the_dispatcher_matches_every_identifier_the_menu_can_print(self):
        # niri/scripts/desktop dispatches these exact words; a renamed identifier
        # here would silently exit 2 instead of performing the chosen action.
        desktop = (Path(__file__).resolve().parents[1] / "niri/scripts/desktop").read_text()
        for identifier in power_menu.ACTION_IDS:
            with self.subTest(identifier=identifier):
                self.assertIn(f"{identifier})", desktop)


if __name__ == "__main__":
    unittest.main()
