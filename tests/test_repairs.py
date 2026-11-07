"""Conversion repairs (domains/classics/script/conversion_repairs.tsv): Taiwan-phrasing words and wrong traditional
forms a transcription took from its converter (香港腳 for 腳氣, 短劇 for 小品, 迴圈 for 循環, 厚樸 for 厚朴), put right in
the text at ingest, in a store already built (``CorpusStore.repair``) and in the committed 要籍语料 (corpus/web)."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

from taochronos.plugins.classics.chronology import Chronology
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import build_jicheng_catalog, ingest_jicheng
from taochronos.plugins.classics.repairs import TABLE, ConversionRepairs, Repair
from taochronos.plugins.classics.store import CorpusStore, fts_phrase

HOME = Path(__file__).resolve().parents[1]
JICHENG = HOME / "tests" / "fixtures" / "jicheng"


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(HOME / "domains" / "classics")


@pytest.fixture(scope="module")
def repairs(pack) -> ConversionRepairs:
    return pack.repairs


def test_the_table_repairs_the_conversion_errors(repairs):
    assert repairs.fingerprint == ConversionRepairs.load(HOME / "domains" / "classics" / "script" / TABLE).fingerprint
    assert repairs.fix("卷七風毒香港腳方") == ("卷七風毒腳氣方", 1)
    assert repairs.fix("《肘後方》云：《短劇方》爛搗熬之") == ("《肘後方》云：《小品方》爛搗熬之", 1)
    assert repairs.fix("（《短劇》作敗醬）") == ("（《小品》作敗醬）", 1)
    assert repairs.fix("蓋經絡晝夜之迴圈") == ("蓋經絡晝夜之循環", 1)
    assert repairs.fix("半夏厚樸湯　厚樸（三分炙）") == ("半夏厚朴湯　厚朴（三分炙）", 2)
    assert repairs.fix("香港脚鸡鸣散") == ("脚气鸡鸣散", 1)  # a simplified copy
    # 厚樸 where it means simple and honest stays
    assert repairs.fix("其俗敦厚樸實，厚樸（炙）") == ("其俗敦厚樸實，厚朴（炙）", 1)
    assert repairs.fix("民性厚樸實") == ("民性厚樸實", 0)
    # what is right already, and a second pass, change nothing
    for text in ("腳氣衝心", "《小品方》", "循環無端", "厚朴", "樸硝"):
        assert repairs.fix(text) == (text, 0)
    once, _ = repairs.fix("香港腳短劇迴圈厚樸")
    assert once == "腳氣小品循環厚朴" and repairs.fix(once) == (once, 0)


def test_rows_are_repaired_in_text_and_locator_but_not_addresses(repairs):
    row = {"id": "jc_x.00001", "text": "治香港腳方", "locator": {"volume": "卷七風毒香港腳方", "section": "大竹瀝湯",
                                                                "image_uri": "https://example.org/香港腳.jpg", "page": None}}
    fixed, n = repairs.fix_row(row)
    assert n == 2 and fixed["text"] == "治腳氣方" and fixed["locator"]["volume"] == "卷七風毒腳氣方"
    assert fixed["locator"]["image_uri"] == row["locator"]["image_uri"] and row["text"] == "治香港腳方"  # a new row
    same, n = repairs.fix_row({"id": "a", "text": "腳氣", "locator": {"section": "x"}})
    assert n == 0 and same["text"] == "腳氣"


def test_a_table_that_would_contradict_itself_is_refused(tmp_path):
    with pytest.raises(ValueError, match="does not contain it"):
        ConversionRepairs([Repair("厚樸", "厚朴", ("敦厚",))])
    with pytest.raises(ValueError, match="another repair changes"):
        ConversionRepairs([Repair("甲", "乙丙"), Repair("丙", "丁")])
    with pytest.raises(ValueError, match="listed twice"):
        ConversionRepairs([Repair("甲", "乙"), Repair("甲", "丙")])
    path = tmp_path / TABLE
    path.write_text("# comment\n甲乙\t丙丁\t\tnote\n", encoding="utf-8")
    table = ConversionRepairs.load(path)
    assert len(table) == 1 and table.fix("甲乙") == ("丙丁", 1)
    assert not ConversionRepairs.load(tmp_path / "missing.tsv")


def _rows() -> list[dict]:
    texts = ["治風毒香港腳，大竹瀝湯方。", "《短劇》葳蕤湯，療冬溫。", "腳氣衝心者死。", "經絡晝夜之迴圈。"]
    return [{"id": f"t_a.{i:05d}", "book_id": "t_a", "seq": i, "kind": "text", "text": t, "punctuation": "editorial",
             "locator": {"volume": "卷七風毒香港腳方" if i == 0 else "卷八", "section": None}, "temporal": {}}
            for i, t in enumerate(texts)]


def _hits(store: CorpusStore, normalize, surface: str) -> set[int]:
    return {r for (r,) in store.db.execute("SELECT rowid FROM grams WHERE grams MATCH ?", (fts_phrase(normalize(surface)),))}


def test_a_built_store_is_repaired_in_place_with_its_index(tmp_path, pack, repairs):
    normalize, fp = pack.variants.normalize_text, pack.variants.fingerprint
    store = CorpusStore(tmp_path / "tcm.sqlite", create=True)
    store.put_book({"id": "t_a", "title": "测试"}, source="test")
    store.add_passages(_rows(), normalize)
    store.set_meta("normalizer", fp)
    store.db.execute("INSERT INTO claim_cache VALUES ('t_a.00000', 'v', '{}')")
    store.count()
    store.commit()
    assert _hits(store, normalize, "香港") and len(_hits(store, normalize, "腳氣")) == 1
    report = store.repair(repairs, normalize, fp)
    assert report["passages"] == 3 and report["repairs"] == 4 and report["books"] == {"t_a": {"passages": 3, "repairs": 4}}
    rows = dict(store.db.execute("SELECT id, text FROM passages"))
    assert rows["t_a.00000"] == "治風毒腳氣，大竹瀝湯方。" and rows["t_a.00001"] == "《小品》葳蕤湯，療冬溫。"
    assert rows["t_a.00003"] == "經絡晝夜之循環。"
    locator = json.loads(store.db.execute("SELECT locator FROM passages WHERE id='t_a.00000'").fetchone()[0])
    assert locator == {"volume": "卷七風毒腳氣方"}
    assert not _hits(store, normalize, "香港") and len(_hits(store, normalize, "腳氣")) == 2 and _hits(store, normalize, "循環")
    assert store.db.execute("SELECT COUNT(*) FROM claim_cache").fetchone()[0] == 0
    assert json.loads(store.meta("counted"))["characters"] == sum(len(t) for t in rows.values())
    assert store.meta("repairs") == repairs.fingerprint
    store.db.execute("INSERT INTO grams(grams) VALUES('integrity-check')")
    assert store.repair(repairs, normalize, fp)["passages"] == 0  # nothing left to do
    store.set_meta("normalizer", "another")
    with pytest.raises(ValueError, match="reindex"):
        store.repair(repairs, normalize, fp)


def test_a_store_whose_index_is_pending_is_repaired_without_it(tmp_path, pack, repairs):
    normalize, fp = pack.variants.normalize_text, pack.variants.fingerprint
    store = CorpusStore(tmp_path / "web.sqlite", create=True)
    store.add_passages(_rows(), normalize, index=False)
    store.set_meta("normalizer", fp)
    store.set_meta("index", "pending")
    store.commit()
    assert store.repair(repairs, normalize, fp)["passages"] == 3
    assert store.db.execute("SELECT COUNT(*) FROM passages WHERE instr(text, '香港') > 0").fetchone()[0] == 0


def test_ingest_repairs_the_passages_as_they_enter_the_store(tmp_path, pack, repairs):
    root = tmp_path / "jicheng"
    shutil.copytree(JICHENG, root)
    book = root / "data" / "D" / "D901.txt"
    book.write_text(book.read_text(encoding="utf-8").replace(
        "[h2]卷上[/h2]\n", "[h2]卷上[/h2]\n[h3]風毒香港腳方[/h3]\n治香港腳，《短劇》葳蕤湯：厚樸（炙）。\n\n", 1), encoding="utf-8")
    chron = Chronology(HOME / "domains" / "classics" / "eras.yaml", pack.variants.normalize_text)
    catalog = build_jicheng_catalog(root, pack.variants.normalize_text, chron, {"books": []}, {}, pack.periods.dynasty_of)
    store = CorpusStore(tmp_path / "tcm.sqlite", create=True)
    report = ingest_jicheng(store, catalog, root, pack.variants.normalize_text, pack.variants.fingerprint, log=lambda m: None,
                            dynasty_of=pack.periods.dynasty_of, chronology=chron, only=["D901"], repairs=repairs)
    assert report["books"]["jc_d901"]["repaired"] >= 3
    texts = [t for (t,) in store.db.execute("SELECT text FROM passages WHERE book_id='jc_d901'")]
    locators = [loc for (loc,) in store.db.execute("SELECT locator FROM passages WHERE book_id='jc_d901'")]
    assert any("治腳氣，《小品》葳蕤湯：厚朴（炙）。" in t for t in texts)
    assert not any(w in t for t in texts + locators for w in repairs.wrong_forms)
    assert any("風毒腳氣方" in loc for loc in locators)


def test_the_committed_web_pack_holds_no_conversion_error(repairs):
    pack = HOME / "corpus" / "web" / "passages.jsonl.gz"
    if not pack.exists():
        pytest.skip("no committed web pack")
    with gzip.open(pack, "rt", encoding="utf-8") as fh:
        left = [row["id"] for row in map(json.loads, fh) if repairs.fix_row(row)[1]]
    assert not left, f"{len(left)} passages to repair, e.g. {left[:5]}: taochronos web pack (it applies the repairs)"


def test_web_repair_puts_the_sites_store_right_and_writes_its_manifest(tmp_path, pack, capsys):
    """`taochronos web repair` (store.yml): the site's compressed store as cloud/store.json names it — its index still to
    be built, made with an older normaliser — repaired, compressed again, with a new manifest and credits."""
    from taochronos.chat.cloud import unpack
    from taochronos.cli import main
    from taochronos.plugins.classics.webcorpus import package_store, site_store_info

    work = tmp_path / "data" / "cloud"
    work.mkdir(parents=True)
    site = tmp_path / "site.sqlite"
    store = CorpusStore(site, create=True)
    store.put_book({"id": "t_a", "title": "测试方", "source": {"license": "CC0 1.0"}}, source="jicheng")
    store.add_passages(_rows(), pack.variants.normalize_text, index=False)
    for key, value in (("normalizer", "older"), ("index", "pending"), ("index_rid", "0"), ("edition", "full")):
        store.set_meta(key, value)
    store.count()
    store.commit()
    store.close()
    info = {**site_store_info(site), "excluded": {"aeam": 7}}
    _, old = package_store(site, work, info)
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    (cloud / "store.json").write_text(json.dumps(old), encoding="utf-8")
    argv = ["--home", str(HOME), "web", "repair", "--data", str(tmp_path / "data"), "--manifest", str(cloud / "store.json")]
    assert main(argv) in (0, None)
    report = json.loads(capsys.readouterr().out)
    assert report["previous"] == old["sha256"] and report["passages"] == 3 and report["repairs"] == 4
    new = json.loads((cloud / "store.json").read_text(encoding="utf-8"))
    assert new["sha256"] == report["sha256"] != old["sha256"] and new["key"] == f"store/{new['sha256']}/"
    assert new["excluded"] == {"aeam": 7} and new["passages"] == old["passages"] == 4
    assert new["characters"] == old["characters"] - 1  # 香港腳 → 腳氣 once in the text (once more in a title)
    assert new["sources"]["jicheng"]["characters"] == new["characters"]
    assert "共 1 部录本" in (cloud / "ATTRIBUTION.md").read_text(encoding="utf-8")
    back = tmp_path / "back.sqlite"
    unpack(work / f"{new['sha256']}.sqlite.xz", back, new)  # the new file is the one the manifest names
    db = CorpusStore(back)
    assert db.meta("index") == "pending" and db.meta("repairs") == pack.repairs.fingerprint
    assert not db.db.execute("SELECT COUNT(*) FROM passages WHERE instr(text, '香港') > 0 OR instr(locator, '香港') > 0").fetchone()[0]
    assert json.loads(db.meta("counted"))["characters"] == new["characters"]
    db.close()
    assert not (work / "tcm.sqlite").exists()
    # a store with nothing left to repair is left alone, and so is its manifest
    assert main(argv) in (0, None)
    again = json.loads(capsys.readouterr().out)
    assert again["passages"] == 0 and json.loads((cloud / "store.json").read_text(encoding="utf-8")) == new
