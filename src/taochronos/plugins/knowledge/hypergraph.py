"""Temporal Provenance Claim Hypergraph.

Each Claim is a hyperedge over typed term nodes (symptoms + pulse + pattern +
principle + formula …), carrying time, edition and provenance.  Pairwise views
(clique expansion) are derived on demand for algorithms that need them, but the
hyperedge stays the unit of record.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Callable, Iterable

from ...protocol.claims import Claim, ClaimRelation, Role

CONTENT_ROLES = (
    Role.DISEASE, Role.PATTERN, Role.SYMPTOM, Role.SIGN, Role.PULSE, Role.TONGUE, Role.PATHOGENESIS,
    Role.ETIOLOGY, Role.TREATMENT_PRINCIPLE, Role.TREATMENT_METHOD, Role.FORMULA, Role.HERB, Role.ORGAN,
    Role.CONDITION, Role.CONCEPT,
)


class ClaimHypergraph:
    def __init__(self, claims: Iterable[Claim] = (), year_fn: Callable[[Claim], float | None] | None = None) -> None:
        self.claims: dict[str, Claim] = {}
        self.by_term: dict[str, set[str]] = defaultdict(set)
        self.by_relation: dict[str, set[str]] = defaultdict(set)
        self.by_book: dict[str, set[str]] = defaultdict(set)
        self.by_passage: dict[str, set[str]] = defaultdict(set)
        self.year_fn = year_fn or (lambda c: c.year())
        for claim in claims:
            self.add(claim)

    # ------------------------------------------------------------ mutation
    def add(self, claim: Claim) -> None:
        if claim.id in self.claims:
            return
        self.claims[claim.id] = claim
        for term in self.members(claim, include_negated=True):
            self.by_term[term].add(claim.id)
        self.by_relation[claim.relation.value].add(claim.id)
        self.by_book[claim.book_id].add(claim.id)
        self.by_passage[claim.passage_id].add(claim.id)

    def __len__(self) -> int:
        return len(self.claims)

    # -------------------------------------------------------------- access
    @staticmethod
    def members(claim: Claim, *, include_negated: bool = False, include_optional: bool = True,
                include_inherited: bool = True, roles: Iterable[Role] | None = None) -> list[str]:
        wanted = set(roles) if roles is not None else set(CONTENT_ROLES)
        out: list[str] = []
        for a in claim.arguments:
            if a.role not in wanted or a.term_id is None:
                continue
            if a.negated and not include_negated:
                continue
            if a.qualifiers.get("optional") and not include_optional:
                continue
            if a.qualifiers.get("inherited") and not include_inherited:
                continue
            if a.qualifiers.get("outcome"):
                continue
            if a.term_id not in out:
                out.append(a.term_id)
        return out

    def year(self, claim: Claim) -> float | None:
        return self.year_fn(claim)

    def filter(
        self,
        *,
        relations: Iterable[ClaimRelation | str] | None = None,
        terms_all: Iterable[str] | None = None,
        terms_any: Iterable[str] | None = None,
        books: Iterable[str] | None = None,
        after: float | None = None,
        before: float | None = None,
    ) -> list[Claim]:
        ids: set[str] | None = None
        if terms_all:
            for t in terms_all:
                ids = set(self.by_term.get(t, set())) if ids is None else ids & self.by_term.get(t, set())
        if terms_any:
            union: set[str] = set()
            for t in terms_any:
                union |= self.by_term.get(t, set())
            ids = union if ids is None else ids & union
        if ids is None:
            ids = set(self.claims)
        if relations:
            rels = {r.value if isinstance(r, ClaimRelation) else r for r in relations}
            ids = {i for i in ids if self.claims[i].relation.value in rels}
        if books:
            bset = set(books)
            ids = {i for i in ids if self.claims[i].book_id in bset}
        out = []
        for i in ids:
            y = self.year(self.claims[i])
            if after is not None and (y is None or y < after):
                continue
            if before is not None and (y is None or y >= before):
                continue
            out.append(self.claims[i])
        return sorted(out, key=lambda c: (self.year(c) or 0, c.id))

    def term_timeline(self, term_id: str) -> list[tuple[float | None, str]]:
        return sorted(((self.year(self.claims[i]), i) for i in self.by_term.get(term_id, ())), key=lambda t: (t[0] or 0, t[1]))

    def degree(self, term_id: str) -> int:
        return len(self.by_term.get(term_id, ()))

    def terms(self, prefix: str | None = None) -> list[str]:
        return sorted(t for t in self.by_term if prefix is None or t.startswith(prefix))

    # --------------------------------------------------------- projections
    def cooccurrence(
        self,
        *,
        roles_a: Iterable[Role] | None = None,
        roles_b: Iterable[Role] | None = None,
        relations: Iterable[ClaimRelation | str] | None = None,
        after: float | None = None,
        before: float | None = None,
        include_optional: bool = True,
    ) -> Counter:
        """Clique expansion restricted to role pairs: counts of (a, b) co-membership in hyperedges."""
        ra = set(roles_a) if roles_a else set(CONTENT_ROLES)
        rb = set(roles_b) if roles_b else set(CONTENT_ROLES)
        counts: Counter = Counter()
        for claim in self.filter(relations=relations, after=after, before=before):
            left = self.members(claim, roles=ra, include_optional=include_optional)
            right = self.members(claim, roles=rb, include_optional=include_optional)
            for a in left:
                for b in right:
                    if a != b:
                        key = (a, b) if ra != rb else tuple(sorted((a, b)))
                        counts[key] += 1
        return counts

    def neighbors(self, term_id: str, *, roles: Iterable[Role] | None = None, k: int = 20,
                  after: float | None = None, before: float | None = None) -> list[tuple[str, int]]:
        counts: Counter = Counter()
        wanted = set(roles) if roles else None
        for cid in self.by_term.get(term_id, ()):
            claim = self.claims[cid]
            y = self.year(claim)
            if after is not None and (y is None or y < after):
                continue
            if before is not None and (y is None or y >= before):
                continue
            for other in self.members(claim, roles=wanted):
                if other != term_id:
                    counts[other] += 1
        return sorted(counts.items(), key=lambda t: (-t[1], t[0]))[:k]

    def transactions(self, relations: Iterable[ClaimRelation | str] = (ClaimRelation.INDICATED_FOR,),
                     after: float | None = None, before: float | None = None) -> list[tuple[str, list[str]]]:
        """(claim id, member terms) — the itemsets used by association-rule mining."""
        return [(c.id, self.members(c)) for c in self.filter(relations=relations, after=after, before=before)]
