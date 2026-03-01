# SPDX-License-Identifier: MIT
"""Rule 2: secrets-in-diff — detect known secret formats, private keys, and .env files."""

from __future__ import annotations

import re

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.context import RuleContext

# Known API key / secret patterns
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], RuleSeverity]] = [
    # Private keys
    ("Private key header", re.compile(r"-----BEGIN.*PRIVATE KEY-----"), RuleSeverity.CRITICAL),
    # AWS access key
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}"), RuleSeverity.CRITICAL),
    # GitHub classic PAT
    ("GitHub classic PAT", re.compile(r"ghp_[a-zA-Z0-9]{36}"), RuleSeverity.CRITICAL),
    # GitHub fine-grained PAT
    ("GitHub fine-grained PAT", re.compile(r"github_pat_[a-zA-Z0-9]{22,}"), RuleSeverity.CRITICAL),
    # GitHub other tokens
    ("GitHub OAuth token", re.compile(r"gho_[a-zA-Z0-9]{36}"), RuleSeverity.CRITICAL),
    ("GitHub user token", re.compile(r"ghu_[a-zA-Z0-9]{36}"), RuleSeverity.CRITICAL),
    ("GitHub server token", re.compile(r"ghs_[a-zA-Z0-9]{36}"), RuleSeverity.CRITICAL),
    ("GitHub refresh token", re.compile(r"ghr_[a-zA-Z0-9]{36}"), RuleSeverity.CRITICAL),
    # OpenAI
    ("OpenAI API key", re.compile(r"sk-[a-zA-Z0-9]{20,}"), RuleSeverity.CRITICAL),
    # Generic long token assignment
    (
        "Generic secret assignment",
        re.compile(
            r"""(?:token|secret|password|api_key)\s*[:=]\s*["']?[^\s"']{12,}""",
            re.IGNORECASE,
        ),
        RuleSeverity.CRITICAL,
    ),
]

# Known placeholder values that should not trigger findings
_PLACEHOLDERS = frozenset(
    {
        "changeme",
        "xxxx",
        "example",
        "placeholder",
        "your-",
        "your_",
        "test",
        "dummy",
        "fake",
        "mock",
        "sample",
        "todo",
        "fixme",
        "replace",
    }
)


def _is_comment_line(content: str) -> bool:
    """Check if a line is a comment in common languages."""
    stripped = content.strip()
    return stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*")


def _is_placeholder(match_text: str) -> bool:
    """Check if matched text contains a known placeholder value."""
    lower = match_text.lower()
    return any(p in lower for p in _PLACEHOLDERS)


def _in_tests_dir(path: str) -> bool:
    """Check if file is in a tests/ directory."""
    return path.startswith("tests/") or "/tests/" in path


class SecretsInDiffRule:
    """Detect known secret formats, private keys, and .env file additions."""

    id = "secrets-in-diff"
    description = "Scan for known API key formats, private keys, and .env additions"
    default_severity = RuleSeverity.CRITICAL

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for f in ctx.files:
            # Skip test directories
            if _in_tests_dir(f.path):
                continue

            # Check for .env file additions
            if f.path.endswith(".env") or "/.env" in f.path:
                for hunk in f.hunks:
                    for line in hunk.lines:
                        if line.type == "add" and line.new_lineno is not None:
                            results.append(
                                RuleResult(
                                    rule_id=self.id,
                                    severity=RuleSeverity.WARN,
                                    message=".env file added to diff — may contain secrets",
                                    file=f.path,
                                    line=line.new_lineno,
                                    evidence=f.path,
                                )
                            )
                            break  # One finding per .env file is enough
                    break  # Only need one hunk

            # Scan added lines for secret patterns
            for hunk in f.hunks:
                for line in hunk.lines:
                    if line.type != "add" or line.new_lineno is None:
                        continue
                    if _is_comment_line(line.content):
                        continue
                    for name, pattern, severity in _SECRET_PATTERNS:
                        match = pattern.search(line.content)
                        if match and not _is_placeholder(match.group(0)):
                            results.append(
                                RuleResult(
                                    rule_id=self.id,
                                    severity=severity,
                                    message=f"{name} detected in diff",
                                    file=f.path,
                                    line=line.new_lineno,
                                    evidence=self._redact(match.group(0)),
                                )
                            )
                            break  # One finding per line is enough

        return results

    @staticmethod
    def _redact(value: str) -> str:
        """Redact a secret value, showing only prefix."""
        if len(value) <= 8:
            return value[:4] + "..."
        return value[:8] + "..."
