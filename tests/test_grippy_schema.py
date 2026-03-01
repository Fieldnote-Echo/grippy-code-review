# SPDX-License-Identifier: MIT
"""Tests for Grippy Pydantic schema models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from grippy.schema import (
    AsciiArtKey,
    ComplexityTier,
    EscalationCategory,
    EscalationTarget,
    Finding,
    FindingCategory,
    GrippyReview,
    Personality,
    Severity,
    ToneRegister,
    VerdictStatus,
)

# --- Helpers ---


def _minimal_finding(**overrides: object) -> dict:
    """Return a minimal valid Finding dict, with overrides applied."""
    base: dict = {
        "id": "F-001",
        "severity": "CRITICAL",
        "confidence": 85,
        "category": "security",
        "file": "src/main.py",
        "line_start": 10,
        "line_end": 15,
        "title": "SQL injection risk",
        "description": "User input is interpolated directly into query.",
        "suggestion": "Use parameterized queries.",
        "evidence": 'line 12: f"SELECT * FROM {user_input}"',
        "grippy_note": "Grippy is not amused.",
    }
    base.update(overrides)
    return base


def _minimal_review(**overrides: object) -> dict:
    """Return a minimal valid GrippyReview dict."""
    base: dict = {
        "audit_type": "pr_review",
        "timestamp": "2026-02-25T12:00:00Z",
        "model": "devstral-small-2-24b-instruct-2512",
        "pr": {
            "title": "feat: add login endpoint",
            "author": "nelson",
            "branch": "feat/login -> main",
            "complexity_tier": "STANDARD",
        },
        "scope": {
            "files_in_diff": 3,
            "files_reviewed": 3,
            "coverage_percentage": 100.0,
            "governance_rules_applied": ["SEC-001"],
            "modes_active": ["pr_review"],
        },
        "findings": [_minimal_finding()],
        "escalations": [],
        "score": {
            "overall": 72,
            "breakdown": {
                "security": 15,
                "logic": 20,
                "governance": 17,
                "reliability": 10,
                "observability": 10,
            },
            "deductions": {
                "critical_count": 1,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "total_deduction": 28,
            },
        },
        "verdict": {
            "status": "FAIL",
            "threshold_applied": 80,
            "merge_blocking": True,
            "summary": "Critical SQL injection finding blocks merge.",
        },
        "personality": {
            "tone_register": "alarmed",
            "opening_catchphrase": "Oh no, not again...",
            "closing_line": "Fix this before I lose what's left of my patience.",
            "ascii_art_key": "critical",
        },
        "meta": {
            "review_duration_ms": 4200,
            "tokens_used": 3100,
            "context_files_loaded": 2,
            "confidence_filter_suppressed": 0,
            "duplicate_filter_suppressed": 0,
        },
    }
    base.update(overrides)
    return base


# --- Enum tests ---


class TestEnumValues:
    """Spot-check enum values to confirm StrEnum mapping."""

    def test_severity_critical(self) -> None:
        assert Severity.CRITICAL.value == "CRITICAL"

    def test_severity_low(self) -> None:
        assert Severity.LOW.value == "LOW"

    def test_tone_grudging_respect(self) -> None:
        assert ToneRegister.GRUDGING_RESPECT.value == "grudging_respect"

    def test_tone_professional(self) -> None:
        assert ToneRegister.PROFESSIONAL.value == "professional"

    def test_complexity_trivial(self) -> None:
        assert ComplexityTier.TRIVIAL.value == "TRIVIAL"

    def test_finding_category_security(self) -> None:
        assert FindingCategory.SECURITY.value == "security"

    def test_escalation_category_compliance(self) -> None:
        assert EscalationCategory.COMPLIANCE.value == "compliance"

    def test_escalation_target_tech_lead(self) -> None:
        assert EscalationTarget.TECH_LEAD.value == "tech-lead"

    def test_verdict_pass(self) -> None:
        assert VerdictStatus.PASS.value == "PASS"

    def test_verdict_provisional(self) -> None:
        assert VerdictStatus.PROVISIONAL.value == "PROVISIONAL"

    def test_ascii_art_all_clear(self) -> None:
        assert AsciiArtKey.ALL_CLEAR.value == "all_clear"


# --- Finding constraint tests ---


class TestFindingConstraints:
    """Verify Field constraints on the Finding model."""

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            Finding(**_minimal_finding(confidence=-1))

    def test_confidence_above_100_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            Finding(**_minimal_finding(confidence=101))

    def test_confidence_at_boundaries_accepted(self) -> None:
        f0 = Finding(**_minimal_finding(confidence=0))
        f100 = Finding(**_minimal_finding(confidence=100))
        assert f0.confidence == 0
        assert f100.confidence == 100

    def test_grippy_note_max_length_rejected(self) -> None:
        long_note = "x" * 281
        with pytest.raises(ValidationError, match="grippy_note"):
            Finding(**_minimal_finding(grippy_note=long_note))

    def test_grippy_note_at_max_length_accepted(self) -> None:
        note_280 = "x" * 280
        f = Finding(**_minimal_finding(grippy_note=note_280))
        assert len(f.grippy_note) == 280

    def test_title_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError, match="title"):
            Finding(**_minimal_finding(title="x" * 281))

    def test_title_at_max_length_accepted(self) -> None:
        f = Finding(**_minimal_finding(title="x" * 280))
        assert len(f.title) == 280

    def test_description_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError, match="description"):
            Finding(**_minimal_finding(description="x" * 2001))

    def test_description_at_max_length_accepted(self) -> None:
        f = Finding(**_minimal_finding(description="x" * 2000))
        assert len(f.description) == 2000

    def test_suggestion_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError, match="suggestion"):
            Finding(**_minimal_finding(suggestion="x" * 1001))

    def test_suggestion_at_max_length_accepted(self) -> None:
        f = Finding(**_minimal_finding(suggestion="x" * 1000))
        assert len(f.suggestion) == 1000

    def test_evidence_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            Finding(**_minimal_finding(evidence="x" * 1001))

    def test_evidence_at_max_length_accepted(self) -> None:
        f = Finding(**_minimal_finding(evidence="x" * 1000))
        assert len(f.evidence) == 1000


# --- Optional field tests ---


class TestOptionalFields:
    """Verify optional/nullable fields accept None."""

    def test_finding_governance_rule_id_none(self) -> None:
        f = Finding(**_minimal_finding(governance_rule_id=None))
        assert f.governance_rule_id is None

    def test_finding_governance_rule_id_present(self) -> None:
        f = Finding(**_minimal_finding(governance_rule_id="SEC-001"))
        assert f.governance_rule_id == "SEC-001"

    def test_personality_disguise_used_none(self) -> None:
        p = Personality(
            tone_register="grumpy",
            opening_catchphrase="Ugh.",
            closing_line="Don't let me catch you again.",
            disguise_used=None,
            ascii_art_key="standard",
        )
        assert p.disguise_used is None

    def test_personality_disguise_used_present(self) -> None:
        p = Personality(
            tone_register="grumpy",
            opening_catchphrase="Ugh.",
            closing_line="Don't let me catch you again.",
            disguise_used="trenchcoat inspector",
            ascii_art_key="standard",
        )
        assert p.disguise_used == "trenchcoat inspector"


# --- GrippyReview round-trip ---


class TestGrippyReviewRoundTrip:
    """Construct -> dump -> validate round-trip on the top-level model."""

    def test_round_trip_serialization(self) -> None:
        review = GrippyReview(**_minimal_review())
        dumped = review.model_dump()

        assert isinstance(dumped, dict)
        assert dumped["audit_type"] == "pr_review"
        assert dumped["pr"]["author"] == "nelson"
        assert len(dumped["findings"]) == 1
        assert dumped["findings"][0]["id"] == "F-001"

    def test_round_trip_revalidation(self) -> None:
        review = GrippyReview(**_minimal_review())
        dumped = review.model_dump()
        restored = GrippyReview.model_validate(dumped)

        assert restored.audit_type == review.audit_type
        assert restored.pr.title == review.pr.title
        assert restored.score.overall == review.score.overall
        assert restored.verdict.status == review.verdict.status
        assert restored.personality.tone_register == review.personality.tone_register

    def test_version_default(self) -> None:
        review = GrippyReview(**_minimal_review())
        assert review.version == "1.0"

    def test_score_overall_boundary(self) -> None:
        """Score.overall must be 0-100."""
        data = _minimal_review()
        data["score"]["overall"] = 101
        with pytest.raises(ValidationError, match="overall"):
            GrippyReview(**data)

    @pytest.mark.parametrize(
        "field", ["security", "logic", "governance", "reliability", "observability"]
    )
    def test_score_breakdown_rejects_negative(self, field: str) -> None:
        """ScoreBreakdown fields must be 0-100, not deduction-style negatives."""
        data = _minimal_review()
        data["score"]["breakdown"][field] = -17
        with pytest.raises(ValidationError):
            GrippyReview(**data)

    @pytest.mark.parametrize(
        "field", ["security", "logic", "governance", "reliability", "observability"]
    )
    def test_score_breakdown_rejects_over_100(self, field: str) -> None:
        data = _minimal_review()
        data["score"]["breakdown"][field] = 101
        with pytest.raises(ValidationError):
            GrippyReview(**data)

    def test_escalation_included(self) -> None:
        data = _minimal_review()
        data["escalations"] = [
            {
                "id": "E-001",
                "severity": "CRITICAL",
                "category": "security",
                "summary": "Credential leak in env file",
                "details": "API key committed to repo.",
                "recommended_target": "security-team",
                "blocking": True,
            }
        ]
        review = GrippyReview(**data)
        assert len(review.escalations) == 1
        assert review.escalations[0].blocking is True


# --- Finding frozen model ---


class TestFindingFrozen:
    """Finding model should be frozen to prevent accidental mutation."""

    def test_finding_is_frozen(self) -> None:
        """Assigning to a field on a frozen Finding raises ValidationError."""
        f = Finding(**_minimal_finding())
        with pytest.raises(ValidationError):
            f.file = "other.py"  # type: ignore[misc]
