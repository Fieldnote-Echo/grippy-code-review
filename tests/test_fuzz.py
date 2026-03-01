# SPDX-License-Identifier: MIT
"""Property-based fuzz tests for parsers and sanitization functions.

Uses hypothesis to generate random inputs and verify that parsers never crash,
produce valid output types, and sanitization functions strip content safely.
"""

from __future__ import annotations

import os
import string

from hypothesis import given, settings
from hypothesis import strategies as st

from grippy.github_review import parse_diff_lines
from grippy.retry import _strip_markdown_fences
from grippy.rules.context import ChangedFile, DiffLine, parse_diff

# ---------------------------------------------------------------------------
# Strategies for generating realistic-ish diff text
# ---------------------------------------------------------------------------

# CI runs 10k examples; set FUZZ_SLOW=1 for 50k (local deep run)
_MAX_EXAMPLES = 50_000 if os.environ.get("FUZZ_SLOW") else 10_000

_PRINTABLE = st.text(alphabet=string.printable, min_size=0, max_size=200)

_DIFF_LINE = st.one_of(
    st.just("+added line"),
    st.just("-removed line"),
    st.just(" context line"),
    st.just("\\ No newline at end of file"),
    st.text(alphabet=string.printable, min_size=0, max_size=120),
)

_HUNK_HEADER = st.builds(
    lambda a, b, c, d: f"@@ -{a},{b} +{c},{d} @@",
    st.integers(min_value=0, max_value=9999),
    st.integers(min_value=0, max_value=999),
    st.integers(min_value=0, max_value=9999),
    st.integers(min_value=0, max_value=999),
)

_FILE_NAME = st.from_regex(r"[a-z][a-z0-9_/]{0,40}\.(py|yml|js|ts|md)", fullmatch=True)

_DIFF_BLOCK = st.builds(
    lambda fname, hunk, lines: (
        f"diff --git a/{fname} b/{fname}\n--- a/{fname}\n+++ b/{fname}\n{hunk}\n" + "\n".join(lines)
    ),
    _FILE_NAME,
    _HUNK_HEADER,
    st.lists(_DIFF_LINE, min_size=1, max_size=30),
)

_FULL_DIFF = st.builds(
    lambda blocks: "\n".join(blocks),
    st.lists(_DIFF_BLOCK, min_size=1, max_size=5),
)


# ---------------------------------------------------------------------------
# Fuzz: parse_diff (rules/context.py) — never crashes, returns valid types
# ---------------------------------------------------------------------------


@given(diff_text=_FULL_DIFF)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_parse_diff_structured(diff_text: str) -> None:
    """parse_diff never crashes on structured diff-like input."""
    result = parse_diff(diff_text)
    assert isinstance(result, list)
    for f in result:
        assert isinstance(f, ChangedFile)
        assert isinstance(f.path, str)
        for hunk in f.hunks:
            for line in hunk.lines:
                assert isinstance(line, DiffLine)
                assert line.type in ("add", "remove", "context")


@given(diff_text=_PRINTABLE)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_parse_diff_arbitrary(diff_text: str) -> None:
    """parse_diff never crashes on arbitrary string input."""
    result = parse_diff(diff_text)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Fuzz: parse_diff_lines (github_review.py) — never crashes, valid types
# ---------------------------------------------------------------------------


@given(diff_text=_FULL_DIFF)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_parse_diff_lines_structured(diff_text: str) -> None:
    """parse_diff_lines never crashes on structured diff-like input."""
    result = parse_diff_lines(diff_text)
    assert isinstance(result, dict)
    for path, lines in result.items():
        assert isinstance(path, str)
        assert isinstance(lines, set)
        for ln in lines:
            assert isinstance(ln, int)
            assert ln >= 0


@given(diff_text=_PRINTABLE)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_parse_diff_lines_arbitrary(diff_text: str) -> None:
    """parse_diff_lines never crashes on arbitrary string input."""
    result = parse_diff_lines(diff_text)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Fuzz: _strip_markdown_fences (retry.py) — never crashes, returns str
# ---------------------------------------------------------------------------


@given(text=_PRINTABLE)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_strip_markdown_fences(text: str) -> None:
    """_strip_markdown_fences never crashes and always returns a string."""
    result = _strip_markdown_fences(text)
    assert isinstance(result, str)


@given(
    inner=_PRINTABLE,
    lang=st.sampled_from(["json", "python", ""]),
)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_strip_markdown_fences_wrapped(inner: str, lang: str) -> None:
    """_strip_markdown_fences extracts content from fenced blocks."""
    wrapped = f"```{lang}\n{inner}\n```"
    result = _strip_markdown_fences(wrapped)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Fuzz: parse_diff edge cases — deleted files, renames, binary files
# ---------------------------------------------------------------------------

_DELETED_FILE_DIFF = st.builds(
    lambda fname, lines: (
        f"diff --git a/{fname} b/{fname}\n"
        f"deleted file mode 100644\n"
        f"--- a/{fname}\n"
        f"+++ /dev/null\n"
        f"@@ -1,{len(lines)} +0,0 @@\n" + "\n".join(f"-{ln}" for ln in lines)
    ),
    _FILE_NAME,
    st.lists(
        st.text(alphabet=string.ascii_letters, min_size=1, max_size=40), min_size=1, max_size=10
    ),
)

_RENAME_DIFF = st.builds(
    lambda old, new: (
        f"diff --git a/{old} b/{new}\n"
        f"similarity index 95%\n"
        f"rename from {old}\n"
        f"rename to {new}\n"
        f"--- a/{old}\n"
        f"+++ b/{new}\n"
        f"@@ -1,3 +1,3 @@\n"
        f" unchanged\n"
        f"-old line\n"
        f"+new line\n"
    ),
    _FILE_NAME,
    _FILE_NAME,
)


@given(diff_text=_DELETED_FILE_DIFF)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_parse_diff_deleted_files(diff_text: str) -> None:
    """parse_diff handles deleted file diffs."""
    result = parse_diff(diff_text)
    assert isinstance(result, list)
    for f in result:
        assert isinstance(f, ChangedFile)


@given(diff_text=_RENAME_DIFF)
@settings(max_examples=_MAX_EXAMPLES)
def test_fuzz_parse_diff_renames(diff_text: str) -> None:
    """parse_diff handles rename diffs."""
    result = parse_diff(diff_text)
    assert isinstance(result, list)
    for f in result:
        assert isinstance(f, ChangedFile)
