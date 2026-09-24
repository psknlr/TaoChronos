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
    """fetch / ingest / status / reindex — build and maintain the full-corpus store."""
    import time

    from .plugins.classics.domain import DomainPack
    from .plugins.classics.ingest import ingest_kanripo, load_catalog
    from .plugins.classics.ingest.fetch import fetch_kanripo, write_lock
    from .plugins.classics.store import CorpusStore, StoreCorpus

    home, data = _corpus_paths(args)
    db = _store_path(args, data)
    source = args.source or "kanripo"
    only = [x for x in (args.only or "").split(",") if x] or None
    if action in ("fetch", "ingest") and source not in ("kanripo", "all"):
        raise SystemExit(f"unknown source {source!r}; available: kanripo (笈成 and Wikisource connectors are added as their data arrive)")
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
        report = ingest_kanripo(store, catalog, sources_dir, pack.variants.normalize_text, pack.variants.fingerprint, only=only, log=print,
                                dynasty_of=pack.periods.dynasty_of)
        store.optimize()
        report["seconds"] = round(time.time() - t0, 1)
        (data / "corpus").mkdir(parents=True, exist_ok=True)
        (data / "corpus" / "ingest-kanripo.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        books = report["books"]
        _out({"store": str(db), "books": len(books), "passages": sum(b["passages"] for b in books.values()),
              "characters": sum(b["characters"] for b in books.values()), "missing": report["missing"],
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
    sp = add("corpus", cmd_corpus, "list the corpus, or fetch / ingest / status / reindex the full-corpus store")
    sp.add_argument("action", nargs="?", default="list", choices=["list", "fetch", "ingest", "status", "reindex"])
    sp.add_argument("source", nargs="?", help="source to fetch or ingest (kanripo)")
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
