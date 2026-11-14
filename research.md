# Cryptic Crossword AI Benchmark — Research Notes

## Goal

Build an AI benchmark based on cryptic crossword clues with strong contamination resistance — clues should not already exist in model training data.

## Existing Benchmarks

### Cryptonite (Efrat et al., EMNLP 2021)
- 523,114 cryptic clues from The Times and The Telegraph (Oct 2000–Oct 2020)
- Answer-disjoint train/validation/test splits
- Included in Google's BIG-bench
- Paper: https://arxiv.org/abs/2103.01242
- Dataset: https://huggingface.co/datasets/aviaefrat/cryptonite
- GitHub: https://github.com/aviaefrat/cryptonite

### Decrypt (Rozner et al., NeurIPS 2021)
- Guardian cryptic clues with word-initial-disjoint splits
- Introduced curriculum learning datasets for training
- Paper: https://arxiv.org/abs/2104.08620
- GitHub: https://github.com/jsrozner/decrypt

### George Ho's Cryptics Dataset
- 500K+ annotated cryptic clues from blogs and digital archives
- Site: https://cryptics.georgeho.org/
- GitHub: https://github.com/eigenfoo/cryptics

## Key Evaluation Papers

### "Are LLMs Good Cryptic Crossword Solvers?" (Sadallah et al., March 2024)
- Tested LLaMA2, Mistral, ChatGPT — near 0% zero-shot accuracy
- Paper: https://arxiv.org/abs/2403.12094

### "Language Models are Crossword Solvers" (Saha et al., NAACL 2025)
- Tested Phi 3, Mistral 7B, LLaMA 2/3, Mixtral, Claude 3 Sonnet, GPT-3.5/4 Turbo
- GPT-4 Turbo: 23.5% on Cryptonite, 20.85% on Init (CoT + self-consistency)
- Claude 3 Sonnet: 12.9% on Cryptonite, 10.8% on Init
- Introduced SweepClip algorithm for full grid solving (93.1% letter accuracy on NYT Monday)
- Contamination test: post-cutoff clues (Guardian/Lovatts after May 2024) showed no performance drop
- Key weakness: LLMs struggle with length constraints (~26% wrong-length answers)
- Strongest on anagrams (74%) and homophones (100%), weakest on synonym conjugation (50%)
- Paper: https://arxiv.org/abs/2406.09043
- Code: https://github.com/espressovi/LMCrossword

### "What Makes Cryptic Crosswords Challenging for LLMs?" (Sadallah et al., COLING 2025)
- Performance 2–16% across models
- Core challenges: definition extraction, wordplay identification, reasoning
- Paper: https://arxiv.org/abs/2412.09012

### "A Reasoning-Based Approach to Cryptic Crossword Clue Solving" (Andrews & Witteveen, ICML 2025)
- LLM + Python verifier approach, claims new SOTA on Cryptonite
- Paper: https://arxiv.org/abs/2506.04824
- GitHub: https://github.com/mdda/cryptic-crossword-reasoning-verifier

### Other Related Papers
- "Proving that Cryptic Crossword Clue Answers are Correct" — verification framework: https://arxiv.org/abs/2407.08824
- "CrossWordBench" — broader crossword benchmark for LLMs and vision models: https://arxiv.org/abs/2504.00043

## Contamination Considerations

All major existing benchmarks use publicly available newspaper clues (Times, Telegraph, Guardian) that are almost certainly in training data. Cryptonite is on HuggingFace and in BIG-bench.

### Strategies for an uncontaminated benchmark
1. **Commission original clues** from professional setters (gold standard)
2. **Modify existing clues** — have setters rework wordplay for the same answer, or same wordplay type for different answers
3. **Use recent paywalled sources** — less likely scraped but not guaranteed
4. **Niche/private sources** — crossword clubs, competitions, small-circulation publications
5. **Verification filter** — test candidate clues against models before inclusion; if solved with high confidence, likely contaminated
6. **Track publication dates** — use post-training-cutoff clues (though this window shrinks over time)

### Where to find setters
- Crossword Centre community
- r/crosswords
- Freelance cryptic setters
- Crossword competition organizers (e.g., Listener Crossword series)

## The London Paper — Candidate Uncontaminated Source

### Background
The London Paper (stylised "thelondonpaper") was a free evening daily newspaper published by NI Free Newspapers Ltd (News International/News UK). Distributed Monday–Friday in central London from 4 September 2006 until 18 September 2009, when it ceased due to financial losses. Targeted young commuters with celebrity-focused, light content. We have crossword clues saved from 2008.

- Wikipedia: https://en.wikipedia.org/wiki/The_London_Paper
- Some pages on web.archive.org but poorly preserved (slow, no formatting)

### Contamination Assessment: Very Low Risk

Investigated March 2026 across multiple channels:

**Crossword blogs checked (none cover The London Paper):**
- Fifteensquared
- Big Dave's Crossword Blog
- Times for the Times

**Crossword solver databases checked (no clues attributed to The London Paper):**
- Dan Word
- Crossword Nexus
- Crossword Solver

**Academic datasets checked (not included in any):**
- Cryptonite — sources are exclusively The Times and The Telegraph
- Decrypt — sources are exclusively The Guardian
- George Ho's Cryptics Dataset (cryptics.georgeho.org) — sources are bigdave44, fifteensquared, times_xwd_times, thehinducrosswordcorner, natpostcryptic, cru_cryptics, nytimes, newyorker, thebrowser, leoedit

**Web archive and crawl data:**
- web.archive.org has some pages from thelondonpaper.com but content is poorly preserved
- No Common Crawl presence found for crossword content
- The newspaper's website was basic and likely did not publish crosswords digitally

**Forums and social media:**
- Reddit searches across r/crosswords, r/crypticcrosswords, r/london, r/unitedkingdom, r/CasualUK — zero relevant results
- No crossword forum discussions found

**Other:**
- The crossword setter is unknown to the crossword community (no pseudonym, no biographical info)
- Wikipedia article on the paper mentions no crossword content — only "Em" cartoon and "City Girl" column as notable features
- London Transport Museum holds a physical copy (accession 2009-12753), suggesting physical archives are the primary survival path
- News International (publisher) also owns The Times, but no sign The London Paper content was merged into their digital archives

### Why this source is strong
- Fits contamination strategy #4 (niche/private sources) from above
- Physical-first free newspaper with minimal web presence
- Pre-social-media archiving era (2008) — before the culture of digitizing and blogging every puzzle
- Short-lived publication (3 years) that left almost no digital trace
- Not covered by any crossword community that feeds into training data

### Open questions
- Are the clues cryptic or quick crosswords?
- How many clues are available?
- Can we verify answer correctness for all clues?

## Live-Track Sources — Survey (13 Nov 2026)

The live track runs on the Guardian daily cryptic, whose puzzle pages embed clues and solutions as JSON. This survey starts from Fifteensquared, which blogs most UK broadsheet cryptics, to look for further sources and harder ones.

### Is the Guardian too easy?

First cohort (Guardian 9–12 Nov 2026, 116 clues from four puzzles), medium-effort runs of 12 Nov:

- DeepSeek v4.1 Flash: 102/116 (88%)
- Kimi K3.1 Pro: 98/115 (85%; the run was still unfinished when read)
- No frontier model has been run yet.

Setter matters more than source. In the DeepSeek run, Carpathian's puzzle went 29/30 and Anto's 30/30, while Paul's (No 30,161) went 19/28 and held 9 of its 14 misses. A cohort without a hard setter would barely separate the top models.

### Which Guardian setters are hard

No published per-setter difficulty data turned up. As a proxy, the intros (text before the first clue) of 741 Fifteensquared posts on Guardian daily and Prize puzzles, 1 Jul 2024 – 14 Nov 2026, were scored for difficulty words (tough, tricky, difficult, struggled, …) against ease words (gentle, easy, straightforward, …), with negations ("not too tricky") and mentions of other setters discounted. This is crude: each weekday has its own blogger, so blogger habits and day of week are confounded with setter, and only the two ends of the ranking mean anything.

- **Harder** (share of posts with difficulty words minus share with ease words ≥ +20 points): Vlad (25 posts), Enigmatist (18), Fed (30), Imogen (35), Paul (94), Brockwell (35). Boatman and Harpo score as high on ≤10 posts.
- **Easier** (≤ −15 points): Maskarade (17), Alia (10), Anto (26), Carpathian (15), Vulcan (61), Pangakupu (28).
- **Not separable**: Brendan, Brummie, Kite, Omnibus, Pasquale, Philistine, Picaroon (left for the Telegraph in Jan 2025), Qaos, Tramp, Yank.

The proxy orders the first cohort's setters the same way the models did: Paul hardest, then Pasquale, then Anto and Carpathian.

Prize puzzles skew hard. Over the same window the six harder setters set 48% of Prize puzzles and the six easier ones 6%; Prize puzzles were 16% of posts. In 2025 the six harder setters had about 110 Daily Cryptic appearances between them (Paul 44, Brockwell 17, Imogen 17, Vlad 12, Enigmatist 10, Fed 10, per Fifteensquared's "Guardian Crossword Stats – 2025"), roughly two a week.

### What Fifteensquared covers

Post counts from the blog's WordPress API (`/wp-json/wp/v2/categories`) on 13 Nov 2026. Difficulty is general reputation, not measured here.

| Source | Posts | Format | Fit for clue-at-a-time |
|---|---|---|---|
| Independent (daily) | 7,339 | Blocked grid | Good, but see access |
| Guardian (daily, Prize) | 6,304 | Blocked grid | In use |
| FT (daily, Mon–Sat) | 5,947 | Blocked grid | Good, but see access; some setters are shared with the Guardian (Paul sets there as Mudd) |
| Inquisitor (i, weekly) | 1,081 | Barred, thematic | Poor: many clues carry a gimmick (extra letters, misprints), so a clue alone often has no single answer |
| Azed (Observer, weekly) | 998 | Barred, mostly plain | Good: clues stand alone, answers lean on Chambers vocabulary; special-format weeks (e.g. Printer's Devilry, Playfair) would need filtering |
| Everyman (Observer, weekly) | 963 | Blocked grid | Easier than the Guardian daily |
| Enigmatic Variations (Sunday Telegraph) | 951 | Barred, thematic | Poor, as Inquisitor |
| Guardian Quiptic | 859 | Blocked grid | Easier tier |
| Private Eye / Cyclops | 507 | Blocked grid | Low volume (fortnightly) |
| Guardian Genius (monthly) | 239 | Varies, often gimmicky | Low volume |
| Listener | 132 | Barred, thematic | Poor, as Inquisitor |
| Spectator | 54 | Barred, thematic | Poor, as Inquisitor |
| Gemelo (Observer, weekly) | 53 | Barred | About a year old; not assessed |

Beelzebub (Independent on Sunday, 387 posts) has had no posts in the past month. Times-family puzzles (Times, Sunday Times, Mephisto) are blogged on Times for the Times and Telegraph puzzles (Cryptic, Toughie) on Big Dave's Crossword Blog; both papers are paywalled and were not checked further. Lovatts, named in design.md, was not checked.

### Access

- **Guardian daily and Prize**: puzzle JSON in the page (`fetch-guardian`). Prize solutions appear a week later.
- **Guardian Genius**: each puzzle is an HTML article (e.g. `/crosswords/2026/nov/02/genius-crossword-no-281`) with an image of the empty grid, a print PDF, and a Formstack entry form in an iframe. The form carries the clues as text: `https://guardiannewsandmedia.formstack.com/forms/genius_crossword_<n>` embeds JSON in which each answer field's `label` is the clue number, text and enumeration (e.g. "1 Her exercise snubs liberal society bars (8)"), under sections headed Across and Down. Multi-word enumerations read "(6, two words)" rather than "(3,3)". There is no grid data (image and PDF only) and no answers: the page of the closed No 278 still shows the empty grid, so answers would come from Fifteensquared, which blogs each Genius after its deadline, about a month after publication. `fetch-guardian` reads none of this, and `/crosswords/genius/<n>` returns 404.
- **Independent**: hosted at puzzles.independent.co.uk on Arkadium's games platform. Neither the page nor its network calls held clue data. On 13 Nov the game page carried a banner saying the Independent Cryptic and Concise crosswords "will be discontinued on Nov. 30th"; unclear whether the puzzle ends or moves.
- **FT**: ft.com/crossword answers plain requests with a Cloudflare challenge (HTTP 403). No free PDF or data feed found.
- **Observer (Azed, Everyman, Gemelo)**: observer.co.uk (Tortoise Media since 2025). Each article page carries a puzzle uuid, and `https://content-api.slowdownwiseup.co.uk/api/mobile/v1/puzzle-data/<uuid>/file/data.json` returns grid, clues and enumerations with no login. Everyman includes per-clue answers; Azed and Gemelo withhold them until the next week's JSON, which carries the previous solution as a flat grid string. The API is undocumented.

### Terms

- observer.co.uk/robots.txt: "Any other use is not permitted, including use for large language models (LLMs)", with `Content-Signal: ai-input=no, ai-train=no` and AI crawlers (ClaudeBot, GPTBot, etc.) disallowed.
- theguardian.com/robots.txt carries the same reservation against LLM, machine-learning and AI uses, and points to <licensing@theguardian.com>.
- The live track already fetches Guardian puzzles and republishes their clues in `logs/live/`; design.md's Publishing rules treat this as revisitable if a publisher objects. Both publishers have now stated the reservation in writing.

### Fifteensquared as a source

A typical post reproduces each clue with its answer and parsing, and nearly all underline the definition (10–15 of the last 15 posts in each category above). Many use a fixed HTML layout (`fts-*` classes) with the clue, answer and parsing in set places. In the last 15 posts per category that layout was used by: FT 13, Everyman 12, Independent 9, Azed 9, Guardian 5, Inquisitor 4, Spectator 4, Enigmatic Variations 0. This could stand in for sources that can't be fetched directly (FT), at the cost of republishing a third party's transcription (blogger typos, the blog's own copyright).

### Options for more signal

1. **Score the parse, not just the answer.** Have the model state its definition and wordplay, and check them against the blog's underlined definition and parsing. Answer-only accuracy rewards guessing from the definition; this raises the ceiling without changing source, and `classify-clues` already fetches the posts.
2. **Weight toward hard setters.** Include Prize puzzles once solved (half are by the harder setters above), and report results by setter.
3. **Azed as a hard track**, with the Observer's permission, filtering special-format weeks.
4. **FT via Fifteensquared**, with the caveats above.
5. **Run a frontier model on the current cohort first.** Around 95% would mean the Guardian track is saturated whatever else changes.
