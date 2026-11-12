import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "build_leaderboard.py"
spec = importlib.util.spec_from_file_location("build_leaderboard", SCRIPT)
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def run(model, public, outcomes):
    return {
        "cohort": "c",
        "model": model,
        "effort": "default",
        "created": "2026-01-01",
        "public": public,
        "log_file": f"{model}.eval",
        "samples": {
            f"clue-{i}": {
                "outcome": outcome,
                "answer": "SECRETANSWER" if outcome == "correct" else "WRONG",
                "input": "Secret clue text (12)",
                "target": "SECRETANSWER",
                "metadata": {"puzzle": 1, "setter": "S", "date": "2026-01-01", "source": "Src", "number": i, "direction": "across"},
            }
            for i, outcome in enumerate(outcomes)
        },
    }


def test_private_cohort_publishes_no_clue_text():
    runs = [run("a/x", False, ["correct", "wrong_answer"]), run("b/y", True, ["correct", "correct"])]
    cohort = site.build_cohort("c", runs, {})
    rendered = json.dumps(cohort) + site.generate_html([cohort])
    assert cohort["public"] is False
    assert "Secret clue text" not in rendered
    assert "SECRETANSWER" not in rendered
    assert all(r["log_file"] is None for r in cohort["runs"] if r["model"] == "a/x")


def test_public_cohort_has_clues_and_head_to_head():
    runs = [
        run("a/x", True, ["correct", "wrong_answer", "correct"]),
        run("b/y", True, ["correct", "correct", "wrong_length"]),
    ]
    labels = {"clues": {"clue-0": {"devices": ["anagram"], "and_lit": False}}}
    cohort = site.build_cohort("c", runs, labels)
    assert [c["answer"] for c in cohort["clue_list"]] == ["SECRETANSWER"] * 3
    pair = cohort["head_to_head"][0]
    assert (pair["both"], pair["only_a"], pair["only_b"], pair["neither"]) == (1, 1, 1, 0)
    assert cohort["by_device"][0]["name"] == "anagram"
    assert "Secret clue text" in site.generate_html([cohort])
