"""Tests for Grippy persistence layer — SQLite graph + LanceDB vectors."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from grippy.graph import EdgeType, FindingStatus, NodeType
from grippy.persistence import GrippyStore, _record_id
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
    evidence: str = "f-string in execute()",
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
        evidence=evidence,
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


# --- _record_id ---


class TestRecordId:
    def test_deterministic(self) -> None:
        """Same inputs produce the same ID."""
        id1 = _record_id(NodeType.FINDING, "abc123def456")
        id2 = _record_id(NodeType.FINDING, "abc123def456")
        assert id1 == id2

    def test_includes_type_prefix(self) -> None:
        """IDs are prefixed with node type."""
        nid = _record_id(NodeType.FILE, "src/app.py")
        assert nid.startswith("FILE:")

    def test_different_inputs_different_ids(self) -> None:
        """Different inputs produce different IDs."""
        id1 = _record_id(NodeType.FINDING, "fingerprint_a")
        id2 = _record_id(NodeType.FINDING, "fingerprint_b")
        assert id1 != id2

    def test_accepts_string_type(self) -> None:
        """Accepts string node type (not just enum)."""
        nid = _record_id("CUSTOM", "some_value")
        assert nid.startswith("CUSTOM:")

    def test_different_types_same_parts_different_digest(self) -> None:
        """Different node types with the same parts produce different hash digests."""
        file_id = _record_id(NodeType.FILE, "src/app.py")
        rule_id = _record_id(NodeType.RULE, "src/app.py")
        # Prefixes differ obviously, but the digests must also differ
        file_digest = file_id.split(":")[1]
        rule_digest = rule_id.split(":")[1]
        assert file_digest != rule_digest


# --- Construction ---


class TestGrippyStoreInit:
    def test_creates_sqlite_file(self, tmp_path: Path) -> None:
        """SQLite database file is created on init."""
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

    def test_sqlite_schema_has_nodes_table(self, store: GrippyStore) -> None:
        """SQLite has nodes table with expected columns."""
        cur = store._conn.cursor()
        cur.execute("PRAGMA table_info(nodes)")
        columns = {row["name"] for row in cur.fetchall()}
        assert {
            "id",
            "type",
            "label",
            "data",
            "session_id",
            "status",
            "fingerprint",
            "created_at",
        } <= columns

    def test_sqlite_schema_has_edges_table(self, store: GrippyStore) -> None:
        """SQLite has edges table with expected columns."""
        cur = store._conn.cursor()
        cur.execute("PRAGMA table_info(edges)")
        columns = {row["name"] for row in cur.fetchall()}
        assert {"source", "target", "relationship", "weight", "properties", "created_at"} <= columns

    def test_wal_mode_enabled(self, store: GrippyStore) -> None:
        """WAL journal mode is active."""
        cur = store._conn.cursor()
        cur.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode == "wal"

    def test_migrates_v1_schema(self, tmp_path: Path) -> None:
        """Opening a DB with v1 schema (source_id, edge_type, target_id) drops and recreates."""
        db_path = tmp_path / "grippy-graph.db"
        import sqlite3

        # Create a v1-shaped database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, label TEXT, data TEXT)")
        conn.execute(
            "CREATE TABLE edges (source_id TEXT, edge_type TEXT, target_id TEXT, metadata TEXT)"
        )
        conn.execute("CREATE TABLE node_meta (node_id TEXT PRIMARY KEY, meta TEXT)")
        conn.commit()
        conn.close()

        # Open with GrippyStore — should migrate
        store = GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )

        # Verify v2 schema is in place
        cur = store._conn.cursor()
        cur.execute("PRAGMA table_info(edges)")
        columns = {row["name"] for row in cur.fetchall()}
        assert "source" in columns
        assert "source_id" not in columns

        # Verify node_meta is gone
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='node_meta'")
        assert cur.fetchone() is None

    def test_lance_table_found_without_list_tables(self, tmp_path: Path) -> None:
        """LanceDB table is found even when list_tables() returns stale results."""
        store = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )
        review = _make_review()
        store.store_review(review)

        # Simulate stale list_tables by clearing the cached reference
        store._nodes_table = None

        # Should still find and use the existing table (not crash)
        nodes = store.get_all_nodes()
        assert len(nodes) > 0

    def test_v2_schema_not_dropped(self, tmp_path: Path) -> None:
        """Opening a DB that already has v2 schema preserves existing data."""
        db_path = tmp_path / "grippy-graph.db"

        # Create store, insert data, close
        store1 = GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )
        review = _make_review()
        store1.store_review(review, session_id="pr-1")
        cur = store1._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM nodes")
        count_before = cur.fetchone()[0]
        store1._conn.close()

        # Re-open — should NOT drop tables
        store2 = GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )
        cur = store2._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM nodes")
        count_after = cur.fetchone()[0]
        assert count_after == count_before


# --- store_review ---


class TestStoreReview:
    def test_stores_nodes_in_sqlite(self, store: GrippyStore) -> None:
        """Review nodes are persisted to SQLite."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM nodes")
        count = cur.fetchone()[0]
        assert count > 0

    def test_stores_edges_in_sqlite(self, store: GrippyStore) -> None:
        """Review edges are persisted to SQLite."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM edges")
        count = cur.fetchone()[0]
        assert count > 0

    def test_stores_vectors_in_lance(self, store: GrippyStore) -> None:
        """Review nodes are persisted to LanceDB with vectors."""
        review = _make_review()
        store.store_review(review)
        nodes = store.get_all_nodes()
        assert len(nodes) > 0

    def test_creates_expected_node_types(self, store: GrippyStore) -> None:
        """Store creates REVIEW, AUTHOR, FILE, FINDING, SUGGESTION, RULE nodes."""
        review = _make_review(findings=[_make_finding(governance_rule_id="SEC-001")])
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT DISTINCT type FROM nodes")
        types = {row["type"] for row in cur.fetchall()}
        assert {
            NodeType.REVIEW.value,
            NodeType.AUTHOR.value,
            NodeType.FILE.value,
            NodeType.FINDING.value,
            NodeType.SUGGESTION.value,
            NodeType.RULE.value,
        } <= types

    def test_creates_expected_edge_types(self, store: GrippyStore) -> None:
        """Store creates EXTRACTED_FROM, REVIEWED_BY, FOUND_IN, FIXED_BY, VIOLATES edges."""
        review = _make_review(findings=[_make_finding(governance_rule_id="SEC-001")])
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT DISTINCT relationship FROM edges")
        rels = {row["relationship"] for row in cur.fetchall()}
        assert {
            EdgeType.EXTRACTED_FROM.value,
            EdgeType.REVIEWED_BY.value,
            EdgeType.FOUND_IN.value,
            EdgeType.FIXED_BY.value,
            EdgeType.VIOLATES.value,
        } <= rels

    def test_finding_node_has_status_column(self, store: GrippyStore) -> None:
        """Finding nodes have status as a real column."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT status FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        row = cur.fetchone()
        assert row["status"] == "open"

    def test_finding_node_has_fingerprint_column(self, store: GrippyStore) -> None:
        """Finding nodes have fingerprint as a real column."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT fingerprint FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        row = cur.fetchone()
        assert row["fingerprint"] is not None
        assert len(row["fingerprint"]) == 12

    def test_finding_id_uses_fingerprint(self, store: GrippyStore) -> None:
        """Finding node ID is derived from fingerprint for cross-round stability."""
        finding = _make_finding()
        expected_id = _record_id(NodeType.FINDING, finding.fingerprint)
        review = _make_review(findings=[finding])
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT id FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        row = cur.fetchone()
        assert row["id"] == expected_id


# --- Idempotency (UPSERT) ---


class TestIdempotency:
    def test_duplicate_store_no_duplicate_nodes(self, store: GrippyStore) -> None:
        """Storing the same review twice doesn't create duplicate nodes."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM nodes")
        count_1 = cur.fetchone()[0]
        store.store_review(review)
        cur.execute("SELECT COUNT(*) FROM nodes")
        count_2 = cur.fetchone()[0]
        assert count_1 == count_2

    def test_duplicate_store_no_duplicate_edges(self, store: GrippyStore) -> None:
        """Storing the same review twice doesn't create duplicate edges."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM edges")
        count_1 = cur.fetchone()[0]
        store.store_review(review)
        cur.execute("SELECT COUNT(*) FROM edges")
        count_2 = cur.fetchone()[0]
        assert count_1 == count_2

    def test_upsert_updates_metadata(self, store: GrippyStore) -> None:
        """UPSERT updates node metadata when evidence changes between runs."""
        finding_v1 = _make_finding(evidence="old evidence")
        review_v1 = _make_review(findings=[finding_v1])
        store.store_review(review_v1)

        # Second store with updated evidence (same fingerprint = same file+category)
        finding_v2 = _make_finding(evidence="new evidence")
        review_v2 = _make_review(findings=[finding_v2])
        store.store_review(review_v2)

        cur = store._conn.cursor()
        cur.execute("SELECT data FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        row = cur.fetchone()
        data = json.loads(row["data"])
        assert data["evidence"] == "new evidence"

    def test_upsert_preserves_resolved_status(self, store: GrippyStore) -> None:
        """UPSERT preserves 'resolved' status — doesn't revert to 'open'."""
        review = _make_review()
        store.store_review(review, session_id="pr-1")

        # Mark finding as resolved
        cur = store._conn.cursor()
        cur.execute("SELECT id FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        finding_id = cur.fetchone()["id"]
        store.update_finding_status(finding_id, FindingStatus.RESOLVED)

        # Re-store the same review — status should stay 'resolved'
        store.store_review(review, session_id="pr-1")
        cur.execute("SELECT status FROM nodes WHERE id = ?", (finding_id,))
        assert cur.fetchone()["status"] == "resolved"


# --- Author tendencies (single-pass SQL join) ---


class TestAuthorTendencies:
    def test_no_tendencies_for_unknown_author(self, store: GrippyStore) -> None:
        """Unknown author returns empty list."""
        result = store.get_author_tendencies("nobody")
        assert result == []

    def test_returns_findings_for_author(self, store: GrippyStore) -> None:
        """Returns finding nodes connected to the author's reviews."""
        review = _make_review(author="nelson")
        store.store_review(review)
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
        store.store_review(review_a)
        store.store_review(review_b)
        alice_tendencies = store.get_author_tendencies("alice")
        bob_tendencies = store.get_author_tendencies("bob")
        alice_titles = {t["title"] for t in alice_tendencies}
        bob_titles = {t["title"] for t in bob_tendencies}
        assert "Alice's bug" in alice_titles
        assert "Alice's bug" not in bob_titles
        assert "Bob's bug" in bob_titles

    def test_traverses_extracted_from_and_reviewed_by(self, store: GrippyStore) -> None:
        """Tendencies traverse Finding -[EXTRACTED_FROM]-> Review -[REVIEWED_BY]-> Author."""
        review = _make_review(author="testdev")
        store.store_review(review)

        # Verify the edges exist
        cur = store._conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = ?",
            (EdgeType.EXTRACTED_FROM.value,),
        )
        assert cur.fetchone()[0] > 0
        cur.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = ?",
            (EdgeType.REVIEWED_BY.value,),
        )
        assert cur.fetchone()[0] > 0

        # The join should work
        tendencies = store.get_author_tendencies("testdev")
        assert len(tendencies) > 0


# --- File patterns (single-pass SQL join) ---


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
        store.store_review(review)
        patterns = store.get_patterns_for_file("src/routes.py")
        assert len(patterns) > 0
        assert patterns[0]["title"] == "XSS vuln"

    def test_traverses_found_in_edges(self, store: GrippyStore) -> None:
        """Patterns traverse Finding -[FOUND_IN]-> File."""
        review = _make_review(findings=[_make_finding(file="src/app.py")])
        store.store_review(review)

        cur = store._conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = ?",
            (EdgeType.FOUND_IN.value,),
        )
        assert cur.fetchone()[0] > 0

        patterns = store.get_patterns_for_file("src/app.py")
        assert len(patterns) > 0


# --- Vector search ---


class TestVectorSearch:
    def test_search_returns_results(self, store: GrippyStore) -> None:
        """Semantic search returns matching nodes."""
        review = _make_review(findings=[_make_finding(title="SQL injection in query builder")])
        store.store_review(review)
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
        store.store_review(review)
        results = store.search_nodes("bug", k=3)
        assert len(results) <= 3


# --- Resolution queries (lifecycle) ---


class TestResolutionQueries:
    """Finding lifecycle: prior findings, status updates."""

    def test_get_prior_findings_returns_open_findings(self, store: GrippyStore) -> None:
        """get_prior_findings returns findings with status='open'."""
        review = _make_review()
        store.store_review(review, session_id="pr-1")
        findings = store.get_prior_findings(session_id="pr-1")
        assert len(findings) > 0
        for f in findings:
            assert f["status"] == "open"

    def test_get_prior_findings_empty_when_no_reviews(self, store: GrippyStore) -> None:
        """No stored reviews -> empty list."""
        findings = store.get_prior_findings(session_id="pr-nonexistent")
        assert findings == []

    def test_get_prior_findings_scoped_by_session(self, store: GrippyStore) -> None:
        """Prior findings are scoped to session_id (PR)."""
        review_r1 = _make_review(
            title="feat: auth",
            timestamp="2026-02-26T12:00:00Z",
            findings=[_make_finding(title="SQL injection", file="auth.py")],
        )
        store.store_review(review_r1, session_id="pr-5")

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
        store.store_review(review_pr5, session_id="pr-5")
        store.store_review(review_pr6, session_id="pr-6")

        prior_5 = store.get_prior_findings(session_id="pr-5")
        prior_6 = store.get_prior_findings(session_id="pr-6")
        assert all(f["title"] == "Bug in PR 5" for f in prior_5)
        assert all(f["title"] == "Bug in PR 6" for f in prior_6)

    def test_update_finding_status(self, store: GrippyStore) -> None:
        """update_finding_status updates both the status column and JSON data."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT id FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        nid = cur.fetchone()["id"]

        store.update_finding_status(nid, "resolved")

        # Check real column
        cur.execute("SELECT status FROM nodes WHERE id = ?", (nid,))
        assert cur.fetchone()["status"] == "resolved"

        # Check JSON data sync
        cur.execute("SELECT data FROM nodes WHERE id = ?", (nid,))
        data = json.loads(cur.fetchone()["data"])
        assert data["status"] == "resolved"

    def test_update_finding_status_with_enum(self, store: GrippyStore) -> None:
        """update_finding_status accepts FindingStatus enum."""
        review = _make_review()
        store.store_review(review)
        cur = store._conn.cursor()
        cur.execute("SELECT id FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        nid = cur.fetchone()["id"]

        store.update_finding_status(nid, FindingStatus.RESOLVED)

        cur.execute("SELECT status FROM nodes WHERE id = ?", (nid,))
        assert cur.fetchone()["status"] == "resolved"

    def test_resolved_findings_excluded_from_prior(self, store: GrippyStore) -> None:
        """Resolved findings are not returned by get_prior_findings."""
        review = _make_review()
        store.store_review(review, session_id="pr-1")
        cur = store._conn.cursor()
        cur.execute("SELECT id FROM nodes WHERE type = ?", (NodeType.FINDING.value,))
        nid = cur.fetchone()["id"]

        store.update_finding_status(nid, FindingStatus.RESOLVED)

        prior = store.get_prior_findings(session_id="pr-1")
        assert len(prior) == 0


# --- Batch embedding protocol ---


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

        with patch.object(
            embedder, "get_embedding_batch", wraps=embedder.get_embedding_batch
        ) as mock_batch:
            store.store_review(review)
            mock_batch.assert_called_once()

    def test_single_embedder_fallback(self, tmp_path: Path) -> None:
        """Embedder without get_embedding_batch falls back to individual calls."""
        embedder = _FakeEmbedder()
        store = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=embedder,
        )
        review = _make_review()

        with patch.object(embedder, "get_embedding", wraps=embedder.get_embedding) as mock_single:
            store.store_review(review)
            assert mock_single.call_count > 0

    def test_batch_embedder_stores_correct_vectors(self, tmp_path: Path) -> None:
        """Batch result vectors are correctly associated with their records."""
        embedder = _FakeBatchEmbedder()
        store = GrippyStore(
            graph_db_path=tmp_path / "test.db",
            lance_dir=tmp_path / "lance",
            embedder=embedder,
        )
        review = _make_review()
        store.store_review(review)

        nodes = store.get_all_nodes()
        assert len(nodes) > 0
        for node in nodes:
            assert "vector" in node
            assert len(node["vector"]) == EMBED_DIM
