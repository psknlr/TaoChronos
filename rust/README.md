# TaoCore

What a search computes over its candidates — BM25 of the query's tokens and the hashed character n-gram cosines of
`src/taochronos/plugins/retrieval/index.py` — compiled: **the same numbers, bit for bit**, several times faster; and the
full-text index's tokens (`store.grams`) the browser's first visit indexes the 要籍语料 with, the same strings.  Why,
what was measured and what was left out: [ADR 0036](../docs/adr/0036-taocore.md).

| Crate | What | Reaches Python as |
|---|---|---|
| `crates/taocore` | the kernel: the characters read, BM25 in two steps, BLAKE2b-64 n-gram vectors, CPython's own `sum()`, the full-text tokens; no dependency, no `unsafe` | — |
| `crates/taocore-py` | the CPython extension (PyO3, abi3: one wheel for Python 3.11 and up) | `import _taocore` |
| `crates/taocore-wasm` | the browser's module: wasm32, no imports, a C ABI; committed as `taocore.wasm` | `import _taocore_wasm` (the runtime worker registers it: `web/js/taocore.js`) |

Only the facade `src/taochronos/plugins/retrieval/taocore.py` imports either (governance's `native_module` rule).  It
checks a kernel against the Python definitions before using it, and falls back to them on any failure:
`TAOCHRONOS_TAOCORE` = `auto` (default) · `off` · `require` (a search fails without a kernel: CI) · `shadow` (both
computed, Python's answer given, differences counted in `taocore.status()`).

What stays in Python, because it differs by platform: a token's weight (idf) is `math.log` of the C library Python runs
on, the average length is Python's int / int, and which summation `sum()` does (compensated from CPython 3.12) is
detected and passed in.

## Building

The compiler is pinned to one release (`rust-toolchain.toml`; rustup reads it here and below, not from the repository's
root).  With [rustup](https://rustup.rs):

```bash
cd rust && rustup toolchain install --no-self-update
```

The extension, into the environment taochronos is installed in (maturin from the hashed lockfile):

```bash
pip install --require-hashes -r requirements/native.txt
```

```bash
pip install --no-deps --no-build-isolation ./rust/crates/taocore-py
```

Then `python -c "from taochronos.plugins.retrieval import taocore; print(taocore.status())"` names `native`.

The browser's module is committed, so that neither the site's build nor its deployment needs Rust.  After a change to
`crates/taocore` or `crates/taocore-wasm`, write it again and commit it — CI rebuilds it and fails unless the bytes are
the same (`rust/wasm.sh --check`), which needs the pinned compiler (another release gives other bytes):

```bash
rust/wasm.sh
```

## Checks

What CI runs (`.github/workflows/ci.yml`, jobs `rust`, `native` and `image`; `audit.yml`, job `rust`):

```bash
cd rust && cargo fmt --all --check && cargo clippy --locked --workspace --all-targets -- -D warnings && cargo test --locked --workspace
```

```bash
REQUIRE_TAOCORE=1 TAOCHRONOS_TAOCORE=require pytest tests/test_taocore.py tests/test_retrieval_index.py
```

`tests/test_taocore.py` compares, bit for bit: the Python path with the indexes it replaced; the extension with the Python
path (Python 3.11's plain sum and 3.12's compensated one); the module, run under Node through the worker's loader, with
the Python path; whole searches with what they gave before TaoCore.  `cargo deny --locked check` reads `Cargo.lock`
against RustSec's advisories and `deny.toml`'s rules (crates.io only, permissive licences, nothing yanked).

## Measuring

The ADR's numbers come from warm searches on the 要籍语料, three ways interleaved — before TaoCore, by the Python
definitions, on the kernel — with every result compared (made there from `corpus/web` when the store is missing):

```bash
PYTHONPATH=src python rust/bench.py /tmp/taocore-bench
```

## Bumping

* **The compiler**: `rust-toolchain.toml`'s `channel`, the Rust stage of `cloud/corpus/Dockerfile` (its tag and digest,
  and `RUSTUP_TOOLCHAIN`), then `rust/wasm.sh` and the new `taocore.wasm` — in one change
  (`tests/test_supply_chain.py` checks they agree).
* **A crate** (Dependabot proposes them): `Cargo.lock` changes; the audit workflow reads it on the pull request.
* **The ABI** (`taocore::ABI`): the loader's `ABI` (`web/js/taocore.js`) and the facade's (`taocore.py`) with it.  A
  worker and a module of different ABIs refuse each other, and the search runs in Python.
