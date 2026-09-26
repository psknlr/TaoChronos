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

## Data files

| File | Content |
|---|---|
| `domains/classics/taboo.yaml` | taboo rules: ruler, start year, character, spellings (pairs or formula suffixes), note |
| `domains/classics/metrology.yaml` | units and their ratios; per period the 两 in grams and the 升 in ml (ranges), the value of 分, sources; the notice |
| `domains/classics/physicians.yaml` | ~70 physicians: names, 本草 short names, dynasty, life or active years, school |
| `domains/classics/drug_families.yaml` | drugs compared as one in compositions (桂, 地黄, 芍药, 术, 甘草, 附子, 山药, …) |
| `corpus/catalog/external-works.yaml` | works known through citations, including lost works whose modern reconstructions are excluded |
| `<data>/corpus/study-cache/` | the entry-heading index and the citation network, keyed by a digest of the store, the normaliser and the book records |

## Limitations

- Extraction is rule-based: formula lists, drug entries and properties are read with patterns and a lexicon. Groups of
  one witness (孤例) and unusual layouts need checking by hand; every output quotes what it read.
- The lexicon decides what counts as a drug: a missing name (a rare drug, a regional name) leaves a composition
  incomplete; harvested names are candidates.
- Citations in undated notes inherit the date of the text they annotate unless they are anachronistic; the 孙星衍
  notes in the 本经 still count as Han citations of the 说文.
- Metrology values and taboo start years are scholarly positions with sources; they can be disputed and edited.
- Taboo evidence and dating by terminus ante quem are conservative, not proof.
