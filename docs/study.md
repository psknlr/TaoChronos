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
| `study punctuate` | 句读 — where do the marks of this 白文 go? | the text with marks only (every character kept), each mark's probability, doubtful places; a punctuated input compared with its editors |
| `study clause` | 条文结构 — what are the parts of this clause? | pieces with their roles (前提 病 症 脉 证 治则 禁忌 方 组成 煎制 服法 加减 预后) and the terms they name; a work's forms |
| `study glosses` | 训诂 — how did the commentators gloss this word? | glosses (…者…也, 貌, 音, 反切, 读为, 当作, 一作) by commentator and date, the readings and who gave each first; a commentary's glossary |
| `study commentaries` | 集注 — what did each commentator say on this clause, and how do they relate? | the commentaries aligned to the clause in date order; 照录 承袭 同解 增益 异解, explicit 驳 and 从, consensus and singular readings |
| `study disputes` | 争议 — who rejected whose view on this? | named views rejected or endorsed, about a term or of a physician, with the reporting work; who rejects whom corpus-wide |
| `study cruxes` | 校勘疑义 — which words of this clause did the commentators doubt? | per clause (or for a whole work) the statements of transposition, emendation, interpolation, omission or doubt, their target words and proposed reading, and who made them; `--write-registry` writes the registry the support reading consults |
| `study pairs` · `network` | 配伍与方证网络 — which drugs go together, and which formulas answer which findings? | drug pairs against chance (lift, PMI, NPMI, odds ratio with its 95% CI, Fisher + BH), a drug's partners by period; over the corpus the drugs written most often, association rules (support, confidence, lift), the groups of drugs and a clustering of the most frequent (average linkage, a dendrogram); a formula's findings and drugs, a finding's formulas |
| `study schools` | 学派 — what sets a school apart, whom did it cite and dispute? | its members and works; the words and formulas it uses more than the other authors of its time; homophily, citing and cited schools, rejections; the school-by-school matrix |
| `study names` | 名称 — what was this drug or formula called, when? | each name's works by period and century, the first to write it, when the preferred name changes, passages equating names, names the lexicon lacks |
| `study chain` | 传播链 — through which earlier witness did each later copy or quotation come? | the passage's dated witnesses as a tree by shared innovations, each edge with its evidence and margin |
| `study entities` | 实体识别 (T7) — what does this passage name? | entities in 24 types (disease, syndrome, symptom, pulse, tongue, formula, herb, dose, preparation, physician, commentator, book, place, time …) with their references, ambiguity and negation; a model, when configured, types the ambiguous and adds the missed as exact spans |
| `study translate` | 释义与今译 (T10) — what does this passage say, layer by layer? | the original (never changed), normalised, punctuated, interpreted (glosses with who first gave them, the sense the date and context favour) and, with a model, a modern Chinese translation that cites its glosses and passes the presentism guard |
| `study places` | 地域 (T27) — where did physicians come from and books appear, and does a term or a school lead in a region? | native places and places of writing (author and signed prefaces), a place's physicians and works, region × period shares of a term or a school with z tests and Benjamini–Hochberg, GeoJSON |
| `study compare` | 方剂比较 — how do these formulas differ in drugs and doses? | each formula's 原方 (or 通行方) witness, its drugs by family with doses, ratios (largest weight = 1) and shares; per pair: shared and own drugs, Jaccard, dose-weighted overlap, dose changes and a verdict (同方 / 同药异量 / 加减化裁 / 异方) |
| `study family` | 类方 — which formulas were made from this one? | the base's core (the drug set most works write); every formula whose written-out compositions hold that core and add few drugs, as 加味 / 减味 / 加减 / 同药异量 / 同方异名, with the drugs added and removed, works, earliest witness and 合方 |
| `study usage` | 用药谱 — how was this drug prescribed through the periods? | its share of the compositions by period (Wilson intervals, trend test); decoction doses by period in 两 and grams (M (P25, P75), x̄ ± s, a Kruskal–Wallis test across periods, Spearman's ρ with the year; a box plot and a scatter with its LOESS curve), the batch doses of pills, powders and 煮散 apart; how often it is the largest dose; preparation notes; partners with lift; formulas |
| `study properties` | 药性谱 — what did the 本草 say of these drugs, side by side? | flavours, natures, toxicity and channels (as organs), the share of works stating each and the first to state it; a formula's 原方 profile weighted by dose |
| `study incompat` | 配伍禁忌 — who said which drugs are 反 or 畏, and which formulas still write them together? | statements of 反 / 畏 with their earliest witness and works by period; where the verses of 十八反 and 十九畏 are written; compositions holding both drugs of a pair; a formula or a list of drugs checked against the pairs |
| `study protocol` | 研究方案 — how would one research this question? | the question read into kinds and entities; hypotheses with prediction, test, falsification and rivals; scope, variables, methods (each a tool with its command), analysis, the figures planned (图 1 … with their form) and the tables (表 1 …: three-line tables filled with the pilot's numbers, or shells with placeholders and their statistics where the pilot did not run the step), quality, limitations, ethics, timeline; a research contract; a pilot run with its charts |

Page images and OCR output (T1–T2) are read by `taochronos vision` (layout, a model's reading, comparison with the
store); descriptions are carried across to modern medicine by `taochronos bridge` ([bridge.md](bridge.md)); a claim is
checked by `taochronos audit` ([v2.md](v2.md)).

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

# 方药研究 and 研究方案 (--charts DIR: the result's figures in the journal style — SVG, numbered, and all of them as one
# figure in panels — with their CSV and JSON, and its three-line tables as Word, LaTeX, CSV and Markdown)
taochronos study compare 桂枝汤 麻黄汤 葛根汤 --charts figures     # --which current: compare the 通行方
taochronos study family 桂枝汤                                     # --min-share 0.75 --max-extra 4
taochronos study usage 半夏 --charts figures
taochronos study properties 黄连 黄芩 黄柏                        # or --formula 小柴胡汤
taochronos study incompat 甘草                                     # a drug, a formula, --herb 甘草 --herb 甘遂, or nothing: the whole rules
taochronos study protocol "十八反之说何时形成？后世何方仍将反药同用？"  # --no-pilot: the protocol without its pilot run

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

# 任务规格 v1.0 (docs/tasks.md)
taochronos study punctuate "太陽病頭痛發熱汗出惡風桂枝湯主之"        # or --passage <id> · --input <file>
taochronos study clause "太阳病，头痛，发热，汗出，恶风，桂枝汤主之。"  # or --work 伤寒论
taochronos study glosses 几几                                      # or --book <id>: a commentary's glossary
taochronos study commentaries "太阳之为病，脉浮，头项强痛而恶寒。"
taochronos study disputes 相火                                     # --person 丹溪 · nothing: who rejects whom
taochronos study cruxes --work shanghanlun,jinkui --write-registry  # or a clause, or --passage <id>
taochronos study pairs 桂枝 --period 宋金元                         # nothing: the strongest pairs and the groups
taochronos study network 桂枝汤                                     # a finding (脉浮) gives its formulas
taochronos study schools 温病 --probe 营分 --probe 膜原              # nothing: every school and the matrix
taochronos study names 山药
taochronos study chain "病人脏无他病，时发热自汗出而不愈者，此卫气不和也。先其时发汗则愈，宜桂枝汤。"
taochronos schema --study chain                                    # the output schemas of docs/tasks.md
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
twelve rarest probes (by index frequency), the rarest probe of each segment of the query's own punctuation (the index
does not cross a mark, and one variant character — 藏 for 脏 — must not hide a witness from every probe) and the five
rarest of all segment probes retrieve candidate passages; a candidate must contain at least two of them. Each candidate is aligned with the query (`difflib`), cropped to the densest aligned block, and scored by
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

《本经》 is read as the 神农本草经 (`citations.yaml`), not as the Qing 本经逢原 whose title begins with it: a title's prefix is
not taken for an abbreviation where the tradition has its own.

## 要籍 (canon)

`taochronos study canon --write-catalog` ranks the works of the corpus by the citation network above and writes the first
535 (`CANON_SIZE`; 350 until October 2026) to `corpus/catalog/canon.yaml` (metadata only).  The ranking is total, so a
longer list keeps the head of the shorter one; `--extend` keeps the works already listed, in their order, and appends the
next ones of this ranking — the way to lengthen the list from a store that lacks some sources of the first ranking (the
web client's packing never reads `NEVER_PACKED` sources, [web.md](web.md#要籍语料--the-browsers-corpus)).  `taochronos web
canon` does both steps on the full store — the catalog, then the browser's corpus — and so does the `canon` workflow
(`.github/workflows/canon.yml`), which lengthened the list to 535 on 2026-10-11: ranks 1–350 as ranked below on the full
corpus, 351–535 appended from its ranking of the site's corpus parts (757 works there).  For each work: **influence**, the distinct works that cite it (a citing
work older than it by more than 30 years is a misresolved title and is not counted); **breadth**, the periods in which it
is cited; **volume**, its citations in all; **transmission**, its witnesses in the corpus; **siku**, whether the 四库全书
editors took it into 子部·医家类.  score = 10·log₂(1+influence) + 2·breadth + 2·log₂(1+volume) + 3·log₂(1+witnesses) +
6·siku; ties fall to the earlier work; non-medical and post-1949 works are not ranked.  Each entry also records its
sources and whether one of its witnesses is under an open licence (CMETA, 汉籍仓库, 维基文库, McGill, 笈成) — the web
client's corpus takes those first ([web.md](web.md#要籍语料--the-browsers-corpus)).  `taochronos study canon [words]` and the tool `classics.canon` list the
works (filter by title or author, dynasty, category; `held: true/false`) and say whether the current corpus holds each.

**Result (full corpus, 759 works ranked).** 1 黄帝内经素问 (cited by 365 works), 2 灵枢, 3 金匮要略, 4 难经, 5 伤寒论,
6 神农本草经, 7 千金要方, 8 脉经, 9 甲乙经, 10 外台秘要, … 14 本草纲目, 17 医宗金鉴, … 39 温疫论; every one of the first 350
is cited by at least two later works; 137 are Qing, 73 Ming.  The 185 appended (351 形色外诊简摩 … 535 证治准绳·类方) are
mostly Qing (122) and Ming (34); citations thin out there — 161 are cited by fewer than two later works, the last 46 by none
(五十二病方, lost until 1973; 针灸问对) — so their order rests on witnesses, volume and the 四库.  It reads what this corpus
quotes: late works have had less time to be cited, and works known only through quotations (佚书) are not in it.

## 方药研究 (herb and formula research)

Five studies read the compositions, the 本草 entries and the 七情 notes of the corpus together.  They share the harvest
of `study pairs` — every composition the store writes out, read once and cached per corpus state (`harvest@3`): the
work, the formula, the drugs by family (桂枝, 桂心, 肉桂 → 桂), each drug's dose and preparation note as written, and the
form the preparation after the drugs makes of them (汤剂, 丸剂, 散剂, 煮散) — one row per work and composition, so that a
formula copied in many editions of one work counts once.  Formulas and drugs are those of the lexicon: the curated one,
and in the browser's corpus the supplement and the core of the harvested lexicon (`domains/classics/lexicon-supplement`,
`lexicon-core`; [data.md](data.md)).

* **方剂比较 (`compare`)** takes two to six formulas, each as one witness writes it: its 原方 (the earliest tradition of
  `study formula`) or, with `--which current`, its 通行方 (the most witnessed).  Doses written in weights are read in 两 of
  the witness's period; counts (枚) and volumes are compared only within their unit.  Each formula gets its ratios (its
  largest weight = 1) and shares of the total weight; each pair its shared and own drugs, Jaccard, the dose-weighted overlap
  (the sum of the smaller share of each shared drug), the dose changes beyond a tenth, and a verdict: 同方, 同药异量, 药味相同
  （剂量未能比较）, 加减化裁 (Jaccard ≥ 0.5) or 异方.
* **类方 (`family`)** starts from the base's core — the drug set most works write under its name — and finds every formula
  whose compositions hold at least `--min-share` (0.75) of the core and add at most `--max-extra` (4) drugs: 加味, 减味,
  加减, and, when the drugs are the same, 同药异量 or 同方异名 by the median share of each drug's weight.  A member that also
  holds the core of another formula (three drugs at least, two beyond the base) names it as its 合方.
* **用药谱 (`usage`)** counts, period by period, the compositions holding a drug (Wilson intervals; a Cochran–Armitage test
  for a trend), its doses as written and read in 两 and grams (median and quartiles), how often it is the formula's largest
  dose (a clue the literature reads as the 君药, not a judgement of 君臣佐使), its preparation notes, the drugs written with it
  (count and lift) and the formulas.  Doses are compared across periods for decoctions only: a pill's, a powder's or a
  煮散's amounts are the batch it is made in (宋 方书 write many a 汤 as a powder boiled by the spoonful: 右为粗末，每服三钱，水一
  盏，煎至七分), so they are summarised by form apart.  The form is the preparation's when it says one, else the name's.
* **药性谱 (`properties`)** sets the readings of `study herb` side by side for several drugs or a formula's drugs: the
  flavours (味微苦而甘 reads 苦 and 甘), the five natures (大寒, 微寒 → 寒), toxicity and channels, each with the share of the
  works stating it and the first work to state it; channels are also read as organs by the usual correspondence (手太阴 →
  肺), and a list keeps its hand or foot (入足厥阴、太阴、少阴经 is 足厥阴, 足太阴 and 足少阴).  For a formula, its profile is
  weighted by the dose of each drug in its 原方.
* **配伍禁忌 (`incompat`)** reads 十八反 and 十九畏 in the texts, from `incompatibility.yaml` (the groups of the two verses, and
  the names each drug goes by): every statement of 反 or 畏 followed by a list of drugs, its subject (the entry's heading,
  else the drug whose note it is in or that its sentence opens with — never another drug's 使 or the object of 恶), quoted
  as its whole sentence; the earliest witness and the works by period of each pair (a 辑本 such as the 神农本草经 is dated as
  the lost work, so the earliest other witness is given too); pairs stated that the verses lack; where the verses are
  written; and the compositions writing both drugs of a pair (甘遂半夏汤 writes 甘遂 with 甘草).  A formula or a list of drugs
  is checked against the pairs.

All five read what the texts write, not what was done or whether it was sound: a composition counts once per work, what
was not written down is not counted, and a 反 written in a book is a text, not a pharmacological finding — the modern
warnings are `modern.safety`'s.

## 研究方案 (research protocols)

`study protocol` turns a question into a protocol that can be carried out and checked.  The question is read against the
lexicon (the formulas, drugs, findings and terms it names) and the period expressions (宋代以前, 明清; a question on both
sides of a date — 宋代以前与以后 — is a comparison split there); its kinds are told by its words and what it names: 方源考,
方剂比较, 类方, 药性源流, 用药谱, 配伍规律, 配伍禁忌, 方证关系, 术语源流, 名称考, 古今对照.  Each kind contributes, in the question's
own names:

* questions and **hypotheses** — each with its prediction, the test that decides it, what would refute it and the rival
  explanations to rule out.  A name is read for what it claims: 白虎加人参汤 is 白虎汤 加 人参, 桂枝去芍药加附子汤 is 桂枝汤 去 芍药
  加 附子, so the comparison's first hypothesis is that one is the other so changed (with the rival that the added drug was
  already in the base: a dose raised, 同药异量); 桂枝加桂汤 adds the drug its base is named after, so there the hypothesis
  is the raised dose itself;
* the **scope** (the corpus, its sources, the period, the 要籍 of the kind's categories to read first, what is included and
  not), the **variables** and how each is read off the texts, the **methods** — each a capability of this system with its
  arguments and the command that reruns it — the **analysis** (statistics and corrections), the **figures** planned, the
  **quality** checks, the **limitations**, the **ethics** (no clinical advice; doses are historical readings; the modern
  warnings for the toxic drugs named) and a **timeline**;
* a **research contract** for `taochronos research` (focus terms, tracks, period, forbidden assumptions).

With the pilot (the default; `--no-pilot` or `pilot: false` skips it) the main steps run once at their default settings:
the protocol then says how much the corpus holds — compositions, works, periods, the earliest witness — whether that is
enough, and carries the pilot's charts; its background cites witnesses, never memory.  It plans research and concludes
nothing.  The result carries the protocol as a document (`document`: the Markdown page, sections numbered as they come),
which the web client offers to download; the model reads the structured protocol instead.  A formula the question names
that the lexicon lacks (桂枝加桂汤 in a corpus without the harvest) is read by its shape — characters up to 汤, 散, 丸, 饮,
丹 or 膏 — never as the drug inside its name, and the limitations say its witnesses are searched by that name only.

The protocol plans its figures and tables as a paper will print them: **图 1 …**, each with its form in words (Tukey 箱线图,
森林图, 散点图, 聚类树状图 …) and the tool that draws it, and **表 1 …** (`table_shells`): each kind's three-line tables, each
naming the study table that fills it.  Where the pilot ran that step, the table holds the step's numbers — the same rows
the study prints (usage: the share of compositions by period with its Wilson interval, the decoction doses as M (P25, P75)
and x̄ ± s with the Kruskal–Wallis and Spearman tests; pairs: each partner's confidence, lift, OR (95% CI) and P; a
formula's witnesses by period and group, and the doses of the witnesses compared; …) — titled …（预试验） and noted as a
first machine reading, to be recomputed and checked against the texts.  Where it did not (the pilot runs three kinds at
most, finds too little, or is skipped), the table is a shell: its column heads (grouped where a paper groups them), a row
of placeholders under each stub in the notation the numbers will take — ×× (××.×) for n (%), ××.× (××.×, ××.×) for
M (P25, P75), ×.×× (×.××–×.××) for an odds ratio and its interval, ×.××× for P — and the statistics behind them, titled
…（模板）.  The document prints them as tables, the result carries them as three-line tables (`tables`) that the page copies
into Word or downloads as a Word document, and the model reads the filled ones' heads, notes and first twelve rows (the
standing instructions forbid it placeholders and invented numbers in a table: a number no tool returned is 未得).

## 图表 (charts)

The results of `formula`, `herb`, `term`, `pairs`, `network`, `names`, `senses`, `compare`, `family`, `usage`,
`properties`, `incompat` (and a protocol's pilot) carry their charts under `charts`: small declarative specifications
(`study/charts.py`, version 1) drawn from the full result before it is trimmed for a model — line (with an interval band),
bar (grouped, with whiskers), hbar, stack (counts or shares), heatmap, range (quartiles and whiskers), **box** (a Tukey box
plot: quartiles, whiskers to the furthest value within 1.5 IQR, the mean, the values beyond the whiskers and, when there
are few, every value beside its box; n under each), **forest** (estimates with their intervals on one axis, a log axis and
a line at 1 for odds ratios, the estimate and its interval written beside each row, the rows not significant after
Benjamini–Hochberg in grey), **scatter** (with a LOESS curve, a bubble's size or up to three groups), **dendrogram** (a
clustering's tree with its cut and its clusters in colour), timeline and network.  Each has a title, a subtitle that says
what is counted and which test gave which number, the rows and their columns (the table and the CSV), and a note and
source line: the caveat that goes with the numbers (machine reading; doses are historical readings, never dosage
guidance) and the corpus version.  A chart adds no inference: its numbers are the result's.  The values a figure draws
one by one (each dose, a tree) travel in the result's `_raw` until the charts are built, and are then taken out: the model
never reads them.

A figure is drawn in one of two styles of one layout (`study/svg.py` in Python, `web/js/chart.js` in the page):

* **journal** (期刊样式) — as a journal prints it: white, black L-shaped axes with outward ticks, no grid, the y-axis title
  turned along its axis, square bars, error bars with caps, sans-serif text at 8 pt of the printed width — 85 mm a single
  column, 120 mm one and a half, 175 mm two — a physical size in millimetres, and its number and caption under it
  (**图 1**　title。what it shows。, then its notes and source); several charts of a result as **one figure in panels**
  (A, B …, each with its short title; one caption: （A）…；（B）…, the notes once, the sources once);
* **screen** — the page's: the title above, a recessive grid, 4 px rounded data ends.

* `taochronos study … --charts DIR` writes each chart as a journal figure (SVG, numbered 图 1, 图 2 … in order), a CSV table
  (UTF-8 with a byte-order mark, for spreadsheet programs) and its JSON specification, all of them as one figure in panels
  (`<stem>-figure.svg`), and the result's tables (below).
* The web client draws them under the step of the tool that made them, in the tool console, and in the ```chart blocks the
  model writes — with hover and keyboard read-outs, a table view, the journal figure in the page, and exports (SVG, PNG and
  TIFF at 300 or 600 dpi, CSV, JSON) ([web.md](web.md#图表--charts-and-their-downloads)).  The model reads only their
  titles (`charts_shown`).

The marks follow one specification: thin, solid, a recessive grid and axes; whole-number ticks for counts; categorical
colours in a fixed order validated for colour-vision deficiency (light and dark), never a ninth hue — the rest is 其他, in
grey — and a category keeps its colour in every chart of a result (`groups`); one hue, light to dark, for magnitude; a
legend for two series or more, never naming two series alike (two witnesses of one book are told apart by their juan,
新编金匮要略方论·卷1（219）); values and labels in ink, never in a series colour.

**Labels keep apart** at every width, in both renderers: a timeline's labels take lanes where no other label is and,
among those, where the fewest stems cross a label — a label at the right edge turned to the left of its dot, the turned
ones placed from the edge inwards — within two lanes more than the compact layout needs; a stem that must still pass a
label is broken around it (no grid on a timeline: the stems are the guides).  Category labels that do not fit their band
turn 40° while neighbours clear each other, stand upright in a narrower band, and only every k-th is written in a band
narrower than a line of text; a name longer than its room is cut with an ellipsis (the table and the hover keep it
whole); a value over a bar is written when every one fits, a line's end value where it clears the other labels, dots and
lines (else the hover has it); a heatmap's colour scale narrows, then moves left, to stay inside a single column; the
count of a box plot's values past its axis (▲n) has a row of its own under the axis title; a scatter's axis title and
bubble key sit clear of a bubble at the top; a ring of nodes writes each name along its radius.
`tests/test_figure_layout.py` draws crowded figures with both renderers at a screen's widths and a journal's and checks
them in Chromium (`tests/collisions.js`): no label over a label, over a dot, a stem, a line or a bar, or off the figure.

## 表格 (three-line tables)

The same results carry their tables under `tables` (`study/tables.py`, version 1): the numbers a paper reports, put in the
form a journal prints — a **three-line table** (三线表): the title above with its number (表 1　…; a page numbers a result's
tables in order), a rule over the column heads, a rule under them and a short one under each group head (two heads over
three columns: 折合克数（g）over M (P25, P75), x̄ ± s and 范围), a rule under the last row, no vertical lines; the notes below —
what each abbreviation means, which test gave which number (Cochran–Armitage z and P, Kruskal–Wallis H, df and P,
Spearman ρ, Fisher with Benjamini–Hochberg), how the texts were counted — and the source.  The statistics are written in
their usual notation: n (%), M (P25, P75), x̄ ± s, a 95% CI as 62.3–98.4, an odds ratio as 2.43 (0.09–67.6), P to three
decimals and P < 0.001 below (* when significant after Benjamini–Hochberg).

| study | its tables |
|---|---|
| `usage` | 各时期写出组成中含该药的比例; 历代汤剂中的用量 (in 两 and grams, the tests in the notes); 各剂型的原书剂量; 同用最多的药物 |
| `pairs` (a drug) | 同方的药物及其关联强度 (confidence both ways, lift, OR (95% CI), P) |
| `pairs` (the corpus) | 高频药物; 药物关联规则; 显著药对; 高频药物的聚类 |
| `compare` · `family` | 组成与剂量 (each formula's dose and ratio); 方剂两两比较; 类方 |
| `term` · `herb` · `properties` | 各时期的出现率 (per 10 000 passages, 95% CI); 历代本草所言之性味, 各项性能的首见; 性味归经 |
| `incompat` · `network` | 言“反”“畏”的著作与最早见证, 同见于写出的组成; 方证对应 |
| `formula` | 写出组成的类别; 见证（按时期与组成类别）; 各见证的剂量与配伍比例 (the dose as written, the ratio to the largest weight) |
| `names` · `senses` | 各名称的历代使用 (the works writing each name, n (%), the name preferred; its changes); 各义项的历代份额 (and the change point) |

`study/tablefmt.py` writes a table as **Word** (.docx: a real Word table with its three rules, its header rows repeated on a
new page, 宋体 and Times New Roman at 10.5 pt, written with the standard library — several tables make one document),
**LaTeX** (`booktabs`: `\toprule`, `\midrule`, `\cmidrule`, `\bottomrule`, in a `table` float with `\caption` and `\label`;
Chinese needs `ctex` with XeLaTeX), **CSV** (with a byte-order mark), **Markdown** and **HTML** with its rules inline (it
pastes into Word as a three-line table).  Statistical symbols are set in italics where the format has them (P, n, z, H, t,
r, ρ, q, x̄, s).  `--charts DIR` writes each table as .csv, .tex and .md, and all of them in `<stem>-tables.docx`.  The model
reads only the tables' titles (`tables_shown`); the page prints them ([web.md](web.md#图表--charts-and-their-downloads)).

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
Staatsbibliothek zu Berlin (Sammlung Unschuld), the Library of Congress, 早稲田 and the NDL Digital Collections — each
with its date, print or
manuscript, shelfmark, IIIF manifest and terms of use, linked to the work by its title (`match`: exact, without volume
counts, without a print prefix; `·alias` when the title is another name of the work, the links to check first). A link by title is a candidate; the record's page is there to check it. No image is
downloaded: the manifest is the address from which a IIIF viewer loads the pages, and from which a future image layer
(page-level OCR, the collation of a print against its image) can fetch them.

<!-- witness-example -->
**Example (full corpus).** `study witnesses 伤寒论`: 10 transcriptions in the store — the 四库 注解伤寒论 (汪济川本, 1545), the 東亜医学協会 text and CMETA's two copies of the 赵开美本 (the 台北故宫 print of 1599 and the 安政 reprint of 1856), CMETA's 康平本 (the 1854 copy at Berlin) and 康治本 (1857), and the 笈成 transcriptions; 3 of them link every passage to the image of its page. And 33 digitised copies in libraries (26 with a IIIF manifest), dated 1668—1856 where the record gives a year — 東京大学総合図書館（医学・本草類，含鶚軒文庫） 9，早稲田大学図書館 7，国立国会図書館 5，京都大学附属図書館（富士川文庫） 5，研医会図書館 4，九州大学附属図書館（医学図書館） 2，慶應義塾大学信濃町メディアセンター（富士川文庫） 1; among them 家刻傷寒論、校正傷寒論、訂字標註傷寒論, linked through their print prefix.
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

## 任务规格 v1.0 — the capabilities added with docs/tasks.md

The [task specification](tasks.md) maps the 27 tasks of the roadmap onto TaoChronos; the capabilities below were
added with it. Each is a study function, a tool (`study.*`), a CLI command, an evaluation suite and a JSON Schema of
its output (`taochronos schema --study`, checked by the tests against real results).

### 句读 (punctuate)

A discriminative model learned from the store's editorially punctuated texts decides, at every gap between two
characters, whether a mark goes there and which (，。；：、？！ and the openings and closings of quotations and notes).
Its features are character n-grams around the gap and the lexicon's terms; the thresholds are set on development
works. The output inserts marks and **never changes a character** (`preserved` is checked on every input). A punctuated
input is stripped, punctuated again and compared with its editors. The model lives in the local cache only (some of
the texts it learns from, the 東亜医学協会's among them, are licensed for local research only). Held out of training:
boundary F1 0.767 on 55 works (rules 0.235), 0.780 on four Siku 白文 works against their 笈成 punctuation (rules 0.303).

### 条文结构 (clause)

A clause is cut at its marks (白文 first punctuated by the model) and each piece takes the first role of
`clause.yaml` that applies — processing, preparation and 加减 before the drugs they name — or a role from the lexicon
categories it names; the drugs with their doses, the findings, pulses, diseases and formulas are listed. With
`--work`, the clauses of a work's main text are profiled by the forms they take. Limits: one role per piece (a piece
that names a pattern from a pulse gets the first rule's); 40 % of the pieces of the fullest 伤寒论 witness are read by
no rule (the 平脉法 dialogues, numbering, notes).

### 训诂 (glosses)

The glosses of a word in the set forms of `exegesis.yaml` (…者…也, …貌, 音, 反切, 读为, 当作, 一作, 通), whose head is
the word itself (项背强几几者 glosses 几几); glosses on the letter (音, 反切, 当作, 一作) are read in the characters as
written — the normaliser would read 痓当作痉 as 痉当作痉. Each gloss carries its commentator (the text layer, else the
book's authors) and date; one work's transcriptions count once; readings are grouped with who gave each first.

### 集注与注家比较 (commentaries)

The clause is found in the commentaries on its classic in the four layouts of the literature (the commentary as the row
after the clause, in rows of its own layer, run on in the paragraph, as bracketed notes after the clause); the
commentary unit after it is cut and dated. Wording is compared with the quoted classic masked out: 照录 (≥ 60 % shared),
承袭 (≥ 30 %, or a run of 14 characters), 自录 (the same person); the concepts each unit adds beyond the clause's own give
同解 (Jaccard ≥ 0.5), 增益 (a superset) and 异解 (Jaccard ≤ 0.1); named predecessors followed by 非也, 误矣, 当从 … give
驳 and 从. A quotation of the clause in another work is kept apart from a commentary. 太阳之为病: 25 commentaries from
1144 on; 张卿子 照录 成无己, 喻昌 承袭 方有执; the consensus concept 表, first brought by 成无己.

### 争议 (disputes)

Wherever a physician of `physicians.yaml` is named with a citing word, the sentence after the reported view is read for
a stance (`exegesis.yaml`): direct speech must close before the verdict, a hypothetical is not a verdict, a double
negation (鲜不, 无不) affirms, a verdict after another name belongs to that name, a later layer's rejection is dated with
its layer, and a work reporting another's rejection (A 书 records that B rejected C) is credited as the reporter. 张介宾
is the physician who rejects 丹溪 most; 景岳 on 丹溪's 相火 is reported in the 吴医汇讲 and the 医述.

### 校勘疑义 (cruxes)

For every clause (whole 条) of a work's base witness, the commentaries on it are read for statements that the words are
out of place (当在…下, 错简), miswritten (当作, 疑是, 字之误), added (衍文, 后人所加), lost (脱, 阙文) or doubtful (疑有误,
不可解).  A statement names its target — the words pointed at, with counters such as 六字 or 之文 — and a crux needs a
target the clause has, or two commentators for a bare doubt.  Left out: a word to be *read as* another (当作…看), a
negated marker (不当在), a repetition the commentator's own witness has, a doubt the author reports only to answer it, a
misplacement between chapters (recorded, not counted), preparation lines and herb lists, and commentaries from 1950 on.
The registry (`domains/classics/cruxes.yaml`) keeps per crux the clause, the kinds, the target and proposed reading and
up to six commentators with a quote of at most 60 characters; the 伤寒论 (1674 clauses) gives 85 cruxes, the 金匮要略
(779) 42.  The support reading finds a registered clause in any witness through its 4-grams (half of them suffice; an
edition's numbering is ignored) and reads a claim resting on the doubted words as *ambiguous*.

### 异文分级 (variant impact)

Every reading of a variant unit is classed, first rule that applies (`collation/impact.py`): orthographic 0.05 ·
lacuna 0.30 · long structural 0.60 · **dose** 1.0 (a numeral or measure that is part of a dose or a frequency, not of 半表
半里 or 十枣汤) · **negation or modal** 0.95 · order 0.35 · **drug or formula** 0.90 and **clinical term** 0.80 (read in the
unit's context) · structural 0.60 · function words 0.20 · lexical 0.50. `study variants` orders its review queue by the
score — for experts to look at doses and negations first, never to decide which witness is right.

### 配伍与方证网络 (pairs, network)

One cached pass over the store reads every written-out composition (after a formula's name, drugs grouped by family:
桂枝/桂心/肉桂 → 桂) and every treatment sentence (…主之, 宜…汤: the findings, pulses, patterns and diseases before the
formula); one work's transcriptions count once. Pairs: support, confidence both ways, lift, PMI, NPMI (the ranking, so
that rare drugs do not come first), a one-sided Fisher test with Benjamini–Hochberg; a drug's partners and triples by
period; the communities of the significant pairs are the groups of drugs that hold together (六味, 四物, 攻逐, 破血, 理气,
消导 …). Network: a formula's findings by lift against how often each finding is named, its drugs; a finding's formulas.
A finding named before a formula is not proof that the formula treats it: each link carries examples.

### 学派 (schools)

The schools and memberships of `schools.yaml` and `physicians.yaml` (the 中医各家学说 groupings). A school's works —
members' works through traditional or compiled attributions, one transcription each, its own layers only (later notes
and modern apparatus left out), witnesses of one work edited by different physicians counted apart, up to 30 000
characters taken evenly — are compared with the other works written within sixty years of any of them (a work printed
long after its author, like 脉因证治, is dated within its author's life). Each physician counts once (a member's works
share one unit, so do another author's) and the other works are reweighed to the school's forms (论著, 医案, 方书, 本草,
歌赋), so that case-record prose is compared with case records. Words of two to four characters used by at least a
quarter of the school's physicians are ranked by the z of the log-odds of their rates with an informative Dirichlet
prior (Monroe, Colaresi & Quinn 2008) and significant when it passes Benjamini–Hochberg and more of the school's
physicians use the word (share test); particles, doses and physicians' names are left out; each word is typed (a word,
a drug, a formula name, making and taking) and quoted. Formulas (from the compositions and treatment sentences) are
ranked the same way; citations give homophily (the share of the school's citations to its own members against the
other works'), the schools it cites and that cite it, rejections both ways, and citations between members.
Limits: a commentary carries its classic's words; one- or two-member schools have little power; a school is a
historian's grouping and a word used more is not a doctrine until its passages are read.

### 名称 (names)

For the names the lexicon records for an entry, the works writing each name period by period and by century (a work
counts once; a name written only inside a longer one — 山药 in 干山药 — is left to the longer); the first works to write
each; the preferred name of each century and where it changes (a one-century blip between agreeing neighbours is read as
theirs); passages equating two names (A，一名B; A即B; 俗名); and names the punctuated texts give after 一名, 又名, 俗呼,
今名 that the lexicon lacks — candidates for curation. 山药: 薯蓣 until the 1000s, 山药 from the 1100s (宋英宗's taboo);
玄参 gives way to 元参 in the 1700s (康熙) and returns after 1900; 山芋 is a name the lexicon lacked.

### 传播链 (chain)

The dated witnesses of a passage (from the concordance, coverage ≥ 0.8) are ordered into a tree by shared innovations
(the principle of textual criticism that only shared changes show descent): a reading none of the earliest-dated
witnesses has is an innovation (the earliest are all the source — the 宋本 writes one clause twice, 属桂枝汤 and 宜桂枝汤);
a witness hangs from the earlier witness whose innovations it shares most, less half of that witness's innovations it
lacks; with none shared, from the source (directly or through a lost intermediary). Spelling equivalents of
`collation.yaml` are not innovations — copyists regularise them independently — and function-word changes weigh half.
Each edge carries its shared readings, its score and its margin over the next candidate (under one reading:
uncertain). On artificial traditions the parent is right 1.0 (0.94 when every copy also regularises spellings on its
own, against 0.87 for the most similar earlier witness).

## Data files

| File | Content |
|---|---|
| `domains/classics/taboo.yaml` | taboo rules: ruler, start year, character, spellings (pairs or formula suffixes), note |
| `domains/classics/metrology.yaml` | units and their ratios; per period the 两 in grams and the 升 in ml (ranges), the value of 分, sources; the notice |
| `domains/classics/physicians.yaml` | 104 physicians: names, 本草 short names, dynasty, life or active years, school (学派), branch within it, field (学科) |
| `domains/classics/schools.yaml` | the schools of the 各家学说 textbooks: label, source (the authority not counted as a member), founder, parent school, branches, note |
| `domains/classics/drug_families.yaml` | drugs compared as one in compositions (桂, 地黄, 芍药, 术, 甘草, 附子, 山药, …) |
| `corpus/catalog/external-works.yaml` | works known through citations, including lost works known only through them |
| `domains/classics/collation.yaml` | orthographic equivalences for collation (沉/沈, 藏/脏, 鞕/硬, 耆/芪 …): variants in the apparatus, never grouping evidence; graphic confusions (已/巳/己) deliberately left out |
| `domains/classics/intertext.yaml` | citation, dialogue, refutation and explanation markers, and the stock phrases of the genre (以水七升，煮取三升，去滓 …) |
| `domains/classics/cases.yaml` | case and visit openers, day markers, sections that file no cases, pulse and tongue patterns, principles, changes, doses, words of response |
| `domains/classics/argument.yaml` | discourse markers of reasoning by relation (lead / tail, direction), the markers that split a clause (则, 故) and their exceptions |
| `domains/classics/clause.yaml` | the roles of a clause (condition, disease, findings, pulse, pattern, principle, contraindication, formula, composition, preparation, administration, modification, prognosis) as patterns tried in order |
| `domains/classics/exegesis.yaml` | the concepts commentators explain the classics with (forms, group), the words of stance towards another commentator, the forms of a gloss |
| `domains/classics/cruxes.yaml` | the textual cruxes (校勘疑义) harvested from the commentaries: clause, kinds, target words, proposed reading, commentators with short quotes (generated by `study cruxes --write-registry`) |
| `<data>/corpus/study-cache/` | the entry-heading index, the citation network and transmission results, the 句读 model, the harvested formula compositions and the school comparisons, keyed by a digest of the store, the normaliser, the book records and the data files they read |

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
- 句读: editors punctuate differently (a 、 against a ，, a quotation opened or not), so a disagreement with one edition
  is not always an error; the model is learned from the texts the store holds and stays in the local cache.
- 条文结构 and 训诂: the roles and gloss forms are patterns; a piece takes one role, and a gloss in a form not listed is
  not found.
- 集注 and 争议: a commentary is found only where it follows the clause in one of the four layouts; a stance is read only
  where a named physician of `physicians.yaml` is cited with a citing word, so the silent disagreements of a
  commentator who names no one are not counted.
- 配伍与方证网络: compositions and treatment sentences are read with patterns and the lexicon; a formula named in a
  sentence with findings is linked to them, which is co-occurrence, not efficacy.
- 学派: the groupings are the textbooks'; a distinctive word is a question for the reader, and small schools have
  little power.
- 名称: only the names the lexicon records are counted; the candidate names from 一名 and 俗名 need curation.
- 传播链: the tree is a hypothesis from shared readings; convergent changes by independent copyists can make a false
  edge, which is why each edge carries its margin and its readings.
- 方药研究: compositions are read with the lexicon, so a formula the lexicon lacks is not compared, and a drug written under
  a name it lacks is not counted (the browser's corpus loads the supplement and the core of the harvest for this); a dose
  the parser cannot read is left out of the doses, not guessed.  类方 finds what the compositions show, not what a
  commentator says a formula derives from; a 合方 is a reading to check.  配伍禁忌: a statement is found only in the form 反 /
  畏 followed by a list; its subject is a rule of thumb that can misattribute a statement in a run of notes.
- 研究方案: kinds are told by cue words and the names found; a question in words the lexicon lacks gets the general
  protocol, filled with the question itself.  The pilot's numbers are this corpus's, at default settings.
