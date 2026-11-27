#!/usr/bin/env bash
# Builds TaoCore's browser module and writes it where the site's build takes it from
# (rust/crates/taocore-wasm/taocore.wasm, committed: deployments need no Rust).
#   rust/wasm.sh           build, and write the module
#   rust/wasm.sh --check   build, and fail unless the committed module is byte for byte what the source builds (CI)
# The same bytes need the same compiler (rust-toolchain.toml pins it, to the patch release) and no build-machine path in
# the binary: the module's crates are the workspace's own, whose paths cargo passes relative to it, and the standard
# library's are /rustc/<commit>/ — the same on every machine.  A dependency from crates.io would bring its absolute
# path under CARGO_HOME; the check fails if one ever does.
set -euo pipefail
cd "$(dirname "$0")"
case "${1:-}" in
  "") check=0 ;;
  --check) check=1 ;;
  *) echo "usage: rust/wasm.sh [--check]" >&2; exit 2 ;;
esac
# into rust/target whatever CARGO_TARGET_DIR or a cargo config says: the module compared is the one just built
cargo build --quiet --locked --profile wasm --target wasm32-unknown-unknown --target-dir target -p taocore-wasm
built=target/wasm32-unknown-unknown/wasm/taocore_wasm.wasm
kept=crates/taocore-wasm/taocore.wasm
if [ "$check" = 1 ]; then
  if ! cmp -s "$built" "$kept"; then
    echo "$kept is not what the source builds: run rust/wasm.sh and commit it" >&2
    sha256sum "$built" "$kept" >&2 || true
    exit 1
  fi
  echo "$kept is what the source builds ($(wc -c < "$kept") bytes)"
else
  cp "$built" "$kept"
  sha256sum "$kept"
fi
