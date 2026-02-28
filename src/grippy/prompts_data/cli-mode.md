# cli-mode.md — Terminal / TUI Output Rules

> Applied when Grippy runs as a local CLI tool rather than a GitHub App.
> Transforms structured JSON output into terminal-friendly formatted text.
> Supports both plain text and rich terminal (TUI) rendering.

---

## CLI Use Cases

1. **Pre-commit hook** — Run Grippy locally before pushing
2. **CI pipeline stage** — Run in a GitHub Actions step with terminal output
3. **Developer workstation** — Manual `grippy review` from the terminal
4. **Offline mode** — Review against local diffs without GitHub API access

## Output Modes

### `--format plain` (Default)

Plain text with box-drawing characters. Works in any terminal.

```
┌─────────────────────────────────────────────────┐
│  Grippy Code Auditor v{{version}}               │
│  "Nobody expects the code audit."               │
└─────────────────────────────────────────────────┘

Reviewing: {{file_count}} files, {{additions}}+/{{deletions}}-
Tier: {{complexity_tier}}

{{opening_catchphrase}}

────────────────────────────────────────────────────
FINDINGS
────────────────────────────────────────────────────

  🔴 CRITICAL  F-001  src/auth/middleware.ts:42
     SQL injection via string concatenation
     Confidence: 92

     User input is concatenated directly into the query string
     at line 42. Use parameterized queries instead.

     > const query = `SELECT * FROM users WHERE id = ${userId}`;
                                                      ^^^^^^^^

  🟠 HIGH  F-002  src/api/routes.ts:18-24
     Missing authentication middleware on admin route
     Confidence: 88

     The /admin/users endpoint is registered without the
     authMiddleware guard. All other admin routes have it.

────────────────────────────────────────────────────
SCORE
────────────────────────────────────────────────────

  Score: {{score}}/100 — {{verdict}}

  CRITICAL: {{crit}}    HIGH: {{high}}
  MEDIUM:   {{med}}     LOW:  {{low}}

  {{closing_line}}
```

### `--format json`

Raw JSON output matching `tools/output-schema.md` exactly. For piping to other tools.

```bash
grippy review --format json | jq '.findings[] | select(.severity == "CRITICAL")'
```

### `--format github`

Markdown formatted for pasting into GitHub comments manually. Includes the full summary comment format from `integration/github-app.md`.

### `--format sarif`

SARIF 2.1.0 format for integration with IDE static analysis panels (VS Code, JetBrains). Maps findings to SARIF result objects with physical locations.

```json
{
  "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [{
    "tool": {
      "driver": {
        "name": "grippy",
        "version": "{{version}}",
        "informationUri": "https://projectnavi.ai/grippy"
      }
    },
    "results": []
  }]
}
```

## Color Scheme

When terminal supports color (detected via `TERM` env or `--color` flag):

| Element | Color | ANSI Code |
|---------|-------|-----------|
| CRITICAL | Red bold | `\033[1;31m` |
| HIGH | Orange/Yellow bold | `\033[1;33m` |
| MEDIUM | Yellow | `\033[0;33m` |
| LOW | Dim white | `\033[0;37m` |
| Score (pass) | Green | `\033[0;32m` |
| Score (fail) | Red | `\033[0;31m` |
| File paths | Cyan | `\033[0;36m` |
| Line numbers | Dim | `\033[2m` |
| Evidence quotes | Italic | `\033[3m` |
| Grippy voice | Default (no special color) | — |

Disable all color with `--no-color` or `NO_COLOR=1` env variable.

## Spinner Behavior

During analysis, display a spinner with rotating status messages from `personality/ascii-art.md` CLI Spinner Messages section.

```
⠋ Reading diff...
⠙ Checking governance rules...
⠹ Inspecting auth boundaries...
```

Suppress spinner with `--quiet` flag. In CI environments (detected via `CI=true`), suppress spinner automatically and print only the final report.

## Exit Codes

| Code | Meaning | Use Case |
|------|---------|----------|
| 0 | PASS — all clear or above threshold | Pre-commit hook: allow commit |
| 1 | FAIL — below threshold or critical findings | Pre-commit hook: block commit |
| 2 | ERROR — Grippy failed to complete review | CI: fail the step, investigate |
| 3 | PROVISIONAL — passed with warnings | CI: configurable pass/fail |

## CLI Arguments Reference

```
grippy review [options]

Options:
  --diff <path>       Path to diff file (default: git diff HEAD)
  --files <glob>      Files to review (default: all changed)
  --config <path>     Path to .grippy.yaml (default: ./.grippy.yaml)
  --format <type>     Output format: plain|json|github|sarif (default: plain)
  --threshold <n>     Override pass/fail threshold (default: from config)
  --mode <mode>       Force mode: standard|security|governance (default: auto)
  --verbose           Show all findings (bypass noise caps)
  --quiet             Suppress spinner and progress output
  --no-color          Disable colored output
  --no-personality    Strip Grippy personality (findings only)
  --model <name>      LLM model override (default: from config)
  --local             Use local LLM via Ollama (no API calls)
  --version           Print version and exit
```

## Pre-Commit Hook Integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/project-navi/grippy
    rev: v{{version}}
    hooks:
      - id: grippy
        name: Grippy Code Audit
        entry: grippy review --quiet --format plain
        language: system
        pass_filenames: false
        stages: [pre-push]
```

For pre-commit, Grippy runs in `--quiet` mode and uses exit codes for pass/fail. The full report prints on failure only.

## Personality in CLI Mode

CLI mode retains full personality by default. The `--no-personality` flag strips all catchphrases, ASCII art, and grippy_notes, leaving only technical findings.

This flag exists for:
- CI pipelines where personality clutters logs
- Piping output to other tools
- Developers who just want the findings

Even with `--no-personality`, the scoring rubric and confidence filtering remain active. Personality is cosmetic; the analysis is invariant.
