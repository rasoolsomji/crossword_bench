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


def normalize(text: str) -> str:
    """Normalize answer for comparison: drop a trailing enumeration the model
    may have echoed (e.g. 'FOR THE BETTER (3,3,6)'), then keep letters/digits only."""
    text = re.sub(r"\(\d+(?:[,-]\d+)*\)\s*$", "", text.strip())
    return re.sub(r"[^A-Za-z0-9]", "", text.upper())


def extract_answer(text: str) -> str | None:
    """Extract the answer from model output.

    Looks for 'ANSWER: ...' pattern (last occurrence), falling back
    to the last all-caps token.
    """
    matches = re.findall(r"ANSWER:\s*(.+)", text, re.IGNORECASE)
    if matches:
        return matches[-1].strip().strip("*\"'`")

    for line in reversed(text.strip().splitlines()):
        line = line.strip().strip("*\"'`")
        if line and line.isupper() and len(line) <= 30:
            return line

    return None


@scorer(metrics=[accuracy(), stderr()])
def cryptic_scorer():
    """Score cryptic crossword answers with normalization."""

    async def score(state: TaskState, target: Target) -> Score:
        output = state.output.completion
        extracted = extract_answer(output)

        if extracted is None:
            return Score(
                value="I",
                answer=None,
                explanation="Could not extract answer from model output.",
                metadata={
                    "clue_type": (state.metadata or {}).get("clue_type", "unknown"),
                },
            )

        is_correct = normalize(extracted) == normalize(target.text)

        return Score(
            value="C" if is_correct else "I",
            answer=extracted,
            explanation=f"Expected '{target.text}', got '{extracted}'",
            metadata={
                "extracted_answer": extracted,
                "clue_type": (state.metadata or {}).get("clue_type", "unknown"),
            },
        )

    return score
