# SPDX-License-Identifier: MIT
"""Validation script — test whether Devstral Q4 holds Grippy's structured JSON output.

Usage:
    uv run python -m grippy.validate_q4 \
        --prompts-dir /path/to/grumpy \
        --base-url $GRIPPY_BASE_URL

Set GRIPPY_BASE_URL in .dev.vars (gitignored) or pass --base-url explicitly.
This is step 4 of the navi-bootstrap validation plan:
  engine correctness + Devstral reliability for local Grippy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from grippy.agent import create_reviewer, format_pr_context
from grippy.schema import GrippyReview

# Load .dev.vars if present (simple KEY=VALUE, no shell expansion)
_DEV_VARS_PATH = Path(__file__).resolve().parent.parent.parent / ".dev.vars"
if _DEV_VARS_PATH.is_file():
    for line in _DEV_VARS_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def get_self_bootstrap_diff() -> str:
    """Get the diff from the self-bootstrap commit (be7f371)."""
    result = subprocess.run(
        ["git", "diff", "be7f371^..be7f371"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Validate Devstral Q4 against Grippy schema")
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        required=True,
        help="Path to Grippy prompt files directory",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GRIPPY_BASE_URL", "http://localhost:1234/v1"),
        help="Devstral API endpoint (default: $GRIPPY_BASE_URL or localhost:1234)",
    )
    parser.add_argument(
        "--model-id",
        default=os.environ.get("GRIPPY_MODEL_ID", "devstral-small-2-24b-instruct-2512"),
        help="Model identifier (default: $GRIPPY_MODEL_ID or devstral-small-2-24b-instruct-2512)",
    )
    args = parser.parse_args()

    print("=== Grippy Q4 Validation ===\n")

    # 1. Load the review agent
    print(f"Loading Grippy agent (mode=pr_review, model={args.model_id})...")
    agent = create_reviewer(
        model_id=args.model_id,
        base_url=args.base_url,
        prompts_dir=args.prompts_dir,
        mode="pr_review",
    )
    print("  Agent created.\n")

    # 2. Get the self-bootstrap diff
    print("Fetching self-bootstrap diff (commit be7f371)...")
    diff = get_self_bootstrap_diff()
    print(f"  Diff loaded: {len(diff)} chars, {diff.count('diff --git')} files.\n")

    # 3. Format the PR context
    user_message = format_pr_context(
        title="feat: self-bootstrap — nboot apply on navi-bootstrap itself",
        author="bravo",
        branch="main → main (self-bootstrap)",
        description=(
            "Run nboot apply on the navi-bootstrap repo itself. "
            "Generates CI, pre-commit, dependabot, CLAUDE.md, and DEBT.md from base pack."
        ),
        diff=diff,
    )

    # 4. Send to Devstral
    print(f"Sending to Devstral at {args.base_url}...")
    print("  (this may take a while on Q4 with full prompt chain)\n")

    run_output = agent.run(user_message)

    # 5. Analyze the response
    print("=== Response received ===\n")

    raw_content = run_output.content
    print(f"Raw content type: {type(raw_content).__name__}")
    print(f"Raw content length: {len(str(raw_content))} chars\n")

    # Try to parse as GrippyReview
    try:
        if isinstance(raw_content, GrippyReview):
            review = raw_content
            print("Pydantic validation: PASSED (returned as model instance)\n")
        elif isinstance(raw_content, dict):
            review = GrippyReview.model_validate(raw_content)
            print("Pydantic validation: PASSED (parsed from dict)\n")
        elif isinstance(raw_content, str):
            data = json.loads(raw_content)
            review = GrippyReview.model_validate(data)
            print("Pydantic validation: PASSED (parsed from JSON string)\n")
        else:
            print(f"Unexpected content type: {type(raw_content)}")
            print(f"Content: {raw_content!r}")
            sys.exit(1)

        # Print summary
        print(f"  Audit type: {review.audit_type}")
        print(f"  Model: {review.model}")
        print(f"  Complexity tier: {review.pr.complexity_tier}")
        print(f"  Files reviewed: {review.scope.files_reviewed}/{review.scope.files_in_diff}")
        print(f"  Findings: {len(review.findings)}")
        for f in review.findings:
            print(
                f"    [{f.severity.value}] {f.title} ({f.file}:{f.line_start}) conf={f.confidence}"
            )
        print(f"  Score: {review.score.overall}/100")
        print(f"  Verdict: {review.verdict.status.value} — {review.verdict.summary}")
        print(f"  Tone: {review.personality.tone_register.value}")
        print(f"  Opening: {review.personality.opening_catchphrase}")
        print(f"  Closing: {review.personality.closing_line}")

        # Write full output for inspection
        output_path = Path("grippy-q4-output.json")
        output_path.write_text(
            json.dumps(review.model_dump(), indent=2, default=str), encoding="utf-8"
        )
        print(f"\n  Full output written to {output_path}")

        print("\n=== RESULT: Q4 holds structured JSON output. ===")

    except (json.JSONDecodeError, Exception) as e:
        print(f"VALIDATION FAILED: {e}\n")
        print("Raw output (first 2000 chars):")
        print(str(raw_content)[:2000])

        # Write raw output for debugging
        output_path = Path("grippy-q4-raw-output.txt")
        output_path.write_text(str(raw_content), encoding="utf-8")
        print(f"\nFull raw output written to {output_path}")

        print("\n=== RESULT: Q4 did NOT hold structured JSON output. ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
