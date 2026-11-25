"""Unified Preferences & Startup page combining Applications, Language, Time & Startup."""
from __future__ import annotations

import datetime

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from control_widgets import nyx_guide_banner, pack, style, wrap_label
from i18n import tr
from language_controls import LanguageSettings
from system_controls import ApplicationsSettings, StartupSettings, TimeSettings


class PreferencesPage(Gtk.Box):
    """Four high-cohesion MD3 subtabs replacing four sparse single-column pages."""

    SUBTABS = (
        ("applications", "Default apps", "默认应用"),
        ("language", "Language & region", "语言与地区"),
        ("time", "Date & time", "日期与时间"),
        ("startup", "Startup", "开机启动"),
    )

    def __init__(self, panel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.panel = panel
        self._clock_source = None

        pack(self, nyx_guide_banner(
            "preferences",
            tr("Manage default applications, system language, live clock/timezone, and Niri autostart apps in one place.",
               "将默认应用、语言与地区、实时时钟/时区同步以及 Niri 开机自启动整合在四个清晰分页中。"),
        ))

        tab_bar = style(Gtk.Box(spacing=6), "md3-subtabs")
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        for key, en, zh in self.SUBTABS:
            btn = Gtk.ToggleButton(label=tr(en, zh))
            btn.connect("toggled", self._on_toggle, key)
            pack(tab_bar, btn, True)
            self._buttons[key] = btn
        pack(self, tab_bar)

        self.stack = Gtk.Stack()
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)

        self.subpages = {
            "applications": ApplicationsSettings(panel),
            "language": LanguageSettings(panel),
            "time": self._wrap_time(TimeSettings(panel)),
            "startup": StartupSettings(panel),
        }
        for key, widget in self.subpages.items():
            self.stack.add_named(widget, key)
        pack(self, self.stack, True)

        self.connect("destroy", lambda *_: self.suspend())
        self.select_subtab("applications")

    def _wrap_time(self, time_page: TimeSettings) -> Gtk.Box:
        wrapper = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clock_card = style(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4), "card")
        pack(clock_card, wrap_label(tr("LIVE SYSTEM CLOCK", "实时系统时钟"), "section-title"))
        self._live_time = pack(clock_card, wrap_label("", "clock"))
        self._live_date = pack(clock_card, wrap_label("", "hint"))
        pack(wrapper, clock_card)
        pack(wrapper, time_page, True)
        wrapper._inner = time_page
        self._tick_clock()
        return wrapper

    def _tick_clock(self):
        if getattr(self, "_live_time", None) is None:
            return GLib.SOURCE_REMOVE
        now = datetime.datetime.now()
        self._live_time.set_text(now.strftime("%H:%M:%S"))
        self._live_date.set_text(now.strftime("%Y-%m-%d  %A"))
        return GLib.SOURCE_CONTINUE

    def resume(self):
        if self._clock_source is None and self.panel.alive:
            self._tick_clock()
            self._clock_source = GLib.timeout_add_seconds(1, self._tick_clock)

    def suspend(self):
        src = self._clock_source
        self._clock_source = None
        if src is not None:
            GLib.source_remove(src)

    def _on_toggle(self, btn, key):
        if not btn.get_active():
            return
        for other_key, other in self._buttons.items():
            if other_key != key and other.get_active():
                other.set_active(False)
        self.stack.set_visible_child_name(key)
        page = self.subpages[key]
        inner = getattr(page, "_inner", page)
        if hasattr(inner, "refresh") and not getattr(inner, "busy", False):
            inner.refresh()

    def select_subtab(self, key: str | None):
        target = key if key in self._buttons else "applications"
        btn = self._buttons[target]
        if not btn.get_active():
            btn.set_active(True)
        else:
            self.stack.set_visible_child_name(target)
        self.resume()

    def cycle_subtab(self, delta: int):
        keys = [item[0] for item in self.SUBTABS]
        current = self.stack.get_visible_child_name() or keys[0]
        idx = keys.index(current) if current in keys else 0
        self.select_subtab(keys[(idx + delta) % len(keys)])

    def refresh(self):
        active = self.stack.get_visible_child_name() or "applications"
        page = self.subpages.get(active)
        inner = getattr(page, "_inner", page)
        if hasattr(inner, "refresh") and not getattr(inner, "busy", False):
            inner.refresh()
        self.resume()
