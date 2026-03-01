# SPDX-License-Identifier: MIT
"""Codebase indexing and search tools for Grippy reviews.

Indexes source files into LanceDB for vector similarity search and provides
Agno-compatible tools that let the review agent search and read the full
codebase — not just the diff.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

log = logging.getLogger(__name__)

# --- Constants ---

_DEFAULT_EXTENSIONS = frozenset({".py", ".md", ".yaml", ".yml", ".toml"})

_DEFAULT_IGNORE_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".eggs",
        "*.egg-info",
    }
)

_CODEBASE_TABLE = "codebase_chunks"

_MAX_RESULT_CHARS = 12_000

# Safety limits for indexing
_MAX_INDEX_FILES = 5_000
_MAX_GLOB_RESULTS = 500


# --- Protocols ---


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedders — compatible with Agno's OpenAIEmbedder."""

    def get_embedding(self, text: str) -> list[float]: ...


@runtime_checkable
class BatchEmbedder(Protocol):
    """Protocol for embedders that support batch embedding."""

    def get_embedding(self, text: str) -> list[float]: ...
    def get_embedding_batch(self, texts: list[str]) -> list[list[float]]: ...


# --- Utilities ---


def _limit_result(text: str, max_chars: int = _MAX_RESULT_CHARS) -> str:
    """Truncate tool output to budget, appending guidance if truncated.

    Returns the text unchanged if within budget. Otherwise truncates and
    appends a message telling the LLM to narrow its query.
    """
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars] + "\n\n... (truncated — narrow your query with a more specific pattern or "
        "smaller line range to see full results)"
    )


def walk_source_files(
    root: Path,
    extensions: frozenset[str] = _DEFAULT_EXTENSIONS,
    ignore_dirs: frozenset[str] = _DEFAULT_IGNORE_DIRS,
) -> list[Path]:
    """Walk repo for indexable source files.

    Respects .gitignore via ``git ls-files`` when available, falling back
    to manual walk with ignore_dirs filtering.

    Returns:
        Sorted list of absolute file paths matching the given extensions.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            cwd=str(root),
            check=True,
        )
        paths = []
        for line in result.stdout.strip().splitlines():
            p = root / line
            if p.suffix in extensions and p.is_file():
                paths.append(p)
        return sorted(paths)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Fallback: manual walk
    paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out ignored directories in-place
        dirnames[:] = [
            d
            for d in dirnames
            if d not in ignore_dirs and not any(fnmatch.fnmatch(d, pat) for pat in ignore_dirs)
        ]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix in extensions:
                paths.append(fpath)
    return sorted(paths)


def chunk_file(
    path: Path,
    max_chunk_chars: int = 4000,
    overlap: int = 200,
    relative_to: Path | None = None,
) -> list[dict[str, Any]]:
    """Split a file into chunks for embedding.

    Small files (< max_chunk_chars) become a single chunk. Larger files
    are split into overlapping character windows with line-boundary alignment.

    Args:
        path: Absolute path to the file.
        max_chunk_chars: Maximum characters per chunk.
        overlap: Character overlap between consecutive chunks.
        relative_to: If set, store paths relative to this root.

    Returns:
        List of chunk dicts: {file_path, chunk_index, start_line, end_line, text}.
    """
    # Clamp overlap to prevent infinite loop
    if overlap >= max_chunk_chars:
        overlap = max(0, max_chunk_chars - 1)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    if not text.strip():
        return []

    if relative_to is not None:
        try:
            rel_path = str(path.relative_to(relative_to))
        except ValueError:
            rel_path = str(path)
    else:
        rel_path = str(path)
    lines = text.splitlines(keepends=True)

    if len(text) <= max_chunk_chars:
        return [
            {
                "file_path": rel_path,
                "chunk_index": 0,
                "start_line": 1,
                "end_line": len(lines),
                "text": text,
            }
        ]

    # Split into overlapping character windows, aligning to line boundaries
    chunks: list[dict[str, Any]] = []
    char_pos = 0
    chunk_idx = 0

    while char_pos < len(text):
        end_pos = min(char_pos + max_chunk_chars, len(text))
        chunk_text = text[char_pos:end_pos]

        # Count lines for metadata
        start_line = text[:char_pos].count("\n") + 1
        end_line = start_line + chunk_text.count("\n")

        chunks.append(
            {
                "file_path": rel_path,
                "chunk_index": chunk_idx,
                "start_line": start_line,
                "end_line": end_line,
                "text": chunk_text,
            }
        )
        chunk_idx += 1

        # Advance with overlap
        char_pos = end_pos - overlap if end_pos < len(text) else end_pos

    return chunks


# --- CodebaseIndex ---


class CodebaseIndex:
    """Indexes source files into LanceDB for vector search."""

    def __init__(
        self,
        *,
        repo_root: Path,
        lance_db: Any,
        embedder: Embedder,
        extensions: frozenset[str] = _DEFAULT_EXTENSIONS,
        ignore_dirs: frozenset[str] = _DEFAULT_IGNORE_DIRS,
        index_paths: list[str] | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._lance_db = lance_db
        self._embedder = embedder
        self._extensions = extensions
        self._ignore_dirs = ignore_dirs
        self._index_paths = index_paths
        self._table: Any | None = None

    @property
    def is_indexed(self) -> bool:
        """Check if the codebase_chunks table already exists."""
        tables = self._lance_db.list_tables()
        # LanceDB >= 0.20 returns ListTablesResponse; older returns list
        table_list = getattr(tables, "tables", tables)
        return _CODEBASE_TABLE in table_list

    def build(self) -> int:
        """Walk, chunk, embed, and store source files. Returns chunk count."""
        if self._index_paths:
            roots = [self._repo_root / p for p in self._index_paths]
        else:
            roots = [self._repo_root]

        all_chunks: list[dict[str, Any]] = []
        for root in roots:
            if not root.exists():
                continue
            if root.is_file():
                file_chunks = chunk_file(root, relative_to=self._repo_root)
                all_chunks.extend(file_chunks)
            else:
                files = walk_source_files(root, self._extensions, self._ignore_dirs)
                if len(files) > _MAX_INDEX_FILES:
                    log.warning(
                        "Capping indexing at %d files (found %d)",
                        _MAX_INDEX_FILES,
                        len(files),
                    )
                    files = files[:_MAX_INDEX_FILES]
                for f in files:
                    file_chunks = chunk_file(f, relative_to=self._repo_root)
                    all_chunks.extend(file_chunks)

        if not all_chunks:
            log.warning("No files found to index")
            return 0

        # Embed in batches
        texts = [c["text"] for c in all_chunks]
        if isinstance(self._embedder, BatchEmbedder):
            vectors = self._embedder.get_embedding_batch(texts)
        else:
            vectors = [self._embedder.get_embedding(t) for t in texts]

        for chunk, vec in zip(all_chunks, vectors, strict=True):
            chunk["vector"] = vec

        # Store — overwrite old table if exists
        self._table = self._lance_db.create_table(
            _CODEBASE_TABLE, data=all_chunks, mode="overwrite"
        )
        log.info("Indexed %d chunks from codebase", len(all_chunks))
        return len(all_chunks)

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Vector similarity search over indexed chunks."""
        if self._table is None:
            if self.is_indexed:
                self._table = self._lance_db.open_table(_CODEBASE_TABLE)
            else:
                return []

        query_vec = self._embedder.get_embedding(query)
        arrow_result = self._table.search(query_vec).limit(k).to_arrow()
        columns = arrow_result.column_names
        arrays = {col: arrow_result.column(col).to_pylist() for col in columns}
        n_rows = arrow_result.num_rows
        return [{col: arrays[col][i] for col in columns} for i in range(n_rows)]


# --- Tool functions ---


def _make_search_code(index: CodebaseIndex) -> Any:
    """Create a search_code tool function bound to an index."""

    def search_code(query: str, k: int = 5) -> str:
        """Search the codebase by semantic similarity.

        Use this to find definitions, patterns, or implementations
        across the full codebase — not just the diff.

        :param query: natural language description of what to find
        :param k: number of results to return (default 5)
        """
        if not index.is_indexed:
            return "Codebase not indexed — proceed with diff-only analysis."
        results = index.search(query, k=k)
        if not results:
            return "No results found."
        lines: list[str] = []
        for r in results:
            header = f"--- {r['file_path']} (lines {r['start_line']}-{r['end_line']}) ---"
            lines.append(header)
            lines.append(r["text"])
            lines.append("")
        return _limit_result("\n".join(lines))

    return search_code


def _make_grep_code(repo_root: Path) -> Any:
    """Create a grep_code tool function bound to a repo root."""

    def grep_code(pattern: str, glob: str = "*.py", context_lines: int = 2) -> str:
        """Regex search across the codebase with context lines.

        Use this to find exact definitions, class names, or string
        patterns across all files.

        :param pattern: regex pattern to search for
        :param glob: file glob to filter (default "*.py")
        :param context_lines: lines of context before/after match (default 2)
        """
        try:
            re.compile(pattern)
        except re.error as e:
            return f"Invalid regex: {e}"

        try:
            # Use -r (not -R) to prevent following symlinks on GNU grep.
            # On BSD grep, -r follows symlinks; -S is needed to prevent it,
            # but -S is not recognised by GNU grep.  Since CI targets Linux
            # (GNU grep), -r alone is sufficient.
            cmd = [
                "grep",
                "-rn",
                "--max-count=50",
                f"--include={glob}",
                f"-C{context_lines}",
                "-E",
                pattern,
                str(repo_root),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 1:
                return "No matches found."
            if result.returncode != 0:
                return f"Search failed: {result.stderr.strip()}"
            return _limit_result(result.stdout)
        except subprocess.TimeoutExpired:
            return "Search timed out — try a more specific pattern."
        except FileNotFoundError:
            return "grep not available on this system."

    return grep_code


def _make_read_file(repo_root: Path) -> Any:
    """Create a read_file tool function bound to a repo root."""

    def read_file(path: str, start_line: int = 0, end_line: int = 0) -> str:
        """Read a file or line range from the codebase with line numbers.

        :param path: relative file path from the repo root
        :param start_line: first line to read (1-based, 0 = from start)
        :param end_line: last line to read (1-based, 0 = to end)
        """
        target = repo_root / path
        # Prevent path traversal
        try:
            target = target.resolve()
            if not target.is_relative_to(repo_root.resolve()):
                return "Error: path traversal not allowed."
        except (OSError, ValueError):
            return "Error: invalid path."

        if not target.is_file():
            return f"File not found: {path}"

        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return f"Error reading file: {e}"

        # Apply line range
        if start_line > 0:
            start_idx = start_line - 1
        else:
            start_idx = 0
        if end_line > 0:
            end_idx = end_line
        else:
            end_idx = len(lines)

        selected = lines[start_idx:end_idx]
        numbered = [f"{start_idx + i + 1:4d} | {line}" for i, line in enumerate(selected)]
        result = f"# {path} (lines {start_idx + 1}-{start_idx + len(selected)})\n"
        result += "\n".join(numbered)
        return _limit_result(result)

    return read_file


def _make_list_files(repo_root: Path) -> Any:
    """Create a list_files tool function bound to a repo root."""

    def list_files(path: str = ".", glob_pattern: str = "*") -> str:
        """List files in a directory, optionally filtered by glob.

        :param path: relative directory path from the repo root (default ".")
        :param glob_pattern: glob pattern to filter files (default "*")
        """
        target = repo_root / path
        # Prevent path traversal
        try:
            target = target.resolve()
            if not target.is_relative_to(repo_root.resolve()):
                return "Error: path traversal not allowed."
        except (OSError, ValueError):
            return "Error: invalid path."

        if not target.is_dir():
            return f"Directory not found: {path}"

        try:
            resolved_root = repo_root.resolve()
            # Collect up to _MAX_GLOB_RESULTS+1 entries lazily to detect truncation
            # without expanding/sorting the entire glob iterator.
            collected: list[Path] = []
            truncated = False
            for entry in target.glob(glob_pattern):
                if entry.resolve().is_relative_to(resolved_root):
                    collected.append(entry)
                    if len(collected) > _MAX_GLOB_RESULTS:
                        truncated = True
                        break
            entries = sorted(collected[:_MAX_GLOB_RESULTS])
        except (OSError, ValueError, RuntimeError) as e:
            return f"Error listing files: {e}"

        lines: list[str] = []
        for entry in entries:
            rel = entry.relative_to(repo_root)
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{rel}{suffix}")

        if not lines:
            return f"No files matching '{glob_pattern}' in {path}/"

        if truncated:
            lines.insert(
                0,
                f"[truncated] showing first {_MAX_GLOB_RESULTS} results; "
                "refine glob_pattern for complete listing",
            )

        return _limit_result("\n".join(lines))

    return list_files


# --- CodebaseToolkit ---


class CodebaseToolkit(Toolkit):
    """Agno Toolkit providing codebase search/read tools for Grippy."""

    def __init__(
        self,
        *,
        index: CodebaseIndex,
        repo_root: Path,
    ) -> None:
        super().__init__(name="codebase")

        # Create tool functions
        search_fn = _make_search_code(index)
        grep_fn = _make_grep_code(repo_root)
        read_fn = _make_read_file(repo_root)
        list_fn = _make_list_files(repo_root)

        # Register via Agno's Function.from_callable pattern (validated in Serena)
        for fn in [search_fn, grep_fn, read_fn, list_fn]:
            func = Function.from_callable(fn)
            self.functions[func.name] = func
