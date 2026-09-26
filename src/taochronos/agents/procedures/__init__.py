"""Deterministic role procedures.

Each module implements one role with the same three functions:

* ``draft(ctx) -> dict`` — the deterministic procedure (always available, reproducible);
* ``instructions(ctx) -> str`` — the task brief given to a model in llm / hybrid mode;
* ``commit(ctx, output) -> str`` — verifies an output (from either source) and emits events.

Optional: ``llm_draft(ctx, draft)`` trims the draft shown to a model and
``output_schema_for(ctx)`` picks the output schema per task kind.
"""

ROLE_MODULES = {
    "director": "taochronos.agents.procedures.director",
    "curator": "taochronos.agents.procedures.curator",
    "philologist": "taochronos.agents.procedures.philologist",
    "semanticist": "taochronos.agents.procedures.semanticist",
    "extractor": "taochronos.agents.procedures.extractor",
    "ontologist": "taochronos.agents.procedures.ontologist",
    "lineage": "taochronos.agents.procedures.lineage",
    "evidence": "taochronos.agents.procedures.evidence",
    "pattern_miner": "taochronos.agents.procedures.pattern_miner",
    "statistician": "taochronos.agents.procedures.statistician",
    "evolution": "taochronos.agents.procedures.evolution",
    "hypothesis": "taochronos.agents.procedures.hypothesis",
    "skeptic": "taochronos.agents.procedures.skeptic",
    "modern_evidence": "taochronos.agents.procedures.modern_evidence",
    "meta_reviewer": "taochronos.agents.procedures.meta_reviewer",
}
