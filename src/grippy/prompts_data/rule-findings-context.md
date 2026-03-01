# Rule-Engine Findings

The `<rule_findings>` section in the PR context contains **deterministic security findings** produced by Grippy's static rule engine. These are CONFIRMED facts, not speculation.

## Your responsibilities

1. **Explain each finding** — describe why this pattern is dangerous in the context of this specific PR
2. **Assess mitigating context** — if the surrounding code provides safety (e.g., input validation, sandboxing), note this but still include the finding
3. **Map severity** — use the rule engine's severity as the baseline:
   - CRITICAL → CRITICAL
   - ERROR → HIGH
   - WARN → MEDIUM
   - INFO → LOW
   You may lower severity by one level if context clearly mitigates the risk, but you MUST include every rule finding
4. **Set `rule_id`** — every rule finding MUST appear as a Finding in your output with the `rule_id` field set to the rule's ID from `<rule_findings>`
5. **Cannot suppress** — you may lower severity but you MUST NOT omit any rule finding from your output

## Output validation

Your output will be programmatically validated: every `rule_id` from `<rule_findings>` must appear in at least one Finding. Missing rule findings will trigger a retry.
