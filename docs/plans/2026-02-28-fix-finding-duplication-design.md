# Fix Finding Duplication — Design

**Date:** 2026-02-28
**Status:** Approved
**Branch:** fix/security-hardening

## Problem

Grippy posts duplicate inline comments across review rounds. On PR #2, the same
scorecard permissions finding appeared 5 times and several other findings appeared
2-3 times each. The scoreboard claimed "7 new" when most were repeats.

Three root causes:

1. **Fingerprints are unstable.** The hash uses `file + category + title`, but the
   LLM rephrases titles between rounds (e.g., "Scorecard permissions may break" vs
   "Scorecard workflow permissions set to {} may break depending on required scopes").
   Different title → different fingerprint → treated as a new finding.

2. **Thread resolution is unwired.** `resolve_threads()` exists in `github_review.py`
   but is never called from `review.py`. Resolved findings' GitHub threads stay open.

3. **No thread ID collection.** There is no mechanism to map a resolved finding's
   fingerprint to its GitHub review thread's GraphQL node ID.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Fingerprint stability | Drop title from hash (`file + category` only) | Title is the instability source. Same file + same category = same finding for dedup purposes. |
| Stale comment handling | Resolve the GitHub review thread | Standard UX — comment collapses but audit trail is preserved. Uses existing `resolve_threads()`. |
| Thread ID source | Query PR comments at post time | Match via `<!-- grippy-finding-{fp} -->` markers already embedded. No new storage needed. |
| Scoreboard count | NEW findings only | Persisting/resolved shown in delta line. Keeps headline focused on what changed. |

## Changes

### 1. Stabilize fingerprints — `src/grippy/schema.py`

Change `Finding.fingerprint` from:
```python
key = f"{self.file.strip()}:{self.category.value}:{self.title.strip().lower()}"
```
to:
```python
key = f"{self.file.strip()}:{self.category.value}"
```

This is a breaking change to fingerprint values. Existing cached DBs will produce
different fingerprints, but this is acceptable — graph data is ephemeral per-PR and
the v1 migration already handles stale schemas.

**Trade-off:** Two genuinely different findings of the same category in the same file
will collide. In practice this is rare in LLM code review (findings target specific
issues, not categories), and the benefit of cross-round stability outweighs it.

### 2. Wire up thread resolution — `src/grippy/github_review.py` + `src/grippy/review.py`

In `post_review()`, after computing the resolution result:

1. Fetch all existing review comments on the PR via `pr.get_review_comments()`
2. For each comment, extract the fingerprint from `<!-- grippy-finding-{fp} -->` marker
3. Build a `fingerprint → comment` mapping
4. For each resolved finding, look up the comment by fingerprint
5. Collect the review thread's GraphQL node ID from matched comments
6. Call `resolve_threads()` with those thread IDs

The GraphQL node ID for resolving a thread is available on
`PullRequestReviewComment.pull_request_review_id` or via the `node_id` field on
the comment object from PyGithub.

### 3. Skip re-posting persisting findings — `src/grippy/github_review.py`

In `post_review()`, filter the inline findings list to only include NEW findings
(those not in `resolution.persisting`). Persisting findings already have open
threads from the prior round — no need to post duplicates.

### 4. Update scoreboard count — `src/grippy/github_review.py`

Change `format_summary_comment(finding_count=len(findings))` to pass only the
count of new findings. The delta line already shows the persisting/resolved breakdown.

## Files Modified

| File | Change |
|------|--------|
| `src/grippy/schema.py` | Drop title from fingerprint hash |
| `src/grippy/github_review.py` | Wire thread resolution, skip persisting inline posts, fix scoreboard count |
| `src/grippy/review.py` | Call thread resolution after posting |
| `tests/test_grippy_schema.py` | Update fingerprint tests for new hash inputs |
| `tests/test_grippy_review.py` | Update any tests that depend on fingerprint values |
| `tests/test_grippy_github_review.py` | Add tests for thread resolution wiring, persisting skip |

## Out of Scope

- Semantic similarity matching (embedding-based dedup) — overkill for this problem
- LanceDB vector dedup — separate concern, not causing user-visible duplication
- `data` JSON / `status` column divergence — noted, separate fix
- Scoreboard personality/ASCII art — presentation enhancement, not dedup
