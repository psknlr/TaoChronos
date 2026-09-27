# ADR 0010 — Caches keyed by content, cruxes read from the commentaries, and research value measured blind

**Status:** accepted

## Context

Four things followed ADR 0009.

1. **Speed.**  Building a full-corpus harness spent most of its time in the YAML scanner (26 of 29 s under the
   profiler: the harvested lexicon alone is 2.7 MB, and PyYAML here has no libyaml).  A full-corpus research run took
   152 s, 44.5 of them in integrity checks: every round replayed the whole log, and every state hash serialised the
   agents, metrics and manifest it then dropped, and walked the serialised tree a second time.
2. **Textual cruxes.**  ADR 0009 named what the support reading cannot see — a 公案 such as 「不可下也。大黄牡丹汤主之」
   or 「表有热，里有寒，白虎汤主之」 reads as a plain indication — and asked for a registry of cruxes consulted by the
   reading, measured on new held-out cases.
3. **Research value.**  ADR 0009's third evaluation layer was the demo-corpus suites and the ablations; the time
   machine's own note said that the demo corpus has too few links first written after its cutoff to show anything.
4. **What that layer found once it ran on the full corpus.**  Arguments from silence were tested against the wrong
   thing.  A *lost* association (D1) and a *hidden* one (D4) are claims about the literature, but the Skeptic tested
   them against co-mentions of the words the full-text search could find (one-character forms left out), and a
   narrowing of the wording to 「不再形成明确记载」 closed the objection unchecked.  So an association that later books
   still state explicitly was called lost (「寒」 with 消渴, 「肥甘」 with 消渴 — the second is a 素问 doctrine), and links
   already written in books the session had not read were called hidden (喘 ⇢ 五苓散, 头痛 ⇢ 承气汤).  Behind one of
   them was an extraction error: in the 白文 of a drug entry, 「寒润五脏治消渴…热毒所生也」, the pathogenesis rule took
   the drug's nature (寒) and what it treats (消渴) into the 「热毒所生」 statement.

## Decision

**Caches keyed by content; integrity checked by increments.**  Every YAML read goes through `protocol/yamlio.py`: the
parsed value is kept under the SHA-256 of the file's bytes (pickled plain data, written atomically, re-parsed when
damaged, `TAOCHRONOS_CACHE=off` to disable), so an edited file is another key and a stale entry cannot be read.
`to_jsonable` takes exact built-in types first and caches dataclass field names per type (same output).  The state
hash serialises only the scientific fields, in one walk, with the cyclic collector paused.  Each round's integrity
check keeps a replay beside the live state and advances it by the new events (`Session.verify_incremental`); the
replay's hash is reused until it moves, a checkpoint right after a consistent check records that check's hash, any
restore drops the kept replay, and the live state is always hashed afresh — so a change behind the log is still found.

**Textual cruxes are data harvested from the commentaries.**  `taochronos study cruxes` reads, for every clause of a
work's base witness, the commentaries on it for statements of transposition (当在…下, 错简), emendation (当作, 疑是,
字之误), interpolation (衍文), omission (脱) and doubt (疑有误, 不可解).  A statement must name words the clause has, or two
commentators must doubt it; read-as glosses (当作…看), negated markers (不当在), repetitions of the commentator's own
witness, reported doubts the author answers, misplacements between chapters, preparation lines and herb lists are left
out, and so are commentaries from 1950 on.  The registry (`domains/classics/cruxes.yaml`, quotes of at most 60
characters) is reviewable data.  The support reading finds a registered clause in any witness by its 4-grams and reads
a claim whose literal wording would support it, but which rests on the doubted words, as *ambiguous* — the crux, its
kinds and its commentators given as cues.  Cue windows stop at the next 「……者，」 condition.

**Research value is measured blind, on the full corpus, against baselines** (`taochronos eval research_value`).  The
store gives time-machine views, `corpus.on_side(cutoff, side)`: only the passages whose whole date range lies before
(or after) the cutoff exist, every read path bounded in SQL — the full-text search, and the study layer's own queries of
the store (`row_filter`: texts, period denominators, the punctuation model's training rows) included — so a harness on
the past view cannot read a later text, and a view never prunes the caches of the whole store.  Two measurements:

* *Link anticipation.*  For every disease and symptom of the lexicon with enough past and future passages (the rule is
  in `evals/gold/research_value.yaml`, written before the first run; a change to it is recorded there with its reason),
  the positive claims of all its past passages form the graph D4 reads; each formula or drug of it not linked to the
  topic is a candidate, and it comes true when future claims of two books link it to the topic.  Adamic–Adar (D4's
  ranking), resource allocation and common neighbours are compared with popularity and chance.
* *End to end.*  The research pipeline runs on the past view; each structured prediction of its hypotheses is judged
  by future claims — strictly (the association's own relation, a quote that supports it) and loosely (any claim naming
  both terms, as the first runs did).  A hidden association is also checked against the whole past, and set beside
  popularity and chance for the same condition on the session's own graph.  Topics are split: dev (runs inspected while
  the pipeline was changed) and held-out.  Any passage of a session outside the past view is counted as leakage.

**An argument from silence is tested against what the scope states.**  `restatements()` finds claims that *state* an
association anywhere in the research scope — the whole store within the contract's window, for a large corpus — from
the passages carrying any written form of both terms, one-character forms included (the extractor, not the index,
decides what a passage states), counting only claims of the association's relation whose quote supports them.  "No
longer stated" is a universal negative: one verified later statement refutes a lost association (`restated_after`,
critical; the detail says when all later statements are of one source family, for a separate argument about
transcription).  Any statement refutes a hidden one (`attested`, critical).  Both are hard objections — no narrowing of
the wording closes them — and the statements are recorded as counter-evidence.  D4 no longer proposes the lexicon's
weak entries (the harvested one-character "drugs" 药, 补, 白), and the pathogenesis rule reads a 「…所生」 statement
where it is made: its cause in the cue's clause or the one before, what it produces up to one clause further back,
and in a clause the segmenter left unmarked only the words within twelve characters of the cue.

## Consequences

* **Speed.**  Full-corpus harness 9.2 s → 0.64 s with a warm cache (demo 0.67 → 0.08 s); the state hash of a full-corpus
  research state 1.32 → 0.63 s, identical; a full-corpus research run 152 → 95 s, its integrity checks 44.5 → 7.0 s;
  the test suite 120 → 66 s (now 332 tests).
* **Cruxes.**  127 cruxes (伤寒论 85 from 1674 clauses, 金匮要略 42 from 779).  Interpretive round 3 (written before any of
  this) scored 7/10 with three unsafe cruxes; round 4 (written after, before it ran) 5/5.  Now dev 23/23, held-out 82/84
  (0.976); the two unsafe misses — 大黄牡丹汤 and 里水 — are cruxes the harvest does not find, reported and not patched.
* **Research value, link anticipation** (cutoffs 1127 and 1368, 189 topic–cutoff pairs with links that came true,
  29 467 candidates, base rate 4.5 %): precision@10 Adamic–Adar 0.168 [0.152, 0.185], common neighbours 0.170,
  resource allocation 0.149, popularity 0.134, chance 0.054; mean average precision 0.199 vs 0.143 (popularity) and
  0.092 (chance).  Adamic–Adar beats popularity on 149 topics and loses on 39 (sign test p = 2.4 × 10⁻¹⁶), and does so at
  each cutoff.  The first run, before weak lexicon entries were excluded from the candidates, gave the same ordering
  (0.162 vs 0.130 vs 0.054).  Common neighbours is slightly ahead of Adamic–Adar within the intervals; D4 was not
  switched on this benchmark's evidence — a further cutoff should decide.
* **Research value, end to end** (cutoff 1368; dev 消渴, 中风; held-out 胸痹, 霍乱, 虚劳, 痰饮): no leakage.  Before the
  changes, held-out predictions held 10/25 (0.40): lost associations 4/9, association rules 1/7, hidden associations 4/8
  — of which only 2 were both new and true, the other two already written before the cutoff.  The new checks change
  what survives review, not what is predicted: on the held-out topics they rejected four predictions — two lost
  associations the future contradicts and the two hidden associations already written before the cutoff — and none of
  the eight discoveries (true and new; one of them an earlier check had already rejected).  Of the predictions of hypotheses that survive review, discoveries
  went from 7/23 (0.30 [0.16, 0.51]) to 7/19 (0.37 [0.19, 0.59]), and surviving lost associations that hold from 4/9 to
  4/7; on the dev topics from 1/12 to 1/8.  The layer's verdict on the pipeline is modest: the ranking it rests on
  anticipates later links well above popularity and chance, but its hypotheses, judged one by one, are borne out about
  as often as not, and association rules rarely.
* **Limits.**  The benchmark measures anticipation, not influence: a link comes true when later physicians wrote it,
  whoever found it first.  Both sides are read by the rule extractor.  The shared full-text index ranks with statistics
  of the whole store (no later passage is read).  The restatement search reads at most 1500 candidate passages per
  pair.  The end-to-end layer is small (39 judged predictions) and its intervals are wide; D1 has no baseline yet (how
  often an early-only association of the frame stays absent), and association rules hold rarely.  Whole-store checks
  exclude withheld passages but not other passages of a confirmation family outside the frame.
