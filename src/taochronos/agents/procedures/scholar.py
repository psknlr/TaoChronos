"""TaoChronos-Scholar (治学): the textual history of the focus terms, read from the whole corpus.

For each focus formula, drug or term the Scholar calls the study tools — 方源考 (``study.formula``), 药性源流
(``study.herb``), 术语源流 (``study.term``) and 语义演变 (``study.senses``) — and keeps a dossier of verbatim witnesses:
where the name first appears, the original and the most-witnessed compositions, the first statement of each property,
the periods in which a term rises or falls, where its senses shift and which of its uses no curated sense covers.
Dossiers are recorded as analyses and printed as an appendix of the Discovery Report.  They describe the texts; they
are not hypotheses and pass no gates.
"""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.events import EventType
from .common import focus_term_ids, surface

OUTPUT = "SourcesDossier"


def instructions(ctx: Any) -> str:
    return ("Trace the focus formulas, drugs and terms through the whole corpus with the study tools and return one "
            "dossier per target: a headline, the key findings as short lines, and the verbatim witnesses they rest on.")


def _years(w: dict[str, Any]) -> str:
    ys = w.get("years") or []
    if not ys:
        return "年代未定"
    return f"{int(ys[0])}" if ys[0] == ys[1] else f"{int(ys[0])}–{int(ys[1])}"


def _witness(w: dict[str, Any] | None, role: str) -> list[dict[str, Any]]:
    if not w or not w.get("passage_id"):
        return []
    return [{"passage_id": w["passage_id"], "locator": w.get("locator", ""), "quote": (w.get("quote") or "")[:200], "role": role}]


def _top(counts: dict[str, int] | None, n: int = 2) -> str:
    return "、".join(k for k, _ in sorted((counts or {}).items(), key=lambda kv: -kv[1])[:n])


def _targets(ctx: Any) -> list[tuple[str, str | None, str]]:
    """(name, term id, kind) for the focus terms: formulas and drugs get their own studies, other terms a term history."""
    lexicon = ctx.cap("domain").lexicon
    cfg = (ctx.config or {}).get("sources_dossier")
    limit = int(cfg.get("max_targets", 6)) if isinstance(cfg, dict) else 6
    wanted = list(ctx.inputs.get("terms") or []) or focus_term_ids(ctx)
    out = []
    for tid in wanted:
        entry = lexicon.entry(tid) if ":" in tid else None
        name = entry.term if entry else surface(tid)
        category = entry.category if entry else ""
        out.append((name, tid if ":" in tid else None, "formula" if category == "formula" else "herb" if category == "herb" else "term"))
    return out[:limit]


def _formula(name: str, r: dict[str, Any]) -> dict[str, Any]:
    s = r.get("summary") or {}
    first = r.get("earliest")
    lines = []
    for g in [g for g in r.get("groups", []) if isinstance(g, dict) and "relation" in g][:5]:
        span = g.get("span") or []
        lines.append(f"{g['relation']}：{'、'.join(g.get('core_terms', []))}（{g.get('witnesses')} 条见证"
                     + (f"，{int(span[0])}–{int(span[1])}" if span else "") + "）")
    others = [o for o in r.get("other_names", []) if isinstance(o, dict) and "name" in o][:6]
    if others:
        lines.append("同方异名：" + "、".join(f"{o['name']}（{o['witnesses']}）" for o in others))
    songs = [x for x in r.get("songs", []) if isinstance(x, dict) and x.get("quote")]
    if songs:
        lines.append(f"方歌：{songs[0]['quote'][:60]}（{songs[0].get('title', '')}）")
    headline = (f"{name}：{s.get('compositions', 0)} 条写出组成的见证，见于 {s.get('works', 0)} 部著作"
                + (f"；原方最早见于{first['locator']}（{_years(first)}）" if first else "；未见写出组成的条文"))
    current = next((g for g in r.get("groups", []) if isinstance(g, dict) and str(g.get("relation", "")).startswith("通行方")), None)
    witnesses = _witness(first, "原方") + _witness((current or {}).get("earliest"), "通行方")
    witnesses += _witness(songs[0] if songs else None, "方歌") + _witness((others[0] if others else {}).get("first"), "同方异名")
    return {"headline": headline, "lines": lines, "witnesses": witnesses}


def _herb(name: str, r: dict[str, Any]) -> dict[str, Any]:
    s = r.get("summary") or {}
    entries = [e for e in r.get("entries", []) if isinstance(e, dict) and "passage_id" in e]
    firsts = [f for f in r.get("firsts", []) if isinstance(f, dict) and "field" in f]
    lines = [f"首言{f['field']}“{f['value']}”：{f['locator']}（{_years(f)}）" for f in firsts if f["field"] != "异名"][:8]
    for per in [p for p in r.get("periods", []) if isinstance(p, dict) and "period" in p][:8]:
        lines.append(f"{per['period']}：{per.get('books', 0)} 部；性 {_top(per.get('natures')) or '—'}；归经 {_top(per.get('channels')) or '—'}")
    headline = f"{name}：{s.get('works', len(entries))} 部本草著作有条目" + (f"；最早见于{s['earliest']}" if s.get("earliest") else "")
    witnesses = _witness(entries[0] if entries else None, "最早条目")
    channel = next((f for f in firsts if f["field"] == "归经"), None)
    witnesses += _witness(channel, "首言归经")
    return {"headline": headline, "lines": lines, "witnesses": witnesses}


def _term(name: str, r: dict[str, Any]) -> dict[str, Any]:
    trend = r.get("trend") or {}
    lines = []
    for row in [x for x in r.get("periods", []) if isinstance(x, dict) and "period" in x]:
        ci = row.get("ci_per_10k") or []
        lines.append(f"{row['period']}：{row['passages']} 段，每万段 {row.get('per_10k')}" + (f"［{ci[0]}, {ci[1]}］" if ci else ""))
    dense = [d for d in r.get("dense_books", []) if isinstance(d, dict) and "title" in d][:4]
    if dense:
        lines.append("论述最密：" + "、".join(f"《{d['title']}》" for d in dense))
    headline = (f"{name}：{r.get('total_passages', 0)} 段"
                + (f"；历期趋势 z={trend['z']:.2f}（p={trend['p']:.2g}）" if trend.get("z") is not None else ""))
    witnesses = []
    for w in [w for w in r.get("earliest", []) if isinstance(w, dict)][:4]:
        witnesses += _witness(w, "早期用例")
    return {"headline": headline, "lines": lines, "witnesses": witnesses}


def _senses(r: dict[str, Any]) -> dict[str, Any]:
    """Lines and witnesses from 语义演变: the sense shares where they shift, and a candidate sense the curation lacks."""
    lines = []
    for cp in [c for c in r.get("change_points", []) if isinstance(c, dict) and "year" in c][:3]:
        before = "、".join(f"{k.split('#')[-1]} {v}" for k, v in list((cp.get("before") or {}).items())[:3])
        after = "、".join(f"{k.split('#')[-1]} {v}" for k, v in list((cp.get("after") or {}).items())[:3])
        lines.append(f"义项转变约 {int(cp['year'])} 年（p={cp['p']}）：之前 {before}；之后 {after}")
    witnesses = []
    cands = [c for c in r.get("candidate_senses", []) if isinstance(c, dict) and c.get("examples")]
    if cands:
        words = "、".join(d["token"] for d in cands[0].get("distinctive", [])[:6] if isinstance(d, dict))
        lines.append(f"候选新义（{cands[0].get('size')} 例，待人工判读）：{words}")
        ex = cands[0]["examples"][0]
        witnesses.append({"passage_id": ex.get("passage_id"), "locator": ex.get("period", ""),
                          "quote": (ex.get("quote") or ex.get("context", ""))[:200], "role": "候选新义例"})
    return {"lines": lines, "witnesses": witnesses}


def draft(ctx: Any) -> dict[str, Any]:
    dossiers = []
    for name, tid, kind in _targets(ctx):
        tool, args, build = {"formula": ("study.formula", {"name": name}, _formula), "herb": ("study.herb", {"name": name}, _herb),
                             "term": ("study.term", {"term": name}, _term)}[kind]
        outcome = ctx.try_tool(tool, **args)
        if not outcome.ok:
            continue
        dossier = build(name, outcome.result)
        if kind == "term":  # 语义演变: where the meaning shifted, and what the curated senses miss
            senses = ctx.try_tool("study.senses", term=name)
            if senses.ok:
                extra = _senses(senses.result)
                dossier["lines"] = list(dossier["lines"]) + extra["lines"]
                dossier["witnesses"] = list(dossier["witnesses"]) + extra["witnesses"]
        dossiers.append({"target": name, "term_id": tid, "kind": kind, **dossier})
    return {"dossiers": dossiers}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    n = 0
    for d in output.get("dossiers", []):
        witnesses = [w for w in d.get("witnesses", []) if corpus.has_passage(w.get("passage_id", ""))]
        if not witnesses:
            continue
        aid = stable_id("ana", "sources", d.get("kind"), d.get("target"))
        result = {"target": d["target"], "kind": d["kind"], "headline": d.get("headline", ""), "lines": list(d.get("lines", []))[:16],
                  "witnesses": witnesses}
        ctx.emit(EventType.ANALYSIS_RECORDED, {"analysis_id": aid, "target_id": d.get("term_id") or d["target"], "kind": "sources_dossier",
                                               "method": f"study.{d['kind']}", "round": ctx.task.round, "result": result},
                 generated=[aid])
        n += 1
    return f"{n} source dossiers"
