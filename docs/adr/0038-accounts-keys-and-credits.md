# ADR 0038 — Accounts, keys and credits: the developer API and its console, in Rust

**Status:** accepted · 2026-11-27 · amends [ADR 0023](0023-workers-paid.md) (of its "sessions in place of addresses",
the signed sessions — for the API and the console, not yet for the site), [ADR 0026](0026-pinned-supply-chain-and-enforced-policies.md)
(a second Rust workspace, and a build tool that downloads nothing), [ADR 0034](0034-what-the-site-ships.md) (the console's
page is public) and [ADR 0036](0036-taocore.md) (Rust beside TaoCore, apart from it)

## Context

A proposal of 2026-11-27, *TaoChronos Secure API and Subscription Architecture*, asked for a platform in which "email
registration establishes an account, authentication establishes a session, project permissions determine access, and a
transactionally enforced budget authorizes every paid operation": Cloudflare Email Service for verification mail; a
TypeScript gateway and identity service; Durable Objects for budgets, D1 for identity, Queues for mail and events;
passkeys with a password option; recovery codes; organisations, projects and scoped API keys; reservations settled
after the call; a public `/v1` of evidence search, citation verification, research runs and chat completions;
subscriptions through a payment adapter; a developer console.  Its own acceptance tests (§12.3) and phases closed it.
The owner's direction, given while it was being read: **Rust for the API service — and, asked, everything in Rust.**

Read against the code: the site and the relay know a visitor by an address (an IPv6 one by its /64) or by an unsigned
browser id ([ADR 0035](0035-the-activity-ledger.md)); nothing has an account, a key or a balance.  The corpus answers
`POST /api/call` for anyone within an address's day ([ADR 0037](0037-what-a-call-may-cost.md)); its research runs share
one queue on one instance.  ADR 0023 had deferred "sessions in place of addresses" for want of a signed identity.

Read against the documentation as it stood on 2026-11-27 (each page read, not remembered) and against the runtime
itself (measured in workerd where it could be):

* **Email Service** sends from a Worker through `send_email` with a structured `send({from, to, subject, text, html})`
  that returns a message id and throws errors with a `code`; it takes **no idempotency key**.  Arbitrary recipients
  need Workers Paid (Free sends only to verified addresses, since 2026-11-24); the daily quota is unpublished ("new
  accounts start with a conservative daily quota").  **Email previews are on by default** for sending domains onboarded
  from 2026-07-02, keeping a message's HTML, text and headers for about seven days — a code in a body would be kept
  there.  Delivery events come through a Queue (`cf.email.sending.message.*`, at least once); the docs do not say that
  an event's message id is the one `send()` returned.  The proposal read event coverage as limited to verified
  addresses; the page that says so widened coverage, it did not narrow it.
* **Cloudflare's own sign-up example** keeps tokens in KV in plain text, verifies with a lookup then a delete that KV's
  eventual consistency does not make single-use, verifies on `GET` (which a mail scanner follows), answers 409 for an
  address that has an account, puts a name into HTML unescaped and limits nothing.  The design below does none of it.
* **Turnstile**'s single use is eventually consistent: tokens validated close together may both pass.
* **Passwords in Workers.**  Web Crypto has no Argon2 and no scrypt, and a module cannot be compiled from bytes at run
  time (measured: "Wasm code generation disallowed by embedder"; WebAssembly must be imported at deploy).  PBKDF2 is
  capped at **100,000 iterations in production** (workerd's `DEFAULT_MAX_PBKDF2_ITERATIONS`, an open issue since 2023,
  and a report of the error at 210,000 in January 2026) — six times under OWASP's floor of 600,000 for PBKDF2-SHA256.
  The local runtime does not enforce the cap: measured here, 600,000 iterations ran in 100 ms, which is why a local
  measurement is no evidence of what production allows.  `node:crypto`'s scrypt is capped at N·r·p ≤ 2^20, which
  OWASP's floor (N = 2^17, r = 8) reaches with 128 MiB of memory: an isolate's whole allowance.
* **RFC 10017** (OAuth 2.0 for Browser-Based Applications, BCP 212, August 2026) is the backend-for-frontend pattern the
  proposal cites; **WebAuthn Level 3** is a W3C Recommendation of 25 August 2026; **NIST SP 800-63B-4** forbids email as
  an out-of-band authenticator but says that codes "sent to validate email addresses or … issued as recovery codes …
  are not authentication processes" — the distinction the proposal draws.

## Decision

### Two Workers in Rust, one crate that decides

1. **`rust/platform/`, a Cargo workspace of its own** ([README](../../rust/platform/README.md)), beside TaoCore's and
   apart from it: its dependencies (workers-rs, the curves) and its policy (`deny.toml`) are its own, and TaoCore's
   committed browser module is built from a graph this one does not touch.  The compiler is the one
   `rust/rust-toolchain.toml` pins.
   * **`core` (`tao-platform`)** holds every decision, synchronous, over any SQLite (`sql::Sql`, the shape of a Durable
     Object's `ctx.storage.sql`): identity, WebAuthn, keys, credits, the API's request rules, mail.  It compiles and
     is tested natively (42 tests, over SQLite itself through rusqlite) and for wasm32 in the Workers.  It reads no
     clock and no system source of randomness: both are handed in.
   * **`api` (`tao-api`)** is **api.impf.ai**: the gateway and the organisations' Durable Object (`Account`).
   * **`console` (`tao-console`)** is **console.impf.ai**: the account console, its people's Durable Object
     (`Identity`) and its mail; it binds `Account` by `script_name`.
   * **`edge` (`tao-edge`)** is what both need of Cloudflare's runtime and decides nothing.
   The page of the console is HTML, CSS and one script (`console/public`): a browser makes passkeys through
   `navigator.credentials`, which only a page's script reaches.  The Worker serves it, with a policy that allows no
   inline script or style and frames nothing.
2. **A Durable Object's synchronous step is the transaction.**  Every method of the cores reads, decides and writes with
   no `await` inside — the cryptography included, since in Rust it is synchronous (the codes, the digests, the
   passkeys' signatures) — and a Durable Object runs nothing else while a synchronous method runs.  workers-rs does not
   expose `transactionSync`, so a storage failure in the middle of a step could leave it half-written: every refusal is
   decided before the first write that is not itself meant to stand (a wrong code's attempt, a challenge taken), so
   that only a storage failure can stop a step part way.

### Who a person is (console.impf.ai)

3. **An address is proved by a code, in the browser that asked.**  A flow binds to its browser (`__Host-tcb`, 256 bits;
   its SHA-256 kept), its purpose (register, sign in, change address), its address and its **generation**: a resend
   makes the next one, the only code from then on, and gives back none of the five attempts.  Ten minutes a code,
   thirty a flow, five mails a flow, a minute between them; per address, five an hour and ten a day; per network
   (an IPv6 /64, HMAC'd), twenty flows an hour; the service, a configurable number a day (Email Service's quota is
   unpublished).  **The code is kept nowhere**: it is an HMAC of (purpose, flow, generation, address) under the Worker
   secret `ACCOUNT_SECRET`, computed when the mail leaves and again when the code is typed — not in a row, not sealed in
   the outbox, not in a log.  The proposal asked for an HMAC verifier and an encrypted delivery payload; deriving the
   code needs neither, and a mail retried after a lost answer carries the same code.
4. **The page learns nothing of an address.**  Registering and signing in answer alike whether an address has an
   account; only the mail differs, and its owner alone reads it ("you already have an account", "no account uses this
   address" — no code).  A flow that sent no code takes none, refusing a code exactly as a wrong one is refused, attempt
   for attempt.  An address the signed-in owner wants to move to is said to be taken: to them alone, after they proved
   their session, within the same limits.
5. **Nothing usable before the address is proved.**  A right code gives one **grant** (256 bits, fifteen minutes, this
   browser): to create the account, with a passkey made against a challenge bound to that grant, or with none.  The
   account, its organisation (its own, with a trial if one is given today), its membership, its passkey and its first
   session are written in one step that also uses the grant; an address registered meanwhile from another browser is
   refused.  No credential an attacker made before the code can survive (§12.3).
6. **Passkeys, verified in Rust** (`webauthn.rs`, WebAuthn L3 §7.1 and §7.2 step by step, the step numbers in the code):
   ES256 (`p256`), EdDSA (`ed25519-dalek`, strict) and RS256 — the signature raised to the key's exponent with
   `num-bigint` and the whole PKCS #1 v1.5 message compared with the one expected, never parsed (the way lax RSA
   verifiers have been forged).  User verification required; discoverable credentials; attestation "none", whatever the
   format, trusted from no maker; a user handle that is random, never an address; the backup flags kept and shown; a
   counter that once counts must rise.  CBOR is read by `cbor.rs`, a strict subset: definite lengths, no tags, no
   floats, each map key once, nothing after the end.  The relying party is `impf.ai` and the console the one origin
   allowed: a later move of the ceremonies (an `auth.impf.ai`, the site's own sign-in) keeps every passkey.
7. **An account a passkey guards is not opened by its mailbox alone.**  An email code then gives a second grant that a
   **recovery code** completes — ten of them, 80 bits each, made with the first passkey, kept as digests, shown once;
   one used ends every other session and tells the owner.  An account with no passkey signs in by its mailbox, which is
   then the whole of its security and is said so on its page.
8. **Sessions are the server's** (RFC 10017's backend-for-frontend): `__Host-tcs`, 256 bits, `HttpOnly`, `Secure`,
   `SameSite=Lax`, the SHA-256 kept; thirty days at most, seven unused.  A change must come from the console's origin,
   as JSON, and not from another site (`Origin`, `Sec-Fetch-Site`).  **A passkey's touch within five minutes** (a
   step-up, which gives the session a new token) is asked before a live key is made or revoked, a passkey removed,
   recovery codes renewed, an address changed or a project's limit set; the first passkey of an account without one is
   made within ten minutes of proving its address.  A recovery ends every session but its own (the account's security
   version).  The person sees their sessions, ends any, and reads their account's last hundred security events.
9. **Mail leaves from the object's outbox**, written in the step that decided it, sent by its alarm (`mail.rs`): what is
   past its time is dropped, a code's mail whose flow moved on (a resend, the code typed) is dropped as obsolete, a
   refusal that will not pass is given up, what may pass is tried again with backoff, four times at most and never past
   its time.  **No code is ever in a subject** (delivery logs and lock screens show subjects), no link does anything (a
   scanner would follow it, and it would open a session in whichever browser opened the mail), nothing a person wrote
   is in a mail, and an address that changed is shown to the old one as its first character and its domain.  Logs name
   a template and an error's code, never an address or a code.  Delivery events, when the owner subscribes a Queue, are
   kept beside their mail by event id, a deferral never undoing a delivery, and never verify an address (§12.3).
10. **Turnstile**, when its keys are set, stands before every flow that sends mail: checked with Cloudflare for this host
   and this action, and kept once by the identity object (its own reuse check is eventually consistent).

### What a key may do, and what a call costs (api.impf.ai)

11. **One `Account` object an organisation** (`accounts.rs`): its projects, its keys, its credits, its calls in flight
   — so that a key's check, its rate, the balance and the reservation are one step.  An object no organisation was
   provisioned in writes nothing when a key names it: a well-formed key is anyone's to compute, and an organisation is
   made by provisioning, never by asking.
12. **An API key** is `tao_<live|test>_<org>_<secret><check>`: the organisation's id (no secret: it says which object
   holds the key, read without a lookup), 192 random bits, and a CRC-32 that refuses a mistyped key before anything is
   asked and lets a scanner find keys with few false alarms.  Kept as its SHA-256 — 192 bits need no key, so no
   rotation of a service secret invalidates a key; shown once, then as `tao_live_…` and four characters of the
   checksum.  Scopes: `evidence:search`, `citations:verify`, `usage:read`.  At most fifty keys not revoked.
13. **Credits in whole numbers, reserved before, settled after.**  *available* = the ledger's sum − what calls in flight
   hold; a call is let through only if its price fits, and is held; settling moves it to spent, a failure gives it back.
   So nothing a call does takes the balance below zero, however many arrive together (§12.3).  A reservation is settled
   once, a usage entry and a grant are written once (their references are unique), a reservation nobody settles lapses
   after two minutes — **released, not charged**, and counted — because a result that may not have reached the caller
   is not one to charge for; a settlement that comes after its lapse is counted and changes nothing.  A price's version
   is kept with every reservation and charge.  `Idempotency-Key`: the same key and request get the first answer again
   (`Idempotent-Replayed`), uncharged; another request under the same key is refused (422); a failed call is no answer,
   and its repeat runs.  Test keys spend no credits: a hundred calls a day an organisation.  Each key 60 calls a minute
   and two in flight, each organisation four in flight, each project an optional monthly limit; the edge's rate limits
   stand before the object (per address, per key).
14. **The products** are the corpus's own tools (`api.rs`): `POST /v1/evidence/search` (`classics.search`) and
   `POST /v1/citations/verify` (`validation.verify_quote`), and `GET /v1/limits`, `GET /v1/usage`.  A request is read
   strictly — the fields a product takes, each within limits narrower than the tool's own, nothing else — and **refused,
   not clamped** (ADR 0037's rule).  The corpus answers 200 whether a tool ran or refused: a call is **charged only when
   the tool ran**; a tool's refusal is the caller's 422, a starting or busy corpus a 503 with its own `Retry-After`,
   anything else a 502 — none charged.  The corpus is given sixty seconds, inside the reservation's two minutes.  What
   is passed on is the result, its citations, its summary and its text for a model; never the harness's receipt.
15. **The owner's endpoints** (`/admin/…`: organisations, grants, adjustments, projects, keys, revocation) answer the
   token whose SHA-256 is `ADMIN_TOKEN_SHA256` — as `STORE_TOKEN_SHA256` does, the token itself is kept nowhere — and are
   off without it.  The console provisions a new person's organisation in the same object, with the trial the identity
   object gave (a configured number of credits, a configured number of trials a day in all), once.

### The supply chain

16. **workers-rs's build tool downloads nothing.**  `worker-build` would fetch esbuild, wasm-opt and wasm-bindgen at
   build time, unpinned and unchecked.  `rust/platform/build.sh` installs `worker-build` 0.9.0 and `wasm-bindgen-cli`
   0.2.130 from crates.io with `--locked` (checksummed by the index; the CLI's version is the one Cargo.lock pins of the
   crate, and the script refuses when they part), hands worker-build the esbuild of wrangler's lockfile (0.28.2, its
   sha512 checked by npm — the version worker-build names), turns wasm-opt off, and checks Cargo.lock before the build
   (worker-build runs cargo without `--locked`).  `deny.toml` allows BSD-3-Clause, which the curves' constant-time core
   (`subtle`, `curve25519-dalek`, `ed25519-dalek`) and workers-rs's router are under, and two releases of `syn`, both
   build-time only.  Advisories, bans, licences and sources pass; the audit workflow checks it each week.
17. **Tested as built before it is deployed.**  The platform workflow tests the core, builds both Workers with the
   pinned tools, runs the API as built in local workerd beside a stand-in corpus (`cloud/api/test/run.sh`: 30 checks —
   charges, refusals, replays, failures not charged, usage, revocation, forged keys, the owner's token), and deploys
   only what the owner has configured (the API once `API_ADMIN_TOKEN_SHA256` is set; the console once `ACCOUNT_SECRET`
   is).  `cloud/console/test/run.sh` drives the console in Chromium with a virtual authenticator — registration by code
   and passkey, recovery codes, the trial, a live key, sign-in by passkey alone, the security page, a change from another
   origin refused — and then spends that key on the API; it needs Playwright, which is not pinned here, so it is a
   developer's check.  Run before this was committed, it found that workers-rs reads an `i64` given to `set_alarm` as
   an offset: the mail alarm had been set fifty-seven years ahead.

## Where this departs from the proposal

* **Rust, not TypeScript**, by the owner's choice; the research framework and TaoCore are unchanged.  The modules are
  0.76 MB (the API) and 1.1 MB (the console), 0.24 and 0.36 MB compressed.
* **No passwords yet.**  Passkeys, email codes and recovery codes.  A password needs a memory-hard hash, which a Worker
  can only have as a WebAssembly module built and pinned like TaoCore's (Argon2id at OWASP's 19 MiB); PBKDF2 at what
  production allows is six times weaker than OWASP's floor, and the proposal itself says not to weaken hashing for the
  runtime.  The console's first readers are developers on computers, where platform authenticators, password managers
  and phones (hybrid) make passkeys.  A password becomes worth its risks when the research site takes sign-in (phones
  without Google services, WeChat's browser): then with that module, a 15-character floor and breached-password checks.
* **One Durable Object for identity, not D1.**  Uniqueness of addresses, single-use grants and challenges, attempt
  counts and the outbox are one step in one object; D1 has no interactive transactions.  One object serves hundreds of
  requests a second and holds 10 GB — far beyond the console's scale; when it is not, the flows shard by address.
* **No Queue for mail** — the object's SQLite is the outbox, written in the step that decides, drained by its alarm
  (ADR 0023's reasoning for the archive).  The delivery events' Queue is the owner's to subscribe; what keeps an event
  (`mail::delivery_events`, and the identity object's `delivery_events`) is written and tested, and the Worker's queue
  handler that would hand it a batch is not (below).
* **One console origin, no `auth.impf.ai` yet.**  The relying party is `impf.ai`, so passkeys survive the move when the
  site takes sign-in through a code flow from the console.
* **Two products, not four.**  Research runs share one queue on one instance with the site's visitors, and the corpus's
  jobs are not yet anyone's (ADR 0023, "not done", 3): a run of the API needs its own queue and ownership of its job
  first.  Chat completions resell a model provider's service (its terms, its costs per token) and need payments first.
* **Credits granted by the owner, not bought.**  The payment adapter needs the owner's choice of provider and entity.
* **No TOTP**: passkeys and recovery codes cover the console's readers; a QR encoder would have to be vendored.

## Not done here, in the order proposed

1. **The site's own sign-in** — sessions in place of addresses for chat.impf.ai and the relay (ADR 0023's first item),
   through an authorisation-code flow from the console, so that fifty clinicians behind one address stop sharing a day.
2. **Passwords**, with an Argon2id module (above).
3. **Payments**: a provider's checkout and signed webhooks into the `Account` ledger (each event once, in any order).
4. **Research runs through the API**: a queue of its own in the corpus server, jobs owned by an organisation, each
   step's reservation.
5. **Teams**: invitations, roles beyond the owner (the tables have them), an organisation's recovery policy.
6. **One gate for the corpus** across organisations (a global count in flight), before many developers share it.
7. **The owner's reports** across organisations (a D1 projection of the ledgers, as the activity ledger's registry).
8. **Delivery events**: the console Worker's queue handler (workers-rs's `queue` feature) and its consumer binding, once
   the owner has subscribed a Queue to the sending domain and checked that its message ids are the ones `send()` returns.

## Consequences

* With the variable `API_ADMIN_TOKEN_SHA256` set, the platform workflow deploys **api.impf.ai**; the owner makes an
  organisation, grants it credits and issues its key with the token ([cloud/api/README.md](../../cloud/api/README.md)).
  With the secret `ACCOUNT_SECRET` set it deploys **console.impf.ai** too, registration off until the owner opens it,
  after the steps of [cloud/console/SETUP.md](../../cloud/console/SETUP.md): Email Service's sending domain on Workers
  Paid, **its previews turned off before anything is sent**, its quota checked.
* The site, the relay and the corpus are unchanged; the API's calls take their share of the corpus's one instance,
  bounded by four in flight an organisation and the prices.
* What the platform keeps of a person: an address, a random handle, passkeys' public keys, digests, security events
  (a hundred), sessions (a device's browser and system, a country). No address of a network, no code, no token.
