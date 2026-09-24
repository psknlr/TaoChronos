"""The 笈成 (JiCheng) connector: archive unpacking, the viewer's file list / gaiji / variant tables, the markup
parser, dating (book metadata, reign eras, dated prefaces, authors) and ingestion into the corpus store."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from taochronos.plugins.classics.chronology import Chronology, cn_int, ganzhi_year
from taochronos.plugins.classics.citations import CitationExtractor
from taochronos.plugins.classics.domain import DomainPack, ScriptTable, VariantTable, _load
from taochronos.plugins.classics.ingest import (
    _date_from_prefaces,
    build_jicheng_catalog,
    ingest_jicheng,
    jicheng_spec,
    jicheng_variant_rows,
)
from taochronos.plugins.classics.ingest.fetch import unpack_archive
from taochronos.plugins.classics.ingest.jicheng import (
    SIGNED_PREFACE,
    Inline,
    JichengParser,
    preface_dates,
    read_filelist,
    read_nclist,
    read_synonym_groups,
)
from taochronos.plugins.classics.store import CorpusStore, StoreCorpus

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME / "tests" / "fixtures" / "jicheng"
OVERRIDES = {"B901": {"z_layer": {"layer": "测试注", "year": [1700, 1700]}, "work": "shanghan_test"},
             "A901": {"composition": [-300, 25], "work": "suwen", "attribution": "pseudepigraphic"}}
KANRIPO = {"books": [{"kr": "KR3eT999", "title": "本草测试", "aliases": [], "work": "bencao_test", "composition": [1590, 1590]}]}


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(HOME / "domains" / "classics")


@pytest.fixture(scope="module")
def chron(pack) -> Chronology:
    return Chronology(HOME / "domains" / "classics" / "eras.yaml", pack.variants.normalize_text)


@pytest.fixture(scope="module")
def catalog(pack, chron) -> dict:
    cat = build_jicheng_catalog(ROOT, pack.variants.normalize_text, chron, KANRIPO, OVERRIDES, pack.periods.dynasty_of)
    return cat


def _entry(catalog: dict, code: str) -> dict:
    return next(b for b in catalog["books"] if b["code"] == code)


# ------------------------------------------------------------------ chronology
def test_chinese_numerals_and_sexagenary_years():
    assert cn_int("元") == 1 and cn_int("十三") == 13 and cn_int("四十六") == 46 and cn_int("一六四四") == 1644
    assert ganzhi_year("甲子", 1, 60) == 4 and ganzhi_year("甲午", 1662, 1722) == 1714


def test_reign_eras_western_years_and_dynasties(chron):
    assert chron.parse("天啟四年") == ((1624, 1624), "era")
    assert chron.parse("康熙戊申") == ((1668, 1668), "era")
    assert chron.parse("崇禎末年") == ((1639, 1644), "era")
    assert chron.parse("元豐年間") == ((1078, 1085), "era")
    assert chron.parse("西元1862-1918年") == ((1862, 1918), "western")
    assert chron.parse("公元前206年-西元8年") == ((-206, 8), "western")
    assert chron.parse(None, "明末清初") == ((1600, 1700), "dynasty")
    assert chron.parse("", "") == (None, "none")


def test_dated_statements_resolve_reused_eras_and_miswritten_years(chron):
    assert [y for y, _, _ in chron.statements("仍至元三年丁丑七月既望")] == [1337]  # the second 至元
    assert [y for y, _, _ in chron.statements("時康熙歲次甲午夏")] == [1714]
    assert [y for y, _, _ in chron.statements("永樂四年丙戍歲秋八月")] == [1406]  # 丙戍 for 丙戌: the number wins
    assert [y for y, _, _ in chron.statements("中華民國十三年八月")] == [1924]


def test_preface_signatures_date_books(chron):
    body = "[h2]序[/h2]\n余集諸方。\n\n乾隆丙午孟秋李某自序\n\n[h2]卷上[/h2]\n康熙元年事，非落款。\n"
    sigs = preface_dates(body, chron, [])
    assert [(y, own) for y, own, _ in sigs] == [(1786, True)]
    # coarse metadata: the author's own dated preface decides; a reprint preface after the span is ignored
    assert _date_from_prefaces((1644, 1911), "dynasty", sigs, False)[:2] == ([1786, 1786], "preface:author")
    assert _date_from_prefaces((1368, 1644), "dynasty", [(1786, False, "")], False)[:2] == ([1368, 1644], "dynasty")
    # a title marking a later layer (增訂, 評 …) takes the latest preface
    assert _date_from_prefaces(None, "none", [(1623, False, ""), (1880, False, "")], True)[:2] == ([1880, 1880], "preface")
    assert _date_from_prefaces(None, "none", [], False) == (None, "undated", None)


# ------------------------------------------------------------------ viewer tables
def test_file_list_resolves_renamed_and_unlisted_files():
    entries = {e.code: e for e in read_filelist(ROOT)}
    assert entries["B901"].path == "B/B901.txt" and entries["B901"].category == "傷寒" and entries["B901"].remark == "測試備註"
    assert entries["C901"].remark == "未列入檔案表" and entries["C901"].name == "本草測試"


def test_variant_table_skips_misjudged_and_one_to_many_sections():
    groups = read_synonym_groups(ROOT / "config" / "synonyms.txt")
    assert ["乾", "干"] not in groups and ["郃", "合"] not in groups
    domain = HOME / "domains" / "classics"  # the normaliser without the table being generated
    base = VariantTable(_load(domain / "variants.yaml"),
                        ScriptTable(domain / "script", files=[f for f in ScriptTable.FILES if f != "jicheng_variants.tsv"]))
    rows = jicheng_variant_rows(groups, base.normalize_text, set(base.script.map))
    mapped = {r[0]: r[1] for r in rows}
    assert mapped.get("厀") == "膝" and mapped.get("瘈") == "瘛"


def test_inline_markup_layers_gaiji_and_numbering():
    nc = read_nclist(ROOT / "config" / "nclist.txt")
    inline = Inline(nc)
    segs = inline.render("[id]1[/id]太陽病[z]注文[/z]桂枝[l]三兩[/l][j]校記[/j][c]xyz[/c][c]abq[/c][[原闕]]")
    text = {s.layer: s.text for s in segs}
    assert "".join(s.text for s in segs if s.layer == "main") == "太陽病桂枝三兩\U0002318e〓[原闕]"
    assert text["z"] == "注文" and inline.numbers == ["1"] and inline.gaiji == ["abq|日/用|鼠"]


# ------------------------------------------------------------------ catalog and parser
def test_catalog_dates_and_classifies_books(catalog):
    assert not catalog["missing"]
    b901, d901, r901, c901 = (_entry(catalog, c) for c in ("B901", "D901", "R901", "C901"))
    assert b901["category"] == "伤寒" and b901["work"] == "shanghan_test" and b901["quality"] == 0.9
    assert b901["composition"] == [1714, 1714] and b901["dating"] == "preface:author"  # 張某's own dated preface
    assert d901["composition"] == [1786, 1786] and d901["dating"] == "preface:author"
    assert r901["modern"] and r901["category"] == "现代"
    assert c901["composition"] == [1590, 1590] and c901["dating"] == "kanripo:KR3eT999" and c901["work"] == "bencao_test"


def test_parser_layers_formulas_prefaces_and_locators(catalog, pack, chron):
    nc = read_nclist(ROOT / "config" / "nclist.txt")
    entry = _entry(catalog, "B901")
    parser = JichengParser(jicheng_spec(entry), nc, pack.periods.dynasty_of, chron)
    rows = parser.parse(ROOT / "data" / entry["file"])
    by_text = {r["text"]: r for r in rows}
    first = by_text["太陽之為病，脈浮，頭項強痛而惡寒。"]  # 注 separated, 校 dropped
    assert first["locator"]["section"] == "辨太陽病脈證 · 第1条" and first["y_start"] == 1714
    note = next(r for r in rows if r["kind"] == "commentary")
    assert note["text"] == "此太陽病之提綱。" and note["layer"] == "测试注" and note["y_start"] == 1700
    assert note["extra"]["anchor"] == first["id"]
    formula = next(r for r in rows if r["kind"] == "formula")
    assert formula["locator"]["section"].endswith("桂枝湯方") and "桂枝三兩，去皮　芍藥三兩" in formula["text"]
    assert "（疏曰：此承上條而言。）" in by_text["太陽病，頭痛發熱，汗出惡風，桂枝湯主之。（疏曰：此承上條而言。）"]["text"]
    assert not any("據宋本改" in r["text"] for r in rows)
    preface = [r for r in rows if r["kind"] == "preface"]
    assert {r["layer"] for r in preface if "張某" in r["text"] or "濟人" in r["text"]} == {SIGNED_PREFACE}
    assert all(r["y_start"] == 1714 for r in preface if r["layer"] == SIGNED_PREFACE)
    assert any(r["y_start"] == 1911 and "凡方" in r["text"] for r in preface)  # undated 凡例: never earlier than 1911
    assert parser.report["gaiji"] == 1 and parser.report["dropped_collation"] == 1 and not parser.report["unknown_tags"]


def test_ingest_into_the_store_and_search(tmp_path, catalog, pack, chron):
    store = CorpusStore(tmp_path / "tcm.sqlite", create=True)
    report = ingest_jicheng(store, catalog, ROOT, pack.variants.normalize_text, pack.variants.fingerprint, log=lambda m: None,
                            dynasty_of=pack.periods.dynasty_of, version="v1.4.8", chronology=chron)
    assert set(report["books"]) == {"jc_a901", "jc_b901", "jc_d901", "jc_r901", "jc_c901"} and not report["unknown_tags"]
    store.optimize()
    corpus = StoreCorpus(store, pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)
    book = corpus.books["jc_b901"]
    assert book.source.url == "https://jicheng.tw/" and book.source.license and not book.source.verified
    assert "（本书为现代著作）" in corpus.books["jc_r901"].source.license
    hits = corpus.contains("桂枝汤")
    assert hits and all(pid.startswith("jc_b901.") for pid in hits)
    assert corpus.contains("栝楼根")  # traditional 栝樓根 found through normalisation
    p = corpus.passage(corpus.contains("消渴方")[0])
    assert p.book_id == "jc_d901" and corpus.year(p) == 1786 and p.punctuation == "editorial"
    # a chapter of a classic in 书名号 is a citation of that classic, an unknown title stays unresolved
    assert corpus.chapter_titles().get("脉要精微论") == "jc_a901"
    cited = corpus.passage(corpus.contains("千金古方")[0])
    mentions = {m.surface: m for m in CitationExtractor(pack, corpus).extract(cited)}
    assert mentions["脈要精微論"].target_kind == "book" and set(mentions["脈要精微論"].candidates) == {"jc_a901"}
    assert mentions["千金古方"].target_kind == "unresolved"
    # catalog edits that leave dates and layers alone only refresh the book records
    again = ingest_jicheng(store, catalog, ROOT, pack.variants.normalize_text, pack.variants.fingerprint, log=lambda m: None,
                           dynasty_of=pack.periods.dynasty_of, chronology=chron, changed_only=True)
    assert again["records_only"] == 5 and not again["books"]


# ------------------------------------------------------------------ archive
@pytest.mark.skipif(shutil.which("7z") is None, reason="needs the 7z program")
def test_unpack_joins_split_volumes(tmp_path):
    src = tmp_path / "src" / "demo"
    (src / "data").mkdir(parents=True)
    (src / "data" / "a.txt").write_text("太陽病" * 400, encoding="utf-8")
    (src / "data" / "b.bin").write_bytes(bytes(range(256)) * 64)
    subprocess.run(["7z", "a", "-mx=0", "-v4k", str(tmp_path / "up" / "jc_test.7z"), str(src)], check=True, capture_output=True)
    volumes = sorted((tmp_path / "up").glob("jc_test.7z.*"), reverse=True)  # any order
    assert len(volumes) >= 2
    whole = b"".join(v.read_bytes() for v in sorted(volumes))
    facts = unpack_archive(volumes, tmp_path / "out", log=lambda m: None)
    assert facts["sha256"] == hashlib.sha256(whole).hexdigest() and facts["volumes"] == len(volumes)
    assert (tmp_path / "out" / "demo" / "data" / "a.txt").read_text(encoding="utf-8") == "太陽病" * 400
    with pytest.raises(ValueError):
        unpack_archive(volumes[:-1], tmp_path / "bad", log=lambda m: None)  # .001 missing
