# ADR 0036 — TaoCore: a search's own rankings compiled where it pays, the same numbers everywhere

**Status:** accepted · 2026-11-26 · amends [ADR 0026](0026-pinned-supply-chain-and-enforced-policies.md) (a compiler,
a Cargo.lock and an image stage join the pinned supply chain) and [ADR 0034](0034-what-the-site-ships.md) (the site
ships `runtime/taocore.wasm`; `rust/` is a new restricted class)

## Context

A proposal of 2026-11-26, *TaoChronos High-Performance Architecture Migration Plan*, asked for a Rust engine, "TaoCore",
beneath the Python harness: crates for text, retrieval and vectors first; Python bindings (PyO3, maturin) with a pure
Python fallback; WebAssembly in the browser through Pyodide; WebAssembly in the Workers where it helps; the JavaScript
moved to TypeScript; Go where it fits; acceleration modes (python, rust-native, rust-wasm, auto, shadow) and a canary
rollout; bit-exact parity — the tokens, BM25 at k1 1.4 and b 0.75, the 512-dimension BLAKE2b hashing embedder, the
rankings; CI for formatting, lints, tests, audits, parity and the WebAssembly build; signed, reproducible artifacts.  And
its own rules: profile first, accelerate what is measured to be slow, keep the browser and the edge first, keep every
step reversible, ask for a measured gain.

Those rules were applied before anything was built.  Seven investigations, each measuring rather than estimating:

* **Where a search's time goes.**  On the 要籍语料 as the site builds it (553 books, 168 278 passages), a warm search took
  59–1 521 ms of CPU (median 558) in CPython and about 2.1 times that in Pyodide.  70% of it (the median; 67% in Pyodide)
  was the per-search indexes of `retrieval/index.py`: tokenising and indexing up to 4 800 candidates (10–54%), embedding
  up to 1 500 (10–56%, and 14–23% more where a search's distinct n-grams outran the hash cache, which then emptied and
  hashed them all again), cosines (2–6%) and BM25's scoring (0–6%).  If those cost nothing, a warm search would be 3.3
  times faster natively and 3.0 in Pyodide; a cold one only 1.56 and 1.8 (claims are extracted, passages fetched).
  `Lexicon.match` was 16–34% of searches with a sense target, SQLite about 5%, `normalize_text` at most 1.3%.
* **The rankings' inputs.**  BM25's index counted every token of every candidate; a search reads its query's tokens
  only.  Counting just those gives the same scores at a quarter to a seventh of the time, in plain Python.
* **The edge.**  The D1 backup's search spends 92% of its time in D1's SQL; the fusion that WebAssembly could replace
  costs 0.01–0.06 ms, less than copying a search's texts into a module would (0.5–1.7 ms).  The site's other Worker
  computes nothing.
* **The graph layer.**  `ClaimHypergraph` is at most 0.3% of a search, the evidence graph 0.02% of an evaluation, the
  validation gates 3–5% of a research run.  The real cost there is `LineageBuilder` (41–56% of a research run), and that is
  difflib and `Lexicon.match`, not graph code.
* **Typing the JavaScript.**  JSDoc checked by `tsc` brought a file to zero errors under `strict` with no statement
  changed, and caught 8 of 9 seeded protocol bugs; `.ts` needs an emit step whose source maps the site's policy forbids.
* **The browser.**  The page's own CSP compiles no WebAssembly (and a test pins that); the runtime worker's allows it.  A
  module of no imports, loaded beside the runtime's archives, measured: 0 CSP reports, the same results, a warm search
  2.7 times faster in Chrome.
* **What "bit-exact" takes.**  Three traps: the indexes' character class was not what it looked like (its second range
  began with 豈 U+8C48, an editor's normalisation of U+F900: one range, U+3400–U+FAFF, Hangul and the private use area
  inside); CPython's `sum()` of floats is compensated from 3.12 and plain in 3.11 (24% of dense scores differ in their
  bits between the two); and `math.log` is the C library's — glibc's FMA path and musl (Pyodide) disagree on 0.009% of
  idf's arguments, a wasm32 build's libm on 7.4%, V8's `Math.log` on 7.5%.  `sqrt` and `round` agree everywhere.

## Decision

### What is built

1. **TaoCore** in a new `rust/` workspace ([rust/README.md](../../rust/README.md)): `taocore`, the kernel — the
   characters read, BM25 in two steps, BLAKE2b-64 n-gram vectors, CPython's own summation; no dependency, no `unsafe`;
   `taocore-py`, a CPython extension (PyO3, abi3: one wheel for Python 3.11 and up); `taocore-wasm`, a module of no
   imports with a C ABI (50 KB), and no wasm-bindgen — its glue and its version-locked command line buy nothing for a
   caller that is Python.  **One call per route per search**, not one per passage (a crossing costs microseconds).
   And the full-text index's tokens (`store.grams`) for the browser's first visit, which indexes the 要籍语料 in the
   visitor's browser: measured there, SQLite's insert was 43% of that indexing, `grams` 27%, `normalize_text` 21%;
   the kernel makes a chunk's tokens at once (`taocore.grams_many`), the same strings.
2. **The same numbers by construction.**  What differs by platform stays in Python: idf's logarithm (`math.log`, the
   kernel's BM25 takes the weights the caller made from its df), the average length (Python's int / int) and which sum
   `sum()` does (detected from the interpreter's own behaviour, passed in).  Ties are broken by the candidate's place,
   which is its id's order.  So each result is the one the Python definitions give on the same interpreter: the
   extension's beside CPython, the module's beside Pyodide.
3. **One facade, failing closed** (`plugins/retrieval/taocore.py`).  It finds a kernel, checks it against the Python
   definitions on edge texts before its first use (every score, bit for bit), and on any failure during a search puts
   it aside for the process and answers in Python.  `TAOCHRONOS_TAOCORE` = `auto` · `off` · `require` · `shadow` — the
   proposal's modes, with `rust-native` and `rust-wasm` left to the platform (a browser has no extension, a server no
   module); any other value is read as `off`, so that a mistyped switch takes the kernel out rather than leave it in,
   and the status names it.  A route never asks the kernel for more results than it has candidates (the browser's
   module would keep the room for good).  A new governance rule, `native_module`, lets no other module import a
   kernel.  The browser's info and the server's log say what searches run on, as Python found it — not counts, which
   are the owner's (ADR 0035).
4. **The browser.**  `taochronos web build` copies the committed module to `runtime/taocore.wasm` and names it in the
   manifest with its SHA-256 and ABI; the worker fetches it beside the archives, imports its loader dynamically (a
   static import that failed would take the worker with it), instantiates it and registers it as `_taocore_wasm` before
   Python imports the package.  The runtime's info says which way searches run (`taocore`).
5. **The server.**  The full corpus's image builds the wheel in a Rust stage pinned by digest, with maturin from a
   hashed lockfile (`requirements/native.txt`), and keeps only the wheel.  `pip install -e .` never needs Rust.
6. **The supply chain** (ADR 0026, extended): the compiler pinned to one release (`rust/rust-toolchain.toml`, 1.97.1),
   the same in the image (a test checks); every cargo and maturin build `--locked`; the committed module rebuilt by CI
   and compared byte for byte (`rust/wasm.sh --check`; the same bytes from another directory and another `CARGO_HOME`
   were checked); `cargo-deny` — built from crates.io by its own lockfile, not a downloaded binary — reading Cargo.lock
   against RustSec's advisories each week and on every change; Dependabot for the crates; `COPY --from` in the image
   only from a stage or a digest (a gap the old test left).  CI's `native` job runs the whole suite with
   `TAOCHRONOS_TAOCORE=require`, on 3.11's plain sum and 3.12's compensated one, so that a build that failed cannot pass
   for one never tested.

### Improved in Python — better than compiling

1. **A search's BM25 counts its query's tokens only** — the scores BM25Index gave, from what it reads of the
   candidates.  Without a kernel a warm search is 1.4–1.5 times faster natively (1.2 in Pyodide).
2. **The embedder's n-gram cache** keeps two halves of 100 000 (about 19 MB at the most, its numbers shared) instead of
   emptying itself at 100 000: a large search no longer hashes every n-gram again each time.
3. **The character class written by number** (`[\u3400-\ud7ff\ue000-\ufaff]`), as the indexes have read it all along, and
   pinned by a test that names the code points; the lone surrogates left out, which no text can be encoded with and which
   stopped a search's dense route (`UnicodeEncodeError`).  The D1 backup's copy (`search.js`) the same, and its other
   copied constants (k1, b, the weights, the fusion's 60, its query tokens under Node) now pinned to the server's.
4. **The worker keeps only what the manifest names.**  It kept whatever arrived under the manifest's SHA-256 — a
   download cut short was reused on every later visit.  Now bytes are kept, and a kept copy used, only when their hash
   is the manifest's; TaoCore's module is refused outright otherwise.  The package's bytecode likewise: it was compiled
   from whatever package arrived and kept under the manifest's name, then laid over the right package on every later
   visit.  Where the browser computes no hash (`crypto.subtle` is a secure context's: an http:// page of another
   machine), nothing is kept and the module is not used.
5. **The hotspots outside retrieval, in Python** — each output proved identical (every 要籍语料 passage, the research
   scopes, the searches):
   * `Lexicon.match` tries only the lengths of the surfaces that begin where it stands (82–91% of positions begin
     none): 4.4 times faster; the searches that target a sense 1.25–1.56 times faster.
   * the lineage builder and the G3 gate keep a passage's text work for every pair or claim it is in: a research
     run's lineage 1.57 times faster on the web scope (2.47 on the demonstration corpus), G3 7.5 times, claim
     extraction 1.42 times; a whole web research run 1.20 times (demo 1.58).  What is kept is bounded by texts and by
     characters, and no text longer than 2 000 characters is kept: a passage is at most 900, but the study tools
     prepare a caller's own text, of any length (100 000 characters held 11 MB).
   * `ClaimHypergraph` builds the indexes nothing reads until one is read (5.3 ms → 0.23 ms for 1 909 claims) —
     where the proposal would have ported it — under a lock, and publishes them whole: the graph the server's threads
     share is never read half indexed.
6. **The JavaScript typed with JSDoc checked by `tsc`** (`tools/typecheck`; a file opts in with `// @ts-check` and is
   checked under `strict`), not converted to TypeScript: nothing is built or emitted, the site ships `web/` as it is.
   The RPC between the page and its worker is declared once (`tools/typecheck/types/runtime.d.ts`); of 18 seeded
   protocol bugs the check catches 17, against 2 without the annotations.

### Declined, and why

* **Three crates** (tao-text, tao-retrieval, tao-vector): one kernel of some 700 lines, because a search's two routes
  read one batch of texts — split, each crate's binding would take the texts across once more — and one ABI is one
  thing to keep in step.
* **WebAssembly in the Workers**: measured to cost more than it saves (above); the D1 backup stays JavaScript.
* **Go**: nothing measured asks for a second service language.
* **Porting the graph and validation layers**: not where the time is; a drop-in port of the hypergraph measured 1.5
  times faster where not building its unread indexes measured 2.4 (done, above), and the gates' cost was a lexicon scan
  repeated per claim (done, above).
* **The logarithm in the kernel** (a correctly rounded one shared by every platform): it would change today's scores on
  every platform; parity with each platform's own Python was asked for, and kept.
* **A PyO3 wheel for Pyodide** (wasm32-emscripten): a nightly compiler with a custom sysroot, a wheel tied to Pyodide's
  ABI, 0.2–0.5 MB; the raw module does the same work at 50 KB.
* **Signing beyond the build's own check**: what the site serves is named by SHA-256 in its manifest, the module is
  rebuilt and compared by CI, and the image pins every input; artifact attestations would add a key and an Action for
  no reader who checks them today.
* **A canary by percentage**: a kernel is used only once it gives the definitions' numbers, bit for bit, and `shadow`
  compares both on real searches — there is no "mostly right" to roll out gradually.
* **WebAssembly as protection**: a module is readable code; this one holds nothing that is not in the repository's
  Python.

## Results

| | Warm searches, the 13 measured queries | Same results |
|---|---|---|
| CPython 3.13, CPU | before 7 219 ms · Python definitions 4 801 ms (1.50×) · extension 2 177 ms (**3.32×**; 1.29–6.30× per query) | all 13 |
| Pyodide 0.28.2 (Node 22) | before 12 195 ms · Python 9 890 ms (1.23×) · module 4 064 ms (**3.00×**) | all 13 |
| Chromium 158, the built site under its CSPs | warm, 10 queries, 1.7–5.8× (桂枝汤 361 → 73 ms, 黄芪补气 584 → 121, 麻黄汤的方源 235 → 42, 风 2 783 → 621); ready 10.1 → 9.4 s | all 10, scores too, and with no loader |

The table is one run each, on a 4-vCPU machine shared with other work: other runs gave 3.1–3.3× natively (the
definitions 1.4–1.5×) and 2.9–3.0× in Pyodide (1.2×) — about the ceiling the profile set (3.3×).  The first visit's
indexing in Pyodide: the works the first answer waits for 5.3 s → 4.5 s, the whole 14.9 s → 12.6 s, the same index.  The
module is 52 322 bytes (0.18% of a first visit); the wheel 232 KB, built in about 25 s.  In Chromium a missing module, a
missing loader and a corrupt module each left a runtime that answered in Python; a module corrupted on its first
download was not kept, and the next visit used it.  Parity (`tests/test_taocore.py`): the extension gives the Python
definitions' scores bit for bit on the test corpus's 265 texts, 51 BM25 queries and 8 dense ones, under three embedder
shapes and both sums (CPython 3.11, 3.12, 3.13); the module, under Node through the worker's own loader, on 24 and 8
under two shapes; whole searches over a store give what they gave before TaoCore.

## Not done here

* **Phones, Firefox and Safari** were not measured; Chrome and Node were.
* **The first search of a visit** keeps most of its cost (claim extraction for up to 600 passages, passage fetches):
  keeping claims extracted ahead would move it, not a kernel.
* **`Lexicon.match` in the kernel**: fixed in Python first (4.4×); the next candidate if it stays hot, with the lineage
  builder's per-pair work (now about 72% of a build: `IntertextAnalyzer.features`, difflib three times a pair).
* **`normalize_text` in the kernel**: 21% of the first visit's indexing in Pyodide, but a table the domain pack loads;
  carrying it across is a change of its own.
* **The image is built by CI and by the deployment**, not here (no Docker daemon where this was written).
* **A Python floor of 3.12** would let the kernel drop its plain sum; 3.11 stays supported.
* A profile finding outside this work: 阴阳毒 is searched as 阴阳 by the alias reading — a relevance question.

## Consequences

* A search's results are what they were — by every way of computing them — and faster where a kernel is present.
* Neither the site's build nor its deployment needs Rust: the module is committed.  A change to `rust/crates/taocore*`
  is committed with the module `rust/wasm.sh` writes, or CI fails.
* The compiler moves in one change: the toolchain file, the image's Rust stage and its `RUSTUP_TOOLCHAIN`, the module.
* The full corpus's image takes a minute or two longer to build (the Rust stage; nothing of it ships but the wheel).
* **Rollback**, each one line, with nothing else to change: `TAOCHRONOS_TAOCORE=off` in the server's environment (an
  `ENV` line in the image's last stage), and in the browser's (a line in `web/js/worker.js`'s `ENV`:
  `os.environ["TAOCHRONOS_TAOCORE"] = "off"`).  The kernels stay where they are, unused, and `taocore.status()` says
  so.  Taking them out is more than a line, and takes their checks with them: the browser's module —
  `rust/crates/taocore-wasm/taocore.wasm` deleted (the build then ships none; the worker says why), with CI's
  `rust/wasm.sh --check` and the tests that read the file (`tests/test_taocore.py`, `tests/test_chat.py`,
  `tests/test_distribution.py`); the image's — its stages `maturin` and `native` and the three lines that install the
  wheel (`cloud/corpus/Dockerfile`), with the job `image`'s import of `_taocore` and the Dockerfile's half of
  `tests/test_supply_chain.py`'s toolchain test.
