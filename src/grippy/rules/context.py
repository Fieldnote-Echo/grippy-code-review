# SPDX-License-Identifier: MIT
"""Diff parser and rule context — structured representation of a PR diff."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grippy.rules.config import ProfileConfig


@dataclass(frozen=True)
class DiffLine:
    """A single line within a diff hunk."""

    type: str  # "add" | "remove" | "context"
    content: str  # Line content without +/- prefix
    old_lineno: int | None  # Left-side line number
    new_lineno: int | None  # Right-side line number


@dataclass(frozen=True)
class DiffHunk:
    """A contiguous hunk from a unified diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine]


@dataclass(frozen=True)
class ChangedFile:
    """A file that was changed in the diff."""

    path: str
    hunks: list[DiffHunk]
    is_new: bool = False
    is_deleted: bool = False
    is_renamed: bool = False
    rename_from: str | None = None


@dataclass
class RuleContext:
    """Context passed to each rule — parsed diff + profile config."""

    diff: str
    files: list[ChangedFile]
    config: ProfileConfig

    @property
    def files_changed(self) -> list[str]:
        """Return list of changed file paths."""
        return [f.path for f in self.files]

    def added_lines_for(self, path_glob: str) -> list[tuple[str, int, str]]:
        """Return (file, lineno, content) for added lines in matching files."""
        results: list[tuple[str, int, str]] = []
        for f in self.files:
            if not fnmatch.fnmatch(f.path, path_glob):
                continue
            for hunk in f.hunks:
                for line in hunk.lines:
                    if line.type == "add" and line.new_lineno is not None:
                        results.append((f.path, line.new_lineno, line.content))
        return results


# --- Diff parser ---

_FILE_HEADER_RE = re.compile(r"^diff --git a/.+ b/(.+)$")
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_RENAME_FROM_RE = re.compile(r"^rename from (.+)$")
_RENAME_TO_RE = re.compile(r"^rename to (.+)$")


def parse_diff(diff_text: str) -> list[ChangedFile]:
    """Parse a unified diff into structured ChangedFile objects.

    Handles: new files, deleted files, renames, binary files, no-newline markers.
    """
    if not diff_text.strip():
        return []

    files: list[ChangedFile] = []
    current_path: str | None = None
    current_hunks: list[DiffHunk] = []
    is_new = False
    is_deleted = False
    is_renamed = False
    rename_from: str | None = None

    # Current hunk state
    hunk_lines: list[DiffLine] = []
    hunk_old_start = 0
    hunk_old_count = 0
    hunk_new_start = 0
    hunk_new_count = 0
    old_line = 0
    new_line = 0
    in_hunk = False

    def _flush_hunk() -> None:
        nonlocal in_hunk, hunk_lines
        if in_hunk and hunk_lines:
            current_hunks.append(
                DiffHunk(
                    old_start=hunk_old_start,
                    old_count=hunk_old_count,
                    new_start=hunk_new_start,
                    new_count=hunk_new_count,
                    lines=list(hunk_lines),
                )
            )
        hunk_lines = []
        in_hunk = False

    def _flush_file() -> None:
        nonlocal current_path, current_hunks, is_new, is_deleted, is_renamed, rename_from
        _flush_hunk()
        if current_path is not None:
            files.append(
                ChangedFile(
                    path=current_path,
                    hunks=list(current_hunks),
                    is_new=is_new,
                    is_deleted=is_deleted,
                    is_renamed=is_renamed,
                    rename_from=rename_from,
                )
            )
        current_path = None
        current_hunks = []
        is_new = False
        is_deleted = False
        is_renamed = False
        rename_from = None

    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # File header
        file_match = _FILE_HEADER_RE.match(line)
        if file_match:
            _flush_file()
            current_path = file_match.group(1)
            i += 1
            continue

        # Metadata lines between file header and first hunk
        if not in_hunk and current_path is not None:
            if line.startswith("new file"):
                is_new = True
                i += 1
                continue
            if line.startswith("deleted file"):
                is_deleted = True
                i += 1
                continue
            if line.startswith("similarity index"):
                is_renamed = True
                i += 1
                continue
            rename_from_match = _RENAME_FROM_RE.match(line)
            if rename_from_match:
                rename_from = rename_from_match.group(1)
                is_renamed = True
                i += 1
                continue
            if _RENAME_TO_RE.match(line):
                i += 1
                continue
            if line.startswith("index ") or line.startswith("---") or line.startswith("+++"):
                i += 1
                continue
            if line.startswith("Binary files"):
                i += 1
                continue

        # Hunk header
        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            _flush_hunk()
            hunk_old_start = int(hunk_match.group(1))
            hunk_old_count = int(hunk_match.group(2) or "1")
            hunk_new_start = int(hunk_match.group(3))
            hunk_new_count = int(hunk_match.group(4) or "1")
            old_line = hunk_old_start
            new_line = hunk_new_start
            in_hunk = True
            hunk_lines = []
            i += 1
            continue

        if in_hunk:
            if line.startswith("+"):
                hunk_lines.append(
                    DiffLine(
                        type="add",
                        content=line[1:],
                        old_lineno=None,
                        new_lineno=new_line,
                    )
                )
                new_line += 1
            elif line.startswith("-"):
                hunk_lines.append(
                    DiffLine(
                        type="remove",
                        content=line[1:],
                        old_lineno=old_line,
                        new_lineno=None,
                    )
                )
                old_line += 1
            elif line.startswith(" "):
                hunk_lines.append(
                    DiffLine(
                        type="context",
                        content=line[1:],
                        old_lineno=old_line,
                        new_lineno=new_line,
                    )
                )
                old_line += 1
                new_line += 1
            elif line.startswith("\\"):
                # "\ No newline at end of file" — skip, don't increment
                pass
            else:
                # Unexpected line in hunk — might be a new file header without blank
                # Re-process this line
                _flush_hunk()
                in_hunk = False
                continue

        i += 1

    _flush_file()
    return files
