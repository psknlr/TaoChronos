# Architecture

TaoChronos follows one rule: **Deterministic Harness, Stochastic Intelligence**. Everything that must be
trustworthy — state, ordering, permissions, verification, stopping — is deterministic code. Intelligence
(models, or the deterministic procedures that stand in for them) proposes; the harness verifies and commits.

## Layers

```
app          cli · bootstrap · config · governance · workspace
evals        TaoChronos-Eval (may use everything)
engine       research loop · validators · Discovery Report
agents       AgentSpec · skills · router · prompts · context views · runtime · role procedures
plugins      classics · knowledge · retrieval · models · sandbox · subagents · storage
tools        the Tool Mesh (tools execute, agents decide)
verification provenance · gates G0–G8 · lifecycle hooks
science      D1–D5 algorithms, statistics, scoring (pure functions)
kernel       sessions · events · reducer · stores · policy · hooks · budgets · scheduler · context · memory · stop · observability
capabilities provider-neutral interfaces (LLM)
protocol     typed research objects (dataclasses, JSON Schema)
```

Allowed imports are declared in `architecture-policy.yaml` and checked by `taochronos governance` (also in CI):
the protocol imports nothing, the kernel only the protocol, agents never import plugins, vendor SDKs appear
only in `plugins/models`, and the kernel names no vendor, database product or classic text.

## The ResearchObject and the event log

All research state lives in one **ResearchObject** (the blackboard): corpus manifest, philology
assessments, term resolutions, claims, evidence, lineage, contradictions, observations, analyses,
hypotheses, reviews, gate results, proposed changes, decisions, expert actions, branches and artifacts.

It is never edited directly. Agents emit **typed events**; the **Reducer** is the only code path that
mutates state, and it enforces invariants no model can bypass:

- the GoalSpec (research contract) is immutable after `ResearchCreated`;
- only `human:` actors may emit `ExpertApproved` / `ExpertRejected` (Gate G7);
- agents may emit `ChangeProposed` but never `ChangeApproved` / `ChangeRejected`;
- events must reference existing tasks, hypotheses and changes.

State is `reduce(events)`. `taochronos replay` rebuilds it from the log and compares it with the live
projection and every checkpoint.

### Transactions and crash recovery

Each agent task runs inside a **transaction**: its domain events are validated when emitted but appended
only at commit, *together with* `TaskCompleted` and a `TransactionCommitted` marker, as one batch. A
crash before the marker leaves a torn tail that `Session.open` discards; the task is then simply re-run.
Tool-call telemetry is appended outside the transaction (it is operational, not scientific).

### Deterministic scientific state

`ResearchObject.state_hash()` hashes only the *scientific* fields. Operational telemetry — agent
instances, attempt counters, token usage, the run trace artifact — is excluded, so:

- two runs of the same contract produce the same hash;
- a run that crashed and resumed produces the same hash as an uninterrupted one;
- a run with `max_parallel_agents: 4` produces the same hash as a sequential one (independent tasks run
  concurrently but commit in a deterministic order).

RecoveryEval checks all three.

### Branches

`Session.fork` copies a prefix of the log into a new session; `ResearchEngine.branch` re-examines one
hypothesis in isolation (independent witnesses, re-review, narrowing) and merges the outcome back as
`BranchMerged`.

## Capabilities, plugins, profiles

Business code asks the **CapabilityRegistry** for a capability (`corpus`, `domain`, `philology`,
`extractor`, `lineage`, `knowledge`, `retriever`, `study`, `llm`, `sandbox`, `subagent`, `event_store`,
`graph_export`…) and never imports a provider. Plugins are Python modules with a
`register(registry, config, context)` function, loaded from a **profile** (`profiles/*.yaml`):

```yaml
name: full-discovery
extends: base            # base declares the bundles (plugins + config), agents, skills, hooks, gates, budgets
tracks: [D1, D2, D3, D4, D5]
stop: {max_rounds: 2, stop_on_validation: false}
```

`Harness` (in `bootstrap.py`) is the composition root: profile → plugins → capabilities → tools → hooks →
agent specs (validated) → router → runtime → store → artifacts.

The `corpus` capability has two implementations behind one interface: the in-memory YAML corpus (demo) and
`StoreCorpus`, a lazy view of the SQLite corpus store with a full-text index (the `full-corpus` profile); large
corpora switch retrieval, curation, lineage and falsification to index-backed candidates (see
[ADR 0003](adr/0003-corpus-store-and-scoped-research.md)).

The `study` capability (`plugins/classics/study`, [ADR 0004](adr/0004-study-layer.md)) holds the 治学 functions —
concordance, formula provenance, materia-medica and term histories, taboo dating, citations, learning cards, reading
paths, datasets — and the deep-discovery capabilities of 2.0: collation and stemma (with the
`plugins/classics/collation` package: anchored alignment, variant units, stemma, TEI), semantic reuse and
transmission, textual strata, case records and trajectories, argument graphs, sense evolution and lost-work
reconstruction. Their methods that read no text live in `science/` (`semantic_reuse`, `stratigraphy`, `trajectories`,
`argumentation`, `sense_evolution`), and case records have a protocol type (`protocol/cases.py`). All of it is used by
the CLI (`taochronos study …`), the `study.*` tools on the existing agents and TaoChronos-Scholar ([study.md](study.md),
[ADR 0005](adr/0005-deep-discovery-capabilities.md)).

## Tools and the scheduler

The **Tool Mesh** (`tools/mesh.py`) exposes 47 tools in seven families (philology, retrieval, knowledge,
analytics, study, literature, validation) plus `research.run_code` (Code Mode). Every call passes the same
gauntlet — permission → argument schema → budget → `BeforeToolCall` hooks → execution → events →
`AfterToolCall` hooks — whether a model or a deterministic procedure makes it. Consecutive
`parallel_safe` calls run concurrently; `exclusive` calls are barriers.

## Hooks and gates

Lifecycle hooks are deterministic guards: `provenance_validator` (claims must quote their passage
verbatim at the stated span), `anachronism_guard` (blocks equations of historical and modern disease
concepts, agent-asserted equivalence and the contract's forbidden assumptions) and `publish_guard`
(reports must cite evidence).

Epistemic gates G0–G8 promote knowledge step by step: G0 source · G1 transcription/OCR · G2 philology ·
G3 semantics · G4 claim provenance · G5 independent replication (author/transcription clusters, not
books) · G6 falsification · G7 expert (human only) · G8 biomedical evidence (only for cross-space
hypotheses). Gates run as `validator:gates` — agents never grade their own work.

## Context OS and memory

A model call sees a **context view**, never the whole blackboard: the pinned Goal Anchor and task, then
role-specific itemised sections that the `ContextManager` compacts (with ids kept) or omits under the
token budget. The hypothesis role's view is ~94% smaller than a naive dump of the blackboard (see the
Context-OS ablation).

Memory has five layers: M0 per-agent scratch · M1 episodic (the event log) · M2 research (the
ResearchObject) · M3 domain (expert-confirmed knowledge; only humans or validators commit) · M4 skills
(`skills/*/SKILL.md`).

## Stop conditions

After every discovery round the `StopEvaluator` (not a model) checks: budget exhausted; evidence
saturation and no novel sources; top hypotheses passing the required gates (strict gates G4–G6 must
*pass*); critical objections needing an expert; the round limit; or an empty plan from the director.

## Observability

`research_metrics` reports research-level signals — evidence and counter-evidence counts, source
diversity (normalised entropy), hypothesis survival, knowledge gain per round, gate outcomes — alongside
operational ones (agents, tool calls, model calls, tokens, cost). `taochronos trace` shows the agent tree
(round → task → agent → tool calls) and the hypothesis genealogy.
