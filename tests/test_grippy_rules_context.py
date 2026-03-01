# SPDX-License-Identifier: MIT
"""Tests for grippy.rules.context — diff parser and RuleContext."""

from __future__ import annotations

import pytest

from grippy.rules.base import RuleSeverity
from grippy.rules.config import ProfileConfig
from grippy.rules.context import ChangedFile, DiffHunk, DiffLine, RuleContext, parse_diff

# --- parse_diff tests ---


class TestParseDiff:
    def test_empty_diff(self) -> None:
        assert parse_diff("") == []
        assert parse_diff("   \n\n  ") == []

    def test_single_file_single_hunk(self) -> None:
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "index 1234..5678 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "+added\n"
            " line2\n"
            "-removed\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].path == "foo.py"
        assert not files[0].is_new
        assert not files[0].is_deleted
        assert len(files[0].hunks) == 1

        hunk = files[0].hunks[0]
        assert hunk.old_start == 1
        assert hunk.new_start == 1
        assert len(hunk.lines) == 4

        # Context line
        assert hunk.lines[0].type == "context"
        assert hunk.lines[0].content == "line1"
        assert hunk.lines[0].old_lineno == 1
        assert hunk.lines[0].new_lineno == 1

        # Added line
        assert hunk.lines[1].type == "add"
        assert hunk.lines[1].content == "added"
        assert hunk.lines[1].old_lineno is None
        assert hunk.lines[1].new_lineno == 2

        # Context line (after add)
        assert hunk.lines[2].type == "context"
        assert hunk.lines[2].content == "line2"
        assert hunk.lines[2].old_lineno == 2
        assert hunk.lines[2].new_lineno == 3

        # Removed line
        assert hunk.lines[3].type == "remove"
        assert hunk.lines[3].content == "removed"
        assert hunk.lines[3].old_lineno == 3
        assert hunk.lines[3].new_lineno is None

    def test_new_file(self) -> None:
        diff = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+line1\n"
            "+line2\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].is_new is True
        assert files[0].is_deleted is False
        assert len(files[0].hunks) == 1
        assert len(files[0].hunks[0].lines) == 2

    def test_deleted_file(self) -> None:
        diff = (
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "index abc1234..0000000\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-line1\n"
            "-line2\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].is_deleted is True
        assert files[0].is_new is False

    def test_renamed_file(self) -> None:
        diff = (
            "diff --git a/old_name.py b/new_name.py\n"
            "similarity index 95%\n"
            "rename from old_name.py\n"
            "rename to new_name.py\n"
            "index abc..def 100644\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1,2 +1,2 @@\n"
            " same\n"
            "-old\n"
            "+new\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].path == "new_name.py"
        assert files[0].is_renamed is True
        assert files[0].rename_from == "old_name.py"

    def test_multiple_files(self) -> None:
        diff = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,1 +1,2 @@\n"
            " existing\n"
            "+new_a\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -1,1 +1,2 @@\n"
            " existing\n"
            "+new_b\n"
        )
        files = parse_diff(diff)
        assert len(files) == 2
        assert files[0].path == "a.py"
        assert files[1].path == "b.py"

    def test_multiple_hunks(self) -> None:
        diff = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,2 +1,3 @@\n"
            " a\n"
            "+b\n"
            " c\n"
            "@@ -10,2 +11,3 @@\n"
            " x\n"
            "+y\n"
            " z\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert len(files[0].hunks) == 2
        assert files[0].hunks[0].new_start == 1
        assert files[0].hunks[1].new_start == 11

    def test_no_newline_at_end(self) -> None:
        diff = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,2 @@\n"
            " existing\n"
            "+added\n"
            "\\ No newline at end of file\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        lines = files[0].hunks[0].lines
        assert len(lines) == 2
        assert lines[1].type == "add"
        assert lines[1].content == "added"

    def test_binary_file(self) -> None:
        diff = (
            "diff --git a/image.png b/image.png\n"
            "new file mode 100644\n"
            "index 0000000..abc1234\n"
            "Binary files /dev/null and b/image.png differ\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].path == "image.png"
        assert files[0].is_new is True
        assert len(files[0].hunks) == 0


# --- RuleContext tests ---


class TestRuleContext:
    @pytest.fixture()
    def config(self) -> ProfileConfig:
        return ProfileConfig(name="security", fail_on=RuleSeverity.ERROR)

    def test_files_changed(self, config: ProfileConfig) -> None:
        files = [
            ChangedFile(path="a.py", hunks=[]),
            ChangedFile(path="b.js", hunks=[]),
        ]
        ctx = RuleContext(diff="", files=files, config=config)
        assert ctx.files_changed == ["a.py", "b.js"]

    def test_added_lines_for_glob(self, config: ProfileConfig) -> None:
        hunk = DiffHunk(
            old_start=1,
            old_count=1,
            new_start=1,
            new_count=3,
            lines=[
                DiffLine(type="context", content="existing", old_lineno=1, new_lineno=1),
                DiffLine(type="add", content="new1", old_lineno=None, new_lineno=2),
                DiffLine(type="add", content="new2", old_lineno=None, new_lineno=3),
            ],
        )
        files = [ChangedFile(path="src/foo.py", hunks=[hunk])]
        ctx = RuleContext(diff="", files=files, config=config)

        results = ctx.added_lines_for("src/*.py")
        assert len(results) == 2
        assert results[0] == ("src/foo.py", 2, "new1")
        assert results[1] == ("src/foo.py", 3, "new2")

    def test_added_lines_for_no_match(self, config: ProfileConfig) -> None:
        hunk = DiffHunk(
            old_start=1,
            old_count=1,
            new_start=1,
            new_count=2,
            lines=[DiffLine(type="add", content="x", old_lineno=None, new_lineno=1)],
        )
        files = [ChangedFile(path="src/foo.py", hunks=[hunk])]
        ctx = RuleContext(diff="", files=files, config=config)
        assert ctx.added_lines_for("*.js") == []
