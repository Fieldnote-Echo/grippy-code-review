"""Tests for Grippy graph data model — typed nodes and directed edges."""

from __future__ import annotations

from grippy.graph import (
    Edge,
    EdgeType,
    FindingStatus,
    Node,
    NodeType,
    ReviewGraph,
    cross_reference_findings,
    node_id,
    review_to_graph,
)
from grippy.schema import (
    AsciiArtKey,
    ComplexityTier,
    Escalation,
    Finding,
    FindingCategory,
    GrippyReview,
    Personality,
    PRMetadata,
    ReviewMeta,
    ReviewScope,
    Score,
    ScoreBreakdown,
    ScoreDeductions,
    Severity,
    ToneRegister,
    Verdict,
    VerdictStatus,
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


def _make_review(
    *,
    findings: list[Finding] | None = None,
    escalations: list[Escalation] | None = None,
    author: str = "testdev",
) -> GrippyReview:
    return GrippyReview(
        version="1.0",
        audit_type="pr_review",
        timestamp="2026-02-26T12:00:00Z",
        model="devstral-small-2-24b-instruct-2512",
        pr=PRMetadata(
            title="feat: add user auth",
            author=author,
            branch="feature/auth → main",
            complexity_tier=ComplexityTier.STANDARD,
        ),
        scope=ReviewScope(
            files_in_diff=3,
            files_reviewed=3,
            coverage_percentage=100.0,
            governance_rules_applied=["SEC-001", "GOV-002"],
            modes_active=["pr_review"],
        ),
        findings=findings if findings is not None else [_make_finding()],
        escalations=escalations if escalations is not None else [],
        score=Score(
            overall=72,
            breakdown=ScoreBreakdown(
                security=60, logic=80, governance=75, reliability=70, observability=75
            ),
            deductions=ScoreDeductions(
                critical_count=0, high_count=1, medium_count=0, low_count=0, total_deduction=28
            ),
        ),
        verdict=Verdict(
            status=VerdictStatus.PROVISIONAL,
            threshold_applied=70,
            merge_blocking=False,
            summary="Fix the SQL injection before merge.",
        ),
        personality=Personality(
            tone_register=ToneRegister.GRUMPY,
            opening_catchphrase="*adjusts reading glasses*",
            closing_line="Fix it or I'm telling the security team.",
            ascii_art_key=AsciiArtKey.WARNING,
        ),
        meta=ReviewMeta(
            review_duration_ms=45000,
            tokens_used=8200,
            context_files_loaded=3,
            confidence_filter_suppressed=1,
            duplicate_filter_suppressed=0,
        ),
    )


# --- Node ID determinism ---


class TestNodeId:
    def test_deterministic_same_inputs(self) -> None:
        """Same inputs produce the same node ID."""
        id1 = node_id(NodeType.FINDING, "src/app.py", 42, "SQL injection in query builder")
        id2 = node_id(NodeType.FINDING, "src/app.py", 42, "SQL injection in query builder")
        assert id1 == id2

    def test_different_inputs_different_ids(self) -> None:
        """Different inputs produce different node IDs."""
        id1 = node_id(NodeType.FINDING, "src/app.py", 42, "SQL injection")
        id2 = node_id(NodeType.FINDING, "src/app.py", 43, "SQL injection")
        assert id1 != id2

    def test_includes_node_type_prefix(self) -> None:
        """Node IDs are prefixed with the node type for readability."""
        nid = node_id(NodeType.FINDING, "src/app.py", 42, "SQL injection")
        assert nid.startswith("FINDING:")

    def test_different_types_different_ids(self) -> None:
        """Same content but different node types produce different IDs."""
        id1 = node_id(NodeType.FINDING, "src/app.py")
        id2 = node_id(NodeType.FILE, "src/app.py")
        assert id1 != id2


# --- Edge model ---


class TestEdge:
    def test_construction(self) -> None:
        edge = Edge(
            type=EdgeType.VIOLATES,
            target_id="RULE:abc123",
            target_type=NodeType.RULE,
        )
        assert edge.type == EdgeType.VIOLATES
        assert edge.target_id == "RULE:abc123"
        assert edge.metadata == {}

    def test_with_metadata(self) -> None:
        edge = Edge(
            type=EdgeType.TENDENCY,
            target_id="PATTERN:xyz",
            target_type=NodeType.PATTERN,
            metadata={"frequency": 3, "last_seen": "2026-02-26"},
        )
        assert edge.metadata["frequency"] == 3


# --- Node model ---


class TestNode:
    def test_construction(self) -> None:
        node = Node(
            id="FINDING:abc123",
            type=NodeType.FINDING,
            label="SQL injection in query builder",
            properties={"severity": "HIGH", "confidence": 85},
            created_at="2026-02-26T12:00:00Z",
        )
        assert node.type == NodeType.FINDING
        assert node.edges == []
        assert node.source_review_id is None

    def test_with_edges(self) -> None:
        edge = Edge(
            type=EdgeType.FOUND_IN,
            target_id="FILE:abc",
            target_type=NodeType.FILE,
        )
        node = Node(
            id="FINDING:abc123",
            type=NodeType.FINDING,
            label="SQL injection",
            properties={},
            edges=[edge],
            created_at="2026-02-26T12:00:00Z",
            source_review_id="REVIEW:xyz",
        )
        assert len(node.edges) == 1
        assert node.source_review_id == "REVIEW:xyz"


# --- ReviewGraph model ---


class TestReviewGraph:
    def test_construction(self) -> None:
        graph = ReviewGraph(
            review_id="REVIEW:abc123",
            nodes=[],
            timestamp="2026-02-26T12:00:00Z",
        )
        assert graph.review_id.startswith("REVIEW:")
        assert graph.nodes == []


# --- review_to_graph transformation ---


class TestReviewToGraph:
    def test_produces_review_node(self) -> None:
        """The graph contains a REVIEW node."""
        review = _make_review()
        graph = review_to_graph(review)
        review_nodes = [n for n in graph.nodes if n.type == NodeType.REVIEW]
        assert len(review_nodes) == 1
        assert review_nodes[0].properties["audit_type"] == "pr_review"
        assert review_nodes[0].properties["overall_score"] == 72
        assert review_nodes[0].properties["verdict"] == "PROVISIONAL"

    def test_produces_author_node(self) -> None:
        """The graph contains an AUTHOR node for the PR author."""
        review = _make_review(author="nelson")
        graph = review_to_graph(review)
        author_nodes = [n for n in graph.nodes if n.type == NodeType.AUTHOR]
        assert len(author_nodes) == 1
        assert author_nodes[0].label == "nelson"

    def test_review_has_reviewed_by_edge(self) -> None:
        """REVIEW node has a REVIEWED_BY edge to the agent."""
        review = _make_review()
        graph = review_to_graph(review)
        review_node = next(n for n in graph.nodes if n.type == NodeType.REVIEW)
        reviewed_by = [e for e in review_node.edges if e.type == EdgeType.REVIEWED_BY]
        assert len(reviewed_by) == 1

    def test_finding_becomes_node_with_edges(self) -> None:
        """Each Finding becomes a FINDING node with FOUND_IN and FIXED_BY edges."""
        review = _make_review(findings=[_make_finding()])
        graph = review_to_graph(review)
        finding_nodes = [n for n in graph.nodes if n.type == NodeType.FINDING]
        assert len(finding_nodes) == 1

        node = finding_nodes[0]
        edge_types = {e.type for e in node.edges}
        assert EdgeType.FOUND_IN in edge_types
        assert EdgeType.FIXED_BY in edge_types

    def test_finding_with_governance_rule_has_violates_edge(self) -> None:
        """Finding with governance_rule_id gets a VIOLATES edge to a RULE node."""
        review = _make_review(findings=[_make_finding(governance_rule_id="SEC-001")])
        graph = review_to_graph(review)
        finding_node = next(n for n in graph.nodes if n.type == NodeType.FINDING)
        violates = [e for e in finding_node.edges if e.type == EdgeType.VIOLATES]
        assert len(violates) == 1
        assert violates[0].target_type == NodeType.RULE

        # RULE node should also exist in graph
        rule_nodes = [n for n in graph.nodes if n.type == NodeType.RULE]
        assert len(rule_nodes) == 1
        assert rule_nodes[0].label == "SEC-001"

    def test_finding_without_governance_rule_has_no_violates_edge(self) -> None:
        """Finding without governance_rule_id skips VIOLATES edge."""
        review = _make_review(findings=[_make_finding(governance_rule_id=None)])
        graph = review_to_graph(review)
        finding_node = next(n for n in graph.nodes if n.type == NodeType.FINDING)
        violates = [e for e in finding_node.edges if e.type == EdgeType.VIOLATES]
        assert len(violates) == 0

    def test_file_nodes_deduplicated(self) -> None:
        """Multiple findings in the same file produce one FILE node."""
        findings = [
            _make_finding(id="F-001", file="src/app.py", line_start=10, title="Bug A"),
            _make_finding(id="F-002", file="src/app.py", line_start=50, title="Bug B"),
        ]
        review = _make_review(findings=findings)
        graph = review_to_graph(review)
        file_nodes = [n for n in graph.nodes if n.type == NodeType.FILE]
        assert len(file_nodes) == 1
        assert file_nodes[0].label == "src/app.py"

    def test_multiple_findings_multiple_files(self) -> None:
        """Findings in different files produce separate FILE nodes."""
        findings = [
            _make_finding(id="F-001", file="src/app.py", line_start=10, title="Bug A"),
            _make_finding(id="F-002", file="src/routes.py", line_start=20, title="Bug B"),
        ]
        review = _make_review(findings=findings)
        graph = review_to_graph(review)
        file_nodes = [n for n in graph.nodes if n.type == NodeType.FILE]
        assert len(file_nodes) == 2

    def test_rule_nodes_deduplicated(self) -> None:
        """Multiple findings violating the same rule produce one RULE node."""
        findings = [
            _make_finding(
                id="F-001", file="a.py", line_start=1, title="A", governance_rule_id="SEC-001"
            ),
            _make_finding(
                id="F-002", file="b.py", line_start=2, title="B", governance_rule_id="SEC-001"
            ),
        ]
        review = _make_review(findings=findings)
        graph = review_to_graph(review)
        rule_nodes = [n for n in graph.nodes if n.type == NodeType.RULE]
        assert len(rule_nodes) == 1

    def test_empty_findings_produces_minimal_graph(self) -> None:
        """Review with no findings still produces REVIEW + AUTHOR nodes."""
        review = _make_review(findings=[])
        graph = review_to_graph(review)
        types = {n.type for n in graph.nodes}
        assert NodeType.REVIEW in types
        assert NodeType.AUTHOR in types
        assert NodeType.FINDING not in types

    def test_finding_properties_preserved(self) -> None:
        """Finding node properties contain the important fields."""
        finding = _make_finding(
            severity=Severity.CRITICAL,
            confidence=95,
            category=FindingCategory.SECURITY,
        )
        review = _make_review(findings=[finding])
        graph = review_to_graph(review)
        finding_node = next(n for n in graph.nodes if n.type == NodeType.FINDING)
        assert finding_node.properties["severity"] == "CRITICAL"
        assert finding_node.properties["confidence"] == 95
        assert finding_node.properties["category"] == "security"

    def test_graph_timestamp_matches_review(self) -> None:
        """Graph timestamp comes from the review."""
        review = _make_review()
        graph = review_to_graph(review)
        assert graph.timestamp == "2026-02-26T12:00:00Z"

    def test_all_nodes_have_source_review_id(self) -> None:
        """Every node except REVIEW itself references the source review."""
        review = _make_review()
        graph = review_to_graph(review)
        review_id = graph.review_id
        for node in graph.nodes:
            if node.type == NodeType.REVIEW:
                assert node.source_review_id is None
            else:
                assert node.source_review_id == review_id

    def test_suggestion_nodes_created(self) -> None:
        """Each finding with a suggestion gets a SUGGESTION node."""
        review = _make_review(findings=[_make_finding(suggestion="Use parameterized queries")])
        graph = review_to_graph(review)
        suggestion_nodes = [n for n in graph.nodes if n.type == NodeType.SUGGESTION]
        assert len(suggestion_nodes) == 1
        assert "parameterized" in suggestion_nodes[0].label.lower()

    def test_node_ids_are_deterministic_across_calls(self) -> None:
        """Same review produces same node IDs."""
        review = _make_review()
        graph1 = review_to_graph(review)
        graph2 = review_to_graph(review)
        ids1 = sorted(n.id for n in graph1.nodes)
        ids2 = sorted(n.id for n in graph2.nodes)
        assert ids1 == ids2

    def test_finding_node_includes_fingerprint(self) -> None:
        """Finding node properties include the deterministic fingerprint."""
        review = _make_review(findings=[_make_finding()])
        graph = review_to_graph(review)
        finding_node = next(n for n in graph.nodes if n.type == NodeType.FINDING)
        assert "fingerprint" in finding_node.properties
        assert len(finding_node.properties["fingerprint"]) == 12


# --- Edge type additions ---


class TestEdgeTypeAdditions:
    """RESOLVES and PERSISTS_AS edges for finding lifecycle tracking."""

    def test_resolves_edge_exists(self) -> None:
        assert EdgeType.RESOLVES == "RESOLVES"

    def test_persists_as_edge_exists(self) -> None:
        assert EdgeType.PERSISTS_AS == "PERSISTS_AS"


# --- cross_reference_findings ---


# --- FindingStatus enum (Commit 6, Issue #9) ---


class TestFindingStatus:
    """FindingStatus enum for finding lifecycle."""

    def test_enum_values(self) -> None:
        assert FindingStatus.OPEN == "open"
        assert FindingStatus.RESOLVED == "resolved"

    def test_review_to_graph_uses_finding_status(self) -> None:
        """Finding node properties use FindingStatus.OPEN, not string literal."""
        review = _make_review(findings=[_make_finding()])
        graph = review_to_graph(review)
        finding_node = next(n for n in graph.nodes if n.type == NodeType.FINDING)
        assert finding_node.properties["status"] == FindingStatus.OPEN
        assert finding_node.properties["status"] == "open"


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
