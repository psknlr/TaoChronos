#!/usr/bin/env bash
# Deploys the site's Worker (taochronos-site, https://chat.impf.ai) with the bindings the account has, then checks the
# site.  Run by .github/workflows/site.yml from the repository's root, once the site is built into _site.
#
# Environment: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID; WRANGLER (the wrangler to run, e.g. wrangler@4.142.0);
# STORE_NAMESPACE (the Workers KV namespace the full corpus store is uploaded into); SITE_URL; STORE_TOKEN_SHA256
# (optional: the sha256 of a store upload token, in place of wrangler.toml's); CORPUS_DEPLOYED=1 when the corpus's
# container has just been deployed (otherwise the KV namespace says whether it is).
set -euo pipefail
cd "$(dirname "$0")"
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID"
auth="Authorization: Bearer $CLOUDFLARE_API_TOKEN"
host="${SITE_URL#https://}"
work=$(mktemp -d)

# ---------------------------------------------------------------- the bindings the account has
cp wrangler.toml wrangler.deploy.toml
if [ -n "${STORE_TOKEN_SHA256:-}" ]; then
  if ! [[ "$STORE_TOKEN_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    echo "::error::the repository variable STORE_TOKEN_SHA256 must be a sha256 in lowercase hex (64 characters)"; exit 1
  fi
  sed -i "s/^STORE_TOKEN_SHA256 = .*/STORE_TOKEN_SHA256 = \"$STORE_TOKEN_SHA256\"/" wrangler.deploy.toml
  echo "store uploads: with the token the repository variable STORE_TOKEN_SHA256 names"
fi
find='import json,sys,os; r=json.load(sys.stdin)["result"]; print(next((n["id"] for n in r if n["title"]==os.environ["STORE_NAMESPACE"]), ""))'
ns=$(curl -fsS -H "$auth" "$api/storage/kv/namespaces?per_page=100" | python3 -c "$find" || true)
if [ -z "$ns" ]; then
  ns=$(curl -fsS -X POST -H "$auth" -H "Content-Type: application/json" -d "{\"title\": \"$STORE_NAMESPACE\"}" \
         "$api/storage/kv/namespaces" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["id"])' || true)
fi
if [ -n "$ns" ]; then
  printf '\n[[kv_namespaces]]\nbinding = "STORE"\nid = "%s"\n' "$ns" >> wrangler.deploy.toml
  echo "the store's KV namespace: $STORE_NAMESPACE"
else
  echo "::warning::no KV namespace (the token may not use Workers KV): the site takes no store uploads (cloud/SETUP.md)"
fi
# the corpus Worker, once its container is deployed (the workflow says so in the KV namespace; the Worker alone, uploaded
# before a container that failed, would answer nothing)
deployed="${CORPUS_DEPLOYED:-}"
if [ -z "$deployed" ] && [ -n "$ns" ]; then
  deployed=$(curl -fsS -H "$auth" "$api/storage/kv/namespaces/$ns/values/deployed%2Fcorpus" 2>/dev/null || true)
fi
if [ -n "$deployed" ] && curl -fsS -o /dev/null -H "$auth" "$api/workers/scripts/taochronos-corpus/settings" 2>/dev/null; then
  printf '\n[[services]]\nbinding = "CORPUS"\nservice = "taochronos-corpus"\n' >> wrangler.deploy.toml
  echo "the corpus Worker: taochronos-corpus"
else
  echo "::warning::the full corpus's container is not deployed: the site's API answers 503 and the page runs the 要籍语料 in the browser"
fi

# ---------------------------------------------------------------- deploy
set +e
npx --yes "$WRANGLER" deploy --config wrangler.deploy.toml 2>&1 | tee "$work/deploy.log"
status=${PIPESTATUS[0]}
set -e
if [ "$status" != 0 ]; then
  if grep -q "externally managed DNS records" "$work/deploy.log"; then
    echo "::error::$host 还有一条自建的 DNS 记录（原先指向 GitHub Pages 的 CNAME），Cloudflare 不能在它上面建 Worker 的自定义域名。请到 Cloudflare → ${host#*.} → DNS → Records 删除名称为 ${host%%.*} 的 CNAME 记录，然后立即重新运行本工作流（Actions → site → Run workflow；见 cloud/SETUP.md 第 3 步）。网站 Worker 已上传，只差这个域名。"
  fi
  exit "$status"
fi

# ---------------------------------------------------------------- check the site over HTTPS
# the first time, the DNS record and the certificate take a few minutes (until then the name may still lead elsewhere)
for i in $(seq 1 40); do
  if curl -fsS --max-time 30 -D "$work/headers.txt" -o "$work/page.html" "$SITE_URL/" && grep -qi '^server: cloudflare' "$work/headers.txt"; then
    break
  fi
  echo "waiting for $SITE_URL on Cloudflare ($i)"; sleep 15
done
if ! grep -qi '^server: cloudflare' "$work/headers.txt" 2>/dev/null; then
  echo "::error::$SITE_URL is not served by Cloudflare after 10 minutes: see the DNS record of $host (cloud/SETUP.md)"; exit 1
fi
grep -qi '^strict-transport-security' "$work/headers.txt"
grep -q "道乃久" "$work/page.html"
test "$(curl -s --max-time 30 -o /dev/null -w '%{http_code}' "http://$host/")" = "301"
curl -fsS --max-time 30 -o /dev/null "$SITE_URL/runtime/boot.json"
echo "$SITE_URL: HTTPS from Cloudflare, http redirected, the page and the browser runtime served"

# ---------------------------------------------------------------- what its API says (this also wakes the full corpus)
# the container starts on the first call: the first after a new image takes minutes
for i in $(seq 1 8); do
  code=$(curl -s -o "$work/info.json" -w '%{http_code}' --max-time 240 "$SITE_URL/api/info" || true)
  if [ "$code" = "200" ]; then break; fi
  if [ "$code" = "503" ] && grep -q '"corpus": *"none"' "$work/info.json"; then break; fi
  echo "the full corpus answers $code ($i)"; sleep 30
done
if grep -q '"corpus": *"none"' "$work/info.json"; then
  echo "::warning::the site runs without the full corpus: the page uses the 要籍语料 in the browser"
  exit 0
fi
python3 - "$work/info.json" <<'EOF'
import json, sys
info = json.load(open(sys.argv[1]))
assert "name" in info, f"the full corpus does not answer: {info}"
c = info["corpus"]
assert c["kind"] == "full", c
print(f"the full corpus: {c['books']} books, {c['passages']:,} passages, {info['tools']['offered']} tools")
EOF
curl -fsS --max-time 300 -X POST -H "Content-Type: application/json" -H "Origin: $SITE_URL" \
  -d '{"name": "classics.search", "arguments": {"query": "桂枝汤", "k": 3}}' "$SITE_URL/api/call" -o "$work/call.json"
python3 - "$work/call.json" <<'EOF'
import json, sys
out = json.load(open(sys.argv[1]))
assert out["ok"] and out["citations"], out
print("a search on the full corpus:", out["summary"], [c["passage_id"] for c in out["citations"]][:3])
EOF
