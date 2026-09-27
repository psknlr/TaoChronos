"""TaoChronos-Eval suites of the V2 capabilities: entities (T7) and the others added with them.

A model can be measured too: set ``TAOCHRONOS_EVAL_LLM=provider:model`` (e.g. ``minimax:MiniMax-M2.7``) and the suites
that have a model phase run it beside the rules, and report both.  Without it only the rules are measured — the numbers
the documentation gives are those.
"""

from __future__ import annotations

import os
from typing import Any

from .base import EvalContext, SuiteResult


def eval_judge(ctx: EvalContext, harness: Any) -> Any:
    """The judge named by TAOCHRONOS_EVAL_LLM, or None."""
    spec = os.environ.get("TAOCHRONOS_EVAL_LLM")
    if not spec:
        return None
    try:
        return harness.judge(spec, max_calls=int(os.environ.get("TAOCHRONOS_EVAL_LLM_CALLS", "120")))
    except ValueError:
        return None


def _gold_spans(sentences: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    out = []
    for sent in sentences:
        text, pos, gold = sent["text"], {}, []
        for surface, type_ in sent["entities"]:
            start = text.find(surface, pos.get(surface, 0))
            if start < 0:
                raise ValueError(f"gold entity {surface!r} not in {text!r}")
            pos[surface] = start + len(surface)
            gold.append({"start": start, "end": start + len(surface), "type": type_, "text": surface})
        out.append((text, gold))
    return out


def _ner(study: Any, cases: list[tuple[str, list[dict[str, Any]]]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from ..plugins.classics.study.entities import score_entities

    gold_all, pred_all, details = [], [], []
    offset = 0
    for text, gold in cases:
        res = study.entities(text)
        pred = [{"start": e["start"], "end": e["end"], "type": e["type"]} for e in res["entities"]]
        g = {(x["start"], x["end"], x["type"]) for x in gold}
        p = {(x["start"], x["end"], x["type"]) for x in pred}
        if g != p:
            details.append({"text": text, "missed": sorted(f"{text[s:e]}:{t}" for s, e, t in g - p),
                            "extra": sorted(f"{text[s:e]}:{t}" for s, e, t in p - g)})
        gold_all += [dict(x, start=x["start"] + offset, end=x["end"] + offset) for x in gold]
        pred_all += [dict(x, start=x["start"] + offset, end=x["end"] + offset) for x in pred]
        offset += len(text) + 1
    s = score_entities(gold_all, pred_all)
    return s, details


def entities(ctx: EvalContext) -> SuiteResult:
    """EntityEval (T7): entity P/R/F1 (exact span and type) on sentences of the classics and sentences written for the
    test — the development set the rules were written on (gold/ner.yaml) and a set annotated before the recognizer ever
    ran on it (gold/ner_heldout.yaml, the fairer estimate); per type; with a model (TAOCHRONOS_EVAL_LLM), both again."""
    from ..plugins.classics.study import StudyService

    h = ctx.default
    study = StudyService(h.pack, h.corpus)
    metrics: dict[str, Any] = {}
    details: list[dict[str, Any]] = []
    for name in ("ner", "ner_heldout"):
        cases = _gold_spans(ctx.gold(name)["sentences"])
        s, d = _ner(study, cases)
        key = "development" if name == "ner" else "held_out"
        metrics[key] = {"precision": s["precision"], "recall": s["recall"], "f1": s["f1"], "span_f1": s["span_only"]["f1"],
                        "entities": s["tp"] + s["fn"], "sentences": len(cases)}
        metrics[f"{key}_per_type"] = {t: v["f1"] for t, v in s["per_type"].items()}
        details += [dict(x, set=key) for x in d]
    notes = ["gold/ner.yaml is the development set; gold/ner_heldout.yaml was annotated before the recognizer ran on it "
             "(first measured F1 0.757; 0.776 after fixing two bugs it revealed — chained processing words, 破八片 read "
             "as a dose — with no rule added for its content)"]
    judge = eval_judge(ctx, h)
    if judge is not None:
        study.judge = judge
        for name in ("ner", "ner_heldout"):
            s, _ = _ner(study, _gold_spans(ctx.gold(name)["sentences"]))
            metrics[("development" if name == "ner" else "held_out") + "_with_model"] = {
                "precision": s["precision"], "recall": s["recall"], "f1": s["f1"], "judge": judge.label}
        metrics["model_usage"] = judge.report()["budget"]
        notes.append(f"with the model {judge.label}: ambiguous spans typed and missed entities added (spans checked)")
    else:
        notes.append("no model measured (set TAOCHRONOS_EVAL_LLM=provider:model to measure the rule + model pipeline)")
    return SuiteResult("entities", metrics, details, notes=notes)


__all__ = ["entities", "eval_judge"]
