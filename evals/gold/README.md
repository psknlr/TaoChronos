# TaoChronos-Eval gold sets

These gold sets are **author-constructed for the demo corpus** (`corpus/demo`, itself an unverified
transcription for method demonstration). They exercise the evaluation *machinery* and document the
intended behaviour; they are not expert-annotated benchmarks and their small size makes the resulting
numbers illustrative, not statistically meaningful. Replace or extend them with expert annotations
before drawing conclusions about a real corpus.

| file | suite | what is annotated |
|---|---|---|
| `philology.yaml` | PhilologyEval | contested spans, reading probabilities, normalisations |
| `claims.yaml` | ClaimEval | complete claim sets (relation + key arguments, negations) for selected passages |
| `contradictions.yaml` | ContradictionEval | passage pairs labelled contradiction / conditional / apparent / support / unrelated |
| `lineage.yaml` | LineageEval | true and false lineage edges (formula derivation, citation, transcription, opposition) |
| `temporal.yaml` | TemporalEval | period-constraint parsing and earliest-attestation queries |
| `anachronism.yaml` | AnachronismEval | statements that must / must not be blocked; expected mapping relations |
| `rediscovery.yaml` | RediscoveryEval | Historical Time Machine cutoffs and books to hold out for source rediscovery |
| `reuse.yaml` | ReuseEval | 33 source–target pairs typed 直接引用 / 近似转录 / 节略 / 撮要 / 转述 / 解释性改写 / 引而驳之 / 套语相似 or unrelated, with the reuse mode |
| `cases.yaml` | CaseEval | case records in two manners, annotated case by case and visit by visit (pulse, formulas, changes, doses, principle, response; patient, outcome) |
| `argument.yaml` | ArgumentEval | 18 passages with their clauses and typed edges (source, target, relation) |
| `fragments/` | FragmentEval | a constructed lost work (集古方, held out) and four books that quote it in the manners of the literature, with other sources beside it (CC0) |

The collation, stratigraphy and sense-evolution suites need no gold file: they build their data with a known answer
(traditions copied down a known stemma, composites with rewritten blocks, occurrences with a planted shift of senses)
from the demo corpus. The 2.0 suites also check the real corpus against results the literature holds (the 运气七篇
of the 素问, the 叔和 chapters of the 伤寒论, the two transcriptions of 吴鞠通医案, the surviving 千金 and 肘后) when the
corpus store exists.

**Development caveat.** The gold sets were written alongside the system and were used while developing it
(e.g. the differential-diagnosis rule in the contradiction classifier was added after a gold pair exposed the
error). Treat the scores as regression tests of intended behaviour, not as unbiased benchmark results.
