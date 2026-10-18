"""The alias layer's build (ADR 0023, ``plugins/classics/aliasbuild.py``) and its CLI, on a synthetic store: the same
inputs give the same bytes, the status table, witnesses (never from a NEVER_PACKED source), blockers, floors, the
local layer, the review sheet and ``aliases check``.  The domain's data and lexicon are the repository's; the store, the
别名录 entries and the curated decisions are invented here."""

from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from taochronos.cli import main
from taochronos.plugins.classics import aliasbuild
from taochronos.plugins.classics.aliasbuild import build_local, build_open, check, review, review_tsv
from taochronos.plugins.classics.aliases import loads_records
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest.aliases import NTU_EXTRACT
from taochronos.plugins.classics.store import CorpusStore
from taochronos.protocol.yamlio import loads_yaml

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
         "狗脊（强膂　扶筋）", "紫金藤（山甘草）", "长石（方石）", "小柏（子柏）", "独活（羌青）", "天南星（虎掌）",
         "百合（强瞿）", "蔓椒（豕椒）"]
TEXTS = {
    "bc_a": [("甘草", "甘草　一名国老，一名蜜甘。味甘，平。"), ("人参", "人参　味甘。一名人衔。"),
             ("何首乌", "味苦。一名九真藤。"), ("黄连", "黄连　一名王连。"), (None, "胡黄连二两，治疳。"),
             (None, "栝楼根　一名地楼。"), (None, "栝楼，一名泽姑。"), (None, "柳华，一本作柳花。"),
             ("百合", "味甘，平。一名强瞿。"),  # an entry only its heading names, a numeral's (not 合's)
             ("二○四　蔓椒", "味苦，温。一名豕椒。")],  # and one numbered with ○ for 〇
    "fang_b": [(None, "国老二两，大黄三两。")] + [(None, "人生去来无定")] * 25 + [(None, "岩中脂二两")] * 5
              + [(None, "岩中脂流于石上")] * 20
              + [(None, "石蜜甘草各一两"), (None, "何首乌（交藤）二两"), (None, "小便不利"), (None, "青木香二两　木香一两"),
                 (None, "茯苓（一作茯神）二两"),
                 # straddles: 常山|甘草 cuts 山甘草, not 常山; 又方|石硫黄 cuts 方石 (石硫黄 written three times as often);
                 # 地肤子|柏子仁 cuts 子柏 (柏子仁 takes its 柏)
                 (None, "常山甘草各一两"), (None, "又方石硫黄揩之"), (None, "石硫黄二两"), (None, "石硫黄一两"),
                 (None, "地肤子柏子仁各二合"),
                 # 纲目 joint headings the lexicon took for one name: 独活羌活 written as two (各), 虎掌天南星 as one
                 (None, "独活羌活各一两"), (None, "虎掌天南星二两"),
                 # a local list's name written only beside two of the local lists' heads (no lexicon herb)
                 (None, "青霞根、白露藤、金风草为末")],
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


@pytest.mark.parametrize("section, head", [
    ("百合", "百合"), ("五味子", "五味子"), ("三七", "三七"), ("百合（本经中品）", "百合"), ("卷二 · 五灵脂", "五灵脂"),
    ("一七一　五味子", "五味子"), ("十、百部", "百部"), ("12. 五倍子", "五倍子"), ("一八一梔子", "梔子"), ("二八七", None),
    ("一○七　白石脂", "白石脂"), ("三○一 　藥實根", "藥實根"), ("一〇〇　合歡", "合歡"), ("一○○", None),
])
def test_an_entry_heading_drops_its_numbering_never_a_name_s_numeral(section, head):
    assert aliasbuild.entry_head(section, lambda s: s) == head


def test_an_entry_named_only_by_a_heading_that_opens_with_a_numeral_witnesses_it(built):
    r = ref(records(built)["强瞿"], "百合")
    assert ("bc_a.00008", "n") in [(w.pid, w.kind) for w in r.w] and "store" in r.src
    r = ref(records(built)["豕椒"], "蔓椒")  # 二○四　蔓椒: numbered with ○
    assert ("bc_a.00009", "n") in [(w.pid, w.kind) for w in r.w] and "store" in r.src


# ------------------------------------------------------------------ the web pack
def write_pack(home: Path, rows: list[dict], level: int = 9) -> Path:
    """The 要籍语料's pack as ``taochronos web pack`` writes it: a passage per line, its keys sorted."""
    pack = home / "corpus" / "web" / "passages.jsonl.gz"
    pack.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    pack.write_bytes(gzip.compress(lines.encode("utf-8"), compresslevel=level, mtime=0))
    return pack


def pack_rows(store: Path) -> list[dict]:
    """The store's passages as a pack holds them (every column ``webcorpus.build_store`` writes), in its order."""
    db = CorpusStore(store, readonly=True)
    cols = ("id", "book_id", "edition_id", "seq", "kind", "layer", "year", "y_start", "y_end", "locator", "temporal",
            "text", "punctuation", "extra")
    rows = [dict(zip(cols, r)) for r in db.db.execute(f"SELECT {', '.join(cols)} FROM passages ORDER BY rid")]
    db.close()
    for r in rows:
        r.update({k: json.loads(r[k]) for k in ("locator", "temporal", "extra")})
    return rows


def test_the_header_fingerprints_the_web_pack_the_store_is_made_of(tmp_path, site, built):
    home, store = make_home(tmp_path), site[1]
    rows = pack_rows(store)
    pack = write_pack(home, rows)
    payload = gzip.decompress(pack.read_bytes())
    assert aliasbuild.pack_fingerprint(pack) == hashlib.sha256(payload).hexdigest()[:12]  # as `web pack` reports it
    result = build_open(store, home)
    header, _ = loads_records(result.text())
    assert header["web_pack"] == aliasbuild.pack_fingerprint(pack) and "web_pack" not in loads_records(built.text())[0]
    assert result.text().split("\n", 1)[1] == built.text().split("\n", 1)[1]  # the records are the same
    assert not [w for w in result.report["warnings"] if "web pack" in w]
    # the same lines compressed otherwise are the same pack
    assert aliasbuild.pack_fingerprint(write_pack(tmp_path / "other", rows, level=1)) == header["web_pack"]
    # a pack the store is not made of (a passage short; a passage's text or heading fixed, its id kept) is not named,
    # and the report says so
    fixed_text = [dict(r, text=r["text"].replace("人衔", "人御")) if r["id"] == "bc_a.00001" else r for r in rows]
    fixed_head = [dict(r, locator={**r["locator"], "section": "二○四"}) if r["id"] == "bc_a.00009" else r for r in rows]
    assert fixed_text != rows and fixed_head != rows
    for other in (rows[:-1], fixed_text, fixed_head):
        write_pack(home, other)
        result = build_open(store, home)
        assert "web_pack" not in loads_records(result.text())[0]
        assert any("header names no web pack" in w for w in result.report["warnings"])


def test_on_a_full_store_the_header_fingerprints_the_pack_that_sets_the_web_flags(tmp_path, site):
    home, store = make_home(tmp_path), tmp_path / "full.sqlite"
    shutil.copyfile(site[1], store)
    db = CorpusStore(store)
    db.set_meta("edition", "full")
    db.commit()
    db.close()
    pack = write_pack(home, [r for r in pack_rows(store) if r["id"] != "bc_a.00000"])  # an excerpt
    header, recs = loads_records(build_open(store, home).text())
    assert header["web_pack"] == aliasbuild.pack_fingerprint(pack)
    flags = {w.pid: w.web for rec in recs for r in rec.r for w in r.w}
    assert flags["bc_a.00000"] is False and flags["jc_c030.00001"] is True


def test_check_warns_of_a_layer_built_against_another_web_pack(tmp_path, site):
    home, store = make_home(tmp_path), site[1]
    rows = pack_rows(store)
    write_pack(home, rows)
    build_open(store, home).write(home / "domains" / "classics" / "aliases")
    result = check(home)
    assert result["ok"] and not [w for w in result["warnings"] if "web pack" in w]
    write_pack(home, rows[:-1])  # a canon run wrote the pack again: the layer is to be built again
    result = check(home)
    assert result["ok"] and any("another web pack" in w for w in result["warnings"])
    assert any("differs from a build" in e for e in check(home, store=store, rebuild=True)["errors"])


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


def test_a_straddle_blocks_only_the_name_it_cuts(built):
    recs, free = records(built), built.builder.free
    assert "常山甘草" not in recs["常山"].b and "常山甘草" in recs["山甘草"].b  # 常山|甘草: 甘草 is a name of its own
    assert "fang_b.00056" in free["常山"] and "fang_b.00056" in free["甘草"]  # 山甘草, cut there, hides no 甘草
    assert "方石硫黄" in recs["方石"].b  # 又方|石硫黄: the straddler is written three times as often
    assert "地肤子柏" in recs["子柏"].b  # 地肤子|柏子仁: 柏子仁 takes the 柏 of 子柏


def test_the_gangmu_joint_headings_block_nothing(built):
    recs = records(built)
    assert "独活羌活" not in recs["独活"].b and "fang_b.00061" in built.builder.free["独活"]  # 独活羌活各一两: two
    assert built.report["concatenations"]["独活羌活"] == ["独活"]
    assert "虎掌天南星" in recs["天南星"].b and "虎掌天南星" not in built.report["concatenations"]  # 二两: one name
    # another 本草 entry's title is one drug's name, though the store never writes it and both its parts are names
    assert "防风党参" in recs["党参"].b and "防风党参" not in built.report["concatenations"]


def test_unblock_drops_a_blocker_and_reports_a_row_that_drops_none(tmp_path, site):
    rows = "{蜜甘: [石蜜甘], 天南星: [虎掌天南星], 国老: [国老汤], 党参: [防风党参], 独活: [独活羌活], 将军: [将军汤]}"
    curated = (CURATED.replace("cover_stops: {}", f"cover_stops: {{将军: [将军湯]}}\nunblock: {rows}")
               .replace("first_use: [", "first_use: [{s: 羌活, year: 1000, wit: [fang_b.00061]}, "))
    result = build_open(site[1], make_home(tmp_path, curated))
    recs = records(result)
    assert "石蜜甘" not in recs["蜜甘"].b and "虎掌天南星" not in recs["天南星"].b  # a straddle, a lexicon headword
    assert "虎掌天南星" in recs["虎掌"].b  # for the name unblocked only
    assert "防风党参" not in recs["党参"].b
    # a joint heading a row reads as one name (its drug's) is no longer two: it blocks the other name
    assert "独活羌活" not in recs["独活"].b and "独活羌活" in recs["羌活"].b
    assert "独活羌活" not in result.report["concatenations"]
    assert result.report["unblocked"] == {"天南星": ["虎掌天南星"], "蜜甘": ["石蜜甘"], "党参": ["防风党参"],
                                          "独活": ["独活羌活"]}
    assert "unblock 国老: 国老汤 is no blocker of it" in result.report["warnings"]
    # a cover string in another spelling stays a cover string (validate_curated reads the rows as written)
    assert "unblock 将军: 将军汤 is a cover string of it too; kept as one" in result.report["warnings"]
    assert recs["将军"].b[0] == "将军汤" and "unblock 将军: 将军汤 is no blocker of it" not in result.report["warnings"]


def test_curated_rows_whose_names_normalise_alike_are_one_row(tmp_path, site):
    rows = "cover_stops: {黄连: [黄连根], 黃連: [黃連鬚]}\nunblock: {将军: [石将军], 將軍: [独用將軍]}"
    curated = CURATED.replace("cover_stops: {}", rows)
    assert aliasbuild.validate_curated(loads_yaml(curated)) == []  # the rows are read as written there
    recs = records(build_open(site[1], make_home(tmp_path, curated)))
    assert set(recs["黄连"].b[:2]) == {"黄连根", "黄连须"}  # both rows' cover strings, neither row lost
    assert not {"石将军", "独用将军"} & set(recs["将军"].b)


def test_a_floor_only_name_heads_a_drug_of_its_own(built):
    recs = records(built)
    assert recs["党参"].r == [] and recs["党参"].ho == "党参" and "党参" in built.context["herbs"]


def test_a_witness_that_only_shows_the_name_in_use_is_a_usage_witness(tmp_path, site, built, monkeypatch):
    home, store = site
    usage = "u" if "u" in aliasbuild.WITNESS_KINDS else "e"  # an equation until the format has the kind
    assert [w.kind for w in ref(records(built)["青木香"], "木香").w] == [usage]  # 青木香二两　木香一两
    monkeypatch.setitem(aliasbuild.WITNESS_KINDS, "u", "usage")
    result = build_open(store, home)
    recs = records(result)
    assert [(w.pid, w.kind) for w in ref(recs["青木香"], "木香").w] == [("fang_b.00054", "u")]
    assert ref(recs["国老"], "甘草").w[0].kind == "e"  # 甘草　一名国老: still an equation
    folder = make_home(tmp_path) / "domains" / "classics" / "aliases"
    result.write(folder)
    assert check(folder.parents[2], store=store)["errors"] == []


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
    ({"unblock": ["青矾石"]}, "unblock: not a mapping"),
    ({"unblock": {"党参": ["防风"]}}, "does not hold"),
    ({"unblock": {"将军": ["大将军"]}, "cover_stops": {"将军": ["大将军"]}}, "a cover string of it too"),
])
def test_curated_yaml_is_validated(curated, error):
    assert any(error in e for e in aliasbuild.validate_curated(curated))


def test_a_malformed_curated_file_stops_the_build_and_fails_check(tmp_path, site, built):
    home = make_home(tmp_path, CURATED.replace("stop: [{s: 小便, why: 常用词, wit: [fang_b.00053]}]", "stop: [小便]"))
    with pytest.raises(ValueError, match="not a mapping"):
        build_open(site[1], home)
    built.write(home / "domains" / "classics" / "aliases")
    assert any("not a mapping" in e for e in check(home)["errors"])


@pytest.mark.parametrize("curated, error", [
    (CURATED + "stops: []\n", "unknown section stops"),
    (CURATED.replace("stop: [{s: 小便, why: 常用词, wit: [fang_b.00053]}]", "stop: 5"), "stop: not a list"),
    (CURATED.replace("wit: [fang_b.00053]}]", "wit: 5}]"), "no witness passage"),
], ids=["unknown-section", "section-not-a-list", "witness-not-a-list"])
def test_check_on_a_store_reports_a_malformed_curated_file(tmp_path, site, built, capsys, curated, error):
    home, store = make_home(tmp_path, curated), site[1]
    built.write(home / "domains" / "classics" / "aliases")
    assert any(error in e for e in check(home, store=store, rebuild=True)["errors"])  # a report, not the build's refusal
    with pytest.raises(SystemExit):
        main(["--home", str(home), "--data", str(store.parents[1]), "aliases", "check", "--db", str(store)])
    assert any(error in e for e in json.loads(capsys.readouterr().out)["errors"])


@pytest.mark.parametrize("name, content, said", [
    ("curated.yaml", CURATED + "pairs: [{s: 国老\n", "curated.yaml is not valid YAML: "),
    ("curated.yaml", b"version: 1\nstop: [\xff]\n", "curated.yaml is not valid YAML: "),
    ("sources.yaml", "sources: [{id: bielu-jc\n", "sources.yaml is not valid YAML: "),
    ("sources.yaml", "- {id: bielu-jc}\n", "sources.yaml: the top level is not a mapping"),
    ("sources.yaml", "sources: [bielu-jc]\n", "sources.yaml: sources is not a list of mappings"),
], ids=["curated-unclosed", "curated-not-utf8", "sources-unclosed", "sources-a-list", "sources-of-strings"])
def test_check_reports_a_file_that_is_not_yaml(tmp_path, site, built, capsys, name, content, said):
    home, store = make_home(tmp_path), site[1]
    folder = home / "domains" / "classics" / "aliases"
    built.write(folder)
    (folder / name).unlink()  # sources.yaml links to the repository's
    (folder / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    result = check(home, store=store, rebuild=True)  # a report, not a traceback
    assert not result["ok"] and any(e.startswith(said) for e in result["errors"])
    with pytest.raises(SystemExit) as stop:
        main(["--home", str(home), "--data", str(store.parents[1]), "aliases", "check", "--db", str(store)])
    assert stop.value.code == 1 and any(e.startswith(said) for e in json.loads(capsys.readouterr().out)["errors"])
    for action in ("build", "review"):  # the build and the review refuse it in a sentence
        with pytest.raises(SystemExit, match=f"^{re.escape(said)}"):
            main(["--home", str(home), "--data", str(store.parents[1]), "aliases", action])


def test_held_out_names_are_refused_in_any_spelling_and_in_reasons(tmp_path, built):
    curated = CURATED.replace("decisions:\n", "decisions:\n  - {s: 黃良, status: open, wit: [bc_a.00000]}\n", 1)
    home = make_home(tmp_path, curated.replace("why: 常用词", "why: 常用词，非人銜"))
    built.write(home / "domains" / "classics" / "aliases")
    held = [e for e in check(home, heldout={"黄良", "人衔"})["errors"] if "held-out" in e]
    # counted, never named: the report does not teach its reader the held-out half
    assert held == ["curated.yaml writes 2 held-out gold names (counted, not shown: find the rows by comparing with "
                    "evals/gold/aliases.yaml outside the eval)"]
    home = make_home(tmp_path / "unblock", CURATED.replace("cover_stops: {}", "unblock: {蜜甘: [石蜜甘]}"))
    built.write(home / "domains" / "classics" / "aliases")
    assert any("1 held-out gold name " in e and "石蜜甘" not in e for e in check(home, heldout={"石蜜甘"})["errors"])
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


def test_the_local_layer_counts_with_the_herb_set_its_profile_loads(built):
    rows = [{"h": "紫云藤", "s": "青霞根", "src": "hurb", "ref": "row 4"},
            {"h": "白露藤", "s": "丹霞子", "src": "hurb", "ref": "row 5"},
            {"h": "金风草", "s": "碧霞根", "src": "hurb", "ref": "row 6"}]
    layer = build_local(built, rows)
    assert layer.context == built.context and "白露藤" not in layer.context["herbs"]  # no local head
    rec = records(layer)["青霞根"]  # beside 白露藤 and 金风草, which the profile's gates know as no herbs
    assert rec.n == 1 and rec.sh == 0 and ref(rec, "紫云藤").st == "candidate"


# ------------------------------------------------------------------ the NTU table (CC BY-NC 4.0), shipped
NTU_ROWS = ["PrimaryDrugNameNo.\tPrimaryDrugName\tDictionarySource\tAlternateName\tRemarks",
            "1\t甘草\t《中华本草》\t国老\t（《别录》）",  # an open pair the table confirms, credited
            "1\t甘草\t《中华本草》\t甜根子\t[四川]",  # written once, in 1950, as a drug
            "2\t甘草\t《中药大辞典》\t甜根子\t[陕西]《四川中药志》",  # the same pair again: a modern book credits nothing
            "3\t人参\t《中华本草》\t仁森嘎布\t（藏名）",  # a folk name in Tibetan the store never writes
            "3\t人参\t《中华本草》\t棒槌\t",
            "4\t金霞果\t《全国中草药汇编》\t棒槌\t《纲目拾遗》",  # a head nothing writes, its name written: shared
            "5\t紫霄藤\t《全国中草药汇编》\t碧云根\t",  # neither name a herb or written: left out
            "6\t鸡（土从）\t《中华本草》\t土鸡\t",  # a head with a lost character: none
            "7\t黄连\t《中华本草》\t水麻tiao\t",  # a lost character (in pinyin): no name
            "7\t黄连\t《中华本草》\t黄连须-根\t《纲目》、《本经》",  # a mark dropped: in doubt; the earliest book
            "8\t黄连\t《中华本草》\t王连\t《摘元方》"]  # a book the works table does not list


def ntu_home(root: Path, *, ship: bool = True, pin: bool = True, rows: list[str] = NTU_ROWS) -> Path:
    """A home with a synthetic NTU extract (corpus/aliases/ntu40k.tsv) and the repository's sources.yaml, the
    extract's pin made this one's (``pin``) and the table shipped or local (``ship``)."""
    home = make_home(root)
    extract = home / NTU_EXTRACT
    extract.parent.mkdir(parents=True)
    extract.write_text("# a synthetic extract of the NTU table\n" + "\n".join(rows) + "\n", encoding="utf-8")
    registry = loads_yaml((DOMAIN / "aliases" / "sources.yaml").read_text(encoding="utf-8"))
    ntu = next(s for s in registry["sources"] if s["id"] == aliasbuild.NTU)
    if pin:
        ntu["pin"]["extract"].update(sha256=hashlib.sha256(extract.read_bytes()).hexdigest(), rows=len(rows) - 1)
    if not ship:
        ntu.update({"ship": False, "class": "local"})
    target = home / "domains" / "classics" / "aliases" / "sources.yaml"
    target.unlink()
    target.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return home


@pytest.fixture(scope="module")
def ntu_built(site, tmp_path_factory):
    home = ntu_home(tmp_path_factory.mktemp("ntu"))
    return home, build_open(site[1], home)


def test_without_the_extract_the_build_reads_no_ntu_pair_and_says_so(built):
    header, _ = loads_records(built.text())
    assert aliasbuild.NTU not in header["sources"] and aliasbuild.NTU not in header
    assert f"{aliasbuild.NTU} ships but {NTU_EXTRACT} is missing: none of its pairs is read" in built.report["warnings"]
    assert built.report["coverage"][f"{aliasbuild.NTU}_rows"] == 0


def test_the_ntu_pairs_ship_through_the_usual_gates(site, ntu_built):
    home, result = ntu_built
    recs = records(result)
    guolao = ref(recs["国老"], "甘草")  # curated, the 别名录's and the table's: the curated status, the table's credit
    assert {"curated", "bielu-jc", aliasbuild.NTU} <= set(guolao.src) and guolao.st == "open"
    assert guolao.cr == ("别录", 480, 500)
    tian = ref(recs["甜根子"], "甘草")  # not a local pair: no early passage needed (the local layer's is a candidate)
    assert (tian.src, tian.st, tian.k, tian.nt, tian.cr) == ([aliasbuild.NTU], "open", "alias", "四川、陕西", None)
    folk = ref(recs["仁森嘎布"], "人参")
    assert (folk.k, folk.nt, folk.st, recs["仁森嘎布"].n) == ("folk", "藏名", "open", 0)
    assert {r.h: r.st for r in recs["棒槌"].r} == {"人参": "cue", "金霞果": "cue"}  # one name, two drugs: shared
    assert ref(recs["棒槌"], "金霞果").cr == ("纲目拾遗", 1765, 1765)
    assert recs["金霞果"].ho == "金霞果" and "金霞果" in result.context["herbs"]  # a head the store never writes
    marked = ref(recs["黄连须根"], "黄连")
    assert marked.st == "candidate" and marked.cr == ("本经", 25, 220)  # in doubt; the earliest book its remark cites
    assert not [s for s in recs if "〓" in s]
    assert aliasbuild.NTU in ref(recs["王连"], "黄连").src and ref(recs["王连"], "黄连").cr is None
    assert "碧云根" not in recs and "紫霄藤" not in recs and "土鸡" not in recs and "鸡" not in recs
    cov = result.report["coverage"]
    assert {k[len(aliasbuild.NTU) + 1:]: v for k, v in cov.items() if k.startswith(aliasbuild.NTU)} == {
        "rows": 11, "lost_heads": 1, "lost_names": 1, "pairs": 8, "left_out": 1, "kept": 7, "credited": 3, "folk": 1,
        "doubt": 1}
    assert result.report[aliasbuild.NTU]["books"] == {"classical": 3, "modern": 1, "unlisted": 1}
    assert result.report[aliasbuild.NTU]["left_out"] == 1
    header, _ = loads_records(result.text())
    assert header[aliasbuild.NTU] == hashlib.sha256((home / NTU_EXTRACT).read_bytes()).hexdigest()[:12]
    assert header["labels"][aliasbuild.NTU] == "NTU 40K（CC BY-NC 4.0）" and aliasbuild.NTU in header["sources"]
    assert not [w for w in result.report["warnings"] if NTU_EXTRACT in w]  # the extract is the pinned one
    assert build_open(site[1], home).text() == result.text()  # the same bytes again


def test_the_ntu_extract_is_read_only_while_it_ships_and_checked_against_its_pin(site, tmp_path):
    result = build_open(site[1], ntu_home(tmp_path / "local", ship=False))
    header, _ = loads_records(result.text())
    assert aliasbuild.NTU not in header["sources"] and aliasbuild.NTU not in header
    assert not [k for k in result.report["coverage"] if k.startswith(aliasbuild.NTU)]
    result = build_open(site[1], ntu_home(tmp_path / "other", pin=False))  # the repository's pin: the real extract's
    assert any(w.startswith(f"{NTU_EXTRACT}: sha256 ") and "differs from the pinned" in w
               for w in result.report["warnings"])
    assert aliasbuild.NTU in loads_records(result.text())[0]["sources"]


def test_the_local_layer_leaves_out_the_rows_of_a_list_that_ships(ntu_built):
    _, result = ntu_built
    rows = [{"h": "紫霄藤", "s": "碧云根", "src": aliasbuild.NTU, "ref": "row 7"},
            {"h": "人参", "s": "棒槌", "src": "hurb", "ref": "row 2"}]
    layer = build_local(result, rows)
    recs = records(layer)
    assert "碧云根" not in recs and "hurb" in ref(recs["棒槌"], "人参").src
    assert layer.report["coverage"]["local_pairs"] == 1 and layer.report["coverage"]["local_shipped"] == 1


def test_the_layer_with_the_ntu_table_passes_check_and_its_sources_are_checked(site, ntu_built):
    home, result = ntu_built
    folder = home / "domains" / "classics" / "aliases"
    result.write(folder)
    assert check(home, store=site[1], rebuild=True)["errors"] == []
    text = (folder / "sources.yaml").read_text(encoding="utf-8")
    try:
        registry = loads_yaml(text)
        ntu = next(s for s in registry["sources"] if s["id"] == aliasbuild.NTU)
        ntu.pop("attribution")
        (folder / "sources.yaml").write_text(yaml.safe_dump(registry, allow_unicode=True), encoding="utf-8")
        assert any("non-commercial licence" in e for e in check(home)["errors"])
        ntu.update({"attribution": "x", "class": "local"})
        (folder / "sources.yaml").write_text(yaml.safe_dump(registry, allow_unicode=True), encoding="utf-8")
        errors = check(home)["errors"]
        assert any("is local, so it does not ship" in e for e in errors)
        ntu["class"] = "shared"
        (folder / "sources.yaml").write_text(yaml.safe_dump(registry, allow_unicode=True), encoding="utf-8")
        assert any(f"{aliasbuild.NTU} has no class of open, nc, derived, local" in e for e in check(home)["errors"])
    finally:
        (folder / "sources.yaml").write_text(text, encoding="utf-8")


NTU_SETTLE = [NTU_ROWS[0],
              "11\t青木香\t《中国药典》\t兜铃根\t",  # a head curated.yaml splits by period: kept apart
              "11\t青木香\t《中国药典》\t木香\t",
              "12\t葶苈子\t《中华本草》\t大室\t",  # 葶苈 with the part it is, two of its names: one drug
              "12\t葶苈子\t《中华本草》\t丁历\t",
              "13\t云端草\t《全国中草药汇编》\t地楼\t",  # another head for 栝楼实's two names: a double, no rival
              "13\t云端草\t《全国中草药汇编》\t泽姑\t",
              "14\t甘草\t《中华本草》\t清心丹\t",  # a formula's name: a candidate (5c)
              "15\t胡黄连\t《中华本草》\t揩之\t"]  # written once, not as a drug, no witness: a candidate (5b)


def test_ntu_heads_kept_apart_joined_by_form_and_doubles(site, built, tmp_path):
    result = build_open(site[1], ntu_home(tmp_path, rows=NTU_SETTLE))
    recs, before = records(result), records(built)
    # 青木香: the editors' 木香 before 1100 and 马兜铃 after; the table's entry under it gives no drug
    assert recs["青木香"].ho is None and "兜铃根" not in recs
    assert {r.h: r.v for r in recs["青木香"].r} == {r.h: r.v for r in before["青木香"].r}
    assert result.report[aliasbuild.NTU]["apart"] == {"heads": {"curated": 1}, "pairs": 2}
    # 葶苈子 joins 葶苈 (its form, and the lexicon's 葶苈子 files 葶苈): 大室 still names one drug
    assert recs["葶苈子"].ho == "葶苈" and {r.h for r in recs["大室"].r} == {"葶苈"}
    assert ref(recs["大室"], "葶苈").st == ref(before["大室"], "葶苈").st
    assert result.report[aliasbuild.NTU]["attached"] == {"names": 1}
    # 云端草 shares 地楼 and 泽姑 with 栝楼 (the drug 栝楼实): its pairs are candidates, the others' keep their status
    for name in ("地楼", "泽姑"):
        assert ref(recs[name], "云端草").st == "candidate"
        assert ref(recs[name], "栝楼实").st == ref(before[name], "栝楼实").st
    assert result.report[aliasbuild.NTU]["doubles"] == 2
    assert ref(recs["清心丹"], "甘草").st == "candidate"  # 5c
    assert (recs["揩之"].n, recs["揩之"].sh, ref(recs["揩之"], "胡黄连").st) == (1, 0, "candidate")  # 5b
    assert aliasbuild.apart_errors(result.records, loads_yaml(CURATED), DomainPack(DOMAIN).variants.normalize_text) == []


def test_check_refuses_a_split_name_the_ntu_table_joins_or_heads():
    from taochronos.plugins.classics.aliases import AliasRecord, Referent

    norm = DomainPack(DOMAIN).variants.normalize_text
    curated = loads_yaml(CURATED)
    joined = [AliasRecord("青木香", ho="马兜铃"), AliasRecord("兜铃根", r=[Referent("青木香", src=[aliasbuild.NTU])])]
    assert aliasbuild.apart_errors(joined, curated, norm) == [
        "青木香: a member of 马兜铃, though curated.yaml splits it (a window, a part's or an older name, a cue)",
        "青木香: heads a drug of the NTU table (1 name), though curated.yaml splits it"]
    assert aliasbuild.apart_errors(joined, curated, norm, heldout={"马兜铃"})[0].startswith(
        "青木香: a member of a held-out name,")
    curated["same_drug"].append({"names": ["马兜铃", "青木香"], "wit": ["bc_a.00000"]})  # the editors join them
    listed = [AliasRecord("青木香", ho="马兜铃"), AliasRecord("兜铃根", r=[Referent("青木香", src=["curated"])])]
    assert aliasbuild.apart_errors(listed, curated, norm) == []


def test_the_layer_diff_lists_what_a_rebuild_changes():
    from taochronos.plugins.classics.aliases import AliasRecord, Referent, dumps_records

    old = dumps_records([AliasRecord("大室", r=[Referent("葶苈", st="open")]), AliasRecord("葶苈子", ho="葶苈子"),
                         AliasRecord("丁历", r=[Referent("葶苈", st="cue"), Referent("亭历", st="cue")])], {})
    new = dumps_records([AliasRecord("大室", r=[Referent("葶苈", st="cue"), Referent("葶苈子", st="cue")]),
                         AliasRecord("葶苈子", ho="葶苈"), AliasRecord("丁历", r=[Referent("葶苈", st="cue")]),
                         AliasRecord("大适", r=[Referent("葶苈", st="open")])], {})
    diff = aliasbuild.layer_diff(old, new)
    assert diff["surfaces"] == {"old": 3, "new": 4, "added": 1, "removed": 0}
    assert (diff["ho"], diff["lost"], diff["drops"], diff["held_out_rows"]) == (1, 1, {"open→cue": 1}, 0)
    assert diff["rows"] == {"ho": [["葶苈子", "葶苈子", "葶苈"]], "lost": [["丁历", "亭历", "cue", ["葶苈"]]],
                            "drops": [["大室", "葶苈", "open", "cue", ["葶苈子"]]]}
    hidden = aliasbuild.layer_diff(old, new, heldout={"大室"})
    assert hidden["held_out_rows"] == 1 and hidden["rows"]["drops"] == [] and hidden["drops"] == {"open→cue": 1}


def test_works_give_years_or_say_modern(tmp_path):
    path = tmp_path / "sources.yaml"
    path.write_text("version: 1\nworks: {纲目: [1578, 1578], 尔雅: [-300, 0], 四川中药志: modern}\n", encoding="utf-8")
    assert aliasbuild.read_registry(path)["works"]["四川中药志"] == aliasbuild.MODERN
    for bad in ("[1578]", "[1600, 1578]", "old", "[1578.5, 1600]", "null"):
        path.write_text(f"version: 1\nworks: {{纲目: {bad}}}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="works 纲目 is not"):
            aliasbuild.read_registry(path)


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
    # beside it the context.json it was counted with: the shipped one, which the local profile loads
    assert (local / "context.json").read_bytes() == (folder / "context.json").read_bytes()
    assert sorted(p.name for p in folder.iterdir()) == sorted(aliasbuild.FILES)  # nothing local under the domain
    main(base + ["review", "--top", "5"])
    assert json.loads(capsys.readouterr().out)["rows"] == 5 and (local / "review.tsv").exists()
    main(base + ["show", "国老", "--profile", "web-canon"])
    shown = json.loads(capsys.readouterr().out)
    assert shown["surface"] == "国老" and (shown["record"] or shown.get("committed"))["s"] == "国老"
    (folder / "curated.yaml").write_text(CURATED.replace("国老, head: 甘草", "常山, head: 甘草"), encoding="utf-8")
    with pytest.raises(SystemExit):
        main(base + ["check"])
    said = json.loads(capsys.readouterr().out)["errors"][0]  # a held-out name: counted, not named
    assert said.startswith("curated.yaml writes 1 held-out gold name ") and "常山" not in said
    for there in (tmp_path / "none.sqlite", tmp_path):  # a store that is not there, or a folder, in a sentence
        with pytest.raises(SystemExit, match="no corpus store at"):
            main(base + ["check", "--db", str(there)])
