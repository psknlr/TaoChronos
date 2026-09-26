# TaoChronos-Eval

```bash
taochronos eval                  # all suites (~2 min with the corpus store: the 2.0 suites also check the real corpus)
taochronos eval --quick          # fast subset
taochronos eval claims temporal -o results.json
```

Gold sets live in `evals/gold/` — **author-constructed for the demo corpus and used during development**.
Read the scores as regression tests of intended behaviour, not benchmark results; replace the gold with
expert annotations before drawing conclusions about a real corpus.

| Suite | Question | Metrics |
|---|---|---|
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

## Current results (demo corpus)

| Suite | Result |
|---|---|
| philology | 7/7 |
| claims | P 0.976 · R 0.952 · F1 0.964 (misses: a prognosis clause of 伤寒论 §71, the second 湿痹 sign definition; one spurious `theory` claim) |
| provenance | 100% verbatim claims and evidence; mean chain depth 7.8; page/line/region/image unavailable (no images in the demo) |
| hallucination | fabricated 100% · perturbed 100% · wrong span 100% detected; verbatim recall 100%; variant spelling accepted |
| contradiction | 12/12 |
| lineage | P 0.867 · R 0.929 — false positives 逍遥散 ← 苓桂术甘汤 and 补阳还五汤 ← 透脓散 (convergent compositions); miss: 王清任's implicit opposition |
| temporal | constraints 6/6 · earliest 6/6 · leakage 0 |
| anachronism | statements 10/10 · mappings 8/8 · agent equivalence blocked |
| recovery | 4/4 crash points; deterministic rerun; parallel = sequential; replay consistent |
| time_machine (1368) | 3 decidable predictions, 2 held (taboo rename persisted; lost association stayed absent); failed: the 肾气丸-family core predicted from two members — 张景岳's 左/右归丸 dropped 泽泻·牡丹皮·茯苓 |
| source_rediscovery | 3/3 re-inferred with consistent date bounds |
| ablations | earliest accuracy: all 1.0 · no sense route 0.67 · BM25 only 0.67; contradiction: no sense resolution 0.83 · no philology 0.92; 1 hypothesis would pass G5 only by counting dependent books; Context OS −94% tokens; without the Skeptic 1 rejected hypothesis survives and no revisions happen |

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
| fragments | a constructed lost work (集古方, held out) quoted by four books in the manners of the 外台秘要, the 医心方, the 证类本草 and a late paraphrase, beside other sources (`gold/fragments/`); the real 千金 and 肘后 | precision 0.86 · coverage 1.0 · no other source's words taken in · volumes 1.0 · real: 千金 precision 0.32 · coverage 0.12; 0.875 of the 肘后's quotations not in the extant text |

These numbers describe the rules on the data they were written for. They are not benchmarks. Expert-annotated gold
on the full corpus (a collated chapter with its stemma, typed reuses, segmented case records, argument graphs, dated
sense shifts) is on the roadmap.

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
so the table documents the protocol, not a result; it becomes meaningful on a large corpus.

## Adding gold

Each suite reads one YAML file; the schemas are documented at the top of every file. Claims gold is
*complete* per listed passage (unlisted extracted claims count as false positives); lineage gold has
positives and negatives (other predictions are reported as unjudged).
