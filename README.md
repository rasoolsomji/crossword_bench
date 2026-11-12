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
  -T dataset=data/live/guardian -T label=guardian-cryptic-2026-11-09..12
```

`dataset` takes a file, directory, glob, or comma-separated list;
`label` names the cohort on the leaderboard. Models are only comparable
within a cohort, so use the same `dataset` and `label` for every model.
Add `--reasoning-effort high` (etc.) to vary effort; each effort level
is its own leaderboard row.

No search or tools are given to the model, which is what keeps the live
track honest: answers are blogged within hours of publication.

## Anchor track (private London Paper set)

With `data/clues.json` present, omit `-T dataset=...`. Without it the
task falls back to the toy `data/sample_clues.json`.

## Leaderboard

```bash
uv run scripts/build_leaderboard.py
```

Writes aggregates only to `docs/`. Never commit `logs/*.eval`,
`data/clues.json`, or the source PDFs: eval logs embed every clue and
answer.

## Tests

```bash
uv run pytest
```
