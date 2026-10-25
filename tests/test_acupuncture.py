"""针灸选穴配穴 · 腧穴考 — the specific-point tables and what follows from them (the phases of Nanjing 64, the mother and
child points of Nanjing 69), the selection reasoned for the review's teaching examples, the combinations named for what
they are (and what they are not), the cautions, and the classics read for their entries and indications on a synthetic
corpus (tests/fixtures/acupuncture): two witnesses that disagree, an entry over two passages, a 三里 under 手阳明."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.acupuncture import Framework
from taochronos.plugins.classics.study.render import markdown

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "acupuncture")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


@pytest.fixture(scope="module")
def fw(study) -> Framework:
    return study._acupuncture.fw


def chosen(r: dict) -> list[str]:
    return [p["code"] for p in r["prescription"]["core"] + r["prescription"]["supplementary"]]


def combo(r: dict, method: str) -> list[dict]:
    return [c for c in r["combinations"] if c["method"] == method]


# ------------------------------------------------------------------ the framework
def test_the_data_is_consistent():
    data = yaml.safe_load((HOME / "domains" / "classics" / "acupuncture.yaml").read_text(encoding="utf-8"))
    codes = {p["code"] for p in data["points"]}
    assert len(codes) == len(data["points"])  # one record per point
    used = [c for codes_ in data["five_shu"]["points"].values() for c in codes_]
    used += [*data["yuan"].values(), *data["luo"].values(), *data["xi"].values(), *data["back_shu"].values(),
             *data["front_mu"].values(), *data["lower_he"].values(), *(h["point"] for h in data["hui"].values()),
             *data["confluent"]["points"], *data["crossing"], *data["four_command"]]
    for table in ("regions", "symptoms", "natures"):
        for v in data[table].values():
            used += v.get("local", []) + v.get("distal", []) + v.get("back", []) + v.get("front", []) + v.get("points", []) + v.get("acute", [])
            assert v.get("rule") is None or v["rule"] in data["rules"]
    assert set(used) <= codes, sorted(set(used) - codes)
    names = [n for p in data["points"] for n in [p["name"], *p.get("aliases", [])]]
    assert len(names) == len(set(names))  # a name the data reads in a text belongs to one point (临泣, 通谷 … are left out)
    for rule in data["rules"].values():  # a probe is searched as written: no punctuation inside it
        for probe in rule.get("probes", []):
            text = probe["text"] if isinstance(probe, dict) else probe
            assert not set(text) & set("，。、；：")


def test_the_specific_point_tables(fw):
    assert sum(1 for c in fw.points if fw.has(c, "five_shu")) == 60
    assert len(fw.d["luo"]) == 15 and {"CV", "GV", "脾之大络"} <= set(fw.d["luo"])  # 十五络
    assert len(fw.d["xi"]) == 16 and fw.d["xi"]["阴维脉"] == "KI9" and fw.d["xi"]["阳跷脉"] == "BL59"  # 十六郄
    assert len(fw.d["hui"]) == 8 and len(fw.d["confluent"]["points"]) == 8 and len(fw.d["lower_he"]) == 6
    for ch, c in fw.channels.items():  # on yin channels the Shu-Stream point is the Yuan-Source point
        if ch in fw.d["yuan"]:
            assert (fw.d["yuan"][ch] == fw.five_shu(ch, "shu_stream")) == bool(c.get("yin")), ch
    phase = lambda code: next(c["phase"] for c in fw.categories(code) if c["type"] == "five_shu")  # noqa: E731
    assert (phase("LU10"), phase("ST44"), phase("LU5"), phase("ST36")) == ("火", "水", "水", "土")  # Nanjing 64, as the review gives
    assert fw.categories("LU9") and {c["type"] for c in fw.categories("LU9")} >= {"five_shu", "yuan", "hui"}  # 太渊: three at once
    assert {fw.points[fw.d["front_mu"][o]]["channel"] for o in ("脾", "肾", "大肠")} == {"LR", "GB", "ST"}  # Mu off its own channel
    for organ, code in fw.d["lower_he"].items():  # the foot yang channels' He-Sea is their Lower He-Sea; the hand yang's is not
        ch = fw.organs[organ]["channel"]
        assert (fw.five_shu(ch, "he_sea") == code) == (fw.channels[ch]["limb"] == "足"), organ
    assert fw.points["ST34"]["part"] == "lower_limb" and "膝上" in fw.points["ST34"]["note"]


def test_mother_and_child_points_follow_the_phases(fw):
    lung, liver = fw.mother_child("LU"), fw.mother_child("LR")
    assert (lung["same"]["mother"], lung["cross"]["mother"]) == ("LU9", "SP3")  # Lung deficiency: Taiyuan; Taibai
    assert (lung["same"]["child"], lung["cross"]["child"]) == ("LU5", "KI10")  # Lung excess: Chize; Yingu
    assert (liver["same"]["mother"], liver["cross"]["mother"]) == ("LR8", "KI10")  # Liver deficiency: Ququan; Yingu
    assert (liver["same"]["child"], liver["cross"]["child"]) == ("LR2", "HT8")  # Liver excess: Xingjian; Shaofu
    assert lung["own"] == "LU8"  # 经渠, the Metal point of the Metal channel
    spleen = fw.mother_child("SP")  # Taibai serves the Lung as the Spleen's own-phase point; the Spleen's mother point is Dadu
    assert spleen["own"] == "SP3" and spleen["same"]["mother"] == "SP2"


def test_the_framework_lists_its_tables(study):
    r = study.acupoints(framework=True)
    assert len(r["five_shu"]) == 12 and r["five_shu"][0]["jing_well"] == {"code": "LU11", "name": "少商", "phase": "木"}
    assert r["counts"] == {"five_shu": 60, "luo": 15, "xi": 16, "hui": 8, "confluent": 8, "lower_he": 6}
    ids = [t["id"] for t in r["tables"]]
    assert ids[:2] == ["acupoints-five-shu", "acupoints-yuan-luo-xi"] and "acupoints-mother-child" in ids
    rule = next(x for x in r["rules"] if x["id"] == "five_phase")
    assert rule["witnesses"][0]["earliest"]["book_id"] == "nj"  # 阴井木 found in the 难经 of the fixture


# ------------------------------------------------------------------ selection
def test_epigastric_fullness_with_nausea(study):
    """The review's first example: 中脘 (local, Stomach Front-Mu, Influential Point of the fu), 足三里 (Stomach He-Sea and
    Lower He-Sea), 内关 for the nausea — a Lower He–Mu and a local–distal combination, and an upper–lower one."""
    r = study.acupoints("胃脘胀满，恶心")
    pres = r["presentation"]
    assert pres["symptoms"] == ["epigastric_fullness", "nausea_vomiting"] and pres["inferred"] == {"regions": ["epigastrium"], "organs": ["胃"]}
    assert [p["code"] for p in r["prescription"]["core"]] == ["CV12", "ST36", "PC6"]
    cv12 = r["prescription"]["core"][0]
    assert {c["label"] for c in cv12["categories"]} >= {"胃之募穴", "腑会"} and cv12["laterality"] == "单穴（正中线）"
    st36 = r["prescription"]["core"][1]
    assert {c["type"] for c in st36["categories"]} >= {"five_shu", "lower_he", "four_command"}
    assert any(x["rule"] == "lower_he" for pur in st36["purposes"] for x in pur["reasons"])
    assert combo(r, "lowerhe_mu")[0]["points"] == ["ST36", "CV12"] and combo(r, "local_distal") and combo(r, "upper_lower")
    assert all(p["purposes"] for p in r["prescription"]["core"] + r["prescription"]["supplementary"])  # every point says why
    assert [s["step"] for s in r["steps"]] == ["1", "2", "3", "4", "5"]
    assert r["implementation"]["modality"] is None and r["implementation"]["frequency"] is None  # the practitioner's to fill
    # the classics: 三里 主「胀满」 in the fixture's 甲乙经, and the rules' witnesses
    fullness = next(f for f in r["classical"]["findings"] if f["symptom"] == "epigastric_fullness")
    assert fullness["points"][0]["code"] == "ST36" and fullness["points"][0]["earliest"]["book_id"] == "jy_a"
    lower = next(x for x in r["rules"] if x["id"] == "lower_he")
    assert lower["witnesses"][0]["earliest"]["passage_id"] == "ls.3"
    # three levels kept apart: PC6 for postoperative nausea, and the review of treatment characteristics
    assert {m["id"] for m in r["evidence"]["modern"]} == {"macpherson2013", "lee2015"}
    pc6 = r["prescription"]["core"][2]
    assert pc6["record"]["modern_evidence"].startswith("lee2015") and "不针对此穴" in pc6["record"]["modern_evidence"]
    assert {"network", "timeline"} == {c["type"] for c in r["charts"]}
    assert [t["id"] for t in r["tables"]] == ["acupoints-prescription", "acupoints-combinations", "acupoints-classical"]


def test_neck_pain_takes_the_taiyang_and_du_relations(study):
    r = study.acupoints(regions=["颈项"], symptoms=["项强"])
    codes = chosen(r)
    assert {"BL10", "GB20"} & set(codes) and {"SI3", "BL62"} <= set(codes)
    assert combo(r, "confluent_pair")[0]["points"] == ["SI3", "BL62"] and r["prescription"]["ashi"]
    assert any(m["id"] == "vickers2018" for m in r["evidence"]["modern"])  # chronic pain: acupuncture as a whole, not this rule


def test_headache_is_located_before_its_channel(study):
    front = study.acupoints("前额头痛")
    assert front["presentation"]["regions"] == ["forehead"]  # 头痛 is located: no general 头部 objective beside it
    assert set(chosen(front)) >= {"GV29", "ST8"} and "LI4" in chosen(front)  # local, and a distal 阳明 point
    side = study.acupoints(regions=["侧头"])
    assert {c["channel"] for c in side["channels"][:2]} == {"GB", "TE"}


def test_mother_child_and_host_guest(study):
    r = study.acupoints(organs=["肺"], natures=["虚"], symptoms=["咳嗽"])
    assert "LU9" in chosen(r)
    mother = [x for p in r["prescription"]["core"] + r["prescription"]["supplementary"] for pur in p["purposes"]
              for x in pur["reasons"] if x["rule"] == "mother_child"]
    assert mother and "太渊" in mother[0]["text"]
    assert any(p["technique"] and p["technique"]["intent"] == "补" for p in r["prescription"]["core"])
    alt = {a["code"] for a in r["alternatives"]} | set(chosen(r))
    assert "SP3" in alt  # the cross-channel mother point is proposed, if not chosen
    hg = study.acupoints(organs=["肺", "大肠"])
    assert [c["points"] for c in combo(hg, "yuan_luo") if c.get("classical") is not False] == [["LU9", "LI6"]]


def test_what_a_combination_is_not(study, fw):
    acu = study._acupuncture
    pres = acu._presentation(None, ["巅顶"], ["易怒"], [], [], [], None, None, False)
    combos = acu._combinations(["LI4", "LR3", "LU9", "LU7"], {}, pres)
    gates = next(c for c in combos if c["method"] == "four_gates")
    assert gates["points"] == ["LI4", "LR3"] and gates["classical"] is False and "不是原络配穴" in gates["text"]
    yl = [c for c in combos if c["method"] == "yuan_luo"]
    assert any(c["points"] == ["LI4", "LU7"] and c.get("classical") is not False for c in yl)  # Large Intestine host: Hegu + Lieque
    same = next(c for c in yl if c["points"] == ["LU9", "LU7"])
    assert same["classical"] is False and same["name"].startswith("本经原穴配络穴")  # one channel's Yuan and Luo
    assert not any(set(c["points"]) == {"LI4", "LR3"} for c in yl)


def test_pregnancy_leaves_points_out_and_cautions_stay(study):
    plain = study.acupoints(symptoms=["痛经"])
    assert "SP6" in chosen(plain) and any(c["kind"] == "pregnancy" and c["severity"] == "note" for c in plain["cautions"])
    r = study.acupoints(symptoms=["痛经"], pregnant=True)
    out = {x["code"] for x in r["excluded"]}
    assert {"SP6", "CV3", "CV4"} <= out and not out & set(chosen(r))
    assert any(c["kind"] == "general" for c in r["cautions"])


def test_reading_a_presentation(study, fw):
    read = fw.read("右侧腰痛，急性发作，畏寒")
    assert read["found"] == {"side": ["right"], "symptom": ["low_back_pain"], "acuity": ["acute"], "nature": ["cold"]}
    assert read["unread"] == ["发作"]
    pres = study.acupoints("右侧腰痛，急性发作，畏寒")["presentation"]
    assert pres["regions"] == ["lumbar"] and pres["inferred"]["regions"] == ["lumbar"]  # the symptom's region
    assert pres["side"] == "right" and pres["acuity"] == "acute"
    r = study.acupoints("knee pain, worse in cold weather")
    assert r["presentation"]["regions"] == ["knee"] and r["presentation"]["natures"] == ["cold"]
    assert r["prescription"]["core"][0]["code"] == "ST35"  # the region's own order of its local points
    with pytest.raises(ValueError):
        study.acupoints("气虚")  # a nature alone names neither where nor what


# ------------------------------------------------------------------ the classics
def test_a_point_in_the_classics(study):
    r = study.point("太渊")
    assert r["point"]["code"] == "LU9" and "太泉" in r["names"]  # the Tang taboo name
    phase = next(c for c in r["checks"] if c["attribute"] == "phase")
    assert phase["data"] == ["土"] and phase["agree"] == 1 and phase["differ"][0]["stated"] == ["水"]
    assert phase["differ"][0]["witness"]["book_id"] == "jy_b"  # the two witnesses disagree; both are quoted
    first = next(e for e in r["entries"] if e["witness"]["book_id"] == "jy_a")
    assert first["stated"]["needle"] == "二分" and first["witness"]["passage_id"] == "jy_a.01"  # read across the passage break
    assert first["witness"]["quote"].startswith("太淵者") or first["witness"]["quote"].startswith("太渊者")
    forms = {x["form"] for x in r["indications"]["examples"]}
    assert forms == {"主之", "主"} and r["indications"]["works"] == 2  # 甲乙经 …太渊主之; 千金 太泉主心痛
    assert any(f["finding"] == "咳嗽" for f in r["indications"]["findings"])


def test_names_are_read_by_their_chapter_and_lists(study):
    hand, foot = study.point("手三里"), study.point("ST36")
    assert [e["witness"]["passage_id"] for e in hand["entries"]] == ["jy_b.2"]  # 三里 under 手阳明
    assert "jy_b.2" not in [e["witness"]["passage_id"] for e in foot["entries"]]
    assert {x["form"] for x in foot["indications"]["examples"]} >= {"主之", "取"}  # 「……取三里」 in the 灵枢 too
    for name in ("尺泽", "曲泽"):  # 「尺泽、曲泽主之」: both points of the list
        assert study.point(name)["indications"]["examples"][0]["condition"] == "热病汗不出，呕吐，胸满"


def test_prohibitions_and_meetings(study):
    assert [p["text"] for p in study.point("神阙")["prohibitions"]] == ["禁不可刺"]
    assert study.point("经渠")["prohibitions"][0]["text"] == "不可灸"
    meeting = next(c for c in study.point("三阴交")["checks"] if c["attribute"] == "meeting")
    assert meeting["agree"] == 1 and meeting["data"] == ["KI", "LR", "SP"]
    with pytest.raises(ValueError):
        study.point("不是穴")


def test_four_gates_read_in_two_senses(study):
    rows = {w["probe"]: w for w in study._acupuncture.rule_witnesses("four_gates")}
    assert rows["十二原出于四关"]["earliest"]["book_id"] == "ls" and "关节" in rows["十二原出于四关"]["reading"]
    assert rows["太冲合谷是也"]["earliest"]["book_id"] == "jq" and rows["四关者两手两足"]["works"] == 0


# ------------------------------------------------------------------ tools, page and CLI (the demonstration corpus)
def test_the_tools_through_the_scheduler(harness):
    call = lambda tool, **a: harness.scheduler.execute(ToolCall(tool, a), actor=Actor.kernel())  # noqa: E731
    out = call("study.acupoints", text="失眠多梦，心悸")
    assert out.ok and out.result["prescription"]["core"][0]["code"] == "HT7" and out.result["tables"]
    out = call("study.acupoints", regions=["腰", "膝"], symptoms=["low back pain"], acute=True)
    assert out.ok and out.result["presentation"]["regions"] == ["lumbar", "knee"] and out.result["presentation"]["acuity"] == "acute"
    out = call("study.acupoints", framework=True)
    assert out.ok and len(out.result["five_shu"]) == 12
    out = call("study.point", point="ST36")
    assert out.ok and out.result["point"]["name"] == "足三里"
    assert not call("study.acupoints").ok and not call("study.point", point="不是穴").ok


def test_the_pages(study):
    sig = study.signature()
    page = markdown("acupoints", study.acupoints("胃脘胀满，恶心"), sig)
    assert page.startswith("# 选穴配穴") and "## 配穴方法" in page and "合募配穴" in page and "## 证据的三个层次" in page
    assert "不是诊断" in page or "不是处方" in page
    page = markdown("point", study.point("太渊"), sig)
    assert page.startswith("# 腧穴考：太渊 LU9") and "相异" in page and "jy_b.1" in page
    assert markdown("acupoints", study.acupoints(framework=True), sig).startswith("# 针灸特定穴与补母泻子")


def test_cli_acupoints_and_point(capsys, tmp_path):
    assert main(["--data", str(tmp_path), "study", "acupoints", "--region", "胃脘", "--symptom", "恶心"]) == 0
    assert capsys.readouterr().out.startswith("# 选穴配穴：胃脘")
    assert main(["--data", str(tmp_path), "study", "point", "LU9"]) == 0
    assert capsys.readouterr().out.startswith("# 腧穴考：太渊 LU9")
    figures = tmp_path / "figures"
    assert main(["--data", str(tmp_path), "study", "acupoints", "--framework", "--charts", str(figures)]) == 0
    capsys.readouterr()
    assert any(p.suffix == ".docx" for p in figures.iterdir())
