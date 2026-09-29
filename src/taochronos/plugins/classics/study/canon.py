"""要籍 — the works that matter most, ranked by how the tradition itself cited them.

One pass of the citation network (``network.py``) gives, for every work of the corpus, the works that cite it — by
title in 书名号 or as 经曰 / 经言.  A work's importance is read from five things:

* **influence** — how many different works cite it (a book citing it a thousand times counts once), counting only
  citing works not older than it (an earlier "citation" is a misresolved title);
* **breadth** — in how many analysis periods it is cited;
* **volume** — how often it is cited in all;
* **transmission** — how many witnesses of it the corpus holds (editions, transcriptions);
* **siku** — whether the 四库全书 editors took it into 子部·医家类 (the Kanripo KR3e texts).

``score = 10·log2(1+influence) + 2·breadth + 2·log2(1+volume) + 3·log2(1+witnesses) + 6·siku``; ties fall to the
earlier work.  Non-medical works and works after 1949 are not ranked.  The list is a reading of this corpus's
citations — what the books in it quote — not a verdict on the tradition: late works have had less time to be cited,
and works known only through quotations (佚书) are not in it.

``taochronos study canon --write-catalog`` writes the list to ``corpus/catalog/canon.yaml`` (metadata only: titles,
authors, dates, counts, which sources hold the work).  Every harness reads it back, whatever its corpus, so the
browser's small corpus can say which of the important works it holds and which only the full corpus has.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .base import StudyBase

# sources whose licence allows republishing their text (corpus/sources.lock.yaml): what a published site may carry
OPEN_SOURCES = {
    "cmeta": "CC BY 4.0 — 數位中醫校書郎 CMETA",
    "kanripo": "CC BY-SA 4.0 — 漢籍リポジトリ Kanseki Repository",
    "wikisource": "CC BY-SA 4.0 — 维基文库 Wikisource",
    "mcgill": "Public Domain Mark 1.0 — McGill University Library",
    "jicheng": "CC0 1.0 — 中醫笈成 JiCheng（公有领域古籍的编辑成果；网站原创内容 CC BY 4.0）",
}
NOT_RANKED = {"现代", "非医籍"}
LATEST = 1950
TOLERANCE = 30  # years by which a citing work may seem to precede the cited one (uncertain dates)
_VOLUME = re.compile(r"\s*[（(](?:上|中|下|[一二三四五六七八九十]+)[)）]$")  # 太平圣惠方(上): one volume of a split witness
METHOD = ("score = 10·log2(1+influence) + 2·breadth + 2·log2(1+volume) + 3·log2(1+witnesses) + 6·siku; influence = "
          "number of distinct works citing it (not older than it), breadth = periods in which it is cited, volume = "
          "citations in all, witnesses = copies in the corpus, siku = in 四库全书·子部·医家类")


def book_sizes(corpus: Any) -> dict[str, int]:
    """Characters per book (passages per book where the corpus has no store)."""
    store = getattr(corpus, "store", None)
    if store is not None:
        with store.lock:
            return dict(store.db.execute("SELECT book_id, SUM(LENGTH(text)) FROM passages WHERE kind != 'toc' GROUP BY book_id"))
    counts: dict[str, int] = defaultdict(int)
    for p in corpus.passages():
        counts[p.book_id] += len(p.text)
    return dict(counts)


def witness_order(book_id: str, sources: dict[str, str], size: dict[str, int]) -> tuple[int, int, str]:
    """The witnesses of a work, best first: an open source in OPEN_SOURCES order (CMETA's collated editions first), then
    the most complete text."""
    src = sources.get(book_id, "")
    return (list(OPEN_SOURCES).index(src) if src in OPEN_SOURCES else len(OPEN_SOURCES), -size.get(book_id, 0), book_id)


class CanonStudy:
    def __init__(self, base: StudyBase, network: Any) -> None:
        self.b = base
        self.net = network
        self._catalog: list[dict[str, Any]] | None = None

    @property
    def path(self) -> Path:
        return self.b.pack.root.parent.parent / "corpus" / "catalog" / "canon.yaml"

    # ------------------------------------------------------------ ranking (needs the full corpus)
    def rank(self, top: int = 350, cache: str | None = None) -> dict[str, Any]:
        corpus = self.b.corpus
        books = corpus.books
        sources: dict[str, str] = dict(getattr(corpus, "sources", {}) or {})
        size = book_sizes(corpus)
        built = self.net.build(cache)
        work_of = {bid: (bk.work or bid) for bid, bk in books.items()}
        witnesses: dict[str, list[str]] = defaultdict(list)
        for bid, w in work_of.items():
            witnesses[w].append(bid)
        start = {w: min((books[b].composition.start for b in bs if books[b].composition), default=None) for w, bs in witnesses.items()}
        cited_by: dict[str, set[str]] = defaultdict(set)
        periods: dict[str, set[str]] = defaultdict(set)
        volume: dict[str, float] = defaultdict(float)
        for key, targets in built["books"].items():
            citing_book, period = key.rsplit("|", 1)
            citing = work_of.get(citing_book, citing_book)
            for target, n in targets.items():
                kind, ident = target.split(":", 1)
                if kind not in ("book", "work"):
                    continue  # works known only through quotations are not in the corpus
                work = work_of.get(ident, ident) if kind == "book" else ident
                if work == citing or work not in witnesses:
                    continue
                s, c = start.get(work), start.get(citing)
                if s is not None and c is not None and c + TOLERANCE < s:
                    continue
                cited_by[work].add(citing)
                periods[work].add(period)
                volume[work] += n
        rows = []
        for work, bids in witnesses.items():
            head = self._representative(bids)
            bk = books[head]
            if bk.category in NOT_RANKED or (start[work] is not None and start[work] >= LATEST):
                continue
            srcs = sorted({sources.get(b, "") for b in bids} - {""})
            influence, breadth, vol = len(cited_by.get(work, ())), len(periods.get(work, ())), volume.get(work, 0.0)
            siku = "kanripo" in srcs
            score = (10 * math.log2(1 + influence) + 2 * breadth + 2 * math.log2(1 + vol) + 3 * math.log2(1 + len(bids))
                     + (6 if siku else 0))
            open_books = sorted((b for b in bids if sources.get(b) in OPEN_SOURCES), key=lambda b: witness_order(b, sources, size))
            rows.append({
                "work": work, "title": _VOLUME.sub("", self.net._work_title(work)), "authors": list(bk.authors[:3]), "dynasty": bk.dynasty,
                "composition": bk.composition.label() if bk.composition else None, "category": bk.category,
                "score": round(score, 2), "cited_by": influence, "periods": breadth, "citations": round(vol),
                "witnesses": len(bids), "siku": siku, "sources": srcs, "open": bool(open_books),
                "open_witness": open_books[0] if open_books else None, "_start": start[work] if start[work] is not None else 9999,
            })
        rows.sort(key=lambda r: (-r["score"], r["_start"], r["work"]))
        for k, r in enumerate(rows, 1):
            r["rank"] = k
            del r["_start"]
        chosen = rows[:top]
        return {"method": METHOD, "ranked": len(rows), "top": top, "open": sum(1 for r in chosen if r["open"]),
                "works": [{"rank": r.pop("rank"), **r} for r in chosen]}

    def _representative(self, bids: list[str]) -> str:
        """The witness whose metadata stands for the work: the earliest, then the one titled as the work."""
        books = self.b.corpus.books
        return min(bids, key=lambda b: (books[b].composition.start if books[b].composition else 9999, len(books[b].title), b))

    # ------------------------------------------------------------ the list, in any corpus
    def catalog(self) -> list[dict[str, Any]]:
        if self._catalog is None:
            path = self.path
            data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
            self._catalog = list((data or {}).get("works") or [])
        return self._catalog

    def lookup(self, query: str = "", *, dynasty: str = "", category: str = "", limit: int = 60, held: bool | None = None) -> dict[str, Any]:
        """The ranked works, filtered, each marked with whether this corpus holds a witness of it."""
        here = {bk.work or bid for bid, bk in self.b.corpus.books.items()} | set(self.b.corpus.books)
        works = self.catalog()
        out = []
        for w in works:
            if query and not any(query in str(x) for x in (w.get("title"), w.get("work"), *(w.get("authors") or []))):
                continue
            if (dynasty and dynasty not in str(w.get("dynasty") or "")) or (category and category not in str(w.get("category") or "")):
                continue
            in_corpus = w.get("work") in here
            if held is not None and in_corpus != held:
                continue
            out.append({k: w.get(k) for k in ("rank", "title", "authors", "dynasty", "composition", "category", "cited_by",
                                               "witnesses", "siku")} | {"in_this_corpus": in_corpus})
        return {"listed": len(works), "held_here": sum(1 for w in works if w.get("work") in here), "matched": len(out),
                "method": METHOD, "works": out[:limit] if limit else out}


def write_catalog(path: Path, ranking: dict[str, Any]) -> dict[str, Any]:
    head = ("# 要籍 — the works of the corpus ranked by how the tradition cited them (taochronos study canon --write-catalog).\n"
            "# Metadata only: no text.  Read with classics.canon; the published site's corpus holds the works marked open.\n"
            f"# {ranking['method']}\n")
    body = {"ranked": ranking["ranked"], "top": ranking["top"], "open": ranking["open"], "works": ranking["works"]}
    path.write_text(head + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    return {"path": str(path), "works": len(ranking["works"]), "open": ranking["open"]}
