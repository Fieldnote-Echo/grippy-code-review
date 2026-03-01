# SPDX-License-Identifier: MIT
"""Graph-aware persistence — SQLite for nodes/edges, LanceDB for vectors.

Stores codebase knowledge data (not finding lifecycle — that's GitHub's job):
- SQLite: nodes table + edges junction table with composite indexes
- LanceDB: node records with vector embeddings for semantic search

Uses the navi-chat SQLite graph pattern: deterministic node IDs, UPSERT
for idempotent writes, single-pass SQL joins for graph traversals.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from grippy.graph import NodeType

# --- Node ID validation ---
# Matches the deterministic format produced by _record_id(): "TYPE:hexhash"
_NODE_ID_RE = re.compile(r"^[A-Z0-9_]+:[a-f0-9]{12}$")

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


# --- Deterministic node IDs ---


def _record_id(node_type: NodeType | str, *parts: str) -> str:
    """Deterministic node ID: '{TYPE}:{sha256[:12]}'.

    Format preserved from the original ``node_id()`` — the node type is
    included in the hash input so different types with the same parts
    produce different digests.
    """
    type_str = node_type.value if isinstance(node_type, NodeType) else node_type
    raw = ":".join([type_str, *parts])
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"{type_str.upper()}:{digest}"


# --- SQLite schema ---

_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
]

_NODES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    label       TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}',
    session_id  TEXT,
    status      TEXT,
    fingerprint TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT
)
"""

_EDGES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS edges (
    source       TEXT NOT NULL,
    target       TEXT NOT NULL,
    relationship TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 1.0,
    properties   TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    UNIQUE (source, relationship, target),
    FOREIGN KEY (source) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target) REFERENCES nodes(id) ON DELETE CASCADE
)
"""

_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_nodes_type_label   ON nodes(type, label)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_type_session ON nodes(type, session_id)",
    "CREATE INDEX IF NOT EXISTS idx_edges_source_rel ON edges(source, relationship)",
    "CREATE INDEX IF NOT EXISTS idx_edges_target_rel ON edges(target, relationship)",
]


class GrippyStore:
    """Graph-aware persistence — SQLite for nodes/edges, LanceDB for vectors."""

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

        # Init LanceDB (lazy import — lancedb is an optional dependency)
        import lancedb  # type: ignore[import-untyped]

        self._lance_dir.mkdir(parents=True, exist_ok=True)
        self._lance_db = lancedb.connect(str(self._lance_dir))
        self._nodes_table: Any = None

    def _init_sqlite(self) -> None:
        cur = self._conn.cursor()
        for pragma in _PRAGMAS:
            cur.execute(pragma)
        self._migrate_v1_schema(cur)
        cur.execute(_NODES_TABLE_SQL)
        cur.execute(_EDGES_TABLE_SQL)
        self._add_updated_at_column(cur)
        for idx_sql in _INDEXES_SQL:
            cur.execute(idx_sql)
        self._conn.commit()

    @staticmethod
    def _migrate_v1_schema(cur: sqlite3.Cursor) -> None:
        """Drop incompatible v1 tables if present.

        The v1 schema had edges(source_id, edge_type, target_id, metadata)
        and a node_meta table.  ``CREATE TABLE IF NOT EXISTS`` would silently
        keep the old columns, causing INSERT failures at runtime.  Since
        graph data is ephemeral per-PR (reconstructed each review round),
        dropping and recreating is safe.
        """
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges'")
        if cur.fetchone() is not None:
            cur.execute("PRAGMA table_info(edges)")
            columns = {row[1] for row in cur.fetchall()}
            if "source_id" in columns:
                # v1 edges — always drop
                cur.execute("DROP TABLE IF EXISTS edges")
                cur.execute("DROP TABLE IF EXISTS node_meta")
                # Only drop nodes if it also has v1 schema (no session_id column)
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'")
                if cur.fetchone() is not None:
                    cur.execute("PRAGMA table_info(nodes)")
                    node_columns = {row[1] for row in cur.fetchall()}
                    if "session_id" not in node_columns:
                        cur.execute("DROP TABLE IF EXISTS nodes")

    @staticmethod
    def _add_updated_at_column(cur: sqlite3.Cursor) -> None:
        """Add updated_at column if missing (backfill from created_at)."""
        cur.execute("PRAGMA table_info(nodes)")
        columns = {row[1] for row in cur.fetchall()}
        if "updated_at" not in columns:
            cur.execute("ALTER TABLE nodes ADD COLUMN updated_at TEXT")
            cur.execute("UPDATE nodes SET updated_at = created_at WHERE updated_at IS NULL")

    def _ensure_nodes_table(self) -> Any:
        """Open existing nodes table if present."""
        if self._nodes_table is not None:
            return self._nodes_table
        try:
            self._nodes_table = self._lance_db.open_table("nodes")
        except (FileNotFoundError, ValueError):
            # FileNotFoundError: table directory doesn't exist on disk
            # ValueError: LanceDB metadata references a missing/corrupt table
            pass
        return self._nodes_table

    # --- Write ops ---

    def _compute_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Compute embedding vectors for all texts (pure, no side effects)."""
        if not texts:
            return []
        if isinstance(self._embedder, BatchEmbedder):
            return self._embedder.get_embedding_batch(texts)
        return [self._embedder.get_embedding(t) for t in texts]

    def _upsert_sqlite(
        self,
        nodes: list[dict[str, Any]],
        edges: list[tuple[str, str, str, str]],
    ) -> None:
        """UPSERT all nodes and edges in a single SQLite transaction."""
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            for node in nodes:
                cur.execute(
                    """INSERT INTO nodes
                    (id, type, label, data, session_id, status, fingerprint, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        label = excluded.label,
                        data = excluded.data,
                        session_id = excluded.session_id,
                        status = excluded.status,
                        fingerprint = excluded.fingerprint,
                        created_at = nodes.created_at,
                        updated_at = excluded.updated_at""",
                    (
                        node["id"],
                        node["type"],
                        node["label"],
                        node["data"],
                        node["session_id"],
                        node["status"],
                        node["fingerprint"],
                        node["created_at"],
                        node["updated_at"],
                    ),
                )
            for source, target, relationship, properties in edges:
                cur.execute(
                    """INSERT INTO edges (source, target, relationship, properties, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(source, relationship, target) DO UPDATE SET
                        properties = excluded.properties""",
                    (source, target, relationship, properties),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _upsert_vectors(
        self,
        nodes: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> None:
        """Upsert node vectors into LanceDB."""
        if not nodes:
            return

        records: list[dict[str, Any]] = []
        for node, vec in zip(nodes, vectors, strict=True):
            records.append(
                {
                    "node_id": node["id"],
                    "node_type": node["type"],
                    "label": node["label"],
                    "text": f"{node['type']}: {node['label']}",
                    "review_id": "",
                    "vector": vec,
                }
            )

        table = self._ensure_nodes_table()
        if table is None:
            self._nodes_table = self._lance_db.create_table("nodes", data=records)
        else:
            arrow_tbl = table.to_arrow()
            existing = dict(
                zip(
                    arrow_tbl.column("node_id").to_pylist(),
                    arrow_tbl.column("text").to_pylist(),
                    strict=True,
                )
            )
            stale_ids = {
                r["node_id"]
                for r in records
                if r["node_id"] in existing and existing[r["node_id"]] != r["text"]
            }
            if stale_ids:
                bad_ids = {nid for nid in stale_ids if not _NODE_ID_RE.match(nid)}
                if bad_ids:
                    raise ValueError(
                        f"Invalid node_id(s) blocked before LanceDB delete: {sorted(bad_ids)}"
                    )
                id_list = ", ".join(f"'{nid}'" for nid in stale_ids)
                table.delete(f"node_id IN ({id_list})")
            upsert_records = [
                r for r in records if r["node_id"] not in existing or r["node_id"] in stale_ids
            ]
            if upsert_records:
                table.add(upsert_records)

    # --- Node queries ---

    def get_all_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes from LanceDB."""
        table = self._ensure_nodes_table()
        if table is None:
            return []
        return _arrow_table_to_dicts(table.to_arrow())

    # --- Vector search ---

    def search_nodes(self, query: str, *, k: int = 5) -> list[dict[str, Any]]:
        """Semantic search over stored nodes using LanceDB vectors."""
        table = self._ensure_nodes_table()
        if table is None:
            return []
        query_vec = self._embedder.get_embedding(query)
        arrow_result = table.search(query_vec).limit(k).to_arrow()
        return _arrow_table_to_dicts(arrow_result)
