"""``taochronos`` — the command-line interface of the TaoChronos research harness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import AGENT_NAME, __version__


def _out(obj: Any) -> None:
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _harness(args: argparse.Namespace, **kw: Any) -> Any:
    from .bootstrap import Harness

    overrides: dict[str, Any] = {}
    if getattr(args, "provider", None):
        overrides["routing"] = {"default_provider": args.provider}
    if getattr(args, "parallel", None):
        overrides["context"] = {"max_parallel_agents": args.parallel}
    return Harness.from_profile(getattr(args, "profile", None) or "full-discovery", home=args.home, data_dir=args.data,
                                overrides=overrides or None, **kw)


def _session(args: argparse.Namespace) -> tuple[Any, Any, Any]:
    harness = _harness(args)
    engine = harness.engine()
    return harness, engine, engine.open(args.session)


# ------------------------------------------------------------------ commands
def cmd_info(args: argparse.Namespace) -> None:
    harness = _harness(args)
    d = harness.describe()
    d["name"], d["version"] = AGENT_NAME, __version__
    d["corpus"] = harness.corpus.stats(harness.pack.periods)
    d["providers"] = {n: harness.capabilities.get("llm", n).available() for n in harness.capabilities.names("llm")}
    _out(d)


def cmd_profiles(args: argparse.Namespace) -> None:
    from .bootstrap import Harness
    from .config import find_home
    from .kernel.profiles import load_profile

    home = Path(args.home) if args.home else find_home()
    rows = []
    for name in Harness.profiles(home):
        p = load_profile(name, [home / "profiles"])
        rows.append(f"{name:20s} tracks={','.join(p.tracks):18s} {p.description}")
    _out("\n".join(rows))


def cmd_agents(args: argparse.Namespace) -> None:
    harness = _harness(args)
    rows = []
    for role, spec in sorted(harness.specs.items(), key=lambda kv: (kv[0] != "director", kv[0])):
        route = harness.router.route(spec)
        rows.append(f"{spec.name:26s} role={role:16s} mode={spec.mode:9s} route={route.provider}:{route.model:22s} "
                    f"out={spec.output_schema:20s} tools={len(spec.tool_names(harness.tools))} skills={','.join(spec.skills)}")
    _out("\n".join(rows))


def _corpus_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    from .config import data_dir as default_data_dir
    from .config import find_home

    home = find_home(args.home)
    data = Path(args.data) if args.data else default_data_dir(home)
    return home, data


def _store_path(args: argparse.Namespace, data: Path) -> Path:
    return Path(args.db) if getattr(args, "db", None) else data / "corpus" / "tcm.sqlite"


def cmd_corpus(args: argparse.Namespace) -> None:
    action = getattr(args, "action", None) or "list"
    if action != "list":
        return _corpus_admin(args, action)
    harness = _harness(args)
    corpus = harness.corpus
    rows = []
    count = getattr(corpus, "book_passage_count", None)
    for book in sorted(corpus.books.values(), key=lambda b: (b.composition.start if b.composition else 0, b.id)):
        n = count(book.id) if count else len(corpus.passages(book_ids=[book.id]))
        rows.append(f"{book.id:26s} 《{book.title}》 {book.dynasty} {book.composition.label() if book.composition else '?':14s} "
                    f"{book.category} · {n} 段 · {book.source.license or '无授权信息'} · {'已核验' if book.source.verified else '未核验'}")
    rows.append(json.dumps(corpus.stats(harness.pack.periods), ensure_ascii=False))
    _out("\n".join(rows))


def _corpus_admin(args: argparse.Namespace, action: str) -> None:
    """fetch / unpack / catalog / ingest / status / reindex — build and maintain the full-corpus store."""
    home, data = _corpus_paths(args)
    db = _store_path(args, data)
    from .plugins.classics.ingest.collections import COLLECTIONS, RANK

    source = args.source or "kanripo"
    only = [x for x in (args.only or "").split(",") if x] or None
    known = ("kanripo", "kr-catalog", "jicheng", *COLLECTIONS)
    if action in ("fetch", "ingest", "unpack", "catalog") and source not in (*known, "all"):
        raise SystemExit(f"unknown source {source!r}; available: {', '.join(known)}, all")
    if source == "all" and action == "ingest":  # every source, in rank order, from the committed catalogs
        _corpus_admin_kanripo(args, "ingest", home, data, db, only)
        _corpus_admin_jicheng(args, "ingest", home, data, db, only)
        for sid in sorted(COLLECTIONS, key=RANK.__getitem__):
            if (data / "sources" / COLLECTIONS[sid].subdir).exists():
                _corpus_admin_collection(args, "ingest", home, data, db, only, COLLECTIONS[sid])
    elif source == "jicheng":
        _corpus_admin_jicheng(args, action, home, data, db, only)
    elif source in COLLECTIONS:
        _corpus_admin_collection(args, action, home, data, db, only, COLLECTIONS[source])
    elif source == "kr-catalog":
        _corpus_admin_krcatalog(args, action, home, data)
    elif action in ("unpack", "catalog"):
        raise SystemExit(f"`corpus {action}` does not apply to {source} (Kanripo texts are catalogued by hand; "
                         "`corpus catalog kr-catalog` adds the Kanripo catalogue's responsibility data)")
    else:
        _corpus_admin_kanripo(args, action, home, data, db, only)
    if action == "ingest":  # the registry of cited works outside the corpus travels with the store
        from .plugins.classics.ingest import load_external_works
        from .plugins.classics.store import CorpusStore

        n = CorpusStore(db).set_external(load_external_works(home / "corpus" / "catalog" / "external-works.yaml"))
        print(f"  external works registered: {n}")


def _corpus_admin_kanripo(args: argparse.Namespace, action: str, home: Path, data: Path, db: Path, only: list[str] | None) -> None:
    import time

    import yaml

    from .plugins.classics.domain import DomainPack
    from .plugins.classics.ingest import ingest_kanripo, load_catalog
    from .plugins.classics.ingest.fetch import fetch_kanripo, write_lock
    from .plugins.classics.store import CorpusStore, StoreCorpus

    catalog = load_catalog(home / "corpus" / "catalog" / "kanripo-kr3e.yaml")
    sources_dir = data / "sources" / "kanripo"
    if action == "fetch":
        res = fetch_kanripo(catalog, sources_dir, only=only, log=print)
        lock = write_lock(home / "corpus" / "sources.lock.yaml", "kanripo", catalog, sources_dir)
        _out({"fetched": len(res["ok"]), "already_present": len(res["skipped"]), "failed": res["failed"],
              "locked_texts": len(lock["texts"]), "lockfile": str(home / "corpus" / "sources.lock.yaml")})
        return
    pack = DomainPack(home / "domains" / "classics")
    if action == "ingest":
        store = CorpusStore(db, create=True)
        t0 = time.time()
        kr_path = home / "corpus" / "catalog" / "kr-catalog-kr3e.yaml"
        kr_catalog = (yaml.safe_load(kr_path.read_text(encoding="utf-8")) or {}).get("texts") if kr_path.exists() else None
        records_only = bool(getattr(args, "changed", False))
        report = ingest_kanripo(store, catalog, sources_dir, pack.variants.normalize_text, pack.variants.fingerprint, only=only, log=print,
                                dynasty_of=pack.periods.dynasty_of, kr_catalog=kr_catalog, records_only=records_only)
        if not records_only:
            store.optimize()
        report["seconds"] = round(time.time() - t0, 1)
        (data / "corpus").mkdir(parents=True, exist_ok=True)
        report_path = data / "corpus" / "ingest-kanripo.json"
        if (only or records_only) and report_path.exists():  # a partial run updates the full report
            full = json.loads(report_path.read_text(encoding="utf-8"))
            for bid, info in report["books"].items():
                full["books"][bid] = {**full["books"].get(bid, {}), **info}
            report_path.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        books = report["books"]
        _out({"store": str(db), "books": len(books), "passages": sum(b.get("passages", 0) for b in books.values()),
              "characters": sum(b.get("characters", 0) for b in books.values()), "records_only": records_only,
              "responsibility_from_kr_catalog": bool(kr_catalog), "missing": report["missing"],
              "note_order_warnings": report["note_order_warnings"], "seconds": report["seconds"]})
        return
    store = CorpusStore(db)
    if action == "reindex":
        n = store.reindex(pack.variants.normalize_text, pack.variants.fingerprint, progress=lambda k: print(f"  {k} passages"))
        store.optimize()
        _out({"reindexed": n, "normalizer": pack.variants.fingerprint})
        return
    corpus = StoreCorpus(store, pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)
    stats = corpus.stats(pack.periods)
    layers = dict(store.db.execute("SELECT layer, COUNT(*) FROM passages GROUP BY layer ORDER BY COUNT(*) DESC LIMIT 40").fetchall())
    kinds = dict(store.db.execute("SELECT kind, COUNT(*) FROM passages GROUP BY kind").fetchall())
    size = db.stat().st_size
    _out({"store": str(db), "size_mb": round(size / 1e6, 1), "books": stats["books"], "passages": stats["passages"],
          "characters": stats["characters"], "by_period": stats["by_period"], "kinds": kinds, "layers": layers,
          "sources": stats["sources"], "index_current": stats["index_current"],
          "normalizer": {"store": store.meta("normalizer"), "domain": pack.variants.fingerprint}})


def _jicheng_root(data: Path, given: str | None = None) -> Path:
    """The unpacked 笈成 collection: the directory holding config/filelist.txt."""
    if given:
        return Path(given)
    base = data / "sources" / "jicheng"
    roots = sorted(p.parent.parent for p in base.glob("*/config/filelist.txt"))
    if not roots:
        raise SystemExit(f"笈成 data not found under {base}: run `taochronos corpus unpack jicheng <jc_*.7z.001> …` first")
    return roots[-1]


def _corpus_admin_jicheng(args: argparse.Namespace, action: str, home: Path, data: Path, db: Path, only: list[str] | None) -> None:
    """笈成檢閱系統 data (a user-supplied archive): unpack → catalog → ingest."""
    import re
    import time

    import yaml

    from .plugins.classics.chronology import Chronology
    from .plugins.classics.domain import DomainPack, ScriptTable, VariantTable, _load
    from .plugins.classics.ingest import build_jicheng_catalog, ingest_jicheng, jicheng_variant_rows, load_catalog
    from .plugins.classics.ingest.fetch import tree_facts, unpack_archive, write_archive_lock
    from .plugins.classics.ingest.jicheng import read_synonym_groups
    from .plugins.classics.ingest.policy import Exclusions
    from .plugins.classics.store import CorpusStore

    lock_path = home / "corpus" / "sources.lock.yaml"
    catalog_path = home / "corpus" / "catalog" / "jicheng.yaml"
    if action == "fetch":
        raise SystemExit("笈成 data is supplied by the user: `taochronos corpus unpack jicheng <jc_*.7z.001> <….002> …`")
    if action == "unpack":
        volumes = [Path(v) for v in (args.paths or [])]
        if not volumes:
            raise SystemExit("give the archive volumes: taochronos corpus unpack jicheng jc_1_4_8_all.7z.001 jc_1_4_8_all.7z.002 …")
        facts = unpack_archive(volumes, data / "sources" / "jicheng", log=print)
        root = _jicheng_root(data)
        m = re.search(r"v(\d+(?:\.\d+)+)", root.name)
        facts = {"name": "笈成檢閱系統資料（笈成中医古籍整理本）", "program": root.name, "version": m.group(0) if m else None,
                 "license": "古籍原文属公有领域；标点、校勘与整理成果归笈成整理者；当代著作与现代整理本不入库，仅供本地研究使用。"
                            "检阅程序：授權任何人使用與散布（© 2009-2013 Danny）",
                 "url": "https://jicheng.tw/", "catalog": catalog_path.name, **facts, **tree_facts(root)}
        write_archive_lock(lock_path, "jicheng", facts)
        _out({"unpacked": str(root), **facts, "lockfile": str(lock_path)})
        return
    root = _jicheng_root(data, getattr(args, "root", None))
    pack = DomainPack(home / "domains" / "classics")
    if action == "catalog" or (action == "ingest" and not catalog_path.exists()):
        chronology = Chronology(home / "domains" / "classics" / "eras.yaml", pack.variants.normalize_text)
        kanripo = load_catalog(home / "corpus" / "catalog" / "kanripo-kr3e.yaml")
        overrides = yaml.safe_load((home / "corpus" / "catalog" / "jicheng-overrides.yaml").read_text(encoding="utf-8")) or {}
        exclusions = Exclusions(home / "corpus" / "catalog" / "exclusions.yaml")
        cat = build_jicheng_catalog(root, pack.variants.normalize_text, chronology, kanripo, overrides, pack.periods.dynasty_of,
                                    exclusions=exclusions)
        header = ("# GENERATED by `taochronos corpus catalog jicheng` from each book's [book] block, the Kanripo catalog and\n"
                  "# jicheng-overrides.yaml — do not edit here: put corrections in jicheng-overrides.yaml and regenerate.\n")
        catalog_path.write_text(header + yaml.safe_dump(cat, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
        # the viewer's variant groups → rare forms normalised to their common form (matching only)
        script_dir = home / "domains" / "classics" / "script"
        base = VariantTable(_load(home / "domains" / "classics" / "variants.yaml"),
                            ScriptTable(script_dir, files=[f for f in ScriptTable.FILES if f != "jicheng_variants.tsv"]))
        existing = set(base.script.map) | set(base.chars)
        rows = jicheng_variant_rows(read_synonym_groups(root / "config" / "synonyms.txt"), base.normalize_text, existing)
        (script_dir / "jicheng_variants.tsv").write_text(
            "# Rare variant forms from the 笈成檢閱系統 variant table (config/synonyms.txt), each mapped to the group's only\n"
            "# common form; groups with two common forms and the sections 易誤判字 and 一對多簡化字 are left out.\n"
            "# GENERATED by `taochronos corpus catalog jicheng`.  columns: variant, normalised form, source, group\n"
            + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
        dating: dict[str, int] = {}
        for b in cat["books"]:
            dating[b["dating"].split(":")[0]] = dating.get(b["dating"].split(":")[0], 0) + 1
        excluded: dict[str, int] = {}
        for b in cat["books"]:
            if b.get("status") == "excluded":
                excluded[b["excluded_reason"]] = excluded.get(b["excluded_reason"], 0) + 1
        summary = {"catalog": str(catalog_path), "books": len(cat["books"]), "missing": cat["missing"], "dating": dating,
                   "modern": sum(1 for b in cat["books"] if b.get("modern")), "excluded": excluded, "variant_rows": len(rows),
                   "metadata_conflicts": cat["metadata_conflicts"]}
        if action == "catalog":
            _out({**summary, "note": "the normaliser changed if variant_rows changed: run `taochronos corpus reindex`"})
            return
        pack = DomainPack(home / "domains" / "classics")  # reload with the new variant table
    catalog = load_catalog(catalog_path)
    if action != "ingest":
        raise SystemExit(f"`corpus {action}` is store-wide: run it without a source")
    lock = (yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}).get("jicheng", {}) if lock_path.exists() else {}
    store = CorpusStore(db, create=True)
    if store.meta("normalizer") not in (None, pack.variants.fingerprint):
        raise SystemExit("the store was indexed with another normaliser: run `taochronos corpus reindex` first, then ingest")
    t0 = time.time()
    report = ingest_jicheng(store, catalog, root, pack.variants.normalize_text, pack.variants.fingerprint, only=only, log=print,
                            dynasty_of=pack.periods.dynasty_of, version=lock.get("version"),
                            chronology=Chronology(home / "domains" / "classics" / "eras.yaml", pack.variants.normalize_text),
                            changed_only=bool(getattr(args, "changed", False)))
    store.optimize()
    report["seconds"] = round(time.time() - t0, 1)
    (data / "corpus").mkdir(parents=True, exist_ok=True)
    report_path = data / "corpus" / "ingest-jicheng.json"
    if (only or getattr(args, "changed", False)) and report_path.exists():  # a partial run updates the full report
        full = json.loads(report_path.read_text(encoding="utf-8"))
        full["books"].update(report["books"])
        full["unknown_tags"].update(report["unknown_tags"])
        report_path.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    books = report["books"]
    _out({"store": str(db), "books": len(books), "passages": sum(b["passages"] for b in books.values()),
          "characters": sum(b["characters"] for b in books.values()), "records_only": report["records_only"],
          "missing": report["missing"], "unknown_tags": report["unknown_tags"], "seconds": report["seconds"]})


def _corpus_admin_collection(args: argparse.Namespace, action: str, home: Path, data: Path, db: Path, only: list[str] | None,
                             col: Any) -> None:
    """A collection read through the common document path: fetch → catalog (dates, admission, duplicates) → ingest."""
    import time
    from collections import Counter

    import yaml

    from .plugins.classics.chronology import Chronology
    from .plugins.classics.domain import DomainPack
    from .plugins.classics.ingest import load_catalog
    from .plugins.classics.ingest.collections import RANK
    from .plugins.classics.ingest.dedupe import load_sketch
    from .plugins.classics.ingest.documents import build_document_catalog, ingest_documents
    from .plugins.classics.ingest.fetch import write_archive_lock
    from .plugins.classics.ingest.policy import Exclusions
    from .plugins.classics.store import CorpusStore

    root = data / "sources" / col.subdir
    lock_path = home / "corpus" / "sources.lock.yaml"
    catalog_dir = home / "corpus" / "catalog"
    catalog_path = catalog_dir / f"{col.id}.yaml"
    if action == "unpack":
        raise SystemExit(f"{col.id} is fetched, not unpacked: `taochronos corpus fetch {col.id}`")
    if action == "fetch":
        facts = col.fetch(root, print)
        entry = write_archive_lock(lock_path, col.id, {"name": col.source["name"], "license": col.source["license"],
                                                        "url": col.source["url"], "catalog": catalog_path.name, **facts})
        _out({"source": col.id, "path": str(root), **{k: v for k, v in entry.items() if k not in ("subcategories", "dump")},
              "lockfile": str(lock_path)})
        return
    if not root.exists():
        raise SystemExit(f"{col.id} is not in {root}: run `taochronos corpus fetch {col.id}` first")
    if action not in ("catalog", "ingest"):
        raise SystemExit(f"`corpus {action}` is store-wide: run it without a source")
    pack = DomainPack(home / "domains" / "classics")
    normalize = pack.variants.normalize_text
    chronology = Chronology(home / "domains" / "classics" / "eras.yaml", normalize)
    t0 = time.time()
    docs = col.read(root)
    print(f"  read {len(docs)} documents from {root} ({time.time() - t0:.0f}s)")
    store = CorpusStore(db, create=True)
    if store.meta("normalizer") not in (None, pack.variants.fingerprint):
        raise SystemExit("the store was indexed with another normaliser: run `taochronos corpus reindex` first")
    if action == "catalog":
        overrides_path = catalog_dir / f"{col.id}-overrides.yaml"
        overrides = (yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}) if overrides_path.exists() else {}
        sketch = load_sketch(store, normalize, data / "corpus" / "sketch.pkl", pack.variants.fingerprint, log=print)
        book_work, book_source = {}, {}
        for bid, src, raw in store.db.execute("SELECT id, source, data FROM books"):
            book_work[bid] = json.loads(raw).get("work") or bid
            book_source[bid] = src
        ignore = {b for b, src in book_source.items() if RANK.get(src, 99) >= col.rank}
        cat = build_document_catalog(
            docs, col.source, normalize=normalize, chronology=chronology,
            kanripo=load_catalog(catalog_dir / "kanripo-kr3e.yaml"), jicheng=load_catalog(catalog_dir / "jicheng.yaml"),
            overrides=overrides, exclusions=Exclusions(catalog_dir / "exclusions.yaml"), sketch=sketch,
            dynasty_of=pack.periods.dynasty_of, prefix=col.prefix, duplicate=col.duplicate, same_work=col.same_work,
            derivative=col.derivative, book_work=book_work, ignore=ignore)
        cat["source"] = {k: v for k, v in col.source.items()}
        header = (f"# GENERATED by `taochronos corpus catalog {col.id}` — dates, admission (exclusions.yaml, policy.py) and\n"
                  f"# duplicate status against the store; corrections go in {col.id}-overrides.yaml, then regenerate.\n")
        catalog_path.write_text(header + yaml.safe_dump(cat, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
        books = cat["books"]
        status = Counter(b["status"] for b in books)
        dup_of = Counter(book_source.get(b["duplicate_of"], col.id) for b in books if b["status"] == "duplicate")
        admitted = [b for b in books if b["status"] == "ingest"]
        _out({"catalog": str(catalog_path), "documents": len(books), "status": dict(status),
              "excluded": dict(Counter(b["excluded_reason"] for b in books if b["status"] == "excluded")),
              "duplicates_of": dict(dup_of), "admitted_characters": sum(b["characters"] for b in admitted),
              "admitted_dating": dict(Counter(b["dating"].split(":")[0] for b in admitted)),
              "admitted_chartype": dict(Counter(b["chartype"] for b in admitted)),
              "seconds": round(time.time() - t0, 1)})
        return
    if not catalog_path.exists():
        raise SystemExit(f"no catalog for {col.id}: run `taochronos corpus catalog {col.id}` first")
    catalog = load_catalog(catalog_path)
    lock = ((yaml.safe_load(lock_path.read_text(encoding="utf-8")) or {}).get(col.id) or {}) if lock_path.exists() else {}
    version = lock.get("commit") or lock.get("revision") or lock.get("latest_revision")
    report = ingest_documents(store, catalog, docs, normalize, pack.variants.fingerprint, chronology=chronology,
                              dynasty_of=pack.periods.dynasty_of, version=str(version)[:12] if version else None, only=only, log=print)
    store.optimize()
    report["seconds"] = round(time.time() - t0, 1)
    (data / "corpus").mkdir(parents=True, exist_ok=True)
    (data / "corpus" / f"ingest-{col.id}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    books = report["books"]
    _out({"store": str(db), "source": col.id, "books": len(books), "passages": sum(b["passages"] for b in books.values()),
          "characters": sum(b["characters"] for b in books.values()), "excluded": len(report["excluded"]),
          "duplicates": len(report["duplicates"]), "seconds": report["seconds"]})


def _corpus_admin_krcatalog(args: argparse.Namespace, action: str, home: Path, data: Path) -> None:
    """The Kanripo catalogue (KR-Catalog, KR/KR3e.txt): responsible persons, their roles and dates, and the Siku
    volume and page of each text, merged into the Kanripo book records at ingest."""
    import yaml

    from .plugins.classics.ingest import load_catalog
    from .plugins.classics.ingest.collections import git_facts
    from .plugins.classics.ingest.fetch import _clone, write_archive_lock
    from .plugins.classics.ingest.krcatalog import KR_CATALOG_URL, cross_check, read_kr_catalog

    root = data / "sources" / "kanripo-catalog" / "kr-catalog"
    lock_path = home / "corpus" / "sources.lock.yaml"
    out_path = home / "corpus" / "catalog" / "kr-catalog-kr3e.yaml"
    if action == "fetch":
        if not (root / ".git").exists():
            root.parent.mkdir(parents=True, exist_ok=True)
            ok, err = _clone(KR_CATALOG_URL, root)
            if not ok:
                raise SystemExit(f"git clone {KR_CATALOG_URL} failed: {err}")
        facts = git_facts(root, KR_CATALOG_URL, "KR/*.txt")
        entry = write_archive_lock(lock_path, "kr-catalog", {"name": "Kanripo 目録（KR-Catalog）", "license": "CC BY-SA 4.0",
                                                             "url": KR_CATALOG_URL, "file": "KR/KR3e.txt",
                                                             "catalog": out_path.name, **facts})
        _out({"source": "kr-catalog", "path": str(root), **entry})
        return
    if action != "catalog":
        raise SystemExit("kr-catalog supports `corpus fetch kr-catalog` and `corpus catalog kr-catalog`; "
                         "its data enters the store with `corpus ingest kanripo`")
    if not (root / "KR" / "KR3e.txt").exists():
        raise SystemExit(f"KR/KR3e.txt is not in {root}: run `taochronos corpus fetch kr-catalog` first")
    entries = read_kr_catalog(root / "KR" / "KR3e.txt")
    kanripo = load_catalog(home / "corpus" / "catalog" / "kanripo-kr3e.yaml")
    wanted = {b["kr"] for b in kanripo["books"]}
    texts = {k: v for k, v in entries.items() if k in wanted}
    from .plugins.classics.domain import DomainPack

    checks = cross_check(texts, kanripo, DomainPack(home / "domains" / "classics").variants.normalize_text)
    header = ("# GENERATED by `taochronos corpus catalog kr-catalog` from KR-Catalog KR/KR3e.txt (Kanripo, CC BY-SA 4.0):\n"
              "# the responsible persons of each text with their roles and dates, and the Siku edition's volume and page.\n"
              "# Merged into the Kanripo book records at `corpus ingest kanripo`; the curated dates in kanripo-kr3e.yaml stay.\n")
    out_path.write_text(header + yaml.safe_dump({"source": "https://github.com/kanripo/KR-Catalog/blob/master/KR/KR3e.txt",
                                                 "texts": texts, "review": checks}, allow_unicode=True, sort_keys=False, width=160),
                        encoding="utf-8")
    _out({"catalog": str(out_path), "texts": len(texts), "in_kr3e": len(entries),
          "persons": sum(len(t.get("persons", [])) for t in texts.values()), "review": len(checks)})


def _mesh_call(harness: Any, tool: str, **arguments: Any) -> Any:
    from .kernel.policy import Actor
    from .kernel.tools import ToolCall

    outcome = harness.scheduler.execute(ToolCall(tool, arguments), actor=Actor.kernel())
    if not outcome.ok:
        raise SystemExit(outcome.error)
    return outcome.result


def cmd_lexicon(args: argparse.Namespace) -> None:
    """Harvest candidate formula and drug names from the corpus store into domains/classics/lexicon-harvested/."""
    import yaml

    from .plugins.classics.domain import DomainPack
    from .plugins.classics.harvest import Harvester, to_yaml_entries
    from .plugins.classics.store import CorpusStore, StoreCorpus

    home, data = _corpus_paths(args)
    pack = DomainPack(home / "domains" / "classics")
    known = {pack.variants.normalize_text(s) for s in pack.lexicon._by_surface}
    store = CorpusStore(_store_path(args, data))
    corpus = StoreCorpus(store, pack.variants.normalize_text)
    harvester = Harvester(pack.variants.normalize_text, known)
    n = 0
    for p in corpus.iter_passages():
        book = corpus.books.get(p.book_id)
        if book is None:
            continue
        harvester.passage(p.id, p.book_id, book.category, p.text, p.locator.section, corpus.year(p), p.kind)
        n += 1
    formulas, herbs = harvester.select(min_books=args.min_books, min_count=args.min_count)
    f_yaml, h_yaml = to_yaml_entries(formulas, herbs)
    out = home / "domains" / "classics" / "lexicon-harvested"
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (("formulas.yaml", f_yaml), ("herbs.yaml", h_yaml)):
        (out / name).write_text("# Candidate terms harvested from the corpus store — NOT curated. See plugins/classics/harvest.py.\n"
                                + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    _out({"passages_scanned": n, "formulas": len(f_yaml["entries"]), "herbs": len(h_yaml["entries"]),
          "herb_aliases": sum(len(e.get("synonyms", [])) for e in h_yaml["entries"]), "output": str(out)})


def cmd_search(args: argparse.Namespace) -> None:
    harness = _harness(args)
    res = _mesh_call(harness, "classics.search", query=args.query, k=args.k)
    lines = [f"query terms: {res['query']['terms']}  period: {res['query']['after']}–{res['query']['before']}  intent: {res['query']['intent']}"]
    for hit in res["hits"]:
        lines.append(f"{hit['score']:8.3f}  {hit['passage_id']:26s} 《{hit['title']}》{hit['locator']} ({hit['dynasty']}, {hit['year']}) "
                     f"[{','.join(hit['routes'])}]\n          {hit['text']}")
    _out("\n".join(lines))


def cmd_extract(args: argparse.Namespace) -> None:
    harness = _harness(args)
    claims = _mesh_call(harness, "kg.extract_claims", passage_id=args.passage)
    _out([{"relation": c["relation"], "quote": c["quote"],
           "arguments": [f"{a['role']}={a['term_id'] or a['surface']}{'(neg)' if a['negated'] else ''}" for a in c["arguments"]],
           "rule": c["extraction"]["rule"]} for c in claims])


def cmd_research(args: argparse.Namespace) -> None:
    harness = _harness(args)
    engine = harness.engine()
    fields: dict[str, Any] = {}
    if args.focus:
        fields["focus_terms"] = [t for t in args.focus.split(",") if t]
    if args.tracks:
        fields["tracks"] = [t.strip() for t in args.tracks.split(",") if t.strip()]
    if args.forbid:
        fields["forbidden_assumptions"] = list(args.forbid)
    if args.holdout_after is not None:
        fields["holdout_after"] = args.holdout_after
    if args.max_rounds is not None:
        fields["stop"] = {"max_rounds": args.max_rounds}
    if args.books:
        fields["corpus"] = {"books": [b for b in args.books.split(",") if b]}
    goal = harness.make_goal(args.question, **fields)
    session = engine.start(goal, session_id=args.session)
    print(f"{AGENT_NAME} · session {session.id} · profile {harness.profile.name}", file=sys.stderr)
    result = engine.run(session)
    if not args.no_workspace:
        from .workspace import publish_workspace

        ws = publish_workspace(harness, session)
        print(f"workspace: {harness.artifacts.path_of(ws)}", file=sys.stderr)
    report = _latest(session.state, "discovery_report", "report.md")
    _out({"session": result.session_id, "status": result.status, "rounds": result.rounds,
          "stop": result.stop.get("reasons", []), "report": str(harness.artifacts.path_of(report)) if report else None,
          "metrics": {k: result.metrics[k] for k in ("claims", "evidence_count", "counter_evidence", "observations",
                                                      "hypotheses", "hypothesis_survival", "agents_spawned", "llm_calls", "cost_usd")}})


def _latest(state: Any, kind: str, filename: str) -> Any:
    arts = [a for a in state.artifacts.values() if a.kind == kind and a.path.endswith(filename)]
    return max(arts, key=lambda a: a.version) if arts else None


def cmd_resume(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    rep = session.recovery
    print(f"recovered: dropped {rep.discarded_events} uncommitted event(s) {rep.discarded_transactions}", file=sys.stderr)
    result = engine.run(session)
    _out({"session": result.session_id, "status": result.status, "rounds": result.rounds})


def cmd_report(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    from .engine.report import build

    _, md, payload = build(harness, session.state, session.id)
    _out(json.dumps(payload, ensure_ascii=False, indent=1, default=str) if args.json else md)


def cmd_trace(args: argparse.Namespace) -> None:
    from .kernel.observability import agent_tree, research_tree

    harness, engine, session = _session(args)
    _out(research_tree(session.state) if args.hypotheses else agent_tree(session.events()))


def cmd_metrics(args: argparse.Namespace) -> None:
    from .kernel.observability import research_metrics

    harness, engine, session = _session(args)
    _out(research_metrics(session.state))


def cmd_events(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    rows = []
    for e in session.events(args.from_seq, args.to_seq):
        if args.type and e.type != args.type:
            continue
        payload = json.dumps(e.payload, ensure_ascii=False, default=str)
        rows.append(f"{e.seq:5d} {e.type:22s} {e.actor:40s} {e.task_id or '':24s} {payload[:args.width]}")
    _out("\n".join(rows))


def cmd_replay(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    if args.to_seq:
        state = session.replay(args.to_seq)
        _out({"at_seq": args.to_seq, "state_hash": state.state_hash(), "status": state.status, "round": state.round,
              "claims": len(state.claims), "hypotheses": len(state.hypotheses)})
    else:
        _out(session.verify())


def cmd_fork(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    if args.hypothesis:
        child, outcome = engine.branch(session, args.hypothesis, purpose=args.purpose or "")
        _out({"branch": child.id, "outcome": outcome})
    else:
        child = session.fork(at_seq=args.at, purpose=args.purpose or "manual fork")
        _out({"branch": child.id, "at_seq": args.at or session.seq, "events": child.seq})


def cmd_review(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    if args.approve == args.reject:
        raise SystemExit("choose exactly one of --approve / --reject")
    engine.expert_review(session, args.hypothesis, approve=args.approve, expert=args.expert, note=args.note or "")
    h = session.state.hypotheses[args.hypothesis]
    _out({"hypothesis": h.id, "status": h.status, "G7": session.state.gates[h.id]["G7"].status})


def cmd_changes(args: argparse.Namespace) -> None:
    from .kernel.policy import Actor

    harness, engine, session = _session(args)
    if args.decide:
        if not args.expert:
            raise SystemExit("--expert is required to decide a change (agents may only propose)")
        engine.decide_change(session, args.decide, approve=not args.reject, actor=Actor.human(args.expert), note=args.note or "")
    rows = []
    for c in sorted(session.state.changes.values(), key=lambda c: c.id):
        p = c.payload
        rows.append(f"{c.id}  [{c.status}{' by ' + c.decided_by if c.decided_by else ''}]  {c.target}:{c.op}  "
                    f"{p.get('historical_label', p.get('sense_id', ''))} —{p.get('relation', '')}→ {p.get('modern_label', p.get('concept_id', ''))}")
    _out("\n".join(rows) or "(no proposed changes)")


def cmd_export(args: argparse.Namespace) -> None:
    harness, engine, session = _session(args)
    state = session.state
    fmt = args.format
    if fmt == "prov":
        exporter = harness.capabilities.get("graph_export", "prov")
        content = json.dumps(exporter(session.events(), state), ensure_ascii=False, indent=1, default=str)
    else:
        exporter = harness.capabilities.get("graph_export", fmt)
        books = {b.id: b.title for b in harness.corpus.books.values()}
        result = exporter(list(state.claims.values()), list(state.lineage.values()), books)
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)
    if args.output:
        Path(args.output).write_text(content, encoding="utf-8")
        _out(f"wrote {args.output} ({len(content)} chars)")
    else:
        _out(content)


def cmd_workspace(args: argparse.Namespace) -> None:
    from .workspace import publish_workspace

    harness, engine, session = _session(args)
    art = publish_workspace(harness, session)
    _out(str(harness.artifacts.path_of(art)))


def cmd_codemode(args: argparse.Namespace) -> None:
    from .kernel.policy import Actor
    from .kernel.tools import ToolContext
    from .plugins.sandbox.codemode import run_code

    harness = _harness(args)
    code = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    ctx = ToolContext(actor=Actor.kernel(), capabilities=harness.capabilities, scheduler=harness.scheduler,
                      services=harness.scheduler.services)
    _out(run_code(ctx, harness.tools, code))


def cmd_sdk(args: argparse.Namespace) -> None:
    from .plugins.sandbox.codemode import sdk_reference

    _out(sdk_reference(_harness(args).tools))


def cmd_schema(args: argparse.Namespace) -> None:
    from .agents.schemas import OUTPUT_SCHEMAS
    from .protocol import PROTOCOL_TYPES
    from .protocol.schema import bundle_schema

    if args.outputs:
        _out(OUTPUT_SCHEMAS)
    else:
        _out(bundle_schema(list(PROTOCOL_TYPES)))


def cmd_governance(args: argparse.Namespace) -> None:
    from .governance import check

    report = check(Path(args.home) if args.home else None)
    _out(report)
    if report["violations"]:
        raise SystemExit(1)


def cmd_eval(args: argparse.Namespace) -> None:
    from .evals import run_suites

    results = run_suites(args.suites or None, home=args.home, data_dir=args.data, quick=args.quick)
    if args.output:
        Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    from .evals import summary_table

    _out(summary_table(results))


STUDY = ("concordance", "formula", "herb", "term", "taboo", "citations", "cards", "reading", "metrology", "dataset",
         "variants", "stemma", "edition", "tei", "reuse", "transmission", "layers", "dating", "authorship", "cases",
         "trajectories")


def cmd_study(args: argparse.Namespace) -> None:
    """治学 — study functions over the classics (docs/study.md): Markdown by default, ``--json`` for the full result."""
    import re

    from .plugins.classics.study.dataset import write_datapackage
    from .plugins.classics.study.render import markdown

    _, data = _corpus_paths(args)
    if not args.profile:
        args.profile = "full-corpus" if (data / "corpus" / "tcm.sqlite").exists() else "full-discovery"
    harness = _harness(args)
    study = harness.capabilities.get("study")
    what, target = args.what, " ".join(args.target).strip() or None
    needs = {"formula": "a formula name", "herb": "a drug name", "term": "a term", "reading": "a topic", "metrology": "a dose"}
    if what in needs and not target:
        raise SystemExit(f"taochronos study {what}: give {needs[what]}")
    if what in ("concordance", "reuse") and not (target or args.passage):
        raise SystemExit(f"taochronos study {what}: give a text or --passage <id>")
    if what in ("stemma", "edition", "tei", "transmission", "layers", "dating") and not (target or args.books):
        raise SystemExit(f"taochronos study {what}: give a work (key, title or book id) or --books")
    notice = ""
    collation = {k: v for k, v in (("books", args.books), ("base", args.base), ("chapter", args.chapter)) if v}
    if args.max_chars:
        collation["max_chars"] = args.max_chars
    if what == "variants":
        res = study.variants(None if args.passage else target, text=target if args.text_mode else None,
                             passage_id=args.passage, **({} if args.passage or args.text_mode else collation))
    elif what == "stemma":
        res = study.stemma(target, root_at=args.root_at, **collation)
    elif what == "edition":
        res = study.edition(target, **collation)
    elif what == "tei":
        text = study.tei(target, **collation)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            _out(f"wrote {args.output}")
        else:
            _out(text)
        return
    elif what == "reuse":
        if args.against or args.against_passage:
            res = study.reuse_pair(target, args.against, source_id=args.passage, target_id=args.against_passage)
        else:
            res = study.reuse(target, args.passage, semantic=not args.no_semantic, limit=args.limit or 300)
    elif what == "transmission":
        res = study.transmission(target, clauses=args.clauses)
    elif what == "layers":
        res = study.layers(target, books=args.books, k=args.k, features=args.features)
    elif what == "dating":
        res = study.dating(target, books=args.books)
    elif what == "cases":
        if not (target or args.book):
            raise SystemExit("taochronos study cases: give a disease (e.g. 风温) or --book <id>")
        res = study.cases(args.book, disease=None if args.book else target, limit=args.limit or 200)
    elif what == "trajectories":
        if not (target or args.book):
            raise SystemExit("taochronos study trajectories: give a disease (e.g. 咳嗽) or --book <id>")
        res = study.trajectories(None if args.book else target, book=args.book, limit=args.limit or 1000)
    elif what == "authorship":
        if not (target or args.book):
            raise SystemExit("taochronos study authorship: give a text or --book <id> [--chapter <篇名>]")
        res = study.authorship(None if args.book else target, book=args.book, chapter=args.chapter_name,
                               candidates=args.candidate or None)
    elif what == "concordance":
        res = study.concordance(target, args.passage, min_coverage=args.min_coverage, limit=args.limit or 300)
    elif what == "formula":
        res = study.formula(target, other_names=not args.no_other_names)
        notice = res.get("metrology_notice", "")
    elif what == "herb":
        res = study.herb(target)
    elif what == "term":
        res = study.term(target)
    elif what == "taboo":
        res = study.taboo(target) if target else study.taboo(min_chars=args.min_chars)
    elif what == "citations":
        res = study.citations(target) if target else study.citations(top=args.top)
    elif what == "cards":
        res = study.cards(book=args.book, formulas=args.formula or [], herbs=args.herb or [], term=args.term, limit=args.limit or 60)
        if args.anki:
            Path(args.anki).write_text(res["anki_tsv"], encoding="utf-8")
    elif what == "reading":
        res = study.reading(target)
    elif what == "metrology":
        reading = study.metrology.convert(target, args.year)
        res = {"dose": target, "year": args.year, "parsed": study.metrology.parse(target), "reading": reading, "notice": study.metrology.notice}
        if not args.json:
            _out(f"{target}（{args.year if args.year is not None else '年代未定'}）→ {(reading or {}).get('text') or '无法折算'}\n> {res['notice']}")
            return
    else:  # dataset
        res = study.dataset(formulas=args.formula or [], herbs=args.herb or [], terms=([args.term] if args.term else []) + list(args.target),
                            citations=args.citations)
        slug = re.sub(r"[^\w一-鿿]+", "-", "-".join((args.formula or []) + (args.herb or []) + ([args.term] if args.term else []) + list(args.target)) or "citations").strip("-")
        out_dir = Path(args.output) if args.output else data / "study" / "datasets" / slug
        pkg = write_datapackage(out_dir, res["tables"], name=f"taochronos-{slug}".lower(), title=f"TaoChronos 治学数据集：{slug}",
                                signature=res["signature"], licenses=res["licenses"], notice=res["notice"])
        _out({"path": str(out_dir), "resources": {r["name"]: r["rows"] for r in pkg["resources"]}, "licenses": res["licenses"]})
        return
    text = json.dumps(res, ensure_ascii=False, indent=1, default=str) if args.json else markdown(what, res, study.signature(), notice)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        _out(f"wrote {args.output}")
    else:
        _out(text)


def cmd_demo(args: argparse.Namespace) -> None:
    args.question = args.question or "消渴的概念如何随时代演变？宋代以前治疗消渴的哪些知识后来被遗忘？"
    args.focus = args.focus or "消渴"
    args.forbid = args.forbid or ["消渴=糖尿病"]
    for key in ("tracks", "holdout_after", "max_rounds", "books"):
        if not hasattr(args, key):
            setattr(args, key, None)
    args.no_workspace = False
    cmd_research(args)


# ------------------------------------------------------------------ parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taochronos", description=f"{AGENT_NAME}: evidence-native knowledge discovery in Chinese medical classics")
    p.add_argument("--home", help="repository root (default: $TAOCHRONOS_HOME or auto-detect)")
    p.add_argument("--data", help="data directory (default: $TAOCHRONOS_DATA or <home>/.taochronos)")
    p.add_argument("--version", action="version", version=f"{AGENT_NAME} {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, fn: Any, help_: str, profile: bool = True) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_)
        if profile:
            sp.add_argument("--profile", default="full-discovery")
            sp.add_argument("--provider", help="default model provider for judgement roles (e.g. anthropic); offline by default")
        sp.set_defaults(fn=fn)
        return sp

    add("info", cmd_info, "describe the harness (plugins, capabilities, agents, providers)")
    add("profiles", cmd_profiles, "list profiles", profile=False)
    add("agents", cmd_agents, "list agent specs and their current routes")
    sp = add("corpus", cmd_corpus, "list the corpus, or fetch / unpack / catalog / ingest / status / reindex the full-corpus store")
    sp.add_argument("action", nargs="?", default="list", choices=["list", "fetch", "unpack", "catalog", "ingest", "status", "reindex"])
    sp.add_argument("source", nargs="?", help="source: kanripo, kr-catalog, jicheng (user-supplied archive), mcgill, wikisource, "
                                             "tcm-ancient-books, tcmoc, hf-tcm-canon, or all (ingest)")
    sp.add_argument("paths", nargs="*", help="archive volumes for `unpack jicheng` (jc_1_4_8_all.7z.001 …)")
    sp.add_argument("--root", help="unpacked 笈成 directory (default: the one under <data>/sources/jicheng)")
    sp.add_argument("--changed", action="store_true",
                    help="ingest jicheng: re-parse only books whose dates or layers changed in the catalog, refresh the other "
                         "records; ingest kanripo: rewrite the book records only (catalog or KR-Catalog changes)")
    sp.add_argument("--only", help="comma-separated text ids (e.g. KR3e0001,KR3e0013) or book ids")
    sp.add_argument("--db", help="corpus store path (default: <data>/corpus/tcm.sqlite)")
    sp = add("lexicon", cmd_lexicon, "harvest candidate formula / drug names from the corpus store", profile=False)
    sp.add_argument("action", choices=["harvest"])
    sp.add_argument("--db", help="corpus store path (default: <data>/corpus/tcm.sqlite)")
    sp.add_argument("--min-books", type=int, default=2)
    sp.add_argument("--min-count", type=int, default=3)
    sp = add("search", cmd_search, "philology-aware temporal GraphRAG search")
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=8)
    sp = add("extract", cmd_extract, "extract claims from one passage")
    sp.add_argument("passage")
    for name, fn, help_ in (("research", cmd_research, "run a research session"), ("demo", cmd_demo, "run the 消渴 demo research")):
        sp = add(name, fn, help_)
        sp.add_argument("question", nargs="?" if name == "demo" else None)
        sp.add_argument("--focus", help="comma-separated focus terms")
        sp.add_argument("--forbid", action="append", help="forbidden assumption (repeatable), e.g. 消渴=糖尿病")
        sp.add_argument("--parallel", type=int, help="run up to N independent agents concurrently")
        sp.add_argument("--session", help="session id")
        if name == "research":
            sp.add_argument("--tracks", help="comma-separated tracks, e.g. D1,D2,D5")
            sp.add_argument("--holdout-after", type=int, help="hide texts dated ≥ this year (Historical Time Machine)")
            sp.add_argument("--max-rounds", type=int)
            sp.add_argument("--books", help="restrict the corpus to these book ids")
            sp.add_argument("--no-workspace", action="store_true")
    for name, fn, help_ in (("resume", cmd_resume, "resume a session after a crash or interruption"),
                            ("report", cmd_report, "print the Discovery Report"), ("trace", cmd_trace, "agent tree / research tree"),
                            ("metrics", cmd_metrics, "research metrics"), ("events", cmd_events, "list events"),
                            ("replay", cmd_replay, "verify the log or replay to a sequence number"),
                            ("fork", cmd_fork, "fork a hypothesis branch"), ("review", cmd_review, "expert review (Gate G7)"),
                            ("changes", cmd_changes, "list or decide proposed canonical-knowledge changes"),
                            ("export", cmd_export, "export the claim hypergraph (json|cypher|graphml|prov)"),
                            ("workspace", cmd_workspace, "build the HTML Discovery Workspace")):
        sp = add(name, fn, help_)
        sp.add_argument("session")
        if name == "report":
            sp.add_argument("--json", action="store_true")
        if name == "trace":
            sp.add_argument("--hypotheses", action="store_true", help="show the hypothesis genealogy instead")
        if name == "events":
            sp.add_argument("--type")
            sp.add_argument("--from-seq", type=int, default=1)
            sp.add_argument("--to-seq", type=int)
            sp.add_argument("--width", type=int, default=140)
        if name == "replay":
            sp.add_argument("--to-seq", type=int)
        if name == "fork":
            sp.add_argument("--hypothesis")
            sp.add_argument("--at", type=int)
            sp.add_argument("--purpose")
        if name == "review":
            sp.add_argument("hypothesis")
            sp.add_argument("--approve", action="store_true")
            sp.add_argument("--reject", action="store_true")
            sp.add_argument("--expert", required=True)
            sp.add_argument("--note")
        if name == "changes":
            sp.add_argument("--decide", metavar="CHANGE_ID")
            sp.add_argument("--reject", action="store_true")
            sp.add_argument("--expert")
            sp.add_argument("--note")
        if name == "export":
            sp.add_argument("--format", default="json", choices=["json", "cypher", "graphml", "prov"])
            sp.add_argument("-o", "--output")
    sp = sub.add_parser("study", help="治学: 经文互见·集注, 方源考, 药性源流, 术语源流, 避讳断代, 引书网络, 学习卡片, 阅读门径, 研究数据集, "
                                      "版本谱系 (variants/stemma/edition/tei), 语义复用 (reuse), 思想传播 (transmission), "
                                      "文本地层 (layers/dating/authorship), 医案轨迹 (cases/trajectories)")
    sp.set_defaults(fn=cmd_study)
    sp.add_argument("what", choices=STUDY)
    sp.add_argument("target", nargs="*", help="the formula, drug, term, topic, text, book id or dose")
    sp.add_argument("--profile", help="default: full-corpus when the corpus store exists, else full-discovery (demo corpus)")
    sp.add_argument("--provider", help=argparse.SUPPRESS)
    sp.add_argument("--passage", help="concordance: a passage id instead of a text")
    sp.add_argument("--min-coverage", type=float, default=0.6, help="concordance: share of the text a witness must carry")
    sp.add_argument("--no-other-names", action="store_true", help="formula: skip the search for 同方异名")
    sp.add_argument("--min-chars", type=int, default=20000, help="taboo survey: smallest book to judge")
    sp.add_argument("--top", type=int, default=12, help="citations: works and physicians per period")
    sp.add_argument("--book", help="cards: 方证 cards from this book (e.g. 伤寒论)")
    sp.add_argument("--formula", action="append", help="cards/dataset: a formula (repeatable)")
    sp.add_argument("--herb", action="append", help="cards/dataset: a drug (repeatable)")
    sp.add_argument("--term", help="cards/dataset: a term")
    sp.add_argument("--citations", action="store_true", help="dataset: include the citation network")
    sp.add_argument("--year", type=float, help="metrology: the year whose measures to read the dose in")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--anki", help="cards: also write an Anki import file (TSV)")
    sp.add_argument("--books", action="append", help="variants/stemma/edition/tei: a witness book id (repeatable; a+b joins volumes)")
    sp.add_argument("--base", help="variants/stemma: the base witness (book id or siglum; default: the one the others carry most)")
    sp.add_argument("--chapter", help="variants/stemma: collate only locators matching this pattern (e.g. 辨太阳病)")
    sp.add_argument("--max-chars", type=int, help="variants/stemma: longest base to collate (default 60000)")
    sp.add_argument("--root-at", help="stemma: root the tree at this witness (default: midpoint)")
    sp.add_argument("--text-mode", action="store_true", help="variants: the target is a passage text, collate its copies and quotations")
    sp.add_argument("--against", help="reuse: the type of reuse of the text in this other text")
    sp.add_argument("--against-passage", help="reuse: … in this passage")
    sp.add_argument("--no-semantic", action="store_true", help="reuse: shared wording only (no concept co-occurrence)")
    sp.add_argument("--clauses", type=int, default=40, help="transmission: clauses of the work to trace")
    sp.add_argument("--k", type=int, default=2, help="layers: number of layers to test")
    sp.add_argument("--features", choices=["frequent", "function"], default="frequent",
                    help="layers: the 100 most frequent characters, or function characters only (less sensitive to topic)")
    sp.add_argument("--chapter-name", help="authorship: one chapter (篇) of --book")
    sp.add_argument("--candidate", action="append", help="authorship: a candidate work or book id (repeatable)")
    sp.add_argument("--json", action="store_true", help="print the full result as JSON")
    sp.add_argument("-o", "--output", help="write to this file (dataset: this directory)")
    sp = add("codemode", cmd_codemode, "run a Research Code Mode program against the SDK")
    sp.add_argument("file", nargs="?")
    add("sdk", cmd_sdk, "print the Research SDK reference (Code Mode)")
    sp = add("schema", cmd_schema, "print JSON Schemas of the protocol (or agent outputs)", profile=False)
    sp.add_argument("--outputs", action="store_true")
    add("governance", cmd_governance, "check the architecture policy", profile=False)
    sp = add("eval", cmd_eval, "run TaoChronos-Eval suites", profile=False)
    sp.add_argument("suites", nargs="*")
    sp.add_argument("--quick", action="store_true")
    sp.add_argument("-o", "--output")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except BrokenPipeError:  # pragma: no cover - e.g. `taochronos export … | head`
        import os

        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
