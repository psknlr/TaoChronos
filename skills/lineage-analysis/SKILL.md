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
6. Cited works absent from the corpus are candidates for source rediscovery (辑佚), dated before their earliest citer.
