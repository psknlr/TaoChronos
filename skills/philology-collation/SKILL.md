---
name: philology-collation
description: Assess readings, variants (异体/通假/讹误) and collation status without forcing a single reading.
tools: [philology.normalize, philology.assess_passage, philology.collate, classics.get_passage]
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

## Pitfalls
- 表里 / 寒热 inversions are classic scribal errors; a “contradiction” inside one article is often philological.
- Do not treat a modern punctuation choice as a textual variant.
