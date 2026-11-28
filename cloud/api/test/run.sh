#!/usr/bin/env bash
# The developer API end to end, as built: the Rust Workers (rust/platform/build.sh api and models) in local workerd —
# wrangler dev from cloud/api's lockfile — the API beside the private model gateway (cloud/models), a stand-in corpus
# (corpus.js) and a stand-in model provider (provider.mjs, which the gateway is pointed at), with an owner's token made
# for this run alone; then scenario.py against it.  CI's platform workflow runs it before it deploys anything
# (.github/workflows/platform.yml).
#   cloud/api/test/run.sh        (after rust/platform/build.sh api && rust/platform/build.sh models, and npm ci
#                                 --ignore-scripts in cloud/api)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
api="$(cd "$here/.." && pwd)"
models="$(cd "$here/../../models" && pwd)"
work="$(mktemp -d)"
port="${PORT:-8787}"
provider_port="${PROVIDER_PORT:-8795}"
# each server is started in a process group of its own (setsid) and the whole group is stopped: npx, wrangler and the
# workerd beneath them — killing npx alone leaves a server behind, still answering on the port
stop() {
  for p in "${dev:-}" "${provider:-}"; do
    if [ -n "$p" ]; then kill -TERM -- "-$p" 2>/dev/null || true; wait "$p" 2>/dev/null || true; fi
  done
  dev=; provider=
}
trap 'stop; rm -rf "$work"' EXIT
token="local-run-$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
sha=$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)
# the Workers' own configurations, but local: no custom domain, the owner's endpoints on, the corpus and the gateway
# bound (the gateway to the stand-in provider, with its key), short time limits (the scenario waits each out once)
python3 - "$api/wrangler.toml" "$sha" "$api" > "$work/wrangler.toml" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
s = s.replace('main = "../../rust/platform/api/build/worker/shim.mjs"', f'main = "{sys.argv[3]}/../../rust/platform/api/build/worker/shim.mjs"')
s = re.sub(r'\[\[routes\]\]\npattern = "api\.impf\.ai"\ncustom_domain = true\n', "", s)
for a, b in [('ADMIN_TOKEN_SHA256 = ""', f'ADMIN_TOKEN_SHA256 = "{sys.argv[2]}"'), ('CORPUS_TIMEOUT_SECONDS = "60"', 'CORPUS_TIMEOUT_SECONDS = "5"'),
             ('MODEL_FIRST_EVENT_TIMEOUT_SECONDS = "30"', 'MODEL_FIRST_EVENT_TIMEOUT_SECONDS = "5"'),
             ('MODEL_IDLE_TIMEOUT_SECONDS = "30"', 'MODEL_IDLE_TIMEOUT_SECONDS = "5"'), ('MODEL_TOTAL_TIMEOUT_SECONDS = "180"', 'MODEL_TOTAL_TIMEOUT_SECONDS = "20"')]:
    assert a in s, a
    s = s.replace(a, b)
s += '\n[[services]]\nbinding = "CORPUS"\nservice = "taochronos-corpus"\n'
s += '\n[[services]]\nbinding = "MODEL_GATEWAY"\nservice = "taochronos-models"\n'
print(s)
PY
mkdir -p "$work/models"
python3 - "$models/wrangler.toml" "$models" "$provider_port" > "$work/models/wrangler.toml" <<'PY'
import sys
s = open(sys.argv[1], encoding="utf-8").read()
s = s.replace('main = "../../rust/platform/models/build/worker/shim.mjs"', f'main = "{sys.argv[2]}/../../rust/platform/models/build/worker/shim.mjs"')
assert 'MINIMAX_BASE = "https://api.minimax.cn/v1"' in s
print(s.replace('MINIMAX_BASE = "https://api.minimax.cn/v1"', f'MINIMAX_BASE = "http://127.0.0.1:{sys.argv[3]}/v1"'))
PY
printf 'MINIMAX_API_KEY="test-provider-key"\n' > "$work/models/.dev.vars"
cp "$here/corpus.js" "$work/corpus.js"
cp "$here/corpus.toml" "$work/corpus.toml"
# a server already on a port would be tested in this one's place
for p in "$port" "$provider_port"; do
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$p/" 2>/dev/null; then echo "port $p is in use" >&2; exit 1; fi
done
(exec setsid node "$here/provider.mjs" "$provider_port" > "$work/provider.log" 2>&1) &
provider=$!
(cd "$api" && exec setsid npx --no -- wrangler dev -c "$work/wrangler.toml" -c "$work/models/wrangler.toml" -c "$work/corpus.toml" \
  --port "$port" --ip 127.0.0.1 --persist-to "$work/state" > "$work/dev.log" 2>&1) &
dev=$!
for _ in $(seq 1 90); do
  if curl -fs -o /dev/null "http://127.0.0.1:$port/v1" 2>/dev/null; then break; fi
  sleep 1
done
ADMIN_TOKEN="$token" PROVIDER="http://127.0.0.1:$provider_port" python3 "$here/scenario.py" "http://127.0.0.1:$port" \
  || { tail -60 "$work/dev.log" >&2; exit 1; }
# the slow call the API gave up was ended at the corpus as well
if grep -q "stand-in corpus: a slow call was aborted" "$work/dev.log"; then
  echo "ok   a call past the time limit is aborted at the corpus too"
else
  echo "FAIL a call past the time limit was not aborted at the corpus" >&2; tail -40 "$work/dev.log" >&2; exit 1
fi
