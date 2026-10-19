---
title: "TaoChronos: A Reliable Agent for Knowledge Discovery in Traditional Chinese Medicine"
journal: "Engineering (Research Article)"
bibliography: references.bib
csl: csl/elsevier-vancouver.csl
link-citations: true
lang: en-US
---

**Authors:** [Author 1]^a,\*^, [Author 2]^a^, … [Corresponding author]^a,\*^

^a^ IMPF-AI (医哲未来人工智能研究院), [address].
\*Corresponding author. E-mail address: [e-mail].

**Article type:** Research Article

# Abstract {.unnumbered}

Large language models (LLMs) can mine the classical literature of traditional Chinese medicine (TCM), yet what they
assert may misquote the texts, misread negations and conditions, count copies of one text as independent testimony,
equate historical with modern diseases, and resist checking without hindsight. We present TaoChronos, an agent for
knowledge discovery from the Chinese medical classics engineered so that reliability is a property of its
architecture rather than of its model: models and rules only propose, deterministic validators grade, and human
experts alone approve. Every state change is a typed event checked against the authority of its emitter; every claim
must quote a dated witness verbatim and be stated by that quote; and an executable research contract, fixed before
the first task, decides acceptance. On a corpus of 966 witnesses (123 million characters, 475 BCE–1949), TaoChronos
rejected 180 of 180 corrupted quotations, kept 19 of 19 safety invariants, each of which broke when its safeguard was
removed, and read 82 of 84 held-out hard interpretive cases correctly. In a blind temporal benchmark, rankings from
texts written before a cutoff anticipated links later physicians wrote (precision@10 0.168 vs 0.134 for popularity and
0.054 for chance; *P* = 2.4 × 10⁻¹⁶). All results were obtained without calling a language model.

**Keywords:** Traditional Chinese medicine; Large language model agents; Knowledge discovery; Provenance; Trustworthy
artificial intelligence

# Introduction

The classical literature of traditional Chinese medicine (TCM) is one of the longest written records of clinical
observation, and it has yielded medicines: a fourth-century prescription in Ge Hong's *Zhouhou beiji fang* suggested
the low-temperature extraction that led to artemisinin [@tu2011artemisinin], and arsenic, a mineral drug of the
tradition, became a cure for acute promyelocytic leukemia [@wang2008apl]. Literature-based discovery joins what
different texts say [@swanson1986fish], and machine reading of modern literature anticipates findings before they are
published [@tshitoyan2019unsupervised; @krenn2023forecasting]. The TCM classics are harder: a passage survives in
witnesses that differ character by character, its date is often a range, commentaries accumulated over centuries,
names changed their meaning, and most of what later books say was copied from earlier ones.

ZhongJingGPT, introduced in 2023 as the first large language model dedicated to TCM, fine-tuned general-purpose
models on instructions constructed from TCM expert knowledge [@kang2025zhongjinggpt; @cmlm2023zhongjing]; Chinese
medical models [@zhang2023huatuogpt; @yang2024zhongjing], TCM benchmarks [@yue2024tcmbench] and LLM-built knowledge
graphs of the ancient literature [@li2025tcmrdkg; @xiang2025kgclassics] followed. LLM agents now plan experiments and
propose and test hypotheses [@boiko2023autonomous; @gottweis2025coscientist; @swanson2025virtuallab;
@huang2025popper; @lu2026endtoend]. In these systems reliability rests largely on the model, and LLMs can state
fluent claims with unsupported citations [@ji2023hallucination; @gao2023alce; @thirunavukarasu2023llm]. On historical
medical texts the failure modes are specific (Table 1).

We argue that reliability must be engineered into the agent's architecture. TaoChronos (道乃久) follows one principle,
*deterministic harness, stochastic intelligence*: state, permissions, verification, stopping and acceptance are
deterministic code, and intelligence — a language model or a rule-based procedure standing in for one — may only
propose. Our four contributions are:

1. **An agent architecture that separates proposal from verdict:** an event-sourced research object, authority by
   principal over 61 event types, a permissioned tool mesh, hooks that require verbatim and semantically supported
   quotations, nine epistemic gates and an executable research contract (Fig. 1).
2. **A dated, layered and license-tracked corpus** of 966 witnesses of 761 works (about 123 million characters,
   2.05 million passages, 475 BCE–1949), with an openly licensed canon defined by the tradition's own citations that
   runs in a web browser (Fig. 2).
3. **A three-layer evaluation of reliability and research value:** safety invariants checked by mutation, hard
   interpretive cases with unsafe errors counted apart in blind rounds, and a blind temporal benchmark in which
   leakage is counted rather than assumed (Figs. 4 and 5).
4. **Guarded ancient–modern translation and full transparency:** phenotypic similarity to modern diseases through the
   Human Phenotype Ontology [@kohler2021hpo], never retrospective diagnosis, and a complete, replayable research run
   released with its unrepaired failure analysis (Fig. 3).

# Materials and methods

## Corpus

Transcriptions came from ten sources, among them the Kanseki Repository (the *Siku quanshu* medical section),
JiCheng (中醫笈成), CMETA (數位中醫校書郎), Wikisource and McGill University Library (Supplementary Table 13). Admission
removes contemporary publications and modern annotated editions; de-duplication against more trusted sources uses
normalized 12-character shingles, while independently collated transcriptions are kept as separate witnesses. Dating
is layer-aware: main text, commentaries, editors' notes and later additions are dated apart, from curated overrides,
book records, dated prefaces (parsed with a table of reign eras), other witnesses and the author's life; an undatable
witness is placed in the Qing (1644–1911), never earlier. Each passage keeps its book, edition, locator, date range,
layer, transcription source and license; normalization of variant forms is used for matching only. A work's influence
is 10 log₂(1 + citing works) + 2 × (periods citing it) + 2 log₂(1 + citations) + 3 log₂(1 + witnesses) + 6 × (inclusion
in the *Siku quanshu*); the openly licensed witnesses of the 535 ranked works (533 have one) form the web corpus
(553 witnesses, 10.46 million characters, 168,278 passages) used in Figs. 2e and 3.

## Agent architecture

The research object holds all scientific state and is changed only by a reducer applying typed events in
transactions; each event carries its principal (kernel, human, validator or agent), set from an identity object, and
the reducer refuses an event its principal may not emit (Fig. 1b). Agents propose; only validators grade gates,
scores and the contract; only a human sets gate G7 (expert approval); an objection closes only when a validator
re-runs its check or an expert decides. Sixteen agents (a Director and fifteen specialists, from Curator and
Philologist to Hypothesis agent and Skeptic) are configurations naming permissions, tools, context view, output
schema, model tier and budget; a deterministic procedure and a model produce the same typed output, verified by one
commit function. Each of 85 tools needs one of eight permissions; a scope guard and a result firewall wrap every call;
receipts form a hash chain. The state hash covers scientific fields only, so reruns, resumed and parallel runs agree.

## Claims, readings, discovery and acceptance

The Extractor turns passages into claim hyperedges, e.g. indicated_for(formula: 五苓散 | pulse: 浮, symptom: 小便不利,
symptom: 微热, disease: 消渴), with spans, negations and conditions. At commit the harness relocates every quotation in
its passage and a semantic-support reader checks that the quotation states the relation, reading cues, consequences,
pronouns, negations and the statement frame (speaker; asserted, reported or rejected stance); a contradicted claim is
refused, and a registry of textual cruxes harvested from commentaries makes doubtful clauses read as ambiguous. Five
engines propose: lost knowledge (D1), concept drift by Jensen–Shannon divergence with permutation tests (D2), formula
evolution (D3), hidden associations by Adamic–Adar link prediction [@adamic2003friends] (D4) and contradictions (D5).
The Skeptic tries to refute each hypothesis [@popper1959logic]; for arguments from silence it searches the whole scope
for explicit supported statements, which raise hard, critical objections. Gates G0–G8 grade source, transcription,
philology, sense, claim provenance, independent source families, falsification, expert approval and modern evidence;
the contract judges each hypothesis on its current version as accepted, needing an expert, inconclusive or rejected.

## Evaluation design

Forty suites form three layers (Supplementary Table 1). (i) Nineteen invariants run as probes against the agent and
against six variants, each with one boundary deleted at run time [@jia2011mutation]. (ii) 107 hard interpretive cases
in eight classes (23 development, 84 held out, split fixed before the first run), unsafe errors counted apart, and
four blind rounds written before the rules that first read them. (iii) A blind temporal benchmark: the full corpus is
split at 1127 and 1368, a passage belonging to a side only if its whole date range does, with every read path bounded
in SQL; for each disease or symptom with 150–6,000 past and ≥ 300 future passages, unlinked formulas and drugs of its
past graph are ranked, and a candidate comes true when claims in ≥ 2 later books link it. Precision@*k* has Wilson
intervals [@wilson1927probable], mean average precision a 999-resample bootstrap interval, and paired comparisons
two-sided exact sign tests. Rules were written before the first run; all results used rules only.

# Results

## A dated, layered corpus

The store holds 966 witnesses, 537 dated to a single year; the basis of each date is recorded, from curation (329) to
signed prefaces (139); 104 undated witnesses are counted as Qing (Fig. 2). Records of 10,001 printed and manuscript
copies in eleven digitized collections link 179 works to physical witnesses (Supplementary Fig. 4). The openly
licensed texts of 533 of the 535 canon works form a web corpus of 553 witnesses that runs in the browser (Fig. 2e).

## One research question, end to end

We asked how the composition and indications of Shenqi wan changed over time, with Shenqi wan and Liuwei dihuang wan as
focus terms and 消渴 = diabetes forbidden, on the open canon corpus (273 books, 1,620 passages; Fig. 3a). The run
planned 30 tasks in three rounds, wrote 678 events, called 143 tools (none refused) and no model; it extracted 935
claims and recorded 80 evidence and 13 counter-evidence records (Fig. 3b). Of 14 hypotheses, the Skeptic kept 2, sent
11 to be narrowed and rejected 1, raising 102 objections (Fig. 3c). Four await an expert: two meet every
machine-checkable criterion — restlessness (烦躁) with strangury (淋) as an indication of Liuwei dihuang wan, on two
independent families of Qing books (H1), and a Ming-to-Qing shift of 中风 from wind attack to stroke (H2) — and two
rest in part on a quotation that does not clearly state its claim. Nine were inconclusive, all short of two
independent families; the association of copious drinking and urine with Shenqi wan (H5) rests on six books that all
carry one *Jingui yaolüe* clause (Fig. 1c). One, that heat (热) and counterflow qi (上气) were not linked after 960
(R1), was rejected because three later books state the link (Fig. 3d,e). A second run wrote the same report.

Reading every hypothesis against its evidence found six failure modes (Supplementary Fig. 1). The independence gate
merged books linked by any transcription or rephrasing, transitively, putting 36 of the 46 evidence books in one
family; with transcription links only, four failed hypotheses would rest on two or three families, though two (H5,
H13) do rest on copies of one clause. The rules read two items of one list as an association (R1), took drift
evidence from passages not naming 中风 and let three drifts whose permutation tests failed (*P* = 0.66–0.98) reach the
expert as 'exploratory', read Xue Ji's records of failed treatments as doctrine, did not merge hypotheses sharing
evidence and, on the sampled open corpus, missed the 1119 first record of Liuwei dihuang wan. None led to acceptance,
and the largest made the gate stricter, not looser; we report them unrepaired.

## Quotations, boundaries and hard readings

On 60 random passages, all verbatim quotations were accepted and all 180 corrupted ones (one character replaced,
random characters, shifted span) rejected (Fig. 4a). All 19 invariants held on the intact agent; each removed boundary
broke the invariant named for it and no other (127 of 133 cells held; Fig. 4b). The agent read 82 of 84 held-out hard
cases correctly (0.976); both errors were unsafe, textual cruxes the harvest does not find (Fig. 4c). Blind rounds
scored 43/53, 30/32, 7/10 (a new class of cruxes) and, after a registry of 127 cruxes was harvested from the
commentaries, 5/5 (Fig. 4d). On 25,000 full-corpus passages this second reader found 71 rule claims contradicted by
their own quotes; after the extractor was fixed, the 12 left are refused at commit.

## Rankings from the past anticipate later links

In 189 topic–cutoff pairs with a link that came true (29,467 candidates, 1,314 true; base rate 4.5%), Adamic–Adar
reached precision@10 0.168 (95% CI 0.152–0.185) against 0.134 for popularity and 0.054 for chance, and mean average
precision 0.199 against 0.143 and 0.092 (Fig. 5b); it beat popularity in 149 pairs and lost in 39
(*P* = 2.4 × 10⁻¹⁶; Fig. 5c). Leakage was zero. Run on the past view at 1368, the pipeline's surviving held-out
predictions were discoveries (true and new) in 7 of 19 (0.37; 95% CI 0.19–0.59), after absence checks rejected two
wrong 'lost' and two already-written 'hidden' associations and no discovery (Fig. 5d). On the open canon corpus alone
(51 pairs, 109 true links) Adamic–Adar beat popularity (37/14, *P* = 0.0018) but not chance (19/32, *P* = 0.092;
Supplementary Fig. 3): the benchmark needs the full corpus.

## Generalization, the study layer and the bridge

Held-out data show where rules transfer (Supplementary Fig. 2, Supplementary Table 14): entity recognition fell from F1
0.99 to 0.78 and lost-text reconstruction from precision 0.86 to 0.32, while a learned punctuation model reached
boundary F1 0.767 on 55 held-out works (rules 0.235) without changing a character. The deterministic study layer
recovers dated taboo renamings (薯蓣 → 山药, 1000–1200; 玄参 → 元参, 1600–1800), the Qing rise of warm disease
(Cochran–Armitage *z* = 7.30 [@armitage1955tests]) and the drug cores of classical formulas (Supplementary Fig. 5). The
ancient–modern bridge maps 168 ancient phenotypes onto 213 HPO terms with typed relations and 64 disease profiles at
qualitative levels; on 12 random held-out passages it reached F1 0.822 (precision 0.938, recall 0.732), and its
presentism guard handled 24 of 24 translation cases. Modern evidence is typed by design and population, and
real-world-data questions compile to one checked, read-only OMOP query [@hripcsak2015ohdsi], never model-written SQL.

# Discussion

TaoChronos shows that the reliability of a discovery agent can be engineered and measured. The checks are code a model
cannot route around: a misquotation cannot be committed, an agent cannot approve its own hypothesis, a finished run is
not an accepted finding, and a test of foresight cannot read the future; each boundary was measured by deleting it.
The design complements TCM language models such as ZhongJingGPT [@kang2025zhongjinggpt]: a domain model can act as the
proposer inside the harness, where its claims meet the same checks. Because the kernel names no classic text, vendor
or database, the architecture can serve other written medical traditions.

Five engineering lessons carry beyond TCM. First, authority belongs to identity objects, not strings: a principal set
by the session cannot be forged by an emitter that writes "human". Second, a quotation is located by the harness,
never trusted from its producer, and read for what it states, not only matched. Third, execution and acceptance are
different outcomes; a contract whose criteria name their judges and failure states keeps "completed" from meaning
"accepted". Fourth, every safeguard should be tested by deleting it: a check whose removal breaks nothing is not shown
to work. Fifth, a temporal view must bound every read path, indexes and caches included, so that a test of foresight
counts leakage instead of assuming its absence.

The temporal benchmark evaluates discovery without hindsight, and its verdict is narrow: rankings anticipate later
links well above popularity and chance [@libennowell2007link], but anticipation is not efficacy, and about a third of
surviving predictions were discoveries. Limitations: most gold sets were written by the authors with the rules they
test, and held-out samples are small; model-assisted modes were not evaluated; the independence gate over-merges
source families (independence should be judged per claim), and a failed test of a hypothesis's own statistic should
be a hard objection rather than narrowed away; the full corpus cannot be redistributed and the open subset
is too small for the benchmark; levels and verdicts are ordinal, not calibrated; and the transcriptions were not
collated by this project. TaoChronos gives no clinical or dosage advice.

# Conclusions

Reliability, for an agent that mines historical medical texts, is not a claim that the agent is right. It is a
guarantee about what the agent cannot do, a record from which every conclusion can be rebuilt, and a measure of how
often its proposals deserve a scholar's time. TaoChronos provides all three, with code, open corpus, evaluation
suites, source data and a complete research record released for checking.

# Figure captions {.unnumbered}

{{FIG fig1_architecture}}

**Fig. 1.** TaoChronos: agents propose, validators grade, experts decide. (a) The agent by principal (rows) and stage
of a research round (columns); letters, permissions; filled circles, agents that may consult a model; vermilion, the
hooks; validators alone grade, and only the expert sets G7. (b) Event authority: which principals may emit each group
of the 61 event types. (c) One clause of the *Jingui yaolüe* in three witnesses aligned character by character, with
the provenance chain of one witness from claim to license.

{{FIG fig2_corpus}}

**Fig. 2.** The corpus. (a) Construction from ten sources. (b) Witnesses per 25-year bin (n = 966; blue, the 740
witnesses of the 535 canon works). (c) Basis of dating; undated witnesses counted as Qing. (d) Influence score of the
canon works against composition date. (e) Characters kept per witness of the open web corpus against canon rank.

{{FIG fig3_end_to_end}}

**Fig. 3.** One research question end to end (rules only). (a) Question and contract. (b) The 30 tasks by round and
agent; numbers, tool calls. (c) The 14 hypotheses through the Skeptic and the validators, and the 102 objections by
check. (d) Final hypotheses against gates and contract criteria. (e) Three outcomes with verbatim evidence. D1–D5,
discovery tracks.

{{FIG fig4_verification}}

**Fig. 4.** Verification and safety. (a) Quotation checks on 60 random passages; lines, Wilson 95% CIs. (b) Nineteen
invariants on the intact agent and six variants with one boundary removed each (outlined, the invariant named for that
boundary). (c) 107 hard interpretive cases in eight classes; numbers, held-out correct. (d) Accuracy in four blind
rounds and on all held-out cases; lines, Wilson 95% CIs.

{{FIG fig5_research_value}}

**Fig. 5.** Research value. (a) The blind temporal benchmark. (b) Precision at 10 and 20 and mean average precision of
five rankers over 189 topic–cutoff pairs (95% CIs). (c) Paired comparisons of average precision, two-sided sign tests.
(d) Predictions of the whole pipeline at 1368 on four held-out topics borne out by later books (Wilson 95% CIs).

{{TABLE1}}

# Acknowledgments {.unnumbered}

We thank the editors and volunteers of the Kanseki Repository, 中醫笈成, 數位中醫校書郎 CMETA, Wikisource, McGill
University Library and the Tōa Igaku Kyōkai. [Funding: grant numbers.]

# Compliance with ethics guidelines {.unnumbered}

[Author names] declare that they have no conflict of interest or financial conflicts to disclose. [Amend: IMPF-AI
operates the web deployment of TaoChronos; declare any relationship with ZhongJingGPT.] No human or animal subjects
were involved; the real-world-data path was tested on a synthetic database only.

# CRediT authorship contribution statement {.unnumbered}

[Author 1]: Conceptualization, Software, Methodology, Writing – original draft. [Author 2]: Data curation,
Validation, Writing – review & editing. [To be completed.]

# Declaration of generative AI and AI-assisted technologies in the writing process {.unnumbered}

[Declare here, as the journal requires, any use of generative AI in preparing this manuscript. No language model was
called in any analysis reported in this paper.]

# Data and code availability {.unnumbered}

Code, the open canon corpus, source catalogs with licenses, evaluation gold sets and the source data of every figure
are at <https://github.com/psknlr/TaoChronos> ([license]; version [tag/commit]). The full corpus store is not
redistributed because some sources forbid redistribution; it is rebuilt from the pinned sources (`docs/data.md`).

# Appendix A. Supplementary data {.unnumbered}

Supplementary data to this article (Supplementary Notes 1–4, Supplementary Figs. 1–5, Supplementary Tables 1–14 and
Supplementary Data 1–2) can be found online.

# References {.unnumbered}

::: {#refs}
:::
