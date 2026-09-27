"""校勘疑义: textual cruxes read from the commentaries, and the support reading that consults them."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from taochronos.plugins.classics.cruxes import CruxIndex, han_view
from taochronos.plugins.classics.study.cruxes import CruxStudy
from taochronos.protocol.claims import Claim, ClaimArgument, ClaimRelation, ExtractionInfo, Role
from taochronos.protocol.documents import TemporalContext
from taochronos.verification.support import assess_support


@pytest.fixture(scope="module")
def reader(harness):
    base = SimpleNamespace(normalize=harness.pack.variants.normalize_text, pack=harness.pack)
    return CruxStudy(base, commentary=None)


CLAUSE = han_view("傷寒心下有水氣欬而微喘發熱不渴服湯已渴者此寒去欲解也小青龍湯主之")[0]


def kinds(reader, text, clause=CLAUSE):
    clause = han_view(reader.b.normalize(clause))[0]
    return [(s["kind"], s["target"], s["strong"]) for s in reader.statements(text, clause)]


def test_a_statement_that_names_the_clause_words_is_a_crux(reader):
    found = kinds(reader, "小青龍湯主之六字，當在發熱不渴之下。")
    assert found == [("transposition", "小青龙汤主之", True)]
    found = kinds(reader, "（按）去桂當是去芍藥", clause="仍頭項強痛小便不利者桂枝去桂加茯苓白朮湯主之")
    assert found and found[0][:2] == ("emendation", "去桂")


def test_what_is_not_a_crux_of_this_clause_is_left_out(reader):
    assert kinds(reader, "脈緩當作浮緩看，浮是太陽病脈。", clause="太陽病發熱汗出惡風脈緩者名為中風") == []  # read as
    assert kinds(reader, "以桂麻用之不當在冬月已屢致戒") == []  # 不当在: no transposition
    assert kinds(reader, "反惡寒之反字，衍文也。") == []  # names words this clause does not have
    assert kinds(reader, "各注家疑為後人所附，而不知此方絕大議論。") == []  # a doubt reported to be answered
    placed = kinds(reader, "此條當是陽明篇錯簡。")
    assert placed and placed[0][0] == "misplacement" and not placed[0][2]
    # a repetition the commentator's witness has is not this witness's problem when the words occur once here
    assert kinds(reader, "則安得又復有小青龍湯主之之文，傳寫之誤甚明") == []
    # the next clause's commentary, run on into this unit, is cut off
    assert kinds(reader, "此寒去欲解也。（四一）傷寒發熱，當作熱字") == []


def test_a_mere_doubt_needs_a_second_voice():
    one = [{"commentator": "甲", "kind": "doubt", "strong": False, "target": None}]
    assert CruxStudy.verdict(one) is None
    two = one + [{"commentator": "乙", "kind": "omission", "strong": False, "target": None}]
    assert CruxStudy.verdict(two)["commentators"] == 2
    named = [{"commentator": "甲", "kind": "emendation", "strong": True, "target": "去桂", "proposed": "去芍药"}]
    assert CruxStudy.verdict(named) == {"kinds": ["emendation"], "target": "去桂", "proposed": "去芍药", "commentators": 1}


def _claim(text, quote, relation, *args):
    lo = text.find(quote)
    arguments = []
    for role, surface in args:
        at = text.find(surface, lo)
        arguments.append(ClaimArgument(role=Role(role), surface=surface, start=at, end=at + len(surface)))
    return Claim(id="c", passage_id="p", book_id="b", relation=ClaimRelation(relation), arguments=arguments, quote=quote,
                 start=lo, end=lo + len(quote), temporal=TemporalContext(), extraction=ExtractionInfo(method="manual"))


def test_the_index_finds_a_clause_through_variants_and_touches_only_claims_on_the_doubted_words(harness):
    n = harness.pack.variants.normalize_text
    index = CruxIndex([{"id": "x", "clause": "伤寒脉浮滑此表有热里有寒白虎汤主之第三十八", "kinds": ["emendation"],
                        "by": [{"commentator": "王肯堂"}]},
                       {"id": "y", "clause": "服桂枝汤或下之仍头项强痛翕翕发热无汗心下满微痛小便不利者桂枝去桂加茯苓白术汤主之",
                        "target": "去桂", "kinds": ["emendation"], "by": [{"commentator": "吴谦"}]}], n)
    text = "傷寒，脈浮滑，此以表有熱，裏有寒，白虎湯主之。"  # another witness: 以 added, no numbering, traditional forms
    claim = _claim(text, text[:-1], "indicated_for", ("formula", "白虎湯"))
    assert assess_support(claim, text, n, index).verdict == "ambiguous"
    assert assess_support(claim, text, n).verdict == "supports"  # without the registry: the literal reading
    t28 = "服桂枝湯，或下之，仍頭項強痛，翕翕發熱，無汗，心下滿微痛，小便不利者，桂枝去桂加茯苓白朮湯主之。"
    on_formula = _claim(t28, t28[:-1], "indicated_for", ("formula", "桂枝去桂加茯苓白朮湯"), ("symptom", "小便不利"))
    assert assess_support(on_formula, t28, n, index).verdict == "ambiguous"
    assert any(c.get("kind") == "crux" for c in assess_support(on_formula, t28, n, index).cues)
    elsewhere = _claim(t28, "仍頭項強痛，翕翕發熱", "defines", ("symptom", "頭項強痛"), ("symptom", "發熱"))
    assert not index.overlapping(n(t28), elsewhere.start, elsewhere.end, [(a.start, a.end) for a in elsewhere.arguments])


def test_the_shipped_registry_is_loaded_and_read(harness):
    assert len(harness.pack.cruxes) >= 100
    p = harness.corpus.passage("shanghanlun.c176")
    claims = [c for c in harness.capabilities.get("extractor").extract(p) if c.relation == ClaimRelation.INDICATED_FOR]
    verdicts = {assess_support(c, p.text, harness.pack.variants.normalize_text, harness.pack.cruxes).verdict for c in claims}
    assert verdicts == {"ambiguous"}  # 表有热，里有寒 — the commentators' crux
    c013 = harness.corpus.passage("shanghanlun.c013")
    ind = next(c for c in harness.capabilities.get("extractor").extract(c013) if c.relation == ClaimRelation.INDICATED_FOR)
    assert assess_support(ind, c013.text, harness.pack.variants.normalize_text, harness.pack.cruxes).verdict == "supports"
