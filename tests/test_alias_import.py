"""Readers for the lists of other names of drugs (ADR 0023): the 本草纲目别名录 in the store and its GB copy, hurbTable and
the NTU table, and the local import with its pins.  The GB copy, hurbTable and the NTU table are synthetic fixtures
here: their licences keep the real files out of the repository."""

from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.ingest.aliases import (
    BOOK,
    import_local,
    local_rows,
    parse_bielu,
    parse_tab,
    read_bielu_gb,
    read_bielu_store,
    read_hurb,
    read_ntu,
    summary,
    table_file,
)

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
    assert gb["甘露"].ref == "line 16" and names(gb["甘露"]) == ["膏露", "天酒", "瑞露", "神浆"]
    lost = gb[" 石"]
    assert (lost.head, lost.flags, names(lost)) == ("", ["lost_head"], ["太白石", "泽乳"])
    assert (gb["金星石"].flags, gb["仲思枣"].flags) == (["no_list"], ["no_list"])  # 仲思枣 lacks its closing \x
    assert (gb["石南藤"].flags, names(gb["石南藤"])) == (["unbracketed"], ["丁公寄"])
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
    assert read_bielu_gb(original, encoding="gb18030")[0].head == "甘露"


def test_lost_characters_notes_repairs_and_drops(gb):
    tie, fan = gb["铁华粉"], gb["繁缕"]
    assert {t.text: (t.flags, t.drop) for t in tie.tokens} == {
        "铁KT": (["lost_char"], "one_char"), "粉": (["lost_char"], "one_char"), "铁霜": ([], None), "铁艳粉": ([], None)}
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


def test_wraps_join_only_when_attested(gb):
    # unattested, a wrap is left apart and its parts flagged
    assert [(t.name, t.flags, t.drop) for t in gb["黄精"].tokens][2:4] == [("野", ["wrap"], "one_char"),
                                                                          ("生姜", ["wrap"], None)]
    assert [(t.name, t.flags) for t in gb["黄芩"].aliases][1:3] == [("子芩", ["wrap"]), ("尾芩", ["wrap"])]
    attested = {"野生姜", "生姜", "子芩", "尾芩", "文烛"}.__contains__
    joined = {e.head: e for e in read_bielu_gb(FIX / "bielu_gb.txt", attested=attested)}
    assert [(t.name, t.flags) for t in joined["黄精"].aliases] == [
        ("黄芝", []), ("戊己芝", []), ("野生姜", ["joined"]), ("鸡格", []), ("垂珠", [])]
    assert [(t.name, t.flags) for t in joined["黄芩"].aliases][1:3] == [("子芩", []), ("尾芩", [])]  # two names
    wenzhu = token(joined["南烛"], "文烛")  # a note's X on one line, its Y on the next
    assert (wenzhu.text, wenzhu.kind, wenzhu.qualifier, wenzhu.flags) == ("赤者名文烛", "variety", "赤者", ["joined"])
    # two names on both sides of a wrap stay apart when each is attested by itself
    text = "\\x蚤休\\x（七叶 \n一枝花 重楼） \n"
    [e] = parse_bielu(text, attested={"七叶一枝花"}.__contains__)
    assert [(t.name, t.flags) for t in e.aliases] == [("七叶一枝花", ["joined"]), ("重楼", [])]
    [e] = parse_bielu(text, attested={"七叶一枝花", "七叶", "一枝花"}.__contains__)
    assert [(t.name, t.flags) for t in e.aliases] == [("七叶", []), ("一枝花", []), ("重楼", [])]


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


# ------------------------------------------------------------------ hurbTable
def test_hurb_rows_are_realigned():
    rows = read_hurb(FIX / "hurb.csv")
    assert [e.ref for e in rows] == [f"row {n}" for n in range(1, 8)]
    gancao, qiancao, dinggong, dongfeng, zhihuangqi, yishou, zisu = rows
    assert (gancao.flags, gancao.info["source"], names(gancao)) == (
        ["source_in_part"], "豆科植物甘草的干燥根和根茎。", ["国老", "蜜甘", "美草"])
    assert token(gancao, "甘草").drop == "same_as_head"
    assert (qiancao.flags, qiancao.info["english"]) == (["latin_in_alias"], "Rubiae Radix et Rhizoma。")
    assert qiancao.tokens == []
    assert (dinggong.flags, names(dinggong)) == (["aliases_in_part"], ["麻辣子藤", "包公藤", "斑鱼烈"])
    assert (dongfeng.flags, dongfeng.info) == (
        ["source_in_english"], {"english": "Severinia buxifolia", "source": "芸香科植物酒饼筋的根。"})
    assert (zhihuangqi.flags, zhihuangqi.info["english"]) == (["none_word", "source_in_part"], "")
    assert zhihuangqi.tokens == []
    assert [(t.name, t.kind, t.note, t.drop) for t in yishou.tokens] == [
        ("棒子头", "alias", "", None), ("狮子草", "alias", "", None), ("狮子草", "alias", "", "duplicate"),
        ("头", "alias", "", "one_char"), ("榜孜多乌", "folk", "藏药", None)]
    assert (zisu.head, names(zisu)) == ("紫苏叶", ["苏叶"])  # no Name: the head from Medicine_Name


def test_hurb_needs_its_columns(tmp_path):
    bad = tmp_path / "hurb.csv"
    bad.write_text("Name,Alias\n甘草,国老\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Medicine_Name.*the header is \['Name', 'Alias'\]"):
        read_hurb(bad)


# ------------------------------------------------------------------ NTU 40K
def test_tab_cells_are_read_one_by_one():
    header, rows = parse_tab('A\tB\tC\tD\n"x \\"y\\"\\nz\\tw"\t\t""\tplain\r\n')
    assert header == ["A", "B", "C", "D"]
    assert rows == [['x "y"\nz\tw', None, "", "plain"]]  # a missing value is None, an empty string ""


def test_ntu_tab(tmp_path):
    rows = read_ntu(FIX / "ntu.tab", normalize=t2s)
    assert len(rows) == 8
    gancao, gancao2, renshen, huangqi, danggui, jinbuhuan, danshen, nameless = rows
    assert (gancao.head, names(gancao), gancao.info) == ("甘草", ["国老"], {
        "primary": "甘草", "alternate": "國老", "attribution": "《神農本草經》", "note": ""})
    assert (names(gancao2), gancao2.info["attribution"], gancao2.info["note"]) == (["美草", "蜜甘"], None, None)
    assert renshen.info["note"] == 'a "quoted" note\nsecond line\tend'
    assert (huangqi.flags, huangqi.info["alternate"], huangqi.tokens) == (["empty"], "", [])
    assert (danggui.flags, danggui.info["alternate"]) == (["missing"], None)
    assert (jinbuhuan.head, names(jinbuhuan)) == ("金不换", ["山乌龟"])
    assert token(danshen, "丹参").drop == "same_as_head"  # 丹參 is the head once normalised
    assert (nameless.head, nameless.flags) == ("", ["no_head"])
    pairs = local_rows(rows, "ntu")
    assert [(r["h"], r["s"]) for r in pairs] == [("甘草", "国老"), ("甘草", "美草"), ("甘草", "蜜甘"), ("人参", "人衔"),
                                                 ("金不换", "山乌龟")]
    assert pairs[0] == {"h": "甘草", "s": "国老", "raw": "國老", "src": "ntu", "ref": "row 1", "at": "《神農本草經》"}
    assert pairs[3]["nt"] == 'a "quoted" note\nsecond line\tend'


def test_ntu_csv_with_chinese_columns():
    rows = read_ntu(FIX / "ntu.csv", normalize=t2s)
    assert [(e.head, names(e), e.info["attribution"]) for e in rows] == [
        ("甘草", ["国老", "美草"], "《神農本草經》"), ("人参", ["人衔"], None), ("黄芪", [], None)]
    assert rows[2].flags == ["missing"]  # in a CSV an empty cell is a missing value


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
    excel = _zip(tmp_path / "excel.zip", {"MANIFEST.TXT": b"files", "table.xlsx": b"PK"})
    with pytest.raises(ValueError, match=r"holds table.xlsx\); export the workbook as CSV"):
        read_ntu(excel)
    (tmp_path / "table.xlsx").write_bytes(b"PK")
    with pytest.raises(ValueError, match="export it as CSV"):
        read_ntu(tmp_path / "table.xlsx")
    odd = tmp_path / "odd.tab"
    odd.write_text("Name\tSynonym\n\"甘草\"\t\"国老\"\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"no primary or alternate name column; the header is \['Name', 'Synonym'\]"):
        read_ntu(odd)


# ------------------------------------------------------------------ the local layer
def test_import_writes_rows_and_pins(tmp_path):
    out = tmp_path / "aliases" / "local"
    data = (FIX / "hurb.csv").read_bytes()
    hurb = import_local("hurb", FIX / "hurb.csv", out, licence="none stated", attribution="hurbTable (GitHub)",
                        pin={"rows": 7}, imported="2026-10-14")
    assert hurb == {"file": "hurb.csv", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "rows": 7,
                    "pairs": 11, "licence": "none stated", "attribution": "hurbTable (GitHub)",
                    "imported": "2026-10-14"}
    rows = [json.loads(line) for line in (out / "hurb.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0] == {"h": "甘草", "s": "国老", "src": "hurb", "ref": "row 1"}
    assert {"h": "翼首草", "s": "榜孜多乌", "k": "folk", "nt": "藏药", "src": "hurb", "ref": "row 6"} in rows

    zipped = _zip(tmp_path / "ntu.zip", {"MANIFEST.TXT": b"files", "ntu.tab": (FIX / "ntu.tab").read_bytes()})
    ntu = import_local("ntu", zipped, out, normalize=t2s, licence="CC BY-NC 4.0",
                       pin={"file": "ntu.tab", "rows": 50606, "sha256": None}, imported="2026-10-14")
    assert (ntu["file"], ntu["from"], ntu["rows"], ntu["pairs"]) == ("ntu.tab", "ntu.zip", 8, 5)
    assert ntu["sha256"] == hashlib.sha256((FIX / "ntu.tab").read_bytes()).hexdigest()  # the table, not the zip
    assert ntu["warnings"] == ["rows 8 differs from the pinned 50606"]
    first = json.loads((out / "ntu.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert (first["h"], first["s"], first["src"]) == ("甘草", "国老", "ntu40k")  # the id in sources.yaml

    gb = import_local("bielu-gb", FIX / "bielu_gb.txt", out, imported="2026-10-14")
    assert (gb["rows"], gb["pairs"]) == (20, 50)  # the entry whose head was lost gives no pair
    gb_rows = [json.loads(line) for line in (out / "bielu-gb.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"h": "白茅", "s": "茹根", "k": "part_name", "q": "根", "src": "bielu-gb", "ref": "line 22"} in gb_rows
    assert {"h": "知母", "s": "连母", "fl": ["lost_char"], "src": "bielu-gb", "ref": "line 27"} in gb_rows

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"bielu-gb": gb, "hurb": hurb, "ntu": ntu}
    again = import_local("hurb", FIX / "hurb.csv", out, pin={"sha256": hurb["sha256"]}, imported="2026-10-15")
    assert again["sha256"] == hurb["sha256"] and "warnings" not in again
    with pytest.raises(ValueError, match="unknown local alias source"):
        import_local("bielu-jc", FIX / "hurb.csv", out)
