"""Work kept, or done only when first asked for, changes nothing.

Lineage compares each passage in many pairs and keeps its comparable form and its prepared text; G3 keeps the lexicon's
terms of a passage for the claims it has; the claim hypergraph builds its indexes when one is first read.  Each is
compared here with the work done afresh: the same lineage edges, the same gate results, the same indexes in the same
order.
"""

from __future__ import annotations

import sys
import threading
import time

from taochronos.plugins.classics import intertext, reuse
from taochronos.plugins.classics.kept import LONGEST_KEPT, TextMemo
from taochronos.plugins.knowledge import hypergraph
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
    monkeypatch.setattr(detector._texts, "texts", 1)  # every form dropped as the next is kept: each computed afresh
    monkeypatch.setattr(detector.intertext._prepared, "texts", 1)
    detector._texts.clear()
    detector.intertext._prepared.clear()
    assert [e.to_dict() for e in builder.reuse_edges(passages)] == kept
    assert len(detector._texts) == 1 and len(detector.intertext._prepared) == 1


def test_a_memo_holds_so_many_texts_and_characters_and_no_long_text():
    memo: TextMemo[int] = TextMemo(texts=3, chars=100)
    long = "黄" * (LONGEST_KEPT + 1)
    assert memo.put(long, 7) == 7 and long not in memo and len(memo) == 0  # given back, never kept
    for i in range(3):
        memo.put(str(i) * 30, i)
    assert len(memo) == 3 and memo.get("1" * 30) == 1
    memo.put("x", 9)  # a fourth text: all go, then it is kept
    assert len(memo) == 1 and memo.get("x") == 9 and memo.get("0" * 30) is None
    memo.put("y" * 60, 1)
    memo.put("z" * 40, 2)  # 61 + 40 would pass 100 characters
    assert len(memo) == 1 and memo.get("z" * 40) == 2


def test_a_memo_shared_by_threads_keeps_its_bounds_and_one_value_for_a_text():
    """The analyzers are shared by the server's threads: a text several of them worked at once has one value while it
    is kept, and however their puts fall no more characters are held than the bound, counted as they are."""

    def together(work) -> None:
        start = threading.Barrier(8)
        threads = [threading.Thread(target=lambda k=k: (start.wait(), work(k))) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    memo: TextMemo[object] = TextMemo(texts=100, chars=5_000)
    given: list[object] = []
    together(lambda k: given.append(memo.put("shared", object())))
    assert len(set(map(id, given))) == 1 and memo.get("shared") is given[0]  # the first kept, handed to all eight

    most: list[int] = []

    def fill(k: int) -> None:
        for i in range(3_000):
            memo.put(f"{k}:{i}".ljust(40, "x"), i)
            if i % 50 == 0:
                most.append(sum(map(len, list(memo._kept))))

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # the threads change places as often as they can
    try:
        together(fill)
    finally:
        sys.setswitchinterval(interval)
    assert max(most) <= 5_000 and memo._held == sum(map(len, memo._kept)) <= 5_000 and len(memo) <= 100


def test_a_callers_long_text_is_prepared_as_ever_and_not_kept(harness):
    """study.reuse and the pair form prepare the caller's own texts, of any length: those are worked each time, as
    before the passages' work was kept, and only a passage's length is kept."""
    detector = harness.capabilities.get("reuse")
    an = detector.intertext
    text = "黄芪补气，" * 2_000  # 10,000 characters
    first = an.prepare(text)
    assert text not in an._prepared and an.prepare(text) == first and an.prepare(text) is not first
    passage = harness.corpus.passages()[0].text
    assert an.prepare(passage) is an.prepare(passage)  # a passage's is kept
    assert detector._comparable(text) == detector._comparable(text) and text not in detector._texts


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


def test_a_graph_is_made_without_the_lock_every_graph_shares(harness):
    """The graph route makes a ClaimHypergraph for every search, and the lock that keeps a shared graph's indexes whole
    is the process's one: making a graph takes it not at all (it doubled the making, and would have queued every search
    behind another graph's indexes being built), and keeps the claims as add() does — the first of an id."""
    claims = harness.capabilities.get("knowledge").claims()
    made: list[ClaimHypergraph] = []
    with hypergraph._INDEXING:  # held, as while some graph's indexes are built
        maker = threading.Thread(target=lambda: made.append(ClaimHypergraph(claims + claims[:5])))
        maker.start()
        maker.join(10)
        assert made, "making a graph waited for the lock"
    slow = ClaimHypergraph()
    for c in claims + claims[:5]:
        slow.add(c)
    assert list(made[0].claims) == list(slow.claims) and all(made[0].claims[k] is slow.claims[k] for k in slow.claims)
    assert {n: dict(getattr(made[0], n)) for n in INDEXES} == {n: dict(getattr(slow, n)) for n in INDEXES}


def test_hypergraph_indexes_read_by_threads_at_once_are_whole(harness, monkeypatch):
    """A graph the server's threads share: those that read an index while it is first built wait for it whole."""
    claims = harness.capabilities.get("knowledge").claims()[:200]
    whole = sum(len(ids) for ids in ClaimHypergraph(claims).by_term.values())
    members = ClaimHypergraph.members
    monkeypatch.setattr(ClaimHypergraph, "members", staticmethod(lambda c, **kw: (time.sleep(0.0002), members(c, **kw))[1]))
    for _ in range(5):  # a build of some 50 ms: the readers come while it runs
        hg = ClaimHypergraph(claims)
        start, seen = threading.Barrier(8), []

        def read() -> None:
            start.wait()
            try:
                seen.append(sum(len(ids) for ids in hg.by_term.values()))
            except RuntimeError as exc:  # read while another thread filled it
                seen.append(str(exc))

        readers = [threading.Thread(target=read) for _ in range(8)]
        for t in readers:
            t.start()
        for t in readers:
            t.join()
        assert seen == [whole] * 8
