# ADR 0009 — Four boundaries, an executable contract, and three evaluation layers

**Status:** accepted

## Context

An external architecture audit of TaoChronos reproduced ten counterexamples (P01–P10) and argued one thesis: do not
rewrite and do not add agents — make the research contract executable, make the reading of evidence reviewable, let
counter-evidence change conclusions, and make every release explicitly authorised.  Its ten probes each crossed one of
four boundaries that the harness drew too faintly:

| boundary | the audit's counterexamples |
|---|---|
| a **quote** is not its **interpretation** | P02 a true quote with a false relation committed; P09 empty or out-of-bounds evidence verified |
| a **model's proposal** is not a **verifier's verdict** | P03 a skeptic closing its own critical objection; P08 an agent writing G7; P04 an AfterToolCall denial ignored |
| an **execution that finished** is not a **research that is accepted** | P06 two goals in one transaction; P07 a rejected event persisted; "completed" meaning "no task left" |
| an **internal score** is not **external evidence** | P10 G8 passing on contradicting modern evidence; P01 withheld material read through a provenance tool; P05 model code reaching the filesystem |

It also asked for selection-aware statistics, claim-level source dependence, typed revisions, scoped novelty, warrants
with rival explanations per discovery type, long-run robustness (budgets, paging, replay, retraction, cancel/retry,
fault injection), discriminating actions, and three layers of evaluation: invariants, hard interpretive cases,
research value.

## Decision

**Authority comes from identity objects, never from strings.**  Every event carries the principal of the actor that
emitted it (kernel › human › validator › agent), set by the session from an `Actor`, never by the emitter; the reducer
checks each event type against `kernel/authority.py`.  A string that says "human" is at most an agent.  Agents act
through a `SessionView` bound to their identity and read a frozen `StateView`.  G7 is set only by an expert's
`ExpertApproved/Rejected`; a `GateEvaluated` carrying G7 is refused from anyone.

**A batch is valid as a whole or not at all.**  A transaction validates each event on the state its predecessors build
(two goals in one batch fail early), revalidates the whole batch at commit, applies it, and only then persists; a
failed persist restores the state from the log.  A rejected event reaches neither the log nor the state, an old
poisoned log reopens only with an explicit repair, and every round checks that the live state equals the log's replay.

**The reading scope is a view, not a filter.**  A `CorpusManifest` withholds tiers (hold-out, confirmation,
expert-only); the reducer keeps withheld material withheld; every read path — tools, retrieval, knowledge, the agent's
own capability handles — goes through a scoped view by principal (agents see no withheld tier, validators see the
confirmation tier, humans and the kernel everything), and an AfterToolCall firewall quarantines any result that names
withheld material.  An AfterToolCall denial withholds the result (only its hash is kept); every call leaves a receipt.

**Quotes are read, not only matched.**  A claim is authentic when its quote is verbatim at its span; it is *supported*
when the quote states its relation — the nearest cue governs each intervention (「不可发汗，宜桂枝汤」), the consequence
decides between warning and recommendation (「汗之则神昏」/「汗之则愈」), an intervention named by 之 is read through its
pronoun, and every argument is read with its negation (「非风、非寒…乃异气所感」 does not support "风 causes 温疫").  The
statement frame records who says it (a report governs until the author answers it: 或曰…余曰非也), the stance
(asserted / reported / rejected), the conditions (若…者, 凡…, and the 「…者，X主之」 clause), negations and time.  A claim
the quote contradicts is refused at commit; G4 reports authenticity, locator, support and scope as layers.

**Objections are a state machine.**  raised → resolution_proposed → closed.  A model may only propose a resolution;
a hard objection (provenance, anachronism, scope, semantic support, single source, transcription dependence) closes
only by a validator's passing re-run, an interpretive one by a verified narrowing or an expert.  G6 fails while a
critical objection is open.

**Model code runs isolated or not at all.**  Sandboxes have tiers (in-process, process, namespace, container); code
of model or user origin needs the namespace tier or better — unprivileged user, mount, network, PID and IPC namespaces,
a read-only root, a private workspace, no network — and is refused where none exists.  Code Mode runs there and reaches
tools only by RPC through the scheduler, under the caller's permissions.

**The contract is executable, and acceptance is not execution.**  A `GoalSpec` carries an `AcceptanceSpec` and an
optional `ConfirmationSpec`; a validator judges every hypothesis against the criteria on the version it now has (gates
computed on an earlier version do not count), each criterion recording its judge, what it observed, what it required
and the state a failure leads to.  The research is `research_accepted`, `needs_expert`, `inconclusive` or
`budget_exhausted` — never "completed" because no task was left.  A report may present only hypotheses judged on their
current versions.

**Warrants and honest statistics.**  Each hypothesis has a warrant: the inference by kind, its assumptions, the rival
explanations of its discovery type (excluded / open / not applicable / unaddressed) and the discriminating analyses
that decided them.  Drift is tested with a max-statistic permutation over all boundaries (the chosen boundary's naive
p-value is kept as a sensitivity), absences with leave-one-family-out and family bootstrap, and hypotheses carry a
structured statistics record instead of 1 − p.  Novelty is scoped (未在指定范围内发现, never "first discovery"); Elo is
an exploration priority over checkable features, not credibility; revisions are typed restricting / substantive.
Predictions can be confirmed on material withheld from exploration.

**Long runs.**  Budgets reserve before a model call and settle after it, in the log (a resumed run starts from the
ledger; an unsettled reservation counts as spent); long tool results are paged, never cut, and older turns compacted
to page handles; model responses can be recorded and replayed exactly; evidence can be retracted, which removes it from
what rested on it, voids the gates and re-judges the contract; tasks can be cancelled and retried; a run manifest
records code, corpus, configuration and a hash chain of tool receipts.  The director plans discriminating actions for
open rivals.

**Three evaluation layers.**  (1) `invariants`: the boundaries above as probes run against the harness under
evaluation — a profile that drops a validator shows up as a broken invariant, and each probe was checked to fail when
its boundary is removed.  (2) `interpretive`: hard interpretive cases (true quote / false relation, a prohibition beside
a prescription, consequences, reported and rejected views, omitted conditions, mixed witnesses, disputed dates), scored
per class with the *unsafe* errors — those that would let a false claim through — counted apart, on a dev split and a
held-out split.  (3) research value: the existing suites and ablations against baselines.

**Held-out discipline.**  The interpretive gold's split was fixed before its first run.  The first run's held-out
score is recorded; the cases whose misses prompted a general change move to dev, and the change is measured on a new
held-out round written before it ran.  A held-out miss is reported, not patched with a rule written for it.

## Consequences

* The ten probes are regression tests (`tests/test_boundaries.py`) and measured invariants (`taochronos eval
  invariants`): 19 of 19 hold, and each of six boundaries removed on purpose breaks its invariant.
* Rule claims now meet a second, independent reader: on 25 000 passages of the full corpus (the 伤寒论, 金匮, 脉经,
  诸病源候论, 千金, 外台, 景岳全书, 本草纲目 and 温疫论 families) it found 71 rule claims contradicted by their own quotes;
  the extractor misreadings behind most of them (「不可与X」 read as 可与X, 「宜下之」 read as an adverse outcome,
  「…主之，若…不可服之」 spanned instead of referred, 「亦非三者攻之」 read as a treatment principle) were fixed at the
  source, leaving 12 — mostly machine-segmented 白文 — which the commit hook refuses.
* The time machine splits the corpus at a cutoff by whole date ranges: a text that may have been written on either side
  (素问·至真要大论, 100–762, at 618) belongs to neither the past corpus nor the future that checks predictions.
* The interpretive layer names what the readers cannot see: a textual crux (公案) — 「不可下也。大黄牡丹汤主之」,
  「表有热，里有寒，白虎汤主之」 — reads as a plain indication.  A curated registry of cruxes, consulted by the support
  reading, is the direction; its cases must come from new held-out material.
* Limits stay stated: the tool-level hold-out is not a blind prediction; the namespace tier is not VM-grade isolation;
  acceptance levels and verdicts are not calibrated probabilities; the gold is author-annotated.
