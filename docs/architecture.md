# Architecture

TaoChronos follows one rule: **Deterministic Harness, Stochastic Intelligence**. Everything that must be
trustworthy — state, ordering, permissions, verification, stopping — is deterministic code. Intelligence
(models, or the deterministic procedures that stand in for them) proposes; the harness verifies and commits.

## Layers

```
app          cli · bootstrap · config · governance · workspace · chat (the web client's runtime, local server, site build)
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

- every event carries the **principal** of the actor that emitted it — kernel › human › validator › agent — set by the
  session from an `Actor` object, never by the emitter; `kernel/authority.py` says which principals may emit each event
  type, and a bare string that says "human" is at most an agent;
- the GoalSpec (research contract) is immutable after `ResearchCreated` (its digest is checked; a second goal is refused);
- only a human expert's `ExpertApproved` / `ExpertRejected` sets Gate G7 — a `GateEvaluated` carrying G7 is refused
  from anyone; agents may emit `ChangeProposed` but never `ChangeApproved` / `ChangeRejected`;
- objections close only as their state machine allows (a hard one by a validator's passing re-run);
- withheld material (hold-out, confirmation, expert-only) stays withheld: a later manifest cannot release it;
- events must reference existing tasks, hypotheses, changes and (unretracted) evidence.

Agents act through a `SessionView` bound to their identity and read a frozen `StateView`; only the kernel, the engine
and the app mint privileged identities (checked by `taochronos governance`).

State is `reduce(events)`. `taochronos replay` rebuilds it from the log and compares it with the live
projection and every checkpoint.  During a run the same comparison is incremental (`Session.verify_incremental`): a
replay kept beside the live state is advanced by the events appended since the last check, its hash is reused until it
moves, a checkpoint right after a consistent check records that check's hash, and any restore drops the kept replay —
the live state itself is always hashed afresh, so a change behind the log is still found.

### Transactions and crash recovery

Each agent task runs inside a **transaction**: its domain events are validated when emitted — each on the state its
predecessors in the batch build, so two goals in one batch fail early — but appended only at commit, *together with*
`TaskCompleted` and a `TransactionCommitted` marker, as one batch. The commit revalidates the whole batch, applies it,
and only then persists it; a failed persist restores the live state from the log, and a rejected event reaches neither.
A crash before the marker leaves a torn tail that `Session.open` discards; the task is then simply re-run. An old log
with an invalid event reopens only with an explicit repair. Every round checks that the live state equals the replay of
the log and restores it if not. Tool-call telemetry is appended outside the transaction (it is operational, not
scientific).

### Deterministic scientific state

`ResearchObject.state_hash()` hashes only the *scientific* fields — and serialises only them, in one walk, with the
cyclic collector paused while the tree is built. Operational telemetry — agent instances, attempt counters, token usage,
the run trace artifact — is excluded, so:

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
[ADR 0003](adr/0003-corpus-store-and-scoped-research.md)).  `corpus.on_side(cutoff, "before" | "after")` is the time
machine's view: only the passages whose whole date range lies on that side exist — every read path is bounded in SQL,
the full-text search and the study layer's own queries of the store (`row_filter`) included — so a harness built on the
past view cannot read a later text
([ADR 0010](adr/0010-speed-cruxes-and-research-value.md)).

Every YAML file the harness reads is parsed once per content (`protocol/yamlio.py`): the parsed value is kept under the
SHA-256 of the file's bytes in `$TAOCHRONOS_CACHE` (`off` disables it; else the XDG cache), so an edited file is simply
another key and a stale entry cannot be read.

The `study` capability (`plugins/classics/study`, [ADR 0004](adr/0004-study-layer.md)) holds the 治学 functions —
concordance, formula provenance, materia-medica and term histories, taboo dating, citations, learning cards, reading
paths, datasets — and the deep-discovery capabilities of 2.0: collation and stemma (with the
`plugins/classics/collation` package: anchored alignment, variant units, stemma, TEI), semantic reuse and
transmission, textual strata, case records and trajectories, argument graphs, sense evolution and lost-work
reconstruction. Their methods that read no text live in `science/` (`semantic_reuse`, `stratigraphy`, `trajectories`,
`argumentation`, `sense_evolution`), and case records have a protocol type (`protocol/cases.py`). All of it is used by
the CLI (`taochronos study …`), the `study.*` tools on the existing agents and TaoChronos-Scholar ([study.md](study.md),
[ADR 0005](adr/0005-deep-discovery-capabilities.md)).

V2 ([v2.md](v2.md), [ADR 0008](adr/0008-v2-rules-first-verifiable-translation.md)) adds five capabilities and a
runtime.  `vision` (layout and reading of page images), `bridge` (the Ancient–Modern Bridge, [bridge.md](bridge.md))
and `audit` (the evidence audit and evidence graph over the corpus, the bridge and modern evidence) are registered by the
classics bundle; `modern` (PubMed typed by design, the safety table) and `rwd` (study specs over OMOP) by the new
`plugins/modern` bundle.  Their checks that read no corpus live in `verification/` (`audit.py`, `evidence_graph.py`,
`presentism.py`) and their shared types in `protocol/` (`bridge.py`, `assertions.py`, `modern.py`).  The judge
(`capabilities/judge.py`) is the one place a model enters these functions: it is handed to a capability (`study.judge`),
never imported by it.  `engine/workflow.py` loads the skill manifests and the core agents, compiles a question into a
DAG and runs it through the tool scheduler as those agents, with every call an artifact of a resumable workspace.

## The web client

`web/` is a conversation in the browser with **Tao-R1** (TaoChronos over the model the user chose): the page runs the
agent loop with the user's own model, and the tools run in `taochronos.chat.ChatRuntime` — in the browser under Pyodide
(the 要籍语料: the openly licensed texts of the ranked key works, `plugins/classics/webcorpus.py`, profile `web-canon`) or
under `taochronos serve` (full corpus; the browser remembers the server, and a server bound beyond this machine requires an
access token).  The agent is 道乃久 (model Tao-R1), published by IMPF-AI; asked who it is, the page answers itself with a
fixed introduction (`web/js/fixed.js`, ADR 0014).  Outside a research run the tools read the whole store
(`tools.common.whole_store`, `term_passages`).  The chat model acts as an agent-principal actor with read and analysis permissions,
so every call goes through the scheduler like any agent's; it never holds `kg:propose`, and Code Mode only by the server's
`--code-mode`.  The page checks every `[[passage_id]]` the model writes against the corpus (the quotation before it,
directly or after normalisation; the passage's existence; whether a tool returned it).  See [web.md](web.md) and
[ADR 0011](adr/0011-web-client.md).  The published page's default service (道乃久默认服务) is a Cloudflare Worker in
`relay/` holding the MiniMax key as a secret; conversation records, sent only by visitors who agreed, are collected hourly
into `data/chat-logs/` by a workflow — the relay holds no GitHub token ([ADR 0012](adr/0012-default-service-relay.md)).

## Tools and the scheduler

The **Tool Mesh** (`tools/mesh.py`) exposes 58 tools in seven families (philology, retrieval, knowledge,
analytics, study, literature, validation) plus `research.run_code` (Code Mode). Every call passes the same
gauntlet — permission → argument schema → budget → `BeforeToolCall` hooks → execution → events →
`AfterToolCall` hooks — whether a model or a deterministic procedure makes it. An `AfterToolCall` denial withholds the
result (only its hash is kept, the call is marked quarantined), and every call leaves a **receipt** (tool, version,
actor, principal, hashes of arguments and result, outcome, duration) whose hash chain the run manifest records.
Capabilities reach tools through views scoped to the caller's reading scope. Consecutive `parallel_safe` calls run
concurrently; `exclusive` calls are barriers. Long results are paged, not cut (`context__page`).

## Hooks and gates

Lifecycle hooks are deterministic guards: `scope_guard` and `scope_firewall` (always installed: no argument may name,
and no result may carry, material withheld from the caller), `provenance_validator` (claims must quote their passage
verbatim at the stated span), `semantic_support` (the quote must *state* the claim — see below), `anachronism_guard`
(blocks equations of historical and modern disease concepts, agent-asserted equivalence and the contract's forbidden
assumptions) and `publish_guard` (reports must cite existing, unretracted evidence and present only hypotheses the
contract judged on their current versions).

**Quotes are read, not only matched** (`verification/support.py`).  A claim's quote *supports* it when it states the
relation: the nearest cue governs each intervention (「不可发汗，宜桂枝汤」), the consequence decides between a warning
and a recommendation (「汗之则神昏」 / 「汗之则愈」), an intervention named by 之 is read through its pronoun, and every
argument is read with its negation (「非风、非寒…乃异气所感」 does not support "风 causes 温疫").  The statement frame
records who says it (a report governs until the author answers it), the stance — asserted, reported, rejected — the
conditions (若…者, 凡…, the 「…者，X主之」 clause), negations and time.  A contradicted claim is refused at commit.  A cue
reaches only to the next 「……者，」 condition, and the reading consults the registry of textual cruxes
(`domains/classics/cruxes.yaml`, harvested from the commentaries by `taochronos study cruxes`): a claim whose literal
wording would support it but rests on words the commentators judged transposed, miswritten, interpolated or lost reads
*ambiguous*, with the crux and its commentators as cues.

**Arguments from silence are tested against what the scope states.**  A lost association (D1) and a hidden one (D4)
are claims about the literature, not about the passages a session read: the Skeptic searches the whole scope — the
store within the contract's window, for a large corpus — for claims that *state* the association (every written form
of both terms, the extractor deciding, supported quotes only).  "No longer stated" is a universal negative: one verified
statement after the pivot refutes a loss (`restated_after`, critical — the objection says when every later statement
is of one source family, which a separate argument about transcription would have to take up), and any statement
refutes a hidden association (`attested`).  Both are hard objections: a narrowing of the wording cannot close them.

Epistemic gates G0–G8 promote knowledge step by step: G0 source · G1 transcription/OCR · G2 philology ·
G3 semantics · G4 claim (layers: authenticity, locator, support, scope) · G5 independent replication
(author/transcription clusters, not books) · G6 falsification (fails while a critical objection is open) · G7 expert
(human only) · G8 biomedical evidence (only for cross-space hypotheses; layers: exists, supports, contradicts,
context, human support, levels — contradicting modern evidence fails it). Gates run as `validator:gates`, stamped with
the hypothesis version they judged — agents never grade their own work.

## Contract, warrants and acceptance

A `GoalSpec` is an executable contract: its `AcceptanceSpec` (minimum support, semantic support, source dependence,
falsification review, open hard and critical objections, rival explanations addressed, gates on the current version,
confirmation, expert review) and an optional `ConfirmationSpec` (material withheld from exploration, by source family
and period, on which the hypotheses' predictions are then checked).  At the end of a run a validator judges every
hypothesis against the criteria on the version it now has; each criterion records its judge, what it observed, what it
required and the state a failure leads to.  The research is `research_accepted`, `needs_expert`, `inconclusive` or
`budget_exhausted` — never "completed" because no task was left.  Each hypothesis carries a **warrant**: its inference,
assumptions, the rival explanations of its discovery type (excluded / open / not applicable / unaddressed) and the
discriminating analyses that decided them; the director plans discriminating actions for the rivals still open.
Objections follow a state machine (raised → resolution proposed → closed): a model only proposes; a hard objection
closes by a validator's passing re-run, an interpretive one by a verified narrowing or an expert.

## Long runs

Budgets reserve before a model call and settle after it, as events (a resumed run starts from the ledger; an unsettled
reservation counts as spent). Each turn's messages are compiled afresh: recent exchanges whole, older tool results
reduced to their page handles. Model responses can be recorded and replayed exactly (`--record-llm`, `--replay-llm`).
Evidence can be retracted — it is removed from what rested on it, the gates that used it are voided, closures that cited
it reopen and the contract is judged again — and tasks cancelled or retried. A run manifest records the code, corpus,
configuration and the hash chain of tool receipts at the start and the end of a run.

## Isolation

Sandboxes have tiers — in-process, process, namespace, container. Code of model or user origin needs the namespace
tier or better (unprivileged user, mount, network, PID and IPC namespaces; a read-only root; a private workspace; no
network) and is refused where none is available. Code Mode runs there and reaches tools only by RPC through the
scheduler, under the caller's permissions. The namespace tier is not VM-grade isolation.

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
Stopping ends the *execution*; whether the research is accepted is the contract's verdict, judged after it.

The boundaries of this page are measured, not only tested: `taochronos eval invariants` runs them as probes against the
harness under evaluation, and `taochronos eval interpretive` scores the reading of hard cases
([evals.md](evals.md), [ADR 0009](adr/0009-boundaries-contract-and-evaluation-layers.md)).

## Observability

`research_metrics` reports research-level signals — evidence and counter-evidence counts, source
diversity (normalised entropy), hypothesis survival, knowledge gain per round, gate outcomes — alongside
operational ones (agents, tool calls, model calls, tokens, cost). `taochronos trace` shows the agent tree
(round → task → agent → tool calls) and the hypothesis genealogy.
