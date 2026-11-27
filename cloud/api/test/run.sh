#!/usr/bin/env bash
# The developer API end to end, as built: the Rust Worker (rust/platform/build.sh api) in local workerd — wrangler dev
# from cloud/api's lockfile — beside a stand-in corpus (corpus.js), with an owner's token made for this run alone;
# then scenario.py against it.  CI's platform workflow runs it before it deploys anything (.github/workflows/platform.yml).
#   cloud/api/test/run.sh        (after rust/platform/build.sh api, and npm ci --ignore-scripts in cloud/api)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
api="$(cd "$here/.." && pwd)"
work="$(mktemp -d)"
trap 'kill "$dev" 2>/dev/null || true; rm -rf "$work"' EXIT
token="local-run-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
sha=$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)
# the Worker's own configuration, but local: no custom domain, the owner's endpoints on, the corpus bound (the stand-in),
# a short time limit for the corpus (the scenario waits it out once)
python3 - "$api/wrangler.toml" "$sha" "$api" > "$work/wrangler.toml" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
s = s.replace('main = "../../rust/platform/api/build/worker/shim.mjs"', f'main = "{sys.argv[3]}/../../rust/platform/api/build/worker/shim.mjs"')
s = re.sub(r'\[\[routes\]\]\npattern = "api\.impf\.ai"\ncustom_domain = true\n', "", s)
s = s.replace('ADMIN_TOKEN_SHA256 = ""', f'ADMIN_TOKEN_SHA256 = "{sys.argv[2]}"').replace('CORPUS_TIMEOUT_SECONDS = "60"', 'CORPUS_TIMEOUT_SECONDS = "5"')
s += '\n[[services]]\nbinding = "CORPUS"\nservice = "taochronos-corpus"\n'
print(s)
PY
cp "$here/corpus.js" "$work/corpus.js"
cp "$here/corpus.toml" "$work/corpus.toml"
port="${PORT:-8787}"
(cd "$api" && exec npx --no -- wrangler dev -c "$work/wrangler.toml" -c "$work/corpus.toml" --port "$port" --ip 127.0.0.1 --persist-to "$work/state" > "$work/dev.log" 2>&1) &
dev=$!
for _ in $(seq 1 90); do
  if curl -fs -o /dev/null "http://127.0.0.1:$port/v1" 2>/dev/null; then break; fi
  sleep 1
done
ADMIN_TOKEN="$token" python3 "$here/scenario.py" "http://127.0.0.1:$port" || { tail -40 "$work/dev.log" >&2; exit 1; }
