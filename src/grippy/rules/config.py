# SPDX-License-Identifier: MIT
"""Profile configuration for the security rule engine."""

from __future__ import annotations

import os
from dataclasses import dataclass

from grippy.rules.base import RuleSeverity


@dataclass(frozen=True)
class ProfileConfig:
    """Configuration for a security profile — controls gate threshold."""

    name: str
    fail_on: RuleSeverity


PROFILES: dict[str, ProfileConfig] = {
    "general": ProfileConfig(name="general", fail_on=RuleSeverity.CRITICAL),
    "security": ProfileConfig(name="security", fail_on=RuleSeverity.ERROR),
    "strict-security": ProfileConfig(name="strict-security", fail_on=RuleSeverity.WARN),
}


def load_profile(cli_profile: str | None = None) -> ProfileConfig:
    """Load profile config with CLI > env > default priority.

    Args:
        cli_profile: Profile name from CLI --profile flag (highest priority).

    Returns:
        ProfileConfig for the resolved profile.

    Raises:
        ValueError: If the profile name is not recognized.
    """
    name = cli_profile or os.environ.get("GRIPPY_PROFILE", "general")
    if name not in PROFILES:
        msg = f"Unknown profile: {name!r}. Valid profiles: {sorted(PROFILES.keys())}"
        raise ValueError(msg)
    return PROFILES[name]
