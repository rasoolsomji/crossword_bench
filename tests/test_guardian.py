import html
import json

import pytest

from crossword_bench.guardian import parse_puzzle_page, puzzle_to_samples


def entry(id_, clue, solution, group=None):
    number, direction = id_.split("-")
    return {
        "id": id_,
        "number": int(number),
        "direction": direction,
        "clue": clue,
        "solution": solution,
        "group": group or [id_],
    }


def puzzle(entries, solution_available=True):
    return {
        "id": "crosswords/cryptic/1",
        "number": 1,
        "date": 1794441600000,
        "creator": {"name": "Setter"},
        "solutionAvailable": solution_available,
        "entries": entries,
    }


def test_single_and_linked_entries():
    group = ["5-across", "2-down"]
    samples = puzzle_to_samples(
        puzzle(
            [
                entry("1-across", "Confused <i>lemon</i> is a fruit&nbsp;(5)", "MELON"),
                entry("5-across", "Improved, in favour of the gambler (3,3,6)", "FORTHE", group),
                entry("2-down", "See 5 across", "BETTER", group),
            ]
        )
    )
    assert [s["id"] for s in samples] == ["guardian-cryptic-1-1-across", "guardian-cryptic-1-5-across"]
    assert samples[0]["input"] == "Confused lemon is a fruit (5)"
    assert samples[0]["metadata"]["date"] == "2026-11-12"
    assert samples[1]["target"] == "FORTHEBETTER"


def test_cross_reference_flag_and_enumeration_check():
    samples = puzzle_to_samples(
        puzzle(
            [
                entry("1-across", "Partner of 7 down, perhaps (4)", "JILL"),
                entry("3-across", "Wrong length (4)", "TOOLONG"),
            ]
        )
    )
    assert len(samples) == 1
    assert samples[0]["metadata"]["cross_reference"] is True


def test_unreleased_solutions_rejected():
    with pytest.raises(ValueError):
        puzzle_to_samples(puzzle([entry("1-across", "Clue (5)", "")], solution_available=False))


def test_parse_puzzle_page():
    props = html.escape(json.dumps({"data": puzzle([entry("1-across", "Clue (5)", "MELON")])}))
    page = f'<html><gu-island name="CrosswordComponent" priority="critical" props="{props}"></gu-island></html>'
    assert parse_puzzle_page(page)["number"] == 1
