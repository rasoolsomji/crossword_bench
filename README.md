# Cryptic Crossword Bench

Measures how well LLMs solve cryptic crossword clues on data that can't
be in their training sets. Each clue is posed on its own (no grid, no
crossing letters, no tools). See [design.md](design.md) for the threat
model and the two-track architecture, and [research.md](research.md)
for prior work.

## Setup

```bash
uv sync
```

Model credentials:

- **Claude**: put `ANTHROPIC_API_KEY=...` in `.env` (gitignored; Inspect
  loads it automatically).
- **OpenAI via a ChatGPT plan**: log in with `codex login`, then use
  `--model codex/<slug>` (e.g. `codex/gpt-6-luna`). This drives
  `codex app-server` rather than the OpenAI API — see
  [codex_provider.py](src/crossword_bench/codex_provider.py) for the
  caveats. With an API key, use Inspect's `openai/<model>` instead.

## Live track (Guardian cryptic)

```bash
uv run fetch-guardian --since 2026-11-09
```

```bash
uv run inspect eval src/crossword_bench/task.py \
  --model anthropic/claude-haiku-5-5 --max-tokens 16000 \
  -T dataset=data/live/guardian -T label=guardian-cryptic-2026-11-09..12 \
  --log-dir logs/live
```

`dataset` takes a file, directory, glob, or comma-separated list;
`label` names the cohort on the leaderboard. Models are only comparable
within a cohort, so use the same `dataset` and `label` for every model.
The task runs at `medium` reasoning effort unless you pass
`--reasoning-effort high` (etc.), so every log records the effort it
used; each effort level is its own leaderboard row.

No search or tools are given to the model, which is what keeps the live
track honest: answers are blogged within hours of publication.

## Anchor track (private London Paper set)

With `data/clues.json` present, omit `-T dataset=...`. Without it the
task falls back to the toy `data/sample_clues.json`.

## Clue labels

```bash
uv run classify-clues
```

Labels each fetched clue with its wordplay devices, following
[clue_taxonomy.md](clue_taxonomy.md). A classifier model (Claude Sonnet
by default) reads the clue, the answer and the Fifteensquared blog's
parsing of the puzzle; only the labels are stored, in `annotations/`.
Labels are assigned after the runs and never shown to the models being
evaluated.

## Results site

```bash
uv run scripts/build_leaderboard.py
```

Writes `docs/index.html` and `docs/results.json`: leaderboard with
intervals, outcome classes, accuracy against tokens and estimated cost,
head-to-head, accuracy by device and by puzzle, and a per-clue table
linking to transcripts. Cost estimates use the list prices in
[pricing.json](pricing.json); add a model there to give it a cost. The Pages workflow
bundles the Inspect log viewer from `logs/live/` on deploy, which needs
the repository's Pages source set to "GitHub Actions" (with "Deploy from
a branch" the viewer is never published and transcript links 404). To
preview the viewer locally:

```bash
uv run inspect view bundle --log-dir logs/live --output-dir docs/logs --overwrite
```

## What is published

| Path | Published | Why |
|---|---|---|
| `logs/live/*.eval` | Yes, in full | Live-track clues are already public and are never reused, so transcripts and reasoning summaries can be open. Pass `--log-dir logs/live` when running a live cohort. |
| `logs/` (anything else) | Never | Anchor-set logs embed every private clue and answer. The site shows aggregates only for these. |
| `data/clues.json`, source PDFs | Never | The private anchor set. |
| `data/live/` | No | Fetched puzzles and cached blog text; reproducible with the fetch commands. |

## Tests

```bash
uv run pytest
```
