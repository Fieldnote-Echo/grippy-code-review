# SPDX-License-Identifier: MIT
"""Rule 4: path-traversal-risk — flag tainted variable names in file operations."""

from __future__ import annotations

import re

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.context import RuleContext

# Variable names that indicate user-controlled input
TAINT_NAMES = frozenset(
    {
        "user",
        "request",
        "input",
        "filename",
        "url",
        "param",
        "query",
        "upload",
        "form",
        "body",
    }
)

# File operation patterns
_FILE_OPS_RE = re.compile(
    r"\b(?:open|Path|path\.join|os\.path\.join|read_file|write_file|send_file)\s*\("
)

# Traversal literals in string concatenation/join context
_TRAVERSAL_RE = re.compile(r"""(?:\.\./|\.\.\\)""")

# String literal argument — should not be flagged
_STRING_LITERAL_ONLY_RE = re.compile(
    r"""\b(?:open|Path|path\.join|os\.path\.join)\s*\(\s*["'][^"']*["']\s*[,)]"""
)

_EXTENSIONS = frozenset({".py", ".js", ".ts"})


def _file_ext(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:] if dot >= 0 else ""


def _has_taint_indicator(content: str) -> bool:
    """Check if any taint name appears as an identifier component in the arguments."""
    # Only check the arguments portion (after first open-paren)
    paren_idx = content.find("(")
    check_portion = content[paren_idx:] if paren_idx >= 0 else content
    # Split by non-alpha characters to get identifier parts
    parts = set(re.split(r"[^a-zA-Z]+", check_portion.lower()))
    return bool(TAINT_NAMES & parts)


def _has_traversal_pattern(content: str) -> bool:
    """Check for ../ or ..\\ in the content."""
    return bool(_TRAVERSAL_RE.search(content))


class PathTraversalRule:
    """Flag file operations with tainted variable names or traversal patterns."""

    id = "path-traversal-risk"
    description = "Flag file operations with user-controlled input indicators"
    default_severity = RuleSeverity.WARN

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for f in ctx.files:
            ext = _file_ext(f.path)
            if ext not in _EXTENSIONS:
                continue
            for hunk in f.hunks:
                for line in hunk.lines:
                    if line.type != "add" or line.new_lineno is None:
                        continue
                    content = line.content

                    # Skip pure string literal arguments
                    if _STRING_LITERAL_ONLY_RE.search(content):
                        continue

                    # Check for file operation with taint indicator
                    if _FILE_OPS_RE.search(content) and _has_taint_indicator(content):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=self.default_severity,
                                message="File operation with user-controlled input indicator",
                                file=f.path,
                                line=line.new_lineno,
                                evidence=content.strip(),
                            )
                        )
                        continue

                    # Check for traversal patterns in file operations
                    if _FILE_OPS_RE.search(content) and _has_traversal_pattern(content):
                        results.append(
                            RuleResult(
                                rule_id=self.id,
                                severity=self.default_severity,
                                message="Path traversal pattern in file operation",
                                file=f.path,
                                line=line.new_lineno,
                                evidence=content.strip(),
                            )
                        )

        return results
