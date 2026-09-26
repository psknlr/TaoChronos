# TaoChronos

**A provenance-grounded research harness for the Chinese medical classics — for scholars, students and discovery.**
*面向中医古籍的可溯源知识发现与治学系统*

[中文 README](README.md) · [Study layer](docs/study.md) · [Architecture](docs/architecture.md) · [Agents](docs/agents.md) ·
[Discovery](docs/discovery.md) · [Evaluation](docs/evals.md) · [Data](docs/data.md) · [Roadmap](docs/roadmap.md) · [ADRs](docs/adr/)

TaoChronos turns 926 Chinese medical classics (about 119 million characters in 1.98 million passages) into a corpus
that can be searched, dated and cited, and offers two layers on top of it:

- **Study (治学)** answers the questions scholars and students ask of the literature every day, the way the 考据
  tradition answers them: where does this passage recur and how do the witnesses differ (concordance with a
  collation apparatus); what was a formula's original composition and what became of it (formula provenance); when
  was a drug first said to enter a channel (materia-medica history); when does a term rise and fall, and what did it
  mean (term history); which edition is this, judging by its taboo characters (taboo dating); whom did each period
  cite (citation network) — plus study cards, reading paths and research datasets.
- **Research** turns a question into a replayable, auditable, falsifiable process: the research director
  **TaoChronos** dispatches 16 specialist agents — research contract → evidence foundation → pattern mining →
  hypotheses → falsification → gates G0–G8 → expert review.

Both layers share one rule: **every statement rests on verbatim witnesses** (book, volume·chapter·section, date,
text layer, source and licence of the transcription). Rule-based reading is labelled as machine reading; people check
and decide.

> ⚠️ The corpus consists of transcriptions from several sources (Siku, 笈成, McGill rare books, Wikisource, web
> text sets), **none collated by this project**; `corpus/demo` holds unverified excerpts for demonstrating the method.
> Contemporary publications, works of contemporary physicians and modern annotated editions are left out. All outputs
> are textual research and computational inference — not medical conclusions or clinical advice. Doses read in
> historical measures are scholarly estimates of historical measures, **never dosage guidance**.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Quick start](#2-quick-start)
3. [Corpus](#3-corpus)
4. [Study: mining the classics on their own terms](#4-study-mining-the-classics-on-their-own-terms)
5. [Research: multi-agent knowledge discovery](#5-research-multi-agent-knowledge-discovery)
6. [Use cases](#6-use-cases)
7. [Models and deployment](#7-models-and-deployment)
8. [Evaluation and quality](#8-evaluation-and-quality)
9. [Architecture](#9-architecture)
10. [Repository layout](#10-repository-layout)
11. [Data and licences](#11-data-and-licences)
12. [Limitations](#12-limitations)
13. [Roadmap and citation](#13-roadmap-and-citation)

---

## 1. What it does

| For | Capability | Entry point |
|---|---|---|
| **Philologists** | concordance with a 校勘记 (other copies / quotations / restatements; 异文, 脱, 衍, 倒); taboo dating of editions; citation network and reception histories | `study concordance` · `study taboo` · `study citations` |
| **Historians of formulas, materia medica and medicine** | formula provenance (original and current compositions, 加减, 同名异方, 同方异名, dose ratios, doses in the measures of their period, indications, verses); drug-property histories (flavour, toxicity, 归经, 升降浮沉 — first statements and changes); term histories (shares by period with intervals, trend test, first attestations, collocates, senses) | `study formula` · `study herb` · `study term` |
| **Researchers who need data** | open tables with provenance, dates and licences (Frictionless data packages) for statistics and visualisation | `study dataset` |
| **Students** | cloze cards for 方证, compositions (with verses), drug properties and key passages, exported to Anki; reading paths from the source classics to the Republican syntheses | `study cards` · `study reading` |
| **Knowledge discovery** | multi-agent research: lost knowledge, concept drift, formula evolution, hidden associations, contradictions, lost sources; verbatim evidence, falsification, gates, expert review | `research` · `report` · `workspace` · `review` |
| **Developers** | plugin kernel, capability registry, a tool mesh of 35 tools, agents as YAML specs, event sourcing and replay, evaluation and architecture governance | `agents` · `eval` · `governance` |

## 2. Quick start

```bash
pip install -e ".[dev]"            # Python ≥ 3.11; data and configuration live in the repository root (or TAOCHRONOS_HOME)
taochronos demo                    # the offline 消渴 demo research (deterministic procedures, ~4 s, demo corpus)
taochronos study formula 六味地黄丸 # study: formula provenance (on the demo corpus until the full corpus is ingested)
taochronos agents                  # the 16 agents and their current routes
```

The full corpus (texts never enter git; fetching, cataloguing and ingestion are reproducible — see [§3](#3-corpus)):

```bash
taochronos corpus fetch kanripo && taochronos corpus ingest kanripo     # the 100 medical works of the Siku quanshu
taochronos corpus unpack jicheng jc_1_4_8_all.7z.001 jc_1_4_8_all.7z.002 jc_1_4_8_all.7z.003
taochronos corpus catalog jicheng && taochronos corpus ingest jicheng    # the 笈成 collection (user-supplied)
taochronos corpus status
```

Study (uses the `full-corpus` profile when the store exists; Markdown by default, `--json` for the full result,
`-o` to write a file):

```bash
taochronos study concordance "太陽之為病，脈浮，頭項強痛而惡寒"
taochronos study formula 小柴胡汤
taochronos study herb 柴胡
taochronos study term 温病
taochronos study taboo                                              # a survey of the store, or give a book id
taochronos study citations 张仲景                                   # a reception history (no target: the network)
taochronos study cards --book 伤寒论 --formula 桂枝汤 --herb 柴胡 --anki cards.tsv
taochronos study reading 温病
taochronos study dataset --formula 桂枝汤 --herb 柴胡 --term 温病 --citations -o datasets/guizhi
taochronos study metrology 三两 --year 200                          # ≈41.4–46.8 g (Han measures) — history, not dosage
```

Research:

```bash
taochronos research "肾气丸的组成与主治如何随时代演变？" --profile full-corpus --focus 肾气丸,六味地黄丸 --forbid 消渴=糖尿病
taochronos report <session>        # the 12-section Discovery Report (with a Sources Dossier appendix under full-corpus)
taochronos workspace <session>     # the offline HTML Discovery Workspace
taochronos review <session> <hypothesis> --approve --expert <name>   # Gate G7: only a person can pass it
taochronos eval                    # all TaoChronos-Eval suites (~30 s)
taochronos governance              # architecture policy check
```

## 3. Corpus

| Source | Licence | Ingested | Notes |
|---|---|---|---|
| Kanseki Repository KR3e, *Siku quanshu* medical works | CC BY-SA 4.0 | **100 works**, 25.7 M characters | unpunctuated Siku / Sibu congkan texts; a curated catalogue with authors, dates, schools, editions and layer dating |
| 笈成 (JiCheng) v1.4.8 | user-supplied, local research only | **797 works** (857 less 60), ~92.3 M characters | punctuated by its editors; headings, prescription blocks, commentaries, collation remarks and missing characters parsed from the markup |
| McGill University Library rare gynaecology books | public domain | **5 works** | Qing prints and manuscripts, unpunctuated |
| Wikisource Category:中醫 (from the Wikimedia dumps) | CC BY-SA 4.0 | **15 works** (new of 625) | 天回医简, 五十二病方, three Republican "ancient" editions of the 伤寒杂病论, 东医宝鉴 … |
| TCM-Ancient-Books / tcmoc | undeclared, local research only | **8** / 0 works | mostly simplified copies of 笈成 texts, deduplicated work by work |
| Hugging Face classical-tcm-canon | proprietary-commercial, local research only, never redistributed | **1 work** | 张志聪's 伤寒论宗印·集注 |
| KR-Catalog (Kanripo catalogue) | CC BY-SA 4.0 | catalogue | roles and dates of 132 persons responsible for the Siku works |

In all **926 works, ~119 million characters, 1.98 million passages**.

- **Admission**: historical texts only. Contemporary publications, contemporary physicians' works and modern annotated
  editions (including modern reconstructions of lost books) are excluded after review (`corpus/catalog/exclusions.yaml`,
  automatic screening for the rest); Republican works (1912–1949) stay as historical sources.
- **Deduplication**: sources are ranked by reliability (Siku → 笈成 → McGill → Wikisource → web sets); each candidate is
  compared with what is already in by 12-character shingles of normalised text, and copies are recorded with the book
  they duplicate and the overlap.
- **Dating**: curated overrides → the Siku catalogue → western years, reign eras and dynasties in the book metadata →
  signed prefaces → other transcriptions of the work → the author's other works; commentaries, editorial notes, added
  chapters and appended prescriptions are dated as layers of their own (王冰注 762, 新校正 1068, the layers of the 证类本草 …);
  inseparable layers are dated by the latest. Undatable works count as Qing, never earlier.
- **Normalisation for matching only**: OpenCC script conversion + Unihan variants + curated medical variants, length-
  preserving; the text is never altered. Unpunctuated Siku text is read through a machine-segmented view whose spans
  map back to the source.
- **Search**: a SQLite store with a character-bigram FTS5 index (terms of any length, phrases, proximity); research
  samples a period-stratified frame, falsification queries the whole store.

See [docs/data.md](docs/data.md) and [ADR 0003](docs/adr/0003-corpus-store-and-scoped-research.md).

## 4. Study: mining the classics on their own terms

The study layer (`plugins/classics/study`, [docs/study.md](docs/study.md), [ADR 0004](docs/adr/0004-study-layer.md)) is a
set of deterministic functions over the corpus. Their results are made of **witnesses** — a verbatim quote, passage id,
《book》volume·chapter·section, date and period, text layer, source and licence — so every statement can be checked.

### What the texts demand, and what the study layer does

| Feature of the classics | Handling |
|---|---|
| One work in several transcriptions, quoted and restated | concordance separates other copies (同书异本), quotations (引文) and restatements (互见), and collates the close witnesses (异文, 脱, 衍, 倒 with their witnesses) |
| Names changed under taboo | 薯蓣 → 薯药 (Tang Daizong) → 山药 (Song Yingzong), 玄参 → 元参, 丸 → 圆 (Song Qinzong): all spellings are searched, and the spellings date the edition |
| One name for several formulas, several names for one formula | compositions are grouped by their drugs: 同名异方 apart, 同方异名 found by the drugs rather than the name |
| 笈成 prints formula and drug names as entry headings | a corpus-wide index of entry headings (cached) finds entries whose text never names them; the parser reads across the entry's paragraphs |
| Measures differ by period | doses are read in the measures of their witness's own date (a Han 两 ≈ 13.8–15.6 g, from the Song ≈ 37–41 g; 分 changes meaning around 960); ratios compare witnesses independently of measures |
| Doctrines are period-bound | 归经 and 升降浮沉 are Jin–Yuan doctrines: their absence from the 本经 is expected; the first statement of each value is reported with its date |
| Uncertain, layered dating | "earliest" orders by the latest date a witness can have (terminus ante quem); citations dated before the cited work existed (editors' notes dated with their text) are set aside |
| Uneven survival across periods | term frequencies are shares of passages per period with 95 % Wilson intervals and a Cochran–Armitage trend test, never raw counts |
| Formulas were learned in verse | 方歌 are found in the verse books: five- or seven-character clauses naming the formula and reciting its drugs (abbreviations included), joined across passages |

### Nine functions, with results on the full corpus

| Function | What it returns | Full-corpus example (machine reading, with quotes to check) |
|---|---|---|
| **Concordance** `study concordance` | every witness of a passage in date order; relation; collation apparatus | 「太阳之为病，脉浮，头项强痛而恶寒」: 113 witnesses in 46 works (8 other copies, 10 quotations, 95 restatements); the 千金翼方 lacks 脉浮. 「上古之人……食饮有节」: 47 witnesses, 32 of them quotations; the transposition 食饮 → 饮食 in 8 |
| **Formula provenance** `study formula` | all written-out compositions; 原方, 通行方, 加减化裁, 同名异方, 孤例; 同方异名; ratios; doses in their period's measures; indications; modifications; verses | 六味地黄丸: 266 compositions in 84 works; the original and current tradition (69 witnesses) begins with the 地黄丸 of the 小儿药证直诀 (1119), ratio 8 : 4 : 4 : 3 : 3 : 3; the name 地黄丸 first belongs to a different formula of the 千金要方 (同名异方). 小柴胡汤: original in the Song edition of the 伤寒论; other names 黄龙汤, 柴胡汤; verses in the 汤头歌诀 and 长沙方歌括 |
| **Materia medica** `study herb` | flavour, nature, toxicity, channels, direction, indications and aliases per work; first statements | 柴胡: 30 works; 味苦平无毒 in the 本经; the first channel, 足少阳, in the 汤液本草 (1289–1308). 山药: 署豫 in the 本经, 薯蓣 in the 证类本草, 山药 in the 汤液本草 (手太阴) |
| **Term history** `study term` | shares by period with intervals, trend test, first attestations, collocates, densest works, senses with candidate modern concepts | 温病: 5 795 passages; 15 per 10 000 in the Ming, 39 in the Qing, 252 in the Republic (z = +29.6). 消渴: 66 per 10 000 in the Han, 38 in the Ming (z = −8.3); collocates shift from 小便不利 to 消中 and 多饮 |
| **Taboo dating** `study taboo` | counts and verdicts per taboo rule, the edition's lower bound; a survey | of 138 works over 200 000 characters, 8 transmit an edition later than their composition: both 千金 books (丸 → 圆, Song prints after 1126), 外台秘要 and 太平圣惠方 (玄, after 1012), 本草品汇精要 (玄 → 元, a Qing copy), 女科证治准绳 (宁 → 甯, after 1821) |
| **Citations** `study citations` | works and physicians cited per period (self-citation, other copies and authors' own names excluded), physician lineage, reception histories | the Ming cites 朱震亨 (2 820), 张机 (2 103), 李杲 (1 621); the Qing 张机 (3 499); the Song–Jin–Yuan 日华子 (1 876, via the 证类本草); the reception of 张仲景 begins with the 针灸甲乙经 and the 脉经 |
| **Cards** `study cards` | 方证 cloze, compositions with verses, drug properties (本经 and later), key passages; Anki export | 「太阳病，头痛，发热，汗出，恶风，〔　　〕主之。」 → 桂枝汤 (伤寒论 §13) |
| **Reading path** `study reading` | source classics → treatments by period → monographs → case records → Republican syntheses, each with the reason | 温病: 素问, 灵枢, 难经, 伤寒论, 甲乙经 → 医经溯洄集, 尚论后篇, 温热逢源 → 温病条辨 → case records → 止园医话 |
| **Datasets** `study dataset` | five tables (composition witnesses, ingredients with period readings, drug entries, term periods, citation edges) + `datapackage.json` | every row has its passage id, locator, date and licence; **short quotes only (≤ 120 characters), never the texts** |

The study layer is part of research too: under `full-corpus`, **TaoChronos-Scholar** traces the focus formulas, drugs
and terms through the whole store in round 0, and the dossiers become the report's appendix "源流考证 · Sources
Dossier" (descriptions of texts, not hypotheses; no gates).

## 5. Research: multi-agent knowledge discovery

```
Research contract GoalSpec (immutable: question, focus terms, tracks, time window and hold-out, forbidden assumptions, required gates)
   │
   ├─ round 0 · foundation   plan → scope → philology → senses → claims (+G0–G4) → lineage → sources dossier → evidence → mappings (proposals)
   ├─ round 1 · discovery    mining D1–D5 → statistics → evolution maps → hypotheses → falsification → revision → re-review
   │                         → cross-space bridges (G8) → gates G0–G8 → scores and Elo tournament → meta-review
   └─ round 2+ · deepening   act on the meta-review: independent evidence, sensitivity analyses … or stop
```

Agents are **configuration** (`agents/*.yaml`), instantiated per task — not a fixed team.

| Agent | Role | Mode |
|---|---|---|
| **TaoChronos** | research director: plans each round, decides which specialists to dispatch | hybrid |
| TaoChronos-Curator | corpus scope, time hold-out, coverage warnings | procedure |
| TaoChronos-Philologist | collation: variants, reading probabilities, collation status | hybrid |
| TaoChronos-Semanticist | historical semantics: period-bound senses, homonymy risk | hybrid |
| TaoChronos-Extractor | claim hyperedges with verbatim spans | hybrid |
| TaoChronos-Ontologist | typed historical–modern mappings (proposals only) | hybrid |
| TaoChronos-Lineage | citation / transcription / rephrasing / derivation / opposition | procedure |
| **TaoChronos-Scholar** | 治学: textual history of the focus terms over the whole store | procedure |
| TaoChronos-Evidence | evidence ledger; independent witnesses for hypotheses | hybrid |
| TaoChronos-PatternMiner | D1–D5 and lost-source clues (tool-first) | procedure |
| TaoChronos-Statistician | significance, BH correction, empirical ranks, coverage | procedure |
| TaoChronos-Evolution | concept timelines, formula family trees | procedure |
| TaoChronos-Hypothesis | hypothesis generation and revision | hybrid |
| TaoChronos-Skeptic | falsification: counter-examples, variants, homonymy, transcription dependence, coverage, statistics | hybrid |
| TaoChronos-ModernEvidence | modern evidence as context only; bridges must pass G8 | hybrid |
| TaoChronos-MetaReviewer | systemic issues and next-round recommendations | hybrid |

**Discovery tracks**

| Track | What | Demo example (computational hypotheses awaiting expert review) |
|---|---|---|
| D1 lost knowledge | associations attested before a pivot year that vanish while their concepts persist; textual testimony of changing use | the 本草纲目's own account of how 忍冬 was used "formerly … later" |
| D2 concept drift | JSD of context distributions by period, permutation tests, dominant senses | 消渴: Sui–Tang "a disease of drinking and urinating much" → Song–Jin–Yuan "three wastings" |
| D3 formula evolution | derivation trees, stable cores, additions and removals, taboo renames | 肾气丸 → 六味地黄丸 → 左/右归丸, core 地黄·山茱萸·山药; 薯蓣 → 山药 |
| D4 hidden associations | association rules (Fisher + BH), Adamic–Adar link prediction | 大便黑 ⇒ 犀角地黄汤; "渴 ⇢ 桂枝汤" rejected by the Skeptic via 伤寒论 §26 |
| D5 contradictions | contradiction / conditional / apparent (variants, homonymy) / support | 半身不遂: 金匮 wind vs 医林改错 qi deficiency; §176 表里 transposition |
| Lost sources | works cited but absent from the corpus, with date bounds | 古今录验方: cited by the 外台秘要, earlier than ~752 |

**Evidence, gates, confidence.** Every hypothesis goes through verbatim evidence → Skeptic review → narrowing
revisions (scope, sense, reading, exploratory) → gates G0–G8 (source, verbatim, collation, sense, extraction,
independent sources, time, expert, modern evidence) → a discovery score `D = w1·E + w2·N + w3·R + w4·T + w5·F − w6·A`
(always reported with its components) → a confidence vector (text, philology, semantics, extraction, cross-source,
time, statistics, modern mapping; modern biomedical validity defaults to **unknown**). Historical terms and modern
concepts are linked only by typed mappings (related / partially_overlapping / uncertain / not_equivalent); only a
human expert can declare equivalence.

### Design principles

| Principle | In the code |
|---|---|
| **Deterministic harness, stochastic intelligence** | the kernel (event sourcing, transactions, gates, stop conditions) is deterministic; models appear only in judgement roles, and their outputs pass schema validation and verbatim checks |
| **Everything is a plugin** | corpus, domain pack, retrieval, study, models, sandbox and storage are plugins; mining, statistics and study are tool-first procedures |
| **Claims, not facts** | a claim is a hyperedge "this book, this edition, this place says so", not a free-floating medical fact |
| **No forced single reading** | variant readings keep their probabilities and an uncertainty mass |
| **No medical anachronism** | typed mappings only; equivalence is an expert's decision |
| **Propose, don't commit** | agents propose changes to canonical knowledge; validators or people decide |
| **Evidence first** | nothing without verbatim evidence is written; fabricated or altered quotes are caught mechanically |
| **The harness decides when to stop** | evidence saturation, no new sources, gates passed, budget exhausted or expert needed |

## 6. Use cases

**Researchers**

- *A formula's history*: `study formula 肾气丸` → the original (崔氏八味丸 in the 金匮要略), the current composition,
  other names (桂附地黄丸/汤), dose ratios by witness, indications and modifications; `study dataset --formula 肾气丸`
  gives the witness table for statistics.
- *A drug's properties over time*: `study herb 附子` → 本经 "温, 有毒", 证类本草 "大毒", 汤液本草 "大热, 阳中之阳"; channel
  statements first appear, among the works collected, in the early-Qing 本草择要纲目 (手少阳, 足少阴, 三焦, 命门) — each change
  with its first book, date and quote.
- *A concept's historical semantics*: `study term 中风` → shares by period and trend, collocates (半身不遂 and 拘急 stand
  out in the Ming), senses; then `research … --focus 中风 --forbid 中风=脑卒中` for a falsifiable study of concept drift.
- *An edition*: `study taboo <book_id>` → taboo counts and the edition's lower bound, cross-checked with the other
  copies found by `study concordance`.
- *Schools and transmission*: `study citations` for each period's authorities; `study citations 李杲` for the reception
  of 东垣's teaching.
- *Reproducible publication*: datasets carry the corpus signature (books, passages, sources, normaliser, catalogue
  digest); the same corpus gives the same results.

**Students**

- `study cards --book 伤寒论 --anki shl.tsv`: cloze cards for every "……者，某方主之" clause of the 伤寒论, for spaced repetition;
- `study cards --formula 桂枝汤 --formula 小柴胡汤`: composition, doses, preparation, decoction, with the verse;
- `study cards --herb 柴胡 --herb 附子`: properties in the 本经 and in a later materia medica;
- `study reading 温病`: a reading path from the 素问 and 伤寒论 to the 温病条辨, each work with the reason to read it;
- `study concordance`: for a passage being read, who quoted it through the ages and how it was reworded.

## 7. Models and deployment

Offline by default: every agent has a deterministic procedure, and the study layer needs no model. Judgement roles
can use a model:

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=...
taochronos demo --profile claude   # Opus 5 (frontier) / Sonnet 5 (medium) / Haiku 4.5 (small)
```

The Claude provider enables server-side refusal fallbacks by default (`fallbacks="default"`, for Opus 5); if a model
refuses, returns output that fails schema validation, or exhausts its budget, the task falls back to the deterministic
procedure and the fallback is recorded as a Decision. OpenAI-compatible endpoints (DeepSeek, Grok, Gemini, local
vLLM/Ollama), external command subagents and Research Code Mode are supported too — see [docs/agents.md](docs/agents.md).

## 8. Evaluation and quality

`taochronos eval` runs on the demo corpus (~30 s). The gold sets were built by the authors for the demo corpus and used
during development: **regression tests, not an unbiased benchmark** (see [evals/gold/README.md](evals/gold/README.md)).

| Suite | Result |
|---|---|
| Philology | 7/7: no forced reading, uncertainty mass kept, normalised matching |
| Claims | P 0.98 · R 0.95 · F1 0.96; 100 % of extracted claims verbatim |
| Provenance | claims and evidence 100 % verbatim; mean provenance chain 7.8 levels (page/line/region/image honestly unavailable: no page images) |
| Hallucination | fabricated and one-character-altered quotes 100 % caught; genuine quotes and legitimate variant spellings accepted |
| Contradiction | 12/12 (including differential-diagnosis and inherited-text hard negatives) |
| Lineage | P 0.87 · R 0.93 (two false lineages from similar compositions) |
| Temporal | period constraints 6/6, earliest attestation 6/6, period leakage 0 |
| Anachronism | 10/10 statements, 8/8 mappings; an agent's "equivalence" blocked |
| Recovery | 4/4 crash points recover to the same scientific-state hash; parallel = serial; replay consistent |
| Time Machine (1368) | 2/3 checkable predictions hold; zero leakage |
| Source rediscovery | 素问 / 灵枢 / 伤寒论 held out in turn: 3/3 re-inferred with consistent date bounds |
| Ablations | without sense routes earliest-attestation 0.67; without sense resolution contradictions 0.83; Context OS −94 % context; without the Skeptic one false hypothesis survives |

Plus 111 unit and integration tests (`pytest`, with format samples of every source and a synthetic corpus for the
study layer, `tests/fixtures/study`) and the architecture governance check (`taochronos governance`: layering,
kernel neutrality, model-SDK isolation, agent rules). CI runs governance, tests, the quick evaluation and the demo
research on Python 3.11 and 3.12.

## 9. Architecture

```
protocol      data models (passages, claims, evidence, hypotheses, events, output schemas)
kernel        event sourcing, transactions, replay, scheduler, policy, hooks, budgets, Context OS, memory, stop, observability
capabilities  provider-neutral interfaces (LLM …)
science       D1–D5 engines, statistics, scoring, gates, provenance
verification  verbatim checks and provenance chains
tools         the tool mesh: philology · retrieval · knowledge · analytics · study · literature · validation (35 tools)
plugins       classics (corpus, store, domain pack, philology, citations, text reuse, study) · knowledge · retrieval · models · sandbox · storage …
agents        AgentSpecs, routing, the LLM loop, deterministic procedures, Code Mode, subagents
engine        the research engine (operational and scientific loops, branches, tournament, report)
```

Code asks the **capability registry** for capabilities (`corpus`, `domain`, `philology`, `lineage`, `retriever`,
`study`, `llm` …) and never imports a provider; plugins are assembled by profiles (`profiles/*.yaml`). Tools import no
plugin, and agents act only through capabilities and tools — enforced by `taochronos governance`. See
[docs/architecture.md](docs/architecture.md).

## 10. Repository layout

```
architecture-policy.yaml   layering, kernel neutrality, SDK isolation, agent rules
agents/                    16 AgentSpecs (YAML)
skills/                    SKILL.md packs (incl. source-criticism, the study method)
profiles/                  full-discovery, full-corpus, classics-basic, formula-discovery, historical-disease, claude
domains/classics/          periods, variants, lexicons, senses, modern concepts, ontology, citations, known findings,
                           and the study data: taboo.yaml, metrology.yaml, physicians.yaml, drug_families.yaml
domains/classics/script/   script and variant normalisation (OpenCC / Unihan / curated)
domains/classics/lexicon-harvested/  candidate formula and drug names harvested from the corpus (full-corpus only)
corpus/                    the demo corpus (unverified), modern evidence summaries, catalogues (catalog/) and source locks
evals/gold/                gold sets
src/taochronos/            protocol/ kernel/ capabilities/ science/ verification/ tools/ plugins/ agents/ engine/ evals/ workspace/
  plugins/classics/study/  the study layer: concordance · formulas · herbs · terms · taboo · network · metrology · learning · dataset · render
tests/                     111 tests (fixtures/: source format samples and the study corpus)
docs/                      study, architecture, agents, discovery, evaluation, data, ADRs, roadmap
```

## 11. Data and licences

- **The repository holds catalogues, lock files, domain data and code only**; transcriptions stay in the local data
  directory (`.taochronos/`, git-ignored) and are rebuilt reproducibly by `corpus fetch / unpack / ingest`.
- Licences are recorded per work in the catalogues and the store and travel with every witness: Kanripo and
  Wikisource CC BY-SA 4.0; McGill public domain; 笈成 supplied by the user — the classical texts are in the public
  domain, the punctuation and editing belong to the 笈成 editors, local research only; the web text sets declare no
  licence, local research only; Hugging Face classical-tcm-canon declares proprietary-commercial terms — local
  research only, never redistributed.
- Datasets and reports contain short quotes (≤ 120 characters) with their sources, never the texts.
- Caches (entry headings, citation network) live in `<data>/corpus/study-cache/`, keyed by a digest of the store,
  the normaliser and the book records; they are rebuilt when the corpus changes.

## 12. Limitations

- The corpus is not collated by this project: the Siku texts carry Qing deletions and taboo changes and are segmented
  by rule; 笈成 transcriptions vary in quality; dating without curation relies on book metadata and signed prefaces,
  and undatable works can only be dated "Qing or earlier".
- The study layer and the extractors are rule-based machine reading: compositions, drug entries and properties are
  read with patterns and a lexicon, so a missing name leaves a composition incomplete; single-witness groups (孤例) and
  unusual layouts need checking by hand. Every output quotes what it read.
- Notes of annotated classics that are not separated into layers take the date of the text; citations anachronistic
  for that date are detected and set aside, others (孙星衍's notes in the 本经 citing the 说文) are not.
- Metrology values, taboo start years and physicians' dates are sourced scholarly positions, open to dispute, in
  reviewable YAML; taboo evidence bounds an edition's date and is indicative only.
- Deduplication by textual overlap cannot draw an absolute line between two transcriptions of one edition and two
  editions; every copy judgement is recorded and can be overturned.
- The demo corpus is small (23 books, 131 excerpts): evaluation numbers are illustrative; the Time Machine and link
  prediction need a large corpus to be statistically meaningful.
- The system gives no medical advice; any research result is a lead until an expert (Gate G7) has reviewed it.

## 13. Roadmap and citation

See [docs/roadmap.md](docs/roadmap.md): expert-built lexicons, senses and gold sets; gold sets for formula parsing and
property extraction; page images and OCR; a segmentation model for unpunctuated text; cross-witness collation and a
variant-reading dataset; more model providers and a human-in-the-loop review interface.

When citing TaoChronos, cite the sources of the corpus you used (Kanseki Repository, 笈成, McGill University Library,
Wikisource …) with their licences, and the corpus signature (given by `study dataset` and in every Discovery Report):

```
TaoChronos: a provenance-grounded research harness for the Chinese medical classics.
https://github.com/psknlr/TaoChronos
```
