"""Tests for Grippy prompt chain loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from grippy.prompts import (
    CHAIN_SUFFIX,
    IDENTITY_FILES,
    MODE_CHAINS,
    SHARED_PROMPTS,
    load_identity,
    load_instructions,
    load_prompt_file,
)

# --- Fixtures ---


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create a temp directory with minimal prompt files for testing."""
    d = tmp_path / "prompts"
    d.mkdir()
    return d


@pytest.fixture
def identity_dir(prompts_dir: Path) -> Path:
    """Populate prompts_dir with CONSTITUTION.md and PERSONA.md."""
    (prompts_dir / "CONSTITUTION.md").write_text("You are Grippy.\n", encoding="utf-8")
    (prompts_dir / "PERSONA.md").write_text("Grudging code inspector.\n", encoding="utf-8")
    return prompts_dir


@pytest.fixture
def full_chain_dir(identity_dir: Path) -> Path:
    """Populate prompts_dir with all files needed for any mode chain."""
    # Mode-specific files
    all_mode_files: set[str] = set()
    for chain in MODE_CHAINS.values():
        all_mode_files.update(chain)
    for filename in all_mode_files:
        (identity_dir / filename).write_text(f"# {filename}\nContent here.\n", encoding="utf-8")
    # Shared prompts
    for filename in SHARED_PROMPTS:
        (identity_dir / filename).write_text(f"# {filename}\nShared content.\n", encoding="utf-8")
    # Chain suffix
    for filename in CHAIN_SUFFIX:
        if not (identity_dir / filename).exists():
            (identity_dir / filename).write_text(
                f"# {filename}\nSuffix content.\n", encoding="utf-8"
            )
    return identity_dir


# --- load_prompt_file ---


class TestLoadPromptFile:
    def test_loads_existing_file(self, prompts_dir: Path) -> None:
        (prompts_dir / "test.md").write_text("hello world", encoding="utf-8")
        result = load_prompt_file(prompts_dir, "test.md")
        assert result == "hello world"

    def test_preserves_content(self, prompts_dir: Path) -> None:
        content = "# Title\n\nParagraph with **bold** and `code`.\n"
        (prompts_dir / "rich.md").write_text(content, encoding="utf-8")
        result = load_prompt_file(prompts_dir, "rich.md")
        assert result == content

    def test_missing_file_raises(self, prompts_dir: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            load_prompt_file(prompts_dir, "nonexistent.md")


# --- load_identity ---


class TestLoadIdentity:
    def test_joins_constitution_and_persona(self, identity_dir: Path) -> None:
        result = load_identity(identity_dir)
        assert "You are Grippy." in result
        assert "Grudging code inspector." in result

    def test_double_newline_separator(self, identity_dir: Path) -> None:
        result = load_identity(identity_dir)
        # Files are "You are Grippy.\n" and "Grudging code inspector.\n"
        # Joined with "\n\n" -> "You are Grippy.\n\n\nGrudging code inspector.\n"
        assert "\n\n" in result
        assert result == "You are Grippy.\n\n\nGrudging code inspector.\n"

    def test_missing_constitution_raises(self, prompts_dir: Path) -> None:
        (prompts_dir / "PERSONA.md").write_text("persona", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            load_identity(prompts_dir)

    def test_missing_persona_raises(self, prompts_dir: Path) -> None:
        (prompts_dir / "CONSTITUTION.md").write_text("constitution", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            load_identity(prompts_dir)


# --- load_instructions ---


class TestLoadInstructions:
    def test_pr_review_mode(self, full_chain_dir: Path) -> None:
        result = load_instructions(full_chain_dir, mode="pr_review")
        assert isinstance(result, list)
        expected = len(MODE_CHAINS["pr_review"]) + len(SHARED_PROMPTS) + len(CHAIN_SUFFIX)
        assert len(result) == expected

    def test_instructions_content_matches_files(self, full_chain_dir: Path) -> None:
        result = load_instructions(full_chain_dir, mode="pr_review")
        for i, filename in enumerate(MODE_CHAINS["pr_review"]):
            assert f"# {filename}" in result[i]

    def test_unknown_mode_raises(self, full_chain_dir: Path) -> None:
        with pytest.raises(ValueError, match="Unknown review mode"):
            load_instructions(full_chain_dir, mode="nonexistent_mode")

    def test_unknown_mode_lists_available(self, full_chain_dir: Path) -> None:
        with pytest.raises(ValueError, match="pr_review"):
            load_instructions(full_chain_dir, mode="bad")

    def test_default_mode_is_pr_review(self, full_chain_dir: Path) -> None:
        result = load_instructions(full_chain_dir)
        expected = len(MODE_CHAINS["pr_review"]) + len(SHARED_PROMPTS) + len(CHAIN_SUFFIX)
        assert len(result) == expected


# --- MODE_CHAINS structure ---


class TestModeChains:
    def test_all_modes_exist(self) -> None:
        expected = {
            "pr_review",
            "security_audit",
            "governance_check",
            "surprise_audit",
            "cli",
            "github_app",
        }
        assert set(MODE_CHAINS.keys()) == expected

    def test_all_chains_start_with_system_core(self) -> None:
        for mode, chain in MODE_CHAINS.items():
            assert chain[0] == "system-core.md", f"{mode} chain doesn't start with system-core.md"

    def test_no_chain_contains_suffix_files(self) -> None:
        for mode, chain in MODE_CHAINS.items():
            assert "output-schema.md" not in chain, f"{mode} contains output-schema.md"
            assert "scoring-rubric.md" not in chain, f"{mode} contains scoring-rubric.md"

    def test_identity_files_are_constitution_and_persona(self) -> None:
        assert IDENTITY_FILES == ["CONSTITUTION.md", "PERSONA.md"]


# --- SHARED_PROMPTS and CHAIN_SUFFIX ---


class TestSharedPrompts:
    """Tests for SHARED_PROMPTS and CHAIN_SUFFIX constants."""

    def test_shared_prompts_has_eight_files(self) -> None:
        assert len(SHARED_PROMPTS) == 8

    def test_chain_suffix_is_scoring_then_output(self) -> None:
        assert CHAIN_SUFFIX == ["scoring-rubric.md", "output-schema.md"]

    def test_shared_prompts_not_in_mode_chains(self) -> None:
        """Shared prompts should not appear in any MODE_CHAINS value."""
        for mode, chain in MODE_CHAINS.items():
            for shared in SHARED_PROMPTS:
                assert shared not in chain, (
                    f"{shared} appears in MODE_CHAINS[{mode!r}] — should be in SHARED_PROMPTS only"
                )

    def test_chain_suffix_not_in_mode_chains(self) -> None:
        """CHAIN_SUFFIX files should not appear in any MODE_CHAINS value."""
        for mode, chain in MODE_CHAINS.items():
            for suffix in CHAIN_SUFFIX:
                assert suffix not in chain, (
                    f"{suffix} appears in MODE_CHAINS[{mode!r}] — should be in CHAIN_SUFFIX only"
                )

    def test_all_shared_prompt_files_exist(self) -> None:
        """Every file in SHARED_PROMPTS must exist in prompts_data/."""
        prompts_dir = Path(__file__).resolve().parent.parent / "src" / "grippy" / "prompts_data"
        for filename in SHARED_PROMPTS:
            path = prompts_dir / filename
            assert path.exists(), f"SHARED_PROMPTS file missing: {path}"

    def test_all_chain_suffix_files_exist(self) -> None:
        """Every file in CHAIN_SUFFIX must exist in prompts_data/."""
        prompts_dir = Path(__file__).resolve().parent.parent / "src" / "grippy" / "prompts_data"
        for filename in CHAIN_SUFFIX:
            path = prompts_dir / filename
            assert path.exists(), f"CHAIN_SUFFIX file missing: {path}"


# --- Composition order ---


class TestCompositionOrder:
    """Tests that load_instructions() composes layers correctly."""

    def test_chain_starts_with_system_core(self, full_chain_dir: Path) -> None:
        result = load_instructions(full_chain_dir, mode="pr_review")
        assert "# system-core.md" in result[0]

    def test_chain_ends_with_output_schema(self, full_chain_dir: Path) -> None:
        result = load_instructions(full_chain_dir, mode="pr_review")
        assert "# output-schema.md" in result[-1]

    def test_scoring_rubric_is_second_to_last(self, full_chain_dir: Path) -> None:
        result = load_instructions(full_chain_dir, mode="pr_review")
        assert "# scoring-rubric.md" in result[-2]

    def test_chain_length_is_mode_plus_shared_plus_suffix(self, full_chain_dir: Path) -> None:
        for mode in MODE_CHAINS:
            result = load_instructions(full_chain_dir, mode=mode)
            expected = len(MODE_CHAINS[mode]) + len(SHARED_PROMPTS) + len(CHAIN_SUFFIX)
            assert len(result) == expected, (
                f"Mode {mode!r}: expected {expected} instructions, got {len(result)}"
            )

    def test_shared_prompts_appear_in_every_mode(self, full_chain_dir: Path) -> None:
        for mode in MODE_CHAINS:
            result = load_instructions(full_chain_dir, mode=mode)
            joined = "\n".join(result)
            for filename in SHARED_PROMPTS:
                assert f"# {filename}" in joined, (
                    f"SHARED_PROMPTS file {filename} missing from mode {mode!r}"
                )

    def test_mode_prompt_appears_second(self, full_chain_dir: Path) -> None:
        """The mode-specific prompt is the second instruction."""
        result = load_instructions(full_chain_dir, mode="pr_review")
        assert "# pr-review.md" in result[1]
