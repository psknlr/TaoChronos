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
