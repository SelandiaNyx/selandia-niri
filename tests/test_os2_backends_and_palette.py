"""Unit tests for Sakura Nyan OS 2.0 full-machine backends, command palette, widgets & AI streaming."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))

import ai_backend
import calendar_widget
import journal_backend
import network_backend
import night_light
import panel_ai
import polkit_helper
import process_backend
import security_backend
import storage_backend


class PolkitHelperSecurityTests(unittest.TestCase):
    def test_rejects_disallowed_commands_and_shell_metacharacters(self):
        with self.assertRaises(ValueError):
            polkit_helper.run_privileged(["rm", "-rf", "/"])
        with self.assertRaises(ValueError):
            polkit_helper.systemctl_system("bad-action", "docker.service")
        with self.assertRaises(ValueError):
            polkit_helper.systemctl_system("restart", "docker.service; id")
        with self.assertRaises(ValueError):
            polkit_helper.set_hostname("bad host!")
        with self.assertRaises(ValueError):
            polkit_helper.ufw_command(["status; rm -rf /"])
        with self.assertRaises(ValueError):
            polkit_helper.ufw_command(["allow", "80/icmp"])


class NetworkAndStorageParserTests(unittest.TestCase):
    def test_nmcli_terse_escaped_colons_parse_cleanly(self):
        fields = network_backend._split_terse(r"yes:My\:Home\:WiFi:82:WPA2:AA\:BB\:CC\:DD:5180 MHz", 6)
        self.assertEqual(fields, ["yes", "My:Home:WiFi", "82", "WPA2", "AA:BB:CC:DD", "5180 MHz"])

    def test_storage_pci_parser_handles_lspci_mm(self):
        sample = '00:02.0 "VGA compatible controller" "Intel Corporation" "Arrow Lake-S" -r06 "ASUSTeK" "Device 1234"\n'
        with patch.object(storage_backend, "_capture", return_value=sample):
            rows = storage_backend.read_pci_summary()
        self.assertEqual(len(rows), 1)
        self.assertIn("VGA", rows[0]["class"])
        self.assertIn("Intel", rows[0]["vendor"])
        self.assertIn("Arrow Lake-S", rows[0]["name"])


class NightLightAndProcessSafetyTests(unittest.TestCase):
    def test_night_light_validates_kelvin_bounds(self):
        clean = night_light.validate({"enabled": True, "kelvin": 4200, "schedule": True})
        self.assertEqual(clean["kelvin"], 4200)
        self.assertTrue(clean["enabled"])
        self.assertTrue(clean["schedule"])
        clamped = night_light.validate({"enabled": False, "kelvin": 99999, "start_hour": 99})
        self.assertEqual(clamped["kelvin"], 6500)
        self.assertEqual(clamped["start_hour"], 23)

    def test_process_signal_blocks_protected_pids(self):
        for bad_pid in (0, 1, os.getpid()):
            with self.assertRaises((PermissionError, ValueError)):
                process_backend.signal_process(bad_pid, force=False)


class SecurityAndJournalTests(unittest.TestCase):
    def test_parse_ufw_status_verbose_rules(self):
        sample = (
            "Status: active\n"
            "Logging: on (low)\n"
            "Default: deny (incoming), allow (outgoing), disabled (routed)\n\n"
            "To                         Action      From\n"
            "--                         ------      ----\n"
            "[ 1] 22/tcp                     ALLOW IN    Anywhere\n"
            "[ 2] 8080/tcp                   DENY IN     192.168.1.0/24\n"
        )
        parsed = security_backend._parse_ufw_status(sample)
        self.assertTrue(parsed["active"])
        self.assertEqual(parsed["default_in"], "deny")
        self.assertEqual(parsed["default_out"], "allow")
        self.assertEqual(len(parsed["rules"]), 2)
        self.assertEqual(parsed["rules"][0]["num"], "1")
        self.assertIn("22/tcp", parsed["rules"][0]["to"])

    def test_journal_plain_report_formats_entries(self):
        report = journal_backend.format_plain_report([
            {"time": "12:00:01", "unit": "niri.service", "level": "err", "message": "Sample error"},
        ])
        self.assertIn("niri.service", report)
        self.assertIn("[ERR]", report)
        self.assertIn("Sample error", report)


class CalendarLunarAndMarkdownTests(unittest.TestCase):
    def test_lunar_dates_match_spring_festivals_and_caption(self):
        self.assertEqual(calendar_widget.lunar_date_zh(datetime.date(2024, 2, 10)), "农历正月初一")
        self.assertEqual(calendar_widget.lunar_date_zh(datetime.date(2025, 1, 29)), "农历正月初一")
        self.assertEqual(calendar_widget.lunar_date_zh(datetime.date(2026, 2, 17)), "农历正月初一")
        self.assertEqual(calendar_widget.lunar_date_zh(datetime.date(2027, 2, 6)), "农历正月初一")
        zh_cap = calendar_widget.date_caption(2026, 11, 25, True)
        self.assertIn("农历", zh_cap)
        self.assertIn("周", zh_cap)
        en_cap = calendar_widget.date_caption(2026, 11, 25, False)
        self.assertIn("Week", en_cap)

    def test_markdown_code_fence_splitter(self):
        blocks = panel_ai._split_markdown_blocks("Here:\n```python\nprint(1)\n```\nDone.")
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0], ("text", "", "Here:"))
        self.assertEqual(blocks[1], ("code", "python", "print(1)"))
        self.assertEqual(blocks[2], ("text", "", "Done."))


class WidgetAndPaletteTests(unittest.TestCase):
    def test_command_palette_matches_pages_and_settings(self):
        from command_palette import CommandPalette

        panel = MagicMock()
        palette = CommandPalette(panel)
        self.addCleanup(palette.destroy)
        palette.entry.set_text("ufw")
        palette._filter()
        matched = [r for r in palette._rows if palette._matches(r)]
        self.assertGreaterEqual(len(matched), 1)
        palette._activate_selected()
        panel.select_control_tab.assert_called_with("security", subtab=None)
        palette.entry.set_text("nonexistent_zz_999")
        palette._filter()
        matched = [r for r in palette._rows if palette._matches(r)]
        self.assertEqual(len(matched), 0)

    def test_sparkline_and_display_canvas_instantiate(self):
        from display_canvas import DisplayArrangeCanvas
        from sparkline_widget import Sparkline

        sp = Sparkline((0.62, 0.66, 1.0))
        self.addCleanup(sp.destroy)
        sp.push(12.5)
        sp.push(48.0)
        self.assertEqual(len(sp._points), 2)

        canvas = DisplayArrangeCanvas(on_move=lambda *_: None)
        self.addCleanup(canvas.destroy)
        canvas.set_outputs([
            {"name": "DP-6", "x": 0, "y": 0, "width": 3840, "height": 2160, "scale": 1.0, "selected": True},
        ])
        self.assertEqual(len(canvas.outputs), 1)


class AiStreamingTests(unittest.TestCase):
    def test_chat_request_streams_ollama_ndjson_chunks(self):
        class StreamHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for chunk, done in (("Hello ", False), ("Gemini!", True)):
                    line = json.dumps({"message": {"content": chunk}, "done": done}).encode() + b"\n"
                    self.wfile.write(line)
                    self.wfile.flush()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        seen = []
        settings = dict(ai_backend.DEFAULTS, endpoint=f"http://127.0.0.1:{server.server_address[1]}", model="test-model")
        req = ai_backend.ChatRequest([{"role": "user", "content": "hi"}], settings, on_chunk=seen.append)
        reply = req.run()
        self.assertEqual(reply, "Hello Gemini!")
        self.assertEqual(seen, ["Hello ", "Gemini!"])


if __name__ == "__main__":
    unittest.main()
