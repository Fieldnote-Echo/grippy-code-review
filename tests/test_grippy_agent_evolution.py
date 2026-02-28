# SPDX-License-Identifier: MIT
"""Tests for Grippy agent evolution — new create_reviewer() parameters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from grippy.agent import _resolve_transport, create_reviewer, format_pr_context

# Default prompts dir for all tests
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "src" / "grippy" / "prompts_data"


# --- Backward compatibility ---


class TestCreateReviewerBackwardCompat:
    """Existing create_reviewer() API must still work unchanged."""

    def test_basic_call_returns_agent(self) -> None:
        """Calling with original params returns an Agent."""
        agent = create_reviewer(prompts_dir=PROMPTS_DIR, mode="pr_review")
        assert agent.name == "grippy"

    def test_default_no_db(self) -> None:
        """Without db_path, agent has no db configured."""
        agent = create_reviewer(prompts_dir=PROMPTS_DIR)
        assert agent.db is None

    def test_all_modes_work(self) -> None:
        """All six review modes produce valid agents."""
        for mode in (
            "pr_review",
            "security_audit",
            "governance_check",
            "surprise_audit",
            "cli",
            "github_app",
        ):
            agent = create_reviewer(prompts_dir=PROMPTS_DIR, mode=mode)
            assert agent.name == "grippy"


# --- Session persistence ---


class TestSessionPersistence:
    def test_db_path_creates_sqlite_session(self, tmp_path: Path) -> None:
        """Providing db_path wires up SqliteDb for session persistence."""
        db_path = tmp_path / "grippy-session.db"
        agent = create_reviewer(
            prompts_dir=PROMPTS_DIR,
            db_path=db_path,
        )
        assert agent.db is not None

    def test_session_id_passed_through(self, tmp_path: Path) -> None:
        """session_id is set on the agent for review continuity."""
        agent = create_reviewer(
            prompts_dir=PROMPTS_DIR,
            db_path=tmp_path / "session.db",
            session_id="pr-123-review",
        )
        assert agent.session_id == "pr-123-review"

    def test_num_history_runs_configured(self, tmp_path: Path) -> None:
        """num_history_runs controls how many prior runs are in context."""
        agent = create_reviewer(
            prompts_dir=PROMPTS_DIR,
            db_path=tmp_path / "session.db",
            num_history_runs=5,
        )
        assert agent.num_history_runs == 5

    def test_default_num_history_runs(self, tmp_path: Path) -> None:
        """Default num_history_runs is 3 when db is configured."""
        agent = create_reviewer(
            prompts_dir=PROMPTS_DIR,
            db_path=tmp_path / "session.db",
        )
        assert agent.num_history_runs == 3

    def test_history_enabled_with_db(self, tmp_path: Path) -> None:
        """add_history_to_context is True when db is configured."""
        agent = create_reviewer(
            prompts_dir=PROMPTS_DIR,
            db_path=tmp_path / "session.db",
        )
        assert agent.add_history_to_context is True

    def test_history_disabled_without_db(self) -> None:
        """add_history_to_context stays False when no db."""
        agent = create_reviewer(prompts_dir=PROMPTS_DIR)
        assert agent.add_history_to_context is not True


# --- Context injection ---


class TestContextInjection:
    def test_additional_context_passed_to_agent(self) -> None:
        """additional_context string is wired into the agent."""
        ctx = "Codebase: navi-bootstrap. Author: nelson. Conventions: use Result types."
        agent = create_reviewer(
            prompts_dir=PROMPTS_DIR,
            additional_context=ctx,
        )
        assert agent.additional_context == ctx

    def test_no_context_by_default(self) -> None:
        """Without additional_context, agent has None."""
        agent = create_reviewer(prompts_dir=PROMPTS_DIR)
        assert agent.additional_context is None


# --- format_pr_context backward compat ---


class TestFormatPrContext:
    """format_pr_context() must continue to work unchanged."""

    def test_basic_formatting(self) -> None:
        result = format_pr_context(
            title="feat: add auth",
            author="testdev",
            branch="feature/auth → main",
            diff="diff --git a/app.py b/app.py\n+new line\n",
        )
        assert "<pr_metadata>" in result
        assert "feat: add auth" in result
        assert "<diff>" in result

    def test_with_governance_rules(self) -> None:
        result = format_pr_context(
            title="fix: null check",
            author="dev",
            branch="fix → main",
            diff="diff --git a/x.py b/x.py\n",
            governance_rules="Rule 1: always validate",
        )
        assert "<governance_rules>" in result

    def test_diff_stats(self) -> None:
        diff = "diff --git a/x.py b/x.py\n+++ b/x.py\n+added\n-removed\n--- a/x.py\n"
        result = format_pr_context(
            title="test",
            author="dev",
            branch="x → main",
            diff=diff,
        )
        assert "Changed Files: 1" in result


# --- Transport selection ---


class TestTransportSelection:
    """Tests for explicit transport selection (F2 fix)."""

    def test_explicit_local_transport(self) -> None:
        """transport='local' uses OpenAILike regardless of env."""
        agent = create_reviewer(prompts_dir=PROMPTS_DIR, transport="local")
        from agno.models.openai.like import OpenAILike

        assert isinstance(agent.model, OpenAILike)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=False)
    def test_explicit_openai_transport(self) -> None:
        """transport='openai' uses OpenAIChat."""
        agent = create_reviewer(prompts_dir=PROMPTS_DIR, transport="openai")
        from agno.models.openai import OpenAIChat

        assert isinstance(agent.model, OpenAIChat)

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GRIPPY_TRANSPORT env var overrides inference."""
        monkeypatch.setenv("GRIPPY_TRANSPORT", "local")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        transport, source = _resolve_transport(None, "test-model")
        assert transport == "local"
        assert source == "env:GRIPPY_TRANSPORT"

    def test_param_precedence_over_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit param takes precedence over GRIPPY_TRANSPORT env var."""
        monkeypatch.setenv("GRIPPY_TRANSPORT", "openai")
        transport, source = _resolve_transport("local", "test-model")
        assert transport == "local"
        assert source == "param"

    def test_inference_warning_when_no_explicit(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Inferring from OPENAI_API_KEY prints a notice warning."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("GRIPPY_TRANSPORT", raising=False)
        transport, source = _resolve_transport(None, "test-model")
        assert transport == "openai"
        assert "inferred" in source
        captured = capsys.readouterr()
        assert "::notice::" in captured.out

    def test_default_is_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env vars and no param defaults to local transport."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GRIPPY_TRANSPORT", raising=False)
        transport, source = _resolve_transport(None, "test-model")
        assert transport == "local"
        assert source == "default"

    def test_invalid_transport_raises(self) -> None:
        """Invalid transport value raises ValueError."""
        with pytest.raises(ValueError, match="Invalid GRIPPY_TRANSPORT"):
            _resolve_transport("cloud", "test-model")

    def test_typo_transport_raises(self) -> None:
        """Common typos are caught and rejected."""
        for typo in ("open-ai", "remote", "gcp", "aws"):
            with pytest.raises(ValueError, match="Invalid GRIPPY_TRANSPORT"):
                _resolve_transport(typo, "test-model")

    def test_transport_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Transport values are normalized (strip + lowercase)."""
        transport, _ = _resolve_transport("  OPENAI  ", "test-model")
        assert transport == "openai"

    def test_env_transport_normalized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GRIPPY_TRANSPORT env var is normalized."""
        monkeypatch.setenv("GRIPPY_TRANSPORT", "  Local  ")
        transport, source = _resolve_transport(None, "test-model")
        assert transport == "local"
        assert source == "env:GRIPPY_TRANSPORT"

    def test_invalid_env_transport_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid GRIPPY_TRANSPORT env var raises ValueError."""
        monkeypatch.setenv("GRIPPY_TRANSPORT", "gcp")
        with pytest.raises(ValueError, match="Invalid GRIPPY_TRANSPORT"):
            _resolve_transport(None, "test-model")
