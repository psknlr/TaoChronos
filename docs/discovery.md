# Discovery

## From passages to claims

A passage is assessed by the Philologist (normalisation, contested spans with reading probabilities,
collation status), its historical terms are resolved to period-bound senses by the Semanticist, and the
Extractor turns it into **claims**: hyperedges such as

```
indicated_for( formula:五苓散 | pulse:浮, symptom:小便不利, symptom:微热, disease:消渴 )   伤寒论 §71, 「若脉浮，小便不利，微热消渴者，五苓散主之」
```

with a verbatim quote, a character span for every argument, negations, optional findings, conditions and
adverse outcomes. Claims carry a temporal context (author / composition / edition / citation clocks) and a
knowledge space (classical text). The provenance validator rejects any claim whose quote or argument spans
do not match the passage.

### Unpunctuated text

Most transcriptions of the classics are 白文. The extractor reads them through a machine-segmented *view*
(`plugins/classics/segment.py`: rules for 曰/云, sentence-final particles, 主之/宜X, 者 before a verdict or a
prescription, doses and preparation, 本草 entry structure, list layout) and maps every quote and argument span
back to the source, so claims stay verbatim. Such claims carry the tag `machine-segmented` and a lower extraction
confidence; a finding-level opposition read through segmentation is labelled *apparent* (type `segmentation`) and
never becomes a hypothesis.

## Discovery engines (tool-first, no model)

**D1 · Lost knowledge.** Association units (herb/formula × finding/disease) attested before a pivot year
(default 960) that never recur afterwards although *both* concepts are still used later (a vanished concept
is concept loss, not association loss). Compound findings are expanded into components so a later
restatement is not mistaken for loss. Independence is counted in author/transcription clusters. The
Statistician attaches `P(no later co-occurrence | association persisted at its early rate)`. Textual
testimony (e.g. 昔人… 后世…) is recorded separately.

**D2 · Concept drift.** For a term family, the context profile of each period (co-occurring terms inside
claims) is compared with Jensen–Shannon divergence; permutation tests give p-values (Benjamini–Hochberg
across terms); the dominant resolved sense per period exposes sense shifts; gained and lost contexts
describe the change.

**D3 · Formula evolution.** Formula compositions (with taboo renames and processing variants merged, e.g.
薯蓣 → 山药) are compared; derivations need shared monarch herbs and substantial overlap. Families report
stable cores, herb retention, added/removed/substituted herbs and indication drift.

**D4 · Hidden association.** Association rules from findings to formulas (support, confidence, lift,
Fisher exact p, BH) and link prediction (Adamic–Adar; baselines: resource allocation, common neighbours,
popularity, random) on the clique expansion of *positive* hyperedges only — a contraindication is not an
association.

**D5 · Contradiction.** Claims about the same subject (identical or parent–child, never siblings) are
compared on axes (etiology, origin, cold/heat, treatment nature, findings). Oppositions are labelled:
`apparent` when a contested reading (philological) or a sense difference (homonymy) explains them,
`conditional` when conditions differ (劳倦, 体质, 时令…), `unrelated/differential` when different
presentations receive different prescriptions, otherwise `contradiction` (direct or theoretical). Passages
linked by transcription or rephrasing count as support.

**Source rediscovery.** Explicit citations and oppositions naming works absent from the corpus become
candidates for lost or held-out sources, with a date bound (earlier than the earliest citer).

## Hypotheses

The Hypothesis agent turns observations into hypotheses with: a statement (in the computational-hypothesis
space), verbatim supporting evidence, the earliest evidence, structured **predictions**
(`absent_after`, `link_appears`, `cooccurrence_after`, `herb_retained`, `sense_shift`, `renaming`,
`earlier_attestation`, `resolution`), a testable prediction in words, alternative explanations, and philological and
anachronism risk labels.

### Scale: frame and whole corpus

On a large corpus the Curator freezes a **sampling frame**: passages the full-text index finds for the question's
terms, their aliases and variants, related terms and the cues of their historical senses, plus one hop to the
formulas and drugs most co-mentioned with them — stratified by period (a floor per period, then relevance) and
recorded in the manifest (`frame`). The reading agents work inside the frame. Absence and later-attestation
checks do not: the Skeptic's co-mention and late-passage counts query the **whole store** within the contract's
window (temporal scope, hold-out, excluded books), so sampling can never manufacture an absence.

### Falsification

The Skeptic runs, per kind: provenance of every quote · anachronism · contested readings inside the evidence
· homonymy · transcription dependence · single source · corpus coverage · statistics after correction ·
later co-mentions and partial persistence (lost knowledge) · contraindications, taxonomic implication,
differential diagnosis and text-level co-mentions (hidden associations) · earlier attestation (testimony) ·
lineage strength (formula families) · overlap with existing understanding (novelty, not validity).

Verdicts are harness policy: an unresolved critical objection rejects; unresolved major objections send a
first-generation hypothesis back for **revision**; revisions *narrow* the claim through qualifiers
(`scope: surveyed_corpus`, `sense: …`, `reading: base`, `status: exploratory`, `tradition: single`,
`level: explicit_claim | transformed | text_attested`), keep all counter-evidence, and are reviewed again.
A qualifier resolves only the objections it answers.

### Gates, scores and ranking

Validators then evaluate G0–G8, compute a **ScoreCard** (textual support, replication, philological
robustness, temporal coherence, novelty, explanatory power, counter-evidence robustness, testability,
anachronism risk) and the **Discovery Score**

```
D = 0.25·E + 0.20·N + 0.20·R + 0.15·T + 0.10·F − 0.10·A
```

(E evidence strength, N novelty against curated existing understanding, R independent replication, T
temporal coherence, F falsification survival, A anachronism risk) — always reported with its components.
Evidence and replication are discounted by how directly a kind's evidence states its claim (link
predictions are indirect). An Elo tournament over score cards orders the leaderboard. Confidence is a
**vector** (textual, philological, semantic, extraction, cross-source, temporal, statistical, modern
mapping); modern biomedical validity stays *unknown* unless a cross-space hypothesis passes G8.

## Knowledge spaces

Classical text · historical interpretation · computational hypothesis · modern TCM · biomedical. Modern
literature enters only through the Modern Evidence agent: attached to hypotheses as *context*, or as a
separate **cross-space bridge** hypothesis (typed mapping, Gate G8). A modern finding never validates an
ancient text, and an ancient text is never evidence of modern efficacy.

## The Discovery Report

Twelve sections, in order: Research Question · Existing Understanding · Corpus Evidence · Temporal Pattern ·
Knowledge Network · New Observations · Candidate Hypotheses · Supporting Evidence · Counterevidence ·
Alternative Explanations · Confidence · Recommended Human Verification — plus the hypothesis genealogy.
What did not survive is reported as clearly as what did. The report, a JSON twin, the evidence ledger
(CSV), the claim hypergraph (JSON; Cypher, GraphML and W3C PROV exports on demand) and the run trace are
versioned artifacts; `taochronos workspace` renders the offline HTML Discovery Workspace.
