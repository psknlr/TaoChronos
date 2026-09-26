---
name: discovery-engines
description: Run and read the tool-first discovery engines D1–D5 and their statistics.
tools: [analysis.lost_knowledge, analysis.concept_drift, analysis.formula_evolution, analysis.association_rules, analysis.link_prediction, analysis.contradictions, analysis.missing_sources, analysis.temporal_profile]
applies_to: [pattern_miner, statistician, evolution]
tags: [discovery]
---
- D1 lost knowledge: associations attested before a pivot year that vanish later while both concepts persist;
  plus textual testimony (昔人…后世…). Statistic: P(no later co-occurrence | early rate).
- D2 concept drift: Jensen–Shannon divergence of context profiles between periods, permutation tests, dominant
  sense per period.
- D3 formula evolution: derivation families, stable cores, added/removed/substituted herbs, taboo renames.
- D4 hidden association: association rules (support, confidence, lift, Fisher p, BH) and Adamic–Adar link
  prediction with explanatory paths.
- D5 contradiction: labelled contradiction / conditional / apparent (philological, sense shift), with candidate
  explanations.
- Source rediscovery: cited works absent from the corpus.
Observations are patterns, not interpretations.
