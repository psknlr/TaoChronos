"""Evolution Analyst: concept timelines (D2) and formula family trees (D3).

Produces the structured evolution maps behind the workspace's “Formula
Evolution” and “Concept Evolution” panels and the report's Temporal Pattern
section.  Narratives are generated from the structure, so every sentence
points back to observations and claims.
"""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.events import EventType
from .common import surface

OUTPUT = "AnalysisSet"


def instructions(ctx: Any) -> str:
    return "Build concept timelines and formula family trees from the D2/D3 observations; narrate only what the structure shows."


def _period_label(ctx: Any, period_id: str) -> str:
    return ctx.cap("domain").periods.label(period_id)


def _timeline(ctx: Any, obs: Any) -> dict[str, Any]:
    d = obs.data
    corpus = ctx.cap("corpus")
    rows = []
    for period in d["periods"]:
        rows.append({
            "period": period,
            "label": _period_label(ctx, period),
            "occurrences": d["occurrences"].get(period, 0),
            "books": [corpus.books[b].title for b in d["books"].get(period, []) if b in corpus.books],
            "dominant_sense": d["dominant_sense"].get(period),
        })
    parts = []
    for row in rows:
        sense = row["dominant_sense"] or "（义项未定）"
        parts.append(f"{row['label']}（{'、'.join('《' + t + '》' for t in row['books'][:3])}）以「{sense.split('#')[-1]}」为主")
    changes = "；".join(f"{_period_label(ctx, c['from_period'])}→{_period_label(ctx, c['to_period'])}：{c['from'].split('#')[-1]}→{c['to'].split('#')[-1]}"
                       for c in d.get("sense_changes", []))
    narrative = f"「{surface(d['term'])}」：" + "；".join(parts) + "。" + (f"义项转换：{changes}。" if changes else "未见主导义项转换，变化主要体现在语境分布。")
    return {"kind": "concept_timeline", "term": d["term"], "rows": rows, "sense_changes": d.get("sense_changes", []),
            "jsd_series": d.get("jsd_series", []), "narrative": narrative}


def _tree(ctx: Any, obs: Any) -> dict[str, Any]:
    fam = obs.data
    nodes = [{"id": m, "label": surface(m), "year": fam["years"].get(m), "root": m in fam["roots"]} for m in fam["members"]]
    edges = [{"from": s["parent"], "to": s["child"], "added": s["added"], "removed": s["removed"],
              "substituted": s["substituted"], "renames": s["renames"], "confidence": s["confidence"]} for s in fam["steps"]]
    lines = []
    for s in fam["steps"]:
        change = []
        if s["added"]:
            change.append("加" + "、".join(surface(h) for h in s["added"]))
        if s["removed"]:
            change.append("去" + "、".join(surface(h) for h in s["removed"]))
        for x in s["substituted"]:
            change.append(f"{surface(x['from'])}易为{surface(x['to'])}")
        lines.append(f"{surface(s['child'])} 由 {surface(s['parent'])} " + ("，".join(change) or "化裁") + "而成")
    core = "、".join(surface(h) for h in fam["stable_core"])
    narrative = "；".join(lines) + "。" + (f"贯穿全族的稳定核心为 {core}。" if core else "")
    return {"kind": "formula_tree", "nodes": nodes, "edges": edges, "stable_core": fam["stable_core"],
            "herb_retention": fam.get("herb_retention", {}), "indication_drift": fam.get("indication_drift", []),
            "narrative": narrative}


def draft(ctx: Any) -> dict[str, Any]:
    done = {a.get("target_id") for a in ctx.state.analyses.values() if a.get("kind") == "evolution"}
    analyses = []
    for o in sorted(ctx.state.observations.values(), key=lambda o: o.id):
        if o.id in done:
            continue
        if o.kind == "concept_drift":
            analyses.append({"target_id": o.id, "kind": "evolution", "method": "concept_timeline", "result": _timeline(ctx, o)})
        elif o.kind == "formula_evolution":
            analyses.append({"target_id": o.id, "kind": "evolution", "method": "formula_tree", "result": _tree(ctx, o)})
    return {"analyses": analyses}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    n = 0
    for a in output.get("analyses", []):
        if a.get("target_id") not in ctx.state.observations:
            continue
        aid = stable_id("ana", "evolution", a["target_id"])
        ctx.emit(EventType.ANALYSIS_RECORDED, {"analysis_id": aid, "target_id": a["target_id"], "kind": "evolution",
                                               "method": a.get("method"), "round": ctx.task.round, "result": a["result"]},
                 generated=[aid])
        n += 1
    return f"{n} evolution maps"
