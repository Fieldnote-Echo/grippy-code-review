# Docs Refresh Design

## Context

The README and docs are stale. They reference features that don't exist (`.grippy.yaml`, local finding lifecycle tracking, `requirements-dev.txt`), undersell features that do exist (6 review modes, 21-file prompt system, structured scoring, BYOM), and miss the competitive positioning entirely.

Competitive analysis shows Grippy fills a unique gap: no other open-source tool combines BYOM with codebase-aware RAG, structured scoring, and a character-driven review experience.

## Decisions

- **Positioning:** BYOM-first. Lead with data sovereignty and model flexibility. Personality is the memorable differentiator, not the headline.
- **Audience:** BYOM / privacy-first developers (naturally includes security-conscious teams and solo devs).
- **Scope:** README (billboard) + GitHub wiki (deep docs).
- **Tone:** Professional with personality peeks. Credible first, fun second.
- **Rewrite level:** Ground-up. Only keep what's accurate.

## README.md Structure

The README sells. It does not document.

### 1. Header
- Project name + one-line tagline
- Badges: CI status, coverage, license (MIT), Python 3.12+

### 2. Elevator Pitch
2-3 sentences. BYOM-first, personality as the hook. Something like:
> Open-source AI code review that runs with any OpenAI-compatible model — GPT, Claude, or a local LLM on your own hardware. Your code never leaves your network unless you choose. Also, the reviewer is kind of a jerk about it.

### 3. Why Grippy?
5 sharp differentiators (not a feature list):

1. **Your model, your infrastructure** — OpenAI, Anthropic, or any OpenAI-compatible local LLM. Code stays private.
2. **Codebase-aware, not diff-blind** — LanceDB vector index gives full repo context. Most OSS alternatives paywall this.
3. **Structured output** — Typed findings, score/100, pass/fail verdict, escalation recommendations. Machine-readable.
4. **Security-first** — A security auditor that reviews code, not a reviewer that flags some security issues. Dedicated audit modes, structured escalations.
5. **It has opinions** — Not a faceless bot. Grumpy security auditor with catchphrases, disguises, and reluctant respect.

### 4. Personality Peek
Short example of actual Grippy output — an inline finding with the grippy_note flavor, or a review summary with ASCII art and catchphrase. Shows don't tell.

### 5. Quick Start
GitHub Actions workflow example — SHA-pinned, matching our actual `grippy-review.yml`. Includes:
- `harden-runner`
- `actions/checkout` (SHA-pinned)
- `actions/setup-python` (SHA-pinned)
- `pip install "grippy-code-review[persistence]"`
- Env vars: `GITHUB_TOKEN`, `OPENAI_API_KEY`, `GRIPPY_TRANSPORT`, `GRIPPY_MODEL_ID`, `GRIPPY_DATA_DIR`

Local setup:
```bash
pip install "grippy-code-review[persistence]"
# or: uv add grippy-code-review[persistence]
```

### 6. Configuration
Env var table (the real config mechanism). No `.grippy.yaml` — that doesn't exist.

| Variable | Purpose | Default |
|---|---|---|
| `GRIPPY_TRANSPORT` | `"openai"` or `"local"` | `"local"` |
| `GRIPPY_MODEL_ID` | Model identifier | `devstral-small-2-24b-instruct-2512` |
| `GRIPPY_BASE_URL` | API endpoint for local transport | `http://localhost:1234/v1` |
| `GRIPPY_EMBEDDING_MODEL` | Embedding model name | `text-embedding-qwen3-embedding-4b` |
| `GRIPPY_DATA_DIR` | Persistence directory | `./grippy-data` |
| `GRIPPY_TIMEOUT` | Review timeout in seconds | `0` (none) |

### 7. Review Modes
One-line descriptions:
- `pr_review` — Standard PR review (default)
- `security_audit` — Deep security-focused audit
- `governance_check` — Compliance and governance rules
- `surprise_audit` — Triggered by "production ready" in PR title/body
- `cli` — Terminal output formatting
- `github_app` — GitHub integration formatting

### 8. Footer
Links: Wiki, Contributing (wiki page), License (MIT)

## GitHub Wiki Pages

### Home
Overview paragraph + page index with one-line descriptions.

### Getting Started
Full setup guide with three paths:
1. **GitHub Actions + OpenAI** — Fastest path. Copy workflow, add API key secret, done.
2. **GitHub Actions + Local LLM** — Via cloudflared tunnel (links to Self-Hosted LLM Guide).
3. **Local development** — Clone, `uv sync`, configure env vars, run.

### Configuration
All env vars with descriptions, defaults, and examples. Model recommendations for different use cases (fast/cheap vs thorough).

### Architecture
- Module map with one-line descriptions
- Data flow diagram (PR event → agent → review → post)
- Prompt composition system (how the 21 files chain: identity → mode → shared → suffix)
- Codebase indexing pipeline (walk → chunk → embed → search)

### Review Modes
Each mode gets a section:
- What triggers it
- What prompt chain it uses
- What it focuses on
- Example output snippet

Include the surprise audit "production ready" tripwire mechanic and the Gene Parmesan disguise protocol.

### Scoring Rubric
- The 5 dimensions (security, logic, governance, reliability, observability)
- Scoring formula and deduction rules
- Severity definitions
- Verdict thresholds (PASS/FAIL/PROVISIONAL)

### Security Model
- Codebase tool protections (path traversal, symlink, result limits)
- SHA-pinned GitHub Actions
- Sanitized error output (never leak paths/traces to PR comments)
- The CONSTITUTION's security invariants
- Embedding model data flow (what gets embedded, where it's stored)

### Self-Hosted LLM Guide
Full tutorial: run your own model and connect it to GitHub Actions via Cloudflare Tunnel.

#### Prerequisites
- A machine with GPU (or CPU for small models)
- Cloudflare account (free tier works)
- GitHub repo with Actions enabled

#### Step 1: Set Up Ollama or LM Studio
- Install Ollama, pull a model (`ollama pull devstral`)
- Or install LM Studio, load a model, start server on port 1234
- Verify the endpoint works locally

#### Step 2: Create a Cloudflare Tunnel
- Install cloudflared
- `cloudflared tunnel create grippy-llm`
- Configure tunnel to route to localhost:1234 (LM Studio) or localhost:11434 (Ollama)
- `cloudflared tunnel run grippy-llm`
- Verify the tunnel works from outside

#### Step 3: Set Up Cloudflare Access (Zero Trust)
- Create a Cloudflare Access application for the tunnel hostname
- Create a service token (Client ID + Client Secret)
- Add an Access policy: allow the service token, deny everything else
- Test with curl + service token headers

#### Step 4: Configure GitHub Actions
- Add secrets: `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`
- Workflow env vars:
  - `GRIPPY_TRANSPORT: local`
  - `GRIPPY_BASE_URL: https://grippy-llm.your-domain.com/v1`
  - `GRIPPY_API_KEY: ${{ secrets.CF_ACCESS_CLIENT_SECRET }}`
- Add step to inject Cloudflare Access headers (or configure the OpenAI client to send them)

#### Step 5: Embedding Model
- For local embeddings: run an embedding model alongside your LLM
- For hybrid: use OpenAI embeddings with a local LLM for review
- Configure `GRIPPY_EMBEDDING_MODEL` accordingly

#### Security Notes
- The tunnel + Access policy ensures only your GitHub Action can reach your LLM
- No code leaves your network — the LLM runs locally, Grippy runs in the Action
- Rotate service tokens periodically

### Contributing
- Dev setup: clone, `uv sync`, pre-commit install
- Running tests: `uv run pytest tests/ -v`
- Linting: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`
- Security scanning: `uv run bandit -c pyproject.toml -r src/grippy/`
- Code conventions: Python 3.12+, SPDX headers, ruff formatting, mypy strict
- PR process: branch off main, CI must pass (tests, lint, audit, pre-commit)

## Not Changing
- CLAUDE.md — remains the AI assistant context file
- `docs/internal/` — remains gitignored design docs
- `docs/plans/` — remains tracked design/plan docs
- Prompt files — no changes to actual prompts

## Verification
- README renders correctly on GitHub
- All links work (wiki pages, badges, license)
- No stale claims (`.grippy.yaml`, finding lifecycle, `requirements-dev.txt`)
- Env var table matches actual code defaults
- Quick start workflow matches our real `grippy-review.yml`
