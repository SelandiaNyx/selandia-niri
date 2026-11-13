#!/usr/bin/env python3
"""Render every settings page with private native GTK fixtures and record geometry."""
import json
import os
from pathlib import Path
import signal
import sys
import time
import unittest
from unittest.mock import patch

if os.environ.get("SELANDIA_PRIVATE_PROBE") != "1":
    raise SystemExit("Run through smoke.py --daily-ui-probe-only")

import cairo
from panel_probe import PanelInteractionTests, Gdk, Gtk, descendants, pump_until, wait_gtk
import appearance
import i18n
import panel_geometry
from navigation_catalog import PAGE_KEYS

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC_KIND = os.environ.get("SELANDIA_UI_DIAGNOSTIC", "")
CALENDAR_DIAGNOSTIC = DIAGNOSTIC_KIND == "calendar16"
DIAGNOSTIC = DIAGNOSTIC_KIND in ("narrow-en-large", "calendar16")
ARTIFACTS = ROOT / ".validation" / ("daily-calendar-diagnostic" if CALENDAR_DIAGNOSTIC
                                    else "daily-ui-diagnostic" if DIAGNOSTIC else "daily-ui")
CONFIGURATIONS = (
    ("wide-zh-dark", "zh_CN", "dark", 1200, 850, 12),
    ("wide-zh-light", "zh_CN", "light", 1200, 850, 12),
    ("wide-en-dark", "en_US", "dark", 1200, 850, 12),
    ("wide-en-light", "en_US", "light", 1200, 850, 12),
    ("narrow-zh-dark", "zh_CN", "dark", 620, 850, 12),
    ("narrow-en-light", "en_US", "light", 620, 850, 12),
    ("wide-zh-large", "zh_CN", "dark", 1200, 850, 20),
    ("narrow-en-large", "en_US", "light", 620, 850, 20),
)
if CALENDAR_DIAGNOSTIC:
    CONFIGURATIONS = (("calendar-zh-16", "zh_CN", "dark", 420, 580, 16),)
elif DIAGNOSTIC:
    CONFIGURATIONS = tuple(config for config in CONFIGURATIONS if config[0] == "narrow-en-large")
RENDER_PAGES = ("calendar",) if CALENDAR_DIAGNOSTIC else ("quick",) if DIAGNOSTIC else PAGE_KEYS


def rect(widget, relative):
    point = widget.translate_coordinates(relative, 0, 0)
    if point is None:
        return None
    return [*point, widget.get_allocated_width(), widget.get_allocated_height()]


def minimum_tree(widget, window):
    """Describe native GTK requests and the CSS costs around each direct child."""
    context = widget.get_style_context()
    def sides(method):
        value = method(Gtk.StateFlags.NORMAL)
        return [value.left, value.right]
    result = {"type": type(widget).__name__, "classes": list(context.list_classes()),
              "rect": rect(widget, window), "preferred_width": list(widget.get_preferred_width()),
              "preferred_at_height": list(widget.get_preferred_width_for_height(widget.get_allocated_height())),
              "preferred_height": list(widget.get_preferred_height()),
              "preferred_at_width": list(widget.get_preferred_height_for_width(widget.get_allocated_width())),
              "size_request": list(widget.get_size_request()), "mapped": widget.get_mapped(),
              "padding": sides(context.get_padding), "border": sides(context.get_border),
              "css_margin": sides(context.get_margin),
              "widget_margin": [widget.get_margin_start(), widget.get_margin_end()]}
    for property_name, getter in (("padding", context.get_padding), ("border", context.get_border),
                                   ("css_margin", context.get_margin)):
        value = getter(Gtk.StateFlags.NORMAL)
        result[property_name + "_vertical"] = [value.top, value.bottom]
    font = context.get_font(Gtk.StateFlags.NORMAL)
    result.update(font=font.to_string(), font_size=font.get_size() / 1024,
                  font_absolute=font.get_size_is_absolute(),
                  css_min_height=context.get_property("min-height", Gtk.StateFlags.NORMAL))
    if isinstance(widget, Gtk.Label):
        result.update(text=widget.get_text(), width_chars=widget.get_width_chars(),
                      max_width_chars=widget.get_max_width_chars())
    if isinstance(widget, Gtk.Box):
        result.update(orientation=int(widget.get_orientation()), spacing=widget.get_spacing(),
                      homogeneous=widget.get_homogeneous())
    if isinstance(widget, Gtk.Container):
        children = []
        widget.forall(children.append)
        result["children"] = [minimum_tree(child, window) for child in children if child.get_visible()]
    return result


class DailyUIInteractionTests(PanelInteractionTests):
    records = []

    def install_theme(self, preferences):
        screen = Gdk.Screen.get_default()
        for css in ((ROOT / "niri/shell/style.css").read_text(),
                    (ROOT / "niri/shell/control_center.css").read_text(),
                    appearance.render_files(preferences)["panel.css"]):
            provider = Gtk.CssProvider()
            provider.load_from_data(css.encode())
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            self.addCleanup(Gtk.StyleContext.remove_provider_for_screen, screen, provider)

    def ready(self, window, key):
        entry = window.page_host.entries.get(key)
        if entry is None or not entry.widget.get_mapped():
            return False
        content = entry.content
        return not any((getattr(content, "busy", False), getattr(content, "loading", False),
                        getattr(window, "appearance_busy", False), getattr(window, "audio_loading", False),
                        getattr(window, "metrics_busy", False)))

    def inspect(self, window, key, configuration):
        entry = window.page_host.entries[key]
        content, page = entry.content, entry.widget
        issues = []
        width, height = window.get_allocated_width(), window.get_allocated_height()
        record = {"configuration": configuration[0], "page": key, "window": [width, height],
                  "heading": rect(window.page_heading, window), "page_rect": rect(page, window),
                  "controls": [], "scrolls": [], "issues": issues}
        navigation = window.navigation
        selected = navigation.list.get_selected_row()
        nav_scroll = navigation.scroll
        selected_rect = rect(selected, nav_scroll) if selected is not None else None
        record["navigation"] = {"selected_key": getattr(selected, "key", None),
                                "selected_row": selected_rect,
                                "viewport": [nav_scroll.get_allocated_width(), nav_scroll.get_allocated_height()],
                                "scroll_value": nav_scroll.get_vadjustment().get_value()}
        if selected is None or getattr(selected, "key", None) != key:
            issues.append("navigation selection does not match the visible page")
        elif not selected.get_mapped() or selected_rect is None:
            issues.append("selected navigation row is not mapped")
        else:
            x, y, row_width, row_height = selected_rect
            visible = (x >= -2 and y >= -2 and x + row_width <= nav_scroll.get_allocated_width() + 2
                       and y + row_height <= nav_scroll.get_allocated_height() + 2)
            record["navigation"]["selected_visible"] = visible
            if not visible:
                issues.append("selected navigation row is outside its scroll viewport")
        if width > configuration[3] + 2 or height > configuration[4] + 2:
            issues.append("window exceeds the requested viewport")
        page_box = record["page_rect"]
        if not page_box or min(page_box[2:]) <= 1:
            issues.append("selected page did not allocate visible content")
        elif page_box[0] < 0 or page_box[0] + page_box[2] > width + 2:
            issues.append("page extends beyond the window horizontally")
        cards = [widget for widget in descendants(content)
                 if widget.get_mapped() and widget.get_style_context().has_class("card")]
        if cards:
            record["first_card"] = rect(cards[0], window)
            heading = record["heading"]
            record["heading_to_card"] = record["first_card"][1] - heading[1] - heading[3]
        scrolls = [widget for widget in descendants(page)
                   if isinstance(widget, Gtk.ScrolledWindow) and widget.get_mapped()]
        for scroll in scrolls:
            vertical, horizontal = scroll.get_vadjustment(), scroll.get_hadjustment()
            maximum = max(0, vertical.get_upper() - vertical.get_page_size())
            scroll_record = {"rect": rect(scroll, window), "upper": vertical.get_upper(),
                             "page_size": vertical.get_page_size(), "maximum": maximum}
            record["scrolls"].append(scroll_record)
            if horizontal.get_upper() > horizontal.get_page_size() + 2:
                issues.append("content requires horizontal scrolling")
            # Exercise the real adjustment at both ends. No actions are clicked.
            vertical.set_value(maximum)
            wait_gtk(.015)
            scroll_record["bottom_reached"] = abs(vertical.get_value() - maximum) <= 2
            if not scroll_record["bottom_reached"]:
                issues.append("page bottom cannot be reached")
            vertical.set_value(0)
        wait_gtk(.035)
        for widget in descendants(content):
            if not widget.get_mapped() or not isinstance(widget, (Gtk.Button, Gtk.Entry, Gtk.ComboBox, Gtk.Range)):
                continue
            # GtkComboBox's internal arrow/entry are implementation details;
            # inspect the composite control's allocation once.
            if not isinstance(widget, Gtk.ComboBox) and widget.get_ancestor(Gtk.ComboBox) is not None:
                continue
            allocation = rect(widget, window)
            title = widget.get_label() if isinstance(widget, Gtk.Button) else None
            control = {"type": type(widget).__name__, "text": title, "rect": allocation,
                       "sensitive": widget.is_sensitive()}
            record["controls"].append(control)
            scroll = widget.get_ancestor(Gtk.ScrolledWindow)
            if scroll is not None:
                local = rect(widget, scroll)
                if local is not None:
                    x, y, control_width, control_height = local
                    if x < -2 or x + control_width > scroll.get_allocated_width() + 2:
                        issues.append(f"control overflows horizontally: {title or type(widget).__name__}")
                    adjustment = scroll.get_vadjustment()
                    maximum = max(0, adjustment.get_upper() - adjustment.get_page_size())
                    if y + control_height > scroll.get_allocated_height() + maximum + 3:
                        issues.append(f"control is below the reachable bottom: {title or type(widget).__name__}")
            if isinstance(widget, Gtk.Button):
                control["ellipsized_labels"] = []
                for label in descendants(widget):
                    if not isinstance(label, Gtk.Label) or not label.get_mapped():
                        continue
                    layout = label.get_layout()
                    text_width, text_height = layout.get_pixel_size()
                    if layout.is_ellipsized():
                        control["ellipsized_labels"].append(label.get_text())
                    if not layout.is_ellipsized() and (text_width > label.get_allocated_width() + 2
                                                     or text_height > label.get_allocated_height() + 2):
                        issues.append(f"button text is clipped: {label.get_text()}")
        if key == "quick":
            record["quick_titles"] = {}
            for tile in ("wifi", "bluetooth", "dnd", "idle"):
                toggle, _state = window.tiles[tile]
                labels = [widget for widget in descendants(toggle)
                          if isinstance(widget, Gtk.Label) and widget.get_mapped()
                          and widget.get_style_context().has_class("quick-title")]
                if len(labels) != 1:
                    issues.append(f"Quick tile has no unique visible title: {tile}")
                    continue
                label = labels[0]
                layout = label.get_layout()
                record["quick_titles"][tile] = {"text": label.get_text(), "rect": rect(label, toggle),
                                                "ellipsized": layout.is_ellipsized(),
                                                "text_pixels": list(layout.get_pixel_size())}
                if layout.is_ellipsized():
                    issues.append(f"Quick tile title is ellipsized: {label.get_text()}")
        return record

    def body_focus_is_preserved(self, window, key):
        """Revealing the current category must not steal existing form focus."""
        content = window.page_host.entries[key].content
        for widget in descendants(content):
            if not widget.get_mapped() or not widget.is_sensitive() or not widget.get_can_focus():
                continue
            if not isinstance(widget, (Gtk.Button, Gtk.Entry, Gtk.Range)):
                continue
            scroll = widget.get_ancestor(Gtk.ScrolledWindow)
            if scroll is not None:
                local = rect(widget, scroll)
                if local is None or local[1] < 0 or local[1] + local[3] > scroll.get_allocated_height():
                    continue
            widget.grab_focus()
            wait_gtk(.015)
            before = window.get_focus()
            window.select_control_tab(key, focus=False)
            wait_gtk(.04)
            return {"tested": True, "widget": type(widget).__name__,
                    "retained": before is not None and window.get_focus() == before}
        return {"tested": False, "reason": "no enabled focusable control within the page viewport"}

    def render_configuration(self, configuration):
        if CALENDAR_DIAGNOSTIC:
            self.calendar_diagnostic(configuration)
            return
        name, language, mode, width, height, font = configuration
        i18n.set_language(language)
        self.appearance_fixture = dict(appearance.DEFAULTS, color_mode=mode, font_size=font,
                                       reduced_motion=True)
        self.install_theme(self.appearance_fixture)
        with patch.object(panel_geometry, "dimensions", return_value=(width, height)):
            window = self.make_control("quick", eager=False)
        failures = []
        target = ARTIFACTS / name
        target.mkdir(parents=True, exist_ok=True)
        for key in RENDER_PAGES:
            # The persistent search field provides a valid focus anchor while
            # changing pages. A field in the previous page would be unmapped.
            window.navigation.search.grab_focus()
            before = window.get_focus()
            window.select_control_tab(key, focus=False)
            pump_until(lambda: self.ready(window, key), timeout=5)
            wait_gtk(.08)
            retained = before is not None and window.get_focus() == before
            body_focus = self.body_focus_is_preserved(window, key)
            record = self.inspect(window, key, configuration)
            record["focus"] = {"page_change_retained": retained, "same_page_body": body_focus}
            if DIAGNOSTIC:
                record["minimum_tree"] = minimum_tree(window, window)
            if not retained:
                record["issues"].append("programmatic page change stole focus from the search entry")
            if body_focus["tested"] and not body_focus["retained"]:
                record["issues"].append("revealing the selected category stole focus from a page control")
            # Draw actual mapped GTK widgets, without a screenshot notification,
            # foreign overlays, or fixture text substituted into the image.
            # A background completion can request another allocation after the
            # geometry pass. Settle it before synchronous GTK drawing; reject a
            # transparent image instead of accepting a blank screenshot.
            for _attempt in range(5):
                window.check_resize()
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, *record["window"])
                window.draw(cairo.Context(surface))
                surface.flush()
                if any(surface.get_data()):
                    break
                wait_gtk(.05)
            else:
                record["issues"].append("native GTK screenshot is blank")
            surface.write_to_png(str(target / (key + ".png")))
            record["screenshot"] = str((target / (key + ".png")).relative_to(ARTIFACTS))
            self.records.append(record)
            if record["issues"]:
                failures.append({"page": key, "issues": record["issues"]})
        self.assertFalse(failures, json.dumps(failures, ensure_ascii=False))

    def calendar_diagnostic(self, configuration):
        name, language, mode, width, height, font = configuration
        preferences = dict(appearance.DEFAULTS, font_size=font, color_mode=mode, reduced_motion=True)
        self.install_theme(preferences)
        i18n.set_language(language)
        self.stack.enter_context(patch.object(appearance, "load_settings", return_value=preferences))
        # Keep the actual layer-shell anchors while providing a deterministic
        # short logical viewport on smoke.py's fresh compositor output.
        with patch.object(panel_geometry, "drawer_geometry", side_effect=(
                lambda _side, _width, monitor_height, _font: (width, height, monitor_height - height - 16))):
            window = self.make_panel("calendar")
        pump_until(lambda: window.get_mapped() and window.surface.get_opacity() > 0)
        wait_gtk(.1)
        calendar = window.calendar
        scroll = calendar.get_ancestor(Gtk.ScrolledWindow)
        header = next(widget for widget in descendants(window)
                      if widget.get_style_context().has_class("panel-header"))
        parts = {"panel_header": header, "content": window.content,
                 "calendar_card": calendar.get_parent(), "calendar": calendar, "grid": calendar.grid,
                 "calendar_header": calendar.month_label.get_parent(), "weekday": calendar.weekday_labels[0],
                 "day": calendar.day_buttons[calendar.day], "footer": window.calendar_date.get_parent(),
                 "scroller": scroll}
        record = {"configuration": name, "page": "calendar", "window": list(window.get_size()),
                  "parts": {}, "rows": [], "minimum_tree": minimum_tree(window, window)}
        for part_name, widget in parts.items():
            record["parts"][part_name] = {key: value for key, value in minimum_tree(widget, window).items()
                                         if key != "children"}
        record["grid_homogeneous"] = {"rows": calendar.grid.get_row_homogeneous(),
                                       "columns": calendar.grid.get_column_homogeneous(),
                                       "row_spacing": calendar.grid.get_row_spacing()}
        for row in range(7):
            cells = [child for child in calendar.grid.get_children()
                     if calendar.grid.child_get_property(child, "top-attach") == row]
            record["rows"].append({"row": row, "allocation": rect(cells[0], window),
                                    "maximum_minimum_height": max(child.get_preferred_height()[0] for child in cells),
                                    "cells": [{"type": type(child).__name__,
                                               "text": child.get_label() if isinstance(child, Gtk.Button)
                                                       else child.get_text() if isinstance(child, Gtk.Label) else "",
                                               "height": child.get_allocated_height(),
                                               "preferred_height": list(child.get_preferred_height())} for child in cells]})
        adjustment = scroll.get_vadjustment()
        record["scroll"] = {"value": adjustment.get_value(), "upper": adjustment.get_upper(),
                            "page_size": adjustment.get_page_size()}
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        def capture(name):
            window.check_resize()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, window.get_allocated_width(), window.get_allocated_height())
            window.draw(cairo.Context(surface))
            surface.write_to_png(str(ARTIFACTS / name))
        capture("calendar-top.png")
        # Emit the native signal handled by the same callback as a wheel event.
        # No clipboard, command, real display setting or hardware action runs.
        before_date, before_scroll = calendar.get_date(), adjustment.get_value()
        event = Gdk.Event.new(Gdk.EventType.SCROLL)
        event.direction = Gdk.ScrollDirection.DOWN
        event.state = 0
        event.window = window.get_window()
        event.set_device(Gdk.Display.get_default().get_default_seat().get_pointer())
        handled = calendar.emit("scroll-event", event)
        wait_gtk(.05)
        record["wheel_down"] = {"consumed": handled, "date_before": list(before_date),
                                 "date_after": list(calendar.get_date()), "scroll_before": before_scroll,
                                 "scroll_after": adjustment.get_value()}
        self.assertFalse(handled, "ordinary wheel must reach the enclosing scroller")
        self.assertEqual(calendar.get_date(), before_date)
        # Exercise the actual ancestor's native handler after the calendar
        # declines the event; emission alone does not perform GTK propagation.
        scroll.emit("scroll-event", event)
        wait_gtk(.1)
        record["wheel_down"]["ancestor_scroll_after"] = adjustment.get_value()
        self.assertGreater(adjustment.get_value(), before_scroll)
        event.state = Gdk.ModifierType.CONTROL_MASK
        self.assertTrue(calendar.emit("scroll-event", event))
        self.assertNotEqual(calendar.get_date(), before_date)
        adjustment.set_value(max(0, adjustment.get_upper() - adjustment.get_page_size()))
        wait_gtk(.05)
        capture("calendar-bottom.png")
        footer = record["parts"]["footer"]["rect"]
        self.assertLessEqual(footer[1] + footer[3], height)
        self.records.append(record)
        self.assertEqual(list(window.get_size()), [width, height])


for configuration in CONFIGURATIONS:
    def test(self, configuration=configuration):
        self.render_configuration(configuration)
    setattr(DailyUIInteractionTests, "test_matrix_" + configuration[0].replace("-", "_"), test)


def main():
    state = Path(os.environ.get("XDG_STATE_HOME", ""))
    if (not state.is_absolute() or not state.name.startswith("selandia-smoke-")
            or not os.environ.get("DBUS_SESSION_BUS_ADDRESS") or not os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("Daily UI probe requires smoke.py's isolated session")
    if not Gtk.init_check()[0]:
        raise RuntimeError("Cannot connect to private GTK display")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    names = [name for name in DailyUIInteractionTests.__dict__ if name.startswith("test_matrix_")]
    suite = unittest.TestSuite(DailyUIInteractionTests(name) for name in names)
    def timeout(_signal, _frame):
        raise TimeoutError("Daily UI native probe exceeded 160 seconds")
    signal.signal(signal.SIGALRM, timeout)
    signal.alarm(160)
    started = time.monotonic()
    try:
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        summary = {"configurations": len(CONFIGURATIONS), "expected_pages": len(RENDER_PAGES) * len(CONFIGURATIONS),
                   "rendered_pages": len(DailyUIInteractionTests.records), "failures": len(result.failures),
                   "errors": len(result.errors), "seconds": round(time.monotonic() - started, 3),
                   "private_state": True, "real_hardware_commands": False,
                   "native_gtk_render": True, "diagnostic": DIAGNOSTIC,
                   "records": DailyUIInteractionTests.records}
        (ARTIFACTS / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({key: value for key, value in summary.items() if key != "records"}), flush=True)
        return 0 if result.wasSuccessful() else 1
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    raise SystemExit(main())
