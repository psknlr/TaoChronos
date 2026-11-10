# ADR 0032 — A turn that waits says so, and waits less: measured first, then five changes

**Status:** accepted · 2026-11-10 · refines [ADR 0012](0012-default-service-relay.md), [ADR 0016](0016-site-and-full-corpus-on-cloudflare.md)

## Context

IMPF-AI reported that 道乃久 often stops responding after a question, or pauses for a very long time before it goes on,
and asked for it to be faster without loss of security or accuracy.  The turns' own records (`data/chat-logs/`, the
times of each model request and each call: [web.md](../web.md#道乃久默认服务--asking-without-a-key-and-conversation-records))
were read before anything was changed — 453 turns from 2026-10-20 to 11-10, 236 of them on the default service with
their times, 1,580 of its model requests answered and 535 not:

| what the records show | |
|---|---|
| turns that came whole | 56% |
| a turn on the default service, start to end | p50 231 s · p90 998 s |
| model requests of a turn that answered | 11 rounds of tools on average, 11 s each at the median, then the answer (65 s, streamed) |
| a model request that answered, sent → first byte | p50 4.1 s · p90 11 s; of the 1,215 a page watched, 2.5% over 30 s, none over 90 s |
| model requests that never began | 1 in 10: the service's own 5xx after 53 s (100), nothing for the page's 120 s (38), the connection lost before a byte (48) |
| asked again right after such a request | 44% began never, again |
| time a turn spent in requests that failed | p90 349 s |
| the model service refusing for want of quota (4–8 November) | 309 requests; 74 turns failed so, most of those asked on 4–7 November |
| a call on the site's server, beyond what the runtime says it took | p50 1.4 s (a passage read in 0 ms: 1.4 s) |
| `classics.search` on the full corpus, as the runtime times it | p50 4.3 s · p90 21 s · 14 past their two minutes |

Five things were found behind these.

1. **The relay waited for the model service as long as it took.**  It answers the page only once the service has
   answered it, so a service that hung kept the page at nothing for 53 s (its own gateway's 5xx) or for the page's whole
   120 s; the page then waited its pause and asked again, counted again by the relay's limits.
2. **Nothing on the page moved while it waited.**  The first round showed 正在思考… however long the wait; in every later
   round the steps above were done and nothing else was drawn until the reply's first part — a page that looked as if it
   had stopped, for each of a turn's eleven requests.
3. **Every call started the container again.**  The corpus Worker's object called the container library's
   start-and-wait before each forwarded call.  With the container up that is not free: a request to the container's port
   to see that it listens, and a write of the object's state under its input gate — per call.
4. **Searches asked together read each other's candidates.**  The one retriever keeps what a search reads of its
   candidates on itself while it runs (their ranks in the index, the indexes built over them), and the server runs its
   callers' calls on threads — a page sends a round's four at a time, and rounds of two to four searches are the most
   common in the records.  Of 24 searches asked four at a time on the site's pack, 15 gave other passages than the same
   search asked alone; one kept 3 of its 10, its dense route gone.  Asked one after another they were the same every time.
5. **A search's time is this module's.**  Profiled on the site's pack under the full-corpus profile, a search is Python
   from end to end, not SQLite: the per-search indexes over its candidates (`retrieval/index.py`) took 60% — every
   character tested by a regular expression of its own, every n-gram hashed anew, the index's average length summed
   again for each passage scored.  Four at once took longer than the four in turn (threads share one interpreter).

## Decision

1. **The relay bounds its wait and asks again itself** (`relay/src/relay.js`, `reach`).  A model service that sends
   nothing — no status, no header — for `UPSTREAM_FIRST_BYTE_SECONDS` (30) is given up and asked again,
   `UPSTREAM_ATTEMPTS` (3) times in all; so is one that cannot be reached, and one that answers with a failure of its own
   (5xx), after a short pause.  A refusal (a key, a region, a rate, a parameter) is the answer.  Nothing of a reply has
   gone to the visitor by then, so nothing is said twice; the visitor is counted once; the visitor leaving ends it.
   Silent every time, the page is told so (504 `upstream_timeout`) within 90 s — under its own 120 s — and asks again as
   it does after any 5xx.  A quota that is spent is told apart from a busy moment where the service says which
   (`upstream_quota`: the page does not ask again, and says so at once instead of after three tries); what the service
   asks to wait (`Retry-After`) is passed on, a minute at most; its word for a refusal goes to the Worker's log.
2. **The page says that it waits, and for how long** (`web/js/view/thread.js`, `waitNode`; `app.js`, `makeHooks`).
   From a round's request to the first part of its reply: 正在等待模型回应…, with the seconds from the third on; after
   half a minute, that the service is slow and is asked again by itself; asked again after a failure, which try it is.
   In every round, under the steps that are done.  Kept with the running turn, never with the conversation.
3. **A container that is up is asked at once** (`cloud/corpus/src/corpus.js`, `forwarded`).  The object starts the
   container, and waits for it, only when it has not itself found it listening or it no longer runs; an answer that is
   not the runtime's, or a call that fails under it, makes it find out again.
4. **What a search keeps while it runs is its thread's own** (`plugins/retrieval/hybrid.py`, `_Running`).  The ranks of
   its candidates and the indexes built over them are no longer the retriever's: a search asked while another runs
   reads only its own, and neither waits for the other.
5. **The indexes do less work for the same numbers** (`plugins/retrieval/index.py`).  The characters by one pass, an
   n-gram's hash kept once known (100,000 at most), a query's weights and the average length once per search.  The
   tokens, each passage's 512 numbers, every score and the order of the results are the plain definitions', bit for bit.

**Set aside.**  *One search at a time* (a lock around the search): it gives the same results too, and a round's four
searches finished somewhat sooner under it (threads share one interpreter, and take turns badly) — but one search that
took long would then hold up every other visitor's, and a page that waits on someone else's search is what this
decision is against.  *Asking the service twice at once* (the second ask racing the first): faster in the tail, but it doubles
the load on a service exactly when it is slow, and what it costs is the owner's to decide.  *Answering the page at once
and keeping the connection alive while the service is asked*: it would let the relay wait longer than the page does, but
every refusal would then travel inside a stream, which pages already open do not read; the bound and the page's own
words give most of it.  *Telling the model to use fewer rounds*: the rounds are where a turn's time goes (eleven
requests before the answer), but they are also how it reads before it quotes — its instructions already say that calls
that do not depend on each other may be made together, and it does (two to four a round).  *Keeping each passage's
vector between searches*: the next thing to try if searches are still slow; it costs memory in the browser's runtime too.

## Consequences

Measured after the change, beside the code before it:

| | before | after |
|---|---|---|
| a hung model request: the page learns of it | after 53 s, or its own 120 s | never, if a later ask answers (each given up at 30 s); else after 90 s |
| asks a visitor is counted for when the service hung once | 2 | 1 |
| one forwarded call, container up (the real library, a stand-in container) | a request to its port, a state write under the object's gate, then the call | the call |
| 24 searches asked four at a time, differing from the same search alone | 15 | 0 (of 48) |
| 16 searches one after another (the site's pack, full-corpus profile) | 8.4 s | 6.5 s, every result byte for byte the same |
| four searches at once | 3.4 s | 2.5 s |
| between a round's steps and the next reply, on the page | nothing | 正在等待模型回应… · 12 秒 |

Replayed on the records' own outcomes (each ask drawn from what the page-watched requests did), a 30 s bound with one
more ask brings a request's mean wait from 10.2 s to 8.2 s and the failures a page sees from 7.3% to under 1% if asks
were independent; they are not (44% after a hang), so the true figure lies between, which is why three asks and not two.

What this does not change, and is the owner's to decide:

- **The model service's quota.**  For four days of November most questions were refused for want of it.  No code
  answers a spent quota; the relay now says which it is, at once, and logs the service's word for it.
- **The container's size.**  `standard-1` is half a vCPU; a search is CPU from end to end.  A larger instance is the
  direct way to faster tools, at its price ([cloud/README.md](../../cloud/README.md)).
- **The second model's region.**  59 requests to GPT-6 Luna were refused for the region the call left from, from both
  places it is asked from (`upstream_region`); a location hint is a hint.

Tests: `relay/test/relay.test.js` (the bound, the asks, one count, the visitor leaving, the quota told apart),
`cloud/test/corpus.test.js` (`forwarded`), `tests/test_retrieval_index.py` (the plain definitions compared; a search
asked while another is held part-way, each keeping its own candidates), `tests/test_web_client.py` (`waitText` under Node; the wait in Chromium, in the
first round, a later one and after a failure).
