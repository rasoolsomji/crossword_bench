# Ideas

Things worth doing that are not scheduled yet. Committed work is the
checklist under "Status / next steps" in [design.md](design.md).

## Confidence as a measured output

Ask each model how sure it is and score how well that predicts being
right.

- **Why.** In the first live cohort (Guardian, 9–12 Nov 2026) Haiku 5.5
  flagged doubt on almost every wrong answer (61 of 61 at medium effort,
  53 of 56 at high) and on few right ones. GPT-6 Luna almost never did
  (4 of 73, 5 of 44), and often gave a confident parse it had made up.
  Hedging words are partly writing style, so read confidence from an
  explicit number instead.
- **How.** Add a `CONFIDENCE: <0-100>` line (the chance the answer is
  right) after the `ANSWER:` line. The scorer parses it; a missing line
  is recorded as no confidence, not as zero.
- **Metrics.** Ranking first: do confident answers turn out right more
  often (AUROC, and accuracy on the answers the model was most sure of).
  Then calibration: do 80% answers come out right about 80% of the time
  (Brier score, reliability chart). Stated confidences are often too
  high or too low across the board but still rank answers well.
- **Cost.** It changes the prompt, so start it at a cohort boundary and
  record a prompt version in the logs. Earlier cohorts have no
  confidence data.
- **Cheaper retrofit.** A judge model could rate the hedging in existing
  final answers. That measures tone, not a probability.

## Automating the live track

A scheduled GitHub workflow can do the whole loop: fetch, run each
model, label the clues, rebuild the page, commit and deploy. Keys go in
repository secrets.

- Codex-backed runs need a local ChatGPT login and can't run in CI;
  models reached by API key (Anthropic, OpenRouter) can.
- Cap spend per run, and skip prize puzzles until their solutions are
  out (the fetcher already does).

## More crosswords: one cohort per week

Right now each cohort is stacked on the one page, newest first, which
is fine for two or three. Leave the layout until there are a few weeks
of data, but fix the unit now: one cohort per week.

- Eventual shape: a front page with the latest week plus a pooled
  all-weeks leaderboard (which is where the intervals tighten), and one
  page per week behind it.
- A pooled board is only fair over clues every listed model saw, so
  models that join late are pooled over their own weeks or shown apart.
