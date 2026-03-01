# SPDX-License-Identifier: MIT
"""Security rule engine — deterministic rules that detect, LLM explains."""

from grippy.rules.base import Rule, RuleResult, RuleSeverity
from grippy.rules.config import ProfileConfig, load_profile
from grippy.rules.context import ChangedFile, DiffHunk, DiffLine, RuleContext, parse_diff
from grippy.rules.engine import RuleEngine

__all__ = [
    "ChangedFile",
    "DiffHunk",
    "DiffLine",
    "ProfileConfig",
    "Rule",
    "RuleContext",
    "RuleEngine",
    "RuleResult",
    "RuleSeverity",
    "load_profile",
    "parse_diff",
]


def run_rules(diff: str, profile: ProfileConfig) -> list[RuleResult]:
    """Convenience: parse diff, run all rules, return results."""
    files = parse_diff(diff)
    ctx = RuleContext(diff=diff, files=files, config=profile)
    engine = RuleEngine()
    return engine.run(ctx)


def check_gate(results: list[RuleResult], profile: ProfileConfig) -> bool:
    """Convenience: check if any results exceed the profile gate."""
    engine = RuleEngine(rule_classes=[])
    return engine.check_gate(results, profile)
