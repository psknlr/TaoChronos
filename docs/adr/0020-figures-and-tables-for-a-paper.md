# ADR 0020 — Figures and tables for a paper

**Status:** accepted · 2026-10-11

## Context

[ADR 0019](0019-herb-formula-research-protocols-charts.md) gave the study results charts: specifications drawn on the
page with read-outs and a table view, downloaded as SVG, PNG, CSV and JSON.  They were the page's charts — a title above,
a grid, rounded bars — and the results' tables were Markdown lists of numbers.  IMPF-AI asked for figures and tables in
the style of scientific research: what a journal prints, and what a researcher takes into a manuscript.

* **Figures.**  A journal figure has its number and caption under it, not a title above; black L-shaped axes with outward
  ticks and no grid; text whose size is set for the printed width (a single column is 85 mm, two are 175 mm); error bars
  with caps; and it is submitted as a vector file or as PNG or TIFF at 300 dpi or more, the resolution in the file.  The
  forms the herb and formula literature reports were missing: a dose distribution as a box plot (Tukey), an association's
  strength with its interval as a forest plot, a dose against time as a scatter with a smoothed curve, the most frequent
  drugs clustered as a dendrogram, association rules (support, confidence, lift).  A result's figures often go into a
  paper as one figure in panels.
* **Tables.**  A journal table is a three-line table (三线表) with a numbered title, grouped heads, the statistics in their
  notation — n (%), M (P25, P75), x̄ ± s, a 95% CI, an odds ratio with its interval, P — and notes that name the
  abbreviations and the tests.  It goes into Word (most Chinese journals), LaTeX, or a spreadsheet.
* **Statistics.**  The tests such tables report were not computed: whether doses differ across periods (Kruskal–Wallis),
  whether they move with time (Spearman), an odds ratio's interval (Woolf).
* **Protocols.**  A research protocol's statistical plan has dummy tables (表格模板): the tables the study will fill, before
  it is run.

## Decision

1. **Statistics in the science layer** (`science/stats.py`, dependency-free, checked against reference values): the
   chi-square and Student-t tails, Kruskal–Wallis with its tie correction and ε², Spearman's ρ with its P, the odds ratio
   with its Woolf interval (Haldane–Anscombe 0.5 when a cell is zero), average-linkage clustering (UPGMA) with its leaf
   order, its cut and the number of clusters where the next merge is the longest branch, LOESS (local linear, tricube), and
   Tukey's box numbers.
2. **The studies report them.**  `usage`: the Kruskal–Wallis test of decoction doses (grams) across periods and Spearman's ρ
   with the year, the mean and SD beside the quartiles; `pairs`: each pair's odds ratio and interval, and over the corpus
   the drugs written most often, the association rules of the significant pairs (both ways, confidence ≥ 50%) and a
   clustering of the 30 most frequent drugs (1 − Jaccard).  The values a figure draws one by one (each dose; the tree)
   travel in the result's `_raw` until the charts are built and are then taken out; the model never reads them.
3. **Four new chart types** (`box`, `forest`, `scatter`, `dendrogram`; the specification stays at version 1: types are
   added, none changed) built where the studies have their numbers: a drug's decoction doses as a box plot and against the
   year with a LOESS curve, a drug's partners as a forest plot of odds ratios (log axis, a line at 1, the rows not
   significant after Benjamini–Hochberg in grey), the corpus's most frequent drugs as a dendrogram, its rules as a scatter.
4. **One layout, two styles** (`study/svg.py`, rewritten to follow `web/js/chart.js`'s layout): the page's **screen** style
   and a **journal** style — white, L axes, outward ticks, no grid, the y title turned, square bars, capped error bars, 8 pt
   at the printed width (the drawing's units are set so that 10.5 of them print as 8 pt), a size in millimetres, and the
   number and caption under it.  Several charts make **one figure in panels** (A, B … in two columns at 175 mm; one caption,
   the notes and sources once).  Python writes the journal style (`--charts DIR`: numbered SVGs, `<stem>-figure.svg`);
   the page shows the journal figure on demand (期刊样式) and exports either style at 85, 120 or 175 mm as SVG, PNG with its
   resolution in pHYs, or TIFF (RGB, PackBits, its resolution in the directory) at 300 or 600 dpi — the bytes written by
   `web/js/bytes.js` (CRC-32, ZIP, pHYs, TIFF), no library.
5. **Three-line tables** (`study/tables.py`: specifications; `study/tablefmt.py` and `web/js/table.js`: writers) for the
   results of `usage`, `pairs`, `compare`, `family`, `term`, `herb`, `properties`, `incompat`, `network` and `formula`,
   carried under `tables` beside the charts: cells are display strings in the journal's notation, columns aligned and
   grouped, notes naming abbreviations and tests, statistical symbols in italics where the format has them.  Written as
   Word (.docx from the standard library: a real table, its three rules, its header rows repeated, 宋体 and Times New
   Roman), LaTeX (booktabs), CSV (with a BOM), Markdown and HTML with its rules inline (it pastes into Word as a three-line
   table); copied by the page as HTML and tab-separated text.  An answer's Markdown tables are drawn as three-line tables
   too, a 「表1　…」 line above taken as their caption and a 「注：…」 line below as their notes.
6. **The model reads titles only.**  `tables` joins `charts` and `document` among the results' page-only fields
   (`chat/results.py` and the D1 backup's `results.js`): the model reads `tables_shown` beside `charts_shown`, and the
   standing instructions tell it that the page numbers them (见上方图 1、表 1), how to write a table's caption and notes in an
   answer, and the three new types of a ```chart block.
7. **Protocols plan figures and tables.**  `study.protocol` numbers its figures with their form in words and gives table
   shells (`table_shells`): each kind's tables with their heads and a row of placeholders in the notation the numbers will
   take (×× (××.×), ××.× (××.×, ××.×), ×.×× (×.××–×.××), ×.×××), and the statistics behind them; the document prints them
   and the result carries them as tables (…（模板）) to copy or download as Word.

## Consequences

* A study's result is larger for the page (its tables, and up to 1 500 doses in a box or scatter), not for the model.
* The usage study's dose chart is a box plot now (the `range` type stays for the specifications that use it); the CLI's
  `--charts DIR` writes the journal style, one more SVG (the panels) and the tables.
* Numbers in the tables are the result's, formatted; a table adds no inference, as a chart adds none.  The tests' notes
  name what they test: a Kruskal–Wallis P compares the doses the texts write in each period, not prescribing.
* The figures' and tables' looks are fixed by the journal conventions (Chinese journals' 三线表 and 图注; 8 pt at the
  printed width), not by a journal's own template: a figure exported without its caption (含图号与图注 off) takes the
  journal's; a Word table takes its styles.
* Tests: the statistics against R and textbook values (`tests/test_statistics.py`); the tables, writers (the Word file
  opened as a ZIP and its XML read), journal figures and panels, the new chart types and the protocol's shells
  (`tests/test_formulas.py`); the bytes (CRC-32, PackBits, TIFF, pHYs, ZIP), the tables' heads, italics, LaTeX and Word XML
  under Node; in Chromium a study's figures and tables under its step — exported as PNG at 300 dpi and TIFF at 600 dpi and
  read back with their resolution, an 85 mm SVG, the panels, a Word document of all the tables, LaTeX, a copy as HTML — and
  an answer's table saved as Word (`tests/test_web_client.py`); the backup's page-only fields (`cloud/test/backup.test.js`).
