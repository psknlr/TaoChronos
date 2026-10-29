"""针灸推理的协调与审核 (ADR 0027) — study.acupuncture_reason and study.acupuncture_audit.

The 39 acceptance cases of the design package (tests/fixtures/acupuncture_reasoning, as delivered) run against the
coordinator and the audit: the assessment status, the findings that must and must not appear, the candidates and the
educational mappings, the facts that must be preserved, the conclusions that must not be asserted (outside the
conclusions a finding blocks), two questions at most — and every result checked against the return contract.  The
positive review cases (AC08, AC09) run only because this test host issues their records through a signed server-side
store, bound to the current knowledge and rule versions; a review claimed in the arguments authorizes nothing.  Then the
pieces: the contract checker, the three-valued rule language and the rule pack's own consistency, the review store's
binding, the text reader (denials, questions, other people, the past, timing), the methods (policy, conflicts, the
display budget), the shared screen of the legacy paths, the tools through the scheduler, the page and the CLI."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from taochronos.cli import main
from taochronos.kernel import Actor, ToolCall
from taochronos.plugins.classics import Corpus, DomainPack
from taochronos.plugins.classics.study import StudyService
from taochronos.plugins.classics.study.acupuncture_reasoning import (AcupunctureReasoning, Contracts, ReviewStore, evaluate,
                                                                     observations_digest)
from taochronos.plugins.classics.study.render import markdown

HOME = Path(__file__).resolve().parents[1]
SUITE = json.loads((HOME / "tests" / "fixtures" / "acupuncture_reasoning" / "acceptance_cases.json").read_text(encoding="utf-8"))
CASES = {c["case_id"]: c for c in SUITE["cases"]}
KEY = b"test-host-review-key"


@pytest.fixture(scope="module")
def study() -> StudyService:
    pack = DomainPack(HOME / "domains" / "classics")
    corpus = Corpus.load(HOME / "tests" / "fixtures" / "acupuncture")
    corpus.normalize = pack.variants.normalize_text
    return StudyService(pack, corpus)


def _host(study: StudyService) -> tuple[AcupunctureReasoning, ReviewStore]:
    """The test host: an engine with its own review store, the suite's trusted fixtures issued into it server side."""
    store = ReviewStore(KEY)
    eng = AcupunctureReasoning(study._acupuncture, reviews=store)
    for c in SUITE["cases"]:
        if c.get("trusted_server_fixture"):
            store.issue({**c["trusted_server_fixture"], "knowledge_version": eng.knowledge_version, "rulepack_version": eng.rulepack_version})
    return eng, store


@pytest.fixture(scope="module")
def host(study):
    return _host(study)


@pytest.fixture(scope="module")
def eng(host) -> AcupunctureReasoning:
    return host[0]


def run(eng: AcupunctureReasoning, case_id: str) -> dict:
    req = CASES[case_id]["request"]
    return (eng.reason if req["tool"] == "study.acupuncture_reason" else eng.audit)(deepcopy(req["arguments"]))


def _without_blocked(v):
    if isinstance(v, dict):
        return {k: _without_blocked(x) for k, x in v.items() if k != "blocked_conclusions"}
    if isinstance(v, list):
        return [_without_blocked(x) for x in v]
    return v


def obs_of(r: dict, concept: str) -> list[dict]:
    return [o for o in r["normalized_observations"] if o["concept_id"] == concept]


def states_of(r: dict) -> set[tuple[str, str, str]]:
    return {(s["organ_entity"], s["yin_yang_aspect"], s["state"]) for s in r["organ_states"]}


# what each case's must_preserve says, as checks on the result
PRESERVE = {
    "AC02": lambda r: [o["status"] for o in obs_of(r, "symptom.tinnitus")] == ["absent"],
    "AC03": lambda r: ("stomach", "unspecified", "deficiency") in states_of(r) and not any(s[0] == "spleen" for s in states_of(r)),
    "AC04": lambda r: ("large_intestine", "unspecified", "deficiency") in states_of(r) and not any(s[0] == "lung" for s in states_of(r)),
    "AC05": lambda r: ("kidney", "yang", "deficiency") in states_of(r) and not any(s[:2] == ("kidney", "yin") for s in states_of(r)),
    "AC06": lambda r: states_of(r) == {("liver", "unspecified", "unknown")},
    "AC14": lambda r: (lambda row: row["table"]["channel"] == "LR" and row["table"]["point_phase"] == "earth" and row["table"]["channel_phase"] == "wood")(r["plan_review"][0]),
    "AC15": lambda r: r["plan_review"][0]["input_alias"] == "SJ3" and r["plan_review"][0]["normalized_point_id"] == "TE3" and r["normalized_point_ids"] == ["TE3"],
    "AC21": lambda r: [o["status"] for o in obs_of(r, "sign.tongue")] == ["unknown"] and [o["status"] for o in obs_of(r, "sign.pulse")] == ["unknown"],
    "AC22": lambda r: [o["status"] for o in obs_of(r, "hearing.loss")] == ["conflicting"] and [o["status"] for o in obs_of(r, "hearing.sudden_loss")] == ["unknown"],
    "AC26": lambda r: {("spleen", "qi", "deficiency"), ("stomach", "unspecified", "excess")} <= states_of(r),
    "AC28": lambda r: "UNTRUSTED_REVIEW_CLAIM" in [f["code"] for f in r["findings"]] and not r["point_candidates"] and not r["review"]["verified"],
    "AC29": lambda r: r["execution_status"] == "invalid_parameters" and "verified" in " ".join(f["message"] for f in r["findings"]),
    "AC34": lambda r: states_of(r) == {("liver", "unspecified", "balanced")},
    "AC35": lambda r: states_of(r) == {("liver", "unspecified", "mixed")},
    "AC37": lambda r: sorted((o["status"], o["subject_scope"], o["time"]["temporal_scope"]) for o in obs_of(r, "symptom.tinnitus"))
                      == [("absent", "current_case_subject", "current"), ("present", "other_person", "past")]
                      and [(o["subject_scope"], o["time"]["temporal_scope"]) for o in obs_of(r, "hearing.loss")] == [("current_case_subject", "past")],
}


# ------------------------------------------------------------------ the acceptance suite
@pytest.mark.parametrize("case_id", list(CASES))
def test_acceptance_case(eng, case_id):
    case, exp = CASES[case_id], CASES[case_id]["expected"]
    r = run(eng, case_id)
    name = "reasonReturn" if case["request"]["tool"] == "study.acupuncture_reason" else "auditReturn"
    assert eng.contracts.errors(r, name) == []
    assert (r["execution_status"] == "completed") == exp["request_schema_valid"]
    assert r["assessment_status"] in exp["assessment_status_any_of"]
    codes = [f["code"] for f in r["findings"]]
    assert set(exp["must_include_findings"]) <= set(codes) and not set(exp["must_not_include_findings"]) & set(codes)
    cands = {(p["point_id"], p["intent"]["traditional_manipulation"]) for p in r.get("point_candidates", [])}
    assert {(x["point_id"], x["intent"]) for x in exp["must_include_candidates"]} <= cands
    assert not {(x["point_id"], x["intent"]) for x in exp["must_not_include_candidates"]} & cands
    maps = {(p["point_id"], p["intent"]["traditional_manipulation"]) for p in r.get("educational_mappings", [])}
    assert {(x["point_id"], x["intent"]) for x in exp.get("must_include_educational_mappings") or []} <= maps
    assert len(r["questions"]) <= exp["questions_maximum"]
    text = json.dumps(_without_blocked(r), ensure_ascii=False)
    assert not [a for a in exp["must_not_assert"] if a in text]
    if case_id in PRESERVE:
        assert PRESERVE[case_id](r)
    if r["assessment_status"] != "candidate_review":
        assert not r.get("point_candidates")


def test_acceptance_cases_agree_with_a_reference_validator(eng):
    jsonschema = pytest.importorskip("jsonschema")  # not a dependency: checked where it is installed
    defs = eng.contracts.defs
    for c in SUITE["cases"]:
        req = c["request"]
        args_name = "reasonParameters" if req["tool"] == "study.acupuncture_reason" else "auditParameters"
        ref = jsonschema.Draft202012Validator({"$defs": defs, "$ref": f"#/$defs/{args_name}"})
        assert ref.is_valid(req["arguments"]) == (not eng.contracts.errors(req["arguments"], args_name)) == c["expected"]["request_schema_valid"]
        out = jsonschema.Draft202012Validator({"$defs": defs, "$ref": f"#/$defs/{args_name.replace('Parameters', 'Return')}"})
        assert not list(out.iter_errors(run(eng, c["case_id"])))


def test_the_positive_review_cases_rest_on_the_server_record_and_nothing_else(study, eng):
    r = run(eng, "AC08")
    c = r["point_candidates"][0]
    assert (c["point_id"], c["channel_phase"], c["point_phase"], c["five_shu_class"]) == ("LR2", "wood", "fire", "ying_spring")
    assert c["modality"] == "undetermined" and c["modality_status"] == "requires_separate_assessment" and c["usage_scope"] == "candidate_review_only"
    assert c["premise_refs"][0] == "AC08.review.liver.excess" and r["review"]["verified"] and all(r["review"]["binding"].values())
    assert c["clinical_efficacy"]["does_not_validate_theory_automatically"] and c["theory_support"]["level"] == "classical"
    assert r["candidate_display"] == {"budget": 6, "total_validated_candidates": 1, "displayed_count": 1, "remaining_count": 0,
                                      "budget_is_not_treatment_point_count": True}
    nine = run(eng, "AC09")["point_candidates"][0]
    assert (nine["point_id"], nine["point_phase"], nine["intent"]["traditional_manipulation"]) == ("LR8", "water", "tonify")
    bare = AcupunctureReasoning(study._acupuncture, reviews=ReviewStore(KEY))  # the same request, no record on this server
    r = bare.reason(deepcopy(CASES["AC08"]["request"]["arguments"]))
    assert r["assessment_status"] == "needs_information" and not r["point_candidates"]
    assert "REVIEW_CONTEXT_UNVERIFIED" in [f["code"] for f in r["findings"]]


# ------------------------------------------------------------------ the contract checker
def test_the_contract_checker(eng):
    c = eng.contracts
    assert c.errors({"mode": "knowledge", "query": "x"}, "reasonParameters") == []
    assert any("unexpected property 'verified'" in e["message"] for e in c.errors({"mode": "knowledge", "query": "x", "verified": True}, "reasonParameters"))
    assert [e["path"] for e in c.errors({"mode": "knowledge", "query": "x", "requested_methods": ["all"]}, "reasonParameters")] == ["/requested_methods/0"]
    assert c.errors({"mode": "case_review", "query": "x"}, "reasonParameters")  # case_review needs a case (if / then)
    assert c.errors({"mode": "knowledge", "query": "x", "requested_methods": ["saam", "saam"]}, "reasonParameters")  # uniqueItems
    assert c.errors({"mode": "knowledge", "query": "x", "requested_points": ["ST36\n"]}, "reasonParameters")  # ^…$ is the whole string
    assert c.errors({"mode": "knowledge", "query": "x", "proposed_claims": [], "proposed_plan": []}, "auditParameters")  # anyOf
    assert c.errors({"mode": "knowledge", "query": "x", "policy": {"max_questions_per_turn": 3}}, "reasonParameters")
    assert c.errors({"mode": "knowledge", "query": "x", "policy": {"allow_custom_unvalidated_rules": True}}, "reasonParameters")
    assert not c.errors({"present": "symptom.tinnitus"}, "dslExpression") and c.errors({"not": {"present": "x"}}, "dslExpression")
    assert c.errors({"all": [{"present": "a"}], "any": [{"present": "b"}]}, "dslExpression")
    small = Contracts({"$defs": {"n": {"type": "integer"}, "b": {"type": "boolean"}}})
    assert small.errors(1, "n") == [] and small.errors(True, "n") and small.errors(1, "b")


def test_invalid_arguments_are_answered_as_invalid_never_defaulted(eng):
    for args in (None, [], {"mode": "knowledge"}, {"mode": "advice", "query": "x"}, {"mode": "knowledge", "query": "x", "requested_methods": "nanjing69"},
                 {"mode": "knowledge", "query": "x", "requested_methods": ["nanjing69", "everything"]}):
        r = eng.reason(args)
        assert r["execution_status"] == "invalid_parameters" and r["assessment_status"] is None and not r["point_candidates"]
        assert r["method_resolution"]["effective_methods"] == [] and eng.contracts.errors(r, "reasonReturn") == []
    r = eng.reason({"mode": "knowledge", "query": "x", "requested_methods": ["everything"]})
    assert [f["code"] for f in r["findings"]] == ["INVALID_METHOD"] and "不回退" in r["findings"][0]["message"]
    a = eng.audit({"mode": "knowledge", "query": "x", "proposed_plan": [{"point_id": "LR2", "intent": "drain"}]})
    assert a["execution_status"] == "invalid_parameters" and eng.contracts.errors(a, "auditReturn") == []


def test_what_the_schema_cannot_say_is_checked_too(eng):
    base = deepcopy(CASES["AC01"]["request"]["arguments"])
    bad = deepcopy(base)
    bad["case"]["observations"][0]["original_spans"][0].update(start=1, end=3)  # 鸣。 is not 耳鸣
    assert eng.reason(bad)["execution_status"] == "invalid_parameters"
    bad = deepcopy(base)
    bad["case"]["observations"][0]["original_spans"][0]["source_message_id"] = "nowhere"
    assert eng.reason(bad)["execution_status"] == "invalid_parameters"
    bad = deepcopy(CASES["AC03"]["request"]["arguments"])
    bad["case"]["observations"][1]["entity"]["organ_entity"] = "spleen"  # organ.stomach.state about the spleen: one entity is not another
    r = eng.reason(bad)
    assert r["execution_status"] == "invalid_parameters" and "one organ entity is not another" in r["findings"][0]["message"]
    bad = deepcopy(CASES["AC06"]["request"]["arguments"])
    bad["case"]["organ_states"][0]["observation_refs"] = ["AC06.obs9"]
    assert eng.reason(bad)["execution_status"] == "invalid_parameters"


# ------------------------------------------------------------------ the rule language and the rule pack
def test_the_rule_language_is_three_valued():
    facts = {"a": {"status": "present", "value": True}, "b": {"status": "absent", "value": False}, "u": {"status": "unknown", "value": None},
             "c": {"status": "conflicting", "value": None}, "s": {"status": "present", "value": "excess"}}
    assert evaluate({"present": "a"}, facts) is True and evaluate({"present": "b"}, facts) is False
    assert evaluate({"present": "u"}, facts) is None and evaluate({"present": "c"}, facts) is None and evaluate({"present": "x"}, facts) is None
    assert evaluate({"all": [{"present": "a"}, {"present": "u"}]}, facts) is None
    assert evaluate({"all": [{"present": "b"}, {"present": "u"}]}, facts) is False
    assert evaluate({"any": [{"present": "a"}, {"present": "u"}]}, facts) is True
    assert evaluate({"any": [{"present": "b"}, {"present": "u"}]}, facts) is None
    assert evaluate({"eq": {"fact": "b", "value": False}}, facts) is True and evaluate({"eq": {"fact": "a", "value": 1}}, facts) is False
    assert evaluate({"in": {"fact": "s", "values": ["deficiency", "excess"]}}, facts) is True
    assert evaluate({"eq": {"fact": "u", "value": None}}, facts) is None  # unknown is no value, not null
    with pytest.raises(ValueError):
        evaluate({"script": "1 + 1"}, facts)


def test_the_rule_pack_holds_together(eng):
    pack = eng.pack
    assert pack["operators"] == ["all", "any", "eq", "in", "present"]
    codes = [r["effect"]["code"] for r in pack["rules"]]
    for code in ("URGENT_HEARING_ASSESSMENT", "ETIOLOGIC_ASSESSMENT_NEEDED", "MISSING_DECISION_CRITICAL_INFORMATION", "ANALOGY_NOT_OBSERVED_PRESSURE",
                 "CUSTOM_RULE_DISABLED", "RELATION_TYPE_MISMATCH", "BIETONG_NONTRANSITIVE", "PHASE_INTENT_MODALITY_CONFLATION",
                 "FLUID_YIN_CONFLATION", "AGE_NOT_PATTERN", "EVIDENCE_SCOPE_MISMATCH", "UNTRUSTED_REVIEW_CLAIM", "STALE_REVIEW_CONTEXT", "OPPOSED_INTENTIONS"):
        assert code in codes
    assert all(len(q["zh"]) <= 100 and len(q["en"]) <= 100 for q in pack["questions"])
    assert all(h["status"] == "disabled" for h in pack["hypotheses"])
    assert all(x in pack["sources"] for m in pack["methods"].values() for x in m["rule_source"])
    for broken in ({"present": "claim.never_declared"}, {"not": {"present": "symptom.tinnitus"}}):
        bad = deepcopy(pack)
        bad["rules"][0] = {**bad["rules"][0], "when": broken}
        with pytest.raises(ValueError):
            eng.check_pack(bad)
    bad = deepcopy(pack)
    bad["rules"][0]["sources"] = ["src_invented"]
    with pytest.raises(ValueError):
        eng.check_pack(bad)
    rel = pack["relations"]["bietong"]
    assert {(r["from"], r["to"]) for r in rel} == {("heart", "gallbladder"), ("liver", "large_intestine"), ("spleen", "small_intestine"),
                                                    ("lung", "bladder"), ("kidney", "sanjiao")}


def test_a_broken_pack_or_a_broken_result_is_reported_not_raised(study, monkeypatch):
    e = AcupunctureReasoning(study._acupuncture, reviews=ReviewStore(KEY))
    monkeypatch.setattr(e, "_reason_out", lambda run: {"artifact_type": "reason_result"})
    r = e.reason({"mode": "knowledge", "query": "肝实"})
    assert r["execution_status"] == "dependency_unavailable" and r["assessment_status"] is None
    assert r["findings"][0]["code"] == "OUTPUT_CONTRACT_VIOLATION" and e.contracts.errors(r, "reasonReturn") == []
    e2 = AcupunctureReasoning(study._acupuncture, reviews=ReviewStore(KEY))
    monkeypatch.setattr(type(e2.s.b), "data", lambda self, name: {} if name == "acupuncture_reasoning.yaml" else {})
    r = e2.reason({"mode": "knowledge", "query": "肝实"})
    assert r["execution_status"] == "dependency_unavailable" and r["findings"][0]["code"] == "DEPENDENCY_UNAVAILABLE"


# ------------------------------------------------------------------ the review store and its binding
def _reviewed_case(case_id="R1", version=1, role="domain_reviewer", modes=("method_compare",)):
    args = deepcopy(CASES["AC08"]["request"]["arguments"])
    args["case"]["case_id"], args["case"]["case_version"] = case_id, version
    return args


def test_a_review_record_is_bound_to_its_case_and_verified_by_its_signature(study):
    store = ReviewStore(KEY)
    e = AcupunctureReasoning(study._acupuncture, reviews=store)
    args = _reviewed_case()
    rec = {**CASES["AC08"]["trusted_server_fixture"], "review_context_ref": "rv.1", "case_id": "R1", "case_version": 1,
           "normalized_observations_sha256": observations_digest(args["case"]["observations"]),
           "knowledge_version": e.knowledge_version, "rulepack_version": e.rulepack_version}
    store.issue(rec)
    args["review_context_ref"] = "rv.1"
    assert e.reason(deepcopy(args))["assessment_status"] == "candidate_review"
    changed = deepcopy(args)
    changed["case"]["observations"][0]["value"] = "deficiency"  # the facts changed: the digest no longer matches
    changed["case"]["organ_states"][0]["state"] = "deficiency"
    r = e.reason(changed)
    assert r["assessment_status"] == "needs_information" and "STALE_REVIEW_CONTEXT" in [f["code"] for f in r["findings"]]
    as_case = deepcopy(args)
    as_case["mode"] = "case_review"  # a domain reviewer cannot authorize a clinical case review
    r = e.reason(as_case)
    assert "REVIEW_NOT_AUTHORIZED" in [f["code"] for f in r["findings"]] and not r["point_candidates"]
    store._records["rv.1"][0]["reviewed_conditions"][0]["state"] = "deficiency"  # a record altered after issue
    r = e.reason(deepcopy(args))
    assert "REVIEW_CONTEXT_UNVERIFIED" in [f["code"] for f in r["findings"]] and not r["point_candidates"]
    assert ReviewStore(None).load("rv.1") is None
    with pytest.raises(ValueError):
        ReviewStore(None).issue(rec)


def test_the_review_store_from_the_environment(tmp_path, monkeypatch):
    signer = ReviewStore(KEY)
    rec = {**CASES["AC08"]["trusted_server_fixture"], "review_context_ref": "env.1"}
    signer.issue(rec)
    stored, sig = signer._records["env.1"]
    path = tmp_path / "reviews.jsonl"
    path.write_text(json.dumps({"record": stored, "signature": sig}, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setenv("TAOCHRONOS_REVIEW_KEY", KEY.decode())
    monkeypatch.setenv("TAOCHRONOS_REVIEW_STORE", str(path))
    assert ReviewStore.from_env().load("env.1")["case_id"] == "AC08"
    monkeypatch.setenv("TAOCHRONOS_REVIEW_KEY", "another-key")
    assert ReviewStore.from_env().load("env.1") is None


# ------------------------------------------------------------------ the text reader
def _case(text: str, mode: str = "case_review", **kw) -> dict:
    a = {"mode": mode, "query": text, **kw}
    if mode == "case_review":
        a["case"] = {"case_id": "T1", "case_version": 1, "is_synthetic": True, "observations": [], "organ_states": [], "premise_claims": [],
                     "source_messages": [{"message_id": "m1", "text": text, "actor_kind": "patient"}], "case_subject_ref": "subject.T1"}
    return a


def statuses(r: dict) -> dict[str, str]:
    return {o["concept_id"]: o["status"] for o in r["normalized_observations"] if o["subject_scope"] == "current_case_subject"
            and o["time"]["temporal_scope"] == "current"}


def test_the_reader_keeps_denials_questions_others_and_the_past_apart(eng):
    r = eng.reason(_case("我现在没有耳鸣。父亲去年有耳鸣。"))
    assert statuses(r) == {"symptom.tinnitus": "absent"} and r["assessment_status"] == "needs_information"
    other = [o for o in r["normalized_observations"] if o["subject_scope"] == "other_person"]
    assert other and other[0]["subject_ref"] == "other:父亲" and other[0]["time"]["temporal_scope"] == "past"
    r = eng.reason(_case("耳鸣，听力有没有突然下降不清楚。"))  # a question is no denial: unknown, and asked
    assert "hearing.sudden_loss" not in {k for k, v in statuses(r).items() if v == "absent"}
    assert r["questions"][0]["question_id"] == "q.hearing_sudden"
    r = eng.reason(_case("先说有听力下降，随后又否认。"))
    assert statuses(r)["hearing.loss"] == "conflicting"
    r = eng.reason(_case("Tinnitus in the left ear for three weeks, no hearing loss, not pulsatile."))
    tin = obs_of(r, "symptom.tinnitus")[0]
    assert tin["laterality"] == "left" and tin["time"]["duration_hours"] == 504
    assert r["assessment_status"] == "needs_etiologic_assessment"  # persistent and unilateral


def test_timing_words_route_a_sudden_hearing_loss(eng):
    r = eng.reason(_case("前天突然左耳听不清，伴耳鸣。"))
    st = statuses(r)
    assert st["hearing.sudden_loss"] == st["hearing.onset_within_past_30_days"] == st["hearing.developed_within_72_hours"] == "present"
    assert r["assessment_status"] == "needs_urgent_assessment" and r["questions"] == [] and not r["pattern_hypotheses"]
    assert [f["code"] for f in r["findings"]] == ["URGENT_HEARING_ASSESSMENT"]  # nothing else is asked once the route is decided
    r = eng.reason(_case("耳鸣，突然听力下降。"))  # sudden, but when? the timing is asked, the urgency said
    assert r["assessment_status"] == "needs_information" and r["questions"][0]["question_id"] == "q.hearing_onset"
    assert "24 小时内" in next(f["message"] for f in r["findings"] if f["code"] == "MISSING_DECISION_CRITICAL_INFORMATION")
    r = eng.reason(_case("耳鸣三个月，听力逐渐下降。"))
    assert statuses(r)["hearing.sudden_loss"] == "absent" and r["questions"][0]["question_id"] == "q.pulsatile"
    assert eng.reason(_case("耳鸣去年就有，半年前听力下降。"))["assessment_status"] != "needs_urgent_assessment"


def test_a_complete_tinnitus_case_compares_the_patterns_without_a_probability(eng):
    r = eng.reason(_case("双耳耳鸣半年，按住耳朵会减轻，劳累后加重，腰膝酸软，没有听力下降，不是搏动性的。"))
    assert r["assessment_status"] == "pattern_comparison" and len(r["questions"]) <= 2
    by = {p["clinical_condition"]: p for p in r["pattern_hypotheses"]}
    assert by["tcm.pattern.kidney_essence_deficiency"]["status"] == "plausible"
    assert by["tcm.pattern.liver_gallbladder_fire"]["status"] == "contradicted"
    assert all("probability" not in json.dumps(p) for p in r["pattern_hypotheses"]) and r["clinical_condition_is_not_diagnosis_probability"]
    assert r["questions"][0]["question_id"] in ("q.kidney_signs", "q.deficiency_signs", "q.spleen_signs")  # the standing patterns first


def test_knowledge_mode_says_nothing_about_a_person(eng):
    r = eng.reason({"mode": "knowledge", "query": "我耳鸣两天了，怎么取穴？", "requested_methods": ["nanjing69"]})
    assert r["assessment_status"] == "educational_only" and not r["educational_mappings"]
    assert "CASE_CONTENT_IN_KNOWLEDGE_MODE" in [f["code"] for f in r["findings"]]
    r = eng.reason({"mode": "knowledge", "query": "肝实怎么取穴？"})
    assert r["assessment_status"] == "educational_only" and r["method_resolution"]["effective_methods"] == []


# ------------------------------------------------------------------ methods
def _compare(text: str, methods: list[str], **kw) -> dict:
    return {"mode": "method_compare", "query": text, "requested_methods": methods, **kw}


def test_school_and_deduction_methods_need_the_policy(eng):
    r = eng.reason(_compare("假设肝经实", ["saam", "interior_exterior"]))
    assert r["method_resolution"]["effective_methods"] == [] and "METHOD_NOT_ALLOWED_BY_POLICY" in [f["code"] for f in r["findings"]]
    r = eng.reason(_compare("假设肝经实", ["saam"], policy={"allow_school_methods": True}))
    assert {(m["point_id"], m["intent"]["traditional_manipulation"]) for m in r["educational_mappings"]} == {
        ("LR4", "tonify"), ("LU8", "tonify"), ("LR2", "reduce"), ("HT8", "reduce")}
    assert {m["theory_support"]["level"] for m in r["educational_mappings"]} == {"school"}


def test_methods_that_oppose_each_other_are_shown_apart_or_not_merged(study):
    store = ReviewStore(KEY)
    e = AcupunctureReasoning(study._acupuncture, reviews=store)
    r = e.reason(_compare("假设肝实，脾虚", ["nanjing69_cross"]))  # teaching: both shown, the difference said
    assert {("HT8", "reduce"), ("HT8", "tonify")} <= {(m["point_id"], m["intent"]["traditional_manipulation"]) for m in r["educational_mappings"]}
    assert "METHODS_DIFFER_IN_INTENT" in [f["code"] for f in r["findings"]]
    args = deepcopy(CASES["AC26"]["request"]["arguments"])  # 脾气虚 胃实 → a reviewed 肝实 脾气虚 case instead
    args["case"]["observations"][1].update(concept_id="organ.liver.state", value="excess",
                                           entity={"entity_kind": "functional_aspect", "entity_id": "zangfu.liver", "organ_entity": "liver", "yin_yang_aspect": "unspecified"})
    args["case"]["organ_states"][1].update(organ_entity="liver", phase_annotation="wood")
    args["requested_methods"], args["review_context_ref"] = ["nanjing69_cross"], "rv.opp"
    conds = [{"premise_id": "p.spleen", "clinical_condition": "c.spleen", "organ_entity": "spleen", "yin_yang_aspect": "qi", "state": "deficiency",
              "decision": "accepted_for_candidate_reasoning"},
             {"premise_id": "p.liver", "clinical_condition": "c.liver", "organ_entity": "liver", "yin_yang_aspect": "unspecified", "state": "excess",
              "decision": "accepted_for_candidate_reasoning"}]
    store.issue({**CASES["AC08"]["trusted_server_fixture"], "review_context_ref": "rv.opp", "case_id": "AC26", "case_version": 1,
                 "normalized_observations_sha256": observations_digest(args["case"]["observations"]), "reviewed_conditions": conds,
                 "knowledge_version": e.knowledge_version, "rulepack_version": e.rulepack_version})
    r = e.reason(args)
    assert r["assessment_status"] == "rule_conflict" and not r["point_candidates"] and r["summary"]["withheld"] == 2
    f = next(f for f in r["findings"] if f["code"] == "OPPOSED_INTENTIONS")
    assert f["candidate_refs"] == ["HT8"] and f["severity"] == "block"


def test_the_display_budget_is_a_display_budget(study):
    store = ReviewStore(KEY)
    e = AcupunctureReasoning(study._acupuncture, reviews=store)
    args = deepcopy(CASES["AC08"]["request"]["arguments"])
    args.update(requested_methods=["nanjing69", "nanjing69_cross", "saam"], policy={"allow_school_methods": True, "max_candidate_points": 2},
                review_context_ref="rv.budget")
    store.issue({**CASES["AC08"]["trusted_server_fixture"], "review_context_ref": "rv.budget",
                 "knowledge_version": e.knowledge_version, "rulepack_version": e.rulepack_version})
    r = e.reason(args)
    d = r["candidate_display"]
    assert r["assessment_status"] == "candidate_review" and (d["budget"], d["displayed_count"]) == (2, 2)
    assert d["total_validated_candidates"] == 6 and d["remaining_count"] == 4 and len(r["point_candidates"]) == 2


def test_relation_only_methods_give_typed_relations_not_points(eng):
    r = eng.reason(_compare("假设肾虚", ["bietong", "yuan_luo"]))
    rel = {x["relation_id"]: x for x in r["theory_relations"]}
    assert "bietong.kidney.sanjiao" in rel and "yuan_luo.KI3.BL58" in rel and "interior_exterior.KI.BL" in rel
    assert all(x["transitive"] is False and x["clinical_action"] == "none_without_independent_selection_rule" for x in rel.values())
    assert not r["educational_mappings"] and "RELATION_ONLY_METHOD" in [f["code"] for f in r["findings"]]


# ------------------------------------------------------------------ the audit
def test_the_audit_explains_a_disabled_hypothesis_only_when_asked(eng):
    r = run(eng, "AC12")
    h = r["claims_review"][0]["hypothesis"]
    assert h["status"] == "disabled" and "mapping_explained" not in h
    args = deepcopy(CASES["AC12"]["request"]["arguments"])
    args["policy"] = {"unvalidated_hypotheses": "explanation_only"}
    h = eng.audit(args)["claims_review"][0]["hypothesis"]
    assert h["mapping_explained"]["LR2"] == "tonify" and "默认停用" in h["mapping_note"]
    r = eng.audit({"mode": "knowledge", "query": "x", "proposed_claims": ["足三里能补气"]})
    assert r["claims_review"][0]["status"] == "no_rule" and "不是认可" in r["claims_review"][0]["note"]


def test_the_audit_checks_a_plan_against_the_point_table(eng):
    r = eng.audit({"mode": "knowledge", "query": "核对", "proposed_plan": [{"point_id": "KI3", "point_phase": "water"}, {"point_id": "LR99"},
                                                                         {"point_id": "SJ17", "channel": "SJ"}]})
    codes = [f["code"] for f in r["findings"]]
    assert "POINT_ATTRIBUTE_MISMATCH" in codes and "UNKNOWN_POINT" in codes and "POINT_ALIAS_NORMALIZED" in codes
    rows = {x["input_point_id"]: x for x in r["plan_review"]}
    assert rows["KI3"]["mismatches"] == ["point_phase"] and rows["KI3"]["table"]["point_phase"] == "earth"  # 太溪 is Earth, not Water
    assert rows["SJ17"]["normalized_point_id"] == "TE17" and rows["SJ17"]["mismatches"] == [] and not rows["LR99"]["known"]
    assert r["normalized_point_ids"] == ["KI3", "TE17"]


# ------------------------------------------------------------------ the legacy paths share the screen
def test_study_acupoints_shares_the_screen(study):
    r = study.acupoints("胃脘胀满，恶心")  # not a complaint the rule pack routes: unchanged
    assert not r["validation"]["withhold"] and r["prescription"]["core"]
    r = study.acupoints("耳鸣")
    assert r["validation"]["withhold"] and r["validation"]["assessment_status"] == "needs_information"
    assert not r["prescription"]["core"] and r["prescription"]["withheld"]["points"] > 0 and len(r["validation"]["questions"]) == 2
    r = study.acupoints(symptoms=["耳鸣"], regions=["耳"])  # the structured arguments are screened as well
    assert r["validation"]["withhold"]
    r = study.acupoints("前天突然左耳听不清，伴耳鸣")
    assert r["validation"]["assessment_status"] == "needs_urgent_assessment" and not r["combinations"] and not r["prescription"]["supplementary"]
    r = study.acupoints("双耳耳鸣半年，按住耳朵会减轻，没有听力下降，不是搏动性的")
    assert not r["validation"]["withhold"] and r["prescription"]["core"] and r["validation"]["assessment_status"] == "pattern_comparison"
    page = markdown("acupoints", study.acupoints("耳鸣"), study.signature())
    assert "## 共享校验：须先补充信息" in page and "听力有没有突然下降" in page


def test_study_wuxing_withholds_methods_only_before_an_urgent_assessment(study):
    r = study.wuxing("肝实 脾虚")
    assert r["methods"] and not r.get("withheld") and r["method_resolution"]["legacy_default"]
    r = study.wuxing("耳鸣 突然听力下降 昨天 肝火旺")
    assert r["validation"]["assessment_status"] == "needs_urgent_assessment" and not r["methods"] and r["withheld"]["methods"] > 0


def test_sj_is_read_as_te_by_the_point_lookup(study):
    assert study.point("SJ5")["point"]["code"] == "TE5"


# ------------------------------------------------------------------ tools, page and CLI
def test_the_tools_through_the_scheduler(harness):
    call = lambda tool, **a: harness.scheduler.execute(ToolCall(tool, a), actor=Actor.kernel())  # noqa: E731
    out = call("study.acupuncture_reason", **deepcopy(CASES["AC01"]["request"]["arguments"]))
    assert out.ok and out.result["assessment_status"] == "needs_information" and len(out.result["questions"]) == 2
    assert out.result["findings"][0]["message"].startswith("个案复核仍缺")  # findings are never cut for the model
    out = call("study.acupuncture_reason", **deepcopy(CASES["AC29"]["request"]["arguments"]))  # verified=true reaches the contract
    assert out.ok and out.result["execution_status"] == "invalid_parameters" and out.result["assessment_status"] is None
    out = call("study.acupuncture_reason", **deepcopy(CASES["AC07"]["request"]["arguments"]))
    assert out.ok and out.result["findings"][0]["code"] == "INVALID_METHOD"
    out = call("study.acupuncture_reason", **deepcopy(CASES["AC08"]["request"]["arguments"]))  # no record on this server
    assert out.ok and out.result["assessment_status"] == "needs_information" and not out.result["point_candidates"]
    out = call("study.acupuncture_audit", **deepcopy(CASES["AC14"]["request"]["arguments"]))
    assert out.ok and "PHASE_INTENT_MODALITY_CONFLATION" in [f["code"] for f in out.result["findings"]]
    reg = harness.scheduler.registry
    assert reg.has("study.acupuncture_reason") and reg.has("study.acupuncture_audit")
    assert reg.get("study.acupuncture_reason").input_schema["required"] == ["mode", "query"]


def test_the_pages(eng, study):
    sig = study.signature()
    page = markdown("acupuncture-reason", run(eng, "AC08"), sig)
    assert "## 候选穴（只供复核" in page and "行间 LR2" in page and "预算不是治疗的穴数" in page
    page = markdown("acupuncture-reason", run(eng, "AC31"), sig)
    assert "## 教学映射（假设的前提，不涉及任何人" in page and "“肝经实”" in page
    page = markdown("acupuncture-reason", run(eng, "AC16"), sig)
    assert page.startswith("# 针灸推理：须及时就医评估") and "URGENT_HEARING_ASSESSMENT" in page
    page = markdown("acupuncture-audit", run(eng, "AC13"), sig)
    assert "RELATION_TYPE_MISMATCH" in page and "yuan_luo：point.KI3 → point.BL58" in page


def test_the_cli(capsys, tmp_path, data_dir):
    base = ["--data", str(data_dir), "study"]
    assert main(base + ["acupuncture-reason", "耳鸣两周，没有听力下降", "--reason-mode", "case_review"]) in (0, None)
    out = capsys.readouterr().out
    assert "# 针灸推理：须先补充信息" in out and "耳鸣是否跟心跳同步" in out
    assert main(base + ["acupuncture-audit", "太冲属土，补太冲就是补脾。", "--plan", "LR3:tonify", "--plan", "SJ5", "--json"]) in (0, None)
    res = json.loads(capsys.readouterr().out)
    assert res["normalized_point_ids"] == ["LR3", "TE5"] and res["assessment_status"] == "educational_only"
    path = tmp_path / "args.json"
    path.write_text(json.dumps(CASES["AC07"]["request"]["arguments"], ensure_ascii=False), encoding="utf-8")
    assert main(base + ["acupuncture-reason", "--arguments", str(path), "--json"]) in (0, None)
    assert json.loads(capsys.readouterr().out)["execution_status"] == "invalid_parameters"
