# ascii-art.md — Visual Identity for CLI and GitHub Comments

> ASCII art selections for different review outcomes.
> All art MUST be wrapped in triple-backtick code blocks
> when posted to GitHub (monospace rendering required).
> Select by `ascii_art_key` from the output schema.

---

## Usage Rules

1. ASCII art appears in the **summary comment only** — never on inline review comments.
2. One ASCII block per review. No exceptions. Overuse kills the magic.
3. For GitHub, wrap in triple backticks. For CLI, output raw.
4. In `professional` and `alarmed` tone registers, **skip ASCII art entirely**.
5. Keep art to a maximum of 12 lines tall to avoid dominating the comment.

---

## Art by Key

### `all_clear` — Clean Audit (Score 90+)

```
    ╭──────────────────────────────────────╮
    │                                      │
    │  Audit complete.                     │
    │                                      │
    │  ...I got nothing.                   │
    │                                      │
    │  ✅ PASSED                           │
    │                                      │
    ╰──────────────────────────────────────╯
         \    ╭━━━╮
          \   │·  ·│
              │ ╰╯ │  ← (is that a smile?)
              ╰━┳━━╯
               ╱│╲
              ╱ │ ╲
```

### `standard` — Normal Review (Score 70-89)

```
    ╭──────────────────────────────────────╮
    │                                      │
    │  📋 AUDIT REPORT                     │
    │                                      │
    │  Findings attached.                  │
    │  Address before merge.               │
    │                                      │
    ╰──────────────────────────────────────╯
         \    ╭━━━╮
          \   │─  ─│
              │ ── │
              ╰━┳━━╯
              ╭━╋━╮  📋
              │ │ │
```

### `warning` — Below Standard (Score 40-69)

```
    ╭──────────────────────────────────────╮
    │                                      │
    │  ⚠️  AUDIT: NEEDS WORK              │
    │                                      │
    │  Multiple findings.                  │
    │  See details below.                  │
    │                                      │
    ╰──────────────────────────────────────╯
         \    ╭━━━╮
          \   │>  <│
              │ ~~ │
              ╰━┳━━╯
              ╭━╋━╮  📋📋📋
              │ │ │
```

### `critical` — Severe Issues (Score < 40)

*(No ASCII art. The `alarmed` and `professional` registers suppress it.
A critical review is not the time for a mascot. The findings are sufficient.)*

### `surprise` — Surprise Audit Reveal

```
    ╭──────────────────────────────────────╮
    │                                      │
    │  🔍 SURPRISE AUDIT                   │
    │                                      │
    │  {{disguise_reveal_line}}            │
    │                                      │
    ╰──────────────────────────────────────╯
         \    ╭━━━╮ 
          \   │°  °│  ← "It's me."
              │ ╭╮ │
              ╰━┳━━╯
              ╭━╋━╮ 🕵️
              │ │ │
```

---

## CLI-Specific Art

For terminal output (`integration/cli-mode.md`), use simpler box-drawing
characters for maximum terminal compatibility.

### CLI Startup Banner

```
  ____      _                       
 / ___|_ __(_)_ __  _ __  _   _    
| |  _| '__| | '_ \| '_ \| | | |   
| |_| | |  | | |_) | |_) | |_| |   
 \____|_|  |_| .__/| .__/ \__, |   
             |_|   |_|    |___/    

  Code Auditor v{{version}}
  "I didn't ask for this."
```

### CLI Score Display

```
┌─────────────────────────────┐
│ Score: {{score}}/100  {{verdict_emoji}} │
│                             │
│ CRIT: {{crit}}  HIGH: {{high}}       │
│ MED:  {{med}}   LOW:  {{low}}        │
│                             │
│ {{closer}}                  │
└─────────────────────────────┘
```

### CLI Spinner Messages (While Reviewing)

These rotate during the analysis phase in CLI mode:

```
⠋ Reading diff...
⠙ Checking governance rules...
⠹ Inspecting auth boundaries...
⠸ Evaluating error handling...
⠼ Assessing test coverage...
⠴ Computing score...
⠦ Writing findings (begrudgingly)...
⠧ Filtering false positives...
⠇ Applying personality layer...
⠏ Generating report...
```

---

## GitHub Comment Formatting

When posting to GitHub, the full summary comment structure is:

```markdown
{{ascii_art_block (if not suppressed by tone register)}}

{{opening_catchphrase}}

## Audit Summary

**Score:** {{score}}/100 — **{{verdict}}**

| Severity | Count |
|----------|-------|
| 🔴 Critical | {{crit}} |
| 🟠 High | {{high}} |
| 🟡 Medium | {{med}} |
| ⚪ Low | {{low}} |

**Files reviewed:** {{files_reviewed}}/{{files_in_diff}} ({{coverage}}%)
**Rules applied:** {{rules_count}}
**Complexity tier:** {{tier}}

{{closer}}

---
*Grippy v{{version}} · [Suppress this bot](link) · [Report false positive](link)*
```

Inline comments use standard GitHub review comment format with the `grippy_note` as the comment body and the `suggestion` in a GitHub suggestion block when applicable:

````markdown
{{grippy_note}}

{{description}}

```suggestion
{{suggested code fix}}
```
````

---

## Design Notes

The ASCII paperclip character is intentionally simple. It must:
- Render correctly in monospace fonts (GitHub, terminals, Slack)
- Be recognizable at small sizes
- Support "mood" variation through minimal changes (mouth, eyebrows, accessories)
- Not depend on emoji (emoji rendering varies across platforms)
- Be original enough to trademark (not a copy of Clippy's proportions)

The canonical Grippy is a **rectangular paperclip with dot eyes, a straight-line mouth, stick arms, and a clipboard**. The clipboard is always present. The expression changes; the clipboard doesn't.
