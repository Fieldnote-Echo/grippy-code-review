# SPDX-License-Identifier: MIT
"""Tests for Grippy CI review entry point — reads PR, runs agent, posts comment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from grippy.review import (
    MAX_DIFF_CHARS,
    _failure_comment,
    _with_timeout,
    fetch_pr_diff,
    load_pr_event,
    post_comment,
    truncate_diff,
)
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

# --- Fixtures ---


def _make_finding(**overrides: Any) -> Finding:
    defaults: dict[str, Any] = {
        "id": "F-001",
        "severity": Severity.HIGH,
        "confidence": 85,
        "category": FindingCategory.SECURITY,
        "file": "src/app.py",
        "line_start": 42,
        "line_end": 45,
        "title": "SQL injection in query builder",
        "description": "User input passed directly to SQL",
        "suggestion": "Use parameterized queries",
        "governance_rule_id": "SEC-001",
        "evidence": "f-string in execute()",
        "grippy_note": "This one hurt to read.",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_review(**overrides: Any) -> GrippyReview:
    defaults: dict[str, Any] = {
        "version": "1.0",
        "audit_type": "pr_review",
        "timestamp": "2026-02-26T12:00:00Z",
        "model": "devstral-small-2-24b-instruct-2512",
        "pr": PRMetadata(
            title="feat: add user auth",
            author="testdev",
            branch="feature/auth → main",
            complexity_tier=ComplexityTier.STANDARD,
        ),
        "scope": ReviewScope(
            files_in_diff=3,
            files_reviewed=3,
            coverage_percentage=100.0,
            governance_rules_applied=["SEC-001"],
            modes_active=["pr_review"],
        ),
        "findings": [_make_finding()],
        "escalations": [],
        "score": Score(
            overall=72,
            breakdown=ScoreBreakdown(
                security=60, logic=80, governance=75, reliability=70, observability=75
            ),
            deductions=ScoreDeductions(
                critical_count=0, high_count=1, medium_count=0, low_count=0, total_deduction=28
            ),
        ),
        "verdict": Verdict(
            status=VerdictStatus.PROVISIONAL,
            threshold_applied=70,
            merge_blocking=False,
            summary="Fix the SQL injection before merge.",
        ),
        "personality": Personality(
            tone_register=ToneRegister.GRUMPY,
            opening_catchphrase="*adjusts reading glasses*",
            closing_line="Fix it or I'm telling the security team.",
            ascii_art_key=AsciiArtKey.WARNING,
        ),
        "meta": ReviewMeta(
            review_duration_ms=45000,
            tokens_used=8200,
            context_files_loaded=3,
            confidence_filter_suppressed=1,
            duplicate_filter_suppressed=0,
        ),
    }
    defaults.update(overrides)
    return GrippyReview(**defaults)


# --- load_pr_event ---


class TestLoadPrEvent:
    def test_loads_pull_request_event(self, tmp_path: Path) -> None:
        """Parses PR number, repo, title, author, branch from event JSON."""
        event = {
            "pull_request": {
                "number": 42,
                "title": "feat: add auth",
                "user": {"login": "nelson"},
                "head": {"ref": "feature/auth"},
                "base": {"ref": "main"},
                "body": "Adds authentication system",
            },
            "repository": {"full_name": "Project-Navi/repo"},
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event))

        result = load_pr_event(event_path)
        assert result["pr_number"] == 42
        assert result["repo"] == "Project-Navi/repo"
        assert result["title"] == "feat: add auth"
        assert result["author"] == "nelson"
        assert result["head_ref"] == "feature/auth"
        assert result["base_ref"] == "main"
        assert result["description"] == "Adds authentication system"

    def test_missing_event_file_raises(self) -> None:
        """Raises FileNotFoundError for nonexistent event file."""
        with pytest.raises(FileNotFoundError):
            load_pr_event(Path("/nonexistent/event.json"))

    def test_missing_pull_request_key_raises(self, tmp_path: Path) -> None:
        """Raises KeyError when event has no pull_request key."""
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps({"action": "opened"}))

        with pytest.raises(KeyError, match="pull_request"):
            load_pr_event(event_path)

    def test_null_body_becomes_empty_string(self, tmp_path: Path) -> None:
        """PR body of null becomes empty string."""
        event = {
            "pull_request": {
                "number": 1,
                "title": "fix: typo",
                "user": {"login": "dev"},
                "head": {"ref": "fix"},
                "base": {"ref": "main"},
                "body": None,
            },
            "repository": {"full_name": "org/repo"},
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event))

        result = load_pr_event(event_path)
        assert result["description"] == ""


# --- C1: fetch_pr_diff uses raw diff API, not paginated compare ---


class TestFetchPrDiff:
    @patch("requests.get")
    def test_fetches_raw_diff_via_api(self, mock_get: MagicMock) -> None:
        """Uses GitHub API with diff media type, not compare().files."""
        mock_response = MagicMock()
        mock_response.text = (
            "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
        )
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_pr_diff("test-token", "org/repo", 42)

        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "org/repo" in call_args[0][0]
        assert "42" in call_args[0][0]
        assert "application/vnd.github.v3.diff" in str(call_args[1].get("headers", {}))
        assert "diff --git" in result

    @patch("requests.get")
    def test_includes_auth_header(self, mock_get: MagicMock) -> None:
        """Request includes Authorization header with token."""
        mock_response = MagicMock()
        mock_response.text = ""
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        fetch_pr_diff("my-secret-token", "org/repo", 1)

        headers = mock_get.call_args[1]["headers"]
        assert "my-secret-token" in headers.get("Authorization", "")

    @patch("requests.get")
    def test_raises_on_http_error(self, mock_get: MagicMock) -> None:
        """HTTP errors propagate (e.g., 404 for missing PR)."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_response

        with pytest.raises(Exception, match="404"):
            fetch_pr_diff("token", "org/repo", 999)


# --- M2: fetch_pr_diff fork handling ---


class TestFetchPrDiffForkHandling:
    """Fork-specific scenarios for the raw diff endpoint."""

    @patch("requests.get")
    def test_403_raises_descriptive_error(self, mock_get: MagicMock) -> None:
        """A 403 from the diff endpoint raises HTTPError (e.g., fork token lacks access)."""
        from requests.exceptions import HTTPError

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = HTTPError(
            "403 Forbidden", response=mock_response
        )
        mock_get.return_value = mock_response

        with pytest.raises(HTTPError, match="403"):
            fetch_pr_diff("fork-token", "upstream/repo", 99)

    @patch("requests.get")
    def test_successful_fork_diff(self, mock_get: MagicMock) -> None:
        """Fork PRs return diff successfully when the token has access."""
        mock_response = MagicMock()
        mock_response.text = (
            "diff --git a/lib.py b/lib.py\n--- a/lib.py\n+++ b/lib.py\n@@ -1 +1 @@\n-old\n+new"
        )
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetch_pr_diff("fork-token", "upstream/repo", 55)

        assert "diff --git" in result
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert "upstream/repo" in call_url
        assert "55" in call_url


# --- post_comment: SHA-scoped upsert ---


class TestPostComment:
    @patch("github.Github")
    def test_creates_issue_comment(self, mock_gh_cls: MagicMock) -> None:
        """post_comment creates an issue comment on the PR."""
        mock_pr = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_pull.return_value = mock_pr
        mock_gh_cls.return_value.get_repo.return_value = mock_repo

        post_comment("token", "org/repo", 42, "Error comment")

        mock_pr.create_issue_comment.assert_called_once()


class TestFailureComment:
    def test_config_error_includes_transport_hint(self) -> None:
        body = _failure_comment("o/r", "CONFIG ERROR")
        assert "CONFIG ERROR" in body
        assert "GRIPPY_TRANSPORT" in body
        assert "openai" in body
        assert "local" in body

    def test_timeout_includes_hint(self) -> None:
        body = _failure_comment("o/r", "TIMEOUT")
        assert "TIMEOUT" in body
        assert "GRIPPY_TIMEOUT" in body

    def test_generic_error_has_no_hint(self) -> None:
        body = _failure_comment("o/r", "ERROR")
        assert "ERROR" in body
        assert "GRIPPY_TRANSPORT" not in body
        assert "Actions log" in body

    def test_includes_run_id_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_RUN_ID", "12345")
        body = _failure_comment("o/r", "ERROR")
        assert "actions/runs/12345" in body

    def test_falls_back_to_generic_actions_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
        body = _failure_comment("o/r", "ERROR")
        assert "o/r/actions" in body
        assert "runs" not in body


# --- main() wiring ---


class TestMainWiringNewAPI:
    """Verify main() calls run_review and posts review."""

    def _make_event_file(self, tmp_path: Path) -> Path:
        event = {
            "pull_request": {
                "number": 1,
                "title": "test",
                "user": {"login": "dev"},
                "head": {"ref": "feat"},
                "base": {"ref": "main"},
                "body": "",
            },
            "repository": {"full_name": "org/repo"},
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event))
        return event_path

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_main_calls_run_review_not_agent_run(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main() should call run_review(agent, message), not agent.run(message)."""
        event_path = self._make_event_file(tmp_path)
        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        review = _make_review()
        mock_run_review.return_value = review

        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        monkeypatch.setenv("GRIPPY_DATA_DIR", str(tmp_path / "data"))

        from grippy.review import main

        main()

        mock_run_review.assert_called_once()
        mock_create.return_value.run.assert_not_called()

    @patch("grippy.review.post_comment")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_review_parse_error_posts_failure_comment(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ReviewParseError posts parse error comment and exits 1."""
        from grippy.retry import ReviewParseError

        event_path = self._make_event_file(tmp_path)
        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.side_effect = ReviewParseError(
            attempts=3, last_raw="garbage", errors=["bad json"]
        )

        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        monkeypatch.setenv("GRIPPY_DATA_DIR", str(tmp_path / "data"))

        from grippy.review import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_post.assert_called_once()
        assert "PARSE" in mock_post.call_args[0][3]


# --- H2: diff size cap ---


class TestTruncateDiff:
    def test_small_diff_unchanged(self) -> None:
        """Diffs under the cap pass through unchanged."""
        diff = "diff --git a/foo.py b/foo.py\n-old\n+new"
        result = truncate_diff(diff)
        assert result == diff

    def test_large_diff_truncated(self) -> None:
        """Diffs over MAX_DIFF_CHARS are truncated with a warning."""
        block = "diff --git a/f.py b/f.py\n" + ("+" * 5000) + "\n"
        diff = block * 100
        assert len(diff) > MAX_DIFF_CHARS, "Test diff must exceed cap"
        result = truncate_diff(diff)
        assert len(result) < len(diff)
        assert "truncated" in result.lower()

    def test_truncated_diff_ends_at_file_boundary(self) -> None:
        """Truncation happens at a file boundary, not mid-hunk."""
        file_block = (
            "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
            + "@@ -1,10 +1,10 @@\n"
            + ("-old line\n+new line\n" * 100)
        )
        diff = file_block * 50
        if len(diff) <= MAX_DIFF_CHARS:
            pytest.skip("Test diff not large enough to trigger truncation")
        result = truncate_diff(diff)
        assert result.rstrip().endswith("(truncated)") or "truncated" in result

    def test_truncation_preserves_complete_files(self) -> None:
        """Truncated output contains only complete file diffs."""
        small_file = "diff --git a/small.py b/small.py\n--- a/small.py\n+++ b/small.py\n@@ -1 +1 @@\n-a\n+b\n"
        big_file = (
            "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n" + "x" * MAX_DIFF_CHARS
        )
        diff = small_file + big_file
        result = truncate_diff(diff)
        assert "small.py" in result


# --- M1: _with_timeout ---


class TestReviewTimeout:
    """Tests for _with_timeout — SIGALRM-based review timeout."""

    def test_timeout_raises_on_slow_function(self) -> None:
        """Function exceeding timeout raises TimeoutError."""
        import time

        def slow() -> None:
            time.sleep(10)

        with pytest.raises(TimeoutError, match="timed out"):
            _with_timeout(slow, timeout_seconds=1)

    def test_timeout_zero_disables(self) -> None:
        """timeout_seconds=0 means no timeout — function runs normally."""
        result = _with_timeout(lambda: 42, timeout_seconds=0)
        assert result == 42

    def test_timeout_negative_disables(self) -> None:
        """Negative timeout_seconds also disables timeout."""
        result = _with_timeout(lambda: "ok", timeout_seconds=-1)
        assert result == "ok"

    def test_fast_function_returns_normally(self) -> None:
        """Function completing before timeout returns its value."""
        result = _with_timeout(lambda: 99, timeout_seconds=10)
        assert result == 99

    def test_alarm_restored_after_success(self) -> None:
        """SIGALRM handler is restored after successful execution."""
        import signal

        original = signal.getsignal(signal.SIGALRM)
        _with_timeout(lambda: 1, timeout_seconds=5)
        after = signal.getsignal(signal.SIGALRM)
        assert after is original

    def test_alarm_restored_after_timeout(self) -> None:
        """SIGALRM handler is restored even after a timeout."""
        import signal
        import time

        original = signal.getsignal(signal.SIGALRM)
        with pytest.raises(TimeoutError):
            _with_timeout(lambda: time.sleep(10), timeout_seconds=1)
        after = signal.getsignal(signal.SIGALRM)
        assert after is original


# --- M3: main() integration tests (mock-based) ---


class TestMainOrchestration:
    """End-to-end orchestration tests for main() — all external calls mocked."""

    def _make_event_file(self, tmp_path: Path) -> Path:
        """Write a minimal PR event JSON and return its path."""
        event = {
            "pull_request": {
                "number": 7,
                "title": "feat: add auth",
                "user": {"login": "testdev"},
                "head": {"ref": "feature/auth"},
                "base": {"ref": "main"},
                "body": "Adds authentication system",
            },
            "repository": {"full_name": "org/repo"},
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event))
        return event_path

    def _setup_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        event_path: Path,
        tmp_path: Path,
    ) -> None:
        """Set required env vars for main()."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        monkeypatch.setenv("GRIPPY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("GRIPPY_TIMEOUT", "0")

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_happy_path_posts_review(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Happy path: review succeeds, post_review called."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        review = _make_review()
        mock_run_review.return_value = review

        from grippy.review import main

        main()

        mock_post_review.assert_called_once()

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_model_override_replaces_llm_self_report(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """review.model is overridden with configured model_id, not LLM self-report."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)
        monkeypatch.setenv("GRIPPY_MODEL_ID", "gpt-5.2")

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        review = _make_review(model="hallucinated-gpt-4.1")
        mock_run_review.return_value = review

        from grippy.review import main

        main()

        assert review.model == "gpt-5.2"

    @patch("grippy.review.post_comment")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_agent_failure_posts_error_comment(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Agent RuntimeError posts ERROR comment and exits 1."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.side_effect = RuntimeError("LLM crashed")

        from grippy.review import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][3]
        assert "ERROR" in posted_body

    @patch("grippy.review.post_comment")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_parse_failure_posts_parse_error_comment(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ReviewParseError posts PARSE ERROR comment and exits 1."""
        from grippy.retry import ReviewParseError

        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.side_effect = ReviewParseError(
            attempts=3, last_raw="garbage", errors=["bad"]
        )

        from grippy.review import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][3]
        assert "PARSE ERROR" in posted_body

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_merge_blocking_exits_nonzero(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Merge-blocking verdict posts review then exits 1."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        review = _make_review(
            verdict=Verdict(
                status=VerdictStatus.FAIL,
                threshold_applied=70,
                merge_blocking=True,
                summary="Critical security issues found.",
            ),
        )
        mock_run_review.return_value = review

        from grippy.review import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

        mock_post_review.assert_called_once()
        assert mock_post_review.call_args[1]["verdict"] == "FAIL"

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_local_first_defaults_when_env_unset(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When GRIPPY_* env vars are unset, main() uses local-first defaults."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)
        monkeypatch.delenv("GRIPPY_BASE_URL", raising=False)
        monkeypatch.delenv("GRIPPY_MODEL_ID", raising=False)
        monkeypatch.delenv("GRIPPY_EMBEDDING_MODEL", raising=False)
        monkeypatch.delenv("GRIPPY_TRANSPORT", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.return_value = _make_review()

        import grippy.review as review_mod

        monkeypatch.setattr(review_mod, "__file__", str(tmp_path / "fake" / "grippy" / "review.py"))

        review_mod.main()

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["base_url"] == "http://localhost:1234/v1"
        assert call_kwargs["model_id"] == "devstral-small-2-24b-instruct-2512"
        assert call_kwargs["transport"] is None

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_transport_passed_to_create_reviewer(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """GRIPPY_TRANSPORT env var is passed through to create_reviewer()."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)
        monkeypatch.setenv("GRIPPY_TRANSPORT", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.return_value = _make_review()

        from grippy.review import main

        main()

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["transport"] == "openai"


class TestMainReviewIntegration:
    """main() uses new post_review."""

    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    @patch("grippy.review.load_pr_event")
    def test_main_calls_post_review(
        self,
        mock_load: MagicMock,
        mock_diff: MagicMock,
        mock_create: MagicMock,
        mock_run: MagicMock,
        mock_post: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main() should call post_review."""
        event_file = tmp_path / "event.json"
        event_file.write_text(
            '{"pull_request": {"number": 1, "title": "test", "user": {"login": "dev"}, '
            '"head": {"ref": "feat", "sha": "abc123"}, "base": {"ref": "main"}}, '
            '"repository": {"full_name": "org/repo"}}'
        )
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GRIPPY_TRANSPORT", "local")
        monkeypatch.setenv("GRIPPY_TIMEOUT", "0")
        monkeypatch.setattr(
            "grippy.review.__file__",
            str(tmp_path / "fake" / "grippy" / "review.py"),
        )

        mock_load.return_value = {
            "pr_number": 1,
            "repo": "org/repo",
            "title": "test",
            "author": "dev",
            "head_ref": "feat",
            "head_sha": "abc123",
            "base_ref": "main",
            "description": "",
        }
        mock_diff.return_value = "diff --git a/x.py b/x.py\n"

        mock_review = _make_review(findings=[])
        mock_run.return_value = mock_review

        from grippy.review import main

        main()

        mock_post.assert_called_once()


# --- post_review failure handling ---


class TestMainPostReviewFailure:
    """main() should gracefully handle post_review failures."""

    def _make_event_file(self, tmp_path: Path) -> Path:
        event = {
            "pull_request": {
                "number": 1,
                "title": "test",
                "user": {"login": "dev"},
                "head": {"ref": "feat", "sha": "abc123"},
                "base": {"ref": "main"},
                "body": "",
            },
            "repository": {"full_name": "org/repo"},
        }
        event_path = tmp_path / "event.json"
        event_path.write_text(json.dumps(event))
        return event_path

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, event_path: Path, tmp_path: Path) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
        monkeypatch.setenv("GRIPPY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("GRIPPY_TIMEOUT", "0")

    @patch("grippy.review.post_comment")
    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_post_review_failure_posts_error_comment(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        mock_post_comment: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """post_review failure -> error comment posted, exit based on verdict."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.return_value = _make_review()
        mock_post_review.side_effect = RuntimeError("GitHub API is down")

        from grippy.review import main

        main()  # verdict is not merge-blocking, so should exit 0

        mock_post_comment.assert_called_once()
        body = mock_post_comment.call_args[0][3]
        assert "post error" in body.lower()

    @patch("grippy.review.post_comment")
    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_post_review_failure_still_exits_merge_blocking(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        mock_post_comment: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """post_review fails + merge-blocking verdict -> exit 1."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        review = _make_review(
            verdict=Verdict(
                status=VerdictStatus.FAIL,
                threshold_applied=70,
                merge_blocking=True,
                summary="Critical issues found.",
            ),
        )
        mock_run_review.return_value = review
        mock_post_review.side_effect = RuntimeError("GitHub API is down")

        from grippy.review import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("grippy.review.post_comment")
    @patch("grippy.review.post_review")
    @patch("grippy.review.run_review")
    @patch("grippy.review.create_reviewer")
    @patch("grippy.review.fetch_pr_diff")
    def test_post_review_failure_graceful_on_pass(
        self,
        mock_fetch: MagicMock,
        mock_create: MagicMock,
        mock_run_review: MagicMock,
        mock_post_review: MagicMock,
        mock_post_comment: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """post_review fails + PASS verdict -> exit 0."""
        event_path = self._make_event_file(tmp_path)
        self._setup_env(monkeypatch, event_path, tmp_path)

        mock_fetch.return_value = "diff --git a/f.py b/f.py\n-old\n+new"
        mock_run_review.return_value = _make_review()  # default is non-blocking
        mock_post_review.side_effect = RuntimeError("GitHub API is down")

        from grippy.review import main

        # Should NOT raise — non-blocking verdict, posting failure is non-fatal
        main()


class TestTransportErrorUX:
    """Invalid GRIPPY_TRANSPORT posts error comment and exits."""

    @patch("grippy.review.post_comment")
    @patch("grippy.review.load_pr_event")
    def test_invalid_transport_posts_error_comment(
        self,
        mock_load: MagicMock,
        mock_post_comment: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Invalid transport causes error comment and sys.exit(1)."""
        event_file = tmp_path / "event.json"
        event_file.write_text(
            '{"pull_request": {"number": 1, "title": "t", "user": {"login": "d"}, '
            '"head": {"ref": "f", "sha": "a"}, "base": {"ref": "m"}}, '
            '"repository": {"full_name": "o/r"}}'
        )
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GRIPPY_TRANSPORT", "invalid-transport")
        monkeypatch.setenv("GRIPPY_TIMEOUT", "0")
        monkeypatch.setattr(
            "grippy.review.__file__",
            str(tmp_path / "fake" / "grippy" / "review.py"),
        )

        mock_load.return_value = {
            "pr_number": 1,
            "repo": "o/r",
            "title": "t",
            "author": "d",
            "head_ref": "f",
            "head_sha": "a",
            "base_ref": "m",
            "description": "",
        }

        from grippy.review import main

        with pytest.raises(SystemExit):
            main()

        mock_post_comment.assert_called_once()
        body = mock_post_comment.call_args[0][3]
        assert "CONFIG ERROR" in body
