import pytest

from crossword_bench.scorer import classify_outcome, extract_answer, normalize


@pytest.mark.parametrize(
    "output, expected",
    [
        ("ANSWER: MELON", "MELON"),
        ("thinking...\nANSWER: melon", "MELON"),
        ("**ANSWER:** MELON", "MELON"),
        ("**ANSWER: MELON**", "MELON"),
        ("Answer: `MELON`", "MELON"),
        ("ANSWER: MELON (5)", "MELON"),
        ("ANSWER: MELON (anagram of LEMON)", "MELON"),
        ("ANSWER: MELON.", "MELON"),
        ("ANSWER: MELON - an anagram of lemon", "MELON"),
        ("ANSWER: FOR THE BETTER (3,3,6)", "FORTHEBETTER"),
        ("ANSWER: WELL-OFF", "WELLOFF"),
        ("ANSWER: ROCK 'N' ROLL", "ROCKNROLL"),
        ("ANSWER: EXAMPLE\nactually no\nANSWER: MELON", "MELON"),
        ("The format is ANSWER: <word>.\nANSWER: MELON", "MELON"),
        ("I think it's this:\n\nMELON", "MELON"),
        ("I think it's this:\n\n**MELON**", "MELON"),
        ("MELON - an anagram of lemon", "MELON"),
        ("MELON: an anagram of lemon (5)", "MELON"),
        ("FOR THE BETTER?", "FORTHEBETTER"),
        ("MELON\n\nQuietly gives P; LEMON is the fodder.", "MELON"),
        ("HERMIT\n\nHER (female) + M (top of mountain) + IT; a hermit is cold.", "HERMIT"),
    ],
)
def test_extract_and_normalize(output, expected):
    extracted = extract_answer(output)
    assert extracted is not None
    assert normalize(extracted) == expected


@pytest.mark.parametrize("output", ["", "I don't know.", "ANSWER:", "ANSWER: ???"])
def test_no_answer(output):
    assert extract_answer(output) is None


def test_normalize_keeps_only_alphanumerics():
    assert normalize("  d'Artagnan-style! ") == "DARTAGNANSTYLE"


@pytest.mark.parametrize(
    "answer, target, kwargs, expected",
    [
        ("melon", "MELON", {}, "correct"),
        ("FOR THE BETTER", "FORTHEBETTER", {}, "correct"),
        ("BANNED", "BAND", {}, "wrong_length"),
        ("BARRICADED", "BARRACKED", {}, "wrong_length"),
        ("RELEARNT", "RELEARNS", {}, "near_miss"),
        ("BIND", "BAND", {}, "wrong_answer"),
        ("LEMON", "MELON", {}, "wrong_answer"),
        (None, "MELON", {}, "no_answer"),
        ("UNKNOWN", "MARTINI", {}, "no_answer"),
        ("N/A", "MELON", {}, "no_answer"),
        ("UNKNOWN", "UNKNOWN", {}, "correct"),
        (None, "MELON", {"stop_reason": "max_tokens"}, "truncated"),
        (None, "MELON", {"error": "Turn interrupted"}, "interrupted"),
    ],
)
def test_classify_outcome(answer, target, kwargs, expected):
    assert classify_outcome(answer, target, **kwargs) == expected
