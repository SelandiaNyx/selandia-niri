#!/usr/bin/env python3
"""Re-derive the post-fix evidence for the audit findings, as JSON.

Run: python3 -B .validation/verify-fixes.py > .validation/fix-summary.json

Only read-only measurements are taken: no compositor, hardware, user setting or
service is touched. A1's cgroup lifecycle needs a reachable user systemd manager
and is reported here as skipped with its reason rather than assumed.
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))
sys.path.insert(0, str(ROOT / "tools"))

import bar_fit
import bar_layout
import font_scale
import i18n
import lock_session
import shortcuts

CJK = re.compile(r"[\u3400-\u9fff]")
report = {}


def systemd_available():
    try:
        result = subprocess.run(["systemctl", "--user", "show", "selandia-niri@.service",
                                 "--property=LoadState", "--value"],
                                capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if result.returncode:
        return False, (result.stderr or result.stdout).strip()
    return result.stdout.strip() == "loaded", result.stdout.strip()


available, detail = systemd_available()
report["A1"] = {
    "launcher_selection": {
        "dedicated_unit_preferred": lock_session.unit_loaded("selandia-lock@.service"),
        "component_unit_available": lock_session.unit_loaded("selandia-niri@.service"),
        "inside_service_unit": lock_session.inside_service_unit(),
    },
    "cgroup_lifecycle_verified": available,
    "note": ("verified with test-only transient units" if available else
             "skipped: no reachable user systemd manager in this environment (" + str(detail) + "); "
             "tests/test_lock_isolation.py asserts this on a real session"),
}

i18n.set_language("en_US")
english = [row for row in shortcuts.load_shortcuts() if CJK.search(row["description"][0])]
i18n.set_language("zh_CN")
chinese = [row for row in shortcuts.load_shortcuts()
           if re.search(r"[A-Za-z][A-Za-z ]* / [\u3400-\u9fff]", row["description"][1])]
i18n.set_language(None)
report["A5"] = {
    "shortcuts": len(shortcuts.load_shortcuts()),
    "english_with_chinese": len(english),
    "chinese_with_english_pair": len(chinese),
    "workspace_target_example": dict(zip(("keys", "english", "chinese"),
                                         (lambda row: (row["keys"], *row["description"]))(
                                             next(r for r in shortcuts.load_shortcuts() if r["keys"] == "Super+1")))),
    "launcher_placeholder": {
        "en_US": "Search applications",
        "zh_CN": "搜索应用",
        "source_template": [line for line in (ROOT / "niri/fuzzel/fuzzel.ini").read_text().splitlines()
                            if line.startswith("placeholder")][0],
    },
}

report["A3"] = {
    "measured_requirement": {layout: bar_fit.required(layout, 16) for layout in bar_layout.LAYOUTS},
    "reported_narrow_output": {"logical_width": 1067, "font_size": 16,
                               "layout": bar_layout.select(width=1067, size=16)},
    "acceptance": {f"{size}px": {name: bar_layout.select(width=width, size=size)
                                 for name, width in (("1920x1080@150%", 1280),
                                                     ("2560x1440@200%", 1280),
                                                     ("3840x2160@150%", 2560))}
                   for size in (12, 16, 20)},
    "compact_right": list(bar_layout.COMPACT_MODULES_RIGHT),
    "connected_outputs": bar_layout.output_widths(),
}

report["A8"] = {
    "interface_px_to_points": {str(px): font_scale.whole_points(px) for px in (12, 13, 16, 20)},
    "gtk_font_16px": font_scale.pango("Noto Sans", 16),
    "qt_font_16px": font_scale.qt("Noto Sans", 16),
    "fuzzel_16px": font_scale.fuzzel_pattern("Inter", font_scale.launcher_pixels(16)),
    "lock_16px_points": font_scale.whole_points(font_scale.lock_pixels(16)),
    "terminal_14pt_unchanged": font_scale.qt_points("Iosevka Term", 14),
}

# A4 needs GTK; it is measured with the same pipeline as tests/test_panel_icons.py.
try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
    import control_widgets

    def alpha_counts(pixbuf):
        data = pixbuf.get_pixels()
        channels = pixbuf.get_n_channels()
        stride = pixbuf.get_rowstride()
        counts = {"transparent": 0, "partial": 0, "opaque": 0}
        for row in range(pixbuf.get_height()):
            base = row * stride
            for column in range(pixbuf.get_width()):
                alpha = data[base + column * channels + channels - 1]
                counts["transparent" if alpha == 0 else "opaque" if alpha == 255 else "partial"] += 1
        counts["solid"] = counts["transparent"] == 0
        return counts

    def load(theme, scale):
        info = theme.lookup_icon_for_scale("input-keyboard-symbolic", 18, scale,
                                           Gtk.IconLookupFlags.FORCE_SYMBOLIC)
        colour = Gdk.RGBA()
        colour.parse("#2e3436")
        loaded = info.load_symbolic(colour, colour, colour, colour)
        return (loaded[0] if isinstance(loaded, tuple) else loaded), info.get_filename()

    system_theme = Gtk.IconTheme.get_default()
    with tempfile.TemporaryDirectory(prefix="selandia-fix-summary-") as runtime:
        root = control_widgets.build_extension(control_widgets.active_theme_name(), runtime)
        theme = Gtk.IconTheme.new()
        theme.set_screen(Gdk.Screen.get_default())
        theme.set_search_path([str(root), *system_theme.get_search_path()])
        theme.set_custom_theme(control_widgets.EXTENSION_NAME)
        icons = {}
        # GTK renders fractional scaling with an integer buffer: 1 = 100%,
        # 2 = 150% (the reported solid square), 3 = 200%.
        for scale, label in ((1, "100%"), (2, "150%"), (3, "200%")):
            before, before_path = load(system_theme, scale)
            after, after_path = load(theme, scale)
            icons[label] = {"before": alpha_counts(before), "before_file": before_path,
                            "after": alpha_counts(after), "after_file": after_path}
        report["A4"] = {"system_theme": Gtk.Settings.get_default().get_property("gtk-icon-theme-name"),
                        "extension_name": control_widgets.EXTENSION_NAME, "scales": icons}
except Exception as error:
    report["A4"] = {"error": str(error)}

report["A2_A6_A7"] = {
    "note": "asserted by the unit tests, each of which fails on the pre-fix code",
    "tests": {
        "A2": "tests/test_panel_lifecycle.py (commit task completes after the window is destroyed)",
        "A6": "tests/test_power_actions.py (Stay awake refuses before locking; suspend failure is reported)",
        "A7": "tests/test_settings_refresh.py (the form is frozen during a re-read; a stale result is ignored)",
    },
}
report["verification_limits"] = [
    "A1 cgroup lifecycle needs a reachable user systemd manager; tests/test_lock_isolation.py skips otherwise",
    "A3 visual acceptance at 1920x1080@150%, 2560x1440@200% and 3840x2160@150% needs a compositor",
    "A4/A3/A5 screenshots need a nested compositor; the nested Niri cannot start in this sandbox",
    "application_theme writes ~/.config, which this sandbox keeps read-only; the converted GTK/Qt font "
    "values are asserted in tests and take effect when Appearance is applied on the desktop",
]
print(json.dumps(report, ensure_ascii=False, indent=2))
