# SPDX-License-Identifier: MIT
"""Tests for grippy.rules.config — profile loading and configuration."""

from __future__ import annotations

import pytest

from grippy.rules.base import RuleSeverity
from grippy.rules.config import PROFILES, load_profile


class TestProfileConfig:
    def test_all_profiles_exist(self) -> None:
        assert "general" in PROFILES
        assert "security" in PROFILES
        assert "strict-security" in PROFILES

    def test_general_profile(self) -> None:
        p = PROFILES["general"]
        assert p.name == "general"
        assert p.fail_on == RuleSeverity.CRITICAL

    def test_security_profile(self) -> None:
        p = PROFILES["security"]
        assert p.name == "security"
        assert p.fail_on == RuleSeverity.ERROR

    def test_strict_security_profile(self) -> None:
        p = PROFILES["strict-security"]
        assert p.name == "strict-security"
        assert p.fail_on == RuleSeverity.WARN


class TestLoadProfile:
    def test_cli_override_highest_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRIPPY_PROFILE", "general")
        p = load_profile(cli_profile="security")
        assert p.name == "security"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRIPPY_PROFILE", "strict-security")
        p = load_profile()
        assert p.name == "strict-security"

    def test_default_is_general(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GRIPPY_PROFILE", raising=False)
        p = load_profile()
        assert p.name == "general"

    def test_invalid_profile_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown profile"):
            load_profile(cli_profile="nonexistent")

    def test_invalid_env_profile_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRIPPY_PROFILE", "badname")
        with pytest.raises(ValueError, match="Unknown profile"):
            load_profile()
