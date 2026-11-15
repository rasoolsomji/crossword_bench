"""Fetch Financial Times cryptics for the live track, via Fifteensquared.

ft.com answers scripted requests with a Cloudflare challenge, so the clues
and answers come from Fifteensquared, which blogs every FT daily. Nearly
all FT posts use one of the blog's two fixed layouts, fts-list and
fts-table, which put each clue's number, text and answer in set places
under ACROSS and DOWN headings. Posts laid out any other way are reported
and skipped.

This reads the blogger's transcription, not the FT's own text. A clue
whose enumeration doesn't fit its answer is skipped, but a typo in the
wording isn't caught, and post titles occasionally carry the wrong puzzle
number. The post's date stands in for the publication date, which the
post doesn't give.
"""

import argparse
import html
import json
import re
import sys
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from crossword_bench.classify import BLOG_API, BLOG_CACHE
from crossword_bench.guardian import _get, clean_clue, refers_to_other_entry

FT_CATEGORY = 6  # Fifteensquared's "Financial Times"
DEFAULT_OUT = Path(__file__).parent.parent.parent / "data" / "live" / "ft"
UK = ZoneInfo("Europe/London")

# "Financial Times 18,505 by IO", "Financial Times 18528 Artexlen", "FT Bank
# Holiday Jumbo 18,361 / Leonidas". Five-digit numbers only: the Sunday
# puzzles have a numbering of their own.
_TITLE = re.compile(r"^(?:Financial Times|FT)\b(?!.*\bSunday\b).*?(\d{2},?\d{3})\s*(?:by\b|/)?\s*(.+?)\s*$", re.I)
# "4. ", "21/2. ", "2/20/5d", or a bare "4" in a cell of its own.
_LABEL = re.compile(r"^(\d+)((?:\s*[/,&]\s*\d+[ad]?)*)([ad]|ac|dn)?(?:\s*[.:]\s*|\s+|$)", re.I)
_ENUMERATION = re.compile(r"\s*\(([\d,\-\s]+)\)\s*$")
_ANSWER = re.compile(r"^[A-Z][A-Z'’ –—-]*$")


class _FtsLayout(HTMLParser):
    """The parts of each clue entry in an fts-list or fts-table layout, with its heading.

    In fts-list an entry is a div.fts-group whose div.fts-subgroup children
    hold the numbered clue, the answer and the parsing. In fts-table it is a
    table row whose td.fts-subgroup cells hold the number, the answer and the
    clue, with the parsing in a tr.fts-subgroup row of its own. A group with
    no parts is a heading (ACROSS, DOWN).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str | None] = []
        self.entry: list[str] | None = None
        self.heading_text: list[str] = []
        self.part: list[str] | None = None
        self.heading = ""
        self.entries: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("p", "br", "li") and self.part is not None:
            self.part.append(" ")
        if tag not in ("div", "table", "tr", "td"):
            return
        classes = (dict(attrs).get("class") or "").split()
        role = None
        if "ignore" in self.stack:
            pass
        elif tag == "div" and "fts" in classes:
            role = "fts"
        elif "fts" not in self.stack:
            pass
        elif tag == "tr" and "fts-subgroup" in classes:
            role = "ignore"
        elif self.entry is None and ("fts-group" in classes or tag == "tr"):
            role, self.entry, self.heading_text = "entry", [], []
        elif self.entry is not None and "fts-subgroup" in classes:
            role, self.part = "part", []
        self.stack.append(role)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ("div", "table", "tr", "td") or not self.stack:
            return
        role = self.stack.pop()
        if role == "part":
            self.entry.append(clean_clue("".join(self.part)))
            self.part = None
        elif role == "entry":
            if self.entry:
                self.entries.append((self.heading, self.entry))
            else:
                self.heading = clean_clue("".join(self.heading_text)).lower()
            self.entry = None

    def handle_data(self, data: str) -> None:
        if "ignore" in self.stack:
            return
        if self.part is not None:
            self.part.append(data)
        elif self.entry is not None:
            self.heading_text.append(data)


def parse_title(title: str) -> tuple[int, str] | None:
    """Puzzle number and setter of an FT daily post, or None for anything else."""
    match = _TITLE.match(title)
    if not match:
        return None
    setter = match.group(2)
    return int(match.group(1).replace(",", "")), setter.title() if setter.isupper() else setter


def read_entry(parts: list[str]) -> tuple[int, str, str] | None:
    """Clue number, clue and answer of an entry, told apart by their content."""
    label = _LABEL.match(parts[0])
    if not label:
        return None
    rest = [parts[0][label.end() :], *parts[1:3]]
    clue = next((i for i, part in enumerate(rest) if _ENUMERATION.search(part)), None)
    answer = next((i for i, part in enumerate(rest) if i != clue and _ANSWER.match(_unaccented(part))), None)
    if clue is None or answer is None:
        return None
    return int(label.group(1)), rest[clue], _unaccented(rest[answer])


def _unaccented(text: str) -> str:
    """SÉANCE as SEANCE, as grids enter it."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def post_to_samples(post: dict) -> list[dict]:
    """Convert a Fifteensquared FT post into Inspect samples, one per clue."""
    title = html.unescape(post["title"]["rendered"])
    parsed = parse_title(title)
    if not parsed:
        raise ValueError(f"Not an FT daily: {title}")
    number, setter = parsed
    layout = _FtsLayout()
    layout.feed(post["content"]["rendered"])
    if not layout.entries:
        raise ValueError("Post uses neither fts layout")

    samples = []
    for heading, parts in layout.entries:
        direction = next((d for d in ("across", "down") if heading.startswith(d)), None)
        entry = read_entry(parts)
        if not direction or not entry:
            print(f"  {number}: skipping unreadable entry under '{heading}': {parts[:3]}", file=sys.stderr)
            continue
        clue_number, clue, answer = entry
        target = re.sub(r"[^A-Z]", "", answer)
        lengths = [int(n) for n in re.findall(r"\d+", _ENUMERATION.search(clue).group(1))]
        if sum(lengths) != len(target):
            print(f"  {number}: skipping {clue_number} {direction}: '{clue}' does not fit {answer}", file=sys.stderr)
            continue
        if refers_to_other_entry(clue):
            print(f"  {number}: skipping {clue_number} {direction}: refers to another entry: {clue}", file=sys.stderr)
            continue
        samples.append(
            {
                "id": f"ft-{number}-{clue_number}-{direction}",
                "input": clue,
                "target": target,
                "metadata": {
                    "source": "Financial Times",
                    "puzzle": number,
                    "date": post["date"][:10],
                    "setter": setter,
                    "direction": direction,
                    "number": clue_number,
                    "url": post["link"],
                },
            }
        )
    if len({s["id"] for s in samples}) != len(samples):
        raise ValueError("Post lists a clue number twice")
    return samples


def _posts(**params) -> list[dict]:
    """All FT posts matching the WordPress query, following its pages."""
    posts, page = [], 1
    while True:
        query = urllib.parse.urlencode(
            {"categories": FT_CATEGORY, "per_page": 100, "page": page, "_fields": "link,title,date,content", **params}
        )
        batch = json.loads(_get(f"{BLOG_API}?{query}"))
        posts += batch
        if len(batch) < 100:
            return posts
        page += 1


def posts_between(since: date, until: date) -> list[dict]:
    return _posts(after=f"{since - timedelta(days=1)}T23:59:59", before=f"{until + timedelta(days=1)}T00:00:00")


def post_for_number(number: int) -> dict | None:
    for search in (f"{number:,}", str(number)):
        for post in _posts(search=search):
            parsed = parse_title(html.unescape(post["title"]["rendered"]))
            if parsed and parsed[0] == number:
                return post
    return None


def cache_post(number: int, post: dict) -> None:
    """Keep the post where classify-clues looks for a puzzle's parsing."""
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", post["content"]["rendered"]))).strip()
    cache = {"url": post["link"], "title": html.unescape(post["title"]["rendered"]), "text": text}
    BLOG_CACHE.mkdir(parents=True, exist_ok=True)
    (BLOG_CACHE / f"{number}.json").write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--since", type=date.fromisoformat, help="Earliest blog post date (YYYY-MM-DD). Default: six weeks ago."
    )
    parser.add_argument("--until", type=date.fromisoformat, help="Latest blog post date. Default: today.")
    parser.add_argument("--numbers", type=int, nargs="+", help="Fetch these puzzle numbers instead of a date range.")
    parser.add_argument("--setter", nargs="+", help="Keep only puzzles by these setters (e.g. Io); any case.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if args.numbers:
        posts = []
        for number in args.numbers:
            post = post_for_number(number)
            if post:
                posts.append(post)
            else:
                print(f"{number}: no Fifteensquared post found", file=sys.stderr)
    else:
        today = datetime.now(UK).date()
        posts = posts_between(args.since or today - timedelta(weeks=6), args.until or today)

    wanted = {s.lower() for s in args.setter or []}
    seen: dict[int, str] = {}
    args.out.mkdir(parents=True, exist_ok=True)
    for post in posts:
        title = html.unescape(post["title"]["rendered"])
        parsed = parse_title(title)
        if not parsed:
            print(f"Skipping '{title}': not an FT daily", file=sys.stderr)
            continue
        number, setter = parsed
        if wanted and setter.lower() not in wanted:
            continue
        if number in seen:
            print(f"{number} ({setter}): skipping, {seen[number]} has the same number in its title", file=sys.stderr)
            continue
        seen[number] = post["link"]
        try:
            samples = post_to_samples(post)
        except ValueError as error:
            print(f"{number} ({setter}): {error}: {post['link']}", file=sys.stderr)
            continue
        if not samples:
            print(f"{number} ({setter}): no usable clues: {post['link']}", file=sys.stderr)
            continue
        cache_post(number, post)
        path = args.out / f"{samples[0]['metadata']['date']}-ft-{number}.json"
        path.write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
        print(f"{number} ({samples[0]['metadata']['date']}, {setter}): {len(samples)} clues -> {path}")


if __name__ == "__main__":
    main()
