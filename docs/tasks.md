# TCM Ancient-Book Agent Task Specification v1.0

**中医古籍智能体任务规格 v1.0** —— 把“面向中医古籍的 Computational Philology + Knowledge Discovery Agent”路线图的
L0–L5 与 27 个任务逐项落到 TaoChronos：每个任务写明 **输入 → 输出（JSON Schema）→ Agent / Tool → 算法 →
Benchmark → Metric（当前值）→ Gold dataset → 人工复核 → 状态与局限**。

它回答两件事：这 27 个任务里，哪些已经做成、怎样做、做得多好（有评测数字）；哪些只做了一部分、哪些还没做，缺什么。
数字都来自 `taochronos eval`（TaoChronos-Eval），不是估计；“全库”数字来自全库评测（966 部书、205 万段），
其余来自构造的金标准或演示语料。

## 目录

- [原则](#原则)
- [总表](#总表)
- [L0 古籍数字化](#l0-古籍数字化)（T1–T3）
- [L1 句读与篇章](#l1-句读与篇章)（T4–T6）
- [L2 语义知识](#l2-语义知识)（T7–T10）
- [L3 数字考据](#l3-数字考据)（T11–T19）
- [L4 知识发现](#l4-知识发现)（T20–T27）
- [L5 Research Agent](#l5-research-agent)
- [P0 清单](#p0-清单)
- [TCM Ancient Book Agent Benchmark](#tcm-ancient-book-agent-benchmark)
- [文献](#文献)

## 原则

1. **No evidence, no claim.** 每个结果由“见证”（witness）组成：原文引文、段落 id、书名·卷·篇（locator）、成书年代与
   时期、文本层（正文、注、按、序跋……）、来源与许可。任何一句都能用段落 id 回查原文（`classics.get_passage`），
   任何引文都能用 `validation.verify_quote` 在语料中定位——编造的引文会被抓出来（hallucination 评测）。
2. **原字不改。** 规范化（异体、繁简）只用于检索与比对，不改写原文；句读只插入标点，原文字符保持率是硬约束（1.0）。
3. **假说，不是裁决。** 谱系、传播链、异文分级、学派成员、争议——输出都是供专家复核的假说与证据，附置信度与
   “难定”标记，不宣布哪个版本“正确”。
4. **年代分层。** 每段按其文本层定年（后人注按层计）；早于被引者生年的引用（编者注按原文年代记）被剔出；
   “最早”按下限（terminus ante quem）排序。
5. **状态照实写。** 已实现（有评测）· 部分 · 未实现。未实现的写明缺什么、接口在哪里。

**输出 JSON Schema。** 每个任务的输出是一个 JSON 对象，其 Schema 写在代码里
（`src/taochronos/plugins/classics/study/schemas.py`，`taochronos schema --study <名>` 打印），并由测试
（`tests/test_tasks.py::test_results_match_the_schemas_of_the_task_specification`）拿真实结果逐一校验——规格与代码不会
走样。下文“输出”一栏给 Schema 名与主要字段；各处的见证对象都是同一个 `WITNESS`：

```json
{"passage_id": "…", "book_id": "…", "title": "…", "work": "…", "authors": ["…"], "dynasty": "…",
 "years": [1144, 1144], "period": "宋金元", "layer": "正文|注|…", "locator": "《书》卷·篇", "quote": "原文",
 "source": "来源", "license": "许可", "punctuation": "editorial|none"}
```

## 总表

状态：● 已实现并有评测 · ◐ 部分 · ○ 未实现

| Task | 名称 | 层 | 状态 | 入口（CLI `taochronos …` / Tool） | Agent | 评测 suite | 主要指标（当前） |
|---|---|---|---|---|---|---|---|
| T1 | 版面理解 / 阅读顺序 | L0 | ● | `vision layout`（ALTO / hOCR / PAGE / PaddleOCR / 词元）· `vision read`（多模态模型识读）· `vision fetch`（IIIF 单页） | philologist · curator | layout | 60 页合成版面：阅读顺序全对 0.983、CER 0.0005、小注 F1 0.999；四种格式读出一致 |
| T2 | OCR / HTR | L0 | ◐ | `vision compare`（任何 OCR 文本对库中录入本：CER、异体归一后 CER、易混字）；识别本身交给外部引擎或多模态模型 | philologist | layout（compare） | 12/12 单字错误检出并定位 |
| T3 | 异体 · 古今 · 通假 · 避讳字 | L0 | ● | `philology.normalize` · `study taboo` · `collation.yaml` | philologist | philology · hallucination | 用例通过率 1.0；异体引文可接受 |
| T4 | 自动断句 | L1 | ● | `study punctuate` / `study.punctuate` | philologist | punctuation | 全库留出 boundary F1 0.767（规则 0.235）；白文 0.780 |
| T5 | 自动标点 + 原字保持 | L1 | ● | 同上 | philologist | punctuation | 原字保持率 1.0；标点类型准确率 0.805 |
| T6 | 篇章 · 条文结构 | L1 | ● | `study clause` / `study.clause` | philologist · extractor | clause | 片段角色准确率 0.977，macro-F1 0.917 |
| T7 | 中医专用 NER | L2 | ● | `study entities` / `study.entities`（24 类；规则筛选 + 模型复核歧义与漏读） | extractor · philologist · semanticist | entities | 开发集 F1 0.991；留出 25 句 F1 0.776 |
| T8 | 关系抽取 | L2 | ● | `kg.extract_claims` | extractor | claims | P 0.976 · R 0.952 · F1 0.964 |
| T9 | 术语标准化 / Entity Linking | L2 | ● | `kg.term` · `study names` / `study.names` · `classics.search`（别名层） | semanticist · ontologist | names · anachronism · aliases | 构造例全对；全库避讳改名 2/2；别名首次留出 P@10 0.683 → 0.791 |
| T10 | 训诂 / 古文释义 | L2 | ● | `study glosses` · `study translate`（五层：原文 / 规范 / 句读 / 释义 / 今译；今译须引所用训释并过以今律古护栏） | philologist · semanticist · scholar | glosses · translation | 训诂准确率 1.0；护栏 24/24；原文层不变 24/24 |
| T11 | 跨版本条文对齐 | L3 | ● | `study concordance` / `study.concordance` | scholar | commentaries · reuse | 引文召回 1.0；管线召回 1.0 |
| T12 | 异文自动发现 | L3 | ● | `study variants` / `study.variants` | philologist | collation | 异文单位 R 0.998 · P 0.999 |
| T13 | 异文重要性（Variant Impact Score） | L3 | ● | `study variants`（`impact`、`review_queue`） | philologist | variant_impact | 准确率 0.967；高影响 P 1.0 R 0.941 |
| T14 | 引文 / 文本复用 | L3 | ● | `study reuse` / `study.reuse` | skeptic | reuse | 类型准确率 0.970；检出 P 1.0 R 0.962 |
| T15 | 出处追踪 / 传播 | L3 | ● | `study chain` · `study transmission` · `study citations` · `study fragments` | lineage · scholar | chain · fragments · source_rediscovery | 传播链父本准确率 1.0 / 0.941（有趋同） |
| T16 | 注家自动对齐 | L3 | ● | `study commentaries` / `study.commentaries` | philologist · scholar | commentaries | 注文单位 F1 1.0 |
| T17 | 注家观点 / 学说比较 | L3 | ● | 同上（关系）· `study disputes` | scholar · skeptic | commentaries · disputes | 关系 F1 1.0；驳斥/赞同准确率 0.864 |
| T18 | 版本谱系 / Stemma | L3 | ● | `study stemma` / `study.stemma` | philologist | collation | 分组精度 0.733（前三 1.0）；污染 P/R 1.0 |
| T19 | 全过程 Provenance | L3 | ● | 见证对象 · `validation.provenance_chain` · `validation.verify_quote` · 闸门 G0–G8 | evidence | provenance · hallucination | 伪造/篡改引文检出 1.0 |
| T20 | 方—证—症—药网络 | L4 | ● | `study network` / `study.network` | pattern_miner · scholar | pairs | 见下 |
| T21 | 方剂配伍规律 | L4 | ● | `study pairs` / `study.pairs` | pattern_miner | pairs | 植入药对前三 1.0，假显著 0.0；全库教科书药对 7/7 |
| T22 | 方剂历史演化 | L4 | ● | `study formula` · `analysis.formula_evolution` | scholar · evolution | （测试 + 研究评测） | — |
| T23 | 疾病 / 证候历史演化 | L4 | ● | `study term` · `study senses` | semanticist · evolution | senses | 变化年份误差 2.28 年 |
| T24 | 概念语义演化 | L4 | ● | `study senses` · `study names` · `analysis.concept_drift` | semanticist · evolution | senses · names | 隐藏义项发现 1.0 |
| T25 | 医家 / 流派 | L4 | ● | `study schools` / `study.schools` · `study citations` | lineage · scholar | schools | 教材学说召回 0.727，归属 0.636（44 项） |
| T26 | 理论争议发现 | L4 | ● | `study disputes` · `analysis.contradictions` | skeptic | disputes · contradiction | 矛盾分类准确率 1.0 |
| T27 | 时间 × 人物 × 地域 | L4 | ● | `study places` / `study.places`（地名表 175 处、医家籍贯、序跋落款、地域×时期统计 + BH 校正、GeoJSON） | lineage · scholar | places | 落款与籍贯陈述 P/R 1.0（20 例）；全库 761 部中 291 部定位 |

## L0 古籍数字化

### T1 版面理解 / 阅读顺序 ●

- **输入。** 一页 OCR 引擎的输出（ALTO、hOCR、PAGE XML、PaddleOCR 结果或 `{text, bbox}` 词元，格式自动识别），或
  一张页面影像（交多模态模型识读）；IIIF manifest 的单页由 `vision fetch` 按需取回（一次一页，条款随图记录，图不入库）。
- **输出。** `layout`（PageGraph）：`blocks[{id, kind（main / commentary / header / page_number / margin / title）, text,
  box, order, parts, rule}]`、`reading_order`、`text`（小注在（）中）、`apparatus`（版心、书眉）、`orientation`、`char_size`。
- **算法。** 竖排自右而左：以 p90 字宽估正文字径；双行小注按左右两半配对、右半先读，跨列续接；版心、书眉、页脚按位置分出；
  逐字输出的引擎先按 x 中心聚类成列再按间隙切分。
- **Benchmark。** layout 套件：60 页合成版面（含噪声、逐字输出）阅读顺序全对 0.983、CER 0.0005、块类型 0.98、小注 F1 0.999；
  ALTO / hOCR / PAGE / PaddleOCR 四种读法结果一致。
- **缺什么。** 真实页面的版面金标准（笈成录入本可作“正文 / 注”对照）；插图、表格与朱批的识别。

### T2 OCR / HTR ◐

- **现状。** 未做识别；已入库的 OCR 文本（如康平本）作为普通见证参与校勘，其错字在 `study variants` 中表现为异文。
- **接口。** 评测指标 CER、罕用字召回、阅读顺序准确率可直接用录入本对照 IIIF 页面计算（`study witnesses` 给出二者
  对应）；OCR 置信度写入 `philology.assess_passage` 的 `ocr_confidence` 字段（现为空）与闸门 G1。

### T3 异体字 / 古今字 / 通假字 / 避讳字 ●

- **输入。** 任意文本或段落 id。
- **输出。** `normalize`：`{"normalized": "…", "normalizations": [{"from", "to", "kind"}]}`；
  `philology.assess_passage` 另给每处规范化的位置、争议读法与语文学置信度。原文从不改写。
- **Tool / Agent。** `philology.normalize`、`philology.assess_passage`；`study taboo`（避讳字 → 版本下限）；philologist。
- **算法。** 规则表：`domains/classics/variants.yaml`（异体、繁简，长度不变，便于回指原文位置）；
  `collation.yaml`（校勘用字对应：沉/沈、脏/藏/臟、硬/鞕…——在别处是不同的词，检索时不合并，校勘时作“异体”低权处理）；
  `taboo.yaml`（避讳字与起讫年）；词表同义项的 `taboo_rename`（薯蓣→山药、玄参→元参）。
- **Benchmark / Metric。** philology 套件（用例通过率 1.0）；hallucination 套件中“异体拼写的真引文被接受”（True）。
- **人工复核。** `study variants` 列出各录入本之间最常见的单字替换，供专家决定是否写入 `collation.yaml`。
- **局限。** 规则表是人工的；字形（glyph）层级与部件语义未建模（需图像）。

## L1 句读与篇章

### T4 自动断句 · T5 自动标点 ●

- **输入。** 白文（或带标点的文本——会先去标点，再与编者的标点比较）；`--passage <id>` 或 `--input <file>`。
- **输出。** `punctuate`：`unpunctuated`、`punctuated`、`preserved`（原字全保）、`inserted`、
  `marks[{at, mark, p}]`、`review`（可疑处，附语境）、`model`（版本、训练规模、阈值）、`measured`（输入原有标点时的
  boundary/sentence F1 与标点类型准确率）。
- **Tool / Agent。** `study.punctuate`；philologist。
- **算法。** 从库中编者标点本学得的判别模型（字 n-gram 与词表特征，逐隙判断“断 / 句末 / 标点类型”），阈值在开发集上
  定；输出只插入标点，每个字符原样保留（`preserved` 恒为真，测试检查任意输入）。模型只存本地缓存，不入库、不外传。
- **Benchmark / Metric。** punctuation 套件：留出著作（不参与训练）的 boundary F1、sentence F1、标点类型准确率、
  原字保持率；另测白文（四库本与其笈成标点本对照）。全库（训练 620 万字）：55 部留出著作（10.4 万字）boundary F1
  0.767（P 0.725，R 0.814；规则基线 0.235），带类型的句末 F1 0.543，标点类型准确率 0.805；白文 4 部（10 万隙）
  boundary F1 0.780（规则 0.303）；原字保持率 1.0。
- **Gold。** 笈成标点本（留出著作）；四库白文与其笈成标点本的对照。
- **人工复核。** `review` 列出模型拿不准的断点；编者标点与模型不一致处可逐条核对。
- **局限。** 断句分歧本身有学术争议（同一条文不同注家断法不同），F1 衡量的是与某一编者一致的程度。

### T6 篇章 · 条文结构 ●

- **输入。** 一条条文、一个段落 id，或 `--work`（一部著作的条文形式统计）。
- **输出。** `clause`：`pieces[{text, role, label, rule, terms}]`，角色为 前提 · 病 · 症 · 脉 · 证·病机 · 治则 · 禁忌 ·
  方 · 组成 · 煎制 · 服法 · 加减 · 预后；`form`（角色序列）、`out_of_order`、`findings`、`pulse`、`diseases`、
  `formulas`、`drugs[{text, herbs}]`。白文先经 T4 断句。
- **Tool / Agent。** `study.clause`；philologist、extractor。
- **算法。** 按标点切片；每片按 `domains/classics/clause.yaml` 的规则（先判炮制、煎制、加减，再判其余）与词表类别定
  角色；“主之 / 宜…汤”定方；剂量模式定组成。卷—篇—章—节的层级由录入本的 locator 给出（笈成标题、Kanripo 卷页）；
  正文/注文/按语/序跋由文本层给出。
- **Benchmark / Metric。** clause 套件：片段角色准确率 0.977，macro-F1 0.917，切分 1.0（87 片，涵盖 13 类角色）。
- **Gold。** `evals/gold/clause.yaml`（伤寒论、金匮与方书式条文，人工标注）。
- **人工复核。** 每片附所用规则；规则集中在 `clause.yaml`，可逐条增改。
- **局限。** 一片兼两义时（“脉浮而紧者，名为伤寒”）只给第一条规则的角色。全库《伤寒论》最全录本的 777 条中，
  40% 的片段没有规则认领（平脉法的问答、条文编号、注文）——规则覆盖的是方证条文的典型形式。

## L2 语义知识

### T7 中医古籍专用 NER ●

- **输入。** 一段文字或段落 id（`study entities`）。
- **输出。** `entities`：`[{id, start, end, text, type（24 类：Disease Syndrome Symptom Sign Pulse Tongue Etiology Pathogenesis
  Theory Treatment Formula Herb Dose Preparation Contraindication Nature Physician Commentator Book Edition School Place
  Location Time）, label, ref, source, rule, ambiguous, alternatives, negated, extraction（rule / model）, decided_by}]`。
- **算法。** 规则筛选：词表、医家、书目、地名、朝代年号与模式（剂量、炮制、脉象、舌象）给出候选，最长覆盖优先，
  上下文规则定同形异义（“风”作病因或风证），否定词标出“不恶寒”；然后**模型复核**：歧义项由模型在候选中裁决、
  并可补读规则漏掉的实体——补读须是原文的精确片段、类型须在表内，否则丢弃。
- **Benchmark。** entities 套件：开发集 41 句 160 实体 F1 0.991；**留出集** 25 句 117 实体（写完规则后标注）F1 0.776
  （首测 0.757，修正两处处理链缺陷后 0.776；未为留出内容增加规则）。
- **Gold。** `evals/gold/ner.yaml`、`evals/gold/ner_heldout.yaml`。

### T8 关系抽取 ●

- **输入。** 段落 id。
- **输出。** `claims`：`[{id, passage_id, relation, arguments[{role, term_id, surface, start, end, negated}], quote,
  start, end, polarity, modality, extraction{method, rule, confidence}, confidence{…}}]`——每条关系带原文区间。
- **Tool / Agent。** `kg.extract_claims`、`kg.claims`、`kg.neighbors`；extractor。
- **算法。** 规则抽取（治疗、组成、禁忌、病机、传变、预后、定义、理论等关系），否定与情态随之记录；关系作为超边
  进入知识超图，保留时间（成书、作者、版本、引用）四个维度。
- **Benchmark / Metric。** claims 套件：P 0.976 · R 0.952 · F1 0.964（按关系的召回见 evals.md）；出处通过率 1.0。
- **Gold。** `evals/gold/claims.yaml`。
- **人工复核。** `kg.propose_change` 只提议，不直接改图；专家批准（G7）才生效。

### T9 术语标准化 / Entity Linking ●

- **输入。** 一个药名、方名或病名（`study names 山药`）；或任一表面形式（`kg.term`）。
- **输出。** `names`：`names[{name, kind（本名/异名/避讳改名/炮制名…）, note, passages, works, first[WITNESS]}]`、
  `periods[{period, works, shares, preferred}]`、`bins`（百年段）、`switches[{from, to, between}]`（通行之名的更替）、
  `equations`（书中以二名相释之处）、`candidates`（词表未收之名）。
- **Tool / Agent。** `kg.term`（表面形式 → 历史概念 → 规范概念，带义项与时期）、`study.names`；semanticist、ontologist。
- **算法。** 词表把表面形式映射到条目（Mention → Historical Concept → Canonical Concept）；`study names` 逐名统计各期
  写作该名的著作数（一部著作计一次，嵌套名如“干山药”不计入“山药”），找出通行之名的更替（孤立一段的波动按邻段读），
  在标点本中读取“X，一名Y / 又名 / 俗呼 / 今名 / 即”找出词表未收之名。
- **Benchmark / Metric。** names 套件：构造语料上更替区间、嵌套分离、互释句全对；全库：有史可稽的避讳改名
  （薯蓣→山药，宋英宗；玄参→元参，康熙）更替落在其年代区间 2/2。anachronism 套件（古今映射不得混同）1.0。
- **Gold。** `evals/gold/names.yaml`（按帝王在位年定区间，与语料无关）。
- **人工复核。** 候选别名（如“山芋”）只是读出，须专家写入词表才算数；映射一律“提议”（`kg.propose_change`）。
- **举例（全库）。** 山药：隋唐以前通行“薯蓣”，1000–1200 年间让位于“山药”；玄参：1700 年代“元参”占上风，民国复归
  “玄参”（避讳解除）；“薯蕷，俗名山藥”（《珍珠囊补遗药性赋》）为互释之证；词表未收的“山芋”见于《本经》森立之本等 6 部书。
- **检索中的药物异名（别名层，[ADR 0023](adr/0023-alias-layer.md)）。** `classics.search` 多一个参数 `aliases`：`auto`（默认；
  画像开启别名层时，问到药名即另检其他名）或 `off`（只检所问之词，即原来的检索）。他名命中至多占 10 条中的 3 条（第 4、7、10 位），
  其余位置仍归所问之名；这几个位置由两类命中交替占用：经别名检出者路由记为 `alias`（`routes` 不含 `alias` 时不另检），
  所问之药在词表中的他形命中保留原路由，出处为“词表”。输出（Schema `search`，`taochronos schema --study search`）
  在原有字段外另有三项，非空时才出现：
  - `query.aliases`：`asked[{surface, term, ambiguous, note, referents[{head, kind, status, valid, floor, source, witness,
    witness_year, credited}]}]`——问句中作药名来问的各名及其所指之药（同名异物全部列出，`ambiguous` 为真）；`valid` 为分期窗口
    `[from, to)`，`floor` 为通行年代的下限，`credited` 为《本草纲目》释名所注出处 `[work, y0, y1]`（书名与成书起止年，无则 null）；
    常用词（stop）单独来问时列出其可能所指，`status` 为 `stop`，并以 `note` 说明多作普通词语、未按其名检索；
    词表将其收为药名者（如景天条下的“救火”），`note` 改为只按词表检索其同条之名，所得命中的 `via` 状态为 `stop`。
    `expansions[{surface, for, direction, referent, kind, status, searched, why}]`——所加之名；`searched` 为假时 `why` 说明原因：
    `cap`（超出上限）、`unattested`（库中未见）、`part`（同株另一部位，只列不检）、`routes`、`share`（无他名位置）。
    `excluded[{surface, for, why}]`——因年代不合未加之名（`why: period`）。
  - `hits[].via[{surface, for, referent, direction, kind, status, source, witness, reading, p}]`：此段写作之名、`for`（所代表的
    所问之名，恒为列表）、所指之药、方向（`alias→drug`、`drug→alias`，或 `asked`：所问之名本身在此段的读法）、类别（异名、
    避讳改名、药用部位名、炮制/加工名、简称、品种/产地名、异写、古名、俗名）、状态（`open`、`cue`、`candidate`、`stop` 或 null）、
    出处标签（如“别名录（中醫笈成）”“古籍互证”“词表”）、书证段落、读法及其概率 `p`。
  - `hits[].flags`：`anachronism:<名><<年>:edition|layer`（此段早于该名通行之年：刊本改字或后人增补）、`homonym:<名>`（同名异物，
    此段未能判定）、`demoted:inside <较长之名>`、`demoted:no-context`（只见于较长之名中或不在药物语境，排在后面）、
    `other-referent:<名>`（此段年代该名另指他药）。
  评测：`aliases` 套件（[evals.md](evals.md)），120 个药名问题、一半留出；首次留出报告 web-canon P@10 0.683 → 0.791，验收 6/10。

### T10 古文释义 / 训诂 ●

- **输入。** 一个字词（`study glosses 几几`）或一部注本（`--book`，其训诂表）。
- **输出。** `glosses`：`glosses[{kind（…者…也 / 貌 / 音 / 反切 / 读为 / 当作 / 一作 / 通）, head, gloss, by（注家）,
  title, passage_id, years, period, type（义/音/文字）, sentence}]`、`readings`（同一释义的诸家与首出者）、`by_period`。
- **Tool / Agent。** `study.glosses`；philologist、semanticist。
- **算法。** 按 `exegesis.yaml` 的训诂格式抽取释义，头词须与所问之词相同（“项背强几几者”释的是“几几”）；
  音注、反切、当作、一作取原文字形（规范化会把“痓当作痉”的两字合一）；同一著作的多个录本只计一次。
- **Benchmark / Metric。** glosses 套件：准确率 1.0，P/R 1.0（16 例）；全库「几几」5 条训释、4 种释义，首出为成无己
  “伸颈之貌”。
- **Gold。** `evals/gold/glosses.yaml`。
- **缺什么。** 路线图中的“逐词训诂 → 句法 → 术语解释 → 句义 → 白话翻译”的后三步：白话翻译需要语言模型，
  且须把译文与训诂证据、原文分开存放（译文不是原文）。现有的是证据层：诸家怎样训释这个词。

## L3 数字考据
- **今译（五层文本）。** `study translate`：原文（永不改动）→ 规范（异体归一）→ 句读（编者标点或句读模型）→ 释义（叠词与术语
  的注家训释及首出者，按年代与语境选择策展义项）→ 今译（有模型复核时生成：须引所用训释，须过以今律古护栏——不得把古病名
  写成现代病名）。translation 套件：护栏判例 24/24，原文层不变 24/24，叠词皆由其注家训释 3/3。

### T11 跨版本条文对齐 ●

- **输入。** 一条条文或段落 id。
- **输出。** `concordance`：`hits[WITNESS + {coverage, relation（同书异本/引文/互见）, aligned, marker}]`（按年代）、
  `apparatus[{base, reading, kind（异文/脱/衍/倒）, witnesses, impact, score}]`、`summary`。
- **Tool / Agent。** `study.concordance`；scholar。
- **算法。** 规范化后切 4 字探针（全文索引不跨标点，故另取问句每个标点段内最罕见的探针），罕见探针召回候选，
  局部对齐（difflib）取最密的对齐块，按覆盖率（≥0.6）保留；引书标记（《…》曰、经曰、仲景云…）定“引文”，
  同一著作定“同书异本”，其余为“互见”。路线图的 exact / near / abridged / expanded / reordered / paraphrased / uncertain
  对应 T14 的复用类型。
- **Benchmark / Metric。** commentaries 套件的引文召回 1.0；reuse 套件的管线召回 1.0。
- **举例（全库）。** 「病人脏无他病…宜桂枝汤」：宋本此条两见（太阳篇作“宜桂枝汤”，可发汗篇作“属桂枝汤”），二者都是
  源头读法；《脉经》《千金》《千金翼》《类证活人书》《注解伤寒论》以下历代转引，按年代排列，附校勘记。
- **局限。** 召回受探针限制：异文密集或改写很重的见证可能漏检（传播链评测在强噪声下见证召回 0.958）。

### T12 异文自动发现 ●

- **输入。** 一部著作（其各录本），或 `--text-mode` 下一条条文的各见证。
- **输出。** `variants`：`witnesses`、`units[{id, start, end, lemma, kind, readings[{text, witnesses}], impact}]`、
  `review_queue`、`summary{units, substantive, per_1000}`；`study tei` 输出 TEI P5 校勘记。
- **Tool / Agent。** `study.variants`、`study.tei`；philologist。
- **算法。** 以一本为底本，逐本对齐投影到底本位置，合并成异文单位；相交的改动拆成列（每列一组同改的见证）；
  类型：增（衍）、删（脱）、改（异文）、倒、缺文、结构性增删、异体（`collation.yaml` 等价字，低权，不入谱系）。
- **Benchmark / Metric。** collation 套件（人工传承：已知底本按已知谱系抄写，逐代加入已知改动，5 组）：单位召回 0.998、
  精度 0.999、拆分召回 1.0。
- **Gold。** 构造的人工传承（evals/textual.py，真值精确已知）。

### T13 异文重要性判断（Variant Impact Score）●

- **输出。** 每个异文单位的 `impact{impact, label, score, reason}` 与按分数排序的 `review_queue`；分级：剂量 1.0 ·
  否定/情态 0.95 · 方药 0.90 · 证候 0.80 · 结构（长）0.60 · 实词 0.50 · 倒文 0.35 · 阙文 0.30 · 虚词 0.20 · 异体 0.05。
- **算法。** 规则按序判定（`collation/impact.py`）：先排除异体与阙文，再看数字/量词是否构成剂量或服次（排除“半表半里”
  “十枣汤”等），再看否定与情态词，再看药名与方名（在上下文中读），再看症、脉、证等临床术语。
- **Benchmark / Metric。** variant_impact 套件：准确率 0.967，macro-F1 0.972；高影响（剂量/否定/方药/证候）P 1.0 R 0.941；
  全库（伤寒论诸本）288 个异文单位，复核队列前十皆为高影响。
- **Gold。** `evals/gold/variant_impact.yaml`（30 例）。
- **人工复核。** 分数只用于排复核队列——专家先看剂量、否定、方药的异文——不据此判定哪一本对。

### T14 引文 / 文本复用检测 ●

- **输出。** `reuse`：`hits[WITNESS + {label（直接引用/近似转录/节略/撮要/转述/解释性改写/引而驳之/套语相似）,
  mode, direction（更早/更晚/难定）, rule, features}]`、`summary{reuses, works, by_label}`；`study reuse --against`
  判断一对文本。
- **Tool / Agent。** `study.reuse`；skeptic（查假说的证据是否只是同源复写）。
- **算法。** 两段式：字面探针与概念共现召回候选，再按规则分型（共享字比例、最长公共片段、顺序、概念保持、驳斥标记），
  每条附所触发的规则与读到的数值；方向按年代。
- **Benchmark / Metric。** reuse 套件：类型准确率 0.970，macro-F1 0.965；复用检出 P 1.0 R 0.962。
- **Gold。** `evals/gold/reuse`（33 对，涵盖八类）。

### T15 出处追踪 / 传播 ●

- **输入。** 一条条文（`study chain`）、一部著作（`study transmission`）、一部书或一位医家（`study citations`）、
  一部佚书（`study fragments`）。
- **输出。** `chain`：`nodes[{passage_id, title, years, relation, innovations, depth}]`、
  `edges[{from, to, basis, shared[{root, reading}], score, margin, uncertain, dates_overlap}]`、`summary`；
  `transmission`：条文在后世的复用、分期、渠道（经中间著作的转引）；`citations`：历代谁引了它、首引者、分期。
- **Tool / Agent。** `study.chain`、`study.transmission`、`study.citations`、`study.fragments`；lineage、scholar。
- **算法（传播链）。** Lachmann 的“共同讹误”原则：以最早一期见证为源（最早一期诸本的读法都算原有），后出见证的
  读法中源所没有的即其“创新”；每个见证挂到与它共享创新最多的更早见证（减去该见证有而它没有的创新之半），
  都不共享则挂在源下（直接或经亡佚中介，文本无法区分）；只按异体字不同者不算创新，虚词之差减半。
- **Benchmark / Metric。** chain 套件（人工传承，6 组×12 见证）：父本准确率 1.0（基线“最相似的更早见证”0.972）；
  加入抄手各自独立的用字规范化后 0.941（基线 0.868）。fragments 套件（佚书辑佚）精度 0.857、覆盖 1.0、
  卷次 1.0；source_rediscovery（留出书目的来源重现）recall@3 1.0。全库两条《伤寒论》条文：各 60 处有年代见证，
  经中间见证者 10 处与 8 处（如 脉经→千金翼方、尚论篇→张氏医通→伤寒溯源集→伤寒大白），最深 2 层与 4 层。
- **人工复核。** 每条边给出共享的异文与边际（margin < 1 标“难定”）；年代交叠的边另标。一条条文的传播是那一条的
  路线，不代表整部书的源流（整部书用 T18）。

### T16 注家自动对齐 · T17 注家观点比较 ●

- **输入。** 一条条文或段落 id。
- **输出。** `commentaries`：`commentaries[{id, commentator, person, title, voice, years, period, text, passage_ids,
  concepts, cites, added}]`（按年代挂到这一条文下）、`relations[{from, to, type, share}]`、`consensus`、`unique`、
  `first_readings`、`quotations`（引用而非注释）。关系类型：照录 · 承袭 · 自录（措辞）；同解 · 增益 · 异解（内容）；
  驳 · 从（明言）。
- **Tool / Agent。** `study.commentaries`、`study.disputes`；philologist、scholar、skeptic。
- **算法。** 在注本中定位条文（四种排版：条文后一行、独立注文层、连写、括注），截取其后的注文单位；以注家（文本层
  或作者）与年代标注；措辞比较时遮去经文引文；概念集合比较得同解/增益/异解；“非也”“误矣”“当从”等标记读出驳与从
  （`exegesis.yaml`）。路线图的 agreement / disagreement / extension / reinterpretation / rejection 分别对应
  同解 / 异解 / 增益 / 异解 / 驳。
- **Benchmark / Metric。** commentaries 套件：注文单位 F1 1.0（13 单位）、文本 F1 0.810、关系 F1 1.0、引文召回 1.0；
  disputes 套件：准确率 0.864，驳 P 1.0 R 0.778，从 P 0.8 R 1.0（22 例）。全库：「太阳之为病」的已知注家 11/11、
  已知承袭关系 2/2；已知争议 3/3（丹溪被驳 32 次、被从 11 次）。
- **Gold。** `evals/gold/commentaries/`（构造的经文与四种排版的注本，CC0）、`evals/gold/disputes.yaml`。
- **举例（全库）。** 「太阳之为病」：自 1144 年起 25 家注；张卿子照录成无己，喻昌承袭方有执；共识概念“表”，首见成无己。

### T18 版本谱系 / Stemma ●

- **输出。** `stemma`：`units`、`distances`、`tree`（邻接法）、`root`、`newick`、`ascii`、`groups`（共享读法组）、
  `patterns`、`contamination`（混合传承）、`conflicts`。
- **算法。** 以实质异文（剔除异体与结构性增删）计见证间距离，邻接法建树（中点或指定定根），共享读法组给出分支
  证据，冲突的分组指示污染。输出是假说。
- **Benchmark / Metric。** collation 套件：Robinson–Foulds 距离 0.333、分组精度 0.733（前三 1.0）、污染 P/R 1.0。
- **局限。** 条文次序、成书地点、人物关系尚未用于定根；整部书的谱系只在有多本录入的著作上可做。

### T19 全过程 Provenance ●

- **输出。** 每个结果的见证对象（见[原则](#原则)）；`provenance`：`[{level（passage/edition/book/source/page/image…）,
  id, label, available}]`；`verify_quote`：`[{passage_id, start, end}]`。
- **Tool / Agent。** `validation.provenance_chain`、`validation.verify_quote`、`validation.gates`；evidence。
- **算法。** 事件溯源的研究对象：每个结论 → 关系超边 → 原文区间 → 段落 → 版本 → 书 → 来源（许可、获取方式、
  录入方）；闸门 G0 来源 · G1 录入/OCR · G2 语文学 · G3 语义 · G4 出处 · G5 独立重复（按作者/录本簇计，不按书计）·
  G6 证伪 · G7 专家（仅人类）· G8 生物医学证据（仅跨空间假说）。
- **Benchmark / Metric。** hallucination 套件（60 例）：原文引文召回 1.0，篡改、伪造、错位引文检出均 1.0；provenance 套件：
  主张与证据逐字可查 1.0、假说皆有证据 1.0，溯源链平均 7.8 级（结论 → 证据 → 主张 → 段落 → 书 → 版本 → 卷/篇/节）；
  页、行、区域、影像四级在演示语料上缺，待 T1/T2。
- **缺什么。** Claim → 像素：页面影像层（T1/T2）接上后补齐 page → image 两级（Kanripo 与 CMETA 已有页码或页面链接）。

## L4 知识发现

### T20 方—证—症—药多层网络 ●

- **输入。** 一个方名、一个症/证名，或空（全库最强的方证联系）。
- **输出。** `network`：`kind`、`indications`、`findings[{finding, category, support, share, lift}]`、
  `drugs[{drug, compositions, share}]`、`by_period`、`examples`。
- **Tool / Agent。** `study.network`；pattern_miner、scholar。
- **算法。** 一次扫描全库（缓存）：写出的组成（方名后的药与剂量，药按药族归并：桂枝/桂心/肉桂 → 桂）与治疗句
  （…主之、宜…汤：方前所列的症、脉、证、病），同一著作多个录本只计一次；方证联系按提升度与 NPMI 排序。
- **Benchmark / Metric。** pairs 套件（演示语料上桂枝汤的药与主治）；全库：桂枝汤居前的主治为 汗出、发热、脉浮、
  恶寒、太阳病，麻黄汤为 脉浮、无汗、伤寒、喘、发热。
- **举例（全库）。** 黄芪桂枝五物汤—血痹、炙甘草汤—脉结、乌梅丸—吐蛔、麻黄汤—脉浮/无汗/喘/衄。
- **局限。** 方前所列之症不等于该方所治（条文可能在比较或排除），故每条附例句。

### T21 方剂配伍规律 ●

- **输出。** `pairs`：`pairs[{a, b, support, lift, pmi, npmi, p, significant}]`；指定药时 `partners[{with, support,
  p_with_given_drug, p_drug_given_with, lift, npmi, significant}]`、`triples`、`by_period`；无指定时 `groups`（药群）。
- **算法。** 以一首组成为一笔交易：支持度、双向置信度、提升度、PMI、NPMI（排序用，避免罕见药居前）、单侧 Fisher
  检验与 Benjamini–Hochberg 多重校正；显著药对图的社区即“常相配伍的药群”；按时期看一对药的占比。路线图列的
  关联规则 / PMI / 社区发现 / 时间分析已实现；频繁子图、嵌入、贝叶斯关联未做。
- **Benchmark / Metric。** pairs 套件：植入药对居前三 1.0，其余药对假显著率 0.0；全库 66,196 首组成，七组教科书药对
  （桂枝—芍药 2527 首、提升度 2.05；麻黄—杏仁 894 首、5.08；柴胡—黄芩 1181 首、3.34；半夏—生姜、大黄—芒硝、附子—干姜、
  当归—川芎）全部显著且提升度 > 1.5。
- **举例（全库）。** 药群复现功能组（六味、四物、攻逐、破血、理气、消导、杀虫、利水、安神）；显著药对如
  水蛭—虻虫、昆布—海藻、乳香—没药、大戟—甘遂。

### T22 方剂历史演化 ●

- **输入。** 一个方名（`study formula 四君子汤`）。
- **输出。** `formula`：`witnesses`（每一处写出的组成，带剂量与炮制）、`groups[{core, witnesses, relation（原方/
  通行方/加减化裁/同名异方/孤例）, earliest, span}]`、`modifications`（加减）、`ratios`（剂量比）、`other_names`
  （同方异名）、`songs`（方歌）、`metrology_notice`。
- **Tool / Agent。** `study.formula`、`analysis.formula_evolution`；scholar、evolution。
- **算法。** 见 study.md「方源考」：按药族比较组成，Jaccard 聚类，最早见者为原方、见证最多者为通行方；剂量按其时代
  的度量衡读出（**历史读法，绝非用药剂量建议**）。
- **Benchmark。** 单元测试与研究评测（D 轨）；尚无方剂演化的专家 gold（路线图列为待建）。

### T23 疾病 / 证候历史演化 · T24 概念语义演化 ●

- **输入。** 一个术语（`study term 消渴`、`study senses 消渴`）。
- **输出。** `term`：各期出现率（每万段，Wilson 区间）、趋势检验、最早见证、各期搭配词、最密集的书、义项；
  `senses`：各期义项占比、变化点、词表未收的候选义项、各期语义邻域。
- **Tool / Agent。** `study.term`、`study.senses`、`study.names`、`analysis.concept_drift`；semanticist、evolution。
- **算法。** 义项由 `terminology.yaml` 的线索词判定，未判定的语境聚类得候选新义项；变化点检验；语义邻域为各期
  搭配词的提升度。路线图的 diachronic embedding 以共现邻域代替（不依赖向量模型，可解释）。
- **Benchmark / Metric。** senses 套件：变化年份误差 2.28 年、变化检出 1.0、标注准确率 0.930、隐藏义项发现 1.0。

### T25 医家 / 流派演化 ●

- **输入。** 一个学派或支派（`study schools 温病`、`错简重订`、`丹溪学派`），或空（总览）。
- **输出。** `schools`：`members[{person, name, dates, works}]`、`comparison`（对照著作数、作者单位、体裁构成）、
  `vocabulary[SHARE_ROW + {type（词/药/方/煎服）, per_10k, used_in, example}]`、`drugs`、`formula_words`、
  `formulas`、`probes`、`citations{cited, homophily{own_share, other_share, ratio}, cites_schools, cited_by_schools,
  rejects_schools, rejected_by, lineage}`；总览另有学派×学派的引用与驳斥矩阵。
- **Tool / Agent。** `study.schools`、`study.citations`；lineage、scholar。
- **算法。** 学派与成员取自 `schools.yaml` 与 `physicians.yaml`（中医各家学说教材的分派：伤寒〔错简重订·维护旧论·
  辨证论治〕、河间、攻邪、易水、丹溪、温补、温病〔温疫〕、汇通……）。本派著作（传统或辑录归属）与同时代（前后 60 年）
  他人著作比较：每位医家只算一个单位，对照组按本派的体裁构成（论著/医案/方书/本草/歌赋）加权；二至四字词按
  Monroe–Colaresi–Quinn 的带信息先验的对数几率（用频 z）排序，显著须同时通过 Benjamini–Hochberg 与“用者比例”检验；
  引用来自全库引人网络（引而驳之的立场读法同 T17）。
- **Benchmark / Metric。** schools 套件：构造语料上植入词居首且显著、共有症状不入列、本派互引；全库：教材所言各派
  学说（`evals/gold/schools.yaml`，44 项）被本派用得更多（z ≥ 1.96）0.727（32/44），用得最多的正是教材所给学派
  0.636（28/44）；本派互引倍数：易水 4.96、温病 4.05、汇通 2.32、伤寒 1.90、丹溪 1.68、温补 0.87。
- **举例（全库）。** 河间：热甚、热极、凉膈、郁结、里热、怫郁、两感，偏用凉膈散、双解散、三一承气汤；易水：气味厚薄
  （味浓、味薄、阴中之阳）、经药；温补：命门（z 7.6）、先天、六味丸、八味丸、补中益气、归脾；温病：时疫、疫邪、风温、
  膜原、战汗、伏邪、斑疹、温邪、辛凉，偏用达原饮，互引为同时代他人的 4.05 倍，王士雄→章楠为派内最强的引用；
  学派之间：丹溪→河间 2.0 倍、温补→易水 1.4 倍与→丹溪 1.6 倍，与教材所述源流一致。未中的学说同样有意思：《儒门事亲》
  写“汗下吐”（44 段）而几乎不写教材的“汗吐下”（1 段）；丹溪诸书多作“补阴”（47 段），少作“滋阴”（6 段），
  “滋阴派”是后人的标签。
- **人工复核。** 学派是后世史家的归类，成员表是可检验的约定而非文本所言；一个词“用得更多”不等于学说，须读其例句。
- **局限。** 注家著作携带其所注经文的用词（伤寒学派的特征词大半来自《伤寒论》本身）；只有一两位成员的学派（攻邪、
  汇通）统计力弱。

### T26 理论争议发现 ●

- **输入。** 一个术语（`study disputes 相火`）、一位医家（`--person 丹溪`），或空（全库谁驳谁）。
- **输出。** `disputes`：`who_rejects_whom`、`most_disputed`、按术语或医家的驳与从，每条带原文与“转述者”
  （A 书转述 B 驳 C）。
- **Tool / Agent。** `study.disputes`、`analysis.contradictions`（D5：同一对象、相反断言、区分条件句与矛盾）；skeptic。
- **算法。** 在引人处读立场（`exegesis.yaml`：直接引语、非也/误矣/不可从 → 驳；当从/诚是 → 从；否定之否定按肯定），
  后出文本层中的驳斥按其层计；D5 按时间距离与学派把矛盾分为直接矛盾与理论框架不同。路线图的 Consensus / Minor /
  Major / Contradiction / Different framework 中，“共识”由 T17 的同解与 `consensus` 给出，“框架不同”由 D5 的学派判据给出。
- **Benchmark / Metric。** disputes 套件（见 T17）；contradiction 套件：准确率 1.0，macro-F1 1.0（12 对）。
- **举例（全库）。** 张介宾是驳丹溪最多者；景岳驳丹溪“相火”（见《吴医汇讲》《医述》转述）；越人“左肾右命门”屡被驳。

### T27 时间 × 人物 × 地域 ●

- **输入。** 一个地名（`study places 江南`）、一个术语（`--term 湿温`）、一个学派（`--school 温病`）或一位医家（`--person`）。
- **输出。** `places`：医家籍贯与行医地、著作的刊刻 / 撰著地（作者籍贯与序跋落款两路）、地域 × 时期的术语或学派份额（两比例
  z 检验 + Benjamini–Hochberg 校正）、GeoJSON。
- **算法。** 地名表（`places.yaml`，175 处，县→府 `in` 链接、异名 `same_as`、歧义标注）；序跋落款须“地名 + 人名 + 序识书题跋”
  且动词在句末，排除“诸…及…”并列与他人之名；传记中“X 人”的籍贯陈述。
- **Benchmark。** places 套件：落款 15 例、籍贯陈述 5 例 P/R 1.0；104 位医家中 84.6% 有地点；全库 761 部中 291 部定位
  （作者 223、落款 68），策展籍贯与文中陈述一致 4/4。
- **例（全库）。** 清代江南著作用“湿温”者 49%，他区 26%（z 2.52，q 0.108）——校正后不显著，如实报告。

## L5 Research Agent

研究循环（`taochronos research "问题"`）：Director 规划 → Curator 冻结语料范围与留出 → 检索与抽取（Evidence、
Extractor）→ 语文学评估（Philologist）→ 源流考证（Scholar：全库追踪焦点术语、方剂、药物，结果作为 Discovery Report
附录「源流考证」）→ 发现引擎 D1–D5（Pattern Miner：失传知识、概念漂移、方剂演化、关联与链接预测、矛盾）→ 统计
（Statistician：显著性、多重检验、覆盖）→ 假说（Hypothesis）→ 证伪（Skeptic）→ 闸门 G0–G8 与评分 → Meta-Reviewer →
报告。事件溯源，可分支、重放、恢复；语言模型可选（离线程序即可跑完全程）。

**路线图的 8 个领域 Agent 与 TaoChronos 的对应**（TaoChronos 用 16 个角色 + 58 个工具，而不是一任务一 Agent）：

| 路线图 | TaoChronos |
|---|---|
| Document Agent（OCR、版面） | 未实现（T1/T2）；影像见证目录为接口 |
| Philology Agent（异体、句读、训诂、翻译） | philologist（`philology.*`、`study.punctuate/glosses/clause/variants/stemma/…`） |
| Collation Agent（对齐、异文、校勘） | philologist（`study.variants/stemma/witnesses`）、scholar（`study.concordance`） |
| Intertext Agent（引文、复用、出处、传播） | lineage（`classics.lineage`、`study.chain/schools`）、skeptic（`study.reuse`） |
| TCM Knowledge Agent（NER、RE、本体、KG） | extractor、ontologist、curator |
| Evolution Agent（概念、方剂、流派） | evolution、semanticist（`study.senses/names`）、scholar |
| Research Agent（问题分解、分析、假说） | director、hypothesis、pattern_miner、statistician |
| Evidence/Critic Agent（provenance、反证、质控） | evidence、skeptic、meta_reviewer |

**路线图的 4 个“科研级任务”**：

| 任务 | TaoChronos |
|---|---|
| Evidence Agent：每个结论有无原文 | evidence（证据账本：逐字、可定位、独立来源）；`validation.verify_quote`；闸门 G4 |
| Counterevidence Agent：主动找反例 | skeptic（证伪：找反证、查复用是否同源、查年代与争议）；闸门 G6 |
| Uncertainty Agent：置信等级 | 评分卡（文本支持、重复、语文学、时间、统计…九维置信）；G5 按作者/录本簇计独立性；“难定”标记 |
| Critic Agent：推论是否超出证据 | skeptic 与 meta_reviewer；古今映射只作“候选”，跨空间结论必须过 G8 |

**假说生成。** hypothesis 角色把观察（如“明以后某方某药比例升高”）写成可检验的假说，skeptic 逐条检索反例，统计
与闸门决定能否晋级；分支与锦标赛比较竞争假说。

**Benchmark。** time_machine（隐去某年之后的文本，看系统能否“预言”后来出现的知识；以 1368 为界：14 个假说、3 个可检
预测，准确率 0.667，截止后的证据泄漏 0）、recovery（在 4 个崩溃点中断后恢复成功率 1.0，重放一致、并行等价）、ablations
（去掉 Skeptic 多存活 1 个错误假说；上下文视图比整段倾倒少用 94% 的 token；只用 BM25 或只用向量检索的召回 0.667 对全路由
1.0）、temporal（时间约束 1.0，时期泄漏 0）、anachronism（时代错置的陈述与映射全部拦下）、source_rediscovery（来源重现）。

## P0 清单

| 路线图 P0 | 状态 | TaoChronos |
|---|---|---|
| 原文精确检索 + provenance | ● | `classics.search`（全文、规范化、异体扩展、药物异名、时间过滤）· 见证对象 · `verify_quote` |
| 自动句读 | ● | T4–T5 `study punctuate` |
| 中医实体识别 | ● | T7 `study entities`（24 类，规则 + 模型复核；留出 F1 0.776） |
| 实体关系抽取 | ● | T8 `kg.extract_claims` |
| 术语/别名规范化 | ● | T9 `kg.term` · `study names` · 别名层（`classics.search` 的 `aliases`） |
| 跨版本条文对齐 | ● | T11 `study concordance` |
| 异文自动识别 | ● | T12–T13 `study variants` |
| 引文 / text reuse 检测 | ● | T14 `study reuse` |
| 注家对齐 | ● | T16 `study commentaries` |
| 注家观点比较 | ● | T17 `study commentaries` · `study disputes` |
| 方—证—症—药知识图谱 | ● | T20–T21 `study network` · `study pairs` · 知识超图 |
| 所有结论回溯至原文/版本/页码 | ● | T19（至页；版面块与框见 T1） |

第二阶段各项（谱系、概念演化、流派、方剂演化、时空、争议、假说）均已实现（T18、T22–T27、L5）。

## TCM Ancient Book Agent Benchmark

路线图的评测表与 TaoChronos-Eval 的对应（`taochronos eval [--quick] [suite …]`）：

| 能力 | 指标 | TaoChronos-Eval suite | 当前值 |
|---|---|---|---|
| OCR | CER / 字准确率 | layout（compare） | 对库中录入本核对：单字错误 12/12 检出（识别交外部引擎） |
| 句读 | Boundary F1 | punctuation | 全库留出 0.767（规则 0.235）；白文 0.780（规则 0.303） |
| 标点 | Punctuation F1 / 类型准确率 | punctuation | 带类型句末 F1 0.543；类型准确率 0.805 |
| 原文保护 | Character Preservation | punctuation | 1.0 |
| NER | Entity F1 | — | 未单列（T7） |
| RE | Relation F1 | claims | 0.964 |
| Entity Linking | Accuracy | names · anachronism | 避讳改名 2/2；映射准确率 1.0 |
| 条文对齐 | Recall | commentaries · reuse | 引文召回 1.0；管线召回 1.0 |
| 异文检测 | Variant F1 | collation | 单位 P 0.999 · R 0.998 |
| 异文分级 | Accuracy / 高影响 F1 | variant_impact | 0.967 / 0.970 |
| 引文发现 | Precision / Recall | reuse | P 1.0 · R 0.962 |
| 传播链 | 父本准确率 | chain | 1.0；趋同噪声下 0.941（基线 0.868） |
| 注家对齐 | Alignment F1 · 已知注家 | commentaries | 1.0 · 11/11 |
| 注家观点 | Relation F1 / 立场准确率 | commentaries · disputes | 1.0 / 0.864 |
| 谱系 | RF · 分组精度 · 污染 | collation | 0.333 · 0.733 · 1.0 |
| KG | Triple P / R | claims | 0.976 / 0.952 |
| 配伍 | 植入发现 · 假显著 · 教科书药对 | pairs | 1.0 · 0.0 · 7/7 |
| 学派 | 学说召回 · 归属 | schools | 0.727 · 0.636 |
| 引文真实性 | Citation Accuracy | hallucination | 伪造/篡改/错位检出 1.0 |
| Grounding | Evidence Faithfulness | hallucination · provenance | 原文召回 1.0 |
| 历时分析 | 变化年份误差 · 专家评价 | senses · names | 2.28 年；专家评价待做 |
| 假说发现 | Novelty + Evidence Support | time_machine · source_rediscovery | 以 1368 为界的时间机器：可检预测准确率 0.667，证据泄漏 0；来源重现 recall@3 1.0 |

## V2：技能与任务的对应

V2（[v2.md](v2.md)）把上面的能力组织成 15 项技能（`skills/manifests/`），由 4 个核心智能体持有，按问题编译成工作流执行
（`taochronos ask`）：

| 技能 | 任务 | 工具 | 模型 |
|---|---|---|---|
| S01 来源与版本 | T19 · 检索 | `classics.search` | 不需要 |
| S02 影像与版面 | T1 · T2 | `vision.layout`（`vision read` 需多模态模型） | 可选 |
| S03 句读·训诂 | T4 · T5 · T10 | `study.translate` · `study.glosses` | 可选 |
| S04 条文结构 | T6 | `study.clause` | 不需要 |
| S05 校勘 | T11 · T12 | `study.concordance` | 不需要 |
| S06 互文与传承 | T14 · T15 | `study.reuse` | 不需要 |
| S07 知识抽取 | T7 · T8 | `study.entities` · `kg.extract_claims` | 可选 |
| S08 名称规范 | T9 | `study.names` | 不需要 |
| S09 源流演变 | T23 · T24 | `study.term` · `study.senses` | 不需要 |
| S10 古代表型化 | （新） | `bridge.phenotype` | 可选 |
| S11 本体桥接 | （新） | `bridge.map` | 不需要 |
| S12 古今映射 | （新） | `bridge.map` · `bridge.reverse` | 可选 |
| S13 现代证据 | （新） | `modern.search` | 不需要 |
| S14 真实世界验证 | （新） | `rwd.ask` | 可选 |
| S15 证据审计 | T19 · 以今律古 | `audit.claim` · `graph.evidence` | 可选 |

新增评测：bridge（开发集 F1 0.985；全库留出 12 段 F1 0.822）、audit（19 条结论全对）、modern（研究类型 10/10、跨层防护 7/7）、
workflow（8/8 问题编译正确；工作区可续跑）。

## 文献

**路线图所列（按原文转录，未在本仓库逐一核验；写论文前须核对原文）。** Xiang et al., *Chinese Medicine*, 2025（中医古籍
KG + RAG + MAS）；TCMSF, 2025（古籍“证”知识图谱）；BABMLLM, *npj Heritage Science*, 2025（古籍多模态 benchmark）；
EvaHan 2024, LREC-COLING（古汉语断句、标点与字符保持）；CHisIEC, LREC-COLING 2024（跨朝代 NER + RE）；
Ancient Chinese Glyph Identification, ACL 2024；WenyanGPT, IJCAI 2025；AncientTRD, 2025（古籍文本复用）；
Disentangling cultural evolution…, *Humanities & Social Sciences Communications*, 2023；大规模古籍知识图谱
（作品—人物—版本—地点）；《伤寒论》复杂网络研究；Provenance Visualization, *DSH*, 2023。

**本仓库所用方法。**
Benjamini, Y. & Hochberg, Y. (1995) Controlling the false discovery rate. *JRSS B* 57(1): 289–300（配伍、学派的多重校正）。
Monroe, B. L., Colaresi, M. P. & Quinn, K. M. (2008) Fightin' Words. *Political Analysis* 16(4): 372–403（学派特征词）。
Bouma, G. (2009) Normalized (pointwise) mutual information in collocation extraction. GSCL（配伍排序）。
Saitou, N. & Nei, M. (1987) The neighbor-joining method. *Molecular Biology and Evolution* 4(4): 406–425（谱系）。
Robinson, D. F. & Foulds, L. R. (1981) Comparison of phylogenetic trees. *Mathematical Biosciences* 53: 131–147（谱系评测）。
Maas, P. (1958) *Textual Criticism*. Oxford（共同讹误原则，传播链）。
Burrows, J. (2002) ‘Delta’: a measure of stylistic difference. *Literary and Linguistic Computing* 17(3): 267–287（作者归属）。
Wilson, E. B. (1927) Probable inference… *JASA* 22: 209–212（出现率区间）。

---

相关文档：[study.md](study.md)（治学层各功能的方法与局限）· [evals.md](evals.md)（评测）· [agents.md](agents.md)
（角色与工具）· [discovery.md](discovery.md)（发现引擎与闸门）· [data.md](data.md)（语料与许可）· [roadmap.md](roadmap.md)。
