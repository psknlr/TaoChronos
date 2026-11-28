#!/usr/bin/env bash
# Deploys the private model gateway (taochronos-models: no route), built by rust/platform/build.sh models, then gives
# it the providers' keys — before the API, whose service binding MODEL_GATEWAY names it.  Run by
# .github/workflows/platform.yml.  Without a key it is deployed all the same, and answers that the model is unavailable:
# the API then counts nothing (docs/adr/0039-model-relay-and-daily-allowance.md).
# Environment: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID; GATEWAY_MINIMAX_API_KEY, or else MINIMAX_API_KEY (the
# website relay's); optional OPENAI_API_KEY; optional GATEWAY_MINIMAX_BASE (an https address: MiniMax's international
# platform is https://api.minimax.io/v1).
set -euo pipefail
cd "$(dirname "$0")"
[ -f ../../rust/platform/models/build/worker/shim.mjs ] || { echo "not built: rust/platform/build.sh models" >&2; exit 1; }
cp wrangler.toml wrangler.deploy.toml
base="$(printf '%s' "${GATEWAY_MINIMAX_BASE:-}" | tr -d '[:space:]')"
if [ -n "$base" ]; then
  if [[ "$base" =~ ^https://[A-Za-z0-9.-]+(/[A-Za-z0-9._/-]*)?$ ]]; then
    sed -i "s#^MINIMAX_BASE = \".*\"\$#MINIMAX_BASE = \"${base%/}\"#" wrangler.deploy.toml
    echo "MiniMax: ${base%/}"
  else
    echo "::warning::GATEWAY_MINIMAX_BASE is not an https address: the default is kept"
  fi
fi
npx --no -- wrangler deploy --config wrangler.deploy.toml
key="$(printf '%s' "${GATEWAY_MINIMAX_API_KEY:-${MINIMAX_API_KEY:-}}" | tr -d '[:space:]')"
if [ -n "$key" ]; then
  printf '%s' "$key" | npx --no -- wrangler secret put MINIMAX_API_KEY --config wrangler.deploy.toml
  echo "Tao-R1: keyed"
else
  echo "::warning::no MiniMax key (GATEWAY_MINIMAX_API_KEY or MINIMAX_API_KEY): Tao-R1 answers that it is unavailable, and nothing is counted"
fi
openai="$(printf '%s' "${OPENAI_API_KEY:-}" | tr -d '[:space:]')"
if [ -n "$openai" ]; then
  printf '%s' "$openai" | npx --no -- wrangler secret put OPENAI_API_KEY --config wrangler.deploy.toml
fi
