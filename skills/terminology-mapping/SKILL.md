---
name: terminology-mapping
description: Propose typed mappings between period-bound senses and modern concepts (related / partially_overlapping / uncertain / not_equivalent).
tools: [kg.term, kg.propose_change]
applies_to: [ontologist, modern_evidence]
tags: [terminology, mapping]
---
## Decision table
| Historical category | Modern category | Relation |
|---|---|---|
| descriptive symptom | symptom | related (equivalence only by a human) |
| symptom | disease | not_equivalent |
| pattern (证) | disease | not_equivalent |
| broad disease name | specific disease | not_equivalent |
| specific disease name | disease | partially_overlapping |
| herb name | species | uncertain (本草考证 needed) |
| sparse attestation | anything | uncertain |

Every mapping is a *proposal* (ProposedChange); validators or experts decide.
