# TaoChronos · 道乃久

**A provenance-grounded research harness for the Chinese medical classics — for scholars, students and discovery.**
The agent **道乃久** (Dào nǎi jiǔ; model **Tao-R1**) is **published by 医哲未来人工智能研究院 (IMPF-AI)**.
*面向中医古籍的可溯源知识发现与治学系统*

**[Use it online · web chat](https://chat.impf.ai/)** · [中文 README](README.md) · [Web client](docs/web.md) · [V2](docs/v2.md) · [Ancient–modern bridge](docs/bridge.md) · [Models](docs/models.md) · [Study layer](docs/study.md) · [Task specification](docs/tasks.md) ·
[Architecture](docs/architecture.md) · [Agents](docs/agents.md) · [Discovery](docs/discovery.md) · [Evaluation](docs/evals.md) · [Data](docs/data.md) · [Roadmap](docs/roadmap.md) · [ADRs](docs/adr/)

TaoChronos turns 966 Chinese medical classics (about 123 million characters in 2.05 million passages) into a corpus
that can be searched, dated and cited, and offers two layers on top of it:

- **Study (治学)** answers the questions scholars and students ask of the literature every day, the way the 考据
  tradition answers them: where does this passage recur and how do the witnesses differ (concordance with a
  collation apparatus); what was a formula's original composition and what became of it (formula provenance); when
  was a drug first said to enter a channel (materia-medica history); when does a term rise and fall, and what did it
  mean (term history); which edition is this, judging by its taboo characters (taboo dating); whom did each period
  cite (citation network) — plus study cards, reading paths and research datasets.
- **Deep discovery 2.0 (深层发现)** reads the structure of the literature itself: **stemmata** (multi-witness collation,
  a tree of the witnesses, shared readings and contamination), **semantic reuse and transmission** (quotation,
  abridgement, summary, paraphrase, reinterpretation, quotation in order to refute … and a work's reception period by
  period), **textual strata** (style layers, dating evidence, authorship), **case-record trajectories**, **argument
  graphs**, **sense evolution** (dated shifts and candidate senses) and **lost-work reconstruction** (辑佚). The seven
  are deterministic capabilities in the tool mesh, called by the existing agents — no agent was added — and what
  proposes never proves: every label carries the rule that fired and the values it read.
- **Task specification v1.0** ([docs/tasks.md](docs/tasks.md), in Chinese) sets out the 27 tasks of a roadmap for
  computational philology and knowledge discovery on the Chinese medical classics (L0 digitisation → L1 句读 and
  structure → L2 semantic knowledge → L3 digital 考据 → L4 knowledge discovery → L5 research agent), each as input,
  output JSON Schema, tools and agents, method, evaluation, gold set and human review, and fills the gaps: **句读**
  (punctuation that never changes a character), **clause structure**, **glosses (训诂)**, **commentaries compared**,
  **disputes**, **variant impact**, **drug pairs**, **the formula–finding network**, **schools**, **names** and
  **transmission chains**.
- **V2: verifiable discovery and ancient–modern translation** ([docs/v2.md](docs/v2.md)). **Rules screen, a model
  judges**: every capability runs on rules; a model (LiteLLM, MiniMax's mainland platform, Poe, DeepSeek, Qwen, Kimi,
  GLM, Doubao, Claude …) adjudicates only what the rules leave uncertain, adds what they missed as exact spans of the
  text, writes cited summaries, and in several places may lower a result but never raise it.  On top: layout and page
  reading (T1–T2), contextual NER in 24 types (T7), a five-layer text with grounded translation (T10), places (T27); the
  **Ancient–Modern Bridge** (ancient phenotypes → HPO with typed relations → 64 modern disease profiles, qualitative
  levels, never probabilities — **phenotypic similarity, not retrospective diagnosis** — and back from a modern disease);
  a **six-layer evidence graph** whose every edge says who asserts it; an **evidence audit** (claims decomposed and
  checked by kind, five verdicts); **modern evidence** typed by design and population (animal work and network
  pharmacology never count as efficacy in people) and **real-world data** (question → study spec → a checked OMOP query;
  a model never writes SQL); **fifteen skill manifests, four core agents, a workflow compiler and a resumable
  executor** (`taochronos ask "…"`).
- **Research** turns a question into a replayable, auditable, falsifiable process: the research director
  **TaoChronos** dispatches 16 specialist agents — research contract → evidence foundation → pattern mining →
  hypotheses → falsification → gates G0–G8 → expert review.  The contract is **executable**: a run whose tasks are
  done has only finished executing — whether the research is accepted is a validator's verdict, criterion by criterion
  (`research_accepted` / `needs_expert` / `inconclusive` / `budget_exhausted`).  A true quote is not a true reading
  (every claim must be *stated* by its quote), a model's proposal is not a verdict, and an internal score is not
  external evidence ([ADR 0009](docs/adr/0009-boundaries-contract-and-evaluation-layers.md)); arguments from silence
  ("lost", "hidden") are tested against what the whole scope states, and research value is measured blind on the full
  corpus against baselines ([ADR 0010](docs/adr/0010-speed-cruxes-and-research-value.md)).

Both layers share one rule: **every statement rests on verbatim witnesses** (book, volume·chapter·section, date,
text layer, source and licence of the transcription). Rule-based reading is labelled as machine reading; people check
and decide.

> 💬 **Web chat · 道乃久**: open **<https://chat.impf.ai/>** and talk with **道乃久** (TaoChronos; model Tao-R1; published by
> IMPF-AI).  Ask at once: **道乃久默认服务** (MiniMax-M3 through IMPF-AI's [relay](relay/README.md); no key needed; during the test
> period conversations are recorded for visitors who agree).  Or choose the underlying model and paste your own API key in the
> settings (DeepSeek, Qwen, Kimi, GLM, Doubao, SiliconFlow, OpenRouter, Poe, LiteLLM, Claude and others are
> listed; any other endpoint can be set by hand under **自定义 API** — address, model, key, headers) and hold a multi-turn
> conversation as in ChatGPT or Claude.  The model answers through all 79 of TaoChronos's tools, and the page checks every
> `[[passage_id]]` it cites word for word (✓ matches the passage · ≠ misquoted · ✕ no such passage); evidence, research runs
> and a tool console (any tool, no model needed) sit in the side panel.  In the browser TaoChronos runs with Pyodide on the
> **要籍语料**: 533 of the **535 key works** ranked by how the tradition cited them ([list](corpus/catalog/canon.yaml))
> (553 witnesses, 10.5 million characters; the first classics whole, the 素问, 灵枢, 伤寒论 and 金匮 with two or three
> witnesses to collate, the others in chapters; [sources and terms](corpus/web/ATTRIBUTION.md)), kept in the browser after the
> first visit so that it opens again in seconds.  For **all the books**, build the full corpus and
> run `taochronos serve`, then connect under Settings → 运行环境 in one step (the browser remembers it; a server on another
> machine is reached with its access token).  See [docs/web.md](docs/web.md).

> ⚠️ The corpus consists of transcriptions from several sources (Siku, 笈成, McGill rare books, CMETA, the 東亜医学協会,
> Wikisource, web text sets), **none collated by this project**; `corpus/demo` holds unverified excerpts for demonstrating the method.
> Contemporary publications and works of contemporary physicians are left out; in the modern editions kept, the editors'
> work is a layer of its own or metadata. All outputs
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
| **句读 and 训诂** | punctuation of 白文 learned from the editors' punctuated texts (marks inserted, every character kept); the parts of a clause (condition, disease, findings, pulse, pattern, principle, contraindication, formula, composition, preparation, administration, modification, prognosis); the glosses of a word in the commentators' set forms (…者…也, 貌, 音, 反切, 读为, 当作, 一作, 通), with who gave each first | `study punctuate` · `study clause` · `study glosses` |
| **Commentators and schools** | the commentaries on a clause aligned and compared (照录, 承袭, 同解, 增益, 异解, 驳, 从); disputes (who rejects whom, on what, and who reports it); schools (the words, drugs, formulas and citations a school uses more than the other works of its time); names (a drug's names, the change of its preferred name, names the lexicon lacks) | `study commentaries` · `study disputes` · `study schools` · `study names` |
| **Historians of formulas, materia medica and medicine** | formula provenance (original and current compositions, 加减, 同名异方, 同方异名, dose ratios, doses in the measures of their period, indications, verses); drug-property histories (flavour, toxicity, 归经, 升降浮沉 — first statements and changes); term histories (shares by period with intervals, trend test, first attestations, collocates, senses); drug pairs (NPMI, Fisher with Benjamini–Hochberg, groups of drugs) and the formula–finding network | `study formula` · `study herb` · `study term` · `study pairs` · `study network` |
| **Herb and formula research** | formulas compared drug by drug (original or current witness: drugs, doses, ratios, dose-weighted overlap; 同方 / 同药异量 / 加减化裁 / 异方); the formulas made from a base (加味, 减味, 加减, 同药异量, 合方); a drug's use through the periods (share of compositions with a trend test, decoction doses by period, pills, powders and 煮散 apart, the largest-dose clue, preparation, partners); the 本草's natures, flavours and channels of several drugs side by side; 十八反 and 十九畏 in the texts (statements, verses, formulas that still write a pair) | `study compare` · `study family` · `study usage` · `study properties` · `study incompat` |
| **Research design** | a question turned into a protocol: kinds and objects, falsifiable hypotheses (prediction, test, refutation, rivals), scope and the works to read first, operational variables, methods (each a tool with a command to rerun it), analysis, figures, quality, limitations, ethics, timeline and a research contract — with a pilot run that says whether the corpus holds enough | `study protocol` |
| **Scientific charts** | results carry chart specifications (lines with interval bands, grouped bars, horizontal bars, stacks, heatmaps, Tukey box plots, forest plots, scatters with LOESS, cluster dendrograms, timelines, networks): drawn on the page with hover and keyboard read-outs and a table view; exported in a journal's style (85 or 175 mm wide, SVG, PNG and TIFF at 300 or 600 dpi, numbered with a caption) and several as one figure in panels; written by the CLI as journal SVG, CSV and JSON | `--charts DIR` · [web](docs/web.md#图表--charts-and-their-downloads) |
| **Three-line tables** | results carry numbered three-line tables: grouped heads; n (%), M (P25, P75), x̄ ± s, 95% CI, OR (95% CI) and P as journals write them, the notes naming the abbreviations and tests (Kruskal–Wallis, Spearman, Fisher + BH); copied into Word or Excel in one click, downloaded as Word (.docx), LaTeX (booktabs), CSV or Markdown; an answer's Markdown tables shown the same way | `--charts DIR` · [web](docs/web.md#图表--charts-and-their-downloads) |
| **Researchers who need data** | open tables with provenance, dates and licences (Frictionless data packages) for statistics and visualisation | `study dataset` |
| **Students** | cloze cards for 方证, compositions (with verses), drug properties and key passages, exported to Anki; reading paths from the source classics to the Republican syntheses | `study cards` · `study reading` |
| **Textual critics** | multi-witness collation into variant units (异文, 脱, 衍, 倒, lacunae, structural differences, orthographic variants) graded by impact (doses, negations, drugs first), a neighbour-joining stemma, groups of shared readings and contamination, one witness against the others, a TEI apparatus; the transmission chain of a passage (shared innovations); a work's witnesses — the transcriptions in the store with their editions, holders and page images, and the prints and manuscripts digitised by libraries with shelfmarks, IIIF manifests and terms | `study variants` · `study stemma` · `study edition` · `study tei` · `study witnesses` · `study chain` |
| **Intellectual historians** | what later books did with a passage (直接引用, 近似转录, 节略, 撮要, 转述, 解释性改写, 引而驳之, 套语相似), each with its rule and values; a work's reception by period and its channels | `study reuse` · `study transmission` |
| **Dating and authorship** | style layers of a work's chapters (permutation-tested), change points and outlying chapters; cited works, late vocabulary and taboo per chapter; Burrows' Delta attribution | `study layers` · `study dating` · `study authorship` |
| **Historians of clinical practice** | case records read visit by visit (findings, diagnosis, principle, formula and doses, changes, doses taken, response, outcome); treatment sequences, transitions and associations with outcome (never evidence of efficacy) | `study cases` · `study trajectories` |
| **Readers of medical reasoning and language** | argument graphs (condition, inference, cause, contrast, analogy, rebuttal, definition, treatment) and the comparison of two works' ways of reasoning; sense shares by period, change points and candidate senses | `study argument` · `study senses` |
| **Reconstruction of lost works** | fragments gathered from the books that quote a lost work, ordered by the volumes the source notes give; the method verified on surviving works, with a reliability per quoting book | `study fragments` |
| **Ask (V2)** | a question compiled into a workflow of skills (S01 sources → … → S15 audit), run by four core agents under their own permissions, every step an artifact of a resumable workspace, every statement of the answer audited | `ask` · `skills` |
| **Ancient–modern translation** | the AncientPhenotypePacket (negated, optional, conditional, after treatment, prognosis, modifiers, course, population, historical names with their senses); HPO projections with relation types; modern profiles with qualitative levels, discriminators and name relations; from a modern disease back to the passages | `bridge phenotype` · `bridge map` · `bridge reverse` · `bridge verify` |
| **Audit and evidence graph** | claims decomposed and checked by kind (verbatim quotes, glosses, presentism, evidence level, inference leaps, clinical advice); the six-layer evidence graph and lineage | `audit` · `graph` |
| **Modern evidence and real-world data** | PubMed typed by design and population, the cross-level guard, safety warnings; real-world questions as validated study specs over OMOP | `modern search` · `modern safety` · `rwd ask` · `rwd synth` |
| **Layout, entities, translation, places** | vertical reading order and 双行小注, a multimodal reading, OCR checked against the store; entities in context; five-layer translation; native places, signed prefaces, regional statistics | `vision` · `study entities` · `study translate` · `study places` |
| **Knowledge discovery** | multi-agent research: lost knowledge, concept drift, formula evolution, hidden associations, contradictions, lost sources; verbatim evidence, falsification, gates, expert review | `research` · `report` · `workspace` · `review` |
| **Your own data** | upload your own data (a clinic's prescriptions, case records, a survey, notes: CSV, Excel, Word, TXT, JSON) for 道乃久 to analyse: read on your machine (in the browser or by a server on it — never by the site's servers), made anonymous as it is read (names and doctors to pseudonyms, identity and record numbers to codes, telephones and addresses removed), conversations touching it never recorded; descriptive statistics, group comparisons (Kruskal–Wallis, χ² / Fisher, Spearman), prescription mining (frequent drugs, doses, pairs by Fisher + BH, rules, clusters, groups compared, the nearest compositions of the classics with their witnesses), with figures and three-line tables, the rows it cites checked like any citation | [web](docs/web.md#我的资料--the-users-own-data) · [notes](docs/mydata.md) |
| **Everyone (web)** | a ChatGPT/Claude-style multi-turn chat: the default service with no key (MiniMax-M3) or a model of your choice answers through every tool, quotations checked word for word, sources one click away (horizontal or vertical reading); a research panel and a tool console; conversations kept in your browser, exportable | [web](https://chat.impf.ai/) · `serve` · `web build` |
| **Developers** | plugin kernel, capability registry, a tool mesh of 79 tools, agents as YAML specs, event sourcing and replay, evaluation and architecture governance; the JSON Schemas of the tasks' outputs | `agents` · `eval` · `governance` · `schema --study` |

## 2. Quick start

**Web**: open <https://chat.impf.ai/> (HTTPS, on Cloudflare: the tools search the full corpus, 958 books, on the site's own
server, and run the 要籍语料 in the browser when it cannot answer; the default service needs no key; deployment in
[cloud/](cloud/README.md)), or bring the full corpus you built into it on your machine:

```bash
pip install -e .
taochronos serve                   # http://localhost:8765 — web chat + the full corpus (when built) + the model proxy; connect under 设置 → 运行环境
taochronos serve --env-keys        # model keys from this machine's environment (MINIMAX_API_KEY …), none typed in the page
taochronos serve --host 0.0.0.0    # for other machines: prints an access token and the address carrying it (or --token / TAOCHRONOS_TOKEN)
taochronos web build -o _site      # the static site (Cloudflare: .github/workflows/site.yml; the GitHub Pages mirror: pages.yml)
taochronos web store               # the full corpus the site's server carries (cloud/store.json); taochronos web upload sends it
```

**Command line**:

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
taochronos corpus fetch cmeta && taochronos corpus catalog cmeta && taochronos corpus ingest cmeta   # CMETA's collated editions
taochronos corpus images all --enrich                                    # image witnesses: library records and IIIF manifests (metadata only)
taochronos corpus status
```

Other names of a drug (the alias layer, [ADR 0023](docs/adr/0023-alias-layer.md); the shipped layer is committed, these
rebuild and inspect it, and bring in the lists that may not be published):

```bash
taochronos aliases show 国老 --profile web-canon     # a name's record: its drugs, kinds, statuses, witnesses, and what a search adds
taochronos aliases build && taochronos aliases check --db .taochronos/corpus/tcm.sqlite   # rebuild on the store; same inputs, same bytes
taochronos aliases import ntu ChineseDrugEthnonymsSynonymyTable.tab   # local only: also `import hurb FILE`, `import bielu-gb FILE`
taochronos aliases build --local                     # the shipped records + the local lists → .taochronos/aliases/local/;
                                                     # also rewrites the shipped layer from the store (--db; --out-dir DIR leaves it)
taochronos research "…" --profile full-corpus-local  # research with the local lists, on this machine only
taochronos eval aliases --quick                      # the alias eval's synthetic part (without --quick, on a store: all of it)
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

Deep discovery 2.0:

```bash
taochronos study stemma 伤寒论                                      # variant units, the stemma, groups, contamination
taochronos study tei 伤寒论 -o shanghan.tei.xml                     # a TEI P5 apparatus
taochronos study witnesses 伤寒论                                   # the transcriptions and the digitised prints and manuscripts
taochronos study reuse "太陽之為病，脈浮，頭項強痛而惡寒"            # typed reuses of a passage across the corpus
taochronos study transmission 伤寒论                                # a work's reception by period, and its channels
taochronos study layers 素问                                        # style layers, change points, outlying chapters
taochronos study dating 素问                                        # dating evidence chapter by chapter
taochronos study authorship --book 伤寒论 --chapter-name 辨脉法 --candidate 脉经 --candidate 金匮要略
taochronos study cases 风温                                         # case records visit by visit (or --book <id>)
taochronos study trajectories 咳嗽                                  # sequences, transitions, associations with outcome
taochronos study argument --work 伤寒论 --against-work 温热论        # two ways of reasoning (or a text / --passage)
taochronos study senses 消渴                                        # senses by period, change points, candidate senses
taochronos study fragments 小品方                                   # 辑佚 (--verify: test the method on a surviving work)
```

V2 (rules first; a model reviews when `--llm` is given):

```bash
taochronos ask "消渴的概念如何随时代演变？与现代糖尿病有何异同？"          # compile → run → an audited answer (resumable workspace)
taochronos ask "…" --plan-only                                           # the compiled DAG of skills
taochronos bridge map --passage jinkui.13.xiaoke1                        # candidates, levels, discriminators, name relations
taochronos bridge reverse E11                                            # from a modern disease to passages and names, by period
taochronos audit "《金匮要略》载「男子消渴，小便反多」，所以肾气丸可以治疗糖尿病。"   # SUPPORTED quote + an inference leap
taochronos graph --passage jinkui.13.xiaoke1 --graphml xiaoke.graphml    # the six-layer evidence graph
taochronos modern search 黄连 --disease diabetes_mellitus --online       # PubMed typed by design (and population)
taochronos rwd ask "2型糖尿病患者中，使用黄连素与糖尿病肾病的关系"         # real-world data (a synthetic OMOP database by default)
taochronos study entities --input clause.txt --llm minimax:MiniMax-M2.7  # NER: rules, then MiniMax (mainland) reviews
taochronos llm presets                                                   # the platforms and their key variables
```

Research:

```bash
taochronos research "肾气丸的组成与主治如何随时代演变？" --profile full-corpus --focus 肾气丸,六味地黄丸 --forbid 消渴=糖尿病
taochronos report <session>        # the 12-section Discovery Report (with a Sources Dossier appendix under full-corpus)
taochronos workspace <session>     # the offline HTML Discovery Workspace
taochronos review <session> <hypothesis> --approve --expert <name>   # Gate G7: only a person can pass it
taochronos eval                    # all TaoChronos-Eval suites (~2 min)
taochronos governance              # architecture policy check
```

## 3. Corpus

| Source | Licence | Ingested | Notes |
|---|---|---|---|
| Kanseki Repository KR3e, *Siku quanshu* medical works | CC BY-SA 4.0 | **100 works**, 25.7 M characters | unpunctuated Siku / Sibu congkan texts; a curated catalogue with authors, dates, schools, editions and layer dating |
| 笈成 (JiCheng) v1.4.8 | CC0 1.0 (the editing); the site's own writing CC BY 4.0; texts public domain | **816 works** (857 less 41), ~93.6 M characters | archive supplied by the user; punctuated by its editors; headings, prescription blocks, commentaries, collation remarks and missing characters parsed from the markup |
| McGill University Library rare gynaecology books | public domain | **5 works** | Qing prints and manuscripts, unpunctuated |
| 數位中醫校書郎 CMETA (collated editions) | CC BY 4.0 (the collation); texts public domain | **11 works**, 1.45 M characters | collated page by page against the images: 伤寒论 (赵开美本: the 台北故宫 copy and the 安政 reprint; 康平本; 康治本), 金匮 (吴迁本, 邓珍本), 素问 (顾从德本), 灵枢 (赵府居敬堂本), 古今医案按, 名医类案, and the 桂林古本 伤寒杂病论 (米伯让's 1980 printing from the 白云阁 blocks, dated by its appearance, 1939); passages carry their page and, where the site shows the images to guests, the page image |
| 東亜医学協会 · 医学古典テキスト | © the association, local research only | **7 works**, 0.32 M characters | 素问, 灵枢, 难经, 伤寒论, 金匮要略, 神农本草经, 扁鹊仓公列传, each from a named base edition |
| Wikisource Category:中醫 and Category:醫書 (from the Wikimedia dumps) | CC BY-SA 4.0 | **18 works** (new of 627) | 天回医简, 五十二病方, three Republican "ancient" editions of the 伤寒杂病论, 东医宝鉴, the Korean 医方类聚 (1445), 医理真传 (唐步祺's explicated edition, his commentary a layer of its own) … |
| TCM-Ancient-Books / tcmoc | undeclared by the repositories, local research only | **8** / 0 works | mostly simplified copies of 笈成 texts, deduplicated work by work (a copy of a 笈成 text is not stored) |
| Hugging Face classical-tcm-canon | proprietary-commercial, local research only, never redistributed | **1 work** | 张志聪's 伤寒论宗印·集注 |
| KR-Catalog (Kanripo catalogue) | CC BY-SA 4.0 | catalogue | roles and dates of 132 persons responsible for the Siku works |
| Image witnesses: NIJL (研医会; the 富士川文庫 of Keio and Kyoto; the University of Tokyo incl. the 鶚軒文庫; Kyushu; Tohoku), Staatsbibliothek zu Berlin (Sammlung Unschuld), Library of Congress (Chinese Rare Books), Waseda, the NDL Digital Collections | per record, as each holder states | **10,001 records** (787 linked to 179 works) | records only — title, date, print or manuscript, holder, shelfmark, IIIF manifest, terms — linked to the works of the store by title; no image downloaded |

In all **966 works, ~123 million characters, 2.05 million passages**.

- **Admission**: historical texts only. Contemporary publications and contemporary physicians' works are excluded after
  review (`corpus/catalog/exclusions.yaml`, automatic screening for the rest); Republican works (1912–1949) stay as
  historical sources. The modern editions were reviewed again and kept — the reconstructions of ten lost books (吴普本草,
  本草经集注, 新修本草, 食疗本草, 海药本草, 本草图经, 名医别录, 集验方, 小品方, a 神农本草经) and nine old books in annotated,
  explicated or translated editions (重订通俗伤寒论, 伤寒恒论, 医理真传, 六因条辨, 万氏秘传片玉心书, 许氏医案, 湖岳村叟医案,
  妇人寿草, 傅青主男科重编考释) — with 吴棹仙's 子午流注说难 (1956): the old text is the main layer, dated as the book; the
  editors' notes, commentary and insertions are layers of their own, dated by the edition; their source references,
  sigla, note calls and converted doses leave the text for the passage's metadata
  ([ADR 0007](docs/adr/0007-modern-apparatus-as-layers.md)). Texts that surfaced in
  modern times under an ancient name (the 桂林古本 伤寒杂病论, the 辅行诀脏腑用药法要, like the Republican 长沙古本 and
  康平本) are not treated as modern publications: they are kept as sources of the time they appeared, dated by their
  appearance and marked pseudepigraphic or disputed — never dated by the age they claim.
- **Deduplication**: sources are ranked by reliability (Siku → 笈成 → McGill → CMETA → 東亜医学協会 → Wikisource → web
  sets); each candidate is compared with what is already in by 12-character shingles of normalised text, and copies are
  recorded with the book they duplicate and the overlap; McGill's, CMETA's and the 東亜医学協会's texts are independent
  witnesses, whose closest books are recorded but never judged.
- **Dating**: curated overrides → the Siku catalogue → western years, reign eras and dynasties in the book metadata →
  signed prefaces → other transcriptions of the work → the author's other works; commentaries, editorial notes, added
  chapters and appended prescriptions are dated as layers of their own (王冰注 762, 新校正 1068, the layers of the 证类本草 …);
  inseparable layers are dated by the latest. Undatable works count as Qing, never earlier. Layers from 1950 on (the
  editors' work, contemporary writings) carry the dynasty label 当代 and belong to no analysis period.
- **Normalisation for matching only**: OpenCC script conversion + Unihan variants + curated medical variants, length-
  preserving; the text is never altered. Unpunctuated Siku text is read through a machine-segmented view whose spans
  map back to the source.
- **Search**: a SQLite store with a character-bigram FTS5 index (terms of any length, phrases, proximity); research
  samples a period-stratified frame, falsification queries the whole store.
- **Other names of a drug** (the alias layer, `domains/classics/aliases/`, [ADR 0023](docs/adr/0023-alias-layer.md)):
  a search for 甘草 also finds the passages that write 国老, for 木通 those that write 通草 before about 960 — in at
  most 3 of 10 places, each labelled with the name, the drug, the kind (异名, 避讳改名, 古名 …), the source and a
  witness passage, while the name asked keeps the others.  A name two drugs share (鬼督邮) lists both and is never
  merged; a common word (小便, 将军之官) is not taken for a drug; a name used only in some periods is searched only
  there, and a passage written before a name came into use is flagged.  Built from the CC0 本草纲目别名录 in the
  store, the editors' decisions and equations read off the texts, each with its witness — a layer of its own beside
  the lexicon, which it leaves unchanged.  On in all three runtimes: the browser (web-canon), the full-corpus server
  and the D1 backup, whose port of it the parity tests hold to Python's (the eval's full-corpus numbers are still
  measured on the web store as a proxy).

See [docs/data.md](docs/data.md) and [ADR 0003](docs/adr/0003-corpus-store-and-scoped-research.md).

### The 535 key works, and the corpus of the web client

- **要籍** (`taochronos study canon --write-catalog` → [`corpus/catalog/canon.yaml`](corpus/catalog/canon.yaml), metadata only):
  the 759 medical works ranked by the citation network of the whole store; the first 535 are listed (`CANON_SIZE`; 350
  until October 2026).  The ranking is total, so the longer list extends the shorter: ranks 1–350 are the list ranked on
  the full corpus, unchanged; ranks 351–535 were appended by the `canon` workflow (`.github/workflows/canon.yml`: `taochronos
  web canon --extend`) on the site's corpus parts — which hold no source whose terms forbid passing it on, 757 works ranked
  there — and the browser's corpus and the D1 backup's tables were made again with them.  score =
  10·log₂(1 + distinct works citing it, not older than it) + 2·periods citing it + 2·log₂(1 + citations) +
  3·log₂(1 + witnesses) + 6·in the 四库全书.  The 素问, 灵枢, 金匮, 难经, 伤寒论, 神农本草经, 千金要方, 脉经, 甲乙经 and
  外台秘要 lead; each of the first 350 is cited by at least two later works, and past them citations thin out (161 of ranks
  351–535 are cited by fewer than two), so the order there rests more on witnesses, volume and the 四库; the 185 added are
  mostly Qing (122) and Ming (34).  It reads what this corpus quotes — late works have had
  less time to be cited, lost works are not in it.  The `classics.canon` tool queries the list in any corpus and says
  whether the current one holds each work's text.
- **要籍语料** (`taochronos web pack` → [`corpus/web/`](corpus/web/ATTRIBUTION.md)): **533 of the 535** (553 witnesses,
  168 000 passages, 10.5 million characters): the best witness of each (the openly licensed first — CMETA's collated
  editions, Kanripo, Wikisource, McGill, 笈成, which give 529 of the works — then the web text sets transcribed from 笈成;
  the most complete within a source), up to three for the first ten, whole within 350 000 characters; the others by rank
  within 50 000 / 25 000 / 12 000 characters (all 185 added: 12 000), as whole chapters spread through the book; passage ids as in the full
  corpus.  The two known only through sources that forbid passing their texts on are listed without text.  The site
  ships the store xz-compressed without its full-text index (13.3 MB); the browser unpacks it as it downloads, indexes
  the first 40 works before it answers and the rest in the background, and keeps the result in IndexedDB
  ([ADR 0013](docs/adr/0013-canon-corpus-in-the-browser.md)).

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

### Deep discovery 2.0: the structure of the literature

The nine functions above answer questions about one formula, drug or term; seven capabilities read the structure of the
literature itself ([docs/study.md](docs/study.md#深层发现-20--the-structure-of-the-literature),
[ADR 0005](docs/adr/0005-deep-discovery-capabilities.md)). Three rules:

- **Capabilities, not agents.** Each is a deterministic function of the study layer, a tool of the tool mesh
  (`study.variants` … `study.fragments`, permission `classics:read`) and a CLI command. The existing agents call them:
  the Philologist (collation, layers, dating, authorship), the Skeptic (reuse, dating, argument), the Evidence agent
  (cases, trajectories, argument), the Semanticist and the Scholar (senses); lineage edges carry their reuse type. No
  agent was added.
- **Candidates are not proof.** Character probes, co-occurring concepts, clusters and encoder similarities only
  propose. Transparent rules over measured features decide, and every label carries the rule that fired and the
  values it read; an encoder's similarity is reported and read by no rule.
- **Measured before trusted.** Each capability has an eval suite: synthetic data with a known answer where one can be
  built, a development set where the rules need examples, and a check on the real corpus where the literature holds a
  result.

| Capability | What it does | Full-corpus example (machine reading, with quotes to check) |
|---|---|---|
| **Stemma** `study variants` · `stemma` · `edition` · `tei` · `witnesses` | anchored alignment of whole works; edits merged into variant units (omissions of 40+ characters are lacunae, not disagreement; long additions such as commentary are structural and never group witnesses); a neighbour-joining tree; minority readings shared by several witnesses group them (agreement in error), and groups the tree cannot hold flag contamination; the base is a coordinate system, not a judgement; `witnesses` lists the transcriptions and the digitised prints and manuscripts | 伤寒论, nine witnesses (two 笈成 texts; three transcriptions of the 赵开美本 — CMETA's 台北故宫 copy and 安政 reprint, the 東亜医学協会 text —; the 康平本; two 注解伤寒论; 张卿子本; the 康治本, fifty formulas, overlaps 0.034 and is set aside): 2 055 variant units; tree ((张卿子, (the two 注解)), (康平本, ((the 笈成 pair), (東亜医学協会, (故宫, 安政))))) — the 成无己 commentary tradition against the plain texts, the 康平本 on a long branch, the three 赵开美本 transcriptions together (38 shared readings); the 康平本 shares 118 units with the commentary tradition; 张卿子本 flagged as contaminated from one 注解 (share 0.29). The 宋本 as printed gives no name line before a prescription (「……可與麻黄杏仁甘草石膏湯。方二十六。」, then the composition); 笈成 and the 東亜医学協会 supply one (the latter marks it ※) — editorial practice, not descent |
| **Reuse and transmission** `study reuse` · `transmission` | two stages: probes and co-occurring concepts propose candidates; rules over coverage, runs, rarity-weighted content, specificity (an E-value), order, length ratio, stock phrasing and citation / refutation / explanation markers decide one of eight types and 明引 / 暗引; a work's reception by period (retained, transformed, disputed) and its channels | 「太阳之为病……」: 446 candidates in 4 s — 66 直接引用, 12 近似转录, 19 节略, 96 转述, 32 解释性改写; 111 found only through their concepts. 局方发挥 quotes 「阴平阳秘」 to refute it (未必); 医学正传 (岂可) and 证治准绳 (误矣) refute 「邪之所凑」. The retained share of the 伤寒论's reuse rises from 53 % (Wei–Jin) to 76 % (Ming) and 90 % (Republic); channels such as 脉经 → 千金翼方 |
| **Strata** `study layers` · `dating` · `authorship` | chapters profiled by the √-frequencies of their most frequent characters, split by k-means and tested by permutation, with membership probabilities; change points by scan statistic and binary segmentation (BH); outlying chapters by Burrows' Delta; per chapter the works cited in the main text, late vocabulary (first used elsewhere 300+ years later, z-scored within the work) and taboo | 素问: the minor layer holds **all seven 运气 chapters** (and four others), marked by 化↑ 火↑ 太↑ 脉↓, p = 0.025; the strongest change point at 65 \| 66 and another at 74 \| 75 — where the seven begin and end (both p = 0.005; weaker ones elsewhere); late vocabulary flags 至真要大论 (z = 4.26), 五常政大论, 六元正纪大论. In the 伤寒论, 辨脉法 and 平脉法 are nearest the 脉经 (the 王叔和 tradition) |
| **Case records** `study cases` · `trajectories` | cases and visits cut sentence by sentence (二诊, 又, dates, 次日, 前方加减); per visit the findings, diagnosis, principle, formula and doses, changes, doses taken and response; PrefixSpan patterns, transitions, Fisher + BH associations with outcome — **records written and selected by physicians: never evidence of efficacy** | 吴鞠通医案, two transcriptions read independently: 285 / 290 cases (counts agree 0.98, outcomes 0.92); 续名医类案 3 246 cases (151 deaths); 咳嗽 818 cases; 中风 287, with sequences such as 苦寒 → 下法 and 益气 → 地黄饮 |
| **Argument** `study argument` | clauses (split before an inner 则 / 故) linked by typed, directed edges from a marker table: condition, consequence, cause / effect, inference, support, contrast, analogy, rebuttal, definition, treatment; only explicit markers; a work's profile and two works compared (JSD, log-odds) | 伤寒论 vs 温热论: JSD 0.063 over relations; the 伤寒论 defines and infers, the 温热论 argues by analogy (7.76 per 1 000 clauses against none) and rebuttal, with more conditions and treatments |
| **Senses** `study senses` | occurrences sampled by period and labelled by curated cues and anti-cues; unlabelled contexts clustered into **candidate senses** (distinctive words and examples, for a person to name); recursive change points of the sense shares (permutation tests); the term's neighbourhood period by period | 消渴: change points near 166 (p = 0.025), 388 (0.005) and 1603 (0.005); the symptom sense falls from 21 % to 0–6 % and returns to 11–13 % in the Qing and the Republic |
| **Lost works** `study fragments` | 外台-style attributions (小品论曰 … （出第十卷中千金同）), 又 continuations, 《…》云; text up to the source note or the next source; volumes and parallels kept, repeats merged, ordered by volume; quoting books older than the work excluded; verified on surviving works, with a reliability per quoting book | 小品方: 132 fragments from 190 quotations, 90 of them in its modern 辑校本 (now in the store). Verification on the 千金要方: 0.32 of its fragments in the surviving text (幼幼新书 0.83, 外台 0.55, 医心方 0.36), covering 12 %; 87.6 % of the 肘后备急方's quotations are not in the extant, reworked 肘后 — candidate lost text |

The examples of both tables were computed on the 926 works of the 2.0 store; the 20 transcriptions added in this
release (CMETA, the 東亜医学協会, 医方类聚, 辅行诀 …) change some counts slightly, and the stemma row has been recomputed on
the current store.

### Task specification v1.0: from 句读 to schools

[docs/tasks.md](docs/tasks.md) writes each of the roadmap's 27 tasks as `Task ID → input → output JSON Schema →
tool / agent → method → benchmark → metric → gold → human review`, and marks what is done (●), partly done (◐) or not
done (○: layout and OCR). The eleven capabilities that were missing follow the three rules of deep discovery 2.0: study
functions and tools (`study.*`) called by the existing agents, each with an eval suite and a JSON Schema of its output
(`taochronos schema --study`), checked by the tests against real results.

| Capability | What it does | Full-corpus example (machine reading, with quotes to check) |
|---|---|---|
| **句读** `study punctuate` | a discriminative model learned from the store's punctuated texts decides at every gap whether a mark goes there and which; **marks are inserted, no character changes** (checked on every output); punctuated input is stripped and compared with its editors; the model stays in the local cache | 55 held-out works (104 k characters): boundary F1 0.767 (rules 0.235), mark types 0.805; 4 Siku 白文 works against their 笈成 punctuation 0.780 (rules 0.303); characters preserved 1.0 |
| **Clause structure** `study clause` | a clause cut at its marks, each piece given a role (condition, disease, findings, pulse, pattern, principle, contraindication, formula, composition, preparation, administration, modification, prognosis), its drugs with doses, findings, pulses, diseases and formulas listed; `--work` profiles a work's clauses | 87 gold pieces: accuracy 0.977, macro-F1 0.917; 40 % of the pieces of the fullest 伤寒论 witness are read by no rule (平脉法 dialogues, numbering, notes) — reported as such |
| **Glosses** `study glosses` | the glosses of a word in the set forms (…者…也, …貌, 音, 反切, 读为, 当作, 一作, 通) whose head is the word itself; glosses on the letter read in the characters as written; readings grouped with who gave each first | 几几: 5 glosses, 4 readings, the first 成无己's 伸颈之貌 |
| **Commentaries** `study commentaries` | the clause found in the commentaries in four layouts and the commentary cut, attributed and dated; wording compared with the classic masked out (照录, 承袭, 自录), concepts added compared (同解, 增益, 异解), stated rejections and endorsements read (驳, 从); quotations elsewhere kept apart | 太阳之为病: 25 commentaries from 1144 on, the known commentators 11/11; 张卿子 照录 成无己, 喻昌 承袭 方有执; the consensus concept 表, first brought by 成无己 |
| **Disputes** `study disputes` | where a physician is named with a citing word, the stance after the reported view: quoted speech closes first, a hypothetical is no verdict, a double negation affirms, a verdict after another name is that name's; a work reporting another's rejection is credited as reporter | 张介宾 rejects 丹溪 most; 丹溪 rejected 32 times, endorsed 11 times; 景岳 on 丹溪's 相火 reported in the 吴医汇讲 and the 医述; 越人's 左肾右命门 repeatedly rejected |
| **Variant impact** `study variants` | each reading classed, first rule that applies: dose 1.0 (not 半表半里 or 十枣汤), negation or modal 0.95, drug or formula 0.90, clinical term 0.80 … orthographic 0.05; the review queue ordered by it — **for experts to read doses and negations first, never to decide which witness is right** | the 伤寒论's 288 variant units, the top ten of the queue all high-impact; 30 gold readings, accuracy 0.967 |
| **Drug pairs** `study pairs` | one cached pass reads every written-out composition (drugs by family, one work counted once); support, confidence both ways, lift, NPMI, Fisher with Benjamini–Hochberg; a drug's partners, triples and periods; communities of the significant pairs as groups of drugs | 66 196 compositions; 7/7 textbook pairs significant (桂枝—芍药 in 2 527, lift 2.05; 麻黄—杏仁 5.08; 柴胡—黄芩 3.34 …); groups recovering 六味, 四物, 攻逐, 破血, 理气, 消导 |
| **Formula–finding network** `study network` | the findings, pulses, patterns and diseases named before a formula in treatment sentences (…主之, 宜…汤), by lift; a formula's findings and drugs, a finding's formulas — **co-occurrence, not efficacy** | 桂枝汤: 汗出, 发热, 脉浮, 恶寒, 太阳病; 麻黄汤: 脉浮, 无汗, 伤寒, 喘; 黄芪桂枝五物汤—血痹, 炙甘草汤—脉结, 乌梅丸—吐蛔 |
| **Schools** `study schools` | the textbooks' groupings (`schools.yaml`) as a convention to test: a school's works against the other works of their time (sixty years), one unit per physician, reweighed to the school's forms; log-odds with an informative Dirichlet prior (Monroe et al. 2008) + BH + a share test; formulas, homophily of citations, schools cited and citing, rejections | the textbooks' 44 doctrines: used more by their school 0.727, most by it 0.636; 温补: 命门 (z 7.6), 先天, 六味丸, 八味丸; 温病: 膜原, 战汗, 伏邪, 达原饮, citing each other 4.05 times as often as their contemporaries; the 儒门事亲 writes 汗下吐 (44 passages), hardly 汗吐下 (1); 丹溪's books write 补阴 (47) more than 滋阴 (6) |
| **Names** `study names` | the works writing each name of an entry by period and century (a name inside a longer one counted apart), the first to write it, the preferred name per century and where it changes (a one-century blip read as its neighbours), passages equating names, names the lexicon lacks | 山药: 薯蓣 until the 1000s, 山药 from the 1100s (the taboo of 宋英宗); 玄参 yields to 元参 in the 1700s (康熙) and returns after 1900; 山芋, a name the lexicon lacked, in 6 works |
| **Transmission chain** `study chain` | the dated witnesses of a passage ordered into a tree by shared innovations (Lachmann): the readings of the earliest witnesses are the source's; each later witness hangs from the earlier witness whose innovations it shares most; spelling equivalents are not innovations, function words weigh half; each edge carries its readings and margin (uncertain under one) | two 伤寒论 clauses, 60 dated witnesses each, 10 and 8 reached through intermediaries (脉经 → 千金翼方, 尚论篇 → 张氏医通 → 伤寒溯源集 → 伤寒大白); artificial traditions: parent accuracy 1.0 (0.941 with convergent spellings, baseline 0.868) |

The examples of this table were computed on the current store (966 works) by the full evaluation; see
[docs/tasks.md](docs/tasks.md).

### Herb and formula research, research protocols and charts

The five herb and formula studies share the one cached pass of `study pairs` (one work counted once; each composition
with its drugs by family, the doses and preparation notes as written, and the form its preparation makes of it — 汤剂,
丸剂, 散剂 or 煮散, so that a 宋 powder boiled by the spoonful is not compared with a decoction): **`study compare`** sets two to
six formulas side by side (drugs, doses in the measures of each witness's period, ratios, dose-weighted overlap, and a
verdict per pair); **`study family`** finds the formulas made from a base by adding or removing drugs, or changing its
doses; **`study usage`** follows a drug through the periods (its share of the compositions with Wilson intervals and a
trend test, decoction doses by period, the largest-dose clue, preparation notes, partners); **`study properties`** sets the
本草's flavours, natures, toxicity and channels of several drugs, or of a formula's, side by side; **`study incompat`**
reads 十八反 and 十九畏 in the texts — who stated each pair first, where the verses are written, and which compositions still
write both drugs.  **`study protocol`** turns a research question into a protocol with falsifiable hypotheses (a formula's
name is read as one: 白虎加人参汤 is 白虎汤 加 人参), operational variables, methods that are this system's tools with the
commands that rerun them, analysis, figures, quality checks, limitations, ethics, a timeline and a research contract, and
runs its main steps once to say whether the corpus holds enough; its figure plan names each figure and its form (图 1 …)
and its tables set out each table a paper will print — holding the pilot's numbers where the pilot ran the step that
fills them (marked 预试验, to be checked against the texts), and elsewhere placeholders in the notation of its numbers
(×× (××.×), ×.×× (×.××–×.××) …) with the statistics behind them — to copy or download as Word; the page offers the whole
protocol as a Markdown document.  Their results — and those of `formula`, `herb`, `term`, `pairs`, `network`, `names` and `senses` — carry
chart specifications and three-line tables: the page draws the charts (a drug's decoction doses as a Tukey box plot and
against the year with a LOESS curve; a drug's partners as a forest plot of odds ratios; the corpus's most frequent drugs as
a cluster dendrogram) and exports them in a journal's style — white, L-shaped axes with outward ticks, 8 pt at 85, 120 or
175 mm, numbered with their caption, as SVG, PNG or TIFF at 300 or 600 dpi, and several as one figure in panels — and
prints the tables as a journal does (n (%), M (P25, P75), OR (95% CI), P; the tests in the notes), to copy into Word or
Excel or download as Word, LaTeX, CSV or Markdown; `--charts DIR` writes the same figures and tables as files.  See
[docs/study.md](docs/study.md#表格-three-line-tables), [ADR 0019](docs/adr/0019-herb-formula-research-protocols-charts.md),
[ADR 0020](docs/adr/0020-figures-and-tables-for-a-paper.md) and [ADR 0021](docs/adr/0021-labels-that-keep-apart-and-tables-with-numbers.md)
(labels that never overlap; a protocol's tables filled with its pilot's numbers).

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
| **TaoChronos-Scholar** | 治学: textual history of the focus terms over the whole store (with sense evolution for terms) | procedure |
| TaoChronos-Evidence | evidence ledger; independent witnesses for hypotheses | hybrid |
| TaoChronos-PatternMiner | D1–D5 and lost-source clues (tool-first) | procedure |
| TaoChronos-Statistician | significance, BH correction, empirical ranks, coverage | procedure |
| TaoChronos-Evolution | concept timelines, formula family trees | procedure |
| TaoChronos-Hypothesis | hypothesis generation and revision | hybrid |
| TaoChronos-Skeptic | falsification: counter-examples, variants, homonymy, transcription dependence, coverage, statistics | hybrid |
| TaoChronos-ModernEvidence | modern evidence as context only; bridges must pass G8 | hybrid |
| TaoChronos-MetaReviewer | systemic issues and next-round recommendations | hybrid |

The deep-discovery tools sit on the existing agents, with no new roles: the Philologist `study.variants/stemma/layers/
dating/authorship`, the Skeptic `study.reuse/dating/argument`, the Evidence agent `study.cases/trajectories/argument`,
the Semanticist `study.term/senses`, the Scholar `study.senses`; the Lineage Analyst gets reuse types through the
lineage edges.

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

**The contract and its boundaries** ([ADR 0009](docs/adr/0009-boundaries-contract-and-evaluation-layers.md)):

- **A quote is not its reading.**  Before a claim is committed its quote must *state* it: the nearest cue governs each
  intervention (「不可发汗，宜桂枝汤」), the consequence tells a warning from a recommendation (「汗之则神昏」 / 「汗之则愈」),
  an intervention named by 之 is read through its pronoun, and every argument is read with its negation (「非风、非寒…乃
  异气所感」 does not support "风 causes 温疫").  The statement's frame records who says it (after 或曰……余曰非也 the words are
  the author's), the stance (asserted / reported / rejected), the conditions (若…者, 凡…, the 「…者，X主之」 clause),
  negations and time.  A claim its quote contradicts is refused.  A claim that rests on words the commentators
  doubted — a textual crux (公案) from the registry harvested from the commentaries in the store (伤寒论 85, 金匮要略 42:
  transpositions, emendations, interpolations, omissions, doubts) — reads *ambiguous*, with the crux and who doubted it.
- **An absence in a sample is not an absence in the literature** ([ADR 0010](docs/adr/0010-speed-cruxes-and-research-value.md)).
  A lost association (D1) and a hidden one (D4) are claims about the literature: the Skeptic searches the whole scope —
  the store within the contract's window, for a large corpus — for claims that *state* the association (one-character
  forms included, the extractor deciding, supported quotes only).  One verified statement after the pivot refutes a
  loss (`restated_after`); any statement refutes a hidden link (`attested`); both are hard objections no rewording
  closes.
- **A proposal is not a verdict.**  Every event carries the principal of its emitter (kernel › human › validator ›
  agent), set by the session from an identity object; only an expert sets G7; objections are a state machine (raised →
  resolution proposed → closed) in which a model only proposes and a hard objection closes only by a validator's
  passing re-run.
- **Execution is not acceptance.**  The contract judges each hypothesis on its current version, each criterion recording
  its judge, observation, requirement and the state a failure leads to.  Each hypothesis has a **warrant** — inference,
  assumptions, the rival explanations of its discovery type (excluded / open / not applicable / unaddressed) and the
  discriminating analyses; predictions can be confirmed on material withheld from exploration; statistics are
  selection-aware (a max-statistic permutation over all boundaries, leave-one-family-out, family bootstrap); novelty
  is scoped ("not found within the stated scope", never "first discovery"); Elo is an **exploration priority**, not
  credibility.
- **An internal score is not external evidence.**  Withheld material does not exist on any read path of an agent (views
  plus a result firewall); G8 reads modern evidence by stance and level (contradicting human evidence fails it); model
  code runs in a namespace-isolated tier or not at all.
- **Long runs.**  Budgets reserve before and settle after each model call, in the log, and a resumed run starts from the
  ledger; long tool results are paged, never cut; model responses can be recorded and replayed exactly
  (`--record-llm` / `--replay-llm`); evidence can be retracted, which propagates (support removed, gates voided, the
  contract judged again); tasks can be cancelled and retried.

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
| **Authority from identity** | authority comes from identity objects, not strings; every event carries a principal checked per event type; agents hold a view bound to their identity and a read-only state |
| **Execution ≠ acceptance** | finished tasks do not make an accepted research: the contract judges each hypothesis on its current version, and a report presents only hypotheses so judged |

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
- *A work's witnesses*: `study stemma 伤寒论` → variant units, the stemma, groups of shared readings and contamination;
  `study tei` for a TEI apparatus, `study edition <book_id>` for one witness against the others; `study witnesses 伤寒论`
  for the transcriptions (edition, year, holder, source, licence — CMETA's passages open the page they were read from)
  and the digitised prints and manuscripts in libraries (date, print or manuscript, holder, shelfmark, IIIF manifest,
  terms), in date order.
- *A passage's reception*: `study reuse <passage>` → each later use typed with its rule (who copied, cut, explained
  or refuted it); `study transmission 伤寒论` for the retained, transformed and disputed shares by period and the channels.
- *How a classic was composed*: `study layers 素问` read with `study dating 素问` — style says that chapters differ,
  citations, late vocabulary and taboo say when they can have been written; `study authorship` for candidate authors.
- *Clinical practice in the records*: `study cases --book <id>` visit by visit; `study trajectories 咳嗽` for the sequences
  physicians followed (associations in a record, not evidence of efficacy).
- *Lost works*: `study fragments 小品方` gathers fragments with their quoting books and volumes; `--verify` tests the
  method and each quoting book on a surviving work first.
- *Reproducible publication*: datasets carry the corpus signature (books, passages, sources, normaliser, catalogue
  digest); the same corpus gives the same results.

**Students**

- `study cards --book 伤寒论 --anki shl.tsv`: cloze cards for every "……者，某方主之" clause of the 伤寒论, for spaced repetition;
- `study cards --formula 桂枝汤 --formula 小柴胡汤`: composition, doses, preparation, decoction, with the verse;
- `study cards --herb 柴胡 --herb 附子`: properties in the 本经 and in a later materia medica;
- `study reading 温病`: a reading path from the 素问 and 伤寒论 to the 温病条辨, each work with the reason to read it;
- `study concordance`: for a passage being read, who quoted it through the ages and how it was reworded;
- `study argument "<passage>"`: how a passage reasons — conditions, inferences, causes, contrasts, analogies, rebuttals,
  definitions and prescriptions marked clause by clause; `study senses 消渴`: a word's senses through the periods.

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
procedure and the fallback is recorded as a Decision.

**Mainland and multi-platform models** ([docs/models.md](docs/models.md)): MiniMax (`minimax`, mainland
`api.minimax.cn`, `MINIMAX_API_KEY`; and `minimax-global`), Poe (`poe`, `POE_API_KEY`, bot names as models), LiteLLM (the
`litellm` package with `<provider>/<model>`, or `litellm-proxy`), DeepSeek, Qwen (DashScope), Kimi (Moonshot), GLM
(Zhipu), Doubao (Volcengine Ark), SiliconFlow, OpenRouter, local vLLM/Ollama.  The study, bridge, audit, vision and
workflow commands take `--llm platform:model` (with `--llm-max-calls`, `--llm-max-cost`, `--llm-refresh`); the profiles
`minimax`, `poe` and `litellm` configure the reasoning models and the judge together.  Judge calls are cached, budgeted,
schema-validated (one repair turn) and logged without their prompts; results record whether the rule, the model or both
decided each item.  External command subagents and Research Code Mode: [docs/agents.md](docs/agents.md).

**Web chat · 道乃久** ([docs/web.md](docs/web.md), [ADR 0011](docs/adr/0011-web-client.md); the default service and records: [ADR 0012](docs/adr/0012-default-service-relay.md)): the agent 道乃久 (TaoChronos;
model Tao-R1), published by IMPF-AI — TaoChronos's tools and evidence discipline over the underlying model you choose, which
the page names (asked who it is, who published it or what model it runs on, the page itself gives a fixed introduction of
the platform: [ADR 0014](docs/adr/0014-identity-fixed-reply.md); an endpoint not in the list can be set by hand).  The conversation runs in the browser
on the default service (no key; the page shows it as 道乃久默认服务 / Tao-R1 and names no vendor) or with your own key,
straight to the provider or through `taochronos serve`; TaoChronos
executes the tools in the browser (Pyodide, the 要籍语料: 533 of the 535 key works) or under
`taochronos serve` (the full corpus, all the books; the browser remembers the server).  The model acts as an
agent with read and analysis permissions only, sees nineteen common tools directly and the rest through a catalog;
MiniMax-M3's `reasoning_details` and tool calls are replayed verbatim turn after turn, and Claude is called through the
official SDK (adaptive thinking, server-side refusal fallbacks).  The local server binds to 127.0.0.1 by default, answers
only this machine's pages, its own pages, the published client and named origins, and forwards model requests only to the
listed providers; bound to any other address it requires an access token.  All the books (about 2.2 GB, under their
sources' licences) are not published with the site: they reach it through the server.  A user may upload their own data
for 道乃久 to analyse ([your own data](docs/mydata.md), [ADR 0022](docs/adr/0022-the-users-own-data.md)): it is read and
made anonymous on their machine, never handled by the site's servers, and a conversation touching it is never recorded.

## 8. Evaluation and quality

`taochronos eval` runs on the demo corpus; with the corpus store, the deep-discovery and task-specification suites also check the real corpus and the research-value layer runs blind on it (~18 min for all suites once the caches are built, ~11 of them research value). The gold sets were built by the authors for the demo corpus and used
during development: **regression tests, not an unbiased benchmark** (see [evals/gold/README.md](evals/gold/README.md)).

The evaluation has three layers ([ADR 0009](docs/adr/0009-boundaries-contract-and-evaluation-layers.md),
[ADR 0010](docs/adr/0010-speed-cruxes-and-research-value.md)): **invariants** (the harness's boundaries as probes run on
the harness under evaluation), **hard interpretive cases** (verbatim quotes that can still be read wrongly, scored per
class with the *unsafe* errors counted apart, on dev and held-out splits) and **research value** (`research_value`: the
full corpus split at a cutoff year, against popularity and chance — with every other suite, the ablations and the
baselines).

| Suite | Result |
|---|---|
| Invariants | 19/19 hold (the audit's P01–P10 and nine boundaries added with them); each of six boundaries removed on purpose (scope guard, result firewall, semantic support, reducer authority, evidence bounds, publish guard) breaks its invariant |
| Interpretive | 107 cases in eight classes (inverted relations, a prohibition beside a prescription, consequences, reported and rejected views, omitted conditions, mixed witnesses, disputed dates, textual cruxes): **held-out 82/84 (0.976)**, dev 23/23; 2 unsafe (大黄牡丹汤 and 里水: cruxes the harvest does not find, reported and not patched); first blind round 43/53 (0.811); round 3 (before the crux registry) 7/10 with 3 unsafe, round 4 (written after it, before it ran) 5/5 |
| Research value (full corpus) | **Link anticipation** at 1127 and 1368 (189 topic–cutoff pairs, 29 467 candidates, base rate 4.5 %): Adamic–Adar, which D4 ranks by, **precision@10 0.168** (popularity 0.134, chance 0.054), mean average precision 0.199 / 0.143 / 0.092; better than popularity on 149 topics, worse on 39 (sign test p = 2.4 × 10⁻¹⁶), at both cutoffs.  **End to end** (the pipeline on the text before 1368; leakage 0): 10 of 25 held-out predictions held; the new absence checks rejected 4 (2 false losses, 2 links written before the cutoff) and no discovery; surviving discoveries 7/23 → **7/19**.  The verdict is modest: the ranking is well above its baselines; the hypotheses, one by one, hold about half the time and association rules rarely |
| Philology | 7/7: no forced reading, uncertainty mass kept, normalised matching |
| Claims | P 1.0 · R 0.976 · F1 0.988 (a general prognosis rule: 则愈 / 自愈 / 欲解 / 可治 … / 者死 / 难治 / 不治; before it F1 0.964 and prognosis recall 0; this gold is dev); 100 % of extracted claims verbatim |
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
| Collation | 5 traditions copied down a known stemma: variant units recall 0.998, precision 0.999; the true split found every time; top-3 groups all genuine; contamination P/R 1.0 |
| Reuse | 33-pair development set: accuracy 0.97, macro-F1 0.965; detection P 1.0 · R 0.96 |
| Stratigraphy | composite texts: layer accuracy 0.955, boundaries R 0.90 / P 0.93, attribution 0.89; real: 运气七篇 7/7, both boundaries, both 叔和 chapters |
| Cases | development set 1.0 throughout; real: the two transcriptions of 吴鞠通医案 agree 0.98 on cases, 0.92 on outcomes |
| Argument | development set edge F1 1.0; real: JSD 0.020 between two transcriptions of one work, 0.091 against another |
| Senses | planted sense shift: change year within 2.3 years, labelling 0.93, hidden sense found 1.0; curated exemplars 6/8 |
| Fragments | constructed corpus: precision 0.86, coverage 1.0, no other source's words taken in; real: 千金 0.32 / 0.12, 肘后 87.6 % not in the extant text |
| Punctuation | real: 55 held-out works boundary F1 0.767 (rules 0.235), mark types 0.805; Siku 白文 0.780 (rules 0.303); characters preserved 1.0 |
| Clause | 16 clauses, 87 pieces: accuracy 0.977, macro-F1 0.92; real: 40 % of the fullest 伤寒论 witness read by no rule |
| Glosses | 16 sentences: accuracy 1.0, P/R 1.0; real: 成无己's 伸颈之貌 the first gloss of 几几 |
| Commentaries | a constructed commentary tradition in four layouts: units F1 1.0, text F1 0.81, relations F1 1.0; real: 25 commentaries on 太阳之为病, known commentators 11/11, known relations 2/2 |
| Disputes | 22 development sentences: accuracy 0.86 (reject P 1.0 · R 0.78; endorse P 0.8 · R 1.0); real: known controversies 3/3 |
| Variant impact | 30 readings: accuracy 0.97, high impact P 1.0 · R 0.94; real: the top ten of the 伤寒论's queue all high-impact |
| Pairs | 600 synthetic compositions: planted pairs top-3 1.0, false significant 0.0; real: 7/7 textbook pairs significant with lift > 1.5 |
| Schools | a synthetic school: planted words top-2 and significant, common words not listed; real: doctrine recall 0.73, attribution 0.64 (44) |
| Names | synthetic works: switch interval, nested names, equations, candidate names right; real: the dated taboo renames 2/2 (薯蓣→山药, 玄参→元参) |
| Chain | 6 artificial traditions of 12 witnesses: parent accuracy 1.0 (most-similar baseline 0.97); with convergent spellings 0.94 (baseline 0.87) |

The V2 suites ([docs/evals.md](docs/evals.md)):

| Suite | Result |
|---|---|
| Entities (T7) | dev F1 0.991; **held-out 25 sentences F1 0.776** |
| Places (T27) | signatures and native-place statements P/R 1.0; 291 of 761 works placed on the full corpus, curated places confirmed 4/4 |
| Translation (T10) | presentism guard 24/24; original layer unchanged 24/24 |
| Layout (T1–T2) | 60 synthetic pages: exact reading order 0.983, CER 0.0005, notes F1 0.999; four OCR formats identical; OCR errors located 12/12 |
| Bridge (AMBE) | dev F1 0.985; **12 held-out passages of the full corpus, annotated before the reader ran: P 0.938 · R 0.732 · F1 0.822**; mapping top-1 1.0; caps 3/3; guard 20/20; 213 HPO ids valid |
| Audit (S15) | 19 claims: verdicts and kinds 1.0, false SUPPORTED 0; safety 3/3 |
| Modern (S13–S14) | typing 10/10; cross-level guard 7/7; RWD: SQL checks pass, planted association recovered, bad SQL refused |
| Workflow (V2) | registry valid; 8/8 questions compile to the skills they need; a rerun reads every step from its workspace |
| Aliases ([ADR 0023](docs/adr/0023-alias-layer.md)) | 120 drug-name questions on the web store, half held out; **second held-out report, 59 items: web-canon (deployed) P@10 0.683 → 0.771**, Wrong@10 25 → 12, asked-name retention 0.589 → 0.749, leakage 0 — acceptance 6/10 (fails: least asked-name retention 0.000, other-name hits at 50 ×1.22 against ×1.5, CandRecall 0.650, SilentMerge 1); full-corpus as a proxy on the web store 0.673 → 0.795, 7/10; the first report had 0.791 and 0.805; synthetic checks all hold |

The development sets of deep discovery and of the task specification were written with their rules: they show
intended behaviour, not generalisation. Expert gold on the full corpus is on the roadmap; the benchmark table of
[docs/tasks.md](docs/tasks.md) lists each task's metric and gold.

Plus 349 unit and integration tests (`pytest`, with format samples of every source, a synthetic corpus for the
study layer, `tests/fixtures/study`, a contract test that checks real results against the JSON Schemas of the tasks, the
audit's P01–P10 as regression tests in `tests/test_boundaries.py`, and `test_contract.py`, `test_statistics.py`,
`test_longrun.py` and `test_eval_layers.py`) and the architecture governance check (`taochronos governance`: layering,
kernel neutrality, model-SDK isolation, agent rules). CI runs governance, tests, the quick evaluation and the demo
research on Python 3.11 and 3.12.

## 9. Architecture

```
protocol      data models (passages, claims, evidence, hypotheses, events, output schemas)
kernel        event sourcing, transactions, replay, scheduler, policy, hooks, budgets, Context OS, memory, stop, observability
capabilities  provider-neutral interfaces (LLM …)
science       D1–D5 engines, statistics, scoring, gates, provenance; reuse rules, strata, trajectories, argument graphs, sense evolution
verification  verbatim checks and provenance chains; the presentism guard; the evidence graph and the evidence audit (V2)
tools         the tool mesh: philology · retrieval · knowledge · analytics · study · bridge · literature · validation (79 tools)
plugins       classics (corpus, store, domain pack, philology, collation, citations, text reuse, study, vision, bridge, audit) · modern (evidence, real-world data) · knowledge · retrieval · models · sandbox · storage …
agents        AgentSpecs, routing, the LLM loop, deterministic procedures, Code Mode, subagents
engine        the research engine (operational and scientific loops, branches, tournament, report); the V2 workflow compiler and executor
```

Code asks the **capability registry** for capabilities (`corpus`, `domain`, `philology`, `lineage`, `retriever`,
`study`, `llm` …) and never imports a provider; plugins are assembled by profiles (`profiles/*.yaml`). Tools import no
plugin, agents act only through capabilities and tools, and agents, tools and plugins mint no privileged identity —
enforced by `taochronos governance`. Every event carries its emitter's principal, checked by the reducer against
`kernel/authority.py`; a transaction is validated as a whole before it is applied and persisted only after, with the
state restored from the log on failure; every round checks the live state against a replay of the log (incrementally:
a kept replay advanced by the new events, the live state hashed afresh). YAML is parsed once per content; a full-corpus
harness builds in 0.64 s instead of 9.2 s, and a full-corpus research run takes 95 s instead of 152 s (integrity checks
7.0 s instead of 44.5 s). See [docs/architecture.md](docs/architecture.md),
[ADR 0009](docs/adr/0009-boundaries-contract-and-evaluation-layers.md) and
[ADR 0010](docs/adr/0010-speed-cruxes-and-research-value.md).

## 10. Repository layout

```
architecture-policy.yaml   layering, kernel neutrality, SDK isolation, agent rules
web/                       the web chat client (plain ES modules, no build step): conversations, streaming, quotation checks,
                           evidence · research · tool console, settings; js/worker.js runs TaoChronos in the browser (Pyodide)
agents/                    16 AgentSpecs (YAML); agents/core/: the four V2 core agents
skills/                    SKILL.md packs (incl. source-criticism, the study method); skills/manifests/: the fifteen V2 skills (S01–S15)
profiles/                  full-discovery, full-corpus, classics-basic, formula-discovery, historical-disease, claude, minimax, poe, litellm
domains/classics/          periods, variants, lexicons, senses, modern concepts, ontology, citations, known findings,
                           and the study data: taboo.yaml, metrology.yaml, physicians.yaml, drug_families.yaml,
                           collation.yaml, intertext.yaml, cases.yaml, argument.yaml,
                           schools.yaml (schools), clause.yaml (clause roles), exegesis.yaml (commentators' concepts, stances, gloss forms)
domains/classics/script/   script and variant normalisation (OpenCC / Unihan / curated)
domains/bridge/            the bridge: 168 ancient phenotypes (forms, HPO projections, relation types), 64 disease profiles (ICD-10), homonyms, the HPO hierarchy used
domains/modern/            modern evidence: the crosswalk for queries, the safety table
domains/classics/lexicon-harvested/  candidate formula and drug names harvested from the corpus (full-corpus only)
corpus/                    the demo corpus (unverified), modern evidence summaries, catalogues (catalog/) and source locks
evals/gold/                gold sets
src/taochronos/            protocol/ kernel/ capabilities/ science/ verification/ tools/ plugins/ agents/ engine/ evals/ workspace/ chat/
  chat/                    the web chat's runtime (tool catalog, calls, citations, research sessions), `serve`, `web build`, providers
  plugins/classics/study/  the study layer: concordance · formulas · herbs · terms · taboo · network · metrology · learning · dataset · render
                           deep discovery: stemma · intertext · stratigraphy · cases · argument · senses · fragments
                           task specification: punctuation · clause · glosses · commentary · disputes · pairs · schools · names · chain · schemas
  plugins/classics/collation/  computational collation: anchored alignment · variant units · variant impact · stemma and contamination · TEI
tests/                     349 tests (fixtures/: source format samples and the study corpus; web_mock.py: scripted model providers for the web client)
docs/                      study, task specification, architecture, agents, discovery, evaluation, data, ADRs, roadmap
```

## 11. Data and licences

- **The repository holds catalogues, lock files, domain data and code only**; transcriptions stay in the local data
  directory (`.taochronos/`, git-ignored) and are rebuilt reproducibly by `corpus fetch / unpack / ingest`.  The one
  exception is the web client's **要籍语料** (`corpus/web/`): the texts of 533 of the 535 ranked works (all in the public domain),
  written by `taochronos web pack`.  The openly licensed witnesses (Kanripo and Wikisource CC BY-SA 4.0, CMETA CC BY 4.0,
  McGill public domain, 笈成 CC0 1.0) are used under their licences; the four works known only through a web text set (its
  repository declares no licence) and the modern editors' part of the 笈成 texts that follow a modern reconstruction or
  annotated edition (which 笈成's CC0 cannot release) are published with the site by IMPF-AI's decision, for study; nothing
  from a source whose terms forbid passing it on (東亜医学協会, a Hugging Face dataset under a proprietary licence) is in it.
  Per-text sources and terms: [ATTRIBUTION.md](corpus/web/ATTRIBUTION.md).
- **Conversation records** (`data/chat-logs/`): during the test period of 道乃久默认服务, the turns of visitors who agreed to
  be recorded (no key, settings or address), held by the relay and collected hourly into this repository.  It must stay
  private; move the directory out before it is ever made public.  The MiniMax key exists only as an encrypted secret of
  the relay and of the repository's Actions — never in the code, the site or a log.
- Licences are recorded per work in the catalogues and the store and travel with every witness: Kanripo and
  Wikisource CC BY-SA 4.0; McGill public domain; CMETA's collation and editing CC BY 4.0 (attribution: 數位中醫校書郎
  CMETA), the texts public domain; the 東亜医学協会's transcriptions © the association, non-commercial personal use
  only and no redistribution — local research only; 笈成 (the archive supplied by the user): 中醫笈成 releases its
  editorial work on the public-domain texts — selection, arrangement, punctuation, annotation — under CC0 1.0 and its own
  writing under CC BY 4.0 ([著作權聲明](https://jicheng.tw/tcm/copyright.html), checked 2026-09-29): credit 中醫笈成; a
  page's own notice prevails, the modern editors' part of the editions 笈成 follows is not covered, and a twentieth-century
  work may itself still be in copyright; the web text sets, mostly simplified copies of 笈成 texts, declare no licence of
  their own — a copy of a 笈成 text is not stored, and what is stored is for local research only; Hugging Face
  classical-tcm-canon declares proprietary-commercial terms — local research only, never redistributed.
- **Lexical data** — the alias layer (`domains/classics/aliases/`, [data.md](docs/data.md#alias-layer-domainsclassicsaliases)):
  what ships (the repository, the site, the server, the D1 backup) comes from the 本草纲目别名录 in the store (book
  `jc_c030`, CC0 1.0 — credited as 别名录（中醫笈成）), the editors' decisions (project data, every pairing, group,
  floor, stop and status with a witness passage) and facts read off the store with their passage ids (equations, the
  本草纲目's 释名, taboo pairs, the lexicon), never from a source whose terms forbid passing it on.  Three lists are for
  local research only and never published: the GB copy of the 别名录 on GitHub and hurbTable (no licence stated), and
  the NTU *Large List of Chinese Drug Names 40K* (CC BY-NC 4.0, DOI 10.21979/N9/V2XBOH; its attribution — Chong,
  William Eng Keat; Stanley-Baker, Michael, 2019 — unverified until confirmed with its Cite button).  Download them
  yourself and import them with `taochronos aliases import ntu FILE` (`hurb`, `bielu-gb`): they go to
  `.taochronos/aliases/local/`, recorded with their file, sha256 and rows and checked against the pin; `aliases build
  --local` builds the local layer, and only the `full-corpus-local` profile, never deployed, reads it.
- Image witnesses are catalogued as records only (title, date, holder, shelfmark, IIIF manifest, terms); **no image is
  downloaded**, and each record carries its holder's terms (研医会 CC BY-NC 4.0, Keio CC BY-NC-SA 4.0, Berlin PDM 1.0,
  the Library of Congress online reading only …).
- Datasets and reports contain short quotes (≤ 120 characters) with their sources, never the texts.
- Caches (entry headings, citation network, transmission results, the 句读 model, the corpus-wide pass over compositions
  and treatment sentences, school comparisons) live in `<data>/corpus/study-cache/`, keyed by a digest of the store,
  the normaliser, the book records and the data files they read; they are rebuilt when the corpus changes. The 句读
  model is learned from the store's punctuated texts, some of which (the 東亜医学協会's among them) are licensed for
  local research only: it stays in the local cache and is never committed or distributed.

## 12. Limitations

- The corpus is not collated by this project: the Siku texts carry Qing deletions and taboo changes and are segmented
  by rule for search and extraction (`study punctuate` punctuates them with a learned model, inserting marks only); 笈成 transcriptions vary in quality; dating without curation relies on book metadata and signed prefaces,
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
- Deep discovery 2.0 is rule-based too. A stemma is a hypothesis about the witnesses in the store, and contamination
  flags ask for a person. The reuse thresholds were set on a 33-pair development set, and concepts the lexicon lacks
  are found only by their wording. Style follows topic as well as author (the 运气 chapters are about 运气), so
  neither style nor dating evidence alone proves an addition. The case parser follows the layouts it was written
  for; only explicit markers make argument edges; candidate senses are clusters of words until a person reads them;
  a fragment is as reliable as its quoting book's verified precision.
- The capabilities of the task specification have their limits too: punctuation measures agreement with one editor
  (editors differ); a clause piece takes one role, and 40 % of the 伤寒论's pieces are read by no rule; commentaries
  are found only in the four layouts, stances only where a physician is named, so unnamed disagreement is not counted;
  formula–finding links are co-occurrence, not efficacy; schools are historians' groupings, a word used more is not a
  doctrine until its passages are read, and small schools have little power; names counts the lexicon's names only; a
  transmission chain is a hypothesis from shared readings, and independent identical changes can make a false edge,
  which is why each edge carries its readings and margin.
- Image witnesses are linked to works by title: a commentary or another work of the same title cannot be told apart
  by the title, so links are for a person to check; only records are harvested, and a record's date is the
  catalogue's (a Japanese era alone gives its span).
- V2: a bridge level is a rule's qualitative grade — **not calibrated, not a probability** — and states phenotypic
  similarity, never a retrospective diagnosis; the 64 profiles and the homonym notes were curated for research screening
  and need clinical and historical review; the ancient-form map recalls 0.73 on held-out text, the bridge's main limit
  (the reason for a model's recall pass); the audit checks what can be checked mechanically (quotes, glosses, levels,
  evidence types, leaps), not a historian's argument; PubMed types are read from indexing and should be checked against
  full texts on a sample; the real-world-data path is a guarded compiler, and on synthetic people it tests the compiler,
  not a finding.
- The boundaries have limits of their own: a tool-level hold-out (the confirmation tier) is not a blind prediction; the
  namespace tier is not VM-grade isolation; the contract's verdicts and levels are ordinal labels, **not calibrated
  probabilities**; the semantic-support reading is a rule-based second reader that sees a textual crux only when the
  commentators state it in words the harvest reads (大黄牡丹汤 and 里水 escape it: the two unsafe held-out errors of the
  interpretive layer, reported and not patched); the interpretive gold is author-annotated.
- The research-value layer measures anticipation, not influence (a link comes true when later books write it, whoever
  found it first); both sides are read by the rule extractor; the full-text index ranks with whole-store statistics (no
  passage of the other side is read); the end-to-end part has 39 judged predictions and wide intervals; lost
  associations have no baseline yet; whole-store checks do not yet leave out a confirmation family's other passages.
- The system gives no medical advice; any research result is a lead until an expert (Gate G7) has reviewed it.

## 13. Roadmap and citation

See [docs/roadmap.md](docs/roadmap.md), and the tasks not yet done in [docs/tasks.md](docs/tasks.md): expert-built
lexicons, senses and gold sets; gold sets for formula parsing and property extraction and for the capabilities of deep
discovery and of the task specification on the full corpus; collation of whole works and a variant-reading dataset; a
corpus-wide reuse graph; regions (physicians' native places, places of practice and printing, T27) and schools and
drug pairs compared by region; dose-aware formula phenotypes; the historical identity of drugs; acupuncture and
non-drug therapies; illustrations and their lineage; a missingness-aware Bayesian D1; temporal hypergraph embeddings
(for candidate generation only); for V2, a layout gold on real pages, a larger held-out sample and wider form map for
the bridge, clinical review of the profiles and more ontologies (ISPO, Mondo, SNOMED CT, LOINC), an expert gold for the
audit, adjusted analyses on a real OMOP database, and a human-in-the-loop review interface.

When citing TaoChronos, cite the sources of the corpus you used (Kanseki Repository, 笈成, McGill University Library,
數位中醫校書郎 CMETA, 東亜医学協会, Wikisource …) with their licences, and the corpus signature (given by `study dataset` and in every Discovery Report):

```
TaoChronos: a provenance-grounded research harness for the Chinese medical classics.
https://github.com/psknlr/TaoChronos
```
