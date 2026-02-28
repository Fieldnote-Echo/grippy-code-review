"""GitHub PR Review API integration — inline comments, resolution, summaries."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import Any

from github import Github, GithubException

from grippy.schema import Finding

_FINDING_MARKER_RE = re.compile(r"<!-- grippy-finding-(\w+) -->")

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


# --- Inline comment builder ---

_SEVERITY_EMOJI = {
    "CRITICAL": "\U0001f534",
    "HIGH": "\U0001f7e0",
    "MEDIUM": "\U0001f7e1",
    "LOW": "\U0001f535",
}


def build_review_comment(finding: Finding) -> dict[str, str | int]:
    """Build a PyGithub-compatible review comment dict for a finding.

    Args:
        finding: The finding to create a comment for.

    Returns:
        Dict with keys: path, body, line, side.
    """
    emoji = _SEVERITY_EMOJI.get(finding.severity.value, "\u26aa")
    body_lines = [
        f"#### {emoji} {finding.severity.value}: {finding.title}",
        f"Confidence: {finding.confidence}%",
        "",
        finding.description,
        "",
        f"**Suggestion:** {finding.suggestion}",
        "",
        f"*\u2014 {finding.grippy_note}*",
        "",
        f"<!-- grippy-finding-{finding.fingerprint} -->",
    ]
    return {
        "path": finding.file,
        "body": "\n".join(body_lines),
        "line": finding.line_start,
        "side": "RIGHT",
    }


# --- Summary dashboard ---


def format_summary_comment(
    *,
    score: int,
    verdict: str,
    finding_count: int,
    new_count: int,
    persists_count: int,
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
        new_count: Findings not seen in prior round.
        persists_count: Findings that persist from prior round.
        resolved_count: Prior findings resolved this round.
        off_diff_findings: Findings outside diff hunks (shown inline here).
        head_sha: Commit SHA for this review.
        pr_number: PR number for marker scoping.
        diff_truncated: Whether the diff was truncated to fit context limits.

    Returns:
        Formatted markdown comment body.
    """
    status_emoji = {
        "PASS": "\u2705",
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
    if new_count or persists_count or resolved_count:
        parts = []
        if new_count:
            parts.append(f"{new_count} new")
        if persists_count:
            parts.append(f"{persists_count} persists")
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
            lines.append(f"#### {sev_emoji} {f.severity.value}: {f.title}")
            lines.append(f"\U0001f4c1 `{f.file}:{f.line_start}`")
            lines.append("")
            lines.append(f.description)
            lines.append("")
            lines.append(f"**Suggestion:** {f.suggestion}")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.append("---")
    lines.append(f"<sub>Commit: {head_sha[:7]}</sub>")
    lines.append("")
    lines.append(f"<!-- grippy-summary-{pr_number} -->")

    return "\n".join(lines)


# --- Finding resolution ---


@dataclass
class PersistingFinding:
    """A finding that persists from a prior round."""

    finding: Finding
    prior_node_id: str


@dataclass
class ResolutionResult:
    """Result of resolving current findings against prior round."""

    new: list[Finding] = field(default_factory=list)
    persisting: list[PersistingFinding] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)


def resolve_findings_against_prior(
    current: list[Finding],
    prior: list[dict[str, Any]],
) -> ResolutionResult:
    """Match current findings against prior round using fingerprints.

    Resolution rules:
    - Exact fingerprint match -> PERSISTS
    - No match in current for a prior finding -> RESOLVED
    - No match in prior for a current finding -> NEW

    Args:
        current: Findings from the current review round.
        prior: Prior findings as dicts with 'fingerprint', 'title', 'node_id'.

    Returns:
        ResolutionResult with new, persisting, and resolved findings.
    """
    result = ResolutionResult()
    prior_by_fp = {p["fingerprint"]: p for p in prior}
    matched_prior_fps: set[str] = set()

    for finding in current:
        fp = finding.fingerprint
        if fp in prior_by_fp:
            result.persisting.append(
                PersistingFinding(
                    finding=finding,
                    prior_node_id=prior_by_fp[fp]["node_id"],
                )
            )
            matched_prior_fps.add(fp)
        else:
            result.new.append(finding)

    for prior_finding in prior:
        if prior_finding["fingerprint"] not in matched_prior_fps:
            result.resolved.append(prior_finding)

    return result


# --- Post review ---

_REVIEW_BATCH_SIZE = 25


def post_review(
    *,
    token: str,
    repo: str,
    pr_number: int,
    findings: list[Finding],
    prior_findings: list[dict[str, Any]],
    head_sha: str,
    diff: str,
    score: int,
    verdict: str,
    diff_truncated: bool = False,
) -> ResolutionResult:
    """Post Grippy review as inline comments + summary dashboard.

    Args:
        token: GitHub API token.
        repo: Repository full name (owner/repo).
        pr_number: Pull request number.
        findings: Current round's findings.
        prior_findings: Prior round's findings (from GrippyStore).
        head_sha: Current commit SHA.
        diff: Full PR diff text.
        score: Overall review score.
        verdict: PASS, FAIL, or PROVISIONAL.
        diff_truncated: Whether the diff was truncated to fit context limits.

    Returns:
        ResolutionResult for callers to update finding status in the store.
    """
    gh = Github(token)
    repository = gh.get_repo(repo)
    pr = repository.get_pull(pr_number)

    # Resolve findings against prior round
    resolution = resolve_findings_against_prior(findings, prior_findings)

    # Detect fork PR — GITHUB_TOKEN is read-only for forks
    is_fork = (
        pr.head.repo is not None
        and pr.base.repo is not None
        and pr.head.repo.full_name != pr.base.repo.full_name
    )

    # Parse diff and classify
    diff_lines = parse_diff_lines(diff)
    inline, off_diff = classify_findings(findings, diff_lines)

    # For fork PRs, skip inline comments — put everything in summary
    if is_fork:
        off_diff = findings
        inline = []

    # Post inline review comments (batched, with 422 fallback)
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

    # Build summary comment
    summary = format_summary_comment(
        score=score,
        verdict=verdict,
        finding_count=len(findings),
        new_count=len(resolution.new),
        persists_count=len(resolution.persisting),
        resolved_count=len(resolution.resolved),
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
            return resolution

    pr.create_issue_comment(summary)
    return resolution


# --- Thread resolution ---


def collect_resolved_thread_ids(
    comments: list[Any],
    resolved: list[dict[str, Any]],
) -> list[str]:
    """Match resolved findings to their GitHub review thread IDs.

    Scans existing PR review comments for ``<!-- grippy-finding-{fp} -->``
    markers and returns the thread node_id for each resolved fingerprint.

    Args:
        comments: PR review comments (from ``pr.get_review_comments()``).
        resolved: Resolved finding dicts with 'fingerprint' key.

    Returns:
        List of GitHub review thread node IDs to resolve.
    """
    if not resolved or not comments:
        return []

    resolved_fps = {r["fingerprint"] for r in resolved}
    thread_ids: list[str] = []

    for comment in comments:
        match = _FINDING_MARKER_RE.search(comment.body)
        if match and match.group(1) in resolved_fps:
            thread_ids.append(comment.node_id)

    return thread_ids


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
