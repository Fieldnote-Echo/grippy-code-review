# SPDX-License-Identifier: MIT
"""Rule 1: workflow-permissions-expanded — block-aware YAML scanning for GitHub Actions."""

from __future__ import annotations

import re

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.context import ChangedFile, DiffHunk, DiffLine, RuleContext

_WORKFLOW_PREFIX = ".github/workflows/"
_WORKFLOW_EXTENSIONS = (".yml", ".yaml")

# SHA pinning: uses: org/action@<40-hex-chars>
_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}\b")
_USES_RE = re.compile(r"^\s*-?\s*uses:\s*(.+)$")
_PERMISSIONS_RE = re.compile(r"^(\s*)permissions\s*:")
_PR_TARGET_RE = re.compile(r"\bpull_request_target\b")
_WRITE_ADMIN_RE = re.compile(r"\b(write|admin)\b")


def _indent_level(line: str) -> int:
    """Return number of leading spaces."""
    return len(line) - len(line.lstrip())


def _collect_hunk_lines(hunk: DiffHunk) -> list[tuple[str, DiffLine]]:
    """Collect (raw_content, DiffLine) pairs preserving added + context lines."""
    results: list[tuple[str, DiffLine]] = []
    for dl in hunk.lines:
        if dl.type in ("add", "context"):
            results.append((dl.content, dl))
    return results


def _is_near_added(lines: list[tuple[str, DiffLine]], idx: int, proximity: int = 2) -> bool:
    """Check if any line within ±proximity of idx is an added line."""
    for offset in range(-proximity, proximity + 1):
        check = idx + offset
        if 0 <= check < len(lines) and lines[check][1].type == "add":
            return True
    return False


class WorkflowPermissionsRule:
    """Detect expanded permissions, pull_request_target, and unpinned actions."""

    id = "workflow-permissions-expanded"
    description = "Block-aware scanning for dangerous GitHub Actions workflow patterns"
    default_severity = RuleSeverity.ERROR

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for f in ctx.files:
            if not f.path.startswith(_WORKFLOW_PREFIX) or not f.path.endswith(_WORKFLOW_EXTENSIONS):
                continue
            for hunk in f.hunks:
                results.extend(self._scan_hunk(f, hunk))
        return results

    def _scan_hunk(self, f: ChangedFile, hunk: DiffHunk) -> list[RuleResult]:
        results: list[RuleResult] = []
        lines = _collect_hunk_lines(hunk)

        for i, (content, dl) in enumerate(lines):
            # Check permissions: blocks
            perm_match = _PERMISSIONS_RE.match(content)
            if perm_match:
                results.extend(self._check_permissions_block(f, lines, i))

            # Check pull_request_target
            if _PR_TARGET_RE.search(content) and _is_near_added(lines, i):
                results.append(
                    RuleResult(
                        rule_id=self.id,
                        severity=RuleSeverity.ERROR,
                        message="pull_request_target trigger detected — runs with base repo secrets",
                        file=f.path,
                        line=dl.new_lineno or dl.old_lineno,
                        evidence=content.strip(),
                    )
                )

            # Check unpinned actions (only on added lines)
            if dl.type == "add":
                uses_match = _USES_RE.match(content)
                if uses_match:
                    action_ref = uses_match.group(1).strip()
                    # Skip local actions (./), docker://, and already SHA-pinned
                    if (
                        not action_ref.startswith("./")
                        and not action_ref.startswith("docker://")
                        and not _SHA_PIN_RE.search(action_ref)
                    ):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=RuleSeverity.WARN,
                                message=f"Unpinned action — use SHA instead of tag: {action_ref}",
                                file=f.path,
                                line=dl.new_lineno,
                                evidence=content.strip(),
                            )
                        )

        return results

    def _check_permissions_block(
        self,
        f: ChangedFile,
        lines: list[tuple[str, DiffLine]],
        perm_idx: int,
    ) -> list[RuleResult]:
        """Scan indented children of a permissions: block for write/admin."""
        results: list[RuleResult] = []
        base_indent = _indent_level(lines[perm_idx][0])

        for j in range(perm_idx + 1, len(lines)):
            child_content, child_dl = lines[j]
            child_indent = _indent_level(child_content)
            if child_indent <= base_indent:
                break
            if _WRITE_ADMIN_RE.search(child_content) and _is_near_added(lines, j):
                results.append(
                    RuleResult(
                        rule_id=self.id,
                        severity=RuleSeverity.ERROR,
                        message="Workflow permissions expanded to write/admin",
                        file=f.path,
                        line=child_dl.new_lineno or child_dl.old_lineno,
                        evidence=child_content.strip(),
                    )
                )

        return results
