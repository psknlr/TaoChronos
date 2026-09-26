from taochronos.verification.provenance import verify_claim


def test_variant_normalisation_is_length_preserving(harness):
    variants = harness.pack.variants
    text = "由邪气内薄于五藏，横连募原也"
    norm = variants.normalize_text(text)
    assert len(norm) == len(text) and "膜原" in norm


def test_lexicon_longest_match_and_synonyms(harness):
    lex = harness.pack.lexicon
    mentions = lex.match("男子消渴，小便反多")
    assert "disease:消渴" in {m.term_id for m in mentions}
    assert lex.canonical("薯蓣") == "herb:山药"  # 避讳改名


def test_period_constraints(harness):
    periods = harness.pack.periods
    assert periods.parse_constraint("宋代以前的消渴方") == (None, 960)
    assert periods.parse_constraint("明清时期的温病学说") == (1368, 1912)
    assert periods.parse_constraint("清热解毒") == (None, None)  # 清 is not a dynasty here


def test_sense_resolution_is_period_bound(harness):
    t = harness.pack.terminology
    sense, p, alts, _ = t.resolve("消渴", "若脉浮，小便不利，微热消渴者，五苓散主之", {"小便不利", "微热", "五苓散"}, 209)
    assert sense == "消渴#症状" and len(alts) > 1


def test_mapping_rules_never_equate_diseases(harness):
    t = harness.pack.terminology
    assert t.propose_mapping("消渴#病·多饮多尿", "modern:diabetes_mellitus").relation.value == "partially_overlapping"
    assert t.propose_mapping("消渴#症状", "modern:diabetes_mellitus").relation.value == "not_equivalent"


def test_every_extracted_claim_quotes_its_passage_verbatim(harness):
    claims = harness.capabilities.get("knowledge").claims()
    assert len(claims) > 150
    normalize = harness.pack.variants.normalize_text
    assert all(not verify_claim(c, harness.corpus, normalize) for c in claims)


def test_extraction_of_a_formula_indication(harness):
    extractor = harness.capabilities.get("extractor")
    p = harness.corpus.passage("shanghanlun.c013")
    claims = extractor.extract(p, harness.philology.assess(p))
    ind = [c for c in claims if c.relation.value == "indicated_for"]
    assert ind and {"formula:桂枝汤", "symptom:汗出", "symptom:恶风"} <= {a.term_id for a in ind[0].arguments}


def test_earliest_attestation_through_a_variant_spelling(harness):
    q, hits = harness.capabilities.get("retriever").search("膜原最早见于何书", k=3)
    assert q.intent == "earliest" and hits[0].passage_id == "suwen.035"


def test_concept_level_retrieval_before_the_name_existed(harness):
    _, hits = harness.capabilities.get("retriever").search("三消的最早记载", k=3)
    assert hits[0].passage_id == "waitai.11.gujin"


def test_temporal_constraints_never_leak(harness):
    q, hits = harness.capabilities.get("retriever").search("宋代以前的消渴方", k=20)
    assert hits and all(h.year is not None and h.year < 960 for h in hits)


def test_allowed_scope_is_enforced(harness):
    allowed = {"shanghanlun.c071"}
    _, hits = harness.capabilities.get("retriever").search("消渴", k=10, allowed=allowed)
    assert {h.passage_id for h in hits} <= allowed


def test_contested_reading_is_not_forced(harness):
    a = harness.philology.assess(harness.corpus.passage("shanghanlun.c176"))
    span = a.contested[0]
    assert span.uncertain >= 0.05 and span.base_probability() < 0.6
    assert any(o.reading == "表有寒，里有热" for o in span.options)
