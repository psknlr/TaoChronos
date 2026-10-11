# ADR 0021 — Labels that keep apart, and tables with numbers

**Status:** accepted · 2026-10-11

## Context

[ADR 0020](0020-figures-and-tables-for-a-paper.md) gave the studies journal figures and three-line tables.  Read on the
535-book corpus, two things fell short.

* **Labels overlapped.**  A family of formulas most of whose members share one year (the 伤寒论's) drew a timeline whose
  stems, running from each dot down to the axis, crossed the labels of the members placed below them; two witnesses from
  one book had one name in a legend; a heatmap's colour scale ran past a single column's width.  Crowded specifications —
  long names, many categories, lines ending at one value, values past a box plot's axis, a ring of thirty nodes — showed
  more: turned category labels over one another, end values over one another, a name past the figure's edge, the ▲ count
  of a box plot over its axis title.  A collision detector run in Chromium over both renderers (real figures and crowded
  ones, three screen widths and three journal widths) found them in 71 of 404 renderings of the page's renderer and 44 of
  274 of the Python one.
* **The protocol's tables had no numbers.**  A protocol's pilot runs its main steps on the corpus, but its tables were
  shells (×× (××.×) …) even where the pilot had computed the very table; and the model, reading only the shells, could
  only copy placeholders into an answer.

## Decision

1. **Layout rules, the same in `study/svg.py` and `web/js/chart.js`:**
   * a timeline's labels take lanes where they overlap no label and, among those, where the fewest stems cross a label
     (its own stem through the labels below it, the stems from above through its text), the highest when several tie,
     within two lanes more than the compact layout (each label in the first lane it fits) — labels turned to the left of
     their dot at the right edge are placed from the edge inwards; a stem that must still pass a label is **broken around
     it** rather than the figure grown into a tall one; the timeline draws its stems first and no grid;
   * category labels turn 40° while neighbours clear each other (a band of 19 px: 12 px between baselines), stand upright
     in a narrower band, and only every k-th is written in a band narrower than a line of text; a name longer than its
     room is cut with an ellipsis (the table and the hover keep it whole);
   * a value is written over each bar only when every one fits; a line's end value above its last point, else below it,
     where it clears the labels set before it, every dot and every line, else not at all;
   * a heatmap's colour scale narrows its steps, then moves left, then cuts its label; turned column labels are cut where
     they would leave the figure;
   * the count of a box plot's values past its axis has a row of its own under the axis title and the key to ▲; a
     scatter's axis title and bubble key sit 18 px over the plot, clear of a bubble at the top; a ring writes each name
     along its radius (turned to read left to right on the left half), a hub's name inside the figure;
   * two witnesses of one book are named by their juan (新编金匮要略方论·卷1（219）), and by their order when that is not
     enough.
2. **No halos.**  A label is never drawn over a mark with a halo (`paint-order: stroke`): Illustrator and PowerPoint ignore
   it and paint the stroke over the glyphs.  The layout keeps labels off the marks; where a stem must pass, the stem is cut.
3. **A test is the measure.**  `tests/test_figure_layout.py` draws crowded specifications with both renderers and checks
   them in Chromium with `tests/collisions.js` — a label's ink (its advance width by the em box, through its transform),
   against every other label, every dot, stem, line and bar, and the figure's edge.  It fails on the renderers before this
   change; the Node test checks that the page lays out a timeline's lanes exactly as Python does.
4. **The pilot fills the protocol's tables.**  Each shell names the study table that fills it (`fills`); the pilot's
   studies return their whole results, and `protocol.fill` puts each table the pilot printed in its shell's place —
   its title marked …（预试验）, a note that the numbers are a first machine reading, to be recomputed and checked against
   the texts.  A shell no pilot step filled stays a template (…（模板）, noted).  New tables were added where a protocol plans
   one that no study printed: a formula's witnesses by period and composition group, the doses of the witnesses compared
   (as written, with the ratio to the largest weight), the works writing each name of a thing by period, and a term's
   senses by period with their change point; 名称考 has a pilot of its own.
5. **The model reads the numbers.**  A filled shell carries the table's heads, notes and first twelve rows in the result
   the model reads (the page and the document print all of them); the standing instructions forbid placeholders and
   invented numbers in a table — a number no tool returned is written 未得, with the step that would give it.

## Consequences

* A crowded timeline may be up to two lanes taller than before, and some stems are drawn in pieces.
* A turned category label, a long row name, a legend entry wider than the figure may be cut; nothing is lost from the
  table, the CSV or the hover.
* A protocol's result is a little larger for the model (about 1–3 KB for its filled tables); its document prints the
  pilot's numbers, which change with the corpus and its index.
* The pilot's numbers are machine readings at default settings; the tables say so, and the protocol remains a plan.
