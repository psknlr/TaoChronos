"""The alias layer's build (ADR 0023, ``plugins/classics/aliasbuild.py``) and its CLI, on a synthetic store: the same
inputs give the same bytes, the status table, witnesses (never from a NEVER_PACKED source), blockers, floors, the
local layer, the review sheet and ``aliases check``.  The domain's data and lexicon are the repository's; the store, the
别名录 entries and the curated decisions are invented here."""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from taochronos.cli import main
from taochronos.plugins.classics import aliasbuild
from taochronos.plugins.classics.aliasbuild import build_local, build_open, check, review, review_tsv
from taochronos.plugins.classics.aliases import loads_records
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.store import CorpusStore

HOME = Path(__file__).resolve().parents[1]
DOMAIN = HOME / "domains" / "classics"

BOOKS = {  # id → (source, category, composition)
    "jc_c030": ("jicheng", "本草", [1544, 1592]),
    "bc_a": ("jicheng", "本草", [500, 500]),
    "fang_b": ("jicheng", "方书", [1100, 1100]),
    "late_c": ("jicheng", "方书", [1800, 1800]),
    "modern_d": ("jicheng", "方书", [1950, 1960]),
    "aeam_x": ("aeam", "本草", [600, 600]),
    "bencao_gangmu_t": ("kanripo", "本草", [1552, 1578]),
}
BIELU = ["（有别名者录之无别名者未录）", "甘草（国老　蜜甘　美草）", "何首乌（地精　九真藤　交藤）", "人参（地精　人衔）",
         "芍药（白术　余容）", "知母（连母　　地参　水浚）", "大黄（将军　黄良）", "云母（去来）", "禹余粮（岩中脂　白余粮）",
         "石蜜（白沙糖）", "黄连（王连　支连　金连子）", "丹砂（朱砂　真朱）", "人尿（小便　轮回酒）", "　石（太白石　泽乳）",
         "葶苈（大室　大适　丁历）", "蚓蚯（地龙子　寒蚓）", "栝楼（地楼　泽姑）", "茯苓（茯神）", "萆薢（赤节　百枝）",
         "狗脊（强膂　扶筋）"]
TEXTS = {
    "bc_a": [("甘草", "甘草　一名国老，一名蜜甘。味甘，平。"), ("人参", "人参　味甘。一名人衔。"),
             ("何首乌", "味苦。一名九真藤。"), ("黄连", "黄连　一名王连。"), (None, "胡黄连二两，治疳。"),
             (None, "栝楼根　一名地楼。"), (None, "栝楼，一名泽姑。"), (None, "柳华，一本作柳花。")],
    "fang_b": [(None, "国老二两，大黄三两。")] + [(None, "人生去来无定")] * 25 + [(None, "岩中脂二两")] * 5
              + [(None, "岩中脂流于石上")] * 20
              + [(None, "石蜜甘草各一两"), (None, "何首乌（交藤）二两"), (None, "小便不利"), (None, "青木香二两　木香一两"),
                 (None, "茯苓（一作茯神）二两")],
    "late_c": [(None, "棒槌二钱"), (None, "大黄一名将军"), (None, "牡丹（即牡丹皮）二两")],
    "modern_d": [(None, "甜根子二钱")] + [(None, "柳花飞")] * 22,
    "aeam_x": [(None, "大黄，一名黄良。")],
    "bencao_gangmu_t": [(None, "　徐长卿（本经上品）　释名鬼督邮（本经）别仙踪（纲目）　集解（未详）")],
}
CURATED = """version: 1
repairs: [{from: 野狼, to: 狼}]
head_repairs: [{passage: jc_c030.00013, head: 礜石, wit: [bc_a.00000]}]
same_drug: [{names: [丹砂, 朱砂], wit: [bc_a.00000]}, {names: [牡丹, 牡丹皮], wit: [late_c.00002]},
            {names: [柳华, 柳花], wit: [bc_a.00007]}]
pairs:
  - {s: 国老, head: 甘草, kind: alias, status: open, wit: [bc_a.00000]}
  - {s: 将军, head: 大黄, status: cue, cues: [大黄, 锦纹], wit: [late_c.00001]}
  - {s: 青木香, head: 木香, kind: old_name, valid: [null, 1100], wit: [fang_b.00054]}
  - {s: 青木香, head: 马兜铃, kind: part_name, valid: [1100, null], wit: [fang_b.00054]}
first_use: [{s: 党参, year: 1700, wit: [bc_a.00000]}]
stop: [{s: 小便, why: 常用词, wit: [fang_b.00053]}]
cover_stops: {}
decisions:
  - {s: 水浚, status: open, why: 编者已核, wit: [bc_a.00000]}
  - {s: 金连子, head: 黄连, status: candidate, wit: [bc_a.00003]}
"""


def make_home(root: Path, curated: str = CURATED) -> Path:
    """A home whose domain is the repository's (linked) but for its alias directory."""
    home = root / "home"
    classics = home / "domains" / "classics"
    classics.mkdir(parents=True)
    for p in DOMAIN.iterdir():
        if p.name != "aliases":
            (classics / p.name).symlink_to(p)
    (classics / "aliases").mkdir()
    (classics / "aliases" / "sources.yaml").symlink_to(DOMAIN / "aliases" / "sources.yaml")
    (classics / "aliases" / "curated.yaml").write_text(curated, encoding="utf-8")
    (home / "architecture-policy.yaml").symlink_to(HOME / "architecture-policy.yaml")
    (home / "profiles").symlink_to(HOME / "profiles")
    (home / "evals" / "gold").mkdir(parents=True)
    (home / "evals" / "gold" / "aliases.yaml").symlink_to(HOME / "evals" / "gold" / "aliases.yaml")
    return home


def make_store(path: Path) -> Path:
    normalize = DomainPack(DOMAIN).variants.normalize_text
    store = CorpusStore(path, create=True)
    for bid, (source, category, years) in BOOKS.items():
        store.put_book({"id": bid, "title": bid, "category": category, "composition": years}, source)
    rows = []
    texts = {"jc_c030": [(None, t) for t in BIELU], **TEXTS}
    for bid, items in texts.items():
        y0, y1 = BOOKS[bid][2]
        for seq, (section, text) in enumerate(items):
            rows.append({"id": f"{bid}.{seq:05d}", "book_id": bid, "seq": seq, "year": (y0 + y1) / 2, "y_start": y0,
                         "y_end": y1, "locator": {"section": section} if section else {}, "temporal": {}, "text": text})
    store.add_passages(rows, normalize)
    store.set_meta("edition", "web")  # every passage counts as the web pack's
    store.commit()
    store.close()
    return path


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("aliasbuild")
    return make_home(root), make_store(root / "data" / "corpus" / "tcm.sqlite")


@pytest.fixture(scope="module")
def built(site):
    home, store = site
    return build_open(store, home)


def records(result) -> dict:
    return {rec.s: rec for rec in result.records}


def ref(rec, head):
    return next(r for r in rec.r if r.h == head)


# ------------------------------------------------------------------ determinism and inputs
def test_two_builds_give_identical_bytes(site, built):
    home, store = site
    again = build_open(store, home)
    assert again.text() == built.text() and again.context_text() == built.context_text()
    code = ("import hashlib, sys; from taochronos.plugins.classics.aliasbuild import build_open; "
            "r = build_open(sys.argv[1], sys.argv[2]); print(hashlib.sha256(r.text().encode()).hexdigest())")
    out = subprocess.run([sys.executable, "-c", code, str(store), str(home)], capture_output=True, text=True,
                         env={"PYTHONHASHSEED": "4242", "PYTHONPATH": str(HOME / "src"), "TAOCHRONOS_CACHE": "off"},
                         check=True)
    assert out.stdout.strip() == hashlib.sha256(built.text().encode()).hexdigest()


def test_the_open_build_takes_no_local_input():
    assert list(inspect.signature(build_open).parameters) == ["store", "home"]
    assert list(inspect.signature(build_local).parameters) == ["open_result", "local_pairs", "store"]


def test_the_header_records_the_inputs_and_the_labels(built):
    header, recs = loads_records(built.text())
    assert {"store", "normalizer", "lexicon", "coverage", "labels", "sources", "counts"} <= set(header)
    assert header["store"]["books"] == len(BOOKS) and header["normalizer"] == DomainPack(DOMAIN).variants.fingerprint
    assert header["labels"]["bielu-jc"] == "别名录（中醫笈成）" and header["labels"]["store"] == "古籍互证"
    assert set(header["sources"]) == set(header["labels"]) <= {"bielu-jc", "curated", "store", "shiming", "taboo",
                                                                "lexicon"}
    assert header["coverage"]["bielu_parsed"] == len(BIELU) - 1 and header["coverage"]["head_repairs"] == 1
    assert [r.s for r in recs] == sorted(r.s for r in recs)
    ctx = json.loads(built.context_text())
    assert ctx["herbs"] == sorted(set(ctx["herbs"])) and "甘草" in ctx["herbs"] and "nameof" in ctx


# ------------------------------------------------------------------ the status table
def test_the_status_table(built):
    recs = records(built)
    assert ref(recs["国老"], "甘草").st == "open"  # 1: a curated pair's status (else: two characters, cue)
    assert recs["小便"].stop and recs["小便"].r == []  # 2: a curated stop
    assert ref(recs["连母"], "知母").st == ref(recs["地参"], "知母").st == "candidate"  # 4: next to a lost character
    assert ref(recs["白术"], "芍药").st == "candidate"  # 5: another drug's headword
    assert {r.h: r.st for r in recs["地精"].r} == {"人参": "cue", "何首乌": "cue"}  # 6: two drugs
    assert recs["去来"].stop and recs["去来"].n == 25 and recs["去来"].r == []  # 7: written often, never as a drug
    assert "去来" in built.stopped and built.stopped["去来"][0].startswith("云母")
    assert (recs["岩中脂"].n, recs["岩中脂"].sh, ref(recs["岩中脂"], "禹余粮").st) == (25, 0.2, "cue")  # 8
    assert ref(recs["水浚"], "知母").st == "open"  # 1: a curated decision (else: two characters, cue)
    assert ref(recs["支连"], "黄连").st == ref(recs["王连"], "黄连").st == "cue"  # 9: two characters
    assert ref(recs["九真藤"], "何首乌").st == "open"  # 10
    assert ref(recs["将军"], "大黄").st == "cue" and ref(recs["将军"], "大黄").c[:2] == ["大黄", "锦纹"]


def test_groups_heads_and_repairs(built):
    recs = records(built)
    assert recs["丹砂"].ho == recs["朱砂"].ho == "丹砂"  # every same-drug member carries the group
    assert ref(recs["朱砂"], "丹砂").st == "cue"  # not a candidate: the headword is of the same drug
    assert recs["甘草"].ho == "甘草" and recs["甘草"].r == []  # a head that is no one's alias
    assert "礜石" in {r.h for r in recs["太白石"].r}  # a head the transcription lost, repaired
    assert "野狼" not in recs and recs["真朱"].r[0].h == "丹砂"


def test_witnesses_are_kept_by_kind_and_date_never_from_a_never_packed_source(built):
    recs = records(built)
    guolao = ref(recs["国老"], "甘草")
    assert guolao.w[0].pid == "bc_a.00000" and "store" in guolao.src and "curated" in guolao.src
    assert [w.kind for w in guolao.w][-1] == "l" and guolao.w[-1].pid == "jc_c030.00001"
    assert ("bc_a.00000", "e") in {(w.pid, w.kind) for w in ref(recs["蜜甘"], "甘草").w}
    assert ("bc_a.00001", "n") in {(w.pid, w.kind) for w in ref(recs["人衔"], "人参").w}  # 本草 entry, 一名
    assert ("bc_a.00002", "n") in {(w.pid, w.kind) for w in ref(recs["九真藤"], "何首乌").w}  # headed by its section
    assert ("fang_b.00052", "g") in {(w.pid, w.kind) for w in ref(recs["交藤"], "何首乌").w}  # gloss
    huangliang = ref(recs["黄良"], "大黄")
    assert [w.pid for w in huangliang.w] == ["jc_c030.00006"] and "store" not in huangliang.src  # aeam_x is never one
    assert all(not w.pid.startswith("aeam_x") for rec in built.records for r in rec.r for w in r.w)
    assert all(len(r.w) <= 3 for rec in built.records for r in rec.r)
    gui = ref(recs["鬼督邮"], "徐长卿")
    assert "shiming" in gui.src and gui.cr == ("本经", 25, 220) and gui.w[0].kind == "m"
    assert ref(recs["别仙踪"], "徐长卿").cr == ("纲目", 1578, 1578)


def test_blockers_floors_and_windows(built):
    recs = records(built)
    assert "胡黄连" in recs["黄连"].b  # a longer name of another drug
    assert "石蜜甘" in recs["蜜甘"].b  # a name straddling the alias in the store
    assert ("青木香", 1100, None) in recs["木香"].b  # the same drug before 1100 only
    assert (recs["山药"].fl, recs["山药"].flb) == (1063, "taboo:song_yingzong_shu") and recs["山药"].ho == "山药"
    assert recs["薯药"].fl == 762 and ref(recs["薯药"], "山药").k == "taboo_rename"
    assert (recs["党参"].fl, recs["党参"].flb) == (1700, "curated")
    assert {r.h: r.v for r in recs["青木香"].r} == {"木香": (None, 1100), "马兜铃": (1100, None)}
    assert recs["国老"].n == 2 and recs["国老"].raw == ["国老"]  # written as normalised: no other spelling


def test_a_lexicon_entry_filing_a_drug_twice_joins_it(built):
    recs = records(built)
    assert {r.h for r in recs["大室"].r} == {"葶苈"} and recs["亭历"].ho == "葶苈"  # herb:亭历 files 大室, 大适 again
    assert ref(recs["亭历"], "葶苈").src == ["lexicon"] and built.report["joined"]["亭历"] == "葶苈"
    # 狗脊 heads pairs of its own, so it stays a rival — and the report points at it
    assert {r.h: r.src for r in recs["赤节"].r} == {"萆薢": ["bielu-jc"], "狗脊": ["lexicon"]}
    assert "赤节:狗脊~萆薢" in built.report["rivals_sharing_names"]


def test_same_drug_members_reach_their_drug(built):
    recs = records(built)
    mudan = ref(recs["牡丹皮"], "牡丹")
    assert (mudan.k, mudan.src, [w.pid for w in mudan.w]) == ("alias", ["curated", "store"], ["late_c.00002"])
    assert recs["牡丹皮"].ho == recs["牡丹"].ho == "牡丹"
    liuhua = recs["柳花"]  # written often and never as a drug, yet a name of the drug: listed, never a stop
    assert not liuhua.stop and liuhua.n >= 20 and ref(liuhua, "柳华").st == "candidate" and liuhua.ho == "柳华"


def test_equations_read_whole_names_and_no_variant_readings(built):
    recs = records(built)
    assert ("bc_a.00006", "e") in {(w.pid, w.kind) for w in ref(recs["泽姑"], "栝楼实").w}
    assert "bc_a.00005" not in {w.pid for w in ref(recs["地楼"], "栝楼实").w}  # 栝楼|根，一名地楼: another drug
    assert "fang_b.00055" not in {w.pid for w in ref(recs["茯神"], "茯苓").w}  # 茯苓（一作茯神）: a variant reading


def test_cues_leave_out_unreliable_names(built):
    recs = records(built)
    assert "王连" in ref(recs["支连"], "黄连").c  # another name of the drug alone
    assert "金连子" not in ref(recs["支连"], "黄连").c  # a candidate
    assert "岩中脂" not in ref(recs["白余粮"], "禹余粮").c  # written 25 times, read as a drug in 20 %


def test_the_report_points_at_garbled_heads(built):
    assert "蚓蚯" in built.report["unattested_heads"]  # the 别名录's 蚯蚓 written backwards


def test_cover_strings_are_kept_first_and_the_cap_reported(tmp_path, site, monkeypatch):
    home = make_home(tmp_path, CURATED.replace("cover_stops: {}", "cover_stops: {黄连: [黄连根]}"))
    monkeypatch.setattr(aliasbuild, "MAX_BLOCKERS", 1)
    result = build_open(site[1], home)
    assert records(result)["黄连"].b == ["黄连根"]  # never written, kept over the 胡黄连 the store writes
    assert any(w.startswith("黄连: ") and "past the cap" in w for w in result.report["warnings"])


@pytest.mark.parametrize("curated, error", [
    ({"stops": []}, "unknown section stops"),
    ({"pairs": [{"s": "国老", "head": "甘草", "kind": "nickname", "wit": ["x.1"]}]}, "unknown kind"),
    ({"pairs": [{"s": "国老", "head": "甘草", "staus": "open", "wit": ["x.1"]}]}, "unknown key staus"),
    ({"stop": ["小便"]}, "is not a mapping"),
    ({"head_repairs": [{"passage": "jc_c030.00001", "head": "礜石"}]}, "no witness"),
    ({"decisions": [{"s": "国老", "status": "open", "wit": ["jc_c030.00001"]}]}, "别名录"),
    ({"decisions": [{"s": "国", "status": "open", "wit": ["x.1"]}]}, "fewer than two"),
    ({"pairs": [{"s": "通草", "head": "木通", "valid": [960, 960], "wit": ["x.1"]}]}, "valid"),
    ({"first_use": [{"s": "党参", "year": "1700", "wit": ["x.1"]}]}, "whole year"),
    ({"cover_stops": {"胡豆": ["车前子"]}}, "does not hold"),
    ({"cover_stops": {"人言": [f"{c}人言" for c in "与古其越夫真学听运道已信如于昔示时外众闻妇国前后常"]}}, "over the 24"),
])
def test_curated_yaml_is_validated(curated, error):
    assert any(error in e for e in aliasbuild.validate_curated(curated))


def test_a_malformed_curated_file_stops_the_build_and_fails_check(tmp_path, site, built):
    home = make_home(tmp_path, CURATED.replace("stop: [{s: 小便, why: 常用词, wit: [fang_b.00053]}]", "stop: [小便]"))
    with pytest.raises(ValueError, match="not a mapping"):
        build_open(site[1], home)
    built.write(home / "domains" / "classics" / "aliases")
    assert any("not a mapping" in e for e in check(home)["errors"])


def test_held_out_names_are_refused_in_any_spelling_and_in_reasons(tmp_path, built):
    curated = CURATED.replace("decisions:\n", "decisions:\n  - {s: 黃良, status: open, wit: [bc_a.00000]}\n", 1)
    home = make_home(tmp_path, curated.replace("why: 常用词", "why: 常用词，非人銜"))
    built.write(home / "domains" / "classics" / "aliases")
    held = [e for e in check(home, heldout={"黄良", "人衔"})["errors"] if "held-out" in e]
    assert held and "黄良" in held[0] and "人衔" in held[0]
    assert not any("held-out" in e for e in check(home, heldout={"甘草根"})["errors"])


# ------------------------------------------------------------------ the local layer
def test_the_local_layer_reclassifies_and_keeps_local_pairs_out_of_the_open_build(site, built):
    home, store = site
    rows = [{"h": "甘草", "s": "甜根子", "src": "hurb", "ref": "row 1"},
            {"h": "人参", "s": "棒槌", "src": "hurb", "ref": "row 2"},
            {"h": "甘草", "s": "国老", "src": "hurb", "ref": "row 1"},
            {"h": "黄连", "s": "黄蓮〓", "src": "hurb", "ref": "row 3", "fl": ["lost_char"]}]
    layer = build_local(built, rows)
    recs = records(layer)
    assert ref(recs["甜根子"], "甘草").st == "candidate"  # local only, read as a drug only after 1912
    assert ref(recs["棒槌"], "人参").st == "cue"  # local only, read as a drug in 1800
    assert ref(recs["国老"], "甘草").st == "open" and "hurb" in ref(recs["国老"], "甘草").src
    header, _ = loads_records(layer.text())
    assert "hurb" in header["sources"] and header["labels"]["hurb"] == "hurbTable"
    assert build_open(store, home).text() == built.text()


# ------------------------------------------------------------------ review and check
def test_the_review_sheet(built):
    rows = review(built, top=10, heldout={"去来"})
    assert rows and all(len(r) == len(aliasbuild.REVIEW_COLUMNS) for r in rows)
    assert "去来" not in {r[1] for r in rows} and [int(r[2]) for r in rows] == sorted((int(r[2]) for r in rows),
                                                                                      reverse=True)
    yan = next(r for r in rows if r[1] == "岩中脂")
    assert yan[4] == "cue" and "禹余粮" in yan[5] and yan[7].startswith(("◆", "◇")) and "【岩中脂】" in yan[7]
    tsv = review_tsv(rows)
    assert tsv.splitlines()[0].split("\t") == list(aliasbuild.REVIEW_COLUMNS)


def test_check_passes_and_refuses(site, built, tmp_path, monkeypatch):
    home, store = site
    folder = home / "domains" / "classics" / "aliases"
    built.write(folder)
    assert check(home, store=store, rebuild=True)["errors"] == []
    text = (folder / "aliases.jsonl").read_text(encoding="utf-8")
    assert any("held-out" in e for e in check(home, heldout={"国老"})["errors"])
    try:
        (folder / "aliases.jsonl").write_text(text.replace('"bc_a.00000"', '"aeam_x.00000"', 1), encoding="utf-8")
        assert any("never be packed" in e for e in check(home, store=store)["errors"])
        assert any("differs from a build" in e for e in check(home, store=store, rebuild=True)["errors"])
        (folder / "aliases.jsonl").write_text(text.replace('"src":["bielu-jc"]', '"src":["hurb"]', 1), encoding="utf-8")
        assert any("does not ship" in e for e in check(home)["errors"])
        (folder / "aliases.jsonl").write_text(text + '{"s":"甘","r":[{"h":"甘草","src":["curated"]}]}\n',
                                              encoding="utf-8")
        assert any("fewer than two" in e for e in check(home)["errors"])
        (folder / "aliases.jsonl").write_text(text, encoding="utf-8")
        (folder / "aliases.jsonl").write_text(text.replace('"late_c.00001"', '"fang_b.00053"'), encoding="utf-8")
        assert any("does not write 将军" in e for e in check(home, store=store)["errors"])  # 小便不利
        (folder / "aliases.jsonl").write_text(text, encoding="utf-8")
        monkeypatch.setitem(aliasbuild.BUDGET, "deflated", 1000)
        assert any("over the budget" in e for e in check(home)["errors"])
        monkeypatch.undo()
        monkeypatch.setitem(aliasbuild.BUDGET, "directory", 1000)
        assert any(e.startswith("aliases/: ") and "over the budget" in e for e in check(home)["errors"])
        monkeypatch.undo()
        (folder / "stray.json").write_text("{}", encoding="utf-8")
        assert any("stray.json" in e for e in check(home)["errors"])
    finally:
        (folder / "aliases.jsonl").write_text(text, encoding="utf-8")
        (folder / "stray.json").unlink(missing_ok=True)
    assert check(home, store=store)["ok"]


def test_a_curated_row_needs_a_witness(tmp_path, site, built):
    home = make_home(tmp_path, CURATED.replace("first_use: [{s: 党参, year: 1700, wit: [bc_a.00000]}]",
                                               "first_use: [{s: 党参, year: 1700}]"))
    built.write(home / "domains" / "classics" / "aliases")
    assert any("no witness" in e for e in check(home)["errors"])


# ------------------------------------------------------------------ the command line
def test_the_command_line(tmp_path, capsys):
    home = make_home(tmp_path)
    data = tmp_path / "data"
    store = make_store(data / "corpus" / "tcm.sqlite")
    base = ["--home", str(home), "--data", str(data), "aliases"]
    main(base + ["build"])
    report = json.loads(capsys.readouterr().out)
    folder = home / "domains" / "classics" / "aliases"
    assert report["bytes"]["aliases.jsonl"]["raw"] == len((folder / "aliases.jsonl").read_bytes())
    assert report["counts"]["status"]["stop"] >= 2 and report["coverage"]["bielu_parsed"] == len(BIELU) - 1
    main(base + ["check", "--db", str(store)])
    assert json.loads(capsys.readouterr().out)["ok"]
    main(base + ["import", "hurb", str(HOME / "tests" / "fixtures" / "aliases" / "hurb.csv")])
    entry = json.loads(capsys.readouterr().out)
    assert entry["source"] == "hurb" and entry["normalizer"] == DomainPack(DOMAIN).variants.fingerprint
    main(base + ["build", "--local"])
    report = json.loads(capsys.readouterr().out)
    local = data / "aliases" / "local"
    assert (local / aliasbuild.LOCAL_FILE).exists() and report["local"]["pairs"]["hurb"] > 0
    assert sorted(p.name for p in folder.iterdir()) == sorted(aliasbuild.FILES)  # nothing local under the domain
    main(base + ["review", "--top", "5"])
    assert json.loads(capsys.readouterr().out)["rows"] == 5 and (local / "review.tsv").exists()
    main(base + ["show", "国老", "--profile", "web-canon"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["surface"] == "国老" and (shown["record"] or shown.get("committed"))["s"] == "国老"
    (folder / "curated.yaml").write_text(CURATED.replace("国老, head: 甘草", "常山, head: 甘草"), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(base + ["check"])
    assert "常山" in json.loads(capsys.readouterr().out)["errors"][0]
