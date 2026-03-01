# SPDX-License-Identifier: MIT
"""Grippy agent factory — builds Agno agents for each review mode."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.openai.like import OpenAILike

from grippy.prompts import load_identity, load_instructions
from grippy.schema import GrippyReview

DEFAULT_PROMPTS_DIR = Path(__file__).parent / "prompts_data"


def _escape_xml(text: str) -> str:
    """Escape XML delimiters to prevent prompt injection via PR metadata."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_VALID_TRANSPORTS = {"openai", "local"}


def _resolve_transport(
    transport: str | None,
    model_id: str,
) -> tuple[str, str]:
    """Resolve transport mode via three-tier priority.

    Resolution order:
        1. Explicit ``transport`` parameter
        2. ``GRIPPY_TRANSPORT`` environment variable
        3. Infer from ``OPENAI_API_KEY`` presence (with warning)

    Returns:
        (transport, source) — e.g. ("openai", "param") or ("local", "env:GRIPPY_TRANSPORT").

    Raises:
        ValueError: If transport value is not "openai" or "local".
    """
    resolved: str | None = None
    source = "default"

    # Tier 1: explicit parameter
    if transport is not None:
        resolved = transport.strip().lower()
        source = "param"

    # Tier 2: environment variable
    if resolved is None:
        env_transport = os.environ.get("GRIPPY_TRANSPORT")
        if env_transport:
            resolved = env_transport.strip().lower()
            source = "env:GRIPPY_TRANSPORT"

    # Tier 3: infer from OPENAI_API_KEY
    if resolved is None:
        if os.environ.get("OPENAI_API_KEY"):
            print(
                f"::notice::Grippy transport inferred from OPENAI_API_KEY. "
                f"Set GRIPPY_TRANSPORT=openai to make this explicit. model={model_id}"
            )
            resolved = "openai"
            source = "inferred:OPENAI_API_KEY"
        else:
            resolved = "local"

    # Validate
    if resolved not in _VALID_TRANSPORTS:
        msg = (
            f"Invalid GRIPPY_TRANSPORT={resolved!r} (source: {source}). "
            f"Must be one of: {', '.join(sorted(_VALID_TRANSPORTS))}"
        )
        raise ValueError(msg)

    return resolved, source


def create_reviewer(
    *,
    model_id: str = "devstral-small-2-24b-instruct-2512",
    base_url: str = "http://localhost:1234/v1",
    api_key: str = "lm-studio",
    transport: str | None = None,
    prompts_dir: Path | str = DEFAULT_PROMPTS_DIR,
    mode: str = "pr_review",
    # Phase 1 additions
    db_path: Path | str | None = None,
    session_id: str | None = None,
    num_history_runs: int = 3,
    additional_context: str | None = None,
    # Phase 3: codebase search
    tools: list[Any] | None = None,
    tool_call_limit: int | None = None,
    # Security rule engine
    include_rule_findings: bool = False,
) -> Agent:
    """Create a Grippy review agent.

    Args:
        model_id: Model identifier at the inference endpoint.
        base_url: OpenAI-compatible API base URL (ignored when transport="openai").
        api_key: API key (LM Studio accepts any non-empty string).
        transport: "openai" or "local". "openai" uses OpenAIChat (reads
            OPENAI_API_KEY from env), "local" uses OpenAILike with explicit
            base_url/api_key. If None, resolved via GRIPPY_TRANSPORT env var
            or inferred from OPENAI_API_KEY presence. Invalid values raise
            ValueError.
        prompts_dir: Directory containing Grippy's 21 markdown prompt files.
        mode: Review mode — pr_review, security_audit, governance_check,
            surprise_audit, cli, github_app.
        db_path: Path to SQLite file for session persistence. None = stateless.
        session_id: Session ID for review continuity across runs.
        num_history_runs: Number of prior runs to include in context (requires db).
        additional_context: Extra context appended to the system message.
        tools: Optional list of Agno Toolkit instances for agent tool use.
        tool_call_limit: Max tool calls per run. None = unlimited.

    Returns:
        Configured Agno Agent with Grippy's prompt chain and structured output schema.
    """
    prompts_dir = Path(prompts_dir)

    # Build optional kwargs — only pass to Agent when configured
    kwargs: dict[str, Any] = {}
    if db_path is not None:
        from agno.db.sqlite import SqliteDb

        kwargs["db"] = SqliteDb(db_file=str(db_path))
        kwargs["add_history_to_context"] = True
        kwargs["num_history_runs"] = num_history_runs
    if session_id is not None:
        kwargs["session_id"] = session_id
    if additional_context is not None:
        kwargs["additional_context"] = additional_context
    if tools is not None:
        kwargs["tools"] = tools
    if tool_call_limit is not None:
        kwargs["tool_call_limit"] = tool_call_limit

    # Resolve transport via three-tier priority
    resolved_transport, source = _resolve_transport(transport, model_id)
    print(f"::notice::Grippy transport={resolved_transport} model={model_id} (source: {source})")

    if resolved_transport == "openai":
        model = OpenAIChat(id=model_id)
    else:
        model = OpenAILike(id=model_id, api_key=api_key, base_url=base_url)

    return Agent(
        name="grippy",
        model=model,
        description=load_identity(prompts_dir),
        instructions=load_instructions(
            prompts_dir,
            mode=mode,
            include_rule_findings=include_rule_findings,
        ),
        output_schema=GrippyReview,
        markdown=False,
        **kwargs,
    )


def format_pr_context(
    *,
    title: str,
    author: str,
    branch: str,
    description: str = "",
    diff: str,
    labels: str = "",
    file_context: str = "",
    governance_rules: str = "",
    learnings: str = "",
    rule_findings: str = "",
) -> str:
    """Format PR context as the user message, matching pr-review.md input format."""
    sections = []

    if governance_rules:
        sections.append(f"<governance_rules>\n{governance_rules}\n</governance_rules>")

    # Count diff stats
    additions = diff.count("\n+") - diff.count("\n+++")
    deletions = diff.count("\n-") - diff.count("\n---")
    changed_files = diff.count("diff --git")

    sections.append(
        f"<pr_metadata>\n"
        f"Title: {_escape_xml(title)}\n"
        f"Author: {_escape_xml(author)}\n"
        f"Branch: {_escape_xml(branch)}\n"
        f"Description: {_escape_xml(description)}\n"
        f"Labels: {labels}\n"
        f"Changed Files: {changed_files}\n"
        f"Additions: {additions}\n"
        f"Deletions: {deletions}\n"
        f"</pr_metadata>"
    )

    sections.append(f"<diff>\n{diff}\n</diff>")

    if file_context:
        sections.append(f"<file_context>\n{file_context}\n</file_context>")

    if learnings:
        sections.append(f"<learnings>\n{learnings}\n</learnings>")

    if rule_findings:
        sections.append(f"<rule_findings>\n{rule_findings}\n</rule_findings>")

    return "\n\n".join(sections)
