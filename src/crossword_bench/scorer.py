"""Scorer for cryptic crossword benchmark."""

import re

from inspect_ai.scorer import (
    Score,
    Target,
    accuracy,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState

_ANSWER_LINE = re.compile(r"ANSWER\W*?[:=]\s*(.+)", re.IGNORECASE)
_WRAPPING = "*_\"'`“”‘’ \t"


def normalize(text: str) -> str:
    """Normalize answer for comparison: letters/digits only, uppercased."""
    return re.sub(r"[^A-Za-z0-9]", "", text.upper())


def _clean_candidate(text: str) -> str:
    """Trim markdown, quotes, and any trailing parenthetical or sentence the
    model appended after the answer (e.g. 'MELON (anagram of lemon).')."""
    text = text.strip(_WRAPPING)
    text = re.sub(r"\s*[(\[].*$", "", text)
    text = re.split(r"\s+[-–—]\s+|[.;:!?](?:\s|$)", text, maxsplit=1)[0]
    return text.strip(_WRAPPING + ".,")


def extract_answer(text: str) -> str | None:
    """Extract the answer from model output.

    Uses the last 'ANSWER: ...' line, falling back to the last short
    all-caps line.
    """
    matches = _ANSWER_LINE.findall(text)
    for raw in reversed(matches):
        candidate = _clean_candidate(raw)
        if normalize(candidate):
            return candidate
    if matches or re.search(r"ANSWER\W*$", text.strip(), re.IGNORECASE):
        return None

    for line in reversed(text.strip().splitlines()):
        candidate = _clean_candidate(line)
        if candidate and candidate.isupper() and len(candidate) <= 40:
            return candidate

    return None


@scorer(metrics=[accuracy(), stderr()])
def cryptic_scorer():
    """Score cryptic crossword answers with normalization."""

    async def score(state: TaskState, target: Target) -> Score:
        clue_type = (state.metadata or {}).get("clue_type", "unknown")
        extracted = extract_answer(state.output.completion)

        if extracted is None:
            return Score(
                value="I",
                answer=None,
                explanation=state.output.error or "Could not extract answer from model output.",
                metadata={
                    "clue_type": clue_type,
                    "failure": "interrupted" if state.output.error else "no_answer",
                },
            )

        got, want = normalize(extracted), normalize(target.text)
        is_correct = got == want
        failure = None
        if not is_correct:
            failure = "wrong_length" if len(got) != len(want) else "wrong_answer"

        return Score(
            value="C" if is_correct else "I",
            answer=extracted,
            explanation=f"Expected '{target.text}', got '{extracted}'",
            metadata={
                "extracted_answer": extracted,
                "clue_type": clue_type,
                "failure": failure,
            },
        )

    return score
