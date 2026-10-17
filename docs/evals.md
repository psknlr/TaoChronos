# TaoChronos-Eval

```bash
taochronos eval                  # all suites (~18 min with the corpus store, caches built: the 2.0 and task suites also check the real corpus; research_value alone ~11)
taochronos eval --quick          # fast subset
taochronos eval claims temporal -o results.json
```

Gold sets live in `evals/gold/` — **author-constructed for the demo corpus and used during development**.
Read the scores as regression tests of intended behaviour, not benchmark results; replace the gold with
expert annotations before drawing conclusions about a real corpus.

The suites form three layers ([ADR 0009](adr/0009-boundaries-contract-and-evaluation-layers.md)):

1. **Invariants** (`invariants`) — the boundaries the harness promises, as probes run against the harness under
   evaluation: a profile that drops a validator, or a plugin that leaks a result, shows up as a broken invariant.
2. **Hard interpretive cases** (`interpretive`) — verbatim quotes that can still be read wrongly, scored per class with
   the *unsafe* errors (those that would let a false claim through) counted apart, on a dev and a held-out split.
3. **Research value** (`research_value`) — does what the system proposes from the past anticipate what later physicians
   wrote?  A blind temporal benchmark on the full corpus against baselines ([ADR 0010](adr/0010-speed-cruxes-and-research-value.md)),
   with the time machine, source rediscovery, the ablations and every other suite.

| Suite | Question | Metrics |
|---|---|---|
| `invariants` | Do the harness's boundaries hold — scope on every read path, semantic support at commit, objections a model cannot close, AfterToolCall denials, isolation of model code, atomic batches, G7 for experts only, evidence bounds, G8 by stance and level, read-only agent views, integrity, retraction, publication on current versions, acceptance ≠ execution? | held / exercised / broken |
| `interpretive` | Are true quotes read right where the reading is hard — inverted relations, a prohibition beside a prescription, consequences, reported and rejected views, omitted conditions, mixed witnesses, disputed dates, textual cruxes? | accuracy and unsafe errors, per class and per split (dev / held-out) |
| `research_value` | On the full corpus split at a cutoff year: do the graph rankings D4 uses anticipate the remedies later books link to a disease, better than popularity and chance?  Do the pipeline's own predictions, made on the past alone, come true? | hits and precision@k, mean average precision, paired sign tests over topics; predictions held (strict / loose), per split and review status; leakage |
| `philology` | Are contested readings kept with probabilities and an uncertain mass? Are variant spellings normalised for matching? | pass rate |
| `claims` | Does extraction find the right hyperedges (relation + key arguments + negations)? | precision · recall · F1 · recall by relation · provenance pass rate |
| `provenance` | Are all committed claims and evidence verbatim? How deep is the Claim → Pixel chain? | verbatim rates · chain depth · level availability |
| `hallucination` | Are fabricated, one-character-perturbed and mis-positioned quotes caught, without flagging real quotes or variant spellings? | detection rates · verbatim recall |
| `contradiction` | Contradiction vs conditional vs apparent vs support vs unrelated (including differential diagnosis and transcription) | accuracy · macro-F1 · confusion |
| `lineage` | Formula derivation, citation, transcription, rephrasing, inheritance, opposition | precision (judged) · recall · unjudged predictions |
| `temporal` | Period constraints, earliest attestations (through variant spellings and concepts that predate their names), period leakage | accuracies · leakage count |
| `anachronism` | Are equations of historical and modern concepts blocked, careful phrasings allowed, mappings typed conservatively, agent-asserted equivalence refused? | statement accuracy · block P/R · mapping accuracy |
| `recovery` | After crashes at several points, does resume reach the identical scientific state? Are reruns and parallel runs identical? | success rate · replay consistency |
| `time_machine` | Research on texts before a cutoff (a separate harness, nothing later indexed); are its structured predictions borne out by later texts? | decidable predictions · accuracy (survived vs other) · leakage · link-prediction baselines |
| `source_rediscovery` | Hold out a cited book: is it re-inferred as a missing source, dated before its earliest citer? | recall@3 · date-bound consistency |
| `ablations` | Which components carry the results? | earliest accuracy without routes · contradiction accuracy without sense/philology · G5 inflation without clusters · Context-OS token reduction · false survivals without the Skeptic |
| `collation` | Are the variants of a known tradition found, and its stemma, groups and contamination recovered? | unit recall / precision · split recall · Robinson–Foulds · group precision · contamination P/R |
| `reuse` | Is each reuse typed right (直接引用 … 套语相似), and are real reuses found? | accuracy · macro-F1 · mode accuracy · detection P/R/F1 · pipeline recall |
| `stratigraphy` | Are the layers of composite texts found, with their boundaries, and are texts attributed to their authors? | layer accuracy · change-point and boundary P/R · attribution accuracy · real checks (素问 运气七篇, 叔和 chapters) |
| `cases` | Are case records cut into cases and visits, and are their fields read right? | segmentation · per-field accuracy · response and outcome accuracy · agreement of two transcriptions |
| `argument` | Are the steps of reasoning found and typed? | labelled and unlabelled edge P/R/F1 · clause segmentation · same-work vs other-work divergence |
| `senses` | Is a planted shift of senses dated, and a sense no cue names found? | change-year error · detection · labelling accuracy · hidden sense found · curated exemplars |
| `fragments` | Is a lost text rebuilt from its quotations without taking in other sources' words? | precision · coverage · decoy leaks · volume accuracy · real verification (千金, 肘后) |
| `punctuation` | Are the marks of 白文 placed where editors place them, with every character kept? | boundary / sentence F1 · mark-type accuracy · preservation rate · rule baseline · held-out works · Siku 白文 |
| `commentaries` | Are the commentaries on a clause found in every layout, attributed and compared? | unit P/R/F1 · text F1 · relation F1 · quotation recall · real: known commentators and relations |
| `disputes` | Are named views read as rejected or endorsed, and quoted words kept apart? | accuracy · reject / endorse P/R/F1 · real: known controversies |
| `variant_impact` | Is each variant reading classed by what it changes (dose, negation, drug, finding …)? | accuracy · macro-F1 · high-impact P/R/F1 · real: the review queue of the 伤寒论 |
| `clause` | Are the parts of a clause (condition … prognosis) found? | piece accuracy · macro-F1 · per-role F1 · segmentation · real: forms of the 伤寒论 |
| `glosses` | Are the glosses of a word found, and only of that word? | accuracy · P/R/F1 · real: the first gloss of 几几 |
| `pairs` | Do planted drug pairs come first, and do few chance pairs pass Benjamini–Hochberg? | planted top-3 · false significant · real: textbook pairs · 方证 links of 桂枝汤 and 麻黄汤 |
| `schools` | Are a school's planted words found, and do the textbooks' doctrines come out as its own? | planted top-2 and significant · common words listed · citation shares · real: doctrine recall and attribution |
| `names` | Is the change of a drug's preferred name dated, and its names equated and completed? | switch interval · nested names apart · equations · candidates · real: dated taboo renames |
| `chain` | Does each witness of a passage hang from the witness it was copied from? | witnesses found · parent accuracy against the most-similar baseline, with and without convergent spellings |
| `aliases` | Is a drug found under its other names (国老 for 甘草, 通草 for 木通 before 960) without losing the name asked, merging two drugs that share a name or reaching outside the years a name meant the drug? ([below](#alias-layer-aliases)) | synthetic checks; per profile, split and item type, for off, naive, on, analysis and the ablations: P@10 (and its gain where off answers) · nDCG@10 · AskedRet@10 (mean, min) · ON@10 · ON@50 · XR@50 · Wrong@10 · CandRecall · CandPrecision · SilentMerge · FlagP/FlagR · Leakage · latency p50/p95; resolution accuracy |

## Current results (demo corpus)

| Suite | Result |
|---|---|
| invariants | 19/19 held (P01–P10 and nine boundaries added with them); each of six boundaries removed on purpose (scope guard, result firewall, semantic support hook, reducer authority, evidence bounds, publish guard) breaks its invariant |
| interpretive | held-out 82/84 (0.976), 2 unsafe (大黄牡丹汤 read as an indication; 里水, a crux the harvest does not find); dev 23/23. First blind round 43/53 (0.811); round 3, before the crux registry, 7/10 with 3 unsafe cruxes; see below |
| philology | 7/7 |
| claims | P 1.0 · R 0.976 · F1 0.988 (miss: the second 湿痹 sign definition). Before the general PROGNOSIS rule (则愈 / 自愈 / 欲解 / 可治 … / 者死 / 难治 / 不治 …): P 0.976 · R 0.952 · F1 0.964, prognosis recall 0 — this gold is dev |
| provenance | 100% verbatim claims and evidence; mean chain depth 7.8; page/line/region/image unavailable (no images in the demo) |
| hallucination | fabricated 100% · perturbed 100% · wrong span 100% detected; verbatim recall 100%; variant spelling accepted |
| contradiction | 12/12 |
| lineage | P 0.867 · R 0.929 — false positives 逍遥散 ← 苓桂术甘汤 and 补阳还五汤 ← 透脓散 (convergent compositions); miss: 王清任's implicit opposition |
| temporal | constraints 6/6 · earliest 6/6 · leakage 0 |
| anachronism | statements 10/10 · mappings 8/8 · agent equivalence blocked |
| recovery | 4/4 crash points; deterministic rerun; parallel = sequential; replay consistent |
| time_machine (1368) | a passage is on one side of the cutoff only when its whole date range is (straddling texts are in neither the past corpus nor the checking future; none at 1368); 3 decidable predictions, 2 held (taboo rename persisted; lost association stayed absent); failed: the 肾气丸-family core predicted from two members — 张景岳's 左/右归丸 dropped 泽泻·牡丹皮·茯苓 |
| source_rediscovery | 3/3 re-inferred with consistent date bounds |
| ablations | earliest accuracy: all 1.0 · no sense route 0.67 · BM25 only 0.67; contradiction: no sense resolution 0.83 · no philology 0.92; 1 hypothesis would pass G5 only by counting dependent books; Context OS −94% tokens; without the Skeptic 1 rejected hypothesis survives and no revisions happen |
| aliases (synthetic) | 9 planted items on a corpus written for the eval: every check held (side places and retention at k = 5, 10, 20; no merge; gates; readings; periods; flags; no leakage; `off` = today's search); P@10 off 0.800 · naive 0.806 · on 0.933; Wrong@10 6 · 7 · 3; on: CandRecall 1.0, SilentMerge 0, FlagR 1.0, leakage 0 |
| aliases, web-canon on the web store (deployed; [below](#alias-layer-aliases)) | **held-out, 59 items (first report, 2026-10-15): acceptance 6/10 — fails AskedRet min ≥ 0.7 (0.000), ON@50 ≥ 1.5 × off (698 → 829, 1.19×), CandRecall ≥ 0.9 (0.650), SilentMerge = 0 (1)**; holds P@10 0.683 → 0.791 (+0.108; naive 0.728; +0.065 on the 52 items `off` answers), no item type down (least change 0.000, period), AskedRet mean 0.589 → 0.759, Wrong@10 25 → 12, leakage 0, p95 965 → 833 ms. Also nDCG@10 0.658 → 0.788 · CandPrecision 0.765 · FlagP 1.0 · FlagR 0.533 · resolution 0.577 (26 rows). Without bencao_gangmu_skqs: P@10 0.679 → 0.790, the same 6/10. Ablations (held-out P@10 · Wrong@10): gates 0.763 · 26, slots 0.763 · 25, boundary 0.791 · 13, period 0.791 · 12, asked_first all 0.793 · 12, asked_first off 0.763 · 8 (AskedRet 0.622), analysis alone 0.769 · 15. Dev (61 items, tuned on): 0.718 → 0.903, 8/10 (CandRecall 0.889, SilentMerge 4) |
| aliases, full-corpus on the web store (proxy) | **held-out, 59 items (first report): acceptance 7/10 — fails ON@50 ≥ 1.5 × off (690 → 827, 1.20×), CandRecall ≥ 0.9 (0.675), SilentMerge = 0 (1)**; holds P@10 0.673 → 0.805 (+0.132; naive 0.748; +0.105 on the 55 items `off` answers), no item type down (least change 0.000, period), AskedRet mean 0.588 → 0.778 and min 0.700, Wrong@10 32 → 23, leakage 0, p95 1066 → 821 ms. Also nDCG@10 0.658 → 0.800 · CandPrecision 0.794 · FlagR 0.533 · resolution 0.538. Without bencao_gangmu_skqs: P@10 0.669 → 0.803, the same 7/10. Dev: 0.687 → 0.902, 8/10. Two runs on fresh copies of the store (553 books) gave identical numbers, latency aside (both runs shared the machine) |
| aliases, web-canon on the web store (deployed), second report ([below](#second-held-out-report-2026-10-15-after-the-phase-ivv-changes-logged-above)) | **held-out, 59 items (second report, 2026-10-15, after the changes in the [change log](#alias-layer-aliases)): acceptance 6/10 — fails AskedRet min ≥ 0.7 (0.000), ON@50 ≥ 1.5 × off (698 → 849, 1.22×), CandRecall ≥ 0.9 (0.650), SilentMerge = 0 (1)**; holds P@10 0.683 → 0.771 (+0.088, first report +0.108; naive 0.728; +0.042 on the 52 items `off` answers), no item type down (least change 0.000, period), AskedRet mean 0.589 → 0.749, Wrong@10 25 → 12, leakage 0, p95 1124 → 842 ms. Also nDCG@10 0.658 → 0.776 · CandPrecision 0.788 · FlagP 1.0 · FlagR 0.533 · resolution 0.577 (26 rows). Against the first report only the 18 alias items moved in P@10: `on` 0.872 → 0.806, `analysis` 0.883 → 0.844. Without bencao_gangmu_skqs: P@10 0.679 → 0.769, the same 6/10. Ablations (held-out P@10 · Wrong@10): gates 0.742 · 26, slots 0.751 · 25, boundary 0.771 · 13, period 0.771 · 12, asked_first all 0.773 · 12, asked_first off 0.751 · 8 (AskedRet 0.610), analysis alone 0.758 · 15. Dev (61 items, tuned on): 0.726 → 0.918, 9/10 (SilentMerge 2) |
| aliases, full-corpus on the web store (proxy), second report | **held-out, 59 items (second report): acceptance 7/10 — fails ON@50 ≥ 1.5 × off (690 → 798, 1.16×), CandRecall ≥ 0.9 (0.675), SilentMerge = 0 (1)**; holds P@10 0.673 → 0.795 (+0.122, first report +0.132; naive 0.748; +0.095 on the 55 items `off` answers), no item type down (least change 0.000, period), AskedRet mean 0.588 → 0.778 and min 0.700, Wrong@10 32 → 23, leakage 0, p95 1188 → 1116 ms. Also nDCG@10 0.658 → 0.802 · CandPrecision 0.818 · FlagR 0.533 · resolution 0.538. Against the first report: alias items `on` 0.878 → 0.844, their ON@50 330 → 288. Without bencao_gangmu_skqs: P@10 0.669 → 0.793, the same 7/10. Dev: 0.693 → 0.916, 9/10 (SilentMerge 2). One run on a fresh copy of the store, alone on the machine but for its first three minutes; latency is now timed after an untimed first call (change log) |

## The first two layers

**Invariants.**  Nineteen probes, each one of the audit's counterexamples (P01–P10) or a boundary added with them, run
against the harness being evaluated (`src/taochronos/evals/boundaries.py`); `tests/test_boundaries.py` checks the same
boundaries on the default harness.  A probe that cannot run in the environment (no user namespaces for the isolation
tier) is reported as *not exercised*, never as held.  Each probe was checked by mutation — the boundary removed, the
invariant broken, the boundary restored, the invariant held again:

| boundary removed | invariant reported broken |
|---|---|
| BeforeToolCall scope guard | I01: the withheld passage read through `philology.inspect_page` |
| AfterToolCall scope firewall | I02: a tool result naming withheld material reached the caller |
| semantic-support commit hook | I04: a true quote with an inverted relation committed |
| reducer authority for `GateEvaluated` | I12: G7 set by an agent and a validator |
| evidence bound checks | I13: five empty or out-of-bounds records verified |
| publish guard | I18: a report published on hypothesis versions the contract never judged |

**Hard interpretive cases** (`gold/interpretive.yaml`, 107 cases in eight classes).  Every quote is verbatim — passages
of the demo corpus, or excerpts of the full corpus given with their book — and every case has one reading that is
right.  The harness reads each with the readers of a research run: the support reading and the statement frame
(`verification/support.py`), the quote locator, the corpus's date ranges.  *Unsafe* errors are counted apart: a
contradicted claim read as supported, a rejected or reported view read as the author's, a condition dropped, a mixed
witness verified, a disputed order asserted, a possibly later text put before a cutoff.

The split was fixed before the suite first ran, and the rounds are reported as they happened:

| round | cases | result |
|---|---|---|
| 1, blind | 60 written together (7 dev: the cases of changes already made — argument negation, the straddling cutoff — and their controls; 53 held out) | held-out 43/53 (0.811), 4 unsafe: a 或曰 view the author answers kept as the report (3), 「《古今录验》论：」 not read as a citation, 「…者，X主之」 conditions without 若/凡 dropped (2), a formula named by 之 unreadable (2), 「未有不成」 not causal, the 大黄牡丹汤 crux |
| changes | general, not per case: a report governs until the author answers it (余曰 / 答曰 / 曰不然 / 是又不然); a book cited by title and colon is a report; a 者-clause followed in its sentence by an action or a consequence is a condition (a definition is not); an intervention named by 之 is read through its pronoun (不可与之 forbids, 服之则厥逆 warns, 宜服之 prescribes); 未有不 is a causal cue | the 9 round-1 cases that prompted them moved to dev |
| 2, blind | 32 new held-out cases written after round 1 and before the changes ran | 30/32 (0.938), 1 unsafe |
| 3, blind | 10 new held-out cases (7 textual cruxes — a new class — and 3 of the other classes), written before any crux machinery | 7/10, 3 unsafe: cruxes read as plain indications |
| changes | a registry of textual cruxes harvested from the commentaries in the store (`study cruxes`, [study.md](study.md#校勘疑义-cruxes)) — rules for the markers of transposition, emendation, interpolation, omission and doubt, not entries for the cases — consulted by the support reading; cue windows that stop at the next 「……者，」 condition | the 5 round-3 cruxes inspected while the harvest was built, and 2 earlier cases whose output was inspected, moved to dev |
| 4, blind | 5 new held-out cases written after the changes and before they ran on them: two cruxes (§63 麻杏石甘汤 「汗出而喘」, 牡疟 蜀漆散) and three controls | 5/5 — both cruxes read *ambiguous*, the controls still *supports* |
| now | 23 dev · 84 held-out | dev 23/23 · held-out 82/84 (0.976), 2 unsafe |

By class (all cases): negation scope, consequence, reported view, omitted condition, mixed witnesses and disputed dates
1.0; relation inversion 0.94; textual crux 0.92.  The two held-out misses are reported, not patched:

* **大黄牡丹汤** (relation inversion, unsafe): 「脉洪数者，脓已成，不可下也。大黄牡丹汤主之」 — most commentators read the
  formula as belonging before 不可下; they say so in words the harvest's markers do not catch, so no crux is registered.
* **里水** (textual crux, unsafe): the doubt on 里水 in the 越婢加术汤 clause is not stated in a form the harvest reads.
  Earlier misses are now caught: 「此以表有热，里有寒，白虎汤主之」 reads *ambiguous* through the registry (郭雍, 王肯堂,
  周扬俊 and 程文囿 doubt the clause), and 「大便微硬者，可与大承气汤，不硬者，不可与之」 reads *supports*, the prohibition no longer reaching
  back across its own 「……者，」 condition.

## Research value (full corpus)

`taochronos eval research_value` (about 11 minutes; skipped with `--quick` and without the corpus store).  At a cutoff
the store splits into the past — passages whose whole date range lies before it — and the future, the passages wholly
after it; a passage that may have been written on either side is in neither (`corpus.on_side`, bounded in SQL on every
read path).  The rules are in `evals/gold/research_value.yaml`, written before the first run; one change since, recorded
there: weak lexicon entries (254 harvested one-character "drugs" — 药, 补, 白, 按 …) are no candidates.

**Link anticipation** — cutoffs 1127 and 1368; every disease and symptom of the lexicon with 150–6000 past and at least
300 future passages (230 topic–cutoff pairs read, 189 with a link that came true); the candidates are the formulas and
drugs of a topic's past graph not linked to it (29 467), and one comes true when future claims of two books link it to
the topic (1 314, a base rate of 4.5 %):

| ranker | precision@10 | precision@20 | mean average precision |
|---|---|---|---|
| Adamic–Adar (D4) | **0.168** [0.152, 0.185] | 0.131 [0.120, 0.142] | **0.199** [0.175, 0.222] |
| common neighbours | 0.170 [0.154, 0.188] | 0.133 [0.123, 0.145] | 0.208 [0.185, 0.232] |
| resource allocation | 0.149 [0.134, 0.166] | 0.118 [0.108, 0.129] | 0.175 [0.154, 0.197] |
| popularity | 0.134 [0.119, 0.150] | 0.101 [0.092, 0.111] | 0.143 [0.126, 0.161] |
| chance (20 draws) | 0.054 | 0.055 | 0.092 |

Adamic–Adar against popularity: 149 topics better, 39 worse, 1 tie (sign test p = 2.4 × 10⁻¹⁶); 73/21 at 1127 and 76/18 at
1368.  Popularity against chance: 116/73 (p = 0.002).  Examples of anticipated links: 消渴 ⇢ 猪苓汤 and 葛根 (before 1127
and before 1368), 胸痹 ⇢ 栝楼实, 霍乱 ⇢ 干姜, 头痛 ⇢ 黄芩, 人参, 半夏.  The first run, with the weak entries still among the
candidates, gave the same order (0.162 / 0.130 / 0.054).  Common neighbours is marginally ahead of Adamic–Adar inside
the intervals; D4 was not switched on this evidence.

**End to end** — the pipeline run on the past view at 1368 (rules only, about a minute a topic); each structured
prediction is judged by future claims (strict: the association's own relation and a supporting quote; the loose reading
of the first runs gave the same verdicts here).  Topics: dev 消渴, 中风 (inspected case by case while the checks below
were built — they were the first held-out pair); held-out 胸痹, 霍乱, 虚劳, 痰饮 (written before those checks; only
aggregates of their first run were looked at).  No passage outside the past view was read (leakage 0).

| held-out (25 predictions) | before | after |
|---|---|---|
| lost associations stay absent (D1) | 4/9 | 4/9 — the 2 rejected were both wrong; 4/7 of those surviving hold |
| association rules hold | 1/7 | 1/7 |
| hidden associations come true (D4) | 4/8, of which 2 new — the other 2 already written before the cutoff | the 2 already written are rejected (`attested`) |
| surviving predictions that are discoveries (true and new) | 7/23 = 0.30 [0.16, 0.51] | **7/19 = 0.37** [0.19, 0.59] |
| discoveries rejected by review | 1 (by an earlier check) | 1 (the same) |

On the dev topics the surviving discoveries went from 1/12 to 1/8; every lost association predicted for 消渴 and 中风 was
contradicted by later books, and both hidden associations that came true (喘 ⇢ 五苓散, 头痛 ⇢ 承气汤) had been written
before 1368 in books the session had not read.  What the dev runs showed, and what changed
([ADR 0010](adr/0010-speed-cruxes-and-research-value.md)): arguments from silence were tested against co-mentions, a
narrowing to 「不再形成明确记载」 closed the objection unchecked, one-character forms (喘, 寒) were left out of the search,
and the pathogenesis rule read 「寒润五脏治消渴…热毒所生也」 as 寒 causing 消渴.  Now the Skeptic looks for explicit,
supported statements of the association in the whole scope — `restated_after` refutes a loss, `attested` a hidden
link, both hard objections — and 「…所生」 is read where it is said.

The layer's verdict is modest: the ranking D4 rests on anticipates later links well above popularity and chance; the
pipeline's hypotheses, judged one by one, hold about as often as not, and association rules rarely.  The numbers are
small and their intervals wide; a baseline for lost associations is still missing.

## 深层发现 2.0

The seven suites of the 2.0 capabilities ([study.md](study.md#深层发现-20--the-structure-of-the-literature)) measure
each capability in the way its task allows. Where an answer can be constructed, the data are synthetic and the answer
is known. Where rules need examples, a small development set is written with the rules: it shows what they are meant
to do, not how they generalise. And where the literature holds a result, the real corpus is checked against it. The
real-corpus parts run when the corpus store exists and are skipped with `--quick`.

| Suite | Data | Result |
|---|---|---|
| collation | 5 artificial traditions copied from the demo corpus down a known stemma (two branches; one witness copied from both) | variant units: recall 0.998 · precision 0.999; the true split recovered in every trial (RF 0.33: neighbour-joining resolves the true polytomy — three copies made independently from one exemplar — into an extra split); top-3 groups all genuine (all groups 0.73); contamination P 1.0 · R 1.0 |
| reuse | 33 author-constructed pairs (`gold/reuse.yaml`), all eight types and unrelated pairs | accuracy 0.97 · macro-F1 0.965 · mode 0.97; detection P 1.0 · R 0.96 · F1 0.98; the demo corpus's gold transcriptions and rephrasings found by `study.reuse`: 1.0 |
| stratigraphy | 5 composites of 16 000 characters with blocks rewritten in a second author's function characters; the real 素问 and 伤寒论 | layer accuracy 0.955; boundaries R 0.90 · P 0.93; change points R 0.45 · P 1.0; attribution 0.89 · real: the 运气七篇 7/7 in the minor layer, both of their boundaries found, 3 of the 4 chapters flagged by late vocabulary are 运气 chapters, 辨脉法 and 平脉法 nearest the 脉经 |
| cases | 6 constructed cases in the two manners of the literature — visits under a heading, narratives (`gold/cases.yaml`); the two transcriptions of 吴鞠通医案 | segmentation, fields, responses, outcomes 1.0 on the development set · real: case counts agree 0.98, outcomes 0.92 |
| argument | 18 author-constructed passages (`gold/argument.yaml`); the 脉经's two transcriptions against 温病条辨 | edges F1 1.0 on the development set · real: JSD 0.020 between the transcriptions of one work, 0.091 against another |
| senses | synthetic occurrences: one sense rises from 15 % to 75 % in the year 1000, an uncued sense appears from 1300 | change year within 2.3 years; detected 1.0; labelling 0.93; the uncued sense found 1.0 (precision 1.0); curated exemplars of 消渴 6/8 |
| fragments | a constructed lost work (集古方, held out) quoted by four books in the manners of the 外台秘要, the 医心方, the 证类本草 and a late paraphrase, beside other sources (`gold/fragments/`); the real 千金 and 肘后 | precision 0.86 · coverage 1.0 · no other source's words taken in · volumes 1.0 · real: 千金 precision 0.32 · coverage 0.12; 0.876 of the 肘后's quotations not in the extant text |

## The task specification (docs/tasks.md)

The ten suites of the capabilities added with the [task specification](tasks.md) (T4–T6, T10, T13, T15–T17,
T20–T21, T25–T26 and T9/T24) follow the same rule — synthetic data where the answer can be constructed, a development
set where rules need examples, the literature's own results on the real corpus:

| Suite | Data | Result |
|---|---|---|
| punctuation | the store's punctuated texts; 55 works held out of training (104 k characters); 4 Siku 白文 works against their 笈成 punctuation | held-out boundary F1 0.767 (P 0.725 · R 0.814; rules 0.235), typed sentence F1 0.543, mark types 0.805; 白文 boundary F1 0.780 (rules 0.303); characters preserved 1.0 |
| commentaries | a constructed classic with commentaries in four layouts (`gold/commentaries/`); the real 太阳之为病 | units F1 1.0 · text F1 0.81 · relations F1 1.0 · quotations 1.0 · real: 25 commentaries, known commentators 11/11, 张卿子 照录 成无己 and 喻昌 承袭 方有执 found |
| disputes | 22 author-constructed sentences (`gold/disputes.yaml`) | accuracy 0.86 · reject P 1.0 R 0.78 · endorse P 0.8 R 1.0 · real: 3/3 known controversies (景岳 on 丹溪's 相火, 越人's 左肾右命门 …) |
| variant_impact | 30 readings (`gold/variant_impact.yaml`) | accuracy 0.97 · macro-F1 0.97 · high impact P 1.0 R 0.94 · real: the 伤寒论's 288 units, the top 10 of its review queue all high-impact |
| clause | 16 clauses of the 伤寒论 and 金匮 (`gold/clause.yaml`) | pieces 0.977 · macro-F1 0.92 · real: 40 % of the pieces of the fullest 伤寒论 witness read by no rule (平脉法 dialogues, numbering, notes) |
| glosses | 16 sentences (`gold/glosses.yaml`) | accuracy 1.0 · P/R 1.0 · real: 成无己's 伸颈之貌 the first gloss of 几几 |
| pairs | 600 synthetic compositions with three planted pairs; the store's 66 196 compositions | planted top-3 1.0 · false significant 0.0 · real: 7/7 textbook pairs significant with lift > 1.5 (桂枝—芍药 2527 compositions, lift 2.05; 麻黄—杏仁 5.08 …) |
| schools | 5 synthetic 温病 physicians and 16 other authors; the store's schools with the textbooks' doctrines (`gold/schools.yaml`, 44) | planted words top-2 and significant, no common word listed · real: doctrine recall 0.73 (z ≥ 1.96), attribution 0.64 |
| names | 20 synthetic works (薯蓣 → 山药); the dated taboo renames (`gold/names.yaml`) | switch interval, nested names, equation, candidate 山芋 all right · real: 2/2 (薯蓣→山药 in 1000–1200, 玄参→元参 in 1600–1800) |
| chain | 6 artificial traditions of 12 witnesses; with each copy regularising spellings on its own | parent accuracy 1.0 (most-similar baseline 0.97); with convergent spellings 0.94 (baseline 0.87); witnesses found 0.96–1.0 |

These numbers describe the rules on the data they were written for. They are not benchmarks. Expert-annotated gold
on the full corpus (a collated chapter with its stemma, typed reuses, segmented case records, argument graphs, dated
sense shifts) is on the roadmap.

## V2: rules first, a model second (docs/v2.md)

The suites of the V2 capabilities.  The model phases run too when `TAOCHRONOS_EVAL_LLM=provider:model` is set
(e.g. `minimax:MiniMax-M2.7`); the numbers below are the rules'.

| Suite | Data | Result |
|---|---|---|
| entities (T7) | 41 dev sentences, 160 entities (`gold/ner.yaml`); **25 held-out sentences**, 117 entities, annotated after the rules were written (`gold/ner_heldout.yaml`) | dev F1 0.991 · **held-out F1 0.776** (P 0.783 · R 0.769) |
| places (T27) | 15 signatures and 5 statements of native place in the forms of real prefaces and biographies, with traps (`gold/places.yaml`); the full corpus | P/R 1.0 · 84.6 % of physicians placed · real: 291 of 761 works placed, curated places confirmed 4/4, 湿温 in 清 江南 49 % vs 26 % (q 0.108, not significant) |
| translation (T10) | 24 presentism cases (equations, retrospective diagnoses, modern names a translation adds, comparisons that must pass); the demo corpus | guard 24/24 · original layer unchanged 24/24 · doublets glossed by their commentators 3/3 |
| layout (T1–T2) | 60 synthetic pages (vertical, 双行小注, 版心, 书眉; noisy and character-level variants); four OCR formats; 12 OCR texts with one error each | reading order exact 0.983 · CER 0.0005 · notes F1 0.999 · formats identical · errors located 12/12 |
| bridge (AMBE) | 20 dev sentences; **12 held-out passages** drawn at random from 65 clinical works of the full corpus, annotated before the reader ran on them; 18 canonical descriptions and 2 negatives (`gold/bridge.yaml`) | dev F1 0.985 · **held-out P 0.938 · R 0.732 · F1 0.822**, bounds 1.0 · mapping top-1 1.0, caps 3/3, guard 20/20 · 213 HPO ids valid in hp/releases/2026-09-01 |
| audit (S15) | 19 claims of every kind and 3 safety texts (`gold/audit.yaml`) | verdicts 1.0 · kinds 1.0 · false SUPPORTED 0 · safety 3/3 |
| modern (S13–S14) | 10 records to type, 7 claim/evidence pairs for the cross-level guard, the synthetic OMOP database (`gold/modern.yaml`) | typing 10/10 · guard 7/7 · RWD: SQL checks pass, planted association recovered, bad SQL refused |
| workflow (V2) | the registry; 8 questions with the skills they need and must not call (`gold/workflow.yaml`); one end-to-end run | registry valid · plans 8/8 · a rerun reads every step from its workspace |

The held-out sets (NER, bridge) were annotated before the rules ran on them; the forms they miss were not added after
scoring, so their numbers are the estimate of generalisation.  Everything else is dev: what the rules are meant to do.

## Alias layer (aliases)

`src/taochronos/evals/aliases.py` measures the alias layer ([ADR 0023](adr/0023-alias-layer.md)) on the frozen gold
`evals/gold/aliases.yaml` (120 items in six types, 80 resolution rows; its construction, split and leakage rules are in
[evals/gold/README.md](../evals/gold/README.md)).

```bash
taochronos eval aliases --quick                                   # the synthetic part only (well under 2 s)
taochronos --data <web data> eval aliases -o aliases-web.json     # web-canon (deployed) and full-corpus (proxy) on the web store
taochronos --data /srv/data eval aliases -o aliases-full.json     # on the site's full store: the server, or the aliases.yml workflow
TAOCHRONOS_ALIAS_EVAL_SPLITS=dev TAOCHRONOS_ALIAS_EVAL_SYSTEMS=off,naive,on taochronos --data <data> eval aliases
```

* **Synthetic part** — always runs: a corpus and a layer written for the eval, planted with 将军 beside 大将军 and
  将军之官, 通草 before and after 960, a name two drugs share (鬼督邮), 蜜甘 inside 石蜜甘, 黄连 inside 胡黄连, the weak 葛
  inside 干葛, 山药 before its first use (1063), and passages on 虚劳 that outrank the asked name in 国老治虚劳 and
  甘草治虚劳. It checks the side queue's places (at most ⌊3k/10⌋ while the main queue lasts) and the asked name's
  retention (at least min(|A|, k − ⌊3k/10⌋), which only the asked-first rule keeps in those two questions) at k = 5, 10
  and 20, that no ambiguous name is merged, the gates, the readings, the anachronism flags, that no hit leaves the question's window and that
  `off` is today's search (ids and scores), and scores its nine items like the gold.
* **Store part** (skipped with `--quick` and without a store under `--data`) — each profile of
  `$TAOCHRONOS_ALIAS_EVAL` (default `web-canon,full-corpus`), on a harness whose corpus leaves the 别名录 (`jc_c030`) out
  of every read path (`EvalContext.profile_harness`), and again without `bencao_gangmu_*` (view `no-gangmu`). The result
  records the store (`sha`, books, passages, edition), the store the layer was built on, and whether the pair is
  deployed (web-canon on the web store, full-corpus on the full store) or a proxy, and checks the gold on the store
  first (`aliases_gold.validate` with its witnesses, and on the web store it was drawn from, its pools).
  Each harness extracts its claims into a cache of its own (a temporary table on its connection to the store): the
  store's claim cache is keyed by the extractor and the variants but not the lexicon, so a profile reading it would
  get claims another profile's lexicon made (the numbers then depended on which profile ran first), and the eval would
  write them into the store under `--data` — the site's store, for the third command. The eval writes nothing into
  the store; its first queries pay for extracting claims, as on a fresh store.
* **Systems** — `off` (B0, today's search); `naive` (B1: today's search with the layer's own one-hop pairs added to
  the question as lexicon surfaces — the layer's names it writes, as written; the heads of the drugs each is an open or
  cue name of, with their spellings; the open and cue names of the drugs each, or a lexicon herb of the question,
  heads — at most `expansions` of them, alias→drug first, with no gates, windows or reserved places: 国老 adds 甘草,
  not 甘草's other names); `on` (B2); `analysis` (the layer's reading of the question alone — names asked as written,
  gated-out hits last — with no expansion, side queue or retention: what the layer gains without other names); and
  the ablations `gates`, `boundary`, `slots`, `period`, `asked_first:all` and `asked_first:off`. Each item is searched at k = 10 and at
  k = 50. Latency is the k = 10 call, timed only after every system has searched the item once untimed at k = 10 (the
  systems' order still turns with the item): a first call fills caches the others then read (the claims of the item's
  passages, extracted into the harness's own cache), and timing first calls charged that cost to whichever system ran
  first, so the rotation decided the p95 comparison. The warm-up adds one untimed search per system and item to a run.
  The first held-out report was timed on those first calls, cold, and on a shared machine: its p50 and p95 compare
  fairly neither its systems nor the second report's.
* **Labels** come only from each item's patterns, on the normalised text with every false friend masked: *asked* (the
  asked form, and one of its cues anywhere in the passage when the item has cues), *other* (a referent's name, the passage's range inside that
  referent's window), *wrong* (neither, and a wrong name, the asked form only inside a masked string, or in a passage
  without a cue);
  relevant = asked or other. The module never imports or calls the layer's gates (`tests/test_evals.py` checks).
  N_rel, N_asked and N_other are counted in the store inside the question's window, up to 50.
* **Metrics** (spec §3.10) per split (dev, heldout, all) and item type: P@10; nDCG@10 (binary gains, ideal over
  min(10, N_rel)); AskedRet@10 = asked hits ÷ min(10, N_asked), its mean and its least value over the items with
  N_asked ≥ 7, traps left out; ON@10 and ON@50 (other, not asked) and XR@50 = ON@50 ÷ min(50, N_other) (neither
  capped at 1, so that a short count shows); Wrong@10;
  CandRecall and CandPrecision of `expect_candidates` against the drugs `query.aliases` names for the asked form whose
  window meets the question's (a drug→alias expansion names the drug the asked form heads: 丹砂, whose names include
  朱砂, names 朱砂; a stop name asked on its own names the drugs it lists beside its note, status `stop`: 解离 →
  防己 — except for an item that expects none, which reads the name as no drug, as the stop's note does), mapped to the
  item's referents by their heads and the item's names first, then — a listed drug that is the asked drug itself, the
  asked form or a form of the lexicon herb entry the question reads it as (`asked_forms`) — by those forms too: 紫葳,
  whose entry holds 凌霄花, names 凌霄花 (a form the item calls wrong is none of them, and forms meeting two referents
  map neither) — else through the gold's same-drug names
  (`same_drug`: a name the gold gives two heads is none; the asked form is never mapped so); the asked form itself
  counts only where the item expects it as a drug of its own (苦菜 beside 贝母), not where it is the lexicon's entry for
  the name asked (胡王使者) or the drug a head names (铜绿 → 铜青); SilentMerge (ambiguous items with fewer than two of
  their expected drugs named, all of them when one is expected); candidates and SilentMerge are None for `off` and
  `naive`, which list none; FlagP and FlagR of `anachronism:` flags on the period items with a floor; Leakage (hits whose midpoint year
  lies outside the window); latency p50 and p95. The resolution rows are scored by what the analysis answers for the
  surface asked alone (expand, candidate or none, heads matched through the same-drug names; a stop name's listing is
  no reading of the name and leaves the action as the rest of the answer makes it). The acceptance of §3.10
  is computed on the main view of each profile (held-out when it ran); beside it (not a check), the P@10 gain on the
  items `off` answers with at least one hit (`answered`), since a question today's search finds nothing for scores 0
  under `off` and the layer gains there by searching the name as written, which `analysis` measures alone.
* **Held-out discipline** — held-out items are reported in aggregate only (`details` lists dev items), are never
  tuned on, and are not run at all while the gold fails `aliases_gold.validate` (its split pin among the checks). `TAOCHRONOS_ALIAS_EVAL_SPLITS`, `TAOCHRONOS_ALIAS_EVAL_SYSTEMS` and `TAOCHRONOS_ALIAS_EVAL_VIEWS` restrict
  a run. Any parameter change after the first held-out report is logged here with its date:

| date | change |
|---|---|
| 2026-10-15 | **Measurement correction** after the first held-out report (the eval's candidate count; no parameter or data of the layer changed). `listed` maps a drug `query.aliases` names that is the asked drug itself — the asked form or a form of the lexicon herb entry the question reads it as (`asked_forms`) — with those forms, so 凌霄花 under 紫葳 counts (紫葳's entry holds 凌霄花); and a stop name asked on its own counts the drugs it lists beside its note (status `stop`: 解离 → 防己) as candidates, which `resolve` does not read as a reading of the name. Dev alone (web-canon, `on`), on the layer of the first report (4f031b6): CandRecall 0.889 → 0.907, CandPrecision 0.828 → 0.831; on the layer of 100444a, which lists stops: 0.907 → 0.926, 0.831 → 0.833; nothing else moves. |
| 2026-10-15 | **Gold correction** after the first held-out report, dev items only (ids, groups, splits and `SPLIT_SHA256` unchanged; no held-out item was changed or looked at): eight real other names that dev runs showed missing, each `adjudicated` `by: correction` with a witness in the store outside jc_c030 and 纲目 — 凌霄 under 紫葳/凌霄花 (alias-08, ambiguous-09), 姜芥 under 荆芥 (alias-11), 鹿胶 under 鹿角胶 (head-25, substring-04), 荼草 and 游冬 under 苦菜 (ambiguous-n1), 硝石 under 消石 (ambiguous-n3), 慈石 under 磁石 (ambiguous-s08), 鸡舌香 under 丁香 (substring-05). Not added: 地锦 for 夜光's 地朕 (no passage outside 纲目 equates them) and 马兜铃 for 清代的青木香 (the fruit, another part; no passage writes a root name beside 青木香). Dev alone (web-canon), the same on the layers of 4f031b6 and 100444a: P@10 `off` 0.718 → 0.728, `on` 0.903 → 0.918; ON@50 433 → 449 and 1039 → 1061; SilentMerge 4 → 2; AskedRet, Wrong@10, leakage and resolution unchanged; CandRecall 0.907 → 0.944 and CandPrecision 0.831 → 0.864 on 4f031b6's layer, 0.926 → 0.963 and 0.833 → 0.867 on 100444a's. |
| 2026-10-15 | **Measurement correction** on review of the two rows above (the eval's candidate count; no parameter or data of the layer changed). A listed drug maps to the referent whose head or names it is before any names it carries (an expansion's surfaces, the asked drug's forms), so that forms holding two referents no longer make 玄石 into 磁石 under 处石; the asked drug's forms leave out the names the item calls wrong and are not used when they meet two referents; and for an item that expects no candidate (a stop the gold reads as no drug), the drugs a stop's listing shows beside its note are no candidates, so they cost no precision — where the item expects candidates they count both ways, as before. Dev (100444a's layer): no number moves (CandRecall 0.963, CandPrecision 0.867, SilentMerge 2). |
| 2026-10-15 | **Gold correction** on review, dev items only (groups, splits and `SPLIT_SHA256` unchanged): 硝石 (ambiguous-n3) and 慈石 (ambiguous-s08), whose witnesses wrote them only beside the item's other referent (芒硝, 玄石), are witnessed by `parallel` rows that tie them to their own (jc_d001.00024 《本经》原文 硝石 ∥ ws_36bca7b992.00020 消石; ws_36bca7b992.00137 慈石 ∥ jc_d001.00409 《本经》原文 磁石); two non-drug strings the new names brought in are masked: 凌霄观 (a building; alias-08, ambiguous-09) and 姜芥水肿 (a 水痘 text; alias-11); the comments on 凌霄's and 鹿胶's witnesses say what they are. Dev (100444a's layer): P@10 `off` 0.728 → 0.726 (alias-11's 水痘 passage at rank 10), ON@50 449 → 448 and 1061 → 1059; nothing else moves. |
| 2026-10-15 | **Rebuild** of the layer (`aliases.jsonl` f0d79c978c30 → 46d2245f0e30, `context.json`) on the web store (fe8fa73507f9): the first since the first report's layer (4f031b6), with the build and curated changes of 100444a and its review. Blockers: curated `unblock` rows free 党参 of 防风党参, 假苏 and 荆芥 of 假苏荆芥, and 青矾 of 青矾石; the 纲目 joint headings the lexicon harvested as one name block neither name (枸杞地骨皮, 独活羌活, 虎掌天南星, 赤箭天麻; 薰草零陵香 blocked nothing), while headings from other materia medica still block (防风党参 of 防风, the 根皮 titles); four straddle blockers go (常山, 恒山, 磁石, 黄芪); a string that is both a cover string and an unblocked string of a name stays a cover blocker. Pair: 独摇草 → 独活 (curated). Records: 2,723 → 2,724 (独摇草 added), 35 changed; pairs 2,136 → 2,138, cue 1,099 → 1,101; 16 blockers dropped on 16 names (blocked records 404 → 394); n rises for 独活 (993 → 995), 青矾 (15 → 18), 木香 (+4), and 常山, 磁石, 黄芪, 甘草, 甘遂 and 茴香 (+1 each); 防风 is unchanged; 党参, 官桂, 浙贝, 苍术 and 鬼督邮 gain `ho` (heads 782 → 787), so `context.json`'s herb list gains 官桂, 浙贝 and 党参; `sh` rises by 0.01–0.07 for 12 names (老米 0.36 → 0.43). 469,984 bytes (103,055 deflated; the directory 143,504 of 150,000, as `home.zip` stores them). `aliases check --db` passes, and a second build gives the same bytes. Dev only (the working tree's code, the old layer against the rebuilt one; off, naive and on; both profiles and views): one item moves, ambiguous-01 (鬼督邮是什么药). Two 纲目 passages that write 鬼督邮 enter its top 50 and push out two side hits, so ON@50 `on` in the main view goes 1059 → 1057 (web-canon) and 1061 → 1059 (full-corpus). The no-gangmu view, every other number and every item's top-10 labels are unchanged. |
| 2026-10-15 | **Search changes of phase IV**, logged late (100444a and its review in 2bc7931; code, no profile parameter): a hit's `via` names the asked names it was found for (`for`); a stop name asked on its own (救火是哪味药, 宋以前的解离) is listed in `query.aliases` with the drugs its record and the lexicon give it (status `stop`) and is never expanded — before, the lexicon's entry for 救火 searched 护火 and 辟火; an expansion given no place says why (`routes`, `share`); a lexicon referent shows under its same-drug group's head; a bare side passage (the name and fewer than 4 other characters once formula names are set aside, without drug context) goes after the others of its drug, nothing dropped; research evidence records keep each hit's `via` and flags as their note. Dev (web-canon and full-corpus, `on`, the first report's layer, as the unit measured it): P@10 0.903 and 0.902, ON@50 1039 and 1041, Wrong@10, SilentMerge, leakage and every item's labels unchanged; bare side hits in web-canon's top 10 about 20 → 0; the candidate counts the stop listing moves are those of the first row (100444a's layer). |
| 2026-10-15 | **Full corpus on** (bb2a948): `profiles/full-corpus.yaml` turns the layer on (`alias: {enabled: true}`) on the server, and the D1 backup searches with its port of it. The eval sets each system's mode itself, so none of its numbers moves, and its full-corpus numbers stay a proxy on the web store. The alias directory is measured at zlib's default level, as `home.zip` stores it (the budget only; the layer's bytes are unchanged). |
| 2026-10-15 | **Review of phase V** (the working tree on bb2a948). *Question reading*: a blocker the lexicon reads itself (川乌头, filed under 川乌) keeps its lexicon mention, asked with its term and forms; a dose beside a name nobody knows (葛二两) leaves it the question's one name; a longer name nobody knows takes in only a part or form after a drug's name and a preparation before it (人参叶, 甘草梢, 酒大黄), never what a question says of the drug (甘草入脾 asks 甘草 and 脾); a stop asked on its own that the lexicon files as a herb (救火 under 景天) is asked as that herb's name, its hits gated and labelled status `stop`. *Labels*: a hit is read as an asked name's drug only where that name passes the gates in it (本司马大将军方 is no reading of 将军). *Readings*: a passage after a name's window is counted from the window's last year (to − 1), a year further than before, so its fit falls by 1/600 above the floor. *Build*: a section's numbering no longer takes the numeral a drug's name opens with (五味子, 百合, 三七); the rebuilt layer (`aliases.jsonl` 46d2245f0e30 → 74ac7543ff4f, `context.json` unchanged) changes two records' witnesses — 会及 (五味子) has two 《本经》 witnesses for one, 强瞿 (百合) gains two and the source `store` — from 469,984 to 470,085 bytes, the directory from 143,504 to 143,523 deflated; `aliases check --db` passes and a second build gives the same bytes; curated rows whose names normalise alike are one row, and the local build counts with the shipped `context.json`. *Eval*: latency is timed after every system has searched the item once untimed (a first call fills the claim cache the others read; only p50 and p95 can move), and the held-out split is refused when the gold fails its checks on the store, as on file. Dev (both profiles and views, all ten systems; bb2a948 against the final tree, on the same store): one item moves, trap-10 (宋以前的解离), now asked as the name of the herb the lexicon files it under — with `on` its asked hits rise from 3 to 5 of the top 10 (AskedRet 0.6 → 1.0, ON@10 7 → 5, P@10 1.0 unchanged), while in the `gates` ablation two wrong hits enter it (P@10 1.0 → 0.8). So dev AskedRet `on` goes 0.809 → 0.816 (web-canon) and 0.807 → 0.814 (full-corpus), ON@10 184 → 182, and `gates` P@10 0.882 → 0.879 and 0.880 → 0.877, Wrong@10 18 → 20 and 19 → 21; nothing else moves on dev, `off` included. |
| 2026-10-15 | **Second held-out report** ([below](#second-held-out-report-2026-10-15-after-the-phase-ivv-changes-logged-above)), run once on the tree with every change above (`aliases.jsonl` 74ac7543ff4f); no change since. |

### Second held-out report (2026-10-15), after the phase IV/V changes logged above

Run once, on the final tree: a frozen snapshot of the working tree (bb2a948 with the review changes logged above;
`aliases.jsonl` 74ac7543ff4f, `hybrid.py` 3f06ac1e186f by sha1), on a fresh copy of the web store (fe8fa73507f9: 553
books, 168,278 passages), with the defaults — `taochronos --data <copy> eval aliases -o aliases-web.json`: both
profiles, dev, held-out and all, the views main and no-gangmu, all ten systems; 98 minutes (each item's k = 10 call
now runs twice, once untimed), alone on 4 cores but for its first three minutes. The gold validated on file and on the
store (witnesses and pools; split pin cd186cf8937f); `aliases check --db` passes (2,724 surfaces; a rebuild gives the
same bytes); the synthetic part holds every check with the first report's numbers; `eval --quick` gives the 35 other
suites the same metrics, details and notes as f4f9aca, timings aside. Held-out items are reported in aggregate only:
none was run on its own or looked at.

**Acceptance on the 59 held-out items** (main view): web-canon meets 6 of 10 and full-corpus 7 of 10 — the checks
that failed in the first report fail again, and the acceptance is not met.

| check | web-canon (deployed) | full-corpus (proxy) |
|---|---|---|
| P@10 ≥ off + 0.03 | 0.683 → 0.771 (+0.088; first report +0.108), holds | 0.673 → 0.795 (+0.122; first +0.132), holds |
| no item type down by more than 0.05 | least change 0.000 (period), holds | least change 0.000 (period), holds |
| AskedRet min ≥ 0.7 | **0.000, fails** (first 0.000) | 0.700, holds |
| AskedRet mean ≥ off | 0.749 vs 0.589 (first 0.759), holds | 0.778 vs 0.588 (first 0.778), holds |
| ON@50 ≥ 1.5 × off | **849 vs 698, 1.22× (first 829, 1.19×), fails** | **798 vs 690, 1.16× (first 827, 1.20×), fails** |
| Wrong@10 ≤ off | 12 vs 25, holds | 23 vs 32, holds |
| CandRecall ≥ 0.9 | **0.650, fails** (first 0.650) | **0.675, fails** (first 0.675) |
| SilentMerge = 0 | **1, fails** (first 1) | **1, fails** (first 1) |
| Leakage = 0 | 0, holds | 0, holds |
| p95 ≤ 1.5 × off | 842 vs 1124 ms, holds | 1116 vs 1188 ms, holds |

Without bencao_gangmu_skqs the same checks hold and fail: web-canon P@10 0.679 → 0.769, ON@50 694 → 849, Wrong@10
26 → 12, p95 962 vs 974 ms; full-corpus P@10 0.669 → 0.793, ON@50 688 → 798, Wrong@10 34 → 23. Beside the checks:
nDCG@10 0.658 → 0.776 (web-canon) and 0.658 → 0.802 (full-corpus); CandPrecision 0.788 and 0.818; FlagP 1.0 and FlagR
0.533 on both, for every layered system but `analysis`, `slots` and `asked_first:off` (FlagR 0.800); the P@10 gain on
the items `off` answers +0.042 (52 items) and +0.095 (55); resolution accuracy 0.577 and 0.538 (26 held-out rows).

**Held-out, main view, 59 items** (P@10 · Wrong@10 · AskedRet mean / min · ON@50):

| system | web-canon | first report | full-corpus | first report |
|---|---|---|---|---|
| off | 0.683 · 25 · 0.589 / 0 · 698 | the same | 0.673 · 32 · 0.588 / 0 · 690 | the same |
| naive | 0.728 · 21 · 0.584 / 0 · 947 | the same | 0.748 · 33 · 0.652 / 0 · 908 | the same |
| on | 0.771 · 12 · 0.749 / 0 · 849 | 0.791 · 12 · 0.759 / 0 · 829 | 0.795 · 23 · 0.778 / 0.7 · 798 | 0.805 · 23 · 0.778 / 0.7 · 827 |
| analysis | 0.758 · 15 · 0.649 / 0 · 713 | 0.769 · 15 · 0.661 / 0 · 698 | 0.778 · 23 · 0.686 / 0 · 705 | 0.783 · 23 · 0.672 / 0 · 703 |
| −gates | 0.742 · 26 · 0.753 / 0 · 892 | 0.763 · 26 · 0.763 / 0 · 876 | 0.766 · 40 · 0.770 / 0.7 · 846 | 0.776 · 40 · 0.770 / 0.7 · 874 |
| −boundary | 0.771 · 13 · 0.749 / 0 · 852 | 0.791 · 13 · 0.759 / 0 · 831 | 0.795 · 24 · 0.778 / 0.7 · 801 | 0.805 · 24 · 0.778 / 0.7 · 830 |
| −slots | 0.751 · 25 · 0.658 / 0 · 931 | 0.763 · 25 · 0.670 / 0 · 916 | 0.768 · 33 · 0.686 / 0 · 881 | 0.773 · 33 · 0.673 / 0 · 912 |
| −period | 0.771 · 12 · 0.749 / 0 · 849 | as `on` | 0.795 · 23 · 0.778 / 0.7 · 798 | as `on` |
| asked_first:all | 0.773 · 12 · 0.749 / 0 · 849 | 0.793 · 12 · 0.756 / 0 · 829 | 0.793 · 23 · 0.778 / 0.7 · 815 | 0.807 · 23 · 0.775 / 0.5 · 827 |
| asked_first:off | 0.751 · 8 · 0.610 / 0 · 973 | 0.763 · 8 · 0.622 / 0 · 953 | 0.764 · 21 · 0.637 / 0 · 930 | 0.769 · 21 · 0.623 / 0 · 946 |

**By item type** (held-out, P@10 `on` − `off`; alias 18 items, head 15, ambiguous 5, period 6, trap 9, substring 6):
web-canon +0.128, +0.073, +0.060, 0.000, +0.144, +0.033 (first report: alias +0.194, the rest the same); full-corpus
+0.233, +0.067, +0.040, 0.000, +0.167, +0.050 (first: alias +0.267). ON@50 by type on web-canon, `off` → `on`: alias
207 → 336, head 151 → 142, ambiguous 98 → 78, period 114 → 104, trap 126 → 187, substring 2 → 2.

**What moved since the first report** (aggregates only). `off` and `naive` give the same held-out numbers, latency
aside: the held-out gold and today's search are unchanged. Every layered system lost P@10 on the 18 alias items and
on no other type: `on` 0.872 → 0.806 on web-canon and 0.878 → 0.844 on full-corpus. `analysis`, which searches no
other name, lost on the same items (0.883 → 0.844 and 0.883 → 0.867), so at least part of the loss lies in how the
asked name itself is read or gated, not only in the other names. On the head items the layer now brings more
other-name hits into the top 10 (web-canon ON@10 21 → 29, nDCG@10 0.911 → 0.954, P@10 unchanged); on full-corpus the
alias items' ON@50 fell 330 → 288, which takes its ON@50 ratio from 1.20× to 1.16×. CandPrecision rose (0.765 →
0.788, 0.794 → 0.818) with the measurement corrections above; CandRecall, SilentMerge, FlagP, FlagR, leakage and
resolution are unchanged. Which of the changes logged above cost the alias items is not known: the dev runs logged
with them show no such loss, and looking for it item by item would be tuning on the held-out half.

**Dev and all items.** Dev (61 items, tuned on): web-canon P@10 0.726 → 0.918, full-corpus 0.693 → 0.916; 9 of 10
checks hold on both, SilentMerge (2) fails; AskedRet min 0.700, CandRecall 0.963, CandPrecision 0.867, Wrong@10 20 →
6 and 20 → 7. All 120 items: web-canon 7 of 10 (AskedRet min 0.000, CandRecall 0.830 and SilentMerge 3 fail),
full-corpus 8 of 10 (CandRecall 0.840, SilentMerge 3). Dev and held-out still diverge: ON@50 is 2.36× `off` on dev and
1.22× on held-out (web-canon), CandRecall 0.963 against 0.650.

**Latency.** p50 and p95 are now timed after an untimed first call per system and item, and the first report's two
runs shared the machine while this one ran alone, so neither is comparable across the reports. Within this run the
layer is not slower at the 95th percentile: `on` 842 ms against `off` 1124 ms on web-canon, 1116 against 1188 ms on
full-corpus (p50 71 against 65 ms, 79 against 94 ms).

## Full corpus

The suites above run on the demo corpus, whose gold they were built against. On the full corpus
(`--profile full-corpus`) the same machinery runs end to end — e.g. the 消渴 question: a frame of 2,400 of 32,736
matching passages (84 books, six periods), 2,444 claims, 95 evidence and 41 counter-evidence records and 22
hypotheses in about a minute offline — and `tests/test_corpus_store.py` checks the parser, the store, verbatim
provenance of claims read from unpunctuated text and a research run over a store. Gold for the full corpus
(punctuation, claims, dating of layers) is future work.

## Study layer

The 治学 functions ([study.md](study.md)) are checked by `tests/test_study.py` on a synthetic corpus written for the
purpose (`tests/fixtures/study`: two copies of one work, a quotation, compositions in several periods, an entry headed
by its formula's name, bracket-less preparation notes with a shared dose, verses, taboo spellings and named
citations): the relation and apparatus of the concordance, the original / current / single-witness groups and the dose
readings of formula provenance, first statements of drug properties, shares and intervals of term histories, taboo
verdicts and edition bounds, citation resolution, cards, reading paths, the data package, the tools, the CLI and the
Scholar's dossiers in a research run. On the full corpus the functions were checked against known results of the
literature (the 小儿药证直诀 origin of 六味地黄丸, the 金匮 崔氏八味丸 for 肾气丸, 黄龙汤 as another name of 小柴胡汤, the Song
丸 → 圆 taboo in the 千金 books); a gold set of expert-checked witnesses for formula parsing and property extraction is
on the roadmap.

## Baselines

The time machine's link-level table compares Adamic–Adar with resource allocation, common neighbours,
popularity and random rankings. On the demo corpus only one link appears for the first time after 1368,
so the table documents the protocol, not a result; on the full corpus it is `research_value` (above).

## Adding gold

Each suite reads one YAML file; the schemas are documented at the top of every file. Claims gold is
*complete* per listed passage (unlisted extracted claims count as false positives); lineage gold has
positives and negatives (other predictions are reported as unjudged).
