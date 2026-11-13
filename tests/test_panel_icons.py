"""The panel's keyboard icon must stay a transparent outline at every scale (A4).

This renders the real GTK icon pipeline into image buffers. Under the Breeze
theme the 2x ``input-keyboard-symbolic`` export is a fully opaque square; the
panel therefore prepends its own verified icon via a private theme extension.
No system icon directory and no global theme setting is touched.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import control_widgets

KEYBOARD = "input-keyboard-symbolic"
SCALES = (1, 2, 3)


def alpha_histogram(pixbuf):
    data = pixbuf.get_pixels()
    channels = pixbuf.get_n_channels()
    stride = pixbuf.get_rowstride()
    width, height = pixbuf.get_width(), pixbuf.get_height()
    transparent = opaque = partial = 0
    for row in range(height):
        base = row * stride
        for column in range(width):
            alpha = data[base + column * channels + channels - 1]
            if alpha == 0:
                transparent += 1
            elif alpha == 255:
                opaque += 1
            else:
                partial += 1
    return {"transparent": transparent, "opaque": opaque, "partial": partial,
            "total": width * height, "size": (width, height)}


def render(theme, name, size, scale):
    info = theme.lookup_icon_for_scale(name, size, scale, Gtk.IconLookupFlags.FORCE_SYMBOLIC)
    if info is None:
        return None, None
    colour = Gdk.RGBA()
    colour.parse("#2e3436")
    loaded = info.load_symbolic(colour, colour, colour, colour)
    # PyGObject returns (pixbuf, was_symbolic) for the C out-parameters.
    pixbuf = loaded[0] if isinstance(loaded, tuple) else loaded
    return pixbuf, info


class KeyboardIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialized, _ = Gtk.init_check()
        if not initialized or Gtk.Settings.get_default() is None or Gdk.Screen.get_default() is None:
            raise unittest.SkipTest("GTK display unavailable; verify icon rendering in the isolated graphical session")

    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory(prefix="selandia-icons-")
        self.addCleanup(self.runtime.cleanup)
        self.reset()
        self.addCleanup(self.reset)
        self.settings = Gtk.Settings.get_default()
        self.original_theme = self.settings.get_property("gtk-icon-theme-name")
        self.addCleanup(self.settings.set_property, "gtk-icon-theme-name", self.original_theme)
        # A scratch theme object accepts a custom theme name and still sees the
        # system search path; the screen singleton refuses both.
        self.theme = Gtk.IconTheme.new()
        self.theme.set_screen(Gdk.Screen.get_default())

    def reset(self):
        control_widgets.PREPARED.update(base=None, directory=None)

    def prepare(self, base):
        directory = control_widgets.build_extension(base, self.runtime.name)
        self.assertIsNotNone(directory, "the panel could not build its icon extension")
        self.theme.set_search_path([str(directory), *Gtk.IconTheme.get_default().get_search_path()])
        self.theme.set_custom_theme(control_widgets.EXTENSION_NAME)
        return directory

    def apply(self, base):
        """Run the shipped entry point and mirror it onto a scratch theme."""
        with patch.object(control_widgets, "active_theme_name", return_value=base):
            directory = control_widgets.prepare_icon_theme(runtime=self.runtime.name)
        self.prepare(base)
        return directory

    def test_extension_is_built_outside_system_icon_directories(self):
        directory = self.apply("breeze-dark")
        self.assertTrue(str(directory).startswith(self.runtime.name))
        index = Path(directory) / control_widgets.EXTENSION_NAME / "index.theme"
        self.assertTrue(index.is_file())
        self.assertIn("Inherits=breeze-dark", index.read_text())
        self.assertNotIn("/usr/share/icons", index.read_text())

    def test_extension_inherits_the_users_theme_instead_of_shadowing_it(self):
        self.apply("breeze-dark")
        for name in ("audio-volume-high-symbolic", "network-wireless-symbolic", "system-shutdown-symbolic"):
            with self.subTest(name=name):
                pixbuf, info = render(self.theme, name, 18, 2)
                self.assertIsNotNone(pixbuf, name)
                self.assertNotIn("/selandia-icons-", str(info.get_filename()),
                                 "a system icon must keep coming from the user's theme")

    def test_keyboard_outline_has_a_transparent_background_at_every_scale(self):
        self.apply("breeze-dark")
        for scale in SCALES:
            with self.subTest(scale=scale):
                pixbuf, info = render(self.theme, KEYBOARD, 18, scale)
                self.assertIsNotNone(pixbuf)
                self.assertTrue(str(info.get_filename()).startswith(self.runtime.name),
                                "the system icon won instead of the verified one")
                counts = alpha_histogram(pixbuf)
                self.assertGreater(counts["transparent"], 0, "the icon has no transparent background")
                self.assertGreater(counts["opaque"], 0, "the icon has no visible outline")
                self.assertGreater(counts["partial"], 0, "the icon is not antialiased")
                self.assertLess(counts["opaque"], counts["total"], "the icon is a solid block")
                self.assertGreater(counts["opaque"] / counts["total"], 0.02, "the icon is nearly invisible")
                self.assertLess(counts["opaque"] / counts["total"], 0.85, "the icon fills the canvas")

    def test_light_and_dark_themes_resolve_the_verified_icon(self):
        for theme_name in ("breeze", "breeze-dark", "Adwaita", "Adwaita-dark", "hicolor"):
            with self.subTest(theme=theme_name):
                self.reset()
                self.apply(theme_name)
                pixbuf, info = render(self.theme, KEYBOARD, 18, 2)
                self.assertIsNotNone(pixbuf)
                self.assertTrue(str(info.get_filename()).startswith(self.runtime.name))
                alpha_histogram(pixbuf)

    def test_other_panel_icons_still_resolve(self):
        self.apply("breeze-dark")
        for name in ("audio-volume-high-symbolic", "network-wireless-symbolic", "system-shutdown-symbolic"):
            with self.subTest(name=name):
                pixbuf, info = render(self.theme, name, 18, 2)
                self.assertIsNotNone(pixbuf, name)

    def test_every_bundled_icon_renders_cleanly(self):
        self.apply("breeze-dark")
        for source in sorted(control_widgets.ICON_ASSETS.glob("*-symbolic.svg")):
            with self.subTest(icon=source.stem):
                pixbuf, info = render(self.theme, source.stem, 18, 2)
                self.assertIsNotNone(pixbuf)
                self.assertTrue(str(info.get_filename()).startswith(self.runtime.name))
                counts = alpha_histogram(pixbuf)
                self.assertGreater(counts["transparent"], 0)
                self.assertLess(counts["opaque"], counts["total"])

    def test_an_unwritable_runtime_directory_falls_back_to_the_temp_dir(self):
        with tempfile.TemporaryDirectory(prefix="selandia-icons-tmp-") as temporary:
            with patch.object(control_widgets, "extension_root", return_value=Path(temporary) / "icons"):
                self.reset()
                directory = self.apply("breeze-dark")
                self.assertTrue(directory.startswith(temporary))

    def test_no_system_icon_file_is_modified(self):
        self.apply("breeze-dark")
        for path in ("/usr/share/icons/breeze-dark/devices/32/input-keyboard-symbolic.svg",
                     "/usr/share/icons/breeze/devices/32/input-keyboard-symbolic.svg"):
            if os.path.lexists(path):
                with open(path, "rb") as stream:
                    self.assertNotIn(b"selandia", stream.read().lower())


if __name__ == "__main__":
    unittest.main()
