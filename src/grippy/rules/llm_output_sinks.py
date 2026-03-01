# SPDX-License-Identifier: MIT
"""Rule 5: llm-output-unsanitized — detect LLM output piped to sinks without sanitization."""

from __future__ import annotations

import re

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.context import DiffHunk, RuleContext

# Central sanitizer registry — single source of truth
SANITIZERS = frozenset(
    {
        "sanitize",
        "escape",
        "html.escape",
        "markupsafe.escape",
        "clean",
        "sanitize_comment",
        "_sanitize_comment_text",
        "_escape_xml",
        "bleach.clean",
    }
)

# LLM/model output tokens
_MODEL_OUTPUT_RE = re.compile(
    r"\b(?:\.run\(|\.chat\(|\.content\b|\.choices\b|\.generate\(|completion\b)"
)

# Output sinks where unsanitized model output is dangerous
_SINK_RE = re.compile(
    r"\b(?:create_comment\(|create_issue_comment\(|\.body\s*=|post\(|render\(|f\"<)"
)

_SANITIZER_RE = re.compile("|".join(re.escape(s) for s in SANITIZERS))


class LlmOutputSinksRule:
    """Detect LLM output piped directly to sinks without sanitization."""

    id = "llm-output-unsanitized"
    description = "Flag model output used in sinks without sanitizer in between"
    default_severity = RuleSeverity.ERROR

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for f in ctx.files:
            if not f.path.endswith(".py"):
                continue
            for hunk in f.hunks:
                results.extend(self._scan_hunk(f.path, hunk))
        return results

    def _scan_hunk(self, path: str, hunk: DiffHunk) -> list[RuleResult]:
        """Scan a single hunk for model output → sink without sanitizer."""
        results: list[RuleResult] = []

        # Collect added lines in order
        added_lines: list[tuple[int, str]] = []
        for line in hunk.lines:
            if line.type == "add" and line.new_lineno is not None:
                added_lines.append((line.new_lineno, line.content))

        # Look for model output tokens, then scan forward for sinks
        for i, (_lineno, content) in enumerate(added_lines):
            if not _MODEL_OUTPUT_RE.search(content):
                continue

            # Scan forward in same hunk for sinks
            for j in range(i, len(added_lines)):
                sink_lineno, sink_content = added_lines[j]
                if _SINK_RE.search(sink_content):
                    # Check if any sanitizer appears between model output and sink
                    between = " ".join(c for _, c in added_lines[i : j + 1])
                    if not _SANITIZER_RE.search(between):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=self.default_severity,
                                message="LLM output used in sink without sanitization",
                                file=path,
                                line=sink_lineno,
                                evidence=sink_content.strip(),
                            )
                        )
                        break  # One finding per model-output → sink chain

        return results
