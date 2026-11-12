# Notes for coding agents

See [README.md](README.md) for setup and commands, and
[design.md](design.md) for what may be published.

## Running evals

- Every run records an explicit reasoning effort. The task sets
  `medium`; pass `--reasoning-effort <level>` for any other level. Never
  leave it to the provider: defaults differ by model and release and are
  not written to the log, and leaderboard rows are keyed by
  (cohort, model, effort).
- On OpenRouter, an effort the model doesn't list (`supported_efforts`
  in `/api/v1/models`) is silently run at the nearest listed level while
  the log keeps the requested one. The task refuses such runs; pass a
  listed level (Kimi K3.1 Pro and DeepSeek v4.1 Flash have no `medium`).
- The task caps output at 64,000 tokens; don't pass a lower
  `--max-tokens`. A lower cap cuts off long reasoning and scores it as
  no answer, which the Codex provider (no cap) never does, so rows stop
  being comparable.
- Claude 4.7+ models (Haiku 5.5 included) return readable thinking
  summaries only when an effort is set. Without one the log holds
  encrypted thinking blocks and the published transcripts show nothing.
- Live-track runs go to `--log-dir logs/live`, which is published in
  full. Logs anywhere else in `logs/` may hold private anchor clues and
  must stay private.
- OpenRouter runs pin one endpoint with `-M provider=...` and
  `allow_fallbacks: false` (see README). Unpinned, OpenRouter spreads
  requests across hosts serving different quantizations.
- `codex/<slug>` runs log reasoning summaries that are bold headings
  only. That is what Codex sends on a ChatGPT login, not a provider bug
  (checked against `codex exec`); see the docstring in
  [codex_provider.py](src/crossword_bench/codex_provider.py).
