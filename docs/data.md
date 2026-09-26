# Data: corpus and domain pack

Both are plain YAML so historians can read, review and version them. `corpus/demo` is a small in-memory corpus
for demonstrating and evaluating the method; the **full corpus** (below) is served from a SQLite corpus store
built from licensed sources by `taochronos corpus fetch / ingest`.

## Corpus

`corpus/<name>/books.yaml` — the bibliographic layer (Gate G0 reads `source`):

```yaml
books:
  - id: suwen
    title: 黄帝内经素问
    aliases: [素问, 黄帝内经, 内经]
    authors: [佚名（托名黄帝、岐伯）]
    dynasty: 战国—西汉
    composition: [-300, 25]          # a range expresses uncertainty
    attribution: pseudepigraphic
    category: 医经
    source: {origin: …, license: …, acquisition: …, transcription: …, verified: false}
    editions:
      - {id: suwen@wangbing, name: 唐王冰次注、北宋林亿等新校正本系统, quality: 0.7}
external_works:                        # works known only through citations (lost or not collected)
  - {id: gujin_luyan, title: 古今录验方, aliases: [古今录验], authors: [甄立言], dynasty: 唐, composition: [618, 650], status: lost}
```

`corpus/<name>/books/<book>.yaml` — passages:

```yaml
book: shanghanlun
edition: shanghanlun@songben
passages:
  - id: shanghanlun.c176
    locator: {chapter: 辨太阳病脉证并治下, section: 第176条}
    text: 伤寒脉浮滑，此以表有热，里有寒，白虎汤主之。
    tags: [白虎汤, 异文, 校勘]
    variants:                          # never overwrite the base text; record readings with witnesses
      - {base: 表有热，里有寒, reading: 表有寒，里有热, witness: 宋本林亿等按语, witness_type: commentator, kind: transposition}
    temporal: {t_composition: [100, 762]}   # optional per-passage clocks (author / composition / edition / citation)
```

The four clocks (`t_author`, `t_composition`, `t_edition`, `t_citation`) let a research contract choose its
time basis; a passage quoting older material can carry `t_citation`.

`corpus/modern/evidence.yaml` — summaries of modern evidence (Biomedical space) with `concept_id`,
`evidence_domain` (`modern_clinical`, `pharmacology`, `molecular`) and `related_terms`. They are never
historical evidence.

## Domain pack (`domains/classics`)

| File | Content |
|---|---|
| `periods.yaml` | analysis periods (half-open year ranges), dynasties, and the expressions used in questions (宋代以前, 明清, 唐以后…) |
| `variants.yaml` | length-preserving character and word normalisations (异体字, 古今字, 通假), witness weights, uncertain-mass floors — normalisation is for matching only; the text is never altered |
| `lexicon/*.yaml` | terms by category (symptom, sign, pulse, disease, pattern, pathogenesis, etiology, treatment, formula, herb, organ, condition, concept) with aliases, typed synonyms (`taboo_rename`, `part_name`, `processing_variant`, `abbreviation`, `variety`), polarity axes, origin, thermal nature, components, broader/related links |
| `terminology.yaml` | historical terms with period-bound **senses** (label, gloss, category, scope, period, cues, anti-cues, exemplars) and *candidate* modern concepts — candidates, never equivalences |
| `modern_concepts.yaml` | modern concepts (labels only; no mapping implied) |
| `ontology.yaml` | entity types, category → claim role, claim relations, treatment verbs, opposition markers, school canons, opposite findings |
| `citations.yaml` | citation patterns and generic references (经曰 → candidate books with weights) |
| `known_findings.yaml` | curated existing understanding used by the novelty check (a restated textbook finding is a rediscovery) |
| `taboo.yaml` | taboo rules for 避讳断代: ruler, the year the taboo starts, the character, the spellings it forces (`pairs` such as 薯蓣/山药, or `formula_suffix` 丸/圆), a note |
| `metrology.yaml` | historical measures for reading doses: unit ratios (斤/两/铢/钱/分/厘, 斛/斗/升/合, counts, 方寸匕 …) and per period the 两 in grams and the 升 in ml (ranges, with sources), the value of 分; the notice that these are historical readings, never dosage guidance |
| `physicians.yaml` | ~70 physicians for the citation network: name, other names (仲景, 东垣 …), 本草 short names (恭, 颂, 藏器 …), dynasty, life or active years, school |
| `drug_families.yaml` | drugs compared as one in formula compositions (桂枝/桂心/肉桂 → 桂; 山药/薯蓣; 陈皮/橘皮 …) |

## Adding a real corpus

1. Write a corpus plugin (or reuse `plugins.classics` with `config: {corpus: corpus/<name>}`) and record
   origin, license and acquisition for every source — TaoChronos refuses unlicensed books at scope time.
2. Mark collation status honestly; attach OCR confidence and page images (`locator.page`, `line`, `region`,
   `image_uri`) to complete the Claim → Pixel chain.
3. Extend the lexicon, terminology and variant tables with expert review; add gold sets under `evals/gold`.
4. Add a profile that points at the new corpus and run `taochronos eval`.

## The full corpus (corpus store)

| Source | Scope | Licence | Connector |
|---|---|---|---|
| 漢籍リポジトリ Kanseki Repository, `KR3e` | 《四库全书·子部·医家类》, all 100 works (文渊阁本 WYG; seven in 四部丛刊 SBCK) — 25.7M characters | CC BY-SA 4.0 | `taochronos corpus fetch|ingest kanripo` |
| 笈成 (JiCheng), data of the 笈成檢閱系統 v1.4.8 (user-supplied archive `jc_1_4_8_all.7z`, 3 volumes) | 857 punctuated texts: 内经难经, 伤寒, 金匮, 本草, 方剂, 温病, 各科, 医案, 综合, 丛书, 歌赋; 798 stored (59 contemporary works and modern editions left out) — 92M characters, 1.61M passages | originals public domain; punctuation and collation by the 笈成 volunteers — local research use | `taochronos corpus unpack|catalog|ingest jicheng` |
| Kanripo catalogue (KR-Catalog), `KR/KR3e.txt` | the 100 KR3e entries: responsible persons with roles (撰, 次注, 校正 …) and dates, Siku volume and page, extent | CC BY-SA 4.0 | `taochronos corpus fetch|catalog kr-catalog` (merged into the Kanripo records) |
| McGill University Library, *Gynaecology in Traditional Chinese Medicine* (GitHub `mcgill-digital/gynaecology_in_chinese_medicine`) | 5 Qing prints and a manuscript (傅青主女科, 重订济阴纲目, 保生碎事, 女科辑要, 珍存秘方), page by page, unpunctuated — 366k characters | Public Domain Mark 1.0 | `taochronos corpus fetch|catalog|ingest mcgill` |
| 數位中醫校書郎 CMETA (`cmeta.lctseng.csie.org`) | the editions the site has collated in full against their page images (精校) and opens to every visitor: 伤寒论 (赵开美本: 台北故宫本 and 安政覆刻本; 康平本; 康治本), 金匮 (吴迁本, 邓珍本), 素问 (顾从德本), 灵枢 (赵府居敬堂本), 古今医案按, 名医类案, and the 桂林古本 伤寒杂病论 (kept as a recension that surfaced in modern times, dated 1939) — 11 read and stored — 1.45M characters, 27,710 passages, located by page and, where the site shows the images to guests, linked to the page image | CC BY 4.0 for the site's collation and editing (attribution: 數位中醫校書郎 CMETA); the texts public domain; images per holder (故宫 Open Data, SBB PDM 1.0, Commons) | `taochronos corpus fetch|catalog|ingest cmeta` |
| 東亜医学協会 · 医学古典テキスト (`aeam.jp/koten`) | 7 PDF texts of named base editions: 素問 (顾从德本), 霊枢 (明无名氏本), 難経, 傷寒論 (赵开美本), 金匱要略 (邓珍本), 神農本草経 (森立之), 扁鵲倉公列伝 — 317k characters, 12,212 passages | © 東亜医学協会: saving and use for non-commercial personal purposes only, no redistribution — local research use only | `taochronos corpus fetch|catalog|ingest aeam` (needs the `pdf` extra: pypdf) |
| 维基文库 zh.wikisource, `Category:中醫` and its subcategories, and `Category:醫書` (from the Wikimedia dumps) | 627 works read, 16 stored after deduplication — 613k characters (the Korean 医方类聚, 1445, comes from 醫書) | CC BY-SA 4.0 (the originals public domain) | `taochronos corpus fetch|catalog|ingest wikisource` |
| TCM-Ancient-Books (GitHub `xiaopangxia/TCM-Ancient-Books`) | 701 texts read, 8 stored — 369k characters | no licence stated — local research use | `taochronos corpus fetch|catalog|ingest tcm-ancient-books` |
| tcmoc (GitHub `lab99x/tcmoc`) | 701 texts read (a copy of the previous), none stored | no licence stated — local research use | `taochronos corpus fetch|catalog|ingest tcmoc` |
| classical-tcm-canon (Hugging Face `wangekxy/classical-tcm-canon`) | 115 records read, 1 stored — 305k characters | dataset card: `license: other` (proprietary-commercial), texts declared public domain — local research use only, never redistributed | `taochronos corpus fetch|catalog|ingest hf-tcm-canon` (needs the `parquet` extra: pyarrow) |
| Image witnesses (影像见证): NIJL 国書データベース, Staatsbibliothek zu Berlin (Sammlung Unschuld), Library of Congress (Chinese Rare Books), 早稲田大学 古典籍総合データベース (NDL デジタルコレクション: harvester ready, catalog not yet built) | the *records* of digitised prints and manuscripts — title, author, date, print or manuscript, holder, shelfmark, IIIF manifest, terms of use — linked to the works of the store by title; no image is downloaded (see *Image witnesses* below) | the records: each catalogue's terms; the images: each holder's licence, per record | `taochronos corpus images [source] [--enrich]` → `corpus/catalog/images/*.csv` |

```bash
taochronos corpus fetch kanripo            # shallow clones into <data>/sources/kanripo, one repository at a time
taochronos corpus ingest kanripo           # (re)build <data>/corpus/tcm.sqlite; --only KR3e0001,KR3e0013 for some books
taochronos corpus unpack jicheng jc_1_4_8_all.7z.001 jc_1_4_8_all.7z.002 jc_1_4_8_all.7z.003   # join, check, extract, lock
taochronos corpus catalog jicheng          # corpus/catalog/jicheng.yaml + script/jicheng_variants.tsv (then `corpus reindex`)
taochronos corpus ingest jicheng           # add the admitted texts to the same store (--only B000,D025 for some books)
taochronos corpus fetch kr-catalog         # the Kanripo catalogue; `corpus catalog kr-catalog` → kr-catalog-kr3e.yaml
taochronos corpus ingest kanripo --changed # rewrite the Kanripo book records only (e.g. after the KR-Catalog step)
taochronos corpus fetch mcgill             # likewise wikisource, tcm-ancient-books, tcmoc, hf-tcm-canon: fetch and lock
taochronos corpus catalog mcgill           # dates, admission and duplicate status → corpus/catalog/mcgill.yaml
taochronos corpus ingest mcgill            # only the admitted texts; copies and left-out texts are removed from the store
taochronos corpus fetch cmeta              # CMETA: the catalogue, the open 精校 texts and their structure files; likewise aeam
taochronos corpus images all --enrich      # image-witness records → corpus/catalog/images/ (paced, cached; metadata only)
taochronos corpus status                   # counts by period, kind and layer; whether the index matches the variant table
taochronos corpus reindex                  # rebuild the full-text index after changing domains/classics/script or variants.yaml
taochronos lexicon harvest                 # candidate formula and drug names → domains/classics/lexicon-harvested/
taochronos research "…" --profile full-corpus
```

`corpus/sources.lock.yaml` pins every text (repository, commit, files, bytes, licence; for 笈成 the archive's
sha256, the number of text files and a digest over their paths and hashes; for Wikisource the categories, the dump
files' sizes and dates and the latest revision; for Hugging Face the dataset revision and each file's sha256; for
CMETA the catalogue's and each text's sha256 and the books whose images guests may see; for the 東亜医学協会 each
PDF's sha256); the texts themselves are never committed.

### Catalog and dating (`corpus/catalog/kanripo-kr3e.yaml`)

One entry per work: id, title (simplified; the original title becomes an alias), aliases used for citation
resolution, `work` (witnesses of one work are one source for Gate G5), authors, dynasty, `composition`, category,
school, edition, and the **layer rules**:

| Rule | Meaning | Example |
|---|---|---|
| `notes` | double-column notes form a commentary layer of their own | 素问: 王冰注 (762) |
| `markers` | notes (or parts of notes) introduced by a marker | 新校正云 (1068); 证类本草: 陶隐居云 (500), 唐本注 (659), 今按 (974), 臣禹锡等谨按 (1061), 图经曰 (1061), 衍义曰 (1116) |
| `indented_commentary` | indented blocks of a commentary edition | 难经本义: 滑寿注 |
| `chapter_layers` | chapters added later | 素问运气七篇, 王冰补入 (762) |
| `section_layers` | sections appended by later editors | 肘后方「附方」(杨用道 1144); 局方绍兴续添、宝庆新增、淳祐新添 |
| `mixed` + `cites_work` | layers cannot be separated: date by the latest layer, keep the older text's date as `t_citation` | 注解伤寒论 (1144; cites 200–219), 类经 (1624), 医宗金鉴 (1742) |

Front matter is dated separately: the Siku abstract (提要) by the 乾隆 year stated in it, prefaces and contents
(卷首) conservatively by the edition. A witness is never dated earlier than its own production unless it is the
standard transmission of an earlier text (素问 in the 王冰/新校正 recension). Dates marked 待核 await review.

### Parsing Kanripo texts

`plugins/classics/ingest/kanripo.py` reads the mandoku format: `#+PROPERTY:` headers (a file may hold several
sections — 提要, 目錄, 序, 凡例 — each under its own `JUAN`), page markers `<pb:…_001-12a>` (kept as `page` and
`line` in the locator), and `¶` line ends. Double-column notes `(A/B)` are read A→B, or B→A for the
transcriptions that list the left column first (declared per book and checked at ingest by a character-bigram
score across line breaks). Characters outside Unicode (`&KR0001;`, `[病-丙+(穩-禾)]`) become 〓 with the original
kept in the passage metadata. Paragraphs are rebuilt from printed lines (a short line or an indentation change
ends one; editions with irregular note widths use a looser threshold); chapter titles, per-卷 contents lines and
credit lines are recognised; ingredient lines and the 右…味 preparation line are merged into their prescription.

### The 笈成 collection (`corpus/catalog/jicheng.yaml`)

The archive is the data of a local viewer: `data/<A–R,Z>/<code>.txt` (one book per file, UTF-8), `config/filelist.txt`
(categories and display names), `config/nclist.txt` (codes of characters outside common fonts, with Unicode code
point, common form and ideographic description) and `config/synonyms.txt` (the viewer's variant groups).
`plugins/classics/ingest/jicheng.py` reads the markup:

| Markup | Treatment |
|---|---|
| `[book]…[/book]` | metadata (書名, 作者, 朝代, 年份, 品質, 版本) → catalog |
| `[h1]`–`[h6]` | headings → volume / chapter / section of the locator (a heading written inside a line is moved onto its own) |
| paragraphs, `[p]` | passages (texts are punctuated: claims are read without machine segmentation) |
| `[box]` | an appended prescription block → passage of kind `formula`, section = its `[b]` name |
| `[z]` `[s]` (`[zb]` `[sb]`) | 注 / 疏: inline as （…）, or a dated commentary layer when the catalog gives one (`z_layer`, `s_layer`, `markers`) |
| `[dz]` `[ds]`, `[l]`, `[b]` `[i]` `[u]` | the author's own full-size notes, small characters (doses), formatting: kept in the text |
| `[j]` `[dj]` (`[jb]` `[djb]`) | the transcribers' collation remarks: never in the reading text |
| `[id]` | numbering added by later editors (宋本条文 numbers): locator only (`第N条`) |
| `[c]code[/c]` | the character from `nclist.txt`, or 〓 with code, description and common form kept in the passage metadata |
| `[wj]` | not yet collated: `collation_status = unverified` |

**Dating**, in order of precedence (`dating` in the catalog records which one applied):

1. `corpus/catalog/jicheng-overrides.yaml` — curated: the classics and their layers (素问: 王冰注 762, 新校正 1068,
   运气七篇; 金匮 宋臣校注 1066; 太素, 类经, 伤寒 commentaries as `mixed` + `cites_work`), the 医宗金鉴 and
   证治准绳 parts, reconstructions (本经, 别录, 吴普本草: `attribution: compiled`), works whose own metadata is
   wrong (医述 is not Yuan, 女科百问 is not 刘宋 …), modern works;
2. the same work in the Kanripo catalog (same normalised title) — its curated date;
3. the book's `[book]` block: 年份 (公元 years), reign eras (「明‧洪武戊午年」), dynasty names — when 年份 and 朝代
   contradict each other, the range a dated preface falls in wins, otherwise the later one;
4. **dated prefaces** — the closing line of a 序 / 跋 (「康熙甲戌歲陽月，休寧八十老人訒庵汪昂書」, parsed by
   `plugins/classics/chronology.py` with `domains/classics/eras.yaml`): when the metadata gives only a dynasty or
   a span over 60 years (or nothing), the author's own dated preface decides, else the earliest dated preface
   inside the span (the latest for titles marking a later layer: 增订, 评, 注 …); a precise metadata year yields
   only to the author's own preface;
5. another transcription of the same work (the "a" files), then the author's other well-dated works (± 20 years,
   within the book's own span);
6. otherwise **undated**: the book is placed in the Qing (1644–1911) — never earlier — and says so in its notes
   and in the report disclaimer.

Paratext is dated on its own: a preface whose closing line is dated takes that year (layer 序跋（按落款年代）);
undated 序 / 跋 / 凡例 / 目录 are placed at the end of the imperial era (1911) unless the book is later; what a modern
editor wrote (内容提要, 整理说明, 点校说明, 概述, 前言, 电子版序 …) is dropped. Republican works (category 近代,
1912–1949) are kept as historical sources; works after 1949 and modern editions are left out (below). Non-medical
texts (非医籍, e.g. 易经) are ingested but left out of research by the `full-corpus` profile
(`discovery.scope.exclude_categories`) unless a research contract names its categories. A `[book]` block whose
closing mark was put after the whole text (M106 脉诀) ends at the first tag line.

### What the corpus leaves out (`corpus/catalog/exclusions.yaml`)

Three classes of text never enter the store: **当代出版物** (written or compiled after 1949: dictionaries, textbooks,
modern compilations and readers), **当代名医著作** (works and case records of physicians of the PRC era) and
**现代校注本** (modern annotated, translated or explicated editions, and modern reconstructions — 辑校本 — of lost
works, whose text interleaves the editor's source marks). `exclusions.yaml` records the reviewed decisions per source
and code (`exclude: <class>` or `keep: true`) and titles excluded wherever they appear (for the collections that copy
one another). `plugins/classics/ingest/policy.py` screens the rest, in order: a reviewed decision; a composition
date from 1949; a title marking a modern edition (校注, 校释, 语译, 今译, 白话, 译注, 新解, 考释, 讲义, 教材, 辞典 …) or a
contemporary physician (经验集, 老中医, 验案精选, 临证经验 …); a density of modern years, units and institutions
(19[4-9]x, 克, 毫升, 医院, 出版社, 教授, 维生素 …); annotation apparatus (【注释】【语译】【按语】 …); numbered
footnotes; a modern editor's source marks in a lost work. Every excluded text is catalogued with its class and the
evidence; a copy of an excluded 笈成 book in another collection inherits the decision, as does a kept one (薛己's
校注妇人良方, 1547, is not a modern edition). In the 笈成 collection: 18 当代出版物, 24 当代名医著作, 17 现代校注本.

Texts that surfaced in modern times under an ancient name are not modern publications in this sense: the 桂林古本 伤寒杂病论
(白云阁藏本, printed 1939; the 桂林本, 1960), the 辅行诀脏腑用药法要 (brought out between 1918 and 1974), like the
Republican 长沙古本 and 康平本, are kept (`keep`, also for a title wherever it appears) as sources of the time they
appeared: dated by their appearance, marked pseudepigraphic or disputed, never dated by the age they claim. The
copies of each in the web collections are catalogued as copies of the stored witness (the 白云阁藏本 on Wikisource,
笈成 F027).

### The other collections (`plugins/classics/ingest/documents.py`)

McGill, CMETA, the 東亜医学協会, Wikisource, TCM-Ancient-Books, tcmoc and the Hugging Face dataset share one path: a
reader turns the source into documents (title, metadata as given, headings and paragraphs, each paragraph with its
page and page image where the source has them), `corpus catalog <source>` dates, screens and deduplicates them into
`corpus/catalog/<source>.yaml` (corrections in `<source>-overrides.yaml`: composition, authors, work, the edition
with its year and holder, mixed layers, dated note layers — `notes`, `markers`, `chapter_layers` as in the Kanripo
catalog —, `force_ingest`), and `corpus ingest <source>` stores the admitted ones.

| Reader | Format | Treatment |
|---|---|---|
| `mcgill.py` | one XML file per page, characters spaced out, `<sf>` small characters, `<formula>`, `<marginalia>`, `<cf>` entities, the transcribers' `[x]`, `{妊}`, `穴[允]`, `<?>` | pages chained through their `next` links; a paragraph running over a page break joined at its first page (`locator.page` = 卷 + 葉); small characters and marginalia → （…）; formulas → `formula` passages; illegible → 〓; unpunctuated (`punctuation: none`) |
| `wikisource.py` | wikitext of each work's main page and subpages | `{{*|…}}`, `<small>`, 小字 → （…）; `{{參|原|讀}}` keeps the original graph; `{{?}}`, `{{PUA}}` → 〓; `-{…}-` conversion keeps the traditional form; header, quality, navigation, image and category templates, references, tables' attributes and the main page's list of subpages dropped; subpages in the order the main page links them, each a heading with `locator.page`; pages pasted from the 中医世家 files read like them |
| `cmeta.py` | the catalogue (`library/catalog.json`), one Markdown text per edition cut at the page boundaries of its images (`<!-- Page N -->`), the structure files (`volumes.json`, `sections.json`, `paratexts.json`: each 卷, 篇 and piece of front matter with its page and first words) | only the editions collated in full (精校) and not held back for the site's allow-list (its rule in `prototype/app.js`); each line a paragraph at its page, a paragraph cut by the page break joined at its first page and a note the break cut made whole; ＝ (重文號) written out; doses in composition lines (桂枝（三兩去皮）) written inline as in the other transcriptions; the 卷 and 篇 headings placed where their first words stand on their page, lines that only repeat headings dropped, front matter under 序跋; `locator.page` and, for the books the site shows to guests, `locator.image_uri` (the page's JPEG); formula names are not supplied where the print has none |
| `aeam.py` | PDF (text extracted with pypdf) | a line ends where the PDF line ends with a space (a bare break is a wrap, also across pages); ◆ 篇, ■ section, ● a formula (its name and composition lines as one `formula` passage) or a drug entry of the 本草经, ○ the cases of 仓公; the Japanese editorial lines (with kana) left out; ※ (the editors' corrections) removed and counted in the notes; the single stop ． becomes ， inside a line and 。 at its end; spaces the PDF left between characters removed; certain look-alikes undone (寐咀 → 㕮咀) |
| `textsets.py` | TCM-Ancient-Books / tcmoc text files (GB18030 or UTF-8; `<篇名>`, `<目录>`, 书名/作者/朝代/年份, `内容：` wrapped at ~50 characters), tcmoc Markdown with YAML front matter, the Hugging Face Parquet file | fixed-width wrapping undone; the title from 书名, the first `<篇名>` or the file name (《…》); the Siku copies' 醫家類 suffix removed |

Dating follows the 笈成 order (override → the same work's Kanripo or 笈成 date → the document's metadata and dated
prefaces → sibling copies, the author's other works → undated, placed in the Qing). A subject category is taken
from the same work in the curated catalogs, otherwise guessed from the title. Documents under 300 characters (hub
pages, stubs) are skipped.

**Duplicate detection** (`plugins/classics/ingest/dedupe.py`). Texts are compared on their normalised Han characters:
a 12-character shingle is sampled where it starts at an anchor character (one code point in eight, by a
multiplicative hash) and its CRC32 is 0 mod 8 — about one position in 64, the same positions in every copy. The
*containment* of a candidate in a stored book is the share of its shingles the book also has (the *reverse*
containment the share of the book's). The index of the store is cached in `<data>/corpus/sketch.pkl` and brought
up to date book by book. Sources rank Kanripo → 笈成 → McGill → CMETA → 東亜医学協会 → Wikisource → TCM-Ancient-Books
→ tcmoc → Hugging Face; a source is compared with the books of higher-ranked sources and, as they are admitted, with its own, so a
catalog does not depend on ingestion order. A candidate is a copy at containment ≥ 0.85 in one book or ≥ 0.9 in its
ten best matches together; for web copies (and simplified texts), converted characters lose shingles, so ≥ 0.4 in a
book of the same work (by title or `work`) or with reverse ≥ 0.4, and ≥ 0.5 in any one book, suffice. Within a
source, traditional texts are judged before simplified, punctuated before bare, complete before partial.
Calibration: Siku and 笈成 witnesses of the same work overlap by 0.5–0.93 (median 0.67), so overlap alone cannot
separate two editions from two transcriptions of one — which is why the lower thresholds apply only to sources
known to copy others. McGill's prints, CMETA's editions and the 東亜医学協会's texts are independent witnesses: their
best matches are recorded, never judged (`duplicate: null`). Every copy is catalogued with `duplicate_of` and its
three closest books.

| Source | Read | Stored | Copies | Left out | Skipped |
|---|---|---|---|---|---|
| mcgill | 5 | 5 | 0 | 0 | 0 |
| cmeta | 11 | 11 | 0 | 0 | 0 |
| aeam | 7 | 7 | 0 | 0 | 0 |
| wikisource | 627 | 16 | 592 | 18 | 1 |
| tcm-ancient-books | 701 | 8 | 649 | 43 | 1 |
| tcmoc | 701 | 0 | 657 | 43 | 1 |
| hf-tcm-canon | 115 | 1 | 112 | 2 | 0 |

Curated dates (`*-overrides.yaml`): 傅青主女科 by its first print (1827; 旧题傅山); 重订济阴纲目 as 武之望 (1620)
with 汪淇's interleaved annotation (1665) as a mixed layer; 天回医简 (Western Han slips excavated 2012–2013); the
Republican "ancient recensions" of the 伤寒杂病论 (长沙 1932–1934, 康平 1937–1947, 白云阁 1939) by their appearance,
never by the date they claim; 事林广记 续集卷十 by the Yuan print (1330–1333); 医方类聚 by its compilation under 世宗 of
Joseon (1443–1445). CMETA's and the 東亜医学協会's texts are catalogued as editions of their works (`work: shanghanlun`,
`suwen` …), each with the print it transcribes, its year and its holder (赵开美本 1599, 台北故宫 平图011603—011607;
顾从德本 1550; 邓珍本 1340; 吴迁本 1395 …); CMETA's 素问 keeps 王冰's notes (762) and the 新校正 (1068) as dated layers
and the 运气七篇 as the chapters 王冰 added, like the Kanripo copy. CMETA's 桂林古本 — 米伯让's corrected 1980 printing
from the 1939 白云阁 blocks — joins the modern-surfaced recensions of the 伤寒杂病论 (work `ws:伤寒杂病论`), dated 1939.

The CMETA and 東亜医学協会 texts reproduce the orthography of their prints (𤍠 for 熱, 𫞓 for 歲, 厺 for 去, 㕮咀 …):
`script/cmeta_variants.tsv` maps the rare forms found by aligning the CMETA editions with the other witnesses of the
same works (34 mappings, each seen consistently at aligned positions), so that searches find them; the collation
treats orthographic habits of a print (发/発, 去/厺, 草/屮, 枣/栆, 俱/倶 in `collation.yaml`) as equivalent, not as
variant readings.

### Image witnesses (`plugins/classics/ingest/images.py`, `corpus/catalog/images/`)

A transcription is one witness of a work; the prints and manuscripts that libraries have scanned are others, and the
only ones that show the page ([ADR 0006](adr/0006-witnesses-and-image-records.md)). `taochronos corpus images` harvests
their **records, never their images**: title (and
its reading or romanisation), author, date statement and years, print (刊) or manuscript (写), holder and collection,
shelfmark, the IIIF manifest (the address from which any IIIF viewer — Mirador, Universal Viewer — loads the pages),
the record's page and its terms of use; and links each record to a work of the store by title. Requests are paced
(one a second, `--pause`) and cached under `<data>/sources/images/cache`; `--enrich` reads the IIIF manifest of every
linked NIJL record for its author, date and licence (`--enrich all`: of every record). Where NIJL's manifest is a
collection pointing to the holder's own (京都大学's images are served by its archive, RMDA), that manifest is read and
recorded.

| Source | Interface | Harvested | Terms of the images |
|---|---|---|---|
| NIJL 国書データベース (`kokusho.nijl.ac.jp`) | the holder lists of its image collections and each record's IIIF manifest | 研医会図書館; 慶應義塾大学 富士川文庫; 京都大学 富士川文庫 (the collection's records in the Kyoto list); 東京大学総合図書館, classes V and T81 (medicine, materia medica — they hold the 鶚軒文庫); 東京大学医学図書館; 九州大学医学図書館; 東北大学医学分館 | per holder, as NIJL's usage page links them: 研医会 CC BY-NC 4.0, 慶應 CC BY-NC-SA 4.0, 京大 free use (RMDA), 九大 Public Domain Mark 1.0, 東大医学図書館 and 東北大 RightsStatements NoC-CR 1.0, 東大総合図書館 its reuse terms; NIJL's own records are free to use |
| Staatsbibliothek zu Berlin · Sammlung Unschuld | K10plus SRU (MARCXML, shelfmarks `Slg. Unschuld …`), joined with the provenance dataset of the Hamburg FDR (Staack 2025, CC BY 4.0: when and where each manuscript was acquired) | the collection's manuscripts and prints; the digitised ones with their manifest | Public Domain Mark 1.0 |
| Library of Congress · Chinese Rare Books | loc.gov JSON API | the medical items: by subject, or by a medical title where the record has none | online reading for education and research; no reuse rights granted (digitised with the National Central Library, Taipei) |
| 早稲田大学 古典籍総合データベース | the class list and item pages | class ヤ09 (医学): title, author, imprint, call number, keywords | the library's terms; no IIIF manifest published |
| NDL デジタルコレクション | NDL Search OpenSearch (publications to 1911) | the titles of the store's pre-1912 works, queried in traditional characters; of the results — NDL Search unites many libraries' catalogues — the items of the Digital Collection whose title is the title looked up | out-of-copyright items are public on the internet. The harvester is ready, the catalog not yet built: NDL Search answers slowly and limits concurrent requests, so the 920 titles take about three hours (`corpus images ndl`) |

**Dates.** A western year where the record gives one; else a Japanese era with its year (享和１ → 1801; an era alone,
〔寛永〕, gives its span; the table runs from 天正 to 昭和); else a Chinese reign era through the domain's era table
(嘉慶5 → 1800, 萬暦9 → 1581, ［康煕］ → 1662–1722); else a period word (［江戸中期］ → 1709–1789, conventional spans).
The date statement is kept as the catalogue gives it.

**Links.** A record's title is compared with the titles and aliases of the store's books in normalised form, after
folding 新字体 to 旧字体 (霊→靈, 医→醫, 薬→藥 …): as written (`exact`); without volume counts, parentheses and
what follows a separator (`without-volumes`); without the print prefixes of Japanese and late imperial editions
(新刊, 重刻, 和刻, 増補, 増訂, 図像, 頭書, 標註 …, `without-print-prefix`). A two-character title (難経, 醫説) links
only as written. A book's own title wins over another book's alias, and a link made through an alias is marked
`·alias` (针经 is also a name of the 灵枢 — and the title of a chapter of the 太平圣惠方): these are the first to check.
Among books of one title, the most trusted source's stands for the work. A link is a candidate for a person to check;
commentaries on a classic (傷寒論講義, 金匱述義) are works of their own and stay unlinked.

`taochronos study witnesses <work>` (tool `study.witnesses`) lists a work's text witnesses in the store — edition,
year, holder, source, licence, passages, and whether its passages link their page images — and its image witnesses by
year, with holder, shelfmark, how the link was made and the terms, and the count by holder.

<!-- image-counts -->
| Catalog | Records | With a IIIF manifest | Linked to a work | Works |
|---|---|---|---|---|
| NIJL · 研医会図書館 | 663 | 663 | 46 | 31 |
| NIJL · 慶應義塾大学 富士川文庫 | 866 | 866 | 24 | 18 |
| NIJL · 京都大学 富士川文庫 | 4,443 | 4,443 | 132 | 78 |
| NIJL · 東京大学総合図書館（V, T81；含鶚軒文庫） | 819 | 819 | 40 | 20 |
| NIJL · 東京大学医学図書館 | 62 | 62 | 0 | 0 |
| NIJL · 九州大学医学図書館 | 946 | 946 | 21 | 19 |
| NIJL · 東北大学医学分館 | 68 | 68 | 0 | 0 |
| Staatsbibliothek zu Berlin · Sammlung Unschuld | 1,044 | 905 | 69 | 40 |
| Library of Congress · Chinese Rare Books | 66 | 66 | 29 | 23 |
| 早稲田大学 · ヤ09 | 661 | 0 | 85 | 65 |
| **all** | **9,638** | **8,838** | **446** | **168** |
<!-- /image-counts -->

### Sources surveyed for this release

| Resource | Outcome |
|---|---|
| Kanseki Repository KR3e, 笈成, McGill (gynaecology collection), Wikisource, TCM-Ancient-Books, tcmoc, classical-tcm-canon | already in the store. Wikisource: the categories 本草 and 醫家 lie inside the 中醫 tree, 傷寒 does not exist and 針灸 adds no work; 醫書 adds 医方类聚 (with a copy of a 笈成 book and an empty page) |
| 數位中醫校書郎 CMETA | 11 editions stored: the 精校 texts the site opens to every visitor (the 桂林古本 among them, kept as a modern-surfaced recension); texts still being collated, allow-listed texts and the excavated texts (modern transcriptions) are not taken |
| 東亜医学協会 医学古典テキスト | 7 texts stored, local research use only |
| ctext.org | not harvested: the site restricts automated bulk download |
| 東京大学 鶚軒文庫 | the portal's search refuses automated requests; the collection is harvested through NIJL (東京大学総合図書館, classes V and T81) |
| NIJL: 研医会, 慶應 富士川文庫; 京都大学 富士川文庫 | image witnesses (see above) |
| Staatsbibliothek zu Berlin, Sammlung Unschuld, with the provenance CSV | image witnesses |
| Library of Congress, Chinese Rare Books | image witnesses |
| 早稲田大学 古典籍総合データベース | image witnesses (no IIIF manifests) |
| NDL デジタルコレクション | harvester ready (`corpus images ndl`: the store's titles among publications to 1911, the Digital Collection's items kept); the catalog is not built yet — about three hours at NDL's rate limits |
| 国立公文書館 デジタルアーカイブ | reachable, but no interface for records in bulk: reference only |
| 北里大学 東洋医学総合研究所 医史学研究部 | research pages without a catalogue interface: reference only |
| Internet Archive | its Chinese-medicine items are almost all modern books in the lending library: not harvested |
| 香港中文大學 digital repository | refuses the requests (HTTP 403) |
| Biodiversity Heritage Library | behind a bot challenge, and its API needs a key: can be added with one |
| 中国中医古籍数字资源库 | unreachable from this environment (the connection is closed) |

### The Kanripo catalogue (`corpus/catalog/kr-catalog-kr3e.yaml`)

`corpus catalog kr-catalog` parses `KR/KR3e.txt` of the KR-Catalog (org-mode: `SOURCE` — the Siku volume and page —,
`EXTENT`, `_RESP`, and under 人物 each person's dynasty, role and dates such as `fl. 762`, `1518 - 1593`,
`12th cent`) and writes the 100 entries with a review list: curated entries whose authors the catalogue does not
name, or whose date lies well outside the dates it gives for that author (6, e.g. 陈言 given as fl. 1500–1540 for the
三因方 of 1174 — the catalogue is wrong there). `corpus ingest kanripo` adds the persons (`responsibility`) and the
Siku location to each book record and a 责任者 line to its notes; the curated dates are never changed.

**Variants.** `corpus catalog jicheng` turns the viewer's variant groups into
`domains/classics/script/jicheng_variants.tsv`: a rare form (outside GB 2312) maps to the group's only common form;
the sections 易誤判字 and 一對多簡化字 (「意義往往不同」) are skipped, and groups with two common forms are never
merged. The table sits between the Unihan variants and OpenCC in the normaliser, so the store must be reindexed
(`taochronos corpus reindex`) when it changes.

### Works cited but not collected (`corpus/catalog/external-works.yaml`)

A registry loaded into the store at every `corpus ingest`: lost medical works known through quotations (古今录验方,
近效方, 删繁方, 深师方, 日华子本草, 本草拾遗, 开宝本草, 本草图经 …, `status: lost`) and extant works outside the
corpus that physicians cite (太平御览, 艺文类聚, 释名, 说文, 经史子 …, `status: extant`). A citation of a lost work is
a lost-source clue (佚书线索); a citation of an extant one is not; an unknown title is reported as a book not in the
corpus (语料未收之书), lost or not. Citations are resolved on normalised titles, by book · chapter (《内经‧阴阳别论》),
and — in the store — against the chapter names of the canonical classics (《脉要精微论》 is a chapter of the 素问,
not a lost book); one-character abbreviations (《本》《肘》) are never taken for lost books. A cited book that is in the
store counts as present even when the research frame did not sample it; only a book the contract withholds
(`exclude_books`) can be "rediscovered".

### The store

`plugins/classics/store.py`: one SQLite file with books (catalog + provenance), passages (verbatim text, locator,
the four clocks, layer, kind) and a contentless FTS5 index over **overlapping character bigrams of the normalised
text**, so substring, phrase and proximity (`NEAR`) queries work for terms of any length. The normaliser's
fingerprint is stored with the index. `StoreCorpus` implements the `Corpus` interface lazily and adds
`contains`, `search` (BM25), `near`, `count_range` and `witnesses`; extracted claims are cached in the store.

### Normalisation tables (`domains/classics/script/`)

`t2s.tsv` — traditional → simplified characters (1:1) from OpenCC `TSCharacters` (Apache-2.0).
`jicheng_variants.tsv` — rare variant forms from the 笈成 viewer's variant table (generated; see above).
`cmeta_variants.tsv` — the rare forms of the CMETA transcriptions (𤍠→熱, 𫞓→歲, 𠉀→候, 𭛁→發 …), found by aligning them
with the other witnesses of the same works.
`ancient_variants.tsv` — ancient and variant forms from the Unicode Unihan database (Unicode License), reviewed
against corpus contexts, plus manual entries for forms that matter in medical texts (䜴→豉, 䓤→葱, 茰→萸, 㪚→散,
讝→谵, 痟→消, 芁→艽, 巵→栀 …). Curated `variants.yaml` entries are applied first and recorded as philological
normalisations; script conversion is systematic and not itemised. All mappings preserve length.

### Harvested vocabulary (`domains/classics/lexicon-harvested/`)

`taochronos lexicon harvest` collects candidate names from the store: drugs from 本草 entries 「X味甘…」 (or, in
punctuated editions, an entry heading followed by 「味甘…」) with their 「一名」 aliases and 本草纲目 entry titles with
the source Li Shizhen credits (本经, 别录…); formulas from prescription headings (the innermost heading of a 笈成
section, counted once per heading, not per passage), block openings and 「…X汤主之」 clauses, with Song-taboo 圆/丸
pairs as synonyms. Disease headings that end like a name (一切痰饮, 留饮) are dropped unless used as a name in
running text, and 「附都气丸」 (附 = appended) is merged into 都气丸. Each entry
keeps its evidence (count, books, earliest witness). Only the `full-corpus` profile loads them, and they never
shadow a curated term; promote reviewed entries into `domains/classics/lexicon/`.
