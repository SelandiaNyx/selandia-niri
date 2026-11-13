"""Real proc/sys parser fixtures; no live system or GPU mutations."""
from collections import namedtuple
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import metrics
import i18n


DiskUsage = namedtuple("DiskUsage", "total used free")


class MetricsTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en_US")
        self.addCleanup(i18n.set_language, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.now = 10.0
        self.sampler = metrics.MetricsSampler(
            self.base / "proc", self.base / "sys", self.base,
            enable_nvidia=False, clock=lambda: self.now,
            disk_usage=lambda _: DiskUsage(1000, 600, 400))
        self.write("proc/stat", "cpu  100 10 20 500 10 5 5 0 90 9\n")
        self.write("proc/meminfo", "MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
        self.write("proc/uptime", "90061.25 2000.0\n")
        self.write("proc/loadavg", "0.20 1.20 2.20 1/123 42\n")

    def write(self, path, data):
        path = self.base / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def network(self, **interfaces):
        content = "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
        for name, (received, sent) in interfaces.items():
            content += f" {name}: {received} 0 0 0 0 0 0 0 {sent} 0 0 0 0 0 0 0\n"
            self.write(f"sys/class/net/{name}/operstate", "up")
            self.write(f"sys/class/net/{name}/ifindex", str(len(name)))
        self.write("proc/net/dev", content)

    def nvidia_card(self, index, address, *, status=None, identifier="0x1111"):
        device = self.base / "sys/bus/pci/devices" / address
        device.mkdir(parents=True)
        for name, value in (("vendor", "0x10de"), ("device", identifier)):
            (device / name).write_text(value)
        if status is not None:
            (device / "power").mkdir()
            (device / "power/runtime_status").write_text(status)
        driver = self.base / "sys/bus/pci/drivers/nvidia"
        driver.mkdir(parents=True, exist_ok=True)
        (device / "driver").symlink_to(driver)
        card = self.base / f"sys/class/drm/card{index}"
        card.mkdir(parents=True)
        (card / "device").symlink_to(device)
        return device

    def test_cpu_guest_time_is_not_counted_twice(self):
        self.assertEqual(metrics.parse_cpu("cpu 100 10 20 500 10 5 5 0 90 9\n"), (650, 510))

    def test_prime_gives_the_first_visible_sample_real_cpu_and_network_rates(self):
        self.network(eth0=(100, 200))
        self.sampler.prime()
        self.now = 10.2
        self.write("proc/stat", "cpu 150 10 20 570 10 5 5 0 90 9\n")
        self.network(eth0=(300, 500))
        data = self.sampler.sample()
        self.assertAlmostEqual(data["cpu_percent"], 50 / 120 * 100)
        self.assertAlmostEqual(data["network"]["down_bps"], 1000)
        self.assertAlmostEqual(data["network"]["up_bps"], 1500)

    def test_cpu_warmup_delta_and_counter_reset(self):
        self.assertIsNone(self.sampler.sample()["cpu_percent"])
        self.write("proc/stat", "cpu 130 10 20 570 10 5 5 0 90 9\n")
        self.assertAlmostEqual(self.sampler.sample()["cpu_percent"], 30)
        self.write("proc/stat", "cpu 1 0 1 10 0 0 0 0\n")
        self.assertIsNone(self.sampler.sample()["cpu_percent"])
        self.write("proc/stat", "cpu 11 0 1 20 0 0 0 0\n")
        self.assertAlmostEqual(self.sampler.sample()["cpu_percent"], 50)

    def test_cpu_no_elapsed_ticks_and_decreasing_iowait_unavailable(self):
        self.sampler.sample()
        self.assertIsNone(self.sampler.sample()["cpu_percent"])
        self.write("proc/stat", "cpu 130 10 20 500 0 5 5 0\n")
        self.assertIsNone(self.sampler.sample()["cpu_percent"])

    def test_malformed_cpu_does_not_become_zero(self):
        for value in ("", "cpu invalid 1 2 3", "cpu 1 2", "cpu -1 2 3 4", "cpu0 1 2 3 4"):
            with self.subTest(value=value):
                self.assertIsNone(metrics.parse_cpu(value))

    def test_memavailable_avoids_counting_reclaimable_cache_as_used(self):
        memory, swap = metrics.parse_memory("MemTotal: 1000 kB\nMemAvailable: 750 kB\nMemFree: 50 kB\nSwapTotal: 500 kB\nSwapFree: 200 kB\n")
        self.assertEqual(memory["used"], 250 * 1024)
        self.assertEqual(memory["percent"], 25)
        self.assertEqual(swap["percent"], 60)

    def test_negative_memory_and_swap_counters_are_unavailable(self):
        memory, swap = metrics.parse_memory("MemTotal: 1000 kB\nMemAvailable: -1 kB\nSwapTotal: 500 kB\nSwapFree: -1 kB\n")
        self.assertIsNone(memory)
        self.assertIsNone(swap)

    def test_unknown_temperature_does_not_break_tooltip_or_hide_valid_same_chip(self):
        data = self.sampler.sample()
        data["temperatures"] = [{"name": "CPU · missing", "celsius": None},
                                {"name": "CPU · package", "celsius": 55},
                                {"name": "CPU · other", "celsius": None},
                                {"name": "GPU · missing", "celsius": None}]
        tooltip = metrics.waybar_payload(data)["tooltip"]
        self.assertIn("CPU · package  55°C", tooltip)
        self.assertIn("GPU · missing  —", tooltip)
        self.assertNotIn("0°C", tooltip)

    def test_detailed_nvidia_query_matches_pci_address_instead_of_enumeration_order(self):
        for index, address, identifier in ((0, "0000:01:00.0", "0x1111"), (1, "0000:02:00.0", "0x2222")):
            self.nvidia_card(index, address, identifier=identifier)
        self.sampler.detailed = True
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        self.sampler.run = Mock(return_value=subprocess.CompletedProcess([], 0,
            "Second, 42, 57, 1024, 8192, 00000000:02:00.0, 590.00\nFirst, N/A, N/A, N/A, N/A, 00000000:01:00.0, N/A\n"))
        first, second = self.sampler._gpus()
        self.assertEqual(second["pci_id"], "0x10de:0x2222")
        self.assertEqual(first["pci_id"], "0x10de:0x1111")
        self.assertEqual(second["driver"], "nvidia")
        self.assertEqual(second["driver_version"], "590.00")
        self.assertIsNone(first["driver_version"])
        self.assertIn("pci.bus_id,driver_version", self.sampler.run.call_args.args[0][1])
        self.assertEqual([call.args[0][-1] for call in self.sampler.run.call_args_list],
                         ["--id=0000:01:00.0", "--id=0000:02:00.0"])

    def test_nvidia_mixed_active_and_sleeping_cards_query_only_active_pci_address(self):
        self.nvidia_card(0, "0000:01:00.0", status="active")
        self.nvidia_card(1, "0000:02:00.0", status="suspended", identifier="0x2222")
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        for detailed in (False, True):
            with self.subTest(detailed=detailed):
                self.sampler.detailed = detailed
                self.sampler.run = Mock(return_value=subprocess.CompletedProcess([], 0,
                    "Active, 42, 57, 1024, 8192, 00000000:01:00.0, 590.00\n"))
                active, sleeping = self.sampler._gpus()
                self.sampler.run.assert_called_once()
                command = self.sampler.run.call_args.args[0]
                self.assertIn("--id=0000:01:00.0", command)
                self.assertIn("pci.bus_id", command[1])
                self.assertEqual(active["percent"], 42)
                self.assertEqual(sleeping["pci_id"], "0x10de:0x2222")
                self.assertEqual(sleeping["status"], "suspended")
                self.assertIsNone(sleeping["percent"])
                self.assertIsNone(sleeping["utilization_source"])

    def test_nvidia_rechecks_runtime_state_before_each_target(self):
        self.nvidia_card(0, "0000:01:00.0", status="active")
        second = self.nvidia_card(1, "0000:02:00.0", status="active")
        self.sampler.nvidia_command = "/fake/nvidia-smi"

        def query(*args, **kwargs):
            (second / "power/runtime_status").write_text("suspending")
            return subprocess.CompletedProcess([], 0, "First, 42, 57, 1024, 8192, 0000:01:00.0, 590.00\n")

        self.sampler.run = Mock(side_effect=query)
        first, sleeping = self.sampler._gpus()
        self.sampler.run.assert_called_once()
        self.assertEqual(first["percent"], 42)
        self.assertEqual(sleeping["status"], "suspended")
        self.assertIsNone(sleeping["percent"])

    def test_nvidia_targets_share_one_timeout_budget(self):
        for index in range(3):
            self.nvidia_card(index, f"0000:0{index + 1}:00.0", status="active")
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        elapsed = [10.0]

        def query(command, **kwargs):
            if command[-1] == "--id=0000:01:00.0":
                elapsed[0] += 0.5
                return subprocess.CompletedProcess([], 0, "First, 42, 57, 1024, 8192, 0000:01:00.0, 590.00\n")
            elapsed[0] += kwargs["timeout"]
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        self.sampler.run = Mock(side_effect=query)
        with patch.object(metrics.time, "monotonic", side_effect=lambda: elapsed[0]):
            first, second, third = self.sampler._gpus()
        self.assertEqual(self.sampler.run.call_count, 2)
        self.assertAlmostEqual(self.sampler.run.call_args_list[0].kwargs["timeout"], 0.8)
        self.assertAlmostEqual(self.sampler.run.call_args_list[1].kwargs["timeout"], 0.3)
        self.assertAlmostEqual(elapsed[0], 10.8)
        self.assertEqual(first["percent"], 42)
        self.assertIsNone(second["percent"])
        self.assertIsNone(third["percent"])

    def test_nvidia_target_errors_do_not_retry_query_all_or_replace_sysfs_rows(self):
        self.nvidia_card(0, "0000:01:00.0", status="active")
        self.nvidia_card(1, "0000:02:00.0", status="suspended")
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        failures = (OSError("missing"), subprocess.TimeoutExpired("nvidia-smi", 0.8),
                    subprocess.CompletedProcess([], 1, "error"),
                    subprocess.CompletedProcess([], 0, "broken\n"),
                    subprocess.CompletedProcess([], 0, "Wrong card, 42, 57, 1024, 8192, 0000:02:00.0, 590.00\n"),
                    subprocess.CompletedProcess([], 0, "Missing address, 42, 57, 1024, 8192\n"))
        for failure in failures:
            with self.subTest(failure=failure):
                self.sampler.run = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
                active, sleeping = self.sampler._gpus()
                self.sampler.run.assert_called_once()
                self.assertIn("--id=0000:01:00.0", self.sampler.run.call_args.args[0])
                self.assertEqual(active["name"], "NVIDIA · card0")
                self.assertIsNone(active["percent"])
                self.assertIsNone(sleeping["percent"])
                self.assertEqual(sleeping["status"], "suspended")

    def test_known_nvidia_without_usable_pci_address_does_not_query_all(self):
        self.write("sys/class/drm/card0/device/vendor", "0x10de")
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        self.sampler.run = Mock()
        self.assertEqual(len(self.sampler._gpus()), 1)
        self.sampler.run.assert_not_called()

    def test_nvidia_query_stops_when_system_page_read_is_invalidated(self):
        self.nvidia_card(0, "0000:01:00.0", status="active")
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        self.sampler.run = Mock()
        self.sampler.gpu_read_allowed = lambda: False
        self.assertIsNone(self.sampler._gpus()[0]["percent"])
        self.sampler.run.assert_not_called()

    def test_memory_legacy_fallback_clamps_and_swap_disabled_is_real_zero(self):
        memory, swap = metrics.parse_memory("MemTotal: 100 kB\nMemFree: 50 kB\nCached: 60 kB\nSReclaimable: 10 kB\nShmem: 5 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
        self.assertEqual(memory["available"], 100 * 1024)
        self.assertEqual(swap, {"total": 0, "used": 0, "percent": 0.0})
        self.assertEqual(metrics.parse_memory("MemTotal: invalid kB\n"), (None, None))
        self.assertEqual(metrics.parse_memory("MemTotal: 1000 kB\n"), (None, None))

    def test_network_rates_use_elapsed_monotonic_time(self):
        self.network(eth0=(1000, 500), lo=(1000, 1000))
        first = self.sampler.sample()["network"]
        self.assertIsNone(first["down_bps"])
        self.assertEqual([row["name"] for row in first["interfaces"]], ["eth0"])
        self.now += 2.5
        self.network(eth0=(3500, 1000))
        second = self.sampler.sample()["network"]
        self.assertEqual(second["down_bps"], 1000)
        self.assertEqual(second["up_bps"], 200)

    def test_network_counter_reset_does_not_spike(self):
        self.network(eth0=(1000000, 500000))
        self.sampler.sample()
        self.now += 2
        self.network(eth0=(100, 50))
        self.assertIsNone(self.sampler.sample()["network"]["down_bps"])
        self.now += 2
        self.network(eth0=(300, 100))
        self.assertEqual(self.sampler.sample()["network"]["down_bps"], 100)

    def test_new_recreated_or_returning_interface_needs_new_baseline(self):
        self.network(eth0=(100, 50))
        self.sampler.sample()
        self.now += 2
        self.network(wlan0=(9000000, 8000000))
        self.assertIsNone(self.sampler.sample()["network"]["down_bps"])
        self.now += 2
        self.network(eth0=(5000000, 4000000))
        self.assertIsNone(self.sampler.sample()["network"]["down_bps"])
        self.now += 2
        self.network(eth0=(6000000, 5000000))
        self.write("sys/class/net/eth0/ifindex", "99")
        self.assertIsNone(self.sampler.sample()["network"]["down_bps"])

    def test_default_route_avoids_summing_bridge_or_vpn_traffic(self):
        self.network(eth0=(100, 100), tun0=(100, 100), docker0=(100, 100))
        self.write("proc/net/route", "Iface Destination Gateway Flags RefCnt Use Metric Mask\neth0 00000000 01020304 0003 0 0 600 00000000\ntun0 00000000 00000000 0001 0 0 10 00000000\n")
        self.sampler.sample()
        self.now += 2
        self.network(eth0=(1200, 800), tun0=(1100, 700), docker0=(1000, 500))
        data = self.sampler.sample()["network"]
        self.assertEqual(data["interface"], "tun0")
        self.assertEqual(data["down_bps"], 500)
        self.assertEqual(len(data["interfaces"]), 3)

    def test_ipv6_only_default_route_and_down_interface(self):
        self.network(eth0=(100, 100), wlan0=(100, 100))
        self.write("proc/net/ipv6_route", f"{'0' * 32} 00 {'0' * 32} 00 {'0' * 32} 00000010 00000000 00000000 00000001 wlan0\n")
        self.assertEqual(self.sampler.sample()["network"]["interface"], "wlan0")
        self.write("sys/class/net/wlan0/operstate", "down")
        self.assertEqual(self.sampler.sample()["network"]["interface"], "eth0")

    def test_network_zero_elapsed_and_bad_rows_are_unavailable(self):
        self.network(eth0=(100, 100))
        self.sampler.sample()
        self.network(eth0=(500, 200))
        self.assertIsNone(self.sampler.sample()["network"]["down_bps"])
        self.assertEqual(metrics.parse_network("bad: 1 2\neth0: bad " + "0 " * 15), {})

    def test_missing_files_return_unavailable_and_json_serializable(self):
        sampler = metrics.MetricsSampler(self.base / "missing", self.base / "missing", enable_nvidia=False,
                                         disk_usage=Mock(side_effect=OSError("unavailable")))
        data = sampler.sample()
        for key in ("cpu_percent", "memory", "swap", "disk", "uptime_seconds", "load_average"):
            self.assertIsNone(data[key], key)
        self.assertEqual(data["gpus"], [])
        self.assertIsNone(data["network"]["interface"])
        json.dumps(data, allow_nan=False)

    def test_amd_utilization_vram_and_temperature(self):
        base = "sys/class/drm/card0/device/"
        for path, value in {"vendor": "0x1002", "product_name": "AMD Test GPU", "gpu_busy_percent": "37",
                            "mem_info_vram_used": "1048576", "mem_info_vram_total": "8388608",
                            "hwmon/hwmon0/temp1_input": "62000"}.items():
            self.write(base + path, value)
        self.write("sys/class/drm/card0-HDMI-A-1/device/gpu_busy_percent", "99")
        gpu, = self.sampler.sample()["gpus"]
        self.assertEqual(gpu["percent"], 37)
        self.assertEqual(gpu["temperature"], 62)
        self.assertEqual(gpu["memory_used"], 1048576)

    def test_intel_without_busy_counter_has_no_invented_utilization(self):
        self.write("sys/class/drm/card1/device/vendor", "0x8086")
        self.write("sys/class/drm/card1/device/hwmon/hwmon1/temp1_input", "45000")
        gpu, = self.sampler.sample()["gpus"]
        self.assertIn("Intel", gpu["name"])
        self.assertIsNone(gpu["percent"])
        self.assertEqual(gpu["temperature"], 45)
        self.assertNotIn("󰢮", metrics.waybar_payload(self.sampler.sample())["text"])

    def test_nvidia_optional_query_na_fields_and_timeout(self):
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        self.sampler.run = Mock(return_value=subprocess.CompletedProcess([], 0,
            "NVIDIA Test, 42, 57, 1024, 8192\nNVIDIA Other, N/A, N/A, N/A, N/A\n"))
        gpus = self.sampler.sample()["gpus"]
        self.assertEqual(gpus[0]["memory_used"], 1024 ** 3)
        self.assertEqual(gpus[0]["percent"], 42)
        self.assertIsNone(gpus[1]["percent"])
        self.assertEqual(self.sampler.run.call_args.kwargs["timeout"], 0.8)
        self.sampler.run.side_effect = subprocess.TimeoutExpired("nvidia-smi", 0.8)
        self.assertEqual(self.sampler.sample()["gpus"], [])

    def test_suspended_nvidia_gpu_is_not_woken_for_polling(self):
        for index, status in enumerate(("suspended", "suspending", "resuming")):
            self.nvidia_card(index, f"0000:0{index + 1}:00.0", status=status)
        self.sampler.nvidia_command = "/fake/nvidia-smi"
        self.sampler.run = Mock()
        gpus = self.sampler.sample()["gpus"]
        self.assertEqual(len(gpus), 3)
        self.assertTrue(all(gpu["percent"] is None and gpu["status"] == "suspended" for gpu in gpus))
        self.sampler.run.assert_not_called()

    def test_thermal_fallback_and_invalid_values(self):
        self.write("sys/class/thermal/thermal_zone0/type", "cpu-thermal")
        self.write("sys/class/thermal/thermal_zone0/temp", "48500")
        self.write("sys/class/thermal/thermal_zone1/temp", "999999999")
        self.assertEqual(self.sampler.sample()["temperatures"], [{"name": "cpu-thermal", "celsius": 48.5}])
        self.write("sys/class/hwmon/hwmon0/name", "coretemp")
        self.write("sys/class/hwmon/hwmon0/temp1_label", "Package id 0")
        self.write("sys/class/hwmon/hwmon0/temp1_input", "51000")
        temperatures = self.sampler.sample()["temperatures"]
        self.assertEqual(len(temperatures), 1)
        self.assertEqual(temperatures[0]["celsius"], 51)

    def test_waybar_tooltip_escapes_hardware_names_and_has_pressure_class(self):
        data = self.sampler.sample()
        data["gpus"] = [{"name": "GPU <script>&", "percent": 97}]
        payload = metrics.waybar_payload(data)
        self.assertIn("GPU &lt;script&gt;&amp;", payload["tooltip"])
        self.assertEqual(payload["class"], "critical")
        self.assertIn("97%", payload["text"])
        self.assertIn("Root storage", payload["tooltip"])
        self.assertNotIn("根分区", payload["tooltip"])

    def test_tooltip_language_changes_without_translating_hardware_data(self):
        data = self.sampler.sample()
        data["gpus"] = [{"name": "GPU · 显卡 <custom>", "percent": 42}]
        english = metrics.waybar_payload(data)
        i18n.set_language("zh_CN")
        chinese = metrics.waybar_payload(data)
        self.assertIn("System monitor", english["tooltip"])
        self.assertIn("系统监控", chinese["tooltip"])
        self.assertNotIn("System monitor", chinese["tooltip"])
        self.assertEqual(english["text"], chinese["text"])
        for payload in (english, chinese):
            self.assertIn("GPU · 显卡 &lt;custom&gt;", payload["tooltip"])

    def test_formatters_use_binary_bytes_and_explicit_unavailable(self):
        self.assertEqual(metrics.format_bytes(1024 ** 3), "1.0 GiB")
        self.assertEqual(metrics.format_rate(2048), "2.0 KiB/s")
        self.assertEqual(metrics.format_rate(0), "0 B/s")
        self.assertEqual(metrics.format_rate(None), "—")
        self.assertEqual(metrics.format_percent(None), "—")
        self.assertEqual(metrics.format_uptime(90061), "1d 1h 1m")
        self.assertIsNone(metrics.number("nan"))
        self.assertIsNone(metrics.number("inf"))


if __name__ == "__main__":
    unittest.main()
