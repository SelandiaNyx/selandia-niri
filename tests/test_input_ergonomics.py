"""Keyboard and mouse ergonomics across top bar, Control Center, modals, and Niri binds."""
from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "niri/shell"))

import gi
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk

import bar_backend
import island
import shortcuts
from panel import Panel
from power_menu import ACTION_IDS, PowerMenu
from clipboard_menu import ClipboardWindow, ConfirmClearWindow
from command_palette import CommandPalette
from calendar_widget import LocalizedCalendar
from panel_preferences import PreferencesPage


def _event(keyval=0, state=0, button=0, direction=None, dy=0.0, y=0.0):
    ev = SimpleNamespace(keyval=keyval, state=state, button=button, direction=direction, y=y)
    ev.get_scroll_deltas = lambda: (True, 0.0, dy)
    return ev


class BarMouseErgonomicsTests(unittest.TestCase):
    def test_top_bar_capsules_expose_scroll_right_click_and_middle_click(self):
        rendered, _ = bar_backend.render([("DP-1", 3840)], size=14)
        left, right, center = rendered.split("(defwindow ")[1:]
        # Left bar: launcher right/middle, workspace scroll, app pill right/middle
        self.assertIn(":onrightclick", left)
        self.assertIn(":onmiddleclick", left)
        self.assertIn("workspace-step {}", left)
        self.assertIn("toggle-window-floating", left)
        self.assertIn("close-window", left)
        # Right bar: audio scroll/mute, wifi & bt right-click toggle, monitor right-click, power/shortcuts on control
        self.assertIn("volume-step {}", right)
        self.assertIn("volume mute", right)
        self.assertIn("toggle-wifi", right)
        self.assertIn("toggle-bluetooth", right)
        self.assertIn("system-monitor", right)
        self.assertIn("swaync-client --skip-wait -d", right)
        self.assertIn(" power", right)
        self.assertIn(" shortcuts", right)
        # Dynamic Island: media right-click play/pause, middle-click next, wheel volume; clock right-click DND
        self.assertIn("media-quick", center)
        self.assertIn("playerctl next", center)
        self.assertIn("volume-step {}", center)
        self.assertIn("swaync-client --skip-wait -d", center)

    def test_sample_bluetooth_reads_singular_adapter_state_and_connected_devices(self):
        mock_bt = MagicMock()
        mock_bt.read_state.return_value = {
            "available": True,
            "adapter": {"path": "/org/bluez/hci0", "powered": True},
            "devices": [{"name": "WH-1000XM5", "connected": True}],
        }
        with patch.dict(sys.modules, {"bluetooth_backend": mock_bt}):
            st = island.sample_bluetooth()
        self.assertTrue(st["bt_on"])
        self.assertEqual(st["bt_icon"], "󰂱 1")
        self.assertIn("WH-1000XM5", st["bt_tooltip"])

        mock_bt.read_state.return_value = {
            "available": True,
            "adapter": {"path": "/org/bluez/hci0", "powered": False},
            "devices": [],
        }
        with patch.dict(sys.modules, {"bluetooth_backend": mock_bt}):
            st_off = island.sample_bluetooth()
        self.assertFalse(st_off["bt_on"])
        self.assertEqual(st_off["bt_icon"], "󰂲")


class NiriMouseBindsTests(unittest.TestCase):
    def test_mouse_wheel_and_thumb_button_binds_exist_and_categorize_under_mouse(self):
        rows = {row["keys"]: row for row in shortcuts.load_shortcuts()}
        expected = (
            "Super+Shift+WheelScrollUp",
            "Super+Shift+WheelScrollDown",
            "Super+Ctrl+WheelScrollUp",
            "Super+Ctrl+WheelScrollDown",
            "Super+WheelScrollLeft",
            "Super+WheelScrollRight",
            "Super+MouseBack",
            "Super+MouseForward",
            "Super+MouseMiddle",
        )
        for key in expected:
            with self.subTest(key=key):
                self.assertIn(key, rows)
                self.assertEqual(rows[key]["category"], ("Mouse", "鼠标"))


class PanelInputErgonomicsTests(unittest.TestCase):
    def test_mouse_side_buttons_navigate_control_center_and_calendar(self):
        dummy = SimpleNamespace(
            mode="control",
            nav_back=MagicMock(),
            nav_forward=MagicMock(),
        )
        self.assertTrue(Panel.on_button(dummy, None, _event(button=8)))
        dummy.nav_back.assert_called_once()
        self.assertTrue(Panel.on_button(dummy, None, _event(button=9)))
        dummy.nav_forward.assert_called_once()
        self.assertFalse(Panel.on_button(dummy, None, _event(button=1)))

        cal = SimpleNamespace(_navigate_month=MagicMock())
        dummy_cal = SimpleNamespace(mode="calendar", calendar=cal)
        self.assertTrue(Panel.on_button(dummy_cal, None, _event(button=8)))
        cal._navigate_month.assert_called_with(-1)
        self.assertTrue(Panel.on_button(dummy_cal, None, _event(button=9)))
        cal._navigate_month.assert_called_with(1)

    def test_panel_keyboard_shortcuts_for_control_calendar_and_ai(self):
        # Control: '/' focuses sidebar search when not in text input, Alt+Home goes to quick, Ctrl+PageDown steps
        nav_search = MagicMock()
        dummy = SimpleNamespace(
            mode="control",
            command_palette=None,
            navigation=SimpleNamespace(search=nav_search, group_first_keys=("quick", "network")),
            get_focus=lambda: None,
            _is_text_input=Panel._is_text_input,
            select_control_tab=MagicMock(),
            _step_page_or_subtab=MagicMock(),
            _toggle_pane_focus=MagicMock(),
            active_popover=None,
        )
        self.assertTrue(Panel.on_key(dummy, None, _event(keyval=Gdk.KEY_slash)))
        nav_search.grab_focus.assert_called_once()
        self.assertTrue(Panel.on_key(dummy, None, _event(keyval=Gdk.KEY_Home, state=Gdk.ModifierType.MOD1_MASK)))
        dummy.select_control_tab.assert_called_with("quick", focus=True)
        self.assertTrue(Panel.on_key(dummy, None, _event(keyval=Gdk.KEY_Page_Down, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy._step_page_or_subtab.assert_called_with(1)
        self.assertTrue(Panel.on_key(dummy, None, _event(keyval=Gdk.KEY_F6)))
        dummy._toggle_pane_focus.assert_called_once()

        # Calendar: T -> today, Ctrl+C -> copy, Alt+Right -> next month
        cal = SimpleNamespace(_navigate_month=MagicMock())
        dummy_cal = SimpleNamespace(
            mode="calendar",
            calendar=cal,
            _calendar_today=MagicMock(),
            _calendar_copy=MagicMock(),
            active_popover=None,
        )
        self.assertTrue(Panel.on_key(dummy_cal, None, _event(keyval=Gdk.KEY_t)))
        dummy_cal._calendar_today.assert_called_once()
        self.assertTrue(Panel.on_key(dummy_cal, None, _event(keyval=Gdk.KEY_c, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy_cal._calendar_copy.assert_called_once()
        self.assertTrue(Panel.on_key(dummy_cal, None, _event(keyval=Gdk.KEY_Right, state=Gdk.ModifierType.MOD1_MASK)))
        cal._navigate_month.assert_called_with(1)

        # AI: Ctrl+N new chat, Ctrl+Shift+C copy reply, Ctrl+, settings
        dummy_ai = SimpleNamespace(
            mode="ai",
            new_ai_chat=MagicMock(),
            copy_reply=MagicMock(),
            toggle_settings=MagicMock(),
            stop_chat=MagicMock(),
            active_popover=None,
        )
        self.assertTrue(Panel.on_key(dummy_ai, None, _event(keyval=Gdk.KEY_n, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy_ai.new_ai_chat.assert_called_once()
        self.assertTrue(Panel.on_key(dummy_ai, None, _event(keyval=Gdk.KEY_C, state=Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)))
        dummy_ai.copy_reply.assert_called_once()
        self.assertTrue(Panel.on_key(dummy_ai, None, _event(keyval=Gdk.KEY_comma, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy_ai.toggle_settings.assert_called_once()

    def test_calendar_smooth_and_shift_scroll_flips_months(self):
        dummy = SimpleNamespace(_smooth_scroll_accum=0.0, _navigate_month=MagicMock())
        # Shift + discrete UP -> previous month
        self.assertTrue(LocalizedCalendar._on_scroll(
            dummy, None, _event(state=Gdk.ModifierType.SHIFT_MASK, direction=Gdk.ScrollDirection.UP)
        ))
        dummy._navigate_month.assert_called_with(-1)
        # Ctrl + smooth scroll accumulates until >= 0.5
        dummy._navigate_month.reset_mock()
        self.assertTrue(LocalizedCalendar._on_scroll(
            dummy, None, _event(state=Gdk.ModifierType.CONTROL_MASK, direction=Gdk.ScrollDirection.SMOOTH, dy=0.3)
        ))
        dummy._navigate_month.assert_not_called()
        self.assertTrue(LocalizedCalendar._on_scroll(
            dummy, None, _event(state=Gdk.ModifierType.CONTROL_MASK, direction=Gdk.ScrollDirection.SMOOTH, dy=0.3)
        ))
        dummy._navigate_month.assert_called_once_with(1)

    def test_preferences_cycle_subtab_wraps(self):
        dummy = SimpleNamespace(
            SUBTABS=PreferencesPage.SUBTABS,
            stack=SimpleNamespace(get_visible_child_name=lambda: "startup"),
            select_subtab=MagicMock(),
        )
        PreferencesPage.cycle_subtab(dummy, 1)
        dummy.select_subtab.assert_called_with("applications")
        PreferencesPage.cycle_subtab(dummy, -1)
        dummy.select_subtab.assert_called_with("time")


class ModalKeyboardAndMouseTests(unittest.TestCase):
    def test_power_menu_number_keys_arrows_and_confirm_toggling(self):
        buttons = {k: MagicMock() for k in ACTION_IDS}
        state = {"page": "actions", "focus": buttons["lock"]}
        dummy = SimpleNamespace(
            action_buttons=buttons,
            cancel_button=MagicMock(),
            confirm_button=MagicMock(),
            stack=SimpleNamespace(get_visible_child_name=lambda: state["page"]),
            get_focus=lambda: state["focus"],
            choose=MagicMock(),
            back=MagicMock(),
            cancel=MagicMock(),
        )
        dummy._move_action_focus = lambda d: PowerMenu._move_action_focus(dummy, d)

        # Up from first button wraps to last ("shutdown")
        self.assertTrue(PowerMenu.on_key(dummy, None, _event(keyval=Gdk.KEY_Up)))
        buttons["shutdown"].grab_focus.assert_called_once()
        # Pressing '4' chooses "restart" (which goes through safe confirmation in live window)
        self.assertTrue(PowerMenu.on_key(dummy, None, _event(keyval=Gdk.KEY_4)))
        dummy.choose.assert_called_with("restart")
        # Confirm screen: Left/Right switches Cancel <-> Confirm, BackSpace goes back
        state["page"] = "confirm"
        state["focus"] = dummy.cancel_button
        self.assertTrue(PowerMenu.on_key(dummy, None, _event(keyval=Gdk.KEY_Right)))
        dummy.confirm_button.grab_focus.assert_called_once()
        self.assertTrue(PowerMenu.on_key(dummy, None, _event(keyval=Gdk.KEY_BackSpace)))
        dummy.back.assert_called_once()

    def test_clipboard_ctrl_digits_shift_delete_and_middle_click(self):
        rows = [MagicMock(), MagicMock(), MagicMock()]
        lb = MagicMock()
        lb.get_selected_row.return_value = rows[1]
        lb.get_row_at_y.return_value = rows[2]
        dummy = SimpleNamespace(
            rows=rows,
            listbox=lb,
            search=SimpleNamespace(has_focus=lambda: True, get_text=lambda: ""),
            confirm_bar=SimpleNamespace(get_visible=lambda: False),
            _matches=lambda r: True,
            _pick=MagicMock(),
            _delete_row=MagicMock(),
            _move_selection=MagicMock(),
        )
        # Ctrl+2 picks 2nd visible item
        self.assertTrue(ClipboardWindow._on_key(dummy, None, _event(keyval=Gdk.KEY_2, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy._pick.assert_called_once_with(rows[1])
        # Shift+Delete removes selected item even while search has focus
        self.assertTrue(ClipboardWindow._on_key(dummy, None, _event(keyval=Gdk.KEY_Delete, state=Gdk.ModifierType.SHIFT_MASK)))
        dummy._delete_row.assert_called_once_with(rows[1])
        # Middle-click deletes clicked row
        dummy._delete_row.reset_mock()
        self.assertTrue(ClipboardWindow._on_list_button(dummy, lb, _event(button=Gdk.BUTTON_MIDDLE, y=96)))
        dummy._delete_row.assert_called_once_with(rows[2])
        # Ctrl+N / PageDown in search
        self.assertTrue(ClipboardWindow._on_search_key(dummy, None, _event(keyval=Gdk.KEY_n, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy._move_selection.assert_called_with(1)
        self.assertTrue(ClipboardWindow._on_search_key(dummy, None, _event(keyval=Gdk.KEY_Page_Down)))
        dummy._move_selection.assert_called_with(6)

    def test_confirm_clear_arrow_toggles_focus(self):
        c, ok = MagicMock(), MagicMock()
        dummy = SimpleNamespace(cancel_btn=c, confirm_btn=ok, get_focus=lambda: c)
        self.assertTrue(ConfirmClearWindow._on_key(dummy, None, _event(keyval=Gdk.KEY_Right)))
        ok.grab_focus.assert_called_once()

    def test_command_palette_ctrl_n_p_page_and_home_end(self):
        dummy = SimpleNamespace(
            entry=SimpleNamespace(get_text=lambda: ""),
            close=MagicMock(),
            _move_selection=MagicMock(),
        )
        self.assertTrue(CommandPalette._on_entry_key(dummy, None, _event(keyval=Gdk.KEY_n, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy._move_selection.assert_called_with(1)
        self.assertTrue(CommandPalette._on_entry_key(dummy, None, _event(keyval=Gdk.KEY_p, state=Gdk.ModifierType.CONTROL_MASK)))
        dummy._move_selection.assert_called_with(-1)
        self.assertTrue(CommandPalette._on_entry_key(dummy, None, _event(keyval=Gdk.KEY_Page_Down)))
        dummy._move_selection.assert_called_with(6)
        self.assertTrue(CommandPalette._on_entry_key(dummy, None, _event(keyval=Gdk.KEY_End)))
        dummy._move_selection.assert_called_with(0, absolute=10**6)


if __name__ == "__main__":
    unittest.main()
