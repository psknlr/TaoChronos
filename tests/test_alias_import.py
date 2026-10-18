"""Readers for the lists of other names of drugs (ADR 0023): the 本草纲目别名录 in the store and its GB copy, hurbTable and
the NTU table, and the local import with its pins.  The GB copy, hurbTable and the NTU table are synthetic fixtures
here: their licences keep the real files out of the repository."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest.aliases import (
    BOOK,
    DOUBT_FLAGS,
    NTU,
    NTU_EXTRACT,
    REPAIRS,
    import_local,
    local_rows,
    ntu_table,
    parse_bielu,
    parse_extract,
    parse_remark,
    parse_tab,
    publish_ntu,
    read_bielu_gb,
    read_bielu_store,
    read_hurb,
    read_ntu,
    remark_counts,
    summary,
    table_file,
    xlsx_sheets,
)
from taochronos.plugins.classics.store import CorpusStore, StoreCorpus

HOME = Path(__file__).resolve().parents[1]
FIX = HOME / "tests" / "fixtures" / "aliases"
WEB = HOME / "corpus" / "web" / "passages.jsonl.gz"
_T2S = str.maketrans("國參銜漿濃歲蕪連經農", "国参衔浆浓岁芜连经农")


def t2s(text: str) -> str:
    """A caller's normaliser in miniature (the build passes the pack's)."""
    return text.translate(_T2S)


def names(entry) -> list[str]:
    return [t.name for t in entry.aliases]


def token(entry, name):
    return next(t for t in entry.tokens if t.name == name)


@pytest.fixture(scope="module")
def gb():
    return {e.head or e.head_raw: e for e in read_bielu_gb(FIX / "bielu_gb.txt")}


# ------------------------------------------------------------------ 本草纲目别名录
def test_store_layout_lines_are_cleaned():
    entries = parse_bielu("\n".join([
        "（有別名者錄之無別名者未錄）",
        "甘露（膏露\u3000天酒\u3000瑞露\u3000神漿）",
        "知母（\u3000母\u3000連母\u3000\u3000地參\u3000水參\u3000）",
        "千歲\u3000（\u3000蕪\u3000苣瓜）",
        "濃朴（烈朴\u3000濃皮\u3000子名逐折）",
        "南藤石南藤丁公寄",
    ]), normalize=t2s)
    assert [e.ref for e in entries] == ["line 2", "line 3", "line 4", "line 5", "line 6"]  # the preface is no entry
    sweet, zhimu, lost, houpo, nanteng = entries
    assert (sweet.head, names(sweet), token(sweet, "神浆").raw) == ("甘露", ["膏露", "天酒", "瑞露", "神浆"], "神漿")
    # a blank slot — a lost character — damages the names on both sides; one-character fragments are dropped
    assert {t.name: (t.flags, t.drop) for t in zhimu.tokens} == {
        "母": (["lost_char"], "one_char"), "连母": (["lost_char"], None), "地参": (["lost_char"], None),
        "水参": (["lost_char"], None)}
    assert (lost.head, lost.head_raw, lost.flags, names(lost)) == ("", "千歲\u3000", ["lost_head"], ["苣瓜"])
    # 浓 for 厚: the head and the names are repaired, the spelling as well
    assert (houpo.head, houpo.flags, names(houpo)) == ("厚朴", ["repaired"], ["烈朴", "厚皮", "逐折"])
    assert (token(houpo, "厚皮").raw, token(houpo, "厚皮").flags) == ("厚皮", ["repaired"])
    assert (token(houpo, "逐折").kind, token(houpo, "逐折").qualifier) == ("part_name", "子")
    assert (nanteng.head, nanteng.flags, nanteng.tokens) == ("南藤石南藤丁公寄", ["no_list"], [])


def test_the_normaliser_and_the_repairs_are_the_callers():
    [e] = parse_bielu("甘露（神漿\u3000野狼牙）")
    assert names(e) == ["神漿", "狼牙"]  # no normaliser: names as written
    [e] = parse_bielu("甘露（神漿\u3000野狼牙）", normalize=t2s, repairs=())
    assert names(e) == ["神浆", "野狼牙"]
    [e] = parse_bielu("甘露（野狼牙）", repairs=[{"from": "野狼", "to": "狼"}])  # curated.yaml rows
    assert names(e) == ["狼牙"]


def test_gb_copy_layout(gb):
    assert len(gb) == 20  # title, metadata, 目录 and 篇名 lines and the preface are no entries
    assert gb["甘雨"].ref == "line 16" and names(gb["甘雨"]) == ["膏雨", "天浆", "瑞雨", "神露"]
    lost = gb[" 石"]
    assert (lost.head, lost.flags, names(lost)) == ("", ["lost_head"], ["太白石", "泽乳"])
    assert (gb["银星石"].flags, gb["仲思李"].flags) == (["no_list"], ["no_list"])  # 仲思李 lacks its closing \x
    assert (gb["石南藤"].flags, names(gb["石南藤"])) == (["unbracketed"], ["丁公寄生"])
    assert (gb["丝瓜"].flags, names(gb["丝瓜"])) == (["unclosed"], ["天丝瓜", "布瓜"])
    assert names(gb["麦门冬"]) == ["门冬", "乌韭", "马韭", "禹余粮"]  # a comma separates too
    assert summary(gb.values()) == {
        "entries": 20, "tokens": 70, "names": 52,
        "dropped": {"duplicate": 2, "lost": 3, "one_char": 12, "same_as_head": 1},
        "notes": 12, "flags": {"lost_char": 3, "repaired": 3, "truncated": 1, "wrap": 4},
        "entry_flags": {"lost_head": 1, "no_list": 2, "repaired": 1, "unbracketed": 1, "unclosed": 1}}


def test_gb18030_and_utf8_read_alike(tmp_path):
    original = tmp_path / "bencao_alias.txt"
    original.write_bytes((FIX / "bielu_gb.txt").read_text(encoding="utf-8").encode("gb18030"))
    as_read = [(e.head, e.flags, [(t.name, t.flags, t.drop) for t in e.tokens]) for e in read_bielu_gb(original)]
    assert as_read == [(e.head, e.flags, [(t.name, t.flags, t.drop) for t in e.tokens])
                       for e in read_bielu_gb(FIX / "bielu_gb.txt")]
    assert read_bielu_gb(original, encoding="gb18030")[0].head == "甘雨"
    with pytest.raises(ValueError, match="bencao_alias.txt: not utf-8 text; pass the file's encoding"):
        read_bielu_gb(original, encoding="utf-8")


def test_lost_characters_notes_repairs_and_drops(gb):
    tie, fan = gb["铁华粉"], gb["繁缕"]
    assert {t.text: (t.flags, t.drop) for t in tie.tokens} == {
        "铁KT": (["lost_char"], "one_char"), "粉": (["lost_char"], "one_char"), "铁霜": ([], None), "铁锈粉": ([], None)}
    assert {t.text: (t.flags, t.drop) for t in fan.tokens} == {
        "KT": (["lost_char"], "lost"), "缕": (["lost_char"], "one_char"), "鹅肠菜": ([], None), "滋草": ([], None)}
    assert token(gb["黄瓜菜"], "蕨").flags == ["lost_char"]  # a stray bracket and a blank after it
    # X名Y / X曰Y: Y is the name, its kind from X; a note that lost X or Y is truncated
    pishi = {t.text: (t.name, t.kind, t.qualifier, t.flags, t.drop) for t in gb["砒石"].tokens}
    assert pishi == {"信石": ("信石", "alias", "", [], None),
                     "生者名砒黄": ("砒黄", "variety", "生者", [], None),
                     "炼者名砒霜": ("砒霜", "processing_variant", "炼者", [], None),
                     "者名人言": ("人言", "variety", "者", ["truncated"], None),
                     "小者名苦": ("苦", "variety", "小者", [], "one_char")}
    assert (token(gb["白茅"], "茹根").kind, token(gb["白茅"], "茹根").qualifier) == ("part_name", "根")
    assert {t.text: (t.name, t.flags, t.drop) for t in gb["黍"].tokens} == {
        "赤黍曰": ("", ["truncated"], "lost"), "赤黍曰糜": ("糜", [], "one_char"), "曰芑": ("芑", ["truncated"], "one_char")}
    assert [(t.text, t.name) for t in gb["狼牙"].aliases] == [("野狼子", "狼子"), ("野狼齿", "狼齿"), ("支兰", "支兰")]
    assert (gb["厚朴"].head_raw, names(gb["厚朴"])) == ("浓朴", ["烈朴", "厚皮", "赤朴", "逐折"])
    yuli = gb["郁李"]
    assert [(t.name, t.drop) for t in yuli.tokens] == [
        ("郁李", "same_as_head"), ("车下李", None), ("车下李", "duplicate"), ("爵李", None), ("无名子", None),
        ("天名精", None)]  # 无名子 and 天名精 are names, not notes
    assert all(not t.qualifier for t in yuli.tokens)


def test_lost_character_marks_never_splice_a_name():
    [e, lost] = parse_bielu("甘露（膏〓\u3000天酒\u3000山□葡萄）\n□石（太白石）")
    assert [(t.name, t.flags) for t in e.aliases] == [("膏〓", ["lost_char"]), ("天酒", []), ("山〓葡萄", ["lost_char"])]
    assert (lost.head, lost.flags) == ("", ["lost_head"])


def test_wraps_join_only_when_attested(gb):
    # unattested, a wrap is left apart and its parts flagged
    assert [(t.name, t.flags, t.drop) for t in gb["黄精"].tokens][2:4] == [("野", ["wrap"], "one_char"),
                                                                          ("生姜", ["wrap"], None)]
    assert [(t.name, t.flags) for t in gb["黄芩"].aliases][1:3] == [("子芩", ["wrap"]), ("尾芩", ["wrap"])]
    attested = {"野生姜", "生姜", "子芩", "尾芩", "文烛"}.__contains__
    joined = {e.head: e for e in read_bielu_gb(FIX / "bielu_gb.txt", attested=attested)}
    assert [(t.name, t.flags) for t in joined["黄精"].aliases] == [
        ("黄芝", []), ("戊己芝", []), ("野生姜", ["joined"]), ("鸡格", []), ("龙衔", [])]
    # two attested names whose join is not: two names, no doubt left
    assert [(t.name, t.flags) for t in joined["黄芩"].aliases][1:3] == [("子芩", []), ("尾芩", [])]
    wenzhu = token(joined["南烛"], "文烛")  # a note's X on one line, its Y on the next
    assert (wenzhu.text, wenzhu.kind, wenzhu.qualifier, wenzhu.flags) == ("赤者名文烛", "variety", "赤者", ["joined"])
    text = "\\x蚤休\\x（七叶 \n一枝花 重楼） \n"
    [e] = parse_bielu(text, attested={"七叶一枝花"}.__contains__)
    assert [(t.name, t.flags) for t in e.aliases] == [("七叶一枝花", ["joined"]), ("重楼", [])]
    # the join and both parts attested (as a substring search finds the parts inside the join): left apart, in doubt
    [e] = parse_bielu(text, attested={"七叶一枝花", "七叶", "一枝花"}.__contains__)
    assert [(t.name, t.flags) for t in e.aliases] == [("七叶", ["wrap"]), ("一枝花", ["wrap"]), ("重楼", [])]


@pytest.fixture(scope="module")
def web_bielu():
    if not WEB.is_file():
        pytest.skip("the committed web corpus is not here")
    with gzip.open(WEB, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if BOOK in line]


def test_store_copy_counts(web_bielu):
    normalize = DomainPack(HOME / "domains" / "classics").variants.normalize_text
    entries = read_bielu_store(web_bielu, normalize=normalize)
    # the web excerpt keeps 778 of the 1,086 entries (the preface passage is none)
    assert summary(entries) == {
        "entries": 778, "tokens": 2422, "names": 2106, "dropped": {"lost": 14, "one_char": 297, "same_as_head": 5},
        "notes": 63, "flags": {"lost_char": 43, "repaired": 6, "truncated": 2},
        "entry_flags": {"lost_head": 32, "no_list": 1, "repaired": 6, "unclosed": 2}}
    by_ref = {e.ref: e for e in entries}
    assert f"{BOOK}.00000" not in by_ref and entries == sorted(entries, key=lambda e: e.ref)
    assert (by_ref[f"{BOOK}.00001"].head, names(by_ref[f"{BOOK}.00001"])) == ("甘露", ["膏露", "天酒", "瑞露", "神浆"])
    houpo = next(e for e in entries if e.head_raw == "濃朴")
    assert houpo.head == "厚朴" and "厚皮" in names(houpo)
    assert any("黄鼠狼" in names(e) for e in entries)
    merged = by_ref[f"{BOOK}.00563"]  # 仲思棗, 杏（甜梅）: two heads run together
    assert (merged.head, merged.flags, names(merged)) == ("", ["lost_head"], ["甜梅"])
    head_repairs = [{"passage": f"{BOOK}.00563", "head": "杏"}]  # as curated.yaml gives them
    repaired = read_bielu_store(web_bielu, normalize=normalize, head_repairs=head_repairs)
    fixed = next(e for e in repaired if e.ref == f"{BOOK}.00563")
    assert (fixed.head, fixed.flags, names(fixed)) == ("杏", ["head_repaired"], ["甜梅"])


def test_store_reader_takes_a_corpus_and_keeps_to_its_book():
    passages = [SimpleNamespace(id=f"{BOOK}.00002", book_id=BOOK, text="明水（方諸水）"),
                SimpleNamespace(id=f"{BOOK}.00001", book_id=BOOK, text="甘露（膏露\u3000天酒）"),
                SimpleNamespace(id="other.00001", book_id="other", text="甘草（國老）")]

    class Corpus:
        def iter_passages(self, *, book_ids):
            assert book_ids == [BOOK]
            return iter(passages)

    entries = read_bielu_store(Corpus(), normalize=t2s)
    assert [(e.ref, e.head, names(e)) for e in entries] == [
        (f"{BOOK}.00001", "甘露", ["膏露", "天酒"]), (f"{BOOK}.00002", "明水", ["方諸水"])]
    assert [e.ref for e in read_bielu_store(passages)] == [f"{BOOK}.00001", f"{BOOK}.00002"]
    with pytest.raises(ValueError, match=f"the store has no {BOOK}"):
        read_bielu_store(passages[2:])
    with pytest.raises(ValueError, match=f"head_repairs name passages the store lacks: {BOOK}.99999"):
        read_bielu_store(passages, head_repairs={f"{BOOK}.99999": "礜石"})  # a typo is no silent no-op


def test_store_reader_on_a_store(tmp_path):
    db = CorpusStore(tmp_path / "tcm.sqlite", create=True)
    for bid, texts in ((BOOK, ["（有別名者錄之無別名者未錄）", "甘露（膏露\u3000天酒）", "仲思棗\u3000杏（甜梅）"]),
                       ("other", ["甘草一名國老"])):
        db.put_book({"id": bid, "title": bid, "composition": [1578, 1578]}, source="test")
        db.add_passages([{"id": f"{bid}.{n:05d}", "book_id": bid, "seq": n, "locator": {}, "temporal": {}, "text": t}
                         for n, t in enumerate(texts)], t2s)
    db.commit()
    repairs = [{"passage": f"{BOOK}.00002", "head": "杏"}, {"passage": f"{BOOK}.00500", "head": "礜石"}]
    with pytest.raises(ValueError, match=f"lacks: {BOOK}.00500"):
        read_bielu_store(db, normalize=t2s, head_repairs=repairs)
    db.set_meta("edition", "web")  # the site's excerpt lacks entries by design: their repairs are skipped
    entries = read_bielu_store(db, normalize=t2s, head_repairs=repairs)
    assert [(e.ref, e.head, e.flags, names(e)) for e in entries] == [
        (f"{BOOK}.00001", "甘露", [], ["膏露", "天酒"]), (f"{BOOK}.00002", "杏", ["head_repaired"], ["甜梅"])]
    corpus = StoreCorpus(db, t2s)
    assert [e.ref for e in read_bielu_store(corpus, head_repairs=repairs)] == [e.ref for e in entries]
    with pytest.raises(ValueError, match=f"the corpus leaves {BOOK} out"):
        read_bielu_store(StoreCorpus(db, t2s, exclude_books=(BOOK,)))


def test_repairs_match_the_curated_list():
    curated = HOME / "domains" / "classics" / "aliases" / "curated.yaml"
    if not curated.is_file():
        pytest.skip("no curated.yaml yet")
    import yaml

    rows = (yaml.safe_load(curated.read_text(encoding="utf-8")) or {}).get("repairs") or []
    normalize = DomainPack(HOME / "domains" / "classics").variants.normalize_text
    assert sorted((normalize(r["from"]), normalize(r["to"])) for r in rows) == sorted(REPAIRS)


# ------------------------------------------------------------------ hurbTable
def test_hurb_rows_are_realigned(tmp_path):
    rows = read_hurb(FIX / "hurb.csv")
    assert [e.ref for e in rows] == [f"row {n}" for n in range(1, 8)]
    yungen, chisi, jingou, xifeng, processed, yushou, ziyun = rows
    assert (yungen.flags, yungen.info["source"], names(yungen)) == (
        ["source_in_part"], "豆科植物云根草的干燥根和根茎。", ["石郎", "蜜根", "白衣"])
    assert token(yungen, "云根草").drop == "same_as_head"
    assert (chisi.flags, chisi.info["english"], chisi.tokens) == (["latin_in_alias"], "Rubri Fili Herba。", [])
    assert (jingou.flags, names(jingou)) == (["aliases_in_part"], ["铜钩藤", "包金藤", "斑石烈"])
    assert (xifeng.flags, xifeng.info) == (
        ["source_in_english"], {"english": "Citrus fictitia", "source": "芸香科植物山柑筋的根。"})
    assert (processed.flags, processed.info["english"], processed.tokens) == (["none_word", "source_in_part"], "", [])
    assert [(t.name, t.kind, t.note, t.drop) for t in yushou.tokens] == [
        ("棒槌头", "alias", "", None), ("狮尾草", "alias", "", None), ("狮尾草", "alias", "", "duplicate"),
        ("头", "alias", "", "one_char"), ("榜多吉", "folk", "藏药", None)]
    assert (ziyun.head, names(ziyun)) == ("紫云叶", ["云叶"])  # no Name: the head from Medicine_Name
    gbk = tmp_path / "hurb.csv"  # as Excel saves a CSV on a Chinese Windows
    gbk.write_bytes((FIX / "hurb.csv").read_text(encoding="utf-8-sig").encode("gb18030"))
    assert [(e.head, names(e), e.info) for e in read_hurb(gbk)] == [(e.head, names(e), e.info) for e in rows]


def test_hurb_needs_its_columns(tmp_path):
    bad = tmp_path / "hurb.csv"
    bad.write_text("Name,Alias\n甘草,国老\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Medicine_Name.*the header is \['Name', 'Alias'\]"):
        read_hurb(bad)


# ------------------------------------------------------------------ NTU 40K
NTU_HEADER = ["PrimaryDrugNameNo.", "PrimaryDrugName", "DictionarySource", "AlternateName", "Remarks"]
NTU_ROWS = [  # synthetic: the real table's shapes, none of its rows
    [1, "甘草", "《中华本草》", "国老", "《本经》"],
    [1, "甘草", "《中华本草》《中药大辞典》", " 美草", None],  # a space before the name, as the table has some
    [2, "鸡（土从）", "《中华本草》", "鸡（土从）菜", "（藏名）"],  # 鸡㙡 written by its parts: the head is lost
    [3, "射干", "《全国中草药汇编》", "乌扇", "《本经》郭璞注）"],
    [4, "水麻tiao", "《中华本草》", "水麻条", "[云南、四川]"],  # pinyin for a character the set lacked
    [5, "马蔺", "《中药大辞典》", "铁木尔-地格达", "[蒙名]"],
    [6, "钩吻", "《中华本草》", "大茶（柴）药", "line one\tcell\nline two\\end"],  # a cell with what must be escaped
    [7, "黑果小檗", "《中药大辞典》", "则热克（维名）", "（孟诜《食疗本草》）"],
    [8, "山楂", "《中华本草》", "野山楂又名：小叶山楂", "[浙江误称]"],
    [18292, "祖司麻", "《中药大辞典》", "祖师麻", "（陶弘景）"],
]


def ntu_workbook(rows=None, *, stats_first=True, rich=True) -> bytes:
    """The NTU workbook in small, built with tests/officefiles.py: a summary sheet first (as the dataset's workbook has
    none, its records sheet is found by its header), the records sheet's strings shared, one of them as rich text with
    a phonetic guide (which is not the cell's text) and one with an escaped carriage return."""
    from officefiles import xlsx

    book = xlsx([NTU_HEADER, *(NTU_ROWS if rows is None else rows)], sheets=2)
    stats = xlsx([["Number of primary names", 9], ["Number of alternate names", 10]], inline=True)
    parts = {}
    with zipfile.ZipFile(io.BytesIO(book)) as z, zipfile.ZipFile(io.BytesIO(stats)) as s:
        for info in z.infolist():
            parts[info.filename] = z.read(info)
        records, summary_ = parts["xl/worksheets/sheet1.xml"], s.read("xl/worksheets/sheet1.xml")
        parts["xl/worksheets/sheet1.xml"], parts["xl/worksheets/sheet2.xml"] = (
            (summary_, records) if stats_first else (records, summary_))
    names = ("SimpleStats", "1-to-1 records") if stats_first else ("1-to-1 records", "SimpleStats")
    parts["xl/workbook.xml"] = (parts["xl/workbook.xml"].decode().replace('name="Sheet1"', f'name="{names[0]}"')
                                .replace('name="Sheet2"', f'name="{names[1]}"').encode())
    if rich:
        sst = parts["xl/sharedStrings.xml"].decode()
        sst = sst.replace("<si><t>水麻tiao</t></si>", '<si><r><rPr><sz val="12"/></rPr><t>水麻</t></r><r><t>tiao</t></r>'
                                                     '<rPh sb="0" eb="2"><t>shuima</t></rPh></si>')
        sst = sst.replace("<si><t>祖师麻</t></si>", "<si><t>祖师_x005F_x000D_麻</t></si>")  # an escaped "_", kept
        parts["xl/sharedStrings.xml"] = sst.encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def workbook(tmp_path) -> Path:
    path = tmp_path / "ChineseDrugEthnonymsSynonymyTable.xlsx"
    path.write_bytes(ntu_workbook())
    return path


def test_tab_cells_are_read_one_by_one():
    header, rows = parse_tab('A\tB\tC\tD\n"x \\"y\\"\\nz\\tw"\t\t""\tplain\r\n')
    assert header == ["A", "B", "C", "D"]
    assert rows == [['x "y"\nz\tw', None, "", "plain"]]  # a missing value is None, an empty string ""


def test_ntu_tab(tmp_path):
    rows = read_ntu(FIX / "ntu.tab", normalize=t2s)
    assert len(rows) == 10
    gancao, gancao2, renshen, huangqi, danggui, jinbuhuan, danshen, nameless, jizong, bangga = rows
    assert (gancao.head, names(gancao), gancao.info) == ("甘草", ["国老"], {
        "number": "1", "primary": "甘草", "dictionary": "《中華本草》", "alternate": "國老", "remarks": "《本經》",
        "dictionaries": ["中華本草"], "remark": {"raw": "《本經》", "books": ["本經"], "regions": [], "language": "",
                                               "persons": [], "other": []}})
    assert (names(gancao2), gancao2.info["dictionaries"], gancao2.info["remark"]) == (
        ["美草", "蜜甘"], ["中华本草", "中药大辞典"], None)
    assert renshen.info["remarks"] == 'a "quoted" note\nsecond line\tend'
    assert renshen.info["remark"]["other"] == ['a "quoted" note\nsecond line\tend']  # no Han character: kept whole
    assert (huangqi.flags, huangqi.info["alternate"], huangqi.tokens) == (["empty"], "", [])
    assert (danggui.flags, danggui.info["alternate"]) == (["missing"], None)
    assert (jinbuhuan.head, jinbuhuan.info["head_note"], names(jinbuhuan)) == ("金不换", "广西", ["山乌龟"])
    assert jinbuhuan.info["remark"]["regions"] == ["云南"]
    assert token(danshen, "丹参").drop == "same_as_head"  # 丹參 is the head once normalised
    assert danshen.info["remark"]["persons"] == ["陶弘景"]
    assert (nameless.head, nameless.flags) == ("", ["no_head"])
    assert (jizong.head, jizong.flags) == ("", ["lost_head"])  # never 鸡
    assert [(t.name, t.kind, t.note, t.flags) for t in jizong.tokens] == [("鸡〓菜", "folk", "藏名", ["lost_char"])]
    assert [(t.name, t.kind, t.note) for t in bangga.tokens] == [("榜阿嘎保", "folk", "藏名")]
    pairs = local_rows(rows, "ntu")
    assert [(r["h"], r["s"]) for r in pairs] == [("甘草", "国老"), ("甘草", "美草"), ("甘草", "蜜甘"), ("人参", "人衔"),
                                                 ("金不换", "山乌龟"), ("榜嘎", "榜阿嘎保")]
    assert pairs[0] == {"h": "甘草", "s": "国老", "raw": "國老", "src": "ntu", "ref": "row 1", "at": "《中華本草》",
                        "nt": "《本經》"}
    assert pairs[3]["nt"] == 'a "quoted" note\nsecond line\tend'
    assert pairs[5] == {"h": "榜嘎", "s": "榜阿嘎保", "k": "folk", "nt": "藏名", "src": "ntu", "ref": "row 10",
                        "at": "《中华本草》"}


def test_ntu_csv_with_chinese_columns():
    rows = read_ntu(FIX / "ntu.csv", normalize=t2s)
    assert [(e.head, names(e), e.info["dictionary"], e.info["remarks"]) for e in rows] == [
        ("甘草", ["国老", "美草"], "《中华本草》", "《本经》"), ("人参", ["人衔"], None, None), ("黄芪", [], None, None)]
    assert rows[2].flags == ["missing"] and rows[0].info["number"] is None  # in a CSV an empty cell is a missing value


def test_ntu_columns_are_found_by_name(tmp_path):
    odd = tmp_path / "odd.tsv"
    odd.write_text("Remarks\tAlternate Name\tprimary_drug_name_no\tPrimary Drug Name\n[云南]\t国老\t1\t甘草\n",
                   encoding="utf-8")
    [e] = read_ntu(odd)
    assert (e.head, names(e), e.info["number"], e.info["remarks"], e.info["dictionary"]) == (
        "甘草", ["国老"], "1", "[云南]", None)  # never PrimaryDrugNameNo. for the primary name


def test_ntu_tsv_in_gb18030_with_marks(tmp_path):
    tsv = tmp_path / "ntu.tsv"
    tsv.write_bytes("主名\t别名\n葡萄\t山□葡萄、山(野)葡萄、*紫葡萄\n甘〓草\t国老\n".encode("gb18030"))
    grape, lost = read_ntu(tsv)
    # a lost character never splices its neighbours (山〓葡萄, never 山葡萄); a one-character bracket inside a name is
    # another reading of the character before it (大茶（柴）药, 钩吻's 大茶药): dropped, and the name left in doubt
    assert [(t.name, t.flags, t.note) for t in grape.tokens] == [
        ("山〓葡萄", ["lost_char"], ""), ("山葡萄", ["marks"], "(野)"), ("紫葡萄", ["marks"], "")]
    assert (lost.head, lost.flags) == ("", ["lost_head"])
    with pytest.raises(ValueError, match="ntu.tsv: not utf-8 text"):
        read_ntu(tsv, encoding="utf-8")


def test_ntu_names_written_by_their_parts_in_pinyin_or_labelled(tmp_path):
    entries = read_ntu(_tsv(tmp_path, [
        ["鸡（土从）", "假鸡（土从）"], ["庵 （艹闾）", "（艹殿）（艹塘）"], ["红心灰", "红心灰（艹？）"],
        ["乌鸦", "（匿/虫）鼻药"], ["水麻tiao", "紫 Z H A N木"], ["钩吻", "大茶（柴）药"], ["马蔺", "铁木尔-地格达"],
        ["黑果小檗", "则热克（维名）"], ["榜嘎", "藏名:榜阿嘎保"], ["山楂", "野山楂又名：小叶山楂"],
        ["乌贼鱼肉", "无针乌贼.金乌贼"], ["[檵木]继木", "继花"], ["生等[藏药名]", "生等膏"], ["鸬鹚（鸬鹚）", "鱼鹰"],
        ["山大黄（华北大黄）", "峪黄"], ["金不换(广西)", "山乌龟"], ["蝲蛄", "东北蝲蛄"],
    ]))
    got = {e.head_raw: (e.head, e.flags, e.info.get("head_note"),
                        [(t.name, t.kind, t.note, t.flags, t.drop) for t in e.tokens]) for e in entries}
    assert got["鸡（土从）"] == ("", ["lost_head"], None, [("假鸡〓", "alias", "", ["lost_char"], None)])
    assert got["庵 （艹闾）"] == ("", ["lost_head"], None, [("〓〓", "alias", "", ["lost_char"], None)])
    assert got["红心灰"][3] == [("红心灰〓", "alias", "", ["lost_char"], None)]
    assert got["乌鸦"][3] == [("〓鼻药", "alias", "", ["lost_char"], None)]
    assert got["水麻tiao"] == ("", ["lost_head"], None, [("紫〓木", "alias", "", ["lost_char"], None)])  # never 水麻
    assert got["钩吻"][3] == [("大茶药", "alias", "（柴）", ["marks"], None)]
    assert got["马蔺"][3] == [("铁木尔地格达", "alias", "", ["marks"], None)]
    assert got["黑果小檗"][3] == [("则热克", "folk", "维名", [], None)]
    assert got["榜嘎"][3] == [("榜阿嘎保", "folk", "藏名", [], None)]
    assert [n for n, *_ in got["山楂"][3]] == ["野山楂", "小叶山楂"]
    assert [n for n, *_ in got["乌贼鱼肉"][3]] == ["无针乌贼", "金乌贼"]
    assert got["[檵木]继木"][:3] == ("檵木", [], "继木")  # the bracket the spelling, 继 the GB2312 stand-in
    assert got["生等[藏药名]"][:3] == ("生等", [], "藏药名")
    assert got["鸬鹚（鸬鹚）"][:3] == ("鸬鹚", [], "鸬鹚")  # a repeat is a note, no lost character
    assert got["山大黄（华北大黄）"][:3] == ("山大黄", [], "华北大黄")
    assert got["金不换(广西)"][:3] == ("金不换", [], "广西")
    assert got["蝲蛄"][3] == [("东北蝲蛄", "alias", "", [], None)]


def _tsv(tmp_path, rows) -> Path:
    path = tmp_path / "names.csv"
    path.write_text("PrimaryDrugName,AlternateName\n" + "".join(f'"{h}","{a}"\n' for h, a in rows), encoding="utf-8")
    return path


@pytest.mark.parametrize(("raw", "expected"), [
    ("《纲目》", {"books": ["纲目"]}),
    ("（《中国高等植物图鉴》）", {"books": ["中国高等植物图鉴"]}),
    ("《本经》《别录》", {"books": ["本经", "别录"]}),
    ("《说文））", {"books": ["说文"]}),  # left unclosed
    ("（伏侯《古今注", {"books": ["古今注"], "persons": ["伏侯"]}),
    ("《尔雅》郭璞注）", {"books": ["尔雅"], "persons": ["郭璞"]}),
    ("《庄子》司马彪注）", {"books": ["庄子"], "persons": ["司马彪"]}),
    ("《禽经》注）", {"books": ["禽经"], "other": ["注"]}),
    ("（孟诜《必效方》）", {"books": ["必效方"], "persons": ["孟诜"]}),
    ("（内蒙古《中草药新医疗法资料选编》）", {"books": ["中草药新医疗法资料选编"], "regions": ["内蒙古"]}),
    ("（广州部队《常用中草药手册》）", {"books": ["常用中草药手册"], "other": ["广州部队"]}),
    ("《中级医刊》（5）：57，1959）", {"books": ["中级医刊"], "other": ["（5）：57，1959"]}),
    ("《广东中药》Ⅱ）", {"books": ["广东中药"], "other": ["Ⅱ"]}),
    ("《南方草木状》.醉草", {"books": ["南方草木状"], "other": ["醉草"]}),
    ("[植物名实图考]", {"books": ["植物名实图考"]}),
    ("[云南]", {"regions": ["云南"]}),
    ("（江苏）", {"regions": ["江苏"]}),
    ("[湖北、四川]", {"regions": ["湖北", "四川"]}),
    ("[云南.四川]", {"regions": ["云南", "四川"]}),
    ("[四川木里盐源]", {"regions": ["四川木里盐源"]}),
    ("[广东吊罗山]", {"regions": ["广东吊罗山"]}),
    ("[贵州南部]", {"regions": ["贵州南部"]}),
    ("[浙江误称]", {"regions": ["浙江"], "other": ["误称"]}),
    ("[树皮名—广东]", {"regions": ["广东"], "other": ["树皮名"]}),
    ("（藏名）", {"language": "藏"}),
    ("[傣语]", {"language": "傣"}),
    ("[傣]", {"language": "傣"}),
    ("（蒙名）", {"language": "蒙"}),
    ("[蒙古]", {"language": "蒙"}),
    ("（维名）", {"language": "维"}),
    ("[苗族语]", {"language": "苗"}),
    ("[藏名译音]", {"language": "藏"}),
    ("（藏药名）", {"language": "藏"}),
    ("[勐海傣语]", {"regions": ["勐海"], "language": "傣"}),
    ("[懓尼]", {"language": "僾尼"}),
    ("（陶弘景）", {"persons": ["陶弘景"]}),
    ("（孙思邈）", {"persons": ["孙思邈"]}),
    ("（通称）", {"other": ["通称"]}),
    ("[孔鯆]", {"other": ["孔鯆"]}),  # a fish, in square brackets: no person
    ("[根名]", {"other": ["根名"]}),
    ("[土名]", {"other": ["土名"]}),  # a local name, not one in the Tu language
    ("[♂]", {"other": ["♂"]}),
])
def test_remarks_are_parsed(raw, expected):
    blank = {"books": [], "regions": [], "language": "", "persons": [], "other": []}
    assert parse_remark(raw) == {"raw": raw, **blank, **expected}


def test_empty_remarks_and_their_counts():
    assert parse_remark(None) is None and parse_remark("  ") is None
    counts = remark_counts(["《纲目》", None, "（藏名）", "[云南]（陶弘景）", "[根名]", "《本经》（傣名）"])
    assert counts == {"rows": 5, "books": 2, "regions": 1, "language": 2, "persons": 1, "other": 1, "only_other": 1,
                      "books_cited": 2, "distinct_books": 2, "languages": {"傣": 1, "藏": 1}}


def test_reader_flags_are_classified(gb, tmp_path):
    entries = [*gb.values(), *read_hurb(FIX / "hurb.csv"), *read_ntu(FIX / "ntu.tab"),
               *parse_bielu("甘露（膏〓　山(野)葡萄）"), *read_ntu(FIX / "ntu.csv"), *read_ntu(_xlsx(tmp_path))]
    flags = {f for e in entries for t in e.tokens for f in t.flags}
    assert flags - {"repaired"} <= DOUBT_FLAGS  # every other token flag puts the pair in doubt (a candidate)


def _xlsx(tmp_path) -> Path:
    path = tmp_path / "book.xlsx"
    path.write_bytes(ntu_workbook())
    return path


def test_ntu_workbook(workbook):
    table = ntu_table(workbook)
    assert (table.sheet, table.sheets, table.header) == ("1-to-1 records", ["SimpleStats", "1-to-1 records"],
                                                          NTU_HEADER)
    assert table.columns == {"number": 0, "primary": 1, "dictionary": 2, "alternate": 3, "remarks": 4}
    # a number as the cell shows it, a missing cell None, rich text without its phonetic guide, _x005F_ an "_"
    assert table.rows[0] == ["1", "甘草", "《中华本草》", "国老", "《本经》"]
    assert table.rows[1] == ["1", "甘草", "《中华本草》《中药大辞典》", " 美草"]
    assert table.rows[4][1] == "水麻tiao" and table.rows[6][4] == "line one\tcell\nline two\\end"
    assert table.rows[9] == ["18292", "祖司麻", "《中药大辞典》", "祖师_x000D_麻", "（陶弘景）"]
    entries = read_ntu(workbook)
    assert [e.ref for e in entries] == [f"row {n}" for n in range(1, 11)]
    assert [(e.head, names(e)) for e in entries][:3] == [("甘草", ["国老"]), ("甘草", ["美草"]), ("", ["鸡〓菜"])]
    assert entries[4].flags == ["lost_head"] and entries[7].info["remark"]["persons"] == ["孟诜"]
    first = xlsx_sheets(ntu_workbook(stats_first=False))
    assert [name for name, _ in first] == ["1-to-1 records", "SimpleStats"]
    assert first[1][1]() == [["Number of primary names", "9"], ["Number of alternate names", "10"]]


def test_workbook_errors(tmp_path):
    from officefiles import xlsx

    stats = tmp_path / "stats.xlsx"
    stats.write_bytes(xlsx([["Count", 3]], sheets=2))
    with pytest.raises(ValueError, match="stats.xlsx: no sheet whose first row names the columns.*Sheet1, Sheet2"):
        read_ntu(stats)
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"PK not a zip")
    with pytest.raises(ValueError, match="broken.xlsx: not an Excel workbook"):
        read_ntu(broken)
    (tmp_path / "old.xls").write_bytes(b"\xd0\xcf")
    with pytest.raises(ValueError, match="old.xls: an Excel 97-2003 workbook; save it as .xlsx"):
        read_ntu(tmp_path / "old.xls")


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_ntu_download_forms(tmp_path):
    tab, csv_ = (FIX / "ntu.tab").read_bytes(), (FIX / "ntu.csv").read_bytes()
    bundle = _zip(tmp_path / "dataverse_files.zip", {"MANIFEST.TXT": b"files", "ntu.csv": csv_, "ntu.tab": tab})
    assert table_file(bundle) == ("ntu.tab", tab)  # the archival .tab before the original
    assert [names(e) for e in read_ntu(bundle)] == [names(e) for e in read_ntu(FIX / "ntu.tab")]
    two = _zip(tmp_path / "two.zip", {"a.tab": tab, "b.tab": tab})
    with pytest.raises(ValueError, match="several .tab tables: a.tab, b.tab"):
        read_ntu(two)
    book = ntu_workbook()
    excel = _zip(tmp_path / "excel.zip", {"MANIFEST.TXT": b"files", "table.xlsx": book})
    assert table_file(excel) == ("table.xlsx", book)  # the original workbook, when the zip holds no .tab
    assert len(read_ntu(excel)) == len(NTU_ROWS)
    old = _zip(tmp_path / "old.zip", {"table.xls": b"\xd0\xcf"})
    with pytest.raises(ValueError, match=r"holds table.xls\); save the workbook as .xlsx"):
        read_ntu(old)
    odd = tmp_path / "odd.tab"
    odd.write_text("Name\tSynonym\n\"甘草\"\t\"国老\"\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"no primary or alternate name column; the header is \['Name', 'Synonym'\]"):
        read_ntu(odd)


# ------------------------------------------------------------------ the committed extract
def test_publish_writes_a_faithful_extract(workbook, tmp_path):
    out = tmp_path / "corpus" / "aliases" / "ntu40k.tsv"
    report = publish_ntu(workbook, out, normalize=t2s, pin={"file": "ChineseDrugEthnonymsSynonymyTable.tab",
                                                            "rows": len(NTU_ROWS), "sha256": None})
    data = workbook.read_bytes()
    text = out.read_text(encoding="utf-8")
    notes, header, rows = parse_extract(text)
    assert all(line.startswith("# ") for line in notes)
    head = "\n".join(notes)
    for needed in ("Large List of Chinese Drug Names 40K", "https://doi.org/10.21979/N9/V2XBOH", "CC BY-NC 4.0",
                   "https://creativecommons.org/licenses/by-nc/4.0/", "Chong, William Eng Keat; Stanley-Baker, Michael",
                   "author order and version unverified", "ChineseDrugEthnonymsSynonymyTable.xlsx",
                   hashlib.sha256(data).hexdigest(), f"{len(NTU_ROWS)} rows", "converted from xlsx to TSV",
                   "columns kept; nothing else changed", 'only the sheet "1-to-1 records"', "SimpleStats"):
        assert needed in head, needed
    assert header == NTU_HEADER
    # one line per row, in order, the cells as the workbook holds them; the escaped cell reads back as it was
    lines = text.split("\n")
    assert lines[len(notes)] == "\t".join(NTU_HEADER) and lines[-1] == ""
    assert lines[len(notes) + 2] == "1\t甘草\t《中华本草》《中药大辞典》\t 美草\t"
    assert lines[len(notes) + 7] == "6\t钩吻\t《中华本草》\t大茶（柴）药\tline one\\tcell\\nline two\\\\end"
    assert len(rows) == len(NTU_ROWS) == len(lines) - len(notes) - 2
    assert rows[6][4] == "line one\tcell\nline two\\end" and rows[1][4] is None
    assert [r[0] for r in rows] == [str(r[0]) for r in NTU_ROWS]
    assert report["rows"] == report["written"] == len(NTU_ROWS) and report["escaped_cells"] == 1
    assert (report["sha256"], report["bytes"], report["file"], report["sheet"]) == (
        hashlib.sha256(data).hexdigest(), len(data), workbook.name, "1-to-1 records")
    assert report["extract"] == {"bytes": len(out.read_bytes()), "sha256": hashlib.sha256(out.read_bytes()).hexdigest()}
    assert report["remarks"]["rows"] == 9 and report["remarks"]["languages"] == {"藏": 1, "蒙": 1}
    assert report["names"]["entries"] == len(NTU_ROWS)
    assert report["warnings"] == [("file ChineseDrugEthnonymsSynonymyTable.xlsx differs from the pinned "
                                   "ChineseDrugEthnonymsSynonymyTable.tab")]
    # the extract reads as the workbook does, and the same file gives the same bytes
    view = [(e.head, e.flags, [(t.name, t.kind, t.note, t.flags, t.drop) for t in e.tokens], e.info)
            for e in read_ntu(out, normalize=t2s)]
    assert view == [(e.head, e.flags, [(t.name, t.kind, t.note, t.flags, t.drop) for t in e.tokens], e.info)
                    for e in read_ntu(workbook, normalize=t2s)]
    again = tmp_path / "again.tsv"
    publish_ntu(workbook, again)
    assert again.read_bytes() == out.read_bytes()
    with pytest.raises(ValueError, match="the extract itself"):
        publish_ntu(out, tmp_path / "third.tsv")


def test_publish_from_the_tab(tmp_path):
    out = tmp_path / "ntu40k.tsv"
    report = publish_ntu(FIX / "ntu.tab", out)
    notes, header, rows = parse_extract(out.read_text(encoding="utf-8"))
    assert header == NTU_HEADER and len(rows) == report["written"] == 10
    assert any("converted from tab to TSV" in n for n in notes) and not any("sheet" in n for n in notes)
    assert rows[2][4] == 'a "quoted" note\nsecond line\tend' and report["escaped_cells"] == 1
    assert rows[3][3] is None  # an empty string and a missing value alike: an empty cell


def test_cli_publishes_ntu_only(workbook, tmp_path, capsys):
    from taochronos.cli import main

    out = tmp_path / "extract.tsv"
    base = ["--home", str(HOME), "--data", str(tmp_path / "data"), "aliases", "import"]
    main([*base, "ntu", str(workbook), "--publish", "-o", str(out)])
    report = json.loads(capsys.readouterr().out)
    assert report["output"] == str(out) and report["rows"] == report["written"] == len(NTU_ROWS) and out.exists()
    assert report["names"]["entries"] == len(NTU_ROWS) and not (tmp_path / "data" / "aliases").exists()
    with pytest.raises(SystemExit, match="only the NTU table is published"):
        main([*base, "hurb", str(FIX / "hurb.csv"), "--publish", "-o", str(tmp_path / "hurb.tsv")])


def test_the_extract_credits_what_sources_yaml_credits():
    import yaml

    sources = {s["id"]: s for s in yaml.safe_load((HOME / "domains" / "classics" / "aliases" / "sources.yaml")
                                                  .read_text(encoding="utf-8"))["sources"]}
    entry = sources[NTU["id"]]
    assert (entry["doi"], entry["licence"], entry["title"]) == (NTU["doi"], NTU["licence"], NTU["title"])
    assert "unverified" in entry["attribution"] and "unverified" in NTU["unverified"]
    assert NTU["citation"].startswith("Chong, William Eng Keat; Stanley-Baker, Michael, 2019")


EXTRACT = HOME / NTU_EXTRACT


def test_the_committed_extract():
    if not EXTRACT.is_file():
        pytest.skip("no corpus/aliases/ntu40k.tsv in this checkout")
    text = EXTRACT.read_text(encoding="utf-8")
    notes, header, rows = parse_extract(text)
    head = "\n".join(notes)
    for needed in ("https://doi.org/10.21979/N9/V2XBOH", "CC BY-NC 4.0", "creativecommons.org/licenses/by-nc/4.0/",
                   "unverified", "ChineseDrugEthnonymsSynonymyTable.xlsx", "sheet \"1-to-1 records\"",
                   "sha256 3a4cf287234f69dea286b136a293baea85d2ad8ad9cd187b83b17b9ab981342c", "50606 rows",
                   "converted from xlsx to TSV", "columns kept; nothing else changed"):
        assert needed in head, needed
    assert header == NTU_HEADER and len(rows) == 50606 and text.endswith("\n") and "\r" not in text
    assert rows[0] == ["1", "阿尔太多榔菊", "《全国中草药汇编》", "太白菊", None]
    assert all(len(r) == 5 for r in rows)
    entries = read_ntu(EXTRACT)
    assert len(entries) == 50606 and sum(e.head == "" for e in entries) == 40  # heads with a character lost
    assert {e.info["primary"] for e in entries if "lost_head" in e.flags} >= {"鸡（土从）", "水麻tiao"}


def test_the_extract_never_reaches_the_browser_or_the_image():
    from taochronos.chat.build import HOME_PARTS

    folder = Path(NTU_EXTRACT).parent.as_posix()
    assert not [p for p in HOME_PARTS if folder == p or folder.startswith(p + "/") or p.startswith(folder)]
    allowed = [line[1:].rstrip("/") for line in (HOME / ".dockerignore").read_text(encoding="utf-8").splitlines()
               if line.startswith("!")]
    assert not [p for p in allowed if folder == p or folder.startswith(p + "/")]
    readme = (HOME / "corpus" / "aliases" / "README.md")
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        assert "CC BY-NC 4.0" in text and "10.21979/N9/V2XBOH" in text and "--publish" in text


# ------------------------------------------------------------------ the local layer
def test_import_writes_rows_and_pins(tmp_path):
    out = tmp_path / "aliases" / "local"
    data = (FIX / "hurb.csv").read_bytes()
    hurb = import_local("hurb", FIX / "hurb.csv", out, normalize=t2s, normalizer="t2s", licence="none stated",
                        attribution="hurbTable (GitHub)", pin={"rows": 7}, imported="2026-10-14")
    assert hurb == {"source": "hurb", "file": "hurb.csv", "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data), "rows": 7, "pairs": 11, "normalizer": "t2s", "licence": "none stated",
                    "attribution": "hurbTable (GitHub)", "imported": "2026-10-14"}
    rows = [json.loads(line) for line in (out / "hurb.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0] == {"h": "云根草", "s": "石郎", "src": "hurb", "ref": "row 1"}
    assert {"h": "羽首草", "s": "榜多吉", "k": "folk", "nt": "藏药", "src": "hurb", "ref": "row 6"} in rows

    zipped = _zip(tmp_path / "ntu.zip", {"MANIFEST.TXT": b"files", "ntu.tab": (FIX / "ntu.tab").read_bytes()})
    ntu = import_local("ntu", zipped, out, normalize=t2s, normalizer="t2s", licence="CC BY-NC 4.0",
                       pin={"file": "ntu.tab", "rows": 50606, "sha256": None}, imported="2026-10-14")
    assert [ntu[k] for k in ("source", "file", "from", "rows", "pairs")] == ["ntu40k", "ntu.tab", "ntu.zip", 10, 6]
    assert ntu["sha256"] == hashlib.sha256((FIX / "ntu.tab").read_bytes()).hexdigest()  # the table, not the zip
    assert ntu["warnings"] == ["rows 10 differs from the pinned 50606"]
    first = json.loads((out / "ntu.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert (first["h"], first["s"], first["src"]) == ("甘草", "国老", "ntu40k")  # the id in sources.yaml

    gb = import_local("bielu-gb", FIX / "bielu_gb.txt", out, normalize=t2s, normalizer="t2s", imported="2026-10-14")
    assert (gb["rows"], gb["pairs"]) == (20, 50)  # the entry whose head was lost gives no pair
    gb_rows = [json.loads(line) for line in (out / "bielu-gb.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"h": "白茅", "s": "茹根", "k": "part_name", "q": "根", "src": "bielu-gb", "ref": "line 22"} in gb_rows
    assert {"h": "知母", "s": "连母", "fl": ["lost_char"], "src": "bielu-gb", "ref": "line 27"} in gb_rows

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"bielu-gb": gb, "hurb": hurb, "ntu": ntu}
    again = import_local("hurb", FIX / "hurb.csv", out, normalize=t2s, normalizer="t2s",
                         pin={"sha256": hurb["sha256"]}, imported="2026-10-15")
    assert again["sha256"] == hurb["sha256"] and "warnings" not in again
    with pytest.raises(ValueError, match="unknown local alias source"):
        import_local("bielu-jc", FIX / "hurb.csv", out, normalize=t2s, normalizer="t2s")
