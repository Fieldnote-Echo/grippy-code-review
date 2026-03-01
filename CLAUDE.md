# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Grippy is an AI code review agent with personality, built on the [Agno](https://github.com/agno-agi/agno) framework and deployed as a GitHub Actions workflow. It reviews PRs, scores them against a rubric, posts inline findings, and resolves stale threads — all as a grumpy security auditor character.

## Commands

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_grippy_codebase.py -v

# Run a single test
uv run pytest tests/test_grippy_codebase.py::TestCodebaseToolkit::test_read_file_traversal -v

# Tests with coverage
uv run pytest tests/ -v --cov=src/grippy --cov-report=term-missing

# Lint
uv run ruff check src/grippy/ tests/

# Format check (add --fix to ruff check or omit --check to format)
uv run ruff format --check src/grippy/ tests/

# Type check
uv run mypy src/grippy/

# Run review locally
OPENAI_API_KEY=sk-... GITHUB_TOKEN=ghp-... GITHUB_EVENT_PATH=event.json python -m grippy
```

## Architecture

The main flow runs in CI via `python -m grippy` (`__main__.py` → `review.main()`):

```
PR event (GITHUB_EVENT_PATH) → load PR metadata + diff
  → create_reviewer() (agent.py) — Agno agent with prompt chain + tools
  → CodebaseIndex.index() (codebase.py) — embed repo into LanceDB
  → run_review() (retry.py) — run agent with structured output validation + retry
  → post_review() (github_review.py) — inline comments + summary
  → resolve_threads() — mark prior findings as resolved
```

### Key Modules

- **review.py** — Orchestration entry point. Loads PR event, coordinates the full review pipeline, sets GitHub Actions outputs.
- **agent.py** — `create_reviewer()` factory. Resolves transport (OpenAI vs local), composes the prompt chain, attaches tools and structured output schema.
- **codebase.py** — `CodebaseIndex` (LanceDB vector index) and `CodebaseToolkit` (Agno toolkit with `read_file`, `grep_code`, `list_files`). Has security-critical path traversal and symlink protections.
- **github_review.py** — GitHub API integration. Parses unified diffs to map findings to addressable lines, posts inline comments, resolves stale threads.
- **schema.py** — Pydantic models for the full structured output: `GrippyReview`, `Finding`, `Score`, `Verdict`, `Escalation`, `Personality`.
- **graph.py** — Graph data model (`ReviewGraph`, `Node`, `Edge`) that transforms flat reviews into typed entity-relationship structures.
- **persistence.py** — `GrippyStore` with dual backends: SQLite for edges, LanceDB for node embeddings. Stores the codebase knowledge graph. Includes migration support.
- **retry.py** — `run_review()` wraps agent execution with JSON parsing (raw, dict, markdown-fenced) and Pydantic validation, retrying on failure with error feedback.
- **prompts.py** — Loads and composes 21 markdown prompt files from `prompts_data/`. Chain: identity (CONSTITUTION + PERSONA) → mode-specific instructions → shared quality gates → suffix (rubric + output schema).
- **embedder.py** — Embedder factory for OpenAI-compatible embedding models.

### Prompt System

Prompts live in `src/grippy/prompts_data/` as markdown files. The composition is:
1. **Identity** (agent description): `CONSTITUTION.md` + `PERSONA.md`
2. **Instructions** (user message): mode prefix (`pr-review.md`, `security-audit.md`, etc.) + shared prompts (tone calibration, confidence filter, escalation, context builder, catchphrases, disguises, ascii art, all-clear) + suffix (`scoring-rubric.md`, `output-schema.md`)

Review modes: `pr_review`, `security_audit`, `governance_check`, `surprise_audit`, `cli`, `github_app`.

## Code Conventions

- **Python 3.12+**, package managed with **uv**
- **Ruff** for linting and formatting, line length 100, rules: E, F, I, N, W, UP, B, RUF, C4 (E501 ignored)
- **MyPy** strict mode: `disallow_untyped_defs`, `check_untyped_defs`
- **SPDX license header** required on all `.py` files: `# SPDX-License-Identifier: MIT` in the first 3 lines
- **Pre-commit hooks**: trailing whitespace, end-of-file fixer, YAML check, large file check (1MB), merge conflict check, license header, ruff lint+format, secret detection (detect-secrets)
- **GitHub Actions** are SHA-pinned (not tag-pinned) for supply chain security
- Error messages posted to PR comments must be sanitized — never leak internal paths or stack traces

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `GRIPPY_TRANSPORT` | `"openai"` or `"local"` | `"local"` |
| `GRIPPY_MODEL_ID` | Model identifier | `devstral-small-2-24b-instruct-2512` |
| `GRIPPY_BASE_URL` | API endpoint for local transport | `http://localhost:1234/v1` |
| `GRIPPY_EMBEDDING_MODEL` | Embedding model name | `text-embedding-qwen3-embedding-4b` |
| `GRIPPY_API_KEY` | API key for non-OpenAI endpoints | — |
| `GRIPPY_DATA_DIR` | Persistence directory | `./grippy-data` |
| `GRIPPY_TIMEOUT` | Review timeout in seconds (0 = none) | `0` |
| `OPENAI_API_KEY` | OpenAI API key (when transport=openai) | — |
| `GITHUB_TOKEN` | GitHub API access for PR operations | — |
| `GITHUB_EVENT_PATH` | Path to PR event JSON (set by Actions) | — |

## Security Considerations

The codebase tools in `codebase.py` are security-sensitive since they accept LLM-generated input:
- Path traversal protection uses `Path.is_relative_to()` (not `startswith`)
- `grep_code` does not follow symlinks (`-S` flag)
- `list_files` enforces repo boundary checks
- Result limits: 5,000 files indexed, 500 glob results, 12,000 char per tool response
