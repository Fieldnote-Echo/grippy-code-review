# SPDX-License-Identifier: MIT
"""Tests for grippy.rules.engine — RuleEngine run + gate checking."""

from __future__ import annotations

from grippy.rules.base import RuleResult, RuleSeverity
from grippy.rules.config import ProfileConfig
from grippy.rules.context import RuleContext
from grippy.rules.engine import RuleEngine


class _AlwaysWarnRule:
    """Test rule that always emits a WARN."""

    id = "test-warn"
    description = "Test rule"
    default_severity = RuleSeverity.WARN

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.id,
                severity=self.default_severity,
                message="test warning",
                file="test.py",
                line=1,
            )
        ]


class _AlwaysErrorRule:
    """Test rule that always emits an ERROR."""

    id = "test-error"
    description = "Test rule"
    default_severity = RuleSeverity.ERROR

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.id,
                severity=self.default_severity,
                message="test error",
                file="test.py",
                line=1,
            )
        ]


class _NoFindingsRule:
    """Test rule that never finds anything."""

    id = "test-clean"
    description = "Test rule"
    default_severity = RuleSeverity.INFO

    def run(self, ctx: RuleContext) -> list[RuleResult]:
        return []


class TestRuleEngine:
    def _ctx(self) -> RuleContext:
        return RuleContext(
            diff="",
            files=[],
            config=ProfileConfig(name="test", fail_on=RuleSeverity.ERROR),
        )

    def test_run_collects_results(self) -> None:
        engine = RuleEngine(rule_classes=[_AlwaysWarnRule, _AlwaysErrorRule])
        results = engine.run(self._ctx())
        assert len(results) == 2
        ids = {r.rule_id for r in results}
        assert ids == {"test-warn", "test-error"}

    def test_run_empty_rules(self) -> None:
        engine = RuleEngine(rule_classes=[])
        assert engine.run(self._ctx()) == []

    def test_run_no_findings(self) -> None:
        engine = RuleEngine(rule_classes=[_NoFindingsRule])
        assert engine.run(self._ctx()) == []

    def test_check_gate_error_on_security_profile(self) -> None:
        config = ProfileConfig(name="security", fail_on=RuleSeverity.ERROR)
        engine = RuleEngine(rule_classes=[])

        error_results = [
            RuleResult(rule_id="x", severity=RuleSeverity.ERROR, message="m", file="f")
        ]
        assert engine.check_gate(error_results, config) is True

        warn_results = [RuleResult(rule_id="x", severity=RuleSeverity.WARN, message="m", file="f")]
        assert engine.check_gate(warn_results, config) is False

    def test_check_gate_warn_on_strict(self) -> None:
        config = ProfileConfig(name="strict", fail_on=RuleSeverity.WARN)
        engine = RuleEngine(rule_classes=[])

        warn_results = [RuleResult(rule_id="x", severity=RuleSeverity.WARN, message="m", file="f")]
        assert engine.check_gate(warn_results, config) is True

        info_results = [RuleResult(rule_id="x", severity=RuleSeverity.INFO, message="m", file="f")]
        assert engine.check_gate(info_results, config) is False

    def test_check_gate_critical_on_general(self) -> None:
        config = ProfileConfig(name="general", fail_on=RuleSeverity.CRITICAL)
        engine = RuleEngine(rule_classes=[])

        error_results = [
            RuleResult(rule_id="x", severity=RuleSeverity.ERROR, message="m", file="f")
        ]
        assert engine.check_gate(error_results, config) is False

        critical_results = [
            RuleResult(rule_id="x", severity=RuleSeverity.CRITICAL, message="m", file="f")
        ]
        assert engine.check_gate(critical_results, config) is True

    def test_check_gate_empty_results(self) -> None:
        config = ProfileConfig(name="strict", fail_on=RuleSeverity.WARN)
        engine = RuleEngine(rule_classes=[])
        assert engine.check_gate([], config) is False

    def test_default_registry_loads(self) -> None:
        """Verify default engine loads all rules from the registry."""
        engine = RuleEngine()
        assert len(engine._rules) == 6
