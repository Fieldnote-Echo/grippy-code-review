"""Graph enums and finding lifecycle utilities for Grippy reviews.

Provides node/edge type enums, finding status tracking, and pure
cross-reference comparison for finding lifecycle classification.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from grippy.schema import Finding


class FindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class EdgeType(StrEnum):
    VIOLATES = "VIOLATES"
    FOUND_IN = "FOUND_IN"
    FIXED_BY = "FIXED_BY"
    IS_A = "IS_A"
    PREREQUISITE_FOR = "PREREQUISITE_FOR"
    EXTRACTED_FROM = "EXTRACTED_FROM"
    TENDENCY = "TENDENCY"
    REVIEWED_BY = "REVIEWED_BY"
    RESOLVES = "RESOLVES"
    PERSISTS_AS = "PERSISTS_AS"


class NodeType(StrEnum):
    REVIEW = "REVIEW"
    FINDING = "FINDING"
    RULE = "RULE"
    PATTERN = "PATTERN"
    AUTHOR = "AUTHOR"
    FILE = "FILE"
    SUGGESTION = "SUGGESTION"


class FindingLifecycle(BaseModel):
    """Cross-round finding comparison result."""

    new: list[Finding]
    persists: list[Finding]
    resolved: list[Finding]


def cross_reference_findings(
    current: list[Finding],
    previous: list[Finding],
) -> FindingLifecycle:
    """Compare current vs previous findings by fingerprint (pure, no DB).

    This is the **pure** resolution function — takes two lists of Finding
    objects and returns their lifecycle classification. Used for offline/CLI
    analysis of two GrippyReview objects.

    The **DB-backed** counterpart is ``resolve_findings_against_prior()`` in
    ``github_review.py``, which operates on dicts (with ``node_id``,
    ``fingerprint``, ``title``) from ``GrippyStore.get_prior_findings()``.
    That function is used in CI to carry ``node_id`` references needed for
    thread resolution and ``FindingStatus`` updates in the graph DB.

    Both functions are intentionally separate:
    - This one is pure, testable, and DB-independent.
    - The github_review one is coupled to the persistence layer by design.

    Returns a FindingLifecycle with:
    - new: findings in current but not previous
    - persists: findings in both (matched by fingerprint)
    - resolved: findings in previous but not current
    """
    prev_fps = {f.fingerprint for f in previous}
    curr_fps = {f.fingerprint for f in current}

    return FindingLifecycle(
        new=[f for f in current if f.fingerprint not in prev_fps],
        persists=[f for f in current if f.fingerprint in prev_fps],
        resolved=[f for f in previous if f.fingerprint not in curr_fps],
    )
