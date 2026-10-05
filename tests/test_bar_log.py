"""Log checks must attribute bar noise instead of filtering it away (audit gap).

The analyser is tested with synthetic logs: no bar, no compositor and no session
is involved. Attribution by proximity produces a human report; only a finding
that names this project directly fails a run, so an upstream GLib assertion is
reported but does not masquerade as a project defect.
"""
import json
import sys
from pathlib import Path
import subprocess
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import bar_log

CLEAN = """[info] Bar configured (height: 46)
[info] module network: started
"""

NOISY = """[info] module network: started
[info] module custom/control: started
(waybar:4711): GLib-CRITICAL **: 09:32:11.123: g_source_set_ready_time: assertion 'source != NULL' failed
[info] module custom/control: enabled
"""

OURS = """[info] module custom/system: started
[error] module custom/system: script failed: python3 -B bar_layout.py ensure exited 1
"""


class AnalyseTests(unittest.TestCase):
    def test_a_clean_log_reports_nothing(self):
        report = bar_log.analyse(CLEAN)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["counts"], {})

    def test_every_severity_is_counted(self):
        report = bar_log.analyse("a WARNING b\nan ERROR c\na CRITICAL d\n")
        self.assertEqual(report["counts"], {"WARNING": 1, "ERROR": 1, "CRITICAL": 1})
        self.assertEqual([finding["severity"] for finding in report["findings"]],
                         ["WARNING", "ERROR", "CRITICAL"])

    def test_a_nearby_module_is_reported_as_the_likely_source(self):
        report = bar_log.analyse(NOISY)
        finding, = report["findings"]
        self.assertEqual(finding["source"], "custom/control")
        self.assertEqual(finding["line"], 3)
        self.assertTrue(any("module custom/control" in line for line in finding["context"]))

    def test_an_upstream_crash_is_not_attributed_to_this_project(self):
        report = bar_log.analyse(NOISY)
        # The proximity hint names our module, but the finding itself is upstream.
        self.assertEqual(report["findings"][0]["source"], "custom/control")
        self.assertEqual(bar_log.project_findings(report), [])

    def test_a_directly_named_project_source_is_a_failure(self):
        report = bar_log.analyse(OURS)
        self.assertTrue(bar_log.project_findings(report))
        finding, = bar_log.project_findings(report)
        self.assertEqual(finding["severity"], "ERROR")
        self.assertIn("bar_layout.py", finding["message"])

    def test_the_producing_process_is_reported_when_no_module_matches(self):
        report = bar_log.analyse("(waybar:12): Gtk-WARNING **: something odd\n")
        finding, = report["findings"]
        self.assertEqual(finding["source"], "waybar")
        self.assertEqual(finding["context"], ["(waybar:12): Gtk-WARNING **: something odd"])
        self.assertEqual(bar_log.project_findings(report), [])


class CommandLineTests(unittest.TestCase):
    def run_log(self, text):
        with tempfile.TemporaryDirectory(prefix="selandia-bar-log-") as temporary:
            log = Path(temporary) / "waybar.log"
            log.write_text(text)
            report = Path(temporary) / "report.json"
            result = subprocess.run([sys.executable, "-B", str(Path(bar_log.__file__)), str(log),
                                     "--json", str(report)],
                                    capture_output=True, text=True, timeout=20)
            return result, json.loads(report.read_text())

    def test_clean_log_exits_zero(self):
        result, report = self.run_log(CLEAN)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report["findings"], [])

    def test_upstream_noise_is_reported_but_not_a_failure(self):
        result, report = self.run_log(NOISY)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(report["findings"]), 1)
        self.assertEqual(report["project_findings"], [])

    def test_project_error_exits_nonzero_and_is_recorded(self):
        result, report = self.run_log(OURS)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report["project_findings"])
        self.assertIn("this project", result.stderr)


if __name__ == "__main__":
    unittest.main()
