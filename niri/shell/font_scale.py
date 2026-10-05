#!/usr/bin/env python3
"""One canonical interface font size, converted explicitly per backend.

The interface size is a logical pixel value at the standard 96 CSS DPI. Each
backend now gets an explicit conversion instead of being handed the same number:

* panel, bar and notification CSS use the logical pixel value directly;
* GTK/Pango, Qt/KDE and the GNOME font name use points, rounded because those
  formats store whole points (16px becomes 12pt);
* Fuzzel uses Fontconfig ``pixelsize`` so its text matches the panel on every
  output scale without a second DPI multiplication;
* swaylock keeps the lock screen's own larger design step, converted to points;
* the terminal keeps its independent point size and is never converted here.
"""
from __future__ import annotations

CSS_DPI = 96.0
POINTS_PER_INCH = 72.0
# Design steps, expressed in the canonical logical-pixel unit.
LAUNCHER_EXTRA_PX = 1.0
LOCK_SCREEN_MULTIPLIER = 2.0


def points(logical_px):
    """Exact point size for a logical pixel size at 96 DPI."""
    return float(logical_px) * POINTS_PER_INCH / CSS_DPI


def whole_points(logical_px):
    """Whole points: Pango, Qt and KDE configurations store integers."""
    return int(round(points(logical_px)))


def pango(family, logical_px):
    """A Pango/GTK/GNOME font description string converted from logical pixels."""
    return f"{family} {whole_points(logical_px)}"


def qt(family, logical_px):
    """A KDE ``kdeglobals``/qt6ct font string converted from logical pixels."""
    return f"{family},{whole_points(logical_px)},-1,5,50,0,0,0,0,0"


def pango_points(family, point_size):
    """A Pango font description for a size that is *already* in points."""
    return f"{family} {points_value(point_size)}"


def qt_points(family, point_size):
    """A KDE font string for a size that is *already* in points."""
    return f"{family},{points_value(point_size)},-1,5,50,0,0,0,0,0"


def points_value(point_size):
    """An independent point size, passed through without a pixel conversion."""
    return int(round(float(point_size)))


def fuzzel_pattern(family, logical_px):
    """A Fontconfig pattern pinned to pixels so Fuzzel never re-applies DPI."""
    return f"{family}:pixelsize={float(logical_px):g}"


def launcher_pixels(logical_px):
    """The launcher's slightly larger design step, in logical pixels."""
    return float(logical_px) + LAUNCHER_EXTRA_PX


def lock_pixels(logical_px):
    """The lock screen's larger design step, in logical pixels."""
    return float(logical_px) * LOCK_SCREEN_MULTIPLIER


