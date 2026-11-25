# ADR 0034 — What the site ships is written down and enforced; what another site's page makes a reader's browser send counts against nobody

**Status:** accepted · 2026-11-25 · refines [ADR 0011](0011-web-client.md) and [ADR 0013](0013-canon-corpus-in-the-browser.md)
(the runtime in the browser), amends [ADR 0018](0018-sentinel-and-edge-rules.md) (what the sentinel counts) and
[ADR 0016](0016-site-and-full-corpus-on-cloudflare.md) (what the server's image is built from)

## Context

A remediation plan of 2026-11-25 read the site as an untrusted client would: the page downloads
`runtime/taochronos.zip`, `runtime/home.zip`, `runtime/corpus.sqlite.xz` and `runtime/boot.json`, they are static files
served past the Worker (and by the mirror on GitHub Pages, past every edge rule), and "any code or data delivered to an
untrusted client must be considered potentially recoverable".  It asked for fourteen measures, from blocking a headless
browser by name to moving the harness to the server.

The plan's premise is right, and the project's design already rests on it: the runtime in the browser is the product
([ADR 0011](0011-web-client.md)) — a visitor with a key of their own reaches the model from the page, nothing of the
conversation passes a server of ours, and the same code runs at `taochronos serve`.  What reaches a browser is public by
construction.  So the question the plan really asks is not "how is the download protected" (it cannot be) but **"is
everything in the download meant to be there"**.  It was not:

* **`home.zip` carried `evals/gold/`**: every gold set, with the splits their files call held out (`ner_heldout.yaml`,
  the held-out half of the alias gold, the held-out lost work of the fragment suite), to every visitor since the site
  went up.  A gold set a system under test can read is spent.  It also carried the governance policy's text, and the
  eight profiles (of twelve) the browser never starts on or extends.
* **`taochronos.zip` was the whole package**: 277 modules, 53 of which no browser imports — a quarter of its lines
  (some 21,000 of 80,000): the server, the command line, the site's own build, the evaluation suites, the D1 tooling
  and the pipeline that builds the corpus — never run in a browser, published all the same.
* **Nothing said what may ship.**  `package_zip()` zipped the directory; `home_zip()` zipped six directories by name.
  A file added to either was published by the next merge.

The corpus store is not a leak: `corpus/web` is public-domain texts in openly licensed transcriptions, packed to be
published (its `ATTRIBUTION.md`).  The mirror is a documented backup.  And the edge logs kept since October show the
four files fetched by something other than a browser twice (2026-10-08, 2026-11-08: the manifest, `boot.json` and the
corpus store, never the two archives) — though a browser's download was not recorded at all, which is the plan's
twelfth point.

The plan's fourth point, the endpoints, was audited alongside (the three Workers, the server, the collectors; 11
findings, none high).  Four were worth more than their rank, and one was reproduced on the deployed code before it was
changed: **a page on any other site could get its readers refused by ours.**  Thirty `<img>` tags pointed at paths of
the relay that are not there scored each reader's address 12 (`referer_foreign`, `burst`, `errors`, `probing`), over
the line at which the sentinel refuses an address for six hours; one tag at a scanner's path did it alone.  The reader
chose none of those requests.

## Decision

### What the site ships

1. **A policy, in one file** — [`distribution-policy.yaml`](../../distribution-policy.yaml).  Every tracked path of the
   repository has a class: *public* (may be published as it is: the client, the 要籍语料, the demonstration corpus),
   *restricted* (the project's own work: published only where the policy names a part of it) or *confidential* (`data/`,
   `evals/`: in no built artifact).  A path under none fails the tests, so a new directory is classified before
   anything is built from it.
2. **The package is derived, the exclusions are written.**  `runtime/taochronos.zip` holds the modules reachable — by
   the imports the code makes, function-level ones included — from what the page's worker imports, the plugins the
   browser's profiles load and the procedures the shipped agents name
   ([`chat/distribution.py`](../../src/taochronos/chat/distribution.py)).  A hand-kept list was the plan's proposal; it
   goes stale in the direction that hurts: a module the runtime needs and the list forgot fails in a visitor's browser,
   not in CI.  What *is* written by hand is the `never` list (the server, the command line, the build, the evaluation
   suites, the corpus pipeline…): an import that would pull one in fails the build, which names the chain
   (`taochronos.plugins.classics.ingest ← taochronos.plugins.classics.webcorpus` was the first it found, and was cut).
3. **The home is the files the policy names**: the browser's profile and the three it extends, the agents, the
   skills, the domain packs, the catalogs.  `architecture-policy.yaml` ships as an empty file (the harness finds its
   home by the name).  No gold set, no record.
4. **The build starts the runtime on exactly what it ships, then audits what it built.**  The two archives are
   unpacked alone into a clean directory and the runtime is booted there in its own process (a module that came from
   anywhere else fails it); `boot.json` is that run's output.  The finished site is then checked against the policy —
   every file is the client's or one the build writes, each archive holds exactly what it should, no forbidden name
   (`*.map`, `*.pem`, `.env`, `*.sqlite`…), nothing that reads as a credential, nothing carrying the confidential
   data's mark — and **a site that fails is not built**.  `taochronos web audit -o DIR` checks any built site; the
   tests run a search, `taochronos_research` and `taochronos_ask` on the two archives alone.
5. **The server's image holds nothing confidential either.**  `cloud/corpus/Dockerfile` copied `evals/gold`; the
   server never read it.  A test reads the image's build files against the policy.
6. **The gold sets carry a mark.**  Each file under `evals/` begins with a comment naming a canary GUID
   (`distribution-policy.yaml`, `site.canaries`).  The audit refuses a site whose text or archives carry it — a copy
   under another name is found by it — and a copy met anywhere else, later, is known for what it is.
   `evals/gold/README.md` now says plainly that everything in it on 2026-11-25 was public until then.

Result: `taochronos.zip` 1,507,509 → 1,113,458 bytes (225 of the package's 279 modules, two of them new here),
`home.zip` 1,566,476 → 1,468,338; `boot.json` unchanged but for the one tool below.

### What counts against a reader

7. **A request another site's page made a browser send is refused and not recorded.**  The browser says who asked:
   `Sec-Fetch-Site: cross-site` or `same-site` (a page's script can neither set nor remove it) with an `Origin` or
   `Referer` that is not ours; a browser too old to send it is read by those two alone (`ledFrom`,
   [`security/sentinel.js`](../../security/sentinel.js)).  The relay answers such a request 403 before anything else;
   the site's API answers 403; a path that is not there answers 404 as to anyone; **none of it writes a row, an event
   or a count for the address**.  A page of the site itself is served — following a link is what links are for — and
   counted as a visit only when it was opened as a page, not loaded as another site's image or frame.  This is also a
   rule of access, whatever the sentinel's mode: a reader's daily allowance of the corpus is not another site's to
   spend.
8. **A scanner's path opened once as a page is someone who followed a link.**  `Sec-Fetch-Site: none` is the address
   bar, a bookmark, a link tapped in a chat program — one message in a group is enough to send its members there.  It is
   also what the scanners that copy a browser's headers send (the `/.ssh/` probes of November did: every header of a
   Chrome navigation, over HTTP/1.1).  So: the first such path in ten minutes from a browser nothing else is odd about
   (`honeypot_opened`, 3) is counted and not refused; a second one refuses the address as before; and what only copies a
   browser — HTTP/1.x, no `Accept-Language`, a tool's agent, no `Sec-Fetch-*` at all — is refused at the first, as
   before.
9. **An event of a visitor who is not flagged says nothing of who.**  A browser's policy report is kept whoever sent
   it, and was kept whole: 1,964 of the 1,971 kept so far carry the address of a visitor the sentinel never flagged,
   against the rule its README states.  Such an event now keeps the host, the path, the network, the kind of browser
   and the embedding app — not the address, the city, the agent's full name or the handshake.

### The endpoints

10. **A tool's argument that names a file needs its own permission.**  `vision.layout` took a `path` and read it:
    on the hosted server, any file the process could read was a tool call away (what came back was only what parses
    as an OCR format — and `/dev/zero` never ends).  `ToolSpec.guarded` names the permission an argument needs beyond
    the tool's (`files:read`); the scheduler checks it for every caller; a conversation's model holds none and is not
    offered the argument; `taochronos ask --page FILE` grants it to that run alone.  The reader takes a regular file
    of at most 32 MB.
11. **What is kept is the answer to the question its key names.**  The corpus Worker keeps the tool catalogs per
    deployment.  It made the key from the first `mode` of a query and forwarded the query whole; the runtime reads the
    last.  `?mode=core&mode=all`, asked before any other request of a deployment, would have been kept as the core
    catalog: every tool, to every page, until the next deployment.  The Worker now asks the container the canonical
    question for the key.
12. **A research run's id is the only key to it, so it is one**: 128 random bits for a run and for its session
    (they were 48), and it goes into no row, event, log line or edge record (`/api/research/…`).  **The queue has an
    end**: twenty runs wait at most, a run asked for beyond that is told so at once, and an address starts at most
    `API_RESEARCH_PER_DAY` (100) a day, counted apart from its calls.
13. **The relay's diagnostic is the owner's, but for the part that is a visitor's.**  `GET /v1/egress` made the
    Worker ask several hosts from several places and wait up to eight seconds for each; anyone could set it off, and
    read where the service calls its models from.  Without the collector's token it now says only how a call from
    where the caller is looks to the second model's edge (one request: what someone in a refused region opens it to
    see); the places and the default model's host need the token, which `relay/collect.py check` sends when it has it.
14. **The page's address over plain http is nobody's.**  `http://chat.impf.ai` was still among the origins the relay
    and — which matters more — `taochronos serve` admit, from before the site was https-only.  The site serves no page
    there, so a page at that origin can only be one somebody on the network put in its place: it would have been given
    a visitor's local tools, their 我的资料 and their model keys.  Removed from both, and from the edge rule's list.
15. **The relay has no preview address.**  `preview_urls = false`, as the other two Workers have: no
    `*.workers.dev` name that none of the zone's rules stand before.

### What is seen

16. **Downloads of the runtime's files are recorded** ([`security/events.py`](../../security/events.py)): a day's
    totals by file, status (200, 206, 304…), method and kind of agent, with the bytes sent and the number of
    addresses — and no address, these being every reader's own downloads.  An address is kept with a fetch only when
    what fetched is not a browser (`ua_tool`, `ua_empty`, `artifact_agent`) or took one file thirty times in the day
    (`artifact_volume`); the suspects list counts it.

## Not done here

* **Moving the harness, or the prompts, to the server** (the plan's seventh point).  The page reaching the model with
  the visitor's own key, the conversation passing no server of ours, the runtime working offline and at
  `taochronos serve`: these are the design, and each ends the day the tools run on our machines.  Nor would it hide
  much: a system prompt is recoverable from any model that follows it, and the tools' value is the corpus work behind
  them, which is published under open licences.  What the policy does give is the lever the plan wanted: **a capability
  that should stay on the server is taken out of what the browser's profiles load, and its modules leave the archive
  with it** — no list to edit, and the build fails if something still imports it.  Nothing is behind that lever today
  because nothing the project holds is of that kind; the full corpus is, and it already stays on the server.
* **A gate on the static files** (the eighth point): signed URLs, a token, a challenge.  The page must fetch them
  before it can do anything, so the page would carry whatever opens the gate.  A challenge costs readers instead: it
  does not open in several in-app browsers, and not reliably from the mainland.  Edge rules 2, 4 and 5 already stand
  before these files (not before the mirror).
* **Blocking `HeadlessChrome`** (in the first point; Lightpanda is blocked since the rules of the same day).  The
  project's own checks are a headless Chromium, and eight page loads in seven weeks came from others.
* **Taking the mirror down** (the ninth point).  It is the documented fallback for when Cloudflare is unreachable, and
  serves the same public files; it is outside every edge rule and its downloads are in no log of ours.  That is a
  trade the owner made knowingly and may make again; nothing confidential is on it after this change.  Old copies of
  the site — GitHub's Pages artifacts, any cache or archive — still hold the gold sets and cannot be recalled.
* **An identity for whoever sends a record** (finding 4 of the audit): a record or a rating is taken from anyone who
  sends the page's `Origin`, within the per-address limits and — for the default service's — only from an address the
  relay answered in the last 26 hours.  `data/chat-logs/` is what visitors chose to send, and is to be read as
  untrusted input by anything that learns from it.  The server-checked guest session that
  [ADR 0026](0026-pinned-supply-chain-and-enforced-policies.md) left undone would close it.
* **Counting an answer's tokens when the upstream reports none** (finding 8): a stream cut before its last chunk is
  charged its reserve (the request's size), not its output.  Bounded by the calls a day and the output cap.
* **New held-out data.**  The policy keeps `evals/` out of everything built; a holdout worth the name has to be
  annotated anew, by someone who is not the system's author.

## Consequences

* **A visitor's download holds what the browser runs and reads, and no more**; the same archives are checked in CI and
  on every build, and a breach stops the build with the file and the reason.
* A new module the browser needs is shipped because something imports it; a new file the runtime reads must be named
  in the policy, or **the build fails where it boots** (the missing file's name is in the error).  A new top-level
  directory needs a class.
* `taochronos eval` needs a checkout: the browser's runtime and the server's image have no gold sets.
  `taochronos ask --page` works as before; a model in a conversation passes OCR tokens, not a path.
* A reader led to our hosts by another site's page is never recorded or refused for it.  A scanner gets the same by
  claiming a page sent it — and is refused what it asked for; its own request is scored as before.  A scanner with a
  whole browser behind it is refused at its second path, not its first.
* `GET /v1/egress` in a browser shows `worker` and `direct` only; for `places` and `model`,
  `LOG_EXPORT_TOKEN=… python3 relay/collect.py check`, or `curl -H "Authorization: Bearer …"`.
* **For the owner, after merging**: run *Actions → security → Run workflow* with `plan`, then `apply` (the origins of
  rule 3 changed; the two rule changes of the same day are still to be applied).  Policy reports already in
  `data/security-logs/site/` keep their addresses until they are rewritten; the collector keeps none from now on.
* Rollback, each one line: `HONEYPOT = "observe"` stops refusals at scanner paths; the `guarded` entry of a tool
  returns its argument; a path added to `site.home.ship` ships it again.
