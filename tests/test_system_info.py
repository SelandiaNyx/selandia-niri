"""Complete inventory with fixture proc/sys/etc; no external inventory tools."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import i18n
import metrics
import system_info


class SystemInfoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="selandia-system-info-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def collect(self, **extra):
        return system_info.collect(proc=self.root / "proc", sys=self.root / "sys", etc=self.root / "etc",
            var=self.root / "var", environment={"XDG_CONFIG_HOME": str(self.root / "config"), "LANG": "en_US.UTF-8"}, **extra)[0]

    def test_missing_data_is_explicit_and_never_blank_or_fake_zero(self):
        data = dict(self.collect())
        for field in ("Machine", "CPU", "GPU / driver", "Displays", "Local IP", "Packages", "Timezone"):
            self.assertEqual(data[field], "Unavailable")
        self.assertTrue(all(value for value in data.values()))
        self.assertGreaterEqual(len(data), 25)

    def test_configured_terminal_follows_the_daily_or_emergency_choice(self):
        self.write("config/niri/theme/alacritty.toml", "")
        for terminal in ('alacritty','kitty'):
            with patch('component_preferences.load',return_value={'terminal':terminal}):
                self.assertEqual(dict(self.collect())['Terminal'],terminal.capitalize()+' (configured)')

    def test_core_fields_work_when_every_external_command_is_missing(self):
        self.write("proc/sys/kernel/hostname", "test-host")
        self.write("proc/sys/kernel/osrelease", "6.17-test")
        self.write("proc/uptime", "3661 0")
        self.write("etc/os-release", 'PRETTY_NAME="Fixture Linux"\n')
        self.write("etc/timezone", "Asia/Shanghai")
        self.write("etc/passwd", f"user:x:{os.getuid()}:1000::/tmp:/usr/bin/zsh\n")
        self.write("proc/cpuinfo", "processor: 0\nmodel name: Fixture CPU\nphysical id: 0\ncore id: 0\ncpu MHz: 1200\n")
        self.write("proc/meminfo", "MemTotal: 1000 kB\nMemAvailable: 750 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
        self.write("sys/class/dmi/id/product_name", "Test Model")
        self.write("sys/class/dmi/id/board_name", "Test Board")
        self.write("var/lib/pacman/local/pkg-1/desc", "%NAME%\npkg\n")
        self.write("config/gtk-3.0/settings.ini", "[Settings]\ngtk-theme-name=Breeze\ngtk-icon-theme-name=breeze\ngtk-font-name=Inter 12\n")
        with patch.dict(os.environ, PATH=""), patch.object(metrics.subprocess, "run", side_effect=FileNotFoundError) as run:
            data = dict(self.collect())
        run.assert_not_called()
        for key, value in (("Host", "test-host"), ("Machine", "Test Model"), ("Mainboard", "Test Board"),
            ("Distribution", "Fixture Linux"), ("Kernel", "6.17-test"), ("Uptime", "1h 1m"),
            ("Shell", "/usr/bin/zsh"), ("CPU", "Fixture CPU"), ("CPU frequency", "1200 MHz"),
            ("Packages", "1"), ("Font", "Inter 12"), ("Timezone", "Asia/Shanghai")):
            self.assertEqual(data[key], value, key)

    def test_local_ip_ignores_loopback_and_preserves_link_local_scope(self):
        self.write("proc/net/fib_trie", " |-- 127.0.0.1\n    /32 host LOCAL\n |-- 192.168.1.2\n    /32 host LOCAL\n")
        self.write("proc/net/if_inet6", "00000000000000000000000000000001 01 80 10 80 lo\nfe800000000000000000000000000001 02 40 20 80 eth0\n")
        self.assertEqual(system_info.local_addresses(self.root / "proc"), ["192.168.1.2", "fe80::1%eth0"])

    def test_native_outputs_handle_zero_mode_index_and_refresh_millihertz(self):
        data = {"DP-1": {"current_mode": 0, "modes": [{"width": 3840, "height": 2160, "refresh_rate": 144000}]},
                "disconnected": {"current_mode": None}}
        with patch.object(system_info, "niri_reply", side_effect=lambda key, env: data if key == "Outputs" else "26.04"):
            rows, _ = system_info.collect(environment={"NIRI_SOCKET": "/tmp/fake"}, sampler=Mock(sample=Mock(return_value={})), desktop={})
        self.assertEqual(dict(rows)["Displays"], "DP-1: 3840×2160 @ 144 Hz")
        self.assertEqual(dict(rows)["Desktop / WM"], "Niri 26.04 / Wayland")

    def test_oem_placeholders_and_malformed_displays_remain_unavailable(self):
        self.write("sys/class/dmi/id/product_name", "To Be Filled By O.E.M.")
        self.write("sys/class/dmi/id/board_name", "Default string")
        malformed = {"broken": {"modes": [], "current_mode": 0}, "bad": {"modes": [None], "current_mode": True}}
        with patch.object(system_info, "niri_reply", return_value=malformed):
            data = dict(self.collect())
        self.assertEqual(data["Machine"], "Unavailable")
        self.assertEqual(data["Mainboard"], "Unavailable")
        self.assertEqual(data["Displays"], "Unavailable")

    def test_plain_text_tabs_preserve_multiline_values_for_native_alignment(self):
        self.assertEqual(system_info.plain_text([("Host", "fixture"), ("GPU", "first\nsecond")]),
                         "Host\t: fixture\nGPU\t: first\n\t  second")

    def test_chinese_alignment_preserves_same_values_for_copy(self):
        i18n.set_language("zh_CN")
        rows = self.collect()
        self.assertIn(("机型", "不可用"), rows)
        text = system_info.plain_text(rows)
        self.assertIn("不可用", text)
        self.assertNotIn("Unavailable", text)
        self.assertEqual(len(text.splitlines()), len(rows))
