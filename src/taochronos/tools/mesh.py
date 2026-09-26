"""The Tool Mesh: philology, retrieval, knowledge, analytics, literature and validation tools.

Tools *execute*; agents decide.  Each tool declares its family, permission and
scheduling metadata (read_only / parallel_safe / exclusive / expensive).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..kernel.tools import ToolContext, ToolRegistry, ToolSpec
from ..protocol.base import stable_id, to_jsonable
from ..protocol.claims import ClaimRelation, Role
from ..protocol.events import EventType
from ..protocol.research import ProposedChange
from ..science import (
    CooccurrenceGraph,
    association_rules,
    communities,
    concept_drift,
    find_contradictions,
    formula_families,
    infer_missing_sources,
    link_prediction,
    lost_knowledge,
)
from ..science.temporal import coverage
from ..verification.provenance import find_quote, provenance_chain
from .adapters import SenseOracle, author_clusters, binner, claim_year_fn, contradiction_context
from .common import claim_card, claims_in_scope, lineage_in_scope, passage_card, scope_ids, scope_passages

S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}


def obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


# ------------------------------------------------------------------ philology
def _normalize(ctx: ToolContext, a: dict) -> Any:
    out, applied = ctx.cap("philology").normalize(a["text"])
    return {"normalized": out, "normalizations": applied}


def _assess(ctx: ToolContext, a: dict) -> Any:
    return to_jsonable(ctx.cap("philology").assess(ctx.cap("corpus").passage(a["passage_id"])))


def _collate(ctx: ToolContext, a: dict) -> Any:
    corpus = ctx.cap("corpus")
    pa, pb = corpus.passage(a["passage_a"]), corpus.passage(a["passage_b"])
    return {"a": pa.id, "b": pb.id, "operations": ctx.cap("philology").collate(pa.text, pb.text)}


def _inspect(ctx: ToolContext, a: dict) -> Any:
    state = ctx.session.state if ctx.session is not None else None

    class _Empty:
        hypotheses: dict = {}
        evidence: dict = {}
        claims: dict = {}

    return provenance_chain(a["object_id"], state or _Empty(), ctx.cap("corpus"))


# ------------------------------------------------------------------ retrieval
def _search(ctx: ToolContext, a: dict) -> Any:
    retriever = ctx.cap("retriever")
    allowed = scope_ids(ctx)
    books = a.get("books")
    q, hits = retriever.search(
        a["query"], k=int(a.get("k", 10)), after=a.get("after"), before=a.get("before"), routes=a.get("routes"),
        books=books, allowed=allowed,
    )
    corpus = ctx.cap("corpus")
    if getattr(corpus, "large", False):
        ctx.cap("knowledge").touch(h.passage_id for h in hits)  # the working set of a session-less large corpus
    return {
        "query": {"terms": q.terms, "after": q.after, "before": q.before, "intent": q.intent,
                  "decomposition": q.decomposition, "variants": q.variants},
        "hits": [
            {**passage_card(ctx, corpus.passage(h.passage_id)), "score": h.score, "routes": sorted(h.routes), "matched": h.matched,
             "note": h.note}
            for h in hits
        ],
        "timeline": retriever.timeline(hits),
    }


def _get_passage(ctx: ToolContext, a: dict) -> Any:
    allowed = scope_ids(ctx)
    if allowed is not None and a["passage_id"] not in allowed:
        raise PermissionError(f"passage {a['passage_id']} is outside the research scope (e.g. temporal hold-out)")
    return passage_card(ctx, ctx.cap("corpus").passage(a["passage_id"]), full=True)


def _list_books(ctx: ToolContext, a: dict) -> Any:
    corpus = ctx.cap("corpus")
    counts = Counter(p.book_id for p in scope_passages(ctx))
    out = []
    for book in corpus.books.values():
        if counts.get(book.id):
            out.append({"book_id": book.id, "title": book.title, "dynasty": book.dynasty,
                        "composition": book.composition.label() if book.composition else None,
                        "category": book.category, "attribution": book.attribution, "passages": counts[book.id]})
    return sorted(out, key=lambda b: (b["composition"] or "", b["book_id"]))


def _lineage(ctx: ToolContext, a: dict) -> Any:
    subject = a.get("subject")
    edges = lineage_in_scope(ctx)
    if subject:
        edges = [e for e in edges if subject in (e.source_id, e.target_id, e.source_passage, e.target_passage)]
    return [to_jsonable(e) for e in edges[: int(a.get("limit", 50))]]


# ------------------------------------------------------------------ knowledge
def _extract(ctx: ToolContext, a: dict) -> Any:
    corpus = ctx.cap("corpus")
    passage = corpus.passage(a["passage_id"])
    allowed = scope_ids(ctx)
    if allowed is not None and passage.id not in allowed:
        raise PermissionError("passage outside research scope")
    claims = ctx.cap("extractor").extract(passage, ctx.cap("philology").assess(passage))
    return [to_jsonable(c) for c in claims]


def _claims(ctx: ToolContext, a: dict) -> Any:
    lex = ctx.cap("domain").lexicon
    wanted = [t if ":" in t else (lex.canonical(t) or t) for t in a.get("terms", [])]
    relation = a.get("relation")
    year = claim_year_fn(ctx.cap("corpus"))
    out = []
    for c in claims_in_scope(ctx):
        members = {x.term_id for x in c.arguments if x.term_id}
        if wanted and not set(wanted) & members:
            continue
        if relation and c.relation.value != relation:
            continue
        y = year(c)
        if a.get("after") is not None and (y is None or y < a["after"]):
            continue
        if a.get("before") is not None and (y is None or y >= a["before"]):
            continue
        out.append({**claim_card(c), "year": y, "book_id": c.book_id})
    out.sort(key=lambda c: (c["year"] or 0, c["claim_id"]))
    return out[: int(a.get("limit", 50))]


def _neighbors(ctx: ToolContext, a: dict) -> Any:
    lex = ctx.cap("domain").lexicon
    term = a["term"] if ":" in a["term"] else (lex.canonical(a["term"]) or a["term"])
    counts: Counter = Counter()
    for c in claims_in_scope(ctx):
        members = [x.term_id for x in c.arguments if x.term_id and not x.negated]
        if term in members:
            counts.update(m for m in members if m != term)
    return [{"term": t, "weight": n} for t, n in counts.most_common(int(a.get("k", 15)))]


def _term(ctx: ToolContext, a: dict) -> Any:
    pack = ctx.cap("domain")
    surface = a["surface"]
    entries = pack.lexicon.lookup(surface) or ([(pack.lexicon.entry(surface), None)] if pack.lexicon.entry(surface) else [])
    hist = pack.terminology.term(surface.split(":", 1)[-1])
    out: dict[str, Any] = {
        "lexicon": [{"term_id": e.term_id, "category": e.category, "aliases": e.aliases, "synonyms": e.synonyms,
                     "polarity": e.polarity, "components": e.components, "broader": e.broader, "related": e.related}
                    for e, _ in entries if e],
    }
    if hist:
        out["senses"] = [
            {"sense_id": s.id, "label": s.label, "category": s.category, "period": s.period.label() if s.period else None,
             "scope": pack.terminology.sense_meta.get(s.id, {}).get("scope"),
             "candidates": pack.terminology.sense_meta.get(s.id, {}).get("candidates", [])}
            for s in hist.senses
        ]
        out["notes"] = hist.notes
    return out


def _propose_change(ctx: ToolContext, a: dict) -> Any:
    change = ProposedChange(
        id=stable_id("chg", a["target"], a["op"], a["payload"], ctx.actor.id),
        target=a["target"],
        op=a["op"],
        payload=a["payload"],
        rationale=a.get("rationale", ""),
        proposer=ctx.actor.id,
        evidence_ids=list(a.get("evidence_ids", [])),
    )
    ctx.emit(EventType.CHANGE_PROPOSED, {"change": change.to_dict()}, generated=[change.id])
    return {"change_id": change.id, "status": "proposed", "note": "canonical knowledge changes require validator or human approval"}


# ------------------------------------------------------------------ analytics
def _family(ctx: ToolContext, term: str) -> set[str]:
    lex = ctx.cap("domain").lexicon
    tid = term if ":" in term else (lex.canonical(term) or term)
    surface = tid.split(":", 1)[-1]
    fam = {tid}
    if len(surface) == 1:
        for e in lex.entries.values():
            if surface in e.term and len(e.term) <= 3 and e.category in ("pathogenesis", "etiology", "disease", "pattern"):
                fam.add(e.term_id)
    return fam


def _drift(ctx: ToolContext, a: dict) -> Any:
    pack, corpus = ctx.cap("domain"), ctx.cap("corpus")
    fam = _family(ctx, a["term"]) if a.get("family", True) else {a["term"]}
    resolutions = ctx.session.state.term_resolutions if ctx.session is not None else None
    return concept_drift(fam, claims_in_scope(ctx), claim_year_fn(corpus), binner(pack),
                         sense_fn=SenseOracle(pack, corpus, resolutions), seed=int(a.get("seed", 0)),
                         n_permutations=int(a.get("permutations", 499)))


def _lost(ctx: ToolContext, a: dict) -> Any:
    pack, corpus = ctx.cap("domain"), ctx.cap("corpus")
    components = {e.term_id: [t for t in (pack.lexicon.canonical(c) for c in e.components) if t]
                  for e in pack.lexicon.entries.values() if e.components}
    return lost_knowledge(claims_in_scope(ctx), claim_year_fn(corpus), binner(pack), pivot_year=a.get("pivot_year", 960),
                          cluster_of=author_clusters(corpus, lineage_in_scope(ctx)), components=components)


def _formula_evolution(ctx: ToolContext, a: dict) -> Any:
    claims = claims_in_scope(ctx)
    profiles = ctx.cap("lineage").formula_profiles(claims, claims)
    year = claim_year_fn(ctx.cap("corpus"))
    indications: dict[str, list] = {}
    for c in claims:
        if c.relation == ClaimRelation.INDICATED_FOR:
            for f in c.args(Role.FORMULA):
                indications.setdefault(f.term_id, []).append(
                    (year(c), [x.term_id for x in c.arguments if x.term_id and x.role in (Role.SYMPTOM, Role.SIGN, Role.DISEASE, Role.PATTERN)]))
    return {"families": formula_families(profiles, lineage_in_scope(ctx), indications),
            "profiles": [{"formula": p.formula_id, "herbs": p.herbs, "year": p.year, "source": p.source, "passage": p.passage_id} for p in profiles]}


def _prefix_filter(prefixes: list[str]):
    return lambda t: any(t.startswith(p) for p in prefixes)


def _rules(ctx: ToolContext, a: dict) -> Any:
    tx = [(c.id, [x.term_id for x in c.arguments if x.term_id and not x.negated])
          for c in claims_in_scope(ctx) if c.relation == ClaimRelation.INDICATED_FOR]
    return association_rules(tx, lhs=_prefix_filter(a.get("lhs", ["symptom:", "sign:", "pulse:", "tongue:"])),
                             rhs=_prefix_filter(a.get("rhs", ["formula:"])), min_support=int(a.get("min_support", 2)),
                             min_confidence=float(a.get("min_confidence", 0.5)))


GRAPH_RELATIONS = (ClaimRelation.INDICATED_FOR, ClaimRelation.HERB_INDICATION, ClaimRelation.COMPOSED_OF)


def _graph(ctx: ToolContext, before: float | None = None, after: float | None = None) -> CooccurrenceGraph:
    """Clique expansion of *positive* hyperedges only: a contraindication is not an association."""
    year = claim_year_fn(ctx.cap("corpus"))
    edges = []
    for c in claims_in_scope(ctx):
        if c.relation not in GRAPH_RELATIONS:
            continue
        y = year(c)
        if before is not None and (y is None or y >= before):
            continue
        if after is not None and (y is None or y < after):
            continue
        edges.append([x.term_id for x in c.arguments if x.term_id and not x.negated and not x.qualifiers.get("outcome")])
    return CooccurrenceGraph(edges)


def _link_prediction(ctx: ToolContext, a: dict) -> Any:
    g = _graph(ctx, before=a.get("before"))
    return link_prediction(g, left=_prefix_filter(a.get("left", ["symptom:", "disease:", "pattern:"])),
                           right=_prefix_filter(a.get("right", ["formula:", "herb:"])), method=a.get("method", "adamic_adar"),
                           k=int(a.get("k", 20)), seed=int(a.get("seed", 0)))


def _communities(ctx: ToolContext, a: dict) -> Any:
    return communities(_graph(ctx), min_weight=int(a.get("min_weight", 1)))[: int(a.get("limit", 12))]


def _contradictions(ctx: ToolContext, a: dict) -> Any:
    pack, corpus = ctx.cap("domain"), ctx.cap("corpus")
    resolutions = ctx.session.state.term_resolutions if ctx.session is not None else None
    cctx = contradiction_context(pack, corpus, ctx.cap("philology"), resolutions, lineage_in_scope(ctx))
    return [to_jsonable(c) for c in find_contradictions(claims_in_scope(ctx), cctx)]


def _missing_sources(ctx: ToolContext, a: dict) -> Any:
    corpus = ctx.cap("corpus")
    present = {p.book_id for p in scope_passages(ctx)}
    if getattr(corpus, "large", False):
        # the frame only samples passages: a cited book that is in the store counts as present unless the research
        # contract excluded it on purpose (held out to be rediscovered)
        state = ctx.session.state if ctx.session is not None else None
        withheld = set(state.goal.corpus.exclude_books) if state is not None and state.goal is not None else set()
        present |= {b for b in corpus.books if b not in withheld}
    aliases = {w.id: [w.title, *w.aliases] for w in corpus.external.values()}
    for b in corpus.books.values():
        aliases.setdefault(b.id, [b.title, *b.aliases])
    edges = lineage_in_scope(ctx)
    return infer_missing_sources(edges, present, aliases=aliases,
                                 year_of_passage=lambda pid: corpus.year(corpus.passage(pid)) if corpus.has_passage(pid) else None)


def _temporal_profile(ctx: ToolContext, a: dict) -> Any:
    pack, corpus = ctx.cap("domain"), ctx.cap("corpus")
    b = binner(pack)
    fam = _family(ctx, a["term"])
    year = claim_year_fn(corpus)
    counts: Counter = Counter()
    books: dict[str, set] = {}
    for c in claims_in_scope(ctx):
        if fam & {x.term_id for x in c.arguments if x.term_id and not x.negated}:
            period = b.of(year(c))
            counts[period] += 1
            books.setdefault(period, set()).add(c.book_id)
    cov = coverage((corpus.year(p) for p in scope_passages(ctx)), b)
    return {"term": sorted(fam), "claims_by_period": {p: counts.get(p, 0) for p in b.ids()},
            "books_by_period": {p: sorted(books.get(p, [])) for p in b.ids()}, "corpus_passages_by_period": cov}


# ------------------------------------------------------------------ literature
def _modern_evidence(ctx: ToolContext, a: dict) -> Any:
    records = ctx.services.get("modern_evidence", [])
    concept, term = a.get("concept_id"), a.get("term")
    return [r for r in records if (not concept or r.get("concept_id") == concept) and (not term or term in r.get("related_terms", []))]


# ------------------------------------------------------------------ validation
def _verify_quote(ctx: ToolContext, a: dict) -> Any:
    pack = ctx.cap("domain")
    hits = find_quote(ctx.cap("corpus"), a["quote"], pack.variants.normalize_text, a.get("passage_id"))
    allowed = scope_ids(ctx)
    return [{"passage_id": p, "start": s, "end": e} for p, s, e in hits if allowed is None or p in allowed]


def _gates(ctx: ToolContext, a: dict) -> Any:
    factory = ctx.services.get("gates")
    if factory is None or ctx.session is None:
        raise RuntimeError("gate evaluation requires a research session")
    gates = factory(ctx.session.state)
    state = ctx.session.state
    sid = a["subject_id"]
    if sid in state.claims:
        results = gates.evaluate_claim(state.claims[sid])
    elif sid in state.evidence:
        results = gates.evaluate_evidence(state.evidence[sid])
    elif sid in state.hypotheses:
        results = gates.evaluate_hypothesis(state.hypotheses[sid], state)
    else:
        raise KeyError(f"unknown subject {sid}")
    return [to_jsonable(r) for r in results]


# ------------------------------------------------------------------ study (治学)
def _study(ctx: ToolContext) -> Any:
    try:
        return ctx.cap("study")
    except KeyError as exc:  # pragma: no cover - every classics bundle registers it
        raise KeyError("no 'study' capability is registered (the classics plugin provides it)") from exc


def _brief(value: Any, items: int = 12, chars: int = 240) -> Any:
    """Keep tool results small for agent context: long lists are cut (with the count left out), long strings shortened,
    bulky keys (member lists, Anki text, per-field quotes) dropped.  The full results are in the CLI and the datasets."""
    if isinstance(value, dict):
        return {k: _brief(v, items, chars) for k, v in value.items() if k not in ("member_ids", "anki_tsv", "quotes")}
    if isinstance(value, list):
        out = [_brief(v, items, chars) for v in value[:items]]
        return out + ([{"omitted": len(value) - items}] if len(value) > items else [])
    if isinstance(value, str) and len(value) > chars:
        return value[:chars] + "…"
    return value


def _study_concordance(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).concordance(a.get("text"), a.get("passage_id"), min_coverage=float(a.get("min_coverage", 0.6)),
                                  limit=int(a.get("limit", 120)))
    return _brief(res, int(a.get("items", 20)))


def _study_formula(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).formula(a["name"], other_names=bool(a.get("other_names", True))), int(a.get("items", 12)))


def _study_herb(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).herb(a["name"]), int(a.get("items", 16)))


def _study_term(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).term(a["term"], sample_per_period=int(a.get("sample_per_period", 200))), int(a.get("items", 12)))


def _study_taboo(ctx: ToolContext, a: dict[str, Any]) -> Any:
    study = _study(ctx)
    res = study.taboo(a["book_id"]) if a.get("book_id") else study.taboo(min_chars=int(a.get("min_chars", 20000)))
    return _brief(res, int(a.get("items", 20)))


def _study_citations(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).citations(a.get("target"), **({} if a.get("target") else {"top": int(a.get("top", 12))})),
                  int(a.get("items", 12)))


def _study_metrology(ctx: ToolContext, a: dict[str, Any]) -> Any:
    m = _study(ctx).metrology
    return {"dose": a["dose"], "year": a.get("year"), "parsed": m.parse(a["dose"]), "reading": m.convert(a["dose"], a.get("year")),
            "notice": m.notice}


def _study_cards(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).cards(book=a.get("book"), formulas=list(a.get("formulas") or []), herbs=list(a.get("herbs") or []),
                            term=a.get("term"), limit=int(a.get("limit", 30)))
    return _brief(res, int(a.get("items", 40)))


def _study_reading(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).reading(a["topic"]), int(a.get("items", 10)))


def _collation_kw(a: dict[str, Any]) -> dict[str, Any]:
    kw = {k: a[k] for k in ("books", "base", "chapter") if a.get(k)}
    if a.get("max_chars"):
        kw["max_chars"] = int(a["max_chars"])
    return kw


def _study_variants(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).variants(a.get("work"), text=a.get("text"), passage_id=a.get("passage_id"), **_collation_kw(a))
    return _brief(res, int(a.get("items", 20)))


def _study_stemma(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).stemma(a.get("work"), root_at=a.get("root_at"), **_collation_kw(a))
    return _brief({k: v for k, v in res.items() if k != "units"}, int(a.get("items", 20)), chars=1600)


def _study_reuse(ctx: ToolContext, a: dict[str, Any]) -> Any:
    study = _study(ctx)
    if a.get("target") or a.get("target_id"):
        return _brief(study.reuse_pair(a.get("text"), a.get("target"), source_id=a.get("passage_id"),
                                       target_id=a.get("target_id")), int(a.get("items", 20)))
    res = study.reuse(a.get("text"), a.get("passage_id"), semantic=bool(a.get("semantic", True)),
                      max_candidates=int(a.get("max_candidates", 800)), limit=int(a.get("limit", 200)))
    return _brief(res, int(a.get("items", 20)))


def _study_transmission(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).transmission(a["work"], clauses=int(a.get("clauses", 30)), max_candidates=int(a.get("max_candidates", 400)))
    return _brief(res, int(a.get("items", 20)))


def _study_layers(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).layers(a.get("work"), books=a.get("books"), k=int(a.get("k", 2)), features=a.get("features", "frequent"))
    return _brief({k: v for k, v in res.items() if k not in ("segments", "feature_names")}, int(a.get("items", 20)))


def _study_dating(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).dating(a.get("work"), books=a.get("books"))
    return _brief({k: v for k, v in res.items() if k != "chapters"}, int(a.get("items", 20)))


def _study_authorship(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).authorship(a.get("text"), book=a.get("book"), chapter=a.get("chapter"), candidates=a.get("candidates"))
    return _brief(res, int(a.get("items", 20)))


def _study_cases(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).cases(a.get("book"), disease=a.get("disease"), limit=int(a.get("limit", 40)))
    return _brief(res, int(a.get("items", 12)))


def _study_trajectories(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).trajectories(a.get("disease"), book=a.get("book"), limit=int(a.get("limit", 600)))
    return _brief({k: v for k, v in res.items() if k != "examples"}, int(a.get("items", 15)))


def _study_argument(ctx: ToolContext, a: dict[str, Any]) -> Any:
    study = _study(ctx)
    if a.get("work"):
        res = study.argument(work=a["work"], against=a.get("against"))
    else:
        res = study.argument(a.get("text"), a.get("passage_id"))
    return _brief(res, int(a.get("items", 15)))


def _study_senses(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).senses(a["term"], per_period=int(a.get("per_period", 250))), int(a.get("items", 12)))


def _study_fragments(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).fragments(a["work"], verify_against=["*"] if a.get("verify") else None)
    return _brief(res, int(a.get("items", 20)))


def _study_witnesses(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).witnesses(a["work"]), int(a.get("items", 20)))


def _study_punctuate(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).punctuate(a.get("text"), a.get("passage_id"))
    res.pop("marks", None)
    res["model"] = {k: v for k, v in res.get("model", {}).items() if k != "held_out"}
    return _brief(res, int(a.get("items", 12)), chars=int(a.get("chars", 1200)))


def _study_commentaries(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).commentaries(a.get("text"), a.get("passage_id"))
    for u in res.get("commentaries", []):
        for key in ("concepts", "lemma", "text"):
            u.pop(key, None)
    return _brief(res, int(a.get("items", 15)))


def _study_disputes(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).disputes(a.get("term"), person=a.get("person")), int(a.get("items", 15)))


def _study_clause(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).clause(a.get("text"), a.get("passage_id"), work=a.get("work")), int(a.get("items", 30)))


def _study_glosses(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).glosses(a.get("term"), book=a.get("book")), int(a.get("items", 15)))


def _study_pairs(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).pairs(a.get("herb"), period=a.get("period")), int(a.get("items", 20)))


def _study_network(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).network(a.get("target")), int(a.get("items", 20)))


def build_tool_registry(extra: list[ToolSpec] | None = None) -> ToolRegistry:
    reg = ToolRegistry()
    specs = [
        ToolSpec("philology.normalize", "Normalise variant characters (异体字/通假) for matching; the original text is never altered.",
                 obj({"text": S}, ["text"]), _normalize, family="philology", permission="classics:read"),
        ToolSpec("philology.assess_passage", "Philological assessment of a passage: normalisations, contested spans with reading probabilities, collation status, confidence.",
                 obj({"passage_id": S}, ["passage_id"]), _assess, family="philology", permission="classics:read"),
        ToolSpec("philology.collate", "Character-level collation (校勘) of two passages.",
                 obj({"passage_a": S, "passage_b": S}, ["passage_a", "passage_b"]), _collate, family="philology", permission="classics:read"),
        ToolSpec("philology.inspect_page", "Resolve the provenance chain of a hypothesis/evidence/claim/passage down to page and image (Claim→Pixel).",
                 obj({"object_id": S}, ["object_id"]), _inspect, family="philology", permission="classics:read"),
        ToolSpec("classics.search", "Philology-aware temporal GraphRAG search over the classics (7 fused routes). Accepts natural-language questions with period constraints (e.g. 宋代以前).",
                 obj({"query": S, "k": I, "after": N, "before": N, "routes": {"type": "array", "items": S}, "books": {"type": "array", "items": S}}, ["query"]),
                 _search, family="retrieval", permission="classics:read", returns="hits with passage ids, periods, routes and matched surfaces"),
        ToolSpec("classics.get_passage", "Full passage with locator, variants, temporal context and notes.",
                 obj({"passage_id": S}, ["passage_id"]), _get_passage, family="retrieval", permission="classics:read"),
        ToolSpec("classics.list_books", "Books in research scope with dates, attribution and passage counts.",
                 obj({}), _list_books, family="retrieval", permission="classics:read"),
        ToolSpec("classics.lineage", "Knowledge-lineage edges (cites / transcribes / rephrases / opposes / formula_derived_from / inherits).",
                 obj({"subject": S, "limit": I}), _lineage, family="retrieval", permission="classics:read"),
        ToolSpec("kg.extract_claims", "Extract hyperedge claims from a passage (lexicon + pattern rules); returns candidates, commits nothing.",
                 obj({"passage_id": S}, ["passage_id"]), _extract, family="knowledge", permission="kg:read"),
        ToolSpec("kg.claims", "Query committed claims by terms, relation and period.",
                 obj({"terms": {"type": "array", "items": S}, "relation": S, "after": N, "before": N, "limit": I}),
                 _claims, family="knowledge", permission="kg:read"),
        ToolSpec("kg.neighbors", "Terms co-occurring with a term inside claim hyperedges.",
                 obj({"term": S, "k": I}, ["term"]), _neighbors, family="knowledge", permission="kg:read"),
        ToolSpec("kg.term", "Lexicon entry, synonyms (避讳/异名), components and period-bound senses of a historical term.",
                 obj({"surface": S}, ["surface"]), _term, family="knowledge", permission="kg:read"),
        ToolSpec("kg.propose_change", "Propose a change to canonical knowledge (terminology/ontology/gold/memory). Never commits.",
                 obj({"target": S, "op": S, "payload": {"type": "object"}, "rationale": S, "evidence_ids": {"type": "array", "items": S}}, ["target", "op", "payload"]),
                 _propose_change, family="knowledge", permission="kg:propose", read_only=False, parallel_safe=False, exclusive=True),
        ToolSpec("analysis.concept_drift", "D2 concept evolution of a term (family) across periods: JSD series, permutation p-values, sense shifts.",
                 obj({"term": S, "family": {"type": "boolean"}, "seed": I, "permutations": I}, ["term"]), _drift,
                 family="analytics", permission="analysis:run"),
        ToolSpec("analysis.lost_knowledge", "D1 associations attested early that vanish later while their concepts persist; plus historical testimony.",
                 obj({"pivot_year": N}), _lost, family="analytics", permission="analysis:run"),
        ToolSpec("analysis.formula_evolution", "D3 formula families: derivation trees, stable cores, added/removed herbs, renames.",
                 obj({}), _formula_evolution, family="analytics", permission="analysis:run"),
        ToolSpec("analysis.association_rules", "D4 association rules from findings to formulas with support/confidence/lift/Fisher p.",
                 obj({"lhs": {"type": "array", "items": S}, "rhs": {"type": "array", "items": S}, "min_support": I, "min_confidence": N}),
                 _rules, family="analytics", permission="analysis:run"),
        ToolSpec("analysis.link_prediction", "D4 hidden associations: unlinked pairs ranked by Adamic–Adar (or other methods) with explanatory paths.",
                 obj({"left": {"type": "array", "items": S}, "right": {"type": "array", "items": S}, "method": S, "k": I, "before": N, "seed": I}),
                 _link_prediction, family="analytics", permission="analysis:run"),
        ToolSpec("analysis.communities", "Symptom–pattern–formula communities (deterministic label propagation).",
                 obj({"min_weight": I, "limit": I}), _communities, family="analytics", permission="analysis:run"),
        ToolSpec("analysis.contradictions", "D5 contradiction discovery with labels (contradiction/conditional/apparent) and candidate explanations.",
                 obj({}), _contradictions, family="analytics", permission="analysis:run", expensive=True),
        ToolSpec("analysis.missing_sources", "Source rediscovery: cited works absent from the corpus, with date bounds.",
                 obj({}), _missing_sources, family="analytics", permission="analysis:run"),
        ToolSpec("analysis.temporal_profile", "Claims per period for a term family, with corpus coverage (sample-size check).",
                 obj({"term": S}, ["term"]), _temporal_profile, family="analytics", permission="analysis:run"),
        ToolSpec("literature.modern_evidence", "Modern evidence records (Biomedical Space) for a concept or term.",
                 obj({"concept_id": S, "term": S}), _modern_evidence, family="literature", permission="literature:read"),
        ToolSpec("study.concordance", "经文互见·集注: where a passage (or a text) recurs in the corpus — other copies of its work (同书异本), "
                 "quotations (引文) and restatements (互见) — in date order, with a collation apparatus (异文/脱/衍/倒) by witness.",
                 obj({"text": S, "passage_id": S, "min_coverage": N, "limit": I, "items": I}), _study_concordance,
                 family="study", permission="classics:read", expensive=True,
                 returns="base witness, hits (relation, coverage, locator, quote), apparatus, summary by period"),
        ToolSpec("study.formula", "方源考: every written-out composition of a formula in date order; 原方 (earliest) and 通行方 (most witnessed), "
                 "加减化裁, 同名异方, 同方异名, dose ratios, doses read in the measures of their period (not dosage guidance), 方歌.",
                 obj({"name": S, "other_names": {"type": "boolean"}, "items": I}, ["name"]), _study_formula,
                 family="study", permission="classics:read", returns="groups, earliest witness, indications, modifications, ratios, songs"),
        ToolSpec("study.herb", "药性源流: flavour, nature, toxicity, channels (归经), direction and indications of a drug, work by work, "
                 "with the first statement of each value.",
                 obj({"name": S, "items": I}, ["name"]), _study_herb, family="study", permission="classics:read",
                 returns="entries with locators and quotes, firsts, periods"),
        ToolSpec("study.term", "术语源流: share of passages using a term by period (Wilson intervals, trend test), first attestations, "
                 "collocates by period, where to read, and period-bound senses with candidate (never equivalent) modern concepts.",
                 obj({"term": S, "sample_per_period": I, "items": I}, ["term"]), _study_term, family="study", permission="classics:read"),
        ToolSpec("study.taboo", "避讳断代: taboo characters a book avoids and the edition date they imply (one book), or a survey of the store.",
                 obj({"book_id": S, "min_chars": I, "items": I}), _study_taboo, family="study", permission="classics:read"),
        ToolSpec("study.citations", "引书与引人: works and physicians each period cites (self-citation and copies excluded), their lineage; "
                 "with a target, the reception of one work or physician by period.",
                 obj({"target": S, "top": I, "items": I}), _study_citations, family="study", permission="classics:read", expensive=True),
        ToolSpec("study.metrology", "历代度量衡: read a written dose (三两, 半升, 方寸匕) in the measures of a year — a historical reading, "
                 "never dosage guidance.",
                 obj({"dose": S, "year": N}, ["dose"]), _study_metrology, family="study", permission="classics:read"),
        ToolSpec("study.cards", "学习卡片: cloze cards (方证, 组成, 药性, 经文) made from the verbatim classics, each with its source.",
                 obj({"book": S, "formulas": {"type": "array", "items": S}, "herbs": {"type": "array", "items": S}, "term": S,
                      "limit": I, "items": I}), _study_cards, family="study", permission="classics:read"),
        ToolSpec("study.reading", "阅读门径: the works to read on a topic — first attestations, the densest treatments by period, "
                 "monographs, case records, Republican syntheses — each with the reason.",
                 obj({"topic": S, "items": I}, ["topic"]), _study_reading, family="study", permission="classics:read"),
        ToolSpec("study.variants", "版本谱系·异文: collate the witnesses of a work (or a passage's copies and quotations with text / passage_id): "
                 "variant units (substitution, omission, addition, transposition; orthographic ones apart), lacunae, "
                 "frequent substitutions (spelling conventions to review).",
                 obj({"work": S, "text": S, "passage_id": S, "books": {"type": "array", "items": S}, "base": S, "chapter": S,
                      "max_chars": I, "items": I}), _study_variants, family="study", permission="classics:read", expensive=True,
                 returns="witnesses with coverage, lacunae and singular readings; summary by kind; units"),
        ToolSpec("study.stemma", "版本谱系·谱系图: distances between the witnesses, a neighbour-joining stemma (Newick and a tree), groups "
                 "of shared readings, agreement patterns, contamination (which witness also copied another branch), "
                 "each witness's taboo-based edition date floor.",
                 obj({"work": S, "books": {"type": "array", "items": S}, "base": S, "chapter": S, "max_chars": I, "root_at": S,
                      "items": I}), _study_stemma, family="study", permission="classics:read", expensive=True,
                 returns="distances, tree, newick, ascii, groups, patterns, contamination, conflicts"),
        ToolSpec("study.reuse", "语义复用: how later books reuse a passage — candidates from shared wording and co-occurring concepts, "
                 "each typed by transparent rules (直接引用 near_verbatim 节略 撮要 转述 解释性改写 引而驳之 套语相似) with its "
                 "features; with target / target_id, the type of one pair.  Candidates prove nothing; the rule and features "
                 "are given with every label.",
                 obj({"text": S, "passage_id": S, "target": S, "target_id": S, "semantic": {"type": "boolean"},
                      "max_candidates": I, "limit": I, "items": I}), _study_reuse, family="study", permission="classics:read",
                 expensive=True, returns="hits (label, rule, features, citation 明引/暗引, relation, direction), summary by label and period"),
        ToolSpec("study.transmission", "思想传播: a work's reception — its clauses' typed reuse in later works, the balance of retained / "
                 "transformed / disputed reuse by period, and the channels (later works that follow an intermediate work's "
                 "wording rather than the source's).",
                 obj({"work": S, "clauses": I, "max_candidates": I, "items": I}, ["work"]), _study_transmission,
                 family="study", permission="classics:read", expensive=True,
                 returns="works with their reuse types, periods, channels, first work of each type"),
        ToolSpec("study.layers", "文本地层: style layers of a work's chapters (most frequent characters, or function characters), "
                 "the split tested by permutation, membership probabilities, layer boundaries and change points in reading "
                 "order, chapters that stand apart (Burrows' Delta).  Style shows that chapters differ, not when or by whom.",
                 obj({"work": S, "books": {"type": "array", "items": S}, "k": I, "features": S, "items": I}), _study_layers,
                 family="study", permission="classics:read", expensive=True,
                 returns="layers with chapters and distinctive features, boundaries, change points, outliers"),
        ToolSpec("study.dating", "断代证据: chapter by chapter, the works cited in the main text (terminus post quem), vocabulary the "
                 "rest of the corpus attests only long after the work's date (where unusually frequent), the taboo "
                 "characters of the witness (its edition).",
                 obj({"work": S, "books": {"type": "array", "items": S}, "items": I}), _study_dating, family="study",
                 permission="classics:read", expensive=True, returns="chapters later than the nominal date with their evidence"),
        ToolSpec("study.authorship", "作者归属: Burrows' Delta of a text (or a book, or one of its chapters) against candidate works.",
                 obj({"text": S, "book": S, "chapter": S, "candidates": {"type": "array", "items": S}, "items": I}),
                 _study_authorship, family="study", permission="classics:read", expensive=True,
                 returns="candidates ranked by delta with the margin to the next"),
        ToolSpec("study.cases", "医案: case records read visit by visit — findings (symptoms, pulse, tongue), diagnosis, principle, "
                 "formula and drugs with doses, 加减 against the last prescription, doses taken, response, outcome — of one "
                 "book or filed under a disease across the case collections.",
                 obj({"book": S, "disease": S, "limit": I, "items": I}), _study_cases, family="study", permission="classics:read",
                 expensive=True, returns="cases with patient, visits and outcome; outcome counts"),
        ToolSpec("study.trajectories", "医案轨迹: across case records of a disease (or a book), the sequences of principles, formulas "
                 "and added drugs common to many cases, what the next visit holds given this one, and the choices associated "
                 "with recovery in the record (associations in a selected record, never evidence of efficacy).",
                 obj({"disease": S, "book": S, "limit": I, "items": I}), _study_trajectories, family="study",
                 permission="classics:read", expensive=True, returns="patterns, transitions, outcome associations"),
        ToolSpec("study.argument", "医理论证: the reasoning of a passage as a graph of clauses (with their concepts) and the steps its "
                 "discourse markers state (条件, 则, 故, 因, 所致, 主之, 界说, 转折, 取象比类, 驳斥, 盖); with work, a work's way of "
                 "reasoning (relations per 1 000 clauses, concept triples, chains); with work and against, two works compared.",
                 obj({"text": S, "passage_id": S, "work": S, "against": S, "items": I}), _study_argument, family="study",
                 permission="classics:read", expensive=True, returns="clauses and edges; or a profile; or a comparison"),
        ToolSpec("study.senses", "语义演变: a term's curated senses by period (from their cue words), the date the sense shares shifted "
                 "(permutation test), candidate senses the curation lacks (clusters of unlabelled contexts, for a person to "
                 "read), and the term's context neighbourhood period by period.",
                 obj({"term": S, "per_period": I, "items": I}, ["term"]), _study_senses, family="study", permission="classics:read",
                 expensive=True, returns="series, change point, candidate senses, neighbourhood, exemplar check"),
        ToolSpec("study.witnesses", "版本与影像见证: every witness of a work — its transcriptions in the store (edition, date, holder, "
                 "licence, whether passages link their page image) and the digitised copies in libraries (NIJL, Berlin, LoC, "
                 "早稲田, NDL: holder, date, shelfmark, IIIF manifest, terms of use), linked by title (check `match`).",
                 obj({"work": S, "items": I}, ["work"]), _study_witnesses, family="study", permission="classics:read",
                 returns="text witnesses; image witnesses with manifests and rights"),
        ToolSpec("study.fragments", "佚书辑佚: a lost work's fragments gathered from the books that quote it (entries opened by its "
                 "name and closed by 出第N卷 notes, 又 continuations, inline 《…》云), merged across quoting books and ordered by "
                 "volume; with verify, checked against the work's surviving witnesses (and each quoting book's reliability).",
                 obj({"work": S, "verify": {"type": "boolean"}, "items": I}, ["work"]), _study_fragments, family="study",
                 permission="classics:read", expensive=True, returns="fragments with volume, topic and witnesses; verification"),
        ToolSpec("study.punctuate", "句读: punctuate 白文 (a text or a passage) with the model learned from the store's punctuated "
                 "texts — marks are only inserted, every character is kept (checked); gaps near the cut are listed for "
                 "review; a punctuated input is stripped, punctuated again and scored against its editors. The model's "
                 "held-out scores (whole works kept out of training) come with every result.",
                 obj({"text": S, "passage_id": S, "items": I, "chars": I}), _study_punctuate, family="study",
                 permission="classics:read", expensive=True, returns="punctuated text, preservation, review gaps, scores"),
        ToolSpec("study.commentaries", "集注对齐与注家比较: the commentaries on a clause (text or passage) across the commentary "
                 "literature — each aligned to the clause (rows after it, run-on text, bracketed notes, anchored rows), "
                 "attributed, dated; compared pairwise: explicit (驳 rejects / 从 endorses / 引 cites a named predecessor), "
                 "wording (照录, 承袭, 自录), content (增益, 同解, 异解 from the concepts each adds); consensus, singular "
                 "readings and who first brought each concept.",
                 obj({"text": S, "passage_id": S, "items": I}), _study_commentaries, family="study",
                 permission="classics:read", expensive=True, returns="commentaries, relations, consensus, first readings"),
        ToolSpec("study.disputes", "争议挖掘: named views rejected or endorsed in the literature (a physician named with a "
                 "reporting word, then a rejection word such as 非也, 谬矣, 殊不知, 此说非 in that or the next sentence) — "
                 "about a term (相火), of a person (丹溪), or, with neither, who rejects whom across the corpus. Use it to "
                 "find counter-evidence and the history of a controversy.",
                 obj({"term": S, "person": S, "items": I}), _study_disputes, family="study", permission="classics:read",
                 expensive=True, returns="disputes with sentences, who rejects whom, endorsements"),
        ToolSpec("study.clause", "条文结构: cut a clause (text or passage; 白文 is punctuated first) into its parts — condition, "
                 "disease, findings, pulse, pattern, principle, contraindication, formula, composition, preparation, "
                 "administration, modification, prognosis — with the findings, pulse, formulas and drugs it names; with "
                 "work, the forms a work's clauses take (e.g. 病→症→方).",
                 obj({"text": S, "passage_id": S, "work": S, "items": I}), _study_clause, family="study",
                 permission="classics:read", returns="pieces with roles, the form, the named terms"),
        ToolSpec("study.glosses", "训诂: the glosses of a word in the commentaries (…者…也, …貌, 犹, 谓, 音, 反切, 读为, 当作, 一作), "
                 "grouped into readings with who first gave each and who repeated it, by period; with book, the glossary "
                 "of a commentary. Emendations are read on the characters as written.",
                 obj({"term": S, "book": S, "items": I}), _study_glosses, family="study", permission="classics:read",
                 expensive=True, returns="glosses with commentator and date, readings, kinds by period"),
        ToolSpec("study.pairs", "配伍规律: drug pairs prescribed together against chance across the written-out compositions of "
                 "the corpus (per work): support, confidence, lift, PMI, one-sided Fisher test with Benjamini–Hochberg; "
                 "with herb, its partners, triples and its share of compositions by period; without, the strongest pairs "
                 "and the groups of drugs that hold together; period restricts to one period.",
                 obj({"herb": S, "period": S, "items": I}), _study_pairs, family="study", permission="classics:read",
                 expensive=True, returns="pairs with statistics, partners, triples, periods, groups"),
        ToolSpec("study.network", "方证网络: from the treatment sentences of the corpus (…主之, 宜…汤) — a formula's findings "
                 "(lift against how often each finding is named) and its drugs, a finding's formulas, or the strongest "
                 "formula–finding links.",
                 obj({"target": S, "items": I}), _study_network, family="study", permission="classics:read",
                 expensive=True, returns="findings or formulas with support, share and lift; drugs; periods"),
        ToolSpec("validation.verify_quote", "Locate a quote verbatim (or after variant normalisation) in the corpus — catches fabricated citations.",
                 obj({"quote": S, "passage_id": S}, ["quote"]), _verify_quote, family="validation", permission="classics:read"),
        ToolSpec("validation.gates", "Evaluate epistemic gates G0–G8 for a claim, evidence record or hypothesis.",
                 obj({"subject_id": S}, ["subject_id"]), _gates, family="validation", permission="validation:run"),
        ToolSpec("validation.provenance_chain", "Alias of philology.inspect_page for validators.",
                 obj({"object_id": S}, ["object_id"]), _inspect, family="validation", permission="classics:read"),
    ]
    for spec in specs + list(extra or []):
        reg.register(spec)
    return reg
