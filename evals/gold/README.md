# TaoChronos-Eval gold sets

These gold sets are **author-constructed for the demo corpus** (`corpus/demo`, itself an unverified
transcription for method demonstration). They exercise the evaluation *machinery* and document the
intended behaviour; they are not expert-annotated benchmarks and their small size makes the resulting
numbers illustrative, not statistically meaningful. Replace or extend them with expert annotations
before drawing conclusions about a real corpus.

| file | suite | what is annotated |
|---|---|---|
| `philology.yaml` | PhilologyEval | contested spans, reading probabilities, normalisations |
| `interpretive.yaml` | InterpretiveEval | 92 hard interpretive cases in seven classes (inverted relations, prohibitions beside prescriptions, consequences, reported / rejected views, omitted conditions, mixed witnesses, disputed dates), with a dev / held-out split fixed before the first run and rounds recorded as they ran |
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
| `aliases.yaml` | AliasEval | 120 drug-name queries on the real corpus (other names, heads, shared names, period-bound names, ordinary-word traps, names inside longer names) with their referents, witnesses and false friends, and 80 resolution rows; dev / held-out split fixed before the first run (below) |

The collation, stratigraphy and sense-evolution suites need no gold file: they build their data with a known answer
(traditions copied down a known stemma, composites with rewritten blocks, occurrences with a planted shift of senses)
from the demo corpus. The 2.0 suites also check the real corpus against results the literature holds (the 运气七篇
of the 素问, the 叔和 chapters of the 伤寒论, the two transcriptions of 吴鞠通医案, the surviving 千金 and 肘后) when the
corpus store exists.

**Development caveat.** The gold sets were written alongside the system and were used while developing it
(e.g. the differential-diagnosis rule in the contradiction classifier was added after a gold pair exposed the
error). Treat the scores as regression tests of intended behaviour, not as unbiased benchmark results.

## The alias gold (`aliases.yaml`)

Unlike the sets above, this one is annotated on the real corpus, the web store (553 books, 168,278 passages); its
witnesses are passage ids of that store. It measures the alias layer (ADR 0023): does a drug query find the passages
written under the drug's other names, without losing the asked form, merging shared names or crossing periods?

**Construction.** The items were selected by hand, not drawn by `propose`. Annotators, one per type, mined their own
candidates with eval-local patterns (X一名Y and its chains, X即Y也, X（即Y）, glosses, 本草 entries with their 一名
lists) over every book outside `jc_c030` and `bencao_gangmu_*`, wrote each item — the referents, the names whose
passages are relevant, the false friends to mask, the cues of a trap, the period window and floor — and kept spares;
an assembler checked the witnesses and merged the six files. An adversarial review then found held-out items on names
the design had already been tuned on, and items outside the §3.10 pools. Those were replaced: by the first spare of
the same type and band that is in a pool (and, landing held-out, touches no tuned name), else by the first fitting
candidates of a seed-23 shuffle of the pool; the file's comments name each replacement and the draws skipped.
The bands follow the items, so they are uneven (60 of 120 items have 20 passages or more; head 3/6/16, period 2/3/15).

Every item names its provenance in `pool`, a sub-pool of `aliases_gold.POOLS` as `aliases_gold.pools(store)` mines it
from the web store: equations, glosses and entries (alias, head); names filed under two lexicon herbs, under two
别名录 heads, or equated with two herbs in the store (ambiguous); taboo pairs, the curated windows and first-use years
(the spec's example until `curated.yaml` exists) and equated names first written 300 years or more apart (period); the
datasets report's false friends and equated two-character names mostly written outside 本草 books (trap); drug names
inside a longer name of another drug (substring). An entry's drug is its section heading read as the layer's build
reads it (`aliasbuild.entry_head`: the innermost heading, bracketed glosses and then the numbering dropped, a zero
written 〇 or ○; a test holds the two numbering rules equal), of two to four characters; a heading of numerals alone
heads an entry only when it is a lexicon herb (三七, not a chapter's 六七). `validate(gold, pools=…)` checks that every
asked form is a candidate of its sub-pool; `python -m taochronos.evals.aliases_gold propose [--all]` writes the pools, or a seed-23
draw stratified by band, to `<data>/aliases/gold-candidates.yaml`. The pools never read the alias layer; `propose`
reads `curated.yaml` (period windows) and the 别名录 (`jc_c030`, for its multi-head names) only to list candidates,
never their pairs, so a pair the layer lacks still counts as a miss.

Every name carries a witness passage outside `jc_c030` (the 别名录, excluded from the corpus during the eval) and
`bencao_gangmu_*` that writes it beside the asked form, a head or another name of the item (in its text, or in its
section heading for a 本草 entry); for the taboo spellings 元参 and 元胡, which no passage writes beside 玄参 and 玄胡,
a `parallel` gives the second passage of the same line or recipe written the other way.

**Still to do (§3.10 step 4).** The pooled adjudication of the top 50 hits of `off`, `naive` and `on` on both stores,
and the hand check of a 10% sample of labels, run with the first eval; a name it adds needs a witness and a date in
`adjudicated`. Until then `frozen` dates the items and splits, not the names. After the first held-out report, real
other names that dev runs showed missing were added to dev items only, each `adjudicated` `by: correction` with a
witness and its date, ids, groups and splits unchanged, and logged in `docs/evals.md`; `tests/test_evals.py` refuses
a name added after `frozen`, or marked `correction`, on a held-out item.

**Labels.** The suite labels hits from the items alone, never from the system's gates: on the normalised text with the
false friends masked, a passage is relevant when it writes the asked form (and, when the item has cues, one of them
anywhere in the passage) or a referent's name inside that referent's `valid` window, and wrong when it writes only a
`wrong` name, a masked or an uncued asked form. Items of the same type differ in what they test (see the file's
header): a period item lists only the referents valid in its window; a trap expected to stay unexpanded (a stop) lists
no candidate and keeps its head only for candidate precision, with no names and no cues, so the passages a forbidden
expansion would add do not score. A stop listing costs nothing: the layer lists a stop asked on its own with its drugs
(status `stop`, beside a note that the name is mostly an ordinary word and nothing was searched under it — or, where
the lexicon files it as a herb, only today's search of that entry's names), and for an item that expects no candidate
those drugs count neither for nor against it; only reading the name as a drug, or listing its drug any other way,
counts against candidate precision. Where an item does expect candidates (解离 → 防己), a stop's listed drugs count
both ways.

**Split and leakage.** Items that share any string — asked form, head, name, wrong name, cue or false friend — share a
group, named by the first of them in file order (its head for an alias item, else its asked form); the split is
`sha1(group) % 2` (0 dev, 1 held-out; `aliases_gold.groups`, `split_of`), so items about one drug never fall on both
sides, and `aliases_gold.SPLIT_SHA256` pins the resulting (id, group, split) list. A resolution row takes the group of
the items it touches, else its own surface. The header's `tuned` list holds the names the design was tuned on before
the gold existed (the retrieval prototype's gold and every drug name the spec writes); no held-out item or row may
use one, so the spec's example `curated.yaml` passes `aliases check`. `aliases_gold.validate` checks the header, the
quotas, the keys and types, the groups, splits and pin, the tuned names, and (with a store) the witnesses and pools.
Held-out results are reported and never tuned on: `curated.yaml` may hold no held-out string
(`aliases_gold.heldout_surfaces`, enforced by `taochronos aliases check`; `aliases review` refuses them), a held-out
ambiguous item comes from a source the shipped layer reads (the lexicon or the 别名录), the eval code may not import
the alias layer's gate functions, and any parameter change after the first held-out report is logged with its date in
`docs/evals.md`. Metrics are also reported without `bencao_gangmu_skqs`.
