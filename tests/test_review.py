"""Rules first, the model second: the review of uncertain decisions and the cited summaries of the study layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from taochronos.capabilities.judge import Judge
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.punctuation import MARKS
from taochronos.plugins.classics.study.review import review_disputes, review_punctuation
from taochronos.plugins.models.scripted import ScriptedProvider

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(HOME / "domains" / "classics")


@pytest.fixture
def study(pack) -> StudyService:
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "study")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


@pytest.fixture
def commentary_study(pack) -> StudyService:
    corpus = Corpus.load(HOME / "evals" / "gold" / "commentaries")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def _answer_all(label_of):
    """A scripted model that answers every asked id with ``label_of(item)``."""

    def step(request):
        rows = json.loads(request.messages[0].text.split("：\n", 1)[1].split("\n\nReturn only")[0])
        decisions = [{"id": r["id"], "label": label_of(r), "reason": "测试"} for r in rows]
        from taochronos.capabilities.llm import LLMResponse, Usage

        return LLMResponse(text=json.dumps({"decisions": decisions}, ensure_ascii=False), tool_uses=[], stop_reason="end_turn",
                           usage=Usage(10, 10), model="m")
    return step


def test_the_model_only_picks_marks_and_the_text_is_kept(study):
    text = "太阳病发热汗出恶风脉缓者名为中风太阳病或已发热或未发热必恶寒体痛呕逆脉阴阳俱紧者名为伤寒"
    model = study._punct.model()
    marked = model.punctuate(text, study.normalize)
    assert marked["review"], "the model leaves some gaps uncertain"
    # a model that flips every uncertain decision: marks where there were none, none where there were marks
    flip = _answer_all(lambda r: "，" if r["current"] == "none" else "none")
    judge = Judge(ScriptedProvider([flip] * 20), "m")
    overrides, summary, rows = review_punctuation(judge, text, marked)
    assert summary["asked"] == len(marked["review"]) and summary["changed"] == summary["answered"] > 0
    again = model.punctuate(text, study.normalize, overrides=overrides)
    assert again["preserved"] and "".join(ch for ch in again["text"] if ch not in MARKS) == text
    for at, mark in overrides.items():
        placed = any(m["at"] == at for m in again["marks"])
        assert placed == (mark is not None)


def test_study_punctuate_reports_the_review_and_scores_both(study):
    passage = next(p for p in study.corpus.passages() if sum(ch in MARKS for ch in p.text) > 3 and len(p.text) > 30)
    agree = _answer_all(lambda r: r["current"])
    study.judge = Judge(ScriptedProvider([agree] * 20), "m")
    r = study.punctuate(passage_id=passage.id)
    review = r["llm_review"]
    assert review["judge"] == "scripted:m" and review["summary"]["changed"] == 0
    assert review["summary"]["agreement"] in (None, 1.0) and r["preserved"]
    if review["summary"]["asked"]:
        assert r["against_editors_reviewed"] == r["against_editors"]  # nothing changed, nothing gained or lost


def test_a_failed_model_leaves_the_rules_in_charge(study):
    study.judge = Judge(ScriptedProvider([{"text": "我无法回答"}] * 40), "m")
    r = study.punctuate("太阳病发热汗出恶风脉缓者名为中风太阳病或已发热或未发热必恶寒体痛呕逆脉阴阳俱紧者名为伤寒")
    study.judge = None
    plain = study.punctuate("太阳病发热汗出恶风脉缓者名为中风太阳病或已发热或未发热必恶寒体痛呕逆脉阴阳俱紧者名为伤寒")
    assert r["punctuated"] == plain["punctuated"]
    assert r["llm_review"]["summary"]["failed_batches"] >= 1 and r["llm_review"]["summary"]["changed"] == 0


def test_dispute_stances_are_rereviewed_only_where_the_rules_are_weak():
    records = [
        {"stance": "reject", "sentence": "丹溪谓阳常有余，此说非也。", "target": "丹溪", "passage_id": "p1", "marker": "非也"},
        {"stance": "cite", "sentence": "东垣云脾胃虚则九窍不通。", "target": "东垣", "passage_id": "p2", "marker": None},
        {"stance": "cite", "sentence": "丹溪之论，然不可执一。", "target": "丹溪", "passage_id": "p3", "marker": None},
    ]
    judge = Judge(ScriptedProvider([_answer_all(lambda r: "reject")]), "m")
    summary, rows = review_disputes(judge, records)
    assert summary["asked"] == 2  # the bare citation without a contrastive word is not asked
    assert records[0]["stance"] == "reject" and records[0]["decided_by"] == "both"
    assert records[1]["stance"] == "cite" and records[1]["decided_by"] == "rule"
    assert records[2]["stance"] == "reject" and records[2]["rule_stance"] == "cite" and records[2]["decided_by"] == "model"


def test_commentaries_get_a_cited_summary(commentary_study):
    def summary(request):
        from taochronos.capabilities.llm import LLMResponse, Usage

        text = request.messages[0].text
        first = text.split("[C1] ", 1)[1].split("\n", 1)[0]
        quote = first.split("）", 1)[1].strip()[:4]
        body = {"sentences": [{"text": f"首家注以「{quote}」释之。", "cites": ["C1"]},
                              {"text": "诸家皆以为表证。", "cites": ["C99"]}]}
        return LLMResponse(text=json.dumps(body, ensure_ascii=False), tool_uses=[], stop_reason="end_turn", usage=Usage(5, 5), model="m")

    commentary_study.judge = Judge(ScriptedProvider([summary]), "m")
    r = commentary_study.commentaries("太阳之为病，脉浮，头项强痛而恶寒。")
    s = r["llm_summary"]
    assert s["ok"] and len(s["sentences"]) == 1 and s["sentences"][0]["cites"] == ["C1"]
    assert s["dropped"] and s["dropped"][0]["why"].startswith("cites no known evidence")
    assert s["evidence"][0]["id"] == "C1"
