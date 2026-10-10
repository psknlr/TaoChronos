"""要籍语料 — the corpus the published site carries.

The full corpus cannot go into a browser: the store is about 2.2 GB (the first 350 ranked works alone are some 57 million
characters).  What goes is the 要籍 list (``corpus/catalog/canon.yaml``), every work with text — the first classics whole,
the rest as whole chapters spread through the book, within a budget that grows with the work's rank.

The witnesses (``WEB_SOURCES``): the openly licensed first (``OPEN_SOURCES`` — CMETA under CC BY 4.0, Kanripo and
Wikisource under CC BY-SA 4.0, McGill in the public domain, and 笈成, which releases its editorial work on the
public-domain texts under CC0 1.0 and its own writing under CC BY 4.0: https://jicheng.tw/tcm/copyright.html), then the
two web text sets transcribed from 笈成 (TCM-Ancient-Books, tcmoc), mostly copies of its texts, whose own repositories
declare no licence.  The site carries these — and the modern editors' part of the 笈成 texts that follow a modern
edition (a reconstruction of a lost book, an annotated edition), which 笈成's CC0 cannot release — by IMPF-AI's decision
(2026-09-28: the works are all in the public domain).  Sources whose terms forbid redistribution (``NEVER_PACKED``) are
never packed: a work known only through them is listed, without text.

``taochronos web pack`` takes, for every ranked work, the best witnesses (CMETA's collated editions first, then the most
complete) — up to three for the first classics, so that their witnesses can be collated in the browser — whole when they
fit the work's budget, otherwise whole chapters spread evenly through the book.  It writes ``corpus/web/``:

* ``books.json`` — each witness's catalog record, the work's rank, and how much of the witness was kept;
* ``passages.jsonl.gz`` — the passages in rank order, with the ids they have in the full corpus (a citation means the
  same passage in the browser and on the server);
* ``ATTRIBUTION.md`` — every text with its source and terms.

``taochronos web build`` turns the pack into a corpus store without its full-text index (``build_store``: the index is
two thirds of a download that compresses badly); the browser indexes it (``index_store``) in two steps — the works ranked
up to ``CORE_RANK`` before it answers, the rest in the background — and keeps the result.
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
from .study.canon import OPEN_SOURCES

# the sources the site's pack may take, in the order their witnesses are preferred (the terms, for the attribution)
WEB_SOURCES: dict[str, str] = {
    **OPEN_SOURCES,
    "tcm-ancient-books": "古籍原文属公有领域；该文本集多为中醫笈成整理本（CC0 1.0）的简体转换本，与笈成本重复者不收；其仓库未声明授权",
    "tcmoc": "古籍原文属公有领域；该文本集据 TCM-Ancient-Books 整理，多为中醫笈成整理本（CC0 1.0）的简体转换本，与笈成本重复者不收；"
             "其仓库未声明授权",
}
# sources whose terms forbid passing their transcriptions on: never in the pack
NEVER_PACKED: dict[str, str] = {
    "aeam": "東亜医学協会：限非营利的个人保存与使用，未经许可不得转载、再分发",
    "hf-tcm-canon": "数据集声明 proprietary-commercial 授权",
}
CORE_RANK = 40  # the works the browser indexes before it answers; those ranked below follow in the background

# by the work's rank: how many witnesses, the characters the first may bring, the characters each further one may bring
TIERS: tuple[tuple[int | None, int, int, int], ...] = ((10, 3, 350_000, 90_000), (40, 1, 50_000, 0), (120, 1, 25_000, 0),
                                                        (None, 1, 12_000, 0))
PREFACE = 4000  # a short 提要 or preface at the head of a book is always kept
COLUMNS = ("id", "book_id", "edition_id", "seq", "kind", "layer", "year", "y_start", "y_end", "locator", "temporal", "text",
           "punctuation", "extra")


def pack_order(book_id: str, sources: dict[str, str], size: dict[str, int]) -> tuple[int, int, str]:
    """The witnesses of a work, best first: by source in ``WEB_SOURCES`` order (CMETA's collated editions first, the
    openly licensed before the rest), then the most complete text."""
    src = sources.get(book_id, "")
    return (list(WEB_SOURCES).index(src) if src in WEB_SOURCES else len(WEB_SOURCES), -size.get(book_id, 0), book_id)


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


PUBLISHED = "随道乃久网站发布，供学习研究（发布方 IMPF-AI 决定，2026-09-28）"


def export_pack(db: sqlite3.Connection, works: list[dict[str, Any]], out: Path,
                tiers: Iterable[tuple[int | None, int, int, int]] = TIERS) -> dict[str, Any]:
    """Write the pack for the ranked ``works`` from the full store's database ``db``."""
    tiers = tuple(tiers)
    sources: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    by_work: dict[str, list[str]] = defaultdict(list)
    for bid, source, data in db.execute("SELECT id, source, data FROM books"):
        if source in WEB_SOURCES:
            raw = json.loads(data)
            sources[bid], records[bid] = source, raw
            by_work[raw.get("work") or bid].append(bid)
    size = dict(db.execute("SELECT book_id, SUM(LENGTH(text)) FROM passages WHERE kind != 'toc' GROUP BY book_id"))
    out.mkdir(parents=True, exist_ok=True)
    books, lines, credits, unheld = [], [], [], []
    for w in works:
        n, first, other = tier(int(w["rank"]), tiers)
        chosen = sorted(by_work.get(w["work"], []), key=lambda b: pack_order(b, sources, size))[:n]
        if not chosen:
            unheld.append(w)
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
            src = dict(data.get("source") or {})
            if sources[bid] not in OPEN_SOURCES:  # the terms under which the site carries it, not the local-research note
                src.update(license=WEB_SOURCES[sources[bid]], published=PUBLISHED)
                data = {**data, "source": src}
            books.append({"id": bid, "source": sources[bid], "rank": w["rank"], "work": w["work"], "witness": k + 1,
                          "excerpt": extent, "data": data})
            lines += [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in kept]
            span = "全书" if extent["whole"] else f"节选 {extent['kept_units']}/{extent['units']} 个章节单位，{extent['kept_chars']:,}/{extent['chars']:,} 字"
            credits.append(f"| {w['rank']} | {data.get('title')} | {src.get('origin', sources[bid])} | "
                           f"{src.get('license') or WEB_SOURCES[sources[bid]]} | {src.get('url') or ''} | {span} |")
    (out / "books.json").write_text(json.dumps(books, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    (out / "passages.jsonl.gz").write_bytes(gzip.compress(payload, compresslevel=9, mtime=0))
    chars = sum(b["excerpt"]["kept_chars"] for b in books)
    works_in = len({b["work"] for b in books})
    head = ["# 要籍语料 · 来源与授权", "",
            f"网页端在浏览器里运行的语料：要籍书目（`corpus/catalog/canon.yaml`，按历代引用排序的 {len(works)} 部要籍）各书的原文，由",
            "`taochronos web pack` 从全量语料生成：最重要的典籍收全书，其余收分布全书的章节节选。所收均为公有领域的古籍；各录本的",
            "来源与条件见下表：", "",
            "* 开放授权的录本（维基文库、漢籍リポジトリ：CC BY-SA 4.0；數位中醫校書郎 CMETA：CC BY 4.0；McGill：公有领域）按其授权使用，"
            "须保留署名；",
            "* 中醫笈成的录本：笈成对公有领域古籍的筛选、编排、标点、附注等编辑成果以 CC0 1.0 释出至公有领域，网站自行创作的内容以",
            "  CC BY 4.0 释出（https://jicheng.tw/tcm/copyright.html），可自由使用，请注明来自中醫笈成；笈成所据今人辑校、校注本（如辑佚",
            "  古书）中的今人成分不在其列，经发布方（IMPF-AI）决定随网站发布，供学习研究；",
            "* 据笈成转录的网络文本集（TCM-Ancient-Books、tcmoc）：多为笈成整理本的简体转换本（与笈成本重复者不收），其仓库未声明",
            "  授权；经发布方（IMPF-AI）决定随网站发布，供学习研究；",
            "* 条款禁止转载或限定授权的来源（" + "；".join(f"{k}：{v}" for k, v in NEVER_PACKED.items()) + "）不收。",
            "", "录文均未经本项目逐字校勘；段落号与全量语料相同。", "",
            f"共 {works_in} 部要籍、{len(books)} 个录本，{chars:,} 字，{len(lines):,} 段。"
            + (f"只有上述不收来源的 {len(unheld)} 部（{'、'.join(w.get('title') or w['work'] for w in unheld)}）只列书目。" if unheld else ""),
            "", "| 要籍序 | 书名 | 来源 | 授权与条件 | 地址 | 收录范围 |", "|---|---|---|---|---|---|"]
    (out / "ATTRIBUTION.md").write_text("\n".join(head + credits) + "\n", encoding="utf-8")
    return {"out": str(out), "works": works_in, "books": len(books), "passages": len(lines), "characters": chars,
            "unheld": [w["work"] for w in unheld], "sha256": hashlib.sha256(payload).hexdigest()}


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
    store.count()
    if not index:
        # the pack is in rank order: the passages of the works the browser indexes first end at this rowid
        core = [b["id"] for b in books if int(b.get("rank") or 0) <= CORE_RANK]
        last = store.db.execute(f"SELECT MAX(rid) FROM passages WHERE book_id IN ({','.join('?' * len(core))})",
                                core).fetchone()[0] if core else None
        store.set_meta("index_core", str(last or 0))
        store.set_meta("index_rid", "0")
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
                chunk: int = 4000, phase: str = "all", limit: int | None = None) -> int:
    """Build the full-text index of a store written without one (``build_store(index=False)``), resumably.

    ``phase="core"`` indexes the passages of the works ranked up to ``CORE_RANK`` (they come first); ``"all"`` whatever is
    left, when it is done the index is optimized and ``built``.  ``limit`` stops after about that many passages, so that
    the browser can index in slices between the questions it answers.  Returns the passages indexed by this call (0 when
    there was nothing left to index)."""
    db = sqlite3.connect(path)
    try:
        state = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('index', 'index_rid', 'index_core')").fetchall())
        if state.get("index") != "pending":
            return 0
        last = int(state.get("index_rid") or 0)
        until = int(state.get("index_core") or 0) if phase == "core" else 0
        bound, params = (" AND rid <= ?", [until]) if until else ("", [])
        total = db.execute(f"SELECT COUNT(*) FROM passages WHERE rid > ?{bound}", [last, *params]).fetchone()[0]
        if last == 0:
            db.execute("INSERT INTO grams(grams, rank) VALUES('automerge', 16)")  # fewer merges while it grows: faster
        done = 0
        while not limit or done < limit:
            rows = db.execute(f"SELECT rid, text FROM passages WHERE rid > ?{bound} ORDER BY rid LIMIT ?",
                              [last, *params, chunk]).fetchall()
            if not rows:
                break
            db.executemany("INSERT INTO grams(rowid, g) VALUES (?, ?)", [(rid, grams(normalize(text))) for rid, text in rows])
            last, done = rows[-1][0], done + len(rows)
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('index_rid', ?)", (str(last),))
            db.commit()
            if progress:
                progress(done, total)
        if phase != "core" and not db.execute("SELECT 1 FROM passages WHERE rid > ? LIMIT 1", (last,)).fetchone():
            db.execute("INSERT INTO grams(grams) VALUES('optimize')")
            db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('index', 'built')")
        db.commit()
        return done
    finally:
        db.close()


def index_state(path: Path) -> dict[str, Any]:
    """How far the browser's index has got: {"state": pending | built, "indexed": passages, "total": passages}."""
    db = sqlite3.connect(path)
    try:
        state = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('index', 'index_rid')").fetchall())
        total = db.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
        built = state.get("index") != "pending"
        indexed = total if built else db.execute("SELECT COUNT(*) FROM passages WHERE rid <= ?",
                                                 (int(state.get("index_rid") or 0),)).fetchone()[0]
        return {"state": "built" if built else "pending", "indexed": indexed, "total": total}
    finally:
        db.close()


# ------------------------------------------------------------------ the site's server: the full corpus (全量语料)
PART_BYTES = 24 * 1024 * 1024  # the compressed store travels in parts of this size: each a value in Workers KV (≤ 25 MiB)


def site_record(data: dict[str, Any], source: str) -> dict[str, Any]:
    """A book's catalog record with the terms under which the site carries it: the transcriptions of the sources that
    declare no licence (``WEB_SOURCES`` beyond ``OPEN_SOURCES``) are published by IMPF-AI's decision, and 笈成's are
    CC0 — a record written by an older ingest may still say "local research only"."""
    src = dict(data.get("source") or {})
    if source == "jicheng":
        from .ingest import JC_SOURCE

        src["license"] = JC_SOURCE["license"]
    elif source not in OPEN_SOURCES:
        src.update(license=WEB_SOURCES[source], published=PUBLISHED)
    return {**data, "source": src}


def server_store(src: Path, out: Path) -> dict[str, Any]:
    """The full corpus as the site's server carries it (``taochronos web store``): every book of a source the site may
    carry (``WEB_SOURCES``; never ``NEVER_PACKED``), its passages as in the full store (the same ids and row ids, so a
    citation means the same passage here, in the browser and on the server), without the full-text index — built where
    the server is built (``index_store``: the index is most of the store, and the normalizer of the code that serves
    it builds it) — and without cached claims.  One compact file (no journal)."""
    for p in (out, out.with_name(out.name + "-wal"), out.with_name(out.name + "-shm"), out.with_name(out.name + "-journal")):
        if p.exists():
            p.unlink()
    store = CorpusStore(out, create=True)
    db = store.db
    db.execute("PRAGMA journal_mode=DELETE")
    db.execute("ATTACH DATABASE ? AS full", (f"file:{src}?mode=ro",))
    kept: dict[str, dict[str, int]] = defaultdict(lambda: {"books": 0})
    excluded: dict[str, int] = defaultdict(int)
    for bid, source, data in db.execute("SELECT id, source, data FROM full.books ORDER BY id").fetchall():
        if source in WEB_SOURCES:
            store.put_book(site_record(json.loads(data), source), source)
            kept[source]["books"] += 1
        else:
            excluded[source] += 1
    db.execute("INSERT INTO external(id, data) SELECT id, data FROM full.external ORDER BY id")
    columns = ", ".join(("rid",) + COLUMNS)
    db.execute(f"INSERT INTO passages({columns}) SELECT {columns} FROM full.passages "
               "WHERE book_id IN (SELECT id FROM main.books) ORDER BY rid")
    normalizer = db.execute("SELECT value FROM full.meta WHERE key = 'normalizer'").fetchone()
    db.commit()
    db.execute("DETACH DATABASE full")
    for source, n, chars in db.execute("SELECT b.source, COUNT(*), SUM(LENGTH(p.text)) FROM passages p "
                                       "JOIN books b ON b.id = p.book_id GROUP BY b.source"):
        kept[source].update(passages=n, characters=chars)
    if normalizer:
        store.set_meta("normalizer", normalizer[0])
    store.set_meta("edition", "full")
    store.set_meta("label", "全量语料")
    store.set_meta("index", "pending")
    store.set_meta("index_rid", "0")
    store.count()
    store.commit()
    db.execute("VACUUM")
    store.close()
    totals = {k: sum(v.get(k, 0) for v in kept.values()) for k in ("books", "passages", "characters")}
    return {"path": str(out), **totals, "sources": {k: dict(v) for k, v in sorted(kept.items())},
            "excluded": dict(sorted(excluded.items())), "bytes": out.stat().st_size}


def compress_store(path: Path, dest: Path, *, preset: int = 6) -> dict[str, Any]:
    """``path`` xz-compressed into ``dest`` (the xz tool with all cores when there is one, else lzma), with the digests
    and the parts it travels in (``PART_BYTES`` each, the last smaller)."""
    import lzma
    import shutil
    import subprocess

    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            raw.update(chunk)
    if shutil.which("xz"):
        with open(dest, "wb") as out:
            subprocess.run(["xz", "-z", "-c", f"-{preset}", "-T0", "--block-size=64MiB", "--check=crc32", str(path)],
                           stdout=out, check=True)
    else:
        comp = lzma.LZMACompressor(format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=preset)
        with open(path, "rb") as f, open(dest, "wb") as out:
            while chunk := f.read(1 << 20):
                out.write(comp.compress(chunk))
            out.write(comp.flush())
    whole, parts = hashlib.sha256(), []
    with open(dest, "rb") as f:
        while chunk := f.read(PART_BYTES):
            whole.update(chunk)
            parts.append({"name": f"part-{len(parts):03d}", "bytes": len(chunk), "sha256": hashlib.sha256(chunk).hexdigest()})
    return {"encoding": "xz", "bytes": dest.stat().st_size, "sha256": whole.hexdigest(), "raw_bytes": path.stat().st_size,
            "raw_sha256": raw.hexdigest(), "part_bytes": PART_BYTES, "parts": parts}


def server_attribution(path: Path, info: dict[str, Any]) -> str:
    """The sources and terms of every text the site's server carries (``cloud/ATTRIBUTION.md``): each source's terms once,
    then every book (with its own terms where they are not its source's)."""
    from collections import Counter

    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        chars = dict(db.execute("SELECT book_id, SUM(LENGTH(text)) FROM passages GROUP BY book_id"))
        books = []
        for bid, source, data in db.execute("SELECT id, source, data FROM books"):
            d = json.loads(data)
            src = d.get("source") or {}
            books.append({"id": bid, "source": source, "title": d.get("title") or bid, "dynasty": d.get("dynasty") or "",
                          "origin": src.get("origin") or source, "license": src.get("license") or WEB_SOURCES[source],
                          "url": src.get("url") or "", "chars": chars.get(bid, 0)})
    finally:
        db.close()
    order = list(WEB_SOURCES)
    books.sort(key=lambda b: (order.index(b["source"]), b["id"]))
    terms = {s: Counter(b["license"] for b in books if b["source"] == s).most_common(1)[0][0] for s in {b["source"] for b in books}}
    origin = {s: Counter(b["origin"] for b in books if b["source"] == s).most_common(1)[0][0] for s in terms}
    cell = lambda text: str(text).replace("|", "／").replace("\n", " ")
    by_source = info["sources"]
    head = ["# 全量语料 · 来源与授权", "",
            "道乃久网站的服务器（chat.impf.ai，部署在 Cloudflare）所用的全量语料：本项目收录的全部古籍中，来源条件允许随网站发布的",
            "各部录本，由 `taochronos web store` 从全量语料生成。所收均为公有领域的古籍：",
            "",
            "* 开放授权的录本（维基文库、漢籍リポジトリ：CC BY-SA 4.0；數位中醫校書郎 CMETA：CC BY 4.0；McGill：公有领域）按其授权使用，"
            "须保留署名；",
            "* 中醫笈成的录本：笈成对公有领域古籍的筛选、编排、标点、附注等编辑成果以 CC0 1.0 释出至公有领域，网站自行创作的内容以",
            "  CC BY 4.0 释出（https://jicheng.tw/tcm/copyright.html），可自由使用，请注明来自中醫笈成；笈成所据今人辑校、校注本（如辑佚",
            "  古书）中的今人成分不在其列，经发布方（IMPF-AI）决定随网站发布，供学习研究；",
            "* 据笈成转录的网络文本集（TCM-Ancient-Books、tcmoc）：多为笈成整理本的简体转换本，其仓库未声明授权；经发布方（IMPF-AI）",
            "  决定随网站发布，供学习研究；",
            "* 条款禁止转载或限定授权的来源（" + "；".join(f"{k}：{v}" for k, v in NEVER_PACKED.items()) + "）不收"
            + ("（" + "、".join(f"{k} {n} 部" for k, n in info["excluded"].items()) + "）" if info["excluded"] else "") + "。",
            "", "录文均未经本项目逐字校勘；段落号与全量语料、网页端的要籍语料相同。", "",
            f"共 {info['books']} 部录本，{info['characters']:,} 字，{info['passages']:,} 段。", "",
            "## 来源", "", "| 来源 | 录本 | 字数 | 出处 | 授权与条件 |", "|---|---|---|---|---|"]
    head += [f"| {s} | {by_source[s]['books']} | {by_source[s].get('characters', 0):,} | {cell(origin[s])} | {cell(terms[s])} |"
             for s in sorted(terms, key=order.index)]
    head += ["", "## 书目", "", "授权与条件与其来源相同者不再重复。", "", "| 书名 | 朝代 | 来源 | 地址 | 字数 | 另注 |", "|---|---|---|---|---|---|"]
    lines = [f"| {cell(b['title'])} | {cell(b['dynasty'])} | {b['source']} | {cell(b['url'])} | {b['chars']:,} | "
             f"{cell(b['license']) if b['license'] != terms[b['source']] else ''} |" for b in books]
    return "\n".join(head + lines) + "\n"
