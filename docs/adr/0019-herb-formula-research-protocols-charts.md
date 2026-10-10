# ADR 0019 — 535 key works; herb and formula research, research protocols and charts

**Status:** accepted · 2026-10-10

## Context

IMPF-AI asked for four things at once: the 要籍 list lengthened from 350 to 535 of the 759 ranked works; the system made
stronger for research on drugs and formulas; tools that help a researcher design a study; and charts fit for a paper,
easy to download.

* **The list.**  The ranking ([ADR 0013](0013-canon-corpus-in-the-browser.md), `study canon`) is total, so 535 is the 350
  and the next 185.  But the list is computed on the full store, which neither this repository nor its CI holds whole: the
  site's corpus parts in KV omit the sources whose terms forbid passing their texts on (`NEVER_PACKED`), and a ranking on
  them moves some of the first 350.
* **Herbs and formulas.**  `study formula`, `herb`, `pairs` and `network` answered one formula or one drug at a time.  The
  questions researchers bring are comparative — how do 桂枝汤 and 桂枝加桂汤 differ, which formulas were made from 白虎汤,
  how was 半夏 dosed through the periods, what did the 本草 say of 黄连, 黄芩 and 黄柏 side by side, who first wrote that
  甘草 反 甘遂 and which formulas write them together.  And the browser's corpus read compositions with the curated lexicon's
  40 formulas only.
* **Research design.**  The engine plans a study internally (contract, tracks, gates), but a person asking 怎么研究 got no
  protocol — hypotheses with what would refute them, variables defined, methods that can be rerun.
* **Charts.**  Results were tables and text; the web client drew only the 统计 pane's charts.

## Decision

1. **535, extending the list.**  `CANON_SIZE = 535`.  `study canon --write-catalog --extend` (and `web canon --extend`)
   keep the works already listed, in their order, and append the next of the new ranking; `taochronos web canon` writes the
   catalog, packs the browser's corpus and regenerates the D1 backup's tables in one step; the `canon` workflow runs it in
   CI on the store assembled from the KV parts (checked against their sha256) and commits the result.  The repository's
   catalog and pack stay at 350 until it runs: no document claims numbers the data does not have.
2. **Five studies over the one harvest** (`study/compare.py`, `usage.py`, `incompat.py`): `compare` (two to six formulas,
   their 原方 or 通行方, drugs by family, doses in the measures of each witness's period, ratios, dose-weighted overlap, a
   verdict per pair), `family` (the formulas whose compositions hold a base's core and add few drugs: 加味, 减味, 加减, 同药
   异量, 同方异名, 合方), `usage` (a drug's share of compositions by period with a trend test, decoction doses by period,
   the largest-dose clue, preparation, partners), `properties` (the 本草's readings of several drugs side by side, a
   formula's weighted by dose) and `incompat` (十八反 and 十九畏 in the texts: statements, verses, formulas writing a pair;
   `incompatibility.yaml`).  The harvest (`harvest@3`) keeps each composition's items and the form its preparation makes
   of it, so that the batch amounts of pills, powders and 宋 煮散 are never compared with a decoction's doses.  Two parsing
   gaps they exposed are closed where they belong: a formula's entry headed 「X方」, and channels listed with one hand or foot
   (入足厥阴、太阴、少阴经) or a compound flavour (味微苦而甘).
3. **Lexicons for the browser.**  The `web-canon` profile loads, after the curated lexicon, a hand-curated supplement of
   common drugs and the core of the harvest — 800 drugs and 2 000 formulas the full corpus attests most (`taochronos lexicon
   core`).  Candidates still: they never shadow a curated term.
4. **A protocol from a question** (`study/protocol.py`, `study protocol`, the tool `study.protocol`): the question read
   into kinds and entities, each kind contributing hypotheses (prediction, test, falsification, rivals), scope, variables,
   methods (this system's tools with their commands), analysis, figures, quality, limitations, ethics, a timeline and a
   research contract; a pilot run of the main steps reports how much the corpus holds.  It plans; it concludes nothing.
5. **Charts as data** (`study/charts.py`): a declarative specification (version 1: line, bar, hbar, stack, heatmap, range,
   timeline, network) built from the full result, carried under `charts`, never trimmed for the interface and never shown
   to the model, which reads only their titles (`charts_shown`).  Two renderers of one mark specification: `study/svg.py`
   (static SVG, for `--charts DIR` with CSV and JSON) and `web/js/chart.js` (interactive SVG with read-outs, a table view,
   and downloads as SVG, PNG, CSV and JSON).  The colours are a categorical order validated for colour-vision deficiency on
   the page's light and dark surfaces, one hue for magnitude, 其他 in grey, a group's colour fixed across a result's
   charts.  The model may also draw numbers it read in a ```chart block, checked before it is drawn.
6. **Tools.**  The six studies are tools of the mesh (79 now); `study.compare`, `study.usage` and `study.protocol` are
   offered to the chat model directly, the rest through the catalog; the D1 backup lists all six as unavailable for the
   reasons its other passage-wide studies are (`passages`; `data` for the protocol).

## Consequences

* The list grows from the tail: ranks 1–350 do not move, so citations of rank and every earlier protocol stay valid.  The
  185 works added are later, less cited works; by the pack's budgets they come in 12 000-character excerpts, some
  2 million characters more for the browser.  Until the workflow or a machine with the store runs `web canon`, the site
  serves the 350.
* The new studies read what the texts write: counts are of works writing a composition, not of practice; a dose is a
  historical reading; a 反 in a book is a text, not a finding — each result says so, and so does each chart's note.
* The harvest is rebuilt once on every store (its version changed).
* Charts add no inference.  Their numbers are the result's; a model's ```chart block can hold only numbers the
  instructions let it take from the tools, and the page shows its source line.
* Tests: `tests/test_formulas.py` on a synthetic corpus (`tests/fixtures/formulas`) read with the browser's lexicons;
  the chart functions under Node; a conversation in Chromium with a study's charts, a ```chart block, downloads and the
  tool console's charts.
