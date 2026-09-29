# 道乃久（TaoChronos）投稿图表 · Nature 风格

一套按 Nature Portfolio 图表规范制作的投稿用图表：**6 张主图、3 张扩展数据图（Extended Data）、2 张扩展数据表**，外加
英文图注、源数据（Source Data）、合规检查报告与**补充材料（Supplementary Information）**。所有数值都来自本仓库可复现的
数据与运行结果，不含任何虚构或示意数据；需要全量语料（未随仓库分发）的少数数值转录自 `docs/evals.md`，并在图注与源数据中
逐项标明。

- 审阅用合订本：[`TaoChronos_display_items.pdf`](TaoChronos_display_items.pdf)（每张图 + 图注，然后是两张扩展数据表和补充图 1）
- 投稿用母版：`figures/out/*.pdf`（矢量，文字可编辑，字体已嵌入）；另有 `*.svg` 与 600 dpi `*.png`
- 图注：[`legends.md`](legends.md)（英文，每条 ≤ 300 词）；表格：`tables/extended_data_tables.docx`（Word 三线表）、
  `extended_data_table*.tex`、`extended_data_table*.md`
- 补充材料：[`supplementary/Supplementary_Information.md`](supplementary/Supplementary_Information.md)（另有 `.docx`），
  补充表 1–12 的 CSV 在 `supplementary/tables/`，补充数据 1–2 为端到端案例的完整报告与事件日志
- 合规报告：[`figures/out/qc/QC_REPORT.md`](figures/out/qc/QC_REPORT.md)（10 张图全部 PASS）

Nature 的 Article 正文通常最多 6 个显示项，所以本轮把两张表移为扩展数据表（Extended Data Table 1–2），正文保留 6 张图。

## 图表体系：每张图一个科学信息

| 编号 | 核心信息 | 面板 | 数据 |
|---|---|---|---|
| **Fig. 1** 智能体架构 | 智能体只能提出，验证器评分，专家裁决；每条结论落到逐字见证 | a 按主体（人 / 智能体 / 内核 / 验证器 / 工具与数据）分行、按研究轮次阶段（规划与反思 · 研读 · 发现 · 质疑 · 古今转译）分列的架构图：16 个智能体各自的职责、权限字母与是否可调用模型，六类钩子（红色）挂在哪里，门控 G0–G8、合同裁决、73 个工具按 9 个家族与所需权限；b 事件权限表（61 类事件、9 种主体组合，谁能发出什么）；c 《金匮要略》“男子消渴…肾气丸主之”三见证逐字对齐与完整出处链 | `agents/`、`skills/manifests`、工具网格、钩子注册、`kernel/authority.py`（`fig1_architecture.json`） |
| **Fig. 2** 语料 | 语料跨越两千年、按层断代；要籍由引用网络界定 | a 语料构建流程（十个来源 → 准入 → 去重 → 分层断代 → 仅用于匹配的规范化 → 语料库）；b 966 部见证的年代分布；c 断代依据；d 要籍影响力得分与成书年代；e 网页端要籍语料各见证保留字数与预算阶梯 | `corpus/catalog`、`corpus/web` |
| **Fig. 3** 端到端研究案例 | 一个研究问题从契约到裁决的全过程 | 问题“肾气丸的组成与主治如何随时代演变？”在开放要籍语料上实跑（纯规则、未调用模型、可复现）：a 研究契约与范围（206 部书、1,399 段）；b 30 个任务按执行顺序落在各智能体上，工具调用数、各轮新增证据与停止规则；c 14 条假说的去向（质疑者保留 3、收窄 10、否决 1）与 117 条质疑按类型的处理；d 14 条最终假说 × 门控 G0–G8 × 9 条合同条款 × 裁决；e 三个结局的逐字证据：H1 满足全部机器条款待专家、H2 五个见证同属一个源流、R1 因后世仍有记载被否决 | `e2e_case.py`（`fig3_e2e_*`） |
| **Fig. 4** 核验与安全 | 引文保持逐字、边界守得住、疑难解读不出不安全错误 | a 伪造/单字篡改/错位引文检出 60/60；b 19 条不变量 × 逐一拆除 6 条边界的突变矩阵（实测，127/133 格成立）；c 107 例疑难解读分 8 类（留出 82/84，2 例不安全错误如实报告）；d 四轮盲测 | `taochronos eval`（演示语料）、`mutation_matrix.py` |
| **Fig. 5** 研究价值 | 只用过去的文献做出的排序，能预见后世医家写下的关联 | a 盲测协议示意；b 五种排序器的 P@10、P@20、MAP；c 逐主题配对符号检验（按平均精度，Adamic–Adar 优于流行度 149:39，P = 2.4 × 10⁻¹⁶）；d 端到端预测 | 全量语料运行记录（`docs/evals.md`） |
| **Fig. 6** 案例 | 确定性的治学层在开放语料上读出写在文本里的历史 | a 薯蓣→山药；b 玄参→元参；c “温病”各期频率；d 配伍挖掘找回经典方核心药组；e 医家引用网络 | 要籍语料上的 `study names/term/pairs/citations` |
| **ED Fig. 1** 泛化 | 规则在哪里能迁移、在哪里不能 | 开发集 vs 留出集/真实语料；句读模型；消融实验 | eval + `docs/evals.md` |
| **ED Fig. 2** 开放语料复跑 | 在开放要籍语料上重跑研究价值盲测 | **a 改为 30 个主题–截止年对逐一展示三种排序器的平均精度与成真链接数**（取代原先无意义的“全量 vs 开放”计数对比）；b 五种排序器；c 配对符号检验：优于流行度 24/6（P = 0.0014），与随机不可区分 13/17（P = 0.58） | 本次在要籍语料上实跑 |
| **ED Fig. 3** 资源 | 文本背后的实物见证与授权 | a 十一个馆藏的 10,001 条影像书目；b 网页语料按来源与授权构成（**笈成现为开放授权，蓝色**） | 影像书目 CSV、`corpus/web` |
| **ED Table 1** | 语料来源、授权、入库部数与字数 | — | 书目 |
| **ED Table 2** | 三层评测汇总（开发集 vs 留出集/真实语料分列） | — | eval + `docs/evals.md` |
| **补充图 1** 失败分析 | 端到端案例哪里出错、为什么 | a 三种“同源”合并规则下的源流数；b 每条假说的独立源流数；c 五类失败模式、表现与可行的检查 | `fig3_e2e_families.csv` 等 |

## 补充材料（Supplementary Information）

| 部分 | 内容 |
|---|---|
| 补充说明 1 · 评测设计 | 三层评测（边界、解读、研究价值）的原则：规则先于运行、开发/留出划分先于首跑、四轮盲测、时间切分与泄漏计数、基线；**补充表 1** 列出全部 40 个评测套件的问题、数据与划分、指标、结果及论文中的出处 |
| 补充说明 2 · 关卡与权限映射 | 五层边界（工具权限 → 钩子 → 事件权限 → 门控 → 研究合同）；**补充表 2** 门控 G0–G8 的通过/警告/失败条件与判定者；**表 3** 合同条款与判定者、未满足时的状态；**表 4** 16 个智能体的权限、工具、模式、模型档位与预算；**表 5** 工具家族与所需权限；**表 6** 钩子与其拒绝的内容；**表 7** 61 类事件的主体权限与理由；**表 8** 对话端 4 个核心智能体、技能 S01–S15 与委托的专家智能体 |
| 补充说明 3 · 完整案例 | 端到端案例的运行方式、规模与结论；**表 9** 全部 24 条假说（门控、未满足条款、质疑、可检验预测）；**表 10** 117 条质疑；**补充数据 1** 系统写出的完整发现报告（`Supplementary_Data_1_e2e_discovery_report.md`）；**补充数据 2** 可回放的完整事件日志（`Supplementary_Data_2_e2e_event_log.jsonl.gz`） |
| 补充说明 4 · 预测清单 | **表 11** 在 1368 年过去视图上整条流水线做出的 82 条预测及其在后世文献中的结果（开放语料）；**表 12** 30 个出现成真链接的主题–截止年对：三种排序器的平均精度与 Adamic–Adar 前 20 名中成真的链接 |
| 补充图 1 | 失败分析（见上表） |

## 规范对照（Nature 显示项要求）

| 项目 | 本套图表 |
|---|---|
| 尺寸 | 全部为双栏 183 mm 宽，高度 58–168 mm（≤ 170 mm）；按最终印刷尺寸以毫米排版，从未缩放 |
| 格式 | 矢量 PDF 为母版（TrueType 嵌入、文字可选可编辑）+ SVG + 600 dpi RGB PNG |
| 字体 | Arial（汉字逐字回退到 Noto Sans CJK SC）；正文 5–7 pt，面板标号 8 pt 粗体小写 |
| 线宽 | 0.25–1 pt |
| 配色 | Okabe–Ito 色盲友好色板；蓝色标示被检验的变量，其余用灰，朱红只用于警示（钩子、失败、否决）；无红绿对比、无彩虹色、无渐变/阴影/网格线 |
| 统计 | 精确 P 值（斜体 P）、检验名称、n、区间定义都写在图注里；小样本同时给出计数（如 82/84） |
| 表格 | 可编辑文本、三线表、无竖线、单位在表头、脚注用 * † ‡ § ‖ |
| 源数据 | `figures/source_data/` 中每张图所画的每个数值（CSV/JSON） |

## 一键重建

```bash
pip install -e . matplotlib numpy scipy pandas pymupdf python-docx
bash paper/make_all.sh          # 约 12 分钟：源数据（含开放语料上的研究价值复跑、架构配置与端到端案例）→ 突变矩阵
                                # → 10 张图 → 图注字数 → 合规检查 → 表格 → 补充材料
python3 paper/build_preview.py  # 合订审阅本（需要 Chromium）
```

`make_data.py` 会在临时目录里用 `corpus/web` 构建要籍语料库、在演示语料上运行 `taochronos eval`、在要籍语料上运行治学工具
和端到端研究案例；不需要全量语料，也不读写你的数据目录。

## 需要作者留意与决定的事项

1. **笈成授权已全部更正**（2026-09-29 核对 https://jicheng.tw/tcm/copyright.html）：笈成对公有领域古籍的筛选、编排、标点、
   附注等编辑成果为 **CC0 1.0**，网站原创内容为 **CC BY 4.0**，使用时注明来自中醫笈成即可。仓库内的代码、书目、网页语料包
   （250 个笈成见证）、`ATTRIBUTION.md`、README 与文档均已同步；要籍目录中可由开放授权见证提供文本的著作从 108 部增至 **344 部**。
   两处例外需要你确认：（a）笈成据**今人辑校本**录入的少数书（集验方、名医别录、食疗本草、小品方、吴普本草、海药本草、新修本草；
   八十一难经、雷公炮炙论、神农本草经复古辑本可能也是），其中的**今人成分**不在笈成的 CC0 之列，目前按 IMPF-AI 的发布决定随网站
   发布，授权文字已如实说明——若你希望更稳妥，可把这几部从网页语料包中移除；（b）TCM-Ancient-Books 中不与笈成本重复的 4 部，
   仓库未声明授权，仍按发布决定随网站发布。投稿的数据可用性声明请与 `corpus/web/ATTRIBUTION.md` 保持一致。
2. **端到端案例暴露了一个值得修的实现问题**（补充图 1）：G5“独立来源”按书合并源流，且对段落级的“转述”（rephrases）链接做
   传递闭包，结果开放语料 368 部书中有 182 部被并成同一“源流”，本案例 38 部证据书中 35 部同源，13 条候选中 12 条未通过 G5
   （其中 6 条另有未满足的条款）；若只按转录链接合并，H4、H5、H9、H12、H13 都有 2–4 个独立源流，按现有条款推算其中 H4、H5、
   H12 会升为“待专家”。建议改为按每条主张的支持段落判断独立性
   （`src/taochronos/tools/adapters.py::author_clusters`）；修复后重跑 `make_all.sh`，Fig. 3 与补充材料会自动更新。另外几类问题
   （同段共现被读成关联、薛己按语随陈自明原文断代、重复假说、开放语料只抽样部分篇章）也都在补充图 1 中如实列出，未作修补。
3. **Fig. 5 的数值来自全量语料的运行记录**（`docs/evals.md`）。全量语料不随仓库分发，本次无法复算；若在本机已构建全量语料，
   建议运行 `taochronos eval research_value -o rv_full.json`，可把 Fig. 5 也升级为逐主题配对图（与 ED Fig. 2a 相同的画法）。
4. **配对比较的指标已更正**：代码（`evals/research_value.py`）比较的是每个主题–截止年对的**平均精度**，上一版 Fig. 4c（现 Fig. 5c）
   与 ED Fig. 2c 的坐标轴/图注误写为 precision@10，本轮已改正。
5. **ED Fig. 2 结果有正有负**：在开放要籍语料上，排序相对流行度的优势可复现，但无法与随机区分。建议保留并在正文说明“该基准需要
   全量语料”；新的 a 面板逐对展示了原因——30 对中 17 对只有 1 个成真链接。
6. **实测突变矩阵与 `docs/evals.md` 有两处出入**（图注已按实测撰写）：拆除证据边界检查后，5 条不可能的证据中是 2 条通过核验；
   拆除作用域守卫后，工具不再被拒，但并没有读出被扣留的段落，伪造的 G7 进入日志但未进入状态。是否同步修正文档，请你决定。
7. **金标准由作者构建**，只是回归测试、不是无偏基准；ED Table 2、ED Fig. 1 与补充表 1 已把开发集与留出集/真实语料分列。
8. **未使用 `data/chat-logs/` 的对话记录**：访客同意的是测试期间记录，用于论文需另行知情同意与伦理审批。
9. **目标期刊**：若投 Nature Communications 或 Nature Medicine，双栏宽为 180 mm——把 `figures/nature_style.py` 中
   `WIDTH["double"]` 改为 180 后重跑 `make_all.sh` 即可。
10. 图中文字以英文为主，汉字只用于古籍原文、书名与术语（均已嵌入字体）；补充数据 1 的发现报告保持系统输出的中文原样。

## 文件

```
paper/
  README.md                     本说明
  legends.md                    英文图注（含源数据说明）
  TaoChronos_display_items.pdf  合订审阅本；preview.html 为其 HTML 版
  make_all.sh · build_preview.py
  figures/
    nature_style.py             毫米排版、字体、色板、自动换行、保存与逐图自检
    make_data.py                源数据提取；e2e_case.py 端到端案例；mutation_matrix.py 突变矩阵实测
    fig1_architecture.py … fig6_case_studies.py · extfig1…3_*.py · suppfig1_failures.py
    check_legends.py · qc_report.py
    source_data/                每张图的源数据（CSV/JSON）
    out/                        PDF · SVG · PNG；qc/ 逐图检查与 QC_REPORT.md
  tables/
    make_tables.py · extended_data_tables.docx · extended_data_table1/2.tex · extended_data_table1/2.md
  supplementary/
    make_supplementary.py · Supplementary_Information.md/.docx · tables/S1–S12*.csv
    Supplementary_Data_1_e2e_discovery_report.md · Supplementary_Data_2_e2e_event_log.jsonl.gz
```
