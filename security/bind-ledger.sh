#!/usr/bin/env bash
# Binds the activity ledger's registry (security/ledger-d1.js) — the D1 database ACTIVITY_DB_NAME, taochronos-activity
# unless named otherwise — into a Worker's deploy configuration as ACTIVITY_DB, once the owner has switched the ledger
# on: the repository secret ACTIVITY_KEY is set (32 characters or more).  The database is made when it is not there;
# both Workers bind the same one.  Without the secret, or when the token may not use D1, the Worker is deployed without
# the binding: it keeps no ledger, gives no visitor an id, and is what it was.  Never fails the deployment.  Run by
# .github/workflows/relay.yml and cloud/site/deploy.sh, which give the Worker the key once it is deployed with the
# binding (a key without the registry does nothing).
#
#   bash security/bind-ledger.sh <the wrangler configuration to append to>
#
# Environment: CLOUDFLARE_API_TOKEN (with Account → D1 → Edit), CLOUDFLARE_ACCOUNT_ID, ACTIVITY_KEY (empty: no ledger),
# ACTIVITY_DB_NAME (optional), UA (the agent the checks name themselves by).
set -uo pipefail
config="$1"
key="$(printf '%s' "${ACTIVITY_KEY:-}" | tr -d '[:space:]')"
name="${ACTIVITY_DB_NAME:-taochronos-activity}"
if [ -z "$key" ]; then
  echo "the activity ledger: none (the repository secret ACTIVITY_KEY is not set): no visitor is given an id, nothing is written down"
  exit 0
fi
if [ "${#key}" -lt 32 ]; then
  echo "::warning::ACTIVITY_KEY is shorter than 32 characters: deployed without the activity ledger (security/README.md, 活动账本)"
  exit 0
fi
if ! [[ "$name" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]]; then
  echo "::error::ACTIVITY_DB_NAME is not a D1 database name ($name): deployed without the activity ledger"
  exit 0
fi
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/d1/database"
call() { curl -A "${UA:-taochronos-deploy/1}" -fsS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$@"; }
# the database's id, by its exact name (the API's search is by part of a name)
find() { call "$api?name=$name&per_page=100" 2>/dev/null | NAME="$name" python3 -c 'import json,sys,os; print(next((d["uuid"] for d in json.load(sys.stdin)["result"] if d["name"]==os.environ["NAME"]), ""))' 2>/dev/null; }
if ! call "$api?per_page=1" > /dev/null 2>&1; then
  echo "::warning::the API token may not use D1 (Account → D1 → Edit): deployed without the activity ledger (security/README.md, 活动账本)"
  exit 0
fi
uuid=$(find || true)
if [ -z "$uuid" ]; then
  call -X POST -H "Content-Type: application/json" -d "{\"name\": \"$name\"}" "$api" > /dev/null 2>&1 && echo "the activity ledger: made the D1 database $name"
  uuid=$(find || true)  # (made here, or by the other Worker's deployment a moment ago)
fi
if ! [[ "$uuid" =~ ^[0-9a-f-]{36}$ ]]; then
  echo "::warning::the D1 database $name could not be found or made: deployed without the activity ledger"
  exit 0
fi
printf '\n[[d1_databases]]\nbinding = "ACTIVITY_DB"\ndatabase_name = "%s"\ndatabase_id = "%s"\n' "$name" "$uuid" >> "$config"
echo "the activity ledger: its registry is the D1 database $name; the Worker is given its key once deployed"
