"""Detailed Linux inventory uses fixture proc/sys; missing readings stay unknown."""
from collections import namedtuple
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import metrics


class DetailedMetricsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selandia-inventory-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = 10.
        self.usage = Mock(return_value=namedtuple("Usage", "total used free")(1000, 600, 400))
        self.sampler = metrics.MetricsSampler(self.root / "proc", self.root / "sys", self.root,
            detailed=True, etc_root=self.root / "etc", pci_ids=self.root / "pci.ids", enable_nvidia=False,
            clock=lambda: self.now, disk_usage=self.usage)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_distribution_kernel_and_cpu_topology_frequency_are_real_fields(self):
        self.write("etc/os-release", 'PRETTY_NAME="Fixture Linux 1"\n')
        self.write("proc/sys/kernel/osrelease", "6.fixture")
        self.write("proc/cpuinfo", "\n\n".join(f"processor: {n}\nmodel name: Test CPU\nphysical id: 0\ncore id: {n//2}\ncpu MHz: 2400" for n in range(4)))
        values = self.sampler.sample()
        self.assertEqual(values["system"]["distribution"], "Fixture Linux 1")
        self.assertEqual(values["system"]["kernel"], "6.fixture")
        self.assertEqual(values["cpu"]["physical_cores"], 2)
        self.assertEqual(values["cpu"]["logical_threads"], 4)
        self.assertEqual(values["cpu"]["frequency_mhz"], 2400)

    def test_unknown_cpu_topology_and_frequency_are_not_zero(self):
        self.write("proc/cpuinfo", "processor: 0\nmodel name: Limited CPU\n")
        values = self.sampler.sample()
        self.assertIsNone(values["cpu"]["physical_cores"])
        self.assertIsNone(values["cpu"]["frequency_mhz"])
        self.assertIsNone(values["system"]["distribution"])
        self.assertIn(metrics.tr("Unavailable", "不可用"), metrics.detailed_sections(values)[0][1])

    def test_sysfs_frequency_uses_online_cpus_only(self):
        self.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "3200000")
        self.write("sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq", "9999999")
        self.write("sys/devices/system/cpu/cpu1/online", "0")
        self.assertEqual(self.sampler.sample()["cpu"]["frequency_mhz"], 3200)

    def test_memory_details_keep_missing_counters_unavailable(self):
        self.write("proc/meminfo", "MemTotal: 100 kB\nMemAvailable: 40 kB\nCached: 20 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB")
        values = self.sampler.sample()
        self.assertEqual(values["memory"]["cached"], 20 * 1024)
        self.assertIsNone(values["memory"]["free"])
        self.assertEqual(values["swap"]["used"], 0)

    def test_mounts_decode_spaces_skip_pseudo_filesystems_and_do_not_probe_remote(self):
        self.write("proc/self/mountinfo", "1 0 8:1 / / rw - ext4 /dev/test rw\n"
            "2 0 8:2 / /media/My\\040Disk rw - btrfs /dev/other rw\n"
            "3 0 0:1 / /proc rw - proc proc rw\n4 0 0:2 / /network rw - nfs host:/share rw\n")
        values = self.sampler.sample()
        rows = {row["mount"]: row for row in values["mounts"]}
        self.assertEqual(set(rows), {"/", "/media/My Disk", "/network"})
        self.assertEqual(rows["/media/My Disk"]["used"], 600)
        self.assertIsNone(rows["/network"]["used"])
        self.assertNotIn(Path("/network"), [call.args[0] for call in self.usage.call_args_list])

    def test_failed_mount_usage_stays_visible_as_unavailable(self):
        self.write("proc/self/mountinfo", "1 0 8:1 / /missing rw - ext4 /dev/test rw\n")
        self.usage.side_effect = OSError("gone")
        row = self.sampler.sample()["mounts"][0]
        self.assertIsNone(row["percent"])
        self.assertIsNone(row["total"])

    def test_gpu_pci_database_and_driver_do_not_require_nvidia_tools(self):
        self.write("pci.ids", "8086  Intel\n\te20b  Arc B580\n")
        self.write("sys/class/drm/card0/device/vendor", "0x8086")
        self.write("sys/class/drm/card0/device/device", "0xe20b")
        driver = self.root / "sys/bus/pci/drivers/xe"
        driver.mkdir(parents=True)
        (self.root / "sys/class/drm/card0/device/driver").symlink_to(driver)
        gpu, = self.sampler.sample()["gpus"]
        self.assertEqual(gpu["name"], "Arc B580")
        self.assertEqual(gpu["driver"], "xe")
        self.assertIsNone(gpu["percent"])

    def test_top_process_rates_warmup_and_pid_reuse(self):
        def process(ticks, start):
            fields = ["0"] * 22
            fields[0], fields[11], fields[12], fields[19], fields[21] = "R", str(ticks), "0", str(start), "25"
            self.write("proc/123/stat", "123 (App (worker)) " + " ".join(fields))
        with patch.object(metrics.os, "sysconf", side_effect=lambda key: {"SC_CLK_TCK": 100, "SC_PAGE_SIZE": 4096}[key]):
            process(100, 1)
            self.assertIsNone(self.sampler.sample()["processes"][0]["cpu_percent"])

            self.now += 2
            process(200, 1)
            row = self.sampler.sample()["processes"][0]
            self.assertEqual(row["cpu_percent"], 50)
            self.assertEqual(row["memory"], 25 * 4096)
            self.now += 2
            process(900, 2)
            self.assertIsNone(self.sampler.sample()["processes"][0]["cpu_percent"])

    def test_partial_topology_and_unreadable_sensors_are_not_fabricated(self):
        self.write("proc/cpuinfo", "processor: 0\ncore id: 0\nphysical id: 0\n\nprocessor: 1\ncore id: unknown\nphysical id: 0")
        self.write("sys/class/hwmon/hwmon0/name", "Fixture sensor")
        self.write("sys/class/hwmon/hwmon0/temp1_input", "unreadable")
        values = self.sampler.sample()
        self.assertIsNone(values["cpu"]["physical_cores"])
        self.assertIsNone(values["temperatures"][0]["celsius"])

    def test_static_inventory_is_cached_but_current_cpu_frequency_is_live(self):
        self.write("proc/cpuinfo", "processor: 0\nmodel name: Test CPU\n")
        self.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "2000000")
        self.write("etc/os-release", 'PRETTY_NAME="First Linux"\n')
        with patch.object(self.sampler, '_cpu_inventory', wraps=self.sampler._cpu_inventory) as inventory:
            first = self.sampler.sample()
            self.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "3000000")
            self.write("etc/os-release", 'PRETTY_NAME="Updated Linux"\n')
            self.now += 2
            second = self.sampler.sample()
            self.assertEqual(inventory.call_count, 1)
            self.assertEqual(first['cpu']['frequency_mhz'], 2000)
            self.assertEqual(second['cpu']['frequency_mhz'], 3000)
            self.assertEqual(second['system']['distribution'], 'First Linux')
            self.now += 301
            self.assertEqual(self.sampler.sample()['system']['distribution'], 'Updated Linux')
            self.assertEqual(inventory.call_count, 2)

    def test_cpu_hotplug_mask_invalidates_topology_cache_immediately(self):
        self.write("sys/devices/system/cpu/online", "0")
        self.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", "2000000")
        self.assertEqual(self.sampler.sample()['cpu']['logical_threads'], 1)
        self.write("sys/devices/system/cpu/online", "0-1")
        self.write("sys/devices/system/cpu/cpu1/cpufreq/scaling_cur_freq", "3000000")
        self.now += 2
        self.assertEqual(self.sampler.sample()['cpu']['logical_threads'], 2)

    def test_partition_capacity_cache_expires_and_callers_cannot_mutate_it(self):
        self.write("proc/self/mountinfo", "1 0 8:1 / / rw - ext4 /dev/test rw\n")
        first = self.sampler.sample()
        self.usage.reset_mock()
        first['mounts'][0]['total'] = -1
        self.now += 2
        second = self.sampler.sample()
        self.assertEqual(second['mounts'][0]['total'], 1000)
        self.assertEqual(self.usage.call_count, 1)  # only the live root card
        self.now += 10
        self.sampler.sample()
        self.assertEqual(self.usage.call_count, 3)

    def test_suspended_gpu_and_its_hwmon_do_not_read_wakeup_counters(self):
        self.write('sys/class/drm/card0/device/vendor', '0x8086')
        self.write('sys/class/drm/card0/device/power/runtime_status', 'suspended')
        self.write('sys/class/hwmon/hwmon0/name', 'xe')
        self.write('sys/class/hwmon/hwmon0/device/power/runtime_status', 'suspended')
        self.write('sys/class/hwmon/hwmon0/temp1_input', '40000')
        with patch.object(metrics, 'read_text', wraps=metrics.read_text) as read:
            data = self.sampler.sample()
        self.assertIsNone(data['gpus'][0]['percent'])
        self.assertEqual(data['gpus'][0]['status'], 'suspended')
        paths = [str(call.args[0]) for call in read.call_args_list]
        self.assertFalse(any(x.endswith(('temp1_input','gpu_busy_percent','mem_info_vram_used')) for x in paths))

    def test_all_unknown_hwmon_readings_still_fall_back_to_thermal_zones(self):
        self.write('sys/class/hwmon/hwmon0/name', 'unreadable sensor')
        self.write('sys/class/hwmon/hwmon0/temp1_input', 'unavailable')
        self.write('sys/class/hwmon/hwmon1/name', 'xe')
        self.write('sys/class/hwmon/hwmon1/device/power/runtime_status', 'suspended')
        self.write('sys/class/hwmon/hwmon1/temp1_input', '99000')
        self.write('sys/class/thermal/thermal_zone0/type', 'cpu-thermal')
        self.write('sys/class/thermal/thermal_zone0/temp', '42000')
        readings = self.sampler._temperatures()
        self.assertEqual(readings, [
            {'name': 'unreadable sensor · temp1_input', 'celsius': None},
            {'name': 'xe', 'celsius': None},
            {'name': 'cpu-thermal', 'celsius': 42.0},
        ])

    def test_drm_client_sampling_is_detailed_only_and_preserves_coverage(self):
        address = '0000:03:00.0'
        device = self.root / 'sys/devices' / address
        device.mkdir(parents=True)
        (device / 'vendor').write_text('0x8086')
        driver = self.root / 'sys/bus/pci/drivers/xe'
        driver.mkdir(parents=True)
        (device / 'driver').symlink_to(driver)
        card = self.root / 'sys/class/drm/card0'
        card.mkdir(parents=True)
        (card / 'device').symlink_to(device)
        with patch('gpu_metrics.DrmClientSampler') as create:
            create.return_value.sample.return_value = {address: {
                'percent': 12.5, 'engine_percent': {'render': 12.5},
                'source': 'drm-fdinfo', 'coverage': 'readable-clients', 'status': 'available'}}
            self.sampler.detailed = False
            self.sampler.sample()
            create.assert_not_called()
            self.sampler.detailed = True
            gpu, = self.sampler.sample()['gpus']
            self.assertEqual(gpu['percent'], 12.5)
            self.assertEqual(gpu['source'], 'Intel')
            self.assertEqual(gpu['utilization_source'], 'drm-fdinfo')
            self.assertEqual(gpu['coverage'], 'readable-clients')
            self.assertIn(metrics.tr('readable clients', '可读客户端'), metrics.gpu_activity_text(gpu))
            self.sampler.prime()
            create.return_value.reset.assert_called_once_with()

    def test_gpu_warmup_and_sleep_are_not_rendered_as_zero_percent(self):
        for status in ('warmup', 'suspended', 'unreadable', 'no-clients'):
            self.assertNotIn('0%', metrics.gpu_activity_text({'status': status, 'percent': None}))
