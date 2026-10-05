"""Prove a confirmed lock survives the cgroup of the service that asked for it.

This is the A1 lifecycle acceptance test. It needs a reachable user systemd
manager and test-only transient units, so it is skipped - with the reason
recorded - anywhere that manager cannot be reached (for example a nested
preview inside a container, or a session where the systemd private socket is
not available). A pass is never faked without systemd.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

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
        self.fake = self.base / "fake-locker.py"
        self.fake.write_text('''import os, pathlib, sys, time
pathlib.Path('/proc/self/comm').write_text('swaylock')
pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))
fd = int(sys.argv[sys.argv.index('--ready-fd') + 1])
os.write(fd, b'\\n')
os.close(fd)
time.sleep(300)
''')
        self.pid_file = self.base / "locker.pid"
        self.probe = self.base / "probe.py"
        self.probe.write_text(f'''import json, sys
sys.path.insert(0, {str(Path(locker.__file__).resolve().parent)!r})
import lock_session
record = lock_session.lock(base={str(self.base)!r}, timeout=15,
                           locker=({PYTHON!r}, {str(self.fake)!r}, {str(self.pid_file)!r}))
print(json.dumps(record))
''')
        self.addCleanup(self.kill_locker)

    def kill_locker(self):
        if self.pid_file.exists():
            try:
                os.kill(int(self.pid_file.read_text()), 15)
            except (ProcessLookupError, ValueError):
                pass

    def test_locker_stays_out_of_and_outlives_the_triggering_service(self):
        unit = f"selandia-lock-probe-{os.getpid()}"
        result = subprocess.run(
            [SYSTEMD_RUN, "--user", "--wait", "--collect", f"--unit={unit}",
             "--property=Type=exec", PYTHON, "-B", str(self.probe)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout.strip().splitlines()[-1])
        locker_cgroup = cgroup_of(record["pid"])
        # The transient unit finished and its cgroup was destroyed, yet the locker
        # is still the confirmed lock for this display.
        self.assertNotIn(unit, locker_cgroup)
        self.assertTrue(locker.confirmed(record, record["display"]),
                        "the locker did not survive the service that requested it")


if __name__ == "__main__":
    unittest.main()
