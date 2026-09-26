"""Output schemas named by ``AgentSpec.output_schema``.

Deterministic procedures and LLM agents produce the *same* typed output for a
role; one commit function per role verifies it (verbatim quotes, spans, sense
ids, hooks) before anything reaches the blackboard.  A model that returns
malformed output is asked to fix it; a model that cannot is replaced by the
deterministic procedure and the fallback is recorded.
"""

from __future__ import annotations

from typing import Any

from .planning import KIND_ROLE

S: dict[str, Any] = {"type": "string"}
N: dict[str, Any] = {"type": "number"}
I: dict[str, Any] = {"type": "integer"}
B: dict[str, Any] = {"type": "boolean"}
STRS: dict[str, Any] = {"type": "array", "items": S}


def obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


QUOTE = obj({"passage_id": S, "quote": S, "claim_id": S}, ["passage_id", "quote"])
READING = obj({"reading": S, "probability": {"type": "number", "minimum": 0, "maximum": 1}, "witness": S, "kind": S, "note": S},
              ["reading", "probability"])
PREDICTION = obj({"kind": S, "subject": S, "object": {"anyOf": [S, {"type": "null"}]}, "description": S,
                  "period": {"anyOf": [obj({"start": I, "end": I}), {"type": "null"}]}}, ["kind", "subject", "description"])

OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "ResearchPlan": obj({
        "rationale": S,
        "focus": STRS,
        "tasks": arr(obj({"kind": {"type": "string", "enum": sorted(k for k in KIND_ROLE if k != "plan")},
                          "inputs": {"type": "object"}, "priority": I, "reason": S}, ["kind"])),
    }, ["rationale", "tasks"]),
    "CorpusManifest": obj({
        "book_ids": STRS, "passage_ids": STRS, "excluded": {"type": "object"}, "coverage": {"type": "object"},
        "holdout_passage_ids": STRS, "time_basis": S, "warnings": STRS,
    }, ["book_ids", "passage_ids"]),
    "PhilologyReport": obj({
        "assessments": arr(obj({
            "passage_id": S,
            "contested": arr(obj({"start": I, "end": I, "base": S, "options": arr(READING),
                                  "uncertain": {"type": "number", "minimum": 0, "maximum": 1}, "rationale": S},
                                 ["start", "end", "base", "options", "uncertain"])),
            "notes": STRS,
        }, ["passage_id"])),
    }, ["assessments"]),
    "TermResolutionReport": obj({
        "resolutions": arr(obj({"term_id": S, "surface": S, "passage_id": S, "start": I, "end": I,
                                "sense_id": {"anyOf": [S, {"type": "null"}]}, "probability": N,
                                "alternatives": {"type": "object"}, "rationale": S},
                               ["term_id", "passage_id", "start", "end", "sense_id", "probability"])),
    }, ["resolutions"]),
    "ClaimSet": obj({
        "claims": arr(obj({"passage_id": S, "relation": S, "quote": S,
                           "arguments": arr(obj({"role": S, "surface": S, "negated": B}, ["role", "surface"])),
                           "modality": S, "context": S}, ["passage_id", "relation", "quote", "arguments"])),
    }, ["claims"]),
    "MappingProposals": obj({
        "mappings": arr(obj({"sense_id": S, "concept_id": S, "relation": S, "rationale": S}, ["sense_id", "concept_id", "relation"])),
    }, ["mappings"]),
    "LineageReport": obj({"edges": arr({"type": "object"})}, ["edges"]),
    "EvidenceSet": obj({
        "records": arr(obj({"passage_id": S, "quote": S, "stance": {"type": "string", "enum": ["supports", "contradicts", "neutral", "context"]},
                            "hypothesis_id": {"anyOf": [S, {"type": "null"}]}, "claim_id": {"anyOf": [S, {"type": "null"}]},
                            "query": S, "note": S}, ["passage_id", "quote", "stance"])),
    }, ["records"]),
    "ObservationSet": obj({"observations": arr({"type": "object"}), "contradictions": arr({"type": "object"})}, ["observations"]),
    "AnalysisSet": obj({"analyses": arr(obj({"target_id": {"anyOf": [S, {"type": "null"}]}, "kind": S, "method": S,
                                             "result": {"type": "object"}}, ["kind", "result"]))}, ["analyses"]),
    "HypothesisSet": obj({
        "hypotheses": arr(obj({
            "statement": S, "kind": S, "observation_ids": STRS, "terms": STRS, "support": arr(QUOTE),
            "alternative_explanations": STRS, "testable_prediction": S, "predictions": arr(PREDICTION),
            "philological_risk": S, "anachronism_risk": S, "novelty_rationale": S, "space": S,
        }, ["statement", "kind", "observation_ids", "support"])),
    }, ["hypotheses"]),
    "RevisionSet": obj({
        "revisions": arr(obj({"parent_id": S, "statement": S, "revision_note": S, "qualifiers": {"type": "object"},
                              "alternative_explanations": STRS, "testable_prediction": S}, ["parent_id", "statement", "revision_note"])),
    }, ["revisions"]),
    "ReviewSet": obj({
        "reviews": arr(obj({
            "hypothesis_id": S,
            "verdict": {"type": "string", "enum": ["survives", "revise", "reject"]},
            "summary": S,
            "checks_run": STRS,
            "objections": arr(obj({"check": S, "severity": {"type": "string", "enum": ["critical", "major", "minor", "info"]},
                                   "detail": S, "counter_evidence": arr(QUOTE), "passage_ids": STRS, "resolved": B, "resolution": S},
                                  ["check", "severity", "detail"])),
        }, ["hypothesis_id", "verdict", "objections"])),
    }, ["reviews"]),
    "ModernEvidenceSet": obj({
        "links": arr(obj({"hypothesis_id": S, "record_id": S, "concept_id": S, "relation": S, "note": S}, ["record_id"])),
        "bridges": arr({"type": "object"}),
    }, ["links"]),
    "SourcesDossier": obj({
        "dossiers": arr(obj({"target": S, "term_id": {"anyOf": [S, {"type": "null"}]}, "kind": {"type": "string", "enum": ["formula", "herb", "term"]},
                             "headline": S, "lines": STRS,
                             "witnesses": arr(obj({"passage_id": S, "locator": S, "quote": S, "role": S}, ["passage_id", "quote"]))},
                            ["target", "kind", "headline", "witnesses"])),
    }, ["dossiers"]),
    "MetaReview": obj({
        "summary": S,
        "systemic_issues": arr(obj({"check": S, "count": I, "note": S}, ["check"])),
        "recommendations": arr(obj({"action": S, "target": S, "reason": S}, ["action", "reason"])),
        "duplicates": arr(STRS),
        "leaderboard": arr({"type": "object"}),
    }, ["summary", "recommendations"]),
}


def output_schema(name: str) -> dict[str, Any]:
    try:
        return OUTPUT_SCHEMAS[name]
    except KeyError:
        raise KeyError(f"unknown output schema {name!r} (known: {sorted(OUTPUT_SCHEMAS)})") from None
