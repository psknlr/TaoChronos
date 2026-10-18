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
    # the paired bootstrap's intervals: the differences of the aggregates, each inside its interval
    boot = syn["bootstrap"]
    assert boot["resamples"] == 2000 and boot["level"] == 0.95 and boot["pairs"] == ["on-off", "on-naive"]
    assert boot["synthetic"]["items"] == 9 and set(boot) - {"synthetic"} == {"resamples", "seed", "level", "metrics",
                                                                               "pairs"}
    for pair, other in (("on-off", "off"), ("on-naive", "naive")):
        got = boot["synthetic"][pair]
        assert got["P@10"]["diff"] == pytest.approx(syn["P@10 on"] - syn[f"P@10 {other}"], abs=1e-4)
        assert got["Wrong@10"]["diff"] == syn["Wrong@10 on"] - syn[f"Wrong@10 {other}"]
        assert got["AskedRet@10"]["diff"] == pytest.approx(syn["AskedRet@10 on"] - syn[f"AskedRet@10 {other}"],
                                                           abs=1e-4)
        for key in ("P@10", "nDCG@10", "Wrong@10", "AskedRet@10"):
            lo, hi = got[key]["ci95"]
            assert lo <= got[key]["diff"] <= hi, (pair, key)
    assert boot["synthetic"]["on-off"]["P@10"]["ci95"][0] > 0  # the layer's gain holds on resampled items
    assert run_suites(["aliases"], home=HOME, data_dir=tmp_path, quick=True)["aliases"]["metrics"]["synthetic"][
        "bootstrap"] == boot  # seeded: every run draws the same resamples


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


@pytest.mark.parametrize("section, head", [
    ("五味子", "五味子"), ("百合（本经中品）", "百合"), ("一七一　五味子", "五味子"), ("十、百部", "百部"), ("12. 五倍子", "五倍子"),
    ("一八一梔子", "梔子"), ("一八三　蘗（柏）木", "蘗木"), ("一○七　白石脂", "白石脂"), ("三○一 　藥實根", "藥實根"),
    ("卷二 · 五灵脂", "五灵脂"), ("二八七", None), ("六畜毛蹄甲", None),
])
def test_alias_gold_reads_entry_headings_as_the_build_does(section, head):
    """The pools' 本草 entries are headed as the build heads them: the same numbering rule (a drug's name that opens
    with a numeral keeps it; ○ numbers as 〇 does), here of two to four characters."""
    from taochronos.evals import aliases_gold
    from taochronos.plugins.classics import aliasbuild

    assert aliases_gold._SECTION_NUM.pattern == aliasbuild._SECTION_NUM.pattern
    assert aliases_gold._entry_head(section, lambda s: s) == head
    if head is not None:
        assert aliasbuild.entry_head(section, lambda s: s) == head


def test_alias_gold_pools_take_no_chapter_number_for_a_drug():
    """A heading of numerals alone (a chapter's 六七, which the build keeps whole for 三七's sake) heads a pool entry
    only as a lexicon herb."""
    from taochronos.evals.aliases_gold import _entry_drug

    herbs = {"三七", "百合"}
    for section, head in (("六七", None), ("一一", None), ("三七", "三七"), ("一八三　百合", "百合"), ("卷二 · 六九", None)):
        assert _entry_drug(section, lambda s: s, herbs) == head, section


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


def test_alias_eval_bootstrap_is_paired_seeded_and_aggregate(monkeypatch):
    """The intervals pair the systems' rows by item, compute each metric on a resample as ``aggregate`` does (means
    over the items that have the metric, Wrong@10 a total) and draw the same resamples on every run."""
    from taochronos.evals.aliases import (
        _resamples,
        bootstrap,
        contrasts,
        interval_text,
        intervals,
    )

    def row(k, split="dev"):
        return {"id": f"i{k}", "split": split, "P@10": k / 20, "nDCG@10": k / 20, "Wrong@10": k % 3,
                "AskedRet@10": None if k % 4 == 0 else 0.5 + k / 40}

    base = [row(k) for k in range(20)]
    shifted = [{**r, "P@10": r["P@10"] + 0.1, "nDCG@10": r["nDCG@10"] + 0.1, "Wrong@10": r["Wrong@10"] + 1}
               for r in base]
    # a shift on every item is no uncertainty when the items are paired — in any order of the rows
    got = bootstrap({"off": base, "on": list(reversed(shifted))}, [("on", "off")], resamples=500)
    assert got["items"] == 20
    assert got["on-off"]["P@10"] == got["on-off"]["nDCG@10"] == {"diff": 0.1, "ci95": [0.1, 0.1]}
    assert got["on-off"]["Wrong@10"] == {"diff": 20, "ci95": [20, 20]}  # a total: one more wrong hit on 20 items
    assert got["on-off"]["AskedRet@10"] == {"diff": 0.0, "ci95": [0.0, 0.0]}  # items without it left out
    # a difference that varies by item: an interval around it, the same on every run, another under another seed
    noisy = [{**r, "P@10": r["P@10"] + (0.3 if k % 2 else -0.1)} for k, r in enumerate(base)]
    rows = {"off": base, "on": noisy}
    got = bootstrap(rows, [("on", "off")], resamples=500)
    lo, hi = got["on-off"]["P@10"]["ci95"]
    assert lo < got["on-off"]["P@10"]["diff"] == 0.1 < hi
    assert got == bootstrap(rows, [("on", "off")], resamples=500)
    assert got != bootstrap(rows, [("on", "off")], resamples=500, seed=1)
    # the mean over the items that have the metric, as aggregate computes it
    fewer = [{**r, "AskedRet@10": None} if k < 10 else r for k, r in enumerate(base)]
    want = sum(r["AskedRet@10"] for r in base[10:] if r["AskedRet@10"] is not None) / 8 \
        - sum(r["AskedRet@10"] for r in base if r["AskedRet@10"] is not None) / 15
    assert bootstrap({"off": base, "on": fewer}, [("on", "off")])["on-off"]["AskedRet@10"]["diff"] == round(want, 4)
    # every pair on the items all its systems scored; nothing for no resamples or no pair
    assert bootstrap({"off": base, "on": shifted[1:], "naive": base}, [("on", "off"), ("on", "naive")])["items"] == 19
    assert bootstrap(rows, [("on", "naive")]) == {} and bootstrap(rows, [("on", "off")], resamples=0) == {}
    assert contrasts(["off", "naive", "on", "analysis", "on@baseline", "naive@baseline"]) == [
        ("on", "off"), ("on", "naive"), ("on", "on@baseline"), ("naive", "naive@baseline")]
    assert contrasts(["off", "analysis", "gates"]) == []
    # per split, and over all of them
    split_rows = {s: [{**r, "split": "dev" if k % 2 else "heldout"} for k, r in enumerate(rs)] for s, rs in rows.items()}
    got = intervals(split_rows, ["dev", "heldout"], resamples=100)
    assert got["pairs"] == ["on-off"] and [got[s]["items"] for s in ("dev", "heldout", "all")] == [10, 10, 20]
    assert got["dev"]["on-off"]["P@10"]["diff"] == 0.3 and got["heldout"]["on-off"]["P@10"]["diff"] == -0.1
    assert intervals(split_rows, ["dev"], resamples=0) == {}
    assert interval_text({"diff": 0.049, "ci95": [0.012, 0.09]}, "P@10") == "+0.049 [+0.012, +0.090]"
    assert interval_text({"diff": -9, "ci95": [-16, -3]}, "Wrong@10") == "-9 [-16, -3]"
    assert interval_text({"diff": None, "ci95": None}, "P@10") is None
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP", "300")
    assert _resamples() == 300
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP", "many")
    with pytest.raises(ValueError, match="TAOCHRONOS_ALIAS_EVAL_BOOTSTRAP"):
        _resamples()


def test_alias_eval_compares_two_layers_on_the_same_items(tmp_path):
    """A second layer searched on the same items in the same rotation (``on@baseline``, what
    TAOCHRONOS_ALIAS_EVAL_BASELINE runs): the same layer differs in nothing; one without 国老 and 王连 loses what
    they find, and on − on@baseline measures it with its interval."""
    import json

    from taochronos.evals.aliases import (
        SYN_HERBS,
        SYN_ITEMS,
        _syn_records,
        bootstrap,
        contrasts,
        layer_label,
        layer_pack,
        layer_retriever,
        run_items,
        synthetic_search,
    )
    from taochronos.plugins.classics.aliases import write_records

    def layer(name, records):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "context.json").write_text(json.dumps({"version": 1, "herbs": sorted(SYN_HERBS)}, ensure_ascii=False),
                                             encoding="utf-8")
        write_records(folder / "aliases.jsonl", records, {"labels": {"bielu-jc": "别名录（中醫笈成）"}})
        return folder

    same = layer("same", _syn_records())
    old = layer("old", [r for r in _syn_records() if r.s not in ("国老", "王连")])
    systems = ["off", "on", "on@baseline"]
    with synthetic_search(HOME) as (r, _, corpus):
        with pytest.raises(FileNotFoundError, match="no alias layer"):
            layer_pack(r.pack, tmp_path / "nowhere")
        boots = {}
        for name, folder in (("same", same), ("old", old)):
            pack = layer_pack(r.pack, folder)
            assert layer_label(pack)["records"] == len(list((folder / "aliases.jsonl").open(encoding="utf-8"))) - 1
            rows, _ = run_items(SYN_ITEMS, r, corpus, systems, others={"on@baseline": layer_retriever(r, pack)})
            assert contrasts(rows) == [("on", "off"), ("on", "on@baseline")]
            boots[name] = bootstrap(rows, contrasts(rows), resamples=500)
            labels = {s: [(x["id"], x["labels"], x["listed"]) for x in rows[s]] for s in systems}
            if name == "same":
                assert labels["on@baseline"] == labels["on"]
            else:
                moved = {a[0] for a, b in zip(labels["on"], labels["on@baseline"]) if a != b}
                assert moved and moved <= {"s-alias", "s-head", "s-substring"}, moved
    for key in ("P@10", "nDCG@10", "Wrong@10", "AskedRet@10"):
        got = boots["same"]["on-on@baseline"][key]
        assert got["diff"] == 0 and got["ci95"] == [0, 0], key
        got = boots["old"]["on-on@baseline"][key]
        assert got["ci95"][0] <= got["diff"] <= got["ci95"][1], key
    lost = boots["old"]["on-on@baseline"]  # 国老's 甘草 passages and 黄连's 王连 passage, in place of wrong hits
    assert lost["P@10"]["diff"] > 0 and lost["nDCG@10"]["diff"] > 0 and lost["Wrong@10"]["diff"] < 0
    assert boots["old"]["on-off"] == boots["same"]["on-off"]  # the same resamples for every pair


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


def test_alias_eval_store_part_compares_a_baseline_layer(tmp_path, monkeypatch):
    """TAOCHRONOS_ALIAS_EVAL_BASELINE on the store part: a wrong path fails before anything runs; the profile's own
    layer as the baseline searches every item as ``on`` does, so on − on@baseline is 0 with a zero interval; the
    baseline's tables, resolution, label and dev details sit beside the others'."""
    import importlib

    from taochronos.evals.aliases_gold import load_gold
    from taochronos.evals.base import EvalContext

    A = importlib.import_module("taochronos.evals.aliases")
    _tiny_store(tmp_path / "corpus" / "tcm.sqlite")
    ctx = EvalContext(HOME, data_dir=tmp_path)
    gold = load_gold(HOME)
    dev = [i for i in gold["items"] if i["split"] == "dev"]
    small = {**gold, "items": [i for i in dev if i["id"] in ("alias-01", "head-11")] + dev[:2],
             "resolution": [r for r in gold["resolution"] if r["split"] == "dev"][:4]}
    for name, value in (("", "web-canon"), ("_SYSTEMS", "off,on"), ("_VIEWS", "main"), ("_SPLITS", "dev"),
                        ("_BOOTSTRAP", "200"), ("_BASELINE", str(tmp_path / "nowhere"))):
        monkeypatch.setenv(f"TAOCHRONOS_ALIAS_EVAL{name}", value)
    with pytest.raises(FileNotFoundError, match="TAOCHRONOS_ALIAS_EVAL_BASELINE"):
        A.store(ctx, small, [], [])
    monkeypatch.setenv("TAOCHRONOS_ALIAS_EVAL_BASELINE", str(HOME / "domains" / "classics" / "aliases"))
    notes, details = [], []
    out = A.store(ctx, small, notes, details)["web-canon"]
    res = out["results"]
    assert set(res["views"]["main"]) == {"off", "on", "on@baseline"}
    assert res["baseline"]["fingerprint"] == res["store"]["layer"] and res["baseline"]["records"] > 0
    assert any(n.startswith("web-canon: baseline layer ") and "on@baseline" in n for n in notes)
    assert res["resolution"]["on@baseline"] == res["resolution"]["on"]
    assert out["P@10 on@baseline"] == out["P@10 on"] is not None and out["resolution on@baseline"] == out["resolution on"]
    boot = res["bootstrap"]
    assert boot["view"] == "main" and boot["resamples"] == 200 and boot["pairs"] == ["on-off", "on-on@baseline"]
    assert set(boot) - {"view", "resamples", "seed", "level", "metrics", "pairs"} == {"dev"}  # one split, no "all"
    assert boot["dev"]["items"] == 4
    assert boot["dev"]["on-on@baseline"]["P@10"] == {"diff": 0, "ci95": [0, 0]}
    assert boot["dev"]["on-on@baseline"]["Wrong@10"] == {"diff": 0, "ci95": [0, 0]}
    assert out["P@10 on-on@baseline"] == "+0.000 [+0.000, +0.000]" and out["Wrong@10 on-on@baseline"] == "+0 [+0, +0]"
    assert out["P@10 on-off"] == A.interval_text(boot["dev"]["on-off"]["P@10"], "P@10")
    assert len(details) == 4
    for d in details:
        assert d["systems"]["on@baseline"]["labels"] == d["systems"]["on"]["labels"]


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
