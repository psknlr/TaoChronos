"""TaoCore, measured (docs/adr/0036-taocore.md): warm searches on the 要籍语料 — before TaoCore (each search indexing every
token of its candidates), by the Python definitions (TAOCHRONOS_TAOCORE=off) and by the kernel (auto), the three
interleaved repetition by repetition, every result compared with the first way's.

    PYTHONPATH=src python rust/bench.py <data dir> [repetitions]

<data dir>/corpus/tcm.sqlite is the store; where it is missing it is made from corpus/web as the site's build makes it and
the browser's first visit indexes it (about half a minute).  The time is the searching thread's CPU (other processes do
not count), the median of the repetitions after one that fills the caches.  The kernel is whichever the facade finds:
install the extension first (rust/README.md) or the third column measures the definitions again.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
import unicodedata
from pathlib import Path

QUERIES = [  # one for each route and feature of classics.search
    ("桂枝汤", {}), ("麻黄", {}), ("附子", {}), ("发热恶寒", {}), ("汗出而喘", {}), ("桂枝汤和麻黄汤的区别是什么", {}),
    ("宋代以前的消渴", {}), ("消渴", {"before": 1368}), ("人参最早见于哪部书", {}), ("国老", {}), ("甘草", {}), ("阴阳毒", {}),
    ("风", {}),
]


def pad(text: str, width: int) -> str:
    """``text`` padded to ``width`` columns of a terminal (a Chinese character takes two)."""
    return text + " " * max(0, width - sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text))


def store(data: Path) -> None:
    from taochronos.config import find_home
    from taochronos.plugins.classics.domain import DomainPack
    from taochronos.plugins.classics.webcorpus import build_store, index_store

    db = data / "corpus" / "tcm.sqlite"
    if db.is_file():
        return
    home = find_home()
    db.parent.mkdir(parents=True, exist_ok=True)
    pack = DomainPack(home / "domains" / "classics")
    print(f"making {db} from corpus/web …", flush=True)
    build_store(home / "corpus" / "web", db, pack.variants.normalize_text, pack.variants.fingerprint,
                external=home / "corpus" / "catalog" / "external-works.yaml", index=False)
    index_store(db, pack.variants.normalize_text, phase="core")
    index_store(db, pack.variants.normalize_text)


def main() -> None:
    data = Path(sys.argv[1]).resolve()
    repetitions = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    store(data)
    os.environ.setdefault("TAOCHRONOS_SQLITE_JOURNAL", "DELETE")  # as the browser's runtime (web/js/worker.js ENV)
    from taochronos.chat import ChatRuntime
    from taochronos.plugins.retrieval import taocore
    from taochronos.plugins.retrieval.index import BM25Index, DenseIndex

    retriever = ChatRuntime.create("web-canon", kind="browser", ephemeral=True, data_dir=data).h.capabilities.get("retriever")
    now = retriever._local_indexes

    class Before:  # what hybrid._local_indexes built until TaoCore
        def __init__(self, cand: set[str]) -> None:
            self.bm = BM25Index()
            for pid in cand:
                self.bm.add(pid, retriever.norm(pid))
            self.dn = DenseIndex(retriever.embedder)
            for pid in sorted(cand, key=lambda pid: (-retriever._rank.get(pid, 0.0), pid))[:1500]:
                self.dn.add(pid, retriever.norm(pid))

        def bm25(self, toks: list[str], k: int) -> list[tuple[str, float]]:
            return self.bm.search(toks, k)

        def dense(self, text: str, k: int) -> list[tuple[str, float]]:
            return self.dn.search(text, k)

    def search(way: str, query: str, options: dict) -> tuple[float, list]:
        retriever._local_indexes = Before if way == "before" else now
        os.environ["TAOCHRONOS_TAOCORE"] = "off" if way == "before" else way
        cpu = time.thread_time()
        _, hits = retriever.search(query, k=10, **options)
        return (time.thread_time() - cpu) * 1000, [(h.passage_id, h.score) for h in hits]

    ways = ["before", "off", "auto"]
    print(f"kernel: {taocore.status()['kernel'] or 'none — ' + taocore.status()['reason']}")
    print(f"{pad('query', 28)} {'before':>8} {'Python':>8} {'kernel':>8}   ms of CPU, median of {repetitions}")
    totals = dict.fromkeys(ways, 0.0)
    differ = 0
    for query, options in QUERIES:
        first = {way: search(way, query, options)[1] for way in ways}  # fills the caches (the claims, the passages)
        same = all(first[way] == first["before"] for way in ways)
        times: dict[str, list[float]] = {way: [] for way in ways}
        for _ in range(repetitions):
            for way in ways:
                ms, hits = search(way, query, options)
                times[way].append(ms)
                same = same and hits == first["before"]
        median = {way: statistics.median(t) for way, t in times.items()}
        for way in ways:
            totals[way] += median[way]
        differ += not same
        label = query + (f" <{options['before']}" if "before" in options else "")
        print(f"{pad(label, 28)} " + " ".join(f"{median[w]:8.0f}" for w in ways) + ("" if same else "   DIFFERENT RESULTS"))
    print(f"{pad('total', 28)} " + " ".join(f"{totals[w]:8.0f}" for w in ways)
          + f"   Python {totals['before'] / totals['off']:.2f}x, kernel {totals['before'] / totals['auto']:.2f}x")
    print("the same results by every way" if not differ else f"{differ} queries gave different results")
    sys.exit(1 if differ else 0)


if __name__ == "__main__":
    main()
