"""Helpers shared by the role procedures (evidence records, term surfaces, scope, clustering)."""

from __future__ import annotations

from typing import Any

from ...protocol.base import stable_id
from ...protocol.claims import Claim
from ...protocol.confidence import ConfidenceVector
from ...protocol.events import EventType
from ...protocol.evidence import EvidenceRecord, Stance
from ...tools.adapters import author_clusters, binner, claim_year_fn


def scope_passage_ids(ctx: Any) -> list[str]:
    corpus = ctx.cap("corpus")
    if ctx.state.corpus is not None:
        return list(ctx.state.corpus.passage_ids)
    return [p.id for p in corpus.passages()]


def scope_passages(ctx: Any) -> list[Any]:
    corpus = ctx.cap("corpus")
    return [corpus.passage(pid) for pid in scope_passage_ids(ctx) if corpus.has_passage(pid)]


def focus_term_ids(ctx: Any) -> list[str]:
    """Canonical lexicon ids for the goal's focus terms plus terms named in the question."""
    pack = ctx.cap("domain")
    lex = pack.lexicon
    out: list[str] = []
    goal = ctx.goal
    if goal is None:
        return out
    for surface in goal.focus_terms:
        tid = surface if ":" in surface else lex.canonical(surface)
        if tid and tid not in out:
            out.append(tid)
    norm = pack.variants.normalize_text(goal.question)
    for m in lex.match(norm, include_weak=False):
        if m.term_id not in out and m.category not in ("condition",):
            out.append(m.term_id)
    return out


def surface(term_id: str) -> str:
    return term_id.split(":", 1)[-1]


def surfaces_of(ctx: Any, term_id: str) -> list[str]:
    entry = ctx.cap("domain").lexicon.entry(term_id)
    forms = entry.surfaces() if entry else [surface(term_id)]
    return sorted(set(forms), key=lambda s: (-len(s), s))


def year_fn(ctx: Any) -> Any:
    return claim_year_fn(ctx.cap("corpus"), ctx.goal.time_basis if ctx.goal else None)


def period_binner(ctx: Any) -> Any:
    return binner(ctx.cap("domain"))


def cluster_fn(ctx: Any) -> Any:
    return author_clusters(ctx.cap("corpus"), list(ctx.state.lineage.values()))


def philological_confidence(ctx: Any, passage_id: str, start: int | None = None, end: int | None = None) -> float | None:
    assessment = ctx.state.philology.get(passage_id)
    if assessment is None:
        return None
    value = assessment.philological_confidence
    if start is not None and end is not None:
        contested = assessment.contested_at(start, end)
        if contested:
            value = min([value] + [c.base_probability() for c in contested])
    return round(value, 4)


def locate(ctx: Any, passage_id: str, quote: str) -> tuple[int, int] | None:
    """Find a quote verbatim (or after length-preserving variant normalisation) inside a passage."""
    corpus = ctx.cap("corpus")
    if not quote or not corpus.has_passage(passage_id):
        return None
    text = corpus.passage(passage_id).text
    idx = text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    normalize = ctx.cap("domain").variants.normalize_text
    idx = normalize(text).find(normalize(quote))
    if idx >= 0 and len(normalize(quote)) == len(quote):
        return idx, idx + len(quote)
    return None


def evidence_record(ctx: Any, passage_id: str, start: int, end: int, *, method: str, stance: Stance = Stance.NEUTRAL,
                    hypothesis_id: str | None = None, claim: Claim | None = None, query: str | None = None,
                    score: float | None = None, note: str = "", textual: float | None = None) -> EvidenceRecord:
    corpus = ctx.cap("corpus")
    passage = corpus.passage(passage_id)
    semantic = None
    if claim is not None:
        probs = [r.probability for r in ctx.state.term_resolutions.values()
                 if r.passage_id == passage_id and r.start >= claim.start and r.end <= claim.end]
        semantic = round(min(probs), 4) if probs else 0.9
    return EvidenceRecord(
        id=stable_id("evd", passage_id, start, end, hypothesis_id, stance.value),
        passage_id=passage_id,
        book_id=passage.book_id,
        edition_id=passage.edition_id,
        locator=passage.locator,
        quote=passage.text[start:end],
        start=start,
        end=end,
        agent=ctx.actor.id,
        retrieval_method=method,
        claim_id=claim.id if claim else None,
        hypothesis_id=hypothesis_id,
        stance=stance,
        retrieval_score=score,
        query=query,
        extraction_model=(claim.extraction.model or claim.extraction.method) if claim else None,
        transformation_history=["normalize:variants", method] + ([f"claim:{claim.extraction.rule or claim.extraction.method}"] if claim else []),
        temporal=passage.temporal,
        confidence=ConfidenceVector(
            textual=textual if textual is not None else (claim.extraction.confidence if claim else 0.7),
            philological=philological_confidence(ctx, passage_id, start, end),
            semantic=semantic,
            extraction=claim.extraction.confidence if claim else None,
        ),
        note=note,
    )


def evidence_from_claim(ctx: Any, claim: Claim, *, hypothesis_id: str | None, stance: Stance = Stance.SUPPORTS,
                        method: str = "claim") -> EvidenceRecord:
    return evidence_record(ctx, claim.passage_id, claim.start, claim.end, method=method, stance=stance,
                           hypothesis_id=hypothesis_id, claim=claim)


def block(ctx: Any, hook: str, point: str, reason: str, subject: str = "") -> None:
    ctx.session.emit(EventType.HOOK_BLOCKED, {"hook": hook, "point": point, "reason": reason, "subject": subject},
                     actor=ctx.actor.id, task_id=ctx.task.id)


def research_window(ctx: Any) -> tuple[float | None, float | None, set[str]]:
    """(after, before, excluded books) that every whole-corpus query must respect: the contract's temporal
    scope, its hold-out (nothing at or after the hold-out year may be seen) and its book exclusions."""
    goal = ctx.goal
    after = before = None
    if goal is not None and goal.temporal_scope is not None:
        after, before = goal.temporal_scope.start, goal.temporal_scope.end + 1
    if goal is not None and goal.holdout_after is not None:
        before = goal.holdout_after if before is None else min(before, goal.holdout_after)
    excluded = set(ctx.state.corpus.excluded) if ctx.state.corpus is not None else set()
    if goal is not None:
        excluded |= set(goal.corpus.exclude_books)
    return after, before, excluded


def whole_corpus(ctx: Any) -> bool:
    """Large corpora answer absence / later-attestation questions from the whole store, not the frame."""
    return bool(getattr(ctx.cap("corpus"), "large", False))


def _candidate_passages(ctx: Any, lefts: list[str], rights: list[str], after: float | None, before: float | None,
                        level: str) -> list[Any]:
    corpus = ctx.cap("corpus")
    if not whole_corpus(ctx):
        return scope_passages(ctx)
    lo, hi, excluded = research_window(ctx)
    after = lo if after is None else (after if lo is None else max(after, lo))
    before = hi if before is None else (before if hi is None else min(before, hi))
    ids = corpus.near(lefts, rights, distance=40 if level == "sentence" else 2000, after=after, before=before)
    return [p for p in corpus.passages_by_id(ids) if p.book_id not in excluded and p.kind != "toc"]


def co_mentions(ctx: Any, left: str, right: str, *, after: float | None = None, before: float | None = None,
                exclude_passages: set[str] | None = None, level: str = "sentence") -> list[tuple[str, int, int]]:
    """Passages mentioning both terms in one sentence (or anywhere in the passage with ``level="passage"``);
    returns (passage, start, end) of the sentence that mentions the left term.  The search space is the
    frame for a small corpus and the whole store (within the contract's window) for a large one."""
    corpus = ctx.cap("corpus")
    pack = ctx.cap("domain")
    normalize = pack.variants.normalize_text
    lefts = [normalize(s) for s in surfaces_of(ctx, left) if len(s) > 1 or left.startswith("herb:")]
    rights = [normalize(s) for s in surfaces_of(ctx, right) if len(s) > 1 or right.startswith("herb:")]
    out = []
    for p in _candidate_passages(ctx, lefts, rights, after, before, level):
        if exclude_passages and p.id in exclude_passages:
            continue
        y = corpus.year(p)
        if after is not None and (y is None or y < after):
            continue
        if before is not None and (y is None or y >= before):
            continue
        norm = normalize(p.text)
        sentences = _sentences(norm) if p.punctuation != "none" else _segmented_sentences(ctx, norm)
        if level == "passage":
            if any(s in norm for s in lefts) and any(s in norm for s in rights):
                for sentence_start, sentence in sentences:
                    if any(s in sentence for s in lefts):
                        out.append((p.id, sentence_start, sentence_start + len(sentence)))
                        break
            continue
        for sentence_start, sentence in sentences:
            li = next((sentence.find(s) for s in lefts if s in sentence), -1)
            ri = next((sentence.find(s) for s in rights if s in sentence), -1)
            if li >= 0 and ri >= 0:
                out.append((p.id, sentence_start, sentence_start + len(sentence)))
                break
    return out


def related_terms(ctx: Any, term_id: str) -> set[str]:
    """Broader and narrower lexicon terms (e.g. 太阳中风 ⊂ 太阳病, 中风)."""
    lex = ctx.cap("domain").lexicon
    out: set[str] = set()
    entry = lex.entry(term_id)
    if entry is not None:
        out |= {t for t in (lex.canonical(b) for b in entry.broader) if t}
    for e in lex.entries.values():
        if any(lex.canonical(b) == term_id for b in e.broader):
            out.add(e.term_id)
    out.discard(term_id)
    return out


def _segmented_sentences(ctx: Any, norm: str) -> list[tuple[int, str]]:
    """Sentences of unpunctuated text via the extractor's machine-segmentation view (source coordinates)."""
    segmenter = getattr(ctx.cap("extractor"), "segmenter", None)
    if segmenter is None:
        return _sentences(norm)
    view = segmenter.view(norm)
    out, start = [], 0
    for i, ch in enumerate(view.text + "。"):
        if ch in "。；！？":
            if i > start:
                a, b = view.to_source(start, i)
                if b > a:
                    out.append((a, norm[a:b]))
            start = i + 1
    return out or [(0, norm)]


def late_passage_count(ctx: Any, pivot: float) -> int:
    """Passages dated at or after ``pivot`` that an absence claim is tested against."""
    corpus = ctx.cap("corpus")
    if not whole_corpus(ctx):
        return sum(1 for p in scope_passages(ctx) if (corpus.year(p) or 0) >= pivot)
    _, before, _ = research_window(ctx)
    return corpus.count_range(after=pivot, before=before)


def _sentences(text: str) -> list[tuple[int, str]]:
    out, start = [], 0
    for i, ch in enumerate(text):
        if ch in "。；！？":
            out.append((start, text[start: i + 1]))
            start = i + 1
    if start < len(text):
        out.append((start, text[start:]))
    return out
