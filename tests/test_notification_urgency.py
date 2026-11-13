"""SwayNC urgency hints: byte values and non-byte defaults."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
from gi.repository import GLib
from notification_events import urgency_from_hints


def urgency_hints(value):
    return GLib.Variant("a{sv}", {"urgency": value})


class NotificationUrgencyTest(unittest.TestCase):
    def test_every_byte_urgency_is_normalized(self):
        for urgency in range(256):
            expected = urgency if urgency <= 2 else 1
            with self.subTest(urgency=urgency):
                hints = urgency_hints(GLib.Variant("y", urgency))
                self.assertEqual(urgency_from_hints(hints), expected)

    def test_missing_and_non_byte_hints_default_to_low(self):
        with self.subTest(case="missing"):
            self.assertEqual(urgency_from_hints(GLib.Variant("a{sv}", {})), 0)
        cases = (
            ("bool-true", GLib.Variant("b", True)),
            ("bool-false", GLib.Variant("b", False)),
            ("int32-minus-one", GLib.Variant("i", -1)),
            ("int32-two", GLib.Variant("i", 2)),
            ("uint32-two", GLib.Variant("u", 2)),
            ("uint32-three", GLib.Variant("u", 3)),
            ("string-two", GLib.Variant("s", "2")),
            ("double-two", GLib.Variant("d", 2.0)),
        )
        for case, value in cases:
            with self.subTest(case=case):
                self.assertEqual(urgency_from_hints(urgency_hints(value)), 0)


if __name__ == "__main__":
    unittest.main()
