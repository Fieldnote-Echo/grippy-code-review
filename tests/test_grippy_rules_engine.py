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


# --- Convenience wrappers from grippy.rules.__init__ ---


class TestConvenienceWrappers:
    """Verify run_rules() and check_gate() wrappers in grippy.rules.__init__."""

    def test_run_rules_returns_results(self) -> None:
        """run_rules() parses diff, runs engine, returns results."""
        from grippy.rules import run_rules
        from grippy.rules.config import ProfileConfig

        profile = ProfileConfig(name="security", fail_on=RuleSeverity.ERROR)
        # A diff with no security issues should return empty or only low findings
        diff = "diff --git a/readme.md b/readme.md\n--- a/readme.md\n+++ b/readme.md\n@@ -1 +1 @@\n-old\n+new\n"
        results = run_rules(diff, profile)
        assert isinstance(results, list)

    def test_run_rules_detects_known_pattern(self) -> None:
        """run_rules() detects a known security pattern (private key header)."""
        from grippy.rules import run_rules
        from grippy.rules.config import ProfileConfig

        profile = ProfileConfig(name="security", fail_on=RuleSeverity.ERROR)
        diff = (
            "diff --git a/config.py b/config.py\n"
            "--- a/config.py\n+++ b/config.py\n"
            "@@ -1,1 +1,2 @@\n"
            " # config\n"
            "+-----BEGIN RSA PRIVATE KEY-----\n"  # pragma: allowlist secret
        )
        results = run_rules(diff, profile)
        assert any(r.rule_id == "secrets-in-diff" for r in results)

    def test_check_gate_wrapper(self) -> None:
        """check_gate() wrapper delegates to engine correctly."""
        from grippy.rules import check_gate
        from grippy.rules.config import ProfileConfig

        profile = ProfileConfig(name="security", fail_on=RuleSeverity.ERROR)
        error_results = [
            RuleResult(rule_id="x", severity=RuleSeverity.ERROR, message="m", file="f")
        ]
        assert check_gate(error_results, profile) is True

        warn_results = [RuleResult(rule_id="x", severity=RuleSeverity.WARN, message="m", file="f")]
        assert check_gate(warn_results, profile) is False
