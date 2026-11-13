"""DRM counter fixtures: no GPU access or global permission changes."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import gpu_metrics


INTEL = "0000:00:02.0"
XE = "0000:03:00.0"


def fdinfo(address=INTEL, client=7, driver="i915", **counters):
    rows = {"drm-driver": driver, "drm-pdev": address, "drm-client-id": str(client), **counters}
    return "\n".join(f"{key}: {value}" for key, value in rows.items())


class ParserTests(unittest.TestCase):
    def test_ns_cycles_capacities_and_memory_keep_their_units(self):
        row = gpu_metrics.parse_fdinfo(fdinfo(**{
            "drm-engine-render": "100 ns", "drm-cycles-video": "60",
            "drm-total-cycles-video": "200", "drm-engine-capacity-video": "2",
            "drm-resident-vram0": "16 MiB", "drm-shared-vram0": "32 KiB"}))
        self.assertEqual(row["engines"]["render"], ("time", 100, None))
        self.assertEqual(row["engines"]["video"], ("cycles", 60, 200))
        self.assertEqual(row["capacities"]["video"], 2)
        self.assertEqual(row["memory"]["resident"]["vram0"], 16 * 1024 ** 2)
        self.assertEqual(row["memory"]["shared"]["vram0"], 32 * 1024)

    def test_time_counters_take_precedence_over_cycle_counters(self):
        row = gpu_metrics.parse_fdinfo(fdinfo(**{"drm-cycles-render": "30", "drm-total-cycles-render": "100",
                                                "drm-engine-render": "80 ns"}))
        self.assertEqual(row["engines"]["render"], ("time", 80, None))

    def test_malformed_or_unsupported_counters_are_not_zero(self):
        for value in ["-1 ns", "NaN ns", "1 ms", "1.5 ns", "invalid"]:
            with self.subTest(value=value):
                row = gpu_metrics.parse_fdinfo(fdinfo(**{"drm-engine-render": value}))
                self.assertEqual(row["engines"], {})
        row = gpu_metrics.parse_fdinfo(fdinfo(**{"drm-engine-render": "1 ns", "drm-engine-capacity-render": "0"}))
        self.assertEqual(row["engines"], {})
        self.assertIsNone(gpu_metrics.parse_fdinfo("drm-driver: i915\ndrm-client-id: 1"))
        self.assertEqual(gpu_metrics.pci_address("00000000:0A:02.0"), "0000:0a:02.0")


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gpu-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 10.0
        self.devices = {}
        for index, address in enumerate([INTEL, XE]):
            device = self.root / "sys/bus/pci/devices" / address
            (device / "drm" / f"renderD{128 + index}").mkdir(parents=True)
            (device / "drm" / f"renderD{128 + index}" / "dev").write_text(f"226:{128 + index}")
            (device / "power").mkdir()
            (device / "power/runtime_status").write_text("active")
            self.devices[address] = device
        self.sampler = gpu_metrics.DrmClientSampler(self.root / "proc", self.root / "sys",
                                                   clock=lambda: self.now, scan_budget=1)
        # Regular fixture files stand in for character devices; real proc/fdinfo
        # parsing, discovery, caching and rate calculations remain exercised.
        def device_lookup(path, nodes):
            address = path.read_text()
            return address if address in nodes.values() else None
        stub = patch.object(self.sampler, "_fd_device", side_effect=device_lookup)
        stub.start()
        self.addCleanup(stub.stop)

    def client(self, address=INTEL, pid=100, descriptor=3, client=7, start=100, **counters):
        process = self.root / "proc" / str(pid)
        (process / "fd").mkdir(parents=True, exist_ok=True)
        (process / "fdinfo").mkdir(exist_ok=True)
        (process / "fd" / str(descriptor)).write_text(address)
        # starttime is field 22, index 19 after the process name.
        (process / "stat").write_text(f"{pid} (fixture) S " + " ".join(["0"] * 18 + [str(start)]))
        (process / "fdinfo" / str(descriptor)).write_text(fdinfo(address, client, "xe" if address == XE else "i915", **counters))

    def read(self, address=INTEL):
        return self.sampler.sample(self.devices)[address]

    def test_warmup_then_real_zero_and_nonzero(self):
        self.client(**{"drm-engine-render": "100 ns"})
        self.assertIsNone(self.read()["percent"])
        self.now += 1
        self.assertEqual(self.read()["percent"], 0)
        self.client(**{"drm-engine-render": "500000100 ns"})
        self.now += 1
        self.assertAlmostEqual(self.read()["percent"], 50)

    def test_dup_and_shared_fds_do_not_double_count_and_devices_stay_separate(self):
        for pid, fd in [(100, 3), (100, 4), (200, 8)]:
            self.client(pid=pid, descriptor=fd, **{"drm-engine-render": "100 ns"})
        self.client(address=XE, pid=300, **{"drm-cycles-rcs": "10", "drm-total-cycles-rcs": "100"})
        self.read()
        for pid, fd in [(100, 3), (100, 4), (200, 8)]:
            self.client(pid=pid, descriptor=fd, **{"drm-engine-render": "250000100 ns"})
        self.client(address=XE, pid=300, **{"drm-cycles-rcs": "50", "drm-total-cycles-rcs": "200"})
        self.now += 1
        rows = self.sampler.sample(self.devices)
        self.assertEqual(rows[INTEL]["clients"], 1)
        self.assertAlmostEqual(rows[INTEL]["percent"], 25)
        self.assertAlmostEqual(rows[XE]["percent"], 40)

    def test_multiple_clients_sum_by_engine_and_capacity_without_summing_classes(self):
        for pid, client in [(100, 7), (200, 8)]:
            self.client(pid=pid, client=client, **{"drm-engine-video": "0 ns", "drm-engine-capacity-video": "2", "drm-engine-render": "0 ns"})
        self.read()
        for pid, client in [(100, 7), (200, 8)]:
            self.client(pid=pid, client=client, **{"drm-engine-video": "500000000 ns", "drm-engine-capacity-video": "2", "drm-engine-render": "100000000 ns"})
        self.now += 1
        row = self.read()
        self.assertEqual(row["engine_percent"], {"video": 50, "render": 20})
        self.assertEqual(row["percent"], 50)

    def test_cycles_use_gpu_clock_delta_not_wall_clock(self):
        self.client(address=XE, **{"drm-cycles-rcs": "100", "drm-total-cycles-rcs": "1000"})
        self.read(XE)
        self.client(address=XE, **{"drm-cycles-rcs": "200", "drm-total-cycles-rcs": "1200"})
        self.now += 0.2
        self.assertAlmostEqual(self.read(XE)["percent"], 50)

    def test_suspended_device_reads_no_fdinfo_and_resume_rewarms(self):
        self.client(**{"drm-engine-render": "10 ns"})
        self.read()
        (self.devices[INTEL] / "power/runtime_status").write_text("suspended")
        original = gpu_metrics._text
        def guarded(path, *args):
            self.assertNotIn("fdinfo", path.parts)
            return original(path, *args)
        with patch.object(gpu_metrics, "_text", side_effect=guarded):
            self.now += 1
            row = self.read()
        self.assertEqual(row["status"], "suspended")
        (self.devices[INTEL] / "power/runtime_status").write_text("active")
        self.now += 1
        self.assertIsNone(self.read()["percent"])

    def test_temporary_engine_counter_regression_keeps_high_water(self):
        self.client(**{"drm-engine-render": "1000000000 ns"})
        self.read()
        self.now += 1
        self.client(**{"drm-engine-render": "900000000 ns"})
        self.assertIsNone(self.read()["percent"])
        self.now += 1
        self.client(**{"drm-engine-render": "1400000000 ns"})
        self.assertAlmostEqual(self.read()["percent"], 20)

    def test_gpu_clock_reset_and_reused_client_process_start_warm_up(self):
        self.client(address=XE, **{"drm-cycles-rcs": "500", "drm-total-cycles-rcs": "1000"})
        self.read(XE)
        self.now += 1
        self.client(address=XE, **{"drm-cycles-rcs": "10", "drm-total-cycles-rcs": "20"})
        self.assertIsNone(self.read(XE)["percent"])
        self.now += 1
        self.client(address=XE, start=999, **{"drm-cycles-rcs": "15", "drm-total-cycles-rcs": "40"})
        self.assertIsNone(self.read(XE)["percent"])

    def test_unreadable_process_identity_never_links_client_rates(self):
        for busy in [100, 500000100, 800000100]:
            self.client(**{"drm-engine-render": f"{busy} ns"})
            (self.root / "proc/100/stat").unlink()
            self.assertIsNone(self.read()["percent"])
            self.now += 1
        self.client(start=999, **{"drm-engine-render": "900000100 ns"})
        self.assertIsNone(self.read()["percent"])
        self.now += 1
        self.client(start=999, **{"drm-engine-render": "1000000100 ns"})
        self.assertAlmostEqual(self.read()["percent"], 10)

    def test_fd_reuse_and_exited_process_trigger_safe_rediscovery(self):
        self.client(**{"drm-engine-render": "100 ns"})
        self.read()
        self.client(client=9, **{"drm-engine-render": "200 ns"})
        self.now += 1
        self.assertIsNone(self.read()["percent"])
        (self.root / "proc/100/fd/3").unlink()
        self.now += 1
        self.assertEqual(self.read()["status"], "no-clients")

    def test_discovery_is_cached_and_new_client_warms_after_interval(self):
        self.client(**{"drm-engine-render": "0 ns"})
        self.read()
        self.client(pid=200, client=8, **{"drm-engine-render": "0 ns"})
        self.now += 1
        self.assertEqual(self.read()["clients"], 1)
        self.now += 10
        row = self.read()
        self.assertEqual(row["clients"], 2)
        self.assertIsNone(row["percent"])

    def test_empty_and_permission_failure_are_distinct(self):
        (self.root / "proc").mkdir()
        self.assertEqual(self.read()["status"], "no-clients")
        self.client(**{"drm-engine-render": "0 ns"})
        self.now += 10
        original = gpu_metrics._text
        def denied(path, *args):
            if "fdinfo" in path.parts:
                raise PermissionError("fixture")
            return original(path, *args)
        with patch.object(gpu_metrics, "_text", side_effect=denied):
            row = self.read()
        self.assertEqual(row["status"], "unreadable")
        self.assertIsNone(row["percent"])

    def test_discovery_budget_and_sampling_pause_are_explicit(self):
        self.client(**{"drm-engine-render": "0 ns"})
        self.sampler.max_descriptors = 0
        row = self.read()
        self.assertFalse(row["discovery_complete"])
        self.sampler.max_descriptors = 100
        self.now += 10
        self.read()
        self.now += 31
        self.assertIsNone(self.read()["percent"])

    def test_gpu_without_a_drm_node_is_unavailable_even_if_another_gpu_has_nodes(self):
        (self.devices[INTEL] / "drm/renderD128/dev").unlink()
        self.assertEqual(self.read()["status"], "unavailable")

    def test_memory_stays_per_client_not_an_invented_global_vram_total(self):
        for pid, client in [(100, 7), (200, 8)]:
            self.client(pid=pid, client=client, **{"drm-resident-vram0": "10 MiB", "drm-shared-vram0": "8 MiB"})
        row = self.read()
        self.assertEqual(len(row["client_memory"]), 2)
        self.assertNotIn("memory_used", row)
        self.assertNotIn("memory_total", row)
        self.assertEqual(row["client_memory"]["7"]["resident"]["vram0"], 10 * 1024 ** 2)


if __name__ == "__main__":
    unittest.main()
