from taochronos.protocol import (
    Claim,
    ClaimArgument,
    ClaimRelation,
    ConfidenceVector,
    ExtractionInfo,
    GoalSpec,
    Role,
    TemporalContext,
    YearRange,
    content_hash,
    stable_id,
)
from taochronos.protocol.schema import schema_for, validate


def test_stable_ids_are_deterministic():
    assert stable_id("clm", "a", 1, {"x": [1, 2]}) == stable_id("clm", "a", 1, {"x": [1, 2]})
    assert stable_id("clm", "a", 1) != stable_id("clm", "a", 2)


def test_model_round_trip_and_hash():
    claim = Claim(
        id="clm_x", passage_id="p", book_id="b", relation=ClaimRelation.INDICATED_FOR,
        arguments=[ClaimArgument(role=Role.FORMULA, surface="桂枝汤", term_id="formula:桂枝汤", start=0, end=3)],
        quote="桂枝汤", start=0, end=3, temporal=TemporalContext(t_composition=YearRange(start=200, end=219)),
        extraction=ExtractionInfo(method="manual"),
    )
    again = Claim.from_dict(claim.to_dict())
    assert again == claim
    assert content_hash(again) == content_hash(claim)


def test_goal_digest_changes_with_the_contract():
    a = GoalSpec(question="消渴")
    b = GoalSpec(question="消渴", forbidden_assumptions=["消渴=糖尿病"])
    assert a.digest() != b.digest()


def test_confidence_is_a_vector_with_unknown_modern_validity():
    view = ConfidenceVector(textual=0.9, philological=0.5).scholar_view()
    assert view["Text confidence"] == "medium"
    assert view["Modern biomedical validity"] == "unknown"


def test_schema_validation():
    schema = schema_for(GoalSpec)
    assert not validate(GoalSpec(question="q").to_dict(), schema)
    assert validate({"question": 3}, schema)
