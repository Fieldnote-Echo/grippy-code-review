# SPDX-License-Identifier: MIT
"""Prompt chain loader — reads Grippy's markdown prompt files and composes them."""

from __future__ import annotations

from pathlib import Path

# Composition order per prompt-wiring-design.md:
# IDENTITY:      CONSTITUTION + PERSONA (Agno description)
# INSTRUCTIONS:  MODE_CHAINS[mode] + SHARED_PROMPTS + CHAIN_SUFFIX (Agno instructions)

IDENTITY_FILES: list[str] = ["CONSTITUTION.md", "PERSONA.md"]

# Mode-specific prefix: system-core + mode prompt
MODE_CHAINS: dict[str, list[str]] = {
    "pr_review": ["system-core.md", "pr-review.md"],
    "security_audit": ["system-core.md", "security-audit.md"],
    "governance_check": ["system-core.md", "governance-check.md"],
    "surprise_audit": ["system-core.md", "surprise-audit.md"],
    "cli": ["system-core.md", "cli-mode.md"],
    "github_app": ["system-core.md", "github-app.md"],
}

# Always-on personality + quality gate prompts (all modes)
SHARED_PROMPTS: list[str] = [
    "tone-calibration.md",
    "confidence-filter.md",
    "escalation.md",
    "context-builder.md",
    "catchphrases.md",
    "disguises.md",
    "ascii-art.md",
    "all-clear.md",
]

# Anchored at the end: scoring rubric then output schema
CHAIN_SUFFIX: list[str] = ["scoring-rubric.md", "output-schema.md"]


def load_prompt_file(prompts_dir: Path, filename: str) -> str:
    """Load a single prompt file and return its content."""
    path = prompts_dir / filename
    if not path.exists():
        msg = f"Prompt file not found: {path}"
        raise FileNotFoundError(msg)
    return path.read_text(encoding="utf-8")


def load_identity(prompts_dir: Path) -> str:
    """Load CONSTITUTION + PERSONA — the identity layer (description)."""
    parts = [load_prompt_file(prompts_dir, f) for f in IDENTITY_FILES]
    return "\n\n".join(parts)


def load_instructions(prompts_dir: Path, mode: str = "pr_review") -> list[str]:
    """Load the composed instruction chain for a review mode.

    Composes: MODE_CHAINS[mode] + SHARED_PROMPTS + CHAIN_SUFFIX.

    Returns a list of strings (one per prompt file) for Agno's instructions parameter.
    """
    if mode not in MODE_CHAINS:
        msg = f"Unknown review mode: {mode}. Available: {list(MODE_CHAINS.keys())}"
        raise ValueError(msg)
    chain = MODE_CHAINS[mode] + SHARED_PROMPTS + CHAIN_SUFFIX
    return [load_prompt_file(prompts_dir, f) for f in chain]
