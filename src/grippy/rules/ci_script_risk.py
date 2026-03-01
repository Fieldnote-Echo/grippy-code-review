# SPDX-License-Identifier: MIT
"""Rule 6: ci-script-execution-risk — curl|bash, sudo, chmod+x detection in CI files."""

from __future__ import annotations

import re

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.context import RuleContext

# Patterns for CI file matching
_CI_FILE_PATTERNS = (
    ".github/workflows/",
    "Dockerfile",
    "Makefile",
    "scripts/",
)
_SHELL_EXTENSIONS = frozenset({".sh", ".bash"})

# curl|bash or wget|bash — piping remote scripts
_PIPE_EXEC_RE = re.compile(r"\b(?:curl|wget)\b.*\|\s*(?:ba)?sh\b")

# sudo usage
_SUDO_RE = re.compile(r"\bsudo\b")

# chmod +x patterns
_CHMOD_X_RE = re.compile(r"\bchmod\s+\+x\b")


def _is_ci_file(path: str) -> bool:
    """Check if a file is a CI/infrastructure file."""
    for prefix in _CI_FILE_PATTERNS:
        if path.startswith(prefix):
            return True
    # Check basename patterns
    basename = path.rsplit("/", 1)[-1]
    if basename.startswith("Dockerfile") or basename == "Makefile":
        return True
    # Check shell extension
    dot = basename.rfind(".")
    if dot >= 0 and basename[dot:] in _SHELL_EXTENSIONS:
        return True
    return False


class CiScriptRiskRule:
    """Detect risky script execution patterns in CI/infrastructure files."""

    id = "ci-script-execution-risk"
    description = "Flag curl|bash, sudo, and chmod+x patterns in CI files"
    default_severity = RuleSeverity.WARN

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for f in ctx.files:
            if not _is_ci_file(f.path):
                continue
            for hunk in f.hunks:
                for line in hunk.lines:
                    if line.type != "add" or line.new_lineno is None:
                        continue
                    content = line.content

                    # curl|bash — CRITICAL
                    if _PIPE_EXEC_RE.search(content):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=RuleSeverity.CRITICAL,
                                message="Remote script piped to shell — supply chain risk",
                                file=f.path,
                                line=line.new_lineno,
                                evidence=content.strip(),
                            )
                        )
                        continue

                    # sudo — WARN
                    if _SUDO_RE.search(content):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=RuleSeverity.WARN,
                                message="sudo usage in CI context",
                                file=f.path,
                                line=line.new_lineno,
                                evidence=content.strip(),
                            )
                        )
                        continue

                    # chmod +x — WARN
                    if _CHMOD_X_RE.search(content):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=RuleSeverity.WARN,
                                message="chmod +x in CI context — verify target script",
                                file=f.path,
                                line=line.new_lineno,
                                evidence=content.strip(),
                            )
                        )

        return results
