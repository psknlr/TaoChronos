#!/usr/bin/env bash
# Binds the archive's private R2 bucket (security/archive.js; docs/adr/0023-workers-paid.md) into a Worker's deploy
# configuration as ARCHIVE — only when the owner named one (the repository variable ARCHIVE_BUCKET), it exists, and
# nothing makes it public (no r2.dev address, no custom domain).  Otherwise the Worker is deployed without it, and the
# repository's collector takes the records and events as before.  Never fails the deployment.  Run by
# .github/workflows/relay.yml and cloud/site/deploy.sh.
#
#   bash security/bind-archive.sh <the wrangler configuration to append to>
#
# Environment: CLOUDFLARE_API_TOKEN (with Account → Workers R2 Storage → Edit), CLOUDFLARE_ACCOUNT_ID, ARCHIVE_BUCKET
# (empty: no archive), UA (the agent the checks name themselves by).
set -uo pipefail
config="$1"
bucket="${ARCHIVE_BUCKET:-}"
if [ -z "$bucket" ]; then
  echo "the archive: none (the repository variable ARCHIVE_BUCKET is not set): records and events go to the repository"
  exit 0
fi
if ! [[ "$bucket" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]]; then
  echo "::error::ARCHIVE_BUCKET is not an R2 bucket name ($bucket): deployed without the archive"
  exit 0
fi
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/r2/buckets/$bucket"
get() { curl -A "${UA:-taochronos-deploy/1}" -fsS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$api$1"; }
if ! get "" > /dev/null 2>&1; then
  echo "::warning::the archive's bucket $bucket was not found, or the API token may not read R2 (Account → Workers R2 Storage → Edit): deployed without it; records and events go to the repository (relay/SETUP.md, 归档)"
  exit 0
fi
# public access, either way R2 offers it: the r2.dev address and custom domains.  Not known is as good as on
managed=$(get "/domains/managed" 2>/dev/null | python3 -c 'import json,sys; print("on" if json.load(sys.stdin)["result"].get("enabled") else "off")' 2>/dev/null || echo "unknown")
custom=$(get "/domains/custom" 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["result"].get("domains") or []))' 2>/dev/null || echo "unknown")
if [ "$managed" != "off" ] || [ "$custom" != "0" ]; then
  echo "::error::the archive's bucket $bucket may be public (r2.dev address: $managed; custom domains: $custom): deployed without it — conversation records are never put where the web can read them. Turn off its r2.dev address and remove its custom domains (R2 → $bucket → Settings), then deploy again"
  exit 0
fi
printf '\n[[r2_buckets]]\nbinding = "ARCHIVE"\nbucket_name = "%s"\n' "$bucket" >> "$config"
echo "the archive: R2 bucket $bucket (private): records and events are drained there, not committed to the repository"
