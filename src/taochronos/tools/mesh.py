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
from .common import (claim_card, claims_in_scope, lineage_in_scope, passage_card, scope_ids, scope_passages, term_passages,
                     whole_store)

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
        books=books, allowed=allowed, aliases=a.get("aliases") or "auto",
    )
    corpus = ctx.cap("corpus")
    if getattr(corpus, "large", False):
        ctx.cap("knowledge").touch(h.passage_id for h in hits)  # the working set of a session-less large corpus
    query = {"terms": q.terms, "after": q.after, "before": q.before, "intent": q.intent,
             "decomposition": q.decomposition, "variants": q.variants}
    if q.alias_view:  # the asked names' drugs, the other names searched and those left out (ADR 0023)
        query["aliases"] = q.alias_view
    return {
        "query": query,
        "hits": [
            {**passage_card(ctx, corpus.passage(h.passage_id), focus=h.matched), "score": h.score,
             "routes": sorted(h.routes), "matched": h.matched, "note": h.note,
             **({"via": h.via} if h.via else {}), **({"flags": h.flags} if h.flags else {})}
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
    if whole_store(ctx):  # every book of the store, not only those of the passages read so far
        counts = corpus.book_counts() if hasattr(corpus, "book_counts") else {b: corpus.book_passage_count(b) for b in corpus.books}
    else:
        counts = Counter(p.book_id for p in scope_passages(ctx))
    query, dynasty, category = (a.get("query") or "").strip(), (a.get("dynasty") or "").strip(), (a.get("category") or "").strip()
    out = []
    for book in corpus.books.values():
        if not counts.get(book.id):
            continue
        if query and not any(query in x for x in (book.title, book.id, *book.aliases, *book.authors)):
            continue
        if (dynasty and dynasty not in (book.dynasty or "")) or (category and category not in (book.category or "")):
            continue
        out.append({"book_id": book.id, "title": book.title, "authors": book.authors[:3], "dynasty": book.dynasty,
                    "composition": book.composition.label() if book.composition else None,
                    "category": book.category, "attribution": book.attribution, "passages": counts[book.id]})
    out.sort(key=lambda b: (b["composition"] or "", b["book_id"]))
    return out[: int(a["limit"])] if a.get("limit") else out


def _canon(ctx: ToolContext, a: dict) -> Any:
    return ctx.cap("study").canon(a.get("query") or "", dynasty=a.get("dynasty") or "", category=a.get("category") or "",
                                  limit=int(a.get("limit") or 60), held=a.get("held"))


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
    if wanted and whole_store(ctx):  # the whole store: the claims of the passages that write the terms
        source = ctx.cap("knowledge").claims_for(term_passages(ctx, wanted, after=a.get("after"), before=a.get("before")))
    else:
        source = claims_in_scope(ctx)
    out = []
    for c in source:
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
    source = ctx.cap("knowledge").claims_for(term_passages(ctx, [term])) if whole_store(ctx) else claims_in_scope(ctx)
    for c in source:
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
    lexicon = ctx.cap("domain").lexicon
    right = _prefix_filter(a.get("right", ["formula:", "herb:"]))

    def candidate(t: str) -> bool:  # a weak lexicon entry (a harvested one-character "drug": 药, 补, 白) is not proposed
        entry = lexicon.entry(t)
        return right(t) and not (entry is not None and entry.weak)

    return link_prediction(g, left=_prefix_filter(a.get("left", ["symptom:", "disease:", "pattern:"])), right=candidate,
                           method=a.get("method", "adamic_adar"), k=int(a.get("k", 20)), seed=int(a.get("seed", 0)))


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


PAGE_WHOLE = ("charts", "tables", "document")  # for the page, whole; the model reads none of them


def _brief(value: Any, items: int = 12, chars: int = 240) -> Any:
    """Keep tool results small for agent context: long lists are cut (with the count left out), long strings shortened,
    bulky keys (member lists, Anki text, per-field quotes) dropped.  The full results are in the CLI and the datasets.
    The chart specifications (``charts``, drawn from the full result), the three-line tables (``tables``) and a result's
    document (``document``) pass as they are: the interface shows them whole, the model's text leaves them out
    (``chat.results``) — a table cut here would print part of its rows and a row saying how many were left out."""
    if isinstance(value, dict):
        return {k: (v if k in PAGE_WHOLE else _brief(v, items, chars)) for k, v in value.items()
                if k not in ("member_ids", "anki_tsv", "quotes")}
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


def _study_casefind(ctx: ToolContext, a: dict[str, Any]) -> Any:
    kw = {k: a[k] for k in ("disease", "formula", "herb", "principle", "outcome", "sex", "period", "physician", "text") if a.get(k)}
    kw.update({k: float(a[k]) for k in ("age_min", "age_max", "after", "before") if a.get(k) is not None})
    if a.get("prior") is not None:
        kw["prior"] = bool(a["prior"])
    res = _study(ctx).casefind(findings=a.get("findings") or (), books=a.get("books"),
                               limit=int(a.get("limit", 30)), **kw)
    return _brief(res, int(a.get("items", 15)))


def _study_similar(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).similar(a.get("text"), case_id=a.get("case_id"), disease=a.get("disease"), books=a.get("books"),
                              k=int(a.get("k", 10)), scope=a.get("scope", "first"))
    return _brief(res, int(a.get("items", 12)))


def _study_case(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).case(a["case_id"], similar=int(a.get("similar", 5))), int(a.get("items", 12)), chars=600)


def _study_casecompare(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).casecompare(by=a.get("by", "book"), disease=a.get("disease"), books=a.get("books"),
                                  groups=a.get("groups"), min_cases=int(a.get("min_cases", 5)))
    return _brief(res, int(a.get("items", 12)))


def _study_modifications(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).modifications(disease=a.get("disease"), formula=a.get("formula"), books=a.get("books"),
                                    findings=a.get("findings", "visit"))
    return _brief(res, int(a.get("items", 15)))


def _study_treatments(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).treatments(a["target"], mode=a.get("mode"), by=a.get("by", "formula"), books=a.get("books"),
                                 min_cases=int(a.get("min_cases", 3)))
    return _brief(res, int(a.get("items", 12)))


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


def _names(value: Any) -> list[str]:
    """A list argument given as a list or as one string (桂枝汤、桂枝加桂汤 / 桂枝汤,桂枝加桂汤)."""
    if isinstance(value, str):
        import re

        return [x for x in re.split(r"[、，,；;\s]+", value) if x]
    return [str(x) for x in value or [] if str(x).strip()]


def _study_compare(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).compare(_names(a.get("formulas")), which=a.get("which") or "original"), int(a.get("items", 30)))


def _study_family(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).family(a["formula"], min_share=float(a.get("min_share", 0.75)),
                                     max_extra=int(a.get("max_extra", 4))), int(a.get("items", 25)))


def _study_usage(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).usage(a["herb"]), int(a.get("items", 15)))


def _study_properties(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).properties(_names(a.get("herbs")) or None, formula=a.get("formula")), int(a.get("items", 16)))


def _study_incompat(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).incompat(a.get("target"), drugs=_names(a.get("herbs")) or None), int(a.get("items", 25)))


def _study_protocol(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).protocol(a["question"], pilot=bool(a.get("pilot", True))), int(a.get("items", 30)), chars=600)


def _study_chain(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).chain(a.get("text"), a.get("passage_id")), int(a.get("items", 30)))


def _study_names(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_study(ctx).names(a["term"]), int(a.get("items", 20)))


def _study_entities(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).entities(a.get("text"), a.get("passage_id"))
    for e in res.get("entities", []):
        for key in ("start", "end", "rule", "label"):
            e.pop(key, None)
    res.pop("types", None)
    return _brief(res, int(a.get("items", 60)))


def _study_places(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).places(a.get("place"), term=a.get("term"), school=a.get("school"), person=a.get("person"))
    res.pop("geojson", None)
    return _brief(res, int(a.get("items", 25)))


def _study_translate(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _study(ctx).translate(a.get("text"), a.get("passage_id"))
    res.pop("normalized_changes", None)
    return _brief(res, int(a.get("items", 12)), chars=int(a.get("chars", 1500)))


def _vision_layout(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return ctx.cap("vision").layout(a.get("tokens"), path=a.get("path"), fmt=a.get("format"))


def _vision_compare(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = ctx.cap("vision").compare(a["text"], passage_id=a.get("passage_id"), reference=a.get("reference"))
    res["differences"] = res.get("differences", [])[:int(a.get("items", 30))]
    return res


def _bridge_phenotype(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = ctx.cap("bridge").phenotype(a.get("text"), passage_id=a.get("passage_id"))
    res.pop("text", None)
    return _brief(res, int(a.get("items", 30)), chars=400)


def _bridge_map(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = ctx.cap("bridge").map(a.get("text"), passage_id=a.get("passage_id"), top=int(a.get("top", 5)))
    packet = res.pop("packet")
    res["findings"] = [{k: f[k] for k in ("id", "surface", "label", "relation", "negated", "optional", "conditional", "status")}
                       | {"hpo": (f["hpo"] or {}).get("label")} for f in packet["findings"]]
    res["source"] = packet.get("source")
    return _brief(res, int(a.get("items", 12)), chars=600)


def _bridge_reverse(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(ctx.cap("bridge").reverse(a["disease"], limit=int(a.get("limit", 15))), int(a.get("items", 15)), chars=400)


def _audit_claim(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(ctx.cap("audit").audit(a["claim"], modern=bool(a.get("modern", True))), int(a.get("items", 12)), chars=500)


def _graph_evidence(ctx: ToolContext, a: dict[str, Any]) -> Any:
    g = ctx.cap("audit").graph(passage_id=a.get("passage_id"), text=a.get("text"), claim=a.get("claim"))
    out: dict[str, Any] = {"stats": g.stats(), "unsupported": g.unsupported()[:10]}
    if a.get("node"):
        out["lineage"] = g.lineage(a["node"])[:5]
    return out


def _modern_search(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = ctx.cap("modern").search(a["subject"], a.get("disease"), design=a.get("design"), limit=int(a.get("limit", 15)))
    if a.get("claim"):
        res["guard"] = ctx.cap("modern").guard(a["claim"], res["records"])
    return _brief(res, int(a.get("items", 15)), chars=300)


def _modern_safety(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return ctx.cap("modern").safety(a["text"])


def _rwd_ask(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = ctx.cap("rwd").ask(a["question"])  # the default (synthetic) database: agents never point at a real one
    res.pop("sql", None)
    return res


def _study_schools(ctx: ToolContext, a: dict[str, Any]) -> Any:
    probes = a.get("probes") or []
    return _brief(_study(ctx).schools(a.get("school"), probes=[probes] if isinstance(probes, str) else probes),
                  int(a.get("items", 20)))


# ------------------------------------------------------------------ 我的资料 (the user's own data)
def _mydata(ctx: ToolContext) -> Any:
    try:
        return ctx.cap("mydata")
    except LookupError as exc:
        raise LookupError("我的资料只在对话中可用（mydata 能力由对话运行环境提供）") from exc


def _mydata_list(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_mydata(ctx).list(), 20, chars=400)


def _mydata_read(ctx: ToolContext, a: dict[str, Any]) -> Any:
    limit = max(1, min(int(a.get("limit", 20)), 100))
    res = _mydata(ctx).read(a.get("dataset"), start=int(a.get("start", 1)), limit=limit, columns=_names(a.get("columns")) or None)
    return _brief(res, limit, chars=800)


def _mydata_search(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_mydata(ctx).search(a["query"], dataset=a.get("dataset"), limit=int(a.get("limit", 30))), int(a.get("limit", 30)), chars=400)


def _mydata_describe(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_mydata(ctx).describe(a.get("dataset"), _names(a.get("columns")) or None), int(a.get("items", 40)))


def _mydata_compare(ctx: ToolContext, a: dict[str, Any]) -> Any:
    return _brief(_mydata(ctx).compare(a["outcome"], a["group"], dataset=a.get("dataset")), int(a.get("items", 20)))


def _mydata_prescriptions(ctx: ToolContext, a: dict[str, Any]) -> Any:
    res = _mydata(ctx).prescriptions(a.get("dataset"), column=a.get("column"), group=a.get("group"),
                                     merge=a.get("merge") or "written", classics=bool(a.get("classics", True)))
    return _brief(res, int(a.get("items", 15)))


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
        ToolSpec("classics.search", "Philology-aware temporal GraphRAG search over the classics (7 fused routes). Accepts natural-language questions with period constraints (e.g. 宋代以前). "
                 "A term's lexicon synonyms are always searched with it; a hit's matched lists the forms it was found "
                 "under.  Where the corpus has an alias layer, passages found under another name of an asked drug "
                 "(异名, 避讳改名, 古名), by the route alias or on the drug's other lexicon forms (which keep their own "
                 "routes), take places 4, 7 and 10 of each 10 while the main ranking lasts and every place after it runs "
                 "out; each is labelled with the name, the drug and its source (via), and ambiguous names are listed as "
                 "candidates (query.aliases).  A routes list without alias skips only the route alias; aliases: off "
                 "turns the layer off, and lexicon synonyms then come back unlabelled.  With neither query.aliases nor "
                 "any via, the alias layer added nothing.  A question longer than 200 characters (a passage pasted in) "
                 "is searched as with aliases: off, but a passage that writes a name before it came into use is still "
                 "flagged (anachronism).",
                 obj({"query": S, "k": I, "after": N, "before": N, "routes": {"type": "array", "items": S},
                      "books": {"type": "array", "items": S}, "aliases": {"type": "string", "enum": ["auto", "off"]}},
                     ["query"]),
                 _search, family="retrieval", permission="classics:read",
                 returns="hits with passage ids, periods, routes and matched surfaces; for a drug's other names, their "
                         "labels (via) and flags"),
        ToolSpec("classics.get_passage", "Full passage with locator, variants, temporal context and notes.",
                 obj({"passage_id": S}, ["passage_id"]), _get_passage, family="retrieval", permission="classics:read"),
        ToolSpec("classics.list_books", "Books in research scope (outside a session: every book of the corpus) with dates, "
                 "attribution and passage counts; filter by title/author words, dynasty or category.",
                 obj({"query": S, "dynasty": S, "category": S, "limit": I}), _list_books, family="retrieval",
                 permission="classics:read"),
        ToolSpec("classics.canon", "要籍: the most important works of Chinese medicine, ranked by how later works cite them "
                 "(corpus/catalog/canon.yaml), with author, dynasty, category, citing works and witnesses, and whether this "
                 "corpus holds the text (held: true/false filters); filter by title/author words, dynasty or category.",
                 obj({"query": S, "dynasty": S, "category": S, "held": {"type": "boolean"}, "limit": I}), _canon,
                 family="retrieval", permission="classics:read"),
        ToolSpec("classics.lineage", "Knowledge-lineage edges (cites / transcribes / rephrases / opposes / formula_derived_from / inherits).",
                 obj({"subject": S, "limit": I}), _lineage, family="retrieval", permission="classics:read"),
        ToolSpec("kg.extract_claims", "Extract hyperedge claims from a passage (lexicon + pattern rules); returns candidates, commits nothing.",
                 obj({"passage_id": S}, ["passage_id"]), _extract, family="knowledge", permission="kg:read"),
        ToolSpec("kg.claims", "Query claims by terms, relation and period (in a session: its committed claims; on the whole "
                 "store: the claims read from the passages that write the terms, spread over time).",
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
        ToolSpec("study.casefind", "医案检索: the case records (across every case collection, oldest first) that fit a query of "
                 "many facets — disease, findings (symptoms, pulse such as 浮数, tongue such as 苔黄), formula, herb, principle, "
                 "outcome (improved/unchanged/worse/died), sex, age range, period or years, collections (books), the "
                 "physician (丹溪, 叶天士: named in the record, else the collection's author), whether "
                 "an earlier physician's treatment is recorded (prior: 误治), words of the text — each with what matched, "
                 "and the facets of all matches (collections, periods, outcomes, formulas, principles, drugs, findings).",
                 obj({"disease": S, "findings": {"type": "array", "items": S}, "formula": S, "herb": S, "principle": S,
                      "outcome": S, "sex": S, "age_min": N, "age_max": N, "after": N, "before": N, "period": S, "physician": S,
                      "books": {"type": "array", "items": S}, "prior": {"type": "boolean"}, "text": S, "limit": I, "items": I}),
                 _study_casefind, family="study", permission="classics:read", expensive=True,
                 returns="cases (id, book, period, patient, visits, outcome, formulas, prior, matched), facets"),
        ToolSpec("study.similar", "类案: the historical case records whose presentation is most like a given one — a text such as "
                 "“发热，咳嗽，脉浮数，舌红苔黄” (read as a first visit) or a case_id — by shared findings weighted by "
                 "rarity (cosine); what each like case did and how it ended, and what the nearest did together with their "
                 "outcomes. What physicians recorded doing, never advice for a patient.",
                 obj({"text": S, "case_id": S, "disease": S, "books": {"type": "array", "items": S}, "k": I, "scope": S,
                      "items": I}), _study_similar, family="study", permission="classics:read", expensive=True,
                 returns="features read, results (score, shared, treated, outcome), practice (formulas, principles, herbs)"),
        ToolSpec("study.case", "医案详解: one case record in full by its case_id (from study.casefind, study.similar or study.cases) "
                 "— its course visit by visit (findings, diagnosis, earlier physicians' treatment, principle, formulas and "
                 "drugs with doses, 加减 as stated and as computed from the drugs listed, doses, response), the passages it "
                 "rests on, and its like cases.",
                 obj({"case_id": S, "similar": I, "items": I}, ["case_id"]), _study_case, family="study",
                 permission="classics:read", expensive=True, returns="course, witnesses, formulas named, similar cases"),
        ToolSpec("study.casecompare", "医家与时代比较: groups of case records side by side — by collection (by=book), by "
                 "physician (by=physician: the one the record names, as a compilation's 丹溪治…, else the collection's "
                 "author), by period or by author; optionally for one disease — visits, outcome rates with intervals, the "
                 "patients each saw, the principles, formulas and drugs each favours against the others (Fisher + BH), "
                 "χ² and Kruskal–Wallis across groups, and by period Cochran–Armitage trends.",
                 obj({"by": S, "disease": S, "books": {"type": "array", "items": S}, "groups": {"type": "array", "items": S},
                      "min_cases": I, "items": I}), _study_casecompare, family="study", permission="classics:read",
                 expensive=True, returns="group profiles with distinctive items, tests, distances, trends"),
        ToolSpec("study.modifications", "随证加减: at the visits of case records that add to or take from the last prescription, the "
                 "findings that go with each drug added or removed (lift, Fisher + BH), the drugs most often added and "
                 "removed, and what is added to each base formula; optionally for a disease or a base formula.",
                 obj({"disease": S, "formula": S, "books": {"type": "array", "items": S}, "findings": S, "items": I}),
                 _study_modifications, family="study", permission="classics:read", expensive=True,
                 returns="finding → drug added/removed associations, bases with their additions, examples"),
        ToolSpec("study.treatments", "同病异治 · 异病同治 in the case records: for a disease, the different treatments its cases "
                 "received (grouped by formula or principle) and the findings that set each group apart; for a formula, "
                 "the diseases it treated and the findings those cases share (the common pattern) and those that differ.",
                 obj({"target": S, "mode": S, "by": S, "books": {"type": "array", "items": S}, "min_cases": I, "items": I},
                     ["target"]), _study_treatments, family="study", permission="classics:read", expensive=True,
                 returns="groups with outcomes and distinctive findings; shared findings (formula mode)"),
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
        ToolSpec("study.compare", "方剂比较 (同药异量): two to six formulas side by side, each as its earliest tradition (原方; "
                 "which=current: the most witnessed) writes it out — drugs, doses as written, each dose in 两 of the witness's "
                 "period and as a ratio (the largest = 1), and for every two formulas the drugs shared and not, Jaccard, a "
                 "dose-weighted overlap and the verdict 同方 / 同药异量 (桂枝汤 vs 桂枝加桂汤; 小承气汤 vs 厚朴三物汤) / 加减化裁 / "
                 "异方. Doses are historical readings, never dosage guidance.",
                 obj({"formulas": {"type": "array", "items": S}, "which": {"type": "string", "enum": ["original", "current"]},
                      "items": I}, ["formulas"]), _study_compare, family="study", permission="classics:read", expensive=True,
                 returns="formulas with witness and drugs (dose, 两, ratio, share), matrix, pairwise comparison and verdicts"),
        ToolSpec("study.family", "类方: the formulas whose written-out compositions hold most of one formula's core (min_share, "
                 "default 0.75; max_extra drugs added, default 4), per work — what each adds and leaves out (加味, 减味, 加减, "
                 "同药), 同药异量 / 同方异名 told apart by the doses, the formula it combines with (合方), its works and earliest "
                 "witness, members by period.",
                 obj({"formula": S, "min_share": N, "max_extra": I, "items": I}, ["formula"]), _study_family, family="study",
                 permission="classics:read", expensive=True,
                 returns="the base formula's core; members with relation, added/removed drugs, works, earliest witness, 合方"),
        ToolSpec("study.usage", "用药谱: one drug across every written-out composition of the corpus (per work) — its share of "
                 "compositions by period with 95% Wilson intervals and a trend test, its doses as written and read in 两 and "
                 "grams of their period (quartiles; never dosage guidance), how often it is the largest dose, its preparation "
                 "notes by period, the drugs it is written with (lift), its formulas and earliest compositions.",
                 obj({"herb": S, "items": I}, ["herb"]), _study_usage, family="study", permission="classics:read", expensive=True,
                 returns="share by period, trend, doses by period, largest-dose share, preparation notes, partners, formulas"),
        ToolSpec("study.properties", "药性谱: what the 本草 say of several drugs (herbs) or of a formula's drugs (formula, its 原方) — "
                 "natures (寒凉平温热), flavours, toxicity and channels (read by the twelve channels' organs), each with the "
                 "share of works stating it and the first statement; for a formula, its profile weighted by dose.",
                 obj({"herbs": {"type": "array", "items": S}, "formula": S, "items": I}), _study_properties, family="study",
                 permission="classics:read", expensive=True,
                 returns="per drug: natures, flavours, toxicity, channels with shares, consensus, first statements; profile"),
        ToolSpec("study.incompat", "配伍禁忌 (十八反·十九畏) in the literature: statements of 反 / 畏 written in the texts (the drug "
                 "an entry is about and the drugs listed after 反 / 畏) with their earliest witness and works by period, "
                 "where the verses are written, and the written-out compositions that still hold both drugs of a pair; "
                 "target: a formula (its 原方 checked) or a drug (its pairs); herbs: a list of drugs to check. Textual "
                 "history, not safety guidance (modern.safety).",
                 obj({"target": S, "herbs": {"type": "array", "items": S}, "items": I}), _study_incompat, family="study",
                 permission="classics:read", expensive=True,
                 returns="rules, check, statements with earliest witnesses, verses, compositions writing a pair together"),
        ToolSpec("study.protocol", "研究方案: turn a research question (especially on formulas and drugs: 方源, 方剂比较/同药异量, 类方, "
                 "药性, 用药, 配伍, 十八反十九畏, 方证, 术语, 名称) into a research protocol — what it names (formulas, drugs, "
                 "findings, terms, period), objectives, questions, hypotheses each with prediction, test, refutation and "
                 "rival explanations, scope (corpus, period, works to read first, inclusion and exclusion), variables, methods "
                 "(the capabilities to run, with arguments and commands), analysis, planned figures, quality checks, "
                 "limitations, ethics, timeline and a research contract; pilot (default true) runs the main steps once and "
                 "reports how much evidence the corpus holds, with charts.",
                 obj({"question": S, "pilot": {"type": "boolean"}, "items": I}, ["question"]), _study_protocol, family="study",
                 permission="classics:read", expensive=True,
                 returns="protocol sections, pilot findings with feasibility, research contract, charts"),
        ToolSpec("study.chain", "传播链: a passage's dated witnesses (copies, quotations, restatements) ordered into a tree by shared "
                 "innovations — each hangs from the earlier witness whose variant readings it shares most (less that one's "
                 "readings it lacks), else from the earliest; each edge with its shared readings, score and margin.",
                 obj({"text": S, "passage_id": S, "items": I}), _study_chain, family="study", permission="classics:read",
                 expensive=True, returns="nodes with dates and relations, edges with evidence and margin, root, summary"),
        ToolSpec("study.names", "名称: the names the lexicon records for a drug, formula or disease (本名, 异名, taboo renames, "
                 "part and preparation names) through time — works writing each name by period and by century, the first "
                 "to write it, when the preferred name changes (薯蓣→山药, 玄参→元参), passages equating two names, and "
                 "names the punctuated texts give after 一名/又名/俗呼 that the lexicon lacks (candidates to curate).",
                 obj({"term": S, "items": I}, ["term"]), _study_names, family="study", permission="classics:read",
                 expensive=True, returns="names with counts and first witnesses, shares by period, switches, equations, candidates"),
        ToolSpec("study.schools", "学派: a school's physicians and works (schools.yaml, physicians.yaml), the words and formulas "
                 "they use more than the other authors of their time (each physician counted once, the others reweighed to "
                 "the school's forms; rate z with an informative Dirichlet prior, share z, Benjamini–Hochberg), whom they "
                 "cite (homophily against the others), whom they reject and who rejects them; without a school, every "
                 "school and the school-by-school citation matrix; probes: words to report for the school.",
                 obj({"school": S, "probes": {"type": "array", "items": S}, "items": I}), _study_schools, family="study",
                 permission="classics:read", expensive=True,
                 returns="members and works, distinctive words, formulas, citations, homophily, rejections, lineage"),
        ToolSpec("study.entities", "实体识别 (T7): the entities of a text or passage in context — Disease, Syndrome, Symptom, Sign, "
                 "Pulse, Tongue, Etiology, Pathogenesis, Location, Nature, Treatment, Formula, Herb, Dose, Preparation, "
                 "Contraindication, Physician, Commentator, School, Theory, Book, Edition, Place, Time — from the lexicon, "
                 "physicians, schools, places, eras and patterns; negated findings flagged; ambiguous spans kept with their "
                 "alternatives (typed by the model when one reviews the study layer).",
                 obj({"text": S, "passage_id": S, "items": I}), _study_entities, family="study", permission="classics:read",
                 returns="entities with type, reference, source, ambiguity and negation; counts by type"),
        ToolSpec("study.places", "地域 (T27, time × person × place): physicians and works by region and period (native places "
                 "from physicians.yaml, places signed in prefaces and colophons); with person, a physician's place as curated, "
                 "stated (「…，真定人」) and signed; with school, where its physicians came from; with term, the share of each "
                 "region's works using the term against the other regions', period by period (z, BH); with place, its "
                 "physicians and works.",
                 obj({"place": S, "term": S, "school": S, "person": S, "items": I}), _study_places, family="study",
                 permission="classics:read", expensive=True, returns="rows by region and period, people and works with places"),
        ToolSpec("study.translate", "释义与今译 (T10): a text in five layers — original (never changed), normalised, punctuated "
                 "(the editors' marks, or the 句读 model's), interpreted (for its doublets and terms: the commentators' "
                 "glosses with who first gave them, and the curated historical sense its date and context favour) and, "
                 "when a model reviews the study layer, a modern Chinese translation that cites the glosses it uses and "
                 "passes the presentism guardrail.",
                 obj({"text": S, "passage_id": S, "items": I, "chars": I}), _study_translate, family="study",
                 permission="classics:read", expensive=True, returns="the five layers; glosses and senses; a checked translation"),
        ToolSpec("vision.layout", "版面理解 (T1): the layout and reading order of a page from an OCR engine's boxes (a file in "
                 "ALTO, hOCR, PAGE, PaddleOCR or token JSON, or tokens {text, bbox}) — vertical columns right to left, "
                 "双行小注 read right half first, 版心 and 书眉 set apart — as a PageGraph with the running text.",
                 obj({"path": S, "format": S, "tokens": {"type": "array"}}), _vision_layout, family="philology",
                 permission="classics:read", returns="blocks with kind, box and order; the running text; the apparatus"),
        ToolSpec("vision.compare", "OCR 核对 (T2): an OCR text against the transcription of the store it reads (found by probes, "
                 "or a passage given) or a reference: character error rate, after normalising variants too, the engine's "
                 "commonest substitutions and each difference in context.",
                 obj({"text": S, "passage_id": S, "reference": S, "items": I}, ["text"]), _vision_compare, family="philology",
                 permission="classics:read", returns="CER, variant-only differences, confusions, differences, the passage"),
        ToolSpec("bridge.phenotype", "古代表型包 (AMBE S10): the findings a passage states — each with its HPO projection and "
                 "relation type (EXACT, CLOSE, PARTIAL_OVERLAP, NO_MODERN_EQUIVALENT …), negated / optional / conditional / "
                 "after treatment, its modifiers — and the historical names it uses with the sense its context selects.",
                 obj({"text": S, "passage_id": S, "items": I}), _bridge_phenotype, family="bridge",
                 permission="classics:read", returns="findings, implied findings, terms with senses and homonym warnings"),
        ToolSpec("bridge.map", "古今映射 (AMBE S11–S12): a passage's findings scored against modern disease profiles (HPO, "
                 "ICD-10), explainably — matched and missing typical findings, conflicts, required findings — with a "
                 "qualitative level (high / moderate / low / insufficient, never a probability), what would tell the "
                 "candidates apart, how its historical names relate to them, and a statement that passes the presentism "
                 "guard.  Phenotypic similarity, not retrospective diagnosis.",
                 obj({"text": S, "passage_id": S, "top": I, "items": I}), _bridge_map, family="bridge",
                 permission="classics:read", expensive=True, returns="candidates with levels, discriminators, term relations, statement"),
        ToolSpec("bridge.reverse", "今病溯古 (AMBE): from a modern disease (id, name or ICD-10 code) to the ancient written forms "
                 "of its findings, the passages that describe several of them together (with a required finding), and the "
                 "historical names those passages use — candidates for historical study, not equivalents.",
                 obj({"disease": S, "limit": I, "items": I}, ["disease"]), _bridge_reverse, family="bridge",
                 permission="classics:read", expensive=True, returns="forms, passages with levels, names by period"),
        ToolSpec("audit.claim", "证据审计 (S15): a claim decomposed into atomic claims, each checked by what it asserts — a "
                 "historical claim against the witness (every quote verbatim), an interpretation against a cited gloss, a "
                 "mapping against the presentism guard and the bridge, a modern claim against typed modern evidence (the "
                 "cross-level guard), an inference for its leap; clinical advice is refused.  Verdicts: SUPPORTED, "
                 "PARTIALLY_SUPPORTED, CONTESTED, INSUFFICIENT_EVIDENCE, UNSUPPORTED.",
                 obj({"claim": S, "modern": {"type": "boolean"}, "items": I}, ["claim"]), _audit_claim, family="validation",
                 permission="classics:read", expensive=True, returns="verdict, atomic claims with checks, safety flags"),
        ToolSpec("graph.evidence", "证据图谱: the six-layer evidence graph (source → historical → TCM semantic → mapping → modern → "
                 "evidence) of a passage's mapping or a claim's audit, every edge with its assertion type; the lineage of a "
                 "node back to the witnesses; the inferred edges with no path to a source.",
                 obj({"passage_id": S, "text": S, "claim": S, "node": S}), _graph_evidence, family="validation",
                 permission="classics:read", expensive=True, returns="stats by layer and assertion type, unsupported edges, lineage"),
        ToolSpec("modern.search", "现代证据 (S13): modern studies of a drug or formula (and a disease), typed by design and "
                 "population (RCT, cohort, animal, cell, network pharmacology …), summed up by level; with a claim, which "
                 "records can carry it (the cross-level guard).  PubMed when the capability is online, else the cache and "
                 "the curated records.",
                 obj({"subject": S, "disease": S, "design": S, "claim": S, "limit": I, "items": I}, ["subject"]), _modern_search,
                 family="literature", permission="literature:read", expensive=True, returns="records by type, summary, guard, safety"),
        ToolSpec("modern.safety", "安全提示: the toxic materials a text names (aconite, aristolochic acid, mercury, arsenic …) — "
                 "warnings only, never advice.", obj({"text": S}, ["text"]), _modern_safety, family="literature",
                 permission="literature:read", returns="materials with their documented risks"),
        ToolSpec("rwd.ask", "真实世界数据 (S14): a question as a study spec over the synthetic OMOP database (exposure, outcome, "
                 "population, windows), compiled into a checked, parameterised, read-only query; counts, risks and a crude "
                 "risk ratio with caveats.  A model never writes the SQL.",
                 obj({"question": S}, ["question"]), _rwd_ask, family="literature", permission="literature:read",
                 expensive=True, returns="the spec, arms, risk ratio, caveats"),
        ToolSpec("mydata.list", "我的资料: the datasets the user has uploaded in this conversation's runtime (files read in "
                 "their own browser or machine and made anonymous: names, identity, telephone and record numbers removed) — "
                 "each one's id, file name, kind (table or text), size, columns with their types (number, date, category, "
                 "text, prescription) and a preview, and what was removed.",
                 obj({}), _mydata_list, family="mydata", permission="mydata:read",
                 returns="datasets with ids, columns and types, de-identification report"),
        ToolSpec("mydata.read", "我的资料: read a dataset — a table's rows (columns to choose some; start, limit) or a text's "
                 "passages — each with its citable id (mine:<dataset>.r<n> for a row, mine:<dataset>.<n> for a passage). "
                 "dataset is its id or file name (may be left out when there is only one).",
                 obj({"dataset": S, "start": I, "limit": I, "columns": {"type": "array", "items": S}}), _mydata_read, family="mydata",
                 permission="mydata:read", returns="rows or passages with mine: ids"),
        ToolSpec("mydata.search", "我的资料: where the user's data writes the words of query (all of them, after the corpus's "
                 "variant folding): the passages and rows with the words around them, and how many there are.",
                 obj({"query": S, "dataset": S, "limit": I}, ["query"]), _mydata_search, family="mydata", permission="mydata:read",
                 returns="hits with mine: ids and context, the total"),
        ToolSpec("mydata.describe", "我的资料 · 描述统计: a table's columns described as a paper's first table — a numeric column's "
                 "n, missing, mean ± SD, median (P25, P75) and range with a histogram; a categorical column's categories, "
                 "n (%), with a bar chart — as three-line tables the page shows and downloads.",
                 obj({"dataset": S, "columns": {"type": "array", "items": S}, "items": I}), _mydata_describe, family="mydata",
                 permission="mydata:read", returns="variables with their statistics; charts and tables for the page"),
        ToolSpec("mydata.compare", "我的资料 · 组间比较: an outcome column across the groups of another column — a numeric "
                 "outcome by Kruskal–Wallis (each group's n, mean ± SD, median (P25, P75); a box plot), a categorical one by "
                 "Pearson's χ² (Fisher's exact test for a 2 × 2 table with an expected count under 5; n (%) by group; a "
                 "stacked chart), two numeric columns by Spearman's ρ (a scatter with a LOESS curve).",
                 obj({"outcome": S, "group": S, "dataset": S, "items": I}, ["outcome", "group"]), _mydata_compare, family="mydata",
                 permission="mydata:read", returns="the test, per-group statistics; charts and tables for the page"),
        ToolSpec("mydata.prescriptions", "我的资料 · 处方用药分析: the prescriptions of a table's column (found by itself, or "
                 "column) or of a text's passages, read with the classics' lexicon (drugs and their doses: 柴胡12g, "
                 "桂枝三两, 柴胡、黄芩各9g) — the drugs used most, their doses in grams, the pairs used together more often "
                 "than chance (one-sided Fisher test, Benjamini–Hochberg), association rules, a clustering of the frequent "
                 "drugs; with group (a diagnosis column), which drugs differ across the groups; with classics, each "
                 "prescription's nearest composition in the classics (Jaccard on drug families) and its witness.  merge: "
                 "written (default: 白芍 and 赤芍 apart) or family (as the classics: 白芍、赤芍 → 芍药).",
                 obj({"dataset": S, "column": S, "group": S, "merge": {"type": "string", "enum": ["written", "family"]},
                      "classics": {"type": "boolean"}, "items": I}),
                 _mydata_prescriptions, family="mydata", permission="mydata:read", expensive=True,
                 returns="frequency, doses, pairs, rules, clusters, groups, nearest classics; charts and tables for the page"),
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
