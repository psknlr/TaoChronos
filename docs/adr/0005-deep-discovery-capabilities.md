# ADR 0005 — 深层发现 2.0: capabilities, not agents; candidates are not proof

**Status:** accepted

## Context

The study layer (ADR 0004) answers questions about one formula, drug or term. The next questions are about the
structure of the literature itself, and the classics make each of them hard in their own way:

- **版本谱系.** A work survives in several transcriptions that differ in variants, lacunae, added commentary and the
  order of passages. Which witnesses descend from which, and which copied from two branches?
- **语义复用.** Later books quote, cut, condense, restate, explain and refute their sources, and they share the stock
  phrasing of the genre (以水七升，煮取三升，去滓), which is no reuse at all. What did each later book do with a passage,
  and how was a work taken up, period by period?
- **文本地层.** Classics grew over centuries: 素问's 运气七篇 are held to be 王冰's addition, and 伤寒论's 辨脉法 to come from
  王叔和's edition. Which chapters belong together, and when can each have been written?
- **医案轨迹.** Case records tell a course of treatment visit by visit. What did physicians do next, and what went with
  recovery in the record?
- **医理论证.** The classics argue (若…则…, 故, 所致, 非…也) as well as prescribe. How does a text reason?
- **语义演变.** A term's senses shift, and some of its uses fit no curated sense.
- **佚书辑佚.** Lost works survive in quotation, with the conventions of each compiler.

A review of the system asked for these as modules and evals. It also asked for two constraints: *do not add a dozen
agents* — new abilities should be deterministic or model-assisted capabilities, exposed through the tool mesh and
called by the existing agents — and *embeddings may generate candidates but cannot prove anything*.

## Decision

1. **Capabilities, not agents.** Each ability is a function of the study capability (`plugins/classics/study`:
   `stemma`, `intertext`, `stratigraphy`, `cases`, `argument`, `senses`, `fragments`). The methods that do not read
   texts live in `science/` (`semantic_reuse`, `stratigraphy`, `trajectories`, `argumentation`, `sense_evolution`),
   which imports only `protocol`. Collation has its own plugin package (`plugins/classics/collation`: anchored
   alignment, variant units, stemma, TEI). Case records get a protocol type (`protocol/cases.py`: `Visit`,
   `CaseRecord`). No agent is added.
2. **Through the tool mesh, to the existing agents.** Twelve tools (`study.variants` … `study.fragments`, family
   `study`, permission `classics:read`, marked expensive) are listed on the agents whose work they serve:
   - the Philologist: collation, stemma, layers, dating, authorship;
   - the Skeptic: reuse, dating, argument — is a supporting passage an independent witness, a later layer, or a
     quotation made in order to refute?;
   - the Evidence agent: cases, trajectories, argument;
   - the Semanticist: term history and senses.

   These are hybrid agents: their model may call the tools. The Scholar's procedure adds the sense evolution of each
   focus term to its dossier. The reuse detector types every lineage edge (直接引用, 转述, 引而驳之 …), so the Lineage
   Analyst's report says *how* a later passage depends on an earlier one.
3. **Candidates are not proof.** Wherever something with high recall proposes pairs, clusters or spans (rare
   character probes, co-occurring concepts, k-means, an encoder's similarity), transparent rules over measured
   features decide. Every label carries the rule that fired, the values it read and a confidence from the margins.
   The rules' thresholds are one table, open to review and override. An encoder's similarity is reported beside
   the features, and no rule reads it.
4. **Missing is not different.** In collation, lacunae are missing data, not disagreement. Long additions and
   replaced blocks are structural (commentary, other passages): listed, never used to group witnesses. Orthographic
   variants (`collation.yaml`) weigh nothing in the stemma. Graphic confusions are deliberately *not* equivalences,
   because shared errors are the evidence of descent. The base witness is a coordinate system, not a judgement of
   the right reading.
5. **Nulls and corrections.** Every structure is tested against data without it:
   - layers against feature-shuffled profiles;
   - change points by permutation, corrected for the places tried (Benjamini–Hochberg);
   - sense change points by permuting dates;
   - associations with the outcome by one-sided Fisher tests with Benjamini–Hochberg;
   - shared content by an E-value (Σ credit × idf − log N).

   Random generators are seeded, and hashing uses `zlib.crc32`, so results repeat.
6. **Say what the evidence can bear.**
   - Style shows *that* chapters differ; dating evidence shows *when* they can have been written; neither alone
     proves an addition.
   - Taboo characters date an edition, not a composition.
   - Associations in case records — written by their physicians and selected for publication — are never evidence
     of efficacy.
   - A stemma is a hypothesis about the witnesses in the store, and contamination flags ask for a person.
   - A fragment is only as good as its compiler, so the reconstruction method is verified on works that survive,
     with a precision for each quoting book.
7. **Measured before trusted.** Each capability has an eval suite. Where an answer can be constructed, the data are
   synthetic with a known answer: traditions copied down a known stemma with a contaminated witness, composite texts
   with rewritten blocks, occurrences with a planted sense shift, a held-out lost work quoted in the manners of the
   literature. Where rules need examples, there is a small development set: typed reuse pairs, annotated case
   records, argument graphs. Where the literature holds a result, it is checked on the real corpus: the 运气七篇 of
   the 素问, the 叔和 chapters of the 伤寒论, two independent transcriptions of 吴鞠通医案, the surviving 千金 and 肘后.
   The development sets are called what they are.
8. **Curated, reviewable domain data.** Orthographic equivalences (`collation.yaml`), markers and stock phrases
   (`intertext.yaml`), case and visit openers and words of response (`cases.yaml`), and discourse markers of
   reasoning (`argument.yaml`) are plain YAML with comments, and the evals measure what they find.

## Consequences

- The agents gain twelve tools and no new roles; the roster, the routing and the gates are unchanged. Offline runs
  are unchanged except for the Scholar's term dossiers.
- Every label can be audited: a reader sees why a passage is 节略 rather than 撮要, which markers made an edge, which
  shared readings put two witnesses in a group.
- Rule-based reading has the limits of its rules and lexicon. A reuse through words the lexicon lacks is found only
  by its wording; terse texts look less argued than they are; parsers written for the manners of some case
  collections can merge or split cases in others. The evals make these limits visible but do not remove them.
- The development sets were written with the rules. Their scores show intended behaviour, not generalisation;
  expert-annotated gold on the full corpus is on the roadmap.
- Encoders and learned models can be added as candidate generators without changing what counts as evidence.
