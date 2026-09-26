"""Corpus Curator: freezes the research scope into a CorpusManifest.

Applies the GoalSpec's corpus scope, temporal scope and hold-out (Historical
Time Machine), reports period coverage and flags thin periods — absence of
evidence in a thinly covered period is weak evidence of absence.
"""

from __future__ import annotations

from typing import Any

from ...protocol.events import EventType
from ...protocol.research import CorpusManifest
from .common import focus_term_ids, related_terms, surface, surfaces_of

OUTPUT = "CorpusManifest"
THIN_PERIOD = 4


def instructions(ctx: Any) -> str:
    return "Freeze the corpus manifest for this research contract: books, passages, hold-out and coverage warnings."


def _books(goal: Any, corpus: Any, exclude_categories: Any = ()) -> tuple[list[str], dict[str, str]]:
    """Books in scope.  ``exclude_categories`` (profile default, e.g. modern works) applies only when the research
    contract does not name its categories itself."""
    scope = goal.corpus
    excluded: dict[str, str] = {}
    books = []
    for book in sorted(corpus.books.values(), key=lambda b: b.id):
        if scope.books and book.id not in scope.books:
            excluded[book.id] = "outside corpus scope"
        elif book.id in scope.exclude_books:
            excluded[book.id] = "excluded by the research contract"
        elif scope.categories and book.category not in scope.categories:
            excluded[book.id] = f"category {book.category} not in scope"
        elif not scope.categories and not scope.books and book.category in exclude_categories:
            excluded[book.id] = f"category {book.category} excluded by the profile"
        elif not book.source.license:
            excluded[book.id] = "no license metadata (Gate G0)"
        else:
            books.append(book.id)
    return books, excluded


def draft(ctx: Any) -> dict[str, Any]:
    goal = ctx.goal
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    if getattr(corpus, "large", False):
        return draft_large(ctx)
    scope = goal.corpus
    basis = goal.time_basis
    books, excluded = _books(goal, corpus)
    keep, holdout = [], []
    for p in corpus.passages(book_ids=books, basis=basis):
        if scope.tags and not set(scope.tags) & set(p.tags):
            continue
        year = corpus.year(p, basis)
        if goal.temporal_scope is not None and (year is None or not goal.temporal_scope.contains(year)):
            continue
        if goal.holdout_after is not None and (year is None or year >= goal.holdout_after):
            holdout.append(p.id)
            continue
        keep.append(p.id)
    coverage: dict[str, int] = {pid: 0 for pid in pack.periods.ids()}
    for pid in keep:
        period = pack.periods.period_of(corpus.year(corpus.passage(pid), basis))
        if period:
            coverage[period] = coverage.get(period, 0) + 1
    warnings = []
    for period, n in coverage.items():
        if 0 < n < THIN_PERIOD:
            warnings.append(f"thin coverage in {pack.periods.label(period)}: {n} passage(s) — absence there is weak evidence")
    unverified = sum(1 for b in books if not corpus.books[b].source.verified)
    if unverified:
        warnings.append(f"{unverified} of {len(books)} books are unverified transcriptions (G1/G2 will warn)")
    if holdout:
        warnings.append(f"{len(holdout)} passage(s) dated ≥ {goal.holdout_after} are held out")
    books_in = sorted({corpus.passage(pid).book_id for pid in keep})
    for b in books:
        if b not in books_in and b not in excluded:
            excluded[b] = "no passages inside the temporal scope"
    return {"book_ids": books_in, "passage_ids": keep, "excluded": excluded,
            "coverage": {k: v for k, v in coverage.items() if v}, "holdout_passage_ids": holdout,
            "time_basis": basis, "warnings": warnings}


def frame_surfaces(ctx: Any) -> tuple[list[str], dict[str, list[str]]]:
    """Term ids of the question and the surfaces that define the sampling frame: every alias and synonym,
    related / broader / narrower terms, components, and the cues of each historical sense (so a concept is
    found before it had its later name)."""
    pack = ctx.cap("domain")
    lex = pack.lexicon
    terms = focus_term_ids(ctx)
    surfaces: dict[str, list[str]] = {}
    for tid in terms:
        forms = list(surfaces_of(ctx, tid))
        entry = lex.entry(tid)
        if entry is not None:
            for other in [*entry.related, *entry.broader, *entry.components]:
                oe = lex.resolve(other)
                forms.extend(oe.surfaces() if oe else [other])
        for rid in related_terms(ctx, tid):
            forms.extend(surfaces_of(ctx, rid))
        hist = pack.terminology.term(surface(tid))
        if hist is not None:
            for sense in hist.senses:
                forms.extend(c for c in sense.cues if len(c) >= 2)
        surfaces[tid] = [f for f in dict.fromkeys(forms) if f and (len(f) >= 2 or tid.startswith("herb:"))]
    return terms, surfaces


def draft_large(ctx: Any) -> dict[str, Any]:
    """Relevance-scoped manifest for a large corpus: the frame is every passage the full-text index finds for
    the question's terms (and, once, for the formulas and drugs most co-mentioned with them), stratified by
    period so that thin periods keep their evidence; the frame is recorded in the manifest.  Checks of
    absence and later attestation do not rely on the frame: the Skeptic queries the whole store."""
    goal = ctx.goal
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    cfg = dict((ctx.config or {}).get("scope") or {})
    max_passages = int(cfg.get("max_passages", 2400))
    floor = int(cfg.get("per_period_floor", 60))
    hops = int(cfg.get("related_hops", 1))
    related_limit = int(cfg.get("related_limit", 12))
    exclude_kinds = set(cfg.get("exclude_kinds", ["toc"]))
    basis = goal.time_basis
    books, excluded = _books(goal, corpus, set(cfg.get("exclude_categories", [])))
    allowed_books = set(books)
    after = before = None
    latest = cfg.get("latest_year")  # without a period of its own, a question reads nothing from this year on
    if goal.temporal_scope is not None:
        after, before = goal.temporal_scope.start, goal.temporal_scope.end + 1
    elif latest is not None:
        before = int(latest)
    terms, surfaces = frame_surfaces(ctx)
    score: dict[str, float] = {}
    matched_by: dict[str, set[str]] = {}
    for tid, forms in surfaces.items():
        for form in forms:
            for rank, (pid, s) in enumerate(corpus.search([form], limit=max_passages * 2, after=after, before=before)):
                score[pid] = score.get(pid, 0.0) + s
                matched_by.setdefault(pid, set()).add(tid)
            hits = corpus.contains(form, after=after, before=before, verify=False)
            half = max_passages // 2
            for pid in (hits if len(hits) <= max_passages else hits[:half] + hits[-half:]):  # earliest and latest
                score.setdefault(pid, 0.1)
                matched_by.setdefault(pid, set()).add(tid)
    expansion: list[str] = []
    if hops and score:
        top = sorted(score, key=lambda pid: (-len(matched_by.get(pid, ())), -score[pid], pid))[:400]
        counts: dict[str, int] = {}
        for p in corpus.passages_by_id(top):
            norm = pack.variants.normalize_text(p.text)
            for m in {(m.term_id, m.category) for m in pack.lexicon.match(norm, include_weak=False)}:
                if m[1] in ("formula", "herb") and m[0] not in terms:
                    counts[m[0]] = counts.get(m[0], 0) + 1
        expansion = [t for t, _ in sorted(counts.items(), key=lambda t: (-t[1], t[0]))[:related_limit]]
        for tid in expansion:
            for pid, s in corpus.search(surfaces_of(ctx, tid), limit=max(50, max_passages // (4 * max(1, related_limit))),
                                        after=after, before=before):
                if pid not in score:
                    score[pid] = 0.5 * s
                    matched_by.setdefault(pid, set()).add(tid)
    passages = {p.id: p for p in corpus.passages_by_id(sorted(score))}
    keep_pool: list[str] = []
    holdout: list[str] = []
    dropped_kind = 0
    for pid, p in passages.items():
        if p.book_id not in allowed_books or p.kind in exclude_kinds:
            dropped_kind += p.kind in exclude_kinds
            continue
        year = corpus.year(p, basis)
        if goal.temporal_scope is not None and (year is None or not goal.temporal_scope.contains(year)):
            continue
        if goal.temporal_scope is None and latest is not None and year is not None and year >= int(latest):
            continue
        if goal.holdout_after is not None and (year is None or year >= goal.holdout_after):
            holdout.append(pid)
            continue
        keep_pool.append(pid)
    # stratified selection: a floor per period, then the best-scoring passages overall
    by_period: dict[str, list[str]] = {}
    for pid in keep_pool:
        period = pack.periods.period_of(corpus.year(passages[pid], basis)) or "?"
        by_period.setdefault(period, []).append(pid)
    order = lambda pid: (-len(matched_by.get(pid, ())), -score[pid], pid)  # noqa: E731
    keep: list[str] = []
    for period, ids in sorted(by_period.items()):
        keep.extend(sorted(ids, key=order)[:floor])
    chosen = set(keep)
    for pid in sorted(keep_pool, key=order):
        if len(keep) >= max_passages:
            break
        if pid not in chosen:
            keep.append(pid)
            chosen.add(pid)
    keep.sort(key=lambda pid: (corpus.year(passages[pid], basis) or 0, pid))
    coverage: dict[str, int] = {}
    for pid in keep:
        period = pack.periods.period_of(corpus.year(passages[pid], basis))
        if period:
            coverage[period] = coverage.get(period, 0) + 1
    warnings = []
    for period in pack.periods.ids():
        n = coverage.get(period, 0)
        available = len(by_period.get(period, []))
        if 0 < n < THIN_PERIOD:
            warnings.append(f"thin coverage in {pack.periods.label(period)}: {n} passage(s) — absence there is weak evidence")
        if available > n:
            warnings.append(f"{pack.periods.label(period)}: {n} of {available} matching passages sampled into the frame")
    if len(keep_pool) > len(keep):
        warnings.append(f"frame sampled {len(keep)} of {len(keep_pool)} matching passages (stratified by period); "
                        "absence and later-attestation checks query the whole corpus store")
    unverified = sum(1 for b in books if not corpus.books[b].source.verified)
    if unverified:
        warnings.append(f"{unverified} of {len(books)} books are unverified transcriptions (G1/G2 will warn)")
    if holdout:
        warnings.append(f"{len(holdout)} matching passage(s) dated ≥ {goal.holdout_after} are held out")
    if goal.temporal_scope is None and latest is not None:
        warnings.append(f"evidence read up to {int(latest)} (the question names no period): the modern editors' layers and "
                        "contemporary works after it are no evidence for historical questions")
    books_in = sorted({passages[pid].book_id for pid in keep})
    frame = {
        "strategy": "full-text index: question terms, their variants, related terms and sense cues; one hop to co-mentioned formulas/herbs; stratified by period",
        "terms": terms, "surfaces": {t: f[:40] for t, f in surfaces.items()}, "expansion": expansion,
        "matched": len(keep_pool), "kept": len(keep), "per_period_floor": floor, "max_passages": max_passages,
        "available_by_period": {k: len(v) for k, v in sorted(by_period.items())}, "excluded_kinds": sorted(exclude_kinds),
        "corpus_passages": len(corpus), "latest_year": int(latest) if latest is not None and goal.temporal_scope is None else None,
    }
    return {"book_ids": books_in, "passage_ids": keep, "excluded": {k: v for k, v in excluded.items()},
            "coverage": coverage, "holdout_passage_ids": sorted(holdout), "time_basis": basis, "warnings": warnings, "frame": frame}


def commit(ctx: Any, output: dict[str, Any]) -> str:
    corpus = ctx.cap("corpus")
    valid = [pid for pid in output["passage_ids"] if corpus.has_passage(pid)]
    holdout = set(output.get("holdout_passage_ids", []))
    manifest = CorpusManifest(
        book_ids=sorted({corpus.passage(pid).book_id for pid in valid}),
        passage_ids=[pid for pid in valid if pid not in holdout],
        excluded=dict(output.get("excluded", {})),
        coverage=dict(output.get("coverage", {})),
        holdout_passage_ids=sorted(holdout),
        time_basis=output.get("time_basis", "composition"),
        warnings=list(output.get("warnings", [])),
        frame=dict(output.get("frame") or {}),
    )
    ctx.emit(EventType.CORPUS_SCOPED, {"manifest": manifest.to_dict()})
    return f"{len(manifest.book_ids)} books, {len(manifest.passage_ids)} passages in scope, {len(manifest.holdout_passage_ids)} held out"
