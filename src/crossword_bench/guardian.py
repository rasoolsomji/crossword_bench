"""Fetch Guardian cryptic crosswords for the live track.

Each puzzle page embeds the full puzzle (clues and, once released,
solutions) as JSON props on a <gu-island name="CrosswordComponent">.
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_URL = "https://www.theguardian.com"
SERIES_URL = f"{BASE_URL}/crosswords/series/cryptic"
DEFAULT_OUT = Path(__file__).parent.parent.parent / "data" / "live" / "guardian"
# Puzzles are dated by the UK publication day, which is a day later than
# the UTC date for a puzzle stamped at midnight during British Summer Time.
UK = ZoneInfo("Europe/London")

_PROPS = re.compile(r'<gu-island[^>]*name="CrosswordComponent"[^>]*props="([^"]*)"')
_PUZZLE_LINK = re.compile(r'href="(?:https://www\.theguardian\.com)?/crosswords/cryptic/(\d+)"')
_ENUMERATION = re.compile(r"\s*\(([\d,\-\s]+)\)\s*$")
_TAG = re.compile(r"<[^>]+>")


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def recent_puzzle_numbers() -> list[int]:
    """Puzzle numbers linked from the series page, newest first."""
    return sorted({int(n) for n in _PUZZLE_LINK.findall(_get(SERIES_URL))}, reverse=True)


def parse_puzzle_page(page: str) -> dict:
    match = _PROPS.search(page)
    if not match:
        raise ValueError("No CrosswordComponent data found on page")
    props = json.loads(html.unescape(match.group(1)))
    data = props.get("data", props)
    if "entries" not in data:
        raise ValueError("Crossword data has no entries")
    return data


def published_date(puzzle: dict) -> date:
    return datetime.fromtimestamp(puzzle["date"] / 1000, tz=UK).date()


def clean_clue(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", raw))).strip()


def refers_to_other_entry(clue: str) -> bool:
    """Whether the clue has a number before its enumeration.

    That is usually a pointer to another entry ("a taste of 25"), whose
    answer a clue posed on its own doesn't have. It also catches a few
    fair clues ("1st of January"), which are dropped with the rest.
    """
    enumeration = _ENUMERATION.search(clue)
    return bool(re.search(r"\d", clue[: enumeration.start()] if enumeration else clue))


def puzzle_to_samples(puzzle: dict) -> list[dict]:
    """Convert a Guardian puzzle into Inspect samples, one per clue.

    Linked entries ("See 12") are folded into the clue that carries the
    text, with the solution joined across the group's entries. Clues that
    refer to another entry are skipped.
    """
    if not puzzle.get("solutionAvailable"):
        raise ValueError(f"Solutions not yet available for {puzzle.get('id')}")

    number = puzzle["number"]
    kind = puzzle.get("crosswordType", "cryptic")
    published = published_date(puzzle)
    setter = (puzzle.get("creator") or {}).get("name")
    by_id = {entry["id"]: entry for entry in puzzle["entries"]}

    samples = []
    for entry in puzzle["entries"]:
        group = entry.get("group") or [entry["id"]]
        if group[0] != entry["id"]:
            continue
        solution = "".join(by_id[member].get("solution") or "" for member in group)
        clue = clean_clue(entry["clue"])
        enumeration = _ENUMERATION.search(clue)
        if not solution or not enumeration:
            print(f"  skipping {entry['id']}: missing solution or enumeration", file=sys.stderr)
            continue
        lengths = [int(n) for n in re.findall(r"\d+", enumeration.group(1))]
        if sum(lengths) != len(solution):
            print(f"  skipping {entry['id']}: enumeration does not match solution", file=sys.stderr)
            continue
        if refers_to_other_entry(clue):
            print(f"  skipping {entry['id']}: refers to another entry: {clue}", file=sys.stderr)
            continue
        samples.append(
            {
                "id": f"guardian-{kind}-{number}-{entry['id']}",
                "input": clue,
                "target": solution,
                "metadata": {
                    "source": f"Guardian {kind}",
                    "puzzle": number,
                    "date": published.isoformat(),
                    "setter": setter,
                    "direction": entry["direction"],
                    "number": entry["number"],
                    "url": f"{BASE_URL}/{puzzle['id']}",
                },
            }
        )
    return samples


def fetch_puzzle(number: int) -> dict:
    # Saturday Prize puzzles share the cryptic numbering but live under their own path.
    try:
        return parse_puzzle_page(_get(f"{BASE_URL}/crosswords/cryptic/{number}"))
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        return parse_puzzle_page(_get(f"{BASE_URL}/crosswords/prize/{number}"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=date.fromisoformat, help="Earliest publication date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--until", type=date.fromisoformat, help="Latest publication date. Default: today.")
    parser.add_argument(
        "--numbers", type=int, nargs="+", help="Fetch these puzzle numbers (cryptic or Prize) instead of a date range."
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    today = datetime.now(UK).date()
    since, until = args.since or today, args.until or today
    args.out.mkdir(parents=True, exist_ok=True)

    reached_since = bool(args.numbers)
    for number in args.numbers or recent_puzzle_numbers():
        try:
            puzzle = fetch_puzzle(number)
        except (ValueError, OSError) as error:
            print(f"{number}: could not fetch: {error}", file=sys.stderr)
            continue
        published = published_date(puzzle)
        if not args.numbers:
            if published > until:
                continue
            if published < since:
                reached_since = True
                break
        try:
            samples = puzzle_to_samples(puzzle)
        except ValueError as error:
            print(f"{number} ({published}): {error}", file=sys.stderr)
            continue
        kind = puzzle.get("crosswordType", "cryptic")
        path = args.out / f"{published.isoformat()}-{kind}-{number}.json"
        path.write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
        print(f"{number} ({published}): {len(samples)} clues -> {path}")

    if not reached_since:
        print(
            f"Warning: the series page lists nothing older than {since}, so earlier "
            "puzzles may be missing; fetch them with --numbers.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
