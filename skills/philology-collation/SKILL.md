---
name: philology-collation
description: Assess readings, variants (异体/通假/讹误) and collation status without forcing a single reading.
tools: [philology.normalize, philology.assess_passage, philology.collate, classics.get_passage, study.variants, study.stemma,
        study.layers, study.dating, study.authorship]
applies_to: [philologist, skeptic]
tags: [philology, 校勘]
---
## Method
1. Separate *normalisation* (异体字, 通假 used only for matching; the text is never altered) from *variants*
   (readings attested by other witnesses).
2. For each contested span keep every plausible reading with a probability and an explicit `uncertain` mass
   (≥ 0.05). Weight witnesses (base edition, collated editions, citations in later works, modern emendation).
3. Check internal coherence of the medical argument (e.g. a cold-natured formula prescribed for an explicitly
   interior-cold reading is incoherent) — down-weight, never delete.
4. Record collation status: unverified transcriptions cap every downstream claim at Gate G1/G2 “warn”.
5. Where a work has several transcriptions, collate them (`study.stemma`, `study.variants`): lacunae are missing
   text, not disagreement; commentary blocks are structural; minority readings shared by several witnesses group them,
   and a group the tree cannot hold flags contamination. The base is a coordinate system, not the right reading.
6. Before a claim is dated by its book, ask which layer its chapter belongs to: `study.layers` (style, tested by
   permutation) says *that* chapters differ, `study.dating` (cited works, late vocabulary, taboo) *when* they can have
   been written; `study.authorship` compares candidate authors. Neither alone proves a later addition.

## Pitfalls
- 表里 / 寒热 inversions are classic scribal errors; a “contradiction” inside one article is often philological.
- Do not treat a modern punctuation choice as a textual variant.
