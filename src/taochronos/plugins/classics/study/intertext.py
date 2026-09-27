"""语义复用与思想传播 — how later books reuse a passage, and how a work was taken up, period by period.

``reuse`` finds a passage's reuses across the corpus in two stages.  Candidates: the concordance's character probes
(wording) and co-occurring concepts (content: the passage's rarest concepts, or their synonyms, found near each other
in another passage) — high recall, no proof.  Labels: each candidate's reused span is located and typed by the
transparent rules of ``science.semantic_reuse`` (直接引用, 近似转录, 节略, 撮要, 转述, 解释性改写, 引而驳之, 套语相似),
with the features and the rule that fired.

``transmission`` does this for the clauses of a work and aggregates the typed edges into the work's reception: which
later works carry how much of it and how (retained, transformed, disputed), how the balance moves across periods,
and the channels — later works whose wording of a clause follows an intermediate work rather than the source.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from ....science.semantic_reuse import LABELS, classify, intermediaries, transmission_network
from ..intertext import IntertextAnalyzer, Prepared
from .base import StudyBase, dated

_CLAUSE_END = re.compile(r"[。；！？]")
MAX_CONCEPT_DF = 60000  # a concept this common finds everything and proves nothing


class IntertextStudy:
    def __init__(self, base: StudyBase, concordance: Any, stemma: Any) -> None:
        self.b = base
        self.concordance = concordance
        self.stemma = stemma
        self.an = IntertextAnalyzer(base.pack, base.corpus)

    # ------------------------------------------------------------ one pair
    def compare(self, source: str, target: str, *, source_id: str | None = None, target_id: str | None = None) -> dict[str, Any]:
        """The reuse type of ``source`` in ``target`` (texts, or passage ids with ``*_id``), with its features."""
        s_text = self.b.corpus.passage(source_id).text if source_id else source
        t_text = self.b.corpus.passage(target_id).text if target_id else target
        out = self.an.label(s_text, t_text)
        out["source"] = self.b.witness(self.b.corpus.passage(source_id)) if source_id else {"quote": s_text[:200]}
        out["target"] = self.b.witness(self.b.corpus.passage(target_id)) if target_id else {"quote": t_text[:200]}
        return out

    # ------------------------------------------------------------ candidates
    def _forms(self, term_id: str) -> list[str]:
        entry = self.b.pack.lexicon.entry(term_id)
        forms = [entry.term, *entry.aliases, *entry.synonyms] if entry else []
        return list(dict.fromkeys(f for f in forms if len(f) >= 2))[:6] or ([entry.term] if entry else [])

    def _concept_candidates(self, src: Prepared, exclude: str | None, limit: int) -> Counter:
        """Passages where two of the source's rarest concepts (in any of their written forms) occur near each other."""
        first: dict[str, Any] = {}
        for c in src.concepts:
            first.setdefault(c.term_id, c)
        usable = [c for c in first.values() if 0 < self.an.df(c.surface) <= MAX_CONCEPT_DF]
        if len(usable) < 2:
            return Counter()
        ranked = sorted(usable, key=lambda c: (self.an.df(c.surface), c.term_id))[:4]
        distance = max(24, 2 * len(src.han))
        hits: Counter = Counter()
        for x, y in combinations(ranked, 2):
            for pid in self.b.corpus.near(self._forms(x.term_id), self._forms(y.term_id), distance=distance, limit=limit * 2):
                if pid != exclude:
                    hits[pid] += 1
        need = 1 if len(ranked) == 2 else 2
        return Counter({pid: k for pid, k in hits.items() if k >= need})

    # ------------------------------------------------------------ one passage across the corpus
    def reuse(self, text: str | None = None, passage_id: str | None = None, *, semantic: bool = True,
              max_candidates: int = 1200, limit: int = 300, include_uncertain: bool = False,
              exclude_books: list[str] | None = None) -> dict[str, Any]:
        b = self.b
        qp = b.corpus.passage(passage_id) if passage_id else None
        raw = text if text else (qp.text if qp else "")
        src = self.an.prepare(raw)
        if len(src.han) < 4:
            raise ValueError("the passage needs at least four characters")
        if len(src.han) > 400:
            src = self.an.prepare(raw[: src.index[399] + 1])
        char_ids, probes = self.concordance._candidates(src.han, passage_id, max_candidates)
        concept_hits = self._concept_candidates(src, passage_id, max_candidates) if semantic else Counter()
        ordered = list(dict.fromkeys(char_ids + [pid for pid, _ in concept_hits.most_common()]))
        excluded = set(exclude_books or [])
        q_years = b.years(qp) if qp else None
        q_book = b.corpus.books.get(qp.book_id) if qp else None
        q_work = (getattr(q_book, "work", None) or qp.book_id) if qp else None
        by_wording = set(char_ids)
        hits: list[dict[str, Any]] = []
        for p in b.passages(ordered[:max_candidates]):
            if p.book_id in excluded or p.kind == "toc":
                continue
            t = self.an.prepare(p.text)
            f, where = self.an.features(src, t)
            if not where["text"]:
                continue
            w_years = b.years(p)
            direction = _direction(q_years, w_years)
            if direction == "earlier":  # the candidate is older: it is the source, the query passage reuses it
                f, _ = self.an.features(self.an.prepare(where["text"]), src)
            label = classify(f)
            if label["label"] == "uncertain" and not include_uncertain:
                continue
            ra, rb = where["raw"]
            w = b.witness(p, start=ra, end=rb, width=0)
            w["quote"] = p.text[ra:rb]
            book = b.corpus.books.get(p.book_id)
            work = getattr(book, "work", None) or p.book_id
            same = q_work is not None and work == q_work
            w.update({k: label[k] for k in ("label", "label_zh", "mode", "rule", "confidence", "citation", "reasons")})
            w["relation"] = "同书异本" if same else ("引文" if f.attribution else "互见")
            w["direction"] = direction
            w["features"] = {k: getattr(f, k) for k in ("cov_source", "cov_target", "concept_cov", "order", "length_ratio",
                                                        "formulaic_share", "similarity", "attribution", "opposition",
                                                        "interpretation", "concepts_shared", "concepts_partial")}
            w["found_by"] = [k for k, ok in (("wording", p.id in by_wording), ("concepts", p.id in concept_hits)) if ok]
            hits.append(w)
        hits.sort(key=lambda w: (dated(w["years"]), w["passage_id"]))
        hits = hits[:limit]
        by_label = Counter(w["label"] for w in hits)
        periods: dict[str, Counter] = defaultdict(Counter)
        for w in hits:
            periods[w["period"] or "未定"][w["label"]] += 1
        first = {}
        for w in hits:
            first.setdefault(w["label"], {k: w[k] for k in ("passage_id", "title", "locator", "years", "quote")})
        return {
            "query": raw[:400], "normalized": src.han, "passage": b.witness(qp) if qp else None,
            "concepts": [{"term_id": c.term_id, "surface": c.surface, "category": c.category} for c in src.concepts],
            "probes": probes, "candidates": {"wording": len(char_ids), "concepts": len(concept_hits), "examined": min(len(ordered), max_candidates)},
            "hits": hits,
            "summary": {"reuses": len(hits), "works": len({w['work'] or w['book_id'] for w in hits}),
                        "by_label": {k: by_label[k] for k in LABELS if by_label.get(k)},
                        "by_label_zh": {LABELS[k]: by_label[k] for k in LABELS if by_label.get(k)},
                        "by_period": {per: dict(c) for per, c in periods.items()},
                        "by_relation": dict(Counter(w["relation"] for w in hits)),
                        "found_by_concepts_only": sum(1 for w in hits if w["found_by"] == ["concepts"]),
                        "first_of_each_type": first},
            "note": "candidates come from shared wording and co-occurring concepts and prove nothing; each label comes from "
                    "the rules of science.semantic_reuse over the aligned span (features and rule given with every hit)",
        }

    # ------------------------------------------------------------ a work's reception
    def clauses(self, work: str, *, n: int = 40, min_chars: int = 10) -> tuple[list[str], list[tuple[str, str]]]:
        """The base witness of a work (its earliest dated transcription) and ``n`` clauses spread evenly over its main
        text: (passage id, clause), each with at least ``min_chars`` characters and two concepts."""
        sets = self.stemma.witness_sets(work)
        base = min(sets, key=lambda ids: (dated(_years(self.b, ids[0])), ids[0]))
        found: list[tuple[str, str]] = []
        for bid in base:
            for pid, _, _, text in self.stemma._rows(bid):
                for piece in _CLAUSE_END.split(text):
                    piece = piece.strip()
                    p = self.an.prepare(piece)
                    if len(p.han) >= min_chars and len({c.term_id for c in p.concepts}) >= 2:
                        found.append((pid, piece))
        if len(found) > n:
            step = len(found) / n
            found = [found[int(i * step)] for i in range(n)]
        return base, found

    def transmission(self, work: str, *, clauses: int = 40, max_candidates: int = 400, cache_dir: str | None = None) -> dict[str, Any]:
        key = hashlib.sha1(json.dumps([work, clauses, max_candidates, self.b.signature()["corpus_digest"]],
                                      ensure_ascii=False).encode()).hexdigest()[:16]
        path = Path(cache_dir) / f"transmission-{key}.json" if cache_dir else None
        if path is not None and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        base, chosen = self.clauses(work, n=clauses)
        base_book = self.b.corpus.books.get(base[0])
        source_work = getattr(base_book, "work", None) or base[0]
        edges: list[dict[str, Any]] = []
        channel_input: list[dict[str, Any]] = []
        same_work: Counter = Counter()
        for k, (pid, clause) in enumerate(chosen):
            res = self.reuse(clause, pid, max_candidates=max_candidates, limit=200, exclude_books=base)
            targets = []
            for h in res["hits"]:
                if h["relation"] == "同书异本":
                    same_work[h["title"]] += 1
                    continue
                if h["direction"] == "earlier" or h["mode"] == "none":
                    continue
                target = h["work"] or h["book_id"]
                year = h["years"][0] if h["years"] else None
                edges.append({"clause": k, "target_work": target, "target_title": h["title"], "year": year,
                              "period": h["period"], "label": h["label"], "passage_id": h["passage_id"]})
                targets.append({"work": target, "title": h["title"], "year": year, "text": self.an.prepare(h["quote"]).han})
            channel_input.append({"source": self.an.prepare(clause).han, "targets": targets})
        network = transmission_network(edges)
        out = {
            "work": source_work, "title": base_book.title if base_book else work, "base": base,
            "clauses": [{"passage_id": pid, "text": text} for pid, text in chosen],
            "edges": len(edges), **network,
            "channels": intermediaries(channel_input, _bigram_similarity),
            "same_work_witnesses": dict(same_work.most_common()),
            "note": "each edge is one clause of the work reused in a later book, typed by the semantic-reuse rules; "
                    "retained = quotation, transcription or abridgement; transformed = summary, paraphrase or "
                    "reinterpretation; disputed = quoted to be refuted.  A channel: a later work whose wording of a "
                    "clause is closer to an intermediate work's than to the source's (evidence of the route, not proof)",
        }
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out


def _years(b: StudyBase, book_id: str) -> list[float] | None:
    book = b.corpus.books.get(book_id)
    rng = getattr(book, "composition", None)
    return [rng.start, rng.end] if rng is not None else None


def _direction(query: tuple[float, float] | None, other: tuple[float, float] | None) -> str:
    """Is the other passage later than the query, earlier, or can the dates not tell?"""
    if query is None or other is None:
        return "later" if query is None else "undetermined"
    if other[0] > query[1]:
        return "later"
    if other[1] < query[0]:
        return "earlier"
    return "undetermined"


def _bigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity of the character bigrams of two normalised Han strings."""
    ga = {a[i: i + 2] for i in range(len(a) - 1)}
    gb = {b[i: i + 2] for i in range(len(b) - 1)}
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


__all__ = ["IntertextStudy"]
