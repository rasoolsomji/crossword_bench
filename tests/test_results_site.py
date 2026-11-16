import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "build_leaderboard.py"
spec = importlib.util.spec_from_file_location("build_leaderboard", SCRIPT)
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def run(model, outcomes):
    return {
        "cohort": "c",
        "model": model,
        "effort": "medium",
        "created": "2026-01-01",
        "log_file": f"{model}.eval",
        "samples": {
            f"clue-{i}": {
                "outcome": outcome,
                "answer": "ANSWER" if outcome == "correct" else "WRONG",
                "input": "Clue text (6)",
                "target": "ANSWER",
                "tokens": {"input": 100, "cached_input": 20, "output": 40, "reasoning": 30},
                "metadata": {"puzzle": 1, "setter": "S", "date": "2026-01-01", "source": "Src", "number": i, "direction": "across"},
            }
            for i, outcome in enumerate(outcomes)
        },
    }


def test_cohort_has_clues_and_head_to_head():
    runs = [
        run("a/x", ["correct", "wrong_answer", "correct"]),
        run("b/y", ["correct", "correct", "wrong_length"]),
    ]
    labels = {"clues": {"clue-0": {"devices": ["anagram"], "and_lit": False}}}
    pricing = {"models": {"x": {"input": 1.0, "cached_input": 0.5, "output": 10.0}}}
    cohort = site.build_cohort("c", runs, labels, pricing)
    assert [c["answer"] for c in cohort["clue_list"]] == ["ANSWER"] * 3
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
    assert "Clue text" in site.generate_html([cohort])


def test_runs_on_a_different_clue_set_are_left_out():
    full = [run(m, ["wrong_answer", "wrong_answer", "correct"]) for m in ("a/x", "b/y")]
    partial = run("c/z", ["correct"])
    cohort = site.build_cohort("c", [*full, partial], {})
    assert [r["model"] for r in cohort["runs"]] == ["a/x", "b/y"]
    assert cohort["clues"] == 3
    assert len(cohort["clue_list"]) == 3


def test_missing_setter_is_shown_as_unknown():
    sample = run("a/x", ["correct"])
    sample["samples"]["clue-0"]["metadata"]["setter"] = None
    cohort = site.build_cohort("c", [sample], {})
    assert cohort["by_puzzle"][0]["name"] == "No 1 · ?"


def test_puzzle_link_names_its_site():
    assert site.puzzle_link_label("https://www.theguardian.com/crosswords/cryptic/30159") == "Puzzle on the Guardian"
    assert site.puzzle_link_label("https://observer.co.uk/puzzles/azed/article/azed-no-2783") == "Puzzle on the Observer"
    ft_post = "https://fifteensquared.net/2026/10/14/financial-times-18505-by-io/"
    assert site.puzzle_link_label(ft_post) == "How it parses (Fifteensquared)"
    assert site.puzzle_link_label("https://example.org/x") == "Puzzle on example.org"
    assert site.puzzle_link_label(None) is None


def test_provider_mapping():
    assert site.provider_of("codex/gpt-6-luna") == "OpenAI"
    assert site.provider_of("anthropic/claude-haiku-5-5") == "Anthropic"
    assert site.provider_of("openrouter/google/gemini") == "Google"
    assert site.provider_of("openrouter/deepseek/deepseek-v4.1-flash-1017") == "DeepSeek"
    assert site.provider_of("openrouter/moonshotai/kimi-k3.1-pro") == "Moonshot"
    assert site.provider_slot("Other") == len(site.PROVIDER_ORDER)
    assert site.provider_of("somewhere/new-model") == "Other"


def test_reasoning_split_by_result():
    sample = run("a/x", ["correct", "wrong_answer", "no_answer"])
    for i, tokens in enumerate([200, 3000, 0]):
        sample["samples"][f"clue-{i}"]["tokens"]["reasoning"] = tokens
    cohort = site.build_cohort("c", [sample], {})
    assert cohort["runs"][0]["reasoning_by_result"] == {"correct": [200], "missed": [0, 3000]}
    html = site.render_reasoning(cohort)
    assert html.count('class="rt-dot') == 3
    assert "1 (0 right)" in html


def test_reasoning_chart_skipped_without_reasoning_tokens():
    sample = run("a/x", ["correct"])
    sample["samples"]["clue-0"]["tokens"]["reasoning"] = 0
    cohort = site.build_cohort("c", [sample], {})
    assert cohort["runs"][0]["reasoning_by_result"] is None
    assert site.render_reasoning(cohort) == ""


def test_quantile_interpolates():
    assert site.quantile([0, 10], 0.5) == 5
    assert site.quantile([1, 2, 3, 4], 0.25) == 1.75


def test_remapped_effort_is_shown_with_the_requested_level():
    remapped = run("openrouter/moonshotai/kimi-k3.1-pro", ["correct"])
    remapped.update(effort="low", requested_effort="medium")
    plain = run("a/x", ["correct"])
    cohort = site.build_cohort("c", [remapped, plain], {})
    rows = {r["model"]: r for r in cohort["runs"]}
    assert rows["openrouter/moonshotai/kimi-k3.1-pro"]["label"] == "moonshotai/kimi-k3.1-pro · low"
    assert rows["openrouter/moonshotai/kimi-k3.1-pro"]["requested_effort"] == "medium"
    assert "requested_effort" not in rows["a/x"]
    assert "Requested as medium" in site.render_leaderboard(cohort)
    assert site.EFFORT_RAN_AS[("openrouter/moonshotai/kimi-k3.1-pro", "medium")] == "low"
