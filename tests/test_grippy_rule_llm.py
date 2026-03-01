# SPDX-License-Identifier: MIT
"""Tests for Rule 5: llm-output-unsanitized."""

from __future__ import annotations

from grippy.rules.base import RuleSeverity
from grippy.rules.config import ProfileConfig
from grippy.rules.context import RuleContext, parse_diff
from grippy.rules.llm_output_sinks import SANITIZERS, LlmOutputSinksRule


def _ctx(diff: str) -> RuleContext:
    return RuleContext(
        diff=diff,
        files=parse_diff(diff),
        config=ProfileConfig(name="security", fail_on=RuleSeverity.ERROR),
    )


def _make_diff(path: str, *added_lines: str) -> str:
    lines = [
        f"diff --git a/{path} b/{path}\n",
        f"--- a/{path}\n",
        f"+++ b/{path}\n",
        f"@@ -1,1 +1,{len(added_lines) + 1} @@\n",
        " existing\n",
    ]
    for line in added_lines:
        lines.append(f"+{line}\n")
    return "".join(lines)


class TestLlmOutputSinks:
    def test_direct_pipe_to_comment(self) -> None:
        diff = _make_diff(
            "bot.py",
            "    result = agent.run(prompt)",
            "    pr.create_issue_comment(result.content)",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert any(r.rule_id == "llm-output-unsanitized" for r in results)

    def test_sanitized_output_not_flagged(self) -> None:
        diff = _make_diff(
            "bot.py",
            "    result = agent.run(prompt)",
            "    safe = sanitize(result.content)",
            "    pr.create_issue_comment(safe)",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert not any(r.rule_id == "llm-output-unsanitized" for r in results)

    def test_html_escape_suppresses(self) -> None:
        diff = _make_diff(
            "bot.py",
            "    result = agent.run(prompt)",
            "    safe = html.escape(result.content)",
            "    pr.create_issue_comment(safe)",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert not any(r.rule_id == "llm-output-unsanitized" for r in results)

    def test_completion_to_post(self) -> None:
        diff = _make_diff(
            "handler.py",
            "    completion = model.generate(prompt)",
            "    post(completion)",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert any(r.rule_id == "llm-output-unsanitized" for r in results)

    def test_choices_to_body(self) -> None:
        diff = _make_diff(
            "handler.py",
            "    text = response.choices[0].text",
            "    comment.body = text",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert any(r.rule_id == "llm-output-unsanitized" for r in results)

    def test_no_model_output_not_flagged(self) -> None:
        diff = _make_diff(
            "handler.py",
            "    text = 'hello world'",
            "    pr.create_issue_comment(text)",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert results == []

    def test_non_python_file_ignored(self) -> None:
        diff = _make_diff(
            "handler.js",
            "    const result = agent.run(prompt);",
            "    pr.create_issue_comment(result.content);",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert results == []

    def test_severity_is_error(self) -> None:
        diff = _make_diff(
            "bot.py",
            "    result = agent.run(prompt)",
            "    pr.create_issue_comment(result.content)",
        )
        results = LlmOutputSinksRule().run(_ctx(diff))
        assert all(r.severity == RuleSeverity.ERROR for r in results)

    def test_sanitizers_frozenset(self) -> None:
        assert isinstance(SANITIZERS, frozenset)
        assert "sanitize" in SANITIZERS
        assert "html.escape" in SANITIZERS
        assert "_sanitize_comment_text" in SANITIZERS
