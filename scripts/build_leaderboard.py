#!/usr/bin/env python3
"""Build leaderboard HTML from Inspect evaluation logs."""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log


def build_leaderboard(log_dir: str = "logs", output_dir: str = "docs") -> None:
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Keep the latest successful run per (cohort, model, effort)
    results: dict[tuple, dict] = {}

    for log_info in list_eval_logs(log_dir):
        log = read_eval_log(log_info.name)
        if log.status != "success" or log.results is None:
            continue

        metrics = {}
        for score_group in log.results.scores or []:
            metrics.update(score_group.metrics)
        if "accuracy" not in metrics:
            continue

        type_counts: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
        failures: dict[str, int] = defaultdict(int)
        for sample in log.samples or []:
            for score in (sample.scores or {}).values():
                clue_type = (score.metadata or {}).get("clue_type", "unknown")
                type_counts[clue_type]["total"] += 1
                if score.value == "C":
                    type_counts[clue_type]["correct"] += 1
                else:
                    failures[(score.metadata or {}).get("failure") or "wrong_answer"] += 1

        per_type = {
            clue_type: {**counts, "accuracy": counts["correct"] / counts["total"]}
            for clue_type, counts in type_counts.items()
        }

        result = {
            "cohort": log.eval.dataset.name or log.eval.task,
            "model": log.eval.model,
            "reasoning_effort": log.eval.model_generate_config.reasoning_effort,
            "accuracy": metrics["accuracy"].value,
            "stderr": metrics["stderr"].value if "stderr" in metrics else None,
            "samples": log.results.completed_samples,
            "failures": dict(failures),
            "per_type": per_type,
            "created": log.eval.created,
        }
        key = (result["cohort"], result["model"], result["reasoning_effort"])
        if key not in results or results[key]["created"] < result["created"]:
            results[key] = result

    if not results:
        print(f"No successful eval logs found in {log_dir}/")
        (output_path / "index.html").write_text(placeholder_html())
        return

    # Models are only comparable within a cohort (identical clues).
    sorted_results = sorted(results.values(), key=lambda r: (r["cohort"], -r["accuracy"]))
    all_types = sorted({ct for r in sorted_results for ct in r["per_type"]} - {"unknown"})

    (output_path / "index.html").write_text(generate_html(sorted_results, all_types))
    (output_path / "results.json").write_text(json.dumps(sorted_results, indent=2) + "\n")

    print(f"Leaderboard written to {output_path / 'index.html'}")
    print(f"Results JSON written to {output_path / 'results.json'}")


def model_label(result: dict) -> str:
    label = escape(result["model"])
    if result["reasoning_effort"]:
        label += f" <span class=\"muted\">({escape(result['reasoning_effort'])})</span>"
    return label


def generate_html(sorted_results: list[dict], all_types: list[str]) -> str:
    cohorts: dict[str, list[dict]] = defaultdict(list)
    for result in sorted_results:
        cohorts[result["cohort"]].append(result)

    sections = ""
    for cohort, cohort_results in cohorts.items():
        rows = ""
        for rank, r in enumerate(cohort_results, 1):
            se = f" &plusmn; {r['stderr']:.1%}" if r["stderr"] else ""
            wrong_length = r["failures"].get("wrong_length", 0)
            no_answer = r["failures"].get("no_answer", 0)
            rows += (
                f"<tr><td>{rank}</td><td>{model_label(r)}</td>"
                f"<td>{r['accuracy']:.1%}{se}</td><td>{r['samples']}</td>"
                f"<td>{wrong_length}</td><td>{no_answer}</td>"
                f"<td>{r['created'][:10]}</td></tr>\n"
            )
        sections += f"""<h2>{escape(cohort)}</h2>
<table>
<thead><tr><th>#</th><th>Model</th><th>Accuracy</th><th>Clues</th><th>Wrong length</th><th>No answer</th><th>Run date</th></tr></thead>
<tbody>
{rows}</tbody>
</table>
"""

    if all_types:
        type_header = "".join(f"<th>{escape(ct)}</th>" for ct in all_types)
        type_rows = ""
        for r in sorted_results:
            if not any(ct in r["per_type"] for ct in all_types):
                continue
            cells = ""
            for ct in all_types:
                if ct in r["per_type"]:
                    info = r["per_type"][ct]
                    cells += f"<td>{info['accuracy']:.0%} ({info['correct']}/{info['total']})</td>"
                else:
                    cells += "<td>&mdash;</td>"
            type_rows += f"<tr><td>{model_label(r)}</td><td>{escape(r['cohort'])}</td>{cells}</tr>\n"
        sections += f"""<h2>Accuracy by clue type</h2>
<table>
<thead><tr><th>Model</th><th>Cohort</th>{type_header}</tr></thead>
<tbody>
{type_rows}</tbody>
</table>
"""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cryptic Crossword Bench</title>
<style>
  :root {{
    --bg: #fafafa; --fg: #1a1a1a; --accent: #2563eb;
    --border: #e5e7eb; --muted: #6b7280; --cell: #fff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #111; --fg: #e5e7eb; --accent: #60a5fa;
      --border: #333; --muted: #9ca3af; --cell: #1a1a1a;
    }}
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg); color: var(--fg);
    max-width: 1000px; margin: 0 auto; padding: 2rem 1rem; line-height: 1.6;
  }}
  h1 {{ margin-bottom: .25rem; }}
  .subtitle {{ color: var(--muted); margin-bottom: 2rem; }}
  h2 {{ margin: 2rem 0 1rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 1rem; }}
  th, td {{ padding: .5rem .75rem; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ font-weight: 600; }}
  td {{ background: var(--cell); }}
  tr:hover td {{ background: var(--border); }}
  .muted {{ color: var(--muted); }}
  .meta {{ color: var(--muted); font-size: .875rem; margin-top: 2rem; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<h1>Cryptic Crossword Bench</h1>
<p class="subtitle">Evaluating LLMs on cryptic crossword clues, one clue at a time, no grid, no tools.</p>

<p class="subtitle">Models are comparable only within a cohort: each table is one fixed set of clues.</p>

{sections}
<p class="meta">Last updated: {now}</p>
</body>
</html>"""


def placeholder_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Cryptic Crossword Bench</title></head>
<body>
<h1>Cryptic Crossword Bench</h1>
<p>No evaluation results yet.</p>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build leaderboard from Inspect logs")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--output-dir", default="docs")
    args = parser.parse_args()
    build_leaderboard(args.log_dir, args.output_dir)
