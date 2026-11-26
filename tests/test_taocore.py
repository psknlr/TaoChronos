"""TaoCore (``plugins/retrieval/taocore.py``, ``rust/``): a search's own rankings are the same by every way of computing
them — the definitions in Python, the CPython extension, the browser's WebAssembly module — bit for bit, and a search
gives what it gave before they existed.

The kernels are optional: where the extension is not installed (``pip install ./rust/crates/taocore-py``) or Node is
missing, their tests skip — unless ``REQUIRE_TAOCORE=1``, which CI's native job sets, so that a build that failed cannot
pass for one that was never tested.
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
from array import array
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_retrieval_index import plain_tokens, texts

from taochronos.plugins.classics.store import grams
from taochronos.plugins.retrieval import taocore
from taochronos.plugins.retrieval.index import BM25Index, DenseIndex, HashingEmbedder, query_tokens
from taochronos.plugins.retrieval.taocore import LocalIndexes

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "rust" / "crates" / "taocore-wasm" / "taocore.wasm"
REQUIRED = os.environ.get("REQUIRE_TAOCORE") == "1"


def native():
    try:
        import _taocore  # noqa: F401
    except ImportError:
        if REQUIRED:
            raise
        pytest.skip("the CPython extension is not installed (rust/crates/taocore-py)")
    return taocore._Native(_taocore)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("TAOCHRONOS_TAOCORE", raising=False)
    taocore.reset()
    yield
    taocore.reset()


def bits(ranked):
    return [(pid, float(score).hex()) for pid, score in ranked]


# ---------------------------------------------------------------- what is compared
def corpus() -> tuple[list[str], list[str]]:
    all_texts = texts()
    ids = [f"p{i:04d}" for i in range(len(all_texts))]
    return ids, all_texts


def queries() -> list[list[str]]:
    rng = random.Random(20261126)
    asked = [query_tokens(q) for q in ("桂枝汤", "消渴", "太阳病头痛发热", "汗", "阴阳", "麻黄汤主之", "不存在的词语", "汤汤", "豈更")]
    asked.append(query_tokens("桂枝") * 3)  # a token asked more than once counts each time
    asked.append(query_tokens("桂枝") + ["汤"] + query_tokens("消渴"))  # a character among bigrams (several surfaces)
    pool = "".join(texts())
    for _ in range(40):  # tokens of the texts themselves: common and rare, one character and two
        start = rng.randrange(len(pool) - 8)
        asked.append(query_tokens(pool[start: start + rng.choice([1, 2, 3, 5, 8])]))
    return [q for q in asked if q]


DENSE_TEXTS = ("桂枝汤的主治", "消渴 三消", "太阳之为病，脉浮，头项强痛而恶寒", "汗出恶风", "", "abc", "汤汤汤", "桂\ud800枝")


def dense_places(n: int) -> list[int]:
    rng = random.Random(5)
    places = list(range(n))
    rng.shuffle(places)  # the index's best first: any order, the dense route keeps it
    return places[: n * 2 // 3]


# ---------------------------------------------------------------- the definitions
def test_the_definitions_rank_as_the_indexes_did():
    """A search's own BM25 counts only its query's tokens, and gives what an index of every token gave."""
    ids, all_texts = corpus()
    old = BM25Index()
    for pid, text in zip(ids, all_texts):
        old.add(pid, text)
    for embedder in (HashingEmbedder(), HashingEmbedder(dim=64, ngram=(2, 4))):
        local = LocalIndexes(ids, all_texts, dense_places(len(ids)), embedder)
        for query in queries():
            for k in (1, 20, 10_000):
                assert bits(local._bm25_python(query, k)) == bits(old.search(query, k))
        dense = DenseIndex(embedder)
        for place in local.dense_places:
            dense.add(ids[place], all_texts[place])
        for text in DENSE_TEXTS:
            for k in (1, 30, 10_000):
                assert bits(local._dense_python(text, k)) == bits(dense.search(text, k))


def test_a_search_gives_what_it_gave_before(tmp_path):
    """Whole searches over a store (a large corpus: each search makes its own rankings) give the passages, scores and
    routes they gave when each search built a BM25Index and a DenseIndex — by the definitions, and by a kernel."""
    retriever, store = fixture_retriever(tmp_path)

    class Before:  # what _local_indexes made until TaoCore
        def __init__(self, cand):
            self.bm = BM25Index()
            for pid in cand:
                self.bm.add(pid, retriever.norm(pid))
            self.dn = DenseIndex(retriever.embedder)
            order = sorted(cand, key=lambda pid: (-retriever._rank.get(pid, 0.0), pid))[:1500]
            for pid in order:
                self.dn.add(pid, retriever.norm(pid))

        def bm25(self, toks, k):
            return self.bm.search(toks, k)

        def dense(self, text, k):
            return self.dn.search(text, k)

    asked = ["五苓散", "消渴", "小便不利", "脉浮", "桂枝汤主之", "太阳病，发汗后，大汗出", "汗"]

    def found():
        out = {}
        for text in asked:
            q, hits = retriever.search(text, k=12)
            out[text] = [(h.passage_id, h.score, sorted(h.routes.items())) for h in hits]
        return out

    now = retriever._local_indexes
    retriever._local_indexes = Before
    before = found()
    retriever._local_indexes = now
    assert any(before.values())
    os.environ["TAOCHRONOS_TAOCORE"] = "off"
    try:
        assert found() == before
    finally:
        del os.environ["TAOCHRONOS_TAOCORE"]
    if taocore.kernel() is not None or REQUIRED:
        os.environ["TAOCHRONOS_TAOCORE"] = "require"
        try:
            assert found() == before
            assert taocore.status()["bm25"] and taocore.status()["dense"]
        finally:
            del os.environ["TAOCHRONOS_TAOCORE"]
    store.close()


def fixture_retriever(where: Path):
    from taochronos.plugins.classics.domain import DomainPack
    from taochronos.plugins.classics.ingest import ingest_kanripo, load_catalog
    from taochronos.plugins.classics.store import CorpusStore, StoreCorpus
    from taochronos.plugins.retrieval import HybridRetriever

    fixtures = ROOT / "tests" / "fixtures" / "kanripo"
    pack = DomainPack(ROOT / "domains" / "classics")
    store = CorpusStore(where / "corpus" / "tcm.sqlite", create=True)
    ingest_kanripo(store, load_catalog(fixtures / "catalog.yaml"), fixtures, pack.variants.normalize_text,
                   pack.variants.fingerprint, log=lambda m: None, dynasty_of=pack.periods.dynasty_of)
    store.optimize()
    retriever = HybridRetriever(pack, StoreCorpus(store, pack.variants.normalize_text, fingerprint=pack.variants.fingerprint))
    assert retriever.large
    return retriever, store


# ---------------------------------------------------------------- the CPython extension
def test_the_extension_ranks_as_the_definitions_do():
    kern = native()
    assert taocore._selftest(kern) == ""
    ids, all_texts = corpus()
    for embedder in (HashingEmbedder(), HashingEmbedder(dim=64, ngram=(2, 4)), HashingEmbedder(dim=500, ngram=(3, 1))):
        local = LocalIndexes(ids, all_texts, dense_places(len(ids)), embedder)
        for query in queries():
            for k in (1, 20, 10_000):
                assert bits(local._bm25_kernel(kern, query, k)) == bits(local._bm25_python(query, k)), query
        for text in DENSE_TEXTS:
            for k in (1, 30, 10_000):
                assert bits(local._dense_kernel(kern, text, k)) == bits(local._dense_python(text, k)), text


# texts for the full-text tokens (store.grams): its runs are of another class than the indexes' — planes 2 and 3, 〇, 〓
TOKEN_EDGES = ["", "。", "桂", "桂枝汤", "桂枝，汤。", "，桂", "abc 桂 x", "〇𠀀𪚥〓", "\U0003134f\U00031350\u3007", "한글\ue3e7桂枝",
               "桂\ud800枝", "汤汤汤", "\u33ff\u3400\u9fff\ua000\uf8ff\uf900\ufaff\ufb00", "\x1e桂\x1e"]


def test_the_extension_makes_the_full_text_tokens_the_store_makes():
    kern = native()
    every = [*TOKEN_EDGES, *texts()]
    assert taocore._grams_kernel(kern, every) == [grams(t) for t in every]
    assert taocore._grams_kernel(kern, ["桂枝"]) == ["桂枝 枝z"]
    with pytest.raises(taocore.Unsuitable):
        taocore._grams_kernel(kern, ["桂\x1f枝", "汤"])  # the separator inside a text: the definitions' to do


def test_the_extension_refuses_what_is_not_its_input():
    kern = native()
    import _taocore

    with pytest.raises(ValueError):
        _taocore.Batch("桂\x1f枝".encode(), 3)
    with pytest.raises(ValueError):
        _taocore.Batch(b"\xff\xfe", 1)
    batch = _taocore.Batch("桂枝汤".encode(), 1)
    with pytest.raises(ValueError):
        batch.bm25([1.0], 1.0, 1.4, 0.75, 5)  # nothing counted yet
    with pytest.raises(ValueError):
        batch.count(["桂枝汤"])  # three characters: no token
    assert batch.count(["桂枝", "桂"]) == ([1, 1], 5)
    with pytest.raises(ValueError):
        batch.bm25([1.0], 1.0, 1.4, 0.75, 5)  # two tokens counted, one weight
    with pytest.raises(ValueError):
        batch.dense([1], b"x", 512, [1], True, 0.05, 5)  # no document 1
    with pytest.raises(ValueError):
        batch.dense([0], b"x", 0, [1], True, 0.05, 5)
    with pytest.raises(ValueError):
        batch.dense([0], b"x", 512, [43], True, 0.05, 5)
    assert kern.name == "native"


# ---------------------------------------------------------------- the browser's module, under Node
NODE_RUN = r"""
import { readFileSync, writeFileSync } from "node:fs";
import { loadTaoCore } from "./taocore.js";
const input = JSON.parse(readFileSync("in.json", "utf8"));
const core = await loadTaoCore(readFileSync("taocore.wasm"));
const enc = new TextEncoder();
const f64 = (xs) => new Uint8Array(new Float64Array(xs).buffer);
const u32 = (xs) => new Uint8Array(new Uint32Array(xs).buffer);
const out = [];
for (const c of input.cases) {
  const b = core.batch(enc.encode(c.texts.join("\u001f")), c.texts.length);
  const r = {};
  if (c.tokens) {
    const got = b.count(enc.encode(c.tokens.join("\n")));
    r.df = got.df; r.total = got.total;
    r.bm25 = b.bm25(f64(c.idf), c.avgdl, 1.4, 0.75, c.k);
  }
  if (c.dense !== undefined) r.dense = b.dense(u32(c.places), enc.encode(c.dense), c.dim, u32(c.ngram), c.compensated, 0.05, c.k);
  b.free();
  out.push(r);
}
const tokens = core.grams(enc.encode(input.grams.join("\u001f")), input.grams.length).split("\u001f");
let refused = 0;  // what the module must not take
for (const bad of [() => core.batch(enc.encode("a\u001fb"), 3), () => core.batch(new Uint8Array([0xff]), 1)]) {
  try { bad(); } catch { refused++; }
}
const one = core.batch(enc.encode("桂枝汤"), 1);
for (const bad of [() => one.count(enc.encode("桂枝汤")), () => one.bm25(f64([1]), 1, 1.4, 0.75, 3),
                   () => one.dense(u32([1]), enc.encode("x"), 512, u32([1]), 1, 0.05, 3),
                   () => one.dense(u32([0]), enc.encode("x"), 512, u32([0]), 1, 0.05, 3)]) {
  try { bad(); } catch { refused++; }
}
for (let i = 0; i < 6; i++) core.batch(enc.encode("x"), 1);  // the module keeps the last few batches: one pushed out is refused
try { one.count(enc.encode("桂")); } catch { refused++; }
try { core.grams(enc.encode("a\u001fb"), 3); } catch { refused++; }
writeFileSync("out.json", JSON.stringify({ out, refused, tokens }));
"""


def test_the_browser_module_ranks_as_the_definitions_do(tmp_path):
    node = shutil.which("node")
    if not node:
        if REQUIRED:
            raise AssertionError("node is needed to test the browser's module")
        pytest.skip("node is not installed")
    ids, all_texts = corpus()
    cases, want = [], []
    for embedder in (HashingEmbedder(), HashingEmbedder(dim=64, ngram=(2, 4))):
        local = LocalIndexes(ids, all_texts, dense_places(len(ids)), embedder)
        n = len(all_texts)
        lengths = [len(plain_tokens(t)) for t in all_texts]
        counted = [Counter(plain_tokens(t)) for t in all_texts]
        for query in queries()[:24]:
            distinct = list(dict.fromkeys(query))
            df = [sum(1 for c in counted if c[t]) for t in distinct]
            idf = [math.log(1 + (n - x + 0.5) / (x + 0.5)) for x in df]
            cases.append({"texts": all_texts, "tokens": query, "idf": idf, "avgdl": sum(lengths) / n, "k": 50})
            want.append({"df": df, "total": sum(lengths), "bm25": local._bm25_python(query, 50)})
        for text in DENSE_TEXTS:
            cases.append({"texts": all_texts, "dense": text, "places": local.dense_places, "dim": embedder.dim,
                          "ngram": list(embedder.ngram), "compensated": int(taocore.COMPENSATED), "k": 60})
            want.append({"dense": local._dense_python(text, 60)})
    shutil.copy(ROOT / "web" / "js" / "taocore.js", tmp_path / "taocore.js")
    shutil.copy(MODULE, tmp_path / "taocore.wasm")
    token_texts = [*TOKEN_EDGES, *all_texts]
    (tmp_path / "in.json").write_text(json.dumps({"cases": cases, "grams": token_texts}), encoding="utf-8")
    (tmp_path / "run.mjs").write_text(NODE_RUN, encoding="utf-8")
    run = subprocess.run([node, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr
    got = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert got["refused"] == 8
    assert got["tokens"] == [grams(t) for t in token_texts]  # the full-text tokens, every one
    for case, w, g in zip(cases, want, got["out"]):
        if "bm25" in w:
            assert g["df"] == w["df"] and g["total"] == w["total"]
            assert bits(list(zip([ids[p] for p in g["bm25"]["places"]], g["bm25"]["scores"]))) == bits(w["bm25"]), case["tokens"]
        else:
            assert bits(list(zip([ids[p] for p in g["dense"]["places"]], g["dense"]["scores"]))) == bits(w["dense"]), case["dense"]


def test_the_module_is_what_the_source_builds():
    """The module is committed (a deployment needs no Rust); CI rebuilds it and compares the bytes (``rust/wasm.sh
    --check``).  Here: it is there, it is WebAssembly with no imports, and its exports are the loader's ABI."""
    data = MODULE.read_bytes()
    assert data[:4] == b"\0asm" and len(data) < 200_000
    node = shutil.which("node")
    if not node:
        return
    script = ("const m = new WebAssembly.Module(require('fs').readFileSync(process.argv[1]));"
              "console.log(JSON.stringify([WebAssembly.Module.imports(m), WebAssembly.Module.exports(m).map(e => e.name).sort()]))")
    imports, exports = json.loads(subprocess.run([node, "-e", script, str(MODULE)], capture_output=True, text=True,
                                                 check=True).stdout)
    assert imports == []
    assert exports == sorted(["memory", "tc_abi", "tc_alloc", "tc_free", "tc_batch", "tc_batch_free", "tc_total", "tc_count",
                              "tc_bm25", "tc_dense", "tc_grams", "tc_result", "tc_result_len"])


RAW = r"""
import { readFileSync, writeFileSync } from "node:fs";
const { instance } = await WebAssembly.instantiate(readFileSync("taocore.wasm"), {});
const x = instance.exports;
const put = (bytes) => { const p = x.tc_alloc(bytes.length); new Uint8Array(x.memory.buffer, p, bytes.length).set(bytes); return [p, bytes.length]; };
const enc = new TextEncoder();
const [t, tl] = put(enc.encode("桂枝汤\u001f桂枝\u001f汤"));
const id = x.tc_batch(t, tl, 3);
const [q, ql] = put(enc.encode("桂枝"));
const df = x.tc_alloc(8);  // room for one df
const idf = x.tc_alloc(8);
new Float64Array(x.memory.buffer, idf, 1).set([1.0]);
const said = { batch: id > 0, counted: x.tc_count(id, q, ql, df, 1), overstated: x.tc_count(id, q, ql, df, 2) };
let places = x.tc_alloc(4), scores = x.tc_alloc(8);  // room for one result
const bm25 = (k, p = places, s = scores) => x.tc_bm25(id, idf, 1, 2.0, 1.4, 0.75, k, p, s);
Object.assign(said, { one: bm25(1), three: bm25(3), wrapped: bm25(2 ** 30 + 1), stray: bm25(1, 64, 128),
                      textStray: x.tc_batch(16, 9, 1), textPast: x.tc_batch(t, tl + 64, 3) });
x.tc_free(places, 4);
said.freed = bm25(1);
x.tc_free(places, 4);  // twice: nothing
x.tc_free(scores, 16);  // another length than given: nothing
said.notFreed = bm25(1, x.tc_alloc(4), scores);
writeFileSync("out.json", JSON.stringify(said));
"""


def test_the_module_reads_and_writes_only_within_what_it_gave(tmp_path):
    """The module checks a buffer's size against what tc_alloc gave, whatever its caller says: room claimed past an
    allocation (as the loader once claimed for a k past 2^30, whose bytes wrapped), a pointer it never gave, a buffer
    given back — each is refused (-1, or 0 for a batch), where it would have written or read past what was given.  A
    second free, or one with another length, frees nothing."""
    node = shutil.which("node")
    if not node:
        if REQUIRED:
            raise AssertionError("node is needed to test the browser's module")
        pytest.skip("node is not installed")
    shutil.copy(MODULE, tmp_path / "taocore.wasm")
    (tmp_path / "run.mjs").write_text(RAW, encoding="utf-8")
    run = subprocess.run([node, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    said = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert said == {"batch": True, "counted": 1, "overstated": -1, "one": 1, "three": -1, "wrapped": -1, "stray": -1,
                    "textStray": 0, "textPast": 0, "freed": -1, "notFreed": 1}


def _wasm(names: list[str]) -> bytes:
    """A WebAssembly module of one function, () -> i32 giving the ABI, exported under each of ``names``; and a memory."""

    def leb(n: int) -> bytes:
        out = bytearray()
        while True:
            low, n = n & 0x7F, n >> 7
            out.append(low | (0x80 if n else 0))
            if not n:
                return bytes(out)

    def vec(items: list[bytes]) -> bytes:
        return leb(len(items)) + b"".join(items)

    def section(kind: int, body: bytes) -> bytes:
        return bytes([kind]) + leb(len(body)) + body

    exports = [leb(len(name)) + name.encode() + b"\x00\x00" for name in names] + [b"\x06memory\x02\x00"]
    return (b"\0asm\x01\0\0\0" + section(1, vec([b"\x60\x00\x01\x7f"])) + section(3, vec([b"\x00"]))
            + section(5, vec([b"\x00\x01"])) + section(7, vec(exports))
            + section(10, vec([b"\x04\x00\x41" + bytes([taocore.ABI]) + b"\x0b"])))


LOADS = r"""
import { readFileSync, writeFileSync } from "node:fs";
import { loadTaoCore } from "./taocore.js";
const said = {};
for (const name of ["bare", "half", "older", "real"]) {
  try { said[name] = Object.keys(await loadTaoCore(readFileSync(`${name}.wasm`))).sort(); }
  catch (e) { said[name] = String(e.message); }
}
writeFileSync("out.json", JSON.stringify(said));
"""


def test_the_loader_takes_a_module_only_with_what_it_calls(tmp_path):
    """A module that speaks the ABI but lacks a function the loader calls is refused as it loads (the searches stay in
    Python from the start), not at a search; one without the tokens' functions is taken without ``grams``, and the
    facade then makes the tokens in Python and keeps the module for the searches."""
    node = shutil.which("node")
    if not node:
        if REQUIRED:
            raise AssertionError("node is needed to test the browser's loader")
        pytest.skip("node is not installed")
    calls = ["tc_alloc", "tc_free", "tc_batch", "tc_batch_free", "tc_total", "tc_count", "tc_bm25", "tc_dense"]
    for name, exported in (("bare", ["tc_abi"]), ("half", ["tc_abi", *calls[:-1]]), ("older", ["tc_abi", *calls])):
        (tmp_path / f"{name}.wasm").write_bytes(_wasm(exported))
    shutil.copy(MODULE, tmp_path / "real.wasm")
    shutil.copy(ROOT / "web" / "js" / "taocore.js", tmp_path / "taocore.js")
    (tmp_path / "run.mjs").write_text(LOADS, encoding="utf-8")
    run = subprocess.run([node, "run.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    said = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert said == {"bare": f"taocore: the module lacks {', '.join(calls)}", "half": "taocore: the module lacks tc_dense",
                    "older": ["abi", "batch"], "real": ["abi", "batch", "grams"]}
    with pytest.raises(taocore.Unsuitable):  # the facade over a loader without grams
        taocore._Wasm(SimpleNamespace(abi=1, batch=lambda data, count: None)).grams(b"x", 1)


# ---------------------------------------------------------------- choosing, and failing closed
class Fake:
    """A kernel for the tests: the extension's answers, or none (``broken``), or other numbers (``wrong``)."""

    name = "fake"

    def __init__(self, inner, *, broken: bool = False, wrong: bool = False, wrong_tokens: bool = False):
        self.inner, self.broken, self.wrong, self.wrong_tokens = inner, broken, wrong, wrong_tokens

    def grams(self, data, count):
        if self.broken:
            raise RuntimeError("a trap")
        got = self.inner.grams(data, count)
        return got.replace("z", "y", 1) if self.wrong_tokens else got

    def batch(self, data, count):
        inner = self.inner.batch(data, count)
        fake = self

        class Batch:
            def count(self, tokens):
                if fake.broken:
                    raise RuntimeError("a trap")
                return inner.count(tokens)

            def bm25(self, idf, avgdl, k):
                places, scores = inner.bm25(idf, avgdl, k)
                return places, [s * (1 + 2 ** -50) if fake.wrong else s for s in scores]

            def dense(self, *args):
                return inner.dense(*args)

        return Batch()


class Definitions:
    """A kernel that is the definitions themselves (to test the choosing without the extension)."""

    name = "definitions"

    def grams(self, data, count):
        texts = data.decode("utf-8").split(taocore.SEPARATOR)
        assert len(texts) == count
        return taocore.SEPARATOR.join(grams(t) for t in texts)

    def batch(self, data, count):
        texts = data.decode("utf-8").split(taocore.SEPARATOR)
        assert len(texts) == count

        class Batch:
            def count(self, tokens):
                self.tokens = tokens
                counted = [Counter(plain_tokens(t)) for t in texts]
                return [sum(1 for c in counted if c[t]) for t in dict.fromkeys(tokens)], sum(len(plain_tokens(t)) for t in texts)

            def bm25(self, idf, avgdl, k):
                local = LocalIndexes([f"{i:06d}" for i in range(len(texts))], texts, [], HashingEmbedder())
                got = local._bm25_python(self.tokens, k)
                return [int(pid) for pid, _ in got], [s for _, s in got]

            def dense(self, places, query, dim, ngram, k):
                local = LocalIndexes([f"{i:06d}" for i in range(len(texts))], texts, places, HashingEmbedder(dim, tuple(ngram)))
                got = local._dense_python(query.decode("utf-8"), k)
                return [int(pid) for pid, _ in got], [s for _, s in got]

        return Batch()


def test_a_kernel_is_used_only_once_it_ranks_as_the_definitions_do(monkeypatch):
    monkeypatch.setattr(taocore, "_find", lambda: (Fake(Definitions(), wrong=True), ""))
    assert taocore.kernel() is None
    assert "BM25 differed" in taocore.status()["reason"]
    taocore.reset()
    monkeypatch.setattr(taocore, "_find", lambda: (Fake(Definitions(), broken=True), ""))
    assert taocore.kernel() is None and "the self-test failed" in taocore.status()["reason"]
    taocore.reset()
    monkeypatch.setattr(taocore, "_find", lambda: (Definitions(), ""))
    assert taocore.kernel() is not None and taocore.status()["kernel"] == "definitions"


def test_a_kernel_that_fails_in_a_search_is_put_aside_and_the_search_answers(monkeypatch):
    ids, all_texts = corpus()
    local = LocalIndexes(ids, all_texts, dense_places(len(ids)), HashingEmbedder())
    want = local._bm25_python(["桂枝", "枝汤"], 20)
    breaking = Fake(Definitions())
    monkeypatch.setattr(taocore, "_find", lambda: (breaking, ""))
    assert taocore.kernel() is breaking  # it passed its self-test
    breaking.broken = True
    assert bits(local.bm25(["桂枝", "枝汤"], 20)) == bits(want)
    s = taocore.status()
    assert s["kernel"] is None and s["failed"] == 1 and "put aside" in s["reason"]
    assert bits(local.bm25(["桂枝", "枝汤"], 20)) == bits(want)  # and from then on, without it
    assert taocore.status()["failed"] == 1


def test_the_modes(monkeypatch):
    ids, all_texts = corpus()
    local = LocalIndexes(ids, all_texts, dense_places(len(ids)), HashingEmbedder())
    want = local._bm25_python(["消渴"], 20)
    monkeypatch.setattr(taocore, "_find", lambda: (None, "no kernel here"))
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "require")
    with pytest.raises(RuntimeError, match="no kernel here"):
        local.bm25(["消渴"], 20)
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "off")
    assert bits(local.bm25(["消渴"], 20)) == bits(want) and taocore.status()["reason"] == "TAOCHRONOS_TAOCORE=off"
    # shadow: both computed, the definitions' answer given, a difference counted
    taocore.reset()
    drifting = Fake(Definitions())
    monkeypatch.setattr(taocore, "_find", lambda: (drifting, ""))
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "shadow")
    assert taocore.kernel() is drifting
    drifting.wrong = True
    assert bits(local.bm25(["消渴"], 20)) == bits(want)
    assert taocore.status()["differed"] == 1
    # what is not the kernel's to compute is computed by the definitions, and the kernel stays
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "auto")
    drifting.wrong = False
    odd = LocalIndexes(["a", "b"], ["桂枝\x1f汤", "消渴"], [0, 1], HashingEmbedder())
    assert odd.bm25(["桂枝"], 5) == odd._bm25_python(["桂枝"], 5)
    other = LocalIndexes(ids, all_texts, [0, 1, 2], type("Other", (HashingEmbedder,), {})())
    assert bits(other.dense("桂枝汤", 5)) == bits(other._dense_python("桂枝汤", 5))
    assert taocore.kernel() is drifting and taocore.status()["failed"] == 0
    # a switch written otherwise is read as off — the kernel taken out rather than left in — and the status says why
    for written in ("python", "0", "false", "OFF", " off "):
        monkeypatch.setenv("TAOCHRONOS_TAOCORE", written)
        assert taocore.mode() == "off" and taocore.status()["reason"] == f"TAOCHRONOS_TAOCORE={written.strip()}"
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "requrie")
    assert taocore.mode() == "off" and "'requrie' is not one of auto, off, require, shadow" in taocore.status()["reason"]
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "")
    assert taocore.mode() == "auto"


def test_the_full_text_tokens_by_every_way(monkeypatch):
    """The first visit indexes the 要籍语料 with store.grams of each passage (webcorpus.index_store): by the kernel where
    there is one, the same strings; and what the kernel may not or cannot do, the definitions do."""
    every = [*TOKEN_EDGES, *texts()[:80]]
    want = [grams(t) for t in every]
    monkeypatch.setattr(taocore, "_find", lambda: (None, "none here"))
    assert taocore.grams_many(every) == want and taocore.grams_many([]) == []
    taocore.reset()
    kernel = Fake(Definitions())
    monkeypatch.setattr(taocore, "_find", lambda: (kernel, ""))
    assert taocore.grams_many(every) == want and taocore.status()["grams"] == 1
    assert taocore.grams_many(["桂\x1f枝"]) == [grams("桂\x1f枝")]  # the separator: the definitions, the kernel kept
    kernel.wrong_tokens = True
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "shadow")
    assert taocore.grams_many(every) == want and taocore.status()["differed"] == 1
    kernel.wrong_tokens, kernel.broken = False, True
    monkeypatch.setenv("TAOCHRONOS_TAOCORE", "auto")
    assert taocore.grams_many(every) == want and taocore.status()["kernel"] is None  # put aside
    taocore.reset()
    kernel.broken, kernel.wrong_tokens = False, True
    assert taocore.kernel() is None and "full-text tokens differed" in taocore.status()["reason"]  # the self-test

    class Before:  # an extension built before it made the tokens: searched with, the tokens made in Python
        name = "before"

        def __init__(self):
            self.inner = Definitions()

        def batch(self, data, count):
            return self.inner.batch(data, count)

        def grams(self, data, count):
            raise taocore.Unsuitable("no grams here")

    taocore.reset()
    monkeypatch.setattr(taocore, "_find", lambda: (Before(), ""))
    assert taocore.kernel() is not None and taocore.grams_many(every) == want and taocore.status()["python"] >= 1


def test_k_is_never_more_room_than_candidates_and_a_negative_one_is_pythons():
    """A route asks for k results; the browser's module reserves room for them in a memory that never shrinks, so the
    facade asks for no more than there are candidates (the same results), and leaves a negative k — Python's slice,
    which drops from the end — to the definitions."""
    kern = native()
    ids, all_texts = corpus()
    local = LocalIndexes(ids, all_texts, dense_places(len(ids)), HashingEmbedder())
    for k in (10**9, len(ids), len(ids) + 1):
        assert bits(local._bm25_kernel(kern, ["桂枝", "枝汤"], k)) == bits(local._bm25_python(["桂枝", "枝汤"], k))
        assert bits(local._dense_kernel(kern, "桂枝汤", k)) == bits(local._dense_python("桂枝汤", k))
    with pytest.raises(taocore.Unsuitable):
        local._bm25_kernel(kern, ["桂枝"], -1)
    with pytest.raises(taocore.Unsuitable):
        local._dense_kernel(kern, "桂枝", -2)
    assert bits(local.bm25(["桂枝"], -1)) == bits(local._bm25_python(["桂枝"], -1))  # and the definitions answer


class LoaderStandIn:
    """web/js/taocore.js's object as Python reaches it under Pyodide, over the extension: what it is given read as the
    loader reads it (Python bytes as UTF-8, as float64s, as uint32s), what it gives back as JavaScript does (arrays of
    numbers, an integral one arriving as a Python int).  So the browser adapter's half of the boundary (taocore._Wasm)
    is tested where there is no browser; the loader's half is the Node test above."""

    abi = 1

    def __init__(self, module):
        self._m = module

    @staticmethod
    def _js(numbers):
        return [int(x) if float(x).is_integer() else x for x in numbers]

    def batch(self, data, count):
        assert isinstance(data, bytes) and isinstance(count, int)
        inner, js = self._m.Batch(data, count), self._js

        class Batch:
            def count(self, tokens):
                assert isinstance(tokens, bytes)
                df, total = inner.count(tokens.decode("utf-8").split("\n") if tokens else [])
                return SimpleNamespace(df=js(df), total=total)

            def bm25(self, idf, avgdl, k1, b, k):
                assert isinstance(idf, bytes) and (k1, b) == (1.4, 0.75)
                places, scores = inner.bm25(list(array("d", idf)), avgdl, k1, b, k)
                return SimpleNamespace(places=js(places), scores=js(scores))

            def dense(self, docs, query, dim, ngram, compensated, threshold, k):
                assert isinstance(docs, bytes) and isinstance(query, bytes) and isinstance(ngram, bytes)
                assert compensated in (0, 1) and type(compensated) is int and threshold == 0.05
                places, scores = inner.dense(list(array("I", docs)), query, dim, list(array("I", ngram)), bool(compensated),
                                             threshold, k)
                return SimpleNamespace(places=js(places), scores=js(scores))

            def free(self):
                pass

        return Batch()

    def grams(self, data, count):
        assert isinstance(data, bytes)
        return self._m.grams(data, count)


def test_the_browser_adapter_speaks_the_loaders_language():
    """taocore._Wasm, which the browser's searches go through: its self-test passes over a stand-in of the loader, and its
    rankings and tokens are the definitions'.  (An argument in the wrong order or form fails here, in CI, and not only in
    a visitor's browser, where the self-test would leave the searches to Python without a word.)"""
    native()
    import _taocore

    kern = taocore._Wasm(LoaderStandIn(_taocore))
    assert kern.name == "wasm" and taocore._selftest(kern) == ""
    ids, all_texts = corpus()
    for embedder in (HashingEmbedder(), HashingEmbedder(dim=64, ngram=(2, 4))):
        local = LocalIndexes(ids, all_texts, dense_places(len(ids)), embedder)
        for query in queries()[:20]:
            assert bits(local._bm25_kernel(kern, query, 40)) == bits(local._bm25_python(query, 40)), query
        for text in DENSE_TEXTS:
            assert bits(local._dense_kernel(kern, text, 40)) == bits(local._dense_python(text, 40)), text
    every = [*TOKEN_EDGES, *all_texts]
    assert taocore._grams_kernel(kern, every) == [grams(t) for t in every]
