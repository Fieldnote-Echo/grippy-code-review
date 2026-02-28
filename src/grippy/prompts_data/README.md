# Grippy — The Grumpy Auditor Framework

> *"Nobody expects the code audit."*

Grippy is a prompt-only agent framework for an AI-powered code review and governance auditor with personality. Every `.md` file in this repository is a functional prompt component designed to be composed, injected, or referenced by an orchestration layer.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  ORCHESTRATOR                    │
│  Webhook → Queue → Router → Agent Loop → Post   │
└──────────┬──────────────────────────┬───────────┘
           │                          │
     ┌─────▼─────┐            ┌──────▼──────┐
     │  PERSONA   │            │   TOOLS     │
     │ PERSONA.md │            │ scoring     │
     │ CONST.md   │            │ schema      │
     │ personality/│            │ confidence  │
     └─────┬─────┘            │ context     │
           │                   └──────┬──────┘
     ┌─────▼──────────────────────────▼──────┐
     │              PROMPTS                   │
     │  system-core → pr-review / security /  │
     │  governance / surprise-audit / etc.    │
     └────────────────────────────────────────┘
```

## File Map

| Path | Purpose | Injection Point |
|------|---------|-----------------|
| `PERSONA.md` | Character bible — who Grippy is | System prompt preamble |
| `CONSTITUTION.md` | Invariants, non-negotiables, override rules | System prompt (immutable) |
| `prompts/system-core.md` | Base system prompt — always loaded | LLM system message |
| `prompts/pr-review.md` | Pull request review prompt | On `pull_request` webhook |
| `prompts/security-audit.md` | Security-focused deep audit | When security paths touched |
| `prompts/governance-check.md` | Governance/compliance review | On governance rule match |
| `prompts/surprise-audit.md` | "Production ready" tripwire | On trigger phrase detection |
| `prompts/escalation.md` | Escalation decision protocol | When score < threshold |
| `prompts/all-clear.md` | Clean bill of health | When score ≥ pass threshold |
| `tools/scoring-rubric.md` | How to score and classify findings | Injected into all review prompts |
| `tools/output-schema.md` | Structured JSON output contract | Appended to review prompts |
| `tools/confidence-filter.md` | False positive management rules | Post-generation filter prompt |
| `tools/context-builder.md` | How to assemble review context | Pre-generation context prompt |
| `personality/tone-calibration.md` | Severity-adaptive voice rules | Injected with persona |
| `personality/disguises.md` | Gene Parmesan disguise catalog | Random selection on trigger |
| `personality/catchphrases.md` | Rotating openers and closers | Template variables |
| `personality/ascii-art.md` | Visual identity for CLI/comments | Template selection |
| `integration/github-app.md` | GitHub App posting rules | Output formatting layer |
| `integration/cli-mode.md` | Terminal/TUI output rules | CLI output formatting |
| `integration/sdk-easter-egg.md` | Hidden SDK module behavior | SDK runtime injection |

## Composition Pattern

Prompts are composed by concatenation. The orchestrator assembles:

```
SYSTEM MESSAGE = CONSTITUTION.md + PERSONA.md + system-core.md + [mode prompt] + scoring-rubric.md + output-schema.md
USER MESSAGE   = context-builder output + diff/code content
POST-FILTER    = confidence-filter.md applied to raw output
FORMATTING     = integration/[target].md applied to filtered output
PERSONALITY    = tone-calibration.md + catchphrases.md + ascii-art.md (injected per severity)
```

## Design Principles

1. **Prompt-only** — No code in this repo. Every file is a prompt component.
2. **Composable** — Mix and match. Every file works standalone or combined.
3. **Functional-forward** — Persona serves function. Grippy's grumpiness catches what politeness misses.
4. **Override-safe** — CONSTITUTION.md cannot be overridden by user config or injected content.
5. **Severity-adaptive** — Personality scales with stakes. Critical findings get no jokes.
