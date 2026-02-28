"""Tests for Grippy persistence layer — SQLite graph edges + LanceDB vectors."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from grippy.graph import EdgeType, NodeType, review_to_graph
from grippy.persistence import GrippyStore
from grippy.schema import (
    AsciiArtKey,
    ComplexityTier,
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

EMBED_DIM = 8


class _FakeEmbedder:
    """Deterministic fake embedder — hash-based, fixed dimension."""

    def get_embedding(self, text: str) -> list[float]:
        import hashlib

        h = hashlib.sha256(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:EMBED_DIM]]


def _make_finding(
    *,
    id: str = "F-001",
    severity: Severity = Severity.HIGH,
    file: str = "src/app.py",
    line_start: int = 42,
    title: str = "SQL injection in query builder",
    governance_rule_id: str | None = "SEC-001",
) -> Finding:
    return Finding(
        id=id,
        severity=severity,
        confidence=85,
        category=FindingCategory.SECURITY,
        file=file,
        line_start=line_start,
        line_end=line_start + 3,
        title=title,
        description="User input passed directly to SQL",
        suggestion="Use parameterized queries",
        governance_rule_id=governance_rule_id,
        evidence="f-string in execute()",
        grippy_note="This one hurt to read.",
    )


def _make_review(
    *,
    findings: list[Finding] | None = None,
    author: str = "testdev",
    title: str = "feat: add user auth",
    timestamp: str = "2026-02-26T12:00:00Z",
) -> GrippyReview:
    return GrippyReview(
        version="1.0",
        audit_type="pr_review",
        timestamp=timestamp,
        model="devstral-small-2-24b-instruct-2512",
        pr=PRMetadata(
            title=title,
            author=author,
            branch="feature/auth → main",
            complexity_tier=ComplexityTier.STANDARD,
        ),
        scope=ReviewScope(
            files_in_diff=3,
            files_reviewed=3,
            coverage_percentage=100.0,
            governance_rules_applied=["SEC-001"],
            modes_active=["pr_review"],
        ),
        findings=findings if findings is not None else [_make_finding()],
        escalations=[],
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
            summary="Fix the SQL injection.",
        ),
        personality=Personality(
            tone_register=ToneRegister.GRUMPY,
            opening_catchphrase="*adjusts reading glasses*",
            closing_line="Fix it.",
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


@pytest.fixture()
def store(tmp_path: Path) -> GrippyStore:
    """Create a GrippyStore with temp dirs for both databases."""
    return GrippyStore(
        graph_db_path=tmp_path / "grippy-graph.db",
        lance_dir=tmp_path / "lance",
        embedder=_FakeEmbedder(),
    )


# --- Construction ---


class TestGrippyStoreInit:
    def test_creates_sqlite_file(self, tmp_path: Path) -> None:
        """SQLite graph database file is created on init."""
        db_path = tmp_path / "grippy-graph.db"
        GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )
        assert db_path.exists()

    def test_creates_lance_dir(self, tmp_path: Path) -> None:
        """LanceDB directory is created on init."""
        lance_dir = tmp_path / "lance"
        GrippyStore(
            graph_db_path=tmp_path / "grippy-graph.db",
            lance_dir=lance_dir,
            embedder=_FakeEmbedder(),
        )
        assert lance_dir.exists()


# --- store_review ---


class TestStoreReview:
    def test_stores_edges_in_sqlite(self, store: GrippyStore) -> None:
        """Review graph edges are persisted to SQLite."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        edges = store.get_all_edges()
        assert len(edges) > 0

    def test_stores_nodes_in_lance(self, store: GrippyStore) -> None:
        """Review graph nodes are persisted to LanceDB."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        nodes = store.get_all_nodes()
        assert len(nodes) > 0

    def test_edge_schema_complete(self, store: GrippyStore) -> None:
        """Each stored edge has source_id, edge_type, target_id, metadata."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        edges = store.get_all_edges()
        for edge in edges:
            assert "source_id" in edge
            assert "edge_type" in edge
            assert "target_id" in edge
            assert "metadata" in edge

    def test_idempotent_store(self, store: GrippyStore) -> None:
        """Storing the same review twice doesn't create duplicate edges."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        count_1 = len(store.get_all_edges())
        store.store_review(graph)
        count_2 = len(store.get_all_edges())
        assert count_1 == count_2


# --- Edge queries ---


class TestEdgeQueries:
    def test_get_edges_by_source(self, store: GrippyStore) -> None:
        """Query edges by source node ID."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        finding_node = next(n for n in graph.nodes if n.type == NodeType.FINDING)
        edges = store.get_edges_by_source(finding_node.id)
        assert len(edges) > 0
        assert all(e["source_id"] == finding_node.id for e in edges)

    def test_get_edges_by_type(self, store: GrippyStore) -> None:
        """Query edges by edge type."""
        review = _make_review(findings=[_make_finding(governance_rule_id="SEC-001")])
        graph = review_to_graph(review)
        store.store_review(graph)
        edges = store.get_edges_by_type(EdgeType.VIOLATES)
        assert len(edges) == 1
        assert edges[0]["edge_type"] == "VIOLATES"

    def test_get_edges_by_target(self, store: GrippyStore) -> None:
        """Query edges by target node ID."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        file_node = next(n for n in graph.nodes if n.type == NodeType.FILE)
        edges = store.get_edges_by_target(file_node.id)
        assert len(edges) > 0
        assert all(e["target_id"] == file_node.id for e in edges)


# --- Author tendencies ---


class TestAuthorTendencies:
    def test_no_tendencies_for_unknown_author(self, store: GrippyStore) -> None:
        """Unknown author returns empty list."""
        result = store.get_author_tendencies("nobody")
        assert result == []

    def test_returns_findings_for_author(self, store: GrippyStore) -> None:
        """Returns finding nodes connected to the author's reviews."""
        review = _make_review(author="nelson")
        graph = review_to_graph(review)
        store.store_review(graph)
        tendencies = store.get_author_tendencies("nelson")
        assert len(tendencies) > 0

    def test_tendencies_scoped_to_author(self, store: GrippyStore) -> None:
        """Author A's reviews don't appear in author B's tendencies."""
        review_a = _make_review(
            author="alice",
            title="feat: alice's PR",
            timestamp="2026-02-26T12:00:00Z",
            findings=[_make_finding(id="F-001", title="Alice's bug", file="a.py", line_start=1)],
        )
        review_b = _make_review(
            author="bob",
            title="feat: bob's PR",
            timestamp="2026-02-26T12:01:00Z",
            findings=[_make_finding(id="F-002", title="Bob's bug", file="b.py", line_start=1)],
        )
        store.store_review(review_to_graph(review_a))
        store.store_review(review_to_graph(review_b))
        alice_tendencies = store.get_author_tendencies("alice")
        bob_tendencies = store.get_author_tendencies("bob")
        alice_titles = {t["title"] for t in alice_tendencies}
        bob_titles = {t["title"] for t in bob_tendencies}
        assert "Alice's bug" in alice_titles
        assert "Alice's bug" not in bob_titles
        assert "Bob's bug" in bob_titles


# --- File patterns ---


class TestFilePatterns:
    def test_no_patterns_for_unknown_file(self, store: GrippyStore) -> None:
        """Unknown file returns empty list."""
        result = store.get_patterns_for_file("nonexistent.py")
        assert result == []

    def test_returns_findings_for_file(self, store: GrippyStore) -> None:
        """Returns finding nodes for a specific file."""
        review = _make_review(
            findings=[_make_finding(file="src/routes.py", line_start=10, title="XSS vuln")]
        )
        store.store_review(review_to_graph(review))
        patterns = store.get_patterns_for_file("src/routes.py")
        assert len(patterns) > 0
        assert patterns[0]["title"] == "XSS vuln"


# --- Vector search ---


class TestVectorSearch:
    def test_search_returns_results(self, store: GrippyStore) -> None:
        """Semantic search returns matching nodes."""
        review = _make_review(findings=[_make_finding(title="SQL injection in query builder")])
        store.store_review(review_to_graph(review))
        results = store.search_nodes("SQL injection", k=5)
        assert len(results) > 0

    def test_search_empty_store_returns_empty(self, store: GrippyStore) -> None:
        """Search on empty store returns empty list."""
        results = store.search_nodes("anything", k=5)
        assert results == []

    def test_search_respects_k_limit(self, store: GrippyStore) -> None:
        """Search returns at most k results."""
        findings = [
            _make_finding(id=f"F-{i:03d}", title=f"Bug {i}", file=f"f{i}.py", line_start=i)
            for i in range(10)
        ]
        review = _make_review(findings=findings)
        store.store_review(review_to_graph(review))
        results = store.search_nodes("bug", k=3)
        assert len(results) <= 3


# --- Resolution queries ---


class TestResolutionQueries:
    """GrippyStore resolution matching for finding lifecycle."""

    def test_get_prior_findings_returns_open_findings(self, store: GrippyStore) -> None:
        """get_prior_findings returns findings with status='open'."""
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph, session_id="pr-1")
        findings = store.get_prior_findings(session_id="pr-1")
        assert len(findings) > 0
        for f in findings:
            assert f["status"] == "open"

    def test_get_prior_findings_empty_when_no_reviews(self, store: GrippyStore) -> None:
        """No stored reviews -> empty list."""
        findings = store.get_prior_findings(session_id="pr-nonexistent")
        assert findings == []

    def test_get_prior_findings_scoped_by_session(self, store: GrippyStore) -> None:
        """Prior findings are scoped to session_id (PR), not individual review."""
        # Round 1: store with session_id
        review_r1 = _make_review(
            title="feat: auth",
            timestamp="2026-02-26T12:00:00Z",
            findings=[_make_finding(title="SQL injection", file="auth.py")],
        )
        graph_r1 = review_to_graph(review_r1)
        store.store_review(graph_r1, session_id="pr-5")

        # Round 2: query BEFORE storing — should see round 1's findings
        prior = store.get_prior_findings(session_id="pr-5")
        assert len(prior) == 1
        assert prior[0]["title"] == "SQL injection"

    def test_prior_findings_excludes_other_sessions(self, store: GrippyStore) -> None:
        """Findings from different PRs are not returned."""
        review_pr5 = _make_review(
            title="PR 5",
            timestamp="2026-02-26T12:00:00Z",
            findings=[_make_finding(title="Bug in PR 5", file="a.py")],
        )
        review_pr6 = _make_review(
            title="PR 6",
            timestamp="2026-02-26T12:01:00Z",
            findings=[_make_finding(title="Bug in PR 6", file="b.py")],
        )
        store.store_review(review_to_graph(review_pr5), session_id="pr-5")
        store.store_review(review_to_graph(review_pr6), session_id="pr-6")

        prior_5 = store.get_prior_findings(session_id="pr-5")
        prior_6 = store.get_prior_findings(session_id="pr-6")
        assert all(f["title"] == "Bug in PR 5" for f in prior_5)
        assert all(f["title"] == "Bug in PR 6" for f in prior_6)

    def test_update_finding_status(self, store: GrippyStore) -> None:
        """update_finding_status changes a finding's status in node_meta."""
        import json as _json

        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        finding_nodes = [n for n in graph.nodes if n.type.value == "FINDING"]
        assert len(finding_nodes) > 0
        nid = finding_nodes[0].id
        store.update_finding_status(nid, "resolved")
        cur = store._conn.cursor()
        cur.execute("SELECT properties FROM node_meta WHERE node_id = ?", (nid,))
        props = _json.loads(cur.fetchone()["properties"])
        assert props["status"] == "resolved"


# --- Migration safety (Commit 4, Issue #4) ---


class TestUpdateFindingStatusWithEnum:
    """update_finding_status accepts FindingStatus enum."""

    def test_update_finding_status_with_enum(self, store: GrippyStore) -> None:
        """update_finding_status accepts FindingStatus.RESOLVED."""
        import json as _json

        from grippy.graph import FindingStatus

        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)
        finding_nodes = [n for n in graph.nodes if n.type.value == "FINDING"]
        assert len(finding_nodes) > 0
        nid = finding_nodes[0].id
        store.update_finding_status(nid, FindingStatus.RESOLVED)
        cur = store._conn.cursor()
        cur.execute("SELECT properties FROM node_meta WHERE node_id = ?", (nid,))
        props = _json.loads(cur.fetchone()["properties"])
        assert props["status"] == "resolved"


class TestMigrationSafety:
    """Migration error handling: ignore 'already exists', propagate real errors."""

    def test_real_error_propagates(self, tmp_path: Path) -> None:
        """OperationalError without 'already exists' propagates."""
        import grippy.persistence as persistence_mod

        # Inject a migration that triggers a real error (invalid SQL)
        original_migrations = persistence_mod._MIGRATIONS
        persistence_mod._MIGRATIONS = [
            "ALTER TABLE nonexistent_table ADD COLUMN bad_col TEXT",
        ]
        try:
            with pytest.raises(sqlite3.OperationalError, match="no such table"):
                GrippyStore(
                    graph_db_path=tmp_path / "test.db",
                    lance_dir=tmp_path / "lance",
                    embedder=_FakeEmbedder(),
                )
        finally:
            persistence_mod._MIGRATIONS = original_migrations

    def test_already_exists_ignored(self, tmp_path: Path) -> None:
        """First init creates column, second init silently ignores 'already exists'."""
        GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )
        # Second init — migration should not raise
        store2 = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance2",
            embedder=_FakeEmbedder(),
        )
        assert store2 is not None


# --- Batch embedding protocol (Commit 4, Issue #8) ---


class _FakeBatchEmbedder:
    """Embedder that supports both single and batch embedding."""

    def get_embedding(self, text: str) -> list[float]:
        import hashlib

        h = hashlib.sha256(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:EMBED_DIM]]

    def get_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.get_embedding(t) for t in texts]


class TestBatchEmbedding:
    """GrippyStore uses batch embedding when available."""

    def test_batch_embedder_used_when_available(self, tmp_path: Path) -> None:
        """Embedder with get_embedding_batch is called once for all texts."""
        embedder = _FakeBatchEmbedder()
        store = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=embedder,
        )
        review = _make_review()
        graph = review_to_graph(review)

        with patch.object(
            embedder, "get_embedding_batch", wraps=embedder.get_embedding_batch
        ) as mock_batch:
            store.store_review(graph)
            # Batch should be called once with all texts
            mock_batch.assert_called_once()
            texts_arg = mock_batch.call_args[0][0]
            assert len(texts_arg) == len(graph.nodes)

    def test_single_embedder_fallback(self, tmp_path: Path) -> None:
        """Embedder without get_embedding_batch falls back to individual calls."""
        embedder = _FakeEmbedder()
        store = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=embedder,
        )
        review = _make_review()
        graph = review_to_graph(review)

        with patch.object(embedder, "get_embedding", wraps=embedder.get_embedding) as mock_single:
            store.store_review(graph)
            # Single should be called N times (once per node)
            assert mock_single.call_count == len(graph.nodes)

    def test_batch_embedder_stores_correct_vectors(self, tmp_path: Path) -> None:
        """Batch result vectors are correctly associated with their records."""
        embedder = _FakeBatchEmbedder()
        store = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=embedder,
        )
        review = _make_review()
        graph = review_to_graph(review)
        store.store_review(graph)

        nodes = store.get_all_nodes()
        assert len(nodes) > 0
        # Each node should have a vector
        for node in nodes:
            assert "vector" in node
            assert len(node["vector"]) == EMBED_DIM
