# 治学 — the study layer

The research agents answer *discovery* questions: they form hypotheses, falsify them and pass them through gates.
The study layer answers the questions scholars and students of Chinese medicine ask of the literature every day, in
the way the 考据 tradition answers them: from the texts, witness by witness.

| Command | Question | Returns |
|---|---|---|
| `study concordance` | 经文互见·集注 — where does this passage recur, and how do the witnesses differ? | witnesses in date order (同书异本 / 引文 / 互见), a collation apparatus (异文 / 脱 / 衍 / 倒) |
| `study formula` | 方源考 — what was the original composition, and what became of it? | every written-out composition, grouped (原方 / 通行方 / 加减化裁 / 同名异方 / 孤例), 同方异名, dose ratios, doses in the measures of their period, 历代主治, 加减, 方歌 |
| `study herb` | 药性源流 — what did each materia medica say of this drug? | flavour, nature, toxicity, channels, direction, indications per work; the first statement of each value |
| `study term` | 术语源流 — when does this term rise and fall, and what did it mean? | share of passages per period with Wilson intervals, trend test, first attestations, collocates, where to read, senses |
| `study taboo` | 避讳断代 — which edition is this, judging by its taboo characters? | taboo rules with counts and verdicts, the edition's lower date bound; or a survey of the store |
| `study citations` | 引书与引人 — whom did each period cite? | works and physicians cited per period, physician-to-physician citation lineage; the reception of one work or physician |
| `study cards` | 学习卡片 — cards to learn from the classics | 方证 / 组成 / 药性 / 经文 cloze cards with sources (Anki TSV) |
| `study reading` | 阅读门径 — what should I read on this topic, and in what order? | source classics, the densest works by period, monographs, case records, Republican syntheses |
| `study dataset` | 研究数据集 — the results as tables for analysis | a Frictionless tabular data package (CSV + `datapackage.json`) with provenance and licences |
| `study metrology` | 历代度量衡 — how much is 三两 in the Han? | the dose read in the measures of a year (a historical reading, never dosage guidance) |
| `study variants` · `stemma` · `edition` · `tei` | 版本谱系 — how do the transcriptions of a work differ, and how are they related? | variant units (异文 / 脱 / 衍 / 倒 / 缺文 / 结构性增删 / 异体), a stemma with the groups of shared readings and contamination, one witness against the others, a TEI P5 apparatus |
| `study witnesses` | 版本与影像见证 — which editions of this work can I read, and where can I see its prints and manuscripts? | the transcriptions in the store (edition, year, holder, source, licence, page images); the digitised copies in libraries (holder, shelfmark, IIIF manifest, terms), linked by title |
| `study reuse` · `transmission` | 语义复用与思想传播 — what did later books do with this passage, and how was this work taken up? | typed reuses (直接引用 / 近似转录 / 节略 / 撮要 / 转述 / 解释性改写 / 引而驳之 / 套语相似) with the rule that fired and the values it read; a work's reception by period, and its channels |
| `study layers` · `dating` · `authorship` | 文本地层 — which chapters of a classic belong together, and when can each have been written? | style layers with membership probabilities and a permutation test, change points, outlying chapters; cited works, late vocabulary and taboo per chapter; Burrows' Delta to candidate works |
| `study cases` · `trajectories` | 医案轨迹 — what did physicians do, visit after visit? | case records as visits (findings, diagnosis, principle, formula, drugs and doses, changes, response, outcome); sequential patterns, transitions, associations with outcome |
| `study argument` | 医理论证 — how does this passage, or this work, reason? | clauses with their concepts and typed edges (condition, consequence, cause, inference, contrast, analogy, rebuttal, definition, treatment …); a work's profile; two works compared |
| `study senses` | 语义演变 — what did this term mean, and when did its meaning shift? | sense shares by period, change points, candidate senses the curation lacks, the term's neighbourhood by period, a check against the curated exemplars |
| `study fragments` | 佚书辑佚 — what survives of a lost work in the books that quote it? | fragments ordered by the volume the source notes give, each with its quoting witnesses and parallels; the method verified on works that survive |

Every result is made of **witnesses**: a verbatim quote with its passage id, locator (《书》卷·篇·节), the book's date
and period, the text layer (正文, 注, 序跋 …), and the source and licence of the transcription. Every statement can be
checked against the text it rests on through its passage id (the `classics.get_passage` tool, or the store). The
functions are deterministic and rule-based; they run on the demo corpus and on the full corpus store.

## Using it

```bash
taochronos study concordance "太陽之為病，脈浮，頭項強痛而惡寒"      # or --passage <id>
taochronos study formula 六味地黄丸 -o liuwei.md                   # Markdown (default) or --json
taochronos study herb 柴胡
taochronos study term 温病
taochronos study taboo jc_d004                                     # one book; without an id: a survey of the store
taochronos study citations 张仲景                                  # reception; without a target: the network
taochronos study cards --book 伤寒论 --formula 桂枝汤 --herb 柴胡 --term 消渴 --anki cards.tsv
taochronos study reading 温病
taochronos study dataset --formula 桂枝汤 --herb 柴胡 --term 温病 --citations -o datasets/guizhi
taochronos study metrology 三两 --year 200

# 深层发现 2.0
taochronos study stemma 伤寒论                                     # --books <id> --books <id>+<id> · --chapter 辨太阳病
taochronos study variants 伤寒论 --chapter 辨太阳病 --json
taochronos study variants "太陽之為病，脈浮，頭項強痛而惡寒" --text-mode   # a passage's copies and quotations
taochronos study tei 伤寒论 -o shanghan.tei.xml
taochronos study witnesses 伤寒论                                  # transcriptions and image witnesses (records only)
taochronos study reuse "太陽之為病，脈浮，頭項強痛而惡寒"           # or --passage <id>; --against "<text>" for one pair
taochronos study transmission 伤寒论 --clauses 40
taochronos study layers 素问 --k 2                                 # --features function
taochronos study dating 素问
taochronos study authorship --book 伤寒论 --chapter-name 辨脉法 --candidate 脉经 --candidate 金匮要略
taochronos study cases 风温                                        # or --book <id>
taochronos study trajectories 咳嗽
taochronos study argument --work 伤寒论 --against-work 温热论       # or a text, or --passage <id>
taochronos study senses 消渴
taochronos study fragments 小品方                                  # --verify: test the method on a surviving work
```

The CLI uses the `full-corpus` profile when the corpus store exists (otherwise the demo corpus). The same functions
are tools of the tool mesh (`study.concordance`, `study.formula`, … — results trimmed for agent context) and a
capability for code (`harness.capabilities.get("study")`, or `StudyService(pack, corpus)`).

In research runs, **TaoChronos-Scholar** traces the focus terms through the whole store in round 0 when the profile
sets `discovery.sources_dossier` (the `full-corpus` profile does). Its dossiers are recorded as analyses and printed
as the appendix **源流考证 · Sources Dossier** of the Discovery Report. They describe texts; they are not hypotheses and
pass no gates.

## What the texts demand

| Feature of the classics | What the study layer does |
|---|---|
| A work survives in several transcriptions, is quoted and restated | concordance separates 同书异本 (same work), 引文 (a citation marker precedes the passage) and 互见 (restatement) |
| Names change under taboo | 薯蓣 → 薯药 (唐代宗) → 山药 (宋英宗), 玄参 → 元参, 丸 → 圆 (宋钦宗): all spellings are searched, and the taboo module turns the spellings into edition dates |
| One name, several formulas; one formula, several names | compositions are grouped by their drugs: 同名异方 are kept apart, 同方异名 are found by searching the drugs, not the name |
| 笈成 prints a formula's or a drug's name as the heading of its entry | a corpus-wide index of entry headings (cached) finds entries whose text never names them; the parser reads across the entry's paragraphs |
| Doses are written in the measures of their period | each dose is read in its period's measures (`metrology.yaml`); ratios compare witnesses independently of measures |
| Doctrines are period-bound | 归经 and 升降浮沉 are Jin–Yuan doctrines — their absence from the 本经 is expected, and the first statement of each is reported with its date |
| Dating is uncertain and layered | "earliest" orders by the latest date a witness can have (terminus ante quem); commentary layers carry their own dates; citations dated before the cited work existed (editors' notes dated with the text they annotate) are set aside |
| Surviving text is uneven across periods | term histories compare shares of passages per period, with intervals, never raw counts |
| Formulas were learned by verse | 方歌 are found in the 歌诀 books: clauses of five or seven characters that name the formula and recite its drugs, abbreviations included |

## 经文互见·集注 (concordance)

**Method.** The query is normalised (variant characters, script) and cut into overlapping 4-character probes; the
eight rarest probes (by index frequency) retrieve candidate passages, and a candidate must contain at least two of
them. Each candidate is aligned with the query (`difflib`), cropped to the densest aligned block, and scored by
*coverage* — the share of the query it carries. Witnesses with coverage ≥ `min_coverage` (0.6) are kept and labelled:

- **同书异本** — another copy of the base work (the work of the query passage, or of the earliest witness with
  coverage ≥ 0.95);
- **引文** — a citation marker (《…》曰, 经曰, 岐伯曰, 仲景云 …) precedes the passage;
- **互见** — the passage is restated without acknowledgement.

**Apparatus (校勘记).** Witnesses with coverage ≥ 0.8 are collated against the base: substitutions (异文),
omissions (脱), additions (衍) and transpositions (倒, merged from an omission and an addition of the same
characters). Operations longer than six characters are not collated (they are different wording, not variants).
Each reading lists its witnesses.

**Example (full corpus).** 「太陽之為病，脈浮，頭項強痛而惡寒」 — 113 witnesses in 46 works: 8 other copies of the
伤寒论, 10 quotations (e.g. 《伤寒证治准绳》 经曰…), 95 restatements; the 千金翼方 witness lacks 脈浮.
「上古之人，其知道者，法於陰陽，和於術數，食飲有節…」 — 47 witnesses in 22 works, 32 of them quotations; the apparatus
records the transposition 食饮 → 饮食 in 8 witnesses (世医得效方, 东医宝鉴, 古今医统大全 …) and the addition of 常 in 3
(备急千金要方, 普济方, 世医得效方).

## 方源考 (formula provenance)

**Names.** The formula's names from the lexicon (本名, 异名) plus the Song taboo spelling (丸 ↔ 圆).

**Finding compositions.** (1) Passages containing a name followed within 260 characters by a dose; a name inside a
longer formula name (柴胡桂枝汤 is not 桂枝汤) or followed by a modification (桂枝汤去芍药…) is skipped, the latter
collected as 加减. (2) Entries headed by a name anywhere in the corpus (an index of section headings, one row per
entry, cached in `study-cache/headings-*.sqlite`): the heading and the entry's paragraphs are read as one text.

**Parsing.** After the name: the indication (治…), then the drug list — each drug with its dose (三两, 半升, 十二枚,
方寸匕, 等分 …), its preparation note in brackets or without (甘草炙, 半夏半升，洗, 附子一枚，炮，去皮), and shared doses
(甘草炙　生姜切，各三两 gives both 三两; 白茯苓（去皮，各三钱） closes a run). The list must start like one; a list that
belongs to another formula (先与小建中汤，不差，与小柴胡汤主之。柴胡… / …桃仁承气汤；实者宜服此：柴胡…) is rejected. The
preparation clause (右五味… / 上为末…) is kept. Drugs are compared by family (`drug_families.yaml`: 桂枝/桂心/肉桂 → 桂).

**Grouping.** Witnesses with the same drug set form an exact set; the most frequent exact sets seed groups and every
other set joins the first seed it shares ≥ 0.7 of its drugs with (Jaccard), else seeds a group of its own. A group is
dated by the earliest witness of its exact seed composition, so an early variant (圣济总录's 地黄丸 with 附子) does not
become the original. Among the groups written under the name asked for: **原方** = the tradition attested earliest,
**通行方** = the most witnessed; other groups are **加减化裁** (Jaccard ≥ 0.5 with either) or **同名异方**; a group of one
witness is **孤例** (a parsing accident or a unique recension — check it by hand).

**同方异名.** Passages where the two rarest drugs of the main composition occur within 40 characters are parsed at
every formula name they contain; compositions with Jaccard ≥ 0.8 are reported with their names, counts, earliest
witness and ratio (`same_drugs` when the drugs are identical).

**Doses.** `metrology.yaml` gives, per period, the grams of a 两 and the millilitres of a 升 as ranges from the
literature (吴承洛, the 光和大司农铜权, 陶弘景's 序例, the 唐六典, the 库平两), and the value of 分 (¼ 两 before 960, 1/100 两
after). A dose is read in the measures of its witness's own date — **a historical reading for comparing the texts,
never a dosage recommendation.** Ratios (the largest dose = 1) compare witnesses independently of measures.

**Example (full corpus).** 六味地黄丸 — 266 written-out compositions in 84 works; 原方·通行方 (69 witnesses): 《小儿药证直诀》
卷下·诸方·地黄丸 (1119; the entry is headed 地黄丸 and its drugs are in the next paragraph), ratio 地黄 8 : 山茱萸 4 : 山药 4 :
泽泻 3 : 牡丹皮 3 : 茯苓 3; under the name 地黄丸 the earliest composition is 《备急千金要方》's (650–659), a different formula
(同名异方). 小柴胡汤 — 原方·通行方 from the 伤寒论(宋本) (柴胡半斤…各三两, read as about 110–125 g / 41–47 g in Han
measures); 同方异名 include 黄龙汤 (same drugs) and 柴胡汤; verses from 汤头歌诀, 退思集类方歌注 and 长沙方歌括. 肾气丸 —
原方 in the 金匮要略 (崔氏八味丸), 同方异名 桂附地黄丸/汤, 地黄汤.

## 药性源流 (materia medica)

**Finding entries.** In the 本草 books: entries headed by the drug (笈成 prints 【释名】【气味】【主治】 as paragraphs under
the heading; up to 12 paragraphs are read), then entries in running text where the name is followed by its flavour
or nature (黄芪味甘微温 / 附子（本经下品）气味辛温). An entry ends where the next drug's begins. One entry per work — the
fullest of its copies.

**Reading.** Flavour (味), nature (寒热温凉平, with 大/微), toxicity (无毒/小毒/有毒/大毒), channels (归经: 入手太阴…, 归脾经,
走肝经 …), direction (升降浮沉, 阴中之阳 …), indications (主… / 治…), aliases (一名…).

**Firsts.** For each value, the earliest work that states it (by terminus ante quem).

**Example (full corpus).** 柴胡 — 30 works (32 copies); 味苦、平、无毒 in the 神农本草经; the first 归经 is 足少阳 in the
汤液本草 (1289–1308), 肝·胆 in the 滇南本草 (1396–1476). 山药 — 署豫 in the 本经 (孙星衍 edition, after the 御览), 薯蓣
in the 证类本草, 山药 in the 汤液本草 (归手太阴): the name follows the taboos of 唐代宗 and 宋英宗.

## 术语源流 (term history)

For a term and its forms, every period is counted in the whole store: passages using the term / all passages of the
period, per 10 000 passages, with a 95 % Wilson interval, and a Cochran–Armitage test for a trend across the ordered
periods. Then the earliest attestation of each work, collocates per period (lexicon terms within 12 characters,
ranked by count × log(1 + lift) against the term's overall collocates), the works where it is densest (share of the
work's passages), and — when the terminology knows the term — its period-bound senses with **candidate** modern
concepts (never equivalences).

**Example (full corpus).** 温病 — 5 795 passages; 47 per 10 000 in the Han, 15 in the Ming, 39 in the Qing, 252 in the
Republic (z = +29.6); densest in 外感温热篇, 温病正宗, 温热逢源. 消渴 — 8 223 passages, 66 per 10 000 in the Han falling to
38 in the Ming (z = −8.3); collocates move from 小便不利 and 寒热 to 消中 and 烦躁 (Song–Jin–Yuan) and 多饮 (Qing).

## 避讳断代 (taboo dating)

`taboo.yaml` lists taboo rules with the year they start and the spellings they force (恒山→常山, 治之→疗之, 薯蓣→薯药→
山药, 玄参→元参, 丸→圆, 丘→邱, 弘→宏, 宁→甯 …). For a book, every pair is counted in both spellings (traditional and
simplified); a rule is **避讳** when the substitute has ≥ 3 occurrences and ≥ 80 %, **未避** when the original has ≥ 3
and ≤ 20 %, otherwise **兼用**. The edition's lower bound is the latest start year among avoided rules (per character,
the earliest rule that explains it). When that bound is later than the composition, the transmitted text was edited
or copied later.

**Example (full corpus).** Of 138 books of 200 000+ characters, 8 show an edition later than the composition: the 千金
要方 and 千金翼方 (丸 → 圆: Song editions after 1126), the 外台秘要 and 太平圣惠方 (玄: after 1012), 本草品汇精要 (玄 → 元: a Qing
copy), 女科证治准绳 (宁 → 甯: after 1821). Taboo evidence dates an edition, not a composition, and is indicative only.

## 引书与引人 (citations)

Every passage is scanned for (1) book titles in 《》, resolved to works of the corpus or to lost works
(`external-works.yaml`: 名医别录, 小品方, 集验方 …), (2) generic references (经曰, 本经云 …) resolved to their candidate works,
(3) physicians' names (`physicians.yaml`: 张仲景/仲景/张机/长沙, 李杲/东垣 …) before 曰/云/谓/方/法, and their 本草 short
names (恭, 颂, 权, 藏器, 大明 …) in the 本草 books. A book citing itself or another copy of its work, and an author citing
himself (时珍曰 in the 本草纲目), are not counted. Citations are counted in the period of the citing passage (its own
layer); a citation dated before the cited work or physician existed — an editor's note dated with the text it
annotates — is set aside and reported. The network is built once (about half a minute for the full store) and cached.

**Example (full corpus).** The Ming cites 朱震亨 (2 820), 张机 (2 103), 李杲 (1 621); the Qing 张机 (3 499), 朱震亨, 李时珍; the
Song–Jin–Yuan 日华子 (1 876, through the 证类本草), 张机, 陶弘景. The reception of 张仲景 begins with the 针灸甲乙经 and
the 脉经; the lineage lists who cites whom (唐慎微 → 日华子, 李时珍 → 苏颂 …).

## 学习 (learning)

- **方证 cards** from a book: every clause that prescribes a formula (…者，桂枝汤主之 / 宜… / 可与…), with the formula
  blanked: 「太阳病，头痛，发热，汗出，恶风，〔　　〕主之。」 → 桂枝汤.
- **组成 cards**: the composition, doses, preparation notes and preparation clause of the formula's 原方, with its best
  verse (方歌).
- **药性 cards**: flavour, nature, toxicity, channels and direction from the earliest entry and from the fullest later one.
- **经文 cards**: the first attestations of a term with the term blanked.
- **Anki**: `--anki cards.tsv` writes an Anki import file (tab-separated, HTML, tags in the third column); each answer
  ends with its source and passage id.
- **阅读门径**: for a topic — 源头经典 (the works where it first appears), 历代发挥 (the works of each period that treat it
  most densely, in date order), 专书 (works named after it), 临证医案 (case records), 近代汇通 (Republican works) — one
  row per work, each with the reason it is there. 温病: 素问, 灵枢, 难经, 伤寒论, 甲乙经 → 医经溯洄集, 尚论后篇, 温热逢源,
  温病指南, 外感温热篇 → 温病条辨 → case records → 止园医话.

## 研究数据集 (datasets)

`study dataset` writes a Frictionless *tabular data package*: `formula_witnesses.csv`, `formula_ingredients.csv` (with
the dose read in its period's measures), `herb_entries.csv`, `term_periods.csv`, `citation_edges.csv`, and
`datapackage.json` with field types and descriptions, the sources and licences involved, the corpus signature
(books, passages, sources, normaliser fingerprint, corpus digest) and the dosage notice. Rows carry passage ids and
locators, so every row can be traced back. **Only short quotes (≤ 120 characters) are exported, never the texts**; the
licences of some transcriptions allow local research use only.

## 深层发现 2.0 — the structure of the literature

The functions above answer questions about one formula, drug or term. The seven below read the structure of the
literature itself: how the witnesses of a work descend from one another, what later books did with a passage, which
parts of a classic were written when, how physicians treated patients visit after visit, how a text argues, when a
word changed its meaning, and what survives of the books that were lost. Three rules hold for all of them
([ADR 0005](adr/0005-deep-discovery-capabilities.md)):

- **Capabilities, not agents.** Each is a deterministic function of the study service, a tool of the tool mesh
  (`study.variants`, `study.stemma`, `study.witnesses`, `study.reuse`, `study.transmission`, `study.layers`,
  `study.dating`, `study.authorship`, `study.cases`, `study.trajectories`, `study.argument`, `study.senses`,
  `study.fragments` — permission `classics:read`) and a CLI command. The existing agents call them: the Philologist
  (collation, witnesses, layers, dating, authorship), the Skeptic (reuse, dating, argument), the Evidence agent (cases, trajectories, argument), the
  Semanticist (terms, senses) and the Scholar, whose term dossiers now carry 语义演变. No agent was added.
- **Candidates are not proof.** Whatever proposes with high recall — character probes, co-occurring concepts,
  clusters, an encoder's similarity — only proposes. Transparent rules over measured features decide, and every label
  carries the rule that fired and the values it read. An encoder's similarity is reported beside the features; no rule
  reads it.
- **Measured before trusted.** Each capability has an eval suite ([evals.md](evals.md)): synthetic data with a known
  answer where one can be built, a development set where the rules need examples, and a check on the real corpus
  against what the literature holds.

The examples below were computed on the store of the 2.0 release (926 books); those of 版本谱系 and 版本与影像见证 on the
current store (with the CMETA and 東亜医学協会 witnesses).

## 版本谱系 (collation and stemma)

**Witnesses.** The transcriptions of a work in the store (a witness split over volumes is joined in volume order:
`--books a+b`), or any books given with `--books`. Only the main text is collated: prefaces, tables of contents,
separated commentary layers and bracketed notes are left out. For a passage (`--text-mode`, `--passage`) the witnesses
are its copies and quotations, from the concordance.

**Base.** A coordinate system, not a claim about the right reading: by default the witness most of whose text the
others carry. Excerpts — witnesses carrying less than half of what the fullest one carries — are set aside first, so a
selection or a commentary that embeds the text does not become the base.

**Alignment.** Whole books are aligned by anchors: k-grams occurring exactly once in each text are paired, the longest
chain of pairs increasing in both texts (patience sorting) is kept, and the gaps are aligned again with shorter
anchors, then with `difflib`. Each witness's edits are projected onto the base's coordinates.

**Variant units.** The edits of all witnesses are merged into units — the smallest stretches of the base containing
every overlapping edit — and each witness's reading of a unit is the stretch aligned to it. Where the changes of
several witnesses meet in one unit (C 人 · EFG 若之 · DH 人之), the unit is split into columns by aligning its readings to
a centre, so that one witness's substitution does not merge with another's addition. Kinds: substitution (异文),
omission (脱), addition (衍), transposition (倒: an omission and an addition of the same ≤ 6 characters close by are one
move, 呕逆 → 逆呕), orthographic (readings that differ only by the equivalences of `collation.yaml`: 沉/沈, 藏/脏, 鞕/硬 …),
**lacunae** (omissions of 40 characters or more: missing text, not disagreement) and **structural** differences (added
commentary, different passages: listed, never used to group witnesses).

**Stemma.** The distance of two witnesses is their weighted disagreement in the units both carry, per 1 000 characters
of base text both carry (function-word variants weigh half, orthographic ones nothing). Neighbour-joining gives the
tree, rooted at the midpoint of its longest path (or `--root-at`); internal nodes are hypothetical exemplars (α, β …).
**Groups**: a minority reading shared by two or more witnesses is a candidate shared innovation (agreement in error).
Groups the tree holds support it; groups it cannot hold point to **contamination** — a witness whose shared readings
keep grouping it with a witness outside its clade (at least 0.2 of its group support, with a minimum support that grows
with the number of units), the direction read from which of the two carries the other's private readings. The most
frequent single-character substitutions are listed as candidates for `collation.yaml`. `edition <book>` sets one
witness against the others (agreement with each, singular readings, lacunae, additions); `tei` writes the apparatus in
TEI P5 parallel segmentation (`<app><lem/><rdg wit="…"/></app>`).

**Example (full corpus).** 伤寒论, nine witnesses — the two 笈成 texts (F 伤寒论(宋本), G 伤寒论), three transcriptions of
the 赵开美本 (D the 台北故宫 copy of 1599 and E the Japanese 安政 reprint of 1856, both from CMETA's page-by-page
collation, and A the 東亜医学協会 text), B the 康平本 (CMETA), H 注解伤寒论 (笈成), I 张卿子伤寒论 and J 注解伤寒论 (四库); the
康治本 (fifty formulas) shares too little text to be placed (overlap 0.034) and is set aside. Base G; 2 055 variant units,
1 682 of them substantive (78.2 per 1 000 characters; 373 orthographic). The tree is ((I, (H, J)), (B, ((F, G), (A, (D,
E))))): the 成无己 commentary tradition against the plain texts; among these the 康平本 on a long branch of its own, and
the three 赵开美本 transcriptions together (group ADE, support 38) apart from the 笈成 pair. Groups: HIJ 472, BHIJ 118 (the
康平本 shares readings with the commentary tradition), HI 78.5, HJ 72.5, ADE 38; I is flagged as contaminated from H
(0.29 of its group support). One difference is editorial practice, not transmission: in the 宋本 as printed (D, E) a
prescription follows its clause with no name line (「……可與麻黄杏仁甘草石膏湯。方二十六。」 then the composition); the
笈成 text and the 東亜医学協会 text supply the name (「麻黄杏仁甘草石膏湯方」), the latter marking it ※ as an editors'
addition. The per-chapter lists of the 宋本 (第二十六。（四味。）) are in D and E only. Five orthographic habits of the
prints found among the frequent substitutions (发/発, 去/厺, 草/屮, 枣/栆, 俱/倶) were added to `collation.yaml`.

金匮, six witnesses — the two 笈成 texts (D, E), the 邓珍本 in CMETA's collation (B) and in the 東亜医学協会 text (A), the
吴迁本 (C, CMETA, a 1395 manuscript copy of a Song print rediscovered in 2007) and the 四库 text (F): 4 234 units. The tree
is (F, (C, (B, (A, (D, E))))); the 吴迁本 and the 四库 text stand apart, yet share 362 units of support (CF), and the
四库 text is flagged as contaminated from the 邓珍本 (0.51) — consistent with its descent from the Ming prints of the
邓珍本 system, a hypothesis to examine in the units listed; the two transcriptions of the 邓珍本 group (AB 44.5).

## 版本与影像见证 (witnesses)

`study witnesses <work>` ([ADR 0006](adr/0006-witnesses-and-image-records.md)) answers the first question of any
textual study — what witnesses are there? — for the
transcriptions in the store and for the prints and manuscripts that libraries have digitised. The **text witnesses**
are the work's books in the store, each with its edition, year and holder (from the source catalogs: CMETA's
赵开美本 at the 台北故宫, shelfmarks 平图011603—011607, printed 1599), its source and licence, its passages, and whether
its passages link the image of their page (CMETA's editions do: a passage's `locator.image_uri` opens the page it was
transcribed from). The **image witnesses** come from the catalog harvested by `taochronos corpus images`
(`corpus/catalog/images/*.csv`, [data.md](data.md#image-witnesses-pluginsclassicsingestimagespy-corpuscatalogimages)):
digitised copies in NIJL's holders (研医会, 慶應 and 京都 富士川文庫, 東京大学 incl. the 鶚軒文庫, 九州, 東北), the
Staatsbibliothek zu Berlin (Sammlung Unschuld), the Library of Congress and 早稲田 (NDL's harvester is ready, its catalog
not yet built) — each with its date, print or
manuscript, shelfmark, IIIF manifest and terms of use, linked to the work by its title (`match`: exact, without volume
counts, without a print prefix; `·alias` when the title is another name of the work, the links to check first). A link by title is a candidate; the record's page is there to check it. No image is
downloaded: the manifest is the address from which a IIIF viewer loads the pages, and from which a future image layer
(page-level OCR, the collation of a print against its image) can fetch them.

<!-- witness-example -->
**Example (full corpus).** `study witnesses 伤寒论`: 10 transcriptions in the store — the 四库 注解伤寒论 (汪济川本, 1545), the 東亜医学協会 text and CMETA's two copies of the 赵开美本 (the 台北故宫 print of 1599 and the 安政 reprint of 1856), CMETA's 康平本 (the 1854 copy at Berlin) and 康治本 (1857), and the 笈成 transcriptions; 3 of them link every passage to the image of its page. And 28 digitised copies in libraries (21 with a IIIF manifest), dated 1668—1856 where the record gives a year — 東京大学総合図書館（医学・本草類，含鶚軒文庫） 9，早稲田大学図書館 7，京都大学附属図書館（富士川文庫） 5，研医会図書館 4，九州大学附属図書館（医学図書館） 2，慶應義塾大学信濃町メディアセンター（富士川文庫） 1; among them 家刻傷寒論、校正傷寒論、訂字標註傷寒論, linked through their print prefix.
<!-- /witness-example -->

## 语义复用与思想传播 (reuse and transmission)

**Two stages.** Candidates come from anything with high recall — the concordance's rare character probes (shared
wording) and the passage's rarest concepts found close together in another passage, in any of their written forms
(shared content). They prove nothing. The label is decided by transparent rules (`science.semantic_reuse`) over
features of the aligned pair:

| Feature | What it measures |
|---|---|
| `cov_source` · `cov_target` | the share of the source's wording found in the target, and of the target that is the source's wording |
| `longest_block` · `mean_block` | the longest run of shared characters, and the mean run |
| `concept_cov` · `concept_prec` | the source's content (its concepts, and content bigrams outside them) that the target expresses, weighted by rarity; the share of the target's content that comes from the source |
| `specificity` · `distinctive` | Σ credit × idf − log N — an E-value in nats: is what the two share rarer than chance among N passages? — and the credit of the source's most distinctive concepts. Genre concepts (太阳病, 脉浮, 恶寒) co-occur everywhere and prove nothing |
| `order` · `length_ratio` | the order concordance of the shared items; the target's length over the source's |
| `formulaic_share` | the share of the shared wording that is stock phrasing (以水七升，煮取三升，去滓 …: `intertext.yaml`) |
| `attribution` · `opposition` · `interpretation` | citation markers (《…》曰, 仲景云), refutation markers (非也, 岂, 殊不知, 未必, 误矣 …) and explanation markers around the span |
| `similarity` | the cosine of a TF-IDF encoder over concepts and bigrams — **reported, read by no rule** |

The later passage may be long (a commentary, a chapter of a compendium), so the reused span is located first: the
densest stretch of shared wording — then of shared concepts — no longer than three times the source; interlinear notes
are left out. The rules, in order: stock phrasing (套语相似) → unrelated or not specific (uncertain) → refutation
(引而驳之) → nearly all the wording both ways (直接引用) → most of the wording at a similar length (近似转录) → the source's
own words, fewer of them (节略) → half the wording or more, reworded (转述) → much shorter, with its content (撮要) →
content restated with explanation (解释性改写) → content in other words and in the same order (转述) → uncertain. Each
label carries its mode (retained / transformed / disputed), whether the citation is acknowledged (明引 / 暗引), the rule,
the values it read and a confidence from the margins. The thresholds are one table (`THRESHOLDS`) and can be
overridden.

**Transmission.** `transmission <work>` traces clauses spread evenly over the work's base witness (its earliest dated
transcription; 40 by default) through the corpus, keeps the later reuses and aggregates them: which works carry how
much of the work and how, the balance of retained, transformed and disputed reuse per period, and the **channels** — a
later work whose wording of a clause follows an intermediate work more closely than the source (counted once per clause
and work).

**Example (full corpus).** 「太陽之為病，脈浮，頭項強痛而惡寒」: 446 candidates examined in 4 s — 66 直接引用, 12 近似转录,
19 节略, 96 转述, 32 解释性改写; 111 of the reuses were reached only through their concepts, not their wording. The 局方发挥
quotes 「阴平阳秘」 in order to refute it (未必); the 医学正传 (岂可) and the 证治准绳 (误矣) do the same with 「邪之所凑」. The
reception of the 伤寒论 (12 clauses): the share of retained reuse rises from 53 % (魏晋) to 59 % (宋金元), 76 % (明), 73 %
(清) and 90 % (民国); the channels include 脉经 → 千金翼方 and 类证活人书 → 仲景伤寒补亡论 / 医学纲目.

## 文本地层 (stratigraphy)

**Layers.** The base witness is cut into chapters (long chapters into parts of about 800 characters; notes left out).
Each segment is profiled by the square root of the per-1 000 frequency of the work's 100 most frequent characters
(`--features function`: the function characters only — less sensitive to topic, but weaker), z-scored. k-means
(k-means++ starts, ten seeded restarts) splits the segments into `--k` layers with membership probabilities; the split
is tested against profiles whose features are shuffled across segments (R² against the null, a permutation p-value).
**Change points** in reading order: a local scan statistic tested by permutation and corrected for the places tried
(Benjamini–Hochberg), and binary segmentation; **layer boundaries** are where the layer changes for at least two
segments. **Outliers**: each chapter's Burrows' Delta from the rest of the work, as a z-score.

**Dating.** Chapter by chapter: the works cited in the main text (citations inside notes belong to the annotator) — a
terminus post quem when the cited work is dated; **late vocabulary** — lexicon terms that no other work uses until at
least 300 years after the work's date and that at least three later works use, as a rate per chapter z-scored within
the work (a thin early corpus makes some words of every early chapter look late; a later layer has many more); and the
taboo characters of the witness, which date its edition, not its composition.

**Authorship.** Burrows' Delta over the function characters between a text — or a book, or one of its chapters
(`--chapter-name`) — and candidate works (`--candidate`; by default the dated works of its category).

**Example (full corpus).** 素问, two layers: the minor layer holds all seven 运气 chapters (天元纪大论 … 至真要大论) with
阴阳应象大论, 阴阳离合论, 血气形志 and 气府论; it uses more 化, 火 and 太 and less 脉; the split is supported (p = 0.025).
The strongest change point falls at 65 | 66, where the 运气七篇 begin, and another at 74 | 75, where they end (both
p = 0.005); binary segmentation finds weaker ones elsewhere too (27 | 28, 49 | 52, and inside the 运气 chapters).
Late vocabulary singles out
至真要大论 (z = 4.26), 五常政大论 and 六元正纪大论. In the 伤寒论, 辨脉法 and 平脉法 are nearest the 脉经 — the tradition
ascribes them to 王叔和 — while the 六经 chapters are nearest the 金匮要略 and 伤寒例 the 甲乙经. Style says *that* chapters
differ, the dating evidence *when* they can have been written; neither alone proves an addition.

## 医案轨迹 (case records)

**Reading.** The case collections — one transcription per work, the fullest, so that no case is counted twice — are
read sentence by sentence. A case opens where a patient is named at the head of a sentence (王　十岁 · 某氏 · 一妇人年四十 ·
喻嘉言治石开晓，), after a date if one comes first (癸亥七月廿五日，伊，二十四岁), outside biographies and prefaces. A visit
opens at 二诊 / 复诊 / 又, at a date or a day marker heading a clause (十四日, 次日, 越三日), or at 前方加… heading a passage.
From each visit: the findings (the lexicon's symptoms and signs; a pulse only with a pulse quality; the tongue), the
diagnosis (diseases, patterns), the principle of treatment (explicit constructions only: 治宜…, 法当…, 用…法), the formula
(read from its context: 用/与/投…汤, …主之) and the drugs with their doses, the drugs added and removed (加… / 去…, not
去皮 or 去节), the number of doses (连进三帖) and the response (愈, 大减, 热退, 如故, 加剧, 遂死 … — in context; words of
response before a visit's own prescription answer the previous visit). The outcome is the last response recorded.
Every field keeps its passage id. The rules and vocabularies are in `cases.yaml`.

**Trajectories.** Each case becomes a sequence of visits, each a set of items (`principle:清热`, `formula:银翘散`,
`added:麦冬`, `finding:脉数`): sequential patterns across visits (PrefixSpan; support = cases), transitions from one visit
to the next (changes first, then continuations; lift over the next visit's baseline), and associations with the
outcome (one-sided Fisher tests, Benjamini–Hochberg). **Case records were written by their physicians and selected for
publication: these are associations in a biased record, never evidence of efficacy.**

**Example (full corpus).** 吴鞠通医案: 285 and 290 cases in its two transcriptions, read independently (case counts agree
to 0.98, outcomes to 0.92). 续名医类案: 3 246 cases, 151 of them ending in death. 咳嗽: 818 cases across the collections;
中风: 287, with sequences such as 苦寒 → 下法 and 益气 → 地黄饮.

## 医理论证 (argument graphs)

A passage is cut into clauses at punctuation and before an inner 则 or 故 (阳胜则热 → 阳胜 · 则热; not inside 法则, 否则 …);
each clause is a node with the concepts the lexicon finds in it, by category. The discourse markers of `argument.yaml`
give typed, directed edges: condition (若, 凡, …者), consequence (则, 必, 然后), cause (因, 由) and effect (…所致, 使然),
inference (故, 是以, 所以), support (盖, …故也), contrast (然, 但, 虽, 非独), analogy (犹, 譬), rebuttal (非…也, 岂, 殊不知,
谬矣), definition (…者，…也, 名曰) and treatment (…主之, 宜). One edge per pair of clauses, the most specific relation
kept; edges stay within a sentence, except inference and support (故 or 盖 opening a sentence reaches back); a clause
ending in 者 is a condition when its sentence goes on to a consequence or a prescription, otherwise a topic that the
next clause defines; 所以然者 announces a reason. **Only explicit markers are used: an unmarked step of reasoning is not
guessed.**

A work's profile counts the relations per 1 000 clauses, the categories of concept each relation links (symptom
—treatment→ formula; etiology —cause→ symptom) and the chains of steps (condition → consequence → treatment). Two works
are compared by the Jensen–Shannon divergence of these distributions and by log-odds z-scores with an informative prior.

**Example (full corpus).** 伤寒论 against 温热论: JSD 0.063 over the relations. The 伤寒论 favours definition and
inference; the 温热论 favours analogy (7.76 per 1 000 clauses, against none) and rebuttal, with more conditions and
treatments — it teaches by likeness and correction, where the 伤寒论 defines and infers.

## 语义演变 2.0 (senses)

Occurrences of the term, in all its written forms, are sampled period by period (up to 300 per period) and read in a
window of twelve characters on each side: the lexicon's concepts and the content bigrams there. The curated senses of
`terminology.yaml` label the contexts their cues fit (cue hits minus twice the anti-cue hits; a tie stays unlabelled).
The contexts no sense fits are clustered (spherical k-means over TF-IDF vectors); a cluster of at least five contexts
with vocabulary of its own is a **candidate sense** the curation lacks, shown with its distinctive words and examples
for a person to read and name. The shares of the senses by period give the series; **change points** are the dates
that split the labelled occurrences into the most different sense distributions (n₁n₂/n × Jensen–Shannon, permutation
test), sought again before and after each (up to three). The term's neighbourhood — its most characteristic context
words in each period — is compared from period to period (Jaccard overlap). The curated exemplar passages check the
labelling.

**Example (full corpus).** 消渴: change points near 166 (p = 0.025), 388 (p = 0.005) and 1603 (p = 0.005); the symptom
sense falls from 21 % of the labelled uses to 0–6 %, and returns to 11–13 % in the Qing and the Republic.

## 佚书辑佚 (lost works)

Lost works survive in quotation. The 外台秘要 opens its entries with their source (小品论曰, 《深师》疗…, 千金…; 又 for "the
same source again") and closes them with a note on where the source had it (（出第十卷中千金同）: volume ten, the same
text in the 千金); the 医心方 and later compilations cite in the same way, and any book may quote 《小品方》云…. `fragments
<work>` finds these attributions under the work's title and aliases and takes the attributed text up to the source
note, or up to the next attribution to another source. It keeps the note's volume and parallels, follows 又 only after
a noted head or when it is marked 又云 / 又曰, and drops fragments under twelve characters. The same fragment quoted in
several books is merged (3-gram overlap), and the fragments are ordered by the volume the notes give, then by where
they are quoted. Quoting books dated before the work are set aside, and every fragment keeps its witnesses.

**Verification.** A method that gathers lost text cannot be checked on lost text, so it is checked on works that
survive. `--verify` rebuilds a surviving work from the books that quote it, with its own transcriptions excluded. It
then measures two things. The first is the share of fragments found in the surviving text (6-grams, at least 30 %),
overall and per quoting book: this says how far each compiler can be trusted. The second is how much of the work is
recovered.

**Example (full corpus).** 小品方: 132 fragments from 190 quotations (外台秘要 in two transcriptions, 妇人大全良方, 千金 …).
Its modern 辑校本 is in the store now (a layer-separated modern edition, [ADR 0007](adr/0007-modern-apparatus-as-layers.md)),
so `--verify` measures the gathering against it: 90 of the 132 (68 %) are in it, and they cover 10 % of it — the rest
of the 辑校本 comes from the 医心方, which the corpus lacks, and from the 尊经阁 manuscript of 卷一. Verification on the
千金要方: 32 % of the fragments
attributed to it are in its surviving text (幼幼新书 0.83, 外台秘要 0.55, 医心方 0.36 — compilers quote with different
freedom), and they cover 12 % of it. For the 肘后备急方, 87.6 % of its quotations are *not* in the extant 肘后 — a reworked
remnant (葛洪 → 陶弘景 → 杨用道's 附广). They are candidate lost text, which is what 辑佚 recovers.

## Data files

| File | Content |
|---|---|
| `domains/classics/taboo.yaml` | taboo rules: ruler, start year, character, spellings (pairs or formula suffixes), note |
| `domains/classics/metrology.yaml` | units and their ratios; per period the 两 in grams and the 升 in ml (ranges), the value of 分, sources; the notice |
| `domains/classics/physicians.yaml` | ~70 physicians: names, 本草 short names, dynasty, life or active years, school |
| `domains/classics/drug_families.yaml` | drugs compared as one in compositions (桂, 地黄, 芍药, 术, 甘草, 附子, 山药, …) |
| `corpus/catalog/external-works.yaml` | works known through citations, including lost works known only through them |
| `domains/classics/collation.yaml` | orthographic equivalences for collation (沉/沈, 藏/脏, 鞕/硬, 耆/芪 …): variants in the apparatus, never grouping evidence; graphic confusions (已/巳/己) deliberately left out |
| `domains/classics/intertext.yaml` | citation, dialogue, refutation and explanation markers, and the stock phrases of the genre (以水七升，煮取三升，去滓 …) |
| `domains/classics/cases.yaml` | case and visit openers, day markers, sections that file no cases, pulse and tongue patterns, principles, changes, doses, words of response |
| `domains/classics/argument.yaml` | discourse markers of reasoning by relation (lead / tail, direction), the markers that split a clause (则, 故) and their exceptions |
| `<data>/corpus/study-cache/` | the entry-heading index, the citation network and transmission results, keyed by a digest of the store, the normaliser and the book records |

## Limitations

- Extraction is rule-based: formula lists, drug entries and properties are read with patterns and a lexicon. Groups of
  one witness (孤例) and unusual layouts need checking by hand; every output quotes what it read.
- The lexicon decides what counts as a drug: a missing name (a rare drug, a regional name) leaves a composition
  incomplete; harvested names are candidates.
- Citations in undated notes inherit the date of the text they annotate unless they are anachronistic; the 孙星衍
  notes in the 本经 still count as Han citations of the 说文.
- Metrology values and taboo start years are scholarly positions with sources; they can be disputed and edited.
- Taboo evidence and dating by terminus ante quem are conservative, not proof.
- 版本谱系: the base is a coordinate system; readings are grouped by normalised text, so orthographic habits not yet
  in `collation.yaml` still count as substantive until reviewed. A stemma of transcriptions is a hypothesis about
  their relations, and contamination flags ask for a person to examine the units listed. Transcriptions differ in
  editorial practice as well as in their exemplars (names supplied for prescriptions, notes kept inline or apart,
  lists of contents): such differences are structural, and are read in the units before they are read as descent.
- 版本与影像见证: image witnesses are linked by title only; commentaries and works of the same title are separate works
  that the title cannot tell apart, and a record's date is the catalogue's (a Japanese era alone gives its span). The
  NIJL records are enriched from their manifests only when linked (`--enrich all` for every record).
- 语义复用: the thresholds were set on a development set of 33 author-constructed pairs; concepts come from the
  lexicon, so a reuse through words the lexicon lacks is found only by its wording. Direction is by date: pairs whose
  dates overlap are reported as undetermined.
- 文本地层: style separates chapters by topic as well as by author (运气 chapters are about 运气); the dating evidence
  depends on the dates of the catalog and on how thin the early corpus is. Neither proves an addition alone.
- 医案轨迹: the parser follows the manners of the collections it was written for (visits under a heading, narratives);
  other layouts can merge or split cases. Outcomes are what the physician recorded.
- 医理论证: only explicit markers make edges, so terse texts look less argued than they are; the counts compare
  manners of writing as much as ways of reasoning.
- 语义演变: senses are only as good as their curated cues; candidate senses are clusters of context words, not
  meanings, until a person reads the examples.
- 佚书辑佚: attribution conventions differ between compilers, and a compiler may paraphrase; the per-book precision
  of the verification is the measure of how much to trust a fragment.
