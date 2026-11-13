"""Lazy Control Center page construction with reversible show/hide hooks."""
from __future__ import annotations

from collections.abc import Mapping

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class PageEntry:
    """The public page object and the widget actually installed in the stack."""

    __slots__ = ("content", "widget")

    def __init__(self, content, widget=None):
        self.content = content
        self.widget = widget if widget is not None else content


class PageSpec:
    __slots__ = ("key", "title", "factory")

    def __init__(self, key, title, factory):
        self.key = key
        self.title = title
        self.factory = factory


class PageHost:
    """Build a stack child on first selection, then keep its draft state alive."""

    def __init__(self, panel, stack, specs):
        self.panel = panel
        self.stack = stack
        self.specs = {spec.key: spec for spec in specs}
        self.entries = {}
        self.placeholders = {}
        self.active = None
        self.disposed = False
        for spec in specs:
            placeholder = Gtk.Box()
            self.placeholders[spec.key] = placeholder
            stack.add_titled(placeholder, spec.key, spec.title)
        self._visible_handler = stack.connect("notify::visible-child-name", self._visible_changed)

    def ensure(self, key):
        if self.disposed:
            raise RuntimeError("page host is disposed")
        entry = self.entries.get(key)
        if entry is not None:
            return entry
        spec = self.specs.get(key)
        if spec is None:
            raise KeyError(key)
        entry = spec.factory()
        if not isinstance(entry, PageEntry):
            entry = PageEntry(entry)
        placeholder = self.placeholders.pop(key, None)
        if placeholder is not None:
            self.stack.remove(placeholder)
        self.stack.add_titled(entry.widget, key, spec.title)
        if hasattr(self.panel, "protect_scroll_controls"):
            self.panel.protect_scroll_controls(entry.widget)
        entry.widget.show_all()
        self.entries[key] = entry
        if self.stack.get_visible_child_name() == key:
            self._visible_changed(self.stack, None)
        return entry

    def page(self, key):
        return self.ensure(key).content

    def built(self, key):
        return key in self.entries

    def _visible_changed(self, _stack, _property):
        name = self.stack.get_visible_child_name()
        if name not in self.entries:
            return
        if name == self.active:
            return
        previous, self.active = self.active, name
        if previous is not None and hasattr(self.panel, "_page_hidden"):
            self.panel._page_hidden(previous)
        # Constructed-but-unmapped pages must have no read sources. on_map
        # activates the selected page once real mapping exists.
        if (hasattr(self.panel, "page_visible") and self.panel.page_visible(name)
                and hasattr(self.panel, "_page_shown")):
            self.panel._page_shown(name)

    def dispose(self):
        self.disposed = True
        handler = getattr(self, "_visible_handler", None)
        if handler is not None:
            try:
                self.stack.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
            self._visible_handler = None
        if self.active is not None and hasattr(self.panel, "_page_hidden"):
            self.panel._page_hidden(self.active)
        self.active = None
        for key in tuple(self.entries):
            if hasattr(self.panel, "_page_dispose"):
                self.panel._page_dispose(key)
        self.entries.clear()
        self.placeholders.clear()


class PageMap(Mapping):
    """Compatibility mapping: indexing builds only the requested page."""

    def __init__(self, host, keys):
        self.host = host
        self._keys = tuple(keys)

    def __getitem__(self, key):
        if key not in self._keys:
            raise KeyError(key)
        return self.host.page(key)

    def __contains__(self, key):
        return key in self._keys

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    def values(self):
        return [self.host.page(key) for key in self._keys]

    def items(self):
        return [(key, self.host.page(key)) for key in self._keys]
