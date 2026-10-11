# 我的资料 — the user's own data

道乃久 reads the classics; with 我的资料 it also reads what a user brings — a clinic's prescriptions, case records, a
survey, reading notes — and analyses it with the same tools and the same discipline: every number computed here, every
row or passage cited and checked, figures and three-line tables ready for a paper.  The file is read where the user is,
made anonymous as it is read, and never recorded.

* code: `src/taochronos/plugins/userdata/` (formats, de-identification, the store, the analyses, prescriptions, the
  `mydata` capability), the `mydata.*` tools of the mesh (`tools/mesh.py`), the chat runtime (`chat/__init__.py`), the
  local server (`chat/server.py`), the browser's worker (`web/js/worker.js`) and the page (`web/js/mydata.js`, `app.js`,
  `view/drawer.js`);
* decision: [ADR 0022](adr/0022-the-users-own-data.md); the page: [web.md](web.md#我的资料--the-users-own-data).

## Where the data goes

| The page works with | The file is read by | Kept |
|---|---|---|
| TaoChronos in the browser (the published site's 要籍语料) | the browser's own runtime (Pyodide, in a worker) | in this browser (IndexedDB), until removed |
| `taochronos serve` on this machine | that server (`POST /api/data`) | in the server's memory, until it stops |
| the site's own server, or `taochronos serve` on another machine | a runtime the page starts in this browser for it | in this browser (IndexedDB) |

A server other machines reach never takes the user's data: the page does not send it (`ServerRuntime.local` is true only
for a server on this machine), and the server refuses it (`/api/data` answers 403 unless it is bound to 127.0.0.1) — one
runtime would otherwise hold its visitors' data together.  When the page works with such a server, the 我的资料 tools,
the rows they cite (`mine:…`) and the normalisation of a quotation from them are answered by the browser's runtime; only
the rest goes to the server.  What is kept is what was read, made anonymous — never the file.

What the model sees: the shape of the datasets a message carries (the page adds a note: id, file name, columns and
their types — never rows), and what its tools return: statistics, and the rows or passages it asks to read, anonymous.
That goes, with the conversation, to the model service the user chose.  A conversation that touches the user's data — a
message that carried a dataset, a 我的资料 tool called — sends no conversation record, even when the visitor agreed to
records ([web.md](web.md#道乃久默认服务--asking-without-a-key-and-conversation-records)).  The figures and tables name
their source 用户资料（本机分析）, not the file.  Only the conversation's own actor holds the tools' permission
(`mydata:read`): a research run's agents never read the user's data.

## Files

`formats.py` reads, with the standard library only (so the browser runs it too):

* **text** — TXT and Markdown in UTF-8, UTF-16 (with its byte-order mark: Excel's "Unicode text") or GB18030 (GBK,
  GB2312: a Chinese Windows file); Word (.docx): its paragraphs, a table written row by row, its cells apart by tabs;
* **tables** — CSV (the delimiter sniffed: comma, tab, semicolon, bar, the full-width comma) and TSV; Excel (.xlsx,
  .xlsm): the first sheet (a note says so when there are more), shared and inline strings, numbers as Excel shows them,
  dates from the cells' number formats (built-in and custom) in the 1900 or the 1904 date system; JSON: an array of
  records, `{columns, rows}`, an array of rows, or `{text}`.

Refused, with what to do: .xls and .doc (save as .xlsx or .docx), PDF (export its text), .wps and .et.  At most 10 MB a
file, 50,000 rows and 200 columns a table, 2,000,000 characters a text, 20 datasets and 200,000 rows in all; a part of an
Office file that would unpack past 60 MB is refused.  A table's blank rows are dropped, a blank head is named (列3), a
repeated one numbered (年龄_2).  A text is cut into passages: its paragraphs, a long one after a sentence near 400
characters.

## Made anonymous

`deid.py`, as the file is read — nothing reads the original:

* a column by its head: a **person** (姓名, 患者, 病人, 就诊人, 联系人, name …) and a **doctor** (医生, 医师, 主治医师 …) get
  pseudonyms, P0001 … and D0001 …; an **identifier** (身份证, 病历号, 病案号, 住院号, 门诊号, 医保, 卡号 …) gets ID0001 …; the
  same value always the same pseudonym, so that a patient's visits stay together, and the originals are kept nowhere; a
  **contact** column (电话, 手机, 地址, 邮箱, 微信, 工作单位 …) is emptied; a **date of birth** keeps its year;
* in every other cell and in a text: identity card numbers (18 or 15 digits, the date checked), mobile and fixed
  telephone numbers, e-mail addresses, a number labelled 病历号 / 住院号 / 医保卡号 …, and a name written after 姓名 /
  患者 / 病人：— each replaced by what it was (〔身份证号〕, 〔手机号〕, 〔姓名〕 …), counted.

A head is matched whole where a looser match would take 患者年龄 or 方剂名称 for a person.  A name written freely in a
text (张某某来诊) is not found by any rule: the notice says so, and the page shows, for each dataset, what was taken out.

## The store

`store.py` keeps each dataset with an id (`d` and six hex digits of the file's hash), its columns typed from their cells
— number (nine in ten are numbers: 1,234.5, 12%), date, category (few distinct short values), text, empty, or
**prescription** (most cells name two drugs or more, read with the classics' lexicon) — and citable parts:
`mine:<id>.r<n>` the n-th row of a table, `mine:<id>.<n>` the n-th passage of a text.  `card(id)` gives a part as the
evidence panel shows a passage (the file's name, 第 n 行, the row as 列：值；…).  `search` folds the query and the data
with the corpus's variant table (繁→简, 异体), as the classics are searched.  `export` / `restore` give a dataset as plain
data and take it back (the browser keeps it as JSON between visits).

## Analyses

`analysis.py` — for a table:

* **describe** — each numeric column's n, missing, x̄ ± s, M (P25, P75) and range, with a histogram (equal bins of a
  round width); each categorical column's categories, n (%), with a bar chart — two three-line tables, 数值变量的描述统计 and
  分类变量的分布;
* **compare** an outcome across the groups of another column (the twelve largest, the rest as 其他): a numeric outcome by
  **Kruskal–Wallis** (each group's n, x̄ ± s, M (P25, P75); a box plot with its values; two groups: the Mann–Whitney U
  test), a categorical one by **Pearson's χ²** with Cramér's V (**Fisher's exact test**, two-sided, for a 2 × 2 table
  with an expected count under 5; n (%) by group; a stacked chart of shares), two numeric columns by **Spearman's ρ** (a
  scatter with a LOESS curve).

`rx.py` — the prescriptions of a table's column (found by its type, or named) or of a text's passages:

* **reading** — each drug found with the classics' lexicon; its dose what follows its name: 柴胡12g, 桂枝三两, 甘草二两
  （炙）, 桂枝去皮三两, 甘草 6 g; 各 gives the dose to the drugs named just before without one (柴胡、黄芩各9g); notes in
  brackets ((先煎)) are read past; a word the lexicon has only in part keeps the character before it (夜交藤, 川牛膝, 生石膏
  — not 加柴胡, not 六两知母); a name the lexicon lacks counts as written when a weight follows it (党参15g), and is listed;
  routine words (水煎服, 每日1剂, 分2次服) are not drugs.  Grams are counted for g, 克, mg and kg; 钱, 两, 片, 枚 stay as
  written — what a 两 weighed depends on the period and the prescriber;
* **merge** — `written` (the default): each drug as written, character variants folded (白芍 and 赤芍, 炙甘草 and 甘草
  apart, as a pharmacopoeia counts them); `family`: as the classics are compared (白芍、赤芍 → 芍药, 炙甘草 → 甘草, 桂枝、
  肉桂 → 桂); a drug written twice in one prescription counts once, its grams added;
* **the analysis** — the drugs used most (n, %, the forms written), their doses in grams (M (P25, P75), a box plot),
  the pairs used together more often than chance (one-sided Fisher test, Benjamini–Hochberg; lift, NPMI, OR (95% CI);
  a forest plot), association rules (confidence ≥ 50%), a clustering of the frequent drugs (1 − Jaccard, UPGMA; a
  dendrogram) — the same statistics `study.pairs` computes on the classics; with a group column (a diagnosis, a
  syndrome), the drugs used differently across the groups (Fisher for two groups, χ² for more; Benjamini–Hochberg; a
  heatmap of shares and a table of n (%) by group);
* **beside the classics** — each prescription's nearest composition written out in the corpus (Jaccard on the drug
  families, at least 0.3 and two drugs shared; of formulas as near, the one more of whose witnesses are as near, and its
  earliest witness), what it shares and what each has alone, and which formulas come nearest most often — with the
  witness to read (the book, its year, the passage).  The compositions are machine-read from the corpus: a name and a
  composition may be wrongly paired, and the result says to check the witness.  Near means a similar composition, not
  the same use or a lineage.

Every result carries its charts and three-line tables (ids `mine-…`) and a note: the numbers describe this data, they
do not infer a cause, and they are not a recommendation for diagnosis or treatment.

## The tools

| Tool | What it does |
|---|---|
| `mydata.list` | the datasets: ids, file names, kinds, sizes, columns with their types, a preview, what was taken out |
| `mydata.read` | a table's rows (`columns`, `start`, `limit`) or a text's passages, each with its `mine:` id |
| `mydata.search` | where the data writes the words of a query (all of them, after folding), with the words around |
| `mydata.describe` | the descriptive statistics of a table's columns |
| `mydata.compare` | `outcome` across the groups of `group`: Kruskal–Wallis, χ² / Fisher, or Spearman |
| `mydata.prescriptions` | the prescription analysis: `column`, `group`, `merge` (`written` / `family`), `classics` |

`dataset` is an id or a file name, and may be left out when there is one.  The runtime's catalog lists these tools apart
(`catalog("core")["mydata"]`); the page offers them to the model while there is data (and in a conversation that used
them), and the standing instructions say how to use them, how to cite `[[mine:…]]` and what not to conclude.

## Runtimes

* `ChatRuntime` registers the store as the `mydata` capability and adds `data_add(name, bytes)`, `data_list`,
  `data_remove`, `data_clear`, `data_export`, `data_restore`; `passage("mine:…")` answers from the store, and the
  citations of a tool's result name the user's rows as the page shows them (file · 第 n 行).
* `taochronos serve`: `POST /api/data` `{name, data}` (base64), `GET /api/data`, `POST /api/data/remove` `{id}`,
  `POST /api/data/clear` — on a server bound to this machine only.
* The browser's worker: `data_add` (the file's bytes handed over, written to Pyodide's file system, read, removed),
  `data_list`, `data_remove`, `data_clear`; each dataset's export is kept in IndexedDB (`mydata:<id>`) and given back to
  the runtime when it starts; a dataset kept in a form the runtime no longer reads is dropped.

## Tests

`tests/test_userdata.py`: the formats (encodings, delimiters, hand-built .xlsx and .docx with dates and tables, what is
refused), de-identification, the store (ids, cards, search, export and restore, limits), the statistics against
reference values, describe and compare, prescriptions read as written and analysed beside the classics, the runtime and
its tools, the permission, the server's endpoints (and a server elsewhere refusing them), the worker's Python.
`tests/test_web_client.py`: the page's logic under Node; in Chromium, the notice, an upload to a server on this machine
(GB18030 CSV), the analysis, a checked `mine:` citation, nothing naming a patient sent to the model and no record sent;
the browser's own runtime keeping a workbook across a reload (IndexedDB) with a stand-in for Pyodide whose Python runs in
the test; and the page working with a server elsewhere keeping the data in the browser.
