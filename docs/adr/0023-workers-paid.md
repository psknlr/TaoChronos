# ADR 0023 — Workers Paid: refusals that say so, paid work checked first, records out of the repository

**Status:** accepted · 2026-10-14 · amends [ADR 0018](0018-sentinel-and-edge-rules.md) (how the site answers a refusal,
and what it does when its sentinel cannot be asked) and [ADR 0012](0012-default-service-relay.md) (where the
conversation records go)

## Context

The account moves to Workers Paid.  Several of the Workers' choices were made for the Free plan's daily allowances,
which were the account's for the day and stopped everything when spent:

* the site's API **fails open** when its `Watch` object cannot be asked (on the Free plan, a spent allowance would
  otherwise have turned every call away), and a quiet reader is answered from the instance's memory for a minute;
* the site answers a refusal — an address the sentinel refuses, a day's reads spent — **as a 503**, so that the page
  falls back on the browser rather than show a passage as missing;
* the relay's book keeps at most `LOG_KEEP` records and **drops the oldest** to make room;
* the records and the sentinels' events are **committed to this repository** every hour, where a visitor's
  conversation stays in the history for good.

On Workers Paid, Durable Object requests have no daily cap (use beyond the allowance is billed) and R2 is at hand.  An
upgrade strategy written for the owner proposed reorganising the Workers around security enforcement, consent-based
archiving and corpus retrieval.  Read against the code, it is right that a refusal must not look like an outage, that
work the account pays for must not start unchecked, that accepted records must not be dropped silently, and that a
repository is the wrong place for records that may have to be deleted.  Some of its premises do not hold here: the
browser's fallback runs the page's own public files and is no way round a refusal; a conversation that touched the
user's own data is already never recorded, whole ([ADR 0022](0022-the-users-own-data.md), 6) — stricter than the
turn-by-turn lineage it asks for; and the relay already reserves a call's tokens before it goes out and refuses a call
it cannot count ([ADR 0018](0018-sentinel-and-edge-rules.md), 2 and 6).

## Decision

1. **A refusal says so.**  The site answers an address its sentinel refuses with **403** (`blocked`) and a day's reads
   or calls spent with **429** (`daily`), each with `Retry-After` and `X-TC-Corpus: refused`; **503** means only that
   the corpus cannot answer.  The page (`web/js/runtime.js`: `refusal`) takes a refusal from the site's own server
   like an outage — it carries on with the 要籍语料 in the browser, on the site's public files, and does not ask the
   server again that visit — but tells the visitor which it was.  A minute's 429 stays the call's own error, and a
   server the visitor chose has no stand-in.  A page cached from before shows the refusal's message as the tool's
   error.  The Workers' analytics and logs now tell refusals from failures.
2. **Paid work is checked first.**  On the site, a call or a research run (`POST /api/call`, `/api/research`) is refused
   with a 503 while the sentinel's object cannot be asked; reads of the public passages still go on (the rate-limit
   bindings stand).  The relay already refuses a model call it cannot count.  A scanner path noted by an instance clears
   what that instance remembered of the address, so its next read waits for the object, which refuses it.
3. **A record taken in is kept until it is collected.**  When `LOG_KEEP` records wait, the relay refuses the next one
   (503 `logs_full`, and a line `logs full` in Workers Logs, where an alert can look) instead of deleting an older one.
   The page never waits for a record, so a visitor sees nothing of it.
4. **The archive: a private R2 bucket, by the owner's choice** (`security/archive.js`).  With the repository variable
   `ARCHIVE_BUCKET` set, the deployments bind that bucket as `ARCHIVE` — only once `security/bind-archive.sh` has found
   it and found it private (no r2.dev address, no custom domain); otherwise they deploy without it, as before, and say
   why.  The Durable Objects are the outbox: a record (the relay's `LogBook`) or an event (the relay's `Limiter`, the
   site's `Watch`) is in their SQLite before its request is answered, and an alarm a moment later drains the oldest
   into the bucket, one object each under a key made of the day and the id (`chat-logs/YYYY/MM/DD/<id>.json`,
   `security-logs/<relay|site>/…`), R2 checking each body's sha256, and removes them through the last one written, never
   further.  A write repeated after a failure lands on the same object.  While a Worker has the bucket its stores have
   one collector: the repository's acknowledgement is refused (409), and `relay/collect.py` and `security/collect.py`
   take nothing from it and say so.  The owner reads a day back with the collector's token (`GET /v1/logs/archive`,
   `…/security/archive?day=`; `collect.py archive --day` writes it to `.archive/`, which git ignores).  No name, address
   or text is in a key; an object carries the conversation's random id as metadata, for a deletion to find.

## Not done here, in the order proposed

Each needs something only the owner can provide or decide (a key, a policy, an account setting), or a measurement first.

1. **Sessions in place of addresses.**  Today a visitor is an address (an IPv6 one by its /64): fifty clinicians behind
   a hospital's address share one day of 600 model calls and one sentinel score.  A Turnstile challenge when a page
   first asks (not before every call) would buy a short-lived, signed guest session; the relay's and the site's limits
   would then be per session, under a wider ceiling per network.  Needs a Turnstile site key and secret, and the page's
   Content-Security-Policy opened to `challenges.cloudflare.com`.
2. **Consent and deletion on the server.**  The consent is the browser's today, and a record carries the visitor's word
   for it; a record of the default service's own conversation is taken only from a visitor it answered lately.  With
   sessions: consent kept per session with an epoch, a receipt for each turn the relay answered (a record without one
   is marked as the client's), deletion of a conversation's objects (by the metadata written now) with a tombstone so a
   late retry cannot write it again, and an R2 lifecycle rule for the retention the owner settles on (relay/SETUP.md
   suggests 90 days; it is a policy, so nothing sets it automatically).
3. **Routing by capability between D1 and the container.**  The site sends every API request to the container whenever
   it has one.  Sending passages and the tools the D1 backup runs ([ADR 0017](0017-d1-backup.md)) to D1, and only the
   rest to the container, would let the container sleep more — but the backup's tools are ports, and an answer that
   mixes two engines unannounced is not reproducible.  First: each answer names the engine and corpus version it came
   from, and the two are compared on the evaluation set.  The container serves research from one instance (`main`):
   per-visitor jobs, isolation and durable job status come before more instances.
4. **Versioned corpus releases** into staging D1 databases, switched once verified against `cloud/store.json`'s
   counts and checksums, with the previous release kept for rollback; D1 read replicas through the Sessions API for the
   immutable corpus only.
5. **An owner's console** behind Cloudflare Access (its JWT verified, not its header trusted), read-only by default, and
   alerts on the lines the Workers already write (`logs full`, `archive … Error`, refusals, a sudden rise in tokens).
6. **The records already committed** under `data/chat-logs/` and `data/security-logs/` stay in the history; removing them
   is a separate, deliberate operation.

## Where this departs from the strategy

* **No Queue and no D1 index for the archive.**  The Durable Object's SQLite already is a durable outbox, written before
  the visitor is answered; one consumer drains it; a put under a key made of the id is idempotent.  A Queue would add a
  second copy, at-least-once redelivery to deduplicate and a 128 KB message limit, for some hundreds of records a day.
  Worth revisiting when something else must hear of each record (an index, a notification).
* **The browser's fallback stays on a refusal.**  It runs the public files any visitor downloads; refusing it would not
  protect the corpus and would cost the visitor the site.
* **Nothing changes for the user's own data.**  It is read on the user's machine and never recorded; the archive changes
  where consented records go, not which records exist.

## Consequences

* A refused visitor is told why; the owner's dashboards count refusals as 4xx and outages as 5xx.
* A failure of the site's `Watch` object now costs visitors the full corpus's tools for the visit (the page carries on in
  the browser) instead of letting calls through unchecked.
* With `ARCHIVE_BUCKET` set and both Workers deployed, the chat-logs workflow commits nothing new; a conversation record
  can be deleted (an R2 object) instead of living in the repository's history.  R2 costs little at this volume (one
  write per record or event; storage within the free 10 GB for a long while); the alarms add a Durable Object request
  per drain.
* Unsetting `ARCHIVE_BUCKET` returns the stores to the repository's collector, from its cursor: ids are never reused.
* Setup: [relay/SETUP.md](../../relay/SETUP.md) (归档).
