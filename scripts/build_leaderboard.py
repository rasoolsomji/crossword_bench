#!/usr/bin/env python3
"""Build the results site (docs/) from Inspect evaluation logs.

Logs under logs/live/ are public: their clues, answers and model
responses are published in full. Logs anywhere else are private and
contribute aggregate numbers only.
"""

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from inspect_ai.log import EvalLog, read_eval_log

from crossword_bench.codex_provider import DEFAULT_EFFORT as CODEX_DEFAULT_EFFORT
from crossword_bench.scorer import OUTCOMES, classify_outcome, extract_answer
from crossword_bench.stats import mcnemar_exact, wilson_interval

PROJECT_ROOT = Path(__file__).parent.parent
PUBLIC_LOG_DIR = PROJECT_ROOT / "logs" / "live"
MISS_GROUPS = ["correct", "wrong_answer", "near_miss", "wrong_length", "no_answer"]
GROUP_OF = {"truncated": "no_answer", "interrupted": "no_answer"}
GLYPHS = {
    "correct": "✓",
    "near_miss": "≈",
    "wrong_answer": "✗",
    "wrong_length": "↔",
    "no_answer": "∅",
}
PROVIDER_NAMES = {
    "codex": "OpenAI",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "vertex": "Google",
    "mistral": "Mistral",
    "grok": "xAI",
    "together": "Together",
    "deepseek": "DeepSeek",
    "moonshotai": "Moonshot",
    "meta-llama": "Meta",
    "mistralai": "Mistral",
    "x-ai": "xAI",
}
# Colour follows the provider, so this order is fixed: a new provider
# takes the slot before "Other", which stays last and neutral grey.
PROVIDER_ORDER = ["OpenAI", "Anthropic", "Google", "xAI", "Mistral", "Meta", "DeepSeek", "Moonshot", "Other"]
DEVICE_LABELS = {
    "anagram": "Anagram",
    "charade": "Charade",
    "container": "Container",
    "reversal": "Reversal",
    "hidden": "Hidden",
    "homophone": "Homophone",
    "deletion": "Deletion",
    "letter_selection": "Letter selection",
    "substitution": "Substitution",
    "double_definition": "Double definition",
    "cryptic_definition": "Cryptic definition",
    "spoonerism": "Spoonerism",
    "other": "Other",
}


def short_model(model: str) -> str:
    return model.split("/", 1)[-1]


def provider_of(model: str) -> str:
    parts = model.split("/")
    key = parts[1] if parts[0] == "openrouter" and len(parts) > 2 else parts[0]
    name = PROVIDER_NAMES.get(key.lower(), key.capitalize())
    return name if name in PROVIDER_ORDER else "Other"


def provider_slot(provider: str) -> int:
    return PROVIDER_ORDER.index(provider) + 1


# OpenRouter ran these requested efforts at another level the model lists,
# without recording which; the task now refuses such runs. Each entry was
# measured by rerunning the same clues at the listed levels.
EFFORT_RAN_AS = {
    # 10 clues: median reasoning 546 tokens at "medium", 585 at low, 1,502 at high.
    ("openrouter/moonshotai/kimi-k3.1-pro", "medium"): "low",
}


def run_effort(log: EvalLog) -> str:
    """Effort the run was made at: the task's default unless the CLI set one."""
    effort = log.plan.config.merge(log.eval.model_generate_config).reasoning_effort
    if effort:
        return effort
    # Runs from before the task always set an effort. Both providers used
    # then defaulted to medium: the codex provider's own fallback, and the
    # Anthropic API default for Haiku 5.5.
    if log.eval.model.startswith("codex/"):
        return CODEX_DEFAULT_EFFORT
    if log.eval.model == "anthropic/claude-haiku-5-5":
        return "medium"
    return "default"


def is_public_log(path: Path) -> bool:
    return path.parent.resolve() == PUBLIC_LOG_DIR.resolve()


def run_settings(log: EvalLog) -> dict:
    return {
        "max_tokens": log.plan.config.merge(log.eval.model_generate_config).max_tokens,
        "cot": bool((log.eval.task_args or {}).get("cot")),
    }


def load_runs(log_dir: Path) -> list[dict]:
    """Latest successful run per (cohort, model, effort)."""
    latest: dict[tuple, dict] = {}
    for path in sorted(log_dir.rglob("*.eval")):
        log = read_eval_log(str(path))
        if log.status != "success" or not log.samples:
            continue
        if log.eval.model.startswith("mockllm/"):
            continue

        samples = {}
        for sample in log.samples:
            if (sample.metadata or {}).get("cross_reference"):
                # Needs another entry's answer, which a clue posed on its own
                # doesn't have.
                continue
            output = sample.output
            # Re-extracted rather than read from the logged score, so scorer
            # fixes apply to logs recorded before them.
            answer = extract_answer(output.completion)
            outcome = classify_outcome(answer, sample.target, output.stop_reason, output.error)
            usage = output.usage
            samples[str(sample.id)] = {
                "tokens": {
                    "input": usage.input_tokens
                    + (usage.input_tokens_cache_read or 0)
                    + (usage.input_tokens_cache_write or 0),
                    "cached_input": usage.input_tokens_cache_read or 0,
                    "output": usage.output_tokens,
                    "reasoning": usage.reasoning_tokens or 0,
                }
                if usage
                else None,
                "outcome": outcome,
                "answer": None if outcome == "interrupted" else answer,
                "input": sample.input,
                "target": sample.target,
                "metadata": sample.metadata or {},
            }

        requested = run_effort(log)
        run = {
            "cohort": log.eval.dataset.name or log.eval.task,
            "model": log.eval.model,
            "effort": EFFORT_RAN_AS.get((log.eval.model, requested), requested),
            "requested_effort": requested,
            "created": log.eval.created,
            "public": is_public_log(path),
            "log_file": path.name,
            "settings": run_settings(log),
            "samples": samples,
        }
        key = (run["cohort"], run["model"], run["effort"])
        if key not in latest or latest[key]["created"] < run["created"]:
            if key in latest:
                warn_if_downgraded(latest[key], run)
            latest[key] = run
        elif latest[key]["created"] > run["created"]:
            warn_if_downgraded(run, latest[key])
    return list(latest.values())


def warn_if_downgraded(older: dict, newer: dict) -> None:
    """Flag a newer run that replaces a row under settings that change scores."""
    old, new = older["settings"], newer["settings"]
    lower_cap = old["max_tokens"] and (not new["max_tokens"] or new["max_tokens"] < old["max_tokens"])
    if lower_cap or old["cot"] != new["cot"]:
        print(
            f"Warning: {newer['log_file']} ({new}) replaces {older['log_file']} ({old}) "
            f"for {newer['model']} at {newer['effort']} effort in cohort {newer['cohort']}",
            file=sys.stderr,
        )


def summarise_run(run: dict, pricing: dict | None = None) -> dict:
    outcomes = Counter(sample["outcome"] for sample in run["samples"].values())
    total = len(run["samples"])
    correct = outcomes["correct"]
    low, high = wilson_interval(correct, total)
    usage = [s["tokens"] for s in run["samples"].values() if s.get("tokens")]
    tokens = None
    if usage:
        tokens = {
            kind: sum(u.get(kind, 0) for u in usage)
            for kind in ("input", "cached_input", "output", "reasoning")
        }
        tokens["output_per_clue"] = tokens["output"] / len(usage)
        tokens["input_per_clue"] = tokens["input"] / len(usage)
    cost = None
    price = (pricing or {}).get("models", {}).get(short_model(run["model"]))
    if tokens and price:
        dollars = (
            (tokens["input"] - tokens["cached_input"]) * price["input"]
            + tokens["cached_input"] * price.get("cached_input", price["input"])
            + tokens["output"] * price["output"]
        ) / 1_000_000
        cost = {"total": dollars, "per_100_clues": dollars / len(usage) * 100}
    reasoning = None
    if any(u.get("reasoning") for u in usage):
        scored = [s for s in run["samples"].values() if s.get("tokens")]
        reasoning = {
            "correct": sorted(s["tokens"]["reasoning"] for s in scored if s["outcome"] == "correct"),
            "missed": sorted(s["tokens"]["reasoning"] for s in scored if s["outcome"] != "correct"),
        }
    requested = run.get("requested_effort", run["effort"])
    return {
        "model": run["model"],
        "provider": provider_of(run["model"]),
        "effort": run["effort"],
        **({"requested_effort": requested} if requested != run["effort"] else {}),
        "label": f"{short_model(run['model'])} · {run['effort']}",
        "correct": correct,
        "total": total,
        "accuracy": correct / total,
        "ci95": [low, high],
        "outcomes": {name: outcomes[name] for name in OUTCOMES if outcomes[name]},
        "tokens": tokens,
        "reasoning_by_result": reasoning,
        "estimated_cost": cost,
        "created": run["created"],
        "log_file": run["log_file"] if run["public"] else None,
    }


def breakdown(runs: list[dict], groups: dict[str, list[str]]) -> list[dict]:
    """Per-run correct counts for each named group of clue ids."""
    rows = []
    for name, ids in groups.items():
        cells = []
        for run in runs:
            scored = [run["samples"][i] for i in ids if i in run["samples"]]
            cells.append(
                {
                    "correct": sum(s["outcome"] == "correct" for s in scored),
                    "total": len(scored),
                }
            )
        pooled = {
            "correct": sum(cell["correct"] for cell in cells),
            "total": sum(cell["total"] for cell in cells),
        }
        rows.append({"name": name, "clues": len(ids), "all_runs": pooled, "runs": cells})
    return rows


def build_cohort(name: str, runs: list[dict], annotations: dict, pricing: dict | None = None) -> dict:
    # Runs are only comparable on identical clues: keep the clue set most
    # runs share (the larger one on a tie) and leave out the rest.
    id_sets = Counter(frozenset(run["samples"]) for run in runs)
    clue_set = max(id_sets, key=lambda ids: (id_sets[ids], len(ids)))
    for run in runs:
        if frozenset(run["samples"]) != clue_set:
            print(
                f"Warning: leaving {run['log_file']} out of cohort {name}: it scored "
                f"{len(run['samples'])} clues, not the cohort's {len(clue_set)}",
                file=sys.stderr,
            )
    runs = [run for run in runs if frozenset(run["samples"]) == clue_set]
    runs = sorted(runs, key=lambda r: -summarise_run(r)["accuracy"])
    public = all(run["public"] for run in runs)
    summaries = [summarise_run(run, pricing) for run in runs]
    clue_ids = list(runs[0]["samples"])
    labels = annotations.get("clues", {})

    head_to_head = []
    for a, run_a in enumerate(runs):
        for b, run_b in enumerate(runs):
            if a >= b:
                continue
            shared = [i for i in run_a["samples"] if i in run_b["samples"]]
            hit_a = {i for i in shared if run_a["samples"][i]["outcome"] == "correct"}
            hit_b = {i for i in shared if run_b["samples"][i]["outcome"] == "correct"}
            only_a, only_b = len(hit_a - hit_b), len(hit_b - hit_a)
            head_to_head.append(
                {
                    "a": a,
                    "b": b,
                    "both": len(hit_a & hit_b),
                    "only_a": only_a,
                    "only_b": only_b,
                    "neither": len(shared) - len(hit_a | hit_b),
                    "p": mcnemar_exact(only_a, only_b),
                }
            )

    by_device: dict[str, list[str]] = defaultdict(list)
    for clue_id in clue_ids:
        for device in labels.get(clue_id, {}).get("devices", []):
            by_device[device].append(clue_id)
    device_rows = breakdown(
        runs, dict(sorted(by_device.items(), key=lambda item: -len(item[1])))
    )

    cohort = {
        "name": name,
        "public": public,
        "clues": len(clue_ids),
        "runs": summaries,
        "head_to_head": head_to_head,
        "by_device": device_rows,
    }
    if not public:
        return cohort

    metadata = {i: runs[0]["samples"][i]["metadata"] for i in clue_ids}
    by_puzzle: dict[str, list[str]] = defaultdict(list)
    for clue_id in clue_ids:
        meta = metadata[clue_id]
        if "puzzle" in meta:
            by_puzzle[f"No {meta['puzzle']:,} · {meta.get('setter') or '?'}"].append(clue_id)
    cohort["by_puzzle"] = breakdown(runs, by_puzzle)

    dates = sorted({m["date"] for m in metadata.values() if "date" in m})
    cohort["source"] = ", ".join(sorted({m["source"] for m in metadata.values() if "source" in m}))
    cohort["dates"] = [dates[0], dates[-1]] if dates else None
    cohort["puzzles"] = len(by_puzzle)

    puzzles = annotations.get("puzzles", {})
    cohort["clue_list"] = [
        {
            "id": clue_id,
            "puzzle": metadata[clue_id].get("puzzle"),
            "setter": metadata[clue_id].get("setter"),
            "ref": f"{metadata[clue_id].get('number', '')}{str(metadata[clue_id].get('direction', ''))[:1]}",
            "clue": runs[0]["samples"][clue_id]["input"],
            "answer": runs[0]["samples"][clue_id]["target"],
            "url": metadata[clue_id].get("url"),
            "parsing_url": puzzles.get(str(metadata[clue_id].get("puzzle")), {}).get("parsing_url"),
            "devices": labels.get(clue_id, {}).get("devices", []),
            "and_lit": labels.get(clue_id, {}).get("and_lit", False),
            "results": [
                {
                    "outcome": run["samples"][clue_id]["outcome"],
                    "answer": run["samples"][clue_id]["answer"],
                    "output_tokens": (run["samples"][clue_id].get("tokens") or {}).get("output"),
                }
                if clue_id in run["samples"]
                else None
                for run in runs
            ],
        }
        for clue_id in clue_ids
    ]
    return cohort


def load_annotations(directory: Path) -> dict:
    merged: dict = {"clues": {}, "puzzles": {}}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        merged["clues"].update(data.get("clues", {}))
        merged["puzzles"].update(data.get("puzzles", {}))
    return merged


# ---------------------------------------------------------------- rendering


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def compact(value: float) -> str:
    if value >= 999_500:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return f"{value:.0f}"


def run_label_html(run: dict) -> str:
    return (
        f'<span class="model">{escape(short_model(run["model"]))}</span>'
        f'<span class="chip">{escape(run["effort"])}</span>'
    )


def provider_legend(cohort: dict) -> str:
    providers = sorted({run["provider"] for run in cohort["runs"]}, key=provider_slot)
    keys = "".join(
        f'<span class="key"><i class="mark p-{provider_slot(p)}"></i>{escape(p)}</span>' for p in providers
    )
    return f'<div class="legend">{keys}</div>'


def render_leaderboard(cohort: dict) -> str:
    ticks = "".join(
        f'<span class="tick" style="left:{t}%"><i></i><b>{t}%</b></span>' for t in (0, 25, 50, 75, 100)
    )
    rows = ""
    for rank, run in enumerate(cohort["runs"], 1):
        low, high = run["ci95"]
        tip = f"{run['model']} · {run['effort']} effort\n"
        if "requested_effort" in run:
            tip += f"Requested as {run['requested_effort']}, which the model doesn't offer; OpenRouter ran it at {run['effort']}\n"
        tip += (
            f"{run['correct']} of {run['total']} correct ({pct(run['accuracy'])})\n"
            f"95% interval {pct(low)} to {pct(high)}"
        )
        tokens = run["tokens"]
        if tokens:
            tip += f"\n{tokens['output_per_clue']:,.0f} output tokens per clue"
        spent = compact(tokens["output_per_clue"]) if tokens else "–"
        rows += f"""<div class="lb-row" tabindex="0" data-tip="{escape(tip)}">
  <div class="lb-rank">{rank}</div>
  <div class="lb-name">{run_label_html(run)}</div>
  <div class="lb-plot">
    <div class="bar p-{provider_slot(run['provider'])}" style="width:{run['accuracy'] * 100:.2f}%"></div>
    <div class="whisker" style="left:{low * 100:.2f}%;width:{(high - low) * 100:.2f}%"></div>
  </div>
  <div class="lb-value"><strong>{pct(run['accuracy'])}</strong><span>{run['correct']}/{run['total']}</span></div>
  <div class="lb-value lb-tokens"><strong>{spent}</strong><span>tokens/clue</span></div>
</div>
"""
    return f"""<section class="card">
<h3>Leaderboard</h3>
<p class="lede">Share of clues answered exactly right. The thin line on each bar is a 95%
interval: {cohort['clues']} clues is a small sample, so the model's long-run accuracy could
sit anywhere in that range. It narrows as more clues are added. Tokens per clue is the
average output the model generated, reasoning included.</p>
{provider_legend(cohort)}
<div class="lb">
{rows}<div class="lb-row lb-axis"><div></div><div></div><div class="lb-plot axis">{ticks}</div><div></div><div></div></div>
</div>
</section>
"""


def render_outcomes(cohort: dict) -> str:
    legend = "".join(
        f'<span class="key"><i class="sw o-{name}"></i>{escape(OUTCOMES[name])}</span>'
        for name in MISS_GROUPS
    )
    rows = table_rows = ""
    for run in cohort["runs"]:
        grouped: Counter = Counter()
        for name, count in run["outcomes"].items():
            grouped[GROUP_OF.get(name, name)] += count
        segments = ""
        for name in MISS_GROUPS:
            count = grouped[name]
            if not count:
                continue
            share = count / run["total"]
            label = f"<b>{count}</b>" if share >= 0.07 else ""
            tip = f"{run['label']}\n{OUTCOMES[name]}: {count} of {run['total']} ({pct(share)})"
            segments += (
                f'<div class="seg o-{name}" style="flex:{count} 0 0" tabindex="0" '
                f'data-tip="{escape(tip)}">{label}</div>'
            )
        rows += f"""<div class="oc-row"><div class="lb-name">{run_label_html(run)}</div><div class="stack">{segments}</div></div>
"""
        cells = "".join(f"<td>{run['outcomes'].get(name, 0)}</td>" for name in OUTCOMES)
        table_rows += f"<tr><th>{escape(run['label'])}</th>{cells}</tr>\n"
    header = "".join(f"<th>{escape(label)}</th>" for label in OUTCOMES.values())
    return f"""<section class="card">
<h3>How answers went wrong</h3>
<p class="lede">Every response sorted into one outcome. A wrong-length answer ignores the
enumeration in the clue; a near miss has the right length and is within two letters. A
placeholder such as UNKNOWN on the answer line counts as no answer, and so do replies that
ran out of tokens or were cut off (the provider refused part way through, or the model
started to use a tool); the table splits those out.</p>
<div class="legend">{legend}</div>
<div class="oc">
{rows}</div>
<details><summary>Show as table</summary>
<div class="scroll"><table class="data">
<thead><tr><th>Run</th>{header}</tr></thead>
<tbody>
{table_rows}</tbody>
</table></div>
</details>
</section>
"""


def render_tokens(cohort: dict) -> str:
    runs = [run for run in cohort["runs"] if run["tokens"]]
    if not runs:
        return ""
    longest = max(run["tokens"]["output_per_clue"] for run in runs)
    rows = table_rows = ""
    for run in runs:
        tokens = run["tokens"]
        per_clue = tokens["output_per_clue"]
        reasoning_share = tokens["reasoning"] / tokens["output"] if tokens["output"] else 0
        per_correct = tokens["output"] / run["correct"] if run["correct"] else None
        cost = run["estimated_cost"]
        cost_text = f"${cost['per_100_clues']:.2f}" if cost else "–"
        tip = (
            f"{run['label']}\n{per_clue:,.0f} output tokens per clue\n"
            f"{pct(reasoning_share, 0)} of output was reasoning\n"
            f"{tokens['input_per_clue']:,.0f} input tokens per clue"
        )
        if cost:
            tip += f"\nAbout {cost_text} per 100 clues at list prices"
        rows += f"""<div class="tk-row" tabindex="0" data-tip="{escape(tip)}">
  <div class="lb-name">{run_label_html(run)}</div>
  <div class="tk-plot"><div class="bar p-{provider_slot(run['provider'])}" style="width:{per_clue / longest * 100:.2f}%"></div></div>
  <div class="lb-value"><strong>{per_clue:,.0f}</strong><span>{pct(reasoning_share, 0)} reasoning</span></div>
</div>
"""
        table_rows += (
            f"<tr><th>{escape(run['label'])}</th><td>{per_clue:,.0f}</td>"
            f"<td>{pct(reasoning_share, 0)}</td><td>{tokens['input_per_clue']:,.0f}</td>"
            f"<td>{tokens['output']:,}</td><td>{tokens['input']:,}</td>"
            f"<td>{f'{per_correct:,.0f}' if per_correct else '–'}</td><td>{cost_text}</td></tr>\n"
        )
    return f"""<section class="card">
<h3>Tokens spent</h3>
<p class="lede">Average output tokens per clue, reasoning included. Reasoning is what the
provider bills as thinking, whether or not it returns the text. Input tokens are mostly the
prompt: runs through an agent harness carry a few thousand extra per clue. Estimated cost
prices every token the run used at the provider's API list price.</p>
<div class="tk">
{rows}</div>
<details><summary>Show as table</summary>
<div class="scroll"><table class="data">
<thead><tr><th>Run</th><th>Output per clue</th><th>Reasoning share</th><th>Input per clue</th><th>Total output</th><th>Total input</th><th>Output per correct answer</th><th>Est. cost per 100 clues</th></tr></thead>
<tbody>
{table_rows}</tbody>
</table></div>
</details>
</section>
"""


def quantile(values: list[float], q: float) -> float:
    position = (len(values) - 1) * q
    below = math.floor(position)
    above = min(below + 1, len(values) - 1)
    return values[below] + (values[above] - values[below]) * (position - below)


def render_reasoning(cohort: dict) -> str:
    runs = [run for run in cohort["runs"] if run.get("reasoning_by_result")]
    positive = [v for run in runs for lane in run["reasoning_by_result"].values() for v in lane if v > 0]
    if not positive:
        return ""
    low, high, ticks = log_axis(positive)
    span = math.log(high / low)
    zero_width = 8  # percent of the plot kept for clues with no reasoning

    def x_of(value: float) -> float:
        if value <= 0:
            return zero_width / 2 - 1
        return zero_width + (100 - zero_width) * math.log(value / low) / span

    gridlines = '<span class="rt-zero"></span>' + "".join(
        f'<span class="rt-gx" style="left:{x_of(t):.2f}%"></span>' for t in ticks
    )
    lanes = [("correct", "right", "Right answer"), ("missed", "missed", "Missed")]
    rows = table_rows = ""
    for run in runs:
        by_result = run["reasoning_by_result"]
        cells = f'<div class="lb-name">{run_label_html(run)}</div>'
        for key, lane_label, name in lanes:
            values = by_result[key]
            dots = ""
            for i, value in enumerate(values):
                # Golden-ratio offsets spread neighbouring values across the
                # lane height so dense clusters stay readable.
                top = 18 + ((i * 0.618034) % 1) * 64
                # The 0 column has no scale, so its dots also spread sideways
                # to show how many there are.
                left = 1 + ((i * 0.381966) % 1) * 4 if value <= 0 else x_of(value)
                dots += (
                    f'<span class="rt-dot o-{"correct" if key == "correct" else "wrong_answer"}" '
                    f'style="left:{left:.2f}%;top:{top:.1f}%" '
                    f'data-tip="{escape(run["label"])}&#10;{name}: {value:,} reasoning tokens"></span>'
                )
            median_text = "–"
            if values:
                median = quantile(values, 0.5)
                median_text = compact(median)
                tip = f"{run['label']}\n{name}s: median {median:,.0f} reasoning tokens over {len(values)} clues"
                dots += (
                    f'<span class="rt-med" style="left:{x_of(median):.2f}%" tabindex="0" '
                    f'data-tip="{escape(tip)}"></span>'
                )
            cells += (
                f'<div class="rt-lane-name">{lane_label}</div>'
                f'<div class="rt-lane">{gridlines}{dots}</div>'
                f'<div class="rt-median">{median_text}</div>'
            )
        rows += f'<div class="rt-row">{cells}</div>\n'

        def spread(values: list[int]) -> tuple[str, str]:
            if not values:
                return "–", "–"
            return (
                f"{quantile(values, 0.5):,.0f}",
                f"{quantile(values, 0.25):,.0f} to {quantile(values, 0.75):,.0f}",
            )

        right, missed = by_result["correct"], by_result["missed"]
        no_reasoning = right.count(0) + missed.count(0)
        table_rows += (
            f"<tr><th>{escape(run['label'])}</th><td>{len(right)}</td>"
            + "".join(f"<td>{cell}</td>" for cell in spread(right))
            + f"<td>{len(missed)}</td>"
            + "".join(f"<td>{cell}</td>" for cell in spread(missed))
            + f"<td>{no_reasoning} ({right.count(0)} right)</td></tr>\n"
        )
    axis = '<span class="tick" style="left:{:.2f}%"><b>0</b></span>'.format(x_of(0)) + "".join(
        f'<span class="tick{"" if math.log10(t).is_integer() else " minor"}" style="left:{x_of(t):.2f}%">'
        f"<b>{compact(t)}</b></span>"
        for t in ticks
    )
    return f"""<section class="card">
<h3>Reasoning on right and missed answers</h3>
<p class="lede">Reasoning tokens spent on each clue, split by whether the answer was right.
Each dot is one clue and the dark line is the median; clues answered with no reasoning at all
sit in the 0 column. Hard clues take longer and are also missed more, so a long trace marks a
hard clue rather than showing that more thinking hurts.</p>
<div class="legend"><span class="key"><i class="sw o-correct"></i>Right answer</span><span class="key"><i class="sw o-wrong_answer"></i>Missed (any other outcome)</span><span class="key"><i class="rt-key"></i>Median</span></div>
<div class="rt">
<div class="rt-row rt-head"><div></div><div></div><div></div><div class="rt-median">median</div></div>
{rows}<div class="rt-row rt-axis"><div></div><div></div><div class="lb-plot axis">{axis}</div><div></div></div>
<p class="sc-axis">Reasoning tokens per clue (log scale)</p>
</div>
<details><summary>Show as table</summary>
<div class="scroll"><table class="data">
<thead><tr><th>Run</th><th>Right</th><th>Median</th><th>Middle half</th><th>Missed</th><th>Median</th><th>Middle half</th><th>No reasoning</th></tr></thead>
<tbody>
{table_rows}</tbody>
</table></div>
</details>
</section>
"""


def log_axis(values: list[float]) -> tuple[float, float, list[float]]:
    low, high = min(values) / 1.7, max(values) * 1.7
    ticks = [
        m * 10**e
        for e in range(math.floor(math.log10(low)), math.ceil(math.log10(high)) + 1)
        for m in (1, 2, 5)
        if low <= m * 10**e <= high
    ]
    return low, high, ticks


def place_labels(labels: list[dict], points: list[dict], width: float = 300, height: float = 260) -> None:
    """Pick a side for each label so labels avoid the marks and each other.

    Works in approximate pixels for a narrow plot; the real plot is fluid
    and usually wider, so this is a best effort that the tooltip and
    table back up.
    """
    def overlaps(a, b, slack=2):
        return (
            a[0] + slack < b[2] and b[0] + slack < a[2] and a[1] + slack < b[3] and b[1] + slack < a[3]
        )

    marks = [(p["x"] * width - 7, p["y"] * height - 7, p["x"] * width + 7, p["y"] * height + 7) for p in points]
    placed: list[tuple] = []
    for label in labels:
        px, py = label["point"]["x"] * width, label["point"]["y"] * height
        w, h = len(label["text"]) * 6.6 + 4, 16
        offsets = {
            "r": (px + 11, py - h / 2),
            "l": (px - 11 - w, py - h / 2),
            "a": (px - w / 2, py + 11),
            "b": (px - w / 2, py - 11 - h),
            "al": (px - w + 6, py + 11),
            "bl": (px - w + 6, py - 11 - h),
            "ar": (px - 6, py + 11),
            "br": (px - 6, py - 11 - h),
        }
        label["side"] = label["prefer"][0]
        for side in label["prefer"]:
            x0, y0 = offsets[side]
            box = (x0, y0, x0 + w, y0 + h)
            if box[0] < 0 or box[2] > width or box[1] < 0 or box[3] > height:
                continue
            if any(overlaps(box, other) for other in [*marks, *placed]):
                continue
            label["side"] = side
            placed.append(box)
            break


def render_scatter(cohort: dict, title: str, axis_title: str, value_of, tick_label) -> str:
    runs = [run for run in cohort["runs"] if value_of(run) is not None]
    if not runs:
        return ""
    low, high, ticks = log_axis([value_of(run) for run in runs])
    span = math.log(high / low)
    points = [
        {
            "run": run,
            "x": math.log(value_of(run) / low) / span,
            "y": run["accuracy"],
            "label": run["effort"],
        }
        for run in runs
    ]
    # One line per model joins its effort levels. The model is named once,
    # at the end of its line; each point carries only its effort.
    by_model: dict[str, list[dict]] = defaultdict(list)
    for point in points:
        by_model[point["run"]["model"]].append(point)
    lines = ""
    labels = []
    for model, group in by_model.items():
        group.sort(key=lambda p: p["x"])
        labels.append(
            {
                "point": group[-1],
                "text": short_model(model),
                "kind": "name",
                "prefer": ["al", "a", "ar", "bl", "b", "br", "l", "r"],
            }
        )
        slot = provider_slot(group[0]["run"]["provider"])
        for start, end in zip(group, group[1:]):
            lines += (
                f'<line class="p-{slot}" x1="{start["x"] * 100:.2f}" y1="{100 - start["y"] * 100:.2f}" '
                f'x2="{end["x"] * 100:.2f}" y2="{100 - end["y"] * 100:.2f}" vector-effect="non-scaling-stroke"/>'
            )
    labels += [
        {"point": point, "text": point["label"], "kind": "effort", "prefer": ["b", "a", "r", "l", "br", "bl", "ar", "al"]}
        for point in sorted(points, key=lambda p: p["x"])
    ]
    place_labels(labels, points)

    marks = f'<svg class="sc-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">{lines}</svg>'
    for point in points:
        run = point["run"]
        slot = provider_slot(run["provider"])
        ci_low, ci_high = run["ci95"]
        tip = (
            f"{run['label']} ({run['provider']})\n{pct(run['accuracy'])} accuracy\n"
            f"{axis_title.split(' (')[0]}: {tick_label(value_of(run))}"
        )
        position = f"left:{point['x'] * 100:.2f}%;bottom:{point['y'] * 100:.2f}%"
        marks += (
            f'<span class="sc-ci" style="left:{point["x"] * 100:.2f}%;bottom:{ci_low * 100:.2f}%;'
            f'height:{(ci_high - ci_low) * 100:.2f}%"></span>'
            f'<span class="sc-pt" style="{position}" tabindex="0" data-tip="{escape(tip)}">'
            f'<i class="mark p-{slot}"></i></span>'
        )
    for label in labels:
        point = label["point"]
        marks += (
            f'<span class="sc-label {label["kind"]} side-{label["side"]}" '
            f'style="left:{point["x"] * 100:.2f}%;bottom:{point["y"] * 100:.2f}%">{escape(label["text"])}</span>'
        )
    grid = "".join(
        f'<span class="sc-gy" style="bottom:{t}%"><b>{t}%</b></span>' for t in (0, 25, 50, 75, 100)
    )
    grid += "".join(
        f'<span class="sc-gx" style="left:{math.log(t / low) / span * 100:.2f}%"><b>{tick_label(t)}</b></span>'
        for t in ticks
    )
    return f"""<figure class="sc">
<figcaption>{escape(title)}</figcaption>
<div class="sc-plot">{grid}{marks}</div>
<p class="sc-axis">{escape(axis_title)}</p>
</figure>
"""


def render_tradeoff(cohort: dict) -> str:
    def dollars(value: float) -> str:
        return f"${value:.2f}" if value >= 0.1 else f"${value:.3f}".rstrip("0")

    tokens = render_scatter(
        cohort,
        "Accuracy against tokens",
        "Output tokens per clue (log scale)",
        lambda run: run["tokens"]["output_per_clue"] if run["tokens"] else None,
        compact,
    )
    cost = render_scatter(
        cohort,
        "Accuracy against estimated cost",
        "Estimated cost per 100 clues (log scale)",
        lambda run: run["estimated_cost"]["per_100_clues"] if run["estimated_cost"] else None,
        dollars,
    )
    if not tokens and not cost:
        return ""
    return f"""<section class="card">
<h3>What accuracy costs</h3>
<p class="lede">Up and to the left is better: more clues solved for less. Colour and shape
show the provider, and a line joins one model's effort levels. Vertical lines are the same 95%
intervals as the leaderboard. Cost is an estimate from API list prices, so it can rank models
differently from raw token counts.</p>
{provider_legend(cohort)}
<div class="sc-grid">
{tokens}{cost}</div>
</section>
"""


def render_head_to_head(cohort: dict) -> str:
    runs = cohort["runs"]
    if len(runs) < 2:
        return ""
    pairs = {}
    for pair in cohort["head_to_head"]:
        pairs[(pair["a"], pair["b"])] = (pair["only_a"], pair["only_b"], pair)
        pairs[(pair["b"], pair["a"])] = (pair["only_b"], pair["only_a"], pair)
    header = "".join(
        f'<th><span class="model">{escape(short_model(r["model"]))}</span><span class="chip">{escape(r["effort"])}</span></th>'
        for r in runs
    )
    rows = ""
    for a, run_a in enumerate(runs):
        cells = ""
        for b, run_b in enumerate(runs):
            if a == b:
                cells += '<td class="self">–</td>'
                continue
            wins, losses, pair = pairs[(a, b)]
            net = wins - losses
            tint = max(0, net) / cohort["clues"] * 100 * 1.6
            significant = pair["p"] < 0.05
            tip = (
                f"{run_a['label']} vs {run_b['label']}\n"
                f"Only {short_model(run_a['model'])} ({run_a['effort']}) solved: {wins}\n"
                f"Only {short_model(run_b['model'])} ({run_b['effort']}) solved: {losses}\n"
                f"Both solved: {pair['both']} · neither: {pair['neither']}\n"
                f"p = {pair['p']:.3f} (exact McNemar)"
            )
            cells += (
                f'<td tabindex="0" data-tip="{escape(tip)}" class="{"sig" if significant else ""}" '
                f'style="--tint:{tint:.1f}%"><b>{wins}–{losses}</b>'
                f'<span>{"+" if net > 0 else ""}{net}{" *" if significant else ""}</span></td>'
            )
        rows += f"<tr><th>{run_label_html(run_a)}</th>{cells}</tr>\n"
    return f"""<section class="card">
<h3>Head to head</h3>
<p class="lede">Each cell counts only the clues where the two runs disagree: clues the row
solved and the column missed, then the reverse. Shading shows the row's net lead.
A star marks a lead unlikely to be chance (p &lt; 0.05).</p>
<div class="scroll"><table class="matrix">
<thead><tr><th></th>{header}</tr></thead>
<tbody>
{rows}</tbody>
</table></div>
</section>
"""


def render_heat_table(title: str, lede: str, first_header: str, rows: list[dict], runs: list[dict], labels: dict | None = None) -> str:
    if not rows:
        return ""
    header = "".join(
        f'<th><span class="model">{escape(short_model(r["model"]))}</span><span class="chip">{escape(r["effort"])}</span></th>'
        for r in runs
    )
    header = '<th class="all"><span class="model">All runs</span><span class="chip">pooled</span></th>' + header
    body = ""
    for row in rows:
        name = (labels or {}).get(row["name"], row["name"])
        cells = ""
        columns = [({"label": "all runs pooled"}, row["all_runs"]), *zip(runs, row["runs"])]
        for position, (run, cell) in enumerate(columns):
            if not cell["total"]:
                cells += "<td>–</td>"
                continue
            share = cell["correct"] / cell["total"]
            tip = f"{name} · {run['label']}\n{cell['correct']} of {cell['total']} correct ({pct(share, 0)})"
            if position == 0:
                cells += (
                    f'<td class="all" tabindex="0" data-tip="{escape(tip)}" style="--tint:{share * 55:.1f}%">'
                    f"<b>{pct(share, 0)}</b></td>"
                )
                continue
            cells += (
                f'<td tabindex="0" data-tip="{escape(tip)}" style="--tint:{share * 55:.1f}%">'
                f"<b>{pct(share, 0)}</b><span>{cell['correct']}/{cell['total']}</span></td>"
            )
        body += f'<tr><th>{escape(name)}<span class="n">{row["clues"]}</span></th>{cells}</tr>\n'
    return f"""<section class="card">
<h3>{escape(title)}</h3>
<p class="lede">{lede}</p>
<div class="scroll"><table class="matrix heat">
<thead><tr><th>{escape(first_header)}<span class="n">clues</span></th>{header}</tr></thead>
<tbody>
{body}</tbody>
</table></div>
</section>
"""


def render_explorer(index: int, cohort: dict) -> str:
    if not cohort.get("clue_list"):
        return ""
    key = "".join(
        f'<span class="key"><i class="glyph g-{name}">{GLYPHS[name]}</i>{escape(OUTCOMES[name])}</span>'
        for name in MISS_GROUPS
    )
    return f"""<section class="card explorer" data-cohort="{index}">
<h3>Every clue</h3>
<p class="lede">Select a row to see each run's answer and open its full transcript, including
the reasoning summary the model returned.</p>
<div class="filters">
  <label>Device <select data-filter="device"></select></label>
  <label>Puzzle <select data-filter="puzzle"></select></label>
  <label>Result <select data-filter="result">
    <option value="">All clues</option>
    <option value="all">Solved by every run</option>
    <option value="none">Solved by none</option>
    <option value="split">Runs disagree</option>
  </select></label>
  <label><input type="checkbox" data-hide-answers>Hide answers</label>
  <span class="count" aria-live="polite"></span>
</div>
<div class="legend">{key}</div>
<div class="scroll"><table class="clues">
<thead></thead>
<tbody></tbody>
</table></div>
</section>
"""


def describe_cohort(cohort: dict) -> str:
    parts = []
    if cohort.get("source"):
        parts.append(escape(cohort["source"]))
    if cohort.get("dates"):
        first, last = (date.fromisoformat(d) for d in cohort["dates"])
        if first == last:
            parts.append(f"{first.day} {first:%b %Y}")
        elif (first.year, first.month) == (last.year, last.month):
            parts.append(f"{first.day}–{last.day} {last:%b %Y}")
        else:
            parts.append(f"{first.day} {first:%b} – {last.day} {last:%b %Y}")
    if cohort.get("puzzles"):
        parts.append(f"{cohort['puzzles']} puzzles")
    parts.append(f"{cohort['clues']} clues")
    if not cohort["public"]:
        parts.append("private set: aggregates only")
    return " · ".join(parts)


def render_cohort(index: int, cohort: dict) -> str:
    runs = cohort["runs"]
    return f"""<section class="cohort" id="cohort-{index}">
<header class="cohort-head">
  <h2>{describe_cohort(cohort)}</h2>
  <p class="muted">Cohort <code>{escape(cohort['name'])}</code>. Runs are comparable only within a cohort.</p>
</header>
{render_leaderboard(cohort)}
{render_outcomes(cohort)}
{render_tradeoff(cohort)}
{render_tokens(cohort)}
{render_reasoning(cohort)}
{render_head_to_head(cohort)}
{render_heat_table("By wordplay device", 'Accuracy on the clues that use each device. A clue using several devices counts under each. Labels follow the <a href="https://github.com/rasoolsomji/crossword_bench/blob/main/clue_taxonomy.md">clue taxonomy</a> and were assigned by a classifier model from published human parsings, so treat small rows with care.', "Device", cohort["by_device"], runs, DEVICE_LABELS)}
{render_heat_table("By puzzle", "Accuracy on each puzzle. Setters differ a lot in style and difficulty.", "Puzzle", cohort.get("by_puzzle", []), runs)}
{render_explorer(index, cohort)}
</section>
"""


def generate_html(cohorts: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = "".join(render_cohort(i, cohort) for i, cohort in enumerate(cohorts))
    if not cohorts:
        body = '<section class="card"><p>No evaluation results yet.</p></section>'
    explorer_data = [
        {
            "runs": [
                {"label": r["label"], "model": short_model(r["model"]), "effort": r["effort"], "log": r["log_file"]}
                for r in cohort["runs"]
            ],
            "clues": cohort.get("clue_list", []),
        }
        for cohort in cohorts
    ]
    data_json = json.dumps(
        {
            "cohorts": explorer_data,
            "outcomes": OUTCOMES,
            "groupOf": GROUP_OF,
            "glyphs": GLYPHS,
            "devices": DEVICE_LABELS,
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    return (
        PAGE_TEMPLATE.replace("__BODY__", body)
        .replace("__DATA__", data_json)
        .replace("__UPDATED__", now)
    )


PAGE_TEMPLATE = (Path(__file__).parent / "results_page.html").read_text()


def build(log_dir: Path, annotations_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    annotations = load_annotations(annotations_dir)
    pricing_path = PROJECT_ROOT / "pricing.json"
    pricing = json.loads(pricing_path.read_text()) if pricing_path.exists() else None

    by_cohort: dict[str, list[dict]] = defaultdict(list)
    for run in load_runs(log_dir):
        by_cohort[run["cohort"]].append(run)
    cohorts = [
        build_cohort(name, runs, annotations, pricing)
        for name, runs in sorted(by_cohort.items(), reverse=True)
    ]

    (output_dir / "index.html").write_text(generate_html(cohorts))
    (output_dir / "results.json").write_text(
        json.dumps({"cohorts": cohorts}, indent=1, ensure_ascii=False) + "\n"
    )
    print(f"{len(cohorts)} cohort(s) written to {output_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "logs")
    parser.add_argument("--annotations-dir", type=Path, default=PROJECT_ROOT / "annotations")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "docs")
    args = parser.parse_args()
    build(args.log_dir, args.annotations_dir, args.output_dir)
