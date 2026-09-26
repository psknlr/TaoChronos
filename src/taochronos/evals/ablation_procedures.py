"""Procedures used only by ablation studies (never loaded by a normal profile)."""

from __future__ import annotations

from typing import Any

from ..agents.procedures import skeptic as _skeptic
from ..protocol.base import stable_id
from ..protocol.events import EventType
from ..protocol.hypothesis import HypothesisReview

OUTPUT = "ReviewSet"


def instructions(ctx: Any) -> str:
    return "Ablation: accept every hypothesis without checks."


def draft(ctx: Any) -> dict[str, Any]:
    return {"reviews": [{"hypothesis_id": h.id, "verdict": "survives", "objections": [], "checks_run": []}
                        for h in _skeptic._targets(ctx)]}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    for item in output.get("reviews", []):
        review = HypothesisReview(id=stable_id("rev", item["hypothesis_id"], ctx.task.round, ctx.task.kind, "ablation"),
                                  hypothesis_id=item["hypothesis_id"], reviewer=ctx.actor.id, verdict="survives",
                                  summary="ablation: no falsification", round=ctx.task.round)
        ctx.emit(EventType.HYPOTHESIS_REVIEWED, {"review": review.to_dict()}, generated=[review.id])
    return f"ablation: {len(output.get('reviews', []))} hypotheses accepted without review"
