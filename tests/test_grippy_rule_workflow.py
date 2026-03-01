# SPDX-License-Identifier: MIT
"""Tests for Rule 1: workflow-permissions-expanded."""

from __future__ import annotations

from grippy.rules.base import RuleSeverity
from grippy.rules.config import ProfileConfig
from grippy.rules.context import RuleContext, parse_diff
from grippy.rules.workflow_permissions import WorkflowPermissionsRule


def _ctx(diff: str) -> RuleContext:
    return RuleContext(
        diff=diff,
        files=parse_diff(diff),
        config=ProfileConfig(name="security", fail_on=RuleSeverity.ERROR),
    )


class TestWorkflowPermissions:
    def test_write_permission_on_added_line(self) -> None:
        diff = (
            "diff --git a/.github/workflows/deploy.yml b/.github/workflows/deploy.yml\n"
            "--- a/.github/workflows/deploy.yml\n"
            "+++ b/.github/workflows/deploy.yml\n"
            "@@ -1,3 +1,5 @@\n"
            " name: deploy\n"
            "+permissions:\n"
            "+  contents: write\n"
            " on:\n"
            "   push:\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert any(
            r.severity == RuleSeverity.ERROR and "write" in r.message.lower() for r in results
        )

    def test_admin_permission(self) -> None:
        diff = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -1,3 +1,5 @@\n"
            " name: ci\n"
            "+permissions:\n"
            "+  packages: admin\n"
            " on:\n"
            "   push:\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert any(r.severity == RuleSeverity.ERROR for r in results)

    def test_read_permission_not_flagged(self) -> None:
        diff = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -1,3 +1,5 @@\n"
            " name: ci\n"
            "+permissions:\n"
            "+  contents: read\n"
            " on:\n"
            "   push:\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert not any(
            "write" in r.message.lower() or "admin" in r.message.lower() for r in results
        )

    def test_pull_request_target(self) -> None:
        diff = (
            "diff --git a/.github/workflows/pr.yml b/.github/workflows/pr.yml\n"
            "--- a/.github/workflows/pr.yml\n"
            "+++ b/.github/workflows/pr.yml\n"
            "@@ -1,3 +1,4 @@\n"
            " name: pr\n"
            " on:\n"
            "+  pull_request_target:\n"
            "   push:\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert any("pull_request_target" in r.message for r in results)

    def test_unpinned_action(self) -> None:
        diff = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -5,3 +5,4 @@\n"
            " jobs:\n"
            "   build:\n"
            "     steps:\n"
            "+      - uses: actions/checkout@v4\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert any(r.severity == RuleSeverity.WARN and "Unpinned" in r.message for r in results)

    def test_sha_pinned_action_not_flagged(self) -> None:
        diff = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -5,3 +5,4 @@\n"
            " jobs:\n"
            "   build:\n"
            "     steps:\n"
            "+      - uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert not any("Unpinned" in r.message for r in results)

    def test_local_action_not_flagged(self) -> None:
        diff = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -5,3 +5,4 @@\n"
            " jobs:\n"
            "   build:\n"
            "     steps:\n"
            "+      - uses: ./my-action\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert not any("Unpinned" in r.message for r in results)

    def test_scalar_permissions_write_all(self) -> None:
        """Scalar 'permissions: write-all' on same line is detected."""
        diff = (
            "diff --git a/.github/workflows/deploy.yml b/.github/workflows/deploy.yml\n"
            "--- a/.github/workflows/deploy.yml\n"
            "+++ b/.github/workflows/deploy.yml\n"
            "@@ -1,3 +1,4 @@\n"
            " name: deploy\n"
            "+permissions: write-all\n"
            " on:\n"
            "   push:\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert any(
            r.severity == RuleSeverity.ERROR and "write" in r.message.lower() for r in results
        )

    def test_scalar_permissions_read_not_flagged(self) -> None:
        """Scalar 'permissions: read-all' is not flagged."""
        diff = (
            "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\n"
            "--- a/.github/workflows/ci.yml\n"
            "+++ b/.github/workflows/ci.yml\n"
            "@@ -1,3 +1,4 @@\n"
            " name: ci\n"
            "+permissions: read-all\n"
            " on:\n"
            "   push:\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert not any(
            "write" in r.message.lower() or "admin" in r.message.lower() for r in results
        )

    def test_non_workflow_file_ignored(self) -> None:
        diff = (
            "diff --git a/config.yml b/config.yml\n"
            "--- a/config.yml\n"
            "+++ b/config.yml\n"
            "@@ -1,1 +1,2 @@\n"
            " key: value\n"
            "+permissions: write\n"
        )
        rule = WorkflowPermissionsRule()
        results = rule.run(_ctx(diff))
        assert results == []
