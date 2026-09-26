"""The collections read through the common document path — McGill, CMETA, the 東亜医学協会 PDFs, Wikisource (dumps),
TCM-Ancient-Books / tcmoc, the Hugging Face dataset — and the KR-Catalog: readers, the admission policy (当代出版物 / 当代名医著作 /
现代校注本), duplicate detection against the store, cataloguing and ingestion."""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

from taochronos.plugins.classics.chronology import Chronology
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest import aeam, cmeta, mcgill, textsets, wikisource
from taochronos.plugins.classics.ingest.collections import COLLECTIONS, RANK
from taochronos.plugins.classics.ingest.dedupe import SketchIndex, classify, han, load_sketch, sample
from taochronos.plugins.classics.ingest.documents import (
    Block,
    Document,
    build_document_catalog,
    chartype,
    document_rows,
    guess_category,
    ingest_documents,
    note_segments,
    strip_modern_paratext,
)
from taochronos.plugins.classics.ingest.krcatalog import cross_check, parse_dates, read_kr_catalog, record_extras
from taochronos.plugins.classics.ingest.policy import (
    CONTEMPORARY,
    CONTEMPORARY_PHYSICIAN,
    MODERN_EDITION,
    Exclusions,
    screen,
)
from taochronos.plugins.classics.store import CorpusStore

HOME = Path(__file__).resolve().parents[1]
FIX = HOME / "tests" / "fixtures" / "collections"
EXCLUSIONS = Exclusions(HOME / "corpus" / "catalog" / "exclusions.yaml")


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(HOME / "domains" / "classics")


@pytest.fixture(scope="module")
def chron(pack) -> Chronology:
    return Chronology(HOME / "domains" / "classics" / "eras.yaml", pack.variants.normalize_text)


# ------------------------------------------------------------------ readers
def test_mcgill_pages_are_chained_cleaned_and_joined():
    [doc] = mcgill.read(FIX / "mcgill")
    assert (doc.code, doc.title, doc.authors, doc.punctuation) == ("fuqingzhu_nuke", "傅青主女科", ["傅山"], "none")
    assert doc.meta["版本"] == "同治八年, 1869"
    kinds = [(b.kind, b.text[:4]) for b in doc.blocks]
    assert kinds[:2] == [("heading", "卷一"), ("heading", "帶下")]
    para = doc.blocks[2]
    # small characters → （…）; the paragraph runs on over the page break and stays at its first page
    assert "下（白物）如涕" in para.text and para.page == "卷一 1a"
    # 〓 an unread character, <cf> an entity, [x] illegible, {妊} a variant glyph, 穴[允] read as 允
    assert "始病〓脈者" in para.text and "当以〓補妊允之" in para.text
    formula = next(b for b in doc.blocks if b.kind == "formula")
    assert formula.text == "完帶湯（白朮一兩）山藥一兩" and formula.page == "卷一 1b"


def test_tab_file_gb18030_metadata_unwrapping_and_modern_paratext(tmp_path):
    # the collections name their files in Chinese; the fixture is stored under an ASCII name (archives and some
    # file systems mangle non-ASCII names) and copied to its real name here
    path = tmp_path / "001-测试方书.txt"
    shutil.copyfile(FIX / "tab" / "001-ceshi-fangshu.txt", path)
    doc = textsets.read_tab_file(path, "tcm-ancient-books")
    assert doc.title == "测试方书" and doc.authors == ["张三"] and doc.meta["年份"] == "公元1600年"
    assert doc.chartype == "simplified"
    text = doc.text()
    assert "内容提要" not in text and "出版社" not in text and "版权所有" not in text  # modern editor, website credit
    paras = [b.text for b in doc.blocks if b.kind == "para"]
    assert paras[0] == "伤寒者，冬时严寒，万类深藏，君子固密，则不伤于寒。触冒之者，乃名伤寒耳。其伤于四时之气，皆能为病。"
    assert [b.text for b in doc.blocks if b.kind == "heading"] == ["卷一", "伤寒论治", "中风论治"]


def test_wikitext_templates_links_conversion_and_tables():
    blocks = wikisource.wikitext_blocks(
        "== 論 ==\n甲{{*|小注}}乙-{A|萬}--{T|zh-hant:題;zh-hans:题}--{zh-hans:药;zh-hant:藥}-<ref>校記</ref>"
        "{{參|甞|嘗}}{{?}}<small>注<small>內</small></small>。\n"
        "[[File:A.jpg|thumb|圖[[Index:B|校]]]][[本草綱目/草部|草部]]與[[傷寒論]]。\n"
        "{{Image label begin|image=a.svg|width={{{width|400}}}}}\n"
        "{|\n|-\n| width=\"200\" style=\"x\"|桂枝湯 || 三兩\n|}\n")
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "論"), ("para", "甲（小注）乙萬藥甞〓（注（內））。"), ("para", "草部與傷寒論。"), ("para", "桂枝湯　三兩")]


def test_wikitext_pasted_text_files_and_rules():
    blocks = wikisource.wikitext_blocks("中医瑰宝苑\n----\n<目录>卷一\n<篇名>伤寒论治\n书名：某书\n属性：伤寒者，冬时严寒。\\x\n")
    assert [(b.kind, b.level, b.text) for b in blocks] == [
        ("para", 0, "中医瑰宝苑"), ("heading", 1, "卷一"), ("heading", 2, "伤寒论治"), ("para", 0, "伤寒者，冬时严寒。")]


def test_wikisource_work_assembles_subpages_and_skips_shells():
    [doc] = wikisource.read(FIX / "wikisource")  # 空頁 is a transclusion shell with no text
    assert doc.code == "測試醫書" and doc.authors == ["李四"]
    assert doc.meta["朝代"] == "明" and doc.meta["年份"] == "公元1580年" and doc.meta["notes"] == "一部測試用的醫書。"
    assert doc.ref == "page 11 rev 101 (+2 subpages)" and doc.url.endswith("/測試醫書")
    heads = [(b.level, b.text, b.page) for b in doc.blocks if b.kind == "heading"]
    assert heads == [(2, "目錄", None), (1, "卷一", "卷一"), (2, "傷寒論", "卷一"), (3, "附方", "卷一"), (1, "卷二", "卷二"),
                     (2, "中風論", "卷二")]
    assert "[[" not in doc.text() and "（附方）" not in doc.text()  # the main page's list of subpages is dropped


def test_hf_parquet_records(tmp_path):
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    table = pa.table({"id": ["shl-01"], "title": ["伤寒论"], "author": ["张仲景"], "dynasty": ["东汉"],
                      "work_family": ["伤寒论"], "edition_type": ["白文"], "rights_basis": ["pd"], "validation_status": ["ok"],
                      "text": ["辨太阳病脉证并治\n太阳之为病，脉浮，头项强痛而恶寒。\n\n太阳病，发热，汗出，恶风，脉缓者，名为中风。"]})
    pq.write_table(table, tmp_path / "x.parquet")
    [doc] = textsets.read_hf(tmp_path / "x.parquet")
    assert doc.title == "伤寒论" and doc.authors == ["张仲景"] and doc.meta["朝代"] == "东汉"
    assert [b.kind for b in doc.blocks] == ["heading", "para", "para"]



def test_cmeta_opens_only_collated_public_editions_and_rejoins_pages():
    [doc] = cmeta.read(FIX / "cmeta")  # 粗校 and allow-list editions are not read
    assert (doc.code, doc.title, doc.punctuation, doc.chartype) == ("test_book", "測試傷寒論（明刊本）", "editorial", "traditional")
    assert doc.meta["notes"] == "某館藏 明刊本（構造的測試資料）" and doc.extra == {"images": True}
    # the structure files place the 卷 and 篇 headings at their first words; front matter is filed under 序跋
    assert [(b.level, b.text) for b in doc.blocks if b.kind == "heading"] == [
        (1, "序跋"), (2, "序"), (1, "卷第一"), (2, "辨太陽病脈證并治第一")]
    paras = [(b.text, b.page) for b in doc.blocks if b.kind == "para"]
    assert paras == [
        ("測試傷寒論序", "1"),
        ("夫傷寒者，百病之長也。", "1"),  # cut by the page break: joined, located at its first page
        ("太陽之為病，脉浮，頭項強痛而惡寒。", "2"),  # the line 測試傷寒論卷第一 only repeats headings
        ("太陽病，發熱，汗出，惡風，脉緩者（一云浮緩），名為中風。", "2"),  # the note the break cut is whole again
        ("\u3000桂枝三兩去皮\u3000芍藥三兩\u3000甘草二兩炙", "3"),  # doses are the print's small characters, not notes
        ("右三味，以水七升，煮取三升，去滓，溫服一升，口乾辟辟燥者，不可與之。", "3"),  # ＝ repeats the character before it
    ]
    assert {b.image for b in doc.blocks if b.kind == "para" and b.page == "3"} == {cmeta.BASE + "images/test_book/0003.jpg"}
    book = next(b for b in __import__("json").loads((FIX / "cmeta" / "catalog.json").read_text(encoding="utf-8")) if b["id"] == "test_book")
    assert all(b.image is None for b in cmeta.read_book(FIX / "cmeta", book, guest=set()).blocks)  # images not open to guests


def test_cmeta_access_rule_and_composition_lines():
    assert cmeta.open_to_all({"collationLevel": "精校", "textUrl": "t.md"})
    assert not cmeta.open_to_all({"collationLevel": "粗校", "textUrl": "t.md"})
    assert not cmeta.open_to_all({"collationLevel": "精校", "textUrl": "t.md", "textAccess": "whitelist"})
    assert not cmeta.open_to_all({"collationLevel": "精校", "textUrl": "t.md", "access": {"allowTextDisplay": False}})
    assert cmeta.expand_repeats("辟＝燥") == "辟辟燥" and cmeta.expand_repeats("＝") == "＝"
    assert cmeta.unbracket_doses("桂枝（三兩去皮）　芍藥（三兩）") == "桂枝三兩去皮　芍藥三兩"
    sentence = "脉緩者（一云浮緩），名為中風。"  # a sentence with a note is not a composition
    assert cmeta.unbracket_doses(sentence) == sentence


def test_aeam_pdf_lines_punctuation_headings_and_formulas(monkeypatch):
    pages = ["『傷寒論』（趙開美本） \n◆辨太陽病脉證并治上第五 \n太陽之為病．脉浮．頭項強痛而惡\n寒． \n太陽病．發熱．汗出．\n惡風．脉緩者．名為中風． \n",
             "●桂枝湯方 \n桂 枝三兩．去皮．芍藥三兩． \n右三味．寐咀．以水七升． \nこれは編者の注である。 \n■※辨陽明病 \n"
             "陽明之為病．胃家實是也． \n○齊侍御史成自言病頭痛． \n"]
    # a line ends where the PDF line ends with a space; a bare break is a wrap, also across the page
    assert aeam.hard_lines(pages)[2:4] == ["太陽之為病．脉浮．頭項強痛而惡寒．", "太陽病．發熱．汗出．惡風．脉緩者．名為中風．"]
    assert aeam.punctuate("右三味．寐咀．以水 七升． ") == "右三味，㕮咀，以水七升。"
    monkeypatch.setattr(aeam, "_pdf_text", lambda path: pages)
    doc = aeam.read_file(Path("shanghanlun.pdf"), "shanghanlun", "傷寒論")
    assert [(b.kind, b.level, b.text) for b in doc.blocks] == [
        ("heading", 1, "辨太陽病脉證并治上第五"),  # the title line 『…』 is left out
        ("para", 0, "太陽之為病，脉浮，頭項強痛而惡寒。"),
        ("para", 0, "太陽病，發熱，汗出，惡風，脉緩者，名為中風。"),
        ("formula", 0, "桂枝湯方\u3000桂枝三兩，去皮，芍藥三兩。\u3000右三味，㕮咀，以水七升。"),  # kana notes left out
        ("heading", 2, "辨陽明病"),
        ("para", 0, "陽明之為病，胃家實是也。"),
        ("para", 0, "齊侍御史成自言病頭痛。"),
    ]
    assert doc.meta == {"notes": "東亜医学協会校改 1 处（原标※）"} and doc.source == "aeam"


def test_note_layers_markers_added_chapters_and_page_images():
    assert note_segments("甲（注（內））乙（未完") == [("text", "甲"), ("note", "注（內）"), ("text", "乙"), ("note", "未完")]
    image = "https://example.org/images/0003.jpg"
    doc = Document(source="cmeta", code="suwen", title="素問", blocks=[
        Block("heading", "卷第一", level=1), Block("heading", "上古天真論", level=2),
        Block("para", "昔在黃帝，生而神靈（王冰云：神靈，謂智也。新校正云：按全元起本在第九卷。），弱而能言。", page="3", image=image),
        Block("heading", "天元紀大論", level=2), Block("para", "黃帝問曰：天有五行（五行，謂木火土金水）。", page="9")])
    entry = {"id": "cm_suwen", "composition": [-300, 25], "dynasty": "战国—西汉",
             "notes": {"layer": "王冰注", "year": [762, 762], "attribution": "唐·王冰次注"},
             "markers": [{"prefix": "新校正云", "layer": "新校正", "year": [1068, 1068]}],
             "chapter_layers": [{"pattern": "天元紀大論", "layer": "运气七篇", "year": [762, 762]}]}
    rows = document_rows(doc, entry)
    assert [(r["layer"], r["text"], r["y_start"]) for r in rows] == [
        ("正文", "昔在黃帝，生而神靈", -300), ("王冰注", "王冰云：神靈，謂智也。", 762), ("新校正", "新校正云：按全元起本在第九卷。", 1068),
        ("正文", "，弱而能言。", -300), ("运气七篇", "黃帝問曰：天有五行。", 762), ("王冰注", "五行，謂木火土金水", 762)]
    assert rows[0]["locator"]["page"] == "3" and rows[0]["locator"]["image_uri"] == image
    assert rows[1]["extra"]["attribution"] == "唐·王冰次注" and "image_uri" not in rows[4]["locator"]

# ------------------------------------------------------------------ policy
def test_screen_excludes_contemporary_works_physicians_and_modern_editions():
    assert screen("某书", "文", [1956, 1956]).reason == CONTEMPORARY
    assert screen("伤寒论校注", "文", [1644, 1911]).reason == MODERN_EDITION
    assert screen("李某老中医经验集", "文", [1644, 1911]).reason == CONTEMPORARY_PHYSICIAN
    modern = "病人血压一百五十，服维生素，每次十克。" * 10
    assert screen("某医话", modern + "古文" * 2000, [1644, 1911]).reason == CONTEMPORARY
    apparatus = "【注释】某。【语译】某。" * 3
    assert screen("某经", apparatus + "古文" * 500, [1644, 1911]).reason == MODERN_EDITION
    assert screen("某经", apparatus, [1644, 1911], keep=True).reason is None
    assert screen("伤寒论", "太阳之为病，脉浮，头项强痛而恶寒。", [200, 219]).reason is None


def test_reviewed_exclusions_by_code_and_by_title():
    assert EXCLUSIONS.decision("jicheng", "R000", "中医名词术语大辞典") == (CONTEMPORARY, False)
    assert EXCLUSIONS.decision("jicheng", "G045", "程门雪遗稿") == (CONTEMPORARY_PHYSICIAN, False)
    assert EXCLUSIONS.decision("jicheng", "C004", "食疗本草") == (MODERN_EDITION, False)
    assert EXCLUSIONS.decision("jicheng", "G043", "校注妇人良方") == (None, True)  # 薛己 1547, not a modern edition
    assert EXCLUSIONS.decision("tcm-ancient-books", "123-思考中医", "思考中医") == (CONTEMPORARY, False)
    assert EXCLUSIONS.decision("wikisource", "傷寒論", "伤寒论") == (None, False)


def test_modern_paratext_credits_and_page_numbers_are_stripped():
    blocks = [Block("para", "前言"), Block("para", "本书由某出版社于1990年出版。"), Block("heading", "卷一", 1),
              Block("para", "－12－"), Block("para", "中医在线 www.example.com"), Block("para", "太阳之为病，脉浮。"),
              Block("heading", "点校说明", 2), Block("para", "今以某本为底本。"), Block("heading", "卷二", 1),
              Block("para", "阳明之为病，胃家实是也。")]
    assert [b.text for b in strip_modern_paratext(blocks)] == ["卷一", "太阳之为病，脉浮。", "卷二", "阳明之为病，胃家实是也。"]


def test_chartype_and_category_guess():
    assert chartype("这个病证的医药学说") == "simplified" and chartype("這個病證的醫藥學說") == "traditional"
    assert guess_category("临证医案笔记") == "医案" and guess_category("本草从新") == "本草"
    assert guess_category("温热经纬") == "温病" and guess_category("幼科铁镜") == "儿科"
    assert guess_category("经验良方") == "方书" and guess_category("医学心悟") == "综合"


# ------------------------------------------------------------------ duplicates
def _text(seed: int, n: int = 6000) -> str:
    rng = random.Random(seed)
    return "".join(chr(0x4E00 + rng.randrange(0, 8000)) for _ in range(n))


def _doc(code: str, title: str, text: str, *, source: str = "tcm-ancient-books", chartype: str = "traditional",
         meta: dict | None = None) -> Document:
    paras = [Block("para", text[i:i + 300] + "。") for i in range(0, len(text), 300)]
    return Document(source=source, code=code, title=title, blocks=[Block("heading", "卷一", level=1), *paras],
                    meta=meta if meta is not None else {"朝代": "明"}, chartype=chartype)


def test_sketch_index_add_remove_ignore_and_classify():
    a, b = _text(1), _text(2)
    idx = SketchIndex()
    ga, gb = sample(a), sample(b)
    assert ga and sample(a) == ga  # content-defined: the same text always gives the same shingles
    idx.add("A", ga)
    idx.add("B", gb)
    idx.add("A2", ga)
    kind, matches, union = classify(idx, sample(a[:3000]))
    assert kind == "duplicate" and {m.book_id for m in matches[:2]} == {"A", "A2"} and matches[0].containment == 1.0
    assert classify(idx, sample(a), ignore={"A", "A2"})[0] == "new"
    idx.remove("A2")
    assert idx.match(ga)[0].book_id == "A" and "A2" not in idx.books
    idx.remove("A")
    assert idx.match(ga) == [] and idx.match(gb)[0].book_id == "B"


SOURCE_A = {"id": "mcgill", "name": "测试来源甲", "license": "Public Domain", "url": "https://example.org/a"}
SOURCE_B = {"id": "tcm-ancient-books", "name": "测试来源乙", "license": "未声明", "url": "https://example.org/b"}
JICHENG = {"books": [{"code": "X1", "id": "jc_x1", "title": "测试方书", "aliases": [], "work": "work_x",
                      "composition": [1600, 1600], "dating": "curated", "status": "ingest", "category": "方书"}]}


def _catalog(docs, source, store, pack, chron, *, tmp_path, rank_ignore=True, **kw):
    normalize = pack.variants.normalize_text
    sketch = load_sketch(store, normalize, tmp_path / "sketch.pkl", pack.variants.fingerprint)
    book_source = dict(store.db.execute("SELECT id, source FROM books"))
    ignore = {b for b, s in book_source.items() if RANK.get(s, 99) >= RANK[source["id"]]} if rank_ignore else set()
    return build_document_catalog(docs, source, normalize=normalize, chronology=chron, kanripo=None, jicheng=JICHENG,
                                  overrides=kw.pop("overrides", {}), exclusions=EXCLUSIONS, sketch=sketch,
                                  dynasty_of=pack.periods.dynasty_of, prefix=kw.pop("prefix", "t"),
                                  book_work={"a_x1": "work_x"}, ignore=ignore, **kw)


def test_catalog_dedupes_against_the_store_and_within_the_source(tmp_path, pack, chron):
    normalize = pack.variants.normalize_text
    store = CorpusStore(tmp_path / "c.sqlite", create=True)
    t1, t3, t6 = _text(11), _text(13), _text(16)
    # the higher-ranked source: one book (an independent source: copies are never marked, only matched)
    cat_a = _catalog([_doc("x1", "测试方书", t1, source="mcgill")], SOURCE_A, store, pack, chron, tmp_path=tmp_path,
                     prefix="a", duplicate=None, same_work=None)
    assert cat_a["books"][0]["status"] == "ingest" and cat_a["books"][0]["work"] == "work_x"
    ingest_documents(store, cat_a, [_doc("x1", "测试方书", t1, source="mcgill")], normalize, pack.variants.fingerprint,
                     chronology=chron, dynasty_of=pack.periods.dynasty_of, log=lambda m: None)
    # a lower-ranked source already in the store (to be ignored when cataloguing a higher one)
    store.put_book({"id": "oc_t6", "title": "他源书", "composition": [1644, 1911]}, source="tcmoc")
    store.add_passages([{"id": "oc_t6.00000", "book_id": "oc_t6", "edition_id": None, "seq": 0, "kind": "text", "layer": "正文",
                         "year": 1700, "y_start": 1644, "y_end": 1911, "locator": {}, "temporal": {}, "text": t6}], normalize)
    store.commit()
    half = t1[:3600] + _text(99, 2400)
    docs = [
        _doc("b1", "别名书", t1),  # a verbatim copy under another title
        _doc("b2", "测试方书", half, chartype="simplified"),  # the same work, 60% in common (a converted copy)
        _doc("b3", "新书", t3),  # new
        _doc("b4", "新书重刻", t3[:5000]),  # a copy of b3, within this source
        _doc("b5", "思考中医", _text(15)),  # excluded by title
        _doc("b6", "他源书", t6),  # only in a lower-ranked source: not a duplicate
        _doc("b7", "近人书", _text(17), meta={"朝代": "民國"}),  # Republican: kept, category 近代
    ]
    cat = _catalog(docs, SOURCE_B, store, pack, chron, tmp_path=tmp_path, derivative=True)
    by = {b["code"]: b for b in cat["books"]}
    assert [b["code"] for b in cat["books"]] == sorted(by)
    assert by["b1"]["status"] == "duplicate" and by["b1"]["duplicate_of"] == "a_x1"
    assert by["b2"]["status"] == "duplicate" and by["b2"]["duplicate_of"] == "a_x1"
    assert by["b2"]["dating"] == "jicheng:X1" and by["b2"]["composition"] == [1600, 1600]
    assert by["b3"]["status"] == "ingest" and by["b3"]["id"] == "t_b3"
    assert by["b4"]["status"] == "duplicate" and by["b4"]["duplicate_of"] == "t_b3"
    assert by["b5"]["status"] == "excluded" and by["b5"]["excluded_reason"] == CONTEMPORARY
    assert by["b6"]["status"] == "ingest"
    assert by["b7"]["status"] == "ingest" and by["b7"]["category"] == "近代" and by["b7"]["modern"]
    # an independent transcription with 60% in common is another witness, not a copy
    cat_w = _catalog([_doc("w1", "测试方书", half, source="wikisource")], {**SOURCE_B, "id": "wikisource"}, store, pack, chron,
                     tmp_path=tmp_path, duplicate=0.9, same_work=0.5)
    assert cat_w["books"][0]["status"] == "ingest" and cat_w["books"][0]["closest"][0]["book"] == "a_x1"

    report = ingest_documents(store, cat, docs, normalize, pack.variants.fingerprint, chronology=chron,
                              dynasty_of=pack.periods.dynasty_of, version="abc123", log=lambda m: None)
    assert set(report["books"]) == {"t_b3", "t_b6", "t_b7"}
    assert report["duplicates"] == {"b1": "a_x1", "b2": "a_x1", "b4": "t_b3"} and report["excluded"] == {"b5": CONTEMPORARY}
    stored = {b for (b,) in store.db.execute("SELECT id FROM books WHERE source='tcm-ancient-books'")}
    assert stored == {"t_b3", "t_b6", "t_b7"}
    import json

    rec = json.loads(store.db.execute("SELECT data FROM books WHERE id='t_b3'").fetchone()[0])
    assert rec["source"]["license"] == "未声明" and rec["source"]["acquisition"].endswith("abc123")
    assert "断代依据" in rec["notes"] and rec["editions"][0]["quality"] == 0.7
    # a later catalog that marks an admitted book as a copy takes it out of the store
    cat["books"] = [{**b, "status": "duplicate", "duplicate_of": "a_x1"} if b["code"] == "b6" else b for b in cat["books"]]
    ingest_documents(store, cat, docs, normalize, pack.variants.fingerprint, chronology=chron, log=lambda m: None)
    assert store.db.execute("SELECT COUNT(*) FROM books WHERE id='t_b6'").fetchone()[0] == 0


def test_stubs_reviewed_copies_and_partial_copies(tmp_path, pack, chron):
    normalize = pack.variants.normalize_text
    store = CorpusStore(tmp_path / "p.sqlite", create=True)
    t1 = _text(31)
    cat_a = _catalog([_doc("x1", "测试方书", t1, source="mcgill")], SOURCE_A, store, pack, chron, tmp_path=tmp_path, prefix="a",
                     duplicate=None, same_work=None)
    ingest_documents(store, cat_a, [_doc("x1", "测试方书", t1, source="mcgill")], normalize, pack.variants.fingerprint,
                     chronology=chron, log=lambda m: None)
    reviewed = {"books": [{"code": "G043", "id": "jc_g043", "title": "校注妇人良方", "aliases": [], "work": "w_g043",
                           "composition": [1547, 1547], "dating": "curated", "status": "ingest", "category": "妇科"}]}
    docs = [_doc("s1", "目录页", "卷一。卷二。"),  # a stub
            _doc("k1", "校注妇人良方", _text(32)),  # 校注 in the title, but the 笈成 copy was reviewed and kept (薛己, 1547)
            _doc("p1", "另一书名", t1[:3300] + _text(33, 2700))]  # 55% of a stored book under another title: an extract
    sketch = load_sketch(store, normalize, tmp_path / "sketch.pkl", pack.variants.fingerprint)
    cat = build_document_catalog(docs, SOURCE_B, normalize=normalize, chronology=chron, kanripo=None, jicheng=reviewed,
                                 overrides={}, exclusions=EXCLUSIONS, sketch=sketch, dynasty_of=pack.periods.dynasty_of,
                                 prefix="t", derivative=True)
    by = {b["code"]: b for b in cat["books"]}
    assert by["s1"]["status"] == "skipped" and "篇幅过短" in by["s1"]["skipped_reason"]
    assert by["k1"]["status"] == "ingest" and by["k1"]["composition"] == [1547, 1547]
    assert by["p1"]["status"] == "duplicate" and by["p1"]["duplicate_of"] == "a_x1"
    report = ingest_documents(store, cat, docs, normalize, pack.variants.fingerprint, chronology=chron, log=lambda m: None)
    assert set(report["skipped"]) == {"s1"} and set(report["books"]) == {"t_k1"}


def test_sketch_cache_follows_the_store(tmp_path, pack):
    normalize = pack.variants.normalize_text
    store = CorpusStore(tmp_path / "s.sqlite", create=True)

    def put(bid: str, text: str) -> None:
        store.put_book({"id": bid, "title": bid}, source="jicheng")
        store.add_passages([{"id": f"{bid}.00000", "book_id": bid, "edition_id": None, "seq": 0, "kind": "text", "layer": "正文",
                             "year": 1700, "y_start": 1700, "y_end": 1700, "locator": {}, "temporal": {}, "text": text}], normalize)
        store.commit()

    put("k1", _text(21))
    put("k2", _text(22))
    cache = tmp_path / "sketch.pkl"
    first = load_sketch(store, normalize, cache, pack.variants.fingerprint)
    assert set(first.books) == {"k1", "k2"} and cache.exists()
    store.delete_book("k1", normalize)
    store.commit()
    put("k3", _text(23))
    second = load_sketch(store, normalize, cache, pack.variants.fingerprint)
    assert set(second.books) == {"k2", "k3"}
    assert second.match(sample(han(normalize(_text(23)))))[0].book_id == "k3"
    assert set(load_sketch(store, normalize, cache, "another-normaliser").books) == {"k2", "k3"}  # rebuilt, same result


# ------------------------------------------------------------------ KR-Catalog
def test_kr_catalog_persons_roles_dates_and_review():
    texts = read_kr_catalog(FIX / "kr" / "KR3e.txt")
    t1 = texts["KR3eT001"]
    assert t1["title"] == "黃帝內經素問" and t1["siku"] == "四庫全書 文淵閣版, V733.1, p1" and t1["extent"] == "24 卷"
    assert [(p["name"], p.get("role")) for p in t1["persons"]] == [("王冰", "次注"), ("林億", "校正")]
    assert t1["persons"][0]["dates"]["range"] == [762, 762] and t1["editions"] == ["WYG"]
    assert parse_dates("1518 - 1593")["range"] == [1518, 1593] and parse_dates("12th cent")["range"] == [1100, 1199]
    assert parse_dates("ca. 250 - ca. 330")["approximate"] and parse_dates("b. 1585")["kind"] == "birth"
    kanripo = {"books": [{"kr": "KR3eT001", "id": "suwen", "authors": ["佚名（托名黄帝、岐伯）"], "composition": [-300, 25],
                          "attribution": "pseudepigraphic"},
                         {"kr": "KR3eT002", "id": "sanyin", "authors": ["陳言"], "composition": [1174, 1174]}]}
    review = cross_check(texts, kanripo)
    assert review == [{"kr": "KR3eT002", "book": "sanyin", "dates": {"curated": [1174, 1174], "kr_catalog": ["陳言 fl. 1500 - 1540"]}}]
    extras = record_extras(t1)
    assert extras["responsibility"][0] == {"name": "王冰", "dynasty": "唐", "role": "次注", "dates": "fl. 762"}
    assert extras["responsibility_note"] == "责任者（Kanripo 目录）：唐·王冰次注（fl. 762）、宋·林億校正"


def test_collections_registry_ranks():
    assert list(sorted(COLLECTIONS, key=RANK.__getitem__)) == ["mcgill", "cmeta", "aeam", "wikisource", "tcm-ancient-books", "tcmoc",
                                                               "hf-tcm-canon"]
    assert COLLECTIONS["mcgill"].duplicate is None and COLLECTIONS["cmeta"].duplicate is None and COLLECTIONS["tcmoc"].derivative
    assert {c.prefix for c in COLLECTIONS.values()} == {"mg", "cm", "ae", "ws", "tab", "oc", "hf"}
