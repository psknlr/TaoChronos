# ADR 0039 — A model's chat through the developer API, and five calls a day for each registered person

**Status:** accepted · 2026-11-28 · amends [ADR 0038](0038-accounts-keys-and-credits.md) (what an execution costs: a
registered person's daily allowance; who an API key belongs to; the organisation's object at schema 2)

## Context

A proposal of 2026-11-28, *Rust-first plan: add model relay to `api.impf.ai` with five daily calls per user*, read
against the repository at `66d4a0f`, asked for `POST /v1/chat/completions` and `GET /v1/models` in the Rust developer
API, relayed through a private Rust Worker that alone holds the providers' keys, and for **one allowance of five
execution requests a registered user a UTC day**, shared by chat, evidence search and citation verification, whichever
keys, projects, organisations, models or key environments they come through.  The owner's direction: adopt it where
appropriate, improve it where possible, implement better alternatives.

Read against the code and the deployment as they stood:

* **api.impf.ai and console.impf.ai are live**, registration open, Turnstile on: the organisations' objects hold real
  keys, credits and usage (schema 1).  Whatever the change does to them, it does in place, to data that exists.
* An API key belongs to an organisation's `Account` object; its execution was a credit reservation in that object, with
  a separate allowance of a hundred test calls a day an organisation.  Nothing knew which person a key's calls were
  for: the console wrote its person's id as a key's `created_by`, the owner's endpoints wrote `"owner"`.
* The console binds the API's `Account` class (`script_name`).  An API Worker that bound the console's `Identity`
  class in turn would make each Worker's first deployment need the other's.
* The website's relay (`relay/src/relay.js`) asks MiniMax's OpenAI-compatible chat completions on its **mainland**
  platform (`api.minimax.cn`, the key in `MINIMAX_API_KEY`), publishes `MiniMax-M3` as **Tao-R1**, asks for its
  reasoning apart (`reasoning_split`), and renames the reasoning's formats `MiniMax-…` → `Tao-…` — by regular
  expressions over the text of a stream.
* Measured here while it was built: **workers-rs 0.9's `Context::wait_until` cannot outlive the handler**.  It wraps the
  future so that each poll re-enters the span that was active when it was called; that span ends when the handler
  returns, and the runtime's `withActiveSpan` then throws, which wasm-bindgen treats as fatal ("Critical error").  A
  stream's end, told after the handler has returned the stream, never was.  And a client that closes its connection is
  noticed by a server only at its next write: a stream whose provider is silent ends by its deadline, not by the leaving.

## Decision

### Who a call is for

1. **Every executable key has an owner** — `keys.owner_user_id`, with when and by whom it was bound — the registered
   person whose allowance it spends.  The console writes the person whose session asks; the owner's endpoints name a
   member (or, none named, the organisation's one active owner, and refuse `owner_required` when there is not exactly
   one); a key a person makes without naming its owner — a console older than owners, during a deployment — is that
   person's, never the organisation's owner's.  Nothing in a request to the API names or changes an owner.
   `created_by` stays as written, for the record.
2. **The organisation's object knows its members by being told**, not by asking.  It keeps `members` (role, status):
   the console says, in the body of each call it makes for a person, `member` and `role` — what the identity object has
   just verified of the session — and provisions a new organisation with its registrant as owner; the owner's endpoints
   add, suspend and restore members, a member's role and status each changed only when it is named (a new role leaves
   a suspension as it was).  A member seen again is not let back by being seen: their status is the owner's.
   So the API needs no call to the identity object on each execution, and no binding to the console's class: the
   proposal's `Identity.api_principal` would have made the one global identity object part of every call's path, and
   the two Workers each other's prerequisite.
3. **The migration to schema 2 runs when an object is next asked**: each new column added only if its table lacks it
   (read from `sqlite_master`), the members table made, the version written last — a migration a failure cut short is
   taken up where it stopped.  A key whose `created_by` is a person's id (the console's) becomes theirs, and they a
   member (owner: the only role the console has made); a key the owner's token made names nobody and executes nothing
   (`user_binding_required`) until the owner gives it to a member (`POST /admin/orgs/{org}/keys/{key}/owner`).  Keys,
   credits, the ledger and usage are kept as they are; the new usage columns start at zero.
4. **Scopes**: `chat:completions` and `models:read` beside the three of ADR 0038.  A key made without naming its scopes
   gets the three it always got — a new scope is given only by naming it, so no update of the service widens a key a
   script makes as it always did.  The console names all five, each a box to untick.

### What a call may spend

5. **One object a person** (`UserQuota`, named `user-quota:<user_id>` — no day, model, project or key in the name, and
   the class never renamed: either would be a fresh allowance).  `DAILY_REQUEST_LIMIT` (5) admissions a UTC day,
   `USER_EXECUTION_CONCURRENCY` (1) in flight; a person suspended there (the owner's `POST /admin/users/{user}/suspend`)
   runs nothing through any key.
6. **The admission, in two steps** (`api/src/exec.rs`): the organisation first — the key, its scope, its owner an
   active member, its project, the model gate, the key's rate and what it and the organisation have in flight — which
   takes a **lease**; then the person's allowance, which **admits and counts in one step** (one SQL write: a repeat of an
   `Idempotency-Key` answered from before, their own call in flight, the day's count).  A refusal at the second gives the
   lease back; an answer of either object that does not say what it should (a lease, a registered owner, an
   admission) lets nothing through.  The proposal's sequence reserved the person's slot first and fenced its dispatch;
   asked in this order there is no reservation to fence — only the organisation can say whose a key is, so it is asked
   first; the request to the gateway or the corpus is made before either is asked, so once the person's object has
   admitted a request there is no step left that could fail between counting and asking.
7. **What counts**: a request admitted counts unless the service it was sent to **says that it ran nothing** — then
   it is *released*, uncounted: the gateway's `X-Tao-Executed: 0` (its own refusal before the provider was asked, or
   the provider's refusal of the request outright: a 4xx, its rate or quota spent, its key or the call's region
   refused, a failure inside a 200's `base_resp`); the corpus's refusal before its tool ran (`ran: false`, or the
   runtime's 400), its 429, or a 503 marked `X-TC-Call: unsent` (a container that could not be started was sent
   nothing).  A gateway or corpus not bound is refused before anything is admitted.  Everything else counts, because
   it may have run: an answer; a failure, a timeout, a caller who left; a connection to the provider, the gateway or
   the corpus that failed (before the request was taken or after — not known); a gateway that answered without saying;
   a tool that failed while it ran, or a failure that does not say whether it ran; a corpus that went away under the
   call; a Worker that died (its request of **unknown** outcome once its lease passes — counted, never taken back by a
   late word, and never run again by a repeat of its key while keys name their requests).  So no unforeseen failure
   is a way to run without counting.  The proposal counted every dispatch; a refusal the provider or the corpus made
   before running anything is no use of the service, and five a day are too few to spend on it.  The day of a request
   is the day it was admitted, and does not change.
8. **Idempotency** belongs to the person's object, in its context — organisation, project, environment and the
   client's key (not the API key: a rotated key repeats the same request).  The request's digest is its method, its
   path, the request as read (keys ordered, messages as they came), the model and its configuration's version.  The
   same digest gets the first answer (`Idempotent-Replayed`, uncounted) while it is kept — a day; another digest is
   refused (422 `idempotency_conflict`); a request still running is 409 `request_in_progress`, one of unknown outcome
   409 `request_outcome_unknown`; a stream is never replayed (409 `stream_replay_unavailable`), nor run again.  Only
   an idempotent request's answer is kept, for `IDEMPOTENCY_HOURS` (24) from its end; a key names its request as long
   from its admission, and a request's record is kept at least a day longer than that, whatever the two settings say.
   A released request frees its key at once.
9. **Funding**: `FUNDING_POLICY = daily_allowance` (the default) spends no credit; `credits` charges a live key's price
   as well — the allowance applies either way, so no setting reverts admission to what it was.  The organisation's own
   test allowance is gone: a test key's real calls are the person's, as a live key's are.  Balances and the ledger stay.

### The models

10. **The private gateway** (`taochronos-models`, `rust/platform/models`): no route, no workers.dev or preview address;
    the API's service binding `MODEL_GATEWAY` is the only way to it.  It holds `MINIMAX_API_KEY` (and `OPENAI_API_KEY`)
    and nothing of a developer's: the API sends it the request as read, never the API key, a cookie or a header of the
    caller's — the end-to-end run checks that nothing of a developer's ever reaches the stand-in provider.  It asks the
    provider **once** (no retry, no second place: a second ask after an ambiguous first is a second answer paid for),
    over https only, following no redirect, and says whether the provider took the request (`X-Tao-Executed`).
11. **Tao-R1** is offered at launch, as the website's relay offers it: MiniMax-M3 on MiniMax's mainland platform with
    the relay's own key (`GATEWAY_MINIMAX_API_KEY` and `GATEWAY_MINIMAX_BASE` take an international key and
    `https://api.minimax.io/v1` instead, for a deployment serving Singapore and the other international regions first).
    `gpt-6-luna` is known and not offered (`MODELS`): OpenAI refuses calls from some of the places a Worker runs, which
    the relay works around by placing its calls, and the gateway does not yet.  `MODEL_API`: `on`, `pilot` (the
    organisations the owner lets in), `off`.
12. **A documented subset of Chat Completions, read strictly** (`core/src/models.rs`): `model`, `messages` (system,
    user, assistant, tool; text or text parts; tool calls and their answers; a reasoning model's `reasoning_details`
    given back), `stream` and `stream_options.include_usage`, one output limit (`max_tokens` or
    `max_completion_tokens`), `temperature` in the model's own range (Tao-R1: 0 to 1, 0 asked of MiniMax as the least
    it takes; a reasoning model that takes none refuses it), `top_p`, `stop`, `tools`, `tool_choice`, `n` of 1.
    Anything else is refused, not ignored: 64 messages, 32 tools, a 64 KiB body — except the protocol's fields an SDK
    writes empty into an answer's message it gives back (`refusal`, `annotations`, `audio`, `function_call`), which
    are taken empty and not sent on.  Output tokens: 4,096 unless asked, 8,192 at the most — not the proposal's 2,048
    and 4,096, because Tao-R1's reasoning counts against the limit and would leave little of an answer.
13. **Answers passed on by the protocol's fields alone**, on each parsed event: the top-level `model` (the public id)
    and `id` (the API's request id); of an answer, its choices, of a choice its message or delta, of those their role,
    text, tool calls (their id, type, function's name and arguments) and reasoning, of the usage its three counts —
    what a developer's next request may give back, and nothing else: a provider's own keys, at any depth (`base_resp`,
    the `*_sensitive` ones, `system_fingerprint`, a message's `name`, `reasoning_content`, `audio_content`, its usage's
    details…), would name it, and be refused when given back.  The reasoning's format names are renamed (`MiniMax-` →
    `Tao-`, and back in what a caller gives back).  A tool call's arguments, and everything a model wrote, pass byte for
    byte — the relay's text-wide regular expressions are not used.
14. **Streams**, read by a bounded incremental parser (CRLF, LF and CR, a CR's LF in the next chunk however many empty
    chunks come between; a byte order mark the stream begins with; a character's bytes split between chunks; an
    event's lines joined; 64 KiB an event, 1 MiB an answer; nothing after `[DONE]`): the gateway enforces the deadlines
    — the first event (30 s from when the provider was asked, headers or no headers), the silence between two (30 s),
    the whole (180 s) — and writes its usage and its end as SSE comments (`: tao {…}`) which the API reads and never
    passes on; a usage event a caller did not ask for is read and dropped.  What the provider sends is read through,
    never whole and then measured: a whole answer past 1 MiB, or past the whole's deadline, is cut there, and of a
    refusal its first 16 KiB within five seconds are read for its code — a long one, or one in Chinese, cannot hold the
    gateway, nor stop it (a byte offset in the middle of a character once did).  The API watches the stream as it
    passes and tells its end — once — from the runtime's own `waitUntil`, given a promise of the task (workers-rs's
    wrapper cannot outlive the handler: Context).  A caller who leaves while the answer arrives is noticed at the next
    write: the gateway's call is aborted, and with it the provider's (`request_signal_passthrough`), and the request is
    recorded as cancelled — counted.  A caller who reads too slowly for the gateway's own deadlines to be reached is
    ended by the API's: past the whole's time and twenty seconds, the gateway's call is aborted and the end told then,
    before the request's lease could lapse.
15. **What a person and the owner see**: `GET /v1/limits` adds `user_quota` (limit, used, in flight, remaining, UTC,
    reset) and `funding`; every execution's answer carries `X-Tao-Quota-Limit`, `-Remaining`, `-Reset`; a spent
    allowance is 429 `daily_quota_exceeded` with `Retry-After` to midnight, apart from the key's own `rate` and
    `concurrency` and the person's `user_concurrency`.  `GET /v1/requests/{id}` gives a request's record to its owner's
    keys of its organisation that may read usage (`usage:read`; seven days: `REQUEST_RECORD_DAYS`).  The console shows the allowance, the person's latest
    requests (outcome, counted, tokens or *unknown*), each key's owner, and the account's id.

### Tests

16. 66 core tests natively (the allowance: five then none until midnight, a new day, concurrency, unknown after the
    lease and a late release that takes nothing back, replay and conflict, streams not replayed, release, suspension,
    pruning — of a request never ended among them; the accounts: owners, members, a role changed under a suspension,
    a key its maker owns, scopes, the model gate, funding, a schema-1 object migrated three times, the second cut
    short; the models: the subset, an SDK's message given back, temperatures, the hash, the providers' terms, answers
    by the protocol's fields at every depth, a stream cut at every byte, with a byte order mark and empty chunks; the
    corpus's answers, ran and unsent).  The API and the gateway as built, in local workerd beside a stand-in corpus and
    a stand-in provider (`cloud/api/test`): the five shared across products, keys and organisations, what counts and
    what does not, streams in pieces of one to seven bytes, tool calls, reasoning, the provider's refusals (one long
    and in Chinese), a slow start, late headers and a stall, a dropped connection and a trickled refusal, a byte order
    mark and words after the end, a caller who leaves, a tool that failed and a corpus that went away, idempotency,
    members and people suspended, the record and its scope, and no credential reaching the provider.  The runtime's
    word whether a tool ran (pytest), the corpus Worker's unsent answers (node).  The console in Chromium (27 checks)
    and its key spent against the person's allowance.

    A security review of the change, by an agent apart from its author, found no way past five a day — admissions for
    a person are one at a time in one object, a repeat runs nothing, every key, project, organisation, environment and
    model counts in the one object — and found the ways a request could be released after it may have run (a gateway
    that failed, a connection the provider dropped, a tool that failed while it ran, a corpus that went away), a panic
    on a long Chinese refusal that took the gateway's shared instance down with other people's requests, unbounded
    reads, a suspension lifted by a role change, a late release that took a count back, records never ended never
    pruned, the first event's deadline given twice, fields of the provider's passed on at depth, and the stream
    parser's three edge cases.  Each is fixed as written above, with its test.

## Where this departs from the proposal

* **No call to the identity object per execution** (2): the members are vouched for to each organisation's object.
* **No reserved state, no fence** (6): the lease first, then one admission that counts.
* **A provider's or the corpus's outright refusal counts nothing** (7), and only when it is said: what may have run
  counts.
* **`MODEL_API = on`** at deployment, not `off` then a pilot: the owner asked for the relay; `pilot` and `off` remain.
* **The organisation's test allowance is gone** (9), as the proposal's shared allowance implies.
* **Output limits per model, 4,096 and 8,192** (12).
* **No compatibility date change**: the gateway sets `enable_request_signal` and `request_signal_passthrough`; the API
  aborts its own call to the gateway when its caller leaves.

## Not done here

1. **The website's relay** keeps its own limits for anonymous visitors: one allowance for both needs the site's
   visitors signed in as the same people (ADR 0023's first item).
2. **A person's own end users**: a shared application key spends its owner's allowance; an allowance for each end user
   needs a verified identity for each, not a field a client sets.
3. **Exact token accounting**: the provider's reported usage is recorded (or *unknown*); no tokenizer estimates it.
4. **gpt-6-luna**, once its calls are placed where OpenAI serves (above).
5. **A person disabled from the console**, and members invited there: today the owner's endpoints suspend; the
   console's people are each their own organisation's owner.

## Consequences

* On deployment (the platform workflow: the gateway, then the API, then the console) every organisation's object is
  migrated at its next call.  Evidence search and citation verification become part of the five a day of the key's
  owner, and spend no credit; balances stay for a credits policy later.  A key the owner's token made before the
  change is refused (`user_binding_required`) until the owner gives it to a member.
* `api.impf.ai` answers `POST /v1/chat/completions` with Tao-R1 for every key that names `chat:completions` — new
  console keys do; a key's scopes are fixed when it is made, so an earlier key's owner makes a new one.
* What is kept of a person, beyond ADR 0038's: their requests' records for seven days (product, model, outcome,
  counted, tokens — no prompt, no answer), and an idempotent request's answer for a day.
