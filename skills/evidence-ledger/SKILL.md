---
name: evidence-ledger
description: Build verbatim, locatable, independently sourced evidence records (Claim → Pixel provenance).
tools: [classics.search, classics.get_passage, kg.claims, validation.verify_quote]
applies_to: [evidence, hypothesis, curator]
tags: [evidence, provenance]
---
## Record
passage id · book · edition · locator (卷/篇/条) · verbatim quote with character span · retrieval method and routes ·
stance (supports / contradicts / neutral / context) · temporal context · confidence vector.

## Rules
- Quote, don't paraphrase. Spans are verified mechanically.
- Independence is by author/transcription cluster, not by book count.
- Absence is only meaningful where period coverage is adequate (see the corpus manifest warnings).
