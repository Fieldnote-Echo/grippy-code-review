# SPDX-License-Identifier: MIT
"""Rule severity, result dataclass, and Rule protocol for the security rule engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from grippy.rules.context import RuleContext


class RuleSeverity(IntEnum):
    """Severity levels for rule findings, ordered for gate comparison."""

    INFO = 0
    WARN = 1
    ERROR = 2
    CRITICAL = 3


@dataclass(frozen=True)
class RuleResult:
    """A single finding produced by a deterministic rule."""

    rule_id: str
    severity: RuleSeverity
    message: str
    file: str
    line: int | None = None
    evidence: str | None = None


@runtime_checkable
class Rule(Protocol):
    """Protocol that every security rule must satisfy."""

    id: str
    description: str
    default_severity: RuleSeverity

    def run(self, ctx: RuleContext) -> list[RuleResult]: ...
