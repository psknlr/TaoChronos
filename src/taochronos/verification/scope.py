"""The research scope, enforced where data is read.

A corpus manifest splits a session's material into **exploration** passages and three **withheld** sets: the hold-out
(after the contract's hold-out year), the **confirmation** set (kept back to re-test what exploration found) and
**expert-only** material.  What a reader may see depends on its principal:

=========  ===============================================================
agent      exploration only
validator  exploration and confirmation (the confirmation step reads it)
human      everything
kernel     everything
=========  ===============================================================

Three layers enforce it, none of which trusts a tool to remember:

1. **Scoped capabilities** — a tool's ``ctx.cap("corpus")`` is a :class:`ScopedCorpusView`: a withheld passage does
   not exist from it (``has_passage`` is false, ``passage`` raises, lists and searches leave it out).  The retriever
   and the knowledge index are wrapped the same way.
2. **Argument guard** (BeforeToolCall) — a call whose arguments name a withheld passage is refused before it runs.
3. **Result firewall** (AfterToolCall) — a result that names a withheld passage is withheld (quarantined), whatever
   route produced it.

This is a *tool- and evidence-level* hold-out: it keeps withheld witnesses out of what agents read, cite and commit.
It is not a blind historical prediction — the models behind the agents may have read these texts in training — and it
works on witnesses, not strings: the same sentence in an exploration edition is legitimately visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..kernel.hooks import HookContext, HookResult

TIERS = ("holdout", "confirmation", "expert_only")
# which withheld tiers each principal may read
READS = {"agent": frozenset(), "validator": frozenset({"confirmation"}), "human": frozenset(TIERS), "kernel": frozenset(TIERS)}


class ScopeViolation(PermissionError):
    """A read of material the reader's scope withholds."""


@dataclass(frozen=True)
class ReadingScope:
    """What one reader may see in one session: ``allowed`` passage ids (None: no manifest, everything) and the
    withheld ids it may not see, with their tier."""

    allowed: frozenset[str] | None
    withheld: dict[str, str] = field(default_factory=dict)

    def permits(self, passage_id: str) -> bool:
        if passage_id in self.withheld:
            return False
        return self.allowed is None or passage_id in self.allowed

    def why(self, passage_id: str) -> str:
        tier = self.withheld.get(passage_id)
        if tier:
            return {"holdout": "held out (after the contract's hold-out year)", "confirmation": "kept for confirmation",
                    "expert_only": "expert-only material"}[tier]
        return "outside the research scope"


_CACHE: dict[tuple[int, str], tuple[Any, ReadingScope]] = {}


def scope_for(state: Any, principal: str) -> ReadingScope | None:
    """The reading scope of a principal in a session state; None when the session has no manifest yet."""
    manifest = getattr(state, "corpus", None) if state is not None else None
    if manifest is None:
        return None
    key = (id(manifest), principal)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is manifest:
        return hit[1]
    reads = READS.get(principal, frozenset())
    tiers = {"holdout": manifest.holdout_passage_ids, "confirmation": getattr(manifest, "confirmation_passage_ids", []),
             "expert_only": getattr(manifest, "expert_only_passage_ids", [])}
    withheld: dict[str, str] = {}
    allowed = set(manifest.passage_ids)
    for tier in TIERS:
        for pid in tiers[tier]:
            if tier in reads:
                allowed.add(pid)
            else:
                withheld.setdefault(pid, tier)
    scope = ReadingScope(None if principal in ("human", "kernel") else frozenset(allowed), withheld)
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = (manifest, scope)
    return scope


def context_scope(ctx: Any) -> ReadingScope | None:
    """The scope of a tool call: the calling actor's principal in the calling session."""
    session = getattr(ctx, "session", None)
    if session is None:
        return None
    return scope_for(session.state, getattr(getattr(ctx, "actor", None), "principal", "agent"))


# ------------------------------------------------------------------ views
class ScopedCorpusView:
    """A corpus as one reader may see it.  Every passage read path is filtered; everything else (books, dates,
    normalisation) is the corpus's own."""

    def __init__(self, corpus: Any, scope: ReadingScope) -> None:
        self._corpus = corpus
        self._scope = scope

    # the passage read paths
    def has_passage(self, passage_id: str) -> bool:
        return self._scope.permits(passage_id) and self._corpus.has_passage(passage_id)

    def passage(self, passage_id: str) -> Any:
        if not self._scope.permits(passage_id):
            raise ScopeViolation(f"passage {passage_id} is {self._scope.why(passage_id)}")
        return self._corpus.passage(passage_id)

    def passages_by_id(self, ids: Iterable[str]) -> list[Any]:
        return self._corpus.passages_by_id([i for i in ids if self._scope.permits(i)])

    def passage_ids(self) -> list[str]:
        return [i for i in self._corpus.passage_ids() if self._scope.permits(i)]

    def around(self, passage_id: str) -> tuple[str | None, str | None, str | None]:
        before, at, after = (x if x is not None and self._scope.permits(x) else None for x in self._corpus.around(passage_id))
        return before, at, after

    def passages(self, *args: Any, **kwargs: Any) -> list[Any]:
        return [p for p in self._corpus.passages(*args, **kwargs) if self._scope.permits(p.id)]

    def iter_passages(self, *args: Any, **kwargs: Any) -> Any:
        return (p for p in self._corpus.iter_passages(*args, **kwargs) if self._scope.permits(p.id))

    def contains(self, *args: Any, **kwargs: Any) -> list[str]:
        limit = kwargs.pop("limit", None)
        hits = [pid for pid in self._corpus.contains(*args, **kwargs) if self._scope.permits(pid)]
        return hits[:limit] if limit else hits

    def count(self, surface: str, **kwargs: Any) -> int:
        return len(self.contains(surface, **kwargs))

    def search(self, *args: Any, **kwargs: Any) -> list[tuple[str, float]]:
        limit = kwargs.pop("limit", 200)
        hits = self._corpus.search(*args, limit=max(limit * 4, limit + len(self._scope.withheld)), **kwargs)
        return [h for h in hits if self._scope.permits(h[0])][:limit]

    def near(self, *args: Any, **kwargs: Any) -> list[str]:
        limit = kwargs.pop("limit", None)
        hits = [pid for pid in self._corpus.near(*args, **kwargs) if self._scope.permits(pid)]
        return hits[:limit] if limit else hits

    def subset(self, passage_ids: Iterable[str]) -> Any:
        return self._corpus.subset([i for i in passage_ids if self._scope.permits(i)])

    def count_range(self, **kwargs: Any) -> int:
        if self._scope.allowed is None and not self._scope.withheld:
            return self._corpus.count_range(**kwargs)
        return len(self.passages(**kwargs)) if not getattr(self._corpus, "large", False) else \
            max(0, self._corpus.count_range(**kwargs) - len(self._scope.withheld))

    def book_passage_count(self, book_id: str) -> int:
        return self._corpus.book_passage_count(book_id)

    def __len__(self) -> int:
        return len(self._scope.allowed) if self._scope.allowed is not None else len(self._corpus)

    @property
    def unscoped(self) -> Any:  # for kernel code that must see the corpus as it is (never handed to agents)
        return self._corpus

    def __getattr__(self, name: str) -> Any:
        # books, year, year_range, basis_for, book, title_index, witnesses, normalize, large, stats, external …
        return getattr(self._corpus, name)


class ScopedRetriever:
    """The retriever with the reader's scope applied to every search."""

    def __init__(self, retriever: Any, scope: ReadingScope) -> None:
        self._retriever = retriever
        self._scope = scope

    def search(self, *args: Any, allowed: set[str] | None = None, **kwargs: Any) -> Any:
        if self._scope.allowed is not None:
            allowed = set(self._scope.allowed) if allowed is None else set(allowed) & self._scope.allowed
        query, hits = self._retriever.search(*args, allowed=allowed, **kwargs)
        return query, [h for h in hits if self._scope.permits(h.passage_id)]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._retriever, name)


class ScopedKnowledge:
    """The corpus-wide claim and lineage index with withheld passages left out."""

    def __init__(self, knowledge: Any, scope: ReadingScope) -> None:
        self._knowledge = knowledge
        self._scope = scope

    def claims(self) -> list:
        return [c for c in self._knowledge.claims() if self._scope.permits(c.passage_id)]

    def claims_for(self, passage_ids: Iterable[str]) -> list:
        return self._knowledge.claims_for([p for p in passage_ids if self._scope.permits(p)])

    def lineage(self, passage_ids: Iterable[str] | None = None) -> list:
        ids = None if passage_ids is None else [p for p in passage_ids if self._scope.permits(p)]
        edges = self._knowledge.lineage(ids) if ids is not None else self._knowledge.lineage()
        return [e for e in edges if all(self._scope.permits(p) for p in (e.source_passage, e.target_passage) if p)]

    def hypergraph(self, passage_ids: Iterable[str] | None = None) -> Any:
        if passage_ids is not None:
            return self._knowledge.hypergraph([p for p in passage_ids if self._scope.permits(p)])
        if self._scope.allowed is not None:
            return self._knowledge.hypergraph(sorted(self._scope.allowed))
        return self._knowledge.hypergraph()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._knowledge, name)


_WRAPPERS = {"corpus": ScopedCorpusView, "retriever": ScopedRetriever, "knowledge": ScopedKnowledge}


def scoped_capability(name: str, value: Any, ctx: Any, *, frame: bool = True) -> Any:
    """The capability a caller sees: wrapped in the caller's scope when the session has one.  Tools see the frame
    (the manifest's exploration passages); agent procedures (``frame=False``) may query the whole store — absence and
    later-attestation checks need it — but withheld material is removed for them just the same."""
    wrapper = _WRAPPERS.get(name)
    if wrapper is None:
        return value
    scope = context_scope(ctx)
    if scope is not None and not frame:
        scope = ReadingScope(None, scope.withheld)
    if scope is None or (scope.allowed is None and not scope.withheld):
        return value
    return wrapper(value, scope)


def capability_views() -> dict[str, Any]:
    return {name: (lambda value, ctx, _n=name: scoped_capability(_n, value, ctx)) for name in _WRAPPERS}


# ------------------------------------------------------------------ guards
def _strings(value: Any, limit: int = 200_000) -> Iterable[str]:
    """Every string in a (JSON-like) value — keys included — up to ``limit`` items."""
    stack = [value]
    seen = 0
    while stack and seen < limit:
        item = stack.pop()
        seen += 1
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for k, v in item.items():
                if isinstance(k, str):
                    yield k
                stack.append(v)
        elif isinstance(item, (list, tuple, set, frozenset)):
            stack.extend(item)
        elif hasattr(item, "__dataclass_fields__"):
            stack.extend(getattr(item, f) for f in item.__dataclass_fields__)
        elif hasattr(item, "passage_id"):  # retrieval hits and similar light objects
            stack.append(getattr(item, "passage_id"))


def withheld_mentions(value: Any, scope: ReadingScope, limit: int = 5) -> list[str]:
    """Withheld passage ids named anywhere in a value (as a whole string, or as the passage part of an id such as
    ``passage_id:start-end``)."""
    if not scope.withheld:
        return []
    found: list[str] = []
    for text in _strings(value):
        if len(text) > 300:
            continue
        candidate = text if text in scope.withheld else text.split(":", 1)[0] if ":" in text else None
        if candidate is not None and candidate in scope.withheld and candidate not in found:
            found.append(candidate)
            if len(found) >= limit:
                break
    return found


def scope_argument_guard(ctx: HookContext) -> HookResult | None:
    """BeforeToolCall: refuse a call whose arguments name a withheld passage."""
    session = ctx.session
    if session is None or ctx.actor is None:
        return None
    scope = scope_for(session.state, getattr(ctx.actor, "principal", "agent"))
    if scope is None:
        return None
    hits = withheld_mentions(ctx.subject, scope, limit=1)
    if hits:
        return HookResult(allow=False, reason=f"argument names passage {hits[0]}, which is {scope.why(hits[0])}")
    return None


def scope_result_firewall(ctx: HookContext) -> HookResult | None:
    """AfterToolCall: withhold a result that names a withheld passage, whatever produced it."""
    session = ctx.session
    outcome = ctx.subject
    if session is None or ctx.actor is None or outcome is None or not getattr(outcome, "ok", False):
        return None
    scope = scope_for(session.state, getattr(ctx.actor, "principal", "agent"))
    if scope is None or not scope.withheld:
        return None
    hits = withheld_mentions(outcome.result, scope)
    if hits:
        return HookResult(allow=False, reason=f"result names {len(hits)} withheld passage(s) (e.g. {hits[0]}: {scope.why(hits[0])})")
    return None
