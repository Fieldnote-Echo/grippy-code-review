# SPDX-License-Identifier: MIT
"""Structured output retry wrapper for Grippy reviews.

Parses agent output into GrippyReview, retrying with validation error
feedback when the model produces malformed JSON or schema violations.
Native json_schema path first — no Instructor dependency.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from grippy.schema import GrippyReview


class ReviewParseError(Exception):
    """Raised when all retry attempts fail to produce a valid GrippyReview."""

    def __init__(self, attempts: int, last_raw: str, errors: list[str]) -> None:
        self.attempts = attempts
        self.last_raw = last_raw
        self.errors = errors
        super().__init__(
            f"Failed to parse GrippyReview after {attempts} attempts. "
            f"Last raw output: ({len(last_raw)} chars, redacted). "
            f"Errors: {'; '.join(errors[-3:])}"
        )


def _safe_error_summary(e: ValidationError) -> str:
    """Extract only field paths and error type codes from a ValidationError.

    Never echoes raw values — prevents attacker-controlled PR content from
    being injected into retry prompts as untagged instructions.
    """
    parts: list[str] = []
    for err in e.errors():
        loc = ".".join(str(loc) for loc in err["loc"])
        parts.append(f"{loc}: {err['type']}")
    return "; ".join(parts)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_response(content: Any) -> GrippyReview:
    """Parse agent response content into GrippyReview.

    Handles: GrippyReview instance, dict, JSON string, markdown-fenced JSON.
    Raises ValueError or ValidationError on failure.
    """
    if isinstance(content, GrippyReview):
        return content

    if content is None:
        msg = "Agent returned None"
        raise ValueError(msg)

    if isinstance(content, dict):
        return GrippyReview.model_validate(content)

    if isinstance(content, str):
        text = content.strip()
        if not text:
            msg = "Agent returned empty string"
            raise ValueError(msg)
        text = _strip_markdown_fences(text)
        data = json.loads(text)
        return GrippyReview.model_validate(data)

    msg = f"Unexpected response type: {type(content).__name__}"
    raise TypeError(msg)


def _validate_rule_coverage(
    review: GrippyReview,
    expected_rule_counts: dict[str, int],
) -> list[str]:
    """Return rule_ids with insufficient findings.

    Validates that the LLM produced at least as many findings per rule_id
    as the deterministic engine detected. Prevents silent dropping of
    multiple findings from the same rule (e.g. several leaked secrets).
    """
    found_counts = Counter(f.rule_id for f in review.findings if f.rule_id)
    missing: list[str] = []
    for rule_id, expected in sorted(expected_rule_counts.items()):
        found = found_counts.get(rule_id, 0)
        if found < expected:
            missing.append(f"{rule_id} (expected {expected}, got {found})")
    return missing


def run_review(
    agent: Any,
    message: str,
    *,
    max_retries: int = 3,
    on_validation_error: Callable[[int, Exception], None] | None = None,
    expected_rule_counts: dict[str, int] | None = None,
) -> GrippyReview:
    """Run a review with structured output validation and retry.

    Args:
        agent: Agno Agent instance (or mock with .run() method).
        message: The user message (PR context) to send.
        max_retries: Number of retries after the initial attempt. 0 = no retries.
        on_validation_error: Optional callback(attempt_number, error) on each failure.

    Returns:
        Validated GrippyReview.

    Raises:
        ReviewParseError: After exhausting all attempts.
    """
    errors: list[str] = []
    last_raw = ""
    current_message = message

    for attempt in range(1, max_retries + 2):  # +2 because range is exclusive and we start at 1
        response = agent.run(current_message)
        content = response.content
        last_raw = str(content)[:2000] if content is not None else "<None>"

        try:
            review = _parse_response(content)
            # Post-parse rule coverage validation
            if expected_rule_counts:
                missing = _validate_rule_coverage(review, expected_rule_counts)
                if missing:
                    error_str = f"Missing rule findings: {', '.join(missing)}"
                    errors.append(f"Attempt {attempt}: {error_str}")
                    if attempt <= max_retries:
                        current_message = (
                            f"Your output is missing findings for these rule-detected issues: "
                            f"{', '.join(missing)}. "
                            f"Every rule finding MUST appear with its rule_id set."
                        )
                        continue
                    # Final attempt still missing — warn but return what we have
                    import warnings

                    warnings.warn(
                        f"Rule coverage incomplete after {attempt} attempts: "
                        f"missing {', '.join(missing)}",
                        stacklevel=2,
                    )
            return review
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as e:
            error_str = str(e)
            errors.append(f"Attempt {attempt}: {error_str}")

            if on_validation_error is not None:
                on_validation_error(attempt, e)

            if attempt <= max_retries:
                if isinstance(e, ValidationError):
                    safe_summary = _safe_error_summary(e)
                elif isinstance(e, json.JSONDecodeError):
                    safe_summary = "JSON decode error"
                elif isinstance(e, TypeError):
                    safe_summary = "Unexpected response type"
                else:
                    safe_summary = "Value error in response"

                current_message = (
                    f"Your previous output failed validation. "
                    f"Error: {safe_summary}\n\n"
                    f"Please fix the errors and output a valid JSON object "
                    f"matching the GrippyReview schema. Output ONLY the JSON."
                )

    raise ReviewParseError(
        attempts=max_retries + 1,
        last_raw=last_raw,
        errors=errors,
    )
