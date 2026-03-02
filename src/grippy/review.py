# SPDX-License-Identifier: MIT
"""Grippy CI review entry point — reads PR event, runs agent, posts comment.

Usage (GitHub Actions):
    python -m grippy.review

Environment variables:
    GITHUB_TOKEN            — GitHub API token for fetching diff and posting comments
    GITHUB_EVENT_PATH       — path to PR event JSON (set by GitHub Actions)
    OPENAI_API_KEY          — OpenAI API key (or unset for local endpoints)
    GRIPPY_BASE_URL         — API endpoint (default: http://localhost:1234/v1)
    GRIPPY_MODEL_ID         — model identifier (default: devstral-small-2-24b-instruct-2512)
    GRIPPY_EMBEDDING_MODEL  — embedding model (default: text-embedding-qwen3-embedding-4b)
    GRIPPY_TRANSPORT        — "openai" or "local" (default: infer from OPENAI_API_KEY)
    GRIPPY_API_KEY          — API key for non-OpenAI endpoints (embedding auth fallback)
    GRIPPY_DATA_DIR         — persistent directory for graph DB + LanceDB
    GRIPPY_TIMEOUT          — seconds before review is killed (0 = no timeout)
    GITHUB_REPOSITORY       — owner/repo (set by GitHub Actions, fallback)
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import navi_sanitize

from grippy.agent import create_reviewer, format_pr_context
from grippy.embedder import create_embedder
from grippy.github_review import post_review
from grippy.retry import ReviewParseError, run_review
from grippy.rules import RuleResult, RuleSeverity, check_gate, load_profile, run_rules

# Max diff size sent to the LLM — ~500K chars ≈ 125K tokens
MAX_DIFF_CHARS = 500_000


_ERROR_HINTS: dict[str, str] = {
    "CONFIG ERROR": "Valid `GRIPPY_TRANSPORT` values: `openai`, `local`.",
    "TIMEOUT": "Increase `GRIPPY_TIMEOUT` or reduce PR diff size.",
}


def _failure_comment(repo: str, error_type: str) -> str:
    """Build a generic error comment for posting to a PR."""
    hint = _ERROR_HINTS.get(error_type, "")
    hint_line = f"\n\n{hint}" if hint else ""
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if run_id:
        log_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    else:
        log_url = f"https://github.com/{repo}/actions"
    return (
        f"## \u274c Grippy Review \u2014 {error_type}\n\n"
        f"Review failed. Check the [Actions log]({log_url}) for details."
        f"{hint_line}\n\n"
        "<!-- grippy-error -->"
    )


def load_pr_event(event_path: Path) -> dict[str, Any]:
    """Parse GitHub Actions pull_request event payload.

    Returns:
        Dict with keys: pr_number, repo, title, author, head_ref, head_sha, base_ref, description.

    Raises:
        FileNotFoundError: If event_path doesn't exist.
        KeyError: If event JSON lacks pull_request key.
    """
    data = json.loads(event_path.read_text(encoding="utf-8"))
    pr = data["pull_request"]
    return {
        "pr_number": pr["number"],
        "repo": data["repository"]["full_name"],
        "title": pr["title"],
        "author": pr["user"]["login"],
        "head_ref": pr["head"]["ref"],
        "head_sha": pr["head"].get("sha", ""),
        "base_ref": pr["base"]["ref"],
        "description": pr.get("body") or "",
    }


def truncate_diff(diff: str, max_chars: int = MAX_DIFF_CHARS) -> str:
    """Truncate diff at file boundaries if it exceeds max_chars.

    Splits on 'diff --git' markers and includes complete files until the
    budget is exhausted. Appends a truncation warning.
    """
    if len(diff) <= max_chars:
        return diff

    # Split into per-file blocks
    parts = diff.split("diff --git ")
    # First element is empty or preamble
    preamble = parts[0]
    file_blocks = [f"diff --git {p}" for p in parts[1:]]

    kept: list[str] = []
    total = len(preamble)
    for block in file_blocks:
        if total + len(block) > max_chars and kept:
            break
        kept.append(block)
        total += len(block)

    truncated_count = len(file_blocks) - len(kept)
    result = preamble + "".join(kept)
    if truncated_count > 0:
        result += f"\n\n... {truncated_count} file(s) truncated (diff exceeded {max_chars} chars) (truncated)"
    return result


def fetch_pr_diff(token: str, repo: str, pr_number: int) -> str:
    """Fetch complete PR diff via GitHub API raw diff endpoint.

    Uses Accept: application/vnd.github.v3.diff to get the full unified
    diff in a single request — no pagination issues.
    """
    import requests

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.diff",
    }
    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()
    return response.text


def post_comment(token: str, repo: str, pr_number: int, body: str) -> None:
    """Post an error/status comment on a PR (used for error paths only)."""
    from github import Github

    gh = Github(token)
    repository = gh.get_repo(repo)
    pr = repository.get_pull(pr_number)
    pr.create_issue_comment(body)


def _with_timeout(fn: Callable[[], Any], *, timeout_seconds: int) -> Any:
    """Run *fn* with a SIGALRM timeout (Linux only).  0 = no timeout."""
    if timeout_seconds <= 0:
        return fn()

    import signal

    def _handler(signum: int, frame: Any) -> None:
        msg = f"Review timed out after {timeout_seconds}s"
        raise TimeoutError(msg)

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout_seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


_SEVERITY_MAP: dict[RuleSeverity, str] = {
    RuleSeverity.CRITICAL: "CRITICAL",
    RuleSeverity.ERROR: "ERROR",
    RuleSeverity.WARN: "WARN",
    RuleSeverity.INFO: "INFO",
}


def _escape_rule_field(text: str) -> str:
    """Sanitize and escape rule finding fields to prevent prompt injection.

    Pipeline: navi-sanitize (invisible chars, bidi, homoglyphs, NFKC) →
    XML delimiter escaping. Crafted filenames or evidence strings could
    contain Unicode obfuscation or XML payloads — both are neutralized.
    """
    text = navi_sanitize.clean(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_rule_findings(results: list[RuleResult]) -> str:
    """Format rule findings as text for the LLM context."""
    lines: list[str] = []
    for r in results:
        sev = _SEVERITY_MAP.get(r.severity, "INFO")
        file_safe = _escape_rule_field(r.file)
        msg_safe = _escape_rule_field(r.message)
        parts = [f"[{sev}] {r.rule_id} @ {file_safe}"]
        if r.line is not None:
            parts[0] += f":{r.line}"
        parts[0] += f": {msg_safe}"
        if r.evidence:
            parts.append(f"  evidence: {_escape_rule_field(r.evidence)}")
        lines.append(" | ".join(parts) if r.evidence else parts[0])
    return "\n".join(lines)


def main(*, profile: str | None = None) -> None:
    """CI entry point — reads env, runs review, posts comment."""
    # Load .dev.vars if present (local dev)
    dev_vars_path = Path(__file__).resolve().parent.parent.parent / ".dev.vars"
    if dev_vars_path.is_file():
        for line in dev_vars_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    # Required env
    token = os.environ.get("GITHUB_TOKEN", "")
    event_path_str = os.environ.get("GITHUB_EVENT_PATH", "")
    base_url = os.environ.get("GRIPPY_BASE_URL", "http://localhost:1234/v1")
    model_id = os.environ.get("GRIPPY_MODEL_ID", "devstral-small-2-24b-instruct-2512")
    api_key = os.environ.get("GRIPPY_API_KEY", "lm-studio")
    transport = os.environ.get("GRIPPY_TRANSPORT") or None
    mode = os.environ.get("GRIPPY_MODE", "pr_review")
    timeout_seconds = int(os.environ.get("GRIPPY_TIMEOUT", "300"))

    if not token:
        print("::error::GITHUB_TOKEN not set")
        sys.exit(1)
    if not event_path_str:
        print("::error::GITHUB_EVENT_PATH not set")
        sys.exit(1)

    event_path = Path(event_path_str)
    if not event_path.is_file():
        print(f"::error::Event file not found: {event_path}")
        sys.exit(1)

    # 1. Parse event
    print("=== Grippy Review ===")
    pr_event = load_pr_event(event_path)
    safe_title = pr_event["title"].replace("\n", " ").replace("\r", " ")
    print(
        f"PR #{pr_event['pr_number']}: {safe_title} "
        f"({pr_event['head_ref']} → {pr_event['base_ref']})"
    )

    # 2. Validate transport early (before expensive diff fetch)
    from grippy.agent import _resolve_transport

    try:
        _resolve_transport(transport, model_id)
    except ValueError as exc:
        print(f"::error::Invalid configuration: {exc}")
        post_comment(
            token,
            pr_event["repo"],
            pr_event["pr_number"],
            _failure_comment(pr_event["repo"], "CONFIG ERROR"),
        )
        sys.exit(1)

    data_dir_str = os.environ.get("GRIPPY_DATA_DIR", "./grippy-data")
    embedding_model = os.environ.get("GRIPPY_EMBEDDING_MODEL", "text-embedding-qwen3-embedding-4b")
    data_dir = Path(data_dir_str)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 2a. Build codebase index for tool-augmented review (non-fatal)
    codebase_tools: list[Any] = []
    workspace = os.environ.get("GITHUB_WORKSPACE", "")
    if workspace:
        try:
            from grippy.codebase import CodebaseIndex, CodebaseToolkit

            cb_embedder = create_embedder(
                transport=transport or "local",
                model=embedding_model,
                base_url=base_url,
                api_key=api_key,
            )
            lance_dir = data_dir / "lance"
            lance_dir.mkdir(parents=True, exist_ok=True)
            import lancedb  # type: ignore[import-untyped]

            lance_db = lancedb.connect(str(lance_dir))
            cb_index = CodebaseIndex(
                repo_root=Path(workspace),
                lance_db=lance_db,
                embedder=cb_embedder,
            )
            if not cb_index.is_indexed:
                print("Indexing codebase...")
                chunk_count = cb_index.build()
                print(f"  Indexed {chunk_count} chunks")
            else:
                print("Codebase index found (cached)")
            codebase_tools = [CodebaseToolkit(index=cb_index, repo_root=Path(workspace))]
        except Exception as exc:
            print(f"::warning::Codebase indexing failed (non-fatal): {exc}")

    # 3. Fetch diff (graceful 403 handling for fork PRs)
    print("Fetching PR diff...")
    try:
        diff = fetch_pr_diff(token, pr_event["repo"], pr_event["pr_number"])
    except Exception as exc:
        print(f"::error::Failed to fetch PR diff: {exc}")
        if "403" in str(exc):
            print(
                "::error::The token may lack access to this fork's diff. "
                "Ensure the GITHUB_TOKEN has read access to the fork, "
                "or use a PAT with `contents: read` scope."
            )
        try:
            post_comment(
                token,
                pr_event["repo"],
                pr_event["pr_number"],
                _failure_comment(pr_event["repo"], "DIFF ERROR"),
            )
        except Exception:
            pass  # nosec B110 — best-effort, don't mask the original error
        sys.exit(1)
    file_count = diff.count("diff --git")
    print(f"  {file_count} files, {len(diff)} chars")

    # 3b. Run security rule engine on FULL diff (before truncation)
    try:
        profile_config = load_profile(cli_profile=profile)
    except ValueError as exc:
        print(f"::error::Invalid profile: {exc}")
        post_comment(
            token,
            pr_event["repo"],
            pr_event["pr_number"],
            _failure_comment(pr_event["repo"], "CONFIG ERROR"),
        )
        sys.exit(1)

    rule_findings: list[RuleResult] = []
    rule_gate_failed = False
    expected_rule_counts: dict[str, int] | None = None
    rule_findings_text = ""

    if profile_config.name != "general":
        print(f"Running rule engine (profile={profile_config.name})...")
        rule_findings = run_rules(diff, profile_config)
        rule_gate_failed = check_gate(rule_findings, profile_config)
        print(f"  {len(rule_findings)} findings, gate={'FAILED' if rule_gate_failed else 'passed'}")
        if rule_findings:
            rule_findings_text = _format_rule_findings(rule_findings)
            expected_rule_counts = dict(Counter(r.rule_id for r in rule_findings))
        mode = "security_audit"

    # H2: cap diff size to avoid overflowing LLM context (after rule engine)
    original_len = len(diff)
    diff = truncate_diff(diff)
    diff_truncated = len(diff) < original_len
    if diff_truncated:
        print(f"  Diff truncated to {MAX_DIFF_CHARS} chars ({file_count} files in original)")

    # 3c. Create agent (after rule engine, so mode/rule_findings are resolved)
    try:
        agent = create_reviewer(
            model_id=model_id,
            base_url=base_url,
            api_key=api_key,
            transport=transport,
            mode=mode,
            db_path=data_dir / "grippy-session.db",
            session_id=f"pr-{pr_event['pr_number']}",
            tools=codebase_tools or None,
            tool_call_limit=10 if codebase_tools else None,
            include_rule_findings=bool(rule_findings),
        )
    except ValueError as exc:
        print(f"::error::Invalid configuration: {exc}")
        post_comment(
            token,
            pr_event["repo"],
            pr_event["pr_number"],
            _failure_comment(pr_event["repo"], "CONFIG ERROR"),
        )
        sys.exit(1)

    # 4. Format context
    user_message = format_pr_context(
        title=pr_event["title"],
        author=pr_event["author"],
        branch=f"{pr_event['head_ref']} → {pr_event['base_ref']}",
        description=pr_event["description"],
        diff=diff,
        rule_findings=rule_findings_text,
    )

    # 5. Run review with retry + validation (replaces agent.run + parse_review_response)
    print("Running review...")
    try:
        review = _with_timeout(
            lambda: run_review(agent, user_message, expected_rule_counts=expected_rule_counts),
            timeout_seconds=timeout_seconds,
        )
    except ReviewParseError as exc:
        print(f"::error::Grippy review failed after {exc.attempts} attempts: {exc}")
        try:
            post_comment(
                token,
                pr_event["repo"],
                pr_event["pr_number"],
                _failure_comment(pr_event["repo"], "PARSE ERROR"),
            )
        except Exception:
            pass  # nosec B110 — best-effort error posting
        sys.exit(1)
    except TimeoutError as exc:
        print(f"::error::Grippy review timed out: {exc}")
        try:
            post_comment(
                token,
                pr_event["repo"],
                pr_event["pr_number"],
                _failure_comment(pr_event["repo"], "TIMEOUT"),
            )
        except Exception:
            pass  # nosec B110 — best-effort error posting
        sys.exit(1)
    except Exception as exc:
        print(f"::error::Grippy agent failed: {exc}")
        try:
            post_comment(
                token,
                pr_event["repo"],
                pr_event["pr_number"],
                _failure_comment(pr_event["repo"], "ERROR"),
            )
        except Exception:
            pass  # nosec B110 — best-effort error posting
        sys.exit(1)

    # Override self-reported model — LLMs hallucinate their own model name
    review.model = model_id

    print(f"  Score: {review.score.overall}/100 — {review.verdict.status.value}")
    print(f"  Findings: {len(review.findings)}")

    # 6. Post review — GitHub owns finding lifecycle
    head_sha = pr_event.get("head_sha", "")
    print("Posting review...")
    try:
        post_review(
            token=token,
            repo=pr_event["repo"],
            pr_number=pr_event["pr_number"],
            findings=review.findings,
            head_sha=head_sha,
            diff=diff,
            score=review.score.overall,
            verdict=review.verdict.status.value,
            diff_truncated=diff_truncated,
        )
        print("  Done.")
    except Exception as exc:
        print(f"::warning::Failed to post review: {exc}")
        try:
            post_comment(
                token,
                pr_event["repo"],
                pr_event["pr_number"],
                _failure_comment(pr_event["repo"], "POST ERROR"),
            )
        except Exception:
            pass  # nosec B110 — best-effort error posting

    # 7. Set outputs for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"score={review.score.overall}\n")
            f.write(f"verdict={review.verdict.status.value}\n")
            f.write(f"findings-count={len(review.findings)}\n")
            f.write(f"merge-blocking={str(review.verdict.merge_blocking).lower()}\n")
            f.write(f"rule-findings-count={len(rule_findings)}\n")
            f.write(f"rule-gate-failed={str(rule_gate_failed).lower()}\n")
            f.write(f"profile={profile_config.name}\n")

    # Exit non-zero if merge-blocking or rule gate failed
    if rule_gate_failed:
        print(f"::warning::Rule gate FAILED (profile={profile_config.name})")
        sys.exit(1)
    if review.verdict.merge_blocking:
        print(f"::warning::Review verdict: {review.verdict.status.value} (merge-blocking)")
        sys.exit(1)


if __name__ == "__main__":
    main()
