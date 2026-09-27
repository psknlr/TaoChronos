---
name: lineage-analysis
description: Detect citation, transcription, rephrasing, formula derivation and opposition; separate independent witnesses from copies.
tools: [classics.lineage, philology.collate, analysis.missing_sources]
applies_to: [lineage, evidence]
tags: [lineage, 源流]
---
## Method
1. Explicit citations (《X》曰 / 经云) → `cites` edges; check whether the quoted text is found in the cited book.
2. Long verbatim overlaps → `transcribes`; paraphrase → `rephrases` (direction by date, flagged when uncertain).
3. Formulas sharing their monarch herbs with added / removed / substituted herbs → `formula_derived_from`.
4. “非…也 / 误以…” against an earlier doctrine → `opposes`.
5. Books by one author or linked by transcription form one *cluster*: count clusters, not books, as sources.
6. Cited works absent from the corpus are candidates for source rediscovery (辑佚), dated before their earliest citer;
   `study.fragments` gathers their text from the quoting books, with a reliability per quoting book measured on works
   that survive.
7. Every `transcribes` / `rephrases` edge carries its reuse type (直接引用, 近似转录, 节略, 撮要, 转述, 解释性改写, 引而驳之,
   套语相似) and the rule that fired: stock phrasing is not lineage, and a quotation made to refute is opposition.
