# SPDX-License-Identifier: MIT
"""Tests for Grippy structured output retry wrapper."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from grippy.retry import ReviewParseError, run_review
from grippy.schema import GrippyReview

# --- Fixtures ---

VALID_REVIEW_DICT: dict[str, Any] = {
    "version": "1.0",
    "audit_type": "pr_review",
    "timestamp": "2026-02-26T12:00:00Z",
    "model": "devstral-small-2-24b-instruct-2512",
    "pr": {
        "title": "feat: add auth",
        "author": "testdev",
        "branch": "feature/auth → main",
        "complexity_tier": "STANDARD",
    },
    "scope": {
        "files_in_diff": 3,
        "files_reviewed": 3,
        "coverage_percentage": 100.0,
        "governance_rules_applied": [],
        "modes_active": ["pr_review"],
    },
    "findings": [],
    "escalations": [],
    "score": {
        "overall": 95,
        "breakdown": {
            "security": 100,
            "logic": 90,
            "governance": 95,
            "reliability": 90,
            "observability": 100,
        },
        "deductions": {
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "total_deduction": 5,
        },
    },
    "verdict": {
        "status": "PASS",
        "threshold_applied": 70,
        "merge_blocking": False,
        "summary": "Clean.",
    },
    "personality": {
        "tone_register": "grudging_respect",
        "opening_catchphrase": "Not bad.",
        "closing_line": "Carry on.",
        "ascii_art_key": "all_clear",
    },
    "meta": {
        "review_duration_ms": 30000,
        "tokens_used": 5000,
        "context_files_loaded": 3,
        "confidence_filter_suppressed": 0,
        "duplicate_filter_suppressed": 0,
    },
}


VALID_REVIEW_JSON = json.dumps(VALID_REVIEW_DICT)


def _make_agent_response(content: Any) -> MagicMock:
    """Create a mock agent RunResponse with given content."""
    response = MagicMock()
    response.content = content
    return response


def _mock_agent(*responses: Any) -> MagicMock:
    """Create a mock agent that returns successive responses from run()."""
    agent = MagicMock()
    agent.run = MagicMock(side_effect=[_make_agent_response(r) for r in responses])
    return agent


# --- Successful parsing ---


class TestRunReviewSuccess:
    def test_parses_dict_response(self) -> None:
        """Agent returning a dict is parsed into GrippyReview."""
        agent = _mock_agent(VALID_REVIEW_DICT)
        result = run_review(agent, "Review this PR")
        assert isinstance(result, GrippyReview)
        assert result.score.overall == 95

    def test_parses_json_string_response(self) -> None:
        """Agent returning a JSON string is parsed into GrippyReview."""
        agent = _mock_agent(VALID_REVIEW_JSON)
        result = run_review(agent, "Review this PR")
        assert isinstance(result, GrippyReview)

    def test_parses_model_instance_response(self) -> None:
        """Agent returning a GrippyReview instance passes through."""
        review = GrippyReview.model_validate(VALID_REVIEW_DICT)
        agent = _mock_agent(review)
        result = run_review(agent, "Review this PR")
        assert result is review

    def test_single_call_on_success(self) -> None:
        """Agent is called exactly once when first response is valid."""
        agent = _mock_agent(VALID_REVIEW_DICT)
        run_review(agent, "Review this PR")
        assert agent.run.call_count == 1


# --- Retry on validation error ---


class TestRunReviewRetry:
    def test_retries_on_invalid_json(self) -> None:
        """Invalid JSON triggers retry with error context."""
        agent = _mock_agent("not json at all", VALID_REVIEW_JSON)
        result = run_review(agent, "Review this PR", max_retries=3)
        assert isinstance(result, GrippyReview)
        assert agent.run.call_count == 2

    def test_retries_on_invalid_schema(self) -> None:
        """Valid JSON but invalid schema triggers retry."""
        bad_schema = {"version": "1.0", "audit_type": "pr_review"}  # missing fields
        agent = _mock_agent(bad_schema, VALID_REVIEW_DICT)
        result = run_review(agent, "Review this PR", max_retries=3)
        assert isinstance(result, GrippyReview)
        assert agent.run.call_count == 2

    def test_retry_message_includes_error(self) -> None:
        """Retry prompt includes the validation error details."""
        agent = _mock_agent("broken", VALID_REVIEW_JSON)
        run_review(agent, "Review this PR", max_retries=3)
        # Second call should have error context in the message
        retry_message = agent.run.call_args_list[1][0][0]
        assert "failed" in retry_message.lower() or "error" in retry_message.lower()

    def test_succeeds_after_multiple_retries(self) -> None:
        """Agent can fail multiple times before succeeding."""
        agent = _mock_agent("bad1", "bad2", VALID_REVIEW_JSON)
        result = run_review(agent, "Review this PR", max_retries=3)
        assert isinstance(result, GrippyReview)
        assert agent.run.call_count == 3


# --- Exhausted retries ---


class TestRunReviewExhausted:
    def test_raises_after_max_retries(self) -> None:
        """Raises ReviewParseError after exhausting retries."""
        agent = _mock_agent("bad1", "bad2", "bad3", "bad4")
        with pytest.raises(ReviewParseError):
            run_review(agent, "Review this PR", max_retries=3)

    def test_error_contains_last_raw_output(self) -> None:
        """ReviewParseError includes the last raw output for debugging."""
        agent = _mock_agent("garbage1", "garbage2", "garbage3", "garbage4")
        with pytest.raises(ReviewParseError) as exc_info:
            run_review(agent, "Review this PR", max_retries=3)
        assert "garbage" in str(exc_info.value)

    def test_error_contains_attempt_count(self) -> None:
        """ReviewParseError includes how many attempts were made."""
        agent = _mock_agent("bad", "bad", "bad", "bad")
        with pytest.raises(ReviewParseError) as exc_info:
            run_review(agent, "Review this PR", max_retries=3)
        # Should mention the number of attempts (initial + retries)
        error_str = str(exc_info.value)
        assert "4" in error_str or "3" in error_str

    def test_max_retries_zero_means_no_retry(self) -> None:
        """max_retries=0 means one attempt only, no retries."""
        agent = _mock_agent("bad", VALID_REVIEW_JSON)
        with pytest.raises(ReviewParseError):
            run_review(agent, "Review this PR", max_retries=0)
        assert agent.run.call_count == 1


# --- Callback ---


class TestRunReviewCallback:
    def test_on_validation_error_called(self) -> None:
        """Callback fires on each validation failure."""
        callback = MagicMock()
        agent = _mock_agent("bad", VALID_REVIEW_JSON)
        run_review(agent, "Review this PR", max_retries=3, on_validation_error=callback)
        assert callback.call_count == 1

    def test_callback_receives_attempt_and_error(self) -> None:
        """Callback gets the attempt number and the error."""
        callback = MagicMock()
        agent = _mock_agent("bad1", "bad2", VALID_REVIEW_JSON)
        run_review(agent, "Review this PR", max_retries=3, on_validation_error=callback)
        assert callback.call_count == 2
        # First call: attempt 1
        first_call_args = callback.call_args_list[0]
        assert first_call_args[0][0] == 1  # attempt number
        # Second call: attempt 2
        second_call_args = callback.call_args_list[1]
        assert second_call_args[0][0] == 2

    def test_no_callback_on_success(self) -> None:
        """Callback is not called when first attempt succeeds."""
        callback = MagicMock()
        agent = _mock_agent(VALID_REVIEW_DICT)
        run_review(agent, "Review this PR", max_retries=3, on_validation_error=callback)
        callback.assert_not_called()


# --- Edge cases ---


class TestRunReviewEdgeCases:
    def test_none_content_triggers_retry(self) -> None:
        """Agent returning None content triggers retry."""
        agent = _mock_agent(None, VALID_REVIEW_JSON)
        result = run_review(agent, "Review this PR", max_retries=3)
        assert isinstance(result, GrippyReview)

    def test_empty_string_triggers_retry(self) -> None:
        """Agent returning empty string triggers retry."""
        agent = _mock_agent("", VALID_REVIEW_JSON)
        result = run_review(agent, "Review this PR", max_retries=3)
        assert isinstance(result, GrippyReview)

    def test_json_string_with_markdown_fences(self) -> None:
        """Agent wrapping JSON in markdown code fences is handled."""
        fenced = f"```json\n{VALID_REVIEW_JSON}\n```"
        agent = _mock_agent(fenced)
        result = run_review(agent, "Review this PR")
        assert isinstance(result, GrippyReview)

    def test_default_max_retries_is_three(self) -> None:
        """Default max_retries is 3 (4 total attempts)."""
        agent = _mock_agent("bad", "bad", "bad", "bad")
        with pytest.raises(ReviewParseError):
            run_review(agent, "Review this PR")
        assert agent.run.call_count == 4  # 1 initial + 3 retries
