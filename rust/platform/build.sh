#!/usr/bin/env bash
# Builds one of the platform's Workers (rust/platform/api or rust/platform/console) into <crate>/build/worker/, where
# cloud/<worker>/wrangler.toml's `main` reads it — with worker-build (workers-rs's), and every tool worker-build would
# otherwise download at build time, unpinned and unchecked, replaced by one pinned here
# (docs/adr/0026-pinned-supply-chain-and-enforced-policies.md; docs/adr/0038-accounts-keys-and-credits.md):
#
#   worker-build   WORKER_BUILD below, installed with `cargo install --locked` (crates.io: checksummed by its index)
#   wasm-bindgen   WASM_BINDGEN below, likewise — and the version Cargo.lock pins of the wasm-bindgen crate: the two
#                  must be one, or the module and its glue disagree
#   esbuild        the one wrangler's lockfile pins, sha512 and all (cloud/<worker>: npm ci --ignore-scripts) — the
#                  version worker-build itself names
#   wasm-opt       none: off in each crate's [package.metadata.wasm-pack.profile.release]
#
#   rust/platform/build.sh --install   install the pinned worker-build and wasm-bindgen (into ~/.cargo/bin)
#   rust/platform/build.sh api         → rust/platform/api/build/worker/shim.mjs
#   rust/platform/build.sh console     → rust/platform/console/build/worker/shim.mjs
set -euo pipefail
cd "$(dirname "$0")"
WORKER_BUILD=0.9.0
WASM_BINDGEN=0.2.130

locked=$(awk '$0 == "name = \"wasm-bindgen\"" { getline; gsub(/[^0-9.]/, "", $0); print; exit }' Cargo.lock)
if [ "$locked" != "$WASM_BINDGEN" ]; then
  echo "Cargo.lock pins wasm-bindgen $locked and this script $WASM_BINDGEN: bump them together" >&2
  exit 1
fi

if [ "${1:-}" = "--install" ]; then
  cargo install worker-build --version "$WORKER_BUILD" --locked
  cargo install wasm-bindgen-cli --version "$WASM_BINDGEN" --locked
  exit 0
fi

crate="${1:-}"
case "$crate" in
  api | console) ;;
  *) echo "usage: rust/platform/build.sh --install | api | console" >&2; exit 2 ;;
esac

version() { "$1" --version 2>/dev/null | awk '{ print $NF }'; }
if [ "$(version worker-build)" != "$WORKER_BUILD" ] || [ "$(version wasm-bindgen)" != "$WASM_BINDGEN" ]; then
  echo "worker-build $WORKER_BUILD and wasm-bindgen $WASM_BINDGEN are needed (found: $(version worker-build || true), $(version wasm-bindgen || true)):" >&2
  echo "  rust/platform/build.sh --install" >&2
  exit 1
fi
esbuild="$(cd "../../cloud/$crate" && pwd)/node_modules/.bin/esbuild"
if [ ! -x "$esbuild" ]; then
  echo "no esbuild from cloud/$crate's lockfile: (cd cloud/$crate && npm ci --ignore-scripts --no-audit --no-fund)" >&2
  exit 1
fi
# Cargo.lock as it is: worker-build runs cargo without --locked, so the lock is checked first (it fails here if
# anything would change it), and the build after it reads the same lock
cargo metadata --locked --format-version 1 > /dev/null
# worker-build takes these instead of downloading its own (and says so in its output)
export WASM_BINDGEN_BIN="$(command -v wasm-bindgen)"
export ESBUILD_BIN="$esbuild"
cd "$crate"
worker-build --release
ls -l build/worker/
