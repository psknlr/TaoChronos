# Agents

An agent is **configuration, not a class**. Each `agents/*.yaml` is an AgentSpec:

```yaml
role: skeptic
name: TaoChronos-Skeptic
objective: Search for counter-evidence, earlier or later sources, edition variants, homonymy …
mode: hybrid                      # procedure | llm | hybrid
procedure: taochronos.agents.procedures.skeptic
skills: [falsification, philology-collation, historical-semantics]
tools: [classics.search, classics.get_passage, kg.claims, philology.assess_passage, validation.verify_quote]
context_view: skeptic
permissions: [classics:read, kg:read, analysis:run, codemode:exec]
output_schema: ReviewSet
model: {min_tier: frontier, effort: high, max_tokens: 16000}
budget: {max_tool_calls: 400, max_llm_calls: 12}
stop_conditions: [output_valid, "max_turns:12"]
code_mode: true
```

Specs are validated when loaded: commit-level permissions are refused, every tool must exist and be
covered by a granted permission, and schemas, context views, skills and procedures must resolve.

## The roster

The research director is **TaoChronos**. It plans each round and decides which specialists the question
needs; the engine then spawns one agent instance per task (`agent:<role>@<task>`).

| Role | Name | Mode | Output |
|---|---|---|---|
| director | TaoChronos | hybrid | ResearchPlan |
| curator | TaoChronos-Curator | procedure | CorpusManifest |
| philologist | TaoChronos-Philologist | hybrid | PhilologyReport |
| semanticist | TaoChronos-Semanticist | hybrid | TermResolutionReport |
| extractor | TaoChronos-Extractor | hybrid | ClaimSet |
| ontologist | TaoChronos-Ontologist | hybrid | MappingProposals |
| lineage | TaoChronos-Lineage | procedure | LineageReport |
| evidence | TaoChronos-Evidence | hybrid | EvidenceSet |
| pattern_miner | TaoChronos-PatternMiner | procedure | ObservationSet |
| statistician | TaoChronos-Statistician | procedure | AnalysisSet |
| evolution | TaoChronos-Evolution | procedure | AnalysisSet |
| scholar | TaoChronos-Scholar | procedure | SourcesDossier |
| hypothesis | TaoChronos-Hypothesis | hybrid | HypothesisSet / RevisionSet |
| skeptic | TaoChronos-Skeptic | hybrid | ReviewSet |
| modern_evidence | TaoChronos-ModernEvidence | hybrid | ModernEvidenceSet |
| meta_reviewer | TaoChronos-MetaReviewer | hybrid | MetaReview |

Validators (`validate_claims`, `validate`, `score`) are harness code running as `validator:gates`, not agents.

**TaoChronos-Scholar** (治学) traces the focus formulas, drugs and terms through the *whole* store with the study
tools (`study.formula`, `study.herb`, `study.term`, and `study.senses` for terms: where the meaning shifted, and a
candidate sense the curation lacks) and records one dossier per target — a headline, key findings and the verbatim
witnesses they rest on. The Director adds its task (`trace_sources`, after `resolve_terms`) to round 0
when the profile sets `discovery.sources_dossier` (as `full-corpus` does); the dossiers become the appendix
“源流考证” of the Discovery Report. They describe texts and pass no gates (see [study.md](study.md)).

**深层发现 2.0 tools, no new roles.** The deep-discovery capabilities
([study.md](study.md#深层发现-20--the-structure-of-the-literature), [ADR 0005](adr/0005-deep-discovery-capabilities.md))
are tools on the agents whose work they serve. The model of a hybrid agent may call them; procedures call what they
need.

| Agent | Tools added |
|---|---|
| Philologist | `study.variants`, `study.stemma`, `study.witnesses`, `study.layers`, `study.dating`, `study.authorship` |
| Skeptic | `study.reuse`, `study.dating`, `study.argument` |
| Evidence | `study.cases`, `study.trajectories`, `study.argument` |
| Semanticist | `study.term`, `study.senses` |
| Scholar | `study.senses` (in its procedure) |

The Lineage Analyst gets the reuse types through the lineage edges themselves.

**任务规格 v1.0 tools, no new roles.** The capabilities added with the [task specification](tasks.md) (句读, 条文结构,
训诂, 集注与注家比较, 争议, 配伍, 方证网络, 学派, 名称, 传播链) are tools on the agents whose work they serve, in the same
way; [tasks.md](tasks.md#l5-research-agent) maps the roadmap's eight domain agents and four research-grade agents onto
these roles.

| Agent | Tools added |
|---|---|
| Philologist | `study.punctuate`, `study.clause`, `study.glosses`, `study.commentaries` |
| Extractor | `study.clause` |
| Skeptic | `study.disputes` |
| Semanticist | `study.glosses`, `study.names` |
| Scholar | `study.commentaries`, `study.disputes`, `study.network`, `study.schools`, `study.names` |
| Pattern Miner | `study.pairs`, `study.network` |
| Lineage Analyst | `study.schools`, `study.chain` |

## One output contract, two producers

Every role module implements `draft(ctx)` (the deterministic procedure), `instructions(ctx)` (the brief a
model receives) and `commit(ctx, output)`. The procedure and a model produce **the same typed output**,
and one `commit` verifies both:

- quotes are located in the passage by the harness (never trusted from the output) — a quote that cannot be
  found verbatim, or after length-preserving variant normalisation, is dropped;
- sense ids must exist, spans must match surfaces, probabilities are normalised with an uncertain floor;
- claims pass the commit hooks: verbatim at their span (provenance) and *stated* by their quote (semantic support —
  a claim its quote contradicts is refused), and they carry the statement's frame (speaker, stance, conditions,
  negations, time) read by the harness, not by the producer;
- hypotheses without verified evidence are dropped (evidence-first), and `AfterHypothesis` hooks block
  anachronisms; a revision is typed restricting or substantive, and a substantive one needs its own support;
- a model may add Skeptic objections but cannot skip a review, soften one or close one: whatever it says was
  "resolved" becomes a *proposed* resolution, which a validator's re-run (hard checks) or a verified narrowing or an
  expert (interpretive ones) may close; the verdict follows from severities (harness policy).

An agent never holds the session: it acts through a `SessionView` bound to its own identity (it cannot emit above its
principal) and reads a frozen `StateView`; its capability handles are scoped to its reading scope, so material withheld
from exploration does not exist for it.

## Modes and routing

The **Cognitive Model Router** decides per task:

- `procedure` for tool-first roles (pattern mining, statistics, lineage, evolution, curation), and for every
  role in the offline profiles;
- otherwise the cheapest available model meeting the spec's `min_tier`, preferring strong classical-Chinese
  readers where the spec asks for it, and a *different* model for the Skeptic than for the Hypothesis agent;
- profile `routing.roles` overrides per role (provider, model, effort, mode, subagent);
- no suitable model → the deterministic procedure, recorded in `ModelRouted`.

In **hybrid** mode the procedure runs first and its draft is given to the model to improve; if the model
refuses, keeps producing invalid output or exhausts its budget, the draft is committed and a `fallback`
Decision is recorded.

## The LLM tool loop

`AgentRuntime._llm_loop`: context view → system prompt (“You are TaoChronos…” for the director,
“You are TaoChronos-<Role>, the … agent of TaoChronos” for specialists) → model call (checked by the
`BeforeLLMCall` hook; its estimated cost reserved in the budget ledger first and settled after) → tool calls executed
by the scheduler under the agent's permissions (long results paged: the model reads on with `context__page`) →
repeat, each turn's messages compiled afresh with older tool results reduced to their page handles, until the model
returns JSON that validates against the output schema (invalid output is sent back with the validation errors;
`max_tokens` truncation is retried) → `commit`.

## Providers

| Plugin | Notes |
|---|---|
| `models.offline` | deterministic procedures; the default |
| `models.anthropic_provider` | official `anthropic` SDK; `claude-opus-5` (frontier), `claude-sonnet-5` (medium), `claude-haiku-4-5` (small); adaptive thinking and `output_config.effort` where supported; server-side refusal fallbacks (`fallbacks="default"`) on Opus 5; refusals are checked before content; assistant turns (including thinking blocks) are replayed verbatim |
| `models.openai_compat` | OpenAI-compatible chat completions with presets for MiniMax (mainland `api.minimax.cn` and global), Poe, DeepSeek, Qwen (DashScope), Kimi (Moonshot), GLM (Zhipu), Doubao (Volcengine Ark), SiliconFlow, OpenRouter, OpenAI, Gemini, Grok, a LiteLLM proxy and local vLLM/Ollama; MiniMax reasoning split off, Poe without `response_format`, `Retry-After` respected; images for vision models; model names come only from configuration |
| `models.litellm_provider` | the `litellm` package: any back end by `<provider>/<model>` (`pip install -e ".[litellm]"`) |
| `models.scripted` | replays queued responses; used by tests |

## V2 core agents

Four core agents (`agents/core/*.yaml`) own the fifteen skills of V2 ([v2.md](v2.md)); each acts with its own permissions
(the kernel's policy checks every tool call a skill makes) and delegates to the specialist roles above.

| Core agent | Skills | Delegates to | Permissions |
|---|---|---|---|
| Research Orchestrator | plan, synthesize | director, meta_reviewer | classics:read, kg:read, analysis:run |
| Classical TCM Scholar | S01–S09 (sources, vision, philology, structure, collation, intertext, extraction, names, evolution) | curator, philologist, extractor, semanticist, lineage, scholar, evolution | classics:read, kg:read |
| Translational Medicine Agent | S10–S14 (phenotypes, ontology bridge, clinical mapping, modern evidence, real-world data) | ontologist, modern_evidence, hypothesis | classics:read, kg:read, literature:read |
| Evidence & Critic Agent | S15 (audit, evidence graph) | evidence, skeptic, statistician | classics:read, kg:read, literature:read, validation:run |

The specialists gained the V2 tools: `bridge.*` (ontologist, modern_evidence, semanticist), `audit.claim` and
`graph.evidence` (skeptic, meta_reviewer, evidence), `modern.search`, `modern.safety`, `rwd.ask` (modern_evidence).

## Subagents

`ctx.spawn(role, kind, inputs)` plans and runs a child task through the local runtime (same gates, same
log). `plugins.subagents.command` runs any command-line agent as a role: it receives
`{agent, role, task, system, prompt, output_schema}` on stdin and prints one JSON object, which is
validated and committed like model output.

## Research Code Mode

Instead of many JSON tool calls, a model may write a short Python program against a generated SDK
(`classics.search(...)`, `kg.claims(...)`, `analysis.concept_drift(...)`, `batch([...])`). The program's
AST is checked against a whitelist (no imports, no private names), runs with a step budget, and every SDK
call goes through the scheduler — so permissions, hooks, budgets and the event log apply. The whitelist is
defence in depth, not the boundary: a model's program runs in the **namespace** sandbox tier (unprivileged user,
mount, network, PID and IPC namespaces; a read-only root; a private workspace; no network) and reaches the SDK only by
RPC through the scheduler. Where no isolating tier exists, model code is refused rather than run in a weaker one.

## Skills

`skills/*/SKILL.md` are reusable research methods (front matter + Markdown). A spec's skills are rendered
into its context view; the index of the others is listed in the system prompt (progressive disclosure).
