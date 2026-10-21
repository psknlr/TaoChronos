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


ARGS = {"type": "object", "properties": {
    "term": {"type": "string"}, "terms": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"},
    "share": {"type": "number"}, "whole": {"type": "boolean"}, "aliases": {"type": "string", "enum": ["auto", "off"]},
    "years": {"type": "array", "items": {"type": "integer"}}, "opts": {"type": "object", "properties": {"n": {"type": "integer"}}},
    "year": {"anyOf": [{"type": "integer"}, {"type": "null"}]}}, "required": ["term"]}


def test_coerce_repairs_the_form_of_a_value_never_its_meaning():
    from taochronos.protocol.schema import coerce

    cases = [
        ({"term": "消渴", "limit": "40"}, {"term": "消渴", "limit": 40}),
        ({"term": "消渴", "limit": 40.0}, {"term": "消渴", "limit": 40}),
        ({"term": "x", "share": "0.6", "whole": "TRUE", "aliases": "Off"}, {"term": "x", "share": 0.6, "whole": True, "aliases": "off"}),
        ({"term": "x", "terms": {"item": "脱疽"}}, {"term": "x", "terms": ["脱疽"]}),
        ({"term": "x", "terms": {"item": ["脱疽", "脱骨疽"]}}, {"term": "x", "terms": ["脱疽", "脱骨疽"]}),
        ({"term": "x", "terms": "脱疽"}, {"term": "x", "terms": ["脱疽"]}),
        ({"term": "x", "terms": '["脱疽", "脱骨疽"]'}, {"term": "x", "terms": ["脱疽", "脱骨疽"]}),
        ({"term": "x", "years": ["1368", 960]}, {"term": "x", "years": [1368, 960]}),
        ({"term": "x", "opts": '{"n": "3"}'}, {"term": "x", "opts": {"n": 3}}),
        ({"term": "x", "year": "1368"}, {"term": "x", "year": 1368}),
        ({"term": ["消渴"]}, {"term": "消渴"}),
        ({"term": {"item": "消渴"}}, {"term": "消渴"}),
        ({"term": 1368}, {"term": "1368"}),
    ]
    for given, wanted in cases:
        fixed, repairs = coerce(given, ARGS)
        assert fixed == wanted and repairs, given
        assert not validate(fixed, ARGS), given
    # what only a guess would repair is left as it is, for validation to report: the same object comes back
    for given in ({"term": "x", "limit": "forty"}, {"term": "x", "limit": 4.5}, {"term": "x", "limit": True},
                  {"term": "x", "terms": "脱疽、脱骨疽"}, {"term": "x", "terms": "脱疽,脱骨疽"}, {"term": "x", "whole": "yes"},
                  {"term": "x", "aliases": "none"}, {"term": ["消渴", "口渴"]}, {"term": None}, {"term": "x", "limit": "1e400"},
                  {"term": "x", "limit": "Infinity"}, {"term": "x"}, {"term": "x", "unknown": "40"}):
        fixed, repairs = coerce(given, ARGS)
        assert fixed is given and not repairs, given
    assert coerce({"term": "x", "limit": "40"}, ARGS)[1] == ['$.limit: "40" → 40']


def test_fit_arguments_says_what_the_tool_takes():
    from taochronos.protocol.schema import fit_arguments, signature

    assert signature(ARGS).startswith("term (string, required); terms (list of string); limit (integer)")
    assert "aliases (string: auto | off)" in signature(ARGS) and "year (integer or null)" in signature(ARGS)
    assert signature({"type": "object", "properties": {}}) == "no parameters"
    assert fit_arguments({"term": "x", "limit": "3"}, ARGS, tool="t") == ({"term": "x", "limit": 3}, ['$.limit: "3" → 3'], None)
    _, _, error = fit_arguments({"name": "x"}, ARGS, tool="kg.thing")
    assert error.startswith("invalid arguments: $: missing required property 'term'; $: unknown parameter 'name' · kg.thing takes: term")
    assert fit_arguments(["x"], ARGS, tool="t")[2].startswith("invalid arguments: $: expected object, got list · t takes:")
    # a schema that takes other properties (or names none) refuses none
    assert fit_arguments({"a": 1}, {"type": "object"}, tool="t")[2] is None
    assert fit_arguments({"a": 1}, {"type": "object", "properties": {}, "additionalProperties": {"type": "integer"}}, tool="t")[2] is None
