# github-app.md — GitHub App Posting Rules

> Applied by the orchestrator after confidence filtering.
> Transforms Grippy's structured JSON output into GitHub API calls.
> This file governs WHAT gets posted WHERE and HOW.

---

## Posting Strategy

Grippy uses two GitHub mechanisms in tandem. Each serves a different purpose.

### Check Runs (Primary — Merge Gate)

The **Checks API** is Grippy's enforcement layer. A check run named `grippy/audit` is created on every reviewed PR. Its conclusion determines whether the PR can merge.

**Mapping:**

| Verdict | Check Run Conclusion | Merge Effect |
|---------|---------------------|--------------|
| PASS | `success` | Allowed |
| PROVISIONAL | `neutral` | Allowed (with warnings visible) |
| FAIL | `failure` | Blocked (when configured as required status check) |

**Check run output includes:**
- `title`: Score and verdict — e.g., "Score: 82/100 — PASS"
- `summary`: Full summary with ASCII art, score table, opener/closer
- `annotations`: One annotation per finding, mapped to file + line

**Annotation mapping:**

```
finding.severity CRITICAL → annotation_level "failure"
finding.severity HIGH     → annotation_level "failure"  
finding.severity MEDIUM   → annotation_level "warning"
finding.severity LOW      → annotation_level "notice"
```

**Annotation limits:** GitHub allows 50 annotations per API request. For reviews with >50 findings, batch using PATCH requests to append additional annotations to the existing check run.

**Re-run support:** When a developer clicks "Re-run" on the check, the orchestrator re-fetches the current diff and runs a fresh review. The new result replaces the old check run.

### Pull Request Reviews (Secondary — Discussion)

The **PR Reviews API** is Grippy's conversation layer. Used for HIGH and CRITICAL findings that benefit from inline discussion.

**When to post a PR review:**
- At least one finding is severity HIGH or CRITICAL
- The finding references specific lines that support inline commenting
- The finding has a `suggestion` field with a concrete code fix

**Review event mapping:**

| Condition | Review Event |
|-----------|-------------|
| Any CRITICAL finding | `REQUEST_CHANGES` |
| 2+ HIGH findings, no CRITICAL | `REQUEST_CHANGES` |
| 1 HIGH finding, no CRITICAL | `COMMENT` |
| MEDIUM/LOW only | No PR review (check run only) |

**Inline comments use:**
- `path`: Finding's `file` field
- `line`: Finding's `line_end` (GitHub anchors to the last line of a range)
- `side`: `RIGHT` (new code side of the diff)
- `body`: Formatted finding with `grippy_note`, description, and suggestion block

**Suggestion blocks** (when `suggestion` field is present):

````markdown
{{grippy_note}}

{{description}}

```suggestion
{{suggested_code}}
```
````

GitHub renders suggestion blocks as one-click applicable fixes. This is one of Grippy's most useful features — begrudging help that's also effortlessly actionable.

### Summary Comment

A single top-level PR comment containing the full audit summary. This is the "face" of the review — where ASCII art, catchphrases, and the score table live.

**Structure:**

```markdown
{{ascii_art (if tone register permits)}}

{{opening_catchphrase}}

## Grippy Audit

**Score:** {{score}}/100 — **{{verdict}}**

| Severity | Count |
|----------|-------|
| 🔴 Critical | {{crit}} |
| 🟠 High | {{high}} |
| 🟡 Medium | {{med}} |
| ⚪ Low | {{low}} |

**Reviewed:** {{files_reviewed}}/{{files_in_diff}} files ({{coverage}}%)  
**Rules:** {{rules_count}} governance rules applied  
**Tier:** {{complexity_tier}}

{{closing_line}}

---
<sub>🔧 Grippy v{{version}} · <a href="{{config_link}}">Configure</a> · <a href="{{feedback_link}}">Report issue</a> · Powered by <a href="https://projectnavi.ai">Project Navi</a></sub>
```

## Rate Limit Handling

- Space write operations by 1 second minimum
- Cache installation tokens for their full 1-hour lifespan
- Use conditional requests (ETags) for read operations
- If rate-limited (HTTP 403 with `retry-after`), queue the post and retry
- Log rate limit events for capacity planning

## Webhook Response Protocol

1. Respond to the webhook within **10 seconds** with HTTP 202
2. Queue the review job asynchronously
3. Create the check run immediately with status `in_progress`
4. Run the review pipeline
5. Update the check run with conclusion and annotations
6. Post PR review (if applicable)
7. Post summary comment

**Idempotency:** Use `X-GitHub-Delivery` header as the idempotency key. If the same delivery ID arrives twice, skip the duplicate.

## Permissions Required

```yaml
permissions:
  pull_requests: write    # PR reviews and comments
  checks: write           # Check runs and annotations  
  contents: read          # Fetch file contents for context
  metadata: read          # Repository metadata

events:
  - pull_request          # opened, synchronize, reopened
  - pull_request_review   # for feedback learning (emoji reactions)
  - check_suite           # re-run requests
  - issue_comment         # /grippy slash commands
```

## Slash Commands

Grippy responds to commands in PR comments:

| Command | Action |
|---------|--------|
| `/grippy review` | Trigger a fresh review |
| `/grippy security` | Trigger security audit mode |
| `/grippy governance` | Trigger governance audit mode |
| `/grippy verbose` | Re-post with all findings (bypass noise caps) |
| `/grippy suppress F-XXX` | Suppress a specific finding for this PR |
| `/grippy explain F-XXX` | Expand explanation for a finding |
| `/grippy score` | Show current score without full review |
| `/grippy off` | Disable Grippy for this PR (logged) |

Commands are detected by the orchestrator from `issue_comment` webhooks. Only the PR author and repo admins can issue commands.
