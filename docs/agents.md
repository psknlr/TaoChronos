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
tools (`study.formula`, `study.herb`, `study.term`) and records one dossier per target — a headline, key findings and
the verbatim witnesses they rest on. The Director adds its task (`trace_sources`, after `resolve_terms`) to round 0
when the profile sets `discovery.sources_dossier` (as `full-corpus` does); the dossiers become the appendix
“源流考证” of the Discovery Report. They describe texts and pass no gates (see [study.md](study.md)).

## One output contract, two producers

Every role module implements `draft(ctx)` (the deterministic procedure), `instructions(ctx)` (the brief a
model receives) and `commit(ctx, output)`. The procedure and a model produce **the same typed output**,
and one `commit` verifies both:

- quotes are located in the passage by the harness (never trusted from the output) — a quote that cannot be
  found verbatim, or after length-preserving variant normalisation, is dropped;
- sense ids must exist, spans must match surfaces, probabilities are normalised with an uncertain floor;
- hypotheses without verified evidence are dropped (evidence-first), and `AfterHypothesis` hooks block
  anachronisms;
- a model may add Skeptic objections but cannot skip a review; a critical objection without verifiable
  counter-evidence is downgraded to major; the verdict follows from severities (harness policy).

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
`BeforeLLMCall` hook and the budget) → tool calls executed by the scheduler under the agent's permissions →
repeat until the model returns JSON that validates against the output schema (invalid output is sent back
with the validation errors; `max_tokens` truncation is retried) → `commit`.

## Providers

| Plugin | Notes |
|---|---|
| `models.offline` | deterministic procedures; the default |
| `models.anthropic_provider` | official `anthropic` SDK; `claude-opus-5` (frontier), `claude-sonnet-5` (medium), `claude-haiku-4-5` (small); adaptive thinking and `output_config.effort` where supported; server-side refusal fallbacks (`fallbacks="default"`) on Opus 5; refusals are checked before content; assistant turns (including thinking blocks) are replayed verbatim |
| `models.openai_compat` | OpenAI-compatible chat completions (OpenAI, DeepSeek, Grok, Gemini's compatibility endpoint, local vLLM/Ollama); model names come only from configuration |
| `models.scripted` | replays queued responses; used by tests |

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
defence in depth, not a security boundary; untrusted models belong behind a process sandbox.

## Skills

`skills/*/SKILL.md` are reusable research methods (front matter + Markdown). A spec's skills are rendered
into its context view; the index of the others is listed in the system prompt (progressive disclosure).
