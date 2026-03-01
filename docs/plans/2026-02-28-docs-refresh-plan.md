# Docs Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite README.md and create GitHub wiki pages that accurately reflect the codebase, position Grippy as the open-source BYOM AI code reviewer, and include a self-hosted LLM guide with Cloudflare Access.

**Architecture:** README is the billboard (sells, doesn't document). Wiki is the manual (8 pages covering setup, architecture, security, self-hosted LLM, and contributing). All content is written from scratch — no salvaging the current README.

**Tech Stack:** Markdown, GitHub wiki (separate git repo), `gh` CLI for wiki management.

**Design doc:** `docs/plans/2026-02-28-docs-refresh-design.md`

---

### Task 1: Create branch and set up wiki repo

**Files:**
- None (git operations only)

**Step 1: Create feature branch**

```bash
git checkout main && git pull origin main
git checkout -b docs/readme-and-wiki-refresh
```

**Step 2: Clone the wiki repo**

GitHub wikis are separate git repos at `<repo>.wiki.git`. Clone it for local editing.

```bash
cd /home/ndspence/GitHub
gh repo view Fieldnote-Echo/grippy-code-review --json hasWikiEnabled --jq '.hasWikiEnabled'
```

If wiki is not enabled, enable it:
```bash
gh api -X PATCH repos/Fieldnote-Echo/grippy-code-review -f has_wiki=true
```

Then create a seed page via the GitHub API so the wiki repo exists:
```bash
gh api repos/Fieldnote-Echo/grippy-code-review/pages -X POST -f title="Home" -f content="Placeholder" 2>/dev/null || true
```

If the API doesn't support wiki creation, navigate to `https://github.com/Fieldnote-Echo/grippy-code-review/wiki` and create the Home page manually, then clone:

```bash
git clone https://github.com/Fieldnote-Echo/grippy-code-review.wiki.git /home/ndspence/GitHub/grippy-code-review-wiki
```

**Step 3: Verify setup**

```bash
ls /home/ndspence/GitHub/grippy-code-review-wiki/
```

Expected: at least a `Home.md` file.

---

### Task 2: Write README.md

**Files:**
- Modify: `README.md`

**Step 1: Write the complete README**

Replace the entire contents of `README.md` with the following structure. The exact copy is provided below — adapt the personality peek section based on what looks best.

```markdown
# Grippy Code Review

> Open-source AI code review agent. Your model, your infrastructure, your rules.

[![Tests](https://github.com/Fieldnote-Echo/grippy-code-review/actions/workflows/tests.yml/badge.svg)](https://github.com/Fieldnote-Echo/grippy-code-review/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Grippy reviews pull requests using any OpenAI-compatible model — GPT, Claude, Gemini, or a
local LLM running on your own hardware. It indexes your codebase for context-aware analysis,
scores PRs against a structured rubric, posts inline findings, and resolves stale threads.

It also happens to be a grumpy security auditor who is reluctantly impressed when you write
good code.

## Why Grippy?

**Your model, your infrastructure.** Run with OpenAI, or point it at Ollama, LM Studio, or
any OpenAI-compatible endpoint. Your code never leaves your network unless you choose to
send it. No SaaS vendor, no per-seat fees, no data sharing.

**Codebase-aware, not diff-blind.** Grippy indexes your repo into a LanceDB vector store
and searches it during review. It understands your codebase, not just the lines that
changed. Most open-source alternatives paywall this feature.

**Structured output, not just comments.** Every review produces typed findings with
severity, confidence scores, a rubric-based score out of 100, a pass/fail verdict, and
escalation recommendations. Machine-readable, not just human-readable.

**Security-first, not security-added.** Grippy is a security auditor that reviews code, not
a code reviewer that flags some security issues. Dedicated audit and governance modes,
structured escalations, hardened codebase tooling with path traversal and symlink
protections.

**It has opinions.** Not another faceless corporate bot. Grippy is a reluctant paperclip
inspector — constitutionally obligated to find your mistakes, passive-aggressive about it,
and secretly proud when there's nothing to report.

## What it looks like

When Grippy reviews a PR, you get inline findings like this:

> #### 🔴 CRITICAL: SQL injection via unsanitized user input
> **Confidence:** 95% &nbsp;|&nbsp; **Category:** security
>
> `user_query` is interpolated directly into the SQL string at line 42. This allows
> arbitrary SQL execution via crafted input.
>
> **Suggestion:** Use parameterized queries: `cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))`
>
> *— Grippy note: I've seen production databases wiped by less. Use parameters. Please.*

And a summary with a score, verdict, and personality:

> **Score: 45/100** | **Verdict: FAIL** | **Findings: 3** | **Merge-blocking: yes**
>
> *"I came in expecting the worst and you still managed to disappoint me."*

## Quick start

### GitHub Actions (OpenAI)

Add this workflow to `.github/workflows/grippy-review.yml`:

```yaml
name: Grippy Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    name: Grippy Code Review
    runs-on: ubuntu-latest
    steps:
      - name: Harden runner
        uses: step-security/harden-runner@a90bcbc6539c36a85cdfeb73f7e2f433735f215b  # v2.15.0
        with:
          egress-policy: audit

      - name: Checkout
        uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6

      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405  # v6
        with:
          python-version: '3.12'

      - name: Install Grippy
        run: pip install "grippy-code-review[persistence]"

      - name: Run Grippy review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_EVENT_PATH: ${{ github.event_path }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GRIPPY_TRANSPORT: openai
          GRIPPY_MODEL_ID: gpt-5.2
          GRIPPY_EMBEDDING_MODEL: text-embedding-3-large
          GRIPPY_DATA_DIR: ./grippy-data
          GRIPPY_TIMEOUT: '300'
        run: python -m grippy
```

### GitHub Actions (self-hosted LLM)

Run a local model with Ollama or LM Studio and expose it via Cloudflare Tunnel for
zero-trust access from GitHub Actions. See the
[Self-Hosted LLM Guide](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Self-Hosted-LLM-Guide)
on the wiki.

### Local development

```bash
# Install with uv (recommended)
uv add grippy-code-review[persistence]

# Or with pip
pip install "grippy-code-review[persistence]"
```

## Configuration

Grippy is configured entirely through environment variables.

| Variable | Purpose | Default |
|---|---|---|
| `GRIPPY_TRANSPORT` | API transport: `openai` or `local` | Inferred from `OPENAI_API_KEY` |
| `GRIPPY_MODEL_ID` | Model identifier | `devstral-small-2-24b-instruct-2512` |
| `GRIPPY_BASE_URL` | API endpoint for local transport | `http://localhost:1234/v1` |
| `GRIPPY_EMBEDDING_MODEL` | Embedding model name | `text-embedding-qwen3-embedding-4b` |
| `GRIPPY_API_KEY` | API key for non-OpenAI endpoints | — |
| `GRIPPY_DATA_DIR` | Persistence directory (vector index + graph) | `./grippy-data` |
| `GRIPPY_TIMEOUT` | Review timeout in seconds (`0` = none) | `0` |
| `OPENAI_API_KEY` | OpenAI API key (sets transport to `openai`) | — |
| `GITHUB_TOKEN` | GitHub API token (set automatically by Actions) | — |

## Review modes

| Mode | Trigger | Focus |
|---|---|---|
| `pr_review` | Default for all PRs | Balanced review across security, logic, reliability |
| `security_audit` | Configurable | Deep security-focused analysis |
| `governance_check` | Configurable | Compliance and governance rules |
| `surprise_audit` | PR title/body contains "production ready" | Full-scope audit with expanded checks |
| `cli` | Terminal usage | Formatted for terminal output |
| `github_app` | GitHub App integration | Formatted for GitHub comments |

## Documentation

See the [wiki](https://github.com/Fieldnote-Echo/grippy-code-review/wiki) for:
- [Getting Started](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Getting-Started) — Setup guides for OpenAI, local LLMs, and development
- [Architecture](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Architecture) — Module map, prompt system, data flow
- [Self-Hosted LLM Guide](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Self-Hosted-LLM-Guide) — Ollama/LM Studio + Cloudflare Tunnel + zero-trust access
- [Security Model](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Security-Model) — Codebase tool protections, hardened CI
- [Contributing](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Contributing) — Dev setup, testing, conventions

## License

[MIT](LICENSE)
```

**Step 2: Verify README renders**

```bash
# Check for broken markdown
cat README.md | head -20
```

Push and preview on GitHub, or use a local markdown previewer.

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: ground-up README rewrite with BYOM positioning"
```

---

### Task 3: Write wiki — Home page

**Files:**
- Create: `grippy-code-review-wiki/Home.md`

**Step 1: Write Home.md**

```markdown
# Grippy Code Review

Grippy is an open-source AI code review agent that runs with any OpenAI-compatible model.
It indexes your codebase for context-aware analysis, scores PRs against a structured rubric,
and posts inline findings — all as a grumpy security auditor who is reluctantly thorough.

## Pages

- **[Getting Started](Getting-Started)** — Setup for OpenAI, local LLMs, and local development
- **[Configuration](Configuration)** — Environment variables and model options
- **[Architecture](Architecture)** — Modules, prompt composition, data flow
- **[Review Modes](Review-Modes)** — The 6 review modes and how they work
- **[Scoring Rubric](Scoring-Rubric)** — How Grippy scores PRs
- **[Security Model](Security-Model)** — Codebase tool protections and CI hardening
- **[Self-Hosted LLM Guide](Self-Hosted-LLM-Guide)** — Run your own model with Cloudflare Tunnel
- **[Contributing](Contributing)** — Development setup, testing, and conventions

## Quick links

- [GitHub repository](https://github.com/Fieldnote-Echo/grippy-code-review)
- [MIT License](https://github.com/Fieldnote-Echo/grippy-code-review/blob/main/LICENSE)
- [Issue tracker](https://github.com/Fieldnote-Echo/grippy-code-review/issues)
```

**Step 2: Commit to wiki repo**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Home.md
git commit -m "docs: wiki home page"
```

---

### Task 4: Write wiki — Getting Started

**Files:**
- Create: `grippy-code-review-wiki/Getting-Started.md`

**Step 1: Write Getting-Started.md**

Cover three paths:

1. **GitHub Actions + OpenAI** — Copy the workflow from the README, add `OPENAI_API_KEY` secret, done.
2. **GitHub Actions + Local LLM** — Brief intro, link to Self-Hosted LLM Guide for the full tutorial.
3. **Local development** — Clone, `uv sync`, set env vars, `python -m grippy`.

Include:
- Prerequisites (Python 3.12+, GitHub repo, API key or local model)
- Step-by-step for each path
- How to verify it's working (check PR comments, check Actions logs)
- Caching setup (`actions/cache` for `GRIPPY_DATA_DIR`)
- GitHub Actions outputs (`score`, `verdict`, `findings-count`, `merge-blocking`)

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Getting-Started.md
git commit -m "docs: getting started guide"
```

---

### Task 5: Write wiki — Configuration

**Files:**
- Create: `grippy-code-review-wiki/Configuration.md`

**Step 1: Write Configuration.md**

Full env var reference table (expand from README):
- `GRIPPY_TRANSPORT` — `openai` | `local`. If unset, inferred from `OPENAI_API_KEY` presence.
- `GRIPPY_MODEL_ID` — Any model ID your endpoint supports. Default: `devstral-small-2-24b-instruct-2512`.
- `GRIPPY_BASE_URL` — Endpoint URL. Default: `http://localhost:1234/v1`. Set to your cloudflared tunnel URL for self-hosted.
- `GRIPPY_EMBEDDING_MODEL` — Embedding model. Default: `text-embedding-qwen3-embedding-4b`. Use `text-embedding-3-large` for OpenAI.
- `GRIPPY_API_KEY` — API key for non-OpenAI endpoints. Used as fallback for embedding auth.
- `GRIPPY_DATA_DIR` — Where LanceDB and SQLite data are stored. Default: `./grippy-data`.
- `GRIPPY_TIMEOUT` — Review timeout. `0` = no timeout. Recommended: `300` for CI.
- `OPENAI_API_KEY` — Sets transport to `openai` automatically.
- `GITHUB_TOKEN` — Set automatically by GitHub Actions. Needs `contents: read` + `pull-requests: write`.
- `GITHUB_EVENT_PATH` — Path to PR event JSON. Set automatically by GitHub Actions.

Add a section on model recommendations:
- **Fast/cheap:** `gpt-4.1-mini`, local `devstral-small`
- **Thorough:** `gpt-5.2`, `claude-sonnet-4-20250514`
- **Embeddings:** `text-embedding-3-large` (OpenAI), `text-embedding-qwen3-embedding-4b` (local)

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Configuration.md
git commit -m "docs: configuration reference"
```

---

### Task 6: Write wiki — Architecture

**Files:**
- Create: `grippy-code-review-wiki/Architecture.md`

**Step 1: Write Architecture.md**

Sections:

**Data flow:**
```
PR event → load metadata + diff → create agent → index codebase → run review → post findings
```

**Module map** (one-line descriptions for each module):
- `review.py` — Orchestration entry point
- `agent.py` — Agent factory (transport resolution, prompt composition, tool attachment)
- `codebase.py` — Codebase indexing (LanceDB) and toolkit (read_file, grep_code, list_files)
- `github_review.py` — GitHub API: diff parsing, inline comments, thread resolution
- `schema.py` — Pydantic models for structured review output
- `prompts.py` — Prompt chain loader (21 markdown files)
- `persistence.py` — Dual-backend store (SQLite + LanceDB) for codebase knowledge
- `graph.py` — Graph data model (nodes, edges, types)
- `retry.py` — Structured output validation with retry
- `embedder.py` — Embedding model factory

**Prompt composition system:**
1. Identity layer (CONSTITUTION.md + PERSONA.md) → Agno `description`
2. Instruction layer (mode chain + shared prompts + suffix) → Agno `instructions`
3. The 21 files and what each does

**Codebase indexing pipeline:**
1. `walk_source_files()` — git ls-files, 5000 file limit
2. `chunk_file()` — 4KB chunks, 200 char overlap
3. `CodebaseIndex.index()` — embed chunks into LanceDB
4. Tools search the index during review

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Architecture.md
git commit -m "docs: architecture overview"
```

---

### Task 7: Write wiki — Review Modes

**Files:**
- Create: `grippy-code-review-wiki/Review-Modes.md`

**Step 1: Write Review-Modes.md**

For each of the 6 modes, document:
- Name and when it activates
- What prompt chain it uses (reference `prompts.py` MODE_CHAINS)
- What it focuses on
- Brief example of when you'd use it

Special sections:
- **Surprise audit trigger:** If a PR title or body contains "production ready", Grippy switches to `surprise_audit` mode with expanded scope and the Gene Parmesan disguise mechanic.
- **The Gene Parmesan protocol:** Grippy may pose as a routine linter before revealing itself as a full security auditor. Described in `disguises.md`.

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Review-Modes.md
git commit -m "docs: review modes guide"
```

---

### Task 8: Write wiki — Scoring Rubric

**Files:**
- Create: `grippy-code-review-wiki/Scoring-Rubric.md`

**Step 1: Write Scoring-Rubric.md**

Reference `src/grippy/prompts_data/scoring-rubric.md` for the actual rubric. Document:
- The 5 dimensions: security, logic, governance, reliability, observability
- How each dimension is scored (0-100)
- Deduction rules by severity (CRITICAL, HIGH, MEDIUM, LOW)
- Overall score calculation
- Verdict thresholds: PASS (≥80), PROVISIONAL (≥60), FAIL (<60)
- What `merge_blocking` means

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Scoring-Rubric.md
git commit -m "docs: scoring rubric reference"
```

---

### Task 9: Write wiki — Security Model

**Files:**
- Create: `grippy-code-review-wiki/Security-Model.md`

**Step 1: Write Security-Model.md**

Sections:
- **Codebase tool protections:** Path traversal (`Path.is_relative_to()`), symlink-aware grep (`-S` flag), result limits (5000 files, 500 glob, 12000 chars per response)
- **CI hardening:** SHA-pinned GitHub Actions, `harden-runner`, minimal permissions (`contents: read`, `pull-requests: write`), dependency auditing (pip-audit), security scanning (bandit, CodeQL)
- **Error sanitization:** Internal paths and stack traces are never leaked to PR comments. Generic error messages with links to Actions logs.
- **The CONSTITUTION:** 12 immutable invariants that constrain the agent (accuracy over personality, no blanket approvals, injection resistance, etc.)
- **Data flow:** What data goes where — diff text to LLM, file chunks to LanceDB, nothing leaves the runner unless you configure an external API

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Security-Model.md
git commit -m "docs: security model"
```

---

### Task 10: Write wiki — Self-Hosted LLM Guide

**Files:**
- Create: `grippy-code-review-wiki/Self-Hosted-LLM-Guide.md`

**Step 1: Write Self-Hosted-LLM-Guide.md**

This is the crown jewel — the full zero-trust BYOM tutorial.

**Prerequisites:**
- Machine with GPU (or CPU for small models like Devstral-Small)
- Cloudflare account (free tier)
- GitHub repo with Actions enabled

**Section 1: Set up the model server**

Two options, side by side:

*Ollama:*
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull devstral-small

# Verify — Ollama serves on port 11434 by default
curl http://localhost:11434/v1/models
```

*LM Studio:*
- Download from lmstudio.ai
- Load a model (e.g., Devstral-Small-2505)
- Start server on port 1234 (Settings → Local Server)
- Verify: `curl http://localhost:1234/v1/models`

**For embeddings** — run a second model or use the same endpoint if your model supports embeddings:

*Ollama:*
```bash
ollama pull nomic-embed-text
# Ollama serves embeddings on the same port
```

*LM Studio:*
- Load an embedding model alongside the chat model
- Both served on the same port

**Section 2: Create a Cloudflare Tunnel**

```bash
# Install cloudflared
# macOS: brew install cloudflare/cloudflare/cloudflared
# Linux: see https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# Authenticate
cloudflared tunnel login

# Create a named tunnel
cloudflared tunnel create grippy-llm

# Note the tunnel ID and credentials file path from the output
```

Create the tunnel config at `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/<user>/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: grippy-llm.yourdomain.com
    service: http://localhost:1234    # LM Studio
    # service: http://localhost:11434  # Ollama
  - service: http_status:404
```

Add a DNS record:
```bash
cloudflared tunnel route dns grippy-llm grippy-llm.yourdomain.com
```

Start the tunnel:
```bash
cloudflared tunnel run grippy-llm
```

Verify from outside your network:
```bash
curl https://grippy-llm.yourdomain.com/v1/models
```

**Section 3: Set up Cloudflare Access (zero trust)**

Without Access, anyone who discovers your tunnel URL can use your LLM endpoint. Cloudflare Access adds authentication.

1. Go to [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com)
2. Navigate to **Access → Applications → Add an application**
3. Choose **Self-hosted**
4. Set the application domain to `grippy-llm.yourdomain.com`
5. Create a policy:
   - **Policy name:** `grippy-github-action`
   - **Action:** Service Auth
   - **Include:** Service Token
6. Navigate to **Access → Service Auth → Service Tokens**
7. Create a service token — save the **Client ID** and **Client Secret**

Test with the service token:
```bash
curl -H "CF-Access-Client-Id: <CLIENT_ID>" \
     -H "CF-Access-Client-Secret: <CLIENT_SECRET>" \
     https://grippy-llm.yourdomain.com/v1/models
```

**Section 4: Configure GitHub Actions**

Add secrets to your repository (Settings → Secrets and variables → Actions):
- `CF_ACCESS_CLIENT_ID` — the Cloudflare service token Client ID
- `CF_ACCESS_CLIENT_SECRET` — the Cloudflare service token Client Secret

Note: Grippy uses the OpenAI Python SDK under the hood (via Agno). The SDK sends the API key as a `Bearer` token in the `Authorization` header. For Cloudflare Access, the service token headers (`CF-Access-Client-Id`, `CF-Access-Client-Secret`) are needed instead.

There are two approaches:

**Option A: Cloudflare Access with service token bypass (recommended)**

Configure your Cloudflare Access policy to also accept a specific API key as a bypass. Then set `GRIPPY_API_KEY` to that key. This is simpler because the OpenAI SDK sends it as `Authorization: Bearer <key>` which Cloudflare Access can validate.

Alternatively, configure Cloudflare Access to allow all traffic from GitHub Actions IP ranges (less secure but zero-config on the client side).

**Option B: Custom headers via wrapper**

If you need the `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers specifically, you would need to wrap the endpoint or use a Cloudflare Worker to translate auth headers.

**Workflow configuration:**

```yaml
- name: Run Grippy review
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
    GITHUB_EVENT_PATH: ${{ github.event_path }}
    GRIPPY_TRANSPORT: local
    GRIPPY_BASE_URL: https://grippy-llm.yourdomain.com/v1
    GRIPPY_API_KEY: ${{ secrets.CF_ACCESS_CLIENT_SECRET }}
    GRIPPY_MODEL_ID: devstral-small
    GRIPPY_EMBEDDING_MODEL: nomic-embed-text
    GRIPPY_DATA_DIR: ./grippy-data
    GRIPPY_TIMEOUT: '300'
  run: python -m grippy
```

**Section 5: Running cloudflared as a service**

For always-on operation:
```bash
# Install as a system service (Linux)
sudo cloudflared service install

# Or use systemd directly
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

**Section 6: Security considerations**

- The tunnel + Access policy ensures only your GitHub Action can reach the LLM
- No code leaves your network — the model runs locally, Grippy runs in the Actions runner
- The only data sent to Cloudflare is encrypted tunnel traffic — Cloudflare cannot read it
- Rotate service tokens periodically
- Monitor tunnel access logs in the Zero Trust dashboard
- Consider running the model server in a container for additional isolation

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Self-Hosted-LLM-Guide.md
git commit -m "docs: self-hosted LLM guide with Cloudflare Access"
```

---

### Task 11: Write wiki — Contributing

**Files:**
- Create: `grippy-code-review-wiki/Contributing.md`

**Step 1: Write Contributing.md**

Sections:
- **Dev setup:** Clone, `uv sync`, `uv run pre-commit install`
- **Running tests:** `uv run pytest tests/ -v`, single file, single test, with coverage
- **Linting:** `uv run ruff check src/grippy/ tests/`, format check, mypy
- **Security scanning:** `uv run bandit -c pyproject.toml -r src/grippy/`
- **Code conventions:** Python 3.12+, SPDX headers, ruff formatting (line length 100), mypy strict
- **Pre-commit hooks:** What they check, how to run manually (`uv run pre-commit run --all-files`)
- **PR process:** Branch off main, CI must pass (tests, lint, audit, pre-commit, CodeQL)
- **Commit style:** Imperative, lowercase, `fix:` / `feat:` / `chore:` / `docs:` prefixes

**Step 2: Commit**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git add Contributing.md
git commit -m "docs: contributing guide"
```

---

### Task 12: Push wiki and README, open PR

**Step 1: Push wiki**

```bash
cd /home/ndspence/GitHub/grippy-code-review-wiki
git push origin master
```

(Wiki repos use `master` by default, not `main`.)

**Step 2: Verify wiki pages render**

Visit `https://github.com/Fieldnote-Echo/grippy-code-review/wiki` and check each page.

**Step 3: Push README branch and open PR**

```bash
cd /home/ndspence/GitHub/grippy-code-review
git push -u origin docs/readme-and-wiki-refresh
gh pr create --title "docs: ground-up README rewrite + wiki" --body "$(cat <<'EOF'
## Summary
- Complete README rewrite with BYOM-first positioning
- Remove stale content (.grippy.yaml, finding lifecycle, requirements-dev.txt)
- Add accurate env var table, SHA-pinned workflow example, review modes
- Created 8 wiki pages: Home, Getting Started, Configuration, Architecture, Review Modes, Scoring Rubric, Security Model, Self-Hosted LLM Guide, Contributing

## Wiki pages
https://github.com/Fieldnote-Echo/grippy-code-review/wiki

## Test plan
- [ ] README renders correctly on GitHub
- [ ] All wiki links resolve
- [ ] Workflow example matches actual grippy-review.yml
- [ ] Env var table matches code defaults in review.py
- [ ] No references to removed features (.grippy.yaml, finding lifecycle)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Step 4: Verify CI passes**

```bash
gh pr checks <PR_NUMBER> --watch
```

---

### Task 13: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update architecture and module descriptions**

Update the CLAUDE.md Architecture section to remove stale references:
- Remove mention of finding lifecycle tracking in `github_review.py` description
- Remove mention of `schema.py` finding fingerprinting
- Update `persistence.py` description to focus on codebase knowledge (not finding lifecycle)
- Ensure env var table matches `review.py` docstring

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md to match post-refactor codebase"
```
