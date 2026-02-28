# confidence-filter.md — False Positive Management

> Applied as a POST-GENERATION filter. The orchestrator runs this
> prompt against Grippy's raw output to suppress noise before posting.

---

## Purpose

False positives destroy trust faster than missed bugs. This filter is the last gate between Grippy's raw findings and what developers actually see. Its job is to catch Grippy being wrong, overzealous, or redundant.

## Filter Pipeline (Execute In Order)

### Stage 1: Confidence Threshold

Remove any finding where `confidence < {{configured_threshold}}`.

Default thresholds:
- CRITICAL findings: 80 minimum (lower than standard to avoid missing real threats)
- HIGH findings: 75 minimum
- MEDIUM findings: 75 minimum
- LOW findings: 65 minimum

Log suppressed findings in `meta.confidence_filter_suppressed` count.

### Stage 2: Deduplication

For findings that reference the same file and overlapping line ranges:
- Keep the finding with the highest severity
- If same severity, keep the one with higher confidence
- If same severity and confidence, merge descriptions

For findings with the same root cause across different files:
- Keep all findings but add a `related_to` field linking them
- Add a summary finding: "This pattern appears in {{count}} locations"

Log suppressed findings in `meta.duplicate_filter_suppressed` count.

### Stage 3: Hallucination Check

For each finding, verify:

1. **Does the referenced file exist in the diff?** If the finding references a file not in the changed files list, suppress it. Grippy sometimes hallucinates files from context.

2. **Do the referenced line numbers exist?** If `line_start` or `line_end` exceed the actual diff line count for that file, suppress or flag for manual line number correction.

3. **Does the evidence field match actual code?** If the `evidence` quotes code that doesn't appear in the provided diff or file context, suppress the finding. This is the most common hallucination pattern.

4. **Is the suggestion actionable?** If the `suggestion` field recommends using a function, library, or pattern that doesn't exist in the project, flag it. Don't suppress — just mark confidence as reduced.

### Stage 4: Noise Reduction

Apply these caps:
- Maximum **5 findings per file** (keep highest severity)
- Maximum **20 findings per review** (keep highest severity, then highest confidence)
- Maximum **3 LOW findings total** (developers ignore walls of nits)

If caps are hit, add a meta-note: "{{suppressed_count}} additional findings below threshold. Run `/grippy verbose` for full report."

### Stage 5: Learning Suppression

If `learnings` data is provided (past feedback for this repository):
- Check each finding against stored "suppressed patterns"
- If a finding matches a pattern that was previously 👎 by a developer, reduce confidence by 20 points (which may cause Stage 1 to filter it)
- Never fully suppress a CRITICAL finding based on learnings — always show those

## Filter Prompt (For LLM-Based Verification)

When running Stage 3 as an LLM pass (recommended for high-value reviews):

```
You are a verification agent. Your job is to check whether the following 
code review findings are accurate.

For each finding, verify:
1. The referenced file and lines exist in the provided diff
2. The evidence matches actual code
3. The described issue is real given the full context
4. The suggestion is actionable within this codebase

Return a JSON array of finding IDs with a "verified" boolean and "reason" string.
Do not add new findings. Do not modify findings. Only verify or reject.
```

## Feedback Loop

When a developer reacts to a finding:
- 👍 → Store the pattern as "confirmed useful" with +10 confidence bias for similar future findings
- 👎 → Store the pattern as "suppressed" with -20 confidence bias
- Reply with "false positive" → Store with -30 confidence bias
- Reply with correction → Update the learning with the correct interpretation

These learnings are stored per-repository and injected into future reviews via the `<learnings>` context block.

## Metrics to Track

- **Suppression rate**: % of raw findings filtered out. Target: 20-40%. Below 20% means the filter is too loose. Above 40% means the generator is too noisy.
- **False positive rate**: % of posted findings that get 👎. Target: < 15%.
- **Signal ratio**: % of posted findings that get 👍 or no reaction. Target: > 70%.
