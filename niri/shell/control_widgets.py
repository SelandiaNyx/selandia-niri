"""Small accessible widgets shared by the native control-center overview.

The panel ships its own verified symbolic icons. Breeze's 2x export of
``input-keyboard-symbolic`` rasterises as a fully opaque square, so the panel
adds a private *inheriting* icon theme built from ``assets/icons`` under a
runtime directory and points this process at it. Because the extension inherits
the user's theme, every other icon still resolves from Breeze/Adwaita; because
it is only this process's GtkSettings value, no system file and no user setting
is modified.
"""
import os
from pathlib import Path
import tempfile

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

EXTENSION_NAME = "selandia-symbolic"
ICON_ASSETS = Path(__file__).resolve().parent.parent / "assets/icons"
PREPARED = {"base": None, "directory": None}


def style(widget, name):
    widget.get_style_context().add_class(name)
    return widget


def pack(parent, child, expand=False):
    parent.pack_start(child, expand, expand, 0)
    return child


def text(value, css, width=24):
    label = style(Gtk.Label(label=value, xalign=0), css)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(width)
    return label


def active_theme_name():
    """The user's icon theme; never our own extension name."""
    settings = Gtk.Settings.get_default()
    name = settings.get_property("gtk-icon-theme-name") if settings is not None else None
    if not name or name == EXTENSION_NAME:
        return PREPARED["base"] or "hicolor"
    return name


def extension_root(runtime=None):
    """A writable private directory; never a system icon directory."""
    for candidate in (runtime, os.environ.get("XDG_RUNTIME_DIR"), tempfile.gettempdir()):
        if candidate:
            return Path(candidate) / f"selandia-icons-{os.getuid()}"
    return None


def index_theme(base):
    return ("[Icon Theme]\n"
            f"Name={EXTENSION_NAME}\n"
            "Comment=Selandia Niri verified symbolic icons\n"
            "Directories=scalable\n"
            f"Inherits={base}\n"
            "\n"
            "[scalable]\n"
            "Size=16\n"
            "Type=Scalable\n"
            "MinSize=6\n"
            "MaxSize=512\n"
            "Context=Devices\n")


def build_extension(base, runtime=None):
    """Write the verified icons as a theme that inherits ``base``."""
    root = extension_root(runtime)
    if root is None:
        return None
    sources = sorted(ICON_ASSETS.glob("*-symbolic.svg"))
    if not sources or base == EXTENSION_NAME:
        return None
    theme = root / EXTENSION_NAME
    try:
        (theme / "scalable").mkdir(parents=True, exist_ok=True)
        (theme / "index.theme").write_text(index_theme(base))
        for source in sources:
            (theme / "scalable" / source.name).write_bytes(source.read_bytes())
    except OSError:
        return None
    return root


def prepare_icon_theme(*, runtime=None):
    """Make the panel's verified icons win for the active (inherited) theme."""
    settings = Gtk.Settings.get_default()
    theme = Gtk.IconTheme.get_default()
    if settings is None or theme is None or not any(ICON_ASSETS.glob("*-symbolic.svg")):
        return None
    base = active_theme_name()
    if PREPARED["base"] == base and PREPARED["directory"] is not None:
        return str(PREPARED["directory"])
    directory = build_extension(base, runtime)
    if directory is None:
        return None
    theme.prepend_search_path(str(directory))
    settings.set_property("gtk-icon-theme-name", EXTENSION_NAME)
    PREPARED.update(base=base, directory=directory)
    return str(directory)


def icon(name, size=20):
    prepare_icon_theme()
    image = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    image.set_pixel_size(size)
    return image


def icon_button(name, tooltip, callback, css, title=None):
    button = style(Gtk.Button(), css)
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(tooltip)
    row = Gtk.Box(spacing=6)
    row.set_halign(Gtk.Align.CENTER)
    button.add(row)
    image = pack(row, icon(name))
    if title:
        pack(row, Gtk.Label(label=title))
    button.connect("clicked", lambda _: callback())
    return button, image
