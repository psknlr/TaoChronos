# ADR 0016 — The site and the full corpus on Cloudflare

**Status:** accepted · 2026-09-30 · the hosting part of [ADR 0011](0011-web-client.md); the browser's corpus of
[ADR 0013](0013-canon-corpus-in-the-browser.md) becomes the fallback

## Context

The published page was a GitHub Pages site under IMPF-AI's domain.  Its certificate was never issued, so it was served over
http (no Cache API, a browser warning on every visit); GitHub Pages is slow and unreliable for its readers, most of them in
mainland China; and the page could only run the 要籍语料 in the browser (348 works, much of them in excerpts): all the
books were for those who ran `taochronos serve`.  IMPF-AI asked for HTTPS and for the site on Cloudflare — where its default
service already runs (ADR 0012) — with the full corpus there.

## Decision

1. **The site is a Worker** (`cloud/site`) on the custom domain `chat.impf.ai`: Cloudflare issues the certificate, the
   Worker redirects http to https and serves the site (`taochronos web build`) as static assets.  Cloudflare puts a
   custom domain only on a name without a DNS record of the account's own, so the CNAME that pointed the name at GitHub
   Pages is deleted when switching; the Pages site stays as a mirror.
2. **The full corpus runs in a container** (`cloud/corpus`): Cloudflare Containers, started on demand by a Durable Object
   and put to sleep when unused.  It is `taochronos`'s own server (`taochronos.chat.cloud serve`, the `ChatServer` of
   `taochronos serve`) without its model proxy and static files, over the full corpus as the site may carry it (`taochronos
   web store`: every source in `WEB_SOURCES`, never `NEVER_PACKED` — 958 books, 122 million characters).  No port of the
   tools to another platform: the page talks to it exactly as to `taochronos serve`.
3. **The site's API is a whitelist.**  The Worker passes on only the runtime's reads and calls (`info`, `catalog`,
   `passage`, `call`, `research`, `session`), only their path, query and body, limited per visitor; the container has no
   address of its own, and answers only the token its Durable Object started it with.
4. **The store travels without its index.**  The store is uploaded once, compressed (1.24 GB → 143 MB, in parts of 24 MiB
   — a Workers KV value each, checked by sha256 when read back), into the site's KV namespace through the site's Worker,
   with a token whose hash is registered only for the upload (the repository variable `STORE_TOKEN_SHA256`: the upload
   is otherwise off); `cloud/store.json` pins the one deployed.  KV rather than R2: every
   account has it, with no plan to buy, and the site's token may already write it.  The image is built in CI: the store is unpacked and checked, indexed with the normalizer of the
   code that serves it, and the caches the tools otherwise build on first use (the punctuation model, the citation network,
   the pair harvest, the schools) are built into the image — a container always starts from its image.
5. **The page does not wait for the container.**  What the runtime says about itself is kept by the Durable Object per
   deployed version and answered at once, and asking for it wakes the container; the page begins a conversation at once and
   the container is up, as a rule, by the time the model calls a tool.  When the site's server cannot answer, the page runs
   the 要籍语料 in the browser, as before.
6. **Degrade, never block.**  The workflow (`site.yml`) deploys the site whatever the account lacks: without the
   uploaded store, or without Containers (the Workers Paid plan), the site is deployed without the full corpus, with a
   warning saying what is missing.  Nor does the site wait for the container: it is deployed right after the tests, the
   container beside it (a build takes minutes), and the site again, bound to it, once a new one is up.  A container
   counts as deployed only once its deployment has succeeded (recorded in the KV namespace): the site is bound to it only
   then, the workflow checks that the account may deploy containers before building one, and a corpus Worker without
   its container answers as if there were none, so that the page falls back at once.

## Consequences

- https://chat.impf.ai is served over HTTPS from Cloudflare's network; the page downloads no corpus and no Pyodide when the
  site's server answers (the page itself, some 0.5 MB, instead of about 25 MB on a first visit).
- Every tool reads all the books the site may carry; citations are the same passage ids as in the full store and the
  browser's pack, so a conversation reads the same either way.
- A cold container takes some tens of seconds (the image is 1.8 GB); the kept info and the wake-up on page load hide most
  of it.  Research jobs live in the one container and are lost when it sleeps mid-run (it sleeps only when unused).
- On the Workers Free plan the site is served all the same (HTTPS, Cloudflare's network, the 要籍语料 in the browser):
  the Worker runs first only for the pages and the API, so the site's files — free and unmetered — do not count
  against the plan's 100,000 Worker requests a day.
- Cost: Workers Paid (5 USD a month) and the container's running time (about 0.036 USD an hour for `standard-1`); the
  store within Workers KV's free tier.  The account's API token must also be allowed to edit Containers.
- Updating the corpus: `taochronos web store`, `taochronos web upload`, commit `cloud/store.json` — the next deployment
  builds the image from it.
