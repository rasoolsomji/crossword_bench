import pytest

from crossword_bench.scorer import extract_answer, normalize


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
