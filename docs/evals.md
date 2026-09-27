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
