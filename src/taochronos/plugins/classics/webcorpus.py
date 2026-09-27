"""要籍语料 — the corpus the published site carries.

The full corpus cannot go on a public website: the store is about 2.2 GB, and most of its sources allow local research
only (``corpus/sources.lock.yaml``).  What can go: the witnesses under open licences (``OPEN_SOURCES`` — Kanripo and
Wikisource under CC BY-SA 4.0, CMETA under CC BY 4.0, McGill in the public domain).

``taochronos web pack`` takes, for every work of the 要籍 list (``corpus/catalog/canon.yaml``) that has such witnesses,
the best of them (CMETA's collated editions first, then the most complete) — up to three for the first classics, so
that their witnesses can be collated in the browser — whole when they fit the work's budget, which grows with its rank,
otherwise whole chapters spread evenly through the book.  It writes ``corpus/web/``:

* ``books.json`` — each witness's catalog record, the work's rank, and how much of the witness was kept;
* ``passages.jsonl.gz`` — the passages, with the ids they have in the full corpus (a citation means the same passage in
  the browser and on the server);
* ``ATTRIBUTION.md`` — every text with its source and licence (the pack as a whole: CC BY-SA 4.0).

``taochronos web build`` turns the pack into a corpus store without its full-text index (``build_store``: a third of
the download); the browser builds the index once (``index_store``, seconds) and keeps the result.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from .ingest import load_external_works
from .store import CorpusStore, grams
from .study.canon import OPEN_SOURCES, witness_order

# by the work's rank: how many witnesses, the characters the first may bring, the characters each further one may bring
TIERS: tuple[tuple[int | None, int, int, int], ...] = ((10, 3, 350_000, 90_000), (40, 1, 50_000, 0), (120, 1, 25_000, 0),
                                                        (None, 1, 12_000, 0))
PREFACE = 4000  # a short 提要 or preface at the head of a book is always kept
COLUMNS = ("id", "book_id", "edition_id", "seq", "kind", "layer", "year", "y_start", "y_end", "locator", "temporal", "text",
           "punctuation", "extra")


def tier(rank: int, tiers: Iterable[tuple[int | None, int, int, int]] = TIERS) -> tuple[int, int, int]:
    for limit, witnesses, first, other in tiers:
        if limit is None or rank <= limit:
            return witnesses, first, other
    return 0, 0, 0


def _units(rows: list[dict[str, Any]], cap: int) -> list[list[dict[str, Any]]]:
    """Consecutive passages of one chapter (卷 · 篇); a chapter much larger than the budget in runs of passages."""
    units: list[list[dict[str, Any]]] = []
    key = None
    for r in rows:
        loc = r["locator"] or {}
        k = (loc.get("volume"), loc.get("chapter"))
        if not units or k != key:
            units.append([])
            key = k
        units[-1].append(r)
    out: list[list[dict[str, Any]]] = []
    step = max(cap // 8, 2000)
    for u in units:
        if sum(len(r["text"]) for r in u) <= cap // 4:
            out.append(u)
            continue
        run: list[dict[str, Any]] = []
        size = 0
        for r in u:
            run.append(r)
            size += len(r["text"])
            if size >= step:
                out.append(run)
                run, size = [], 0
        if run:
            out.append(run)
    return out


def select(rows: list[dict[str, Any]], cap: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The passages to keep of one witness: all of them within the budget, else whole units spread through the book."""
    rows = [r for r in rows if r["kind"] != "toc"]
    total = sum(len(r["text"]) for r in rows)
    units = _units(rows, cap)
    if total <= cap:
        return rows, {"chars": total, "kept_chars": total, "units": len(units), "kept_units": len(units), "whole": True}
    kept: list[list[dict[str, Any]]] = []
    size = pos = 0
    for k, u in enumerate(units):
        n = sum(len(r["text"]) for r in u)
        head = k == 0 and n <= PREFACE and u[0]["kind"] == "preface"
        # keep a unit while the share kept lags the reading position: the kept chapters spread through the book
        if head or (size + n <= cap and size <= cap * pos / total):
            kept.append(u)
            size += n
        pos += n
    out = [r for u in kept for r in u]
    return out, {"chars": total, "kept_chars": size, "units": len(units), "kept_units": len(kept), "whole": False}


def export_pack(db: sqlite3.Connection, works: list[dict[str, Any]], out: Path,
                tiers: Iterable[tuple[int | None, int, int, int]] = TIERS) -> dict[str, Any]:
    """Write the pack for the ranked ``works`` from the full store's database ``db``."""
    tiers = tuple(tiers)
    sources: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    by_work: dict[str, list[str]] = defaultdict(list)
    for bid, source, data in db.execute("SELECT id, source, data FROM books"):
        if source in OPEN_SOURCES:
            raw = json.loads(data)
            sources[bid], records[bid] = source, raw
            by_work[raw.get("work") or bid].append(bid)
    size = dict(db.execute("SELECT book_id, SUM(LENGTH(text)) FROM passages WHERE kind != 'toc' GROUP BY book_id"))
    out.mkdir(parents=True, exist_ok=True)
    books, lines, credits = [], [], []
    for w in works:
        n, first, other = tier(int(w["rank"]), tiers)
        chosen = sorted(by_work.get(w["work"], []), key=lambda b: witness_order(b, sources, size))[:n]
        for k, bid in enumerate(chosen):
            rows = [dict(zip(COLUMNS, r)) for r in db.execute(f"SELECT {', '.join(COLUMNS)} FROM passages WHERE book_id=? ORDER BY seq", (bid,))]
            for r in rows:
                r["locator"], r["temporal"] = json.loads(r["locator"]), json.loads(r["temporal"])
                extra = json.loads(r["extra"] or "{}")
                extra.pop("source_file", None)
                r["extra"] = extra
            kept, extent = select(rows, first if k == 0 else other)
            if not kept:
                continue
            data = records[bid]
            books.append({"id": bid, "source": sources[bid], "rank": w["rank"], "work": w["work"], "witness": k + 1,
                          "excerpt": extent, "data": data})
            lines += [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in kept]
            src = data.get("source") or {}
            span = "全书" if extent["whole"] else f"节选 {extent['kept_units']}/{extent['units']} 个章节单位，{extent['kept_chars']:,}/{extent['chars']:,} 字"
            credits.append(f"| {w['rank']} | {data.get('title')} | {src.get('origin', sources[bid])} | "
                           f"{src.get('license', OPEN_SOURCES[sources[bid]])} | {src.get('url') or ''} | {span} |")
    (out / "books.json").write_text(json.dumps(books, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    (out / "passages.jsonl.gz").write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    chars = sum(b["excerpt"]["kept_chars"] for b in books)
    works_in = len({b["work"] for b in books})
    head = ["# 要籍语料 · 来源与授权", "",
            "网页端（GitHub Pages）在浏览器里运行的语料：要籍书目（`corpus/catalog/canon.yaml`，按历代引用排序的 350 部要籍）中",
            "有开放授权录本的各部古籍的原文，由 `taochronos web pack` 从全量语料生成。**整个语料包以 CC BY-SA 4.0 发布**；各书的来源",
            "与授权如下（CC BY 与公有领域的文本可以并入 CC BY-SA 的汇编，须保留署名）。录文均未经本项目逐字校勘；段落号与全量语料相同。",
            "其余要籍（多为笈成等仅限本地研究使用的来源）不随网站发布，接入全量语料（`taochronos serve`）后可用。", "",
            f"共 {works_in} 部要籍、{len(books)} 个录本，{chars:,} 字，{len(lines):,} 段。", "",
            "| 要籍序 | 书名 | 来源 | 授权 | 地址 | 收录范围 |", "|---|---|---|---|---|---|"]
    (out / "ATTRIBUTION.md").write_text("\n".join(head + credits) + "\n", encoding="utf-8")
    return {"out": str(out), "works": works_in, "books": len(books), "passages": len(lines), "characters": chars,
            "sha256": hashlib.sha256(payload).hexdigest()}


def read_pack(pack: Path) -> tuple[list[dict[str, Any]], Iterable[dict[str, Any]]]:
    books = json.loads((pack / "books.json").read_text(encoding="utf-8"))

    def rows() -> Iterable[dict[str, Any]]:
        with gzip.open(pack / "passages.jsonl.gz", "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    return books, rows()


def build_store(pack: Path, path: Path, normalize: Callable[[str], str], fingerprint: str, *, external: Path | None = None,
                index: bool = True) -> dict[str, Any]:
    """The pack as a corpus store: one compact file (no journal), the same bytes for the same pack.  Without ``index``
    the full-text index is left empty (``meta.index = pending``) for ``index_store`` to build where the store is used."""
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if p.exists():
            p.unlink()
    books, rows = read_pack(pack)
    store = CorpusStore(path, create=True)
    for b in books:
        store.put_book(b["data"], b["source"])
    n = store.add_passages(rows, normalize, index=index)
    store.set_meta("normalizer", fingerprint)
    store.set_meta("edition", "web")
    store.set_meta("label", "要籍语料")
    store.set_meta("index", "built" if index else "pending")
    store.commit()
    if external is not None:
        store.set_external(load_external_works(external))
    if index:
        store.optimize()
    store.db.execute("PRAGMA journal_mode=DELETE")
    store.db.execute("VACUUM")
    store.close()
    return {"path": str(path), "books": len(books), "passages": n, "bytes": path.stat().st_size}


def index_store(path: Path, normalize: Callable[[str], str], *, progress: Callable[[int, int], None] | None = None,
                chunk: int = 4000) -> int:
    """Build the full-text index of a store written without one (``build_store(index=False)``); returns the passages
    indexed (0 when the index was built already)."""
    db = sqlite3.connect(path)
    try:
        row = db.execute("SELECT value FROM meta WHERE key='index'").fetchone()
        if not row or row[0] != "pending":
            return 0
        total = db.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        done, last = 0, 0
        while True:
            rows = db.execute("SELECT rid, text FROM passages WHERE rid > ? ORDER BY rid LIMIT ?", (last, chunk)).fetchall()
            if not rows:
                break
            db.executemany("INSERT INTO grams(rowid, g) VALUES (?, ?)", [(rid, grams(normalize(text))) for rid, text in rows])
            last, done = rows[-1][0], done + len(rows)
            if progress:
                progress(done, total)
        db.execute("INSERT INTO grams(grams) VALUES('optimize')")
        db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('index', 'built')")
        db.commit()
        return done
    finally:
        db.close()
