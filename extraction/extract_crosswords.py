#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pymupdf>=1.24.0",
#     "pytesseract>=0.3.10",
#     "Pillow>=10.0.0",
# ]
# ///
"""Extract cryptic crossword clues and answers from The London Paper PDFs.

Usage:
    uv run extraction/extract_crosswords.py <pdf_path_or_dir> [-o output_dir]

Each PDF page should be a crossword page from The London Paper (Aug 2009).
The script extracts cryptic clues and solutions using OCR, then matches
clues with answers from the following day's solutions section.

Requirements:
    - Tesseract OCR (brew install tesseract on macOS)
"""

import argparse
import io
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image

# ============================================================
# Image / OCR helpers
# ============================================================

def render_page(page, dpi=300):
    zoom = dpi / 72
    mat = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def ocr_crop(img, x0, y0, x1, y1):
    """OCR a region given fractional (0-1) coordinates."""
    w, h = img.size
    box = (
        max(0, int(w * x0)),
        max(0, int(h * y0)),
        min(w, int(w * x1)),
        min(h, int(h * y1)),
    )
    return pytesseract.image_to_string(img.crop(box))


# ============================================================
# Layout detection
# ============================================================

def find_layout(img):
    """Find key layout positions using TSV OCR data.

    Returns dict of fractional (0-1) y/x positions for:
      col1_x   – left edge of clue column 1  (Across + Down start)
      col2_x   – left edge of clue column 2  (Down clues 2+)
      across_y – "Across" header
      down_y   – "Down" header
      sol_y    – "friday's solutions" section
      gk_y     – "general knowledge" in right column (end of cryptic Down)
    """
    w, h = img.size
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    pos = {
        "col1_x": 0.49,
        "col2_x": 0.69,
        "across_y": 0.10,
        "down_y": 0.29,
        "sol_y": 0.34,
        "gk_y": 0.27,
    }

    for i, text in enumerate(data["text"]):
        t = str(text).strip().lower()
        if not t:
            continue
        x_pct = data["left"][i] / w
        y_pct = data["top"][i] / h

        if t == "across" and 0.45 < x_pct < 0.55 and y_pct < 0.15:
            pos["across_y"] = y_pct
            pos["col1_x"] = x_pct

        if t == "down" and 0.45 < x_pct < 0.55 and 0.25 < y_pct < 0.35:
            pos["down_y"] = y_pct

        if t in ("solutions", "friday") and y_pct > 0.30:
            pos["sol_y"] = min(pos["sol_y"], y_pct)

        # "general" in right column above solutions → end of cryptic Down
        if t == "general" and x_pct > 0.65 and 0.20 < y_pct < 0.35:
            pos["gk_y"] = y_pct

    # Refine col2_x from Down-clue numbers detected in right half
    for i, text in enumerate(data["text"]):
        t = str(text).strip()
        x_pct = data["left"][i] / w
        y_pct = data["top"][i] / h
        if re.match(r"^\d{1,2}[.,]?$", t) and x_pct > 0.60 and y_pct < 0.30:
            pos["col2_x"] = min(pos["col2_x"], x_pct - 0.01)

    return pos


# ============================================================
# Clue parsing
# ============================================================

_LENGTH_RE = re.compile(r"\(\d+[-,]?\d*[-,]?\d*\)\s*$")
_SEE_RE = re.compile(r"See \d+ (Down|Across)[.,]?\s*$", re.IGNORECASE)
_COMBINED_RE = re.compile(
    r"^(\d{1,2})\s*&\s*(\d{1,2})\s*(Ac|Down)[.,]?\s*(.*)", re.IGNORECASE
)


def _is_noise(s):
    """Detect header text, OCR garbage, and other non-clue lines."""
    if re.match(
        r"^(Across|Down|cryptic|crosswo|Try our|Look for|http|general|friday)",
        s, re.IGNORECASE,
    ):
        return True
    if re.match(r"^\d{2}/\d{2}/", s) or re.match(r"^\d+ of \d+$", s):
        return True
    if re.search(
        r"(tomorrow's paper|Knowledge Crossword|yptic or|answers in)",
        s, re.IGNORECASE,
    ):
        return True
    # Lines starting with ' (common header fragment)
    if s.startswith("'") or s.startswith("\u2018"):
        return True
    # Short garbage (non-clue fragments)
    if len(s) <= 3 and not re.match(r"^\d{1,2}[.,]?$", s):
        return True
    return False


def _clean_line(s):
    """Clean common OCR artifacts from a clue line."""
    # Remove leading single-char fragment before a number: "d 10." → "10."
    s = re.sub(r"^[a-z]\s+(?=\d{1,2}[.,]?\s)", "", s)
    # Remove leading length fragment before a number: "8) 19." → "19."
    s = re.sub(r"^\d+\)\s*(?=\d{1,2}[.,]?\s)", "", s)
    # Remove leading stray punctuation: ", 4." → "4."
    s = re.sub(r"^[,;]\s*(?=\d)", "", s)
    return s


def _classify_lines(text):
    """Classify each OCR line as num / dot / blank / text."""
    items = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            items.append(("blank", None))
            continue

        s = _clean_line(s)
        if not s:
            continue
        if _is_noise(s):
            # Hard stop at section breaks
            if re.match(r"^.?eneral", s, re.IGNORECASE):
                break
            continue

        # Lone number: "7."
        m = re.match(r"^(\d{1,2})[.,]?\s*$", s)
        if m and int(m.group(1)) <= 30:
            items.append(("num", int(m.group(1))))
            continue

        # Combined reference: "5 &21Ac. text..."
        m = _COMBINED_RE.match(s)
        if m:
            num = int(m.group(1))
            ref = m.group(2)
            ref_dir = "Ac." if "ac" in m.group(3).lower() else "Down."
            rest = m.group(4).strip()
            items.append(("num", num))
            if rest:
                items.append(("text", f"& {ref} {ref_dir} {rest}"))
            continue

        # Number + text: "7. A little squirt..."
        m = re.match(r"^(\d{1,2})[.,]?\s+(.+)", s)
        if m and int(m.group(1)) <= 30 and len(m.group(2).strip()) >= 2:
            items.append(("num", int(m.group(1))))
            items.append(("text", m.group(2).strip()))
            continue

        # Dot + text: ". Likely to look..."
        m = re.match(r"^\.\s+(.+)", s)
        if m:
            items.append(("dot", None))
            items.append(("text", m.group(1).strip()))
            continue

        # Lone dot
        if s == ".":
            items.append(("dot", None))
            continue

        # Everything else is text (skip very short garbage)
        if len(s) >= 3:
            items.append(("text", s))

    return items


def _parse_separated(items):
    """Numbers are grouped first, then texts (one per clue).

    Also handles the case where a combined-clue inserts partial text
    between numbers (e.g. "5 &21Ac. text..." followed by more numbers).
    """
    numbers, texts = [], []
    cur = ""
    partial_for_num_idx = {}  # {num_index: partial_text}

    for kind, val in items:
        if kind in ("num", "dot"):
            if cur:
                # Text appeared between numbers — save as partial
                partial_for_num_idx[len(numbers) - 1] = cur.strip()
                cur = ""
            numbers.append(val)
        elif kind == "text":
            cur = f"{cur} {val}" if cur else val
            if _LENGTH_RE.search(cur) or _SEE_RE.search(cur):
                texts.append(cur.strip())
                cur = ""
        elif kind == "blank" and cur:
            # Blank line separates text blocks (e.g. "See 5 Down.\n\nComplete...")
            texts.append(cur.strip())
            cur = ""

    if cur:
        texts.append(cur.strip())

    # Merge partial texts: prepend to the corresponding text block
    for idx, partial in partial_for_num_idx.items():
        if idx < len(texts):
            texts[idx] = f"{partial} {texts[idx]}"
        else:
            texts.append(partial)

    clues = list(zip(numbers, texts))
    for i in range(len(numbers), len(texts)):
        clues.append((None, texts[i]))
    return "", clues


def _parse_inline(items):
    """Numbers appear inline with their text."""
    clues = []
    orphan = ""
    cur_num = None
    cur_text = ""
    first = False

    for kind, val in items:
        if kind in ("num", "dot"):
            if first and cur_text:
                clues.append((cur_num, cur_text.strip()))
            elif cur_text and not first:
                orphan = cur_text.strip()
            first = True
            cur_num = val
            cur_text = ""
        elif kind == "text":
            cur_text = f"{cur_text} {val}" if cur_text else val

    if first and cur_text:
        clues.append((cur_num, cur_text.strip()))
    elif cur_text:
        orphan = cur_text.strip()

    return orphan, clues


_LENGTH_ANYWHERE_RE = re.compile(r"\(\d+[-,]?\d*[-,]?\d*\)")


def _trim_clues(clues):
    """Trim trailing garbage after the length indicator in each clue."""
    trimmed = []
    for num, text in clues:
        # Find the last length indicator and truncate there
        matches = list(_LENGTH_ANYWHERE_RE.finditer(text))
        if matches:
            trimmed.append((num, text[: matches[-1].end()].strip()))
        elif _SEE_RE.search(text):
            m = _SEE_RE.search(text)
            trimmed.append((num, text[: m.end()].strip()))
        else:
            trimmed.append((num, text))
    return trimmed


def parse_clue_column(text):
    """Parse an OCR column into (orphan_text, [(number|None, clue_text)]).

    Handles both separated-numbers and inline-numbers layouts.
    """
    items = _classify_lines(text)
    if not items:
        return "", []

    # Detect mode: ≥3 consecutive number tokens → separated
    consec, mx = 0, 0
    for kind, _ in items:
        if kind in ("num", "dot"):
            consec += 1
            mx = max(mx, consec)
        else:
            consec = 0

    if mx >= 3:
        orphan, clues = _parse_separated(items)
    else:
        orphan, clues = _parse_inline(items)

    return orphan, _trim_clues(clues)


# ============================================================
# Solutions parsing
# ============================================================

def _parse_solution_entries(text):
    """Parse '1 Answer; 2 Answer; ...' → {num: answer}."""
    entries = {}
    for part in re.split(r"[;,.]\s*(?=\d+\s)", text):
        m = re.match(r"(\d+)\s+(.*)", part.strip())
        if m:
            answer = m.group(2).strip().rstrip(";,.")
            if answer:
                entries[int(m.group(1))] = answer
    return entries


def parse_solutions(text):
    """Parse the solutions section for cryptic answers."""
    sol = {"across": {}, "down": {}}
    flat = " ".join(text.split())

    m = re.search(r"\bCryptic\b", flat, re.IGNORECASE)
    if not m:
        return sol
    flat = flat[m.end() :]

    gk = re.search(r"General\s*Knowledge", flat, re.IGNORECASE)
    if gk:
        flat = flat[: gk.start()]

    am = re.search(r"Across:\s*(.*?)Down:", flat, re.IGNORECASE)
    if am:
        sol["across"] = _parse_solution_entries(am.group(1))

    dm = re.search(r"Down:\s*(.*)", flat, re.IGNORECASE)
    if dm:
        sol["down"] = _parse_solution_entries(dm.group(1))

    return sol


# ============================================================
# Page extraction
# ============================================================

def extract_date(text):
    m = re.search(r"(\d{1,2}\s+\w{3,9}\s+\d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%d %b %Y").date()
        except ValueError:
            pass
    return None


def extract_page(page, idx):
    img = render_page(page, dpi=300)
    lay = find_layout(img)

    page_date = extract_date(page.get_text())
    log = lambda msg: print(f"  p{idx + 1} ({page_date}): {msg}", file=sys.stderr)

    # ---- OCR three regions ----
    col1_text = ocr_crop(
        img,
        lay["col1_x"] - 0.02,
        lay["across_y"] - 0.01,
        lay["col2_x"],
        lay["sol_y"] - 0.01,
    )
    col2_text = ocr_crop(
        img,
        lay["col2_x"] - 0.02,
        0.06,
        0.92,
        lay["gk_y"] + 0.01,
    )
    sol_text = ocr_crop(img, 0.08, lay["sol_y"] - 0.02, 0.65, 0.52)

    # ---- Parse column 1: split at "Down" header ----
    down_split = re.search(r"^Down\b", col1_text, re.MULTILINE | re.IGNORECASE)
    if down_split:
        across_raw = col1_text[: down_split.start()]
        down1_raw = col1_text[down_split.end() :]
    else:
        across_raw = col1_text
        down1_raw = ""

    _, across_clues = parse_clue_column(across_raw)
    _, down1_clues = parse_clue_column(down1_raw)

    # ---- Parse column 2: Down clues 2+ ----
    col2_orphan, down_rest = parse_clue_column(col2_text)

    # ---- Merge Down clue 1 ----
    down_clues = {}
    clue1_from_col1 = dict(down1_clues).get(1)
    if clue1_from_col1:
        if _LENGTH_RE.search(clue1_from_col1):
            down_clues[1] = clue1_from_col1
        elif col2_orphan:
            down_clues[1] = f"{clue1_from_col1} {col2_orphan}"
        else:
            down_clues[1] = clue1_from_col1
    elif col2_orphan:
        down_clues[1] = col2_orphan

    for num, txt in down_rest:
        if num is not None:
            down_clues[num] = txt

    # Keep unresolved (number=None) separately for later matching
    unresolved_down = [txt for num, txt in down_rest if num is None]

    # ---- Parse solutions ----
    solutions = parse_solutions(sol_text)

    log(
        f"across={len(across_clues)} down={len(down_clues)}+{len(unresolved_down)}? "
        f"sol_a={len(solutions['across'])} sol_d={len(solutions['down'])}"
    )

    return {
        "date": page_date.isoformat() if page_date else None,
        "clues": {
            "across": {str(n): t for n, t in across_clues if n is not None},
            "down": {str(k): v for k, v in sorted(down_clues.items())},
        },
        "unresolved_down": unresolved_down,
        "solutions": {
            "across": {str(k): v for k, v in sorted(solutions["across"].items())},
            "down": {str(k): v for k, v in sorted(solutions["down"].items())},
        },
        "_raw": {
            "col1": col1_text,
            "col2": col2_text,
            "sol": sol_text,
        },
    }


# ============================================================
# Matching clues ↔ answers
# ============================================================

def next_weekday(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


_ENUM_RE = re.compile(r"\((\d+(?:[,-]\d+)*)\)\s*$")
_ANSWER_OK_RE = re.compile(r"^[A-Za-z][A-Za-z '\-]*$")
_CLUE_START_RE = re.compile(r"^[A-Z\"'‘“]")


def enum_total(text):
    """Total letter count promised by a clue's enumeration, e.g. (3,3,6) → 12."""
    m = _ENUM_RE.search(text)
    if not m:
        return None
    return sum(int(n) for n in re.split(r"[,-]", m.group(1)))


def answer_letters(answer):
    return re.sub(r"[^A-Za-z]", "", answer)


def clue_usable(text):
    """A clue we can validate: starts like a clue (not a truncated fragment)
    and carries an enumeration. Excludes 'See 5 Down.' cross-references."""
    return enum_total(text) is not None and bool(_CLUE_START_RE.match(text))


_INTERIOR_ENUM_RE = re.compile(r"\(\d+(?:[,-]\d+)*\)\s*")


def split_concatenated(entries):
    """Split texts holding several clues that OCR glued together, e.g.
    'Be prominent ... (5,3) : 15. One better (7)' → two clues. A clue's
    enumeration is terminal, so text after one starts a new clue."""
    out = []
    for num, text in entries:
        rest = text
        while rest.strip():
            m = _INTERIOR_ENUM_RE.search(rest)
            if not m or m.end() >= len(rest.rstrip()):
                out.append((num, rest.strip()))
                break
            out.append((num, rest[: m.end()].strip()))
            tail = re.sub(r"^[^A-Za-z0-9(]+", "", rest[m.end() :])
            nm = re.match(r"(\d{1,2})[.,]\s*", tail)
            num = None
            if nm and int(nm.group(1)) <= 30:
                num = int(nm.group(1))
                tail = tail[nm.end() :]
            rest = tail
    return out


def merge_fragments(entries):
    """Merge clue texts split across entries: an enumeration-less entry
    followed by a lowercase-starting entry that carries the enumeration."""
    out = []
    i = 0
    while i < len(entries):
        num, text = entries[i]
        if (
            enum_total(text) is None
            and _CLUE_START_RE.match(text)
            and i + 1 < len(entries)
        ):
            _, nxt = entries[i + 1]
            if nxt and nxt[0].islower() and enum_total(nxt) is not None:
                out.append((num, f"{text} {nxt}"))
                i += 2
                continue
        out.append((num, text))
        i += 1
    return out


def align_texts_to_solutions(texts, solutions):
    """Order-preserving alignment of clue texts to solution slots.

    OCR sometimes drops a clue number, which shifts every later clue onto
    the wrong number, so extracted numbers can't be trusted for pairing.
    Both lists are in grid order. A validated text (enumeration present)
    may only occupy a slot whose answer length matches its enumeration;
    an unvalidated text is a wildcard that may occupy any slot — it can't
    be emitted as data, but it still holds its place in the sequence so
    its neighbours don't slide into the wrong slots.

    Scoring: validated matches dominate; contiguous runs of matches beat
    agreement with the (possibly shifted) extracted numbers, which is only
    a last-resort tiebreaker.

    texts: [(extracted_num_or_None, clue_text, validated_bool)]
    solutions: [(num, answer)]
    Returns [(text_idx, sol_idx)] for validated texts only.
    """
    m, n = len(texts), len(solutions)
    MATCH, ADJACENT, NUM_AGREE, GAP = 100, 2, 1, 10

    etotals = [enum_total(t) for _, t, _ in texts]
    lengths = [len(answer_letters(a)) for _, a in solutions]
    usable_answer = [bool(_ANSWER_OK_RE.match(a)) for _, a in solutions]

    # score[i][j][k]: best score for texts[i:] vs solutions[j:].
    # k tracks context: 0 = no match yet (leading skips are free),
    # 1 = matched earlier (skipping a slot now leaves an interior gap),
    # 2 = previous action was a match (adjacency bonus available).
    score = [[[0, 0, 0] for _ in range(n + 1)] for _ in range(m + 1)]
    choice = [[[0, 0, 0] for _ in range(n + 1)] for _ in range(m + 1)]

    for i in range(m - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            num, _text, validated = texts[i]
            snum = solutions[j][0]
            if validated:
                allowed = usable_answer[j] and etotals[i] == lengths[j]
                reward = MATCH + (NUM_AGREE if num == snum else 0)
            else:
                allowed = True  # wildcard: holds its place, earns nothing
                reward = 0
            for k in (0, 1, 2):
                after = min(k, 1)
                best, ch = score[i + 1][j][after], 0  # skip text
                skip_slot = score[i][j + 1][after] - (GAP if k else 0)
                if skip_slot > best:
                    best, ch = skip_slot, 1
                if allowed:
                    s = reward + (ADJACENT if k == 2 else 0) + score[i + 1][j + 1][2]
                    if s > best:
                        best, ch = s, 2
                score[i][j][k], choice[i][j][k] = best, ch

    pairs, i, j, k = [], 0, 0, 0
    while i < m and j < n:
        ch = choice[i][j][k]
        if ch == 2:
            if texts[i][2]:
                pairs.append((i, j))
            i, j, k = i + 1, j + 1, 2
        elif ch == 0:
            i, k = i + 1, min(k, 1)
        else:
            j, k = j + 1, min(k, 1)
    return pairs


def match_clues_answers(pages):
    by_date = {p["date"]: p for p in pages if p["date"]}
    matched, unmatched = [], []

    for dstr in sorted(by_date):
        page = by_date[dstr]
        d = date.fromisoformat(dstr)
        nxt = next_weekday(d).isoformat()

        if nxt not in by_date:
            for direction in ("across", "down"):
                for num, clue in page["clues"][direction].items():
                    unmatched.append(
                        {
                            "input": clue,
                            "date": dstr,
                            "direction": direction,
                            "number": int(num),
                            "reason": f"no page for {nxt}",
                        }
                    )
            for txt in page.get("unresolved_down", []):
                unmatched.append(
                    {
                        "input": txt,
                        "date": dstr,
                        "direction": "down",
                        "number": None,
                        "reason": f"no page for {nxt}",
                    }
                )
            continue

        next_sol = by_date[nxt]["solutions"]
        for direction in ("across", "down"):
            entries = merge_fragments(
                split_concatenated(
                    sorted(
                        ((int(k), v) for k, v in page["clues"][direction].items()),
                        key=lambda kv: kv[0],
                    )
                )
            )
            solutions = sorted(
                ((int(k), v) for k, v in next_sol[direction].items()),
                key=lambda kv: kv[0],
            )

            def emit(pairs, texts, sols):
                taken = set()
                for ti, sj in pairs:
                    taken.add(ti)
                    tnum, ttext, _ = texts[ti]
                    snum, ans = sols[sj]
                    meta = {
                        "source": "The London Paper",
                        "date": dstr,
                        "direction": direction,
                        "number": snum,
                    }
                    if tnum is not None and tnum != snum:
                        meta["ocr_number"] = tnum
                    matched.append(
                        {"input": ttext, "target": ans.upper(), "metadata": meta}
                    )
                return taken

            def report(texts, taken):
                for ti, (tnum, ttext, validated) in enumerate(texts):
                    if ti in taken:
                        continue
                    unmatched.append(
                        {
                            "input": ttext,
                            "date": dstr,
                            "direction": direction,
                            "number": tnum,
                            "reason": (
                                "no length-consistent solution slot"
                                if validated
                                else "unusable clue text (fragment or no enumeration)"
                            ),
                        }
                    )

            texts = [(num, t, clue_usable(t)) for num, t in entries]
            pairs = align_texts_to_solutions(texts, solutions)
            taken_texts = emit(pairs, texts, solutions)
            taken_slots = {sj for _, sj in pairs}
            report(texts, taken_texts)

            # Down clues whose numbers OCR missed entirely: align them
            # against the slots not already claimed by a validated match.
            if direction == "down":
                extra = [
                    (num, t, clue_usable(t))
                    for num, t in merge_fragments(
                        split_concatenated(
                            [(None, t) for t in page.get("unresolved_down", [])]
                        )
                    )
                ]
                leftover = [
                    s for j, s in enumerate(solutions) if j not in taken_slots
                ]
                pairs2 = align_texts_to_solutions(extra, leftover)
                taken2 = emit(pairs2, extra, leftover)
                report(extra, taken2)

    return matched, unmatched


# ============================================================
# Main
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="Extract cryptic crossword data from The London Paper PDFs"
    )
    ap.add_argument("pdf_path", help="PDF file or directory of PDFs")
    ap.add_argument(
        "-o", "--output", default="extraction/output", help="Output directory"
    )
    args = ap.parse_args()

    pdf_path = Path(args.pdf_path)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    if pdf_path.suffix.lower() == ".json":
        # Re-run matching from a previously extracted pages.json, no OCR
        with open(pdf_path) as f:
            all_pages = json.load(f)
        print(f"{len(all_pages)} pages loaded from {pdf_path}", file=sys.stderr)
    else:
        pdfs = (
            sorted(pdf_path.glob("*.pdf")) + sorted(pdf_path.glob("*.PDF"))
            if pdf_path.is_dir()
            else [pdf_path]
        )

        all_pages = []
        for pdf in pdfs:
            print(f"Processing {pdf.name} ...", file=sys.stderr)
            doc = pymupdf.open(str(pdf))
            for i in range(len(doc)):
                all_pages.append(extract_page(doc[i], i))

        # Save per-page data (without raw OCR)
        clean = [{k: v for k, v in p.items() if k != "_raw"} for p in all_pages]
        with open(out / "pages.json", "w") as f:
            json.dump(clean, f, indent=2)

        # Save raw OCR for debugging
        with open(out / "pages_raw.json", "w") as f:
            json.dump(all_pages, f, indent=2)

        print(f"\n{len(all_pages)} pages extracted → {out / 'pages.json'}", file=sys.stderr)

    # Match
    matched, unmatched = match_clues_answers(all_pages)
    if matched:
        with open(out / "clues.json", "w") as f:
            json.dump(matched, f, indent=2)
        print(f"{len(matched)} matched clues → {out / 'clues.json'}", file=sys.stderr)

    if unmatched:
        with open(out / "unmatched.json", "w") as f:
            json.dump(unmatched, f, indent=2)
        print(
            f"{len(unmatched)} unmatched clues → {out / 'unmatched.json'}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
