# ADR 0004 — A study layer (治学) of deterministic, witness-based functions

**Status:** accepted

## Context

With 926 works and 1.98 million passages in the store, the research agents answer *discovery* questions
(hypotheses, gates, falsification). Scholars and students of Chinese medicine also ask a different kind of question
of the literature, every day, and expect it answered the way the 考据 tradition answers it: *where does this passage
recur and how do the witnesses differ; what was the original composition of this formula and how did it change; when
was this drug first said to enter this channel; when does this term rise and fall; which edition is this, judging by
its taboo characters; whom did each period cite?* These questions have answers that can be read off the texts, but
only if the tools respect what is peculiar to these texts:

- one work survives in several transcriptions (同书异本), is quoted by later works (引文) and restated without
  acknowledgement (互见);
- a name changes under taboo (薯蓣 → 薯药 → 山药, 玄参 → 元参, 丸 → 圆), a formula has other names (同方异名) and a name
  covers other formulas (同名异方), and a 笈成 entry prints the formula's name only as its heading;
- doses are written in the measures of their period (a Han 两 is not a Song 两; 分 changes meaning around 960);
- doctrines are period-bound (归经 and 升降浮沉 are Jin–Yuan), so an absence in the 本经 is expected, not a gap;
- a book known only by its dynasty must not be dated before one dated to a reign;
- commentary layers and editorial notes are later than the text they annotate;
- verses (方歌) are how the formulas were — and are — learned.

## Decision

1. **A `study` capability** (`plugins/classics/study`), registered by the classics plugin, with one function per
   question: concordance, formula, herb, term, taboo, citations, cards, reading, dataset. The functions are
   deterministic and rule-based, work on the demo corpus and on the store, and return plain data.
2. **Everything is a witness.** Every result is built from *witnesses* — a verbatim quote with its passage id,
   locator (《书》卷·篇·节), book date, period, layer, source and licence — so every statement can be checked
   against the text it rests on. Machine reading is labelled as such.
3. **Dating by terminus ante quem.** "Earliest" orders witnesses by the latest date they can have, then the
   earliest; a quotation dates the quoted text no later than the quoting book.
4. **Curated, reviewable domain data** in `domains/classics`: `taboo.yaml` (rules with the year they start and the
   spellings they force), `metrology.yaml` (period measures with their sources and a notice that they are
   historical readings, never dosage guidance), `physicians.yaml` (names and 本草 short names of ~70 physicians
   with dates and schools), `drug_families.yaml` (桂枝/桂心/肉桂 → 桂), and lost works in `external-works.yaml`.
5. **Formula provenance by exact compositions.** Compositions are parsed from the text (including entries headed by
   the name, bracket-less preparation notes, shared doses 各三两) and grouped by their drug sets: the most frequent
   exact sets seed the groups, and a group is dated by the earliest witness of its exact composition — an early
   variant does not become the "original".  原方 is the earliest tradition *under the name asked for*.
6. **Statistics that survive uneven survival.** Term histories compare shares of passages per period (Wilson
   intervals, Cochran–Armitage trend), never raw counts.
7. **Caches keyed by the corpus.** Expensive indexes (entry headings, the citation network) are cached under
   `<data>/corpus/study-cache/`, keyed by a digest of the store, the normaliser and the book records.
8. **Three surfaces.** The CLI (`taochronos study …`: Markdown, JSON, Anki, Frictionless data packages), the tool
   mesh (`study.*`, through the capability — tools import no plugin), and the TaoChronos-Scholar agent, which the
   Director adds to round 0 when a profile sets `discovery.sources_dossier`; its dossiers become an appendix of the
   Discovery Report ("源流考证"). They describe texts; they are not hypotheses and pass no gates.
9. **Datasets carry quotes, not texts.** Exports hold short quotes (≤ 120 characters) with passage ids, locators
   and licences; the transcriptions themselves never leave the local store.

## Consequences

- Researchers get reproducible, citable answers with provenance; students get cards and reading paths grounded in
  the same witnesses.
- Rule-based extraction is fallible (single-witness groups are flagged 孤例 for checking by hand; drug entries are
  read with patterns); every output shows the quotes needed to check it.
- The curated data encode scholarly positions (metrology values, taboo start years, physician dates) that may be
  disputed; they are plain YAML with sources, open to review.
- Taboo evidence dates an edition, not a composition, and is indicative only.
