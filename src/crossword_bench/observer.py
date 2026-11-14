"""Fetch the Observer's barred cryptics, Azed and Gemelo, for the live track.

A puzzle article on observer.co.uk carries only a puzzle UUID. The puzzle
itself is a Sticky Puzzles bundle on the Observer's content API, whose
data.json holds the clues and the grid layout. Both series are prize
puzzles, so until the solution is released data.json has only an MD5 hash
of it. The solution later appears in full in the puzzle's own data.json,
and the next puzzle in the series carries it as its previous solution,
whichever comes first. Either is checked against the hash before use.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from crossword_bench.guardian import _get, clean_clue, refers_to_other_entry

SITE = "https://observer.co.uk"
API = "https://content-api.slowdownwiseup.co.uk/api/mobile/v1"
SERIES = ("azed", "gemelo")
DEFAULT_OUT = Path(__file__).parent.parent.parent / "data" / "live" / "observer"
UK = ZoneInfo("Europe/London")

# The article's page data is embedded as an escaped JSON string, so the
# quotes may or may not be backslashed.
_PUZZLE_UUID = re.compile(r'\\?"type\\?":\\?"puzzle\\?",\\?"uuid\\?":\\?"([0-9a-f-]{36})')


def article_slugs(series: str) -> dict[int, str]:
    """Article slugs by puzzle number, from the series' topic pages.

    The topic page lists the newest puzzles and links to a longer listing
    (/topics/gemelo/40, then /60, ...); those links are followed until
    none is left.
    """
    article = re.compile(rf'href="/puzzles/{series}/article/({series}-no-(\d+)[^"/]*)"')
    more = re.compile(rf'href="/topics/{series}/(\d+)"')
    slugs: dict[int, str] = {}
    url, visited = f"{SITE}/topics/{series}", set()
    while url and url not in visited:
        visited.add(url)
        page = _get(url)
        found = {int(number): slug for slug, number in article.findall(page)}
        new = found.keys() - slugs.keys()
        slugs.update(found)
        longer = [int(n) for n in more.findall(page)]
        url = f"{SITE}/topics/{series}/{max(longer)}" if longer and new else None
    return slugs


def puzzle_uuid(article_page: str) -> str:
    match = _PUZZLE_UUID.search(article_page)
    if not match:
        raise ValueError("No puzzle found in the article")
    return match.group(1)


def fetch_puzzle(series: str, slug: str) -> tuple[str, dict]:
    """The article URL and the puzzle's data.json."""
    url = f"{SITE}/puzzles/{series}/article/{slug}"
    uuid = puzzle_uuid(_get(url))
    bundle = json.loads(_get(f"{API}/puzzle-data/{uuid}/"))
    return url, json.loads(_get(API + bundle["files"]["data.json"]))


def puzzle_number(puzzle: dict) -> int:
    return int(puzzle["meta"]["number"])


def published_date(puzzle: dict) -> date:
    return datetime.strptime(puzzle["copy"]["date-publish"], "%A, %d %B %Y").date()


def solution(puzzle: dict, following: dict | None = None) -> str | None:
    """The puzzle's solution grid as a row-major string, once released.

    Taken from the puzzle itself or from `following`, the next puzzle in
    the series. Returns None while neither has it.
    """
    settings = puzzle["copy"]["settings"]
    candidates = [settings.get("solution")]
    if following:
        previous = following["copy"]["settings"]
        if re.sub(r"\D", "", previous.get("previous_title", "")) == str(puzzle_number(puzzle)):
            candidates.append(previous.get("previous_solution"))
    expected = settings.get("solution_hashed")
    for candidate in filter(None, candidates):
        if expected and hashlib.md5(candidate.encode()).hexdigest() != expected:
            raise ValueError("Published solution does not match the puzzle's solution hash")
        return candidate
    return None


def _span(value: str | int) -> range:
    first, _, last = str(value).partition("-")
    return range(int(first), int(last or first) + 1)


def enumerated_length(enumeration: str) -> int | None:
    """Letters in an enumeration as the Observer gives it.

    Forms seen: "12", "12, 5 words", "4,8", "2-5", "8, apostrophe" and
    "7, 1 word or 2". Word counts and anything after "or" are not lengths.
    """
    lengths = re.sub(r"\d+\s*words?\b|\bor\b.*", "", enumeration)
    return sum(int(n) for n in re.findall(r"\d+", lengths)) or None


def split_enumeration(text: str, printed: str) -> tuple[str, str]:
    """Move an enumeration written into the clue text into the enumeration.

    A few clues end with their own, either in full ("(6, 2 words)" where
    the format says "6") or as a bare word count ("(3 words)").
    """
    match = re.search(r"\s*\(([^()]*\d[^()]*)\)$", text)
    if not match:
        return text, printed
    inner = match.group(1).strip()
    text = text[: match.start()]
    if enumerated_length(inner):
        return text, inner
    if not printed or "word" in printed:
        return text, printed or inner
    return text, f"{printed}, {inner}"


def require_plain(puzzle: dict) -> None:
    """Refuse special puzzles, whose preamble changes what a clue means.

    Some only constrain how clues are written and could be posed, but
    others have misprints, letters to drop, or entries that differ from
    the answers. Azed's clue-writing competitions count as special too:
    the competition word gets a bare definition, which the data rarely
    marks with its asterisk.
    """
    description = " ".join((puzzle["copy"].get("description") or "").split())
    if description not in ("", "Plain"):
        raise ValueError(f"special puzzle: {description[:100]}{'...' if len(description) > 100 else ''}")


def puzzle_to_samples(puzzle: dict, grid: str, url: str) -> list[dict]:
    """Convert a plain Observer puzzle into Inspect samples, one per clue.

    `grid` is the solution from `solution()`. Clues are posed with the
    enumeration as the paper prints it, e.g. "(12, 5 words)". Clues that
    refer to another entry are skipped.
    """
    require_plain(puzzle)
    copy = puzzle["copy"]
    kind = puzzle["meta"]["variant"]
    cols, rows = int(copy["gridsize"]["cols"]), int(copy["gridsize"]["rows"])
    if len(grid) != cols * rows:
        raise ValueError(f"Solution has {len(grid)} letters for a {cols}x{rows} grid")

    number = puzzle_number(puzzle)
    cells = {word["id"]: [(x, y) for y in _span(word["y"]) for x in _span(word["x"])] for word in copy["words"]}
    samples = []
    for group in copy["clues"]:
        direction = group["title"].lower()
        for clue in group["clues"]:
            ref = f"{clue['number']}-{direction}"
            text, enumeration = split_enumeration(
                clean_clue(clue.get("clue") or ""), clean_clue(clue.get("format") or "")
            )
            answer = "".join(grid[(y - 1) * cols + (x - 1)] for x, y in cells.get(clue["word"], []))
            if not text or not enumeration:
                print(f"  skipping {ref}: missing clue or enumeration", file=sys.stderr)
                continue
            if text.startswith("*"):
                print(f"  skipping {ref}: competition word, given only a definition: {text}", file=sys.stderr)
                continue
            if enumerated_length(enumeration) != len(answer) or not re.fullmatch(r"[A-Z]+", answer):
                print(f"  skipping {ref}: enumeration does not match solution", file=sys.stderr)
                continue
            if refers_to_other_entry(text):
                print(f"  skipping {ref}: refers to another entry: {text}", file=sys.stderr)
                continue
            samples.append(
                {
                    "id": f"observer-{kind.lower()}-{number}-{ref}",
                    "input": f"{text} ({enumeration})",
                    "target": answer,
                    "metadata": {
                        "source": f"Observer {kind}",
                        "puzzle": number,
                        "date": published_date(puzzle).isoformat(),
                        # The data names no setter; Azed is itself the setter's pseudonym.
                        "setter": copy.get("setter") or copy.get("byline") or kind,
                        "direction": direction,
                        "number": clue["number"],
                        "url": url,
                    },
                }
            )
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--series", nargs="+", choices=SERIES, default=list(SERIES))
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="Earliest publication date (YYYY-MM-DD). Default: six weeks ago, as solutions "
        "come out weeks after publication.",
    )
    parser.add_argument("--until", type=date.fromisoformat, help="Latest publication date. Default: today.")
    parser.add_argument("--numbers", type=int, nargs="+", help="Fetch these puzzle numbers of one --series.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.numbers and len(args.series) != 1:
        parser.error("--numbers needs exactly one --series")

    today = datetime.now(UK).date()
    since, until = args.since or today - timedelta(weeks=6), args.until or today
    args.out.mkdir(parents=True, exist_ok=True)

    for series in args.series:
        slugs = article_slugs(series)
        loaded: dict[int, tuple[str, dict] | None] = {}

        def load(number: int) -> tuple[str, dict] | None:
            if number not in loaded:
                loaded[number] = fetch_puzzle(series, slugs[number]) if number in slugs else None
            return loaded[number]

        for number in args.numbers or sorted(slugs, reverse=True):
            name = f"{series} {number}"
            try:
                fetched = load(number)
                if fetched is None:
                    print(f"{name}: not listed on {SITE}/topics/{series}", file=sys.stderr)
                    continue
                url, puzzle = fetched
                published = published_date(puzzle)
                if not args.numbers:
                    if published > until:
                        continue
                    if published < since:
                        break
                require_plain(puzzle)
                following = load(number + 1)
                grid = solution(puzzle, following[1] if following else None)
                if grid is None:
                    print(f"{name} ({published}): solution not yet released", file=sys.stderr)
                    continue
                samples = puzzle_to_samples(puzzle, grid, url)
            except (ValueError, KeyError, OSError) as error:
                print(f"{name}: skipped: {error}", file=sys.stderr)
                continue
            path = args.out / f"{published.isoformat()}-{series}-{number}.json"
            path.write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
            print(f"{name} ({published}): {len(samples)} clues -> {path}")


if __name__ == "__main__":
    main()
