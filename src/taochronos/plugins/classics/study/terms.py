"""术语源流 — the history of a term in numbers and in quotations.

For a term (with its aliases and variant forms) the whole store is counted period by period: the share of passages
that use it, with a Wilson interval, against the passages of that period (so a period with more surviving text does
not look more interested in the term), and a Cochran–Armitage test for a trend across the ordered periods.  Then the
earliest attestations (one per work), the terms it keeps company with in each period (collocates within a window,
ranked by how much more often they occur with it then than overall), the books where it is densest (where to read),
and — when the terminology knows the term — its period-bound senses and the modern concepts proposed as *candidates*
(never equivalences).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .base import StudyBase, dated, trend_test, wilson


class TermStudy:
    def __init__(self, base: StudyBase) -> None:
        self.b = base

    def _ids(self, form: str, after: float | None = None, before: float | None = None) -> list[str]:
        corpus = self.b.corpus
        if getattr(corpus, "large", False):
            return corpus.contains(form, after=after, before=before, verify=True)
        return corpus.contains(form, after=after, before=before, normalize=self.b.normalize)

    def run(self, term: str, *, window: int = 12, sample_per_period: int = 400, earliest: int = 8) -> dict[str, Any]:
        b = self.b
        term_id, forms = b.surfaces(term)
        keys = [b.normalize(f) for f, _ in forms if b.normalize(f)]
        totals = b.period_totals()
        rows = []
        ids_by_period: dict[str, list[str]] = {}
        for per in b.periods:
            ids: set[str] = set()
            for f, _ in forms:
                ids.update(self._ids(f, per.start, per.end))
            ids_by_period[per.id] = sorted(ids)
            n = totals[per.id]["passages"]
            k = len(ids)
            lo, hi = wilson(k, n)
            rows.append({"period": per.label, "id": per.id, "passages": k, "total": n,
                         "per_10k": round(10000 * k / n, 2) if n else None,
                         "ci_per_10k": [round(10000 * lo, 2), round(10000 * hi, 2)] if n else None,
                         "characters": totals[per.id]["characters"]})
        trend = trend_test([(r["passages"], r["total"]) for r in rows])
        # earliest attestations: one per work, in date order
        first: list[dict[str, Any]] = []
        seen_works: set[str] = set()
        for per in b.periods:
            for p in b.passages(ids_by_period[per.id][:400]):
                book = b.corpus.books.get(p.book_id)
                work = (getattr(book, "work", None) if book else None) or p.book_id
                if work in seen_works:
                    continue
                norm = b.normalize(p.text)
                pos = min((norm.find(k) for k in keys if norm.find(k) >= 0), default=-1)
                if pos < 0:
                    continue
                seen_works.add(work)
                first.append(b.witness(p, start=pos, end=pos + len(keys[0]), width=30))
            if len(first) >= earliest:
                break
        first.sort(key=lambda w: (dated(w["years"]), w["passage_id"]))
        collocates = self._collocates(ids_by_period, keys, term_id, window, sample_per_period)
        return {
            "term": {"term_id": term_id, "name": term, "forms": [{"form": f, "kind": k} for f, k in forms]},
            "periods": rows, "trend": {"z": trend[0], "p": trend[1]} if trend else None,
            "total_passages": sum(r["passages"] for r in rows), "earliest": first[:earliest],
            "collocates": collocates, "dense_books": self._dense_books(ids_by_period),
            "senses": self._senses(term), "notice": "频率为“含该词段落 / 该期全部段落”，括号内为 95% Wilson 区间；各期存世文献多寡不同，比例而非绝对数才可比较。",
        }

    def _collocates(self, ids_by_period: dict[str, list[str]], keys: list[str], term_id: str | None, window: int,
                    sample: int) -> list[dict[str, Any]]:
        b = self.b
        lex = b.pack.lexicon
        per_counts: dict[str, Counter] = {}
        overall: Counter = Counter()
        for per in b.periods:
            ids = ids_by_period[per.id]
            step = max(1, len(ids) // sample)
            counts: Counter = Counter()
            for p in b.passages(ids[::step][:sample]):
                norm = b.normalize(p.text)
                for k in keys:
                    for m in re.finditer(re.escape(k), norm):
                        ctx = norm[max(0, m.start() - window): m.start()] + "|" + norm[m.end(): m.end() + window]
                        for mention in lex.match(ctx):
                            if mention.entry.term_id == term_id or mention.weak or len(mention.surface) < 2:
                                continue
                            counts[mention.entry.term_id] += 1
            per_counts[per.id] = counts
            overall.update(counts)
        total_all = sum(overall.values()) or 1
        out = []
        for per in b.periods:
            counts = per_counts[per.id]
            total = sum(counts.values())
            if not total:
                continue
            scored = []
            for tid, n in counts.items():
                if n < 2:
                    continue
                lift = (n / total) / (overall[tid] / total_all)
                scored.append((n * math.log(1 + lift), tid, n, lift))
            scored.sort(reverse=True)
            out.append({"period": per.label, "sampled": min(len(ids_by_period[per.id]), sample),
                        "top": [{"term": lex.entry(t).term if lex.entry(t) else t, "term_id": t, "count": n,
                                 "lift": round(lift, 2)} for _, t, n, lift in scored[:10]]})
        return out

    def _dense_books(self, ids_by_period: dict[str, list[str]]) -> list[dict[str, Any]]:
        b = self.b
        per_book = Counter(b.book_counts([pid for ids in ids_by_period.values() for pid in ids]))
        rows = []
        for bid, k in per_book.most_common(200):
            book = b.corpus.books.get(bid)
            if book is None:
                continue
            n = b.corpus.book_passage_count(bid) if hasattr(b.corpus, "book_passage_count") else 0
            if n < 20:
                continue
            rows.append({"book_id": bid, "title": book.title, "dynasty": book.dynasty,
                         "years": [book.composition.start, book.composition.end] if book.composition else None,
                         "passages": k, "share": round(k / n, 4), "category": book.category})
        rows.sort(key=lambda r: (-r["share"], -r["passages"]))
        return rows[:15]

    def _senses(self, term: str) -> list[dict[str, Any]]:
        terminology = self.b.pack.terminology
        hist = terminology.term(term) or terminology.term(self.b.normalize(term))
        if hist is None:
            return []
        out = []
        for s in hist.senses:
            meta = terminology.sense_meta.get(s.id, {})
            out.append({"sense": s.id, "label": s.label, "gloss": s.gloss,
                        "period": [s.period.start, s.period.end] if s.period else None,
                        "cues": list(s.cues)[:8], "candidates": meta.get("candidates", []),
                        "note": "现代概念仅为候选映射，不等同"})
        return out


__all__ = ["TermStudy"]
