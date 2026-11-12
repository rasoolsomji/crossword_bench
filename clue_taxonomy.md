# Clue taxonomy

The rubric used to label each clue with the wordplay devices it relies
on. Labels are assigned after the fact by a classifier model
(`classify-clues`) that sees the clue, its answer and, where one exists,
a published human parsing of the puzzle. They are never shown to the
models being evaluated. This file is the classifier's instructions, so
edits here change the labels: bump the version when you change a rule.

Version: 1

## Devices

A clue gets every device a solver must apply to reach the answer.

| Label | Use when |
|---|---|
| `anagram` | Letters of some fodder are rearranged. There is an anagram indicator. |
| `charade` | The answer is two or more parts joined in sequence. |
| `container` | One part is placed inside or around another. |
| `reversal` | A part, or the whole answer, is read backwards (or upwards in a down clue). |
| `hidden` | The answer sits as consecutive letters across the words of the clue. A hidden answer that is also reversed gets `hidden` and `reversal`. |
| `homophone` | The answer, or a part, sounds like another word or phrase. |
| `deletion` | Letters are removed from a word: beheading, curtailing, removing the middle, or subtracting a named string. |
| `letter_selection` | Letters are picked by position: first letters, last letters, alternate letters, middle letters. Acrostics belong here. |
| `substitution` | One letter or string in a word is swapped for another. |
| `double_definition` | Two or more definitions side by side and no other wordplay. |
| `cryptic_definition` | One misleading or punning definition of the whole answer and no other wordplay. |
| `spoonerism` | The initial sounds of two words are exchanged. |
| `other` | Wordplay that fits none of the above: reverse clues (the answer describes the wordplay), visual or typographic tricks, and one-off novelties. |

## Rules

1. Label what the solver has to do, not what the surface reading
   suggests. A clue that mentions mixing but contains no anagram is not
   an anagram.
2. Standard abbreviations and single-word synonyms are not devices.
   "Learner" for L, or "worker" for ANT, labels nothing on its own. One
   synonym is not a `charade`; a charade needs at least two parts joined.
3. Include devices applied to a part. A charade whose second part is a
   reversed word gets `charade` and `reversal`.
4. Taking one letter by position ("head of state" for S) is
   `letter_selection` only when it is the main way a part is produced
   from a longer word; treat conventional single-letter abbreviations
   under rule 2.
5. `double_definition` and `cryptic_definition` are exclusive of the
   wordplay devices: if there is wordplay, label the wordplay instead.

## Primary device

Each clue also gets one `primary` device: the outermost operation that
assembles the final answer. If the whole answer is an anagram, the
primary is `anagram` even if the fodder was built by deletion. If parts
are joined and one of them is an anagram, the primary is `charade`. If
one part goes inside another, the primary is `container`. When two
operations are equally outermost, choose the one earlier in the table
above.

## &lit

Set `and_lit` when the whole clue serves as both the definition and the
wordplay, including "semi-&lit" clues where the whole clue is the
definition and part of it is the wordplay. Devices are labelled as
usual.

## Source

`source` records what the label rests on: `blog` when a published
parsing of that clue was supplied and used, `model` when the classifier
had to parse the clue itself. Prefer the published parsing where the two
disagree, unless it is plainly about a different clue.
