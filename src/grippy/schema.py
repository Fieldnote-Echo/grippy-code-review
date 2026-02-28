"""Pydantic models mapping Grippy's output-schema.md to typed Python objects."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, Field

# --- Enums ---


class Severity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ComplexityTier(StrEnum):
    TRIVIAL = "TRIVIAL"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"
    CRITICAL = "CRITICAL"


class FindingCategory(StrEnum):
    SECURITY = "security"
    LOGIC = "logic"
    GOVERNANCE = "governance"
    RELIABILITY = "reliability"
    OBSERVABILITY = "observability"


class EscalationCategory(StrEnum):
    SECURITY = "security"
    COMPLIANCE = "compliance"
    ARCHITECTURE = "architecture"
    PATTERN = "pattern"
    DOMAIN = "domain"


class EscalationTarget(StrEnum):
    SECURITY_TEAM = "security-team"
    INFRASTRUCTURE = "infrastructure"
    DOMAIN_EXPERT = "domain-expert"
    TECH_LEAD = "tech-lead"
    COMPLIANCE = "compliance"


class VerdictStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PROVISIONAL = "PROVISIONAL"


class ToneRegister(StrEnum):
    GRUDGING_RESPECT = "grudging_respect"
    MILD = "mild"
    GRUMPY = "grumpy"
    DISAPPOINTED = "disappointed"
    FRUSTRATED = "frustrated"
    ALARMED = "alarmed"
    PROFESSIONAL = "professional"


class AsciiArtKey(StrEnum):
    ALL_CLEAR = "all_clear"
    STANDARD = "standard"
    WARNING = "warning"
    CRITICAL = "critical"
    SURPRISE = "surprise"


# --- Nested models ---


class PRMetadata(BaseModel):
    title: str
    author: str
    branch: str = Field(description="source → target")
    complexity_tier: ComplexityTier


class ReviewScope(BaseModel):
    files_in_diff: int
    files_reviewed: int
    coverage_percentage: float
    governance_rules_applied: list[str]
    modes_active: list[str]


class Finding(BaseModel):
    model_config = {"frozen": True}

    id: str = Field(description="F-001 through F-999")
    severity: Severity
    confidence: int = Field(ge=0, le=100)
    category: FindingCategory
    file: str
    line_start: int
    line_end: int
    title: str
    description: str
    suggestion: str
    governance_rule_id: str | None = None
    evidence: str
    grippy_note: str = Field(max_length=280)

    @cached_property
    def fingerprint(self) -> str:
        """Deterministic 12-char hex hash for cross-round finding matching.

        Uses file + category — stable across line number shifts,
        severity re-ratings, title rephrasing, and description rewrites.
        """
        key = f"{self.file.strip()}:{self.category.value}"
        return hashlib.sha256(key.encode()).hexdigest()[:12]


class Escalation(BaseModel):
    id: str = Field(description="E-001 through E-099")
    severity: Literal["CRITICAL", "HIGH", "MEDIUM"]
    category: EscalationCategory
    summary: str
    details: str
    recommended_target: EscalationTarget
    blocking: bool


class ScoreBreakdown(BaseModel):
    security: int = Field(ge=0, le=100)
    logic: int = Field(ge=0, le=100)
    governance: int = Field(ge=0, le=100)
    reliability: int = Field(ge=0, le=100)
    observability: int = Field(ge=0, le=100)


class ScoreDeductions(BaseModel):
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    total_deduction: int


class Score(BaseModel):
    overall: int = Field(ge=0, le=100)
    breakdown: ScoreBreakdown
    deductions: ScoreDeductions


class Verdict(BaseModel):
    status: VerdictStatus
    threshold_applied: int
    merge_blocking: bool
    summary: str


class Personality(BaseModel):
    tone_register: ToneRegister
    opening_catchphrase: str
    closing_line: str
    disguise_used: str | None = None
    ascii_art_key: AsciiArtKey


class ReviewMeta(BaseModel):
    review_duration_ms: int
    tokens_used: int
    context_files_loaded: int
    confidence_filter_suppressed: int
    duplicate_filter_suppressed: int


# --- Top-level output ---


class GrippyReview(BaseModel):
    """Complete structured output from a Grippy review.

    Maps 1:1 to the JSON schema defined in output-schema.md.
    """

    version: str = "1.0"
    audit_type: Literal["pr_review", "security_audit", "governance_check", "surprise_audit"]
    timestamp: str = Field(description="ISO-8601")
    model: str

    pr: PRMetadata
    scope: ReviewScope
    findings: list[Finding]
    escalations: list[Escalation]
    score: Score
    verdict: Verdict
    personality: Personality
    meta: ReviewMeta
