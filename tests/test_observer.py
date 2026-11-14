import hashlib

import pytest

from crossword_bench import observer

GRID = "MELTAREA"


def clue(word, number, text, format_):
    return {"word": word, "number": number, "clue": text, "format": format_, "length": 0}


def puzzle(across, down, description="Plain", number=7, settings=None):
    return {
        "meta": {"variant": "Azed", "number": str(number)},
        "copy": {
            "description": description,
            "setter": "",
            "byline": "",
            "date-publish": "Sunday, 01 November 2026",
            "gridsize": {"cols": "4", "rows": "2"},
            "settings": settings or {},
            "words": [
                {"id": 1, "x": "1-4", "y": "1"},
                {"id": 2, "x": "1-4", "y": "2"},
                {"id": 3, "x": "1", "y": "1-2"},
                {"id": 4, "x": "3", "y": "1-2"},
            ],
            "clues": [{"title": "Across", "clues": across}, {"title": "Down", "clues": down}],
        },
    }


def md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def test_answers_read_from_grid():
    samples = observer.puzzle_to_samples(
        puzzle(
            [clue(1, 1, "Thaw <i>slowly</i>&rsquo;s start", "4"), clue(2, 5, "Region (2 words)", "4")],
            [clue(3, 1, "Partner of 7 down", "2"), clue(4, 3, "* French article", "2")],
        ),
        GRID,
        "https://observer.co.uk/puzzles/azed/article/azed-no-7",
    )
    assert [s["id"] for s in samples] == ["observer-azed-7-1-across", "observer-azed-7-5-across"]
    assert [s["input"] for s in samples] == ["Thaw slowly’s start (4)", "Region (4, 2 words)"]
    assert [s["target"] for s in samples] == ["MELT", "AREA"]
    assert samples[0]["metadata"]["date"] == "2026-11-01"
    assert samples[0]["metadata"]["setter"] == "Azed"


def test_enumeration_that_does_not_fit_is_skipped():
    samples = observer.puzzle_to_samples(puzzle([clue(1, 1, "Thaw", "5")], [clue(4, 3, "Article", "2")]), GRID, "")
    assert [s["target"] for s in samples] == ["LE"]


@pytest.mark.parametrize(
    "enumeration, length",
    [
        ("12", 12),
        ("12, 5 words", 12),
        ("4,8", 12),
        ("2-5", 7),
        ("8, apostrophe", 8),
        ("11, 3 words, apostrophe", 11),
        ("7, 1 word or 2", 7),
        ("5 ,2 words", 5),
        ("12. 2 words", 12),
        ("", None),
    ],
)
def test_enumerated_length(enumeration, length):
    assert observer.enumerated_length(enumeration) == length


def test_clue_with_its_own_enumeration():
    assert observer.split_enumeration("Basically gold-loving (6, 2 words)", "6") == (
        "Basically gold-loving",
        "6, 2 words",
    )
    assert observer.split_enumeration("Let go of remote (2 words)", "8") == ("Let go of remote", "8, 2 words")
    assert observer.split_enumeration("Treat (2 words)", "8, 2 words") == ("Treat", "8, 2 words")
    assert observer.split_enumeration("Plain clue", "4") == ("Plain clue", "4")


def test_solution_from_puzzle_or_next_in_series():
    hashed = {"solution_hashed": md5(GRID)}
    assert observer.solution(puzzle([], [], settings={**hashed, "solution": GRID})) == GRID
    assert observer.solution(puzzle([], [], settings=hashed)) is None

    following = puzzle([], [], number=8, settings={"previous_title": "No. 7", "previous_solution": GRID})
    assert observer.solution(puzzle([], [], settings=hashed), following) == GRID

    other = puzzle([], [], number=9, settings={"previous_title": "No. 8", "previous_solution": GRID})
    assert observer.solution(puzzle([], [], settings=hashed), other) is None

    with pytest.raises(ValueError):
        observer.solution(puzzle([], [], settings={**hashed, "solution": "MELTAREZ"}))


def test_special_puzzles_refused():
    with pytest.raises(ValueError, match="special puzzle"):
        observer.puzzle_to_samples(puzzle([], [], description="Misprints: one letter in each clue"), GRID, "")
    assert observer.puzzle_to_samples(puzzle([], [], description=" "), GRID, "") == []


def test_puzzle_uuid_from_article_page():
    uuid = "7effe77f-6b3c-468f-9445-10371e04d0d7"
    page = f'self.__next_f.push([1,"[{{\\"type\\":\\"puzzle\\",\\"uuid\\":\\"{uuid}\\"}}]"])'
    assert observer.puzzle_uuid(page) == uuid
    with pytest.raises(ValueError):
        observer.puzzle_uuid("<html></html>")


def test_article_slugs_follow_longer_listings(monkeypatch):
    def link(slug):
        return f'<a href="/puzzles/azed/article/{slug}">'

    pages = {
        "/topics/azed": link("azed-no-3") + link("azed-no-2") + '<a href="/topics/azed/40">',
        "/topics/azed/40": link("azed-no-3") + link("azed-no-1-christmas-competition") + '<a href="/topics/azed/60">',
        "/topics/azed/60": link("azed-no-3") + '<a href="/topics/azed/80">',
    }
    fetched = []

    def fake_get(url):
        path = url.removeprefix(observer.SITE)
        fetched.append(path)
        return pages[path]

    monkeypatch.setattr(observer, "_get", fake_get)
    assert observer.article_slugs("azed") == {3: "azed-no-3", 2: "azed-no-2", 1: "azed-no-1-christmas-competition"}
    assert fetched == ["/topics/azed", "/topics/azed/40", "/topics/azed/60"]
