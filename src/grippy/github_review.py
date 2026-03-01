# SPDX-License-Identifier: MIT
"""GitHub PR Review API integration — inline comments, resolution, summaries.

Finding lifecycle is owned by GitHub: fetch existing comments, compare,
post only genuinely new findings, resolve threads for absent findings.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

import nh3
from github import Github, GithubException

from grippy.schema import Finding

# --- Diff parser ---


def parse_diff_lines(diff_text: str) -> dict[str, set[int]]:
    """Parse unified diff to extract addressable RIGHT-side line numbers.

    GitHub's PR Review API only allows comments on lines that appear in
    the diff hunk. This function returns a mapping of file paths to the
    set of right-side (new file) line numbers that are addressable.

    Args:
        diff_text: Complete unified diff text from GitHub API.

    Returns:
        Dict mapping file paths to sets of addressable line numbers.
    """
    if not diff_text.strip():
        return {}

    result: dict[str, set[int]] = {}
    current_file: str | None = None
    right_line = 0

    for line in diff_text.splitlines():
        # Track current file from diff headers
        file_match = re.match(r"^diff --git a/.+ b/(.+)$", line)
        if file_match:
            current_file = file_match.group(1)
            if current_file not in result:
                result[current_file] = set()
            continue

        # Parse hunk header for right-side starting line
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            right_line = int(hunk_match.group(1))
            continue

        if current_file is None:
            continue

        # Skip diff metadata lines
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("diff --git"):
            continue
        if line.startswith("new file") or line.startswith("index "):
            continue

        # Deleted lines: only advance left-side counter (not tracked)
        if line.startswith("-"):
            continue

        # Added lines: addressable on the right side
        if line.startswith("+"):
            result[current_file].add(right_line)
            right_line += 1
            continue

        # Context lines (space prefix): addressable on right side
        if line.startswith(" "):
            result[current_file].add(right_line)
            right_line += 1
            continue

        # "\ No newline at end of file" — skip, don't increment
        if line.startswith("\\"):
            continue

        # Any other line (unexpected metadata) — skip

    return result


# --- Finding classification ---


def classify_findings(
    findings: list[Finding],
    diff_lines: dict[str, set[int]],
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into inline-eligible and off-diff.

    A finding is inline-eligible if its file appears in the diff and its
    line_start is within an addressable hunk line.

    Args:
        findings: List of findings from the review.
        diff_lines: Output of parse_diff_lines().

    Returns:
        (inline_findings, off_diff_findings)
    """
    inline: list[Finding] = []
    off_diff: list[Finding] = []
    for finding in findings:
        file_lines = diff_lines.get(finding.file)
        if file_lines and finding.line_start in file_lines:
            inline.append(finding)
        else:
            off_diff.append(finding)
    return inline, off_diff


# --- Output sanitization ---

# Dangerous URL schemes in markdown link syntax — not covered by nh3
# since [text](javascript:...) is markdown, not HTML.
_DANGEROUS_SCHEME_RE = re.compile(
    r"(?:javascript|data|vbscript)\s*:",
    re.IGNORECASE,
)


def _sanitize_comment_text(text: str) -> str:
    """Sanitize LLM-generated text using allowlist-based HTML cleaning.

    Uses nh3 (Rust-based HTML sanitizer) instead of a regex blocklist.
    Strips all HTML tags from free-text fields — only standard markdown
    syntax (bold, italic, code spans, etc.) is preserved. A second pass
    neutralizes dangerous URL schemes in markdown link syntax.

    This is defense-in-depth: GitHub's own renderer also sanitizes, but
    we neutralize injection attempts before they ever reach the API.

    Args:
        text: Raw text from an LLM-generated field.

    Returns:
        Cleaned text with HTML tags removed and dangerous schemes stripped.
    """
    text = nh3.clean(text, tags=set())
    text = _DANGEROUS_SCHEME_RE.sub("", text)
    return text


# --- Inline comment builder ---

_SEVERITY_EMOJI = {
    "CRITICAL": "\U0001f534",
    "HIGH": "\U0001f7e0",
    "MEDIUM": "\U0001f7e1",
    "LOW": "\U0001f535",
}

# Marker format: <!-- grippy:file:category:line -->
_GRIPPY_MARKER_RE = re.compile(r"<!-- grippy:(?P<file>[^:]+):(?P<category>[^:]+):(?P<line>\d+) -->")


def _finding_marker(finding: Finding) -> str:
    """Build an HTML comment marker for dedup — keyed on file, category, line."""
    return f"<!-- grippy:{finding.file}:{finding.category.value}:{finding.line_start} -->"


def build_review_comment(finding: Finding) -> dict[str, str | int]:
    """Build a PyGithub-compatible review comment dict for a finding.

    Args:
        finding: The finding to create a comment for.

    Returns:
        Dict with keys: path, body, line, side.
    """
    emoji = _SEVERITY_EMOJI.get(finding.severity.value, "\u26aa")
    title = _sanitize_comment_text(finding.title)
    description = _sanitize_comment_text(finding.description)
    suggestion = _sanitize_comment_text(finding.suggestion)
    grippy_note = _sanitize_comment_text(finding.grippy_note)
    body_lines = [
        f"#### {emoji} {finding.severity.value}: {title}",
        f"Confidence: {finding.confidence}%",
        "",
        description,
        "",
        f"**Suggestion:** {suggestion}",
        "",
        f"*\u2014 {grippy_note}*",
        "",
        _finding_marker(finding),
    ]
    return {
        "path": finding.file,
        "body": "\n".join(body_lines),
        "line": finding.line_start,
        "side": "RIGHT",
    }


# --- GitHub comment fetching ---


def _parse_marker(body: str) -> tuple[str, str, int] | None:
    """Extract (file, category, line) from a grippy marker in comment body."""
    match = _GRIPPY_MARKER_RE.search(body)
    if match:
        return (match.group("file"), match.group("category"), int(match.group("line")))
    return None


def fetch_grippy_comments(
    pr: Any,
) -> dict[tuple[str, str, int], Any]:
    """Fetch existing Grippy review comments from a PR.

    Scans all review comments for grippy markers and returns them keyed
    by (file, category, line) for O(1) dedup lookups.

    Args:
        pr: PyGithub PullRequest object.

    Returns:
        Dict mapping (file, category, line) to the comment object.
    """
    result: dict[tuple[str, str, int], Any] = {}
    for comment in pr.get_review_comments():
        key = _parse_marker(comment.body)
        if key is not None:
            result[key] = comment
    return result


# --- Summary dashboard ---


def format_summary_comment(
    *,
    score: int,
    verdict: str,
    finding_count: int,
    new_count: int,
    resolved_count: int,
    off_diff_findings: list[Finding],
    head_sha: str,
    pr_number: int,
    diff_truncated: bool = False,
) -> str:
    """Format the compact summary dashboard as an issue comment.

    Args:
        score: Overall review score (0-100).
        verdict: PASS, FAIL, or PROVISIONAL.
        finding_count: Total findings this round.
        new_count: Genuinely new findings posted this round.
        resolved_count: Prior findings resolved this round.
        off_diff_findings: Findings outside diff hunks (shown inline here).
        head_sha: Commit SHA for this review.
        pr_number: PR number for marker scoping.
        diff_truncated: Whether the diff was truncated to fit context limits.

    Returns:
        Formatted markdown comment body.
    """
    status_emoji = {
        "PASS": "\u2705",  # nosec B105
        "FAIL": "\u274c",
        "PROVISIONAL": "\u26a0\ufe0f",
    }.get(verdict, "\U0001f50d")

    lines: list[str] = []
    lines.append(f"## {status_emoji} Grippy Review \u2014 {verdict}")
    lines.append("")
    lines.append(f"**Score: {score}/100** | **Findings: {finding_count}**")
    lines.append("")

    if diff_truncated:
        lines.append(
            "> \u26a0\ufe0f **Notice:** Diff was truncated to fit context limits."
            " Some files may not have been reviewed."
        )
        lines.append("")

    # Delta section
    if new_count or resolved_count:
        parts = []
        if new_count:
            parts.append(f"{new_count} new")
        if resolved_count:
            parts.append(f"\u2705 {resolved_count} resolved")
        lines.append(f"**Delta:** {' \u00b7 '.join(parts)}")
        lines.append("")

    # Off-diff findings
    if off_diff_findings:
        lines.append("<details>")
        lines.append(f"<summary>Off-diff findings ({len(off_diff_findings)})</summary>")
        lines.append("")
        for f in off_diff_findings:
            sev_emoji = _SEVERITY_EMOJI.get(f.severity.value, "\u26aa")
            f_title = _sanitize_comment_text(f.title)
            f_description = _sanitize_comment_text(f.description)
            f_suggestion = _sanitize_comment_text(f.suggestion)
            lines.append(f"#### {sev_emoji} {f.severity.value}: {f_title}")
            lines.append(f"\U0001f4c1 `{f.file}:{f.line_start}`")
            lines.append("")
            lines.append(f_description)
            lines.append("")
            lines.append(f"**Suggestion:** {f_suggestion}")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append(f"<sub>Commit: {head_sha[:7]}</sub>")
    lines.append("")
    lines.append(f"<!-- grippy-summary-{pr_number} -->")

    return "\n".join(lines)


# --- Post review ---

_REVIEW_BATCH_SIZE = 25


def post_review(
    *,
    token: str,
    repo: str,
    pr_number: int,
    findings: list[Finding],
    head_sha: str,
    diff: str,
    score: int,
    verdict: str,
    diff_truncated: bool = False,
) -> None:
    """Post Grippy review as inline comments + summary dashboard.

    GitHub owns finding lifecycle:
    1. Fetch existing grippy comments from this PR
    2. Compare new findings against existing — skip matches
    3. Post only genuinely new findings as inline comments
    4. Resolve threads for findings no longer present
    5. Post/update summary with delta counts

    Args:
        token: GitHub API token.
        repo: Repository full name (owner/repo).
        pr_number: Pull request number.
        findings: Current round's findings.
        head_sha: Current commit SHA.
        diff: Full PR diff text.
        score: Overall review score.
        verdict: PASS, FAIL, or PROVISIONAL.
        diff_truncated: Whether the diff was truncated to fit context limits.
    """
    gh = Github(token)
    repository = gh.get_repo(repo)
    pr = repository.get_pull(pr_number)

    # 1. Fetch existing grippy comments
    existing = fetch_grippy_comments(pr)

    # 2. Classify: which current findings already have comments?
    new_findings: list[Finding] = []
    for finding in findings:
        key = (finding.file, finding.category.value, finding.line_start)
        if key not in existing:
            new_findings.append(finding)

    # 3. Identify resolved: existing comments not in current findings
    current_keys = {(f.file, f.category.value, f.line_start) for f in findings}
    resolved_comments = [comment for key, comment in existing.items() if key not in current_keys]

    # Detect fork PR — GITHUB_TOKEN is read-only for forks
    is_fork = (
        pr.head.repo is not None
        and pr.base.repo is not None
        and pr.head.repo.full_name != pr.base.repo.full_name
    )

    # Parse diff and classify new findings
    diff_lines = parse_diff_lines(diff)
    inline, off_diff = classify_findings(new_findings, diff_lines)

    # For fork PRs, skip inline comments — put everything in summary
    if is_fork:
        off_diff = new_findings
        inline = []

    # 4. Post inline review comments (batched, with 422 fallback)
    failed_findings: list[Finding] = []
    if inline:
        comments = [build_review_comment(f) for f in inline]
        for i in range(0, len(comments), _REVIEW_BATCH_SIZE):
            batch = comments[i : i + _REVIEW_BATCH_SIZE]
            try:
                pr.create_review(
                    event="COMMENT",
                    comments=batch,  # type: ignore[arg-type]
                )
            except GithubException as exc:
                if exc.status == 422:
                    # Move this batch's findings to off-diff
                    failed_findings.extend(inline[i : i + _REVIEW_BATCH_SIZE])
                else:
                    raise
    if failed_findings:
        off_diff.extend(failed_findings)

    # 5. Resolve threads for findings no longer present (non-fatal)
    actual_resolved = 0
    if resolved_comments:
        try:
            thread_ids = [c.node_id for c in resolved_comments]
            actual_resolved = resolve_threads(repo=repo, pr_number=pr_number, thread_ids=thread_ids)
            print(f"  Resolved {actual_resolved}/{len(thread_ids)} threads")
        except Exception as exc:
            print(f"::warning::Thread resolution failed: {exc}")

    # 6. Build summary comment
    summary = format_summary_comment(
        score=score,
        verdict=verdict,
        finding_count=len(findings),
        new_count=len(new_findings),
        resolved_count=actual_resolved,
        off_diff_findings=off_diff,
        head_sha=head_sha,
        pr_number=pr_number,
        diff_truncated=diff_truncated,
    )

    # Upsert: edit existing summary or create new
    marker = f"<!-- grippy-summary-{pr_number} -->"
    for comment in pr.get_issue_comments():
        if marker in comment.body:
            comment.edit(summary)
            return

    pr.create_issue_comment(summary)


# --- Thread resolution ---


def resolve_threads(
    *,
    repo: str,
    pr_number: int,
    thread_ids: list[str],
) -> int:
    """Auto-resolve GitHub review threads via GraphQL.

    Uses ``gh api graphql`` subprocess for authentication simplicity.

    Args:
        repo: Repository full name (owner/repo).
        pr_number: Pull request number (for logging).
        thread_ids: List of GitHub review thread node IDs (PRRT_...).

    Returns:
        Number of threads successfully resolved.
    """
    _resolve_mutation = (
        "mutation ResolveThread($threadId: ID!) { "
        "resolveReviewThread(input: {threadId: $threadId}) { "
        "thread { id isResolved } } }"
    )
    resolved = 0
    for thread_id in thread_ids:
        try:
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={_resolve_mutation}",
                    "-f",
                    f"threadId={thread_id}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                resolved += 1
            else:
                print(f"::warning::Failed to resolve thread {thread_id}: {result.stderr}")
        except Exception as exc:
            print(f"::warning::Exception resolving thread {thread_id}: {exc}")
    return resolved
