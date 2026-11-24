"""Accessible MD3 + High-Anime widgets shared across Control Center 2.0.

The panel ships its own verified symbolic icons. Breeze's 2x export of
``input-keyboard-symbolic`` rasterises as a fully opaque square, so the panel
adds a private *inheriting* icon theme built from ``assets/icons`` under a
runtime directory and points this process at it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango

from i18n import tr

EXTENSION_NAME = "selandia-symbolic"
ICON_ASSETS = Path(__file__).resolve().parent.parent / "assets/icons"
PREPARED = {"base": None, "directory": None}


def style(widget, name):
    widget.get_style_context().add_class(name)
    return widget


def pack(parent, child, expand=False):
    parent.pack_start(child, expand, expand, 0)
    return child


def text(value, css, width=30):
    label = style(Gtk.Label(label=value, xalign=0), css)
    label.set_ellipsize(Pango.EllipsizeMode.END)
    label.set_max_width_chars(width)
    return label


def wrap_label(value, css=None):
    label = Gtk.Label(label=value, xalign=0)
    label.set_line_wrap(True)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if css:
        style(label, css)
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
        scalable = theme / "scalable"
        scalable.mkdir(parents=True, exist_ok=True)
        index_path = theme / "index.theme"
        index_content = index_theme(base)
        if not index_path.is_file() or index_path.read_text() != index_content:
            index_path.write_text(index_content)
        for source in sources:
            target = scalable / source.name
            data = source.read_bytes()
            if not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)
    except OSError:
        return None
    return root


def prepare_icon_theme(*, runtime=None):
    """Make the panel's verified icons win for the active (inherited) theme."""
    settings = Gtk.Settings.get_default()
    theme = Gtk.IconTheme.get_default()
    if settings is None or theme is None:
        return None
    base = active_theme_name()
    if PREPARED["base"] == base and PREPARED["directory"] is not None:
        return str(PREPARED["directory"])
    if not any(ICON_ASSETS.glob("*-symbolic.svg")):
        return None
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


def status_badge(label_text: str, kind: str = "info") -> Gtk.Label:
    """Compact semantic status pill (ok / warn / err / info)."""
    badge = style(Gtk.Label(label=label_text), "status-badge")
    if kind:
        badge.get_style_context().add_class(kind)
    badge.set_valign(Gtk.Align.CENTER)
    return badge


def setting_row(title: str, control: Gtk.Widget, subtitle: str = "") -> Gtk.Box:
    """Compact horizontal setting row: title+subtitle left, control right."""
    row = Gtk.Box(spacing=12)
    row.set_valign(Gtk.Align.CENTER)
    left = pack(row, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), True)
    lbl = pack(left, wrap_label(title, "control-label"))
    lbl.set_hexpand(True)
    if subtitle:
        pack(left, wrap_label(subtitle, "hint"))
    control.set_valign(Gtk.Align.CENTER)
    pack(row, control)
    return row


def data_row(*children: Gtk.Widget, spacing: int = 10) -> Gtk.Box:
    """Flat, non-nested list row for processes, logs, disks, services, Wi-Fi."""
    row = style(Gtk.Box(spacing=spacing), "data-row")
    has_explicit = any(getattr(child, "_row_expand", False) for child in children)
    auto_expanded = False
    for child in children:
        expand = getattr(child, "_row_expand", False)
        if not has_explicit and not auto_expanded and len(children) >= 2 and isinstance(child, (Gtk.Label, Gtk.Box)):
            expand = True
            auto_expanded = True
        pack(row, child, expand)
    return row


def card_grid(wide: bool = True, spacing: int = 12) -> Gtk.Grid:
    """Responsive 2-column grid on wide windows, single column on narrow."""
    grid = Gtk.Grid(column_spacing=spacing, row_spacing=spacing, column_homogeneous=wide)
    grid._wide = wide
    grid._items = 0
    return grid


def grid_add(grid: Gtk.Grid, widget: Gtk.Widget, *, full_width: bool = False):
    widget.set_hexpand(True)
    widget.set_valign(Gtk.Align.START)
    wide = getattr(grid, "_wide", True)
    cols = 2 if wide else 1
    if full_width:
        row = (grid._items + cols - 1) // cols if grid._items % cols else grid._items // cols
        grid.attach(widget, 0, row, cols, 1)
        grid._items = (row + 1) * cols
    else:
        col = grid._items % cols
        row = grid._items // cols
        grid.attach(widget, col, row, 1, 1)
        grid._items += 1
    return widget


def _guide_state_path() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "selandia-niri/guides.json"


def _guide_dismissed(page_key: str) -> bool:
    try:
        data = json.loads(_guide_state_path().read_text())
        return bool(data.get(page_key, False))
    except (OSError, ValueError, TypeError):
        return False


def _set_guide_dismissed(page_key: str) -> None:
    path = _guide_state_path()
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
        if not isinstance(data, dict):
            data = {}
        data[page_key] = True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
    except OSError:
        pass


def nyx_guide_banner(page_key: str, message: str, *, skin: str | None = None,
                     action_label: str | None = None, action_cb=None) -> Gtk.Box:
    """Compact high-anime Gemini mascot speech-bubble guide banner (dismissible)."""
    banner = style(Gtk.Box(spacing=10), "nyx-guide-banner")
    banner.set_valign(Gtk.Align.START)
    try:
        from appearance import mascot_asset
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        avatar_file = mascot_asset(skin, "avatar")
        if avatar_file.is_file():
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(avatar_file), 36, 36, True)
            frame = style(Gtk.Box(), "nyx-guide-avatar")
            frame.set_valign(Gtk.Align.CENTER)
            pack(frame, Gtk.Image.new_from_pixbuf(pix))
            pack(banner, frame)
    except Exception:
        pass
    msg = pack(banner, wrap_label(message, "nyx-guide-text"), True)
    msg.set_valign(Gtk.Align.CENTER)
    if action_label and callable(action_cb):
        btn = style(Gtk.Button(label=action_label), "small-button")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda _: action_cb())
        pack(banner, btn)
    dismiss = style(Gtk.Button(label="×"), "flat")
    dismiss.set_valign(Gtk.Align.CENTER)
    dismiss.set_tooltip_text(tr("Hide this tip", "收起此引导提示"))
    def on_dismiss(_btn):
        _set_guide_dismissed(page_key)
        banner.set_no_show_all(True)
        banner.hide()
    dismiss.connect("clicked", on_dismiss)
    pack(banner, dismiss)
    if _guide_dismissed(page_key):
        banner.set_no_show_all(True)
        banner.hide()
    return banner


def inline_confirm_bar(prompt: str, confirm_label: str, on_confirm, on_cancel) -> tuple[Gtk.Box, Gtk.Button]:
    """Destructive confirmation strip with keyboard focus safely anchored on Cancel."""
    bar = style(Gtk.Box(spacing=10), "inline-confirm")
    pack(bar, wrap_label(prompt, "control-label"), True)
    cancel_btn = Gtk.Button(label=tr("Cancel", "取消"))
    cancel_btn.connect("clicked", lambda _: on_cancel())
    confirm_btn = style(Gtk.Button(label=confirm_label), "power-button")
    confirm_btn.connect("clicked", lambda _: on_confirm())
    pack(bar, cancel_btn)
    pack(bar, confirm_btn)
    return bar, cancel_btn


class StickyActionBar(Gtk.Box):
    """Pinned bottom action bar with unsaved dirty indicator and Apply/Discard/Defaults."""

    def __init__(self, *, on_apply=None, on_discard=None, on_defaults=None, apply_label=None):
        super().__init__(spacing=10)
        style(self, "sticky-action-bar")
        self.status_label = pack(self, wrap_label("", "hint"), True)
        self.status_label.set_valign(Gtk.Align.CENTER)
        self.dirty_badge = style(Gtk.Label(label=tr("● Unsaved", "● 有未保存修改")), "status-badge")
        self.dirty_badge.get_style_context().add_class("warn")
        self.dirty_badge.set_no_show_all(True)
        pack(self, self.dirty_badge)
        self.defaults_btn = None
        if on_defaults:
            self.defaults_btn = style(Gtk.Button(label=tr("Defaults", "恢复默认")), "small-button")
            self.defaults_btn.connect("clicked", lambda _: on_defaults())
            pack(self, self.defaults_btn)
        self.discard_btn = None
        if on_discard:
            self.discard_btn = style(Gtk.Button(label=tr("Discard", "放弃修改")), "small-button")
            self.discard_btn.connect("clicked", lambda _: on_discard())
            self.discard_btn.set_no_show_all(True)
            pack(self, self.discard_btn)
        self.apply_btn = None
        if on_apply:
            self.apply_btn = style(Gtk.Button(label=apply_label or tr("Apply", "应用设置")), "accent-button")
            self.apply_btn.connect("clicked", lambda _: on_apply())
            pack(self, self.apply_btn)

    def set_dirty(self, dirty: bool):
        self.dirty_badge.set_visible(bool(dirty))
        if self.discard_btn is not None:
            self.discard_btn.set_visible(bool(dirty))

    def set_status(self, message: str):
        self.status_label.set_text(message)
