# TaoChronos

**面向中医古籍的可溯源多智能体知识发现系统**
*A provenance-grounded, evidence-native research harness for knowledge discovery in Chinese medical classics.*

[English README](README.en.md) · [架构](docs/architecture.md) · [智能体](docs/agents.md) · [发现引擎](docs/discovery.md) · [评测](docs/evals.md) · [数据格式](docs/data.md) · [路线图](docs/roadmap.md)

TaoChronos 把一次古籍研究变成一个**可重放、可审计、可证伪**的过程：研究问题被写成不可变的研究契约，
由研究主管智能体 **TaoChronos** 按需调度专科智能体（校勘、训诂、抽取、谱系、证据、模式挖掘、统计、
假说、质疑、元评审……），每一个结论都必须落到**逐字可核的原文证据**上，并经过认识论门控 G0–G8，
最后由人类专家定夺。

> ⚠️ `corpus/demo` 是为演示方法而整理的**未经核验的节录**；全量语料（《四库全书·子部·医家类》100 部，
> 汉籍仓库录文，CC BY-SA 4.0；笈成整理本 797 部，使用者提供；麦吉尔大学、维基文库与网络文本集去重后新增
> 29 部）同样**未经本项目逐字校勘**。当代出版物、当代名医著作与现代校注本不入库。所有输出都是
> **计算推断**（Computational Hypothesis Space），不是医学结论，也不是临床建议。

---

## 设计原则

| 原则 | 在代码中的体现 |
|---|---|
| **Deterministic Harness, Stochastic Intelligence** | 内核（事件溯源、事务、门控、停止条件）完全确定；模型只在需要判断的角色中出现，且其输出必须通过模式校验与逐字核验 |
| **Everything is a Plugin, not Everything is an Agent** | 语料、领域包、检索、模型、沙箱、存储都是插件；模式挖掘与统计是工具优先的确定性过程，不需要模型 |
| **Claims, not facts** | 主张（claim）是“某书某版某处这样说”的超边，而非脱离语境的医学事实 |
| **No forced single reading** | 有异文之处保留各读法的概率和“不确定”质量（≥0.05） |
| **No medical anachronism** | 历史术语与现代概念之间只能是带类型的映射（related / partially_overlapping / uncertain / not_equivalent）；只有人类专家能认定“等价” |
| **Propose, don't commit** | 智能体只能提议修改规范知识（术语、本体、金标准、领域记忆）；校验器或人类决定 |
| **Evidence-first** | 没有逐字证据的假说不会被写入；伪造或改写的引文会被机械核验拦截 |
| **The harness decides when to stop** | 证据饱和、无新来源、门控通过、预算耗尽或需要专家介入——由内核判断，而不是模型宣称“完成了” |

## 快速开始

```bash
pip install -e ".[dev]"            # Python ≥ 3.11；数据与配置位于仓库根目录（或设置 TAOCHRONOS_HOME）
taochronos demo                    # 离线运行“消渴”示例研究（确定性过程，约 4 秒）
taochronos agents                  # 查看 15 个智能体及其当前路由
taochronos search "膜原最早见于何书"
taochronos research "中风的病因学说如何演变？" --focus 中风 --tracks D2,D5 --forbid "中风=脑卒中"
taochronos report <session>        # 12 节发现报告（Markdown）
taochronos workspace <session>     # 离线 HTML 发现工作台
taochronos review <session> <hypothesis> --approve --expert 张三   # Gate G7：只有人能通过
taochronos eval                    # TaoChronos-Eval 全部评测
taochronos governance              # 架构策略检查
```

使用 Claude 作为推理模型（判断型角色走模型，工具型角色仍为确定性过程）：

```bash
pip install -e ".[anthropic]"
export ANTHROPIC_API_KEY=...
taochronos demo --profile claude   # Opus 5（前沿层）/ Sonnet 5（中层）/ Haiku 4.5（小层）
```

Claude 提供者默认开启服务端拒答回退（`fallbacks="default"`，适用于 Opus 5）；若模型拒答、输出无法通过
模式校验或预算耗尽，该任务会回退到确定性过程，并把回退记录为一条 Decision。也支持 OpenAI 兼容端点
（DeepSeek、Grok、Gemini、本地 vLLM/Ollama）与外部命令子智能体，见 [docs/agents.md](docs/agents.md)。

## 全量古籍语料

演示语料之外，TaoChronos 接入了汉籍仓库（Kanseki Repository）**KR3e 医家类**——即《四库全书·子部·医家类》
全部 **100 部**医籍：约 **2566 万字、35.4 万段**。原文不进入 git；抓取、入库、索引都可复现：

```bash
taochronos corpus fetch kanripo     # 逐个浅克隆 100 个文本仓库到数据目录，写 corpus/sources.lock.yaml（提交号、授权、体量）
taochronos corpus ingest kanripo    # 解析 → 分层断代 → SQLite 语料库 + 全文索引（约 3 分钟）
taochronos corpus status            # 书数、段数、字数、分期、分层统计；索引是否与当前异体表一致
taochronos lexicon harvest          # 从全量语料采集候选方名（~12000）与药名（~3000，含“一名”异名与纲目首见出处）
taochronos research "消渴的概念如何随时代演变？" --profile full-corpus --focus 消渴 --forbid 消渴=糖尿病
```

- **逐部书目**（`corpus/catalog/kanripo-kr3e.yaml`）：作者、朝代、成书年、类别、学派、版本，以及**分层断代**——
  王冰注（762）、新校正（1068）、运气七篇（王冰补入，762）、证类本草的陶注/唐本注/开宝/嘉祐/图经/衍义各层、
  四库提要（按“乾隆 N 年”解析）、卷首序目（按版本）。层次无法可靠分离的传本，一律按最晚一层保守断代，
  并把所传的早期文本年代记为 `t_citation`。
- **繁简与古籍异体归一**（`domains/classics/script/`）：OpenCC 繁简表 + Unihan 异体 + 按医籍语境人工校订
  （䜴→豉、䓤→葱、茰→萸、㪚→散、讝→谵、痟→消……），只用于匹配，原文永不改动。
- **白文机器断句**：四库本无标点，抽取器在带虚拟标点的“视图”上工作，再把每个引文与论元位置映射回原文，
  逐字溯源不断链；断句所致的症状对立只记为“表面矛盾”，不生成假说。
- **规模化研究**：Curator 用全文索引按问题词、异名、相关词与义项线索召回候选，按时期分层抽样成可审计的
  抽样框架（记录在语料清单里）；而“后世是否再出现”“失传”之类的否证检查由 Skeptic 直接查询**整个语料库**
  （同时遵守时间留出与书目排除），不受抽样影响。

### 笈成中医古籍整理本（857 部）

使用者提供的《笈成檢閱系統》v1.4.8 资料（`jc_1_4_8_all.7z`，分 3 卷）也接入同一个语料库：内经难经、伤寒金匮、
本草、方剂、温病、内外妇儿各科、针灸、诊法、医案、综合与丛书，共 857 部，剔除当代与现代整理之作 60 部后
入库 **797 部、约 9230 万字、160 万段**，都有整理者的新式标点。

```bash
taochronos corpus unpack jicheng jc_1_4_8_all.7z.001 jc_1_4_8_all.7z.002 jc_1_4_8_all.7z.003  # 合并分卷、校验、解压、写入锁定文件
taochronos corpus catalog jicheng   # 生成逐部书目与异体字表（覆盖表 corpus/catalog/jicheng-overrides.yaml 人工校订）
taochronos corpus reindex           # 异体字表变动后重建索引
taochronos corpus ingest jicheng    # 入库（约 5 分钟）
```

- **标记解析**：`[h1]`–`[h6]` 标题入定位（卷/篇/节），`[box]` 方剂块单独成段（kind=formula），`[z]/[s]` 注疏
  按书目分层或以（…）内联，`[j]` 校记与 `[id]` 后人编号不进正文（编号保留为“第 N 条”定位），`[c]` 缺字按
  缺字表还原为 Unicode，无法还原的记为 〓 并保留组字式。
- **断代**：人工覆盖表 → 四库书目中同一著作的年代 → 书籍信息中的公元年、年号（「明‧洪武戊午年」）与朝代
  （二者矛盾时以序跋落款所在范围为准，否则取较晚者）→ **序跋落款年代**（「康熙甲戌歲陽月……汪昂書」，
  作者自序优先）→ 同一著作的其他录本 → 同一作者其他著作 ±20 年；实在无从考定的 149 部按清代保守计，
  绝不提前。有落款的序跋单独按落款年代断代，无落款的序跋凡例按 1911 年计。
- **异体字**：笈成异体字表中的罕见异体（非 GB 2312 字）归并到组内唯一的通用字；“易誤判字”“一對多簡化字”
  两节（原表注明“意義往往不同”）不合并。
- **研究范围**：民国著作（类别“近代”，1912—1949）作为历史文献保留；非医籍（易经等）入库但默认不进入研究，
  除非研究契约显式指定类别。

### 剔除范围：当代出版物、当代名医著作、现代校注本

语料只收历史文献。`corpus/catalog/exclusions.yaml` 逐部记录人工复核的决定，自动筛查（`policy.py`）补其余：

| 类别 | 含义 | 例 |
|---|---|---|
| 当代出版物 | 1949 年以后成书或编纂 | 辞典、教材、《思考中医》《中医之钥》、今人汇编与读物 |
| 当代名医著作 | 当代医家的著作与医案 | 程门雪、邢锡波、赵绍琴、《名老中医之路》《名老中医经验集》 |
| 现代校注本 | 今人校注、译注、阐释本，以及亡佚古书的现代辑校本 | 徐荣斋《重订通俗伤寒论》、唐步祺阐释本、《新修本草》《小品方》等辑复本 |

自动筛查看书名（校注、语译、今译、经验集、验案精选……）、1940 年以后的年份、现代单位与机构（克、毫升、医院、
出版社……）、注释体例（【注释】【语译】）、编号脚注，以及辑本中今人所加的出处标记；`keep: true` 可推翻误判
（如明·薛己《校注妇人良方》）。今人所写的内容提要、整理说明、点校说明、电子版序与网站署名一律不进正文。
笈成本剔除 60 部（当代出版物 19、当代名医著作 24、现代校注本 17）；同一著作在其他来源中的副本沿用同一判定。

### 更多来源与去重

```bash
taochronos corpus fetch|catalog kr-catalog    # 汉籍仓库目录 KR3e：责任者、职能（撰/注/校正）、生卒与四库册页
taochronos corpus fetch|catalog|ingest mcgill # 麦吉尔大学图书馆善本妇科文献（公有领域）
taochronos corpus fetch|catalog|ingest wikisource         # 维基文库 Category:中醫（经 Wikimedia 转储，不走 API）
taochronos corpus fetch|catalog|ingest tcm-ancient-books  # GitHub xiaopangxia/TCM-Ancient-Books
taochronos corpus fetch|catalog|ingest tcmoc              # GitHub lab99x/tcmoc
taochronos corpus fetch|catalog|ingest hf-tcm-canon       # Hugging Face wangekxy/classical-tcm-canon
```

这些集合大量互相转抄（多为笈成本的简体转换本），所以入库前逐部与语料库比对：取规范化汉字的 12 字片段
（按内容定锚抽样，约 1/64），计算“候选文本有多少落在某部已收书里”。来源按可信度排序（四库 → 笈成 → 麦吉尔 →
维基文库 → 网络文本集），每个来源只与排在它前面的来源及自身比对，结果与入库先后无关。
网络副本的判定阈值：与单部书重合 ≥ 0.85，或前十部合计 ≥ 0.9；简体副本因转换丢字，同一著作 ≥ 0.4、
任一部书 ≥ 0.5 即视为副本。麦吉尔抄刻本是独立版本，只记录相似度、不判重复。

| 来源 | 读入 | 新增入库 | 副本 | 剔除 |
|---|---|---|---|---|
| 麦吉尔大学善本妇科文献（公有领域） | 5 | **5**（清刻本与抄本，白文，36.6 万字） | 0 | 0 |
| 维基文库 Category:中醫（CC BY-SA 4.0） | 625 | **15**（天回医简、五十二病方、民国三种“古本”伤寒杂病论、东医宝鉴等，34 万字） | 590 | 19 |
| TCM-Ancient-Books | 701 | **8**（医略、医源、灵药秘方、外经微言、医法圆通、眼科奇书等，37 万字） | 647 | 45 |
| tcmoc | 701 | 0（全为上一来源的副本） | 655 | 45 |
| classical-tcm-canon（Hugging Face） | 115 | **1**（张志聪伤寒论宗印·集注，31 万字） | 110 | 4 |

全部合计 **926 部、约 1.19 亿字、198 万段**。汉籍仓库目录（KR-Catalog）为四库 100 部补上 132 位责任者的
职能与生卒，并列出 6 处与本项目书目不一致之处待核（如陈言生卒）。维基文库的“古本”伤寒杂病论（长沙、康平、
白云阁）按民国问世年代断代；Hugging Face 数据集卡片声明为 proprietary-commercial，只作本地研究、不再分发。

## 一次研究如何运行

```
研究契约 GoalSpec（不可变：问题、焦点术语、轨道、时间范围与留出、禁止假设、必需门控）
   │
   ├─ 第 0 轮 · 证据基础   TaoChronos 规划 → 语料圈定 → 校勘 → 义项消歧 → 主张抽取(+G0–G4) → 谱系 → 证据账本 → 术语映射(仅提议)
   ├─ 第 1 轮 · 发现       模式挖掘 D1–D5 → 统计检验 → 演化图谱 → 假说生成 → 证伪 → 修订 → 再证伪
   │                       → 跨空间桥接(G8) → 门控 G0–G8 → 评分与 Elo 锦标赛 → 元评审
   └─ 第 2+ 轮 · 深化      按元评审建议：为缺乏独立来源的假说寻找证据、敏感性分析……或停止
```

智能体是**配置**（`agents/*.yaml`），不是类；按任务动态实例化，而不是一个固定团队。

| 智能体 | 角色 | 模式 |
|---|---|---|
| **TaoChronos** | 研究主管：规划每一轮、决定调度哪些专科智能体 | hybrid |
| TaoChronos-Curator | 语料圈定、时间留出、覆盖度警告 | procedure |
| TaoChronos-Philologist | 校勘：异文、读法概率、校勘状态 | hybrid |
| TaoChronos-Semanticist | 历史语义：时代义项消歧、同名异义风险 | hybrid |
| TaoChronos-Extractor | 主张超边抽取（逐字跨度） | hybrid |
| TaoChronos-Ontologist | 带类型的古今映射（仅提议） | hybrid |
| TaoChronos-Lineage | 引用/转录/改写/化裁/反驳谱系 | procedure |
| TaoChronos-Evidence | 证据账本；为假说寻找独立见证 | hybrid |
| TaoChronos-PatternMiner | D1–D5 与佚书线索（工具优先） | procedure |
| TaoChronos-Statistician | 显著性、BH 校正、经验排名、覆盖度 | procedure |
| TaoChronos-Evolution | 概念时间线、方剂家族树 | procedure |
| TaoChronos-Hypothesis | 假说生成与修订 | hybrid |
| TaoChronos-Skeptic | 证伪：反例、异文、同名异义、转录依赖、覆盖度、统计 | hybrid |
| TaoChronos-ModernEvidence | 现代证据只作背景；跨空间桥接假说须过 G8 | hybrid |
| TaoChronos-MetaReviewer | 系统性问题与下一轮建议 | hybrid |

## 发现轨道

| 轨道 | 做什么 | 演示语料中的例子（均为待专家核验的计算推断） |
|---|---|---|
| D1 失传知识 | 在分界年之前出现、之后消失而概念仍在使用的关联；文本自述的用法变迁 | 《本草纲目》自述忍冬“昔人…后世…”用法之变 |
| D2 概念演变 | 各时期语境分布的 JSD、置换检验、主导义项 | 消渴：隋唐“多饮多尿之病”→宋金元“三消体系”（样本少，标为探索性） |
| D3 方剂演化 | 化裁谱系、稳定核心、加减、避讳改名 | 肾气丸→六味地黄丸→左/右归丸，核心 地黄·山茱萸·山药；薯蓣→山药 |
| D4 隐性关联 | 关联规则（Fisher + BH）、Adamic–Adar 链接预测 | 大便黑 ⇒ 犀角地黄汤；“渴⇢桂枝汤”被质疑者以《伤寒论》第 26 条鉴别否决 |
| D5 矛盾发现 | 矛盾 / 条件性 / 表面（异文、同名异义）/ 支持 | 半身不遂：《金匮》风 vs《医林改错》元气亏损；第 176 条“表里字差” |
| 佚书线索 | 被引用却不在语料中的著作及其年代下限 | 《古今录验方》：见引于《外台秘要》，成书早于约 752 年 |

每个假说都经过：逐字证据 → 质疑者检查 → 必要时收窄修订（范围、义项、读法、探索性……）→ 门控 G0–G8 →
发现分数 `D = w1·E + w2·N + w3·R + w4·T + w5·F − w6·A`（始终与分量一起报告）→ 置信向量（文本、训诂、
语义、抽取、跨源、时间、统计、现代映射——现代生物医学有效性默认 **unknown**）。

## 评测（TaoChronos-Eval）

`taochronos eval` 在演示语料上运行（约 45 秒）。金标准由作者为演示语料构建并在开发中使用，
**只作回归测试，不是无偏基准**（见 [evals/gold/README.md](evals/gold/README.md)）。

| 套件 | 结果 |
|---|---|
| Philology | 7/7：不强行定读、保留不确定质量、规范化匹配 |
| Claims | P 0.98 · R 0.95 · F1 0.96；抽取主张 100% 逐字可核 |
| Provenance | 主张与证据 100% 逐字；平均溯源链 7.8 层（演示语料无页面图像，页/行/区域/图像层如实标为不可用） |
| Hallucination | 伪造与单字篡改引文 100% 检出；真实引文与合法异体写法不误报 |
| Contradiction | 12/12（含鉴别诊断、文本承袭等难负例） |
| Lineage | P 0.87 · R 0.93（逍遥散、补阳还五汤两条组成相似的伪谱系） |
| Temporal | 时代约束 6/6、最早出处 6/6、时代泄漏 0 |
| Anachronism | 10/10 陈述、8/8 映射；智能体断言“等价”被拦截 |
| Recovery | 4/4 崩溃点恢复后科学状态哈希一致；并行 = 串行；重放一致 |
| Time Machine（1368） | 可判定预测 2/3 成立（左/右归丸去“三泻”，使“核心保留”预测失败）；零泄漏 |
| Source rediscovery | 素问/灵枢/伤寒论逐一留出后 3/3 被重新推断，年代下限一致 |
| Ablations | 去义项路由：最早出处 0.67；去义项消歧：矛盾 0.83；Context OS 令上下文 −94%；关闭质疑者：1 个伪假说存活 |

## 目录

```
architecture-policy.yaml   架构策略（分层、内核中立、SDK 隔离、智能体规则）
agents/                    15 个 AgentSpec（YAML）
skills/                    SKILL.md 能力包
profiles/                  配置画像：full-discovery、classics-basic、formula-discovery、historical-disease、claude
domains/classics/          领域包：时期、异体字、词表、历史义项、现代概念、本体、引用、既有认识
corpus/                    演示语料（未经核验）、现代证据摘要、全量书目 catalog/ 与来源锁定 sources.lock.yaml
domains/classics/script/   繁简与古籍异体归一表（OpenCC / Unihan / 人工校订）
domains/classics/lexicon-harvested/  从全量语料采集的候选方名、药名（仅 full-corpus 画像加载）
evals/gold/                评测金标准
src/taochronos/
  protocol/  kernel/  capabilities/  science/  verification/  tools/  plugins/  agents/  engine/  evals/  workspace/
tests/                     96 个测试（含汉籍仓库、笈成、麦吉尔、维基文库、网络文本集与 KR 目录的格式样例 fixtures/）
docs/                      架构、智能体、发现、评测、数据、ADR、路线图
```

## 局限

- 演示语料很小（23 部书、131 段节录），且为未经核验的整理本；评测数值只具说明意义。
- 全量语料为汉籍仓库录文（文渊阁四库本 / 四部丛刊本）、笈成整理本与少量其他来源，均未经本项目校勘；四库本有
  清人删改与避讳改字，白文断句为规则式，长段内可能把相邻条文并入同一主张；笈成本为志愿者录入，品质不一，断代
  在无人工考定时依据其书籍信息与序跋落款，无从考定者只能保守定为“清代或更早”；采集的方名、药名是候选，需专家审定。
- 去重按文本重合度判定，同一版本的两个录本与不同版本之间的界线并不绝对（四库本与笈成本同书的重合度在
  0.5—0.93 之间）；被判为副本的书在各来源书目中逐部记录其所重复的书与重合度，可以人工改判。
- 规则抽取器与领域词表为演示而编写，覆盖有限；真实研究需要专家构建的词表、义项与金标准。
- 组成相似度不足以区分真正的化裁与趋同组方（见 Lineage 评测中的两条伪谱系）。
- Time Machine 与链接预测需要大规模语料才有统计意义；当前只验证流程。
- 系统不提供医学建议；任何结论在专家（Gate G7）核验前都只是研究线索。
