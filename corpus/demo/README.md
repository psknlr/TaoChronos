# TaoChronos 演示语料 · Demonstration corpus

> **请勿将本目录作为学术引用来源。 Do not cite this directory as a scholarly source.**

本目录收录约二十部中医古籍的**短篇摘录**，仅用于演示和测试 TaoChronos 的数据模型、检索、Claim 抽取、发现算法与评测管线。

- **底本与版权**：所涉原著均为 1900 年以前的作品，属公有领域。本摘录由 TaoChronos 作者据常见的现代排印本转录，以 CC0-1.0 释出。
- **校勘状态**：所有段落的 `collation_status` 均为 `unverified`。文本**未与任何特定版本对校**，可能有转录、断句或异文方面的错误；部分段落为节录（`abridged: true`，文中以“……”标示）。
- **定位信息**：卷、篇、条文号用于演示 `Claim → Pixel` 溯源链；`precision: approximate` 表示定位信息尚需核实。本演示语料不附原书图像，因此溯源链止于段落与篇目层级。
- **注释中的“待核”**：凡标注“待核”的异文出处或年代，均需专家核实后再使用。

系统本身会反映这些限制：Gate G1（OCR/转录）与 G2（校勘）对演示段落给出 `warn`，置信向量中的 `philological` 维度也相应降低。这正是设计原则“不能直接把 OCR/转录文本当成 Ground Truth”的体现。

## 文件结构

- `books.yaml`：书目、作者、成书/刊刻年代、版本、来源与许可（Gate G0）。
- `books/<book_id>.yaml`：逐段文本、定位、标签、异文（`variants`）以及时间覆盖（例如《素问》运气七篇的成书年代争议）。
- `../modern/evidence.yaml`：少量现代证据摘要（证据域为 `modern_clinical` 或 `pharmacology`），用于演示 Gate G8 与“四个知识空间隔离”。

## 替换为真实语料

真实研究应通过 `corpus` 能力插件接入经授权的数据源（如自建校勘本，或获得许可的古籍数据库），并为每个来源记录 `origin / license / acquisition`。不建议通过未经授权的逆向接口获取版权数据库内容。
