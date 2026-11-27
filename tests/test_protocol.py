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


def test_coerce_leaves_out_a_parameter_not_set_written_as_null():
    """``null`` where the schema neither requires a parameter nor takes ``null`` for it is a parameter not set, as some
    models write each one: it is left out, and said to be — never a required one, an item of a list, or a value the
    schema takes as ``null``; nor is the text ``"null"`` taken for it."""
    from taochronos.protocol.schema import coerce, fit_arguments

    fixed, repairs = coerce({"term": "x", "limit": None, "terms": None, "aliases": None, "year": None}, ARGS)
    assert fixed == {"term": "x", "year": None}  # year takes null
    assert repairs == ["$.limit: null → left out", "$.terms: null → left out", "$.aliases: null → left out"]
    assert coerce({"term": "x", "opts": {"n": None}}, ARGS) == ({"term": "x", "opts": {}}, ["$.opts.n: null → left out"])
    assert coerce({"term": "x", "limit": None, "share": "0.5"}, ARGS)[0] == {"term": "x", "share": 0.5}
    assert fit_arguments({"term": "x", "unknown": None}, ARGS, tool="t") == ({"term": "x"}, ["$.unknown: null → left out"], None)
    for given in ({"term": None}, {"term": "x", "terms": [None]}, {"term": "x", "limit": "null"}, {"term": "x", "year": None}):
        fixed, repairs = coerce(given, ARGS)
        assert fixed is given and not repairs, given
    refused = fit_arguments({"term": None, "limit": None}, ARGS, tool="t")[2]
    assert refused.startswith("invalid arguments: $.term: expected string, got NoneType")
    # a schema that takes other properties may take null for them: theirs is left as it is
    for schema in ({"type": "object"}, {"type": "object", "properties": {}, "additionalProperties": {"type": "integer"}},
                   {"type": "object", "properties": {"b": {"type": "string"}}, "additionalProperties": True}):
        assert coerce({"a": None}, schema) == ({"a": None}, []), schema


def test_a_value_has_a_size_as_well_as_a_type():
    """How large a value may be: a number within its bounds — and a number at all, which NaN is not (JSON text can
    carry it here) — a text and a list no longer than they may be.  One of hundreds of digits is not written out."""
    schema = {"type": "object", "properties": {
        "k": {"type": "integer", "minimum": 1, "maximum": 100}, "year": {"type": "number", "minimum": -5000, "maximum": 5000},
        "text": {"type": "string", "maxLength": 5}, "names": {"type": "array", "items": {"type": "string", "maxLength": 3}, "maxItems": 2}}}
    assert not validate({"k": 1, "year": -221.5, "text": "桂枝汤主之", "names": ["桂枝", "芍药"]}, schema)
    assert not validate({"k": 100, "year": 5000, "text": "", "names": []}, schema)
    for value, said in [({"k": 0}, "$.k: 0 < minimum 1"), ({"k": 101}, "$.k: 101 > maximum 100"),
                        ({"k": 10 ** 300}, "$.k: a number of 301 digits > maximum 100"),
                        ({"year": float("nan")}, "$.year: not a number"), ({"year": float("inf")}, "$.year: inf > maximum 5000"),
                        ({"year": float("-inf")}, "$.year: -inf < minimum -5000"),
                        ({"text": "桂枝汤主之也"}, "$.text: 6 characters > maxLength 5"),
                        ({"names": ["a", "b", "c"]}, "$.names: 3 items > maxItems 2"),
                        ({"names": ["桂枝汤方"]}, "$.names[0]: 4 characters > maxLength 3")]:
        assert validate(value, schema) == [said], value
    assert not validate({"year": float("nan")}, {"type": "object", "properties": {"year": {"type": "number"}}})  # no bound, no say


def test_a_value_too_large_is_said_to_be_so_whatever_its_form():
    """A number written as text is repaired where that makes it valid — and where it is only too large as well: what
    is then said is its limit, which the model can act on, and not that "1000" is no integer."""
    from taochronos.protocol.schema import fit_arguments

    schema = {"type": "object", "properties": {"k": {"type": "integer", "minimum": 1, "maximum": 100},
                                               "names": {"type": "array", "items": {"type": "string"}, "maxItems": 2}}}
    fixed, repairs, error = fit_arguments({"k": "1000"}, schema, tool="t")
    assert fixed == {"k": 1000} and repairs == ['$.k: "1000" → 1000'] and error.startswith("invalid arguments: $.k: 1000 > maximum 100 · t takes:")
    assert fit_arguments({"k": 3000.0}, schema, tool="t")[2].startswith("invalid arguments: $.k: 3000 > maximum 100")
    assert fit_arguments({"names": '["a", "b", "c"]'}, schema, tool="t")[2].startswith("invalid arguments: $.names: 3 items > maxItems 2")
    assert fit_arguments({"k": "abc"}, schema, tool="t")[2].startswith("invalid arguments: $.k: expected integer, got str")
    assert fit_arguments({"k": "50", "names": "a"}, schema, tool="t") == ({"k": 50, "names": ["a"]}, ['$.k: "50" → 50', '$.names: "a" → ["a"]'], None)


def test_a_list_written_as_text_is_read_whole():
    """A list or an object written as JSON text is read into one — and the text can spell half a character
    (``\\ud800``) though it holds none: what comes out of the reading has none either."""
    from taochronos.protocol.schema import coerce

    schema = {"type": "object", "properties": {"books": {"type": "array", "items": {"type": "string"}},
                                               "opts": {"type": "object", "properties": {"name": {"type": "string"}}}}}
    text = '["shanghanlun\\ud83d", "jinkui"]'
    assert "\ud83d" not in text
    fixed, repairs = coerce({"books": text, "opts": '{"name": "\\udc00x", "\\ud800": 1}'}, schema)
    assert fixed == {"books": ["shanghanlun�", "jinkui"], "opts": {"name": "�x", "�": 1}} and len(repairs) == 2
    json_text = __import__("json").dumps(fixed, ensure_ascii=False)
    json_text.encode("utf-8")  # it can be written down
    deep = "[" * 100000 + "]" * 100000  # nested deeper than the reader goes: left as it is, for validate to say
    assert coerce({"books": deep}, schema)[0] == {"books": deep}
