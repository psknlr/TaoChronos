# ADR 0035 — The activity ledger: every request written down for a visitor who is nobody; a question is a turn

**Status:** accepted · 2026-11-25 · amends [ADR 0018](0018-sentinel-and-edge-rules.md) (what the Workers keep of a
request), [ADR 0012](0012-default-service-relay.md) (what a question is) and [ADR 0023](0023-workers-paid.md) (the
archive takes batches; of its "sessions in place of addresses", the signed identity, not the limits)

## Context

A proposal of 2026-11-25, *Comprehensive User Activity Logging and Persistent Analytics*, asked that the Workers record
"all legitimate users, not only suspicious visitors": lifetime unique visitors and daily, weekly and monthly active ones,
complete page and API histories, "browser and network fingerprint analysis", every question including those nobody
agreed to have archived, model invocations with their tokens and tools, retention, sessions and geography — in a *User
Activity Ledger* beside the sentinel, with D1 as a visitor registry, R2 as an event archive, and daily reports in this
repository.

Its premise is right.  The sentinel keeps a request whole only from `FLAG_SCORE` up; a page's own request leaves a
count.  The usage counts ([`security/usage.js`](../../security/usage.js)) know a visitor by a hash of the address and
forget it after two days: they can say how many *visitor-days* a month had, not how many visitors, nor who came back.
Nothing counts a question asked of a visitor's own model, because nothing of it passes a server of ours.

Read against the code, three things were worse than the proposal knew, and one thing it asked for would have undone
what the site says of itself:

* **A question was not counted as a question.**  The relay took "a call that ends with a user's message" for one.  The
  self-check's note (`［自查：…］`), the note that asks an answer cut at the output limit to be written on, and the same
  call made again after a failure all end with a user's message: each was a question more.  In the records that carry
  timings (490 turns of the default service), a turn's first call was made again 315 times — 249 of them after a 429,
  which a record does not tell the model service's from the relay's own (only the first is a call the relay had let
  through), and at least 13 after a failure the relay can only answer once it has (502, 504, a reply that did not come
  whole); five turns were asked for a rewrite or written on.  The counts of 提问 so far are too high by something
  between 4% and 65% of those turns, and nobody can now say where in between.
* **A page a returning reader opens was not counted.**  The browser holds the page and asks whether it changed; the
  answer is 304, and only a 200 was a page opened.
* **The edge's own counts were of a window, not of a day.**  `security/events.py` asks in windows of four hours, kept a
  group's first window as its day, and judged "three hundred requests in a day" by one window.
* **The proposed event** carried a visitor's persistent id beside `conversation_id` and `turn_id` — the ids a
  conversation record carries in clear.  Whoever held both would read which visitor asked what, across every
  conversation that visitor ever agreed to have recorded.  The records carry no address so that they cannot be put to a
  person ([ADR 0012](0012-default-service-relay.md)); a pseudonym that outlives them all is worse than an address.

## Decision

### The ledger

1. **Apart from the sentinel, and off until the owner switches it on.**  [`security/ledger.js`](../../security/ledger.js)
   (the event, the outbox, the drain), [`security/ledger-d1.js`](../../security/ledger-d1.js) (the registry) and
   [`security/visitor.js`](../../security/visitor.js) (who a browser is).  The sentinel still scores, flags and refuses,
   and still alone holds an address; the ledger holds none and decides nothing.  `FLAG_SCORE` is not touched.  Without
   the secret `ACTIVITY_KEY` and the D1 database the deployment then binds, both Workers are what they were — no cookie,
   no event, no endpoint.  A ledger that fails is never in an answer's way: it is counted, not thrown.
2. **An event** is one line of what happened: `page_view`, `page_ready`, `api_read`, `api_call`, `research_started`,
   `question_submitted`, `model_invocation`, `model_settled`, `model_refused`, `turn_finished`, `record_archived`,
   `feedback_submitted`, `sponsor_submitted`, `visitor_choice`, and `request` for anything else a Worker answered.  It
   keeps: when, the host and the site's own route, the method, the status, how long; **four words of a browser** (its
   family, its system, phone or desktop, its language) and **what Cloudflare says of the network** (country, first-level
   region, network number, protocol, TLS version); what the sentinel made of it in three words (`traffic_class`,
   `risk_score`, `security_action`); and a visitor's id.  Never the address, the agent string, a version, the client
   hints, the handshake, a path that is not the site's own, a query, the id of a research run, or anything a visitor
   wrote.  A request another site's page made a browser send is counted with its country and nothing else of who sent
   it; what the sentinel flagged is counted, classed, and for no visitor.
3. **The Durable Objects are the outbox** — the site's `Watch`, the relay's `Limiter`, each beside what it already keeps.
   An event is in its SQLite under an id that makes a second writing a no-op.  One alarm drains it: into the registry
   (D1, both Workers the same database) and, where the Worker has the archive's bucket, into R2 — an hour an object,
   gzip, once the hour is over (`activity-logs/<site|relay>/YYYY/MM/DD/HH.jsonl.gz`), with a manifest a day that says
   what each object must hash to.  A row goes once both have it.  With 200,000 waiting, a new event is dropped **and
   counted**: what the counts then lack is known exactly.
4. **Written to be written twice.**  An outbox is drained at least once, and two of them write to one database in no
   order.  Every insert is by its id; every update sets a value; every sum — a visitor's day, a visit, a question's
   calls and tokens, a day's metrics — is made again from the rows it is a sum of.  The tests apply the same batches
   twice and in another order and compare the tables.

### A visitor

5. **A visitor is a browser, and is nobody.**  The site's Worker sets a cookie on a page a browser opens:
   `__Host-tcv`, 128 random bits, signed, `HttpOnly` (no script reads it), host-only (it goes to chat.impf.ai and to no
   other impf.ai host), good for **thirteen months from the day it was issued** — a visit does not extend it.  The
   ledger keeps `v_` + an HMAC of it: whoever reads the ledger cannot make a cookie, and whoever holds a cookie cannot
   find its rows without the key.  The relay is another host, so the page asks its own (`POST /api/activity/hello`) for
   a day's signed **pass** and shows it to the relay (`X-Tao-Visitor`).  **No fingerprint**: an address, a canvas or a
   font list tells people apart who did not agree to it; a cookie is theirs to delete.
6. **Who gets none.**  A browser that asks not to be tracked (`Sec-GPC`, `DNT`); a visitor who switched the count off
   under 设置 → 数据 → 访问统计 (the cookie then says `off`, and nothing more); anything that is not a browser; a request
   another site's page caused.  What they do is counted without a visitor.  The same pane shows a visitor their id and
   **deletes everything held under it** (`POST /api/activity/forget`): their row, their days and their visits go, their
   events stay as no one's, and the deletion is written down without the id.  `ACTIVITY_IDS` chooses: `notice` (the
   default: an id unless declined), `optin` (only once switched on), `off` (no ids at all).
7. **An id counts as a visitor once a browser has brought it back.**  One given out and never seen again — a crawler's,
   a browser's that keeps no cookies — is a page opened, not a visitor, or every page such a browser opens would be a
   new one.
8. **A stretch's visitors are the union of its days'.**  The registry keeps a row a visitor a day; a week's, a month's
   or all time's visitors are `COUNT(DISTINCT …)` over the stretch, never the days added up.  The active visitors of the
   seven and thirty days ending with a day are kept with that day.

### A question

9. **A question is a turn, not a call.**  The page names each turn (`X-Tao-Turn`, its answer's message id) on every
   call the relay makes for it — for every model now, not only the one limited in questions — and the turn's first
   call is the question, whatever the later ones end with ([`relay/src/gate.js`](../../relay/src/gate.js)).  This
   corrects the usage counts whether or not there is a ledger.  A page that names no turn (a tab open since before) is
   counted by what was last asked, per caller and day.
10. **Every question, whoever answered it.**  The relay's own (`basis: relay`, seen by the relay, with each model call:
    how it ended, its tokens, how often the model service was asked, how long it took to begin).  A visitor's own
    model's or the page's own reply (`basis: client`): the page tells the relay the turn's end in counts — how it
    ended, its rounds, its tools by the site's names, its tokens (`POST /v1/activity`) — and never the question, the
    answer, a tool's arguments, a key, or the name of an endpoint or model the visitor set by hand.  A turn only its
    record tells of (`basis: record`: a page older than this).  **Unrecorded = all − recorded**, the recorded being the
    turns whose record the relay took in.
11. **The ledger cannot say who asked what.**  No conversation id is kept.  The page's name of a turn is in no event:
    the relay's object remembers a keyed digest of it for a week — so that a turn's calls, its end and its record find
    each other — in a table that is in no export, and the events carry an id of the ledger's own making.  A record's
    event names no visitor.  A turn that touches the visitor's own health or data (a diet conversation, 我的资料) is
    counted and for no one: the page sends no pass with it, and the relay drops one that came.  The archive names a
    visitor by the day (an HMAC of the id and the day): it counts a day's visitors and cannot follow one to the next.

### What is read of it

12. **The counts are the owner's alone.**  No page of the site shows them — not a pane under 设置, not a visitor their
    own visits.  Every endpoint that answers with counts (`/api/activity/stats`, `/api/stats`, `/v1/stats`, and the
    pipeline's `health` and `archive`) answers the collector's token alone (`LOG_EXPORT_TOKEN`), with no CORS headers,
    and says even that there is nothing to count only to the token's holder; the relay's CORS no longer allows an
    `Authorization` header from a page.  The owner reads them where only the owner's accounts reach: the reports below,
    with [`data/activity-analytics/SUMMARY.md`](../../data/activity-analytics/SUMMARY.md) and each run's summary page
    as their readable face, in this private repository; and the registry itself in Cloudflare's D1 console, for any
    question the reports do not answer ([security/README.md](../../security/README.md), 活动账本 → 日常).  An earlier
    draft of this decision had a 统计 pane opened with `STATS_TOKEN`, or with `STATS_PUBLIC` to everyone: a key
    typed into a page lives in that browser, and a page that can show the counts can be made to show them to someone
    else.
13. **The reports** ([`security/activity.py`](../../security/activity.py), `.github/workflows/activity.yml`,
    [`data/activity-analytics/`](../../data/activity-analytics/README.md)): a file a day, a week, a month, a year, and
    the lifetime — sums only, a place or a referring site with fewer than three visitors folded into the rest; the
    periods asked of the registry as wholes.  The same run checks the pipeline — an outbox nothing drains, events
    dropped or lost since the last look, yesterday's archive against its manifest, the count of visitors there ever
    were (it never falls) — and fails when something is wrong, after it has committed.
14. **The days before the ledger** are told from what was kept of them: the Workers' daily counts and the records
    committed here.  Run on the records as they stand: 57 days from 2026-09-28, 1,368 recorded questions, 8,463 model
    calls, 333 million tokens in and 8.8 million out, 20,429 tool calls.  The visitors of those days are given as the two
    numbers they lie between — the busiest day's, and every day's added up: the keys that could have said were deleted
    two days after each.
15. **The edge** ([`security/events.py`](../../security/events.py)): a group is counted over the whole day; a day pulled
    again takes the larger count of each line; and, where the zone offers it, every request of the day by host, country
    and status (`kind: traffic`) — what a Worker saw and what it never did — with no address, path or agent.
16. **A page the browser holds and asks about (304) is a page opened**, for the ledger and for the daily counts.

## Where this departs from the proposal

* **No fingerprint analysis of visitors** (its section 1; its own section 9 says as much).  The handshake, the client
  hints and the agent string stay with the sentinel's events of what it flags.
* **`conversation_id` is not kept, `turn_id` is the ledger's own**, and the turn's record is matched in the relay's
  object, not by an id anyone can join on (11).  The counts the proposal wanted from them come out the same.
* **`session_id` is not carried by the events.**  A visit is made in the registry from a visitor's events (no gap over
  30 minutes, within a day): a session cookie would be a second identifier, two Workers would each have made their own,
  and a sum made again from its rows survives a batch that comes twice.
* **`account_id`**: there are no accounts.  Counting one person on two devices as one needs them, and nothing else does.
* **Not every request a row.**  A reader's like reads of a minute are one line with their number (an answer that cites
  sixty passages reads sixty); what is not a visitor's — a scanner's knocks, a crawler — is added up by the minute.
* **The persistent id is in D1 alone.**  R2 holds a visitor's day under a name that changes with the day; forgetting a
  visitor is then a deletion in one place, and a bucket that leaked could not be made into anyone's history.
* **"Lifetime" has an edge.**  An id lasts thirteen months, so the same browser is a new visitor after that; a visitor
  not seen for twenty-five months is deleted and counted as having been.  Both are the price of not keeping a pseudonym
  for good, and both numbers are configuration.
* **Reports in the repository are folded** below three visitors a place; the proposal's "anonymized" needs a rule.

## Not done here

* **Asking first.**  The default is `notice`: an id unless the browser declines or the visitor switches it off, said in
  设置 → 数据 and in 关于.  It keeps to the conditions under which the French regulator (CNIL) exempts a site's own
  audience measurement from prior consent — a cookie of thirteen months at most, read by no other site and used for
  nothing else, its rows kept twenty-five months at most, said plainly and with a way to object.  Whether that is
  enough for every reader's jurisdiction (China's PIPL asks for consent where no other ground applies) is the owner's
  judgement, with advice, and not an engineering one.  `ACTIVITY_IDS = "optin"` is the other answer, at the price of
  counting almost nobody.
* **Limits by visitor** ([ADR 0023](0023-workers-paid.md), not done 1).  The id says who to count, not who to trust: a
  client that keeps no cookie has no id, and limits stay by address.
* **The relay's refusals of another site's requests** are in Workers Logs as before and in no event: a round trip to
  the object for each would let any page spend the object's requests.  The site's are counted (it holds them a moment
  and sends them together).
* **A reply the visitor left before its end** tells nobody how it ended: its call stays `open`, with no tokens.
* **The mirror's visitors** (GitHub Pages) have no site behind the page: their turns are counted without a visitor.
* **A lifecycle rule on the bucket.**  How long the archive's objects are kept is a policy; nothing sets it.  With the
  day's names in them, 400 days is a reasonable one.
* **Matching the ledger's recorded questions to the records line by line.**  By design there is nothing to match on;
  the counts of a week can be compared.
* **What was never kept**: the visitors, visits and unrecorded questions of the days before the ledger.

## Consequences

* The owner can say how many different visitors a stretch had, who came back, how many questions were asked and how
  many of them nobody agreed to record, what each model cost, and what the site's tools are used for — and cannot say
  who anyone was or what anyone asked.
* **The counts of 提问 fall** to what they should have been, and those of 页面访问 rise by the pages returning readers
  opened.  The older numbers stay as they were written.
* A visitor finds a new field under 设置 → 数据 (访问统计: the switch, their id, the deletion) and a sentence more in 关于
  — once the site has a ledger, and not before — and no count of anyone's, their own included.
* Cost, on Workers Paid: one object request for the events of two seconds of an instance and one a drain; D1 rows
  written per event and read per sum (thousands a day at this site's size, against 25 billion read and 50 million
  written a month included); with the archive, an object an hour a Worker.
* **For the owner, to switch it on**:
  1. Create the repository secret **`ACTIVITY_KEY`** (`openssl rand -hex 32`).  It must stay what it is: with another
     key every browser is a new visitor, and the ledger's history breaks there.
  2. The deploy token needs Account → D1 → Edit (it has it if the D1 backup is in use).  Run the **relay** and **site**
     workflows: each makes or finds the database `taochronos-activity`, binds it, and gives its Worker the key.
  3. Run **security → Run workflow** (`plan`, then `apply`): rule 3 now also holds `POST /v1/activity` to the page's
     origins.
  4. The **activity** workflow reports each night with the collector's token; run it once by hand with `backfill`
     ticked to write the days before from the Workers' daily counts.  Read `data/activity-analytics/SUMMARY.md`; delete
     the secret `STATS_TOKEN` if it is still set, from the repository and from both Workers: nothing reads it now.
  5. Optional: `ARCHIVE_BUCKET` ([ADR 0023](0023-workers-paid.md)) also archives the ledger's events.  It is the same
     switch that moves the conversation records and the sentinel's events from the repository to the bucket.
* Rollback, each one line: `ACTIVITY = "off"` in both `wrangler.toml` stops the ledger and the cookie (a browser's
  cookie lapses unread); `ACTIVITY_IDS = "off"` keeps the counts and gives nobody an id.  The turn's name stays either
  way: it is what makes a question one.
