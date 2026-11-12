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
        "effort": "medium",
        "created": "2026-01-01",
        "public": public,
        "log_file": f"{model}.eval",
        "samples": {
            f"clue-{i}": {
                "outcome": outcome,
                "answer": "SECRETANSWER" if outcome == "correct" else "WRONG",
                "input": "Secret clue text (12)",
                "target": "SECRETANSWER",
                "tokens": {"input": 100, "cached_input": 20, "output": 40, "reasoning": 30},
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
    pricing = {"models": {"x": {"input": 1.0, "cached_input": 0.5, "output": 10.0}}}
    cohort = site.build_cohort("c", runs, labels, pricing)
    assert [c["answer"] for c in cohort["clue_list"]] == ["SECRETANSWER"] * 3
    pair = cohort["head_to_head"][0]
    assert (pair["both"], pair["only_a"], pair["only_b"], pair["neither"]) == (1, 1, 1, 0)
    assert cohort["by_device"][0]["name"] == "anagram"
    assert cohort["runs"][0]["tokens"] == {
        "input": 300,
        "cached_input": 60,
        "output": 120,
        "reasoning": 90,
        "output_per_clue": 40,
        "input_per_clue": 100,
    }
    assert cohort["clue_list"][0]["results"][0]["output_tokens"] == 40
    assert cohort["runs"][0]["provider"] == "Other"
    priced = next(r for r in cohort["runs"] if r["model"] == "a/x")
    assert priced["estimated_cost"]["total"] == (240 * 1.0 + 60 * 0.5 + 120 * 10.0) / 1_000_000
    assert next(r for r in cohort["runs"] if r["model"] == "b/y")["estimated_cost"] is None
    assert cohort["by_device"][0]["all_runs"] == {"correct": 2, "total": 2}
    assert "Secret clue text" in site.generate_html([cohort])


def test_provider_mapping():
    assert site.provider_of("codex/gpt-6-luna") == "OpenAI"
    assert site.provider_of("anthropic/claude-haiku-5-5") == "Anthropic"
    assert site.provider_of("openrouter/google/gemini") == "Google"
    assert site.provider_of("somewhere/new-model") == "Other"
