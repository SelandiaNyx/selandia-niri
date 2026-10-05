#!/usr/bin/env python3
"""Attribute bar log noise to the module or child process that produced it.

Repeated theme reloads can emit ``Glib::DispatchNotifier`` CRITICAL lines while
the bar survives. Filtering those lines away would hide the signal, so this tool
reports every CRITICAL/ERROR/WARNING together with the nearest module marker and
the surrounding lines, and says whether the source is this project's own code or
an undetermined upstream component.

Usage:
    python3 -B tools/bar_log.py .validation/waybar.log [--json out.json]
Exit status is 1 when a finding is attributable to this project.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SEVERITY = re.compile(r"\b(CRITICAL|ERROR|WARNING|WARN)\b", re.IGNORECASE)
SOURCE = re.compile(r"(?:module\s+|#)([A-Za-z0-9_./-]+)|(\bcustom/[A-Za-z0-9_-]+|\bniri/[A-Za-z0-9_-]+)")
# Anything that names this project's own scripts or modules.
PROJECT_MARKERS = ("custom/", "niri/", "selandia", "python3", "bar_layout.py", "metrics.py",
                   "scripts/components", "scripts/desktop", "swaync-client")
CONTEXT = 2
LOOKBACK = 6


def source_for(lines, index):
    """Nearest module/child marker at or just before the finding."""
    for candidate in range(index, max(-1, index - LOOKBACK), -1):
        match = SOURCE.search(lines[candidate])
        if match:
            return match.group(1) or match.group(2)
    match = re.search(r"\(([\w.+-]+):\d+\)", lines[index])
    return match[1] if match else None


def analyse(text):
    lines = text.splitlines()
    findings = []
    counts = {}
    for index, line in enumerate(lines):
        match = SEVERITY.search(line)
        if not match:
            continue
        severity = match.group(1).upper()
        severity = "WARNING" if severity == "WARN" else severity
        counts[severity] = counts.get(severity, 0) + 1
        findings.append({
            "line": index + 1,
            "severity": severity,
            "source": source_for(lines, index),
            "message": line.strip()[:400],
            "context": [item.strip()[:200] for item in lines[max(0, index - CONTEXT):index + CONTEXT + 1]],
        })
    return {"lines": len(lines), "counts": counts, "findings": findings}


def project_findings(report):
    """Findings whose own text names this project.

    ``source`` is a best-effort proximity hint for a human reader and is
    deliberately *not* used here: an upstream GLib assertion that happens to
    follow one of our modules must not be reported as our defect.
    """
    return [finding for finding in report.get("findings", [])
            if any(marker in (finding.get("message") or "") for marker in PROJECT_MARKERS)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Attribute bar log noise to its source")
    parser.add_argument("log", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    report = analyse(arguments.log.read_text(errors="replace"))
    report["project_findings"] = project_findings(report)
    if arguments.json:
        arguments.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("lines", "counts")}, ensure_ascii=False))
    for finding in report["findings"]:
        print(f"{finding['line']}: {finding['severity']} [{finding['source'] or 'unattributed'}] {finding['message']}")
    if report["project_findings"]:
        print("FAIL: " + str(len(report["project_findings"])) + " finding(s) name this project", file=sys.stderr)
        return 1
    print("OK: no finding names this project" + ("" if not report["findings"] else
                                                 f" ({len(report['findings'])} upstream/unattributed)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
