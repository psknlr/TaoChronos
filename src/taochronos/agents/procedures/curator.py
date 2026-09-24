"""Corpus Curator: freezes the research scope into a CorpusManifest.

Applies the GoalSpec's corpus scope, temporal scope and hold-out (Historical
Time Machine), reports period coverage and flags thin periods — absence of
evidence in a thinly covered period is weak evidence of absence.
"""

from __future__ import annotations

from typing import Any

from ...protocol.events import EventType
from ...protocol.research import CorpusManifest

OUTPUT = "CorpusManifest"
THIN_PERIOD = 4


def instructions(ctx: Any) -> str:
    return "Freeze the corpus manifest for this research contract: books, passages, hold-out and coverage warnings."


def draft(ctx: Any) -> dict[str, Any]:
    goal = ctx.goal
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    scope = goal.corpus
    basis = goal.time_basis
    excluded: dict[str, str] = {}
    books = []
    for book in sorted(corpus.books.values(), key=lambda b: b.id):
        if scope.books and book.id not in scope.books:
            excluded[book.id] = "outside corpus scope"
        elif book.id in scope.exclude_books:
            excluded[book.id] = "excluded by the research contract"
        elif scope.categories and book.category not in scope.categories:
            excluded[book.id] = f"category {book.category} not in scope"
        elif not book.source.license:
            excluded[book.id] = "no license metadata (Gate G0)"
        else:
            books.append(book.id)
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
    )
    ctx.emit(EventType.CORPUS_SCOPED, {"manifest": manifest.to_dict()})
    return f"{len(manifest.book_ids)} books, {len(manifest.passage_ids)} passages in scope, {len(manifest.holdout_passage_ids)} held out"
