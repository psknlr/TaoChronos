---
name: historical-semantics
description: Resolve period-bound senses of historical terms (消渴, 伤寒, 中风, 痰, 湿…) and flag homonymy.
tools: [kg.term, classics.get_passage, classics.search]
applies_to: [semanticist, skeptic]
tags: [semantics, homonymy]
---
## Method
1. A historical term has *senses*, each bound to a period, with cues and anti-cues. The same surface may name a
   symptom in one text and a disease in another (伤寒论 消渴 vs 金匮 消渴).
2. Resolve each mention with the passage's date and context terms; keep the full distribution over senses.
3. Flag mentions whose best sense has p < 0.6 as homonym risks; they reach Gate G3 and the Skeptic.

## Pitfalls
- Never let a later sense leak backwards (三消 is not a Han-dynasty concept).
- A sense is not a modern concept. 消渴 ≠ 糖尿病 — that mapping is the ontologist's typed proposal.
