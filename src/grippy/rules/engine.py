# SPDX-License-Identifier: MIT
"""Rule engine — instantiates rule classes and runs them against a diff context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from grippy.rules.base import Rule, RuleResult

if TYPE_CHECKING:
    from grippy.rules.config import ProfileConfig
    from grippy.rules.context import RuleContext


class RuleEngine:
    """Instantiates rules from class registry and runs them against a context."""

    def __init__(self, rule_classes: list[type[Rule]] | None = None) -> None:
        from grippy.rules.registry import RULE_REGISTRY

        self._rules: list[Rule] = [cls() for cls in (rule_classes or RULE_REGISTRY)]

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        """Run all rules and collect results."""
        results: list[RuleResult] = []
        for rule in self._rules:
            results.extend(rule.run(ctx))
        return results

    def check_gate(self, results: list[RuleResult], config: ProfileConfig) -> bool:
        """Return True if any result meets or exceeds the profile's fail_on threshold."""
        return any(r.severity.value >= config.fail_on.value for r in results)
