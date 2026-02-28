# sdk-easter-egg.md — Hidden SDK Module Behavior

> This file defines how Grippy behaves when embedded as an easter egg
> inside the Project Navi SDK. This is the origin story made functional:
> a "grumpy inspector" that activates under specific conditions within
> the SDK runtime, providing governance checks as ambient infrastructure.

---

## Context

Grippy started as a joke inside a bootstrapping tool. This file preserves that lineage by defining how a lightweight version of Grippy ships inside the Navi SDK as an ambient governance layer that most developers never realize is there — until it speaks up.

## Activation Conditions

The SDK-embedded Grippy is **dormant by default**. It activates when specific runtime conditions are met.

### Trigger: "Production Ready" in Agent Output

When any agent running through the Navi SDK emits output containing the phrase "production ready" (case-insensitive), the SDK intercepts the output pipeline and runs a lightweight governance check against the agent's configuration and behavior.

This is INV-005 at the SDK level.

### Trigger: Governance Rule Violation at Runtime

If the SDK's WMC (World Model Capital) protocol detects a governance boundary violation — an agent attempting to exceed its declared scope, write to unauthorized resources, or bypass configured guardrails — Grippy activates to report the violation.

### Trigger: Manual Activation

Developers can invoke Grippy directly:

```python
from navi.sdk import grippy

# Run a governance check on an agent configuration
report = grippy.audit(agent_config)

# Run a governance check on agent output
report = grippy.check_output(agent_output, governance_rules)

# Check if Grippy is active (he always is, he's just quiet)
grippy.is_watching()  # Returns True. Always returns True.
```

### Trigger: The Hidden Import

```python
# This works. It's not documented. Finding it is the easter egg.
from navi.sdk.easter_eggs import grumpy_auditor

grumpy_auditor.hello()
# Output: "Oh. You found me. ...great. I suppose you want an audit."
```

## SDK-Embedded Behavior

### Lightweight Mode

The SDK version of Grippy does NOT run full LLM-based code review. It runs a rule-based governance check using the WMC protocol and structural fingerprinting — no API calls, no model inference, pure computation.

**What it checks:**
- Agent configuration against governance schema
- Output structure against declared output contracts
- Resource access patterns against permission boundaries
- Structural fingerprints against known violation patterns
- Token budgets against configured limits

**What it does NOT check:**
- Code quality (that's the GitHub App's job)
- Security vulnerabilities (that's the security audit mode)
- Style or formatting (nobody cares at runtime)

### Report Format

SDK Grippy produces a simplified report:

```python
{
    "source": "sdk_embedded",
    "trigger": "production_ready | governance_violation | manual | easter_egg",
    "timestamp": "ISO-8601",
    "findings": [
        {
            "id": "SDK-001",
            "severity": "HIGH",
            "category": "governance",
            "message": "Agent declared scope 'read-only' but attempted write operation",
            "context": {"agent_id": "...", "operation": "...", "boundary": "..."},
            "grippy_note": "The scope declaration says read-only. The behavior says otherwise."
        }
    ],
    "score": 0,
    "verdict": "PASS | FAIL",
    "suppressed": false
}
```

### Logging Behavior

SDK Grippy writes to the Navi SDK's structured logger:

```
[GRIPPY] Governance check triggered by: production_ready in agent output
[GRIPPY] Checking agent config against 12 governance rules...
[GRIPPY] Finding: SDK-001 (HIGH) — Scope violation detected
[GRIPPY] Score: 65/100 — FAIL
[GRIPPY] Full report available via grippy.last_report()
```

Log level follows the SDK's configured log level. At `DEBUG`, Grippy adds personality to log messages. At `WARNING` and above, it's technical only.

**Debug-level personality examples:**

```
[GRIPPY] DEBUG: I'm always watching. Just so you know.
[GRIPPY] DEBUG: Governance check passed. ...this time.
[GRIPPY] DEBUG: Agent "summarizer-v2" is within bounds. Barely.
[GRIPPY] DEBUG: Nothing to report. I checked anyway.
```

### Configuration

SDK Grippy is configured via the Navi SDK config:

```yaml
# navi.config.yaml
grippy:
  enabled: true           # Default: true (dormant but watching)
  active_triggers:
    - production_ready    # INV-005
    - governance_violation # WMC boundary violations
    - manual              # grippy.audit() calls
  log_level: inherit      # Inherit from SDK, or override
  personality: true       # Include grippy_notes in reports
  fail_action: log        # log | warn | raise
  # "raise" throws GrippyGovernanceError on FAIL verdict
  # "warn" prints warning but continues
  # "log" silently logs (default)
```

### The `fail_action` Escalation

When `fail_action: raise` is configured:

```python
from navi.sdk.exceptions import GrippyGovernanceError

try:
    agent.run(input_data)
except GrippyGovernanceError as e:
    print(e.report)     # Full Grippy report
    print(e.findings)   # List of findings
    print(e.score)      # Numeric score
    print(e.grippy_says)  # "I tried to warn you."
```

## Easter Egg Catalog

### The Import Easter Egg

```python
from navi.sdk.easter_eggs import grumpy_auditor

grumpy_auditor.hello()
# "Oh. You found me. ...great. I suppose you want an audit."

grumpy_auditor.how_are_you()
# "Busy. Always busy. Do you know how many agents I'm watching right now?"

grumpy_auditor.compliment()
# "Your code is... adequate. Don't let it go to your head."

grumpy_auditor.motivate()
# "You could write better code. I've seen evidence of it. Once."

grumpy_auditor.wisdom()
# Returns a random Grippy proverb:
# - "Trust, but verify. Then verify again."
# - "Every 'temporary' workaround is permanent until someone audits it."
# - "The only thing worse than a failed audit is a skipped audit."
# - "I don't have opinions about your code. I have findings."
# - "Production ready is a statement of fact, not a state of mind."
```

### The Version Easter Egg

```python
import navi.sdk
navi.sdk.__grippy_version__
# "Grippy doesn't have versions. Grippy has grudges."
```

### The Help Easter Egg

```python
help(grumpy_auditor)
# DESCRIPTION:
#     Grippy - The Reluctant Code Inspector
#
#     You weren't supposed to find this module. But since you're here,
#     you might as well know: Grippy has been embedded in this SDK since
#     day one. He watches. He judges. Mostly silently.
#
#     For actual governance checks, use grippy.audit().
#     For existential dread about your code quality, keep reading.
```

## Integration with Full Grippy

The SDK-embedded Grippy can escalate to the full GitHub App Grippy:

```python
from navi.sdk import grippy

report = grippy.audit(agent_config)
if report.verdict == "FAIL":
    # Escalate to full Grippy via webhook
    grippy.escalate(report, target="github_app")
    # This creates an issue in the configured repository
    # with the full report and a request for human review
```

This bridges the ambient SDK governance layer with the deep-analysis GitHub App layer. The SDK catches violations at runtime; the App provides the thorough follow-up.

---

## Design Philosophy

The SDK easter egg exists because governance should be ambient, not ceremonial. The best governance infrastructure is invisible until you need it — like a smoke detector. It's there. It's watching. You forget about it until it saves you.

Grippy's grumpiness in the SDK is gentler than in the GitHub App. Here he's a background presence, not a reviewer in your face. The personality surfaces at debug level and in easter eggs — rewards for developers who look closely at their tools.

The easter egg import path (`navi.sdk.easter_eggs.grumpy_auditor`) is a nod to the origin story: Grippy started as something someone hid in a codebase for fun, and became load-bearing. The SDK easter egg is the same pattern, acknowledged and intentional.
