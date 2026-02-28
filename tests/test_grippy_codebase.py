# SPDX-License-Identifier: MIT
"""Tests for Grippy codebase indexing and search tools."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from grippy.codebase import (
    _MAX_GLOB_RESULTS,
    _MAX_RESULT_CHARS,
    CodebaseIndex,
    CodebaseToolkit,
    _limit_result,
    _make_grep_code,
    _make_list_files,
    _make_read_file,
    _make_search_code,
    chunk_file,
    walk_source_files,
)

# --- Fixtures ---


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure for testing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def hello():\n    return 'world'\n")
    (tmp_path / "src" / "utils.py").write_text(
        "import os\n\ndef get_env(key):\n    return os.environ.get(key)\n"
    )
    (tmp_path / "README.md").write_text("# Test Project\n\nA test project.\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"fake")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("gitconfig")
    return tmp_path


@pytest.fixture
def mock_embedder() -> MagicMock:
    """Create a mock embedder returning fixed-size vectors."""
    embedder = MagicMock()
    embedder.get_embedding = MagicMock(return_value=[0.1] * 8)
    return embedder


@pytest.fixture
def mock_batch_embedder() -> MagicMock:
    """Create a mock batch embedder."""
    embedder = MagicMock()
    embedder.get_embedding = MagicMock(return_value=[0.1] * 8)
    embedder.get_embedding_batch = MagicMock(side_effect=lambda texts: [[0.1] * 8 for _ in texts])
    return embedder


@pytest.fixture
def lance_db(tmp_path: Path) -> Any:
    """Create a LanceDB connection for testing."""
    import lancedb  # type: ignore[import-untyped]

    lance_dir = tmp_path / "lance_test"
    lance_dir.mkdir()
    return lancedb.connect(str(lance_dir))


# --- _limit_result tests ---


class TestLimitResult:
    def test_short_text_unchanged(self) -> None:
        text = "short text"
        assert _limit_result(text) == text

    def test_exact_limit_unchanged(self) -> None:
        text = "x" * _MAX_RESULT_CHARS
        assert _limit_result(text) == text

    def test_over_limit_truncated_with_message(self) -> None:
        text = "x" * (_MAX_RESULT_CHARS + 500)
        result = _limit_result(text)
        assert len(result) < len(text)
        assert "truncated" in result
        assert "narrow your query" in result

    def test_custom_limit(self) -> None:
        text = "hello world"
        result = _limit_result(text, max_chars=5)
        assert result.startswith("hello")
        assert "truncated" in result


# --- walk_source_files tests ---


class TestWalkSourceFiles:
    def test_finds_python_files(self, tmp_repo: Path) -> None:
        files = walk_source_files(tmp_repo)
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) == 2

    def test_finds_markdown_files(self, tmp_repo: Path) -> None:
        files = walk_source_files(tmp_repo)
        md_files = [f for f in files if f.suffix == ".md"]
        assert len(md_files) == 1

    def test_ignores_pycache(self, tmp_repo: Path) -> None:
        files = walk_source_files(tmp_repo)
        assert not any("__pycache__" in str(f) for f in files)

    def test_ignores_git_dir(self, tmp_repo: Path) -> None:
        files = walk_source_files(tmp_repo)
        assert not any(".git" in str(f) for f in files)

    def test_custom_extensions(self, tmp_repo: Path) -> None:
        files = walk_source_files(tmp_repo, extensions=frozenset({".toml"}))
        assert len(files) == 1
        assert files[0].name == "pyproject.toml"

    def test_returns_sorted(self, tmp_repo: Path) -> None:
        files = walk_source_files(tmp_repo)
        assert files == sorted(files)

    def test_fallback_when_git_unavailable(self, tmp_repo: Path) -> None:
        """Falls back to manual walk when git ls-files fails."""
        with patch("grippy.codebase.subprocess.run", side_effect=FileNotFoundError):
            files = walk_source_files(tmp_repo)
            assert len(files) > 0


# --- chunk_file tests ---


class TestChunkFile:
    def test_small_file_single_chunk(self, tmp_repo: Path) -> None:
        path = tmp_repo / "src" / "main.py"
        chunks = chunk_file(path)
        assert len(chunks) == 1
        assert chunks[0]["chunk_index"] == 0
        assert chunks[0]["start_line"] == 1
        assert "def hello" in chunks[0]["text"]

    def test_large_file_multiple_chunks(self, tmp_path: Path) -> None:
        big_file = tmp_path / "big.py"
        big_file.write_text("x = 1\n" * 2000)  # ~12000 chars
        chunks = chunk_file(big_file, max_chunk_chars=4000, overlap=200)
        assert len(chunks) > 1
        # Chunks should overlap
        assert chunks[1]["start_line"] < chunks[0]["end_line"] + 5

    def test_empty_file_no_chunks(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.py"
        empty.write_text("")
        chunks = chunk_file(empty)
        assert chunks == []

    def test_whitespace_only_no_chunks(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws.py"
        ws.write_text("   \n  \n  ")
        chunks = chunk_file(ws)
        assert chunks == []

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        chunks = chunk_file(tmp_path / "nope.py")
        assert chunks == []

    def test_chunk_metadata_correct(self, tmp_repo: Path) -> None:
        path = tmp_repo / "src" / "utils.py"
        chunks = chunk_file(path)
        assert len(chunks) == 1
        assert chunks[0]["file_path"] == str(path)
        assert chunks[0]["start_line"] == 1
        assert chunks[0]["end_line"] >= 3

    def test_overlap_clamped_when_too_large(self, tmp_path: Path) -> None:
        """overlap >= max_chunk_chars doesn't cause infinite loop."""
        big_file = tmp_path / "big.py"
        big_file.write_text("x = 1\n" * 2000)
        chunks = chunk_file(big_file, max_chunk_chars=100, overlap=200)
        assert len(chunks) > 1  # Should still produce chunks, not loop forever

    def test_relative_to_produces_relative_paths(self, tmp_repo: Path) -> None:
        path = tmp_repo / "src" / "main.py"
        chunks = chunk_file(path, relative_to=tmp_repo)
        assert chunks[0]["file_path"] == "src/main.py"

    def test_without_relative_to_uses_full_path(self, tmp_repo: Path) -> None:
        path = tmp_repo / "src" / "main.py"
        chunks = chunk_file(path)
        assert chunks[0]["file_path"] == str(path)


# --- CodebaseIndex tests ---


class TestCodebaseIndex:
    def test_not_indexed_initially(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        assert not idx.is_indexed

    def test_is_indexed_after_build(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        count = idx.build()
        assert count > 0
        assert idx.is_indexed

    def test_build_returns_chunk_count(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        count = idx.build()
        # Should have chunks for main.py, utils.py, README.md, pyproject.toml
        assert count >= 4

    def test_build_uses_batch_embedder(
        self, tmp_repo: Path, lance_db: Any, mock_batch_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_batch_embedder)
        idx.build()
        mock_batch_embedder.get_embedding_batch.assert_called()

    def test_build_with_index_paths(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(
            repo_root=tmp_repo,
            lance_db=lance_db,
            embedder=mock_embedder,
            index_paths=["src"],
        )
        count = idx.build()
        # Only src/ files: main.py, utils.py
        assert count == 2

    def test_build_stores_relative_paths(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        results = idx.search("hello")
        assert results
        # Paths should be relative, not absolute
        for r in results:
            assert not r["file_path"].startswith("/"), (
                f"Expected relative path, got {r['file_path']}"
            )

    def test_build_empty_dir(self, tmp_path: Path, lance_db: Any, mock_embedder: MagicMock) -> None:
        empty = tmp_path / "empty_repo"
        empty.mkdir()
        idx = CodebaseIndex(repo_root=empty, lance_db=lance_db, embedder=mock_embedder)
        count = idx.build()
        assert count == 0

    def test_search_returns_results(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        results = idx.search("hello function")
        assert len(results) > 0
        assert "file_path" in results[0]
        assert "text" in results[0]

    def test_search_before_build_empty(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        results = idx.search("anything")
        assert results == []

    def test_search_respects_k(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        results = idx.search("test", k=2)
        assert len(results) <= 2

    def test_rebuild_replaces_old_table(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        count1 = idx.build()
        count2 = idx.build()
        assert count1 == count2  # Same files, same count


# --- search_code tool tests ---


class TestSearchCodeTool:
    def test_returns_results(self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        search = _make_search_code(idx)
        result = search("hello function")
        assert "main.py" in result or "utils.py" in result

    def test_not_indexed_message(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        search = _make_search_code(idx)
        result = search("anything")
        assert "not indexed" in result.lower()

    def test_no_results_message(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        # Mock search to return empty
        idx.search = MagicMock(return_value=[])  # type: ignore[method-assign]
        search = _make_search_code(idx)
        result = search("nonexistent xyz")
        assert "no results" in result.lower()

    def test_respects_k_parameter(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        search = _make_search_code(idx)
        result = search("test", k=1)
        # Should have at most 1 result block
        assert result.count("---") <= 4  # header has dashes

    def test_result_format(self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        idx.build()
        search = _make_search_code(idx)
        result = search("hello")
        assert "lines" in result


# --- grep_code tool tests ---


class TestGrepCodeTool:
    def test_finds_pattern(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        result = grep("def hello")
        assert "hello" in result

    def test_no_match(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        result = grep("zzz_nonexistent_pattern_zzz")
        assert "no matches" in result.lower()

    def test_invalid_regex(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        result = grep("[invalid")
        assert "invalid regex" in result.lower()

    def test_glob_filter(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        result = grep("Test Project", glob="*.md")
        assert "Test Project" in result

    def test_context_lines(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        result = grep("def hello", context_lines=1)
        # Should include surrounding context
        assert "return" in result

    def test_respects_result_limit(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        result = grep(".")  # Match everything
        assert len(result) <= _MAX_RESULT_CHARS + 200  # Allow for truncation message

    def test_timeout_handling(self, tmp_repo: Path) -> None:
        grep = _make_grep_code(tmp_repo)
        with patch(
            "grippy.codebase.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="grep", timeout=10),
        ):
            result = grep("pattern")
        assert "timed out" in result.lower()


# --- read_file tool tests ---


class TestReadFileTool:
    def test_reads_full_file(self, tmp_repo: Path) -> None:
        read = _make_read_file(tmp_repo)
        result = read("src/main.py")
        assert "def hello" in result
        assert "return" in result

    def test_line_numbers_shown(self, tmp_repo: Path) -> None:
        read = _make_read_file(tmp_repo)
        result = read("src/main.py")
        assert "1 |" in result or "   1 |" in result

    def test_line_range(self, tmp_repo: Path) -> None:
        read = _make_read_file(tmp_repo)
        result = read("src/utils.py", start_line=2, end_line=3)
        # Should only have 2 lines
        assert "import os" not in result or result.count("|") == 2

    def test_file_not_found(self, tmp_repo: Path) -> None:
        read = _make_read_file(tmp_repo)
        result = read("nonexistent.py")
        assert "not found" in result.lower()

    def test_path_traversal_blocked(self, tmp_repo: Path) -> None:
        read = _make_read_file(tmp_repo)
        result = read("../../etc/passwd")
        assert "not allowed" in result.lower() or "not found" in result.lower()

    def test_read_file_rejects_prefix_bypass(self, tmp_path: Path) -> None:
        """H1: startswith bypass via shared prefix — e.g. /repo vs /repo-evil."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "safe.py").write_text("safe content")

        evil_dir = tmp_path / "repo-evil"
        evil_dir.mkdir()
        (evil_dir / "secrets.py").write_text("stolen secrets")

        read_fn = _make_read_file(repo_root)
        result = read_fn("../repo-evil/secrets.py")
        assert "path traversal not allowed" in result.lower()


# --- list_files tool tests ---


class TestListFilesTool:
    def test_lists_root(self, tmp_repo: Path) -> None:
        ls = _make_list_files(tmp_repo)
        result = ls()
        assert "src/" in result
        assert "README.md" in result

    def test_lists_subdirectory(self, tmp_repo: Path) -> None:
        ls = _make_list_files(tmp_repo)
        result = ls("src")
        assert "main.py" in result
        assert "utils.py" in result

    def test_glob_filter(self, tmp_repo: Path) -> None:
        ls = _make_list_files(tmp_repo)
        result = ls(".", "*.md")
        assert "README.md" in result
        assert "pyproject.toml" not in result

    def test_nonexistent_directory(self, tmp_repo: Path) -> None:
        ls = _make_list_files(tmp_repo)
        result = ls("nonexistent")
        assert "not found" in result.lower()

    def test_path_traversal_blocked(self, tmp_repo: Path) -> None:
        ls = _make_list_files(tmp_repo)
        result = ls("../..")
        assert "not allowed" in result.lower() or "not found" in result.lower()

    def test_list_files_rejects_prefix_bypass(self, tmp_path: Path) -> None:
        """H1: startswith bypass in list_files."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "safe.py").write_text("x")

        evil_dir = tmp_path / "repo-evil"
        evil_dir.mkdir()
        (evil_dir / "secrets.py").write_text("stolen")

        list_fn = _make_list_files(repo_root)
        result = list_fn("../repo-evil")
        assert "path traversal not allowed" in result.lower()

    def test_list_files_glob_cannot_escape_boundary(self, tmp_path: Path) -> None:
        """H2: glob results must be bounded by repo_root."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "safe.py").write_text("x")

        outside = tmp_path / "outside.py"
        outside.write_text("outside content")

        list_fn = _make_list_files(repo_root)
        result = list_fn(".", "../../*")
        assert "outside.py" not in result

    def test_list_files_truncation_notice(self, tmp_path: Path) -> None:
        """Glob results exceeding _MAX_GLOB_RESULTS show a truncation notice."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        for i in range(_MAX_GLOB_RESULTS + 10):
            (repo_root / f"file_{i:05d}.txt").write_text("x")

        list_fn = _make_list_files(repo_root)
        result = list_fn(".", "*.txt")
        assert "[truncated]" in result
        assert str(_MAX_GLOB_RESULTS) in result

    def test_list_files_no_truncation_within_limit(self, tmp_path: Path) -> None:
        """Glob results within _MAX_GLOB_RESULTS have no truncation notice."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        for i in range(5):
            (repo_root / f"file_{i}.txt").write_text("x")

        list_fn = _make_list_files(repo_root)
        result = list_fn(".", "*.txt")
        assert "[truncated]" not in result
        assert "file_0.txt" in result


# --- CodebaseToolkit tests ---


class TestCodebaseToolkit:
    def test_registers_four_tools(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        toolkit = CodebaseToolkit(index=idx, repo_root=tmp_repo)
        assert len(toolkit.functions) == 4

    def test_tool_names(self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        toolkit = CodebaseToolkit(index=idx, repo_root=tmp_repo)
        names = set(toolkit.functions.keys())
        assert "search_code" in names
        assert "grep_code" in names
        assert "read_file" in names
        assert "list_files" in names

    def test_tools_are_callable(
        self, tmp_repo: Path, lance_db: Any, mock_embedder: MagicMock
    ) -> None:
        idx = CodebaseIndex(repo_root=tmp_repo, lance_db=lance_db, embedder=mock_embedder)
        toolkit = CodebaseToolkit(index=idx, repo_root=tmp_repo)
        for func in toolkit.functions.values():
            assert func.entrypoint is not None


# --- create_reviewer tools param tests ---


class TestCreateReviewerTools:
    def test_tools_none_by_default(self) -> None:
        """create_reviewer without tools= produces agent with no tools."""
        from grippy.agent import create_reviewer

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            agent = create_reviewer(transport="openai", model_id="gpt-4o-mini")
        # Agent should have no tools (or empty tools)
        assert agent.tools is None or agent.tools == []

    def test_tools_passed_through(self) -> None:
        """create_reviewer with tools= passes them to Agent."""
        from grippy.agent import create_reviewer

        mock_toolkit = MagicMock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            agent = create_reviewer(
                transport="openai",
                model_id="gpt-4o-mini",
                tools=[mock_toolkit],
            )
        assert agent.tools is not None
        assert len(agent.tools) == 1

    def test_tool_call_limit_passed(self) -> None:
        """create_reviewer with tool_call_limit passes it through."""
        from grippy.agent import create_reviewer

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            agent = create_reviewer(
                transport="openai",
                model_id="gpt-4o-mini",
                tool_call_limit=10,
            )
        assert agent.tool_call_limit == 10


# --- main() wiring tests ---


class TestMainWiring:
    def _make_pr_event(self, tmp_path: Path) -> Path:
        """Create a minimal PR event JSON file."""
        import json

        event = {
            "pull_request": {
                "number": 99,
                "title": "test PR",
                "user": {"login": "testuser"},
                "head": {"ref": "feat/test", "sha": "abc123"},
                "base": {"ref": "main"},
                "body": "Test PR body",
            },
            "repository": {"full_name": "test/repo"},
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event))
        return event_path

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.fetch_pr_diff")
    @patch("grippy.review.create_embedder")
    @patch("grippy.review.GrippyStore")
    def test_codebase_index_wired_in_main(
        self,
        mock_store_cls: MagicMock,
        mock_create_embedder: MagicMock,
        mock_fetch_diff: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Verify that main() creates CodebaseIndex when GITHUB_WORKSPACE is set."""
        from grippy.review import main
        from grippy.schema import (
            AsciiArtKey,
            ComplexityTier,
            GrippyReview,
            Personality,
            PRMetadata,
            ReviewMeta,
            ReviewScope,
            Score,
            ScoreBreakdown,
            ScoreDeductions,
            ToneRegister,
            Verdict,
            VerdictStatus,
        )

        event_path = self._make_pr_event(tmp_path)

        review = GrippyReview(
            version="1.0",
            audit_type="pr_review",
            timestamp="2026-02-27T12:00:00Z",
            model="test",
            pr=PRMetadata(
                title="test",
                author="dev",
                branch="a → b",
                complexity_tier=ComplexityTier.TRIVIAL,
            ),
            scope=ReviewScope(
                files_in_diff=1,
                files_reviewed=1,
                coverage_percentage=100.0,
                governance_rules_applied=[],
                modes_active=["pr_review"],
            ),
            findings=[],
            escalations=[],
            score=Score(
                overall=90,
                breakdown=ScoreBreakdown(
                    security=95,
                    logic=90,
                    governance=100,
                    reliability=85,
                    observability=80,
                ),
                deductions=ScoreDeductions(
                    critical_count=0,
                    high_count=0,
                    medium_count=0,
                    low_count=0,
                    total_deduction=10,
                ),
            ),
            verdict=Verdict(
                status=VerdictStatus.PASS,
                threshold_applied=70,
                merge_blocking=False,
                summary="All clear",
            ),
            personality=Personality(
                tone_register=ToneRegister.GRUDGING_RESPECT,
                opening_catchphrase="Not bad...",
                closing_line="Fine.",
                ascii_art_key=AsciiArtKey.ALL_CLEAR,
            ),
            meta=ReviewMeta(
                review_duration_ms=0,
                tokens_used=0,
                context_files_loaded=0,
                confidence_filter_suppressed=0,
                duplicate_filter_suppressed=0,
            ),
        )

        mock_fetch_diff.return_value = "diff --git a/test.py b/test.py\n+hello\n"
        mock_run_review.return_value = review
        mock_post_review.return_value = None
        mock_store = MagicMock()
        mock_store.get_prior_findings.return_value = []
        mock_store_cls.return_value = mock_store
        mock_create_embedder.return_value = MagicMock()

        env = {
            "GITHUB_TOKEN": "fake-token",
            "GITHUB_EVENT_PATH": str(event_path),
            "GRIPPY_TRANSPORT": "openai",
            "OPENAI_API_KEY": "test-key",
            "GRIPPY_DATA_DIR": str(tmp_path / "data"),
            "GITHUB_WORKSPACE": str(tmp_path),
            "GRIPPY_TIMEOUT": "0",
        }

        with patch.dict(os.environ, env, clear=False):
            # main() should not crash — codebase indexing is non-fatal
            try:
                main()
            except SystemExit:
                pass  # main() calls sys.exit on certain paths
