"""Tests for Grippy graph enums and finding lifecycle utilities."""

from __future__ import annotations

from grippy.graph import (
    EdgeType,
    FindingStatus,
    NodeType,
    cross_reference_findings,
)
from grippy.schema import (
    Finding,
    FindingCategory,
    Severity,
)

# --- Fixtures ---


def _make_finding(
    *,
    id: str = "F-001",
    severity: Severity = Severity.HIGH,
    confidence: int = 85,
    category: FindingCategory = FindingCategory.SECURITY,
    file: str = "src/app.py",
    line_start: int = 42,
    line_end: int = 45,
    title: str = "SQL injection in query builder",
    description: str = "User input passed directly to SQL",
    suggestion: str = "Use parameterized queries",
    governance_rule_id: str | None = "SEC-001",
    evidence: str = "f-string in execute()",
    grippy_note: str = "This one hurt to read.",
) -> Finding:
    return Finding(
        id=id,
        severity=severity,
        confidence=confidence,
        category=category,
        file=file,
        line_start=line_start,
        line_end=line_end,
        title=title,
        description=description,
        suggestion=suggestion,
        governance_rule_id=governance_rule_id,
        evidence=evidence,
        grippy_note=grippy_note,
    )


# --- Enum values ---


class TestEdgeTypeAdditions:
    """Edge type enum values."""

    def test_resolves_edge_exists(self) -> None:
        assert EdgeType.RESOLVES == "RESOLVES"

    def test_persists_as_edge_exists(self) -> None:
        assert EdgeType.PERSISTS_AS == "PERSISTS_AS"

    def test_extracted_from_edge_exists(self) -> None:
        assert EdgeType.EXTRACTED_FROM == "EXTRACTED_FROM"

    def test_reviewed_by_edge_exists(self) -> None:
        assert EdgeType.REVIEWED_BY == "REVIEWED_BY"


class TestNodeType:
    def test_node_types(self) -> None:
        assert NodeType.REVIEW == "REVIEW"
        assert NodeType.FINDING == "FINDING"
        assert NodeType.FILE == "FILE"
        assert NodeType.AUTHOR == "AUTHOR"
        assert NodeType.SUGGESTION == "SUGGESTION"
        assert NodeType.RULE == "RULE"


# --- FindingStatus enum ---


class TestFindingStatus:
    """FindingStatus enum for finding lifecycle."""

    def test_enum_values(self) -> None:
        assert FindingStatus.OPEN == "open"
        assert FindingStatus.RESOLVED == "resolved"


# --- cross_reference_findings ---


class TestCrossReferenceFindings:
    """cross_reference_findings compares current vs previous findings by fingerprint."""

    def test_new_finding_no_previous(self) -> None:
        """All findings are NEW when there's no previous round."""
        current = [_make_finding(file="a.py", title="Bug A")]
        result = cross_reference_findings(current, [])
        assert len(result.new) == 1
        assert len(result.persists) == 0
        assert len(result.resolved) == 0

    def test_persisting_finding(self) -> None:
        """Finding with same fingerprint in both rounds is PERSISTS."""
        f1 = _make_finding(file="a.py", title="Bug A", line_start=10)
        f2 = _make_finding(file="a.py", title="Bug A", line_start=50)
        result = cross_reference_findings([f2], [f1])
        assert len(result.persists) == 1
        assert len(result.new) == 0
        assert len(result.resolved) == 0

    def test_resolved_finding(self) -> None:
        """Finding in previous but not current is RESOLVED."""
        prev = _make_finding(file="a.py", title="Bug A")
        current = _make_finding(file="b.py", title="Bug B")
        result = cross_reference_findings([current], [prev])
        assert len(result.resolved) == 1
        assert result.resolved[0].fingerprint == prev.fingerprint

    def test_mixed_lifecycle(self) -> None:
        """Mix of new, persisting, and resolved findings."""
        shared = _make_finding(file="shared.py", title="Shared Bug")
        old_only = _make_finding(file="old.py", title="Old Bug")
        new_only = _make_finding(file="new.py", title="New Bug")
        result = cross_reference_findings([shared, new_only], [shared, old_only])
        assert len(result.new) == 1
        assert len(result.persists) == 1
        assert len(result.resolved) == 1
