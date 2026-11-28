"""The developer API end to end (cloud/api/test/run.sh): the Rust Worker as built, in local workerd, beside a stand-in
corpus (corpus.js) — an organisation, credits, a key; calls charged, refused, replayed, not charged; usage, limits,
revocation, forged keys, the owner's token.  Standard library only.  Usage: scenario.py BASE_URL (ADMIN_TOKEN in the
environment)."""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import zlib

BASE = sys.argv[1].rstrip("/")
TOKEN = os.environ["ADMIN_TOKEN"]

def ask(method, path, body=None, key=None, headers=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if key: h["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(BASE + path, method=method, headers=h, data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null"), dict(e.headers)

def check(what, cond, detail=""):
    print(("ok  " if cond else "FAIL"), what, "" if cond else detail)
    if not cond: check.failed += 1
check.failed = 0

# the owner makes an organisation, grants credits, makes a key
s, org, _ = ask("POST", "/admin/orgs", {"name": "Pilot lab"}, key=TOKEN)
check("owner makes an organisation", s == 200 and org["org"]["id"].startswith("org_"), (s, org))
oid = org["org"]["id"]
s, g, _ = ask("POST", f"/admin/orgs/{oid}/grants", {"credits": 25, "reference": "trial", "note": "pilot"}, key=TOKEN)
check("a grant of 25", s == 200 and g["added"] and g["credits"]["available"] == 25, g)
s, g2, _ = ask("POST", f"/admin/orgs/{oid}/grants", {"credits": 25, "reference": "trial"}, key=TOKEN)
check("the same grant again adds nothing", s == 200 and not g2["added"] and g2["credits"]["available"] == 25, g2)
s, k, _ = ask("POST", f"/admin/orgs/{oid}/keys", {"environment": "live", "name": "server"}, key=TOKEN)
check("a live key, shown once", s == 200 and k["key"].startswith("tao_live_") and len(k["key"]) == 82, k)
key = k["key"]
s, summary, _ = ask("GET", f"/admin/orgs/{oid}", key=TOKEN)
check("the summary lists the key without it", key not in json.dumps(summary) and summary["keys"][0]["shown"] == k["shown"], summary)

# paid calls
s, r, h = ask("POST", "/v1/evidence/search", {"query": "桂枝汤", "k": 5}, key=key)
check("a search answers, charged 10", s == 200 and r["usage"]["credits"] == 10 and r["data"]["citations"][0]["passage_id"] == "shl:12", (s, r))
check("its request id is its header", h.get("X-Request-Id") == r["id"] and r["id"].startswith("req_"), h)
check("no receipt is passed on", "receipt" not in json.dumps(r) and "agent:chat" not in json.dumps(r), r)
check("the tool was asked what the API read", r["data"]["result"]["asked"] == {"query": "桂枝汤", "k": 5}, r["data"]["result"])
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "麻黄汤"}, key=key)
check("a second search: 20 spent", s == 200, (s, r))
s, r, h = ask("POST", "/v1/evidence/search", {"query": "葛根汤"}, key=key)
check("a third: 402, 5 left is not 10", s == 402 and r["error"]["type"] == "insufficient_credits" and r["error"]["code"] == "credits", (s, r))
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "太阳之为病，脉浮，头项强痛而恶寒。"}, key=key)
check("a verification costs 2", s == 200 and r["usage"]["credits"] == 2, (s, r))

# a repeat with the same Idempotency-Key: the first answer, no second charge
s1, r1, _ = ask("POST", "/v1/citations/verify", {"quote": "脉浮"}, key=key, headers={"Idempotency-Key": "order-1"})
s2, r2, h2 = ask("POST", "/v1/citations/verify", {"quote": "脉浮"}, key=key, headers={"Idempotency-Key": "order-1"})
check("a repeat is the first answer, replayed", s1 == s2 == 200 and r1 == r2 and h2.get("Idempotent-Replayed") == "true", (r1, r2, h2))
s3, r3, _ = ask("POST", "/v1/citations/verify", {"quote": "other"}, key=key, headers={"Idempotency-Key": "order-1"})
check("the same key for another request: 422", s3 == 422 and r3["error"]["code"] == "idempotency_mismatch", (s3, r3))
s, lim, _ = ask("GET", "/v1/limits", key=key)
check("limits: 25 − 20 − 2 − 2 = 1 available", s == 200 and lim["data"]["credits"]["available"] == 1, lim)

# what is not charged
s, g, _ = ask("POST", f"/admin/orgs/{oid}/grants", {"credits": 100, "reference": "more"}, key=TOKEN)
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "refuse"}, key=key)
check("a tool's refusal: 422, not charged", s == 422 and r["error"]["code"] == "tool_refused" and "maximum 100" in r["error"]["message"], (s, r))
s, r, h = ask("POST", "/v1/evidence/search", {"query": "down"}, key=key)
check("the corpus starting: 503 with its Retry-After, not charged", s == 503 and h.get("Retry-After") == "7", (s, r, h))
t0 = time.time()
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "slow"}, key=key)
check("a corpus slower than the time limit: 503 after it, not charged", s == 503 and 4 < time.time() - t0 < 8, (s, r, time.time() - t0))
s, lim, _ = ask("GET", "/v1/limits", key=key)
check("nothing of those three was charged: 101", lim["data"]["credits"]["available"] == 101 and lim["data"]["credits"]["held"] == 0, lim)

# what is refused before anything is reserved
for body, code in [({"query": "x", "k": 500}, "range"), ({"query": "x", "limit": 3}, "field"), ([], "json")]:
    s, r, _ = ask("POST", "/v1/evidence/search", body, key=key)
    check(f"a request the API does not take: 400 {code}", s == 400 and r["error"]["code"] == code, (s, r))
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"})
check("no key: 401 missing_key", s == 401 and r["error"]["code"] == "missing_key", r)
forged = key[:9] + "0" * 26 + key[35:]
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"}, key=forged)
check("a key whose checksum is wrong: 401", s == 401 and r["error"]["code"] == "invalid_key", r)
def crockford(b):
    A = "0123456789abcdefghjkmnpqrstvwxyz"; n = int.from_bytes(b, "big"); bits = len(b) * 8; pad = (5 - bits % 5) % 5; n <<= pad; bits += pad
    return "".join(A[(n >> (bits - 5 * (i + 1))) & 31] for i in range(bits // 5))
body = "tao_live_" + "1" * 26 + "_" + "2" * 39
made = body + crockford(zlib.crc32(body.encode()).to_bytes(4, "big"))
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"}, key=made)
check("a well-formed key of an organisation nobody made: 401", s == 401 and r["error"]["code"] == "invalid_key", (s, r))
s, r, _ = ask("GET", "/v1/usage", key=key)
check("usage by day for the key's project", s == 200 and any(d["product"] == "evidence.search" and d["calls"] == 2 and d["failed"] == 3 for d in r["data"]["data"]), r)
s, r, _ = ask("POST", f"/admin/orgs/{oid}/keys/{k['id']}/revoke", {}, key=TOKEN)
check("the owner revokes the key", s == 200 and r["revoked"], r)
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=key)
check("a revoked key: 401 revoked_key", s == 401 and r["error"]["code"] == "revoked_key", r)
s, r, _ = ask("POST", "/admin/orgs", {"name": "x"}, key="not-the-token-0123456789")
check("the owner's endpoints refuse another token", s == 401, r)
s, r, _ = ask("GET", "/nowhere")
check("an unknown path: 404 JSON", s == 404 and r["error"]["type"] == "not_found", r)
print("failed:", check.failed)
sys.exit(1 if check.failed else 0)
