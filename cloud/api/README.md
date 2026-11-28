# 道乃久开发者接口 · TaoChronos API

`https://api.impf.ai` — the classics' evidence for programs: a search of the full corpus and a check that a quotation
is where it is said to be, each answered with the passages it rests on.  A Cloudflare Worker written in Rust
(`rust/platform/api`); why it is built as it is: [ADR 0038](../../docs/adr/0038-accounts-keys-and-credits.md).

## Keys

Every call carries a key: `Authorization: Bearer tao_live_…`.  A key belongs to a project of an organisation, and is
made in the [console](https://console.impf.ai) (or by the owner: below).  It is shown once; keep it where your server
keeps its secrets — never in a web page, an app's bundle or a repository (the API sends no CORS headers: a browser
cannot call it).

| | `tao_live_…` | `tao_test_…` |
|---|---|---|
| spends | the organisation's credits | nothing |
| allowance | the credits available | 100 calls a day for the organisation |

Scopes, chosen when the key is made: `evidence:search`, `citations:verify`, `usage:read`.  A key that is mistyped or cut
short is refused before anything is asked (its last seven characters are a checksum).

## Products

### `POST /v1/evidence/search`

```json
{ "query": "桂枝汤 汗出 恶风", "k": 10, "after": 200, "before": 1600, "books": ["伤寒论"] }
```

| Field | | |
|---|---|---|
| `query` | text, 1–500 characters | what to find: a question, terms, a phrase |
| `k` | 1–50, default 10 | how many passages |
| `after`, `before` | years, −5000–5000 | only passages dated within |
| `books` | 1–20 titles | only these works |

### `POST /v1/citations/verify`

```json
{ "quote": "太阳之为病，脉浮，头项强痛而恶寒。", "passage_id": "shanghanlun:1" }
```

`quote` (1–2,000 characters) is looked for verbatim, then after variant normalisation; `passage_id` (optional) names
where it is said to be.

### The answer

```json
{
  "id": "req_7m0x…",
  "object": "evidence.search",
  "created": 1795824000,
  "data": {
    "result": { "…": "the tool's result" },
    "citations": [{ "passage_id": "…", "…": "…" }],
    "summary": "…",
    "text": "the result as a model reads it"
  },
  "usage": { "credits": 10, "environment": "live", "price_version": "p1d0a3763" }
}
```

`data` is the corpus tool's own result (`classics.search`, `validation.verify_quote`): its shape follows the tool.
`text` is the same result compacted for a language model, should you hand it one.

A request is read strictly: a field a product does not take, or a value past its limit, is refused (400) — not ignored,
not clamped.

## What it costs

| Product | Credits (live key) |
|---|---|
| `evidence.search` | 10 |
| `citations.verify` | 2 |

`GET /v1` lists the prices and their version.  A call is **charged only when the corpus ran it**: a refusal of its
arguments (422), a corpus starting or busy (503), any failure of ours (502, 500) costs nothing.  A call's price is
reserved when it is let through and settled when it ends, so calls arriving together never spend more than is available.

## Repeating a request

Send `Idempotency-Key: <1–255 visible characters>` with a POST.  The same key with the same request, within a day, is
answered with the first answer (`Idempotent-Replayed: true`) and charged once; with another request, 422
(`idempotency_mismatch`); while the first is still running, 409 with `Retry-After: 1`.  A failed call is no answer: its
repeat runs.

## Limits

* 60 calls a minute and 2 in flight per key; 4 in flight per organisation; test keys 100 calls a day per organisation.
* A project may have a monthly limit in credits (the console's owner sets it).
* `GET /v1/limits` says what the key may do now; `GET /v1/usage?from=YYYY-MM-DD&to=YYYY-MM-DD` (scope `usage:read`) its
  project's calls, credits, failures and refusals by day, product and environment.

## Errors

```json
{ "id": "req_…", "error": { "type": "insufficient_credits", "code": "credits", "message": "evidence.search costs 10 credits; 5 are available" } }
```

| Status | `type` | `code` (some) |
|---|---|---|
| 400 | `invalid_request` | `json`, `field`, `type`, `length`, `range`, `characters`, `idempotency_key` |
| 401 | `authentication` | `missing_key`, `invalid_key`, `revoked_key`, `expired_key` |
| 402 | `insufficient_credits` | `credits`, `project_limit` |
| 403 | `permission` | `scope`, `project_archived`, `org_disabled` |
| 409 | `conflict` | `idempotency_in_progress`, `idempotency_unavailable` |
| 413 | `invalid_request` | `too_large` (a body is at most 64 KiB) |
| 422 | `invalid_request` | `tool_refused` (the corpus's own words), `idempotency_mismatch` |
| 429 | `rate_limit` | `rate`, `concurrency`, `test_allowance`, `address` — with `Retry-After` |
| 502, 503 | `unavailable` | `corpus`, `accounts` — with `Retry-After` on 503 |

Every answer carries `X-Request-Id`; quote it when you write to us.

## Examples

```bash
curl -sS https://api.impf.ai/v1/evidence/search \
  -H "Authorization: Bearer $TAO_API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "桂枝汤 汗出 恶风", "k": 5}'
```

Python, the standard library alone:

```python
import json, os, urllib.request

def tao(path, body):
    req = urllib.request.Request(f"https://api.impf.ai{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['TAO_API_KEY']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)

hits = tao("/v1/evidence/search", {"query": "桂枝汤 汗出 恶风", "k": 5})
for c in hits["data"]["citations"]:
    print(c["passage_id"])
```

TypeScript (Node 18+, Deno, Workers):

```ts
const res = await fetch("https://api.impf.ai/v1/citations/verify", {
  method: "POST",
  headers: { Authorization: `Bearer ${process.env.TAO_API_KEY}`, "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
  body: JSON.stringify({ quote: "太阳之为病，脉浮，头项强痛而恶寒。" }),
});
if (!res.ok) throw new Error(`${res.status} ${(await res.json()).error.code}`);
const { data, usage } = await res.json();
```

## The owner's endpoints

Organisations, credits and keys without the console — for a pilot's first developers, or a correction.  Setting the
API up, and these endpoints step by step: [docs/platform.md](../../docs/platform.md), Part 3.  They answer
the token whose SHA-256 is the Worker's `ADMIN_TOKEN_SHA256` (the repository variable `API_ADMIN_TOKEN_SHA256`; the
token itself is kept nowhere but by the owner), and are off without it.

```bash
token=$(openssl rand -hex 32)                       # keep it in your password manager
printf '%s' "$token" | sha256sum | cut -d' ' -f1    # → the repository variable API_ADMIN_TOKEN_SHA256
```

| | |
|---|---|
| `POST /admin/orgs` `{"name"}` | a new organisation (its id, `org_…`, in the answer) |
| `GET /admin/orgs/{org}` | its credits, projects, keys (never a key itself), today's usage, what lapsed |
| `POST /admin/orgs/{org}/grants` `{"credits", "reference", "note"}` | credits in, once per reference |
| `POST /admin/orgs/{org}/adjustments` `{"credits", "reference", "note"}` | a correction, either sign |
| `POST /admin/orgs/{org}/projects` `{"name", "monthly_limit"}` | a project |
| `POST /admin/orgs/{org}/projects/{project}/limit` `{"monthly_limit"}` | its limit (`null`: none) |
| `POST /admin/orgs/{org}/keys` `{"environment", "name", "scopes", "project", "expires_days"}` | a key, shown once |
| `POST /admin/orgs/{org}/keys/{key}/revoke` | revoked at once |

```bash
curl -sS -X POST https://api.impf.ai/admin/orgs -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d '{"name": "Pilot lab"}'
curl -sS -X POST https://api.impf.ai/admin/orgs/org_…/grants -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
  -d '{"credits": 10000, "reference": "pilot-2026-12", "note": "pilot"}'
curl -sS -X POST https://api.impf.ai/admin/orgs/org_…/keys -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
  -d '{"environment": "live", "name": "lab server"}'
```

## Here

| | |
|---|---|
| `wrangler.toml` | the Worker: prices, limits, its Durable Object (`Account`), the edge's rate limits |
| `deploy.sh` | deploys it with the corpus's Worker bound when the account has it, and the owner's token by its digest |
| `test/run.sh` | the API as built, in local workerd beside a stand-in corpus (`test/corpus.js`): `test/scenario.py`'s checks |

```bash
rust/platform/build.sh --install && (cd cloud/api && npm ci --ignore-scripts --no-audit --no-fund) && rust/platform/build.sh api
```

```bash
cloud/api/test/run.sh
```
