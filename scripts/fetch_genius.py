"""Fetch a Guardian Genius puzzle's clues and answers via Fifteensquared.

Once a Genius competition closes the Guardian page holds only a grid image
and a print PDF (the entry form that carried the clues as text is
withdrawn), and it never shows the answers. Fifteensquared blogs each
Genius after its deadline in a table giving every clue beside its answer,
so both come from there. The post is cached where classify-clues looks
for it.

Genius puzzles often carry a gimmick that leaves some clues unsolvable on
their own (no definition, wordplay that skips a letter): drop those with
--skip. Check the clues against the print PDF before running models on
them, since this reads the blogger's transcription.

    uv run scripts/fetch_genius.py 280 --skip BECKER GODUNOV ...
"""

import argparse
import html
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

from crossword_bench.classify import BLOG_API, BLOG_CACHE
from crossword_bench.guardian import BASE_URL, _get, clean_clue

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_OUT = PROJECT_ROOT / "data" / "live" / "guardian-hard"
SERIES_URL = f"{BASE_URL}/crosswords/series/genius"
GENIUS_CATEGORY = 28  # Fifteensquared's "Guardian Genius"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_ANSWER = re.compile(r"^[A-Z][A-Z' -]*$")
_ENUMERATION = re.compile(r"\s*\(([\d,\-\s]+)\)\s*$")


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def find_article(number: int) -> tuple[str, str, str]:
    """URL, publication date and setter of the Guardian Genius page."""
    links = re.findall(rf'/crosswords/(\d{{4}}/[a-z]{{3}}/\d{{2}})/genius-crossword-no-{number}\b', _get(SERIES_URL))
    if not links:
        sys.exit(f"Genius No {number} is not linked from {SERIES_URL}")
    url = f"{BASE_URL}/crosswords/{links[0]}/genius-crossword-no-{number}"
    byline = re.search(r'"byline":"([^"]+)"', _get(url))
    published = datetime.strptime(links[0], "%Y/%b/%d").date()
    return url, published.isoformat(), byline.group(1) if byline else None


def find_blog_post(number: int) -> dict:
    query = urllib.parse.urlencode(
        {"categories": GENIUS_CATEGORY, "search": str(number), "_fields": "link,title,content"}
    )
    for post in json.loads(_get(f"{BLOG_API}?{query}")):
        title = html.unescape(post["title"]["rendered"])
        if re.search(rf"\b{number}\b", title):
            return {"url": post["link"], "title": title, "html": post["content"]["rendered"]}
    sys.exit(f"No Fifteensquared post found for Genius No {number}")


def clue_rows(post_html: str) -> list[tuple[str, str]]:
    """(clue, answer) pairs from the blog's table, in the order given."""
    rows = []
    for row in _ROW.findall(post_html):
        cells = _CELL.findall(row)
        answer = next((_text(c) for c in cells if _ANSWER.match(_text(c)) and len(_text(c)) > 1), None)
        clue_cell = next((c for c in cells if "color: blue" in c), None)
        if answer and clue_cell:
            # The clue is the italic line; the parsing follows it in the same cell.
            rows.append((clean_clue(clue_cell.split("</i>")[0]), answer))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int)
    parser.add_argument("--skip", nargs="*", default=[], help="Answers whose clues can't be solved on their own.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    url, published, setter = find_article(args.number)
    post = find_blog_post(args.number)
    rows = clue_rows(post["html"])
    if not rows:
        sys.exit(f"No clue table found in {post['url']}")
    unknown = set(args.skip) - {answer for _, answer in rows}
    if unknown:
        sys.exit(f"--skip names answers not in the blog: {sorted(unknown)}")

    samples = []
    for position, (clue, answer) in enumerate(rows, start=1):
        if answer in args.skip:
            continue
        target = re.sub(r"[^A-Z]", "", answer)
        enumeration = _ENUMERATION.search(clue)
        lengths = [int(n) for n in re.findall(r"\d+", enumeration.group(1))] if enumeration else []
        if sum(lengths) != len(target):
            sys.exit(f"Enumeration of '{clue}' does not fit {answer}")
        samples.append(
            {
                "id": f"guardian-genius-{args.number}-{position:02d}",
                "input": clue,
                "target": target,
                "metadata": {
                    "source": "Guardian Genius",
                    "puzzle": args.number,
                    "date": published,
                    "setter": setter,
                    # Genius grids vary (jigsaws, unnumbered entries), so clues are
                    # numbered by their place in the blog's table.
                    "direction": "",
                    "number": position,
                    "url": url,
                    "cross_reference": bool(re.search(r"\d", clue[: enumeration.start()])),
                },
            }
        )

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{published}-genius-{args.number}.json"
    path.write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
    BLOG_CACHE.mkdir(parents=True, exist_ok=True)
    cache = {"url": post["url"], "title": post["title"], "text": _text(post["html"])}
    (BLOG_CACHE / f"{args.number}.json").write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    print(f"Genius {args.number} ({published}, {setter}): {len(samples)} clues, {len(args.skip)} skipped -> {path}")


if __name__ == "__main__":
    main()
