"""Graph-aware persistence — SQLite for nodes/edges, LanceDB for vectors.

Stores review data directly from GrippyReview (no intermediate graph model):
- SQLite: nodes table + edges junction table with composite indexes
- LanceDB: node records with vector embeddings for semantic search

Uses the navi-chat SQLite graph pattern: deterministic node IDs, UPSERT
for idempotent writes, single-pass SQL joins for graph traversals.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import lancedb  # type: ignore[import-untyped]

from grippy.graph import EdgeType, FindingStatus, NodeType
from grippy.schema import GrippyReview

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
    created_at  TEXT NOT NULL
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

        # Init LanceDB
        self._lance_dir.mkdir(parents=True, exist_ok=True)
        self._lance_db = lancedb.connect(str(self._lance_dir))
        self._nodes_table: lancedb.table.Table | None = None

    def _init_sqlite(self) -> None:
        cur = self._conn.cursor()
        for pragma in _PRAGMAS:
            cur.execute(pragma)
        self._migrate_v1_schema(cur)
        cur.execute(_NODES_TABLE_SQL)
        cur.execute(_EDGES_TABLE_SQL)
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
                # v1 schema — drop everything and start fresh
                cur.execute("DROP TABLE IF EXISTS edges")
                cur.execute("DROP TABLE IF EXISTS node_meta")
                cur.execute("DROP TABLE IF EXISTS nodes")

    def _ensure_nodes_table(self) -> lancedb.table.Table | None:
        """Open existing nodes table if present."""
        if self._nodes_table is not None:
            return self._nodes_table
        existing_tables = self._lance_db.list_tables()
        if "nodes" in existing_tables:
            self._nodes_table = self._lance_db.open_table("nodes")
        return self._nodes_table

    # --- Store ---

    def store_review(self, review: GrippyReview, *, session_id: str = "") -> None:
        """Persist a GrippyReview — nodes/edges to SQLite, vectors to LanceDB.

        Atomicity strategy:
        1. Compute embeddings (pure, no side effects)
        2. SQLite transaction (UPSERT nodes + edges)
        3. LanceDB upsert vectors (idempotent on rerun)
        """
        # Build all node/edge data from the review
        nodes, edges, embed_texts = self._build_graph_data(review, session_id=session_id)

        # 1. Compute embeddings first (pure)
        vectors = self._compute_embeddings(embed_texts)

        # 2. SQLite transaction — UPSERT all nodes + edges
        self._upsert_sqlite(nodes, edges)

        # 3. LanceDB — upsert vectors
        self._upsert_vectors(nodes, vectors)

    def _build_graph_data(
        self,
        review: GrippyReview,
        *,
        session_id: str = "",
    ) -> tuple[list[dict[str, Any]], list[tuple[str, str, str, str]], list[str]]:
        """Build node records, edge tuples, and embedding texts from a review.

        Returns:
            (nodes, edges, embed_texts) where:
            - nodes: list of dicts with id, type, label, data, session_id, status, fingerprint, created_at
            - edges: list of (source, target, relationship, properties_json) tuples
            - embed_texts: list of text strings for embedding (parallel to nodes)
        """
        nodes: list[dict[str, Any]] = []
        edges: list[tuple[str, str, str, str]] = []
        embed_texts: list[str] = []
        seen_ids: set[str] = set()

        def _add_node(
            node_id: str,
            node_type: NodeType,
            label: str,
            data: dict[str, Any],
            *,
            status: str | None = None,
            fingerprint: str | None = None,
        ) -> None:
            if node_id in seen_ids:
                return
            seen_ids.add(node_id)
            nodes.append(
                {
                    "id": node_id,
                    "type": node_type.value,
                    "label": label,
                    "data": json.dumps(data),
                    "session_id": session_id,
                    "status": status,
                    "fingerprint": fingerprint,
                    "created_at": review.timestamp,
                }
            )
            # Build embedding text
            text = f"{node_type.value}: {label}"
            if data:
                props_str = " ".join(f"{k}={v}" for k, v in data.items())
                text = f"{text} {props_str}"
            embed_texts.append(text)

        # Review node
        review_nid = _record_id(NodeType.REVIEW, review.model, review.timestamp)
        _add_node(
            review_nid,
            NodeType.REVIEW,
            f"Review: {review.pr.title}",
            {
                "audit_type": review.audit_type,
                "overall_score": review.score.overall,
                "verdict": review.verdict.status.value,
                "model": review.model,
            },
        )

        # Author node (PR author)
        author_nid = _record_id(NodeType.AUTHOR, review.pr.author)
        _add_node(
            author_nid,
            NodeType.AUTHOR,
            review.pr.author,
            {"branch": review.pr.branch},
        )

        # REVIEWED_BY: Review → Author
        edges.append((review_nid, author_nid, EdgeType.REVIEWED_BY.value, "{}"))

        # Process each finding
        for finding in review.findings:
            # FILE node (deduplicated by path)
            file_nid = _record_id(NodeType.FILE, finding.file)
            _add_node(file_nid, NodeType.FILE, finding.file, {})

            # SUGGESTION node
            suggestion_nid = _record_id(
                NodeType.SUGGESTION, finding.file, str(finding.line_start), finding.suggestion
            )
            _add_node(suggestion_nid, NodeType.SUGGESTION, finding.suggestion, {})

            # RULE node (if governance_rule_id present)
            if finding.governance_rule_id:
                rule_nid = _record_id(NodeType.RULE, finding.governance_rule_id)
                _add_node(rule_nid, NodeType.RULE, finding.governance_rule_id, {})

            # FINDING node — use fingerprint for stable IDs across line shifts
            finding_nid = _record_id(NodeType.FINDING, finding.fingerprint)
            finding_data = {
                "severity": finding.severity.value,
                "confidence": finding.confidence,
                "category": finding.category.value,
                "file": finding.file,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "evidence": finding.evidence,
                "fingerprint": finding.fingerprint,
                "status": FindingStatus.OPEN.value,
            }
            _add_node(
                finding_nid,
                NodeType.FINDING,
                finding.title,
                finding_data,
                status=FindingStatus.OPEN.value,
                fingerprint=finding.fingerprint,
            )

            # Edges: Finding → Review, Finding → File, Finding → Suggestion
            edges.append((finding_nid, review_nid, EdgeType.EXTRACTED_FROM.value, "{}"))
            edges.append((finding_nid, file_nid, EdgeType.FOUND_IN.value, "{}"))
            edges.append((finding_nid, suggestion_nid, EdgeType.FIXED_BY.value, "{}"))

            # Finding → Rule (if governance_rule_id present)
            if finding.governance_rule_id:
                edges.append((finding_nid, rule_nid, EdgeType.VIOLATES.value, "{}"))

        return nodes, edges, embed_texts

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
                    """INSERT INTO nodes (id, type, label, data, session_id, status, fingerprint, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        label = excluded.label,
                        data = excluded.data,
                        session_id = excluded.session_id,
                        status = COALESCE(nodes.status, excluded.status),
                        fingerprint = excluded.fingerprint,
                        created_at = excluded.created_at""",
                    (
                        node["id"],
                        node["type"],
                        node["label"],
                        node["data"],
                        node["session_id"],
                        node["status"],
                        node["fingerprint"],
                        node["created_at"],
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
            existing_ids = set(arrow_tbl.column("node_id").to_pylist())
            new_records = [r for r in records if r["node_id"] not in existing_ids]
            if new_records:
                table.add(new_records)

    # --- Node queries ---

    def get_all_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes from LanceDB."""
        table = self._ensure_nodes_table()
        if table is None:
            return []
        return _arrow_table_to_dicts(table.to_arrow())

    # --- High-level queries (single-pass SQL joins) ---

    def get_author_tendencies(self, author: str) -> list[dict[str, Any]]:
        """Get finding patterns associated with a specific author.

        Single-pass SQL: Finding -[EXTRACTED_FROM]-> Review -[REVIEWED_BY]-> Author
        """
        cur = self._conn.cursor()
        cur.execute(
            """SELECT n.id, n.label, n.data, n.status, n.fingerprint
            FROM nodes n
            JOIN edges e1 ON e1.source = n.id AND e1.relationship = ?
            JOIN nodes r ON r.id = e1.target AND r.type = ?
            JOIN edges e2 ON e2.source = r.id AND e2.relationship = ?
            JOIN nodes a ON a.id = e2.target AND a.type = ? AND a.label = ?
            WHERE n.type = ?""",
            (
                EdgeType.EXTRACTED_FROM.value,
                NodeType.REVIEW.value,
                EdgeType.REVIEWED_BY.value,
                NodeType.AUTHOR.value,
                author,
                NodeType.FINDING.value,
            ),
        )
        results = []
        for row in cur.fetchall():
            data = json.loads(row["data"])
            data["title"] = row["label"]
            results.append(data)
        return results

    def get_patterns_for_file(self, file_path: str) -> list[dict[str, Any]]:
        """Get findings associated with a specific file.

        Single-pass SQL: Finding -[FOUND_IN]-> File
        """
        cur = self._conn.cursor()
        cur.execute(
            """SELECT n.id, n.label, n.data, n.status, n.fingerprint
            FROM nodes n
            JOIN edges e ON e.source = n.id AND e.relationship = ?
            JOIN nodes f ON f.id = e.target AND f.type = ? AND f.label = ?
            WHERE n.type = ?""",
            (
                EdgeType.FOUND_IN.value,
                NodeType.FILE.value,
                file_path,
                NodeType.FINDING.value,
            ),
        )
        results = []
        for row in cur.fetchall():
            data = json.loads(row["data"])
            data["title"] = row["label"]
            results.append(data)
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

        Single query, no JSON parsing — uses real columns.
        Call BEFORE store_review() so only prior round findings are returned.
        """
        cur = self._conn.cursor()
        cur.execute(
            """SELECT id AS node_id, label AS title, data, status, fingerprint
            FROM nodes
            WHERE type = ? AND session_id = ? AND status = ?""",
            (NodeType.FINDING.value, session_id, FindingStatus.OPEN.value),
        )
        results = []
        for row in cur.fetchall():
            data = json.loads(row["data"])
            data["node_id"] = row["node_id"]
            data["title"] = row["title"]
            data["status"] = row["status"]
            data["fingerprint"] = row["fingerprint"]
            results.append(data)
        return results

    def update_finding_status(self, node_id: str, status: str | FindingStatus) -> None:
        """Update a finding's status — direct column update + JSON sync."""
        status_val = status if isinstance(status, str) else status.value
        cur = self._conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            cur.execute("SELECT data FROM nodes WHERE id = ?", (node_id,))
            row = cur.fetchone()
            if row:
                data = json.loads(row["data"])
                data["status"] = status_val
                cur.execute(
                    "UPDATE nodes SET status = ?, data = ? WHERE id = ?",
                    (status_val, json.dumps(data), node_id),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
