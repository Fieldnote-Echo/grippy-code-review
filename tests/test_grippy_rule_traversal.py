# SPDX-License-Identifier: MIT
"""Tests for Rule 4: path-traversal-risk."""

from __future__ import annotations

from grippy.rules.base import RuleSeverity
from grippy.rules.config import ProfileConfig
from grippy.rules.context import RuleContext, parse_diff
from grippy.rules.path_traversal import PathTraversalRule


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


class TestPathTraversal:
    def test_open_with_user_input(self) -> None:
        diff = _make_diff("app.py", "f = open(user_path)")
        results = PathTraversalRule().run(_ctx(diff))
        assert any("user-controlled" in r.message for r in results)

    def test_open_with_request(self) -> None:
        diff = _make_diff("app.py", "f = open(request.form['file'])")
        results = PathTraversalRule().run(_ctx(diff))
        assert len(results) >= 1

    def test_path_join_with_input(self) -> None:
        diff = _make_diff("app.py", "p = os.path.join(base, user_input)")
        results = PathTraversalRule().run(_ctx(diff))
        assert any(r.rule_id == "path-traversal-risk" for r in results)

    def test_path_join_with_upload(self) -> None:
        diff = _make_diff("views.py", "p = path.join(upload_dir, upload_filename)")
        results = PathTraversalRule().run(_ctx(diff))
        assert len(results) >= 1

    def test_string_literal_not_flagged(self) -> None:
        diff = _make_diff("app.py", 'f = open("config.json")')
        results = PathTraversalRule().run(_ctx(diff))
        assert results == []

    def test_traversal_unix(self) -> None:
        diff = _make_diff("app.py", 'p = os.path.join(base, "../../../etc/passwd")')
        results = PathTraversalRule().run(_ctx(diff))
        assert any("traversal" in r.message.lower() for r in results)

    def test_traversal_windows(self) -> None:
        diff = _make_diff("app.py", 'p = os.path.join(base, "..\\\\..\\\\secret")')
        results = PathTraversalRule().run(_ctx(diff))
        assert any("traversal" in r.message.lower() for r in results)

    def test_non_code_file_ignored(self) -> None:
        diff = _make_diff("README.md", "open(user_path)")
        results = PathTraversalRule().run(_ctx(diff))
        assert results == []

    def test_js_file_supported(self) -> None:
        diff = _make_diff("app.js", "const f = path.join(base, user_input)")
        results = PathTraversalRule().run(_ctx(diff))
        assert len(results) >= 1

    def test_ts_file_supported(self) -> None:
        diff = _make_diff("app.ts", "const f = path.join(base, user_input)")
        results = PathTraversalRule().run(_ctx(diff))
        assert len(results) >= 1

    def test_severity_is_warn(self) -> None:
        diff = _make_diff("app.py", "f = open(user_path)")
        results = PathTraversalRule().run(_ctx(diff))
        assert all(r.severity == RuleSeverity.WARN for r in results)

    def test_no_taint_indicator_not_flagged(self) -> None:
        diff = _make_diff("app.py", "f = open(config_path)")
        results = PathTraversalRule().run(_ctx(diff))
        assert results == []
