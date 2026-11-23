from __future__ import annotations

import calendar
import datetime
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GObject, Gtk
from i18n import get_language


MONTH_NAMES_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]
MONTH_NAMES_ZH = [
    "一月", "二月", "三月", "四月", "五月", "六月",
    "七月", "八月", "九月", "十月", "十一月", "十二月"
]
WEEKDAY_NAMES_EN = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
WEEKDAY_NAMES_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _clamp(val: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(val, maximum))


class LocalizedCalendar(Gtk.Box):
    __gsignals__ = {
        "day-selected": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, year: int | None = None, month: int | None = None, day: int | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.get_style_context().add_class("glass-calendar")

        today = datetime.date.today()
        self.year = year if year is not None else today.year
        self.month = month if month is not None else (today.month - 1)  # 0-based
        self.day = day if day is not None else today.day

        self._clamp_current_date()

        self.month_label = Gtk.Label()
        self.month_label.get_style_context().add_class("calendar-title")
        self.weekday_labels: list[Gtk.Label] = []
        self.day_buttons: dict[int, Gtk.Button] = {}

        self.prev_button = Gtk.Button(label="‹")
        self.next_button = Gtk.Button(label="›")
        self.prev_button.get_style_context().add_class("calendar-nav-btn")
        self.next_button.get_style_context().add_class("calendar-nav-btn")
        self.prev_button.connect("clicked", lambda _: self._navigate_month(-1))
        self.next_button.connect("clicked", lambda _: self._navigate_month(1))

        self.grid = Gtk.Grid()
        self.grid.set_column_spacing(3)
        self.grid.set_row_spacing(3)
        self.grid.set_row_homogeneous(True)
        self.grid.set_column_homogeneous(True)

        self._build_ui()
        self.add_events(Gdk.EventMask.SCROLL_MASK)
        self.connect("scroll-event", self._on_scroll)
        self.connect("key-press-event", self._on_key_press)

    def _clamp_current_date(self):
        self.year = _clamp(self.year, 1, 9999)
        self.month = _clamp(self.month, 0, 11)
        max_d = _days_in_month(self.year, self.month + 1)
        self.day = _clamp(self.day, 1, max_d)

    def _is_zh(self) -> bool:
        return get_language() == "zh_CN"

    def _build_ui(self):
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.get_style_context().add_class("calendar-header")
        header_box.pack_start(self.prev_button, False, False, 0)
        header_box.pack_start(self.month_label, True, True, 0)
        header_box.pack_end(self.next_button, False, False, 0)
        self.pack_start(header_box, False, False, 0)

        self.pack_start(self.grid, True, True, 0)
        self._refresh()

    def _refresh(self):
        zh = self._is_zh()
        prev_name = "上个月" if zh else "Previous Month"
        next_name = "下个月" if zh else "Next Month"
        self.prev_button.get_accessible().set_name(prev_name)
        self.prev_button.set_tooltip_text(prev_name)
        self.next_button.get_accessible().set_name(next_name)
        self.next_button.set_tooltip_text(next_name)
        self.prev_button.set_sensitive((self.year, self.month) != (1, 0))
        self.next_button.set_sensitive((self.year, self.month) != (9999, 11))

        if zh:
            m_text = f"{self.year}年 {MONTH_NAMES_ZH[self.month]}"
        else:
            m_text = f"{MONTH_NAMES_EN[self.month]} {self.year}"
        self.month_label.set_text(m_text)
        self.set_tooltip_text("Ctrl + 滚轮切换月份" if zh else "Ctrl + scroll to change month")

        for child in self.grid.get_children():
            self.grid.remove(child)
            child.destroy()

        self.weekday_labels.clear()
        self.day_buttons.clear()

        # Week header
        wn_lbl = Gtk.Label(label="Wk" if not zh else "周")
        wn_lbl.get_style_context().add_class("calendar-week-header")
        self.grid.attach(wn_lbl, 0, 0, 1, 1)

        wd_names = WEEKDAY_NAMES_ZH if zh else WEEKDAY_NAMES_EN
        for col_idx, wd in enumerate(wd_names, start=1):
            wlbl = Gtk.Label(label=wd)
            wlbl.get_style_context().add_class("calendar-weekday-header")
            self.weekday_labels.append(wlbl)
            self.grid.attach(wlbl, col_idx, 0, 1, 1)

        cal = calendar.Calendar(firstweekday=calendar.MONDAY)
        weeks = list(cal.monthdays2calendar(self.year, self.month + 1))
        # A fixed six-row frame keeps the drawer allocation stable when the
        # selected month needs only four or five week rows.
        while len(weeks) < 6:
            weeks.append([(0, 0)] * 7)
        today_date = datetime.date.today()

        for row_idx, week in enumerate(weeks[:6], start=1):
            valid_days = [d for d, _ in week if d != 0]
            if valid_days:
                rep_day = valid_days[0]
                iso_week = datetime.date(self.year, self.month + 1, rep_day).isocalendar()[1]
                week_text = f"{iso_week:02d}"
            else:
                week_text = ""

            week_lbl = Gtk.Label(label=week_text)
            week_lbl.get_style_context().add_class("calendar-week-num")
            self.grid.attach(week_lbl, 0, row_idx, 1, 1)

            for col_idx, (d, _) in enumerate(week, start=1):
                if d == 0:
                    empty_lbl = Gtk.Label(label="")
                    empty_lbl.get_style_context().add_class("calendar-empty-cell")
                    self.grid.attach(empty_lbl, col_idx, row_idx, 1, 1)
                    continue

                btn = Gtk.Button(label=str(d))
                full_date = datetime.date(self.year, self.month + 1, d).isoformat()
                btn.get_accessible().set_name(full_date)
                btn.set_tooltip_text(full_date)
                btn.get_style_context().add_class("calendar-day-btn")
                is_today = (self.year == today_date.year and (self.month + 1) == today_date.month and d == today_date.day)
                if is_today:
                    btn.get_style_context().add_class("today")
                if d == self.day:
                    btn.get_style_context().add_class("selected")
                    btn.set_can_focus(True)
                else:
                    btn.set_can_focus(False)

                btn.connect("clicked", self._make_day_clicked_handler(d))
                self.day_buttons[d] = btn
                self.grid.attach(btn, col_idx, row_idx, 1, 1)

        self._rendered_key = (today_date, zh)
        self.grid.show_all()

    def _make_day_clicked_handler(self, d: int):
        def _handler(_):
            self.select_day(d)
        return _handler

    def _navigate_month(self, delta: int):
        target_m = self.month + delta
        target_y = self.year + (target_m // 12)
        target_m = target_m % 12
        if 1 <= target_y <= 9999:
            self.select_month(target_m, target_y)

    def _on_scroll(self, _widget, event: Gdk.EventScroll) -> bool:
        # Leave ordinary wheel events to the enclosing ScrolledWindow, so all
        # six weeks remain reachable in short drawers and at larger text sizes.
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return False
        if event.direction == Gdk.ScrollDirection.UP:
            self._navigate_month(-1)
            return True
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self._navigate_month(1)
            return True
        return False

    def _on_key_press(self, _widget, event: Gdk.EventKey) -> bool:
        kv = event.keyval
        state = event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK)

        if kv in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            self.select_day(1)
            return True
        elif kv in (Gdk.KEY_End, Gdk.KEY_KP_End):
            self.select_day(_days_in_month(self.year, self.month + 1))
            return True
        elif kv in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down):
            delta = -1 if kv == Gdk.KEY_Left else (1 if kv == Gdk.KEY_Right else (-7 if kv == Gdk.KEY_Up else 7))
            self._move_relative(delta_days=delta)
            return True
        elif kv in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            direction = -1 if kv == Gdk.KEY_Page_Up else 1
            if state & Gdk.ModifierType.CONTROL_MASK:
                self._move_relative(delta_years=direction)
            else:
                self._move_relative(delta_months=direction)
            return True
        return False

    def _move_relative(self, delta_days: int = 0, delta_months: int = 0, delta_years: int = 0):
        if delta_days != 0:
            try:
                curr_date = datetime.date(self.year, self.month + 1, self.day)
                new_date = curr_date + datetime.timedelta(days=delta_days)
                if 1 <= new_date.year <= 9999:
                    month_changed = (new_date.year != self.year or (new_date.month - 1) != self.month)
                    self.year = new_date.year
                    self.month = new_date.month - 1
                    self.day = new_date.day
                    if month_changed:
                        self._refresh()
                    else:
                        self._update_day_focus_and_selection()
                    self.emit("day-selected")
                    if self.day in self.day_buttons:
                        self.day_buttons[self.day].grab_focus()
            except OverflowError:
                pass
            return

        target_y = self.year + delta_years
        target_m = self.month + delta_months
        target_y += target_m // 12
        target_m %= 12
        if 1 <= target_y <= 9999:
            self.year = target_y
            self.month = target_m
            max_d = _days_in_month(self.year, self.month + 1)
            self.day = _clamp(self.day, 1, max_d)
            self._refresh()
            self.emit("day-selected")
            if self.day in self.day_buttons:
                self.day_buttons[self.day].grab_focus()

    def _update_day_focus_and_selection(self):
        for d, btn in self.day_buttons.items():
            sc = btn.get_style_context()
            if d == self.day:
                sc.add_class("selected")
                btn.set_can_focus(True)
            else:
                sc.remove_class("selected")
                btn.set_can_focus(False)

    def get_date(self) -> tuple[int, int, int]:
        return (self.year, self.month, self.day)

    def refresh_today(self):
        """Rebuild the six-row grid when the date or language changed since last render."""
        current_key = (datetime.date.today(), self._is_zh())
        if getattr(self, "_rendered_key", None) == current_key:
            return
        toplevel = self.get_toplevel()
        focused = toplevel.get_focus() if isinstance(toplevel, Gtk.Window) else None
        day_had_focus = bool(focused) and any(
            focused is button or focused.is_ancestor(button)
            for button in self.day_buttons.values())
        self._refresh()
        if day_had_focus and self.day in self.day_buttons:
            self.day_buttons[self.day].grab_focus()

    def select_month(self, month: int, year: int):
        self.year = _clamp(year, 1, 9999)
        self.month = _clamp(month, 0, 11)
        max_d = _days_in_month(self.year, self.month + 1)
        self.day = _clamp(self.day, 1, max_d)
        self._refresh()
        self.emit("day-selected")
        if self.day in self.day_buttons and self.day_buttons[self.day].get_can_focus():
            self.day_buttons[self.day].grab_focus()

    def select_day(self, day: int):
        max_d = _days_in_month(self.year, self.month + 1)
        new_d = _clamp(day, 1, max_d)
        if new_d != self.day or not self.day_buttons:
            self.day = new_d
            self._update_day_focus_and_selection()
            self.emit("day-selected")
        if self.day in self.day_buttons:
            self.day_buttons[self.day].grab_focus()
