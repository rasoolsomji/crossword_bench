"""Fetch Guardian cryptic crosswords for the live track.

Each puzzle page embeds the full puzzle (clues and, once released,
solutions) as JSON props on a <gu-island name="CrosswordComponent">.
"""

import argparse
import html
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://www.theguardian.com"
SERIES_URL = f"{BASE_URL}/crosswords/series/cryptic"
DEFAULT_OUT = Path(__file__).parent.parent.parent / "data" / "live" / "guardian"

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


def clean_clue(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", raw))).strip()


def puzzle_to_samples(puzzle: dict) -> list[dict]:
    """Convert a Guardian puzzle into Inspect samples, one per clue.

    Linked entries ("See 12") are folded into the clue that carries the
    text, with the solution joined across the group's entries.
    """
    if not puzzle.get("solutionAvailable"):
        raise ValueError(f"Solutions not yet available for {puzzle.get('id')}")

    number = puzzle["number"]
    published = datetime.fromtimestamp(puzzle["date"] / 1000, tz=timezone.utc).date()
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
        samples.append(
            {
                "id": f"guardian-cryptic-{number}-{entry['id']}",
                "input": clue,
                "target": solution,
                "metadata": {
                    "source": "Guardian cryptic",
                    "puzzle": number,
                    "date": published.isoformat(),
                    "setter": setter,
                    "direction": entry["direction"],
                    "number": entry["number"],
                    "url": f"{BASE_URL}/{puzzle['id']}",
                    # Clues that point at other entries can't be solved in isolation.
                    "cross_reference": bool(re.search(r"\d", clue[: enumeration.start()])),
                },
            }
        )
    return samples


def fetch_puzzle(number: int) -> dict:
    return parse_puzzle_page(_get(f"{BASE_URL}/crosswords/cryptic/{number}"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=date.fromisoformat, help="Earliest publication date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--until", type=date.fromisoformat, help="Latest publication date. Default: today.")
    parser.add_argument("--numbers", type=int, nargs="+", help="Fetch these puzzle numbers instead of a date range.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    today = datetime.now(timezone.utc).date()
    since, until = args.since or today, args.until or today
    args.out.mkdir(parents=True, exist_ok=True)

    for number in args.numbers or recent_puzzle_numbers():
        puzzle = fetch_puzzle(number)
        published = datetime.fromtimestamp(puzzle["date"] / 1000, tz=timezone.utc).date()
        if not args.numbers:
            if published > until:
                continue
            if published < since:
                break
        try:
            samples = puzzle_to_samples(puzzle)
        except ValueError as error:
            print(f"{number} ({published}): {error}", file=sys.stderr)
            continue
        path = args.out / f"{published.isoformat()}-cryptic-{number}.json"
        path.write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
        print(f"{number} ({published}): {len(samples)} clues -> {path}")


if __name__ == "__main__":
    main()
