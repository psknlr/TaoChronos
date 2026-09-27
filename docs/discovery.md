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

## Deep discovery 2.0: the structure of the literature

The engines above work on claims. Seven study capabilities read the structure of the literature that the claims come
from ([study.md](study.md#深层发现-20--the-structure-of-the-literature), [ADR 0005](adr/0005-deep-discovery-capabilities.md)).
They are tools of the existing agents, not new agents. Each one sharpens a question the engines ask:

| Capability | What it adds to discovery |
|---|---|
| 版本谱系 `study.variants` · `study.stemma` | Which witnesses of a work are copies of which. Independence in G5 counts clusters of dependent witnesses; a stemma shows which transcriptions share an exemplar, and a reading found in one branch only is a variant of transmission, not a second testimony. |
| 语义复用 `study.reuse` · `study.transmission` | *How* a later passage depends on an earlier one. Every lineage edge (`transcribes`, `rephrases`) carries its reuse type (直接引用, 节略, 转述, 解释性改写 …) and the rule that fired. A passage quoted in order to refute it (引而驳之) is opposition, not support. The Skeptic can ask whether ten supporting passages are ten reuses of one. |
| 文本地层 `study.layers` · `study.dating` · `study.authorship` | Whether a passage belongs to the layer a claim's date assumes. Evidence from the 运气七篇 is held to date from 王冰's edition, not from the Han; the Skeptic and the Philologist can check a chapter's style layer, cited works, late vocabulary and taboo floor before a claim is dated by its book. |
| 医案轨迹 `study.cases` · `study.trajectories` | Practice beside doctrine: what physicians prescribed, changed and recorded as the outcome, visit by visit. These are associations in a selected record, so the Evidence agent cites them as case evidence, never as efficacy. |
| 医理论证 `study.argument` | Whether a passage asserts, infers, conditions or rebuts. A clause under 非…也 or 殊不知 is a rejected view; a consequence under 若…则 holds only under its condition — the line D5 draws between a contradiction and a conditional statement. |
| 语义演变 `study.senses` | D2 at the level of senses: sense shares by period, dated change points and candidate senses the curation lacks. The Scholar's dossier for a focus term reports them, and the Semanticist can check a resolution against them. |
| 佚书辑佚 `study.fragments` | Source rediscovery infers that a lost source existed and dates it; 辑佚 recovers what it said, from the books that quote it, with a precision for each compiler measured on works that survive. |

What proposes is never what proves. Candidates come from probes, co-occurring concepts, clusters or an encoder, and
transparent rules over measured features decide, each label carrying its rule and values. The seven eval suites
measure each capability ([evals.md](evals.md#深层发现-20)).

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
window (temporal scope, hold-out, excluded books).  Co-mentions were not enough: the research-value benchmark found
associations called lost that later books still *state*, and links called hidden that earlier books had written
([ADR 0010](adr/0010-speed-cruxes-and-research-value.md)).  So the Skeptic also searches the whole window for claims
that state the association — every written form of both terms, one-character ones included, the extractor deciding and
the quote supporting — and one such statement after the pivot refutes a loss, any one refutes a hidden link.

### Falsification

The Skeptic runs, per kind: provenance of every quote · anachronism · contested readings inside the evidence
· homonymy · transcription dependence · single source · corpus coverage · statistics after correction ·
later co-mentions, partial persistence and explicit later statements — `restated_after`, hard (lost knowledge) ·
contraindications, taxonomic implication, differential diagnosis, text-level co-mentions and explicit statements
anywhere in the scope — `attested`, hard (hidden associations) · earlier attestation (testimony) ·
lineage strength (formula families) · overlap with existing understanding (novelty, not validity).

Verdicts are harness policy: an unresolved critical objection rejects; unresolved major objections send a
first-generation hypothesis back for **revision**; revisions *narrow* the claim through qualifiers
(`scope: surveyed_corpus`, `sense: …`, `reading: base`, `status: exploratory`, `tradition: single`,
`level: explicit_claim | transformed | text_attested`), keep all counter-evidence, and are reviewed again.
A qualifier resolves only the objections it answers — and only as a *proposal*: objections are a state machine
(raised → resolution proposed → closed), a hard objection (provenance, anachronism, scope, semantic support, single
source, transcription dependence) closes only by a validator's passing re-run, an interpretive one by a verified
narrowing or an expert.  A revision is typed: *restricting* (qualifiers only, the parent's support carried over) or
*substantive* (a new statement or new terms: it needs its own support); the child's id depends on its content.

Statistics say what they test: concept drift is tested with a max-statistic permutation over all period boundaries
(the chosen boundary's naive p-value is kept as a sensitivity, never as the result); absences carry a level (1–3; a
level-4 "never existed" is never asserted) with leave-one-source-family-out and a family bootstrap; each hypothesis
carries a structured statistics record rather than a "1 − p" confidence.

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
predictions are indirect). An Elo tournament orders the leaderboard by pairwise comparison of what a reader can check
(live defeaters, confirmation on withheld material, independent source families explained, rivals excluded, extra
assumptions) — an **exploration priority**, not a credibility.  Novelty is scoped: against the curated list of existing
understanding, the corpus under study and (when searched) the literature — 未在指定范围内发现, never "first discovery".
Confidence is a **vector** (textual, philological, semantic, extraction, cross-source, temporal, statistical, modern
mapping); modern biomedical validity stays *unknown* unless a cross-space hypothesis passes G8.

Each hypothesis carries a **warrant** — its inference by kind, its assumptions, the rival explanations of its
discovery type (for lost knowledge: a lost source, a renaming, a change of practice, sampling; for drift: a change of
sense, of genre, of corpus composition …) each excluded, open, not applicable or unaddressed, and the discriminating
analyses that decided them — and the research as a whole is judged by its **contract**
([architecture.md](architecture.md#contract-warrants-and-acceptance)): research accepted, needs an expert,
inconclusive, or budget exhausted.

## Knowledge spaces

Classical text · historical interpretation · computational hypothesis · modern TCM · biomedical. Modern
literature enters only through the Modern Evidence agent: attached to hypotheses as *context*, or as a
separate **cross-space bridge** hypothesis (typed mapping, Gate G8). A modern finding never validates an
ancient text, and an ancient text is never evidence of modern efficacy.

## The Discovery Report

Sections, in order: Research Question · Contract Evaluation (execution and research verdicts, each hypothesis's
criteria) · Existing Understanding · Corpus Evidence · Temporal Pattern · Knowledge Network · New Observations ·
Candidate Hypotheses (with their exploration priority, warrant, confirmation, statistics and scoped novelty) ·
Supporting Evidence · Counterevidence · Alternative Explanations (the warrants' rivals) · Confidence · Recommended Human
Verification — plus the hypothesis genealogy. Retracted evidence is left out of the evidence table.
What did not survive is reported as clearly as what did. The report, a JSON twin, the evidence ledger
(CSV), the claim hypergraph (JSON; Cypher, GraphML and W3C PROV exports on demand) and the run trace are
versioned artifacts; `taochronos workspace` renders the offline HTML Discovery Workspace.
