---
title: "TaoChronos: A Reliable Agent for Knowledge Discovery in Traditional Chinese Medicine"
short-title: "TaoChronos: a reliable agent for TCM knowledge discovery"
journal: "npj Digital Medicine (Article)"
bibliography: references.bib
csl: csl/nature.csl
link-citations: true
lang: en-GB
---

**Authors:** [Author 1]^1,\*^, [Author 2]^1^, … [Corresponding author]^1,\*^

^1^ IMPF-AI (医哲未来人工智能研究院), [address].
\*Corresponding author: [e-mail].

# Abstract

Large language models can mine the classical literature of traditional Chinese medicine (TCM), but their claims may
misquote the texts, misread negations and conditions, count copies of one text as independent testimony, equate
historical with modern diseases, and resist checking without hindsight. We present TaoChronos, an agent for knowledge
discovery from Chinese medical classics in which models and rules only propose, deterministic validators grade
and human experts alone approve. Every claim must quote a dated witness verbatim and be stated by that quote. On 966
witnesses (123 million characters, 475 BCE–1949), TaoChronos rejected 180 of 180 corrupted quotations, kept 19 of 19
safety invariants, each broken when its safeguard was removed, and read 82 of 84 held-out hard interpretive cases
correctly. In a blind temporal benchmark, rankings from earlier texts alone anticipated links that later
physicians wrote (precision@10 0.168 versus 0.134 for popularity and 0.054 for chance; *P* = 2.4 × 10⁻¹⁶).

# Introduction

The classical literature of traditional Chinese medicine (TCM) is one of the longest written records of clinical
observation. For two thousand years physicians wrote down findings, prescriptions and outcomes, and copied, annotated,
abridged and contested one another's texts. The record has yielded medicines: the low-temperature extraction of
qinghao that led to artemisinin was suggested by a fourth-century prescription in Ge Hong's *Zhouhou beiji fang*
[@tu2011artemisinin], and arsenic, a mineral drug of the tradition, became a cure for acute promyelocytic leukaemia
[@wang2008apl]. Literature-based discovery has long held that connections no single text states can be found
by joining what different texts say [@swanson1986fish], and machine reading of the modern scientific literature can
anticipate findings years before they are published [@tshitoyan2019unsupervised; @sourati2023accelerating;
@krenn2023forecasting]. The TCM classics, however, are unlike a modern literature. A passage survives in witnesses
that differ character by character; its date is often a range, and the commentaries on it accumulated over centuries;
a name meant different things in different periods; and most of what later books say was copied from earlier ones.

Large language models (LLMs) have entered this field quickly. ZhongJingGPT, introduced in 2023 as the first large
language model dedicated to TCM, fine-tuned general-purpose models on instructions constructed from TCM expert
knowledge [@kang2025zhongjinggpt; @cmlm2023zhongjing], alongside Chinese medical models such as HuatuoGPT and
Zhongjing [@zhang2023huatuogpt; @yang2024zhongjing]; benchmarks now test such models on TCM and classical Chinese
[@yue2024tcmbench; @zhou2023wyweb], pretrained models read the classical corpus [@wang2023gujibert], and LLMs help
build knowledge graphs from the ancient medical literature [@li2025tcmrdkg; @xiang2025kgclassics] beside databases
that link herbs, compounds, targets and symptoms from modern sources [@ru2014tcmsp; @wu2019symmap; @fang2021herb].
More broadly, LLMs encode clinical knowledge [@singhal2023clinical], and LLM agents now search and synthesize the
literature, call tools, plan experiments, and propose and test hypotheses [@yao2023react; @boiko2023autonomous;
@bran2024chemcrow; @gottweis2025coscientist; @swanson2025virtuallab; @huang2025popper; @skarlinski2024paperqa2;
@asai2026openscholar; @lu2026endtoend; @wang2024agentsurvey]. In these systems the reliability of what is asserted rests largely on the model. LLMs can
state fluent claims with fabricated or unsupported citations [@ji2023hallucination; @gao2023alce;
@thirunavukarasu2023llm]; retrieval augmentation and atomic fact checking reduce such errors but do not rule them out
[@lewis2020rag; @min2023factscore], and the discoveries of agentic systems are usually judged afterwards, by experts or by
experiments, rather than by checks built into the system. On historical medical texts the failure modes are specific
(Table 1): a quotation altered by one character; a true quotation read as stating what it denies; five copies of one
clause counted as five testimonies; an ancient disease name equated with a modern diagnosis; an association called
'lost' that a later book still states; an agent grading its own work; and a 'prediction' tested on books the system
had already read. Tools for the digital humanities restore, date and contextualize ancient texts
[@assael2022ithaca; @assael2025aeneas; @sturgeon2018reuse; @sturgeon2020ctext], but do not make discoveries under such controls.

We argue that in this domain reliability must be a property of the agent's architecture rather than of its model. It
should be impossible, not merely unlikely, for the agent to commit a misquotation, to grade its own work, to mistake a
finished run for an accepted finding, or to see the future when its foresight is tested. TaoChronos (道乃久) is built on
this principle, which we call *deterministic harness, stochastic intelligence*: everything that must be trustworthy —
state, permissions, verification, stopping and acceptance — is deterministic code, and intelligence, whether a
language model or a rule-based procedure standing in for one, may only propose. This paper makes four contributions.

1. **An agent architecture that separates proposal from verdict.** Sixteen agents, a Director and fifteen
   specialists, work on an event-sourced
   research object through a permissioned tool mesh. Every event carries the principal that emitted it, and the
   reducer refuses an event that principal may not emit, so agents propose, validators grade and only a human expert
   approves. Lifecycle hooks require every claim to quote its passage verbatim and to be stated by that quote; nine
   epistemic gates (G0–G8) grade sources, readings, independence of testimony and falsification; and an executable
   research contract, fixed before the first task, decides whether a research is accepted, so that finishing the
   tasks never counts as success (Fig. 1, Table 1).
2. **A dated, layered and licence-tracked corpus of the Chinese medical classics.** It holds 966 witnesses of 761
   works (about 123 million characters in 2.05 million passages, 475 BCE–1949), each passage with its book, edition,
   locator, date range, textual layer, transcription source and licence. Commentaries and later additions are dated
   apart from the text they annotate, independent transcriptions are kept as separate witnesses, and an openly
   licensed canon, defined by the tradition's own citation network, runs in a web browser together with a
   deterministic study layer for philology and the history of formulas, drugs and terms (Figs. 2 and 6).
3. **A three-layer evaluation of reliability and research value.** Safety invariants are run as probes against the
   agent and checked by mutation; hard interpretive cases are scored with unsafe errors counted apart, on a held-out
   split fixed before the first run and in blind rounds; and a blind temporal benchmark asks whether what the agent
   ranks from the past anticipates what later physicians wrote, with every read path bounded in time so that leakage
   is counted rather than assumed (Figs. 4 and 5, Table 2).
4. **Guarded translation to modern medicine and complete transparency.** An ancient–modern bridge projects the
   findings of a passage into the Human Phenotype Ontology [@kohler2021hpo] with typed relations and reports
   phenotypic similarity, never a retrospective diagnosis; modern evidence is typed by study design and population,
   and real-world-data queries are compiled from checked specifications, never written by a model [@hripcsak2015ohdsi].
   A complete research run is released with its replayable event log and an analysis of its failures that were
   reported, not repaired (Fig. 3, Supplementary Fig. 1).

Every result in this paper was obtained with the deterministic procedures alone, without calling a language model.
The numbers therefore measure the floor the architecture guarantees whichever model is plugged in.

# Results

## An agent in which proposal and verdict are separated

A scientist's question becomes a research contract: its focus terms, forbidden equivalences (for example 消渴 = diabetes
mellitus), discovery tracks, required gates, acceptance criteria and stop rule, hashed before the first task
(Fig. 1a). The Director plans each round and chooses, among fifteen specialists, the agents the kernel spawns: a
Curator who freezes the scope, a Philologist (readings, variants and collation), a Semanticist (period-bound senses), an
Extractor (claims with verbatim spans), Lineage and Scholar agents (citation, transcription and the textual history of
the focus terms), an Evidence agent, a Pattern Miner running five discovery engines (D1, lost knowledge; D2, concept
drift; D3, formula evolution; D4, hidden associations; D5, contradictions), a Statistician, an Evolution analyst, a
Hypothesis agent, a Skeptic, a Meta-reviewer, and two agents for the translation to modern medicine (Supplementary
Table 4). An agent is configuration, not code: a specification names its permissions, tools, context view, output
schema, model tier and budget, and a deterministic procedure and a language model produce the same typed output,
which one commit function verifies.

Every change to the research is a typed event in an append-only log, and the reducer is the only code that changes
state. Each event carries its principal (kernel, human, validator or agent), set from an identity object and never by
the emitter; the reducer checks it against an authority table of 61 event types (Fig. 1b, Supplementary Table 7).
Agents may plan, read, extract, propose and review; only validators grade gates, scores, rankings and the contract;
only a human expert may approve or reject a hypothesis (gate G7) or steer a research; an objection is closed only by a
validator's passing re-run of its check or by an expert, never by a model. Each of the 73 tools needs one of seven
permissions, and every call passes a scope guard before it runs and a result firewall after it, so material withheld
from a research does not exist for its agents (Supplementary Tables 5 and 6). Claims pass three commit hooks:
provenance (the harness, not the producer, locates the quote in its passage), semantic support (the quote must state
the claim's relation) and an anachronism guard. Gates G0–G8 grade the source, transcription, philology, sense, claim
provenance, independent source families, falsification, expert approval and, for cross-space hypotheses only, modern
biomedical evidence (Supplementary Table 2). At the end of a run a validator judges every hypothesis against the
contract on its current version: the research is accepted, needs an expert, is inconclusive or exhausted its budget,
and individual hypotheses may be rejected (Supplementary Table 3). Every claim can be walked back through a provenance chain, in the sense of the W3C PROV model
[@moreau2013provdm], to the words of a witness, its edition, its transcription and its licence (Fig. 1c).

## A dated, layered corpus spanning two millennia

The corpus joins transcriptions from ten sources (Fig. 2a, Supplementary Table 13). Admission keeps historical texts
and removes contemporary publications, works of contemporary physicians and modern annotated editions;
de-duplication against more trusted sources uses normalized 12-character shingles, while independently collated
transcriptions are kept as separate witnesses. Dating is layer-aware: main text, commentaries, editors' notes and
later additions are dated apart, and a witness that cannot be dated is counted as Qing (1644–1911), never earlier.
The store holds 966 witnesses of 761 works, about 123 million characters in 2.05 million passages, from the Warring
States to the Republican period (Fig. 2b). Of the 966 witnesses, 537 are dated to a single year; the basis of every
date is recorded, from curation by the editors (329) and the year in the book's record (204) to signed prefaces (139) and the
author's life (116); 104 are undated and counted as Qing (Fig. 2c). Normalization of variant and simplified forms is
used for matching only; the transcription is never altered.

The tradition's own citations define its canon. An influence score combines the works that cite a work, the periods
in which it is cited, its citations, its witnesses and its inclusion in the *Siku quanshu* (Fig. 2d). The openly
licensed texts of the 350 highest-ranked works form a web corpus of 348 works and 368 witnesses (8.51 million
characters) that runs in the browser, whole for the first classics and by chapters for the rest (Fig. 2e). Catalogue
records of 10,001 printed and manuscript copies in eleven digitized collections link 179 works to physical witnesses
(Supplementary Fig. 4).

## One research question, end to end

We put one question to the agent on the open canon corpus: 肾气丸的组成与主治如何随时代演变？ (How did the
composition and indications of Shenqi wan change over time?), with Shenqi wan and Liuwei dihuang wan as focus terms
and 消渴 = diabetes forbidden (Fig. 3a). The contract required verbatim quotations and at least two evidence records
from at least two independent source families, gates G0–G6 to pass on the current version of each hypothesis (G4–G6
strictly), no open hard or critical objection, rival explanations addressed and expert review before publication;
the run would stop after two rounds or when new evidence added less than 5%. The scope held 206 books and 1,399
passages naming a focus term.

The run planned 30 tasks in three rounds and wrote 734 events (agents 477, validators 124, kernel 133); it called 156
tools, none refused, and no language model (Fig. 3b). It extracted 777 claims and recorded 87 evidence and 22
counter-evidence records. Of 14 hypotheses proposed in round 1, the Skeptic kept 3, sent 10 back to be narrowed and
rejected 1, raising 117 objections (Fig. 3c, Supplementary Table 10). The run stopped in round 2 when new evidence fell
to 4.6%. The contract's verdict (Fig. 3d,e): one hypothesis, that restlessness (烦躁) is a characteristic indication
of Liuwei dihuang wan, met every criterion a machine can check, resting on two independent families of Qing books,
and waits for an expert; twelve were inconclusive, all of them short of two independent source families and six
also failing other criteria; and one, that the
association of Lizhong wan with fever was lost after 960, was rejected because a later book restates it. A second run
wrote the same report. The report, the event log and every hypothesis and objection are released (Supplementary Data
1 and 2, Supplementary Tables 9 and 10).

Reading every surviving hypothesis against its evidence found five failure modes (Supplementary Fig. 1). The largest
is in the independence gate: merging books linked by any transcription or rephrasing link, closed transitively, put
35 of the 38 books that supplied evidence, and 182 of the 368 books of the corpus, into one source family; with
transcription links only, five of the hypotheses that failed G5 would rest on two to four families. The rules also
read co-occurrence in a passage as association (R1's evidence and the later passage that refuted it both name
Lizhong wan beside fever without giving it for fever), dated Xue Ji's case notes of 1547 with the text of 1237 they
annotate, stated one contradiction twice, and found the earliest Liuwei dihuang wan in 1638 because the open corpus
keeps 8 of the 24 chapters of the 1119 work that first records it. We report these failures unrepaired. None of them
concerned the one hypothesis that met every machine criterion, and the largest made the independence gate stricter
rather than looser; but the misreadings behind H2, H10 and H11 show why the final judgement, gate G7, belongs to an
expert.

## Quotations stay verbatim, boundaries hold and hard readings stay safe

On 60 random passages, every verbatim quotation was accepted and every quotation with one character replaced, of
random characters or of the right words at a shifted span was rejected (240 of 240 decisions; Fig. 4a); variant
spellings were accepted after normalization. Every claim and evidence record committed in a demonstration run was
verbatim, with a mean provenance chain of 7.8 levels.

Nineteen invariants (the boundaries the agent promises) were run as probes against the intact agent and against six
variants, each with one boundary removed at run time, in the manner of mutation testing [@jia2011mutation]. All 19 held on the intact agent; each removal broke the
invariant named for its boundary and no other, so 127 of 133 cells held (Fig. 4b). In three cases a second safeguard
limited the damage: without the scope guard, the tool it no longer refused returned nothing of the withheld passage;
forged expert approvals reached the log but not the state; and without the bound checks two of five impossible
evidence records were verified.

Hard interpretive cases test readings that a verbatim quotation does not protect: an inverted relation, a prohibition
beside a prescription, a consequence that is a warning rather than a cure, a view the author reports or rejects, an
omitted condition, mixed witnesses, a disputed date and a textual crux. Of 107 such cases in eight classes, 23 were
used to write the rules and 84 were held out, the split fixed before the first run. The agent read 82 of the 84
held-out cases correctly (0.976; Fig. 4c). Both errors were unsafe: a clause in which most commentators place the
formula Dahuang mudan tang before the prohibition 不可下也, and a doubted word (里水) in the Yuebi jia zhu tang clause,
neither stated in a form the crux harvest reads. Accuracy was measured in four blind
rounds, each on cases written before the rules that first read them (Fig. 4d). The first scored 43 of 53, with four
unsafe errors; general rules (a report governs until its author answers it; a 者-clause followed by an action is a
condition; an intervention named by 之 is read through its pronoun) raised the second to 30 of 32. The third round
introduced textual cruxes and scored 7 of 10, three unsafe; a registry of 127 cruxes harvested from the commentaries
by rules for transposition, emendation, interpolation, omission and doubt raised the fourth to 5 of 5. On 25,000
passages of the full corpus, this second, independent reader found 71 rule claims contradicted by their own quotes;
fixing the extractor at the source left 12, which the commit hook refuses.

## Rankings computed from the past anticipate the links later physicians wrote

To ask whether the agent's discoveries have research value without relying on experts' hindsight, we split the full
corpus at two cutoffs, 1127 and 1368, into passages written wholly before and wholly after each; passages that may
have been written on either side belong to neither (Fig. 5a). The rules were written before the first run. For every
disease or symptom with 150–6,000 past and at least 300 future passages, the formulas and drugs of its past graph not
yet linked to it were ranked, and a candidate came true when claims in two or more later books linked it to the
topic. In 189 topic–cutoff pairs at least one of the 29,467 candidates came true (1,314 in all; base rate 4.5%).
Adamic–Adar [@adamic2003friends], the ranking engine D4 uses, reached a precision@10 of 0.168 (95% confidence
interval 0.152–0.185) and a mean average precision of 0.199, against 0.134 and 0.143 for popularity and 0.054 and 0.092
for chance (Fig. 5b). It ranked above popularity in 149 pairs and below it in 39 (two-sided sign test,
*P* = 2.4 × 10⁻¹⁶), at each cutoff (Fig. 5c). Common neighbours scored as well as Adamic–Adar within the intervals.
Examples of anticipated links include 消渴 (wasting-thirst) with Zhuling tang and Gegen, 胸痹 (chest impediment) with
Gualou shi, and 霍乱 (sudden turmoil) with dried ginger. No passage outside the past view was read.

The whole pipeline was then run on the past view at 1368 for two development and four held-out topics, and its
structured predictions were judged by later books (Fig. 5d). Of 25 held-out predictions, lost associations stayed
absent in 4 of 9, association rules held in 1 of 7, and hidden associations came true in 4 of 8, of which two were new.
The checks on arguments from silence rejected two wrong 'lost' and two already-written 'hidden' associations and no
discovery, raising the share of surviving predictions that were discoveries, true and new, from 7 of 23 to 7 of 19
(0.37; 95% CI 0.19–0.59). The verdict is modest: the ranking anticipates later links well above popularity and chance,
while the pipeline's hypotheses, judged one by one, come true about as often as not. Re-run with identical rules on
the open canon corpus, the benchmark had only 30 pairs with a true link (56 among 6,178 candidates): Adamic–Adar still
ranked above popularity (24 of 30, *P* = 0.0014) but could not be told from chance (13 better, 17 worse, *P* = 0.58)
(Supplementary Fig. 3, Supplementary Tables 11 and 12). The benchmark needs the full corpus.

## The study layer recovers history written into the texts

The deterministic study layer answers the questions scholars ask of the literature daily, and on the open canon
corpus it recovers results the history of medicine already holds (Fig. 6). The share of works writing 山药 rather than
薯蓣 switches between 1000 and 1200, after naming taboos on the names of the Tang emperor Daizong (762) and the Song
emperor Yingzong (1063), and 元参 replaces 玄参 between 1600 and 1800, after the taboo on the Kangxi emperor's name
(1662) (Fig. 6a,b). Passages on warm disease (温病) per 10,000 passages stay between 25 and 36 from the Han to the
Ming and rise to 66 in the Qing (Cochran–Armitage *z* = 6.62, *P* = 3.6 × 10⁻¹¹), when the doctrine of warm diseases
grew into a school of its own (Fig. 6c). Drug pairs that co-occur
beyond chance in 303 compositions (one-sided Fisher exact tests, Benjamini–Hochberg *q* < 0.05 [@benjamini1995fdr])
form groups that coincide with the cores of classical formulas — Liuwei dihuang wan, Guizhi tang, the Mahuang tang
family, Xiao chaihu tang and Baihu tang — found without formula names (Fig. 6d); on the full store all seven textbook
pairs tested were significant with lift above 1.5. Of 1,279 citations between 72 physicians, 511 (40%) cite Zhang Ji,
the author of the *Shanghan lun* (Fig. 6e).

## Generalization and the bridge to modern medicine

Where rules were written with examples, held-out data show how far they transfer (Supplementary Fig. 2, Table 2).
Hard interpretive readings fell from 1.00 on development cases to 0.98 on held-out cases, entity recognition in 24
types from an F1 of 0.99 to 0.78, and lost-text reconstruction from a precision of 0.86 on a constructed lost work to
0.32 on the real *Qianjin yaofang*. A punctuation model learned from editorially punctuated texts placed sentence
boundaries with an F1 of 0.767 on 55 held-out works (rules, 0.235) and 0.780 on unpunctuated *Siku* texts, changing no
character. Ablations showed which components carry the results: without the sense route of retrieval the earliest
attestation of a term was found for 4 of 6 terms instead of 6, without sense resolution contradictions were typed
right in 10 of 12 pairs instead of 12, and without the Skeptic a rejected hypothesis survived review; the agents'
context views were 94% smaller than a naive dump of the research state (8,427 against 142,388 tokens).

The ancient–modern bridge reads the findings of a passage — negated, optional, conditional or after treatment — into
168 ancient phenotypes projected onto 213 terms of the Human Phenotype Ontology, each with a relation type (exact,
broader, partial overlap, historical semantic shift, no modern equivalent and others), and compares them with 64
modern disease profiles at qualitative levels that are never probabilities. On 12 passages drawn at random from 65
clinical works and annotated before the reader ran on them, it found findings with a precision of 0.938 and a recall of
0.732 (F1 0.822). A presentism guard handled 24 of 24 translation cases correctly, refusing equations,
retrospective diagnoses and modern names a translation adds while letting careful comparisons pass; modern records are typed by design and population, and a cross-level guard refuses animal, cell or
computational work read as efficacy in people (7 of 7). Asked for passages resembling diabetes mellitus, the bridge
returns the *Waitai miyao* and the 'three wastings' of the *Jingyue quanshu* at a high level and the 消渴 of the
*Jingui yaolüe* at a moderate one; asked for malaria, it also returns the alternating chills and fever of the
*Shanghan lun* — a resemblance of a pattern to a disease, which is why the bridge reports resemblance and never
diagnosis.

TaoChronos also runs as a conversation agent in the browser (Pyodide) on the open canon corpus, where a user's chosen
model answers through 79 tools and the page checks every cited passage word for word (verbatim, misquoted or no such
passage). Conversation records were not used in this study.

# Discussion

TaoChronos shows that the reliability of an agent for knowledge discovery from historical medical texts can be
designed and measured rather than hoped for. The checks that make it reliable are not instructions to a model; they
are code a model cannot route around. A misquotation cannot be committed, an agent cannot approve its own hypothesis,
a finished run is not an accepted finding, and a test of foresight cannot read the future. Each boundary was measured
by removing it and watching its invariant break, and the readings that verbatim quotation does not protect were
measured on cases held out before the rules were written. We think this inversion — the model's output as untrusted
input to deterministic checks, rather than the model as the judge of its own output — is what high-stakes uses of
agents in medicine need.

The design complements TCM language models. ZhongJingGPT and its successors carry knowledge of TCM in their weights
[@kang2025zhongjinggpt; @yang2024zhongjing]; TaoChronos carries none, but holds whatever a model proposes to the
witnesses. A domain model can serve as the proposer inside the harness, where its claims meet the same provenance,
support, independence and anachronism checks as the rules' and its discoveries face the same contract. Because the
kernel names no classic text, vendor or database, the same architecture could serve other written medical traditions
— Kampo, Ayurveda or the Greek and Arabic corpora — and other literatures in which copies, commentaries and changes of
meaning entangle the evidence.

The blind temporal benchmark offers a way to evaluate discovery without asking experts to judge novelty with
hindsight. Its conclusion is deliberately narrow. Rankings from the past anticipated what later physicians wrote,
well above popularity and chance, in line with link prediction on modern literatures [@libennowell2007link;
@krenn2023forecasting]; but anticipation is not influence or efficacy, both sides were read by the same rule
extractor, and about a third of the pipeline's surviving predictions were discoveries. On the open subset the
benchmark could not separate the ranking from chance. For digital medicine the lesson is that a classical text can
suggest what to study, as it did for artemisinin [@tu2011artemisinin], and that provenance, independence and the
absence of hindsight decide whether the suggestion deserves attention. TaoChronos never turns a suggestion into advice:
the bridge reports resemblance, modern evidence must come from people to pass gate G8, and dosage or clinical advice is
refused.

The study has limits. First, most gold sets were written by the authors with the rules they test; they are
regression tests of intended behaviour, and only held-out and real-corpus results estimate generalization, some on
small samples (12 bridge passages; 84 interpretive cases). Expert-annotated gold on the full corpus is needed.
Second, every number was obtained with rules alone; model-assisted modes are implemented, with recorded and replayable
responses, but not evaluated here. Third, the end-to-end run exposed an over-merging of source families that makes the
independence gate too strict; judging independence per claim, from the passages that support it, is the fix we
propose. Fourth, the full corpus cannot be redistributed because some sources forbid it; the open canon corpus
reproduces the end-to-end run and the study layer but is too small for the temporal benchmark, whose full-corpus
values are documented runs. Fifth, levels, verdicts and gates are ordinal labels, not calibrated probabilities, and the
64 disease profiles need clinical review. Sixth, the transcriptions were not collated by this project, Siku texts
carry Qing alterations, and undated texts can only be placed 'Qing or earlier'. Finally, an alias-aware search added
since met six or seven of ten pre-specified acceptance checks on its held-out set, depending on the profile, and is
reported as such.

Reliability, in this sense, is not a claim that the agent is right. It is a guarantee about what the agent cannot do,
a record from which every conclusion can be rebuilt, and a measure of how often its proposals deserve a scholar's
time. We release the code, the open corpus, the evaluation suites, every figure's source data and the complete
record of a research run, findable and reusable in the sense of the FAIR principles [@wilkinson2016fair], so that
each of these can be checked.

# Methods

## Corpus construction

Transcriptions were taken from the Kanseki Repository (the medical section of the *Siku quanshu*, 100 works,
CC BY-SA 4.0), JiCheng (中醫笈成, 816 of 857 edited texts; CC0 1.0 for its editorial work), CMETA (數位中醫校書郎, 11
editions collated against page images, CC BY 4.0), the Tōa Igaku Kyōkai (7 texts, local research use only), Wikisource
(18 works new after de-duplication of 627, CC BY-SA 4.0), McGill University Library (5 works, public domain) and three
further collections (Supplementary Table 13). Every text is pinned in a lock file by repository, commit, file hashes
and licence; texts are never committed to the repository unless their licence allows redistribution. Admission
screens out, in order, reviewed decisions, works composed from 1949, titles that mark a modern edition or a
contemporary physician, a density of modern years, units and institutions, annotation apparatus and modern editors'
source marks; each excluded text is catalogued with its class and evidence. De-duplication ranks sources by trust and
records a candidate sharing enough normalized 12-character shingles with an admitted work as its copy; McGill, CMETA
and Tōa Igaku Kyōkai transcriptions are kept as independent witnesses.

Each work's catalogue entry gives its authors, composition date range and layer rules: double-column notes as a
commentary layer, marked notes (for example the Song editors' 新校正云 of 1068 in the *Suwen*), indented commentary,
chapters and sections added later (the seven *Yunqi* chapters inserted by Wang Bing in 762), and mixed layers dated by
the latest, with the older text's date kept as its citation date. Front matter is dated separately; undated prefaces
are placed at the end of the imperial era. Dates follow, in order of precedence, curated overrides, the Kanripo
catalogue, the book's own record (years, reign eras, dynasties), dated prefaces parsed with a table of eras, another
witness of the work and the author's other dated works; an undatable witness is placed in the Qing, never earlier.
Passages keep book, edition, volume, chapter, section and, where available, page and line, the date range, the layer,
the transcription source and the licence. Normalization of variant, simplified and taboo forms is used for indexing
and matching only.

## Canon and the open web corpus

The influence of a work is 10 log₂(1 + citing works not older than it) + 2 × (periods in which it is cited) +
2 log₂(1 + citations) + 3 log₂(1 + witnesses) + 6 × (inclusion in the *Siku quanshu*), computed on the citation network
the study layer resolves. The openly licensed witnesses of the 350 highest-ranked works form the web corpus used for
Figs. 2e, 3 and 6 and Supplementary Fig. 3: a work's first witness kept up to 350,000 characters for ranks 1–10, then
50,000, 25,000 and 12,000, whole where shorter and by sampled chapters otherwise, and second and third witnesses for
the ten highest-ranked works. The figures were built on this snapshot (348 works, 368 witnesses, 8.51 million
characters, 135,083 passages); the distributed corpus has since been extended to 533 of 535 ranked works.

## Claims, readings and the claim hypergraph

The Extractor turns a passage into claims: hyperedges such as indicated_for(formula: 五苓散 | pulse: 浮, symptom: 小便不利,
symptom: 微热, disease: 消渴), each with a verbatim quotation, a character span for every argument, negations, optional
findings, conditions and adverse outcomes, and a temporal context. Unpunctuated text is read through a
machine-segmented view whose spans map back to the source, and such claims carry a lower extraction confidence. At
commit the provenance validator relocates every quotation in its passage (verbatim, or after length-preserving
variant normalization) and refuses one that cannot be found. The semantic-support reader then decides whether the
quotation states the claim: the nearest cue governs each intervention, the consequence decides between warning and
recommendation, an intervention named by 之 is read through its pronoun, each argument is read with its negation, and a
statement frame records the speaker, the stance (asserted, reported or rejected), conditions, negations and time. A
claim its quotation contradicts is refused. Textual cruxes are harvested from the commentaries in the store by rules
for markers of transposition, emendation, interpolation, omission and doubt (a statement must name words the clause
has, or two commentators must doubt it); a claim that rests on doubted words reads as ambiguous.

## The agent harness

The research object holds all scientific state and is changed only by the reducer applying typed events. Each agent
task runs in a transaction whose events are validated on the state their predecessors build and appended at commit
as one batch; a crash before the commit marker leaves a torn tail that is discarded, and the task is re-run. The state
hash covers scientific fields only, so reruns, resumed runs and parallel runs give the same hash. Agents act through a
view bound to their identity and read a frozen state view; capability handles are scoped to the research's reading
scope, and withheld tiers (hold-out, confirmation, expert-only) stay withheld. Every tool call passes permission,
argument schema, budget and hooks, and leaves a receipt (tool, version, actor, principal, hashes of arguments and
result) whose hash chain the run manifest records. Code written by a model runs only in a namespace sandbox (no
network, read-only root) and reaches tools through the scheduler. A model call sees a compiled context view, never the
whole research object, and its estimated cost is reserved in a budget ledger before it is made. In hybrid mode the
procedure drafts and a model may improve the draft; if the model fails, the draft is committed and the fallback
recorded. The Cognitive Model Router prefers, where models are configured, a different model for the Skeptic than for
the Hypothesis agent.

## Discovery engines, hypotheses and falsification

D1 finds associations of a drug or formula with a finding or disease attested before a pivot year (960 by default)
and absent afterwards although both concepts remain in use, with the probability of no later co-occurrence had the
early rate persisted, leave-one-family-out and a family bootstrap. D2 compares the contexts of a term across periods
by Jensen–Shannon divergence with a max-statistic permutation test over all period boundaries and
Benjamini–Hochberg correction across terms, a count-based counterpart of studies of semantic change
[@hamilton2016diachronic]. D3 compares compositions, with taboo renamings and processing variants
merged, into formula families. D4 mines association rules (support, confidence, lift, Fisher exact *P*,
Benjamini–Hochberg) and ranks unlinked candidates by Adamic–Adar on the clique expansion of positive hyperedges only.
D5 compares claims about one subject on etiology, origin, cold and heat, treatment and findings, and labels oppositions
apparent, conditional, differential or contradictory. Hypotheses carry verbatim evidence, structured predictions
(absent after, link appears, co-occurrence after, herb retained, sense shift and others), rival explanations and a
warrant. The Skeptic tries to refute every hypothesis before it is believed [@popper1959logic]. It checks provenance, anachronism, contested readings, homonymy, transcription dependence, single
sources, coverage, corrected statistics and, for arguments from silence, explicit supported statements anywhere in the
scope (restated after the pivot for D1, attested for D4), which are hard, critical objections. Objections follow a state
machine (raised, resolution proposed, closed); a model can only propose a resolution. A revision is restricting
(qualifiers only, the parent's support carried over) or substantive (it needs its own support).

## Gates and the research contract

Gates are computed by validators on the version of each hypothesis they judge (Supplementary Table 2). G5 counts
independent source families: clusters of witnesses of one work or author or linked by transcription or rephrasing.
G6 fails while a critical objection is open. G7 is set only by a human expert's approval or rejection, and a gate event
carrying G7 is refused from any principal. G8 applies to hypotheses that cross into biomedicine: records in people must
support the claim, and contradicting modern evidence fails it. The contract's acceptance criteria (minimum support,
semantic support, source dependence, falsification review, open hard and critical objections, rival explanations
addressed, gates on the current version and expert review) each record their judge, what was observed, what was
required and the state an unmet criterion leads to (Supplementary Table 3).

## Evaluation

TaoChronos-Eval has 40 suites in three layers (Supplementary Note 1, Supplementary Table 1). Invariants are probes run
against the agent under test; for the mutation matrix each of six boundaries (scope guard, result firewall,
semantic-support hook, reducer authority over G7, evidence-bound checks and publish guard) was removed by deleting its
check at run time and all 19 probes were run on each variant. The 107 interpretive cases are verbatim quotations of the
demonstration or full corpus with one correct reading; unsafe errors (a contradicted claim read as supported, a
reported view read as the author's, a dropped condition, a mixed witness verified, a disputed order asserted, a
possibly later text put before a cutoff) are counted apart. Cases whose misses prompted a general change were moved to
development, and the change was measured on a new held-out round written before it ran; held-out misses were reported,
not patched. Quotation checks drew 60 random passages and four probes each (verbatim; one character replaced; random
characters; verbatim at a shifted span). Collation and stemma recovery were tested on artificial traditions copied
down a known stemma, as in benchmarks of computer-assisted stemmatology [@roos2009stemmatology].

For the temporal benchmark, `corpus.on_side(cutoff, side)` exposes only passages whose whole date range lies on one
side of the cutoff, with every read path, including full-text search and the study layer's queries, bounded in SQL.
Topics were the diseases and symptoms of the lexicon with 150–6,000 past and at least 300 future passages (future
passages read up to 6,000 per topic, sampled by passage-identifier hash); candidates were the formulas and drugs of the
topic's past positive-claim graph not linked to it, the lexicon's 254 weak one-character entries excepted (a change made
after the first run, which gave the same ordering); a candidate came true when positive claims of at least two later
books linked it to the topic. Precision@*k* pools hits over pairs (Wilson intervals [@wilson1927probable]); mean average
precision has a 999-resample bootstrap interval; chance is the mean of 20 random rankings; paired comparisons use
two-sided exact sign tests of average precision with ties excluded. End-to-end predictions were judged strictly (a
later claim of the association's own relation whose quotation supports it). Development topics (消渴, 中风) were
inspected while the absence checks were built; held-out topics (胸痹, 霍乱, 虚劳, 痰饮) were fixed before them and only
aggregates were examined. Any passage read outside the past view would have been counted as leakage.

## Study-layer analyses

Name switches (Fig. 6a,b) are the share of works per century writing each name; the switch interval is where the
preferred name changes. Term frequencies (Fig. 6c) are passages per 10,000 by period with Wilson intervals and a
two-sided Cochran–Armitage test for trend [@armitage1955tests]. Drug pairs (Fig. 6d) count a composition repeated in
copies of one work once, test pairs present in at least ten works with one-sided Fisher exact tests and
Benjamini–Hochberg control, and rank significant pairs by normalized pointwise mutual information [@bouma2009npmi].
Citations (Fig. 6e) are resolved from explicit attributions to physicians; links whose cited physician lived after the
citing one (five links, 28 citations) were omitted as chronologically impossible.

## The ancient–modern bridge, modern evidence and real-world data

The bridge normalizes the passage, matches written forms longest first (one-character forms only at clause boundaries),
bounds each finding (negated, optional, conditional, after treatment) and reads the passage's course, population and
the period-bound sense of each historical term. Each disease profile is scored by specificity-weighted coverage of its
typical findings, the share of the description it explains, matching through the HPO hierarchy, conflicts and
compatibility; qualitative levels follow rules over the matched findings, and every cap that applies (no required
finding, support only from what a name implies, a formula's indications) is reported. All 213 HPO identifiers were
checked against release 2026-09-01. Modern records are typed by publication type, MeSH headings, title and abstract;
network-pharmacology [@hopkins2008network] and docking studies are typed as computational, never as efficacy;
real-world-data questions become a study specification validated against the database's vocabulary and compiled into
one fixed, parameterized, read-only query over the OMOP Common Data Model, evaluated here on a synthetic database only.

## Software and reproducibility

TaoChronos is written in Python (≥3.11; the kernel depends only on PyYAML) and checked by 645 test functions and an
architecture policy on allowed imports. Every figure, table and supplementary item of this paper is rebuilt from the
repository by `paper/make_all.sh`, which builds the open corpus store, runs `taochronos eval` on the demonstration
corpus (40 suites, 47 s), the study layer and the end-to-end case on the open corpus, and the mutation matrix; values
that need the full corpus store are transcribed from the documented runs in `docs/evals.md` and marked.

## Use of large language models

[Declare here, as the journal requires, any use of large language models in preparing this manuscript. No language
model was called in any analysis reported in this paper.]

# Data availability

The open canon corpus (`corpus/web`), the demonstration corpus, the catalogues of all sources with their licences and
the image-witness records are in the repository; the attribution and licence of each source are in
`corpus/web/ATTRIBUTION.md`. The full corpus store is not redistributed because some of its sources forbid
redistribution; it is rebuilt from the sources with the commands in `docs/data.md`, pinned by
`corpus/sources.lock.yaml`. Source data for every figure are in `paper/figures/source_data`. The Discovery Report and
event log of the end-to-end run are Supplementary Data 1 and 2. No patient data were used; the real-world-data path was
tested on a synthetic OMOP database.

# Code availability

The code is available at <https://github.com/psknlr/TaoChronos> [licence to be added]; the version used for this paper
is [release tag / commit]. A web deployment runs at <https://chat.impf.ai/>.

# Acknowledgements

We thank the editors and volunteers of the Kanseki Repository, 中醫笈成, 數位中醫校書郎 CMETA, Wikisource, McGill
University Library and the Tōa Igaku Kyōkai, whose transcriptions made this work possible. [Funding.]

# Author contributions

[To be completed, e.g. in CRediT form: conceptualization, software, data curation, formal analysis, writing.]

# Competing interests

[To be completed. IMPF-AI operates the web deployment of TaoChronos; please also declare any relationship with
ZhongJingGPT.]

# References

::: {#refs}
:::
