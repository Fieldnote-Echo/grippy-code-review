# Grippy Code Review

AI code review agent with personality. Built on [Agno](https://github.com/agno-agi/agno), deployed as a GitHub Actions workflow.

Grippy reviews your pull requests, scores them, posts inline findings, and resolves stale threads — all with the charm of a grumpy security auditor who secretly respects good code.

## What it does

- Reviews PR diffs against a structured scoring rubric
- Posts inline findings with confidence-calibrated severity
- Tracks finding lifecycle across review rounds (NEW / PERSISTS / RESOLVED)
- Indexes your codebase for context-aware reviews (reduces false positives)
- Supports multiple review modes: PR review, security audit, governance check, surprise audit

## Quick start

### GitHub Actions

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
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
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
          GRIPPY_DATA_DIR: ./grippy-data
        run: python -m grippy
```

### Local

```bash
pip install "grippy-code-review[persistence]"
python -m grippy
```

## Configuration

Create `.grippy.yaml` in your repo root:

```yaml
review:
  modes: [pr_review, security_audit]
  default_mode: pr_review

thresholds:
  pass: 80
  provisional: 60
```

## Architecture

```
PR opened → CI checkout → Index codebase → Embed into LanceDB
                                                  ↓
                      Grippy reviews diff ←→ search_code / grep_code / read_file / list_files
                                                  ↓
                                          Score + inline findings → PR comments
```

**Modules:** `agent`, `schema`, `graph`, `persistence`, `review`, `retry`, `prompts`, `embedder`, `codebase`, `github_review`

## Development

```bash
# Install dev dependencies
pip install -e ".[persistence]" && pip install -r requirements-dev.txt
# Or with uv:
uv sync

# Run tests
uv run pytest tests/ -v

# Lint + type check
uv run ruff check src/grippy/ tests/
uv run mypy src/grippy/
```

## License

[MIT](LICENSE)
