#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Quality gate ratchet — coverage and test count can never regress.

Usage:
    python scripts/quality_gate.py check   # CI: fail if metrics regressed
    python scripts/quality_gate.py update  # main branch: bump gate if improved
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import defusedxml.ElementTree as DefusedET

GATE_PATH = Path(__file__).resolve().parent.parent / ".github" / "quality-gate.json"
COVERAGE_XML = Path("coverage.xml")
TEST_RESULTS_XML = Path("test-results.xml")


def _load_gate() -> dict[str, int | float]:
    with open(GATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_gate(gate: dict[str, int | float]) -> None:
    with open(GATE_PATH, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2)
        f.write("\n")


def _parse_coverage() -> float:
    """Parse line coverage percentage from coverage.xml."""
    tree = DefusedET.parse(COVERAGE_XML)
    root = tree.getroot()
    rate_str = root.attrib.get("line-rate")
    if rate_str is None:
        print("ERROR: coverage.xml missing 'line-rate' attribute on root element", file=sys.stderr)
        sys.exit(1)
    return round(float(rate_str) * 100, 1)


def _parse_test_count() -> int:
    """Parse total test count from JUnit XML.

    Handles both <testsuites><testsuite tests="N"> (pytest default)
    and <testsuite tests="N"> root formats.
    """
    tree = DefusedET.parse(TEST_RESULTS_XML)
    root = tree.getroot()
    if "tests" in root.attrib:
        return int(root.attrib["tests"])
    # pytest wraps in <testsuites>, sum all <testsuite> counts (deep search)
    suites = root.findall(".//testsuite")
    if not suites:
        print(
            "ERROR: test-results.xml has no 'tests' attribute and no <testsuite> elements",
            file=sys.stderr,
        )
        sys.exit(1)
    return sum(int(s.attrib.get("tests", 0)) for s in suites)


def check() -> bool:
    """Compare current metrics against the gate. Return True if passed."""
    gate = _load_gate()
    coverage = _parse_coverage()
    test_count = _parse_test_count()

    passed = True

    gate_coverage = gate["coverage_pct"]
    if coverage < gate_coverage:
        print(f"FAIL: coverage {coverage}% < gate {gate_coverage}%")
        passed = False
    else:
        print(f"OK: coverage {coverage}% >= gate {gate_coverage}%")

    gate_tests = gate["test_count"]
    if test_count < gate_tests:
        print(f"FAIL: test count {test_count} < gate {gate_tests}")
        passed = False
    else:
        print(f"OK: test count {test_count} >= gate {gate_tests}")

    return passed


def update() -> bool:
    """Bump gate if metrics improved. Return True if gate was updated."""
    gate = _load_gate()
    coverage = _parse_coverage()
    test_count = _parse_test_count()

    updated = False

    if coverage > gate["coverage_pct"]:
        print(f"BUMP: coverage {gate['coverage_pct']}% -> {coverage}%")
        gate["coverage_pct"] = coverage
        updated = True

    if test_count > gate["test_count"]:
        print(f"BUMP: test count {gate['test_count']} -> {test_count}")
        gate["test_count"] = test_count
        updated = True

    if updated:
        _save_gate(gate)
        print("Gate updated.")
    else:
        print("No improvements — gate unchanged.")

    return updated


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "update"):
        print(f"Usage: {sys.argv[0]} check|update", file=sys.stderr)
        sys.exit(2)

    mode = sys.argv[1]

    if not COVERAGE_XML.exists():
        print(f"ERROR: {COVERAGE_XML} not found", file=sys.stderr)
        sys.exit(1)
    if not TEST_RESULTS_XML.exists():
        print(f"ERROR: {TEST_RESULTS_XML} not found", file=sys.stderr)
        sys.exit(1)

    if mode == "check":
        sys.exit(0 if check() else 1)
    else:
        update()


if __name__ == "__main__":
    main()
