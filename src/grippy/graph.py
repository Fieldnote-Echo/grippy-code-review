"""Graph enums for Grippy's codebase knowledge graph.

Provides node/edge type enums for the graph persistence layer.
Finding lifecycle is owned by GitHub (not tracked locally).
"""

from __future__ import annotations

from enum import StrEnum


class EdgeType(StrEnum):
    VIOLATES = "VIOLATES"
    FOUND_IN = "FOUND_IN"
    FIXED_BY = "FIXED_BY"
    IS_A = "IS_A"
    PREREQUISITE_FOR = "PREREQUISITE_FOR"
    EXTRACTED_FROM = "EXTRACTED_FROM"
    TENDENCY = "TENDENCY"
    REVIEWED_BY = "REVIEWED_BY"


class NodeType(StrEnum):
    REVIEW = "REVIEW"
    RULE = "RULE"
    PATTERN = "PATTERN"
    AUTHOR = "AUTHOR"
    FILE = "FILE"
