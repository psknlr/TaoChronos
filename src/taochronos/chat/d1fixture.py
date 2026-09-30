"""A small D1 backup for the tests (``cloud/test/backup.test.js``, ``tests/test_d1.py``): ten books of the committed
要籍 pack (corpus/web — every kind of source, of passage id, of date), made into a store, its results precomputed by
the Python tools, and exported and imported by the exporter itself into local SQLite files (``db-<k>.sqlite``), spread
over three databases as the full corpus is over five.  ``python -m taochronos.chat.d1 fixture <dir>``.
"""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any

BOOKS = ("cm_shanghan_npm", "cm_jingui_wuqian", "ws_36bca7b992", "suwen_wangbing", "hejiju_fang", "jc_o056", "yimen_falv",
         "ws_abfd7a1046", "tab_277", "mg_nuke_jiyao")
CLAUSE = "太阳之为病，脉浮，头项强痛而恶寒"
KEYS: list[tuple[str, str, dict[str, Any]]] = [
    ("study.formula", "桂枝汤", {"name": "桂枝汤"}),
    ("study.herb", "人参", {"name": "人参"}),
    ("study.term", "消渴", {"term": "消渴"}),
    ("study.network", "桂枝汤", {"target": "桂枝汤"}),
    ("study.taboo", "", {}),
    ("kg.claims", "disease:消渴", {"terms": ["disease:消渴"]}),
]
# the Python tools' answers on the fixture, which the backup's must equal (a search: its query analysis)
REFERENCE: list[tuple[str, dict[str, Any]]] = [
    ("classics.get_passage", {"passage_id": "cm_shanghan_npm.00001"}),
    ("classics.get_passage", {"passage_id": "suwen_wangbing.000.00001"}),
    ("classics.get_passage", {"passage_id": "hejiju_fang.000.00002"}),
    ("classics.get_passage", {"passage_id": "cm_jingui_wuqian.99999"}),
    ("classics.list_books", {}),
    ("classics.list_books", {"query": "伤寒"}),
    ("classics.list_books", {"dynasty": "宋", "limit": 3}),
    ("classics.canon", {"limit": 5}),
    ("classics.canon", {"query": "伤寒"}),
    ("classics.canon", {"held": True}),
    ("kg.term", {"surface": "消渴"}),
    ("kg.term", {"surface": "桂枝汤"}),
    ("kg.term", {"surface": "pulse:浮"}),  # an id that is not category:term (the term is 脉浮)
    ("kg.term", {"surface": "formula:小柴胡汤"}),
    ("kg.term", {"surface": "薯蓣"}),
    ("philology.normalize", {"text": "太陽之為病，脈浮，頭項強痛而惡寒。黃耆、五藏"}),
    ("philology.normalize", {"text": "募原淡飲栝蔞"}),
    ("philology.assess_passage", {"passage_id": "suwen_wangbing.000.00001"}),
    ("philology.assess_passage", {"passage_id": "cm_jingui_wuqian.00365"}),
    ("philology.collate", {"passage_a": "cm_jingui_wuqian.00356", "passage_b": "cm_jingui_wuqian.00365"}),
    ("philology.inspect_page", {"object_id": "suwen_wangbing.000.00001"}),
    ("validation.provenance_chain", {"object_id": "cm_shanghan_npm.00001"}),
    ("validation.verify_quote", {"quote": CLAUSE}),
    ("validation.verify_quote", {"quote": "桂枝湯主之"}),  # twice in one chunk (00356, 00365), among others
    ("validation.verify_quote", {"quote": "太阳之为病脉浮头项强痛而恶寒"}),  # 白文 against punctuated witnesses
    ("validation.verify_quote", {"quote": "这句话不在任何古籍里出现过"}),
    ("validation.verify_quote", {"quote": "脉浮紧"}),
    ("validation.verify_quote", {"quote": "柴胡桂枝湯主之", "passage_id": "cm_jingui_wuqian.00365"}),
    ("study.metrology", {"dose": "一两半", "year": 1600}),
    ("study.metrology", {"dose": "三两", "year": 200}),
    ("study.metrology", {"dose": "半升", "year": 200}),
    ("modern.safety", {"text": "附子一枚，炮，朱砂、雄黄各少许"}),
    ("literature.modern_evidence", {"term": "青蒿"}),
    ("classics.search", {"query": "太阳之为病脉浮头项强痛而恶寒"}),
    ("classics.search", {"query": "宋代以前的消渴"}),
    ("classics.search", {"query": "桂枝汤", "books": ["cm_shanghan_npm"]}),
]


def build_fixture(out: str | Path, *, home: str | Path | None = None, log: Any = print) -> dict[str, Any]:
    from ..config import find_home
    from ..plugins.classics.domain import DomainPack
    from ..plugins.classics.webcorpus import build_store
    from .d1 import SqliteTarget, make_plan, run_import, summary
    from .d1results import Precompute, clause_key, runtime_for

    root = find_home(str(home) if home else None)
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    pack_dir = out / "pack"
    pack_dir.mkdir(parents=True)
    books = [b for b in json.loads((root / "corpus" / "web" / "books.json").read_text(encoding="utf-8")) if b["id"] in BOOKS]
    (pack_dir / "books.json").write_text(json.dumps(books, ensure_ascii=False), encoding="utf-8")
    with gzip.open(root / "corpus" / "web" / "passages.jsonl.gz", "rt", encoding="utf-8") as f:
        lines = [line for line in f if json.loads(line)["book_id"] in BOOKS]
    (pack_dir / "passages.jsonl.gz").write_bytes(gzip.compress("".join(lines).encode("utf-8"), mtime=0))
    pack = DomainPack(root / "domains" / "classics")
    store = out / "data" / "corpus" / "tcm.sqlite"
    store.parent.mkdir(parents=True)
    # the pack keeps whole chapters spread through each book, with their numbers in the full corpus: the store has gaps
    build_store(pack_dir, store, pack.variants.normalize_text, pack.variants.fingerprint, index=True)
    runtime = runtime_for(store, home=root)
    norm = pack.variants.normalize_text
    keys = KEYS + [("study.commentaries", clause_key(CLAUSE, norm), {"text": CLAUSE})]
    results = Precompute(runtime, only=keys, log=log)
    plan = make_plan(store, home=root, version="fixture0000000", results=results, db_bytes=1_600_000, db0_reserve=400_000)
    target = SqliteTarget(out)
    report = run_import(plan, target, budget=10**9, log=lambda m: None)
    target.close()
    reference = []
    for name, args in REFERENCE:
        r = runtime.call(name, args, max_chars=16000)
        reference.append({"name": name, "args": args, "ok": r["ok"], "result": r.get("result"), "error": r.get("error")})
    runtime.h.corpus.store.close()
    info = {"report": report, "summary": summary(plan, statements=False), "clause": CLAUSE, "keys": [[t, k] for t, k, _ in keys],
            "reference": reference}
    (out / "fixture.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"fixture: {report['statements']} statements, {plan.databases} databases, {len(plan.chunks)} chunks, complete={report['complete']}")
    return info
