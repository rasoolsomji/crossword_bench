#!/usr/bin/env python3
"""Build leaderboard HTML from Inspect evaluation logs."""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log


def build_leaderboard(log_dir: str = "logs", output_dir: str = "docs") -> None:
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    logs = list_eval_logs(log_dir)
    if not logs:
        print(f"No eval logs found in {log_dir}/")
        # Write a placeholder page so Pages deployment doesn't fail
        (output_path / "index.html").write_text(placeholder_html())
        sys.exit(0)

    # Collect results — keep the latest run per (model, task) pair
    results: dict[str, dict] = {}

    for log_info in logs:
        log = read_eval_log(log_info.name)
        if log.status != "success":
            continue

        model = log.eval.model
        task_name = log.eval.task

        # Overall accuracy
        acc = None
        se = None
        for score_group in log.results.scores or []:
            metrics = score_group.metrics
            if "accuracy" in metrics:
                acc = metrics["accuracy"].value
            if "stderr" in metrics:
                se = metrics["stderr"].value

        if acc is None:
            continue

        # Per clue-type breakdown
        type_counts: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
        for sample in log.samples or []:
            clue_type = (sample.metadata or {}).get("clue_type", "unknown")
            for _scorer_name, score in (sample.scores or {}).items():
                type_counts[clue_type]["total"] += 1
                if score.value == "C":
                    type_counts[clue_type]["correct"] += 1

        type_accuracy = {}
        for ct, counts in type_counts.items():
            if counts["total"] > 0:
                type_accuracy[ct] = {
                    "accuracy": counts["correct"] / counts["total"],
                    "correct": counts["correct"],
                    "total": counts["total"],
                }

        created = log.eval.created or datetime.now(timezone.utc).isoformat()
        key = f"{model}|{task_name}"

        if key not in results or results[key]["created"] < created:
            results[key] = {
                "model": model,
                "task": task_name,
                "accuracy": acc,
                "stderr": se,
                "per_type": type_accuracy,
                "created": created,
            }

    sorted_results = sorted(results.values(), key=lambda x: x["accuracy"], reverse=True)

    all_types = sorted({ct for r in sorted_results for ct in r["per_type"]})

    (output_path / "index.html").write_text(generate_html(sorted_results, all_types))

    json_out = {r["model"]: {k: v for k, v in r.items() if k != "model"} for r in sorted_results}
    (output_path / "results.json").write_text(json.dumps(json_out, indent=2))

    print(f"Leaderboard written to {output_path / 'index.html'}")
    print(f"Results JSON written to {output_path / 'results.json'}")


def generate_html(sorted_results: list[dict], all_types: list[str]) -> str:
    overall_rows = ""
    for rank, r in enumerate(sorted_results, 1):
        se = f" &plusmn; {r['stderr']:.1%}" if r["stderr"] else ""
        overall_rows += (
            f"<tr><td>{rank}</td><td>{r['model']}</td>"
            f"<td>{r['task']}</td>"
            f"<td>{r['accuracy']:.1%}{se}</td>"
            f"<td>{r['created'][:10]}</td></tr>\n"
        )

    type_header = "".join(f"<th>{ct}</th>" for ct in all_types)
    type_rows = ""
    for r in sorted_results:
        cells = ""
        for ct in all_types:
            if ct in r["per_type"]:
                info = r["per_type"][ct]
                cells += f"<td>{info['accuracy']:.0%} ({info['correct']}/{info['total']})</td>"
            else:
                cells += "<td>&mdash;</td>"
        type_rows += f"<tr><td>{r['model']}</td>{cells}</tr>\n"

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
  .meta {{ color: var(--muted); font-size: .875rem; margin-top: 2rem; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<h1>Cryptic Crossword Bench</h1>
<p class="subtitle">Evaluating LLMs on cryptic crossword clues</p>

<h2>Leaderboard</h2>
<table>
<thead><tr><th>#</th><th>Model</th><th>Task</th><th>Accuracy</th><th>Date</th></tr></thead>
<tbody>
{overall_rows}
</tbody>
</table>

<h2>Accuracy by Clue Type</h2>
<table>
<thead><tr><th>Model</th>{type_header}</tr></thead>
<tbody>
{type_rows}
</tbody>
</table>

<p class="meta">Last updated: {now}</p>
</body>
</html>"""


def placeholder_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Cryptic Crossword Bench</title></head>
<body>
<h1>Cryptic Crossword Bench</h1>
<p>No evaluation results yet. Run some evals and commit the logs!</p>
</body>
</html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build leaderboard from Inspect logs")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--output-dir", default="docs")
    args = parser.parse_args()
    build_leaderboard(args.log_dir, args.output_dir)
