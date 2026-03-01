# Security Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all 10 findings from the security audit — 3 HIGH, 3 MEDIUM, 4 LOW.

**Architecture:** Patch existing files in-place. No new modules. Tests for security-critical fixes (path traversal). Workflow changes are YAML-only.

**Tech Stack:** Python 3.12+, GitHub Actions, uv

---

### Task 1: Fix path traversal in `read_file` and `list_files` (H1/H2)

**Files:**
- Modify: `src/grippy/codebase.py:400-410` (read_file path check)
- Modify: `src/grippy/codebase.py:445-470` (list_files path check + glob filtering)
- Test: `tests/test_grippy_codebase.py`

**Step 1: Write failing tests for path traversal bypass**

Add to `tests/test_grippy_codebase.py`:

```python
def test_read_file_rejects_prefix_bypass(tmp_path: Path) -> None:
    """H1: startswith bypass via shared prefix — e.g. /repo vs /repo-evil."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "safe.py").write_text("safe content")

    evil_dir = tmp_path / "repo-evil"
    evil_dir.mkdir()
    (evil_dir / "secrets.py").write_text("stolen secrets")

    read_fn = _make_read_file(repo_root)
    result = read_fn("../repo-evil/secrets.py")
    assert "path traversal not allowed" in result.lower()


def test_list_files_rejects_prefix_bypass(tmp_path: Path) -> None:
    """H1: startswith bypass in list_files."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "safe.py").write_text("x")

    evil_dir = tmp_path / "repo-evil"
    evil_dir.mkdir()
    (evil_dir / "secrets.py").write_text("stolen")

    list_fn = _make_list_files(repo_root)
    result = list_fn("../repo-evil")
    assert "path traversal not allowed" in result.lower()


def test_list_files_glob_cannot_escape_boundary(tmp_path: Path) -> None:
    """H2: glob results must be bounded by repo_root."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "safe.py").write_text("x")

    outside = tmp_path / "outside.py"
    outside.write_text("outside content")

    list_fn = _make_list_files(repo_root)
    result = list_fn(".", "../../*")
    assert "outside.py" not in result
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/test_grippy_codebase.py -v -k "prefix_bypass or glob_cannot_escape"`
Expected: FAIL — the startswith check lets these through

**Step 3: Fix the path checks in codebase.py**

In `_make_read_file`, replace the startswith check (lines ~404-407):

```python
        # Prevent path traversal
        try:
            target = target.resolve()
            if not target.is_relative_to(repo_root.resolve()):
                return "Error: path traversal not allowed."
        except (OSError, ValueError):
            return "Error: invalid path."
```

In `_make_list_files`, replace the startswith check (lines ~449-454) with the same pattern:

```python
        # Prevent path traversal
        try:
            target = target.resolve()
            if not target.is_relative_to(repo_root.resolve()):
                return "Error: path traversal not allowed."
        except (OSError, ValueError):
            return "Error: invalid path."
```

And filter glob results (line ~460):

```python
        try:
            resolved_root = repo_root.resolve()
            entries = sorted(
                e for e in target.glob(glob_pattern)
                if e.resolve().is_relative_to(resolved_root)
            )
        except (OSError, ValueError) as e:
            return f"Error listing files: {e}"
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/test_grippy_codebase.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add src/grippy/codebase.py tests/test_grippy_codebase.py
git commit -m "fix: path traversal bypass via startswith — use is_relative_to

Replace str.startswith path check with Path.is_relative_to() to prevent
prefix-based bypasses (e.g. /repo vs /repo-evil). Filter list_files
glob results through the same boundary check.

Fixes: H1, H2 from security audit"
```

---

### Task 2: Fix grep symlink following (L2)

**Files:**
- Modify: `src/grippy/codebase.py:362-378` (grep_code command)

**Step 1: Add `-S` flag to grep command**

In `_make_grep_code`, update the `cmd` list (line ~363):

```python
            cmd = [
                "grep",
                "-rnS",
                "--max-count=50",
                f"--include={glob}",
                f"-C{context_lines}",
                "-E",
                pattern,
                str(repo_root),
            ]
```

Note: `-S` tells grep not to follow symlinks when recursing directories. Combined with `-rn` as `-rnS`.

**Step 2: Run tests**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/test_grippy_codebase.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add src/grippy/codebase.py
git commit -m "fix: prevent grep from following symlinks outside repo

Add -S flag to grep_code to avoid traversing symlinks that could
point outside the repository boundary.

Fixes: L2 from security audit"
```

---

### Task 3: SHA-pin GitHub Actions (H3)

**Files:**
- Modify: `.github/workflows/grippy-review.yml`
- Modify: `.github/workflows/tests.yml`

**Step 1: Pin actions in grippy-review.yml**

Replace unpinned refs with SHA-pinned versions and add harden-runner:

```yaml
    steps:
      - name: Harden runner
        uses: step-security/harden-runner@cb605e52c26070c328afc4562f0b4ada7618a84e  # v2.10.4
        with:
          egress-policy: audit

      - name: Checkout
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

      - name: Set up Python
        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0
        with:
          python-version: '3.12'

      - name: Cache Grippy data
        uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830  # v4.3.0
        with:
```

**Step 2: Pin actions in tests.yml**

Replace all unpinned refs. Both `test` and `lint` jobs use checkout + setup-python:

```yaml
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2

      - name: Set up Python
        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065  # v5.6.0
```

**Step 3: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add .github/workflows/grippy-review.yml .github/workflows/tests.yml
git commit -m "fix: SHA-pin all GitHub Actions to prevent supply chain attacks

Pin checkout, setup-python, and cache to specific commit SHAs.
Add harden-runner to grippy-review.yml (has access to OPENAI_API_KEY).
Matches pinning strategy already used in codeql.yml and scorecard.yml.

Fixes: H3 from security audit"
```

---

### Task 4: Sanitize error messages in PR comments (M1/M2)

**Files:**
- Modify: `src/grippy/review.py` (4 error comment blocks)

**Step 1: Replace all error PR comment bodies**

There are 4 places in `main()` where error details are posted to PR comments:

1. **Config error** (~line 268): already uses `{exc}` — replace with generic
2. **Diff fetch error** (~line 289): uses `{exc}` — replace with generic
3. **Parse error** (~line 327): posts `exc.last_raw[:500]` — replace with generic
4. **Agent error** (~line 353): uses `{exc}` — replace with generic
5. **Post-review fallback** (~line 417): uses `{exc}` — replace with generic

Replace each with this pattern (adjust ERROR_TYPE per block):

```python
failure_body = (
    "## \u274c Grippy Review \u2014 {ERROR_TYPE}\n\n"
    "Review failed. Check the "
    "[Actions log](https://github.com/"
    f"{pr_event['repo']}/actions) for details.\n\n"
    "<!-- grippy-error -->"
)
```

Keep all `print()` / `print(f"::error::...")` lines intact — those go to Actions logs.

**Step 2: Run tests**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/test_grippy_review.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add src/grippy/review.py
git commit -m "fix: sanitize error messages posted to PR comments

Replace raw exception messages and model output in PR comments with
generic error messages pointing to Actions logs. Prevents leaking
internal paths, API details, or prompt content via error comments.

Fixes: M1, M2 from security audit"
```

---

### Task 5: Remove duplicate `parse_review_response` (L1)

**Files:**
- Modify: `src/grippy/review.py` (delete function)
- Modify: `src/grippy/__init__.py` (remove export)

**Step 1: Delete `parse_review_response` from review.py**

Remove the entire function (lines ~65-96).

**Step 2: Remove from `__init__.py` exports**

Remove `parse_review_response` from the import block and `__all__` list.

**Step 3: Run tests and lint**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/ -v && uv run ruff check src/grippy/`
Expected: ALL PASS, no lint errors

**Step 4: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add src/grippy/review.py src/grippy/__init__.py
git commit -m "refactor: remove duplicate parse_review_response

Superseded by retry._parse_response which also handles markdown fences.
No external callers — the main flow uses run_review() from retry.py.

Fixes: L1 from security audit"
```

---

### Task 6: Fix step numbering (L3)

**Files:**
- Modify: `src/grippy/review.py:438`

**Step 1: Renumber duplicate step comment**

Change `# 8. Set outputs for GitHub Actions` to `# 9. Set outputs for GitHub Actions`.

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add src/grippy/review.py
git commit -m "fix: correct duplicate step numbering in review.py

Fixes: L3 from security audit"
```

---

### Task 7: Narrow scorecard permissions (L4)

**Files:**
- Modify: `.github/workflows/scorecard.yml:10`

**Step 1: Replace top-level permissions**

Change `permissions: read-all` to `permissions: {}`.

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add .github/workflows/scorecard.yml
git commit -m "fix: narrow scorecard.yml top-level permissions

Replace read-all with empty permissions — job-level already declares
the specific permissions needed.

Fixes: L4 from security audit"
```

---

### Task 8: Generate and commit uv.lock (M3)

**Files:**
- Create: `uv.lock`

**Step 1: Generate lockfile**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv lock`

**Step 2: Verify it was created**

Run: `ls -la /home/ndspence/GitHub/grippy-code-review/uv.lock`

**Step 3: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git add uv.lock
git commit -m "fix: commit uv.lock for reproducible builds

Pins transitive dependencies to prevent silent supply chain
substitution in CI.

Fixes: M3 from security audit"
```

---

### Task 9: Run full quality checks

**Step 1: Run all tests**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run pytest tests/ -v --cov=src/grippy --cov-report=term-missing`

**Step 2: Run linter**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run ruff check src/grippy/ tests/`

**Step 3: Run type checker**

Run: `cd /home/ndspence/GitHub/grippy-code-review && uv run mypy src/grippy/`

Expected: All pass with no regressions.
