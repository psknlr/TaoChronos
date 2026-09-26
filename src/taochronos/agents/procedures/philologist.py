"""Philologist (校勘): readings, variants, collation status — never a forced single reading.

The deterministic draft weighs witnesses and a TCM-coherence check; a model
may re-weigh contested spans and add rationale.  The commit enforces the
invariants: spans inside the passage, the base reading equal to the text,
probabilities normalised, and an explicit uncertain mass that never drops
below the floor.
"""

from __future__ import annotations

from typing import Any

from ...protocol.events import EventType
from ...protocol.outputs import ContestedSpan, PhilologyAssessment, ReadingOption
from .common import scope_passages

OUTPUT = "PhilologyReport"
MIN_UNCERTAIN = 0.05


def instructions(ctx: Any) -> str:
    return ("Assess the contested spans of the passages in scope. For each contested span keep all plausible readings "
            "with probabilities and an explicit 'uncertain' mass (≥ 0.05); explain your weighting in 'rationale' "
            "(witness quality, 通假/异体, internal coherence of the medical argument). Do not change passage texts.")


def draft(ctx: Any) -> dict[str, Any]:
    philology = ctx.cap("philology")
    return {"assessments": [philology.assess(p).to_dict() for p in scope_passages(ctx)]}


def llm_draft(ctx: Any, full: dict[str, Any]) -> dict[str, Any]:
    """Only passages with contested spans are worth a model's attention."""
    return {"assessments": [{"passage_id": a["passage_id"], "contested": a["contested"], "notes": a.get("notes", [])}
                            for a in full["assessments"] if a.get("contested")]}


def _checked_spans(text: str, spans: list[dict[str, Any]]) -> tuple[list[ContestedSpan], list[str]]:
    out, problems = [], []
    for raw in spans:
        start, end = int(raw["start"]), int(raw["end"])
        if not (0 <= start < end <= len(text)):
            problems.append(f"span {start}:{end} outside passage")
            continue
        base = text[start:end]
        if raw.get("base") != base:
            problems.append(f"base reading {raw.get('base')!r} ≠ text {base!r}")
            continue
        options = [ReadingOption(reading=o["reading"], probability=max(0.0, float(o["probability"])), witness=o.get("witness", "?"),
                                 kind=o.get("kind", "reading"), note=o.get("note", "")) for o in raw.get("options", [])]
        if not any(o.reading == base for o in options):
            options.insert(0, ReadingOption(reading=base, probability=0.0, witness="base text of the edition", kind="base"))
        uncertain = max(MIN_UNCERTAIN, float(raw.get("uncertain", MIN_UNCERTAIN)))
        mass = sum(o.probability for o in options)
        scale = (1.0 - uncertain) / mass if mass > 0 else 0.0
        for o in options:
            o.probability = round(o.probability * scale, 4) if mass > 0 else round((1.0 - uncertain) / len(options), 4)
        out.append(ContestedSpan(start=start, end=end, base=base, options=options, uncertain=round(uncertain, 4),
                                 rationale=raw.get("rationale", "")))
    return out, problems


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    philology = ctx.cap("philology")
    merged: dict[str, dict[str, Any]] = {a["passage_id"]: a for a in (ctx.draft or {}).get("assessments", [])}
    in_scope = {p.id for p in scope_passages(ctx)}
    adjusted, rejected = 0, 0
    for item in output.get("assessments", []):
        pid = item.get("passage_id")
        if pid not in in_scope or not corpus.has_passage(pid):
            rejected += 1
            continue
        base = dict(merged.get(pid) or philology.assess(corpus.passage(pid)).to_dict())
        if "contested" in item and item["contested"] != base.get("contested"):
            spans, problems = _checked_spans(corpus.passage(pid).text, item["contested"])
            if problems:
                rejected += 1
                ctx.note(f"{pid}: kept deterministic reading weights ({'; '.join(problems)})")
            else:
                assessment = PhilologyAssessment.from_dict(base)
                assessment.contested = spans
                assessment.notes = [n for n in assessment.notes if not n.startswith("contested span")] + [
                    f"contested span “{c.base}”: " + " · ".join(f"{o.reading} {o.probability:.2f}" for o in c.options)
                    + f" · uncertain {c.uncertain:.2f}" for c in spans] + [f"reading weights revised by {ctx.route.model}"]
                base = assessment.to_dict()
                adjusted += 1
        if item.get("notes"):
            base["notes"] = list(dict.fromkeys(list(base.get("notes", [])) + [n for n in item["notes"] if isinstance(n, str)]))
        merged[pid] = base
    assessments = [merged[k] for k in sorted(merged)]
    ctx.emit(EventType.PASSAGE_ASSESSED, {"assessments": assessments})
    contested = sum(1 for a in assessments if a.get("contested"))
    unverified = sum(1 for a in assessments if a.get("collation_status") == "unverified")
    extra = f"; {adjusted} re-weighted by model, {rejected} model edits rejected" if (adjusted or rejected) else ""
    return f"{len(assessments)} passages assessed; {contested} with contested readings; {unverified} uncollated{extra}"
