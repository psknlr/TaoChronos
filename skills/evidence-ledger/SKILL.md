---
name: evidence-ledger
description: Build verbatim, locatable, independently sourced evidence records (Claim → Pixel provenance).
tools: [classics.search, classics.get_passage, kg.claims, validation.verify_quote, study.cases, study.trajectories,
        study.argument]
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
- Case records (`study.cases`) are clinical testimony written and selected by their physicians: cite a visit with its
  findings, prescription and recorded response; patterns across cases (`study.trajectories`) are associations in a
  biased record, never evidence of efficacy.
- Quote a clause with its role in the argument (`study.argument`): a statement under 非…也 or 殊不知 is a view the
  author rejects, and a consequence under 若…则 holds only under its condition.
