"""The alias layer (ADR 0023): the record file, its defaults and order, and the index's loader."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field

import pytest

from taochronos.plugins.classics.aliases import (
    CONTEXT_PATTERNS,
    DEFAULT_ALIAS,
    FORMAT,
    KINDS,
    STATUSES,
    VERSION,
    AliasIndex,
    AliasRecord,
    Expansion,
    Referent,
    Witness,
    assemble,
    dumps_records,
    gate_form,
    loads_records,
    meets,
    overlaps,
    write_records,
)
from taochronos.plugins.classics.domain import Lexicon, Terminology
from taochronos.plugins.classics.store import is_han


def sample() -> list[AliasRecord]:
    """Synthetic records with every field set somewhere."""
    return [
        AliasRecord("国老", n=12, sh=0.67, r=[Referent("甘草", t="herb:甘草", src=["bielu-jc", "curated"], w=[
            Witness("shanghan_zhige.00012", 1180, 1180, "e", True), Witness("jc_c030.00217", 1568, 1568, "l")])]),
        AliasRecord("将军", n=116, sh=0.04, b=["大将军", "将军之官"], r=[
            Referent("大黄", st="cue", c=["大黄", "锦纹", "川军", "荡涤", "承气"], src=["curated"]),
            Referent("硫黄", st="candidate", src=["bielu-jc"])]),
        AliasRecord("通草", raw=["通草", "通艸"], b=[("通草汤", None, 960)], r=[
            Referent("木通", k="old_name", v=(None, 960), src=["curated"]),
            Referent("通脱木", v=(960, None), src=["curated"])]),
        AliasRecord("山药", fl=1063, flb="taboo:yingzong", ho="山药"),
        AliasRecord("薯蓣", r=[Referent("山药", k="taboo_rename", src=["taboo"])]),
        AliasRecord("小便", stop=True, n=5855, sh=0.04),
        AliasRecord("鬼督邮", r=[
            Referent("徐长卿", st="cue", a=["赤箭"], src=["bielu-jc"]),
            Referent("天麻", g="赤箭", st="cue", cr=("本经", 25, 220), nt="赤箭天麻", src=["shiming"])]),
    ]


META = {"store": {"sha": "abc", "books": 553, "passages": 168278}, "normalizer": "e5cf04a507c3"}


def lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines()]


def test_records_survive_a_round_trip_byte_for_byte():
    text = dumps_records(sample(), META)
    header, records = loads_records(text)
    assert records == sorted(sample(), key=lambda r: r.s)
    assert dumps_records(records, META) == text
    assert header["store"] == META["store"] and header["format"] == FORMAT and header["version"] == VERSION


def test_defaults_are_left_out_on_writing_and_restored_on_reading():
    minimal = AliasRecord("国老", r=[Referent("甘草", src=["bielu-jc"])])
    line = dumps_records([minimal]).splitlines()[1]
    assert line == '{"r":[{"h":"甘草","src":["bielu-jc"]}],"s":"国老"}'
    (rec,) = loads_records(line)[1]
    assert (rec.raw, rec.stop, rec.n, rec.sh, rec.b, rec.fl, rec.flb, rec.ho) == (
        ["国老"], False, 0, 0, [], None, None, None)
    (ref,) = rec.r
    assert (ref.g, ref.t, ref.k, ref.st, ref.v, ref.c, ref.a, ref.w, ref.cr, ref.nt) == (
        "甘草", None, "alias", "open", None, ["甘草"], [], [], None, "")
    # a window that bounds nothing is no window; what differs from a default is kept, even when empty
    other = AliasRecord("将军", b=[("大将军", None, None), ("将军之官", 1000, None)],
                        r=[Referent("大黄", g="川军", v=(None, None), c=[], src=[])])
    written = lines(dumps_records([other]))[1]
    assert written == {"s": "将军", "b": ["大将军", ["将军之官", 1000, None]],
                       "r": [{"h": "大黄", "g": "川军", "c": [], "src": []}]}
    assert loads_records(dumps_records([other]))[1][0].b == ["大将军", ("将军之官", 1000, None)]
    # the share is kept to two decimals
    assert lines(dumps_records([AliasRecord("国老", sh=0.6666)]))[1]["sh"] == 0.67


def test_the_header_counts_what_the_file_holds():
    header = lines(dumps_records(sample(), {**META, "counts": {"surfaces": 0}, "sources": ["ntu40k"]}))[0]
    assert list(header) == ["_header"]
    header = header["_header"]
    assert header["counts"] == {"surfaces": 7, "pairs": 8, "open": 4, "cue": 3, "candidate": 1, "stop": 1}
    assert header["sources"] == ["bielu-jc", "curated", "shiming", "taboo"]
    assert header["normalizer"] == META["normalizer"]


def test_writing_is_deterministic(tmp_path):
    text = dumps_records(sample(), META)
    shuffled = sample()
    random.Random(23).shuffle(shuffled)
    assert dumps_records(shuffled, dict(reversed(list(META.items())))) == text
    rows = text.splitlines()
    assert [json.loads(r)["s"] for r in rows[1:]] == sorted(r.s for r in sample())  # code-point order
    for row in rows:
        assert row == json.dumps(json.loads(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    a = write_records(tmp_path / "a" / "aliases.jsonl", sample(), META).read_bytes()
    b = write_records(tmp_path / "b.jsonl", shuffled, META).read_bytes()
    assert a == b == text.encode("utf-8") and a.endswith(b"\n") and b"\r" not in a
    with pytest.raises(ValueError, match="duplicate"):
        dumps_records([AliasRecord("国老"), AliasRecord("国老")])


def write_lines(path, *objs):
    path.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs), encoding="utf-8")
    return path


def test_unusable_records_are_skipped_and_counted(tmp_path):
    first = write_lines(
        tmp_path / "a.jsonl",
        {"_header": {"format": FORMAT, "version": VERSION, "sources": ["bielu-jc", "curated"]}},
        {"s": "国老", "r": [{"h": "甘草", "src": ["bielu-jc"]}, {"h": "甘草", "k": "nickname", "src": ["hurb"]}]},
        {"s": "干葛", "r": [{"h": "葛根", "k": "nickname", "src": ["hurb"]}]},  # loses every referent: dropped
        {"s": "白虎", "ho": "白虎", "r": [{"h": "石膏", "st": "maybe", "src": ["hurb"]}]},  # a head still: kept
        {"s": "黄蘗", "r": [{"h": "", "src": ["hurb"]}, {"h": "黄柏", "k": "spelling", "src": ["curated"]}]},
        {"s": "葛", "r": [{"h": "葛根", "src": ["bielu-jc"]}]},
        {"s": "铁KT", "r": [{"h": "铁", "src": ["bielu-jc"]}]},
        {"s": "  "},
        {"r": [{"h": "甘草", "src": ["bielu-jc"]}]},
    )
    second = write_lines(tmp_path / "b.jsonl", {"s": "国老", "r": [{"h": "黄芪", "src": ["ntu40k"]}]})
    index = AliasIndex.load([first, second])
    assert index.skipped == {"blank": 3, "one_char": 2, "duplicate": 1, "kind": 2, "status": 1}
    assert sorted(index.records) == ["国老", "白虎", "黄蘗"]
    assert [ref.h for ref in index.record("国老").r] == ["甘草"]  # the first file's record, its usable referent
    assert index.record("白虎").r == [] and index.record("白虎").ho == "白虎"
    assert [(ref.h, ref.k) for ref in index.record("黄蘗").r] == [("黄柏", "spelling")]
    assert index.sources == ["bielu-jc", "curated"]  # declared, and used by what was kept


def test_the_loader_and_the_empty_index(tmp_path):
    path = write_records(tmp_path / "aliases.jsonl", sample(), META)
    context = tmp_path / "context.json"
    context.write_text(json.dumps({"version": 1, "herbs": ["甘草", "大黄"]}), encoding="utf-8")
    index = AliasIndex.load([path], context=context)
    assert index.enabled and len(index) == 7 and index.max_len == 3
    assert index.record("国老").r[0].w[0] == Witness("shanghan_zhige.00012", 1180, 1180, "e", True)
    assert index.record("甘草") is None
    assert index.context["herbs"] == ["甘草", "大黄"]
    assert index.headers[0]["store"] == META["store"]
    assert index.sources == ["bielu-jc", "curated", "shiming", "taboo"]
    assert len(index.fingerprint) == 12 and index.fingerprint == AliasIndex.load([str(path)], context).fingerprint
    assert AliasIndex.load([path]).fingerprint != index.fingerprint  # the context is part of it
    changed = write_records(tmp_path / "changed.jsonl", sample()[1:], META)
    assert AliasIndex.load([changed], context).fingerprint != index.fingerprint
    assert AliasIndex.load([path], {"herbs": []}).context == {"herbs": []}
    for empty in (AliasIndex.empty(), AliasIndex.load([])):
        assert not empty.enabled and len(empty) == 0 and empty.max_len == 0 and empty.fingerprint == ""
        assert empty.record("国老") is None and empty.sources == [] and not any(empty.skipped.values())


@pytest.mark.parametrize("text,message", [
    ('{"_header":{"format":"other","version":1}}\n', "is not"),
    (f'{{"_header":{{"format":"{FORMAT}","version":{VERSION + 1}}}}}\n', "or older"),
    ('{"s":"国老"}\nnot json\n', ":2: not JSON"),
    ('["国老"]\n', ":1: not a record"),
    (f'{{"s":"国老"}}\n{{"_header":{{"format":"{FORMAT}","version":1}}}}\n', "a header after"),
    ('{"s":"国老","r":[{"h":"甘草","w":[["p",1,2,"e"]]}]}\n', ":1: malformed record"),
])
def test_another_format_or_a_damaged_line_is_refused(text, message):
    with pytest.raises(ValueError, match=message):
        loads_records(text)


def test_kinds_statuses_and_defaults():
    assert KINDS == {"alias": "异名", "taboo_rename": "避讳改名", "part_name": "药用部位名",
                     "processing_variant": "炮制/加工名", "abbreviation": "简称", "variety": "品种/产地名",
                     "spelling": "异写", "old_name": "古名", "folk": "俗名"}
    assert STATUSES == ("open", "cue", "candidate")
    assert DEFAULT_ALIAS["enabled"] is False and DEFAULT_ALIAS["share"] == [3, 10]
    assert (DEFAULT_ALIAS["expansions"], DEFAULT_ALIAS["mask_bits"], DEFAULT_ALIAS["asked_first"]) == (8, 30, "herbs")


def test_three_thousand_records_load_quickly(tmp_path):
    rng = random.Random(23)
    han = [chr(c) for c in range(0x4E00, 0x4E00 + 400)]
    surfaces = sorted({"".join(rng.sample(han, rng.choice((2, 3, 4)))) for _ in range(3400)})[:3000]
    records = [AliasRecord(s, n=rng.randrange(50), sh=rng.random(), b=[s + "汤"], r=[
        Referent(rng.choice(han) + rng.choice(han), st=rng.choice(STATUSES), src=["bielu-jc"],
                 w=[Witness(f"jc_c030.{i:05d}", 1568, 1568, "l", True)])]) for i, s in enumerate(surfaces)]
    path = write_records(tmp_path / "aliases.jsonl", records)
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        index = AliasIndex.load([path])
        best = min(best, time.perf_counter() - start)
    assert len(index) == 3000 and best < 0.1


# --------------------------------------------------------------------------- the runtime index: gates and expansion
CONTEXT = {"version": 1, "herbs": ["芒硝", "厚朴", "枳实", "甘草", "人参", "黄芩"], **CONTEXT_PATTERNS}


def layer() -> AliasIndex:
    """A synthetic layer with the investigation's cases."""
    a = Referent
    return AliasIndex([
        AliasRecord("大黄", ho="大黄", n=900),
        AliasRecord("将军", n=116, b=["大将军", "将军之官"], r=[
            a("大黄", st="cue", c=["大黄", "锦纹", "川军", "荡涤", "承气"], src=["curated"]),
            a("石硫黄", st="candidate", src=["bielu-jc"])]),
        AliasRecord("黄良", n=30, r=[a("大黄", src=["bielu-jc"])]),
        AliasRecord("火参", n=5, r=[a("大黄", src=["bielu-jc"])]),
        AliasRecord("肤如", r=[a("大黄", src=["bielu-jc"])]),
        AliasRecord("锦纹", n=40, r=[a("大黄", st="cue", src=["bielu-jc"])]),
        AliasRecord("川军", n=12, r=[a("大黄", st="candidate", src=["bielu-jc"])]),
        AliasRecord("人参", ho="人参", n=5000),
        AliasRecord("何首乌", ho="何首乌", n=300),
        AliasRecord("地精", n=40, b=["天地精", "道地精"], r=[a("人参", st="cue", src=["bielu-jc"]),
                                                             a("何首乌", st="cue", src=["bielu-jc"])]),
        AliasRecord("交藤", n=20, r=[a("何首乌", src=["bielu-jc"])]),
        AliasRecord("夜合", n=60, r=[a("何首乌", st="cue", src=["bielu-jc"]), a("合欢", st="cue", src=["bielu-jc"])]),
        AliasRecord("合欢", ho="合欢", n=200),
        AliasRecord("合昏", n=10, r=[a("合欢", src=["bielu-jc"])]),
        AliasRecord("甘草", ho="甘草", n=9000),
        AliasRecord("国老", n=12, r=[a("甘草", t="herb:甘草", src=["bielu-jc", "curated"], w=[
            Witness("qianjin.00012", 652, 652, "e"), Witness("jc_c030.00217", 1568, 1568, "l", True)])]),
        AliasRecord("蜜甘", n=8, b=["石蜜甘"], r=[a("甘草", src=["bielu-jc"])]),
        AliasRecord("美草", n=25, r=[a("甘草", st="cue", src=["bielu-jc"]), a("旋花", st="cue", src=["lexicon"])]),
        AliasRecord("旋花", ho="旋花", n=50),
        AliasRecord("筋根花", n=3, r=[a("旋花", src=["bielu-jc"])]),
        AliasRecord("木香", ho="木香", n=400, b=[("青木香", 1100, None)]),
        AliasRecord("青木香", n=80, r=[a("木香", v=(None, 1100), src=["curated"]),
                                     a("马兜铃", k="part_name", v=(1100, None), src=["curated"])]),
        AliasRecord("马兜铃", ho="马兜铃", n=150),
        AliasRecord("通草", n=300, r=[a("木通", k="old_name", v=(None, 960), src=["curated"]),
                                    a("通脱木", v=(960, None), src=["curated"])]),
        AliasRecord("木通", ho="木通", n=500),
        AliasRecord("通脱木", ho="通脱木", n=40),
        AliasRecord("黄柏", ho="黄柏", n=700),
        AliasRecord("黄蘗", n=90, r=[a("黄柏", k="spelling", src=["curated"])]),
        AliasRecord("檗木", n=20, r=[a("黄柏", k="spelling", src=["curated"])]),
        AliasRecord("山药", ho="山药", n=800, fl=1063, flb="taboo:yingzong"),
        AliasRecord("薯蓣", n=600, r=[a("山药", k="taboo_rename", src=["taboo"])]),
        AliasRecord("小便", stop=True, n=5855, sh=0.04),
    ], context=CONTEXT)


def lexicon(tmp_path, herbs: dict[str, list[str]]) -> Lexicon:
    """A herb lexicon: term → synonyms (JSON is YAML)."""
    path = tmp_path / f"herbs-{len(list(tmp_path.iterdir()))}.yaml"
    entries = [{"term": t, "synonyms": [{"surface": s} for s in syns]} for t, syns in herbs.items()]
    path.write_text(json.dumps({"category": "herb", "entries": entries}, ensure_ascii=False), encoding="utf-8")
    return Lexicon([path])


@dataclass
class Query:
    """What the expansion reads of a ``ParsedQuery``."""

    asked: dict[str, str | None]
    surfaces: dict[str, list[str]] = field(default_factory=dict)
    quoted: list[str] = field(default_factory=list)
    groups: dict[str, list[list[str]]] = field(default_factory=dict)
    after: int | None = None
    before: int | None = None

    def all_surfaces(self) -> list[str]:
        return list(dict.fromkeys([f for forms in self.surfaces.values() for f in forms] + self.quoted))


def ask(lex: Lexicon | None, *names: str, after: int | None = None, before: int | None = None) -> Query:
    """A query asking ``names`` as the analyzer puts it: lexicon herbs with their forms, other names quoted."""
    q = Query({}, after=after, before=before)
    for s in names:
        entry = lex.resolve(s, "herb") if lex is not None else None
        q.asked[s] = entry.term_id if entry is not None else None
        if entry is not None:
            q.surfaces[entry.term_id] = entry.surfaces()
        else:
            q.quoted.append(s)
    return q


def plan(index: AliasIndex, q: Query, lex: Lexicon | None = None, **cfg) -> list[tuple]:
    return [(e.surface, e.direction[0], e.searched, e.why) for e in index.expansions(q, lex, cfg)]


def test_gate_form_keeps_han_and_ascii_and_breaks_the_rest():
    assert gate_form("大黄（酒洗）二两，芒硝 各半两。A1") == "大黄|酒洗|二两|芒硝|各半两|A1"
    probe = ("\u33ff\u3400\u9fff\ua000\uf8ff\uf900\ufaff\ufb00\U0001ffff\U00020000\U0003134f\U00031350"
             "〇〓、Ａ１az09_ \n\t|·")
    assert gate_form(probe) == "".join(c if is_han(c) or (c.isascii() and c.isalnum()) else "|" for c in probe)
    assert len(gate_form(probe)) == len(probe) and gate_form("") == ""


def test_scan_takes_the_longest_name_left_to_right_and_skips_stop_names():
    index = layer()
    assert index.scan("大将军与将军") == [(1, 3, "将军"), (4, 6, "将军")]
    assert index.scan("青木香木香") == [(0, 3, "青木香"), (3, 5, "木香")]  # 青木香 before the 木香 inside it
    assert index.scan("小便不利，用甘草") == [(6, 8, "甘草")]  # a stop name is no name; a head is one
    assert index.scan("国老蜜甘草") == [(0, 2, "国老"), (2, 4, "蜜甘")]  # left to right: 蜜甘 before 甘草
    assert AliasIndex.empty().scan("国老") == []


def test_groups_and_names():
    index = layer()
    assert [s for s, _ in index.by_group("大黄")] == ["将军", "川军", "火参", "肤如", "锦纹", "黄良"]
    assert index.by_group("没有") == []
    assert index.groups_for("herb:甘草", []) == ["甘草"]  # by the lexicon's term id
    assert index.groups_for(None, ["何首乌", "地精", "夜合"]) == ["何首乌"]  # by head only: aliases are no group
    assert index.groups_for(None, ["通草", "木通", "通脱木"]) == ["木通", "通脱木"]
    # names that tell a group apart: heads and its own aliases, never a shared name or a candidate
    assert index.names("大黄") == ["大黄", "火参", "肤如", "锦纹", "黄良"]
    assert index.names("何首乌") == ["交藤", "何首乌"] and index.names("旋花") == ["旋花", "筋根花"]


def test_free_offsets_leave_out_the_name_inside_longer_strings():
    index = layer()
    rec = index.record
    g = gate_form("大将军出征，将军之官，谋虑出焉。将军二两")
    assert index.free_offsets(g, "将军", rec("将军").b, (None, None)) == [g.rindex("将军")]
    assert index.free_offsets(g, "将军", [], (None, None)) == [1, 6, 16]  # no blockers, every occurrence
    g = gate_form("天地精气，地精一名人参")
    assert index.free_offsets(g, "地精", rec("地精").b, (None, None)) == [5]
    g = gate_form("石蜜甘平无毒。蜜甘，甘草也")  # a straddle: 石蜜|甘 is not 蜜甘
    assert index.free_offsets(g, "蜜甘", rec("蜜甘").b, (None, None)) == [7]
    # 青木香 is 木香 until 1100: the blocker holds only for passages that may be later
    g = gate_form("青木香二两")
    assert index.free_offsets(g, "木香", rec("木香").b, (650, 700)) == [1]
    assert index.free_offsets(g, "木香", rec("木香").b, (1578, 1578)) == []
    assert index.free_offsets(g, "木香", rec("木香").b, (1000, 1200)) == []  # a range that reaches the window
    assert index.free_offsets(g, "木香", rec("木香").b, (None, None)) == []
    assert index.free_offsets(g, "将军", ["大将军"], (None, None)) == []  # absent
    assert index.free_offsets("将军将军", "将军", ["将军", "军"], (None, None)) == [0, 2]  # not longer: no blocker


@pytest.mark.parametrize("text,cues,expected", [
    ("将军二两，水煮", [], True),  # dose
    ("将军（炙）三两", [], True),  # dose after a note
    ("将军芒硝各三两", [], True),  # each
    ("将军（酒洗）", [], True),  # preparation
    ("将军洗净", [], False),  # a preparation needs its bracket
    ("大黄一名将军", [], True),  # name-of
    ("其味苦，荡涤肠胃，推陈致新，将军之性也", ["荡涤"], True),  # cue within 20
    ("荡涤肠胃，推陈致新，调中化食，安和五脏，此其所以号为将军", ["荡涤"], False),  # cue too far
    ("将军之性也", ["将军"], False),  # the name is no cue of itself
    ("芒硝、厚朴、将军、枳实", [], True),  # two herbs near: a list
    ("芒硝、将军出征", [], False),  # one herb only
    ("芒硝厚朴，以此十余字隔开之将军", [], False),  # herbs beyond 10
    ("君为将军，臣为谋主", [], False),
])
def test_drug_context(text, cues, expected):
    index = layer()
    g = gate_form(text)
    offs = index.free_offsets(g, "将军", [], (None, None))
    assert offs and index.drug_context(g, "将军", offs, cues) is expected


def test_drug_context_reads_its_windows_and_patterns_from_the_profile_and_the_context():
    g = gate_form("其味苦，荡涤肠胃，推陈致新，将军之性也")
    offs = [g.index("将军")]
    assert not layer().drug_context(g, "将军", offs, ["荡涤"], cfg={"cue_window": 5})
    bare = AliasIndex([AliasRecord("将军", r=[Referent("大黄")])])  # no context: the patterns, no herb set
    assert bare.drug_context(gate_form("将军二两"), "将军", [0], [])
    assert not bare.drug_context(gate_form("芒硝、厚朴、将军"), "将军", [6], [])


def test_accept_applies_the_four_gates_in_order():
    index = layer()
    exps = {e.surface: e for e in index.expansions(ask(None, "甘草"), None, {})}
    shared = exps["美草"]
    assert (shared.status, shared.shared, shared.own, shared.rivals) == (
        "cue", True, ["国老", "甘草", "蜜甘"], ["旋花", "筋根花"])

    def accept(text, e, yr=(None, None), **cfg):
        return index.accept(gate_form(text), e, yr, cfg=cfg)
    assert accept("美草二两，国老", shared) == (True, "ok")
    assert accept("美草之叶", exps["美草"]) == (False, "context")
    assert accept("美草二两", shared) == (False, "rival")  # no own name
    assert accept("旋花一名美草，国老", shared) == (False, "rival")  # a rival's name
    assert accept("美草二两，国老", shared, ablate=["gates"]) == (True, "ok")
    assert accept("美草之叶，国老", shared, ablate=["gates"]) == (True, "ok")
    assert accept("国老", shared) == (False, "absent")
    assert accept("石蜜甘平", exps["蜜甘"]) == (False, "boundary")
    assert accept("石蜜甘平", exps["蜜甘"], ablate=["boundary"]) == (True, "ok")
    (late,) = index.expansions(ask(None, "木通", before=907), None, {})  # 唐以前的木通: 通脱木 is no rival then
    assert (late.surface, late.valid, late.shared, late.rivals) == ("通草", (None, 960), False, [])
    (undated,) = index.expansions(ask(None, "木通"), None, {})
    assert (undated.shared, undated.own, undated.rivals) == (True, ["木通"], ["通脱木"])
    assert accept("通草", undated, (650, 700)) == (False, "rival")
    assert accept("通草", late, (650, 700)) == (True, "ok")
    assert accept("通草", late, (1578, 1578)) == (False, "period")
    assert accept("通草", late, (900, 1100)) == (True, "ok")  # the range may fall before 960
    assert accept("通草", late, (1578, 1578), ablate=["period"]) == (True, "ok")
    (late,) = index.expansions(ask(None, "马兜铃"), None, {})  # the rival 木香 inside 青木香 does not count
    assert (late.surface, late.shared, late.own, late.rivals) == ("青木香", True, ["马兜铃"], ["木香"])
    late.own = ["独行根"]
    assert accept("青木香，独行根也", late, (1578, 1578)) == (True, "ok")
    assert accept("青木香，独行根也，非木香", late, (1578, 1578)) == (False, "rival")
    candidate = Expansion("川军", "大黄", "drug→alias", "大黄", "大黄", status="candidate")
    assert accept("川军二两", candidate) == (False, "candidate")


TERMS = {"terms": [{"id": "鬼督邮", "senses": [
    {"id": "鬼督邮#徐长卿", "label": "徐长卿", "category": "herb", "period": [200, 700],
     "cues": ["徐长卿", "石下长卿"], "anti_cues": ["赤箭"]},
    {"id": "鬼督邮#天麻", "label": "天麻", "category": "herb", "period": [900, 1600],
     "cues": ["天麻", "赤箭", "定风草"]}]}]}


@pytest.mark.parametrize("text,year", [
    ("鬼督邮一名徐长卿，生泰山山谷", 1100), ("鬼督邮一名徐长卿，生泰山山谷", 650), ("鬼督邮，赤箭也，一名定风草", 650),
    ("鬼督邮生山谷", 1300), ("徐长卿即鬼督邮，与赤箭相似", 400), ("鬼督邮生山谷", 100), ("鬼督邮生山谷", None),
    ("鬼督邮，石下长卿也", 1900),
])
def test_reading_follows_the_terminology_formula(text, year):
    index = AliasIndex([AliasRecord("鬼督邮", r=[
        Referent("徐长卿", v=(200, 700), c=["徐长卿", "石下长卿"], a=["赤箭"]),
        Referent("天麻", g="赤箭", v=(900, 1600), c=["天麻", "赤箭", "定风草"])])])
    best, p, probs, _ = Terminology(TERMS, {}).resolve("鬼督邮", text, set(), year)
    ref, q = index.reading(gate_form(text), "鬼督邮", (year, year))
    assert q == p
    if p >= 0.5 and list(probs.values()).count(p) == 1:
        assert ref is not None and ref.h == best.split("#")[1]
    else:
        assert ref is None


def test_reading_counts_cues_near_a_free_occurrence_only():
    index = AliasIndex([AliasRecord("鬼督邮", b=["鬼督邮草"], r=[Referent("徐长卿"), Referent("天麻", c=["天麻", "赤箭"])])])
    near = "鬼督邮，赤箭也"
    assert index.reading(gate_form(near), "鬼督邮", (None, None))[0].h == "天麻"
    far = "鬼督邮。" + "此药生于山谷之中，" * 6 + "赤箭"
    assert index.reading(gate_form(far), "鬼督邮", (None, None)) == (None, 0.5)
    assert index.reading(gate_form("鬼督邮草，赤箭"), "鬼督邮", (None, None)) == (None, 0.5)  # blocked
    assert index.reading(gate_form(near), "鬼督邮", (None, None), cfg={"reading_window": 1}) == (None, 0.5)
    single = layer()
    assert single.reading(gate_form("国老"), "国老", (None, None)) == (single.record("国老").r[0], 1.0)
    assert single.reading("小便", "小便", (None, None)) == (None, 0.0)
    assert single.reading("某某", "某某", (None, None)) == (None, 0.0)


def test_floors_flag_and_name_the_edition_or_the_layer():
    index = layer()
    assert index.floor_flag("山药", (650, 680), (1100, 1100)) == "anachronism:山药<1063:edition"
    assert index.floor_flag("山药", (650, 680), (650, 680)) == "anachronism:山药<1063:layer"
    assert index.floor_flag("山药", (650, 680), None) == "anachronism:山药<1063:layer"
    assert index.floor_flag("山药", (1000, 1100), None) is None  # may be as late as the floor
    assert index.floor_flag("山药", (1063, 1063), None) is None
    assert index.floor_flag("山药", (None, None), None) is None
    assert index.floor_flag("薯蓣", (650, 680), None) is None and index.floor_flag("某某", (650, 680), None) is None


def test_one_hop_only(tmp_path):
    index = layer()
    # an alias reaches its drugs, never their other names: 地精 → 人参, 何首乌; never 交藤, 夜合 or 合欢
    assert plan(index, ask(None, "地精")) == [("人参", "a", True, None), ("何首乌", "a", True, None)]
    core = lexicon(tmp_path, {"何首乌": ["交藤", "地精", "夜合"], "人参": [], "合欢": []})
    assert plan(index, ask(core, "地精"), core) == [("人参", "a", True, None)]  # 何首乌 is searched already
    # a lexicon that files 地精 under 何首乌 does not make it 何首乌's way to 夜合
    thin = lexicon(tmp_path, {"何首乌": ["地精"], "人参": []})
    assert plan(index, ask(thin, "地精"), thin) == [("人参", "a", True, None)]
    # a drug reaches its own names, never another drug's: 何首乌 → 交藤, 夜合, 地精; never 合昏 or 合欢
    assert plan(index, ask(None, "何首乌")) == [
        ("交藤", "d", True, None), ("夜合", "d", True, None), ("地精", "d", True, None)]
    assert plan(index, ask(core, "何首乌"), core) == []  # the lexicon searches them already
    hand = {e.surface: e for e in index.expansions(ask(None, "何首乌"), None, {})}
    assert (hand["夜合"].shared, hand["夜合"].own, hand["夜合"].rivals) == (True, ["交藤", "何首乌"], ["合昏", "合欢"])
    assert (hand["交藤"].shared, hand["交藤"].rivals) == (False, [])


def test_a_name_outside_the_query_period_is_left_out():
    index = layer()
    qing = ask(None, "通草", after=1644, before=1912)  # 清代的通草: 通脱木, never 木通
    assert plan(index, qing) == [("通脱木", "a", True, None), ("木通", "a", False, "period")]
    assert plan(index, ask(None, "通草", before=907)) == [("木通", "a", True, None), ("通脱木", "a", False, "period")]
    assert plan(index, ask(None, "通草", after=900, before=1000)) == [
        ("木通", "a", True, None), ("通脱木", "a", True, None)]
    assert plan(index, ask(None, "木通", before=907)) == [("通草", "d", True, None)]  # 唐以前的木通
    assert plan(index, ask(None, "木通", after=1644)) == [("通草", "d", False, "period")]
    assert plan(index, qing, ablate=["period"]) == [("木通", "a", True, None), ("通脱木", "a", True, None)]
    assert index.view(qing, {})["excluded"] == [{"surface": "木通", "for": "通草", "why": "period"}]


def test_expansions_are_ordered_then_capped():
    index = layer()
    q = ask(None, "国老", "大黄")
    # alias→drug first, then open before cue, then more passages first; an unattested name is never searched
    assert plan(index, q) == [("甘草", "a", True, None), ("黄良", "d", True, None), ("火参", "d", True, None),
                              ("肤如", "d", False, "unattested"), ("将军", "d", True, None), ("锦纹", "d", True, None)]
    assert plan(index, q, expansions=3) == [
        ("甘草", "a", True, None), ("黄良", "d", True, None), ("火参", "d", True, None),
        ("肤如", "d", False, "unattested"), ("将军", "d", False, "cap"), ("锦纹", "d", False, "cap")]
    assert [e[2] for e in plan(index, q, mask_bits=4)] == [True, True, False, False, False, False]  # 30 − 2 surfaces
    q.groups = {"formula:x": [["芒硝", "厚朴"]]}
    assert [e[2] for e in plan(index, q, mask_bits=4)] == [True, False, False, False, False, False]
    assert [e[2] for e in plan(index, q, mask_bits=2)] == [False] * 6
    assert "川军" in [e[0] for e in plan(index, q, ablate=["gates"])]  # a candidate only when the gates are off
    assert plan(index, ask(None, "小便")) == [] and plan(AliasIndex.empty(), q) == []
    # shuffled records and asked names in another order change nothing but which asked name a shared one serves
    shuffled = list(layer().records.values())
    random.Random(23).shuffle(shuffled)
    again = AliasIndex(shuffled, context=CONTEXT)
    assert plan(again, ask(None, "国老", "大黄")) == plan(index, q) == plan(index, ask(None, "大黄", "国老"))


def test_spellings_and_heads():
    index = layer()
    # an alias reaches its head and the head's spellings; a spelling's own group stays one drug
    assert plan(index, ask(None, "国老")) == [("甘草", "a", True, None)]
    assert plan(index, ask(None, "檗木")) == [("黄柏", "a", True, None), ("黄蘗", "a", True, None)]
    assert plan(index, ask(None, "黄柏")) == [("黄蘗", "d", True, None), ("檗木", "d", True, None)]
    (e,) = index.expansions(ask(None, "薯蓣"), None, {})
    assert (e.surface, e.head, e.kind, e.src) == ("山药", "山药", "taboo_rename", ["taboo"])
    assert [e.surface for e in index.expansions(ask(None, "甘草"), None, {})] == ["国老", "蜜甘", "美草"]


def test_the_query_view(tmp_path):
    index = layer()
    view = index.view(ask(None, "国老"), {})
    assert view == {"asked": [{"surface": "国老", "term": None, "ambiguous": False, "referents": [
        {"head": "甘草", "kind": "异名", "status": "open", "valid": None, "floor": None,
         "source": ["别名录（中醫笈成）", "编者审定"], "witness": "qianjin.00012", "witness_year": 652, "credited": None}]}],
        "expansions": [{"surface": "甘草", "for": "国老", "direction": "alias→drug", "referent": "甘草", "kind": "异名",
                        "status": "open", "searched": True, "why": None}], "excluded": []}
    web = index.view(ask(None, "国老"), {"witness_scope": "web"})["asked"][0]["referents"][0]
    assert (web["witness"], web["witness_year"]) == ("jc_c030.00217", 1568)
    assert index.view(ask(None, "薯蓣"), {})["asked"][0]["referents"][0]["floor"] == 1063
    general = ask(None, "通草")
    shown = index.view(general, {})["asked"][0]
    assert shown["ambiguous"] and [(r["head"], r["kind"], r["valid"]) for r in shown["referents"]] == [
        ("木通", "古名", [None, 960]), ("通脱木", "异名", [960, None])]
    # a head alone is not listed; its expansions are
    assert index.view(ask(None, "甘草"), {})["asked"] == []
    # a name the lexicon files under two herbs is listed with both, from the lexicon
    lex = lexicon(tmp_path, {"狗脊": ["百枝"], "防风": ["百枝"], "甘草": ["国老"]})
    view = index.view(ask(lex, "百枝"), {}, lex)
    assert view["asked"][0]["ambiguous"] and [(r["head"], r["source"]) for r in view["asked"][0]["referents"]] == [
        ("狗脊", ["词表"]), ("防风", ["词表"])]
    # one drug filed in both is one referent
    assert [r["head"] for r in index.view(ask(lex, "国老"), {}, lex)["asked"][0]["referents"]] == ["甘草"]
    exps = index.expansions(general, None, {})
    assert index.view(general, {}, expansions=exps) == index.view(general, {})
    assert index.view(ask(lex, "消渴"), {}, lex) == {} and AliasIndex.empty().view(ask(None, "国老"), {}) == {}
    assert index.view(ask(None, "小便"), {}) == {}


def test_windows():
    assert overlaps(None, (1, 2)) and overlaps((None, 960), (None, None)) and overlaps((960, None), (900, 1000))
    assert overlaps((None, 960), (959, 959)) and not overlaps((None, 960), (960, 960))
    assert overlaps((960, None), (960, 960)) and not overlaps((960, None), (900, 959))
    assert meets(None, 1, 2) and meets((None, 960), None, None) and not meets((None, 960), 960, None)
    assert meets((None, 960), 959, None) and meets((960, None), None, 961) and not meets((960, None), None, 960)


def test_assemble_reserves_every_place_where_num_k_over_den_steps():
    M, S = [f"m{i}" for i in range(20)], [f"s{i}" for i in range(20)]
    assert assemble(M, S, 10) == ["m0", "m1", "m2", "s0", "m3", "m4", "s1", "m5", "m6", "s2"]
    assert [i + 1 for i, h in enumerate(assemble(M, S, 20)) if h[0] == "s"] == [4, 7, 10, 14, 17, 20]
    assert [i + 1 for i, h in enumerate(assemble(M, S, 20, 2, 10)) if h[0] == "s"] == [5, 10, 15, 20]
    assert assemble(M[:2], S, 6) == ["m0", "m1", "s0", "s1", "s2", "s3"]  # the side queue fills in
    assert assemble(M, [], 5) == M[:5] and assemble([], S[:2], 5) == ["s0", "s1"] and assemble([], [], 5) == []
    assert assemble(M, S, 0) == []
    for k in range(1, 41):
        for num, den in ((3, 10), (2, 10), (1, 3)):
            out = assemble(M * 3, S, k, num, den)
            assert len(out) == k and sum(h[0] == "s" for h in out) == min(len(S), num * k // den)


def test_three_thousand_records_with_their_context_load_and_scan_quickly(tmp_path):
    rng = random.Random(23)
    han = [chr(c) for c in range(0x4E00, 0x4E00 + 400)]
    surfaces = sorted({"".join(rng.sample(han, rng.choice((2, 3, 4)))) for _ in range(3400)})[:3000]
    heads = surfaces[:300]
    records = [AliasRecord(s, n=rng.randrange(50), b=[s + "汤"], ho=s if s in heads else None, r=[] if s in heads else [
        Referent(rng.choice(heads), st=rng.choice(STATUSES), src=["bielu-jc"])]) for s in surfaces]
    path = write_records(tmp_path / "aliases.jsonl", records)
    context = tmp_path / "context.json"
    context.write_text(json.dumps({**CONTEXT, "herbs": surfaces}, ensure_ascii=False), encoding="utf-8")
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        index = AliasIndex.load([path], context)
        best = min(best, time.perf_counter() - start)
    assert len(index) == 3000 and best < 0.1
    text = "".join(rng.choice(han) for _ in range(2000))
    start = time.perf_counter()
    found = index.scan(text)
    assert time.perf_counter() - start < 0.05
    assert all(text[i:j] == s and index.record(s) is not None for i, j, s in found)
    assert sum(len(index.by_group(h)) for h in heads) == 2700
