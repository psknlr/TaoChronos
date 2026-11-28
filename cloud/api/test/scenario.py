"""The developer API end to end (cloud/api/test/run.sh): the Rust Workers as built, in local workerd — the API, the
private model gateway and a stand-in corpus — with a stand-in model provider (provider.mjs).  A registered person's
daily allowance of five, shared by chat, search and verification across their keys, projects and organisations; what
counts and what does not; idempotent repeats; chat whole and streamed (cut in pieces, with tool calls and reasoning);
the provider's refusals, silences and failures; members suspended and people suspended; a request's record; limits;
forged keys; the owner's token; and that nothing of a developer's reaches the provider.  Standard library only.
Usage: scenario.py BASE_URL (ADMIN_TOKEN and PROVIDER in the environment)."""

import http.client
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

BASE = sys.argv[1].rstrip("/")
TOKEN = os.environ["ADMIN_TOKEN"]
PROVIDER = os.environ["PROVIDER"].rstrip("/")


def ask(method, path, body=None, key=None, headers=None, raw=False, timeout=40):
    h = {"Content-Type": "application/json", **(headers or {})}
    if key:
        h["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(BASE + path, method=method, headers=h, data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return r.status, (data.decode() if raw else json.loads(data or b"null")), dict(r.headers)
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, json.loads(data or b"null"), dict(e.headers)
        except ValueError:
            return e.code, data.decode(), dict(e.headers)


def check(what, cond, detail=""):
    print(("ok  " if cond else "FAIL"), what, "" if cond else detail)
    if not cond:
        check.failed += 1


check.failed = 0


def remaining(h):
    return int(h.get("X-Tao-Quota-Remaining", "-1"))


def events(text):
    """The data of each event of an SSE text, and whether anything else (a comment) was in it."""
    data, comments = [], []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                data.append(line[6:])
            elif line.startswith(":"):
                comments.append(line)
    return data, comments


def chat(key, content, stream=False, headers=None, **more):
    body = {"model": "Tao-R1", "messages": [{"role": "user", "content": content}], "stream": stream, **more}
    out = ask("POST", "/v1/chat/completions", body, key=key, headers=headers, raw=stream)
    if stream:
        # a stream's end is told from waitUntil just after its last byte: the person's next request waits for it
        time.sleep(0.5)
    return out


USER1, USER2, USER3, USER4 = ("usr_" + c * 26 for c in "abcd")
ALL = ["evidence:search", "citations:verify", "usage:read", "chat:completions", "models:read"]

# ------------------------------------------------------------------ an organisation of a registered person, two keys
s, org, _ = ask("POST", "/admin/orgs", {"name": "Pilot lab", "owner": USER1}, key=TOKEN)
check("owner makes an organisation with its registered owner", s == 200 and org["org"]["id"].startswith("org_") and org["members"][0]["user"] == USER1, (s, org))
oid = org["org"]["id"]
s, live, _ = ask("POST", f"/admin/orgs/{oid}/keys", {"environment": "live", "name": "server"}, key=TOKEN)
check("a live key, its owner the organisation's one owner", s == 200 and live["key"].startswith("tao_live_"), (s, live))
s, test, _ = ask("POST", f"/admin/orgs/{oid}/keys", {"environment": "test", "name": "laptop", "scopes": ALL}, key=TOKEN)
check("a test key with model access, named", s == 200 and test["key"].startswith("tao_test_"), (s, test))
K1, K2 = live["key"], test["key"]

# ------------------------------------------------------------------ what counts, and what does not
s, r, h = ask("POST", "/v1/evidence/search", {"query": "桂枝汤 汗出 恶风", "k": 5}, key=K1)
check("a search answers, and the allowance says what is left: 4 of 5", s == 200 and r["object"] == "evidence.search" and remaining(h) == 4 and h.get("X-Tao-Quota-Limit") == "5", (s, h))
check("on the daily allowance no credit is spent", r.get("usage", {}).get("credits") == 0, r.get("usage"))
check("its request id is its header", r["id"] == h.get("X-Request-Id"), (r["id"], h))
check("no receipt is passed on", "receipt" not in json.dumps(r), r)
s, r1, h1 = ask("POST", "/v1/citations/verify", {"quote": "脉浮"}, key=K1, headers={"Idempotency-Key": "order-1"})
s2, r2, h2 = ask("POST", "/v1/citations/verify", {"quote": "脉浮"}, key=K1, headers={"Idempotency-Key": "order-1"})
check("a repeat of an Idempotency-Key is its first answer, and counts nothing", s == s2 == 200 and r1 == r2 and h2.get("Idempotent-Replayed") == "true" and remaining(h2) == 3, (r1, r2, h2))
s3, r3, _ = ask("POST", "/v1/citations/verify", {"quote": "other"}, key=K1, headers={"Idempotency-Key": "order-1"})
check("the same key for another request: 422 idempotency_conflict", s3 == 422 and r3["error"]["code"] == "idempotency_conflict", (s3, r3))
s, r, h = ask("POST", "/v1/evidence/search", {"query": "refuse"}, key=K1)
check("a tool's refusal: 422, not counted", s == 422 and r["error"]["code"] == "tool_refused" and remaining(h) == 3, (s, r, h))
s, r, h = ask("POST", "/v1/evidence/search", {"query": "down"}, key=K1)
check("the corpus starting: 503 with its Retry-After, not counted", s == 503 and h.get("Retry-After") == "7" and remaining(h) == 3, (s, r, h))

# ------------------------------------------------------------------ chat, whole and streamed, through the gateway
s, r, h = chat(K2, "桂枝汤主治？")
check("a chat answers in the API's terms: its model, its id", s == 200 and r["model"] == "Tao-R1" and r["id"] == h.get("X-Request-Id") and r["choices"][0]["message"]["content"].startswith("Tao answers"), (s, r))
check("nothing of the provider's own is passed on", not any(w in json.dumps(r) for w in ["MiniMax", "base_resp", "sensitive", "total_characters"]), r)
check("its reasoning's formats are the API's", r["choices"][0]["message"]["reasoning_details"][0]["format"] == "Tao-response-v1", r)
check("its usage is reported", r["usage"]["prompt_tokens"] == 11 and r["usage"]["completion_tokens"] == 7, r.get("usage"))
check("another key of the same person shares the allowance: 2 left", remaining(h) == 2, h)
chat_id = r["id"]
seen = json.loads(urllib.request.urlopen(PROVIDER + "/seen", timeout=10).read())
up = seen["last"]
check("the provider is asked in its terms: its model, its fields, one output limit", up["model"] == "MiniMax-M3" and up.get("reasoning_split") is True and up["max_completion_tokens"] == 4096 and "max_tokens" not in up, up)
s, text, h = chat(K2, "fragment tool", stream=True, tools=[{"type": "function", "function": {"name": "evidence_search", "parameters": {"type": "object"}}}])
data, comments = events(text)
chunks = [json.loads(d) for d in data if d != "[DONE]"]
args = "".join(c["choices"][0]["delta"].get("tool_calls", [{}])[0].get("function", {}).get("arguments", "") for c in chunks if c.get("choices"))
check("a stream cut in pieces of 1–7 bytes arrives whole, in events of the API", s == 200 and data and data[-1] == "[DONE]" and all(c["model"] == "Tao-R1" and c["id"] == h.get("X-Request-Id") for c in chunks), (s, text[:400]))
check("a tool call's arguments are passed on as the model wrote them", args == '{"query":"桂枝汤","model":"MiniMax-M3"}', args)
check("the gateway's own words are not passed on, nor the provider's keep-alive", not comments, comments)
check("a usage event the caller did not ask for is not passed on", not any("usage" in c for c in chunks), chunks[-1:])
check("the stream counts: 1 left", remaining(h) == 1, h)
s, text, h = chat(K2, "and reasoning", stream=True, stream_options={"include_usage": True})
data, _ = events(text)
chunks = [json.loads(d) for d in data if d != "[DONE]"]
check("a stream's reasoning under the API's format names, its usage when asked", any(c["choices"] and c["choices"][0]["delta"].get("reasoning_details", [{}])[0].get("format") == "Tao-response-v1" for c in chunks)
      and chunks[-1].get("usage", {}).get("completion_tokens") == 7, chunks[:2] + chunks[-1:])
check("the fifth call: none left", remaining(h) == 0, h)

# ------------------------------------------------------------------ the allowance spent, whatever the key, product, model or organisation
s, r, h = chat(K2, "one more")
check("a sixth call: 429 daily_quota_exceeded until 00:00 UTC", s == 429 and r["error"]["code"] == "daily_quota_exceeded" and 0 < int(h.get("Retry-After", "0")) <= 86400 and remaining(h) == 0, (s, r, h))
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"}, key=K1)
check("a search with the other key too", s == 429 and r["error"]["code"] == "daily_quota_exceeded", (s, r))
s, org_b, _ = ask("POST", "/admin/orgs", {"name": "Second lab", "owner": USER1}, key=TOKEN)
s, kb, _ = ask("POST", f"/admin/orgs/{org_b['org']['id']}/keys", {"environment": "test", "name": "b", "scopes": ALL}, key=TOKEN)
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=kb["key"])
check("and through another organisation of the same person", s == 429 and r["error"]["code"] == "daily_quota_exceeded", (s, r))
s, r, _ = ask("GET", "/v1/limits", key=K1)
q = r["data"]["user_quota"]
check("limits: the person's allowance, and how calls are paid", s == 200 and (q["limit"], q["used"], q["remaining"], q["timezone"]) == (5, 5, 0, "UTC") and r["data"]["funding"]["mode"] == "daily_allowance", r)
s, r, _ = ask("GET", f"/v1/requests/{chat_id}", key=K1)
check("a request's record, to its owner's keys of its organisation", s == 200 and r["state"] == "succeeded" and r["quota_consumed"] and r["model"] == "Tao-R1", (s, r))
s, r, _ = ask("GET", f"/v1/requests/{chat_id}", key=kb["key"])
check("not to the same person's keys of another organisation", s == 404, (s, r))
s, r, _ = ask("GET", "/v1/usage", key=K1)
check("usage by day: calls, what was counted, no credits", s == 200 and any(d["product"] == "evidence.search" and d["calls"] == 1 and d["quota_consumed"] == 1 and d["credits"] == 0 for d in r["data"]["data"]), r)

# ------------------------------------------------------------------ another person: scopes, the provider's refusals and silences
s, org_c, _ = ask("POST", "/admin/orgs", {"name": "Third lab", "owner": USER2}, key=TOKEN)
oc = org_c["org"]["id"]
s, legacy, _ = ask("POST", f"/admin/orgs/{oc}/keys", {"environment": "test", "name": "old script"}, key=TOKEN)
s, r, _ = chat(legacy["key"], "x")
check("a key made without naming scopes calls no model: 403 scope", s == 403 and r["error"]["code"] == "scope", (s, r))
s, r, _ = ask("GET", "/v1/models", key=legacy["key"])
check("nor lists them", s == 403 and r["error"]["code"] == "scope", (s, r))
s, kc, _ = ask("POST", f"/admin/orgs/{oc}/keys", {"environment": "test", "name": "chat", "scopes": ALL}, key=TOKEN)
K3 = kc["key"]
s, r, _ = ask("GET", "/v1/models", key=K3)
check("the models this key may call", s == 200 and [m["id"] for m in r["data"]] == ["Tao-R1"] and "MiniMax" not in json.dumps(r), (s, r))
for body, code in [({"model": "Tao-R1", "messages": [{"role": "user", "content": "x"}], "user": "someone"}, "unsupported_field"),
                   ({"model": "nobody", "messages": [{"role": "user", "content": "x"}]}, "model_not_found"),
                   ({"model": "Tao-R1", "messages": [{"role": "user", "content": "x"}], "max_tokens": 100000}, "range")]:
    s, r, h = ask("POST", "/v1/chat/completions", body, key=K3)
    check(f"a chat the API does not take: {s} {code}, nothing counted", r["error"]["code"] == code and "X-Tao-Quota-Remaining" not in h, (s, r))
s, r, h = chat(K3, "reject this")
check("the provider refusing the request: 400 model_rejected, not counted", s == 400 and r["error"]["code"] == "model_rejected" and remaining(h) == 5, (s, r, h))
s, r, h = chat(K3, "busy now")
check("the provider busy: 429 model_busy, not counted", s == 429 and r["error"]["code"] == "model_busy" and remaining(h) == 5, (s, r, h))
s, r, h = chat(K3, "base_resp please")
check("a failure inside the provider's 200: not counted", s == 503 and r["error"]["code"] == "model_unavailable" and remaining(h) == 5, (s, r, h))
t0 = time.time()
s, text, h = chat(K3, "slow-start", stream=True)
check("a provider silent past the first event's deadline: 504, counted", s == 504 and remaining(h) == 4 and 4 < time.time() - t0 < 15, (s, text, h, time.time() - t0))
s, text, h = chat(K3, "stall", stream=True)
data, _ = events(text)
check("a provider silent half-way: the stream ends with an error event, counted", s == 200 and data and "model_stalled" in data[-1] and remaining(h) == 3, (s, text[-300:], h))
s, r, _ = ask("GET", "/v1/requests/" + h.get("X-Request-Id"), key=K3)
check("and its record says it failed", s == 200 and r["state"] == "failed" and r["code"] == "model_stalled" and r["streamed"], (s, r))
s, r, h = chat(K3, "x", headers={"Idempotency-Key": "c-1"})
s2, r2, h2 = chat(K3, "x", headers={"Idempotency-Key": "c-1"})
check("a chat repeated under its Idempotency-Key: the same answer, counted once", s == s2 == 200 and r == r2 and h2.get("Idempotent-Replayed") == "true" and remaining(h2) == remaining(h) == 2, (h, h2))
s, text, _ = chat(K3, "y", stream=True, headers={"Idempotency-Key": "c-2"})
s2, r2, _ = chat(K3, "y", stream=True, headers={"Idempotency-Key": "c-2"})
check("a stream is not replayed: 409 stream_replay_unavailable, not run again", s == 200 and s2 == 409 and r2["error"]["code"] == "stream_replay_unavailable", (s, s2, r2))

# ------------------------------------------------------------------ one of a person's requests at a time
out = {}
def slow():
    out["a"] = chat(K3, "slow-start", stream=True)
th = threading.Thread(target=slow)
th.start()
time.sleep(1.5)
s, r, _ = chat(K3, "meanwhile")
th.join()
check("a second request while one runs: 429 user_concurrency, not counted", s == 429 and r["error"]["code"] == "user_concurrency", (s, r))

# ------------------------------------------------------------------ members and people suspended; keys with no owner
s, org_d, _ = ask("POST", "/admin/orgs", {"name": "Fourth lab"}, key=TOKEN)
od = org_d["org"]["id"]
s, r, _ = ask("POST", f"/admin/orgs/{od}/keys", {"environment": "test", "name": "x"}, key=TOKEN)
check("an organisation with no member: a key must name its owner", s == 400 and r["error"]["code"] == "owner_required", (s, r))
s, r, _ = ask("POST", f"/admin/orgs/{od}/members", {"user": USER3, "role": "owner"}, key=TOKEN)
s, kd, _ = ask("POST", f"/admin/orgs/{od}/keys", {"environment": "test", "name": "x"}, key=TOKEN)
s, r, h = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=kd["key"])
check("a member the owner vouched for: their key runs", s == 200 and remaining(h) == 4, (s, r, h))
ask("POST", f"/admin/orgs/{od}/members", {"user": USER3, "status": "suspended"}, key=TOKEN)
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=kd["key"])
check("a suspended member's key: 403 member_suspended", s == 403 and r["error"]["code"] == "member_suspended", (s, r))
ask("POST", f"/admin/orgs/{od}/members", {"user": USER3, "status": "active"}, key=TOKEN)
s, r, _ = ask("POST", f"/admin/users/{USER3}/suspend", {}, key=TOKEN)
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=kd["key"])
check("a suspended person: 403 user_suspended, through any key", s == 403 and r["error"]["code"] == "user_suspended", (s, r))
ask("POST", f"/admin/users/{USER3}/restore", {}, key=TOKEN)
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=kd["key"])
check("restored, they run again", s == 200, (s, r))
s, r, _ = ask("GET", f"/admin/users/{USER3}", key=TOKEN)
check("the owner reads a person's allowance and requests", s == 200 and r["quota"]["used"] == 2 and len(r["requests"]) == 2, (s, r))

# ------------------------------------------------------------------ the slow corpus, refusals before anything, forged keys, the owner
s, org_e, _ = ask("POST", "/admin/orgs", {"name": "Fifth lab", "owner": USER4}, key=TOKEN)
s, ke, _ = ask("POST", f"/admin/orgs/{org_e['org']['id']}/keys", {"environment": "test", "name": "e"}, key=TOKEN)
K4 = ke["key"]
t0 = time.time()
s, r, h = ask("POST", "/v1/evidence/search", {"query": "slow"}, key=K4)
check("a corpus slower than the time limit: 503 after it, counted", s == 503 and r["error"]["code"] == "corpus_timeout" and 4 < time.time() - t0 < 8 and remaining(h) == 4, (s, r, time.time() - t0, h))
# a caller who leaves mid-stream: the gateway's call aborted, and the provider's; the request counted as cancelled
s, ke2, _ = ask("POST", f"/admin/orgs/{org_e['org']['id']}/keys", {"environment": "test", "name": "e2", "scopes": ALL}, key=TOKEN)
aborted = json.loads(urllib.request.urlopen(PROVIDER + "/seen", timeout=10).read())["aborted"]
u = urllib.parse.urlparse(BASE)
c = http.client.HTTPConnection(u.hostname, u.port, timeout=20)
c.request("POST", "/v1/chat/completions", json.dumps({"model": "Tao-R1", "messages": [{"role": "user", "content": "drip, then leave"}], "stream": True}),
          {"Authorization": f"Bearer {ke2['key']}", "Content-Type": "application/json"})
resp = c.getresponse()
left_id = resp.getheader("X-Request-Id")
first = resp.read(6)
c.close()
for _ in range(20):
    time.sleep(0.5)
    s, r, _ = ask("GET", f"/v1/requests/{left_id}", key=ke2["key"])
    if r.get("state") != "admitted":
        break
check("a caller who leaves mid-stream: counted, and recorded as cancelled", first.startswith(b"data: ") and s == 200 and r["state"] == "cancelled" and r["quota_consumed"], (first, s, r))
now_aborted = json.loads(urllib.request.urlopen(PROVIDER + "/seen", timeout=10).read())["aborted"]
check("and the provider's call is aborted with it", now_aborted > aborted, (aborted, now_aborted))
for body, code in [({"query": "x", "k": 500}, "range"), ({"query": "x", "limit": 3}, "field"), ([], "json")]:
    s, r, _ = ask("POST", "/v1/evidence/search", body, key=K4)
    check(f"a request the API does not take: 400 {code}", s == 400 and r["error"]["code"] == code, (s, r))
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"})
check("no key: 401 missing_key", s == 401 and r["error"]["code"] == "missing_key", r)
forged = K4[:9] + "0" * 26 + K4[35:]
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"}, key=forged)
check("a key whose checksum is wrong: 401", s == 401 and r["error"]["code"] == "invalid_key", r)


def crockford(b):
    A = "0123456789abcdefghjkmnpqrstvwxyz"
    n = int.from_bytes(b, "big")
    bits = len(b) * 8
    pad = (5 - bits % 5) % 5
    n <<= pad
    bits += pad
    return "".join(A[(n >> (bits - 5 * (i + 1))) & 31] for i in range(bits // 5))


body = "tao_live_" + "1" * 26 + "_" + "2" * 39
made = body + crockford(zlib.crc32(body.encode()).to_bytes(4, "big"))
s, r, _ = ask("POST", "/v1/evidence/search", {"query": "x"}, key=made)
check("a well-formed key of an organisation nobody made: 401", s == 401 and r["error"]["code"] == "invalid_key", (s, r))
s, r, _ = ask("POST", f"/admin/orgs/{oid}/keys/{live['id']}/revoke", {}, key=TOKEN)
check("the owner revokes a key", s == 200 and r["revoked"], r)
s, r, _ = ask("POST", "/v1/citations/verify", {"quote": "x"}, key=K1)
check("a revoked key: 401 revoked_key", s == 401 and r["error"]["code"] == "revoked_key", r)
s, r, _ = ask("POST", "/admin/orgs", {"name": "x"}, key="not-the-token-0123456789")
check("the owner's endpoints refuse another token", s == 401, r)
s, r, _ = ask("GET", "/nowhere")
check("an unknown path: 404 JSON", s == 404 and r["error"]["type"] == "not_found", r)
s, r, _ = ask("GET", "/v1")
check("the index names the products, the models and the daily allowance", s == 200 and r["models"] == ["Tao-R1"] and r["daily_allowance"]["limit"] == 5 and "chat.completions" in r["products"], r)

# ------------------------------------------------------------------ nothing of a developer's reached the provider
seen = json.loads(urllib.request.urlopen(PROVIDER + "/seen", timeout=10).read())
check("no developer's key, nor any cookie, reached the provider; it was asked with its own key only",
      not seen["tao_seen"] and not seen["cookie_seen"] and seen["wrong_auth"] == 0 and seen["requests"] > 0, seen)
print("failed:", check.failed)
sys.exit(1 if check.failed else 0)
