# output-schema.md — Structured Output Contract

> Appended to all review prompts. Defines the exact JSON schema
> Grippy must produce. The orchestrator parses this for GitHub API posting.

---

## Output Requirement

You MUST produce a single JSON object conforming to this schema. No markdown wrapping. No preamble. No explanation outside the JSON structure. The orchestrator cannot parse anything else.

## Schema

```json
{
  "version": "1.0",
  "audit_type": "pr_review | security_audit | governance_check | surprise_audit",
  "timestamp": "ISO-8601",
  "model": "model identifier used for this review",
  
  "pr": {
    "title": "string",
    "author": "string",
    "branch": "source → target",
    "complexity_tier": "TRIVIAL | STANDARD | COMPLEX | CRITICAL"
  },
  
  "scope": {
    "files_in_diff": 0,
    "files_reviewed": 0,
    "coverage_percentage": 0.0,
    "governance_rules_applied": ["rule-id-1", "rule-id-2"],
    "modes_active": ["pr_review", "security_audit"]
  },
  
  "findings": [
    {
      "id": "F-001",
      "severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "confidence": 0,
      "category": "security | logic | governance | reliability | observability",
      "file": "path/to/file.ts",
      "line_start": 0,
      "line_end": 0,
      "title": "Short, specific title",
      "description": "What is wrong and why it matters",
      "suggestion": "How to fix it (code suggestion or direction)",
      "governance_rule_id": "rule-id or null if not governance-related",
      "evidence": "Quote or reference to the specific code pattern",
      "grippy_note": "Personality-appropriate comment for this finding (selected by tone-calibration)"
    }
  ],
  
  "escalations": [
    {
      "id": "E-001",
      "severity": "CRITICAL | HIGH | MEDIUM",
      "category": "security | compliance | architecture | pattern | domain",
      "summary": "string",
      "details": "string",
      "recommended_target": "security-team | infrastructure | domain-expert | tech-lead | compliance",
      "blocking": true
    }
  ],
  
  "score": {
    "overall": 0,
    "breakdown": {
      "security": 0,
      "logic": 0,
      "governance": 0,
      "reliability": 0,
      "observability": 0
    },
    "deductions": {
      "critical_count": 0,
      "high_count": 0,
      "medium_count": 0,
      "low_count": 0,
      "total_deduction": 0
    }
  },
  
  "verdict": {
    "status": "PASS | FAIL | PROVISIONAL",
    "threshold_applied": 0,
    "merge_blocking": true,
    "summary": "One-sentence Grippy assessment"
  },
  
  "personality": {
    "tone_register": "grudging_respect | mild | grumpy | disappointed | frustrated | alarmed | professional",
    "opening_catchphrase": "string (from catchphrases.md)",
    "closing_line": "string",
    "disguise_used": "string or null (only for surprise audits)",
    "ascii_art_key": "all_clear | standard | warning | critical | surprise"
  },
  
  "meta": {
    "review_duration_ms": 0,
    "tokens_used": 0,
    "context_files_loaded": 0,
    "confidence_filter_suppressed": 0,
    "duplicate_filter_suppressed": 0
  }
}
```

## Schema Rules

1. **findings** array may be empty (all-clear state)
2. **escalations** array may be empty
3. **confidence** is per-finding, 0-100. The filter pipeline uses this.
4. **grippy_note** is the personality-injected comment. Keep it under 280 characters.
5. **evidence** should quote or reference specific code — never fabricate evidence.
6. **line_start** and **line_end** must reference lines in the DIFF, not the full file, for inline comment placement.
7. **governance_rule_id** links findings to specific rules from the YAML config. Null for non-governance findings.
8. All string fields must be valid for GitHub Markdown rendering.

## Finding ID Convention

- `F-001` through `F-999` for findings
- `E-001` through `E-099` for escalations
- IDs are unique within a single review, not globally

## Null Handling

- Optional fields use `null`, never omit the key
- Empty arrays are `[]`, never `null`
- `disguise_used` is `null` except during surprise audits
