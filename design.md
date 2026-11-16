# Cryptic Crossword Bench — Design

Decision record as of November 2026. Background research and source
vetting live in [research.md](research.md).

## Goal

Measure how well LLMs solve cryptic crossword clues on data that
provably cannot be in their training sets, and keep that property as
new models ship. Contamination resistance is the benchmark's entire
differentiator: 500K+ cryptic clues are already public (Cryptonite,
Decrypt, George Ho's dataset), so a new benchmark is only interesting
if its clues postdate the models it tests.

## Where model performance stands (Sep 2026)

- Older models zero-shot: near 0% (Sadallah et al. 2024); 2–16% across
  models (COLING 2025).
- GPT-4-class few-shot + CoT: GPT-4 Turbo 23.5% on Cryptonite, Claude 3
  Sonnet 12.9% (Saha et al., NAACL 2025); 5-shot GPT-4o 27.6%.
- Published SOTA: 32.5% top-1 on Cryptonite — Andrews & Witteveen
  (ICML 2025), a scaffolded pipeline (candidate LMs + wordplay
  formalized as Python + verifier), not a raw model.
- Human experts: ~99%.

No rigorous published numbers exist for current frontier reasoning
models. They are presumably well above 30%, but the clean measurement
is blocked by exactly the contamination problem this project solves.
Headroom to 99% is the pitch.

## Contamination threat model

**Memorization (training-time) is the threat that matters.**
Clue–answer pairs are unusually memorization-friendly: the clue is a
globally unique short string, the answer a single word, and any log or
dataset file places them adjacent — a ready-made cloze completion.
Contamination doesn't need to be total to ruin the leaderboard: if
genuine skill sits at 15–35%, a memorized 10% of clues swamps real
differences between models. And it is asymmetric in time — publish
today and every *future* model is tainted while today's are clean, so
scores drift upward in a way that imitates progress.

**Consequences:**

- Only clues published after a model's training cutoff are clean for
  it. Public text, GitHub included, is pretraining data, and "we run
  evals with web search disabled" is no defense for older clues: that
  blocks retrieval at eval time, not weights that already contain the
  pair.
- Raw Inspect `.eval` logs embed every sample's input and target, and
  model transcripts restate both. Publishing logs = publishing the
  clues, which is safe only once they have been used.

## Architecture: the live track

Fetch clues on the day a newspaper/hobby site publishes them, evaluate
the same day, score against the published answers. Clues postdate every
existing model's training cutoff by construction, so **everything can
be public — full logs included**: each day's clues are burned the
moment they're used, and future models training on them doesn't matter
because those models will be evaluated on future clues.

- Sources: Guardian daily cryptic (free, ~30 clues/day, structured data
  on the puzzle page), Independent, FT, Lovatts daily cryptic (the
  source Saha et al. used for their own post-cutoff contamination
  check). Single-clue hobby sites (Minute Cryptic etc.) are garnish —
  one clue/day is too thin to rank models on.
- **Web search must be disabled at eval time** — for this track that
  control is load-bearing, since the clue and, within hours, blogged
  answers (Fifteensquared etc.) are on the open web. Record eval
  timestamps.
- Models are comparable only within a cohort (same clues). New models
  enter the leaderboard from their arrival date; report a trailing
  window (e.g. 90 days) in which all listed models saw identical clues.
- Copyright: fetched puzzle files stay out of the repo. Published logs
  and the results page do carry each clue and answer alongside our
  scoring, with links back to the puzzle (see Publishing rules).
- Runs as a daily scheduled job (GitHub Action cron or equivalent).
- Prototype (Nov 2026): `fetch-guardian` pulls puzzles by date range
  into `data/live/` (gitignored), and the
  task runs a directory of them as one cohort. Each clue is posed alone,
  without the grid or crossing letters, so scores understate what a
  model could do on a full puzzle. Clues with a number before the
  enumeration usually point at another entry ("a taste of 25") and are
  skipped, as are a few fair clues the rule also catches. Guardian
  Saturday prize puzzles withhold solutions for a week and are skipped
  until then.
- Model access without API keys goes through harnesses (`codex
  app-server` for a ChatGPT plan). A harness is not a bare model: it
  injects its own context and tools that cannot all be removed. The
  Codex provider disables web search and interrupts any turn that
  starts a tool call, but treat harness-backed rows as indicative, not
  as clean API measurements.

### Publishing rules

| Public | Not published |
|---|---|
| All code, this doc, research notes | Fetched puzzle files (`data/live/`) |
| Results site: accuracy, intervals, per-clue outcomes with clue text and answers | Scratch logs elsewhere in `logs/` |
| Live-track logs in full (`logs/live/`): clues, answers, transcripts, reasoning summaries | |
| Device labels for live clues (`annotations/`) | Cached third-party blog text used to produce them |

Enforced by `.gitignore` (`data/live/`, every `.eval` outside
`logs/live/`). The Pages workflow builds the site from `logs/live/` on
every push to `main`, with a transcript viewer bundled from the same
logs.

Publishing live logs supersedes the earlier "reference clue IDs, don't
mirror the puzzle" caution: the logs do reproduce each clue and answer.
That is a deliberate trade for transparency, on the footing that solver
blogs reproduce every clue daily; revisit it if a publisher objects.

## Status / next steps

- [x] Inspect task + scorer + leaderboard + Pages deploy
- [x] Prototype live-track fetcher (Guardian) and first live cohort
      (9–12 Nov 2026, 116 clues)
- [x] Outcome classes, device labels ([clue_taxonomy.md](clue_taxonomy.md)),
      head-to-head, published live logs
- [ ] Live-track daily job; second source (Lovatts/FT/Independent)
- [ ] Human spot-check of the classifier's device labels
