"""Graph-aware persistence — SQLite for edges, LanceDB for vectors.

Stores ReviewGraph data in two backends:
- SQLite: edge junction table (source_id, edge_type, target_id, metadata)
- LanceDB: node records with vector embeddings for semantic search

Both are embedded/file-based. No servers. Designed to migrate cleanly to
SurrealDB: edges become graph relations, nodes become records.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import lancedb  # type: ignore[import-untyped]

from grippy.graph import EdgeType, FindingStatus, NodeType, ReviewGraph

# --- Types ---


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedders — compatible with Agno's OpenAIEmbedder."""

    def get_embedding(self, text: str) -> list[float]: ...


@runtime_checkable
class BatchEmbedder(Protocol):
    """Protocol for embedders that support batch embedding."""

    def get_embedding(self, text: str) -> list[float]: ...
    def get_embedding_batch(self, texts: list[str]) -> list[list[float]]: ...


def _arrow_table_to_dicts(table: Any) -> list[dict[str, Any]]:
    """Convert a pyarrow Table to a list of dicts without pandas."""
    columns = table.column_names
    arrays = {col: table.column(col).to_pylist() for col in columns}
    n_rows = table.num_rows
    return [{col: arrays[col][i] for col in columns} for i in range(n_rows)]


# --- SQLite schema ---

_EDGE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS edges (
    source_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    UNIQUE(source_id, edge_type, target_id)
)
"""

_EDGE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type)",
]

_NODE_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS node_meta (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL,
    label TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    review_id TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL
)
"""

_MIGRATIONS = [
    # v1.1: add session_id for PR-scoped finding lifecycle
    "ALTER TABLE node_meta ADD COLUMN session_id TEXT",
]


class GrippyStore:
    """Graph-aware persistence — SQLite for edges, LanceDB for vectors."""

    def __init__(
        self,
        *,
        graph_db_path: Path | str,
        lance_dir: Path | str,
        embedder: Embedder,
    ) -> None:
        self._graph_db_path = Path(graph_db_path)
        self._lance_dir = Path(lance_dir)
        self._embedder = embedder

        # Init SQLite
        self._graph_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._graph_db_path))
        self._conn.row_factory = sqlite3.Row
        self._init_sqlite()

        # Init LanceDB
        self._lance_dir.mkdir(parents=True, exist_ok=True)
        self._lance_db = lancedb.connect(str(self._lance_dir))
        self._nodes_table: lancedb.table.Table | None = None

    def _init_sqlite(self) -> None:
        cur = self._conn.cursor()
        cur.execute(_EDGE_TABLE_SQL)
        for idx_sql in _EDGE_INDEXES_SQL:
            cur.execute(idx_sql)
        cur.execute(_NODE_META_TABLE_SQL)
        for migration in _MIGRATIONS:
            try:
                cur.execute(migration)
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if "already exists" in msg or "duplicate column" in msg:
                    pass  # Column already present — skip
                else:
                    raise  # Real error — propagate
        self._conn.commit()

    def _ensure_nodes_table(self) -> lancedb.table.Table | None:
        """Open existing nodes table if present."""
        if self._nodes_table is not None:
            return self._nodes_table
        existing_tables = self._lance_db.list_tables()
        if "nodes" in existing_tables:
            self._nodes_table = self._lance_db.open_table("nodes")
        return self._nodes_table

    # --- Store ---

    def store_review(self, graph: ReviewGraph, *, session_id: str = "") -> None:
        """Persist a ReviewGraph — edges to SQLite, nodes to LanceDB."""
        self._store_edges(graph, session_id=session_id)
        self._store_nodes(graph)

    def _store_edges(self, graph: ReviewGraph, *, session_id: str = "") -> None:
        cur = self._conn.cursor()
        for node in graph.nodes:
            # Store node metadata
            cur.execute(
                "INSERT OR IGNORE INTO node_meta "
                "(node_id, node_type, label, properties, review_id, session_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    node.id,
                    node.type.value,
                    node.label,
                    json.dumps(node.properties),
                    node.source_review_id,
                    session_id,
                    node.created_at,
                ),
            )
            for edge in node.edges:
                cur.execute(
                    "INSERT OR IGNORE INTO edges "
                    "(source_id, edge_type, target_id, metadata) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        node.id,
                        edge.type.value,
                        edge.target_id,
                        json.dumps(edge.metadata),
                    ),
                )
        self._conn.commit()

    def _store_nodes(self, graph: ReviewGraph) -> None:
        """Embed and store nodes in LanceDB for vector search."""
        records: list[dict[str, Any]] = []
        texts: list[str] = []
        for node in graph.nodes:
            text = f"{node.type.value}: {node.label}"
            if node.properties:
                props_str = " ".join(f"{k}={v}" for k, v in node.properties.items())
                text = f"{text} {props_str}"
            texts.append(text)
            records.append(
                {
                    "node_id": node.id,
                    "node_type": node.type.value,
                    "label": node.label,
                    "text": text,
                    "review_id": node.source_review_id or "",
                }
            )

        if not records:
            return

        if isinstance(self._embedder, BatchEmbedder):
            vectors = self._embedder.get_embedding_batch(texts)
        else:
            vectors = [self._embedder.get_embedding(t) for t in texts]
        for rec, vec in zip(records, vectors, strict=True):
            rec["vector"] = vec

        table = self._ensure_nodes_table()
        if table is None:
            # First time — create table with initial records
            self._nodes_table = self._lance_db.create_table("nodes", data=records)
        else:
            # Table exists — add only records with new IDs
            arrow_tbl = table.to_arrow()
            existing_ids = set(arrow_tbl.column("node_id").to_pylist())
            new_records = [r for r in records if r["node_id"] not in existing_ids]
            if new_records:
                table.add(new_records)

    # --- Edge queries ---

    def get_all_edges(self) -> list[dict[str, Any]]:
        """Return all edges as dicts."""
        cur = self._conn.cursor()
        cur.execute("SELECT source_id, edge_type, target_id, metadata FROM edges")
        return [dict(row) for row in cur.fetchall()]

    def get_edges_by_source(self, source_id: str) -> list[dict[str, Any]]:
        """Return edges originating from a specific node."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT source_id, edge_type, target_id, metadata FROM edges WHERE source_id = ?",
            (source_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_edges_by_type(self, edge_type: EdgeType) -> list[dict[str, Any]]:
        """Return edges of a specific type."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT source_id, edge_type, target_id, metadata FROM edges WHERE edge_type = ?",
            (edge_type.value,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_edges_by_target(self, target_id: str) -> list[dict[str, Any]]:
        """Return edges pointing to a specific node."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT source_id, edge_type, target_id, metadata FROM edges WHERE target_id = ?",
            (target_id,),
        )
        return [dict(row) for row in cur.fetchall()]

    # --- Node queries ---

    def get_all_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes from LanceDB."""
        table = self._ensure_nodes_table()
        if table is None:
            return []
        return _arrow_table_to_dicts(table.to_arrow())

    # --- High-level queries ---

    def get_author_tendencies(self, author: str) -> list[dict[str, Any]]:
        """Get finding patterns associated with a specific author.

        Walks: AUTHOR node → (via review_id) → FINDING nodes in same review.
        Returns finding properties (title, severity, category, etc).
        """
        cur = self._conn.cursor()
        # Find the author's node
        cur.execute(
            "SELECT node_id FROM node_meta WHERE node_type = ? AND label = ?",
            (NodeType.AUTHOR.value, author),
        )
        author_rows = cur.fetchall()
        if not author_rows:
            return []

        # Get review IDs that this author is associated with
        review_ids = set()
        for row in author_rows:
            cur.execute(
                "SELECT review_id FROM node_meta WHERE node_id = ?",
                (row["node_id"],),
            )
            meta = cur.fetchone()
            if meta and meta["review_id"]:
                review_ids.add(meta["review_id"])

        if not review_ids:
            return []

        # Get findings from those reviews
        placeholders = ",".join("?" for _ in review_ids)
        cur.execute(
            f"SELECT label, properties FROM node_meta "
            f"WHERE node_type = ? AND review_id IN ({placeholders})",
            (NodeType.FINDING.value, *review_ids),
        )
        results = []
        for row in cur.fetchall():
            props = json.loads(row["properties"])
            props["title"] = row["label"]
            results.append(props)
        return results

    def get_patterns_for_file(self, file_path: str) -> list[dict[str, Any]]:
        """Get findings associated with a specific file.

        Walks: FILE node ← FOUND_IN ← FINDING nodes.
        """
        cur = self._conn.cursor()
        # Find the file's node ID
        cur.execute(
            "SELECT node_id FROM node_meta WHERE node_type = ? AND label = ?",
            (NodeType.FILE.value, file_path),
        )
        file_row = cur.fetchone()
        if not file_row:
            return []

        # Find FOUND_IN edges pointing to this file
        cur.execute(
            "SELECT source_id FROM edges WHERE edge_type = ? AND target_id = ?",
            (EdgeType.FOUND_IN.value, file_row["node_id"]),
        )
        finding_ids = [row["source_id"] for row in cur.fetchall()]
        if not finding_ids:
            return []

        # Get finding details
        placeholders = ",".join("?" for _ in finding_ids)
        cur.execute(
            f"SELECT label, properties FROM node_meta WHERE node_id IN ({placeholders})",
            finding_ids,
        )
        results = []
        for row in cur.fetchall():
            props = json.loads(row["properties"])
            props["title"] = row["label"]
            results.append(props)
        return results

    # --- Vector search ---

    def search_nodes(self, query: str, *, k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over stored nodes using LanceDB vectors."""
        table = self._ensure_nodes_table()
        if table is None:
            return []
        query_vec = self._embedder.get_embedding(query)
        arrow_result = table.search(query_vec).limit(k).to_arrow()
        return _arrow_table_to_dicts(arrow_result)

    # --- Resolution queries ---

    def get_prior_findings(self, *, session_id: str) -> list[dict[str, Any]]:
        """Get open findings for a PR session.

        Call BEFORE store_review() so only prior round findings are returned.
        """
        cur = self._conn.cursor()
        cur.execute(
            "SELECT node_id, label, properties FROM node_meta "
            "WHERE node_type = ? AND session_id = ?",
            (NodeType.FINDING.value, session_id),
        )
        results = []
        for row in cur.fetchall():
            props = json.loads(row["properties"])
            if props.get("status") == "open":
                props["node_id"] = row["node_id"]
                props["title"] = row["label"]
                results.append(props)
        return results

    def update_finding_status(self, node_id: str, status: str | FindingStatus) -> None:
        """Update a finding's status in node_meta properties."""
        cur = self._conn.cursor()
        cur.execute("SELECT properties FROM node_meta WHERE node_id = ?", (node_id,))
        row = cur.fetchone()
        if row:
            props = json.loads(row["properties"])
            props["status"] = status
            cur.execute(
                "UPDATE node_meta SET properties = ? WHERE node_id = ?",
                (json.dumps(props), node_id),
            )
            self._conn.commit()
