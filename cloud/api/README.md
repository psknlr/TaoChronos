# 道乃久开发者接口 · TaoChronos API

`https://api.impf.ai` — a model's chat, and the classics' evidence for programs: a search of the full corpus and a check
that a quotation is where it is said to be, each answered with the passages it rests on.  A Cloudflare Worker written
in Rust (`rust/platform/api`); why it is built as it is: [ADR 0038](../../docs/adr/0038-accounts-keys-and-credits.md),
[ADR 0039](../../docs/adr/0039-model-relay-and-daily-allowance.md).

## Keys

Every call carries a key: `Authorization: Bearer tao_live_…`.  A key belongs to a project of an organisation, and to a
**registered person** — its owner, whose daily allowance its calls spend.  It is made in the
[console](https://console.impf.ai) (its owner: you) or by the owner of the service (below).  It is shown once; keep it
where your server keeps its secrets — never in a web page, an app's bundle or a repository (the API sends no CORS
headers: a browser cannot call it).

| | `tao_live_…` | `tao_test_…` |
|---|---|---|
| for | your service | trying things |
| spends | your daily allowance | your daily allowance |

Scopes, chosen when the key is made: `chat:completions`, `models:read`, `evidence:search`, `citations:verify`,
`usage:read`.  A key made without naming them gets the last three only: model access is given by naming it.  A key that
is mistyped or cut short is refused before anything is asked (its last seven characters are a checksum).

## The daily allowance

**Five execution requests a day for each registered person**, renewed at 00:00 UTC (08:00 in Singapore) — chat,
evidence search and citation verification together, whichever of your keys, projects, organisations, models or
environments they come through.  Another key does not add to it.

* **Counted**: a request admitted and asked of the service — whether it answers, fails, runs out of time, or you leave
  before its end — and any request that may have run: a connection that failed under it, a tool that failed while it
  ran, a service that went away mid-call.
* **Not counted**: a request refused before it runs (its body, its scope, a limit), a repeat answered from before
  (`Idempotency-Key`), and a request the service says it refused without running it (the model's provider refusing
  it, busy or unavailable; the corpus not started; a tool refusing its arguments before it ran) — the answer then says
  `nothing was counted`, and its `X-Tao-Quota-Remaining` is as before.
* One of your requests runs at a time (`429 user_concurrency` while another does).

Every answer to an execution carries what is left:

```text
X-Tao-Quota-Limit: 5
X-Tao-Quota-Remaining: 3
X-Tao-Quota-Reset: 1795910400        (the next 00:00 UTC, in Unix seconds)
```

and a spent allowance is `429 daily_quota_exceeded`, with `Retry-After` until midnight UTC.

## Products

### `POST /v1/chat/completions` (scope `chat:completions`)

A model's chat, in the Chat Completions format — a documented subset of it, read strictly: a field it does not take is
refused (400 `unsupported_field`), never ignored.

```json
{
  "model": "Tao-R1",
  "messages": [{ "role": "user", "content": "桂枝汤主治何证？" }],
  "max_tokens": 1024,
  "stream": true
}
```

| Field | | |
|---|---|---|
| `model` | `Tao-R1` | `GET /v1/models` lists those this key may call |
| `messages` | 1–64 | `system`, `user`, `assistant`, `tool`; content is text or text parts (`{"type":"text","text":…}`, no images); an assistant's `tool_calls` and a tool's `tool_call_id`; an assistant's `reasoning_details` given back as the answer gave them — and an answer's message given back as an SDK writes it (`refusal`, `annotations`, `audio`, `function_call` empty) |
| `stream`, `stream_options.include_usage` | | server-sent events, as Chat Completions streams them; the usage in the last event when asked |
| `max_tokens` or `max_completion_tokens` | 1–8,192 | one of them; 4,096 when neither — Tao-R1's reasoning counts against it |
| `temperature` 0–1, `top_p` (0, 1], `stop` (1–4 texts) | | Tao-R1's range: 0 is its least randomness |
| `tools` (1–32 functions), `tool_choice` | | the model's tool calls come back to you: your program runs the tool and sends its answer |
| `n` | 1 | one answer a request |

The answer is a `chat.completion` (or `chat.completion.chunk` events) with `"model": "Tao-R1"` and `"id"` your request's
id (`X-Request-Id`), and the protocol's fields only — role, content, tool calls, reasoning, finish reason, usage — so
that its message may be given back as it came.  Tao-R1 reasons: its reasoning comes in `reasoning_details` (format
`Tao-…`); give them back with the assistant's message in the next turn of a tool loop.  A stream that fails after it began ends with an event
`{"error": {…}}`.  Each request counts once: a tool loop of a question, a search and the answer is three.

### `GET /v1/models` (scope `models:read`)

```json
{ "object": "list", "data": [{ "id": "Tao-R1", "object": "model", "capabilities": { "streaming": true, "tools": true, "reasoning": true }, "limits": { "max_output_tokens": 8192, "default_output_tokens": 4096, "max_messages": 64 } }] }
```

Free: it counts nothing.

### `POST /v1/evidence/search` (scope `evidence:search`)

```json
{ "query": "桂枝汤 汗出 恶风", "k": 10, "after": 200, "before": 1600, "books": ["伤寒论"] }
```

| Field | | |
|---|---|---|
| `query` | text, 1–500 characters | what to find: a question, terms, a phrase |
| `k` | 1–50, default 10 | how many passages |
| `after`, `before` | years, −5000–5000 | only passages dated within |
| `books` | 1–20 titles | only these works |

### `POST /v1/citations/verify` (scope `citations:verify`)

```json
{ "quote": "太阳之为病，脉浮，头项强痛而恶寒。", "passage_id": "shanghanlun:1" }
```

`quote` (1–2,000 characters) is looked for verbatim, then after variant normalisation; `passage_id` (optional) names
where it is said to be.

The two answer alike:

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
  "usage": { "credits": 0, "environment": "live", "price_version": "p…" }
}
```

`data` is the corpus tool's own result (`classics.search`, `validation.verify_quote`): its shape follows the tool.
`text` is the same result compacted for a language model, should you hand it one.

## Repeating a request

Send `Idempotency-Key: <1–255 visible characters>` with a POST.  The same key with the same request, within a day, in
the same project and environment, is answered with the first answer (`Idempotent-Replayed: true`) and counted once —
whichever of your keys sends it.

| | |
|---|---|
| another request under the same key | 422 `idempotency_conflict` |
| the first still running | 409 `request_in_progress`, `Retry-After: 1` |
| the first ended without a known outcome | 409 `request_outcome_unknown`: it is not run again |
| the first was a stream | 409 `stream_replay_unavailable`: a stream is not kept, nor run again |
| the first was refused before it ran (not counted) | the repeat runs |

## Limits and records

* Per key: 60 calls a minute, 2 in flight; per organisation: 4 in flight; per person: 1 in flight and the daily
  allowance above.
* `GET /v1/limits`: the key, its rate, what is in flight, how calls are paid (`funding`), and its owner's `user_quota`
  (`limit`, `used`, `in_flight`, `remaining`, `reset_at`).
* `GET /v1/usage?from=YYYY-MM-DD&to=YYYY-MM-DD` (scope `usage:read`): the key's project's calls, counted calls,
  failures, refusals and tokens by day, product and environment.
* `GET /v1/requests/{id}` (scope `usage:read`): a request's record — its product, model, outcome (`succeeded`,
  `failed`, `cancelled`, `unknown`, `released`), whether it was counted, its tokens — for seven days, to its owner's
  keys of its organisation.

## Errors

```json
{ "id": "req_…", "error": { "type": "rate_limit", "code": "daily_quota_exceeded", "message": "your daily allowance of 5 requests is spent; it renews at 00:00 UTC" } }
```

| Status | `type` | `code` (some) |
|---|---|---|
| 400 | `invalid_request` | `json`, `field`, `unsupported_field`, `unsupported_content`, `type`, `length`, `range`, `value`, `idempotency_key`, `model_rejected` |
| 401 | `authentication` | `missing_key`, `invalid_key`, `revoked_key`, `expired_key` |
| 402 | `insufficient_credits` | `credits`, `project_limit` (when calls are paid in credits) |
| 403 | `permission` | `scope`, `user_binding_required`, `member_suspended`, `user_suspended`, `model_access`, `project_archived`, `org_disabled` |
| 404 | `not_found` | `model_not_found`, `request`, `path` |
| 409 | `conflict` | `request_in_progress`, `request_outcome_unknown`, `stream_replay_unavailable`, `idempotency_unavailable` |
| 413 | `invalid_request` | `too_large` (a body is at most 64 KiB) |
| 422 | `invalid_request` | `tool_refused` (the corpus's own words), `idempotency_conflict` |
| 429 | `rate_limit` | `daily_quota_exceeded`, `user_concurrency`, `rate`, `concurrency`, `address`, `model_busy` — with `Retry-After` |
| 502, 503, 504 | `unavailable` | `model_error`, `response_too_large`, `model_unavailable`, `model_api_disabled`, `model_timeout`, `model_stalled`, `tool_failed`, `corpus`, `corpus_timeout`, `accounts`, `quota` |

Whether a failure was counted is in its message (`nothing was counted`, or `counted`) and in `X-Tao-Quota-Remaining`.

Every answer carries `X-Request-Id`; quote it when you write to us.

## Examples

```bash
curl -sS https://api.impf.ai/v1/chat/completions \
  -H "Authorization: Bearer $TAO_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "Tao-R1", "messages": [{"role": "user", "content": "桂枝汤主治何证？"}]}'
```

```bash
curl -sS --no-buffer https://api.impf.ai/v1/chat/completions \
  -H "Authorization: Bearer $TAO_API_KEY" -H "Content-Type: application/json" -H "Idempotency-Key: q-2026-11-28-1" \
  -d '{"model": "Tao-R1", "stream": true, "messages": [{"role": "user", "content": "麻黄汤与桂枝汤何别？"}]}'
```

Any Chat Completions client takes the API as its base — the OpenAI Python SDK:

```python
import os
from openai import OpenAI

client = OpenAI(base_url="https://api.impf.ai/v1", api_key=os.environ["TAO_API_KEY"])
answer = client.chat.completions.create(model="Tao-R1", messages=[{"role": "user", "content": "桂枝汤主治何证？"}])
print(answer.choices[0].message.content)
```

A search, the standard library alone:

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
console.log(res.headers.get("X-Tao-Quota-Remaining"), "left today");
```

## The owner's endpoints

Organisations, members, credits and keys without the console — for a pilot's first developers, or a correction.  Setting
the API up, and these endpoints step by step: [docs/platform.md](../../docs/platform.md), Part 3.  They answer the token
whose SHA-256 is the Worker's `ADMIN_TOKEN_SHA256` (the repository variable `API_ADMIN_TOKEN_SHA256`; the token itself is
kept nowhere but by the owner), and are off without it.  What they are told of people — a person's id, a member's role —
is taken as said: the owner vouches for it.

```bash
token=$(openssl rand -hex 32)                       # keep it in your password manager
printf '%s' "$token" | sha256sum | cut -d' ' -f1    # → the repository variable API_ADMIN_TOKEN_SHA256
```

| | |
|---|---|
| `POST /admin/orgs` `{"name", "owner"}` | a new organisation; `owner`: a registered person's id (`usr_…`, the console's security page shows it) |
| `GET /admin/orgs/{org}` | its members, credits, projects, keys (never a key itself), today's usage, what lapsed |
| `POST /admin/orgs/{org}/members` `{"user", "role", "status"}` | a member added, or their role or status (`active`, `suspended`) changed |
| `POST /admin/orgs/{org}/grants` `{"credits", "reference", "note"}` | credits in, once per reference |
| `POST /admin/orgs/{org}/adjustments` `{"credits", "reference", "note"}` | a correction, either sign |
| `POST /admin/orgs/{org}/projects` `{"name", "monthly_limit"}` | a project |
| `POST /admin/orgs/{org}/projects/{project}/limit` `{"monthly_limit"}` | its limit (`null`: none) |
| `POST /admin/orgs/{org}/keys` `{"environment", "name", "scopes", "project", "expires_days", "owner"}` | a key, shown once; `owner`: a member (the organisation's one owner when left out) |
| `POST /admin/orgs/{org}/keys/{key}/owner` `{"user"}` | a key given to a member |
| `POST /admin/orgs/{org}/keys/{key}/revoke` | revoked at once |
| `POST /admin/orgs/{org}/models` `{"access"}` | the organisation let in while `MODEL_API` is `pilot` |
| `GET /admin/users/{user}` | a person's allowance and latest requests |
| `POST /admin/users/{user}/suspend`, `…/restore` | a person's executions stopped, or let go on — through every key |

```bash
curl -sS -X POST https://api.impf.ai/admin/orgs -H "Authorization: Bearer $token" -H "Content-Type: application/json" -d '{"name": "Pilot lab", "owner": "usr_…"}'
curl -sS -X POST https://api.impf.ai/admin/orgs/org_…/keys -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
  -d '{"environment": "live", "name": "lab server", "scopes": ["chat:completions", "models:read", "evidence:search", "citations:verify", "usage:read"]}'
```

## Here

| | |
|---|---|
| `wrangler.toml` | the Worker: the daily allowance, the models, limits, its Durable Objects (`Account`, `UserQuota`), the edge's rate limits |
| `deploy.sh` | deploys it with the corpus's Worker and the model gateway bound when the account has them, and the owner's token by its digest |
| `test/run.sh` | the API and the model gateway as built, in local workerd beside a stand-in corpus (`test/corpus.js`) and a stand-in model provider (`test/provider.mjs`): `test/scenario.py`'s checks |
| `../models/` | the private model gateway: its configuration and deployment |

```bash
rust/platform/build.sh --install && (cd cloud/api && npm ci --ignore-scripts --no-audit --no-fund) && rust/platform/build.sh api && rust/platform/build.sh models
```

```bash
cloud/api/test/run.sh
```
