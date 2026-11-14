# Cryptic Crossword Bench — Design

Decision record as of September 2026. Background research and source
vetting live in [research.md](research.md).

## Goal

Measure how well LLMs solve cryptic crossword clues on data that
provably cannot be in their training sets, and keep that property as
new models ship. Contamination resistance is the benchmark's entire
differentiator: 500K+ cryptic clues are already public (Cryptonite,
Decrypt, George Ho's dataset), so a new benchmark is only interesting
if its clues aren't scrapeable.

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

- Public GitHub is pretraining data. Repos are scraped quickly and
  weighted heavily. "We run evals with web search disabled" is no
  defense — that blocks retrieval at eval time, not weights that
  already contain the pair.
- Raw Inspect `.eval` logs embed every sample's input and target, and
  model transcripts restate both. Publishing logs = publishing the
  dataset. Only aggregates (accuracy, per-type tables, per-sample
  correct/incorrect vectors keyed by opaque IDs) are safe to publish.
- API usage is fine. Anthropic/OpenAI API traffic is not trained on by
  default; the real risk is public exposure, not evaluation. Extraction
  of the held-out set is still done with local-only OCR as
  belt-and-braces (see below).

## Architecture: two tracks

### Track 1 — Live daily track (fully public)

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

### Track 2 — The London Paper anchor (private)

The London Paper (2006–2009, defunct, physical-first, near-zero digital
footprint — see research.md for the vetting) supplies clues that no
model has seen and no scrape will find. Two uses:

1. **Static anchor set**: a fixed subset every model is evaluated on
   identically, forever. This is what the live track can't provide —
   longitudinal comparison (a 2027 model vs a 2026 model on the same
   clues). Never published; aggregates only.
2. **Rotation batches** (LiveBench-style): evaluate all current models
   on a batch, then optionally publish that batch in full for
   transparency and never reuse it. Freshness starts at publication,
   not authorship, so a batch must be evaluated before it appears
   anywhere. The PDF archive is large enough to sustain this.

### Publishing rules

| Public | Private |
|---|---|
| All code, this doc, research notes | Source PDFs |
| Aggregate results (`docs/`: accuracy, stderr, per-type tables) | Clue text + answers (`data/clues.json`) |
| Per-sample correct/incorrect vectors keyed by opaque IDs | Raw `.eval` logs and transcripts of the anchor set |
| Live-track logs in full (`logs/live/`): clues, answers, transcripts, reasoning summaries | |
| Device labels for live clues (`annotations/`) | Cached third-party blog text used to produce them |
| Optional: SHA-256 commitments of each clue+answer; a handful of sacrificed example clues; used-up rotation batches | Anything else containing clue text |

Enforced by `.gitignore` (`*.pdf`, `data/clues.json`, every `.eval`
outside `logs/live/`). The results builder treats a run as public only
if its log sits in `logs/live/`; any other cohort gets aggregate numbers
and no clue text. The Pages workflow deploys committed `docs/` plus a
transcript viewer bundled from `logs/live/`.

Publishing live logs supersedes the earlier "reference clue IDs, don't
mirror the puzzle" caution: the logs do reproduce each clue and answer.
That is a deliberate trade for transparency, on the footing that solver
blogs reproduce every clue daily; revisit it if a publisher objects.

## Dataset pipeline (August 2009 set)

`extraction/extract_crosswords.py` OCRs each page locally (pymupdf +
tesseract — no AI touches the clues) and matches day *N* clues to day
*N+1* solutions. OCR drops clue numbers on some pages, which originally
shifted ~32% of pairs onto wrong answers. Matching therefore no longer
trusts OCR'd numbers: clue texts are aligned to solution slots with an
order-preserving DP in which a clue may only occupy a slot whose answer
length matches the clue's enumeration; unvalidated fragments act as
place-holding wildcards, interior gaps are penalized, and OCR-glued
multi-clue texts are split at interior enumerations. Every emitted pair
is enumeration-consistent by construction.

Current yield: **350 matched pairs** from Aug 2009 (spot-checks solve
correctly), 97 unmatched (54 unusable fragments — recoverable by human
review against the PDFs, 31 from the month's last day whose solutions
fell outside the archive, 12 with no consistent slot). Re-run matching
without OCR via `uv run extraction/extract_crosswords.py
extraction/output/pages.json`.

Known gaps: the anchor set has no device labels (live clues are
labelled by `classify-clues` from published parsings, which the London
Paper lacks, so anchor labels would have to rest on the classifier's
own parsing); a human review pass over the
350 (OCR noise like "limber" for "climber") is worthwhile before
calling it the anchor set.

## Status / next steps

- [x] Inspect task + scorer + leaderboard + Pages deploy (aggregates only)
- [x] Extraction pipeline with realignment; 350-pair Aug 2009 set wired
      into `data/clues.json` (private)
- [ ] Human review pass over the 350 pairs; salvage fragments
- [ ] Extract remaining months from the PDF archive
- [ ] Split anchor set vs rotation stock
- [ ] First real-model runs on the anchor set
- [x] Prototype live-track fetcher (Guardian) and first live cohort
      (9–12 Nov 2026, 116 clues)
- [x] Outcome classes, device labels ([clue_taxonomy.md](clue_taxonomy.md)),
      head-to-head, published live logs
- [ ] Live-track daily job; second source (Lovatts/FT/Independent)
- [ ] Human spot-check of the classifier's device labels
- [ ] Hash commitments + opaque-ID per-sample vectors in `docs/`
