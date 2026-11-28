#!/usr/bin/env bash
# Deploys the developer API (taochronos-api: api.impf.ai), built by rust/platform/build.sh api, with what the account
# has: the full corpus's Worker (CORPUS) when it is deployed — as cloud/site/deploy.sh binds it —, the private model
# gateway (MODEL_GATEWAY: cloud/models, deployed first), and the owner's token
# by its digest (the token itself is kept nowhere here).  Run by .github/workflows/platform.yml.
# Environment: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID; API_ADMIN_TOKEN_SHA256 (64 hex: the sha256 of the owner's token).
set -euo pipefail
cd "$(dirname "$0")"
UA="taochronos-deploy/1"
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID"
auth="Authorization: Bearer $CLOUDFLARE_API_TOKEN"
[ -f ../../rust/platform/api/build/worker/shim.mjs ] || { echo "not built: rust/platform/build.sh api" >&2; exit 1; }
cp wrangler.toml wrangler.deploy.toml
if curl -A "$UA" -fsS -o /dev/null -H "$auth" "$api/workers/scripts/taochronos-corpus/settings" 2>/dev/null; then
  printf '\n[[services]]\nbinding = "CORPUS"\nservice = "taochronos-corpus"\n' >> wrangler.deploy.toml
  echo "the corpus Worker: taochronos-corpus"
else
  echo "::warning::the full corpus's Worker is not deployed: every search and verification is answered 503 and nothing is counted"
fi
# the private model gateway (cloud/models), deployed before this Worker by the same workflow
if curl -A "$UA" -fsS -o /dev/null -H "$auth" "$api/workers/scripts/taochronos-models/settings" 2>/dev/null; then
  printf '\n[[services]]\nbinding = "MODEL_GATEWAY"\nservice = "taochronos-models"\n' >> wrangler.deploy.toml
  echo "the model gateway: taochronos-models"
else
  echo "::warning::the model gateway is not deployed: every chat is answered 503 and nothing is counted"
fi
sha=$(printf '%s' "${API_ADMIN_TOKEN_SHA256:-}" | tr -d '[:space:]' | tr 'A-F' 'a-f')
if [[ "$sha" =~ ^[0-9a-f]{64}$ ]]; then
  sed -i "s/^ADMIN_TOKEN_SHA256 = \"\"$/ADMIN_TOKEN_SHA256 = \"$sha\"/" wrangler.deploy.toml
  echo "the owner's endpoints: on"
else
  echo "::warning::API_ADMIN_TOKEN_SHA256 is not 64 hex characters: the owner's endpoints stay off"
fi
npx --no -- wrangler deploy --config wrangler.deploy.toml
