# SPDX-License-Identifier: MIT
"""Tests for Rule 2: secrets-in-diff."""

from __future__ import annotations

from grippy.rules.base import RuleSeverity
from grippy.rules.config import ProfileConfig
from grippy.rules.context import RuleContext, parse_diff
from grippy.rules.secrets_in_diff import SecretsInDiffRule


def _ctx(diff: str) -> RuleContext:
    return RuleContext(
        diff=diff,
        files=parse_diff(diff),
        config=ProfileConfig(name="security", fail_on=RuleSeverity.ERROR),
    )


def _make_diff(path: str, added_line: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,1 +1,2 @@\n"
        " existing\n"
        f"+{added_line}\n"
    )


class TestSecretsInDiff:
    def test_aws_key(self) -> None:
        diff = _make_diff("config.py", 'AWS_KEY = "AKIAIOSFODNN7ABCDEFG"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any(r.severity == RuleSeverity.CRITICAL and "AWS" in r.message for r in results)

    def test_github_classic_pat(self) -> None:
        diff = _make_diff("setup.py", 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any("GitHub classic PAT" in r.message for r in results)

    def test_github_fine_grained_pat(self) -> None:
        diff = _make_diff("setup.py", 'token = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZab"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any("GitHub fine-grained PAT" in r.message for r in results)

    def test_github_other_tokens(self) -> None:
        for prefix in ("gho_", "ghu_", "ghs_", "ghr_"):
            diff = _make_diff(
                "config.py", f'token = "{prefix}ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"'
            )
            results = SecretsInDiffRule().run(_ctx(diff))
            assert any(r.severity == RuleSeverity.CRITICAL for r in results), f"Failed for {prefix}"

    def test_openai_key(self) -> None:
        diff = _make_diff("config.py", 'api_key = "sk-abcdefghijklmnopqrstuvwxyz"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any("OpenAI" in r.message for r in results)

    def test_private_key_header(self) -> None:
        diff = _make_diff("certs/key.pem", "-----BEGIN RSA PRIVATE KEY-----")
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any(
            r.severity == RuleSeverity.CRITICAL and "Private key" in r.message for r in results
        )

    def test_generic_secret_assignment(self) -> None:
        diff = _make_diff("config.py", 'password = "supersecretvalue123"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any("Generic secret" in r.message for r in results)

    def test_env_file_addition(self) -> None:
        diff = _make_diff(".env", "DB_PASSWORD=hunter2")
        results = SecretsInDiffRule().run(_ctx(diff))
        assert any(r.severity == RuleSeverity.WARN and ".env" in r.message for r in results)

    def test_comment_line_skipped(self) -> None:
        diff = _make_diff("config.py", '# token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert not any("GitHub" in r.message for r in results)

    def test_placeholder_skipped(self) -> None:
        diff = _make_diff("config.py", 'token = "changeme"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert not any("Generic secret" in r.message for r in results)

    def test_placeholder_your_dash_skipped(self) -> None:
        diff = _make_diff("config.py", 'api_key = "your-api-key-here"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert not any("Generic secret" in r.message for r in results)

    def test_tests_directory_skipped(self) -> None:
        diff = _make_diff("tests/test_auth.py", 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"')
        results = SecretsInDiffRule().run(_ctx(diff))
        assert results == []

    def test_context_line_not_flagged(self) -> None:
        diff = (
            "diff --git a/config.py b/config.py\n"
            "--- a/config.py\n"
            "+++ b/config.py\n"
            "@@ -1,2 +1,3 @@\n"
            ' token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"\n'
            "+# new comment\n"
            " other = True\n"
        )
        results = SecretsInDiffRule().run(_ctx(diff))
        assert not any("GitHub" in r.message for r in results)

    def test_evidence_is_redacted(self) -> None:
        diff = _make_diff("config.py", "AKIAIOSFODNN7EXAMPLE_LONGKEY")
        results = SecretsInDiffRule().run(_ctx(diff))
        for r in results:
            if r.evidence and "AKIA" in r.evidence:
                assert r.evidence.endswith("...")
                assert len(r.evidence) < 20
