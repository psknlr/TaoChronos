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

**Development caveat.** The gold sets were written alongside the system and were used while developing it
(e.g. the differential-diagnosis rule in the contradiction classifier was added after a gold pair exposed the
error). Treat the scores as regression tests of intended behaviour, not as unbiased benchmark results.
