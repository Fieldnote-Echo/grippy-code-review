# Security Hardening Design — Grippy Code Review

**Date:** 2026-02-27
**Author:** Alpha (Claude Code)
**Approved by:** Nelson

## Context

Full security and functional audit of `Fieldnote-Echo/grippy-code-review` identified
13 findings across 4 severity levels. This design covers fixes for all of them.

## Findings Summary

| ID  | Severity | Title | File |
|-----|----------|-------|------|
| H1  | HIGH | Path traversal bypass via `startswith` | codebase.py:405,451 |
| H2  | HIGH | `list_files` glob results escape repo boundary | codebase.py:460 |
| H3  | HIGH | Unpinned GitHub Actions (supply chain) | grippy-review.yml, tests.yml |
| M1  | MEDIUM | Raw model output posted to PR on parse failure | review.py:325-333 |
| M2  | MEDIUM | Exception messages posted to PR comments | review.py:354-359 |
| M3  | MEDIUM | No lockfile committed | pyproject.toml |
| L1  | LOW | Duplicate `parse_review_response` (dead code) | review.py:65-96 |
| L2  | LOW | `grep_code` follows symlinks | codebase.py:373 |
| L3  | LOW | Duplicate step numbering | review.py:438 |
| L4  | LOW | `permissions: read-all` in scorecard.yml | scorecard.yml:10 |

## Fix Designs

### H1/H2: Path Traversal — `codebase.py`

**Problem:** `str(target).startswith(str(repo_root.resolve()))` can be bypassed when
directories share a prefix (e.g., `/repo` vs `/repo-evil`). Additionally, `list_files`
glob results are not validated against the repo boundary.

**Fix:** Replace `startswith` with `Path.is_relative_to()` (Python 3.12+ guaranteed).
Filter glob results through the same check.

```python
# read_file and list_files path check
if not target.is_relative_to(repo_root.resolve()):
    return "Error: path traversal not allowed."

# list_files glob result filtering
resolved_root = repo_root.resolve()
entries = [e for e in sorted(target.glob(glob_pattern))
           if e.resolve().is_relative_to(resolved_root)]
```

### H3: Action Pinning — `grippy-review.yml`, `tests.yml`

**Problem:** Tag-based action refs (`@v4`, `@v5`) can be moved to arbitrary commits.

**Fix:** SHA-pin all actions. Use same checkout SHA as `codeql.yml`. Look up current
SHAs for `setup-python` and `cache`. Add `harden-runner` to `grippy-review.yml`
(has access to `OPENAI_API_KEY`).

### M1/M2: Error Message Sanitization — `review.py`

**Decision:** Generic errors only. No raw output, exception messages, or model output
in PR comments. All diagnostic info stays in `print()` (Actions logs only).

**Fix:** Replace all error comment bodies with:
```
## {emoji} Grippy Review — {ERROR_TYPE}
Review failed. Check the [Actions log](...) for details.
<!-- grippy-error -->
```

### M3: Lockfile — `uv.lock`

**Decision:** Commit `uv.lock` for reproducible builds.

**Fix:** Run `uv lock` in grippy repo and commit the lockfile.

### L1: Dead Code — `review.py`

**Decision:** Remove entirely (no external callers known).

**Fix:** Delete `parse_review_response` from `review.py` and remove from
`__init__.py` exports.

### L2: Symlink Following — `codebase.py`

**Fix:** Add `-S` (don't follow symlinks for directories) to grep command.

### L3: Step Numbering — `review.py`

**Fix:** Renumber second `# 8.` to `# 9.`.

### L4: Scorecard Permissions — `scorecard.yml`

**Fix:** Change top-level `permissions: read-all` to `permissions: {}`.
Job-level permissions already declare what's needed.
