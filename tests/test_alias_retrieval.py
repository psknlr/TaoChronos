"""Alias-aware retrieval (ADR 0023): today's search when off, the side queue's places, the asked name's retention, the
gates and the labels — on a synthetic alias layer and corpus."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from taochronos.evals.textual import _write_corpus
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.aliases import (
    STOP_NOTE,
    AliasIndex,
    AliasRecord,
    Referent,
    Witness,
    gate_form,
    write_records,
)
from taochronos.plugins.retrieval import HybridRetriever, hybrid
from taochronos.plugins.retrieval.hybrid import Hit, _share

HOME = Path(__file__).resolve().parents[1]
R = Referent

RECORDS = [
    AliasRecord("甘草", ho="甘草", n=900, sh=0.9),
    AliasRecord("国老", n=12, sh=0.5, r=[R("甘草", t="herb:甘草", src=["bielu-jc", "curated"], w=[
        Witness("wit.000", 652, 652, "e"), Witness("wit.001", 1180, 1180, "e", True)])]),
    AliasRecord("蜜甘", n=8, sh=0.6, b=["石蜜甘"], r=[R("甘草", src=["bielu-jc"])]),
    AliasRecord("美草", n=25, sh=0.8, r=[R("甘草", st="cue", src=["bielu-jc"]), R("旋花", st="cue", src=["lexicon"])]),
    AliasRecord("旋花", ho="旋花", n=50, sh=0.8),
    AliasRecord("大黄", ho="大黄", n=900, sh=0.9),
    AliasRecord("将军", n=116, sh=0.4, b=["大将军", "将军之官"], r=[
        R("大黄", st="cue", c=["大黄", "锦纹", "川军", "荡涤", "承气"], src=["curated"]),
        R("石硫黄", st="candidate", src=["bielu-jc"])]),
    AliasRecord("石硫黄", ho="石硫黄", n=40, sh=0.8),
    AliasRecord("木通", ho="木通", n=500, sh=0.9),
    AliasRecord("通草", n=300, sh=0.85, r=[R("木通", k="old_name", v=(None, 960), src=["curated"]),
                                         R("通脱木", v=(960, None), src=["curated"])]),
    AliasRecord("通脱木", ho="通脱木", n=40, sh=0.8),
    AliasRecord("鬼督邮", n=50, sh=0.9, r=[R("徐长卿", st="cue", c=["徐长卿", "别仙踪"], src=["bielu-jc"]),
                                          R("赤箭", st="cue", c=["赤箭", "天麻"], src=["shiming"])]),
    AliasRecord("徐长卿", ho="徐长卿", n=100, sh=0.9),
    AliasRecord("赤箭", ho="赤箭", n=100, sh=0.9),
    AliasRecord("山药", ho="山药", n=800, sh=0.8, fl=1063, flb="taboo:yingzong"),
    AliasRecord("薯蓣", n=600, sh=0.8, r=[R("山药", k="taboo_rename", src=["taboo"])]),
    AliasRecord("署预", n=30, sh=0.8, r=[R("山药", k="spelling", v=(None, 1063), src=["curated"])]),  # synthetic window
    AliasRecord("黄柏", ho="黄柏", n=700, sh=0.9),
    AliasRecord("黄蘗", n=90, sh=0.8, r=[R("黄柏", k="spelling", src=["curated"])]),
    AliasRecord("小便", stop=True, n=5855, sh=0.04),
    # common words and invented drugs: a head the corpus seldom writes as a drug (the lexicon files 果然 as a herb), a
    # cue name mostly written otherwise, a false friend the lexicon files under 景天, a head written inside a longer
    # drug's name and with only a doubtful pairing, a name with only a first-use floor
    AliasRecord("果然", ho="果然", n=45, sh=0.0),
    AliasRecord("行水", n=93, sh=0.22, r=[R("云根", st="cue", c=["云根"], src=["bielu-jc"])]),
    AliasRecord("救火", stop=True, n=44, sh=0.14),
    AliasRecord("景天", ho="景天", n=100, sh=0.8),
    AliasRecord("云根", ho="云根", n=60, sh=0.7, b=["云根藤"], r=[R("云实", st="candidate", src=["bielu-jc"])]),
    AliasRecord("云参", n=50, sh=0.76, fl=1700, flb="curated"),
    # a false friend whose record keeps the drugs it was paired with (an acupoint's name, as the corpus mostly writes it)
    AliasRecord("云门", stop=True, n=60, sh=0.05, r=[R("云根", st="candidate", src=["bielu-jc"])]),
]
HERBS = ["甘草", "大黄", "芒硝", "大枣", "生姜", "人参", "桂枝", "茯苓", "黄连", "升麻", "木通", "通草", "徐长卿", "赤箭",
         "山药", "黄柏", "当归", "芍药", "干地黄", "景天", "云根", "云根藤"]
CN = "一二三四五六七八九十"
GANCAO = [f"治某病方{i}：甘草{CN[i % 10]}两，大枣十二枚，水煮服。" for i in range(25)]
GUOLAO = [f"又方{i}：国老{CN[i]}两，生姜三两，大枣十二枚，煮取。" for i in range(6)]
BOOKS = (
    [(f"g{i:02d}", f"甘草方{i}", "甲", 200 + 60 * i, "方书", [t]) for i, t in enumerate(GANCAO)]
    + [(f"l{i:02d}", f"国老方{i}", "乙", 600 + 150 * i, "方书", [t]) for i, t in enumerate(GUOLAO)]
    + [("m01", "蜜方", "丙", 900, "方书", ["蜜甘一两，人参二两，为末。"]),
       ("m02", "石蜜", "丙", 500, "本草", ["石蜜甘平，主心腹邪气。"]),
       ("u01", "美草", "丙", 500, "本草", ["美草，一名旋花，生平泽。"]),
       ("j01", "兵书", "丁", 300, "杂", ["大将军出征，三军随之。"]),
       ("j02", "灵兰", "丁", 300, "医经", ["心者，君主之官；肝者，将军之官。"]),
       ("j03", "承气方", "丁", 400, "方书", ["将军二两，芒硝三合，煮取一升。"]),
       ("j04", "武官", "丁", 400, "杂", ["将军者，武官也，非药。"]),
       ("j05", "大黄方", "丁", 450, "方书", ["大黄四两，芒硝三合，荡涤肠胃。"]),
       ("t01", "古通方", "戊", 550, "方书", ["通草三两，治小便不利。"]),
       ("t02", "古通方二", "戊", 600, "方书", ["通草、桂枝各二两。"]),
       ("t03", "清本草", "戊", 1700, "本草", ["通草，即通脱木之茎髓，色白。"]),
       ("t04", "清方", "戊", 1750, "方书", ["通草一钱，灯心一束。"]),
       ("t05", "清本草二", "戊", 1800, "本草", ["通脱木，生山侧，茎中有瓤。"]),
       ("k01", "木通古", "戊", 500, "本草", ["木通，主除脾胃寒热。"]),
       ("k02", "木通明", "戊", 1600, "方书", ["木通三两。"]),
       ("d01", "督邮一", "己", 500, "本草", ["徐长卿，一名鬼督邮，味辛温。"]),
       ("d02", "督邮二", "己", 600, "本草", ["赤箭，一名鬼督邮，杀鬼精物。"]),
       ("d03", "督邮三", "己", 700, "方书", ["鬼督邮二两，治鬼疰。"]),
       ("d04", "督邮四", "己", 750, "杂", ["鬼督邮之名，见于古书。"]),
       ("d05", "督邮五", "己", 760, "杂", ["古书载鬼督邮，今不识。"]),
       ("e01", "长卿一", "己", 500, "本草", ["徐长卿，味辛温，主蛊毒。"]),
       ("e02", "长卿二", "己", 550, "方书", ["徐长卿三两，治疫疠。"]),
       ("f01", "赤箭一", "己", 520, "本草", ["赤箭，味辛温，主杀鬼。"]),
       ("f02", "赤箭二", "己", 560, "本草", ["天麻者，赤箭之根也。"]),
       ("o01", "独摇", "己", 640, "本草", ["独摇草，生山谷，无风自动。"]),
       ("s01", "唐方", "庚", 700, "方书", ["山药三两，干地黄八两。"]),
       ("s02", "宋方", "庚", 1200, "方书", ["山药一两，茯苓一两。"]),
       ("s03", "薯蓣方", "庚", 650, "方书", ["薯蓣丸，治虚劳。"]),
       ("s04", "署预方", "庚", 1300, "方书", ["署预丸，治虚劳诸不足。"]),
       ("h01", "干葛方", "辛", 900, "方书", ["干葛二两，升麻一两。"]),
       ("h02", "葛根方", "辛", 1000, "方书", ["葛根四两，麻黄三两。"]),
       ("h03", "黄蘗方", "辛", 1100, "方书", ["黄蘗一两，黄连一两。"]),
       ("h04", "黄柏方", "辛", 1150, "方书", ["黄柏二两，知母二两。"]),
       ("x01", "服后", "壬", 800, "方书", ["服后果然汗出而愈。"]),
       ("x02", "汗论", "壬", 700, "医经", ["太阳病，汗出恶风。"]),
       ("y01", "行水", "癸", 800, "医经", ["行水之法，利小便也。"]),
       ("y02", "云根方", "癸", 900, "方书", ["云根三两，茯苓二两。"]),
       ("y03", "云根藤", "癸", 1000, "本草", ["云根藤，生山谷，蔓延。"]),
       ("y04", "云根藤方", "癸", 1100, "方书", ["云根藤二两，当归一两。"]),
       ("z01", "抱薪", "子", 300, "杂", ["抱薪救火，火愈盛。"]),
       ("z02", "慎火草", "子", 500, "本草", ["慎火草，一名救火，味苦平。"]),
       ("z03", "景天方", "子", 600, "方书", ["景天三两，治火疮。"]),
       ("z04", "慎火方", "子", 650, "方书", ["慎火三两，捣汁涂之。"]),
       ("z05", "误治", "子", 1700, "医案", ["误投桂枝人参，是抱薪救火也。"]),
       ("q01", "枳壳方", "丑", 1100, "方书", ["枳壳二两，麸炒。"]),
       ("q02", "枳实方", "丑", 300, "方书", ["枳实三枚，炙。"]),
       ("w01", "云参古", "寅", 1600, "本草", ["云参三钱，补中气。"]),
       ("w02", "云参清", "寅", 1800, "方书", ["云参五钱，白术三钱。"]),
       # a contents line and a heading that write 甘草 and nothing else: BM25 puts them first, the side queue last
       ("b01", "目录", "卯", 1900, "方书", ["炙甘草汤　甘草汤"]),
       ("b02", "目录二", "卯", 1900, "方书", ["甘草散"])]
)


def ids(hits) -> list[str]:
    return [h.passage_id for h in hits]


def side(hits) -> list:
    return [h for h in hits if h.tier in ("B", "X")]


@pytest.fixture(scope="module")
def layer(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("aliases")
    (root / "context.json").write_text(json.dumps({"version": 1, "herbs": sorted(HERBS)}, ensure_ascii=False),
                                       encoding="utf-8")
    return write_records(root / "aliases.jsonl", RECORDS, {"labels": {"bielu-jc": "别名录（中醫笈成）"}})


@pytest.fixture(scope="module")
def pack(layer) -> DomainPack:
    """The full-corpus lexicon (its weak one-character herbs 葛 and 黄 included) with the synthetic layer."""
    return DomainPack(HOME / "domains/classics", extra_lexicons=["lexicon-supplement", "lexicon-harvested"],
                      aliases_file=layer)


@pytest.fixture(scope="module")
def corpus(pack, tmp_path_factory) -> Corpus:
    corpus = Corpus.load(_write_corpus(tmp_path_factory.mktemp("alias-corpus"), BOOKS, "TaoChronos test (synthetic)"))
    corpus.normalize = pack.variants.normalize_text
    return corpus


@pytest.fixture(scope="module")
def retriever(pack, corpus) -> HybridRetriever:
    return HybridRetriever(pack, corpus, alias={"enabled": True})


# ------------------------------------------------------------------ the layer and its parameters
def test_the_pack_loads_the_layer_and_its_context(pack, tmp_path):
    assert pack.aliases.enabled and len(pack.aliases) == len(RECORDS) and pack.aliases.context["herbs"] == sorted(HERBS)
    plain = DomainPack(HOME / "domains/classics", aliases=["no-such-layer"])
    assert not plain.aliases.enabled and len(plain.aliases) == 0
    with pytest.raises(FileNotFoundError, match="aliases build --local"):
        DomainPack(HOME / "domains/classics", aliases_file=tmp_path / "aliases-local.jsonl")


def test_profiles_and_plugins_hand_the_layer_and_its_parameters_on(layer, corpus, tmp_path):
    from taochronos.bootstrap import HarnessContext
    from taochronos.kernel.profiles import load_profile
    from taochronos.kernel.registry import CapabilityRegistry

    # loaded; on for the site's corpus, whose search tool shows the labels (phase A), off for the full corpus (phase B)
    for name, enabled in (("web-canon", True), ("full-corpus", False)):
        config = {b["plugin"]: b.get("config") or {} for b in load_profile(name, [HOME / "profiles"]).bundles}
        assert config["taochronos.plugins.classics"]["aliases"] == ["aliases"]
        assert "aliases_local" not in config["taochronos.plugins.classics"]
        assert config["taochronos.plugins.retrieval"]["alias"]["enabled"] is enabled
    registry = CapabilityRegistry()
    context = HarnessContext(home=HOME, data_dir=tmp_path)
    registry.load_plugin("taochronos.plugins.classics", {"corpus_object": corpus, "aliases_local": str(layer)}, context)
    registry.load_plugin("taochronos.plugins.retrieval", {"alias": {"enabled": True, "share": [2, 10]}}, context)
    retriever = registry.get("retriever")
    assert retriever.pack.aliases.enabled and retriever.alias["share"] == [2, 10] and retriever.alias["expansions"] == 8


# ------------------------------------------------------------------ today's search when off
ORDINARY = [("膜原最早见于何书", {"k": 3}), ("三消的最早记载", {"k": 3}), ("宋代以前的消渴方", {"k": 20}),
            ("消渴", {"k": 10, "allowed": {"shanghanlun.c071"}}), ("太阳病", {"k": 10}), ("桂枝汤", {"k": 10})]


@pytest.fixture(scope="module")
def demo_pair(harness, layer):
    """Today's retriever on the demo corpus, and one over the same corpus whose pack has the layer and turns it on."""
    today = harness.capabilities.get("retriever")
    pack = DomainPack(HOME / "domains/classics", aliases_file=layer)
    return today, HybridRetriever(pack, harness.corpus, knowledge=today.knowledge, embedder=today.embedder,
                                  weights=today.weights, alias={"enabled": True})


def test_off_is_todays_search_ids_and_scores(demo_pair):
    today, layered = demo_pair
    for text, kw in ORDINARY + [("甘草", {"k": 10}), ("将军", {"k": 10}), ("唐以前的木通", {"k": 10})]:
        q0, h0 = today.search(text, **kw)
        q1, h1 = layered.search(text, aliases="off", **kw)
        assert [(h.passage_id, h.score, h.routes, h.matched) for h in h1] == [
            (h.passage_id, h.score, h.routes, h.matched) for h in h0], text
        assert q1.to_dict() == q0.to_dict() and not q1.asked and not q1.drugs and not q1.expansions
        assert not q1.alias_view
        assert all(not h.via and not h.flags and not h.tier for h in h1)


def test_ordinary_questions_are_unchanged_with_the_layer_on(demo_pair):
    today, layered = demo_pair
    for text, kw in ORDINARY:
        assert ids(layered.search(text, aliases="on", **kw)[1]) == ids(today.search(text, **kw)[1]), text


def test_the_default_pack_keeps_todays_search(harness):
    retriever = harness.capabilities.get("retriever")
    assert not harness.pack.aliases.enabled and retriever.alias["enabled"] is False
    for text, kw in ORDINARY:
        base = [(h.passage_id, h.score) for h in retriever.search(text, aliases="off", **kw)[1]]
        for mode in ("auto", "on"):
            q, hits = retriever.search(text, aliases=mode, **kw)
            assert [(h.passage_id, h.score) for h in hits] == base and not q.asked
    with pytest.raises(ValueError, match="aliases must be one of"):
        retriever.search("消渴", aliases="yes")


# ------------------------------------------------------------------ places and retention
@pytest.mark.parametrize("text", ["甘草", "国老", "鬼督邮", "将军"])
def test_side_places_and_asked_name_retention(retriever, text):
    whole = retriever.search(text, k=200)[1]
    main_total = len(whole) - len(side(whole))
    asked_total = sum(h.tier == "A" for h in whole)
    for k in (5, 10, 20):
        hits = retriever.search(text, k=k)[1]
        m = k - 3 * k // 10
        main_out = len(hits) - len(side(hits))
        assert len(side(hits)) <= 3 * k // 10 or main_out == main_total, (text, k)  # beyond that only once M ran out
        assert sum(h.tier == "A" for h in hits) >= min(asked_total, m), (text, k)
        assert len(set(ids(hits))) == len(hits)


def test_a_drug_is_found_under_its_other_names_with_their_labels(retriever):
    q, hits = retriever.search("甘草", k=10)
    assert q.asked == {"甘草": "herb:甘草"} and [e.surface for e in q.expansions if e.searched] == ["国老", "蜜甘", "美草"]
    assert [h.tier for h in hits] == ["A", "A", "A", "B", "A", "A", "B", "A", "A", "B"]
    b = side(hits)
    assert {h.matched[0] for h in b} <= {"国老", "蜜甘"} and all(h.routes == {"alias": i + 1} for i, h in enumerate(b))
    assert b[0].via == [{"surface": b[0].matched[0], "for": ["甘草"], "referent": "甘草", "direction": "drug→alias",
                         "kind": "异名",
                         "status": "open", "source": ["别名录（中醫笈成）"] + (["编者审定"] if b[0].matched[0] == "国老" else []),
                         "witness": "wit.000" if b[0].matched[0] == "国老" else None, "reading": "甘草", "p": 1.0}]
    every = ids(retriever.search("甘草", k=60)[1])
    assert "m01.000" in every and "m02.000" not in every  # 蜜甘 free, but not inside 石蜜甘
    assert "u01.000" not in every  # 美草 beside 旋花 is not 甘草's (the rival gate)


def test_an_alias_reaches_its_drug_and_keeps_its_own_places(retriever):
    q, hits = retriever.search("国老", k=10)
    assert q.asked == {"国老": None} and "国老" in q.quoted and q.terms == []
    assert [(e.surface, e.direction, e.searched) for e in q.expansions] == [("甘草", "alias→drug", True)]
    assert sum(h.tier == "A" for h in hits) == 6 and all("国老" in h.matched for h in hits if h.tier == "A")
    assert {h.matched[0] for h in side(hits)} == {"甘草"}
    assert q.alias_view["asked"][0]["referents"][0]["witness"] == "wit.000"
    web = HybridRetriever(retriever.pack, retriever.corpus, alias={"enabled": True, "witness_scope": "web"})
    q, hits = web.search("国老", k=10)
    assert q.alias_view["asked"][0]["referents"][0]["witness"] == "wit.001"
    assert {h.via[0]["witness"] for h in side(hits)} == {"wit.001"}


def test_a_shared_name_lists_every_referent_and_rotates_its_places(retriever):
    q, hits = retriever.search("鬼督邮", k=10)
    asked = q.alias_view["asked"][0]
    assert asked["surface"] == "鬼督邮" and asked["ambiguous"]
    assert [r["head"] for r in asked["referents"]] == ["徐长卿", "赤箭", "鬼督邮"]  # the lexicon's own entry too
    b = [h for h in hits if h.tier == "B"]
    assert [h.via[0]["referent"] for h in b] == ["徐长卿", "赤箭", "徐长卿", "赤箭"]  # round-robin over the drugs
    by = {h.passage_id: h for h in hits}
    assert by["d01.000"].via[0]["reading"] == "徐长卿" and by["d02.000"].via[0]["reading"] == "赤箭"
    assert by["d03.000"].via[0]["reading"] is None and "homonym:鬼督邮" in by["d03.000"].flags
    assert by["o01.000"].tier == "X" and by["o01.000"].via[0]["surface"] == "独摇草"  # the lexicon's other form


def test_a_common_word_needs_drug_context_and_is_demoted_after_the_side_queue_never_dropped(retriever):
    q, hits = retriever.search("将军", k=10)
    order = ids(hits)
    by = {h.passage_id: h for h in hits}
    assert q.drugs == ["将军"]  # alone, the name is asked as a drug
    assert order[:2] == ["j03.000", "j05.000"] and by["j03.000"].tier == "A"  # 将军二两: a dose
    assert by["j05.000"].tier == "B" and by["j05.000"].via[0]["referent"] == "大黄"
    assert set(order[2:]) == {"j01.000", "j02.000", "j04.000"} and all(by[p].tier == "D" for p in order[2:])
    assert by["j01.000"].flags == ["demoted:inside 大将军"] and by["j02.000"].flags == ["demoted:inside 将军之官"]
    assert by["j04.000"].flags == ["demoted:no-context"] and not by["j04.000"].via
    # the candidate 石硫黄 is listed, never a reading: 将军 beside a dose reads as 大黄
    assert by["j03.000"].via[0]["reading"] == "大黄" and by["j03.000"].via[0]["p"] == 1.0 and not by["j03.000"].flags
    loose = retriever.search("将军", k=10, alias_params={"ablate": ["gates", "boundary"]})[1]
    assert {h.passage_id for h in loose if h.tier == "A"} == {"j01.000", "j02.000", "j03.000", "j04.000"}


def test_lexicon_forms_go_to_the_side_queue_for_a_drug_and_other_referents_follow_the_main_queue(retriever):
    hits = retriever.search("山药", k=10)[1]
    by = {h.passage_id: h for h in hits}
    assert set(ids(hits)[:2]) == {"s01.000", "s02.000"} and ids(hits)[2:] == ["s04.000", "s03.000"]
    assert by["s03.000"].tier == "X" and by["s03.000"].via[0]["surface"] == "薯蓣"
    assert by["s03.000"].via[0]["kind"] == "避讳改名" and by["s03.000"].via[0]["source"] == ["词表"]
    assert by["s04.000"].flags == ["other-referent:署预"]  # 署预 is 山药 only before 1063 (synthetic)
    assert "anachronism:山药<1063:layer" in by["s01.000"].flags and not by["s02.000"].flags
    off = retriever.search("山药", k=10, alias_params={"asked_first": "off"})[1]
    assert all(h.tier != "X" for h in off) and "s03.000" in ids(off)


def test_slots_ablation_ranks_by_score(retriever):
    hits = retriever.search("国老", k=10, alias_params={"ablate": "slots"})[1]
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


# ------------------------------------------------------------------ periods, scope and order
def test_periods_bound_the_expansions_and_never_leak(retriever):
    q, hits = retriever.search("唐以前的木通", k=10)
    assert (q.after, q.before) == (None, 618) and hits and all(h.year < 618 for h in hits)
    assert {h.passage_id for h in hits if h.tier == "B"} == {"t01.000", "t02.000"}  # 通草 before 960 is 木通
    q, hits = retriever.search("清代的通草", k=10)
    assert [(e.surface, e.searched, e.why) for e in q.expansions] == [("通脱木", True, None), ("木通", False, "period")]
    assert q.alias_view["excluded"] == [{"surface": "木通", "for": "通草", "why": "period"}]
    assert all(1644 <= h.year < 1912 for h in hits) and "t05.000" in ids(hits)
    for text in ("宋代以前的国老", "宋代以前的甘草", "宋代以前的鬼督邮"):
        hits = retriever.search(text, k=20)[1]
        assert hits and all(h.year is not None and h.year < 960 for h in hits), text


def test_allowed_and_books_hold_for_side_hits(retriever, corpus):
    every = set(corpus.passage_ids())
    allowed = every - {f"g{i:02d}.000" for i in range(0, 25, 2)}
    hits = retriever.search("国老", k=20, allowed=allowed)[1]
    assert side(hits) and {h.passage_id for h in hits} <= allowed
    hits = retriever.search("国老", k=20, books=["l00", "l01", "g03", "g04"])[1]
    assert {h.passage_id for h in hits} == {"l00.000", "l01.000", "g03.000", "g04.000"}


def test_an_origin_question_reads_each_queue_in_order_with_the_asked_name_first(retriever):
    q, hits = retriever.search("国老最早见于何书", k=10)
    assert q.intent == "earliest" and hits[0].tier == "A" and "国老" in hits[0].matched
    assert sum(h.tier == "A" for h in hits) == 6  # every 国老, then the earliest 甘草 in the side places
    assert [i for i, h in enumerate(hits) if h.tier == "B"] == [3, 6, 8, 9]
    assert [h.passage_id for h in hits if h.tier == "B"] == ["g00.000", "g01.000", "g02.000", "g03.000"]
    for tiers in ({"A"}, {"B"}):
        years = [h.year for h in hits if h.tier in tiers]
        assert years == sorted(years)
    slots = retriever.search("国老最早见于何书", k=10, alias_params={"ablate": "slots"})[1]
    assert [h.year for h in slots] == sorted(h.year for h in slots)  # one ranking, one order


# ------------------------------------------------------------------ reading the question
def test_unknown_runs_and_alias_spans_outrank_weak_characters(retriever):
    analyzer = retriever.analyzer
    assert analyzer.analyze("干葛").terms == ["herb:葛"]  # today: the weak 葛
    q = analyzer.analyze("干葛", aliases=True)
    assert q.asked == {"干葛": None} and q.terms == [] and q.quoted == ["干葛"]
    assert ids(retriever.search("干葛", k=10)[1]) == ["h01.000"]  # not 葛根
    assert analyzer.analyze("黄蘗").terms == ["herb:黄"]
    q, hits = retriever.search("黄蘗", k=10)
    assert q.asked == {"黄蘗": None} and q.terms == []  # the alias over the weak 黄
    assert ids(hits) == ["h03.000", "h04.000"] and hits[1].via[0]["referent"] == "黄柏"
    assert analyzer.analyze("辰砂", aliases=True).asked == {"辰砂": None}  # no record: the run itself
    assert analyzer.analyze("辰砂", aliases=True, cfg={"unknown_runs": False}).terms == ["herb:砂"]
    q = analyzer.analyze("桂枝汤", aliases=True)
    assert q.asked == {"桂枝汤": "formula:桂枝汤"} and not q.expansions  # 桂枝 inside the formula is the formula's
    # only a herb's weak character gives way, and a run never takes in a question word
    for text in ("葛的功效", "葛治何病", "论葛", "肝藏血", "治风", "脾主运化"):
        q = analyzer.analyze(text, aliases=True)
        assert q.terms == analyzer.analyze(text).terms and all(s in text for s in q.asked) and not q.quoted, text
    assert not analyzer.analyze("葛的功效", aliases=True).drugs  # one character: the lexicon's 葛, as today
    assert analyzer.analyze("斑杖根", aliases=True).asked == {"斑杖根": None}  # two weak herbs and 杖: one name
    assert analyzer.analyze("姜枣", aliases=True).terms == analyzer.analyze("姜枣").terms  # all known: two herbs


def test_a_name_written_inside_its_own_blocker_is_not_asked(retriever):
    for text in ("肝者将军之官", "大将军"):
        q, hits = retriever.search(text, k=10)
        assert "将军" not in q.asked and not q.drugs and not q.expansions and not side(hits), text
        assert ids(hits) == ids(retriever.search(text, k=10, aliases="off")[1]), text
    assert "j02.000" in ids(retriever.search("肝者将军之官", k=10)[1])
    # a blocker that names a drug itself is asked as written, the name inside it not at all
    q, hits = retriever.search("云根藤", k=10)
    assert q.asked == {"云根藤": None} and q.drugs == ["云根藤"] and q.quoted == ["云根藤"] and q.terms == []
    assert set(ids(hits)) == {"y03.000", "y04.000"} and all(h.tier == "A" for h in hits)


def test_a_common_word_is_asked_as_a_drug_only_where_the_question_reads_as_one(retriever):
    # a head the corpus seldom writes as a drug, a cue name mostly written otherwise, a false friend: today's search
    for text in ("服后果然汗出", "行水的方法", "救火的方法"):
        q, hits = retriever.search(text, k=10)
        assert not q.drugs and not q.expansions and not q.alias_view and not side(hits), text
        assert all(h.tier in ("A", "O", "L") and not h.via for h in hits), text
        assert ids(hits) == ids(retriever.search(text, k=10, aliases="off")[1]), text
    assert "行水" not in retriever.analyzer.analyze("行水的方法", aliases=True).asked  # the layer's span withdrawn
    for text in ("行水", "行水是什么药", "行水与当归"):  # alone, beside a drug word, beside another drug
        q = retriever.analyzer.analyze(text, aliases=True)
        assert q.drugs[0] == "行水" and [e.surface for e in q.expansions if e.searched] == ["云根"], text


def test_a_false_friend_the_lexicon_files_as_a_herb_counts_only_as_that_herb(retriever):
    q, hits = retriever.search("救火是哪味药", k=10)
    by = {h.passage_id: h for h in hits}
    assert q.drugs == ["救火"] and q.asked["救火"] == "herb:景天"
    assert by["z02.000"].tier == "A"  # 慎火草，一名救火
    assert by["z01.000"].tier == "D" and by["z01.000"].flags == ["demoted:no-context"]  # 抱薪救火
    assert by["z03.000"].tier == "X" and by["z03.000"].via == [{
        "surface": "景天", "for": ["救火"], "referent": "景天", "direction": "alias→drug", "kind": "异名", "status": "open",
        "source": ["词表"], "witness": None, "reading": None, "p": None}]
    assert ids(hits).index("z03.000") < ids(hits).index("z01.000")  # the demoted after the side queue
    # beside 桂枝 and 人参 it is still no herb's name: only a 一名 or 景天's other names say a false friend is the drug
    assert by["z05.000"].tier == "D" and by["z05.000"].flags == ["demoted:no-context"]
    loose = {h.passage_id: h for h in retriever.search("救火是哪味药", k=10, alias_params={"ablate": "gates"})[1]}
    assert loose["z05.000"].tier == "A"


def test_a_shared_name_spoken_of_as_a_name_reads_as_a_drug(retriever):
    by = {h.passage_id: h for h in retriever.search("鬼督邮", k=20)[1]}
    assert by["d04.000"].tier == "A" and "homonym:鬼督邮" in by["d04.000"].flags  # 之名: a name, of no drug in sight
    assert by["d05.000"].tier == "D" and by["d05.000"].flags == ["demoted:no-context"]
    gates = retriever._gates(retriever.analyzer.analyze("鬼督邮", aliases=True, cfg=retriever.alias), retriever.alias)
    assert gates["asked"] == [("鬼督邮", [], ["别仙踪", "天麻", "徐长卿", "赤箭"], False)]


def test_a_drug_written_inside_a_longer_name_nobody_knows_is_asked_as_written(retriever):
    q, hits = retriever.search("慎火草", k=10)
    by = {h.passage_id: h for h in hits}
    assert q.asked == {"慎火": "herb:景天", "慎火草": None} and q.drugs == ["慎火"] and q.longer == {"慎火": "慎火草"}
    assert q.terms == ["herb:景天"] and "慎火草" in q.quoted  # 景天's forms searched as today, the name as written
    assert by["z02.000"].tier == "A" and by["z04.000"].tier == "X"  # 慎火 alone is one of 景天's other forms
    assert by["z04.000"].via[0]["surface"] == "慎火" and by["z04.000"].via[0]["referent"] == "景天"
    for text in ("慎火", "慎火的功效", "景天"):  # the name alone, or beside question words: no longer name
        assert not retriever.analyzer.analyze(text, aliases=True).longer, text
    assert analyzer_terms(retriever, "桂枝汤") == ["formula:桂枝汤"]  # a known longer name is that name


def analyzer_terms(retriever, text: str) -> list[str]:
    return retriever.analyzer.analyze(text, aliases=True).terms


def test_only_an_asked_drugs_other_names_go_to_the_side_queue(retriever):
    q, hits = retriever.search("枳壳", k=10)
    by = {h.passage_id: h for h in hits}
    assert q.drugs == ["枳壳"] and "枳实" in q.all_surfaces()  # the lexicon's related term, searched as today
    assert by["q01.000"].tier == "A" and by["q02.000"].tier == "L" and not by["q02.000"].via  # in the main queue
    # a hit with no surface (graph, lineage or sense) stays in the main queue too
    gates = retriever._gates(q, retriever.alias)
    assert retriever._tier(Hit("q02.000", 1.0, matched=[]), gates, retriever.alias) == ("O", [])
    assert retriever._tier(Hit("q02.000", 1.0, matched=["枳实"]), gates, retriever.alias) == ("L", [])
    # in an origin answer the asked name's earliest comes first, the related term's earlier passage after it
    assert ids(retriever.search("枳壳最早见于何书", k=10)[1]) == ["q01.000", "q02.000"]


def test_a_head_reads_as_itself_and_a_floor_alone_names_a_drug(retriever):
    q, hits = retriever.search("云根", k=10)
    by = {h.passage_id: h for h in hits}
    assert by["y02.000"].tier == "A" and not by["y02.000"].via and not by["y02.000"].flags  # 云实 is only a candidate
    assert by["y04.000"].flags == ["demoted:inside 云根藤"]
    q, hits = retriever.search("云参最早见于何书", k=10)
    assert q.asked == {"云参": None} and q.drugs == ["云参"]
    assert ids(hits) == ["w01.000", "w02.000"] and hits[0].flags == ["anachronism:云参<1700:layer"]
    assert not hits[1].flags


def test_routes_restrict_the_alias_search_too(retriever):
    for routes in (["temporal"], ["alias"], ["bm25", "alias"]):
        hits = retriever.search("国老", k=10, routes=routes)[1]
        assert hits and {r for h in hits for r in h.routes} <= set(routes), routes
    assert {h.tier for h in retriever.search("国老", k=10, routes=["temporal"])[1]} == {"A"}


@pytest.mark.parametrize("share", [[3, 0], [11, 10], [-1, 10], "3/10", [3], [2.5, 10]])
def test_the_side_share_is_checked(retriever, share):
    with pytest.raises(ValueError, match="share"):
        retriever.search("国老", alias_params={"share": share})


def test_a_blocker_inside_its_own_blocker_covers_nothing():
    # 草甘遂 would hide 甘遂, but in 甘草甘遂 it is itself the straddle of 甘草 and 甘遂: one step, in questions and passages
    index = AliasIndex([AliasRecord("甘遂", ho="甘遂", b=["草甘遂"]),
                        AliasRecord("草甘遂", b=["甘草甘遂"], r=[R("蚤休", src=["bielu-jc"])])])
    assert index.free_offsets(gate_form("甘草甘遂各一两"), "甘遂", ["草甘遂"], None) == [2]
    assert index.free_offsets(gate_form("草甘遂一两"), "甘遂", ["草甘遂"], None) == []
    assert index.covers(gate_form("草甘遂一两"), 1, "甘遂", "草甘遂", None) == 0


def test_a_reading_weighs_no_candidate_and_a_head_its_own_drug():
    index = AliasIndex([AliasRecord("乙草", ho="乙草", r=[R("丙草", st="candidate")]),
                        AliasRecord("丁草", ho="丁草", r=[R("戊草", st="cue", c=["戊草", "己根"])]),
                        AliasRecord("丁根", r=[R("丁草")])])
    assert index.readings("乙草") == [] and index.reading("乙草一两", "乙草", (None, None)) == (None, 0.0)
    assert [(r.h, r.g, r.c) for r in index.readings("丁草")] == [("戊草", "戊草", ["戊草", "己根"]),
                                                               ("丁草", "丁草", ["丁根", "丁草"])]
    assert index.reading("丁草，一名丁根", "丁草", (None, None))[0].h == "丁草"  # its own name beside it
    assert index.reading("丁草，己根", "丁草", (None, None))[0].h == "戊草"


# ------------------------------------------------------------------ what every label says it answers
def test_every_label_names_the_asked_names_it_answers(retriever):
    for text in ("甘草", "国老", "鬼督邮", "救火是哪味药", "慎火草", "山药", "将军"):
        q, hits = retriever.search(text, k=20)
        claims = {e.surface: [e.for_, *e.also] for e in q.expansions}
        for h in hits:
            for v in h.via:
                assert v["for"] and set(v["for"]) <= set(q.asked), (text, h.passage_id, v)
                if h.tier == "B":
                    assert v["for"] == claims[v["surface"]], (text, h.passage_id)
                elif v["direction"] == "asked":
                    assert v["for"] == [v["surface"]], (text, h.passage_id)
    by = {h.passage_id: h for h in retriever.search("慎火草", k=10)[1]}
    assert by["z04.000"].via[0]["for"] == ["慎火"]  # the drug the longer name asks
    by = {h.passage_id: h for h in retriever.search("鬼督邮", k=10)[1]}
    assert by["d01.000"].via[0]["for"] == ["鬼督邮"] and by["o01.000"].via[0]["for"] == ["鬼督邮"]


def test_a_name_reached_for_two_asked_names_answers_both(retriever):
    q, hits = retriever.search("国老与蜜甘", k=10)
    assert q.drugs == ["国老", "蜜甘"]
    [e] = [e for e in q.expansions if e.surface == "甘草"]
    assert (e.for_, e.also, e.searched) == ("国老", ["蜜甘"], True)
    assert q.alias_view["expansions"][0]["for"] == "国老"  # the view keeps one asked name per expansion
    b = [h for h in hits if h.tier == "B"]
    assert b and all(h.via[0]["for"] == ["国老", "蜜甘"] for h in b)


def test_an_expansion_without_a_side_place_is_not_searched_and_says_why(retriever):
    for kw, why in (({"k": 3}, "share"), ({"k": 10, "alias_params": {"share": [0, 10]}}, "share"),
                    ({"k": 10, "routes": ["bm25", "graph"]}, "routes"), ({"k": 3, "routes": ["bm25"]}, "routes")):
        q, hits = retriever.search("国老", **kw)
        assert [(e.surface, e.searched, e.why) for e in q.expansions] == [("甘草", False, why)], kw
        assert [(x["surface"], x["searched"], x["why"]) for x in q.alias_view["expansions"]] == [("甘草", False, why)]
        assert not [h for h in hits if h.tier == "B"], kw
    q, _ = retriever.search("国老", k=4)  # ⌊3·4/10⌋ = 1: a place, so a search
    assert [(e.searched, e.why) for e in q.expansions] == [(True, None)]
    q, hits = retriever.search("国老", k=3, alias_params={"ablate": "slots"})  # no places to keep: one ranking
    assert q.expansions[0].searched
    # a period or a cap says why as before
    q, _ = retriever.search("清代的通草", k=3)
    assert [(e.surface, e.why) for e in q.expansions] == [("通脱木", "share"), ("木通", "period")]


def test_a_stop_name_asked_on_its_own_lists_its_drugs_and_searches_none(retriever):
    def listed(text):
        q = retriever.analyzer.analyze(text, aliases=True, cfg=retriever.alias)
        return q, [(a["surface"], [(r["head"], r["status"], r["source"]) for r in a["referents"]], a.get("note"))
                   for a in (q.alias_view.get("asked") or [])]

    # the lexicon files 救火 under 景天: that drug, of status stop, and no other name of it searched
    for text in ("救火", "救火是哪味药", "宋以前的救火"):
        q, rows = listed(text)
        assert q.stops == ["救火"] and rows == [("救火", [("景天", "stop", ["词表"])], STOP_NOTE)], text
        assert not q.expansions and q.alias_view["expansions"] == [], text
    # the record's own pairs, which no search reads, and the lexicon's
    q, rows = listed("云门是什么药")
    assert q.stops == ["云门"] and rows == [("云门", [("云根", "stop", ["别名录（中醫笈成）"])], STOP_NOTE)]
    assert not q.drugs and not q.expansions
    # inside a phrase, or beside another name or word, it is the word: nothing listed, today's search
    for text in ("救火的方法", "抱薪救火", "云门穴", "云门与云根", "针刺云门"):
        q, rows = listed(text)
        assert not q.stops and not [r for r in rows if r[2]], text
    q, hits = retriever.search("救火是哪味药", k=10)
    assert q.alias_view["asked"][0]["note"] == STOP_NOTE and not [h for h in hits if h.tier == "B"]


def test_side_passages_that_give_the_name_nothing_follow_the_others_of_their_drug(retriever):
    pack = retriever.pack
    bm25 = [pid for pid, _ in retriever.corpus.search(["甘草"], limit=50)]
    assert bm25.index("b02.000") < bm25.index("g00.000")  # the heading outranks every prescription on BM25
    q, hits = retriever.search("国老", k=60)
    b = [h.passage_id for h in hits if h.tier == "B"]
    assert b[-2:] in (["b01.000", "b02.000"], ["b02.000", "b01.000"]) and len(b) == 27  # last, never dropped
    assert not {"b01.000", "b02.000"} & set(ids(retriever.search("国老", k=10)[1]))
    exp = next(e for e in q.expansions if e.surface == "甘草")
    norm = pack.variants.normalize_text
    assert pack.aliases.bare(gate_form(norm("炙甘草汤　甘草汤")), exp, (1900, 1900))
    assert not pack.aliases.bare(gate_form(norm("甘草二两，大枣十二枚")), exp, (500, 500))


# ------------------------------------------------------------------ retention, as a property of every search
@contextmanager
def watched(retriever):
    """What one alias search placed: the main queue after retention (``retained``; only where the asked-first rule
    holds), and the main and side queues the places were dealt from."""
    seen: dict = {}
    retain, deal = retriever._retain, hybrid.assemble

    def _retain(*args, **kwargs):
        seen["retained"] = out = retain(*args, **kwargs)
        return out

    def _assemble(M, S, k, num=3, den=10):
        seen.update(main=list(M), side=list(S))
        return deal(M, S, k, num, den)

    retriever._retain, hybrid.assemble = _retain, _assemble
    try:
        yield seen
    finally:
        del retriever._retain
        hybrid.assemble = deal


def asked_form(retriever, q, hit) -> bool:
    """Whether a hit writes an asked drug as the question writes it, outside that name's blockers."""
    index = retriever.pack.aliases
    g = gate_form(retriever.norm(hit.passage_id))
    yr = retriever._range(retriever.corpus.passage(hit.passage_id))
    for s in q.drugs:
        form = q.longer.get(s, s)
        rec = index.record(form)
        if index.free_offsets(g, gate_form(form), rec.b if rec is not None else [], yr):
            return True
    return False


def violations(retriever, text: str, k: int, **kw) -> list[str]:
    """The properties one alias search breaks (ADR 0023): the asked form keeps min(|A|, k − ⌊num·k/den⌋) places, |A|
    being the asked drugs' hits the main queue holds after the search for more; the side queue holds at most
    ⌊num·k/den⌋ places while the main queue lasts; no passage twice; none outside the question's window."""
    with watched(retriever) as seen:
        q, hits = retriever.search(text, k=k, aliases="on", **kw)
    num, den = _share({**retriever.alias, **(kw.get("alias_params") or {})}["share"])
    share = num * k // den
    out = []
    if len(set(ids(hits))) < len(hits):
        out.append("duplicates")
    if q.after is not None or q.before is not None:
        leaked = [h for h in hits if h.year is None or (q.after is not None and h.year < q.after)
                  or (q.before is not None and h.year >= q.before)]
        if leaked:
            out.append(f"leakage {len(leaked)}")
    if "main" in seen:
        placed = set(ids(hits))
        side_n = sum(h.tier in ("B", "X") for h in hits)
        if side_n > share and not all(h.passage_id in placed for h in seen["main"]):
            out.append(f"side {side_n} > {share} while the main queue lasts")
    if "retained" in seen:
        available = sum(h.tier == "A" for h in seen["retained"])
        asked = sum(asked_form(retriever, q, h) for h in hits)
        if asked < min(available, k - share):
            out.append(f"asked form {asked} < min({available}, {k - share})")
    return out


SWEEP_FORMS = ("{}", "{}是什么药", "唐以前的{}", "明清的{}", "{}最早见于何书")


def test_retention_holds_for_every_name_of_the_layer_and_the_herbs(retriever):
    names = sorted({rec.s for rec in RECORDS} | set(HERBS))
    broken = {}
    for name in names:
        for form in SWEEP_FORMS:
            for k in (5, 10, 20):
                bad = violations(retriever, form.format(name), k)
                if bad:
                    broken[(form.format(name), k)] = bad
    assert broken == {}
    # the check sees a broken search: the asked name moved behind the rest, the side queue dealt first
    retriever._retain = lambda q, M, *args, **kwargs: [h for h in M if h.tier != "A"] + [h for h in M if h.tier == "A"]
    assert violations(retriever, "枳壳", 1) == ["asked form 0 < min(1, 1)"]  # 枳实, the related term, took the place
    assert not hasattr(retriever, "__dict__") or "_retain" not in retriever.__dict__
    deal = hybrid.assemble
    hybrid.assemble = lambda M, S, k, num=3, den=10: (S + M)[:k]
    try:
        assert violations(retriever, "国老", 10) == ["side 10 > 3 while the main queue lasts", "asked form 0 < min(6, 7)"]
    finally:
        hybrid.assemble = deal
