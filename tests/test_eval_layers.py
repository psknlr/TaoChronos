"""The evaluation layers the audit asked for — invariants and hard interpretive cases — and the readings they measure."""

from __future__ import annotations

import dataclasses

import pytest

from conftest import HOME
from taochronos.evals.base import EvalContext
from taochronos.protocol.claims import Claim, ClaimArgument, ClaimRelation, ExtractionInfo, Role
from taochronos.protocol.documents import TemporalContext, YearRange
from taochronos.verification.support import assess_support, statement_frame


@pytest.fixture(scope="module")
def ectx(tmp_path_factory):
    return EvalContext(home=HOME, data_dir=tmp_path_factory.mktemp("eval-layers"), quick=True)


# ------------------------------------------------------------------ layer 1: invariants
def test_every_invariant_holds_on_the_default_harness(ectx):
    from taochronos.evals import SUITES

    result = SUITES["invariants"](ectx)
    m = result.metrics
    assert m["broken"] == [] and m["held"] == m["exercised"] and m["invariants"] >= 19
    assert all(r["held"] in (True, None) for r in result.details)


def test_an_invariant_breaks_when_its_boundary_is_removed(ectx):
    from taochronos.evals.boundaries import INVARIANTS, Broken
    from taochronos.kernel.hooks import HookPoint

    h, _ = ectx.pipeline()
    probe = next(fn for iid, *_, fn in INVARIANTS if iid == "I04")
    saved = [x for x in h.hooks._hooks[HookPoint.BEFORE_CLAIM_COMMIT] if x.name == "semantic_support"]
    h.hooks.unregister("semantic_support")
    try:
        with pytest.raises(Broken):
            probe(h, ectx)
    finally:
        for x in saved:
            h.hooks.register(HookPoint.BEFORE_CLAIM_COMMIT, x.name, x.fn, x.priority)
    assert probe(h, ectx)  # and holds again once the boundary is back


# ------------------------------------------------------------------ layer 2: hard interpretive cases
def test_the_interpretive_suite_scores_per_class_and_split(ectx):
    from taochronos.evals import SUITES

    result = SUITES["interpretive"](ectx)
    m = result.metrics
    assert m["gold_errors"] == [] and m["dev"]["accuracy"] == 1.0  # the dev cases are the regression tests of the rules
    assert set(m["accuracy_by_class"]) == {"relation_inversion", "negation_scope", "consequence", "reported_view",
                                           "omitted_condition", "witness_mixing", "date_dispute"}
    assert m["heldout"]["n"] >= 70 and m["heldout"]["unsafe"] <= 2  # the two textual cruxes (公案) are reported, not hidden


# ------------------------------------------------------------------ the readings measured
def _claim(text: str, relation: str, quote: str, *args: tuple) -> Claim:
    lo = text.find(quote)
    arguments = []
    for role, surface, *flags in args:
        if "referent" in flags:
            arguments.append(ClaimArgument(role=Role(role), surface=surface, qualifiers={"referent": "之"}))
            continue
        at = text.find(surface, lo)
        arguments.append(ClaimArgument(role=Role(role), surface=surface, start=at, end=at + len(surface), negated="negated" in flags))
    return Claim(id="c", passage_id="p", book_id="b", relation=ClaimRelation(relation), arguments=arguments, quote=quote,
                 start=lo, end=lo + len(quote), temporal=TemporalContext(), extraction=ExtractionInfo(method="manual"))


def test_a_claim_that_asserts_what_the_quote_denies_is_contradicted():
    text = "夫温疫之为病，非风、非寒、非暑、非湿，乃天地间别有一种异气所感。"
    quote = text[:-1]
    wrong = _claim(text, "causes", quote, ("disease", "温疫"), ("etiology", "风"), ("etiology", "异气"))
    right = _claim(text, "causes", quote, ("disease", "温疫"), ("etiology", "风", "negated"), ("etiology", "异气"))
    assert assess_support(wrong, text).verdict == "contradicts" and assess_support(right, text).verdict == "supports"
    double = "凡积久饮酒，未有不成消渴。"  # a double negation asserts
    assert assess_support(_claim(double, "causes", double[:-1], ("etiology", "饮酒"), ("disease", "消渴")), double).verdict == "supports"


def test_an_intervention_named_by_zhi_is_read_through_its_pronoun():
    text = "桂枝本为解肌，若其人脉浮紧，发热汗不出者，不可与之也。"
    quote = "若其人脉浮紧，发热汗不出者，不可与之也"
    assert assess_support(_claim(text, "indicated_for", quote, ("formula", "桂枝汤", "referent")), text).verdict == "contradicts"
    assert assess_support(_claim(text, "contraindicated", quote, ("formula", "桂枝汤", "referent")), text).verdict == "supports"
    warn = "服之则厥逆，筋惕肉瞤，此为逆也。"
    assert assess_support(_claim(warn, "contraindicated", warn[:-1], ("formula", "大青龙汤", "referent")), warn).verdict == "supports"


def test_the_frame_ends_a_report_where_the_author_answers_it():
    text = "或曰得毋为积滞而设与余曰非也邪气客于下焦气血壅滞郁而为积"
    frame = lambda q: statement_frame(text, text.find(q), text.find(q) + len(q))  # noqa: E731
    assert frame("为积滞而设")["stance"] == "rejected" and frame("邪气客于下焦")["stance"] == "asserted"
    cited = "《近效极要》论：消渴旧来以为难疗"
    assert statement_frame(cited, cited.find("消渴"), len(cited))["stance"] == "reported"


def test_the_frame_keeps_the_condition_a_quote_leaves_out_but_not_a_definition():
    text = "二阳并病，太阳证罢，但发潮热，手足漐漐汗出，大便难而谵语者，下之则愈，宜大承气汤。"
    q = "宜大承气汤"
    assert any("谵语" in c for c in statement_frame(text, text.find(q), text.find(q) + len(q))["conditions"])
    definition = "夫消渴者，渴不止，小便多是也。"
    assert statement_frame(definition, 5, len(definition) - 1)["conditions"] == []


def test_disputed_dates_are_ordered_by_ranges_and_sit_on_one_side_of_a_cutoff_only_wholly():
    yunqi, zhubing = YearRange(100, 762), YearRange(610, 610)
    assert yunqi.order(zhubing) == "undetermined" and YearRange(-300, 25).order(YearRange(200, 219)) == "before"
    assert yunqi.side_of(618) == "straddling" and zhubing.side_of(618) == "before" and YearRange(652, 652).side_of(618) == "after"


# ------------------------------------------------------------------ extraction: prognosis and the misreadings the checks found
@pytest.fixture(scope="module")
def extract(harness):
    ex = harness.capabilities.get("extractor")
    base = harness.corpus.passage("shanghanlun.c071")
    return lambda text: ex.extract(dataclasses.replace(base, id="probe", text=text, variants=[]))


def test_prognosis_is_extracted_with_its_outcome(extract, harness):
    c071 = harness.capabilities.get("extractor").extract(harness.corpus.passage("shanghanlun.c071"))
    prog = [c for c in c071 if c.relation == ClaimRelation.PROGNOSIS]
    assert prog and {"disease:太阳病", "condition:发汗后"} <= set(prog[0].terms()) and prog[0].context.startswith("outcome:favourable")
    dies = [c for c in extract("伤寒下利，日十余行，脉反实者死。") if c.relation == ClaimRelation.PROGNOSIS]
    assert dies and dies[0].context.startswith("outcome:unfavourable")
    means = [c for c in extract("脉浮无汗而喘者，发汗则愈。") if c.relation == ClaimRelation.PROGNOSIS][0]
    assert [a.term_id for a in means.arguments if a.qualifiers.get("means")] == ["treatment_method:发汗"]
    assert not [c for c in extract("上工不治已病治未病。") if c.relation == ClaimRelation.PROGNOSIS]  # a principle, not an outcome


def test_the_extractor_no_longer_reads_a_prohibition_as_a_prescription(extract):
    claims = extract("伤寒脉浮，发热无汗，其表不解，不可与白虎汤。")
    assert not [c for c in claims if c.relation == ClaimRelation.INDICATED_FOR]
    assert not [c for c in extract("脉实者，宜下之，脉浮虚者，宜发汗。") if c.extraction.rule == "ADV"]  # 宜下之 recommends
    assert not [c for c in extract("三法皆不可用者，亦非三者攻之所可能及也。") if c.extraction.rule == "TREAT"]
    same = [c for c in extract("太阳中风，脉浮紧，不汗出而烦躁者，大青龙汤主之，若脉微弱，汗出恶风者，不可服之。")
            if c.relation == ClaimRelation.CONTRAINDICATED]
    assert same and all(a.start is None for a in same[0].args(Role.FORMULA))  # 之 names it by reference, not by its span
