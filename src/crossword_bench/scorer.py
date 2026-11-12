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


def _bare_line(line: str) -> str:
    """A line with only wrapping, end punctuation and an enumeration removed."""
    text = line.strip(_WRAPPING)
    text = re.sub(r"\s*\(\s*\d+(?:\s*[,-]\s*\d+)*\s*\)$", "", text)
    return text.strip(_WRAPPING + ".,?!")


def extract_answer(text: str) -> str | None:
    """Extract the answer from model output.

    Uses the last 'ANSWER: ...' line. Failing that, the last line that is
    nothing but a short all-caps answer, then the last line that starts
    with one ('MELON - an anagram of lemon').
    """
    matches = _ANSWER_LINE.findall(text)
    for raw in reversed(matches):
        candidate = _clean_candidate(raw)
        if normalize(candidate):
            return candidate
    if matches or re.search(r"ANSWER\W*$", text.strip(), re.IGNORECASE):
        return None

    leading = []
    for line in reversed(text.strip().splitlines()):
        candidate = _clean_candidate(line)
        if candidate and candidate.isupper() and len(candidate) <= 40:
            # A wordplay line such as 'HER (female) + M + IT' also starts
            # with capitals, so a line holding only the answer wins.
            if candidate == _bare_line(line):
                return candidate
            leading.append(candidate)

    return leading[0] if leading else None


# Normalized placeholders a model writes on the ANSWER line when it gives
# up. They count as no answer unless they happen to be the target.
GIVE_UPS = {"UNKNOWN", "UNSURE", "UNSOLVED", "NOANSWER", "NA", "IDK", "DONTKNOW", "IDONTKNOW"}

OUTCOMES = {
    "correct": "Correct",
    "near_miss": "Near miss",
    "wrong_answer": "Wrong answer",
    "wrong_length": "Wrong length",
    "no_answer": "No answer",
    "truncated": "Ran out of tokens",
    "interrupted": "Used a tool",
}


def classify_outcome(
    answer: str | None,
    target: str,
    stop_reason: str | None = None,
    error: str | None = None,
) -> str:
    """Classify a response into one of OUTCOMES.

    A near miss has the right length and differs from the target in at
    most two letters (answers of six letters or more only, since two
    letters of a short word is a different word).
    """
    if answer is None or not normalize(answer):
        if error:
            return "interrupted"
        return "truncated" if stop_reason in ("max_tokens", "model_length") else "no_answer"
    got, want = normalize(answer), normalize(target)
    if got == want:
        return "correct"
    if got in GIVE_UPS:
        return "no_answer"
    if len(got) != len(want):
        return "wrong_length"
    if len(want) >= 6 and sum(a != b for a, b in zip(got, want)) <= 2:
        return "near_miss"
    return "wrong_answer"


@scorer(metrics=[accuracy(), stderr()])
def cryptic_scorer():
    """Score cryptic crossword answers with normalization."""

    async def score(state: TaskState, target: Target) -> Score:
        clue_type = (state.metadata or {}).get("clue_type", "unknown")
        extracted = extract_answer(state.output.completion)
        outcome = classify_outcome(
            extracted, target.text, state.output.stop_reason, state.output.error
        )
        if extracted is None:
            explanation = state.output.error or "Could not extract answer from model output."
        else:
            explanation = f"Expected '{target.text}', got '{extracted}'"

        return Score(
            value="C" if outcome == "correct" else "I",
            answer=extracted,
            explanation=explanation,
            metadata={"clue_type": clue_type, "outcome": outcome},
        )

    return score
