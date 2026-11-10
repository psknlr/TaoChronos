# ADR 0033 — The model is asked from more than one place: why it was asked again so often, and what ends it

**Status:** accepted · 2026-11-10 · refines [ADR 0032](0032-a-turn-that-waits-says-so-and-waits-less.md), [ADR 0012](0012-default-service-relay.md)

## Context

After [ADR 0032](0032-a-turn-that-waits-says-so-and-waits-less.md) the page says when it asks the model again
(正在重新请求模型（第 n 次重试）…), and IMPF-AI saw how often it does.  The turns' records (`data/chat-logs/`, 270 turns on
the default service from 2026-10-20 to the morning of 11-10, 2,280 model requests; the collector had not yet run after
that day's deployment) were read for every request that was asked again, and for what came before it.

**How often, and after what.**  469 requests — one in five — were a round asked again after a failure:

| what came before | asked again | |
|---|---|---|
| the model service answered 429 | 233 | 4–8 November only |
| its own 5xx, 40–60 s after the request | 89 | |
| the connection lost before a byte | 44 | |
| nothing for the page's 120 s | 38 | |
| the connection cut mid-reply | 21 | |
| the second model refused the region | 40 | (a page before it stopped asking again for that) |
| other | 4 | |

**What it is not.**

- *Not our own traffic.*  A rate limit fails the request that follows many; here the request that follows none fails.
  Outside 4–8 November, with nothing asked in the minute before, 24% did not begin; with four or more asked, under 1%;
  no 429 at all.
- *Not the page being hidden.*  44% of the requests that got the service's own 5xx were asked while the page was hidden,
  and a 5xx is an answer the relay received: that is how often a page is hidden, not a cause.
- *Not the browser's connection, nor the relay's code.*  From the same page and the same browsers, in the same weeks:
  209 requests straight to DeepSeek and 165 to GPT-6 Luna through this relay (and a placed object) — not one silent,
  lost, cut or answered 5xx.  To the default model: 204 of 1,633.
- *Not the model service being down.*  Within two minutes of a request that did not begin, other visitors' requests
  failed 2 times in 29 — as at any other time (27 in 721).

**What it is.**  Requests that do not begin are one visitor's for a while, not everyone's: 69 of 105 conversations had
none, and five had 64 of the 182 (16 of 25, 15 of 26, 13 of 29 requests of a turn).  They are more of the evening in
Beijing (20% from 18 to 24 h, 6–11% by day, 0–3% at night), more after an idle gap and more for a longer request (2–3%
within 5 s of the request before; after 5–15 s, 3% for a request under 25,000 tokens and 9% for one over 50,000; after
15–30 s, 6% and 20%).  A request asked again at once failed again one time in three.

And the place explains it.  The relay is a Worker: it runs at the Cloudflare location the visitor reached, and calls
the model service from there.  The sentinel's events hold 1,829 requests from browsers in mainland China: 56% reached
Cloudflare in North America (Seattle, San Jose, Los Angeles), 44% in Europe (Amsterdam, London, Frankfurt), and 8 — six
visitors — in East Asia.  The model service is in mainland China.  So a visitor's request left China for Amsterdam and
was sent back into China from Amsterdam, on Amsterdam's own path — worst in the Chinese evening, worse for a large
request after an idle connection, bad for one location while another's is fine.  The second model never showed it
because its calls are already made from a place chosen for them (the `Egress` object, [ADR 0023](0023-workers-paid.md)).

The 429s of 4–8 November fit the same reading, not a spent balance: the first request of a conversation was refused
five times in six, a request asked again after a refusal every time, and a request that followed one that had answered
once in a hundred — at gaps up to two minutes.  A balance does not let follow-ups through; a limit on an address shared
with everyone else who calls the service from that Cloudflare location, counted on new connections, would.

## Decision

1. **The default model is asked from more than one place** (`relay/src/relay.js`, `reach`; `UPSTREAM_VIA = "direct,apac"`).
   "direct" is where the Worker runs; any other name is a Durable Object location hint, and an object placed there makes
   the call (`Egress`, now for both models' hosts and no other: `placedFetch`).
2. **An ask that is silent is joined, not replaced** (`UPSTREAM_HEDGE_SECONDS = "12"`).  After 12 s without a byte the
   next place is asked too; the first to answer is the reply, the other is dropped.  A request stuck on one place's
   path costs the 12 s, not 30 s or the page's two minutes; one that is only slow is not thrown away.  92% of the
   requests that answered had begun within 12 s, so about one request in thirteen is asked twice.
3. **A place that just failed is asked last** (`deps.routes`, the instance's memory).  Silent at the join, failed or
   refused, a place is put last for five minutes — a minute for a refusal — twice as long each time it does so again,
   half an hour at most, and forgotten when it answers.  A visitor on a bad path waits the 12 s once, not at every
   request of the turn.
4. **A refusal that may be one place's is asked about at another, once.**  A 429 or a 403 is kept while a place not yet
   asked — and not itself just seen refusing — is asked; the service's own word (a key, a parameter) is the answer at
   once.  A place's own refusal while another place gave no answer at all does not speak for the service: the page is
   told it did not answer, and asks again.
5. **Every reply says how it came** (`X-Tao-Asks`, `X-Tao-Via`), and the turn's record keeps it (`requests[].asks`,
   `.via`).  `taochronos records` counts it (`asked_again`): how often the page asked again, how often the service
   needed one ask, and which place answered.  `GET /v1/egress` shows whether the model service's host answers from each
   place, and how soon.  The Worker's log says where an ask was silent (`… via direct at AMS: joined`).

The first place stays "direct": that path is the one known to work nine times in ten, and the path from an object in
East Asia has not carried a request yet.  Once the records show it answering, `UPSTREAM_VIA = "apac,direct"` makes it
the first — one line.

**Set aside.**  *Asking again sooner without a second place*: the same path fails again one time in three.  *Keeping
the connection to the model service warm*: a Worker has no connection of its own to keep.  *Answering the page at once
and sending it heartbeats while the service is asked*: with the wait cut to seconds, the browser's own patience is no
longer reached; and every refusal would then travel inside a stream that pages already open do not read.  *A table of
which Cloudflare locations are near the service*: the relay finds out by asking.

## Consequences

| a request whose first ask does not begin | before ADR 0032 | with ADR 0032 | now |
|---|---|---|---|
| the visitor waits | 53 s to the 5xx, or the page's 120 s; then the page's pause | 30 s, then the same place again | 12 s, then another place answers |
| the next request of the same turn | the same again (a third of the time) | the same | asks the place that answered first |
| asks the visitor is counted for | 2 or more | 1 | 1 |
| said to the page when no place answers | — | after 90 s | after 54 s at most |

What it costs: about one request in thirteen is asked of the model service twice (the second ended when the first
answers; whether the service charges for a request ended before it began to answer is its own rule), and each call made
through the placed object keeps that object busy for as long as the reply streams.

What it does not change: a reply cut off mid-way (21 in the records) is still asked again by the page — nothing of it
can be taken up elsewhere once part has been sent; and the model service's own quota is still its own.

Verified beside the tests: the Worker as `wrangler` bundles it, run in the Workers runtime on this machine with the model
service stood in for (its first ask never answering): the placed object's ask answered through the `EGRESS` binding and
streamed back (2 asks, `via: apac`), the next request asked that place first, nothing but the key and the content
headers reached the service, and silent everywhere the page was told after three asks.

Not verified: none of this has run on Cloudflare.  Whether an object in East Asia reaches the model service, and how
well, shows in `GET /v1/egress` at once (the relay's deployment prints it) and in the records' `via` within days.  And a
visitor who leaves: the relay stops asking when Cloudflare tells it so (`request.signal`, the Worker's
`enable_request_signal` flag, as before) — the local runtime did not tell it, and it then made its three asks, which is
the most it ever makes for one request.

Tests: `relay/test/relay.test.js` (a silent ask joined and the place remembered, a slow place not thrown away, a failure
asked at the next place, a place's refusal and the service's, the placed object's hosts, headers and its own wait, the
record's fields), `tests/test_chat_records.py` (`asked_again`), `tests/test_web_client.py` (what the page keeps of how a
reply came).
