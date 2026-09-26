# ADR 0002 — Deterministic procedures are first-class agents

**Status:** accepted

## Context

A research harness must stay usable, testable and reproducible when no model is available, when a model
refuses, or when a budget runs out. It must also be possible to measure what a model adds.

## Decision

Every role implements a deterministic procedure (`draft`) that produces the same typed output a model would,
and one `commit` function verifies both. The Cognitive Model Router can route any judgement role to a model
(`hybrid`: the model improves the procedure's draft) and falls back to the procedure — recording a
`fallback` Decision — whenever the model route fails. Tool-first roles (pattern mining, statistics, lineage,
evolution, curation) never use a model.

## Consequences

- The offline profile is a complete, deterministic research system (the basis of the evaluation suite,
  crash-recovery tests and CI).
- Model contributions are measurable against the same verification (fabricated quotes dropped,
  anachronisms blocked, schema violations retried) and the same evaluation.
- Procedures encode domain rules explicitly (in code and YAML), which makes them reviewable by historians
  but limited by their coverage — the reason judgement roles route to models when available.
