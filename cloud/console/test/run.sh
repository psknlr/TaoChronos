#!/usr/bin/env bash
# The console end to end, as built, in a real browser: both Rust Workers (rust/platform/build.sh api and console) in
# local workerd beside a stand-in corpus (cloud/api/test/corpus.js) — the console registers a person, provisions their
# organisation with a trial in the API Worker's Account object, makes a live key (browser.cjs, Chromium through
# Playwright); then the API Worker, on the same state, is asked a search with that key, which must be counted against
# the registered person's daily allowance.  A developer's check: it needs Playwright with Chromium (`require("playwright")`), which this repository
# does not pin.  Local only — no mail leaves: wrangler dev's Email Service writes each mail to a file.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
console="$(cd "$here/.." && pwd)"
api="$(cd "$console/../api" && pwd)"
work="$(mktemp -d)"
# each wrangler dev is started in a process group of its own (setsid) and the whole group is stopped: npx, wrangler and
# the workerd beneath them — killing npx alone leaves a server behind, still answering on the port
stop() { if [ -n "${dev:-}" ]; then kill -TERM -- "-$dev" 2>/dev/null || true; wait "$dev" 2>/dev/null || true; dev=; fi; }
trap 'stop; rm -rf "$work"' EXIT
mkdir -p "$work/console"
python3 - "$console/wrangler.toml" "$console" > "$work/console/wrangler.toml" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
s = s.replace('main = "../../rust/platform/console/build/worker/shim.mjs"', f'main = "{sys.argv[2]}/../../rust/platform/console/build/worker/shim.mjs"')
s = re.sub(r'\[\[routes\]\]\npattern = "console\.impf\.ai"\ncustom_domain = true\n', "", s)
for a, b in [('REGISTRATION = "off"', 'REGISTRATION = "open"'), ('RP_ID = "impf.ai"', 'RP_ID = "localhost"'),
             ('CONSOLE_ORIGIN = "https://console.impf.ai"', 'CONSOLE_ORIGIN = "http://localhost:8788"'), ('TRIAL_CREDITS = "0"', 'TRIAL_CREDITS = "40"')]:
    assert a in s, a
    s = s.replace(a, b)
print(s)
PY
printf 'ACCOUNT_SECRET="local-%s"\n' "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')" > "$work/console/.dev.vars"
python3 - "$api/wrangler.toml" "$api" > "$work/api.toml" <<'PY'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
s = s.replace('main = "../../rust/platform/api/build/worker/shim.mjs"', f'main = "{sys.argv[2]}/../../rust/platform/api/build/worker/shim.mjs"')
s = re.sub(r'\[\[routes\]\]\npattern = "api\.impf\.ai"\ncustom_domain = true\n', "", s)
print(s + '\n[[services]]\nbinding = "CORPUS"\nservice = "taochronos-corpus"\n')
PY
cp "$api/test/corpus.js" "$api/test/corpus.toml" "$work/"
wait_for() { for _ in $(seq 1 90); do curl -fs -o /dev/null "$1" 2>/dev/null && return 0; sleep 1; done; return 1; }
# a server already on a port would be tested in this one's place
for port in 8787 8788; do
  if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$port/" 2>/dev/null; then echo "port $port is in use" >&2; exit 1; fi
done
(cd "$console" && exec setsid npx --no -- wrangler dev -c "$work/console/wrangler.toml" -c "$work/api.toml" -c "$work/corpus.toml" --port 8788 --ip 127.0.0.1 \
  --persist-to "$work/state" > "$work/console.log" 2>&1) &
dev=$!
wait_for http://127.0.0.1:8788/auth/config
CONSOLE=http://localhost:8788/ node "$here/browser.cjs" "$work/console.log" "$work/key.txt" || { tail -30 "$work/console.log" >&2; exit 1; }
stop
(cd "$api" && exec setsid npx --no -- wrangler dev -c "$work/api.toml" -c "$work/corpus.toml" --port 8787 --ip 127.0.0.1 --persist-to "$work/state" > "$work/api.log" 2>&1) &
dev=$!
wait_for http://127.0.0.1:8787/v1
out=$(curl -fsS -X POST http://127.0.0.1:8787/v1/evidence/search -H "Authorization: Bearer $(cat "$work/key.txt")" -H "Content-Type: application/json" -d '{"query":"桂枝汤"}')
limits=$(curl -fsS http://127.0.0.1:8787/v1/limits -H "Authorization: Bearer $(cat "$work/key.txt")")
python3 - "$out" "$limits" <<'PY'
import json, sys
d, l = json.loads(sys.argv[1]), json.loads(sys.argv[2])["data"]
assert d["usage"]["credits"] == 0, d                       # the daily allowance spends no credit
assert l["credits"]["available"] == 40, l["credits"]       # the trial is untouched
q = l["user_quota"]
assert (q["used"], q["remaining"]) == (1, 4), q            # one of the registered person's five
PY
echo "ok   the console's key is the API's: a search counted against its owner's daily allowance (4 of 5 left), no credit spent"
