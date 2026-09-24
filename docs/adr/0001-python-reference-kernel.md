# ADR 0001 — A Python reference kernel with a language-neutral protocol

**Status:** accepted

## Context

The design calls for a model-agnostic research operating system whose kernel could later be ported (e.g. to
TypeScript for a web runtime, or to a service). The research community around classical Chinese medicine and
digital humanities works mostly in Python, and the discovery algorithms are data-science code.

## Decision

- The reference kernel, plugins and science engine are Python ≥ 3.11 with a single runtime dependency
  (PyYAML); the Anthropic SDK is optional.
- The **protocol** (typed research objects and the event vocabulary) is the contract: dataclasses with
  canonical JSON, deterministic ids and JSON Schema export (`taochronos schema`). Another runtime can
  consume the event log and the schemas without importing Python code.
- Event logs are append-only JSONL or SQLite; state is always `reduce(events)`.

## Consequences

- Easy installation and inspection for researchers; the whole system runs offline.
- Throughput is bounded by a single Python process; parallel agents use threads with deterministic commit
  order. Scaling out would add a queue-backed scheduler behind the same kernel interfaces.
- Porting the kernel means re-implementing the reducer and invariants against the same schemas; the
  RecoveryEval and determinism tests define the behaviour to match.
