"""The capabilities of the task specification (docs/tasks.md) that the study layer gained with it: 句读 (T4–T5) and
the others added beside it, each on synthetic text whose answer is known."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.punctuation import (MARKS, PunctuationModel, both_kinds, gaps, has_marks,
                                                             model_labels, score, strip_marks)

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(HOME / "domains" / "classics")


@pytest.fixture(scope="module")
def study(pack) -> StudyService:
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "study")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


# ------------------------------------------------------------------ 句读 (T4–T5)
FINDINGS = ["发热", "汗出", "恶风", "脉浮", "头痛", "项强", "身疼", "腰痛", "无汗", "喘", "恶寒", "呕逆", "口渴", "心烦", "下利"]
DISEASES = ["太阳", "阳明", "少阳", "太阴", "少阴", "厥阴"]
FORMULAS = ["桂枝汤", "麻黄汤", "葛根汤", "小柴胡汤", "白虎汤", "四逆汤", "理中丸", "真武汤"]


def _clauses(rng: random.Random) -> str:
    """A 条文 of the synthetic corpus: disease, three to five findings, the formula (clause and sentence marks known)."""
    found = rng.sample(FINDINGS, rng.randint(3, 5))
    return f"{rng.choice(DISEASES)}病，{'，'.join(found)}者，{rng.choice(FORMULAS)}主之。"


def _synthetic(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return ["".join(_clauses(rng) for _ in range(rng.randint(1, 3))) for _ in range(n)]


def test_gaps_read_the_marks_of_a_punctuated_text():
    chars, labels = gaps("太陽病，發熱汗出。桂枝湯主之（方見上）。")
    assert chars == "太陽病發熱汗出桂枝湯主之"  # notes in brackets are left out
    assert labels == [0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 0]
    assert gaps("右四味　以水七升")[1][2] == 1  # a space between the items of a prescription is a clause mark
    assert both_kinds([1, 1, 2, 1, 0, 2]) and not both_kinds([2, 2, 2, 2, 2])  # an editor who puts 。 everywhere
    assert has_marks("太阳病，发热，汗出。") and not has_marks("防己（一两）甘草（半两）　右剉麻豆大○喘者加麻黄")


def test_score_counts_boundaries_sentences_and_mark_types():
    s = score([0, 1, 0, 2, 0], [0, 2, 1, 2, 0])
    assert (s["boundary_p"], s["boundary_r"]) == (round(2 / 3, 4), 1.0)
    assert (s["sentence_p"], s["sentence_r"], s["mark_type_accuracy"]) == (0.5, 1.0, 0.5)


def test_model_learns_the_marks_and_never_changes_a_character(pack):
    normalize = pack.variants.normalize_text
    model = PunctuationModel().train(_synthetic(400, 1), lexicon=pack.lexicon)
    test = _synthetic(60, 2)
    gold: list[int] = []
    pred: list[int] = []
    for text in test:
        chars, labels = gaps(text)
        gold += labels
        pred += model_labels(model, chars)
    s = score(gold, pred)
    assert s["boundary_f1"] > 0.9 and s["mark_type_accuracy"] > 0.8
    out = model.punctuate(strip_marks(test[0]), normalize)
    assert out["preserved"] and out["text"].endswith("。")
    assert strip_marks(out["text"]) == strip_marks(test[0])


def test_punctuate_places_marks_around_notes_quotes_and_item_circles(pack):
    model = PunctuationModel().train(_synthetic(400, 1), lexicon=pack.lexicon)
    out = model.punctuate("太阳病发热汗出恶风者桂枝汤主之（方见上）太阳病头痛发热身疼无汗者麻黄汤主之", pack.variants.normalize_text)
    assert "主之（方见上）。太阳病" in out["text"]  # the mark follows the note, not inside the main text's run
    circles = model.punctuate("太阳病发热汗出者桂枝汤主之○少阳病口渴心烦者小柴胡汤主之", pack.variants.normalize_text)
    assert "主之。○少阳病" in circles["text"]  # before the circle that opens the next item
    kept = model.punctuate("太阳病，发热汗出恶风者桂枝汤主之", pack.variants.normalize_text)
    assert kept["text"].startswith("太阳病，发热") and kept["text"].count("，，") == 0  # existing marks stay, none doubled


def test_punctuate_keeps_every_character_of_arbitrary_input(pack):
    model = PunctuationModel().train(_synthetic(200, 3), lexicon=pack.lexicon)
    rng = random.Random(5)
    alphabet = "太阳病发热汗出恶风者桂枝汤主之曰云何也（）「」○　，。□ab1"
    for _ in range(200):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        out = model.punctuate(text, pack.variants.normalize_text)
        assert out["preserved"]
        assert len(out["text"]) == len(text) + out["inserted"]
        assert "".join(ch for ch in out["text"] if ch not in MARKS) == "".join(ch for ch in text if ch not in MARKS)


def test_study_punctuate_compares_a_punctuated_passage_with_its_editors(study):
    passage = next(p for p in study.corpus.passages() if has_marks(p.text) and len(p.text) > 20)
    r = study.punctuate(passage_id=passage.id)
    assert r["preserved"] and r["passage"]["passage_id"] == passage.id
    assert 0 <= r["against_editors"]["boundary_f1"] <= 1 and r["baseline_rules"] is not None
    plain = study.punctuate("太阳病发热汗出恶风脉缓者名为中风")
    assert plain["preserved"] and "against_editors" not in plain and plain["punctuated"].endswith("。")


def test_punctuate_through_the_tool_and_the_cli(harness, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("study.punctuate", {"text": "太阳病发热汗出恶风脉缓者名为中风"}), actor=Actor.kernel())
    assert out.ok and out.result["preserved"] and "marks" not in out.result
    assert main(["--data", str(tmp_path), "study", "punctuate", "太阳病发热汗出恶风脉缓者名为中风"]) == 0
    page = capsys.readouterr().out
    assert page.startswith("# 句读：") and "原字保留：是" in page


# ------------------------------------------------------------------ 集注对齐与注家比较 (T16–T17), 争议 (T26)
@pytest.fixture(scope="module")
def commentary_study(pack) -> StudyService:
    corpus = Corpus.load(HOME / "evals" / "gold" / "commentaries")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def test_commentaries_are_aligned_in_every_layout(commentary_study):
    r = commentary_study.commentaries("太阳之为病，脉浮，头项强痛而恶寒。")
    layouts = {u["book_id"]: u["layout"] for u in r["commentaries"]}
    assert layouts == {"chengzhu": ["row"], "fangzhu": ["row"], "yuzhu": ["run_on"], "kezhu": ["run_on"]}
    assert [u["commentator"] for u in r["commentaries"]] == ["成无己", "方有执", "喻昌", "柯琴"]  # in date order
    assert [q["passage_id"] for q in r["quotations"]] == ["huizuan.001"]  # quoted inside a compilation's own text
    yu = next(u for u in r["commentaries"] if u["book_id"] == "yuzhu")
    assert "中风" not in yu["text"]  # the next clause, with its own commentary, is not this clause's commentary
    assert {"六经", "膀胱", "营卫"} <= set(yu["reading"])
    rel = {(x["from_commentator"], x["to_commentator"], x["type"]) for x in r["relations"]}
    assert ("喻昌", "方有执", "承袭") in rel  # shared wording beyond the clause itself
    assert r["consensus"] and r["consensus"][0]["concept"] == "表"


def test_commentaries_read_explicit_rejection_and_approval(commentary_study):
    r = commentary_study.commentaries("太阳病，发热，汗出，恶风，脉缓者，名为中风。")
    rel = {(x["from_commentator"], x["to_commentator"], x["type"]) for x in r["relations"]}
    assert ("喻昌", "成无己", "驳") in rel and ("柯琴", "喻昌", "从") in rel
    ke = next(u for u in r["commentaries"] if u["book_id"] == "kezhu")
    assert ke["text"].startswith("（喻氏之说甚是")  # the note after the second clause of a 白文 paragraph


def test_disputes_keep_the_quoted_words_apart(commentary_study):
    people = commentary_study._commentary.people
    normalize = commentary_study.normalize

    def stance(text: str) -> tuple[str | None, str | None]:
        found = people.cited(normalize(text))
        return (found[0]["stance"], found[0].get("reported_by")) if found else (None, None)

    assert stance("丹溪谓阳常有余，阴常不足，此说非也。") == ("reject", None)
    assert stance("丹溪曰：气无补法，世俗之误也。") == (None, None)  # 丹溪's own verdict on others
    assert stance("丹溪曰：「诸痛不可补气。」此言未当也。") == ("reject", None)
    assert stance("丹溪所谓阴字有虚之义，若作阴冷看，其误甚矣。") == (None, None)  # a hypothetical misreading
    assert stance("丹溪谓属金而有水与火，良不谬也。") == (None, None)  # the marker denied
    assert stance("景岳之说，鲜不误矣。") == ("reject", None)  # … and affirmed
    assert stance("丹溪论阳有余阴不足，景岳驳之。") == ("reject", "zhang_jiebin")  # a rejection reported
    assert stance("河间之论甚妙，但未详其治法耳。") == ("endorse", None)


def test_commentaries_and_disputes_through_tools_and_cli(harness, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("study.disputes", {"person": "丹溪"}), actor=Actor.kernel())
    assert out.ok and "who_rejects_whom" in out.result
    out = harness.scheduler.execute(ToolCall("study.commentaries", {"text": "太阳之为病，脉浮，头项强痛而恶寒。"}),
                                    actor=Actor.kernel())
    assert out.ok and "commentaries" in out.result
    assert main(["--data", str(tmp_path), "study", "disputes", "--person", "丹溪"]) == 0
    assert capsys.readouterr().out.startswith("# 争议：丹溪")


# ------------------------------------------------------------------ 条文结构 (T6), 训诂 (T10)
def test_clause_parts_in_order(study):
    r = study.clause("伤寒二三日，心中悸而烦者，小建中汤主之。")
    assert [x["role"] for x in r["pieces"]] == ["condition", "findings", "formula"] and r["form"] == "前提→症→方"
    r = study.clause("右五味，以水七升，煮取三升，去滓，温服一升。若渴者，去半夏，加栝楼根四两。")
    assert [x["role"] for x in r["pieces"]] == ["preparation", "preparation", "preparation", "preparation", "administration",
                                               "condition", "modification", "modification"]
    r = study.clause("桂枝三两，去皮，芍药三两。")
    assert [x["role"] for x in r["pieces"]] == ["composition", "composition", "composition"]  # 去皮 is the drug's processing
    assert r["drugs"] and r["out_of_order"] == []


def test_clause_reads_bai_wen_through_the_punctuation_model(study):
    r = study.clause("太阳病发热汗出恶风脉缓者名为中风")
    assert r["punctuated_by_model"] and r["pieces"][0]["role"] == "disease"
    assert "".join(ch for x in r["pieces"] for ch in x["text"] if ch not in "，。；：、") == "太阳病发热汗出恶风脉缓者名为中风"


def test_glosses_are_of_the_word_not_of_a_clause_ending_in_it(study):
    find = study._glosses.find
    normalize = study.normalize

    def gloss(text: str) -> list[tuple[str, str, str]]:
        return [(g["kind"], g["head"], g["gloss"]) for g in find(normalize(text), text)]

    assert ("者也", "几几", "伸颈之貌") in gloss("几几者，伸颈之貌也。")
    assert ("反切", "强", "群养") in gloss("强，群养切。") and not any(k == "反切" for k, _, _ in gloss("痉，脊强反折。"))
    assert ("校改", "痓", "痉") in gloss("痓当作痉，传写之误也。")  # read as written: the normaliser takes both for 痉
    assert ("者也", "濈濈然", "连绵") in gloss("濈濈然者，程氏云：「连绵也。」")


def test_clause_and_glosses_through_tools_and_cli(harness, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("study.clause", {"text": "少阴病，脉沉者，急温之，宜四逆汤。"}), actor=Actor.kernel())
    assert out.ok and out.result["form"] == "病→脉→治则→方"
    assert main(["--data", str(tmp_path), "study", "glosses", "消渴"]) == 0
    assert capsys.readouterr().out.startswith("# 训诂：消渴")


# ------------------------------------------------------------------ 方证网络 (T20), 配伍 (T21)
def test_pair_statistics_find_planted_pairs():
    from taochronos.plugins.classics.study.pairs import PairsStudy

    rng = random.Random(3)
    herbs = [f"h{k:02d}" for k in range(20)]
    transactions = []
    for _ in range(400):
        t = set(rng.sample(herbs, 4))
        if "h00" in t or "h01" in t:
            t |= {"h00", "h01"}  # always together
        transactions.append(t)
    table = PairsStudy.pair_table(transactions, min_support=5)
    top = table[0]
    assert (top["a"], top["b"]) == ("h00", "h01") and top["significant"] and top["conf_ab"] == 1.0
    assert sum(r["significant"] for r in table[1:]) <= 2  # chance pairs rarely pass Benjamini–Hochberg


def test_harvest_reads_compositions_and_treatment_sentences(study):
    built = study._pairs.h.build(None)
    guizhi = [c for c in built["compositions"] if c[1] == "formula:桂枝汤"]
    assert guizhi and {"family:桂", "family:芍药", "family:甘草"} <= set(guizhi[0][2])
    net = study.network("桂枝汤")
    assert net["kind"] == "formula" and {"桂", "芍药"} <= {d["drug"] for d in net["drugs"]}
    res = study.pairs("桂枝", min_support=1)
    assert res["key"] == "family:桂" and any(p["with"] == "芍药" for p in res["partners"])


def test_pairs_and_network_through_tools_and_cli(harness, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("study.network", {"target": "桂枝汤"}), actor=Actor.kernel())
    assert out.ok and out.result["kind"] == "formula"
    assert main(["--data", str(tmp_path), "study", "pairs", "甘草"]) == 0
    assert capsys.readouterr().out.startswith("# 配伍：甘草")


# ------------------------------------------------------------------ 学派 (T25)
def _school_corpus(root: Path) -> Path:
    """Four 温病 physicians of physicians.yaml and twelve other authors of their time: the school's works write 营分 in
    several phrases, the others once; all write the same findings; the school's works quote 叶天士, the others 丹溪."""
    import yaml

    rng = random.Random(7)
    school = [("wy", "温疫论", "吴有性", 1642), ("wr", "温热论", "叶桂", 1746), ("tb", "温病条辨", "吴瑭", 1798),
              ("sr", "湿热病篇", "薛雪", 1750)]
    others = [(f"o{k}", f"医书第{'一二三四五六七八九十'[k % 10]}{k}", f"某{'甲乙丙丁戊己庚辛壬癸子丑'[k]}", 1650 + 13 * k) for k in range(12)]
    common = ["发热", "恶寒", "脉浮", "头痛", "汗出", "口渴", "咳嗽", "心烦", "腹满", "下利", "身重", "脉数"]
    src = {"origin": "TaoChronos test fixture (synthetic)", "license": "CC0-1.0", "acquisition": "written for the test"}
    (root / "books").mkdir(parents=True, exist_ok=True)
    meta: dict = {"books": []}
    for bid, title, author, year in school + others:
        own = bid in {s[0] for s in school}
        meta["books"].append({"id": bid, "title": title, "authors": [author], "dynasty": "清", "composition": [year, year],
                              "category": "温病" if own else "综合", "source": src})
        passages = []
        for i in range(30):
            words = rng.sample(common, 4)
            if own and i % 2 == 0:
                words += [rng.choice(["热入营分", "营分受热", "邪在营分", "营分有热"]), rng.choice(["卫分之邪", "邪在卫分"])]
            if bid == "o3" and i == 0:
                words.append("营分")
            text = "，".join(words) + "。"
            if i == 5:
                text += "叶天士曰：温邪上受，首先犯肺。" if own else "丹溪曰：阳常有余，阴常不足。"
            passages.append({"id": f"{bid}.{i:03d}", "text": text})
        (root / "books" / f"{bid}.yaml").write_text(
            yaml.safe_dump([{"book": bid, "defaults": {"kind": "text"}, "passages": passages}], allow_unicode=True), encoding="utf-8")
    (root / "books.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def school_study(pack, tmp_path_factory) -> StudyService:
    corpus = Corpus.load(_school_corpus(tmp_path_factory.mktemp("schools")))
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def test_school_words_are_those_its_physicians_write_more(school_study):
    r = school_study.schools("温病学派")
    assert r["school"] == "温病" and r["works"] == 4 and r["comparison"]["units"] == 4
    words = [w["item"] for w in r["vocabulary"]]
    assert words[:2] in (["营分", "卫分"], ["卫分", "营分"]) and all(w["significant"] for w in r["vocabulary"][:2])
    assert not {"发热", "脉浮", "天士", "叶天士"} & set(words)  # shared by all; a physician's name goes to the citations
    top = r["vocabulary"][0]
    assert top["share"] == 1.0 and top["other_share"] < 0.1 and top["example"]["book_id"] in {"wy", "wr", "tb", "sr"}
    homophily = r["citations"]["homophily"]  # the school quotes its own, the others never do
    assert homophily["own_share"] == 1.0 and homophily["other_share"] == 0.0 and homophily["ratio"] is None
    assert [m["name"] for m in r["members"] if m["works"]] == ["吴有性", "叶桂", "薛雪", "吴瑭"]


def test_school_membership_and_weights(school_study):
    sc = school_study._schools
    assert sc.resolve("温疫") == "温病·温疫" and sc.resolve("错简重订") == "伤寒·错简重订" and sc.resolve("丹溪学派") == "丹溪"
    own, other = sc.group_works("温病"), sc.comparison("温病")
    w = sc.weights("温病", own, other)
    assert w["units"] == 4 and not w["by_works"] and abs(sum(w["own"].values()) - 4) < 1e-9
    assert abs(sum(w["other"].values()) - 12) < 1e-9  # twelve other authors, one unit each
    assert not sc.wordlike("之邪") and not sc.wordlike("三两") and not sc.wordlike("天士") and sc.wordlike("营分")


def test_schools_through_tools_and_cli(harness, school_study, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("study.schools", {"school": "温病"}), actor=Actor.kernel())
    assert out.ok
    survey = school_study.schools()
    assert any(s["school"] == "温病" and s["works"] == 4 for s in survey["schools"])
    assert main(["--data", str(tmp_path), "study", "schools", "温病"]) == 0
    assert capsys.readouterr().out.startswith("# 学派：温病学派")


# ------------------------------------------------------------------ 名称 (T9, T24), 传播链 (T15)
def _write_corpus(root: Path, books: list[tuple[str, str, str, int, str, list[str]]]) -> Path:
    """books: (id, title, author, year, category, passages) → a corpus directory."""
    import yaml

    src = {"origin": "TaoChronos test fixture (synthetic)", "license": "CC0-1.0", "acquisition": "written for the test"}
    (root / "books").mkdir(parents=True, exist_ok=True)
    meta = {"books": [{"id": b, "title": t, "authors": [a], "dynasty": "", "composition": [y, y], "category": c, "source": src}
                      for b, t, a, y, c, _ in books]}
    for b, _, _, _, _, texts in books:
        passages = [{"id": f"{b}.{i:03d}", "text": text} for i, text in enumerate(texts)]
        (root / "books" / f"{b}.yaml").write_text(
            yaml.safe_dump([{"book": b, "defaults": {"kind": "text"}, "passages": passages}], allow_unicode=True), encoding="utf-8")
    (root / "books.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")
    return root


def test_names_follow_薯蓣_giving_way_to_山药(pack, tmp_path):
    books = [(f"e{k}", f"古方{k}", f"甲{k}", y, "方书", ["薯蓣丸，治虚劳。薯蓣三两。"]) for k, y in enumerate([520, 540, 560, 620, 640, 660])]
    books += [(f"l{k}", f"后方{k}", f"乙{k}", y, "方书", ["山药丸，治虚劳。山药三两。"]) for k, y in enumerate([1120, 1140, 1160, 1220, 1240, 1260])]
    books += [("gan", "炮制书", "丙", 1250, "本草", ["干山药，蒸之。"]),
              ("eq", "本草释名", "丁", 1300, "本草", ["山药，一名薯蓣，一名山芋。"]),
              ("eq2", "本草便览", "戊", 1400, "本草", ["薯蓣，一名山芋，俗呼山药。"])]
    corpus = Corpus.load(_write_corpus(tmp_path / "names", books))
    corpus.normalize = pack.variants.normalize_text
    r = StudyService(pack, corpus).names("山药")
    rows = {n["name"]: n for n in r["names"]}
    assert rows["山药"]["works"] == 8 and rows["干山药"]["works"] == 1  # 干山药 is its own name, not 山药's
    assert rows["薯蓣"]["kind"] == "避讳改名" and rows["薯蓣"]["first"][0]["years"] == [520, 520]
    assert [(s["from"], s["to"]) for s in r["switches"]] == [("薯蓣", "山药")] and r["switches"][0]["between"] == [600, 1200]
    assert any(set(e["names"]) == {"山药", "薯蓣"} for e in r["equations"])
    assert [c["name"] for c in r["candidates"]] == ["山芋"]  # the name the lexicon lacks


def test_chain_follows_shared_changes(pack, tmp_path):
    base = "太阳病，头痛发热，身疼腰痛，骨节疼痛，恶风无汗而喘者，麻黄汤主之。"

    def change(text: str, old: str, new: str) -> str:
        assert old in text
        return text.replace(old, new, 1)

    a = change(base, "头痛", "头项强痛")
    b = change(a, "腰痛", "腰脊痛")
    c = change(base, "恶风", "恶寒")
    d = change(b, "而喘", "而咳喘")
    e = change(c, "骨节", "百节")
    texts = {"r": (200, base), "a": (500, a), "b": (800, b), "c": (900, c), "d": (1000, d), "e": (1100, e), "f": (1200, base)}
    books = [(k, f"书{k}", f"某{k}", y, "伤寒", [t]) for k, (y, t) in texts.items()]
    corpus = Corpus.load(_write_corpus(tmp_path / "chain", books))
    corpus.normalize = pack.variants.normalize_text
    r = StudyService(pack, corpus).chain(base)
    parent = {e["to"].split(".")[0]: e["from"].split(".")[0] for e in r["edges"]}
    assert r["root"]["book_id"] == "r"
    assert parent == {"a": "r", "b": "a", "c": "r", "d": "b", "e": "c", "f": "r"}
    edge = next(x for x in r["edges"] if x["to"].startswith("d"))
    assert {s["reading"] for s in edge["shared"]} >= {"项强", "脊"} and edge["basis"] == "shared readings"
    assert r["summary"]["depth"] == 3


def test_names_and_chain_through_tools_and_cli(harness, capsys, tmp_path):
    out = harness.scheduler.execute(ToolCall("study.names", {"term": "山药"}), actor=Actor.kernel())
    assert out.ok
    out = harness.scheduler.execute(ToolCall("study.chain", {"text": "太阳病，发热，汗出，恶风，脉缓者，名为中风。"}), actor=Actor.kernel())
    assert out.ok
    assert main(["--data", str(tmp_path), "study", "names", "山药"]) == 0
    assert capsys.readouterr().out.startswith("# 名称：山药")
    assert main(["--data", str(tmp_path), "study", "chain", "太阳病，发热，汗出，恶风，脉缓者，名为中风。"]) == 0
    assert capsys.readouterr().out.startswith("# 传播链：")


# ------------------------------------------------------------------ the output schemas of docs/tasks.md
def test_results_match_the_schemas_of_the_task_specification(pack, study, commentary_study, school_study, harness):
    from taochronos.protocol.schema import validate
    from taochronos.plugins.classics.study.schemas import STUDY_SCHEMAS

    pid = next(iter(harness.corpus.passages())).id

    def tool(name: str, args: dict):
        out = harness.scheduler.execute(ToolCall(name, args), actor=Actor.kernel())
        assert out.ok, out.error
        return out.result

    results = {
        "normalize": tool("philology.normalize", {"text": "太陽病，發熱汗出"}),
        "punctuate": study.punctuate("太阳病头痛发热汗出恶风桂枝汤主之"),
        "clause": study.clause("太阳病，头痛，发热，汗出，恶风，桂枝汤主之。"),
        "claims": tool("kg.extract_claims", {"passage_id": pid}),
        "names": study.names("山药"),
        "glosses": commentary_study.glosses("几几"),
        "concordance": commentary_study.concordance("太阳之为病，脉浮，头项强痛而恶寒。"),
        "variants": commentary_study.variants("shanghanlun"),
        "reuse": commentary_study.reuse("太阳之为病，脉浮，头项强痛而恶寒。"),
        "chain": commentary_study.chain("太阳之为病，脉浮，头项强痛而恶寒。"),
        "transmission": commentary_study.transmission("shanghanlun", clauses=3),
        "commentaries": commentary_study.commentaries("太阳之为病，脉浮，头项强痛而恶寒。"),
        "stemma": commentary_study.stemma("shanghanlun"),
        "provenance": tool("validation.provenance_chain", {"object_id": pid}),
        "verify_quote": tool("validation.verify_quote", {"quote": "消渴"}),
        "network": study.network("桂枝汤"),
        "pairs": study.pairs("桂枝", min_support=1),
        "formula": study.formula("桂枝汤"),
        "term": study.term("消渴"),
        "senses": study.senses("消渴"),
        "schools": school_study.schools("温病"),
        "disputes": commentary_study.disputes(),
        "search": tool("classics.search", {"query": "消渴", "k": 3}),
    }
    assert set(results) == set(STUDY_SCHEMAS)
    for name, result in results.items():
        assert not validate(result, STUDY_SCHEMAS[name]), (name, validate(result, STUDY_SCHEMAS[name])[:5])
