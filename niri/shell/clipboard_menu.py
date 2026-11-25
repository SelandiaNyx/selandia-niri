#!/usr/bin/env python3
"""Native GTK3 Layer-Shell visual clipboard manager (replaces fuzzel dmenu).

Zero resident RAM: launches on demand via ``Super+V`` (history picker) or
``Super+Shift+V`` (``--confirm-clear`` safe confirmation modal). Wraps native
``cliphist`` + ``wl-copy`` with live async image thumbnail previews, search,
single-item deletion, and Gemini Starlight MD3 styling.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from appearance import load_settings, mascot_asset
from control_widgets import icon, pack, prepare_icon_theme, style
from i18n import tr

_BINARY_IMAGE_RE = re.compile(r"^\[\[ binary data .+ (png|jpe?g|webp|bmp|gif|tiff|avif) .+ \]\]$", re.IGNORECASE)
MAX_ENTRIES = 120
MAX_THUMB_LOADS = 24


def parse_entries(raw: str) -> list[dict]:
    """Parse ``cliphist list`` lines into structured entry dicts."""
    items: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        item_id, sep, preview = line.partition("\t")
        if not sep:
            preview = line
            item_id = ""
        is_image = bool(_BINARY_IMAGE_RE.match(preview.strip()))
        items.append({
            "raw": line,
            "id": item_id.strip(),
            "preview": preview.strip(),
            "is_image": is_image,
            "search": preview.casefold(),
        })
        if len(items) >= MAX_ENTRIES:
            break
    return items


def read_history() -> list[dict]:
    res = subprocess.run(["cliphist", "list"], capture_output=True, text=True, timeout=5)
    if res.returncode != 0:
        return []
    return parse_entries(res.stdout)


def copy_entry(raw_line: str) -> None:
    decoded = subprocess.run(["cliphist", "decode"], input=raw_line.encode("utf-8"),
                             capture_output=True, check=True, timeout=5)
    subprocess.run(["wl-copy"], input=decoded.stdout, capture_output=True, check=True, timeout=5)


def delete_entry(raw_line: str) -> None:
    subprocess.run(["cliphist", "delete"], input=(raw_line + "\n").encode("utf-8"),
                   capture_output=True, check=True, timeout=5)


def clear_all_history() -> None:
    subprocess.run(["cliphist", "wipe"], capture_output=True, check=False, timeout=5)
    subprocess.run(["wl-copy", "--clear"], capture_output=True, check=False, timeout=5)
    try:
        subprocess.Popen(["notify-send", "-a", "Selandia Niri",
                          tr("Clipboard history cleared", "剪贴板历史已清空")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def decode_thumbnail(raw_line: str, max_w: int = 84, max_h: int = 48) -> GdkPixbuf.Pixbuf | None:
    """Decode a binary cliphist image into a bounded GdkPixbuf thumbnail."""
    try:
        res = subprocess.run(["cliphist", "decode"], input=raw_line.encode("utf-8"),
                             capture_output=True, check=True, timeout=4)
        if not res.stdout or len(res.stdout) > 16 * 1024 * 1024:
            return None
        loader = GdkPixbuf.PixbufLoader()
        loader.write(res.stdout)
        loader.close()
        pix = loader.get_pixbuf()
        if pix is None:
            return None
        w, h = pix.get_width(), pix.get_height()
        if w <= 0 or h <= 0:
            return None
        scale = min(max_w / w, max_h / h, 1.0)
        return pix.scale_simple(max(1, round(w * scale)), max(1, round(h * scale)), GdkPixbuf.InterpType.BILINEAR)
    except Exception:
        return None


def load_theme() -> dict:
    prepare_icon_theme()
    prefs = load_settings()
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", prefs.get("color_mode", "dark") == "dark")
    screen = Gdk.Screen.get_default()
    if screen is not None:
        for path in (BASE / "shell/style.css", BASE / "theme/panel.css", BASE / "shell/control_center.css"):
            if not path.is_file():
                continue
            provider = Gtk.CssProvider()
            provider.load_from_path(str(path))
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return prefs


def _configure_layer(window: Gtk.Window, width: int, height: int = -1):
    window.set_decorated(False)
    window.set_resizable(False)
    window.set_app_paintable(True)
    window.set_default_size(width, height)
    window.set_size_request(width, height)
    visual = window.get_screen().get_rgba_visual()
    if visual:
        window.set_visual(visual)
    ctx = window.get_style_context()
    ctx.add_class("glass-window")
    ctx.add_class("clipboard-window")
    if GtkLayerShell.is_supported():
        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, "selandia-clipboard")
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_exclusive_zone(window, -1)
    else:
        window.set_position(Gtk.WindowPosition.CENTER)


class ConfirmClearWindow(Gtk.ApplicationWindow):
    """Safe confirmation modal for ``Super+Shift+V`` with default focus on Cancel."""

    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="Selandia · Clear Clipboard")
        prefs = load_theme()
        if prefs.get("reduced_motion"):
            self.get_style_context().add_class("reduce-motion")
        _configure_layer(self, 360, -1)

        surface = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "glass-surface")
        self.add(surface)

        header = pack(surface, style(Gtk.Box(spacing=10), "panel-header"))
        pack(header, icon("edit-clear-all-symbolic", 18))
        pack(header, style(Gtk.Label(label=tr("Clear Clipboard", "清空剪贴板"), xalign=0), "control-heading"), True)
        close_btn = style(Gtk.Button(label="×"), "close-button")
        close_btn.connect("clicked", lambda _: self.get_application().quit())
        pack(header, close_btn)

        body = pack(surface, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12), "panel-content"))
        q = style(Gtk.Label(label=tr("Permanently wipe all saved clipboard text and image history?",
                                     "确定永久清空所有已保存的剪贴板文字与图片历史吗？"), xalign=0), "power-question")
        q.set_line_wrap(True)
        pack(body, q)

        btns = pack(body, Gtk.Box(spacing=10))
        self.cancel_btn = pack(btns, style(Gtk.Button(label=tr("Cancel", "取消")), "text-button"), True)
        self.cancel_btn.connect("clicked", lambda _: self.get_application().quit())
        self.confirm_btn = pack(btns, style(Gtk.Button(label=tr("Clear All", "确认清空")), "power-button"), True)
        self.confirm_btn.connect("clicked", self._confirm)

        self.connect("key-press-event", self._on_key)
        self.connect("map", lambda *_: self.cancel_btn.grab_focus())

    def _on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            self.get_application().quit()
            return True
        if event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_KP_Left, Gdk.KEY_KP_Right):
            target = self.confirm_btn if self.get_focus() is self.cancel_btn else self.cancel_btn
            target.grab_focus()
            return True
        return False

    def _confirm(self, *_):
        clear_all_history()
        self.get_application().quit()


class ClipboardWindow(Gtk.ApplicationWindow):
    """Searchable visual clipboard picker with live image previews and per-item delete."""

    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="Selandia · Clipboard")
        prefs = load_theme()
        if prefs.get("reduced_motion"):
            self.get_style_context().add_class("reduce-motion")
        _configure_layer(self, 580, 640)

        self.pool = ThreadPoolExecutor(max_workers=2)
        self._alive = True
        self.entries: list[dict] = []
        self.rows: list[Gtk.ListBoxRow] = []
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_key)

        surface = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0), "glass-surface")
        self.add(surface)

        # Header with Gemini avatar
        header = pack(surface, style(Gtk.Box(spacing=12), "panel-header"))
        avatar_path = mascot_asset(prefs.get("mascot", "gemini"), "avatar")
        if avatar_path.is_file():
            try:
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(avatar_path), 42, 42, True)
                frame = style(Gtk.Box(), "mascot-avatar-frame")
                frame.set_valign(Gtk.Align.CENTER)
                pack(frame, Gtk.Image.new_from_pixbuf(pix))
                pack(header, frame)
            except (GLib.Error, OSError):
                pass
        titles = pack(header, Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), True)
        titles.set_valign(Gtk.Align.CENTER)
        pack(titles, style(Gtk.Label(label=tr("Clipboard History", "剪贴板历史"), xalign=0), "control-heading"))
        self.count_label = pack(titles, style(Gtk.Label(label=tr("Loading…", "读取中…"), xalign=0), "control-caption"))

        self.clear_btn = style(Gtk.Button(label=tr("Clear all", "清空全部")), "small-button")
        self.clear_btn.set_valign(Gtk.Align.CENTER)
        self.clear_btn.connect("clicked", lambda _: self._show_confirm(True))
        pack(header, self.clear_btn)

        close_btn = style(Gtk.Button(label="×"), "close-button")
        close_btn.set_valign(Gtk.Align.CENTER)
        close_btn.connect("clicked", lambda _: self.get_application().quit())
        pack(header, close_btn)

        body = pack(surface, style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "panel-content"), True)

        # Inline clear confirmation bar (hidden until clicked)
        self.confirm_bar = pack(body, style(Gtk.Box(spacing=10), "inline-confirm"))
        self.confirm_bar.set_no_show_all(True)
        pack(self.confirm_bar, style(Gtk.Label(label=tr("Wipe entire clipboard history?", "确定清空全部剪贴板记录？"), xalign=0), "control-label"), True)
        self.confirm_cancel = style(Gtk.Button(label=tr("Cancel", "取消")), "small-button")
        self.confirm_cancel.connect("clicked", lambda _: self._show_confirm(False))
        self.confirm_ok = style(Gtk.Button(label=tr("Wipe", "确认清空")), "power-button")
        self.confirm_ok.connect("clicked", self._wipe_all)
        pack(self.confirm_bar, self.confirm_cancel)
        pack(self.confirm_bar, self.confirm_ok)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text(tr("Search clipboard text or images…", "搜索剪贴板文字或图片…"))
        self.search.connect("search-changed", self._filter)
        self.search.connect("activate", self._activate_selected)
        self.search.connect("key-press-event", self._on_search_key)
        pack(body, self.search)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self.scroll = scroll
        self.listbox = style(Gtk.ListBox(), "clipboard-list")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.set_filter_func(self._matches)
        self.listbox.connect("row-activated", lambda _lb, row: self._pick(row))
        self.listbox.connect("button-press-event", self._on_list_button)
        scroll.add(self.listbox)
        pack(body, scroll, True)

        self.empty_label = pack(body, style(Gtk.Label(label=tr("Clipboard history is empty.", "剪贴板历史为空。")), "empty-state"))
        self.empty_label.set_no_show_all(True)

        footer = pack(body, style(Gtk.Label(
            label=tr("↑↓ / Ctrl+1…9 Copy · Shift+Del / Middle-click Remove · Esc Close",
                     "↑↓ 或 Ctrl+1…9 快速复制 · Shift+Del 或中键删除 · Esc 关闭"),
            xalign=0,
        ), "hint"))
        footer.set_ellipsize(Pango.EllipsizeMode.END)

        self.connect("map", lambda *_: self.search.grab_focus())
        self._load_async()

    def _on_destroy(self, *_):
        self._alive = False
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _show_confirm(self, show: bool):
        if show:
            self.confirm_bar.set_no_show_all(False)
            self.confirm_bar.show_all()
            self.confirm_bar.set_no_show_all(True)
            self.confirm_cancel.grab_focus()
        else:
            self.confirm_bar.hide()
            self.search.grab_focus()

    def _wipe_all(self, *_):
        clear_all_history()
        self.get_application().quit()

    def _load_async(self):
        def worker():
            items = read_history()
            GLib.idle_add(self._populate, items)
        self.pool.submit(worker)

    def _populate(self, items: list[dict]):
        if not self._alive:
            return GLib.SOURCE_REMOVE
        self.entries = items
        for child in self.listbox.get_children():
            child.destroy()
        self.rows.clear()

        thumbs_queued = 0
        for item in items:
            row = Gtk.ListBoxRow()
            row._item = item
            style(row, "clipboard-row")
            box = Gtk.Box(spacing=10)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(10)
            box.set_margin_end(8)

            if item["is_image"]:
                img = Gtk.Image.new_from_icon_name("image-x-generic-symbolic", Gtk.IconSize.DND)
                img.set_size_request(84, 48)
                style(img, "clipboard-thumb")
                pack(box, img)
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                col.set_valign(Gtk.Align.CENTER)
                pack(col, style(Gtk.Label(label=tr("Image", "图片"), xalign=0), "control-label"))
                meta = style(Gtk.Label(label=item["preview"].strip("[] "), xalign=0), "hint")
                meta.set_ellipsize(Pango.EllipsizeMode.END)
                meta.set_max_width_chars(38)
                pack(col, meta)
                pack(box, col, True)
                if thumbs_queued < MAX_THUMB_LOADS:
                    thumbs_queued += 1
                    self._queue_thumb(item["raw"], img)
            else:
                lbl = Gtk.Label(label=item["preview"], xalign=0)
                lbl.set_ellipsize(Pango.EllipsizeMode.END)
                lbl.set_lines(2)
                lbl.set_line_wrap(True)
                lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                lbl.set_max_width_chars(52)
                lbl.set_valign(Gtk.Align.CENTER)
                pack(box, lbl, True)

            del_btn = style(Gtk.Button(label="×"), "flat")
            del_btn.set_valign(Gtk.Align.CENTER)
            del_btn.set_tooltip_text(tr("Delete entry", "删除此条"))
            del_btn.connect("clicked", lambda _b, r=row: self._delete_row(r))
            pack(box, del_btn)

            row.add(box)
            self.listbox.add(row)
            self.rows.append(row)

        self.listbox.show_all()
        self._update_summary()
        if self.rows:
            self.listbox.select_row(self.rows[0])
        return GLib.SOURCE_REMOVE

    def _queue_thumb(self, raw_line: str, image_widget: Gtk.Image):
        def worker():
            pix = decode_thumbnail(raw_line)
            if pix is not None and self._alive:
                def apply():
                    if self._alive and image_widget.get_parent() is not None:
                        image_widget.set_from_pixbuf(pix)
                    return GLib.SOURCE_REMOVE
                GLib.idle_add(apply)
        self.pool.submit(worker)

    def _matches(self, row: Gtk.ListBoxRow) -> bool:
        terms = self.search.get_text().strip().casefold().split()
        if not terms:
            return True
        hay = row._item["search"]
        return all(t in hay for t in terms)

    def _update_summary(self):
        visible = sum(1 for r in self.rows if self._matches(r))
        total = len(self.rows)
        self.count_label.set_text(
            tr(f"{visible} / {total} items", f"{visible} / {total} 条记录")
            if self.search.get_text().strip()
            else tr(f"{total} saved items", f"共 {total} 条历史记录")
        )
        self.empty_label.set_visible(visible == 0)
        self.clear_btn.set_sensitive(total > 0)

    def _filter(self, *_):
        self.listbox.invalidate_filter()
        self._update_summary()
        for row in self.rows:
            if self._matches(row):
                self.listbox.select_row(row)
                break

    def _pick(self, row: Gtk.ListBoxRow | None):
        if row is None or not hasattr(row, "_item"):
            return
        try:
            copy_entry(row._item["raw"])
        except Exception:
            pass
        self.get_application().quit()

    def _delete_row(self, row: Gtk.ListBoxRow):
        if row not in self.rows:
            return
        raw = row._item["raw"]
        idx = self.rows.index(row)
        self.rows.remove(row)
        self.listbox.remove(row)
        row.destroy()
        self._update_summary()
        visible = [r for r in self.rows if self._matches(r)]
        if visible:
            self.listbox.select_row(visible[min(idx, len(visible) - 1)])
        self.pool.submit(lambda: delete_entry(raw))

    def _activate_selected(self, *_):
        row = self.listbox.get_selected_row()
        if row is None or not self._matches(row):
            row = next((r for r in self.rows if self._matches(r)), None)
        self._pick(row)

    def _reveal_row(self, row: Gtk.ListBoxRow | None):
        if row is None or getattr(self, "scroll", None) is None:
            return
        adj = self.scroll.get_vadjustment()
        alloc = row.get_allocation()
        if adj is not None and alloc.height > 0 and adj.get_page_size() > 0:
            adj.clamp_page(alloc.y, alloc.y + alloc.height)

    def _on_list_button(self, _lb, event):
        if event.button == Gdk.BUTTON_MIDDLE:
            row = self.listbox.get_row_at_y(int(event.y))
            if row is not None and row in self.rows:
                self._delete_row(row)
                return True
        return False

    def _move_selection(self, step: int, *, absolute: int | None = None):
        visible = [r for r in self.rows if self._matches(r)]
        if not visible:
            return
        if absolute is not None:
            target = visible[max(0, min(len(visible) - 1, absolute))]
        else:
            cur = self.listbox.get_selected_row()
            idx = visible.index(cur) if cur in visible else -1
            target = visible[(idx + step) % len(visible)]
        self.listbox.select_row(target)
        self._reveal_row(target)

    def _on_search_key(self, _entry, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down) or (ctrl and event.keyval in (Gdk.KEY_n, Gdk.KEY_N)):
            self._move_selection(1)
            return True
        if event.keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up) or (ctrl and event.keyval in (Gdk.KEY_p, Gdk.KEY_P)):
            self._move_selection(-1)
            return True
        if event.keyval in (Gdk.KEY_Page_Down, Gdk.KEY_KP_Page_Down):
            self._move_selection(6)
            return True
        if event.keyval in (Gdk.KEY_Page_Up, Gdk.KEY_KP_Page_Up):
            self._move_selection(-6)
            return True
        if ctrl and event.keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self._move_selection(0, absolute=0)
            return True
        if ctrl and event.keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            self._move_selection(0, absolute=10**6)
            return True
        return False

    def _on_key(self, _win, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if event.keyval == Gdk.KEY_Escape:
            if self.confirm_bar.get_visible():
                self._show_confirm(False)
            elif self.search.get_text():
                self.search.set_text("")
            else:
                self.get_application().quit()
            return True
        if self.confirm_bar.get_visible() and event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_KP_Left, Gdk.KEY_KP_Right):
            target = self.confirm_ok if self.get_focus() is self.confirm_cancel else self.confirm_cancel
            target.grab_focus()
            return True
        if ctrl and Gdk.KEY_1 <= event.keyval <= Gdk.KEY_9:
            visible = [r for r in self.rows if self._matches(r)]
            idx = event.keyval - Gdk.KEY_1
            if idx < len(visible):
                self._pick(visible[idx])
            return True
        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete) and (shift or not self.search.has_focus()):
            row = self.listbox.get_selected_row()
            if row is not None and self._matches(row):
                self._delete_row(row)
                return True
        return False


class ClipboardApp(Gtk.Application):
    def __init__(self, confirm_clear: bool = False):
        super().__init__(application_id="org.selandia.Clipboard",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.confirm_clear = confirm_clear
        self.window = None

    def do_activate(self):
        if self.window is not None:
            return
        self.window = ConfirmClearWindow(self) if self.confirm_clear else ClipboardWindow(self)
        self.window.show_all()
        self.window.present()


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    confirm_clear = args == ["--confirm-clear"]
    if args and not confirm_clear:
        print("Usage: clipboard_menu.py [--confirm-clear]", file=sys.stderr)
        return 2
    if not Gtk.init_check()[0]:
        print(tr("A running Wayland session is required.", "需要正在运行的 Wayland 会话。"), file=sys.stderr)
        return 1
    return ClipboardApp(confirm_clear=confirm_clear).run([])


if __name__ == "__main__":
    raise SystemExit(main())
