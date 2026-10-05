"""Prove a confirmed lock survives the cgroup of the service that asked for it.

This is the A1 lifecycle acceptance test. It needs a reachable user systemd
manager and test-only transient units, so it is skipped - with the reason
recorded - anywhere that manager cannot be reached. A pass is never faked
without systemd.

Safety: the whole test runs against synthetic Wayland display names, so it can
never publish a readiness record for the real desktop's display, and it stops the
temporary lock units and their probe lockers on the way out.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "niri/shell"))
import lock_session as locker

PYTHON = shutil.which("python3") or sys.executable
SYSTEMD_RUN = shutil.which("systemd-run")


def cgroup_of(pid):
    for line in Path("/proc", str(pid), "cgroup").read_text().splitlines():
        _, _, path = line.partition("::")
        if path:
            return path
    raise RuntimeError("no cgroup for " + str(pid))


def systemctl(*arguments, timeout=15):
    return subprocess.run(["systemctl", "--user", *arguments], capture_output=True, text=True, timeout=timeout)


class LockIsolationTests(unittest.TestCase):
    """Only runs where the isolation being asserted can actually exist."""

    @classmethod
    def setUpClass(cls):
        if SYSTEMD_RUN is None:
            raise unittest.SkipTest("systemd-run is not installed; A1 isolation is unverified here")
        if not locker.unit_loaded("selandia-niri@.service"):
            raise unittest.SkipTest("no reachable user systemd manager or undeployed units; "
                                    "A1 cgroup isolation is unverified here")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="selandia-lock-isolation-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        (self.base / "theme").mkdir()
        (self.base / "theme/swaylock.conf").write_text("color=000000\n")
        self.suffix = uuid.uuid4().hex[:12]
        # Synthetic displays: never the real desktop's display name.
        self.displays = [f"wayland-selandia-isolation-a-{self.suffix}",
                         f"wayland-selandia-isolation-b-{self.suffix}"]
        self.runtime = os.environ["XDG_RUNTIME_DIR"]
        self.units = []
        self.records = []
        self.fake = self.base / "fake-locker.py"
        self.fake.write_text('''import os, pathlib, sys, time
# Executed as a script, so argv[0] is this file: the pid path is argv[1].
assert sys.argv[1].endswith(".pid"), sys.argv
pathlib.Path('/proc/self/comm').write_text('swaylock')
pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))
fd = int(sys.argv[sys.argv.index('--ready-fd') + 1])
os.write(fd, b'\\n')
os.close(fd)
time.sleep(600)
''')
        self.pid_files = {display: self.base / f"locker-{index}.pid"
                          for index, display in enumerate(self.displays)}
        self.probe = self.base / "probe.py"
        self.probe.write_text(f'''import json, os, sys
sys.path.insert(0, {str(Path(locker.__file__).resolve().parent)!r})
import lock_session
os.environ["WAYLAND_DISPLAY"] = sys.argv[1]
os.environ["XDG_RUNTIME_DIR"] = sys.argv[2]
# Capture what this process really is before locking.
inside = lock_session.inside_service_unit()
with open("/proc/self/cgroup") as stream:
    cgroup = stream.read().strip()
record = lock_session.lock(base={str(self.base)!r}, timeout=25,
                           locker=({PYTHON!r}, {str(self.fake)!r}, sys.argv[3]),
                           runtime=sys.argv[2], environment=dict(os.environ))
with open(sys.argv[4], "w") as stream:
    json.dump({{"record": record, "inside_service_unit": inside, "cgroup": cgroup}}, stream)
''')
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for unit in reversed(self.units):
            systemctl("stop", unit + ".service")
        for pid_file in self.pid_files.values():
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), 15)
                except (ProcessLookupError, ValueError):
                    pass
        for record in self.records:
            key, _ = locker.paths(self.runtime, record["display"])
            systemctl("stop", f"selandia-lock@{key}.service")
            for suffix in (".json", ".request", ".lock", ".log"):
                Path(self.runtime, "selandia-lock-" + key + suffix).unlink(missing_ok=True)

    def trigger(self, display, name):
        """Run the real lock from inside a transient test-only service unit."""
        unit = f"selandia-lock-probe-{name}-{self.suffix}"
        self.units.append(unit)
        output = self.base / f"out-{name}.json"
        result = subprocess.run(
            [SYSTEMD_RUN, "--user", "--wait", "--collect", f"--unit={unit}",
             "--property=Type=exec", PYTHON, "-B", str(self.probe), display, self.runtime,
             str(self.pid_files[display]), str(output)],
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(output.read_text())
        self.records.append(report["record"])
        return unit, report

    def test_two_trigger_services_reuse_and_never_own_the_lock(self):
        first_unit, first = self.trigger(self.displays[0], "first")
        # The caller really was inside a service unit: this is the dangerous case.
        self.assertTrue(first["inside_service_unit"])
        self.assertIn(first_unit + ".service", first["cgroup"])
        locker_cgroup = cgroup_of(first["record"]["pid"])
        self.assertNotIn("selandia-lock-probe", locker_cgroup)

        second_unit, second = self.trigger(self.displays[0], "second")
        self.assertIn(second_unit + ".service", second["cgroup"])
        self.assertEqual(first["record"], second["record"], "the second trigger did not reuse the confirmed lock")
        self.assertIn("selandia-lock@", locker_cgroup,
                      "the locker is not in its own per-display unit cgroup")
        # Both trigger units have exited; the lock must still be confirmed.
        self.assertTrue(locker.confirmed(first["record"], first["record"]["display"]),
                        "the lock did not survive the services that requested it")
        self.assertEqual(self.pid_files[self.displays[0]].read_text(), str(first["record"]["pid"]))

    def test_another_display_gets_its_own_unit_and_never_disturbs_the_first(self):
        _unit, first = self.trigger(self.displays[0], "alpha")
        self.assertTrue(locker.process_identity(first["record"]["pid"]))
        _other, second = self.trigger(self.displays[1], "beta")
        self.assertNotEqual(first["record"]["pid"], second["record"]["pid"])
        self.assertNotEqual(first["record"]["display"], second["record"]["display"])
        self.assertIn("selandia-lock@", cgroup_of(second["record"]["pid"]))
        # The first display's lock is untouched by the second one.
        self.assertTrue(locker.confirmed(first["record"], first["record"]["display"]))

    def test_the_lock_is_not_inside_a_component_cgroup(self):
        """A component restart must not be able to reach the locker's cgroup."""
        _unit, report = self.trigger(self.displays[0], "cgroup")
        cgroup = cgroup_of(report["record"]["pid"])
        for component in ("idle", "sleep-lock", "waybar"):
            with self.subTest(component=component):
                self.assertNotIn(f"selandia-niri@{component}.service", cgroup)


if __name__ == "__main__":
    unittest.main()
