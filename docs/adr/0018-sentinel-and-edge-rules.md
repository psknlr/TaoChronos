# ADR 0018 — The sentinel: what the Workers record of a request, and what refuses it at the edge

**Status:** accepted · 2026-10-05 · amended by [ADR 0023](0023-workers-paid.md): the site answers a refusal as 403 or
429 (not 503), and refuses calls while its object cannot be asked

## Context

In the first week on Cloudflare the zone saw what every public host sees: probes for `/wp-config.php` and its backups,
`/.git/HEAD`, `/wp-json/batch/v1`, a Worker's own `/js/worker.js` fetched by `Python-urllib`; agents naming themselves
`Go-http-client`, `python-requests`, or a known crawler (`ChatGPT-User`, `PerplexityBot`) while probing paths no crawler
asks for; a dozen source addresses, most in hosting networks.  Cloudflare's managed rules refused them all.  Nothing of
this reached the Workers — and little of it was kept: the Free plan keeps security events for a month, sampled and
without an export; the Workers saw neither the probes nor what a client that passed the edge was like.

The two Workers protect what matters by other means ([ADR 0012](0012-default-service-relay.md), [ADR 0016](0016-site-and-full-corpus-on-cloudflare.md)):
the relay's key never leaves it, calls are counted per visitor, origins are checked, the site's API is a short allow-list
behind rate limits.  What they could not do was *see*: tell the page's own request from a script that pasted the page's
origin in, notice a scraper paging through `/api/passage`, keep the characteristics of whoever tried, or bound a visitor's
cost by what the answers actually cost rather than by how many were asked for.

## Decision

1. **One sentinel for both Workers** (`security/sentinel.js`, imported by `relay/` and `cloud/site/`; tested under Node).
   Every request is reduced to a *fingerprint* — what the edge knows (address, network, country, location, protocol,
   TLS version and ClientHello traits) and the headers a browser sends with a fetch (`Sec-Fetch-*`, `Sec-CH-UA`,
   `Accept-Language`, `Origin`, the referer's origin) — and *assessed*: a score with named reasons, from this one request
   (an automation agent, a crawler's name without verification, a browser's name without a browser's headers, an old
   protocol or TLS, a hosting network, a foreign origin, a traversal in the path) and, for the relay's model calls, from
   the body's shape against the page's (a system prompt first, tools, a stream with usage, `max_completion_tokens`;
   hashes of the system prompt and the question, never their text).
2. **Memory in the Durable Objects the Workers already have.**  `WatchCore` keeps, per visitor, a row (counts, agents,
   probed paths, networks, the block) and the last ten minutes in memory (bursts, the same question again, errors,
   distinct paths not found).  The relay folds it into the limiter's object — one round trip gates a call: the sentinel,
   then the counters; the site gets a `Watch` object and waits for it on API calls only (a quiet reader's minute is
   counted in the Worker and reported in one round trip), so that pages stay as fast as they were.  Rows and events
   are written sparingly: the plan's allowances — requests to the objects, rows written — are the account's for the
   day.  The object out of reach, the site's reads go on and the relay's calls are refused with a 503: a call is never
   let through uncounted; nothing thrown in the sentinel itself reaches a visitor.
3. **Three modes, observe first.**  `SENTINEL = observe` (the default) records and flags and refuses nobody; `enforce`
   refuses an address over the block score for six hours; `off` records nothing.  A scanner path (`HONEYPOT = block`)
   refuses its address in observe mode too — a day for a hosting network's address, the ordinary six hours for a home
   network's, which many may share: nobody asks these hosts for `/wp-config.php` by mistake, and the list holds nothing
   the site serves and nothing under `/.well-known/`.  The repository's own clients (user agent `taochronos-`) are
   labelled in the events, not exempted — an agent string is anyone's to send; their calls stay under the block score,
   which a test pins.  The site answers a refusal as a 503, which the page takes as the corpus being away: it falls
   back on the 要籍语料 in the browser rather than show a passage as missing.
4. **Addresses only when flagged.**  A visitor is known by a hash (with the secret `SENTINEL_SALT`, the same across
   months).  The row keeps the address, and an event is written with the whole fingerprint, only from the flag score on;
   the page's own requests score 0 and leave a count.  The consent notice's promise (no address in a conversation record)
   stands: the records and the security events are separate stores, and the events hold no conversation.
5. **The events go to the repository, as the records do.**  Both Workers offer `…/security/export` and `…/security/ack`
   under the collector's token; `security/collect.py`, in the chat-logs workflow, appends them to `data/security-logs/`
   and only then lets the Workers delete them.  `…/security/summary` shows the owner the visitors by score and the
   addresses refused now.  `…/security/csp` takes the browsers' Content-Security-Policy reports (the site sends the
   policy in report-only mode first) and keeps them as events.
6. **Cost bounded by use.**  The relay charges a call an estimate from its size as it is let through and settles it
   with the usage the upstream reports when the answer ends, against the visitor's day (`TOKENS_PER_DAY`) and the day
   (`TOTAL_TOKENS_PER_DAY`), beside the calls; the next call over the budget is refused with a sentence the visitor can
   act on.  A visitor who leaves cancels the model call (`request.signal`).  The site caps a visitor's day of reads and
   of calls: a scraper takes little, and one address cannot spend the account's Worker requests.
7. **The edge as code** (`security/rules.yaml`, applied by `security/apply.py` through the Rulesets API with a token of
   its own): the custom rules and the rate limit the Free plan allows, written for its operators, refusing scanner paths,
   spoofed crawlers (a known bot's name without Cloudflare's verification), empty, scanner and scraping-library agents
   (blocked: none of them is a browser; `curl` and `wget` are left alone for the owner's own use), the block list, and a
   flood before it reaches the Workers' daily allowance; `security/events.py` keeps the edge's own security events
   beyond the plan's retention, paged, with a summary of suspects.  The repository's clients name themselves
   (`taochronos-collector/1`, `taochronos-deploy/1`) and are spared the browser integrity check by name — a spoofable
   courtesy that bypasses no other rule.

## Consequences

- Nothing changes for a visitor with a browser: score 0, no event, no latency on the pages; an API call waits for one
  Durable Object round trip.  A visitor behind an in-app browser that sends fewer headers scores a point or two and is
  served; only in enforce mode, and only over ten points, is anyone refused — and the data to set that threshold is
  what observe mode collects first.
- The owner reads `data/security-logs/` and the summaries, then turns `SENTINEL` to `enforce` and extends the edge
  rules with what the events show (addresses, networks, agents); the thresholds are variables, the lists are in one file.
- The Durable Objects do more per request (a row read and written); on the relay in the same round trip as before, on
  the site one more per API call, within the Free plan's allowance at this site's traffic.  The events table is capped
  (`EVENT_KEEP`); the visitor rows are swept after `WATCH_DAYS`.
- `data/security-logs/` holds addresses and headers of flagged clients: the repository stays private, as it does for
  the records.
