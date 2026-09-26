"""Full-corpus machinery: script normalisation, 白文 segmentation, the Kanripo parser, the SQLite corpus store,
the lexicon harvester, and a research run over a store (synthetic texts in the Kanripo format)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from taochronos.bootstrap import Harness
from taochronos.kernel import MemoryEventStore
from taochronos.plugins.classics.domain import DomainPack
from taochronos.plugins.classics.harvest import Harvester
from taochronos.plugins.classics.ingest import book_spec, ingest_kanripo, load_catalog
from taochronos.plugins.classics.ingest.kanripo import KanripoParser, cells, read_file, split_sections
from taochronos.plugins.classics.segment import Segmenter, is_unpunctuated
from taochronos.plugins.classics.store import CorpusStore, StoreCorpus, fts_phrase, grams
from taochronos.plugins.knowledge.extraction import ClaimExtractor
from taochronos.verification.provenance import find_quote, verify_claim

HOME = Path(__file__).resolve().parents[1]
FIXTURES = HOME / "tests" / "fixtures" / "kanripo"


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return DomainPack(HOME / "domains" / "classics")


@pytest.fixture(scope="module")
def catalog() -> dict:
    return load_catalog(FIXTURES / "catalog.yaml")


@pytest.fixture(scope="module")
def store_path(tmp_path_factory, pack, catalog) -> Path:
    path = tmp_path_factory.mktemp("store") / "corpus" / "tcm.sqlite"
    store = CorpusStore(path, create=True)
    report = ingest_kanripo(store, catalog, FIXTURES, pack.variants.normalize_text, pack.variants.fingerprint,
                            log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    assert not report["missing"] and not report["note_order_warnings"]
    store.optimize()
    store.close()
    return path


@pytest.fixture(scope="module")
def corpus(store_path, pack) -> StoreCorpus:
    return StoreCorpus(CorpusStore(store_path), pack.variants.normalize_text, fingerprint=pack.variants.fingerprint)


# ------------------------------------------------------------------ normalisation
def test_script_normalisation_is_length_preserving_and_idempotent(pack):
    n = pack.variants.normalize_text
    for text, expected in [("太陽病頭痛發熱", "太阳病头痛发热"), ("巵子䜴湯主之", "栀子豉汤主之"), ("隂陽", "阴阳"),
                           ("黃耆五錢", "黄芪五钱"), ("五苓㪚", "五苓散"), ("茱茰", "茱萸"), ("讝語", "谵语")]:
        out = n(text)
        assert out == expected and len(out) == len(text)
        assert n(out) == out
    # curated variant normalisations are still recorded for the philologist; script conversion is not itemised
    _, applied = pack.variants.normalize("欬逆上氣")
    assert [a.source for a in applied] == ["欬"]


def test_lexicon_matches_traditional_text(pack):
    norm = pack.variants.normalize_text("太陽病發熱汗出惡風脉緩者名為中風桂枝湯主之")
    terms = {m.term_id for m in pack.lexicon.match(norm)}
    assert {"formula:桂枝汤", "symptom:发热", "symptom:汗出"} <= terms


# ------------------------------------------------------------------ segmentation
def test_segmented_view_maps_back_to_the_source(pack):
    seg = Segmenter(pack.lexicon)
    text = "太阳病头痛发热身疼腰痛骨节疼痛恶风无汗而喘者麻黄汤主之"
    view = seg.view(text)
    assert view.text == "太阳病头痛发热身疼腰痛骨节疼痛恶风无汗而喘者，麻黄汤主之。"
    start = view.text.index("麻黄汤")
    assert view.to_source(start, start + 3) == (text.index("麻黄汤"), text.index("麻黄汤") + 3)
    assert view.inserted == 2 and is_unpunctuated(text)
    listing = seg.view("人参（去芦）　茯苓（去皮）　　甘草")
    assert "、" in listing.text and "　" not in listing.text


def test_whitetext_claims_are_verbatim(pack, corpus):
    extractor = ClaimExtractor(pack)
    passage = next(p for p in corpus.passages(book_ids=["ceshi_fangshu"]) if "腎氣丸" in p.text)
    claims = extractor.extract(passage)
    formulas = {a.term_id for c in claims for a in c.arguments if a.role.value == "formula"}
    assert {"formula:肾气丸", "formula:桂枝汤", "formula:五苓散"} <= formulas
    for c in claims:
        assert "machine-segmented" in c.tags and c.extraction.method.endswith("machine-segmentation")
        assert passage.text[c.start:c.end] == c.quote
        assert verify_claim(c, corpus, pack.variants.normalize_text) == []


# ------------------------------------------------------------------ Kanripo parser
def test_mandoku_headers_sections_and_widths():
    f = read_file(FIXTURES / "KR3eT001" / "KR3eT001_001.txt")
    assert f.props["ID"] == "KR3eT001" and f.props["BASEEDITION"] == "WYG" and f.props["JUAN"] == "1"
    assert cells("凡消渇(一本/作)之病") == 7  # a double-column note is as wide as its wider column
    assert [s.props["JUAN"] for s in split_sections(read_file(FIXTURES / "KR3eT001" / "KR3eT001_000.txt"))] == ["提要"]


def test_parser_layers_dates_notes_and_gaiji(catalog):
    by = {e["kr"]: e for e in catalog["books"]}
    rows = KanripoParser(book_spec(by["KR3eT001"], catalog)).parse(FIXTURES / "KR3eT001")
    tiyao = rows[0]
    assert tiyao["kind"] == "preface" and tiyao["layer"] == "四库提要" and tiyao["year"] == 1781  # 乾隆四十六年
    formula = next(r for r in rows if "猪苓" in r["text"])
    # ingredient lines and the 右… preparation line form one prescription passage, doses kept inline
    assert "澤瀉（一兩六銖）" in formula["text"] and "右五味" in formula["text"] and formula["locator"]["section"] == "五苓散方"
    assert "（十八銖）　茯苓" in formula["text"]
    marked = next(r for r in rows if r["layer"] == "校语")
    assert marked["text"] == "一本作人參湯" and marked["year"] == 1066 and marked["kind"] == "commentary"
    gaiji = next(r for r in rows if "〓" in r["text"])
    assert gaiji["extra"]["gaiji"] == ["&KR0001;", "[病-丙+(穩-禾)]"]
    assert all(r["locator"]["page"] for r in rows)

    rows2 = KanripoParser(book_spec(by["KR3eT002"], catalog)).parse(FIXTURES / "KR3eT002")
    main, wang, xin = rows2
    assert main["year"] == -137.5 and "轉為消渴治之以蘭" in main["text"] and "溢謂" not in main["text"]
    # right-to-left column order (BA): 「溢謂溢出消渴者熱」 is read before 「之而為消渴也」
    assert wang["layer"] == "王冰注" and wang["text"].startswith("溢謂溢出消渴者熱之而為消渴也")
    assert wang["temporal"]["dynasty"] == "唐" and wang["year"] == 762
    assert xin["layer"] == "新校正" and xin["text"] == "新校正云按" and xin["year"] == 1068


# ------------------------------------------------------------------ store
def test_store_round_trip_and_search(corpus, pack):
    assert len(corpus) == 8 and set(corpus.books) == {"ceshi_fangshu", "ceshi_neijing"}
    book = corpus.book("ceshi_neijing")
    assert book.source.license == "CC BY-SA 4.0" and book.work == "ceshi_neijing"
    assert grams("消渴，饮") == "消渴 渴z x 饮z" and fts_phrase("消渴") == '"消渴"' and fts_phrase("渴") == "渴*"
    hits = corpus.contains("消渴")  # traditional 消渇 / 消渴 both found through normalisation, earliest first
    assert hits[0] == "ceshi_neijing.001.00000" and len(hits) >= 3
    assert corpus.contains("白虎加人参汤") and not corpus.contains("白虎加人参汤", before=100)
    assert corpus.search(["五苓散"])[0][0].startswith("ceshi_fangshu")
    assert corpus.near(["脾瘅"], ["消渴"], distance=60) == ["ceshi_neijing.001.00000"]
    commentary = corpus.passage("ceshi_neijing.001.00001")
    assert "layer:王冰注" in commentary.tags and commentary.temporal.year() == 762
    assert corpus.count_range(after=1000) == 3  # 提要, 校语, 新校正
    main = corpus.passage("ceshi_neijing.001.00000").text
    at = main.index("治之以蘭除陳氣也")
    assert find_quote(corpus, "治之以蘭除陳氣也", pack.variants.normalize_text) == [("ceshi_neijing.001.00000", at, at + 8)]
    assert corpus.stats(pack.periods)["index_current"] is True


def test_reingest_is_idempotent(store_path, pack, catalog, tmp_path):
    copy = tmp_path / "copy.sqlite"
    shutil.copy(store_path, copy)
    store = CorpusStore(copy)
    before = store.db.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    ingest_kanripo(store, catalog, FIXTURES, pack.variants.normalize_text, pack.variants.fingerprint, only=["KR3eT002"], log=lambda m: None)
    after = store.db.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    fresh = StoreCorpus(store, pack.variants.normalize_text)
    assert before == after and fresh.near(["脾瘅"], ["消渴"], distance=60) == ["ceshi_neijing.001.00000"]


def test_harvester_finds_prescription_headings(corpus, pack):
    harvester = Harvester(pack.variants.normalize_text, set())
    for p in corpus.iter_passages():
        harvester.passage(p.id, p.book_id, corpus.book(p.book_id).category, p.text, p.locator.section, corpus.year(p), p.kind)
    formulas, _ = harvester.select(min_books=1, min_count=1)
    assert "五苓散" in {c.term for c in formulas}


# ------------------------------------------------------------------ research over a store
def test_research_over_a_corpus_store(store_path, tmp_path, pack):
    # a modern editor's note on 消渴 (dated 1950—2010): no evidence for a question that names no period
    local = tmp_path / "tcm.sqlite"
    shutil.copy(store_path, local)
    store = CorpusStore(local)
    store.put_book({"id": "modern_note", "title": "今人按语", "aliases": [], "authors": [], "dynasty": "当代", "category": "内科",
                    "composition": [1950, 2010], "author_life": None, "dating_basis": "composition", "attribution": "traditional",
                    "school": None, "work": "modern_note", "editions": [{"id": "modern_note@test", "name": "测试", "year": None, "quality": 0.5}],
                    "source": {"origin": "test", "license": "CC BY-SA 4.0", "acquisition": "test", "url": None, "transcription": "",
                               "verified": False}, "notes": "", "layers": [], "source_id": "test", "source_ref": "modern_note"},
                   source="test")
    store.add_passages([{"id": "modern_note.00000", "book_id": "modern_note", "edition_id": "modern_note@test", "seq": 0,
                         "kind": "commentary", "layer": "今人按", "year": 1980.0, "y_start": 1950, "y_end": 2010,
                         "locator": {"volume": None, "chapter": "按", "section": None, "precision": "exact"},
                         "temporal": {"dynasty": "当代", "t_author": None, "t_composition": [1950, 2010], "t_edition": None, "t_citation": None},
                         "text": "今人按：消渴即今之糖尿病，消渴之病多由胰岛所致。", "punctuation": "editorial", "extra": {"layer": "今人按"}}],
                       pack.variants.normalize_text)
    store.commit()
    store.close()
    harness = Harness.from_profile("full-corpus", home=HOME, data_dir=tmp_path, store=MemoryEventStore(),
                                   overrides={"bundles": [
                                       {"plugin": "taochronos.plugins.classics", "config": {"domain": "domains/classics", "store": str(local)}},
                                       {"plugin": "taochronos.plugins.knowledge"}, {"plugin": "taochronos.plugins.retrieval"},
                                       {"plugin": "taochronos.plugins.models.offline"}, {"plugin": "taochronos.plugins.sandbox"},
                                       {"plugin": "taochronos.plugins.subagents"}]})
    assert harness.corpus.large
    engine = harness.engine()
    session = engine.start(harness.make_goal("消渴的病因与治法如何演变？", focus_terms=["消渴"], forbidden_assumptions=["消渴=糖尿病"]),
                           session_id="store")
    engine.run(session)
    state = session.state
    assert state.corpus.frame["terms"] == ["disease:消渴"] and state.corpus.frame["matched"] >= 3
    assert state.corpus.frame["latest_year"] == 1950 and "modern_note.00000" not in state.corpus.passage_ids
    assert state.claims and all(verify_claim(c, harness.corpus, harness.pack.variants.normalize_text) == [] for c in state.claims.values())
    report = next(a for a in state.artifacts.values() if a.kind == "discovery_report" and a.media_type == "text/markdown")
    text = (tmp_path / "artifacts" / report.path).read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in text and "未经本项目逐字校勘" in text
