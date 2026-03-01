# SPDX-License-Identifier: MIT
"""Tests for Grippy graph enums."""

from __future__ import annotations

from grippy.graph import (
    EdgeType,
    NodeType,
)

# --- Enum values ---


class TestEdgeType:
    """Edge type enum values."""

    def test_violates_edge_exists(self) -> None:
        assert EdgeType.VIOLATES == "VIOLATES"

    def test_found_in_edge_exists(self) -> None:
        assert EdgeType.FOUND_IN == "FOUND_IN"

    def test_extracted_from_edge_exists(self) -> None:
        assert EdgeType.EXTRACTED_FROM == "EXTRACTED_FROM"

    def test_reviewed_by_edge_exists(self) -> None:
        assert EdgeType.REVIEWED_BY == "REVIEWED_BY"

    def test_tendency_edge_exists(self) -> None:
        assert EdgeType.TENDENCY == "TENDENCY"

    def test_is_a_edge_exists(self) -> None:
        assert EdgeType.IS_A == "IS_A"


class TestNodeType:
    def test_node_types(self) -> None:
        assert NodeType.REVIEW == "REVIEW"
        assert NodeType.FILE == "FILE"
        assert NodeType.AUTHOR == "AUTHOR"
        assert NodeType.RULE == "RULE"
        assert NodeType.PATTERN == "PATTERN"

    def test_finding_removed(self) -> None:
        """FINDING and SUGGESTION node types removed — lifecycle owned by GitHub."""
        values = {m.value for m in NodeType}
        assert "FINDING" not in values
        assert "SUGGESTION" not in values
