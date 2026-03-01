#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Test parity enforcement — every source module >50 LOC must have a test file.

Usage:
    python scripts/check_test_parity.py check   # CI: fail if violations regressed
    python scripts/check_test_parity.py update  # main branch: lower gate if improved
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "grippy"
TEST_DIR = Path(__file__).resolve().parent.parent / "tests"
GATE_PATH = Path(__file__).resolve().parent.parent / ".github" / "quality-gate.json"
PARITY_MAP_PATH = Path(__file__).resolve().parent.parent / ".github" / "test-parity-map.json"

# Files that are never expected to have tests
SKIP_FILES = {"__init__.py", "__main__.py"}

MIN_LOC = 50

# Subpackages: explicit test map overrides default naming
SUBPACKAGE_PARITY: dict[str, dict[str, Path | str | set[str] | dict[str, str]]] = {
    "rules": {
        "src": SRC_DIR / "rules",
        "test_prefix": "test_grippy_rule_",
        "skip": {"__init__.py", "registry.py"},
        "test_map": {
            "base": "skip",
            "context": "test_grippy_rules_context.py",
            "engine": "test_grippy_rules_engine.py",
            "config": "test_grippy_rules_config.py",
            "workflow_permissions": "test_grippy_rule_workflow.py",
            "secrets_in_diff": "test_grippy_rule_secrets.py",
            "dangerous_sinks": "test_grippy_rule_sinks.py",
            "path_traversal": "test_grippy_rule_traversal.py",
            "llm_output_sinks": "test_grippy_rule_llm.py",
            "ci_script_risk": "test_grippy_rule_ci.py",
        },
    },
}


def _load_gate() -> dict[str, int | float]:
    with open(GATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_gate(gate: dict[str, int | float]) -> None:
    with open(GATE_PATH, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2)
        f.write("\n")


def _load_parity_map() -> dict[str, str]:
    """Load override map: source stem -> test file name (or 'skip')."""
    if not PARITY_MAP_PATH.exists():
        return {}
    with open(PARITY_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


def _count_loc(path: Path) -> int:
    """Count non-blank, non-comment lines."""
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
    return count


def find_violations() -> list[str]:
    """Return list of source modules missing test files."""
    parity_map = _load_parity_map()
    violations = []

    # Top-level src/grippy/*.py
    for src_file in sorted(SRC_DIR.glob("*.py")):
        if src_file.name in SKIP_FILES:
            continue

        loc = _count_loc(src_file)
        if loc < MIN_LOC:
            continue

        stem = src_file.stem
        override = parity_map.get(stem)

        if override == "skip":
            continue

        if override:
            test_file = TEST_DIR / override
        else:
            test_file = TEST_DIR / f"test_grippy_{stem}.py"

        if not test_file.exists():
            violations.append(f"{src_file.name} ({loc} LOC) -> missing {test_file.name}")

    # Subpackages (e.g. rules/)
    for pkg_name, pkg_config in SUBPACKAGE_PARITY.items():
        src_path = Path(str(pkg_config["src"]))
        test_prefix = str(pkg_config["test_prefix"])
        skip_files = set(pkg_config.get("skip", set()))  # type: ignore[arg-type]
        test_map: dict[str, str] = pkg_config.get("test_map", {})  # type: ignore[assignment]

        if not src_path.is_dir():
            continue

        for src_file in sorted(src_path.glob("*.py")):
            if src_file.name in SKIP_FILES or src_file.name in skip_files:
                continue

            loc = _count_loc(src_file)
            if loc < MIN_LOC:
                continue

            stem = src_file.stem

            # Check test_map for explicit overrides
            if stem in test_map:
                if test_map[stem] == "skip":
                    continue
                test_file = TEST_DIR / test_map[stem]
            else:
                test_file = TEST_DIR / f"{test_prefix}{stem}.py"

            if not test_file.exists():
                violations.append(
                    f"{pkg_name}/{src_file.name} ({loc} LOC) -> missing {test_file.name}"
                )

    return violations


def check() -> bool:
    """Compare violations against gate. Return True if passed."""
    gate = _load_gate()
    violations = find_violations()

    gate_violations = gate.get("parity_violations", 0)

    if violations:
        print(f"Missing test files ({len(violations)}):")
        for v in violations:
            print(f"  {v}")
    else:
        print("All source modules have test files.")

    if len(violations) > gate_violations:
        print(f"\nFAIL: {len(violations)} violations > gate {gate_violations}")
        return False

    print(f"\nOK: {len(violations)} violations <= gate {gate_violations}")
    return True


def update() -> bool:
    """Lower gate if violations decreased. Return True if gate was updated."""
    gate = _load_gate()
    violations = find_violations()

    current = len(violations)
    gate_violations = gate.get("parity_violations", 0)

    if current < gate_violations:
        print(f"BUMP: parity violations {gate_violations} -> {current}")
        gate["parity_violations"] = current
        _save_gate(gate)
        return True

    print(f"No improvement — {current} violations (gate: {gate_violations})")
    return False


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("check", "update"):
        print(f"Usage: {sys.argv[0]} check|update", file=sys.stderr)
        sys.exit(2)

    mode = sys.argv[1]

    if mode == "check":
        sys.exit(0 if check() else 1)
    else:
        update()


if __name__ == "__main__":
    main()
