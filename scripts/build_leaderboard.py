#!/usr/bin/env python3
"""Build the results site (docs/) from Inspect evaluation logs.

Logs under logs/live/ are public: their clues, answers and model
responses are published in full. Logs anywhere else are private and
contribute aggregate numbers only.
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

from inspect_ai.log import read_eval_log

from crossword_bench.scorer import OUTCOMES, classify_outcome
from crossword_bench.stats import mcnemar_exact, wilson_interval

PROJECT_ROOT = Path(__file__).parent.parent
PUBLIC_DIR_NAME = "live"
MISS_GROUPS = ["correct", "wrong_answer", "near_miss", "wrong_length", "no_answer"]
GROUP_OF = {"truncated": "no_answer", "interrupted": "no_answer"}
GLYPHS = {
    "correct": "✓",
    "near_miss": "≈",
    "wrong_answer": "✗",
    "wrong_length": "↔",
    "no_answer": "∅",
}
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
            score = next(iter((sample.scores or {}).values()), None)
            answer = score.answer if score else None
            output = sample.output
            samples[str(sample.id)] = {
                "outcome": classify_outcome(
                    answer, sample.target, output.stop_reason, output.error
                ),
                "answer": answer,
                "input": sample.input,
                "target": sample.target,
                "metadata": sample.metadata or {},
            }

        run = {
            "cohort": log.eval.dataset.name or log.eval.task,
            "model": log.eval.model,
            "effort": log.eval.model_generate_config.reasoning_effort or "default",
            "created": log.eval.created,
            "public": path.parent.name == PUBLIC_DIR_NAME,
            "log_file": path.name,
            "samples": samples,
        }
        key = (run["cohort"], run["model"], run["effort"])
        if key not in latest or latest[key]["created"] < run["created"]:
            latest[key] = run
    return list(latest.values())


def summarise_run(run: dict) -> dict:
    outcomes = Counter(sample["outcome"] for sample in run["samples"].values())
    total = len(run["samples"])
    correct = outcomes["correct"]
    low, high = wilson_interval(correct, total)
    return {
        "model": run["model"],
        "effort": run["effort"],
        "label": f"{short_model(run['model'])} · {run['effort']}",
        "correct": correct,
        "total": total,
        "accuracy": correct / total,
        "ci95": [low, high],
        "outcomes": {name: outcomes[name] for name in OUTCOMES if outcomes[name]},
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
        rows.append({"name": name, "clues": len(ids), "runs": cells})
    return rows


def build_cohort(name: str, runs: list[dict], annotations: dict) -> dict:
    runs = sorted(runs, key=lambda r: -summarise_run(r)["accuracy"])
    public = all(run["public"] for run in runs)
    summaries = [summarise_run(run) for run in runs]
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
            by_puzzle[f"No {meta['puzzle']:,} · {meta.get('setter', '?')}"].append(clue_id)
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


def run_label_html(run: dict) -> str:
    return (
        f'<span class="model">{escape(short_model(run["model"]))}</span>'
        f'<span class="chip">{escape(run["effort"])}</span>'
    )


def render_leaderboard(cohort: dict) -> str:
    ticks = "".join(
        f'<span class="tick" style="left:{t}%"><i></i><b>{t}%</b></span>' for t in (0, 25, 50, 75, 100)
    )
    rows = ""
    for rank, run in enumerate(cohort["runs"], 1):
        low, high = run["ci95"]
        tip = (
            f"{run['model']} · {run['effort']} effort\n"
            f"{run['correct']} of {run['total']} correct ({pct(run['accuracy'])})\n"
            f"95% interval {pct(low)} to {pct(high)}"
        )
        rows += f"""<div class="lb-row" tabindex="0" data-tip="{escape(tip)}">
  <div class="lb-rank">{rank}</div>
  <div class="lb-name">{run_label_html(run)}</div>
  <div class="lb-plot">
    <div class="bar" style="width:{run['accuracy'] * 100:.2f}%"></div>
    <div class="whisker" style="left:{low * 100:.2f}%;width:{(high - low) * 100:.2f}%"></div>
  </div>
  <div class="lb-value"><strong>{pct(run['accuracy'])}</strong><span>{run['correct']}/{run['total']}</span></div>
</div>
"""
    return f"""<section class="card">
<h3>Leaderboard</h3>
<p class="lede">Share of clues answered exactly right. The thin line on each bar is the
95% interval: the range the score would plausibly land in on a different set of clues
of this size.</p>
<div class="lb">
{rows}<div class="lb-row lb-axis"><div></div><div></div><div class="lb-plot axis">{ticks}</div><div></div></div>
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
enumeration in the clue; a near miss has the right length and is within two letters.</p>
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
    body = ""
    for row in rows:
        name = (labels or {}).get(row["name"], row["name"])
        cells = ""
        for run, cell in zip(runs, row["runs"]):
            if not cell["total"]:
                cells += "<td>–</td>"
                continue
            share = cell["correct"] / cell["total"]
            tip = f"{name} · {run['label']}\n{cell['correct']} of {cell['total']} correct ({pct(share, 0)})"
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

    by_cohort: dict[str, list[dict]] = defaultdict(list)
    for run in load_runs(log_dir):
        by_cohort[run["cohort"]].append(run)
    cohorts = [build_cohort(name, runs, annotations) for name, runs in sorted(by_cohort.items(), reverse=True)]

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
