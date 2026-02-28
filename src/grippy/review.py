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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from grippy.agent import create_reviewer, format_pr_context
from grippy.embedder import create_embedder
from grippy.github_review import post_review
from grippy.graph import FindingStatus, review_to_graph
from grippy.persistence import GrippyStore
from grippy.retry import ReviewParseError, run_review

# Max diff size sent to the LLM — ~200K chars ≈ 50K tokens (H2 fix)
MAX_DIFF_CHARS = 200_000


_ERROR_HINTS: dict[str, str] = {
    "CONFIG ERROR": "Valid `GRIPPY_TRANSPORT` values: `openai`, `local`.",
    "TIMEOUT": "Increase `GRIPPY_TIMEOUT` or reduce PR diff size.",
}


def _failure_comment(repo: str, error_type: str) -> str:
    """Build a generic error comment for posting to a PR."""
    hint = _ERROR_HINTS.get(error_type, "")
    hint_line = f"\n\n{hint}" if hint else ""
    return (
        f"## \u274c Grippy Review \u2014 {error_type}\n\n"
        "Review failed. Check the "
        f"[Actions log](https://github.com/{repo}/actions) for details."
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
    diff in a single request — no pagination issues (C1 fix).
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


def main() -> None:
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
    print(
        f"PR #{pr_event['pr_number']}: {pr_event['title']} "
        f"({pr_event['head_ref']} → {pr_event['base_ref']})"
    )

    # 2. Validate transport + create agent early (before expensive diff fetch)
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

    try:
        agent = create_reviewer(
            model_id=model_id,
            base_url=base_url,
            transport=transport,
            mode=mode,
            db_path=data_dir / "grippy-session.db",
            session_id=f"pr-{pr_event['pr_number']}",
            tools=codebase_tools or None,
            tool_call_limit=10 if codebase_tools else None,
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

    # 3. Fetch diff (M2: graceful 403 handling for fork PRs)
    print("Fetching PR diff...")
    try:
        diff = fetch_pr_diff(token, pr_event["repo"], pr_event["pr_number"])
    except Exception as exc:
        print(f"::error::Failed to fetch PR diff: {exc}")
        if "403" in str(exc):
            print(
                "::error::The token may lack access to this fork's diff. "
                "Ensure the workflow has `pull_request_target` trigger or "
                "the token has read access to the fork."
            )
        try:
            post_comment(
                token,
                pr_event["repo"],
                pr_event["pr_number"],
                _failure_comment(pr_event["repo"], "DIFF ERROR"),
            )
        except Exception:
            pass  # Don't mask the original error
        sys.exit(1)
    file_count = diff.count("diff --git")
    print(f"  {file_count} files, {len(diff)} chars")

    # H2: cap diff size to avoid overflowing LLM context
    original_len = len(diff)
    diff = truncate_diff(diff)
    if len(diff) < original_len:
        print(f"  Diff truncated to {MAX_DIFF_CHARS} chars ({file_count} files in original)")

    # 4. Format context
    user_message = format_pr_context(
        title=pr_event["title"],
        author=pr_event["author"],
        branch=f"{pr_event['head_ref']} → {pr_event['base_ref']}",
        description=pr_event["description"],
        diff=diff,
    )

    # 5. Run review with retry + validation (replaces agent.run + parse_review_response)
    print(f"Running review (model={model_id}, endpoint={base_url})...")
    try:
        review = _with_timeout(
            lambda: run_review(agent, user_message),
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
            pass
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
            pass
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
            pass
        sys.exit(1)

    # Override self-reported model — LLMs hallucinate their own model name
    review.model = model_id

    print(f"  Score: {review.score.overall}/100 — {review.verdict.status.value}")
    print(f"  Findings: {len(review.findings)}")

    # 6. Build graph, get prior findings, THEN persist (non-fatal)
    session_id = f"pr-{pr_event['pr_number']}"
    prior_findings: list[dict[str, Any]] = []
    store: GrippyStore | None = None
    print("Persisting review graph...")
    try:
        embedder = create_embedder(
            transport=transport or "local",
            model=embedding_model,
            base_url=base_url,
        )
        graph = review_to_graph(review)
        store = GrippyStore(
            graph_db_path=data_dir / "grippy-graph.db",
            lance_dir=data_dir / "lance",
            embedder=embedder,
        )
        # Query prior findings BEFORE storing current round
        try:
            prior_findings = store.get_prior_findings(session_id=session_id)
        except Exception:
            prior_findings = []
        store.store_review(graph, session_id=session_id)
        print(f"  Graph: {len(graph.nodes)} nodes persisted")
    except Exception as exc:
        print(f"::warning::Graph persistence failed: {exc}")

    # 7. Post review with inline comments + summary dashboard
    head_sha = pr_event.get("head_sha", "")
    print("Posting review...")
    resolution = None
    try:
        resolution = post_review(
            token=token,
            repo=pr_event["repo"],
            pr_number=pr_event["pr_number"],
            findings=review.findings,
            prior_findings=prior_findings,
            head_sha=head_sha,
            diff=diff,
            score=review.score.overall,
            verdict=review.verdict.status.value,
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
            pass  # Don't mask the original error

    # 8. Update resolved finding status in graph DB (non-fatal)
    if resolution is not None and resolution.resolved and store is not None:
        try:
            for resolved in resolution.resolved:
                store.update_finding_status(resolved["node_id"], FindingStatus.RESOLVED)
            print(f"  Marked {len(resolution.resolved)} findings as resolved")
        except Exception as exc:
            print(f"::warning::Failed to update finding status: {exc}")

    # 9. Set outputs for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"score={review.score.overall}\n")
            f.write(f"verdict={review.verdict.status.value}\n")
            f.write(f"findings-count={len(review.findings)}\n")
            f.write(f"merge-blocking={str(review.verdict.merge_blocking).lower()}\n")

    # Exit non-zero if merge-blocking
    if review.verdict.merge_blocking:
        print(f"::warning::Review verdict: {review.verdict.status.value} (merge-blocking)")
        sys.exit(1)


if __name__ == "__main__":
    main()
