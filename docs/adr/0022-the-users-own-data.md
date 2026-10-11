# ADR 0022 — The user's own data (我的资料)

**Status:** accepted · 2026-10-11

## Context

道乃久 analysed only the classics.  Its users — clinicians, students, researchers — hold data of their own that they
want read the same way: a clinic's prescriptions to count and compare, case records to search, a survey to describe, a
dataset to set beside the formulas of the classics.  Such data names patients.  The page runs where it can be trusted
with it (the visitor's browser; a server on their machine) and where it cannot (the site's own server, which the
published page uses when it answers — the D1 backup of [ADR 0017](0017-d1-backup.md) among them; a server on another
machine shared by several people); its model is a service of the visitor's choosing; and the site records conversations
for its test period, with consent ([ADR 0012](0012-default-service-relay.md)).

## Decision

1. **Read where the user is.**  A file is read by a runtime on the user's machine: the browser's own (Pyodide), or
   `taochronos serve` bound to this machine.  The page decides (`dataRuntime`): its runtime when that is local
   (`runtime.local`), else a browser runtime it starts for the data.  The 我的资料 tools, the `mine:` passages and the
   normalisation of a quotation from them go to that runtime (`routed`); everything else goes where it went.  A server
   other machines reach refuses the data endpoints (403): its single runtime would hold its visitors' data together;
   the site's D1 backup lists the 我的资料 tools as unavailable there, for that reason.
2. **Made anonymous as it is read** (`plugins/userdata/deid.py`): columns by their heads — persons and doctors to
   pseudonyms (consistent within a column, not reversible), identifiers to codes, contact details removed, a birth date to
   its year — and identity, telephone, e-mail and labelled record numbers and labelled names in any text.  What is kept is
   the anonymous dataset, never the file.  The rule-based method misses freely written names; the notice says so, and the
   page shows what was removed from each dataset.
3. **Told before the first upload** (`web/js/mydata.js`, `DATA_NOTICE`): where the file is read, what is removed, what
   the model reads and that it goes to the chosen model service, that nothing is recorded, how long it is kept, what the
   statistics are not.  Shown once per browser and version, and repeated in the 资料 panel.
4. **The model reads the shape, then asks.**  A message carrying a dataset tells the model its id, file name, columns and
   their types — no rows.  The model reads further only through the `mydata.*` tools (list, read, search, describe,
   compare, prescriptions), offered while there is data; their results go to it compactly, their figures and tables to
   the page whole.  Rows and passages are cited as `[[mine:<id>.r<n>]]` / `[[mine:<id>.<n>]]` and checked like the
   classics' passages.
5. **Only the conversation.**  The tools need `mydata:read`, which the chat actor holds and no research agent does: a
   discovery run never reads the user's data.
6. **Never recorded.**  A conversation that carried a dataset or called a 我的资料 tool sends no conversation record,
   whatever the visitor agreed to; the figures' and tables' source line names 用户资料（本机分析）, not the file.
7. **Kept in the browser, by the browser.**  The worker keeps each dataset's export in IndexedDB (`mydata:<id>`) and gives
   it back to the runtime when it starts; removing a dataset removes it there.  A local server keeps datasets in memory.
8. **Analyses a paper can use, with the classics beside them.**  Descriptive statistics, group comparisons
   (Kruskal–Wallis, χ² / Fisher, Spearman) and prescription mining (frequency, doses in grams, pairs by one-sided Fisher
   with Benjamini–Hochberg, rules, UPGMA clusters, groups compared) with the study layer's charts and three-line tables;
   prescriptions read with the classics' lexicon — drugs counted as written by default (白芍 and 赤芍 apart), by family
   on request — and each set beside its nearest composition in the corpus with its witness.

## Consequences

* The published site can take personal data without its servers ever holding it; the cost, when the page works with the
  site's server, is the browser's runtime started (and on a first visit downloaded) for the data.
* What reaches the model is anonymous but still data: the notice names the model service, and the tool results are
  compact.  A freely written name can pass the rules; users are asked to check their files.
* The local server holds data only while it runs; the browser keeps it until the user removes it (or clears the site's
  data).
* Old binary formats and PDF are refused with what to save them as, rather than read badly.
* The compositions of the classics are machine-read; a match names its witness to be read, and the result says so.
