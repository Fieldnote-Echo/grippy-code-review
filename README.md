# Grippy Code Review

> Open-source AI code review agent. Your model, your infrastructure, your rules.

[![Tests](https://github.com/Fieldnote-Echo/grippy-code-review/actions/workflows/tests.yml/badge.svg)](https://github.com/Fieldnote-Echo/grippy-code-review/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)

Grippy reviews pull requests using any OpenAI-compatible model — GPT, Claude, or a local LLM running on your own hardware. It indexes your codebase into a vector store for context-aware analysis, then posts structured findings with scores, verdicts, and escalation paths. It also happens to be a grumpy security auditor who secretly respects good code.

## Why Grippy?

- **Your model, your infrastructure.** Bring your own model. No SaaS dependency, no per-seat fees. Run GPT-5 through OpenAI, Claude through a compatible proxy, or a local model via Ollama or LM Studio.

- **Codebase-aware, not diff-blind.** Grippy embeds your repository into a LanceDB vector index and searches it during review. It understands the code around the diff, not just the diff itself. Most OSS alternatives paywall this behind a hosted tier.

- **Structured output, not just comments.** Every review produces typed findings with severity, confidence, and category. A score out of 100. A verdict (PASS / FAIL / PROVISIONAL). Escalation targets for findings that need human attention.

- **Security-first, not security-added.** Grippy is a security auditor that also reviews code, not the other way around. Dedicated audit modes go deeper than a general-purpose linter.

- **It has opinions.** Grippy is a grumpy security auditor persona, not a faceless bot. Good code gets grudging respect. Bad code gets disappointment. The personality keeps reviews readable and honest.

## What it looks like

An inline finding on a PR diff:

> **CRITICAL** | `security` | confidence: 95
>
> **SQL injection via string interpolation**
>
> `query = f"SELECT * FROM users WHERE id = {user_id}"` constructs a SQL query from unsanitized input. Use parameterized queries.
>
> *grippy_note: I've seen production databases get wiped by less. Parameterize it or I'm telling the security team.*

A review summary posted as a PR comment:

> **Score: 45/100** | Verdict: **FAIL** | Complexity: STANDARD
>
> 3 findings (1 critical, 1 high, 1 medium) | 1 escalation to security-team
>
> *"I've reviewed thousands of PRs. This one made me mass in-progress a packet of antacids."*

## Quick start

### GitHub Actions (OpenAI)

Add `.github/workflows/grippy-review.yml` to your repo:

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
      - uses: step-security/harden-runner@a90bcbc6539c36a85cdfeb73f7e2f433735f215b  # v2.15.0
        with:
          egress-policy: audit

      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6

      - uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405  # v6
        with:
          python-version: '3.12'

      - name: Install Grippy
        run: pip install "grippy-code-review[persistence]"

      - name: Run review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_EVENT_PATH: ${{ github.event_path }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GRIPPY_TRANSPORT: openai
          GRIPPY_MODEL_ID: gpt-5.2
          GRIPPY_EMBEDDING_MODEL: text-embedding-3-large
          GRIPPY_DATA_DIR: ./grippy-data
          GRIPPY_TIMEOUT: 300
        run: python -m grippy
```

### GitHub Actions (self-hosted LLM)

Grippy works with any OpenAI-compatible API endpoint, including Ollama, LM Studio, and vLLM. We recommend **Devstral-Small 24B at Q4 quantization or higher** — tested during development for structured output compliance and review quality. See the [Self-Hosted LLM Guide](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Self-Hosted-LLM-Guide) on the wiki for full setup instructions.

### Local development

```bash
# With uv (recommended)
uv add "grippy-code-review[persistence]"

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
| `GRIPPY_DATA_DIR` | Persistence directory | `./grippy-data` |
| `GRIPPY_TIMEOUT` | Review timeout in seconds (0 = none) | `0` |
| `OPENAI_API_KEY` | OpenAI API key (sets transport to `openai`) | — |
| `GITHUB_TOKEN` | GitHub API token (set automatically by Actions) | — |

## Review modes

| Mode | Trigger | Focus |
|---|---|---|
| `pr_review` | Default on PR events | Full code review: correctness, security, style, maintainability |
| `security_audit` | Manual or scheduled | Deep security analysis: injection, auth, cryptography, data exposure |
| `governance_check` | Manual or scheduled | Compliance and policy: licensing, access control, audit trails |
| `surprise_audit` | PR title/body contains "production ready" | Full-scope audit with expanded governance checks |
| `cli` | Local invocation | Interactive review for local development and testing |
| `github_app` | GitHub App webhook | Event-driven review via installed GitHub App |

## Documentation

- [Getting Started](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Getting-Started) — Setup for OpenAI, local LLMs, and development
- [Configuration](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Configuration) — Environment variables and model options
- [Architecture](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Architecture) — Module map, prompt system, data flow
- [Review Modes](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Review-Modes) — The 6 review modes and how they work
- [Scoring Rubric](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Scoring-Rubric) — How Grippy scores PRs
- [Security Model](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Security-Model) — Codebase tool protections, hardened CI
- [Self-Hosted LLM Guide](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Self-Hosted-LLM-Guide) — Ollama/LM Studio + Cloudflare Tunnel
- [Contributing](https://github.com/Fieldnote-Echo/grippy-code-review/wiki/Contributing) — Dev setup, testing, conventions

## License

[MIT](LICENSE)
