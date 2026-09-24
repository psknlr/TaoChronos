---
name: claim-extraction
description: Extract claims as hyperedges with verbatim quotes and argument spans (主之 / 宜 / 禁 / 所致 / 诸…皆属于…).
tools: [kg.extract_claims, kg.term, classics.get_passage, validation.verify_quote]
applies_to: [extractor]
tags: [extraction]
---
## Method
1. A claim is one assertion: the whole symptom set + pulse + pattern + principle + formula is one hyperedge, not a
   bag of triples. Keep negations (不恶寒), options (或…), conditions (发汗后, 冬月) and adverse outcomes (汗之则…).
2. Relations: indicated_for, contraindicated, defines, causes, pathogenesis, treatment_principle, composed_of,
   herb_indication, transforms_to, complication, prognosis, theory.
3. Quote verbatim; copy argument surfaces exactly. The harness locates every span and the provenance validator
   rejects anything it cannot find.

## Pitfalls
- Headings (…病脉证并治) supply context, not text; mark heading-derived arguments.
- Do not modernise: 小便不利 stays 小便不利.
