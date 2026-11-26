"""Work kept, or done only when first asked for, changes nothing.

Lineage compares each passage in many pairs and keeps its comparable form and its prepared text; G3 keeps the lexicon's
terms of a passage for the claims it has; the claim hypergraph builds its indexes when one is first read.  Each is
compared here with the work done afresh: the same lineage edges, the same gate results, the same indexes in the same
order.
"""

from __future__ import annotations

from taochronos.plugins.classics import intertext, reuse
from taochronos.plugins.knowledge.hypergraph import ClaimHypergraph
from taochronos.verification.gates import GateEvaluator

INDEXES = ("by_term", "by_relation", "by_book", "by_passage")


def test_lineage_edges_whether_the_texts_are_kept_or_not(harness, monkeypatch):
    builder, detector = harness.capabilities.get("lineage"), harness.capabilities.get("reuse")
    passages = harness.corpus.passages()
    detector._texts.clear()
    detector.intertext._prepared.clear()
    kept = [e.to_dict() for e in builder.reuse_edges(passages)]
    assert kept and len(detector._texts) > 100 and detector.intertext._prepared
    monkeypatch.setattr(reuse, "TEXTS_KEPT", 1)  # every form dropped as the next is kept: each computed afresh
    monkeypatch.setattr(intertext, "PREPARED_KEPT", 1)
    detector._texts.clear()
    detector.intertext._prepared.clear()
    assert [e.to_dict() for e in builder.reuse_edges(passages)] == kept
    assert len(detector._texts) == 1 and len(detector.intertext._prepared) == 1


def test_g3_whether_a_passages_terms_are_kept_or_not(harness, monkeypatch):
    claims = sorted(harness.capabilities.get("knowledge").claims(), key=lambda c: c.id)

    def g3_results() -> tuple[list[dict], int]:
        gates = GateEvaluator(harness.corpus, harness.philology, harness.pack)
        return [gates.g3(c).to_dict() for c in claims], len(gates._contexts)

    kept, texts = g3_results()
    assert texts and any(r["status"] == "warn" for r in kept)
    monkeypatch.setattr(GateEvaluator, "_context", lambda self, norm: {m.entry.term for m in self.pack.lexicon.match(norm)})
    assert g3_results()[0] == kept


def test_hypergraph_indexes_built_when_first_read(harness):
    claims = harness.capabilities.get("knowledge").claims()
    plain: dict[str, dict[str, set[str]]] = {name: {} for name in INDEXES}
    seen: set[str] = set()
    for c in claims:  # the indexes the plain way: every claim indexed as it comes, the first of an id kept
        if c.id in seen:
            continue
        seen.add(c.id)
        for term in ClaimHypergraph.members(c, include_negated=True):
            plain["by_term"].setdefault(term, set()).add(c.id)
        plain["by_relation"].setdefault(c.relation.value, set()).add(c.id)
        plain["by_book"].setdefault(c.book_id, set()).add(c.id)
        plain["by_passage"].setdefault(c.passage_id, set()).add(c.id)
    half = len(claims) // 2
    hg = ClaimHypergraph(claims[:half])
    assert not any(name in vars(hg) for name in INDEXES)  # nothing built until read
    assert hg.terms()  # read: built from the first half
    for c in claims[half:] + claims[:1]:  # then kept up to date, a repeated id ignored
        hg.add(c)
    for name in INDEXES:
        index = getattr(hg, name)
        assert dict(index) == plain[name] and list(index) == list(plain[name]), name
    assert list(hg.claims) == list(dict.fromkeys(c.id for c in claims))
