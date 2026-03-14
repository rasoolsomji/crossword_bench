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
