import pytest

from crossword_bench import ft


def list_entry(label, definition, rest, answer, parsing="Parsing"):
    return (
        '<div class=" fts-group">'
        f'<div class=" fts-subgroup"><span style="color: #4682b4">{label} </span>'
        f'<span style="color: #4682b4;text-decoration: underline">{definition}</span>'
        f'<span style="color: #4682b4">{rest}</span></div>'
        f'<div class=" fts-subgroup" style="color: #424242;font-weight: bold">{answer}</div>'
        f'<div class=" fts-subgroup"><p>{parsing}</p><p><em>A note (5)</em></p></div>'
        "</div>"
    )


def table_entry(number, answer, clue):
    return (
        f'<tr><td class="fts-subgroup" style="color: #4682b4"><span>{number}</span></td>'
        f'<td class="fts-subgroup"><span style="font-weight: bold">{answer}</span></td>'
        f'<td class="fts-subgroup"><div><span>{clue}</span></div></td></tr>'
        '<tr class="fts-subgroup"><td colspan="2"></td><td><p>ACROSS parsing (4)</p></td></tr>'
    )


def post(content, title="Financial Times 18,505 by IO"):
    return {
        "title": {"rendered": title},
        "date": "2026-10-14T09:47:08",
        "link": "https://fifteensquared.net/2026/10/14/financial-times-18505-by-io/",
        "content": {"rendered": f"<p>Intro (3)</p><div><div><p>A table</p></div></div>{content}"},
    }


LIST_LAYOUT = (
    '<div class=" fts fts-list fts-spacing-small">'
    '<div class=" fts-group">ACROSS</div><div>'
    + list_entry("4.", "Bird", " in a tree (6,3)", "LITTLE OWL")
    + list_entry("21/2.", "Toys", " under wraps (5,5)", "TEDDY BEARS")
    + list_entry("12.", "Writer", " for 6 (5)", "MILNE")
    + '</div><div class=" fts-group">DOWN</div><div>'
    + list_entry("1.", "Rest", " at first (2,2,4)", "AT AN INCH")
    + list_entry("3.", "Medium", " convened (6)", "SÉANCE")
    + list_entry("5.", "Plan", " drawn up (5)", "DRAFTS")
    + "</div></div>"
)

TABLE_LAYOUT = (
    '<div class="fts fts-table fts-spacing-medium"><table><tbody>'
    '<tr><td colspan="3" class="fts-group">ACROSS</td></tr>'
    + table_entry("1", "PROPHESY", "Oracle supports dissent (8)")
    + table_entry("9", "SEVENTY – EIGHT", "Old record (7-5)")
    + '<tr><td colspan="3" class="fts-group">DOWN</td></tr>'
    + table_entry("2/20/5d", "SAMUEL TAYLOR COLERIDGE", "Poet (6,6,9)")
    + table_entry("7", "H2O", "Water (3)")
    + "</tbody></table></div>"
)


def test_list_layout():
    samples = ft.post_to_samples(post(LIST_LAYOUT))
    assert [s["id"] for s in samples] == [
        "ft-18505-4-across",
        "ft-18505-21-across",
        "ft-18505-1-down",
        "ft-18505-3-down",
    ]
    assert [s["input"] for s in samples] == [
        "Bird in a tree (6,3)",
        "Toys under wraps (5,5)",
        "Rest at first (2,2,4)",
        "Medium convened (6)",
    ]
    assert [s["target"] for s in samples] == ["LITTLEOWL", "TEDDYBEARS", "ATANINCH", "SEANCE"]
    assert samples[0]["metadata"] == {
        "source": "Financial Times",
        "puzzle": 18505,
        "date": "2026-10-14",
        "setter": "Io",
        "direction": "across",
        "number": 4,
        "url": "https://fifteensquared.net/2026/10/14/financial-times-18505-by-io/",
    }


def test_table_layout():
    samples = ft.post_to_samples(post(TABLE_LAYOUT, title="Financial Times 18531 Neo"))
    assert [(s["id"], s["input"], s["target"]) for s in samples] == [
        ("ft-18531-1-across", "Oracle supports dissent (8)", "PROPHESY"),
        ("ft-18531-9-across", "Old record (7-5)", "SEVENTYEIGHT"),
        ("ft-18531-2-down", "Poet (6,6,9)", "SAMUELTAYLORCOLERIDGE"),
    ]
    assert samples[0]["metadata"]["setter"] == "Neo"


def test_entry_missing_its_clue_is_skipped():
    broken = '<div class="fts fts-list"><div class="fts-group">ACROSS</div><div>'
    broken += '<div class="fts-group"><div class="fts-subgroup">DRAFT</div><div class="fts-subgroup">R in DAFT</div></div>'
    broken += list_entry("8.", "Polish", " gallery (5)", "EMERY") + "</div></div>"
    assert [s["target"] for s in ft.post_to_samples(post(broken))] == ["EMERY"]


def test_post_in_another_layout_refused():
    with pytest.raises(ValueError, match="neither fts layout"):
        ft.post_to_samples(post("<table><tr><td>1</td><td>GOLF</td></tr></table>"))


@pytest.mark.parametrize(
    "title, parsed",
    [
        ("Financial Times 18,505 by IO", (18505, "Io")),
        ("Financial Times 18528 Artexlen", (18528, "Artexlen")),
        ("Financial Times 18296 / Mudd", (18296, "Mudd")),
        ("Financial Times 18,502 by Rosa Klebb", (18502, "Rosa Klebb")),
        ("Financial Times Jumbo Crossword No 18,336 by GUY", (18336, "Guy")),
        ("FT Bank Holiday Jumbo 18,361 / Leonidas", (18361, "Leonidas")),
        ("Financial Times Sunday 168 – News by Jason", None),
        ("SUNDAY No 169 – WORLD by GOZO", None),
    ],
)
def test_parse_title(title, parsed):
    assert ft.parse_title(title) == parsed


@pytest.mark.parametrize(
    "parts, entry",
    [
        (["4. Clue (4)", "WORD"], (4, "Clue (4)", "WORD")),
        (["4 A clue (4)", "WORD"], (4, "A clue (4)", "WORD")),
        (["12", "WORD", "Clue (4)"], (12, "Clue (4)", "WORD")),
        (["TICK", "Double definition"], None),
        (["4. Clue (4)", "BARB (criticism) + ADOS"], None),
    ],
)
def test_read_entry(parts, entry):
    assert ft.read_entry(parts) == entry
