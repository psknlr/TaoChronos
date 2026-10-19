# Figure legends

Legends follow the Nature layout: a title sentence, the panels, then the statistics (n, centre, error, test, P).
Each is under 300 words (`python paper/figures/check_legends.py`).

## Fig. 1 | TaoChronos (道乃久): agents propose, validators grade, experts decide.

**a**, The harness as configured (web-canon profile), by principal (rows) and by the stage of a research round
(columns). A scientist's question becomes a research contract, hashed before the first task. The Director plans each round and picks, from fifteen specialists, the agents the kernel spawns; each reads only
through the research's scoped view and calls only the tools its permissions allow (letters). Filled circles, agents
that may consult a language model where their rules leave a case
uncertain (Fig. 3 called none). The
Skeptic's objections return to the Hypothesis agent, which may only narrow a claim. Every write is an event in the
log. Hooks (vermillion) refuse a tool call or result outside the research's scope, a claim whose quote is
not verbatim or contradicts it, an equation of a historical with a modern concept, and a report on versions the contract
never judged. Validators alone grade claims, gates G0–G6 and G8, scores and the contract's verdict, and close a hard
objection only by re-running its check; the expert alone sets G7. **b**, Event authority: the principals allowed to emit
each group of the 61 event types (number of types); the reducer refuses any other event. **c**, One clause
of the *Jingui yaolüe* (chapter 13) in three witnesses, aligned character by character: the Deng Zhen print (1340), the
Wu Qian manuscript (1395), which lacks 小便一斗, and the Yuan print of the *Maijing* (1330), which writes 圎 for 丸, a
Song taboo form that dates its exemplar after 1126; shaded, variant positions. Below, the provenance chain of the first
witness from claim to licence; the conversation client checks every cited passage (✓ verbatim, ≠ quotation differs,
× no such passage). CMETA, 數位中醫校書郎. Agents, tools and permissions: Supplementary Tables 4–8.

## Fig. 2 | A dated, layered corpus spanning two millennia, and the canon its citations define.

**a**, Construction of the corpus. Transcriptions from ten sources pass admission (historical texts only),
de-duplication against more trusted sources (normalized 12-character shingles; independently collated transcriptions
are kept as separate witnesses), layer-aware dating (main text, commentaries, editors' notes and later additions dated
apart; undated material counted as Qing, never earlier) and normalization used for matching only. **b**, Witnesses per
25-year bin by composition date; each witness counts once, its weight spread evenly over its date range (n = 966;
blue, the 740 witnesses of the 535 canon works). Bands mark the analysis periods; the last, unlabelled band is the
Republican period (1912–1949). **c**, Basis on which each witness was dated; the 104 undated witnesses are counted as
Qing (vermillion), never earlier. **d**, Influence score of the 535 canon works against the midpoint of their
composition range; point area, witnesses in the corpus (capped at 10). Score = 10 log₂(1 + citing works not older than
it) + 2 × periods in which it is cited + 2 log₂(1 + citations) + 3 log₂(1 + witnesses) + 6 × inclusion in the *Siku
quanshu*; the ten highest (blue) are keyed by rank. Later works have had fewer chances to be cited: the score describes
what the corpus cites, not a verdict on the tradition. **e**, Characters kept for each witness of the open web corpus
against the canon rank of its work (log–log). Dashed line, the budget of a work's first witness (350,000 characters for
ranks 1–10, then 50,000, 25,000 and 12,000); blue, texts kept whole; triangles, second and third witnesses of the ten
highest-ranked works. Data: corpus catalogues (`corpus/catalog`) and the web corpus pack (`corpus/web`).

## Fig. 3 | One research question, end to end.

**a**, The question, put to the harness on the open canon corpus (web-canon profile; rules only, no model called), and
the contract fixed before the first task. **b**, The 30 tasks in the order the Director planned them over three rounds:
agent tasks (blue), validator tasks (grey); numbers, tool calls. Below each round, the evidence records, new books and
hypotheses it added; the run stopped after the last round the contract allowed, which added no evidence. **c**, The 14
hypotheses proposed in round 1: the Skeptic kept 2, sent 11 back to be narrowed and rejected 1; validators then judged
the 13 candidates. Below, the Skeptic's 102 objections by check: closed by a validator once the claim was narrowed,
left open, or critical. **d**, The final hypotheses against the gates and the contract's criteria. H1 and H2 meet every
criterion a machine can check; H3 and H4 rest in part on a quotation that does not clearly state its claim, which the
contract leaves to an expert. Nine fail on independent sources (G5): passage reuse, closed transitively, puts 36 of the
46 evidence books into one source family (Supplementary Fig. 1). **e**, Three outcomes with their verbatim evidence. H1
waits for an expert. H5 rests on six books of one family: the 消渴 clause of the *Jingui yaolüe*, its witnesses and
copies. R1 is rejected because three later books state the link; they copy the canonical list of the kidney channel's
illnesses that the earlier passage holds, and the rules read two findings of one list as an association. A second run
writes the same report; report, event log, hypotheses and objections: Supplementary Data 1–2 and Supplementary Tables
9–10. D1–D5, discovery tracks: lost knowledge, concept evolution, formula evolution, hidden associations,
contradictions.

## Fig. 4 | Quotations stay verbatim, the harness's boundaries hold, and hard readings stay safe.

**a**, Quotation checks on 60 random passages of the demonstration corpus: verbatim quotations accepted; quotations
with one character replaced, of random characters, or verbatim at a shifted span rejected. Dots, proportions; lines,
Wilson 95% confidence intervals. **b**, Nineteen invariants (I01–I19) run as probes on the intact harness and on six
variants, each with one boundary removed by deleting its check at run time. Every removal broke the invariant named for
its boundary (outlined) and no other; 127 of 133 cells held. In three cases a second safeguard limited the damage:
without the scope guard the tool it no longer refused returned nothing of the withheld passage; forged G7 events
reached the log but not the state; without the bound checks two of five impossible evidence records verified. **c**,
107 hard interpretive cases in eight classes, each a verbatim quotation with one correct reading (development, 23 cases
used to write the rules; held-out, 84). Numbers, held-out cases read correctly. Both errors were unsafe, a reading that
commentators dispute accepted as supported (the Dahuang mudan tang clause and the 里水 of the Yuebi jia zhu tang
clause); they are reported, not patched. **d**, Accuracy in four blind rounds, each on new cases written before the
rules that first read them, and on all held-out cases under the current rules. Lines, Wilson 95% confidence intervals;
below, correct/total and unsafe errors. Data: `taochronos eval` on the demonstration corpus (**a**, **c**),
`paper/figures/mutation_matrix.py` (**b**) and `docs/evals.md` (**d**).

## Fig. 5 | Rankings computed from the past anticipate the links later physicians wrote.

**a**, Blind temporal benchmark on the full corpus. At each cutoff (1127, 1368) the store splits into passages dated
wholly before and wholly after it; passages that straddle it belong to neither side. For every disease or symptom of
the lexicon with 150–6,000 past and at least 300 future passages, the formulas and drugs of its past graph not yet
linked to it are ranked; a candidate comes true when claims in two or more later books link it to the topic. **b**,
Precision at 10 and 20 and mean average precision of five rankers over the 189 topic–cutoff pairs in which at least one
link came true. Dots, means; lines, 95% confidence intervals; chance, 20 random rankings; dashed line, base rate
(4.5%). **c**, Paired comparisons of average precision over topic–cutoff pairs; two-sided sign tests, one tie excluded.
**d**, Predictions of the whole pipeline run on the past view at 1368 for four held-out topics (胸痹, 霍乱, 虚劳, 痰饮):
proportion borne out by later books, with Wilson 95% confidence intervals. Open circle, before the absence checks, which
rejected two wrong 'lost' and two already attested 'hidden' associations and no discovery. No passage outside the past
view was read (leakage 0). Values of the full-corpus run documented in `docs/evals.md`; the full store is not
distributed, and Extended Data Fig. 2 repeats the benchmark on the open corpus.

## Fig. 6 | On the open canon corpus, the study layer recovers history written into the texts.

All panels are computed by the deterministic study layer on the open web corpus (533 works, 168,278 passages).
**a**, **b**, Share of works per century writing an original drug name and the name a naming taboo imposed: 薯蓣 and
山药 (**a**), 玄参 and 元参 (**b**). Dashed lines, the years from which the names were avoided: Tang Daizong (李豫, 762) and
Song Yingzong (赵曙, 1063) in **a**; the Song ancestor Shengzu (赵玄朗, 1012) and the Kangxi emperor (玄烨, 1662)
in **b**; shading, the switch interval the tool detected; marker area, works in
the century; open markers, centuries with fewer than three works or only undated front matter dated conservatively to
1911. A work writing both names counts for both. **c**, Passages mentioning 温病 (warm disease) per 10,000 passages by
period, with Wilson 95% confidence intervals; numbers, passages with the term. Two-sided Cochran–Armitage test for trend
across the ordered periods. **d**, Normalized pointwise mutual information (NPMI) of drug pairs co-occurring
significantly in 4,554 compositions (a composition repeated in copies of one work counted once; pairs in at least ten
works tested; one-sided Fisher exact test, Benjamini–Hochberg q < 0.05; 1,184 pairs). Groups are communities of the
strong pairs (NPMI ≥ 0.3), found without formula names; shown (outlined) are the five of twelve whose drugs hold
together most tightly (mean NPMI of their significant pairs). Each holds the core of a classical formula (right);
liquorice (甘草), present in 43% of compositions, joins none. **e**, Citations between physicians: arcs join citing and cited
physicians placed at the midpoints of their dates; width ∝ √citations; blue, citations of Zhang Ji (张机). Five links
whose cited physician lived after the citing one (28 citations) are omitted as chronologically impossible.

## Extended Data Fig. 1 | Where the rules transfer and where they do not.

**a**, Development or constructed data (open circles) against held-out or real-corpus data (blue) for nine
capabilities; numbers, the two scores; †, real-corpus value from the full corpus (`docs/evals.md`). Development sets
were written with the rules they test. **b**, Sentence-boundary F1 of the learned punctuation model and of the rule
baseline on the demonstration corpus (four folds), on 55 works held out of training, and on four unpunctuated *Siku*
texts scored against their JiCheng punctuation (†, full corpus); every character was preserved in all settings. **c**,
Ablations on the demonstration corpus: earliest-attestation accuracy with retrieval routes removed (6 terms),
contradiction typing without sense resolution or philology (12 passage pairs), the context supplied to agents, and
review without the Skeptic.

## Extended Data Fig. 2 | The research-value benchmark on the open canon corpus.

The benchmark of Fig. 5 re-run with identical rules on the open web corpus (533 works, most sampled by chapters).
**a**, Average precision of Adamic–Adar (blue), popularity (grey) and the expectation under chance (open circles) in
each of the 51 topic–cutoff pairs in which at least one link came true (24 at 1127, 27 at 1368; log scale); lines join
Adamic–Adar to popularity, blue where Adamic–Adar is higher; right, links that came true in the pair. More than half
of the pairs have a single true link (28 of 51; 109 among 10,115 candidates), so one hit moves a ranking. **b**,
Precision@10 and mean average precision of the five rankers, both cutoffs pooled (n = 51 pairs); dots, means; lines,
95% confidence intervals; dashed line, base rate (1.08%). **c**, Paired comparisons of average precision, two-sided
sign tests. Adamic–Adar still ranks above popularity (37 of 51 pairs, P = 0.0018) but cannot be told from chance (19
better, 32 worse, P = 0.092), and popularity falls below chance (7 better, 44 worse, P = 1.2 × 10⁻⁷). The benchmark
needs the full corpus; the replication is reported as a limit of the open subset. Every pair and every prediction:
Supplementary Tables 11 and 12.

## Extended Data Fig. 3 | The witnesses behind the texts.

**a**, Catalogue records of printed and manuscript copies in eleven digitized collections (title, date, print or
manuscript, shelfmark, IIIF manifest and licence; no image is downloaded) and those linked by title to a work of the
corpus (787 records of 179 works); links made by title need checking by hand. **b**, Sources of the open web corpus in
millions of characters and witnesses. Blue, openly licensed transcriptions: JiCheng, whose selection, arrangement,
punctuation and notes on public-domain texts are released under CC0 1.0 and its own writing under CC BY 4.0 (the
modern editors' part of the few texts it took from modern reconstructions of lost books excepted); CMETA, CC BY 4.0;
Kanseki Repository and Wikisource, CC BY-SA 4.0; McGill, public domain. Grey, the four TCM-Ancient-Books texts that
match no JiCheng text, whose repository declares no licence, carried on the decision of the releasing institute
(IMPF-AI). Sources whose terms forbid redistribution are never included. IIIF, International Image Interoperability
Framework.

## Supplementary Fig. 1 | Where the end-to-end run of Fig. 3 went wrong, and why.

The legend is in the Supplementary Information (`paper/supplementary/Supplementary_Information.md`).

## Source data

Every plotted value is in `paper/figures/source_data/` (CSV or JSON), written by `paper/figures/make_data.py` and
`paper/figures/e2e_case.py` from the repository's catalogues, the harness's configuration, the open web corpus and
`taochronos eval`; values that need the full corpus store are transcribed from `docs/evals.md` and marked there and in
the legends.
