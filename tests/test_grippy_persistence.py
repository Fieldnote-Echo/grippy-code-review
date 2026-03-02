# SPDX-License-Identifier: MIT
"""Tests for Grippy persistence layer — SQLite graph + LanceDB vectors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from grippy.graph import NodeType
from grippy.persistence import _NODE_ID_RE, GrippyStore, _record_id

EMBED_DIM = 8


class _FakeEmbedder:
    """Deterministic fake embedder — hash-based, fixed dimension."""

    def get_embedding(self, text: str) -> list[float]:
        import hashlib

        h = hashlib.sha256(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:EMBED_DIM]]


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
        id1 = _record_id(NodeType.FILE, "src/app.py")
        id2 = _record_id(NodeType.FILE, "src/app.py")
        assert id1 == id2

    def test_includes_type_prefix(self) -> None:
        """IDs are prefixed with node type."""
        nid = _record_id(NodeType.FILE, "src/app.py")
        assert nid.startswith("FILE:")

    def test_different_inputs_different_ids(self) -> None:
        """Different inputs produce different IDs."""
        id1 = _record_id(NodeType.FILE, "a.py")
        id2 = _record_id(NodeType.FILE, "b.py")
        assert id1 != id2

    def test_accepts_string_type(self) -> None:
        """Accepts string node type (not just enum)."""
        nid = _record_id("CUSTOM", "some_value")
        assert nid.startswith("CUSTOM:")

    def test_different_types_same_parts_different_digest(self) -> None:
        """Different node types with the same parts produce different hash digests."""
        file_id = _record_id(NodeType.FILE, "src/app.py")
        rule_id = _record_id(NodeType.RULE, "src/app.py")
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
            "updated_at",
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

    def test_v1_migration_preserves_v2_nodes(self, tmp_path: Path) -> None:
        """v1 edges + v2 nodes (mixed state): migration drops edges but preserves nodes."""
        db_path = tmp_path / "grippy-graph.db"

        conn = sqlite3.connect(str(db_path))
        # v1 edges
        conn.execute(
            "CREATE TABLE edges (source_id TEXT, edge_type TEXT, target_id TEXT, metadata TEXT)"
        )
        # v2 nodes (has session_id column)
        conn.execute(
            "CREATE TABLE nodes ("
            "id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, "
            "data TEXT NOT NULL DEFAULT '{}', session_id TEXT, status TEXT, "
            "fingerprint TEXT, created_at TEXT NOT NULL, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO nodes (id, type, label, created_at) "
            "VALUES ('n1', 'file', 'test', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        store = GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )

        # v1 edges should be gone, v2 nodes should be preserved
        cur = store._conn.cursor()
        cur.execute("PRAGMA table_info(edges)")
        edge_cols = {row[1] for row in cur.fetchall()}
        assert "source" in edge_cols  # v2 schema
        assert "source_id" not in edge_cols

        cur.execute("SELECT COUNT(*) FROM nodes")
        assert cur.fetchone()[0] == 1  # preserved

    def test_v2_schema_not_dropped(self, tmp_path: Path) -> None:
        """Opening a DB that already has v2 schema preserves existing data."""
        db_path = tmp_path / "grippy-graph.db"

        # Create store, insert a node manually, close
        store1 = GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )
        cur = store1._conn.cursor()
        cur.execute(
            "INSERT INTO nodes (id, type, label, data, created_at) "
            "VALUES ('n1', 'FILE', 'test.py', '{}', '2026-01-01')"
        )
        store1._conn.commit()
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


# --- UPSERT ops ---


class TestUpsertSqlite:
    """Direct tests for _upsert_sqlite write operations."""

    def test_upsert_inserts_nodes(self, store: GrippyStore) -> None:
        """_upsert_sqlite inserts new nodes."""
        nodes = [
            {
                "id": "FILE:abc123",
                "type": "FILE",
                "label": "src/app.py",
                "data": "{}",
                "session_id": "pr-1",
                "status": None,
                "fingerprint": None,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]
        store._upsert_sqlite(nodes, [])
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM nodes")
        assert cur.fetchone()[0] == 1

    def test_upsert_inserts_edges(self, store: GrippyStore) -> None:
        """_upsert_sqlite inserts edges."""
        nodes = [
            {
                "id": "FILE:aaa",
                "type": "FILE",
                "label": "a.py",
                "data": "{}",
                "session_id": "",
                "status": None,
                "fingerprint": None,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            },
            {
                "id": "REVIEW:bbb",
                "type": "REVIEW",
                "label": "Review",
                "data": "{}",
                "session_id": "",
                "status": None,
                "fingerprint": None,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            },
        ]
        edges = [("FILE:aaa", "REVIEW:bbb", "FOUND_IN", "{}")]
        store._upsert_sqlite(nodes, edges)
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM edges")
        assert cur.fetchone()[0] == 1

    def test_upsert_preserves_created_at(self, store: GrippyStore) -> None:
        """Re-upserting a node preserves original created_at."""
        node_v1 = {
            "id": "FILE:abc",
            "type": "FILE",
            "label": "old.py",
            "data": "{}",
            "session_id": "",
            "status": None,
            "fingerprint": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
        store._upsert_sqlite([node_v1], [])

        node_v2 = {
            **node_v1,
            "label": "new.py",
            "created_at": "2026-02-01",
            "updated_at": "2026-02-01",
        }
        store._upsert_sqlite([node_v2], [])

        cur = store._conn.cursor()
        cur.execute("SELECT created_at, updated_at FROM nodes WHERE id = 'FILE:abc'")
        row = cur.fetchone()
        assert row["created_at"] == "2026-01-01"
        assert row["updated_at"] == "2026-02-01"


# --- Vector search ---


class TestVectorSearch:
    def test_search_empty_store_returns_empty(self, store: GrippyStore) -> None:
        """Search on empty store returns empty list."""
        results = store.search_nodes("anything", k=5)
        assert results == []

    def test_get_all_nodes_empty(self, store: GrippyStore) -> None:
        """get_all_nodes on empty store returns empty list."""
        nodes = store.get_all_nodes()
        assert nodes == []


# --- Node ID validation ---


class TestNodeIdValidation:
    """Validate _NODE_ID_RE and the guard in _upsert_vectors."""

    @pytest.mark.parametrize(
        "node_id",
        [
            "FILE:abcdef012345",
            "REVIEW:0123456789ab",
            "PATTERN:aabbccddeeff",
            "FILE_V2:abcdef012345",
        ],
    )
    def test_valid_ids_match(self, node_id: str) -> None:
        """Well-formed node IDs pass the regex."""
        assert _NODE_ID_RE.match(node_id)

    @pytest.mark.parametrize(
        "node_id",
        [
            "FILE:abc' OR 1=1 --",
            "'; DROP TABLE nodes; --",
            "FILE:abc",
            "file:abcdef012345",
            "FILE:ABCDEF012345",
            "",
        ],
    )
    def test_invalid_ids_rejected(self, node_id: str) -> None:
        """Malformed node IDs do NOT pass the regex."""
        assert not _NODE_ID_RE.match(node_id)

    def test_upsert_vectors_rejects_malformed_stale_id(self, store: GrippyStore) -> None:
        """_upsert_vectors raises ValueError when a stale node_id fails validation.

        Scenario: a poisoned node_id is already in LanceDB (first insert bypasses
        the delete path). On the second call with changed text, the id becomes
        stale and must pass validation before reaching table.delete().
        """
        poisoned_id = "FILE:abc' OR 1=1 --"
        fake_vec = [0.0] * EMBED_DIM

        # First call — creates the LanceDB table (no delete path triggered)
        nodes_v1 = [{"id": poisoned_id, "type": "FILE", "label": "old.py", "data": "{}"}]
        store._upsert_vectors(nodes_v1, [fake_vec])

        # Second call — same id, different label → triggers stale-id delete path
        nodes_v2 = [{"id": poisoned_id, "type": "FILE", "label": "new.py", "data": "{}"}]
        with pytest.raises(ValueError, match="Invalid node_id"):
            store._upsert_vectors(nodes_v2, [fake_vec])

    def test_upsert_vectors_replaces_stale_records(self, store: GrippyStore) -> None:
        """Valid stale node_id triggers delete + re-insert with updated text.

        This covers the happy path at persistence.py:301-307 — when a node's
        label changes between calls, the old LanceDB record is deleted and
        a new one with the updated embedding is inserted.
        """
        valid_id = "FILE:abcdef012345"
        fake_vec = [0.1] * EMBED_DIM

        # First call — creates the table with initial label
        nodes_v1 = [{"id": valid_id, "type": "FILE", "label": "old_label.py", "data": "{}"}]
        store._upsert_vectors(nodes_v1, [fake_vec])

        # Verify initial state
        table = store._ensure_nodes_table()
        arrow = table.to_arrow()
        texts_v1 = arrow.column("text").to_pylist()
        assert len(texts_v1) == 1
        assert "old_label" in texts_v1[0]

        # Second call — same id, different label → stale delete + re-insert
        new_vec = [0.9] * EMBED_DIM
        nodes_v2 = [{"id": valid_id, "type": "FILE", "label": "new_label.py", "data": "{}"}]
        store._upsert_vectors(nodes_v2, [new_vec])

        # Re-fetch table handle after mutation to avoid testing handle caching
        table = store._ensure_nodes_table()
        arrow = table.to_arrow()
        node_ids = arrow.column("node_id").to_pylist()
        texts_v2 = arrow.column("text").to_pylist()
        assert len(node_ids) == 1
        assert node_ids[0] == valid_id
        assert "new_label" in texts_v2[0]
        assert "old_label" not in texts_v2[0]

    def test_upsert_vectors_skips_unchanged_records(self, store: GrippyStore) -> None:
        """Records with same node_id and same text are not re-inserted."""
        valid_id = "FILE:abcdef012345"
        fake_vec = [0.5] * EMBED_DIM

        nodes = [{"id": valid_id, "type": "FILE", "label": "same.py", "data": "{}"}]
        store._upsert_vectors(nodes, [fake_vec])
        store._upsert_vectors(nodes, [fake_vec])

        table = store._ensure_nodes_table()
        arrow = table.to_arrow()
        assert len(arrow.column("node_id").to_pylist()) == 1


# --- Populated store queries (get_all_nodes, search_nodes) ---


class TestPopulatedStoreQueries:
    """Tests for get_all_nodes and search_nodes on a non-empty store."""

    def _insert_node(self, store: GrippyStore) -> None:
        """Insert a node into both SQLite and LanceDB."""
        nodes = [
            {
                "id": "FILE:abcdef012345",
                "type": "FILE",
                "label": "src/app.py",
                "data": '{"path": "src/app.py"}',
                "session_id": "pr-1",
                "status": None,
                "fingerprint": None,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]
        store._upsert_sqlite(nodes, [])
        vecs = store._compute_embeddings(["FILE src/app.py"])
        store._upsert_vectors(nodes, vecs)

    def test_get_all_nodes_returns_populated_results(self, store: GrippyStore) -> None:
        """get_all_nodes returns records after inserting a node."""
        self._insert_node(store)
        nodes = store.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0]["node_id"] == "FILE:abcdef012345"

    def test_search_nodes_returns_results(self, store: GrippyStore) -> None:
        """search_nodes returns results for a non-empty store."""
        self._insert_node(store)
        results = store.search_nodes("app.py", k=5)
        assert len(results) >= 1


# --- BatchEmbedder fast path ---


class _FakeBatchEmbedder:
    """Embedder that supports both single and batch operations."""

    def get_embedding(self, text: str) -> list[float]:
        import hashlib

        h = hashlib.sha256(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:EMBED_DIM]]

    def get_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.get_embedding(t) for t in texts]


class TestBatchEmbedder:
    """Tests for _compute_embeddings batch path."""

    def test_batch_embedder_used_when_available(self, tmp_path: Path) -> None:
        """BatchEmbedder.get_embedding_batch is called instead of per-item."""
        store = GrippyStore(
            graph_db_path=tmp_path / "grippy-graph.db",
            lance_dir=tmp_path / "lance",
            embedder=_FakeBatchEmbedder(),
        )
        result = store._compute_embeddings(["hello", "world"])
        assert len(result) == 2
        assert len(result[0]) == EMBED_DIM

    def test_compute_embeddings_empty_list(self, store: GrippyStore) -> None:
        """Empty list returns empty list without calling embedder."""
        result = store._compute_embeddings([])
        assert result == []


# --- Upsert vectors empty early return ---


class TestUpsertVectorsEdgeCases:
    """Edge cases for _upsert_vectors."""

    def test_empty_nodes_returns_early(self, store: GrippyStore) -> None:
        """Calling _upsert_vectors with empty lists does nothing."""
        store._upsert_vectors([], [])
        # _ensure_nodes_table only opens an existing table (never creates) —
        # None confirms no table was created by the empty upsert above.
        assert store._ensure_nodes_table() is None


# --- SQLite rollback on error ---


class TestSqliteRollback:
    """Verify _upsert_sqlite rolls back on failure."""

    def test_rollback_on_bad_node(self, store: GrippyStore) -> None:
        """Malformed node triggers rollback — no partial writes."""
        good_node = {
            "id": "FILE:aaa111222333",
            "type": "FILE",
            "label": "good.py",
            "data": "{}",
            "session_id": "pr-1",
            "status": None,
            "fingerprint": None,
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
        # Bad edge with wrong number of elements will cause sqlite error
        bad_edge = ("src", "tgt", "REL")  # Missing 4th element (properties)

        with pytest.raises(ValueError):
            store._upsert_sqlite([good_node], [bad_edge])  # type: ignore[list-item]

        # Verify rollback: no nodes inserted
        cur = store._conn.cursor()
        cur.execute("SELECT COUNT(*) FROM nodes")
        assert cur.fetchone()[0] == 0


# --- updated_at migration ---


class TestUpdatedAtMigration:
    """Verify _add_updated_at_column adds the column and backfills."""

    def test_adds_updated_at_to_old_schema(self, tmp_path: Path) -> None:
        """DB missing updated_at column gets it added + backfilled from created_at."""
        db_path = tmp_path / "grippy-graph.db"

        # Create a DB with the node table but WITHOUT updated_at
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE nodes ("
            "id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, "
            "data TEXT NOT NULL DEFAULT '{}', session_id TEXT, status TEXT, "
            "fingerprint TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO nodes (id, type, label, created_at) "
            "VALUES ('n1', 'FILE', 'test.py', '2026-01-15T10:00:00Z')"
        )
        # Need edges table too for the store to open
        conn.execute(
            "CREATE TABLE edges ("
            "source TEXT NOT NULL, target TEXT NOT NULL, relationship TEXT NOT NULL, "
            "weight REAL DEFAULT 1.0, properties TEXT DEFAULT '{}', "
            "created_at TEXT NOT NULL, "
            "PRIMARY KEY (source, relationship, target))"
        )
        conn.commit()
        conn.close()

        # Open with GrippyStore — should trigger migration
        store = GrippyStore(
            graph_db_path=db_path,
            lance_dir=tmp_path / "lance",
            embedder=_FakeEmbedder(),
        )

        # Verify column exists and was backfilled
        cur = store._conn.cursor()
        cur.execute("PRAGMA table_info(nodes)")
        columns = {row["name"] for row in cur.fetchall()}
        assert "updated_at" in columns

        cur.execute("SELECT updated_at FROM nodes WHERE id = 'n1'")
        updated_at = cur.fetchone()[0]
        assert updated_at == "2026-01-15T10:00:00Z"
