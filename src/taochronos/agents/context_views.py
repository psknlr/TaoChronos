"""Context views: what slice of the blackboard a model call sees.

Every view pins the Goal Anchor (the immutable research contract) and the
current task, then adds role-specific, itemised sections that the Context OS
can compact when the budget is tight.  Views read the ResearchObject; they
never see the raw event log or another agent's scratchpad.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from ..kernel.context import ContextSection
from ..kernel.memory import MemoryLayer
from ..protocol.research import ResearchObject, TaskNode


@dataclass
class ViewInput:
    state: ResearchObject
    task: TaskNode
    spec: Any
    capabilities: Any
    skills: Any = None
    memory: Any = None


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def goal_anchor(state: ResearchObject) -> ContextSection:
    g = state.goal
    if g is None:
        return ContextSection("Goal anchor", "(no goal contract)", priority=0, pinned=True)
    lines = [
        f"Question: {g.question}",
        f"Focus terms: {', '.join(g.focus_terms) or '(derived from the question)'}",
        f"Tracks: {', '.join(g.tracks)}",
        f"Temporal scope: {g.temporal_scope.label() if g.temporal_scope else 'all periods'}; time basis: {g.time_basis}",
    ]
    if g.holdout_after is not None:
        lines.append(f"Hold-out: texts dated ≥ {g.holdout_after} are hidden (Historical Time Machine)")
    if g.forbidden_assumptions:
        lines.append("Forbidden assumptions: " + "; ".join(g.forbidden_assumptions))
    lines.append(f"Required evidence: ≥{g.required_evidence.min_independent_sources} independent sources, verbatim quotes")
    lines.append(f"Required gates: {', '.join(g.required_validation)}")
    if g.success_criteria:
        lines.append("Success criteria: " + "; ".join(g.success_criteria))
    return ContextSection("Goal anchor (immutable contract)", "\n".join(lines), priority=0, pinned=True)


def task_section(task: TaskNode) -> ContextSection:
    body = f"Task {task.id}: {task.kind} (round {task.round})"
    if task.inputs:
        body += "\nInputs: " + _j(task.inputs)
    return ContextSection("Current task", body, priority=1, pinned=True)


def open_questions(state: ResearchObject) -> ContextSection:
    items = []
    for c in sorted(state.contradictions.values(), key=lambda c: c.id):
        if not c.resolved:
            items.append(f"[{c.id}] {c.label}/{c.type} on {c.subject} ({c.axis}): {c.explanation[:120]}")
    for h in sorted(state.hypotheses.values(), key=lambda h: h.id):
        if h.status == "needs_revision":
            items.append(f"[{h.id}] needs revision: {h.statement[:100]}")
    return ContextSection("Open questions", "", priority=20, items=items or ["(none)"])


def skills_section(inp: ViewInput) -> ContextSection | None:
    if inp.skills is None or not inp.spec.skills:
        return None
    return ContextSection("Skills", inp.skills.render(inp.spec.skills), priority=40)


def memory_section(inp: ViewInput, terms: list[str]) -> ContextSection | None:
    if inp.memory is None:
        return None
    items = [f"[{m.id}] {m.summary}" for m in inp.memory.recall(MemoryLayer.M3_DOMAIN, terms, k=6)]
    items += [f"[{m.id}] method: {m.summary}" for m in inp.memory.recall(MemoryLayer.M4_SKILL, terms, k=3)]
    return ContextSection("Established domain memory (expert-confirmed)", "", priority=45, items=items) if items else None


def _focus(inp: ViewInput) -> list[str]:
    g = inp.state.goal
    return list(g.focus_terms) if g else []


def passage_items(inp: ViewInput, passage_ids: list[str], limit: int = 40, full: bool = False) -> list[str]:
    corpus = inp.capabilities.get("corpus")
    out = []
    for pid in passage_ids[:limit]:
        if not corpus.has_passage(pid):
            continue
        p = corpus.passage(pid)
        book = corpus.book(p.book_id)
        text = p.text if full or len(p.text) <= 160 else p.text[:160] + "…"
        out.append(f"[{pid}] 《{book.title}》{p.locator.label()} ({book.dynasty}, {corpus.year(p)}): {text}")
    return out


def claim_items(state: ResearchObject, claim_ids: list[str], limit: int = 30) -> list[str]:
    out = []
    for cid in claim_ids[:limit]:
        c = state.claims.get(cid)
        if c is None:
            continue
        args = ", ".join(f"{a.role.value}={a.term_id or a.surface}{'(neg)' if a.negated else ''}" for a in c.arguments)
        out.append(f"[{cid}] {c.relation.value} @ {c.passage_id}: 「{c.quote}」 {{{args}}}")
    return out


def hypothesis_items(state: ResearchObject, hypotheses: list[Any], evidence_per: int = 4) -> list[str]:
    out = []
    for h in hypotheses:
        quotes = []
        for eid in h.supporting_evidence[:evidence_per]:
            e = state.evidence.get(eid)
            if e:
                quotes.append(f"{e.passage_id}「{e.quote[:60]}」")
        out.append(f"[{h.id}] ({h.kind}, gen{h.generation}, {h.status}) {h.statement}\n   support: {'; '.join(quotes) or '(none)'}"
                   + (f"\n   qualifiers: {_j(h.qualifiers)}" if h.qualifiers else ""))
    return out


# ------------------------------------------------------------------ views
def view_default(inp: ViewInput) -> list[ContextSection]:
    return [open_questions(inp.state)]


def view_director(inp: ViewInput) -> list[ContextSection]:
    from ..kernel.observability import research_metrics

    s = inp.state
    tasks = Counter(t.status for t in s.task_graph.values())
    sections = [
        ContextSection("Research metrics", _j({k: v for k, v in research_metrics(s).items() if k in (
            "round", "claims", "evidence_count", "counter_evidence", "observations", "contradictions", "hypotheses",
            "hypothesis_survival", "source_diversity", "gates")}), priority=10),
        ContextSection("Task graph", _j(dict(tasks)), priority=12),
        open_questions(s),
    ]
    meta = [a for a in s.analyses.values() if a.get("kind") == "meta_review"]
    if meta:
        latest = max(meta, key=lambda a: a.get("round", 0))
        recs = latest.get("result", {}).get("recommendations", [])
        sections.append(ContextSection("Meta-review recommendations", "", priority=11,
                                       items=[f"{r.get('action')} → {r.get('target', '')}: {r.get('reason', '')}" for r in recs]))
    leaders = sorted(s.active_hypotheses(), key=lambda h: (-h.elo, h.id))[:8]
    sections.append(ContextSection("Hypothesis leaderboard", "", priority=15, items=hypothesis_items(s, leaders, 2)))
    return sections


def view_philology(inp: ViewInput) -> list[ContextSection]:
    corpus = inp.capabilities.get("corpus")
    ids = [p for p in (inp.state.corpus.passage_ids if inp.state.corpus else corpus.passage_ids()) if corpus.passage(p).variants]
    return [ContextSection("Passages with recorded variants", "", priority=10, items=passage_items(inp, ids, full=True))]


def view_semantic(inp: ViewInput) -> list[ContextSection]:
    risky = [r for r in inp.state.term_resolutions.values() if r.homonym_risk]
    items = [f"[{r.id}] {r.surface} @ {r.passage_id}[{r.start}:{r.end}] → {r.sense_id} (p={r.probability}); alternatives {_j(r.alternatives)}"
             for r in sorted(risky, key=lambda r: r.id)]
    pack = inp.capabilities.get("domain")
    senses = []
    for term in sorted({r.term_id.split(':', 1)[-1] for r in risky}):
        ht = pack.terminology.term(term)
        if ht:
            senses += [f"{s.id}: {s.gloss} (period {s.period.label() if s.period else '?'}; cues {','.join(s.cues[:8])})" for s in ht.senses]
    return [ContextSection("Homonym-risk resolutions", "", priority=10, items=items or ["(none)"]),
            ContextSection("Curated senses", "", priority=12, items=senses)]


def view_extraction(inp: ViewInput) -> list[ContextSection]:
    covered = {c.passage_id for c in inp.state.claims.values()}
    scope = inp.state.corpus.passage_ids if inp.state.corpus else []
    bare = [p for p in scope if p not in covered]
    return [ContextSection("Passages without extracted claims", "", priority=10, items=passage_items(inp, bare, full=True))]


def view_terminology(inp: ViewInput) -> list[ContextSection]:
    pack = inp.capabilities.get("domain")
    items = [f"{c.id}: {c.label} ({c.category}, {c.space.value})" for c in pack.terminology.concepts.values()]
    return [ContextSection("Modern concepts (labels only — no mapping implied)", "", priority=20, items=items)]


def view_evidence(inp: ViewInput) -> list[ContextSection]:
    s = inp.state
    weak = [h for h in s.active_hypotheses() if s.gate_status(h.id, "G5") in ("warn", "fail", "pending")]
    return [ContextSection("Hypotheses needing independent sources", "", priority=10, items=hypothesis_items(s, weak) or ["(none)"])]


def view_hypothesis(inp: ViewInput) -> list[ContextSection]:
    s = inp.state
    used = {o for h in s.hypotheses.values() for o in h.observation_ids}
    items = []
    for o in sorted(s.observations.values(), key=lambda o: (-o.score, o.id)):
        if o.id in used:
            continue
        items.append(f"[{o.id}] ({o.kind}, score {o.score:.2f}) {o.title} — {o.summary} | stats {_j(o.statistics)} | claims {', '.join(o.claim_ids[:6])}")
    claim_ids = [c for o in s.observations.values() if o.id not in used for c in o.claim_ids[:4]]
    pack = inp.capabilities.get("domain")
    known = [f"{f.get('id')}: {f.get('statement', '')}" for f in pack.known_findings]
    sections = [ContextSection("New observations (from non-LLM miners)", "", priority=10, items=items or ["(none)"]),
                ContextSection("Claims behind the observations", "", priority=14, items=claim_items(s, claim_ids)),
                ContextSection("Existing understanding (for novelty)", "", priority=30, items=known)]
    revise = [h for h in s.hypotheses.values() if h.status == "needs_revision"]
    if revise:
        rev_items = hypothesis_items(s, revise)
        for h in revise:
            for r in s.reviews_for(h.id):
                rev_items += [f"   objection {o.id} [{o.severity}/{o.check}] {o.detail}" for o in r.unresolved()]
        sections.append(ContextSection("Hypotheses to revise", "", priority=8, items=rev_items))
    return sections


def view_skeptic(inp: ViewInput) -> list[ContextSection]:
    s = inp.state
    targets = [h for h in s.hypotheses.values() if h.status in ("proposed", "survived", "needs_revision")]
    contested = []
    for h in targets:
        for eid in h.supporting_evidence:
            e = s.evidence.get(eid)
            a = s.philology.get(e.passage_id) if e else None
            if a and a.contested_at(e.start, e.end):
                contested.append(f"{e.id} @ {e.passage_id}: contested reading inside the quote")
    return [ContextSection("Hypotheses under review", "", priority=10, items=hypothesis_items(s, targets, 6)),
            ContextSection("Philological risks in the evidence", "", priority=14, items=contested or ["(none)"]),
            open_questions(s)]


def view_meta(inp: ViewInput) -> list[ContextSection]:
    s = inp.state
    items = []
    for r in sorted(s.reviews.values(), key=lambda r: r.id):
        items.append(f"[{r.hypothesis_id}] {r.verdict}: " + "; ".join(f"{o.severity}/{o.check}{'✓' if o.resolved else ''}" for o in r.objections))
    scores = [f"[{h.id}] D={h.discovery_score} elo={h.elo:.0f} {h.status}" for h in sorted(s.hypotheses.values(), key=lambda h: (-h.elo, h.id))]
    return [ContextSection("Reviews", "", priority=10, items=items), ContextSection("Scores", "", priority=12, items=scores)]


VIEWS: dict[str, Callable[[ViewInput], list[ContextSection]]] = {
    "default": view_default,
    "director": view_director,
    "curation": view_default,
    "philology": view_philology,
    "semantic": view_semantic,
    "extraction": view_extraction,
    "terminology": view_terminology,
    "lineage": view_default,
    "evidence": view_evidence,
    "mining": view_default,
    "statistics": view_default,
    "evolution": view_default,
    "sources": view_default,
    "hypothesis": view_hypothesis,
    "skeptic": view_skeptic,
    "modern": view_evidence,
    "meta": view_meta,
}


def build_sections(name: str, inp: ViewInput) -> list[ContextSection]:
    sections = [goal_anchor(inp.state), task_section(inp.task)]
    sections += VIEWS.get(name, view_default)(inp)
    extra = [skills_section(inp), memory_section(inp, _focus(inp))]
    sections += [s for s in extra if s is not None]
    return sections
