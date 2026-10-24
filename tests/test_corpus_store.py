"""Full-corpus machinery: script normalisation, 白文 segmentation, the Kanripo parser, the SQLite corpus store,
the lexicon harvester, and a research run over a store (synthetic texts in the Kanripo format)."""

from __future__ import annotations

import gzip
import json
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
from taochronos.verification.scope import ReadingScope, ScopedCorpusView

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


def test_the_bigram_tokens_are_those_of_each_run_of_han_characters():
    def reference(norm):  # the definition, one character at a time
        from taochronos.plugins.classics.store import BREAK, PAD, is_han
        out, start = [], -1
        for i in range(len(norm) + 1):
            han = i < len(norm) and is_han(norm[i])
            if han and start < 0:
                start = i
            elif not han and start >= 0:
                run = norm[start:i]
                out += [run[j: j + 2] for j in range(len(run) - 1)] + [run[-1] + PAD]
                start = -1
                if i < len(norm):
                    out.append(BREAK)
            elif not han and i < len(norm) and out and out[-1] != BREAK:
                out.append(BREAK)
        return " ".join(out)

    import random
    rng = random.Random(7)
    alphabet = "天地人消渴，。 a1〇〓\U00020000\u3400\u9fff\uf900\ufaffx"
    samples = ["", "，", "天", "天，", "，天", "天地，人", "，，天地，，", "〇〓", "𠀀𠀁天"]
    samples += ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 16))) for _ in range(20000)]
    for s in samples:
        assert grams(s) == reference(s), s


def test_a_store_written_once_keeps_its_counts(tmp_path, store_path, pack):
    import shutil as _shutil
    copy = tmp_path / "counted.sqlite"
    _shutil.copy(store_path, copy)
    scanned = StoreCorpus(CorpusStore(copy), pack.variants.normalize_text).stats(pack.periods)
    store = CorpusStore(copy)
    store.count()
    store.commit()
    corpus = StoreCorpus(store, pack.variants.normalize_text)
    assert store.counted() is not None and corpus.stats(pack.periods) == scanned  # read, not scanned: the same
    store.db.execute("DELETE FROM passages WHERE rid = (SELECT MAX(rid) FROM passages)")
    assert store.counted() is None  # the passages changed: counted again
    store.close()


def test_a_quotation_is_found_however_it_is_punctuated(corpus, pack):
    n = pack.variants.normalize_text
    main = corpus.passage("ceshi_neijing.001.00000").text
    at = main.index("治之以蘭除陳氣也")
    # a reader's punctuation over a 白文 witness, in either script
    assert find_quote(corpus, "治之以蘭，除陳氣也。", n) == [("ceshi_neijing.001.00000", at, at + 8)]
    assert find_quote(corpus, "治之以兰，除陈气也", n) == [("ceshi_neijing.001.00000", at, at + 8)]
    # a quotation that runs across the witness's own marks, located in the witness's text
    dosage = corpus.passage("ceshi_fangshu.001.00003").text
    [(pid, start, end)] = find_quote(corpus, "猪苓十八銖，澤瀉一兩六銖", n)
    assert pid == "ceshi_fangshu.001.00003" and dosage[start:end] == "猪苓（十八銖）\u3000\u3000澤瀉（一兩六銖"
    # a changed or a missing character is never accepted
    assert find_quote(corpus, "治之以蘭，除舊氣也", n) == []
    assert find_quote(corpus, "治之以蘭，除氣也", n) == []


def test_outside_a_session_the_tools_read_the_whole_store(store_path, tmp_path):
    from taochronos.chat import ChatRuntime

    local = tmp_path / "tcm.sqlite"
    shutil.copy(store_path, local)
    harness = Harness.from_profile("full-corpus", home=HOME, data_dir=tmp_path, store=MemoryEventStore(),
                                   overrides={"bundles": [
                                       {"plugin": "taochronos.plugins.classics", "config": {"domain": "domains/classics", "store": str(local)}},
                                       {"plugin": "taochronos.plugins.knowledge"}, {"plugin": "taochronos.plugins.retrieval"},
                                       {"plugin": "taochronos.plugins.models.offline"}]})
    rt = ChatRuntime(harness, kind="test")
    # every book of the store, before anything has been read; filtered by author, dynasty, category
    books = rt.call("classics.list_books", {})["result"]
    assert {b["book_id"]: b["passages"] for b in books} == {"ceshi_fangshu": 5, "ceshi_neijing": 3}
    assert [b["book_id"] for b in rt.call("classics.list_books", {"query": "张某"})["result"]] == ["ceshi_fangshu"]
    assert [b["book_id"] for b in rt.call("classics.list_books", {"category": "医经"})["result"]] == ["ceshi_neijing"]
    assert len(rt.call("classics.list_books", {"limit": 1})["result"]) == 1
    # claims and neighbours of a term: read from the passages that write it, not from what happens to have been read
    claims = rt.call("kg.claims", {"terms": ["消渴"]})["result"]
    assert claims and all("disease:消渴" in {a["term"] for a in c["arguments"]} for c in claims)
    assert {c["passage_id"] for c in claims} <= set(corpus_ids := harness.corpus.contains("消渴")) and corpus_ids
    assert not rt.call("kg.claims", {"terms": ["消渴"], "before": -1000})["result"]
    neighbours = rt.call("kg.neighbors", {"term": "消渴"})["result"]
    assert "formula:肾气丸" in str(neighbours)


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


def test_the_normaliser_fingerprint_is_the_same_under_every_python(pack):
    """A store records the fingerprint of the normaliser it was indexed with; it must not depend on the Python that
    computes it.  repr() escapes the ideographs its Unicode database does not know yet (CJK Extension H under 3.11,
    written as themselves from 3.12 on): the fingerprint writes them as themselves under every Python."""
    from taochronos.plugins.classics.domain import _stable_repr

    ext_h = chr(0x31F5A)  # 𱽚, Unicode 15.0: one of the variant table's characters
    assert _stable_repr([(ext_h, "丁")]) == f"[('{ext_h}', '丁')]"
    assert _stable_repr(["a\\U00031f5a"]) == repr(["a\\U00031f5a"])  # a backslash of the text itself is left as it is
    assert ext_h in pack.variants.script.map or any(ext_h in (k, v) for k, v in pack.variants.chars.items())


def test_a_passage_knows_the_ones_before_and_after_it_and_an_id_that_is_none_what_is_there(tmp_path, pack):
    """``around`` on two books of the committed 要籍 pack: 素问, whole chapters of it (seq 44 is followed by 76, under
    another volume's code), and 伤寒论 whole, in five temporal groups.  A passage's neighbours are those of its book in
    seq order — over a left-out chapter, within a view's bounds, never one a reader's scope withholds; an id that is no
    passage is answered with the passage its number names (an id ends in its seq) and those it falls between."""
    from taochronos.plugins.classics.webcorpus import build_store

    keep = {"suwen_wangbing", "cm_shanghan_npm"}
    books = [b for b in json.loads((HOME / "corpus" / "web" / "books.json").read_text(encoding="utf-8")) if b["id"] in keep]
    (tmp_path / "books.json").write_text(json.dumps(books, ensure_ascii=False), encoding="utf-8")
    with gzip.open(HOME / "corpus" / "web" / "passages.jsonl.gz", "rt", encoding="utf-8") as f:
        lines = [line for line in f if json.loads(line)["book_id"] in keep]
    (tmp_path / "passages.jsonl.gz").write_bytes(gzip.compress("".join(lines).encode("utf-8"), mtime=0))
    build_store(tmp_path, tmp_path / "tcm.sqlite", pack.variants.normalize_text, pack.variants.fingerprint, index=False)
    corpus = StoreCorpus(CorpusStore(tmp_path / "tcm.sqlite"), pack.variants.normalize_text)

    def in_order(view, book):  # the book's passages in seq order, as the view has them
        ids = [i for i in view.passage_ids() if i.startswith(f"{book}.")]
        return sorted(ids, key=lambda i: int(i.rsplit(".", 1)[1]))

    for view in (corpus, corpus.on_side(700, "before")):
        for book in sorted(keep):
            ids = in_order(view, book)
            assert ids and [view.around(i) for i in ids] == [(a, i, b) for a, i, b in zip([None, *ids], ids, [*ids[1:], None])]
    assert corpus.on_side(700, "before").around("cm_shanghan_npm.00000")[2] != corpus.around("cm_shanghan_npm.00000")[2]
    assert corpus.around("suwen_wangbing.000.00044") == ("suwen_wangbing.000.00043", "suwen_wangbing.000.00044",
                                                         "suwen_wangbing.001.00076")
    # ids that are not passages: in a left-out chapter, under another volume's code or none, unpadded, past the end
    assert corpus.around("suwen_wangbing.000.00050") == ("suwen_wangbing.000.00044", None, "suwen_wangbing.001.00076")
    for written in ("suwen_wangbing.001.00044", "suwen_wangbing.00044", "suwen_wangbing.44"):
        assert corpus.around(written) == ("suwen_wangbing.000.00043", "suwen_wangbing.000.00044", "suwen_wangbing.001.00076")
    assert corpus.around("cm_shanghan_npm.99999") == ("cm_shanghan_npm.02548", None, None)
    assert corpus.around("cm_shanghan_npm." + "9" * 40) == ("cm_shanghan_npm.02548", None, None)
    for nothing in ("cm_shanghan_npm.preface", "nothing.00001", "cm_shanghan_npm", ""):
        assert corpus.around(nothing) == (None, None, None)
    assert corpus.without_books(["suwen_wangbing"]).around("suwen_wangbing.000.00044") == (None, None, None)
    # a reader's scope: what it withholds is not named
    scoped = ScopedCorpusView(corpus, ReadingScope(allowed=None, withheld={"suwen_wangbing.000.00043": "holdout"}))
    assert scoped.around("suwen_wangbing.000.00044") == (None, "suwen_wangbing.000.00044", "suwen_wangbing.001.00076")

