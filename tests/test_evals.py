import shutil

import pytest

from taochronos.evals import run_suites
from taochronos.governance import check

from conftest import HOME


def test_quick_eval_suites(tmp_path):
    results = run_suites(["philology", "anachronism", "temporal", "hallucination", "contradiction"], home=HOME, data_dir=tmp_path)
    assert results["philology"]["metrics"]["pass_rate"] == 1.0
    assert results["anachronism"]["metrics"]["agent_equivalence_blocked"] is True
    assert results["anachronism"]["metrics"]["block"]["fp"] == 0
    assert results["temporal"]["metrics"]["period_leakage"] == 0
    assert results["hallucination"]["metrics"]["fabricated_detection"] == 1.0
    assert results["contradiction"]["metrics"]["accuracy"] >= 0.8


def test_source_rediscovery(tmp_path):
    metrics = run_suites(["source_rediscovery"], home=HOME, data_dir=tmp_path)["source_rediscovery"]["metrics"]
    assert metrics["recall@3"] == 1.0 and metrics["date_bound_consistent"] == 1.0


def test_governance_detects_a_layering_violation(tmp_path):
    copy = tmp_path / "repo"
    shutil.copytree(HOME, copy, ignore=shutil.ignore_patterns(".git", ".taochronos", "__pycache__", "*.egg-info", "tests"))
    assert check(copy)["violations"] == []
    bad = copy / "src" / "taochronos" / "kernel" / "leak.py"
    bad.write_text("from ..plugins.models.anthropic_provider import AnthropicProvider  # claude\n")
    rules = {v["rule"] for v in check(copy)["violations"]}
    assert {"layering", "kernel_forbidden_term"} <= rules


# ------------------------------------------------------------------ the alias layer (spec §3.10)
def test_alias_eval_synthetic_part(tmp_path):
    data = run_suites(["aliases"], home=HOME, data_dir=tmp_path, quick=True)["aliases"]
    syn = data["metrics"]["synthetic"]
    for name in ("off_is_legacy", "places_and_retention", "no_merge", "readings", "gates", "periods", "flags",
                 "no_leakage"):
        assert syn[name] is True, name
    assert syn["P@10 on"] > syn["P@10 off"] and syn["P@10 on"] > syn["P@10 naive"]
    assert syn["Wrong@10 on"] < syn["Wrong@10 off"] and syn["Wrong@10 on"] < syn["Wrong@10 naive"]
    assert syn["ON@10 on"] > syn["ON@10 off"] and syn["AskedRet@10 on"] >= 0.9
    assert syn["CandRecall on"] == 1.0 and syn["SilentMerge on"] == 0
    assert syn["CandRecall off"] is syn["SilentMerge off"] is syn["CandRecall naive"] is syn["SilentMerge naive"] is None
    assert syn["FlagR on"] == 1.0 and syn["FlagR off"] == 0.0
    assert syn["Leakage on"] == syn["Leakage naive"] == syn["Leakage off"] == 0
    assert syn["seconds"] < 5  # the spec's budget is 2 s; slack for a cold lexicon cache
    assert data["metrics"]["gold"]["valid"] and "store part skipped (--quick)" in data["notes"]
    assert {d["id"] for d in data["details"]} == {f"s-{x}" for x in (
        "alias", "head", "trap", "period-early", "period-late", "ambiguous", "substring", "weak", "floor")}


def test_alias_labeller_reads_only_the_items_patterns():
    from taochronos.evals.aliases import Labeller

    item = {"asked": "将军", "asked_cues": ["芒硝"], "false_friends": ["大将军", "将军之官"], "wrong": ["武官"],
            "referents": [{"head": "大黄", "names": ["大黄", "锦纹"], "valid": [None, 960]}]}
    label = Labeller(item)
    assert label("将军二两，芒硝三合", (400, 400)) == (True, False, False)
    assert label("大将军出征", (300, 300)) == (False, False, True)  # only inside a masked string
    assert label("将军者，非药也", (300, 300)) == (False, False, True)  # without a cue
    assert label("大黄四两", (400, 400)) == (False, True, False)
    assert label("大黄四两", (1200, 1200)) == (False, False, False)  # outside the referent's window: no label
    assert label("武官也", (300, 300)) == (False, False, True)
    assert Labeller({"asked": "青木香", "false_friends": [], "wrong": [], "referents": [
        {"head": "木香", "names": ["木香"], "valid": None}]})("青木香", None) == (True, False, False)


def test_alias_eval_never_uses_the_layers_gates():
    """Labels come from the items' patterns: the eval imports the layer's records and writer only, and never calls a
    gate of an alias index (it reads what the search answers)."""
    import ast

    tree = ast.parse((HOME / "src/taochronos/evals/aliases.py").read_text(encoding="utf-8"))
    gates = {"gate_form", "overlaps", "meets", "assemble", "free_offsets", "covers", "drug_context", "accept",
             "reading", "readings", "floor_flag", "scan", "expansions", "view", "referents", "names", "groups_for",
             "by_group"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("classics.aliases"):
            assert {a.name for a in node.names} <= {"AliasRecord", "Referent", "Witness", "write_records"}
        if isinstance(node, ast.Import):
            assert not any(a.name.endswith("classics.aliases") for a in node.names)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in gates, node.func.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("getattr", "hasattr"):
            target, name = node.args[0], node.args[1]
            if isinstance(name, ast.Constant):
                assert name.value not in gates, name.value
            else:  # a name chosen at run time only where Naive hands today's analyzer what it does not override
                assert ast.unparse(target) == "self.base", ast.unparse(node)


def test_alias_gold_holds_its_contract():
    from taochronos.evals.aliases_gold import load_gold, split_of, validate

    gold = load_gold(HOME)
    assert validate(gold) == []
    assert all(item["split"] == split_of(item["group"]) for item in gold["items"])
    # names added after the first held-out report (2026-10-15) are corrections of dev items only, dated from it on
    late = [(item["split"], a["date"]) for item in gold["items"] for a in item["adjudicated"]
            if a["by"] == "correction" or a["date"] > gold["frozen"]]
    assert late and all(split == "dev" and date >= "2026-10-15" for split, date in late)


def test_alias_eval_retention_check_needs_the_asked_first_rule():
    """The planted 国老治虚劳: passages on 虚劳 outrank 国老, which keeps its places only by the asked-first rule."""
    from taochronos.evals.aliases import _checks, synthetic_search

    with synthetic_search(HOME) as (r, legacy, _):
        assert _checks(r, legacy)["places_and_retention"]
        r.alias = {**r.alias, "asked_first": "off"}
        checks = _checks(r, legacy)
    assert not checks["places_and_retention"] and checks["no_merge"]


def _q(asked=(), expansions=(), after=None, before=None):
    from types import SimpleNamespace

    return SimpleNamespace(alias_view={"asked": list(asked), "expansions": list(expansions)}, after=after,
                           before=before)


def test_alias_eval_lists_the_items_drugs_not_the_name_asked():
    from taochronos.evals.aliases import listed, same_drug, score

    hu = {"id": "x", "type": "ambiguous", "asked": "胡王使者", "expect_candidates": ["独活", "白头翁"], "referents": [
        {"head": "独活", "names": ["独活", "护羌使者"]}, {"head": "白头翁", "names": ["白头翁", "野丈人"]}]}
    q = _q([{"surface": "胡王使者", "referents": [{"head": "胡王使者"}, {"head": "白头翁"}]}])
    assert listed(hu, q) == ["白头翁"]  # the lexicon's own entry for the name asked is no candidate
    ku = {"id": "y", "type": "ambiguous", "asked": "苦菜", "expect_candidates": ["苦菜", "贝母"], "referents": [
        {"head": "苦菜", "names": ["苦菜"]}, {"head": "贝母", "names": ["贝母"]}]}
    assert listed(ku, _q([{"surface": "苦菜", "referents": [{"head": "苦菜"}, {"head": "贝母"}]}])) == ["苦菜", "贝母"]
    tong = {"id": "z", "type": "head", "asked": "铜绿", "expect_candidates": [], "referents": [
        {"head": "铜绿", "names": ["铜青"]}]}
    q = _q([{"surface": "铜绿", "referents": [{"head": "铜青"}]}],
           [{"surface": "铜青", "for": "铜绿", "direction": "drug→alias", "referent": "铜绿"}])
    assert listed(tong, q) == []  # the drug a head names is no candidate, by referent or by expansion
    # a window the question misses lists nothing; the gold's same-drug names map a spelling, never the asked form
    q = _q([{"surface": "通草", "referents": [{"head": "木通", "valid": [None, 960]}, {"head": "通脱木"}]}], after=1200)
    assert listed({"asked": "通草", "referents": [{"head": "通脱木", "names": []}]}, q) == ["通脱木"]
    same = same_drug([{"referents": [{"head": "磁石", "names": ["慈石"]}]},
                      {"referents": [{"head": "徐长卿", "names": ["鬼督邮"]}, {"head": "赤箭", "names": ["鬼督邮"]}]}])
    assert same["磁石"] == {"慈石"} and same["徐长卿"] == set() == same["赤箭"]  # a name two heads share is none
    chu = {"type": "ambiguous", "asked": "处石", "expect_candidates": ["磁石", "玄石"], "referents": [
        {"head": "磁石", "names": ["磁石"]}, {"head": "玄石", "names": ["玄石"]}]}
    q = _q([{"surface": "处石", "referents": [{"head": "慈石"}, {"head": "玄石"}]}])
    assert listed(chu, q) == ["慈石", "玄石"] and listed(chu, q, same) == ["磁石", "玄石"]
    # SilentMerge counts the expected drugs listed; candidates are None for a system without the layer
    texts = lambda pid: ("", None)
    counts = {"rel": 0, "asked": 0, "other": 0}
    row = score(hu, lambda text, yr: (False, False, False), texts, counts, _q([{"surface": "胡王使者", "referents": [
        {"head": "胡王使者"}, {"head": "白头翁"}]}]), [], [], 1.0)
    assert row["merge"] is True and row["cand"] == (1, 1, 2)
    row = score(hu, lambda text, yr: (False, False, False), texts, counts, _q(), [], [], 1.0, layered=False)
    assert row["merge"] is None and row["cand"] is None


def test_alias_eval_maps_the_asked_drug_by_its_lexicon_forms():
    """The asked drug's own expansions name the referent its lexicon entry holds (紫葳, filed with 凌霄花); another
    drug listed beside it is never mapped through those forms (慈石 stays 慈石 under 处石, whose entry is 磁石's)."""
    from types import SimpleNamespace

    from taochronos.evals.aliases import _drug, asked_forms, listed

    zi = {"asked": "紫葳", "expect_candidates": ["凌霄花"], "referents": [{"head": "凌霄花", "names": ["凌霄花"]}]}
    q = _q([], [{"surface": s, "for": "紫葳", "direction": "drug→alias", "referent": "紫葳"} for s in ("凌霄", "女葳")])
    assert listed(zi, q) == []
    assert listed(zi, q, forms={"紫葳", "凌霄花", "陵苕"}) == ["凌霄花"]
    chu = {"asked": "处石", "expect_candidates": ["磁石", "玄石"], "referents": [
        {"head": "磁石", "names": ["磁石"]}, {"head": "玄石", "names": ["玄石"]}]}
    q = _q([{"surface": "处石", "referents": [{"head": "慈石"}, {"head": "玄石"}]}])
    assert listed(chu, q, forms={"磁石", "元石", "处石"}) == ["慈石", "玄石"]
    # a drug the gold names maps to its referent before any forms: forms meeting two referents tell neither apart
    # (玄石 is no 磁石 when 处石's forms hold both), and a drug named beside another's surfaces is still itself
    q = _q([{"surface": "处石", "referents": [{"head": "磁石"}, {"head": "玄石"}]}])
    assert listed(chu, q) == ["磁石", "玄石"] == listed(chu, q, forms={"处石", "磁石", "玄石"})
    assert _drug(chu, "玄石", {"磁石"}) == "玄石" and _drug(chu, "慈石", {"磁石"}) == "磁石"
    # a form the item calls wrong is no name of the asked drug: listed, it is a candidate of its own, not the referent
    # (the lexicon entry holds a wrong drug's name, as a herb's entry can hold another's 一名)
    mei = {"asked": "甲名", "expect_candidates": ["甲药"], "referents": [{"head": "甲药", "names": ["甲药"]}],
           "wrong": ["乙药"]}
    q = _q([{"surface": "甲名", "referents": [{"head": "乙药"}]}])
    assert listed(mei, q, forms={"甲名", "甲药", "乙药"}) == ["乙药"]
    assert listed({**mei, "wrong": []}, q, forms={"甲名", "甲药", "乙药"}) == ["甲药"]  # else the lexicon decides
    yi = {**mei, "wrong": [], "referents": mei["referents"] + [{"head": "乙药", "names": ["乙药", "乙草"]}]}
    q = _q([{"surface": "甲名", "referents": [{"head": "乙草"}]}])
    assert listed(yi, q, forms={"甲名", "甲药", "乙草"}) == ["乙药"]  # another referent's name, never the asked drug
    # the forms: the asked form's herb entry, else that of a name read inside it (慎火 of 慎火草), normalised
    entries = {"herb:紫葳": SimpleNamespace(category="herb", surfaces=lambda: ["紫葳", "淩霄花"]),
               "herb:景天": SimpleNamespace(category="herb", surfaces=lambda: ["景天", "慎火"]),
               "formula:x": SimpleNamespace(category="formula", surfaces=lambda: ["某汤"])}
    pack = SimpleNamespace(variants=SimpleNamespace(normalize_text=lambda s: s.replace("淩", "凌")),
                           lexicon=SimpleNamespace(entry=entries.get))
    assert asked_forms(pack, SimpleNamespace(asked={"紫葳": "herb:紫葳"}), "紫葳") == {"紫葳", "凌霄花"}
    assert asked_forms(pack, SimpleNamespace(asked={"慎火": "herb:景天", "慎火草": None}), "慎火草") == {
        "慎火草", "景天", "慎火"}
    assert asked_forms(pack, SimpleNamespace(asked={"某汤": "formula:x"}), "某汤") == {"某汤"}
    assert asked_forms(pack, SimpleNamespace(), "国老") == {"国老"}


def test_alias_eval_counts_a_stop_names_listed_drugs():
    """A stop name asked on its own lists its drugs as candidates (status ``stop``): they count for the gold item that
    expects them, not against one that expects none, and they are no reading of the name for a resolution row."""
    from types import SimpleNamespace

    from taochronos.evals.aliases import listed, resolve, score

    jie = {"type": "trap", "asked": "解离", "expect_candidates": ["防己"], "referents": [
        {"head": "防己", "names": ["防己", "木防己"]}]}
    stop = {"surface": "解离", "term": None, "ambiguous": False, "note": "…",
            "referents": [{"head": "防己", "status": "stop", "valid": None}]}
    q = _q([stop], before=960)
    assert listed(jie, q) == ["防己"]
    row = score(jie, lambda text, yr: (False, False, False), lambda pid: ("", None), {"rel": 0, "asked": 0, "other": 0},
                q, [], [], 1.0)
    assert row["cand"] == (1, 1, 1) and row["merge"] is None
    jiu = {"type": "ambiguous", "asked": "救火", "expect_candidates": ["景天", "萤火"], "referents": [
        {"head": "景天", "names": ["景天"]}, {"head": "萤火", "names": ["萤火"]}]}
    q = _q([{"surface": "救火", "ambiguous": True, "referents": [{"head": "景天", "status": "stop"},
                                                                 {"head": "萤火", "status": "stop"}]}])
    assert listed(jiu, q) == ["景天", "萤火"]
    # an item that expects none reads the name as no drug, and a stop's listing beside its note agrees: no candidate,
    # no loss of precision; a drug listed as a reading of the name still counts against it
    trap = {"type": "trap", "asked": "某词", "expect_candidates": [], "referents": [{"head": "某虫", "names": []}]}
    q = _q([{**stop, "surface": "某词", "referents": [{"head": "某虫", "status": "stop", "valid": None}]}])
    assert listed(trap, q) == []
    row = score(trap, lambda text, yr: (False, False, False), lambda pid: ("", None),
                {"rel": 0, "asked": 0, "other": 0}, q, [], [], 1.0)
    assert row["cand"] == (0, 0, 0)
    assert listed(trap, _q([{"surface": "某词", "referents": [{"head": "某虫", "status": "candidate"}]}])) == ["某虫"]
    pack = SimpleNamespace(variants=SimpleNamespace(normalize_text=lambda s: s),
                           lexicon=SimpleNamespace(entry=lambda term: None))
    q = SimpleNamespace(alias_view={"asked": [{**stop, "surface": "月经", "referents": [
        {"head": "某药", "status": "stop"}, {"head": "某草", "status": "stop"}], "ambiguous": True}]},
                        expansions=[], asked={"月经": None})
    assert resolve({"surface": "月经", "expect_action": "none", "expect_heads": []}, q, {}, pack) == ("none", [], True)


def test_alias_eval_resolution_rows():
    from types import SimpleNamespace

    from taochronos.evals.aliases import resolve

    entry = SimpleNamespace(category="herb", term="山药", surfaces=lambda: ["山药", "薯蓣"])
    pack = SimpleNamespace(variants=SimpleNamespace(normalize_text=lambda s: s),
                           lexicon=SimpleNamespace(entry=lambda term: entry if term == "herb:山药" else None))
    exp = lambda surface, head, direction, why=None: SimpleNamespace(
        surface=surface, head=head, direction=direction, why=why)
    same = {"磁石": {"慈石"}}
    # an alias read as its drug, the head matched through the same-drug names
    q = SimpleNamespace(alias_view={"asked": [{"surface": "处石", "referents": [{"head": "慈石", "status": "open"}]}]},
                        expansions=[exp("慈石", "慈石", "alias→drug")], asked={"处石": None})
    assert resolve({"surface": "处石", "expect_action": "expand", "expect_heads": ["磁石"]}, q, same, pack) == (
        "expand", ["慈石"], True)
    # several drugs listed: a candidate row, never an expansion
    q = SimpleNamespace(alias_view={"asked": [{"surface": "鬼督邮", "ambiguous": True, "referents": [
        {"head": "徐长卿", "status": "cue"}, {"head": "赤箭", "status": "cue"}]}]}, expansions=[], asked={"鬼督邮": None})
    row = {"surface": "鬼督邮", "expect_action": "candidate", "expect_heads": ["赤箭", "徐长卿"]}
    assert resolve(row, q, same, pack) == ("candidate", ["徐长卿", "赤箭"], True)
    assert resolve({**row, "expect_action": "expand"}, q, same, pack)[2] is False
    # a lexicon herb filed under another name expands to it; a head reaching only its own names is none
    q = SimpleNamespace(alias_view={}, expansions=[], asked={"薯蓣": "herb:山药"})
    assert resolve({"surface": "薯蓣", "expect_action": "expand", "expect_heads": ["山药"]}, q, same, pack)[2]
    q = SimpleNamespace(alias_view={}, expansions=[exp("国老", "甘草", "drug→alias")], asked={"甘草": None})
    assert resolve({"surface": "甘草", "expect_action": "none", "expect_heads": []}, q, same, pack) == ("none", [], True)


def test_alias_eval_acceptance_and_the_gain_where_off_answers():
    from taochronos.evals.aliases import _acceptance, aggregate, table

    def row(iid, p10, labels, on50, kind="alias", merge=None, cand=None):
        return {"id": iid, "split": "dev", "type": kind, "P@10": p10, "nDCG@10": p10, "AskedRet@10": 1.0,
                "n_asked": 10, "ON@10": 0, "ON@50": on50, "XR@50": None, "Wrong@10": 0, "cand": cand, "merge": merge,
                "flag": None, "leak": 0, "ms": 10.0, "labels": labels}

    rows = {"off": [row("a", 0.0, "", 0), row("b", 0.5, "a.a.", 1), row("c", 1.0, "aaaa", 1, "ambiguous")],
            "on": [row("a", 1.0, "aaaa", 1, cand=(0, 0, 0)), row("b", 0.75, "aaa.", 1, cand=(0, 0, 0)),
                   row("c", 1.0, "aaaa", 1, "ambiguous", False, (2, 2, 2))]}
    tables = {s: {"dev": table(rs)} for s, rs in rows.items()}
    acc = _acceptance(tables, "dev", rows)
    assert acc["P@10 gain"] == 0.4167 and acc["P@10 gain where off answers"] == 0.125  # (.75 + 1) / 2 → (.5 + 1) / 2
    assert acc["items off answers"] == [2, 3]
    assert acc["checks"]["P@10 +0.03"] and acc["checks"]["CandRecall ≥ 0.9"] and acc["checks"]["SilentMerge 0"]
    assert acc["checks"]["ON@50 ≥ 1.5×off"] is True  # 3 ≥ 1.5 × 2
    tables["on"]["dev"]["all"]["ON@50"] = 2
    assert _acceptance(tables, "dev")["checks"]["ON@50 ≥ 1.5×off"] is False
    assert aggregate(rows["off"])["SilentMerge"] is None and aggregate(rows["off"])["CandRecall"] is None


def _tiny_store(path):
    from taochronos.plugins.classics.domain import DomainPack
    from taochronos.plugins.classics.store import CorpusStore

    normalize = DomainPack(HOME / "domains" / "classics").variants.normalize_text
    store = CorpusStore(path, create=True)
    books = {"bc_a": ("本草", [500, 500], ["甘草，一名国老，味甘平。", "大黄四两，芒硝三合。"]),
             "jc_c030": ("本草", [1544, 1592], ["甘草（国老　蜜甘）"]),
             "fang_b": ("方书", [1100, 1100], ["国老二两，生姜三两，大枣十二枚。", "甘草汤：甘草二两，水煮服，治咽痛。"])}
    rows = []
    for bid, (category, (y0, y1), texts) in books.items():
        store.put_book({"id": bid, "title": bid, "category": category, "composition": [y0, y1]}, "jicheng")
        rows += [{"id": f"{bid}.{seq:05d}", "book_id": bid, "seq": seq, "year": (y0 + y1) / 2, "y_start": y0,
                  "y_end": y1, "locator": {}, "temporal": {}, "text": text} for seq, text in enumerate(texts)]
    store.add_passages(rows, normalize)
    store.commit()
    store.close()


def test_alias_eval_profile_harness_leaves_the_store_alone(tmp_path, monkeypatch):
    """The 别名录 is out of every read path, claims go to a cache of the harness's own (the store's claim cache is
    neither read nor written), unknown profiles are refused, and a gold that fails its checks runs no held-out item."""
    import importlib
    import sqlite3

    from taochronos.evals.aliases_gold import load_gold
    from taochronos.evals.base import EvalContext

    path = tmp_path / "corpus" / "tcm.sqlite"
    _tiny_store(path)
    ctx = EvalContext(HOME, data_dir=tmp_path)
    harness = ctx.profile_harness("web-canon", exclude_books=["jc_c030"])
    assert sorted(harness.corpus.books) == ["bc_a", "fang_b"]
    retriever = harness.capabilities.get("retriever")
    hits = retriever.search("甘草", k=10, aliases="on")[1]
    assert hits and not any(h.passage_id.startswith("jc_c030") for h in hits)
    cached = lambda: sqlite3.connect(path).execute("SELECT COUNT(*) FROM claim_cache").fetchone()[0]
    assert harness.corpus.store.db.execute("SELECT COUNT(*) FROM claim_cache").fetchone()[0] > 0 and cached() == 0
    shared = ctx.profile_harness("web-canon", private_claims=False)
    shared.capabilities.get("retriever").search("甘草", k=10, aliases="off")
    assert cached() > 0  # what the private cache keeps out of the store

    A = importlib.import_module("taochronos.evals.aliases")
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL", "web-canon,no-such-profile")
    with pytest.raises(ValueError, match="no-such-profile"):
        A.store(ctx, load_gold(HOME), [], [])
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL", "web-canon")
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL_SYSTEMS", "off,on")
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL_VIEWS", "main")
    gold = load_gold(HOME)
    dev = {i["id"] for i in gold["items"] if i["split"] == "dev"}
    # a gold that holds on file but fails on the store (the tiny store has none of its witnesses): checked before any
    # item is chosen, it runs no held-out item, and its note gives an example on a dev item only
    searched = []

    def run_items(items, *args, **kw):
        searched.append({i["split"] for i in items})
        return {s: [] for s in args[2]}, []

    checks, notes = {}, []
    with monkeypatch.context() as m:
        m.setattr(A, "run_items", run_items)
        out = A.store(ctx, gold, notes, [], checks)["web-canon"]
    assert checks["store_valid"] is False and checks["store_checks"] == "witnesses"
    assert searched == [{"dev"}] and out["split"] == "dev" and out["results"]["splits"] == ["dev"]
    assert "held-out split refused: the gold fails its checks on the store (aliases_gold.validate)" in notes
    note = next(n for n in notes if n.startswith("gold on the store: "))
    assert ", e.g. " in note and note.split(", e.g. ", 1)[1].split(": ", 1)[0] in dev
    # refused by hand (a gold that fails its checks on file)
    notes, details = [], []
    out = A.store(ctx, gold, notes, details, heldout=False)["web-canon"]
    assert out["split"] == "dev" and out["results"]["splits"] == ["dev"] and "held-out split refused" in notes[0]
    assert {d["id"] for d in details} == dev


def test_alias_eval_problem_notes_name_no_heldout_item():
    from taochronos.evals.aliases import _problems_note
    from taochronos.evals.aliases_gold import split_of

    groups = [f"g{k}" for k in range(40)]
    dev_group = next(g for g in groups if split_of(g) == "dev")
    held_group = next(g for g in groups if split_of(g) == "heldout")
    gold = {"items": [{"id": "d-1", "group": dev_group, "split": "dev"},
                      {"id": "h-1", "group": held_group, "split": "heldout"},
                      {"id": "h-2", "group": held_group, "split": "dev"}]}  # a moved split: its rule says held-out
    problems = ["h-1: witness x of 某名 is missing", "h-2: witness y of 某名 is missing", "tuned: [某名]",
                "d-1: witness z of 甲名 is missing"]
    assert _problems_note("gold on the store", problems, gold) == (
        "gold on the store: 4 problems, 1 on dev items, e.g. d-1: witness z of 甲名 is missing")
    assert _problems_note("gold", problems[:3], gold) == "gold: 3 problems, 0 on dev items"


def test_alias_eval_times_warm_calls_only(monkeypatch):
    """A first call on an item fills caches every system then reads (the claims of its passages): latency is timed
    after each system has searched the item once, so the rotation's first system is not charged for it."""
    import importlib
    from types import SimpleNamespace

    A = importlib.import_module("taochronos.evals.aliases")  # the package exports the suite under the same name
    clock, warm, calls = [0.0], set(), []

    def search(text, k, aliases=None, alias_params=None):
        clock[0] += 0.001 if text in warm else 0.5  # seconds: a cold item costs 500 ms, a warm one 1 ms
        warm.add(text)
        calls.append((aliases, k))
        return SimpleNamespace(alias_view={}, after=None, before=None), []

    monkeypatch.setattr(A, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    corpus = SimpleNamespace(normalize=lambda s: s, contains=lambda *a, **kw: [])
    retriever = SimpleNamespace(search=search, pack=SimpleNamespace(variants=SimpleNamespace(normalize_text=str)),
                                analyzer=SimpleNamespace(analyze=lambda text: SimpleNamespace(after=None, before=None)))
    items = [{"id": f"i{k}", "split": "dev", "type": "alias", "query": f"问{k}", "asked": f"名{k}",
              "referents": [{"head": f"药{k}", "names": []}]} for k in range(4)]
    rows, _ = A.run_items(items, retriever, corpus, ["off", "on"])
    assert [round(r["ms"], 3) for s in ("off", "on") for r in rows[s]] == [1.0] * 8
    assert calls[:4] == [("off", 10), ("on", 10), ("off", 10), ("off", 50)]  # each system once untimed, then timed
