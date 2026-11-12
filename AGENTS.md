# Notes for coding agents

See [README.md](README.md) for setup and commands, and
[design.md](design.md) for what may be published.

## Running evals

- Every run records an explicit reasoning effort. The task sets
  `medium`; pass `--reasoning-effort <level>` for any other level. Never
  leave it to the provider: defaults differ by model and release and are
  not written to the log, and leaderboard rows are keyed by
  (cohort, model, effort).
- Claude 4.7+ models (Haiku 5.5 included) return readable thinking
  summaries only when an effort is set. Without one the log holds
  encrypted thinking blocks and the published transcripts show nothing.
- Live-track runs go to `--log-dir logs/live`, which is published in
  full. Logs anywhere else in `logs/` may hold private anchor clues and
  must stay private.
