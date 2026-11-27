# The platform's Workers, in Rust

The developer API (api.impf.ai) and the account console (console.impf.ai): who a person is, what an API key may do,
what a call costs — [ADR 0038](../../docs/adr/0038-accounts-keys-and-credits.md).  A Cargo workspace of its own, apart
from TaoCore's (`../Cargo.toml`): its dependencies and its policy (`deny.toml`) are its own.  The compiler is the one
`../rust-toolchain.toml` pins.

| Crate | What |
|---|---|
| `core` (`tao-platform`) | every decision, synchronous, over any SQLite: `identity` (email codes, grants, sessions, recovery), `webauthn` and `cbor` (passkeys, WebAuthn L3 §7.1–7.2), `accounts` and `keys` (organisations' keys, credits, reservations), `api` (the products' requests and the corpus's answers), `mail` (templates, the outbox's drain); `crypto`, `codec`, `email`, `sql`, `time` beneath.  Tested natively, over SQLite (rusqlite) |
| `edge` (`tao-edge`) | what both Workers need of Cloudflare's runtime: the core's `Sql` over a Durable Object's SQLite, entropy, the clock, answers |
| `api` (`tao-api`) | api.impf.ai: the gateway and the `Account` Durable Object (one an organisation) — deployed from `cloud/api` |
| `console` (`tao-console`) | console.impf.ai: the backend-for-frontend, the `Identity` Durable Object and its mail, the page (`public/`) — deployed from `cloud/console` |

In a Durable Object nothing else runs while a synchronous method runs: every method of the cores reads, decides and
writes with no `.await` in between, which is the whole of their concurrency control.

## Checks

```bash
(cd rust/platform && cargo fmt --all --check && cargo clippy --locked -p tao-platform --all-targets -- -D warnings && cargo clippy --locked --target wasm32-unknown-unknown -p tao-edge -p tao-api -p tao-console -- -D warnings && cargo test --locked -p tao-platform)
```

CI runs exactly this (`.github/workflows/ci.yml`, job `platform`); the audit workflow checks `Cargo.lock` with
cargo-deny against `deny.toml` each week.

## Building

`build.sh` builds a Worker with workers-rs's `worker-build`, and gives it every tool it would otherwise download at
build time, unpinned: `worker-build` and `wasm-bindgen` installed from crates.io with `--locked`, the esbuild of the
Worker's wrangler lockfile, no wasm-opt.

```bash
rust/platform/build.sh --install
```

```bash
(cd cloud/api && npm ci --ignore-scripts --no-audit --no-fund) && rust/platform/build.sh api
```

The Worker is then `api/build/worker/shim.mjs`, which `cloud/api/wrangler.toml` names; `cloud/api/test/run.sh` runs it
in local workerd, and the platform workflow deploys it.  Likewise `console`.
