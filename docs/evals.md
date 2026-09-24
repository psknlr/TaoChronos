# TaoChronos-Eval

```bash
taochronos eval                  # all suites (~45 s on the demo corpus)
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

## Full corpus

The suites above run on the demo corpus, whose gold they were built against. On the full corpus
(`--profile full-corpus`) the same machinery runs end to end — e.g. the 消渴 question: a frame of 2,400 of 32,736
matching passages (84 books, six periods), 2,444 claims, 95 evidence and 41 counter-evidence records and 22
hypotheses in about a minute offline — and `tests/test_corpus_store.py` checks the parser, the store, verbatim
provenance of claims read from unpunctuated text and a research run over a store. Gold for the full corpus
(punctuation, claims, dating of layers) is future work.

## Baselines

The time machine's link-level table compares Adamic–Adar with resource allocation, common neighbours,
popularity and random rankings. On the demo corpus only one link appears for the first time after 1368,
so the table documents the protocol, not a result; it becomes meaningful on a large corpus.

## Adding gold

Each suite reads one YAML file; the schemas are documented at the top of every file. Claims gold is
*complete* per listed passage (unlisted extracted claims count as false positives); lineage gold has
positives and negatives (other predictions are reported as unjudged).
