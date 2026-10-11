"""我的资料 — a user's own files read (TXT, Word, CSV, Excel, JSON), made anonymous, kept and analysed: described,
compared by groups, prescriptions read with the classics' lexicon and set beside the compositions of the classics;
offered to the chat model as the 我的资料 tools, citable as ``mine:…``, kept by the browser between visits, and
refused by a server other machines reach."""

from __future__ import annotations

import base64
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from officefiles import docx, xlsx
from taochronos.chat import ChatRuntime
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.userdata import UserData, Unreadable, analysis, deid
from taochronos.plugins.userdata.formats import MAX_BYTES, read
from taochronos.plugins.userdata.rx import PrescriptionReader
from taochronos.plugins.userdata.store import MAX_DATASETS, NotFound, column_types, number, passages_of
from taochronos.science.stats import chi_square_independence, fisher_exact_two_sided, mean_sd

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics", extra_lexicons=("lexicon-supplement", "lexicon-core"))
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "formulas")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


@pytest.fixture(scope="module")
def reader(study) -> PrescriptionReader:
    return PrescriptionReader(study)


def clinic(rows: int = 60) -> bytes:
    """A clinic's table: who (to be made anonymous), a diagnosis, an age, an outcome and the prescription."""
    import random

    rng = random.Random(11)
    bases = {"感冒": ["柴胡", "黄芩", "半夏", "党参", "甘草", "生姜", "大枣"], "咳嗽": ["麻黄", "杏仁", "甘草", "石膏"],
             "腹痛": ["桂枝", "白芍", "甘草", "生姜", "大枣"]}
    lines = ["姓名,手机,身份证号,出生日期,医生,性别,年龄,诊断,处方,疗效"]
    for i in range(rows):
        dx = list(bases)[i % 3]
        drugs = [d for d in bases[dx] if rng.random() > 0.15 or d in bases[dx][:2]]
        rx = " ".join(f"{d}{rng.choice([6, 9, 12])}g" for d in drugs)
        age = 20 + (i % 3) * 20 + rng.randint(0, 9)  # 感冒 younger, 腹痛 older
        lines.append(f"张{i % 7},1390000{i:04d},110105199001{i % 28 + 1:02d}{i:03d}X,1990-01-{i % 28 + 1:02d},李医生{i % 2},"
                     f"{'男女'[i % 2]},{age},{dx},{rx},{'有效' if i % 3 != 2 or i % 2 else '无效'}")
    return "\n".join(lines).encode("utf-8")


# ------------------------------------------------------------------ reading files
def test_text_files_in_the_encodings_a_chinese_computer_writes():
    for raw in ("桂枝汤主之。\r\n第二段。".encode("gb18030"), "﻿桂枝汤主之。\n第二段。".encode("utf-8"),
                "桂枝汤主之。\n第二段。".encode("utf-16")):
        p = read("笔记.txt", raw)
        assert p.kind == "text" and p.text.splitlines() == ["桂枝汤主之。", "第二段。"]
    assert read("notes.md", "# 题\n\n正文".encode()).text.startswith("# 题")
    assert passages_of("甲。\n\n乙。\n丙。") == ["甲。", "乙。", "丙。"]
    long = "气" * 300 + "。" + "血" * 300 + "。" + "精" * 400
    parts = passages_of(long)
    assert [len(x) for x in parts] == [301, 301, 400] and "".join(parts) == long  # cut after a sentence, nothing lost


def test_tables_from_csv_tsv_and_json():
    p = read("a.csv", "姓名;年龄\n甲;30\n乙;41\n\n".encode("gb18030"))  # a semicolon sniffed, a blank row dropped
    assert p.kind == "table" and p.columns == ["姓名", "年龄"] and p.rows == [["甲", "30"], ["乙", "41"]]
    p = read("a.tsv", "药\t剂量\t\n柴胡\t12g\n".encode())
    assert p.columns == ["药", "剂量", "列3"] and p.rows == [["柴胡", "12g", ""]]  # a head left blank is named
    p = read("dup.csv", "年龄,年龄\n1,2\n".encode())
    assert p.columns == ["年龄", "年龄_2"]
    p = read("r.json", json.dumps([{"药": "柴胡", "味": ["苦", "辛"]}, {"药": "黄芩"}], ensure_ascii=False).encode())
    assert p.columns == ["药", "味"] and p.rows == [["柴胡", "苦、辛"], ["黄芩", ""]]
    p = read("t.json", json.dumps({"columns": [{"key": "a", "label": "甲"}], "rows": [{"a": 1}]}).encode())
    assert p.columns == ["甲"] and p.rows == [["1"]]
    assert read("x.json", json.dumps({"text": "一段话"}).encode()).kind == "text"
    with pytest.raises(Unreadable, match="JSON"):
        read("x.json", b"{oops")


def test_excel_workbooks_with_shared_and_inline_strings_and_dates():
    book = xlsx([["姓名", "就诊日期", "年龄", "处方"], ["张三", 45200, 30, "柴胡12g 黄芩9g"], ["李四", 45231.5, 41.5, "麻黄9g"]],
                date_columns=(1,), sheets=2)
    p = read("门诊.xlsx", book)
    assert p.columns == ["姓名", "就诊日期", "年龄", "处方"]
    assert p.rows == [["张三", "2023-10-01", "30", "柴胡12g 黄芩9g"], ["李四", "2023-11-01 12:00", "41.5", "麻黄9g"]]
    assert p.notes and "2 个工作表" in p.notes[0]
    p = read("b.xlsx", xlsx([["日期", "x"], [0, 1]], date_columns=(0,), date1904=True, inline=True))
    assert p.rows == [["1904-01-01", "1"]]  # the 1904 date system, inline strings


def test_word_documents_with_tables():
    p = read("病案.docx", docx(["主诉：咳嗽三日。", "处方：麻黄9g 杏仁9g"], [["药", "剂量"], ["甘草", "6g"]]))
    assert p.kind == "text" and "主诉：咳嗽三日。" in p.text and "药\t剂量\n甘草\t6g" in p.text


def test_what_cannot_be_read_says_why():
    for name, data, said in (("a.xls", b"\xd0\xcf\x11\xe0", "另存为 .xlsx"), ("a.doc", b"\xd0\xcf", "另存为 .docx"),
                             ("a.pdf", b"%PDF-1.4", "导出为 .txt"), ("a.csv", b"   \n", "空"), ("a.xlsx", b"PK\x03\x04junk", "损坏"),
                             ("a.docx", xlsx([["a"], ["1"]]), "不是 Word"), ("a.csv", b"a,b\n", "只有表头")):
        with pytest.raises(Unreadable, match=said):
            read(name, data)
    with pytest.raises(Unreadable, match="过大"):
        read("big.txt", b"x" * (MAX_BYTES + 1))


# ------------------------------------------------------------------ de-identification
def test_identifiers_are_taken_out_of_free_text():
    counts: dict[str, int] = {}
    text = ("患者：王小明，身份证号 11010519491231002X，电话 138-0013-8000 或 (010)62345678，邮箱 wxm@example.com，"
            "住院号：ZY20230001。处方：柴胡12g。")
    out = deid.mask_text(text, counts)
    assert "王小明" not in out and "11010519491231002X" not in out and "13800138000" not in out.replace("-", "")
    assert "62345678" not in out and "wxm@example.com" not in out and "ZY20230001" not in out
    assert "处方：柴胡12g" in out and "患者：〔姓名〕" in out
    assert counts == {"身份证号": 1, "手机号": 1, "电话": 1, "邮箱": 1, "编号": 1, "姓名": 1}
    assert deid.mask_text("柴胡12g，黄芩9g，2023年10月1日复诊", {}) == "柴胡12g，黄芩9g，2023年10月1日复诊"  # doses, dates stay


def test_a_tables_columns_by_what_they_hold():
    assert [deid.column_rule(h) for h in ("姓名", "患者姓名", "患者年龄", "方剂名称", "医生", "主治医师", "手机", "家庭住址",
                                          "出生日期", "病历号", "诊断")] == \
        ["person", "person", None, None, "staff", "staff", "contact", "contact", "birth", "identifier", None]
    rows, report = deid.table(["姓名", "医生", "电话", "出生日期", "病历号", "主诉"],
                              [["张三", "李医生", "13800138000", "1990-05-01", "A123", "咳嗽，电话13900139000"],
                               ["王五", "李医生", "", "1985年3月", "A124", "发热"], ["张三", "赵医生", "", "", "A123", ""]])
    assert [r[:5] for r in rows] == [["P0001", "D0001", "", "1990", "ID0001"], ["P0002", "D0001", "", "1985", "ID0002"],
                                     ["P0001", "D0002", "", "", "ID0001"]]  # the same person, the same pseudonym
    assert rows[0][5] == "咳嗽，电话〔手机号〕" and report["masked"] == {"手机号": 1}
    assert report["columns"] == {"姓名": "以化名代替（P0001…）", "医生": "以化名代替（D0001…）", "电话": "已删除",
                                 "出生日期": "只留出生年份", "病历号": "以编号代替（ID0001…）"}


# ------------------------------------------------------------------ the store
def test_column_types_and_numbers():
    assert [number(x) for x in ("1,234.5", "12%", "-3", "12g", "")] == [1234.5, 12.0, -3.0, None, None]
    rows = [[str(i), f"2023-01-{i + 1:02d}", "男女"[i % 2], f"第{i}条很长的自由文本" * 3] for i in range(20)]
    assert column_types(["n", "d", "c", "t"], rows) == {"n": "number", "d": "date", "c": "category", "t": "text"}
    assert column_types(["x"], [[""], [""]]) == {"x": "empty"}


def test_the_store_keeps_datasets_citable_and_gives_them_back(reader):
    ud = UserData(normalize=lambda t: t.replace("黃", "黄"), detect=reader.looks_like)
    ds = ud.add("门诊.csv", clinic(30))
    assert ds.kind == "table" and len(ds.rows) == 30 and ds.types["处方"] == "prescription" and ds.types["年龄"] == "number"
    assert ds.rows[0][:5] == ["P0001", "", "ID0001", "1990", "D0001"] and "张0" not in json.dumps(ds.rows, ensure_ascii=False)
    note = ud.add("笔记.txt", "黃芩苦寒。\n\n患者：王小明，咳嗽。".encode())
    assert note.passages == ["黄芩苦寒。".replace("黄", "黃"), "患者：〔姓名〕，咳嗽。"] and note.deid["masked"] == {"姓名": 1}
    assert ud.get("门诊") is ds and ud.get(ds.id) is ds
    card = ud.card(f"mine:{ds.id}.r2")
    assert card["locator"] == "第 2 行" and card["title"] == "门诊.csv" and card["mine"] and "姓名：P0002" in card["text"]
    assert ud.card(f"mine:{note.id}.1")["text"] == "黃芩苦寒。"
    found = ud.search("黄芩")  # each dataset, after the domain's folding
    assert {h["passage_id"].split(".")[0] for h in found["hits"]} == {f"mine:{ds.id}", f"mine:{note.id}"}
    page = ud.read(ds.id, start=3, limit=2, columns=["诊断", "处方"])
    assert [r["passage_id"] for r in page["rows"]] == [f"mine:{ds.id}.r3", f"mine:{ds.id}.r4"] and set(page["rows"][0]) == {"passage_id", "诊断", "处方"}
    for bad in (f"mine:{ds.id}.r31", f"mine:{ds.id}.2", "mine:nothing.r1", "shl.1"):
        with pytest.raises(NotFound):
            ud.part(bad)
    with pytest.raises(NotFound, match="没有列「血压」"):
        ds.column("血压")
    kept = json.loads(json.dumps(ud.export(ds.id), ensure_ascii=False))  # as the browser keeps it
    fresh = UserData()
    again = fresh.restore(kept)
    assert again.rows == ds.rows and again.types == ds.types and again.id == ds.id
    assert ud.remove(ds.id) and ud.list()[0]["id"] == note.id and ud.clear() == 1 and ud.list() == []
    with pytest.raises(NotFound, match="还没有上传资料"):
        ud.search("x")
    many = UserData()
    for i in range(MAX_DATASETS):
        many.add(f"{i}.txt", f"第{i}份".encode())
    with pytest.raises(Unreadable, match="至多"):
        many.add("more.txt", b"x")


# ------------------------------------------------------------------ statistics
def test_the_tests_the_analyses_use():
    assert round(fisher_exact_two_sided(3, 1, 1, 3), 4) == 0.4857  # the lady tasting tea
    assert round(fisher_exact_two_sided(8, 2, 1, 5), 4) == 0.035 and round(fisher_exact_two_sided(0, 5, 5, 0), 5) == 0.00794
    t = chi_square_independence([[10, 20], [20, 10]])
    assert t["chi2"] == 6.667 and t["df"] == 1 and round(t["p"], 5) == 0.00982 and t["cramers_v"] == 0.3333
    assert chi_square_independence([[3, 0], [0, 0]]) is None  # one row and one column with counts
    m, sd = mean_sd([2, 4, 4, 4, 5, 5, 7, 9])
    assert m == 5 and round(sd, 4) == 2.1381


def test_describe_and_compare_a_table(reader):
    ud = UserData(detect=reader.looks_like)
    ds = ud.add("门诊.csv", clinic(60))
    d = analysis.describe(ds)
    age = next(v for v in d["variables"] if v["column"] == "年龄")
    ages = [float(x) for x in ds.values("年龄")]
    assert age["n"] == 60 and age["mean"] == round(sum(ages) / 60, 4) and age["min"] == min(ages)
    assert next(v for v in d["variables"] if v["column"] == "处方")["hint"].startswith("处方列")
    numeric, categorical = d["tables"]
    assert numeric["id"] == "mine-numeric" and [r["v"] for r in numeric["rows"]] == ["出生日期", "年龄"]  # a birth date: its year
    assert {r["v"] for r in categorical["rows"] if r["v"]} >= {"性别", "诊断", "疗效"}
    assert all(c["source"] == "道乃久（TaoChronos）· 用户资料（本机分析）" for c in d["charts"] + d["tables"])
    assert not any("门诊.csv" in json.dumps(x, ensure_ascii=False) for x in d["charts"] + d["tables"])  # a figure leaves the page
    r = analysis.compare(ds, "年龄", "诊断")
    assert r["kind"] == "numeric by group" and r["test"]["name"] == "Kruskal–Wallis" and r["test"]["p"] < 0.001
    assert [g["group"] for g in r["groups"]] == ["感冒", "咳嗽", "腹痛"] and r["charts"][0]["type"] == "box"
    r = analysis.compare(ds, "疗效", "诊断")
    assert r["kind"] == "categorical by group" and r["test"]["name"] == "Pearson chi-square" and r["charts"][0]["type"] == "stack"
    r = analysis.compare(ds, "疗效", "性别")  # 2 × 2
    assert r["test"]["name"] in ("Pearson chi-square", "Fisher")
    small = ud.add("小.csv", "组,结局\n甲,是\n甲,是\n甲,是\n乙,否\n乙,否\n乙,是\n".encode())
    r = analysis.compare(small, "结局", "组")
    assert r["test"] == {"name": "Fisher", "p": pytest.approx(0.4, abs=1e-9)}  # expected counts under 5
    two = ud.add("相关.csv", "\n".join(["x,y"] + [f"{i},{i * 2 + (i % 3)}" for i in range(30)]).encode())
    r = analysis.compare(two, "y", "x")
    assert r["kind"] == "correlation" and r["test"]["rho"] > 0.95 and r["charts"][0]["fit"]
    with pytest.raises(ValueError, match="文本资料"):
        analysis.describe(ud.add("t.txt", "一段话".encode()))


# ------------------------------------------------------------------ prescriptions
def test_a_prescription_read_as_it_is_written(reader):
    def drugs(text, merge="written"):
        items, unknown = reader.parse(text, merge)
        return [(i["name"], i["dose"], i["grams"]) for i in items], unknown

    assert drugs("柴胡12g 黄芩9g 半夏9g 党参15g 甘草6g") == (
        [("柴胡", "12g", 12.0), ("黄芩", "9g", 9.0), ("半夏", "9g", 9.0), ("党参", "15g", 15.0), ("甘草", "6g", 6.0)], ["党参"])
    assert drugs("桂枝三两，芍药三两，甘草二两（炙），生姜三两，大枣十二枚")[0] == [
        ("桂枝", "三两", None), ("芍药", "三两", None), ("甘草", "二两", None), ("生姜", "三两", None), ("大枣", "十二枚", None)]
    assert drugs("柴胡、黄芩各9g，白芍 10g，赤芍10g 甘草 6 g")[0] == [
        ("柴胡", "9g", 9.0), ("黄芩", "9g", 9.0), ("白芍", "10g", 10.0), ("赤芍", "10g", 10.0), ("甘草", "6g", 6.0)]
    assert drugs("柴胡、黄芩各9g，白芍 10g，赤芍10g", "family")[0] == [
        ("柴胡", "9g", 9.0), ("黄芩", "9g", 9.0), ("芍药", "10g+10g", 20.0)]  # as the classics: one family, its grams added
    assert drugs("麻黄9克 杏仁9克 炙甘草6克 生石膏30克(先煎) 每日1剂 分2次服 年龄45岁")[0] == [
        ("麻黄", "9克", 9.0), ("杏仁", "9克", 9.0), ("炙甘草", "6克", 6.0), ("生石膏", "30克", 30.0)]
    # a name the lexicon has only in part keeps the character before it — not a word that introduces it, nor a unit
    assert drugs("夜交藤15g 川牛膝10g，加柴胡10g 石膏一斤知母六两")[0] == [
        ("夜交藤", "15g", 15.0), ("川牛膝", "10g", 10.0), ("柴胡", "10g", 10.0), ("石膏", "一斤", None), ("知母", "六两", None)]
    assert [n for n, _, _ in drugs("夜交藤15g 川牛膝10g 生石膏30g", "family")[0]] == ["何首乌", "牛膝", "石膏"]
    assert drugs("党参十五克 桂枝去皮三两")[0] == [("党参", "十五克", 15.0), ("桂枝", "三两", None)]
    assert reader.looks_like(["柴胡12g 黄芩9g", "麻黄 杏仁 甘草", "桂枝汤"]) == "prescription"
    assert reader.looks_like(["咳嗽三日", "发热", "头痛"]) is None


def test_prescriptions_analysed_and_set_beside_the_classics(reader):
    ud = UserData(detect=reader.looks_like)
    ds = ud.add("门诊.csv", clinic(60))
    r = reader.analyse(ds, group="诊断")
    assert r["column"] == "处方" and r["prescriptions"] == 60 and r["merge"] == "written"
    top = {f["drug"]: f["prescriptions"] for f in r["frequency"]}
    assert top["甘草"] == sum("甘草" in rx for rx in ds.values("处方")) and "白芍" in top and "芍药" not in top
    assert {u["name"] for u in r["unrecognised"]} == {"党参"}
    doses = {d["drug"]: d for d in r["doses_g"]}
    assert doses["甘草"]["min"] >= 6 and doses["甘草"]["max"] <= 12
    pairs = {p["pair"] for p in r["pairs"]}
    assert {"麻黄—杏仁", "杏仁—麻黄"} & pairs and r["pairs_significant"] >= 3
    assert r["groups"]["test"].startswith("Pearson") and any(d["drug"] == "麻黄" and d["significant"] for d in r["groups"]["drugs"])
    nearest = {n["formula"] for n in r["classics"]["nearest"]}
    assert {"小柴胡汤", "桂枝汤"} <= nearest  # 感冒's 柴胡…大枣 and 腹痛's 桂枝 白芍 甘草 生姜 大枣
    match = next(m for m in r["classics"]["matches"] if m["formula"] == "桂枝汤")
    assert match["passage_id"].startswith(f"mine:{ds.id}.r") and match["jaccard"] >= 0.2 and match["witness"]["title"]
    witness = reader.s.passages([match["witness"]["passage_id"]])[0]  # the composition, to read in the classic
    assert "桂枝" in witness.text and match["witness"]["year"] is not None
    ids = {c["id"] for c in r["charts"]} | {t["id"] for t in r["tables"]}
    assert {"mine-rx-frequency", "mine-rx-doses", "mine-rx-pairs", "mine-rx-groups", "mine-rx-classics", "mine-rx-tree"} <= ids
    fam = reader.analyse(ds, merge="family", classics=False)
    assert "芍药" in {f["drug"] for f in fam["frequency"]} and "classics" not in fam and "groups" not in fam
    with pytest.raises(ValueError, match="merge"):
        reader.analyse(ds, merge="other")
    few = ud.add("少.csv", "处方\n柴胡12g 黄芩9g\n".encode())
    with pytest.raises(ValueError, match="只有 1 张"):
        reader.analyse(few, "处方")


# ------------------------------------------------------------------ the chat runtime and its tools
@pytest.fixture(scope="module")
def runtime(tmp_path_factory) -> ChatRuntime:
    return ChatRuntime.create("full-discovery", kind="test", ephemeral=True, data_dir=tmp_path_factory.mktemp("mine"))


def test_the_runtime_offers_the_tools_while_the_page_holds_data(runtime):
    runtime.data_clear()
    cat = runtime.catalog("core")
    assert sorted(t["tool"] for t in cat["mydata"]) == ["mydata.compare", "mydata.describe", "mydata.list", "mydata.prescriptions",
                                                       "mydata.read", "mydata.search"]
    assert not any(t["tool"].startswith("mydata.") for t in cat["tools"])  # offered by the page, while there is data
    assert {t["tool"] for t in runtime.catalog("all")["tools"]} >= {"mydata.prescriptions"}
    assert runtime.info()["mydata"]["prescriptions"] is True and ".xlsx" in runtime.info()["mydata"]["accepted"]
    out = runtime.data_add("门诊.xlsx", xlsx([l.split(",") for l in clinic(30).decode().splitlines()]))
    assert out["ok"] and out["dataset"]["rows"] == 30
    ds = out["dataset"]["id"]
    listed = runtime.call("mydata.list", {})
    assert listed["ok"] and ds in listed["text"] and "张0" not in listed["text"]
    rx = runtime.call("mydata__prescriptions", {"group": "诊断"})
    assert rx["ok"] and rx["result"]["charts"] and rx["result"]["tables"]
    assert "charts_shown" in rx["text"] and '"rows":' not in rx["text"]  # the model reads the numbers, not the tables
    cites = {c["passage_id"]: c for c in rx["citations"]}
    row = cites[f"mine:{ds}.r1"]
    assert row["title"] == "门诊.xlsx" and row["locator"] == "第 1 行" and row["dynasty"] == "我的资料"  # as the page names it
    via = runtime.call("taochronos_call", {"tool": "mydata.compare", "arguments": {"outcome": "年龄", "group": "诊断"}})
    assert via["ok"] and via["result"]["test"]["name"] == "Kruskal–Wallis"
    assert runtime.passage(f"mine:{ds}.r2")["ok"] and not runtime.passage(f"mine:{ds}.r99")["ok"]
    bad = runtime.call("mydata.compare", {"outcome": "血压", "group": "诊断"})
    assert not bad["ok"] and "没有列「血压」" in bad["error"] and "KeyError" not in bad["error"]
    assert runtime.data_add("x.xls", b"\xd0\xcf\x11\xe0") == {"ok": False, "error": "不能直接读取 .xls 文件：请在 Excel 中另存为 .xlsx 或 .csv"}
    kept = runtime.data_export(ds)
    assert runtime.data_remove(ds)["ok"] and runtime.data_list()["datasets"] == []
    assert runtime.data_restore(kept)["dataset"]["id"] == ds and runtime.data_clear() == {"ok": True, "removed": 1}
    empty = runtime.call("mydata.describe", {})
    assert not empty["ok"] and "还没有上传资料" in empty["error"]


def test_only_the_conversation_reads_the_users_data(runtime):
    """A research agent's actor, or any actor without the chat's grant, cannot call the 我的资料 tools."""
    runtime.data_add("a.csv", "x,y\n1,2\n3,4\n5,6\n7,8\n".encode())
    agent = Actor(id="agent:researcher", role="researcher", principal="agent", permissions=frozenset({"classics:read", "analysis:run"}))
    out = runtime.h.scheduler.execute(ToolCall("mydata.list", {}), actor=agent)
    assert not out.ok and "mydata:read" in (out.error or "")
    assert runtime.h.scheduler.execute(ToolCall("mydata.list", {}), actor=runtime.actor).ok
    runtime.data_clear()


def test_the_page_keeps_tables_whole():
    """A table the page prints is passed whole; only what the model reads is cut (the mesh's _brief)."""
    from taochronos.tools.mesh import _brief

    table = {"id": "t", "rows": [{"a": str(i)} for i in range(40)]}
    out = _brief({"tables": [table], "charts": [{"rows": list(range(50))}], "items": list(range(40))})
    assert out["tables"][0]["rows"] == table["rows"] and len(out["charts"][0]["rows"]) == 50 and out["items"][-1] == {"omitted": 28}


# ------------------------------------------------------------------ where the data goes
def _post(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — the test's own server
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_a_server_on_this_machine_takes_the_data_one_elsewhere_refuses_it(runtime):
    from taochronos.chat.server import ChatServer

    srv = ChatServer(("127.0.0.1", 0), runtime, web_root=None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        status, out = _post(f"{base}/api/data", {"name": "门诊.csv", "data": base64.b64encode(clinic(12)).decode()})
        assert status == 200 and out["ok"] and out["dataset"]["rows"] == 12
        with urllib.request.urlopen(f"{base}/api/data", timeout=30) as r:  # noqa: S310
            assert [d["id"] for d in json.loads(r.read())["datasets"]] == [out["dataset"]["id"]]
        assert _post(f"{base}/api/data", {"name": "a.csv", "data": "%%%"})[0] == 400
        assert _post(f"{base}/api/data/remove", {"id": out["dataset"]["id"]})[1]["ok"]
        assert _post(f"{base}/api/data/clear", {})[1] == {"ok": True, "removed": 0}
    finally:
        srv.shutdown()
        srv.server_close()
    shared = ChatServer(("0.0.0.0", 0), runtime, web_root=None, token="t0k")
    threading.Thread(target=shared.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{shared.server_address[1]}/api/data", method="POST",
                                     data=json.dumps({"name": "a.csv", "data": base64.b64encode(b"x,y\n1,2\n").decode()}).encode(),
                                     headers={"Content-Type": "application/json", "X-TC-Token": "t0k"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=30)  # noqa: S310
        assert err.value.code == 403 and "其他机器" in json.loads(err.value.read())["error"]
        assert runtime.data_list()["datasets"] == []
    finally:
        shared.shutdown()
        shared.server_close()


def test_the_browser_workers_python_keeps_and_gives_back_the_data(tmp_path):
    """The Python the browser's worker runs (web/js/worker.js, BOOT): a file it was handed, its export kept as JSON and
    given back, the way the worker writes it, at the next visit."""
    source = (HOME / "web" / "js" / "worker.js").read_text(encoding="utf-8")
    boot = re.search(r"const BOOT = `(.*?)`;", source, re.S).group(1).replace("/home/pyodide/data", str(tmp_path / "data"))
    space: dict = {"_profile": "full-discovery"}
    exec(boot, space)  # noqa: S102 — the repository's own code
    rpc = lambda method, params="{}": json.loads(space["_rpc"](method, params))  # noqa: E731
    upload = tmp_path / "mydata-1"
    upload.write_bytes(clinic(9))
    out = rpc("data_add", json.dumps({"name": "门诊.csv", "path": str(upload)}))
    assert out["ok"] and out["dataset"]["rows"] == 9
    kept = space["_rpc"]("data_export", json.dumps({"id": out["dataset"]["id"]}))  # the string IndexedDB keeps
    assert rpc("data_clear")["removed"] == 1 and rpc("data_list")["datasets"] == []
    assert rpc("data_restore", f'{{"data":{kept}}}')["ok"]  # as restoreData() builds the call, without parsing it again
    assert [d["id"] for d in rpc("data_list")["datasets"]] == [out["dataset"]["id"]]
    assert rpc("data_remove", json.dumps({"id": out["dataset"]["id"]}))["ok"]
    assert not rpc("data_restore", '{"data":{"v":1}}')["ok"]  # a dataset an older page kept in another form: dropped
