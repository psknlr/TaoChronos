# 道乃久开发者平台 — setting up the developer API and its console

For the owner of the Cloudflare account and of this repository: every step from the platform's code on `main` to
**api.impf.ai** answering developers' programs and **console.impf.ai** letting developers register — what to click,
what to type, what you should see, and what to do when you see something else.

* Why the platform is built as it is: [ADR 0038](adr/0038-accounts-keys-and-credits.md).
* The API as developers read it: [cloud/api/README.md](../cloud/api/README.md).
* The rest of the deployment (the site, the full corpus, the default service) and the deploy token this guide reuses:
  [deploy.md](deploy.md).

The platform serves developers in Singapore and the other international regions first; where a choice depends on the
region, this guide makes it for them.  Cloudflare's labels are quoted as its documentation gave them on 28 November
2026, GitHub's as they appear on screen.
Daily counters reset at 00:00 UTC — 08:00 in Beijing and Singapore.  Commands are for a terminal on macOS, Linux or
Windows' WSL; each block is one command.

**The short way:** read Part 1, then do Parts 2 to 7 in order — each ends with a check.  About an hour of work spread
over a day, because the sending domain's DNS and the mail tests take waiting.

---

## Contents

- [Part 1. What you are setting up](#part-1-what-you-are-setting-up)
- [Part 2. Before you start](#part-2-before-you-start)
- [Part 3. The API, api.impf.ai](#part-3-the-api-apiimpfai)
- [Part 4. The sending domain (Email Service)](#part-4-the-sending-domain-email-service)
- [Part 5. The console, console.impf.ai](#part-5-the-console-consoleimpfai)
- [Part 6. Turnstile](#part-6-turnstile)
- [Part 7. Opening registration](#part-7-opening-registration)
- [Part 8. Running it](#part-8-running-it)
- [Part 9. Every setting](#part-9-every-setting)
- [Part 10. Troubleshooting](#part-10-troubleshooting)
- [Part 11. Checking it on your own computer](#part-11-checking-it-on-your-own-computer)

---

## Part 1. What you are setting up

```text
a developer's server ── Authorization: Bearer tao_live_… ──▶ api.impf.ai          Worker taochronos-api
                                                              ├─ Account objects, one an organisation:
                                                              │  its keys, credits, calls in flight
                                                              └─ CORPUS (service binding) ──▶ taochronos-corpus

a developer's browser ── passkeys, a session cookie ────────▶ console.impf.ai      Worker taochronos-console
                                                              ├─ the Identity object: people, codes, sessions,
                                                              │  and the mail outbox ──▶ Email Service ──▶ inboxes
                                                              └─ ACCOUNT: taochronos-api's Account class
```

One workflow, **platform** (`.github/workflows/platform.yml`), builds both Workers, tests them, and deploys each only
once what it needs is set.  It runs on every push to `main` that touches the platform, and whenever you run it.  The
Durable Objects, the rate limits and the two Custom Domains are made by the deploy itself from the Workers'
`wrangler.toml`: there is nothing to create by hand in Cloudflare but the sending domain and the Turnstile widget.

| You set | Then |
|---|---|
| the variable `API_ADMIN_TOKEN_SHA256` | the API is deployed, with the owner's endpoints on (Part 3) |
| a sending domain, its previews off | the console's mail can leave (Part 4) |
| the secret `ACCOUNT_SECRET` | the console is deployed too — with registration **off** (Part 5) |
| the variable `TURNSTILE_SITE_KEY` and the secret `TURNSTILE_SECRET` | a human check before every step that sends mail (Part 6) |
| the variable `CONSOLE_REGISTRATION` = `open` | anyone may register — and only with Turnstile on (Part 7) |
| the variable `CONSOLE_TRIAL_CREDITS` | each new organisation starts with that many credits (Part 7) |

Everything else — prices, limits, lifetimes — is in the two `wrangler.toml` files, with defaults that work (Part 9).

The order matters twice: the API before the console (the console binds the API's class; the workflow keeps this
order), and the sending domain, with its previews off, **before** the console sends its first mail.

---

## Part 2. Before you start

### 2.1 What you need

| | How to check |
|---|---|
| The account on **Workers Paid** | as [deploy.md](deploy.md) assumes.  Email Service sends to any address only on Paid; on Free, only to verified ones |
| The zone `impf.ai` on Cloudflare DNS | Email Service needs Cloudflare DNS for the records it adds |
| No DNS record of your own for `api.impf.ai` or `console.impf.ai` | Dashboard → `impf.ai` → **DNS → Records**: search `api`, then `console`.  A Custom Domain makes its own record and cannot be made over an existing CNAME: delete any you find (unless something uses it — then choose other hostnames) |
| GitHub Actions starting jobs | [deploy.md 2.1](deploy.md#21-github-actions) |
| The repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` | the ones the other Workers deploy with ([deploy.md 2.3](deploy.md#23-github-secrets-and-variables)) |
| A terminal with `openssl`, or Python 3 | to make the token and the secret |
| A password manager | for the owner's token |

### 2.2 The deploy token's permissions

The deploy token of [deploy.md 2.2](deploy.md#22-the-cloudflare-deploy-token) already has what the platform needs:

| Scope | Permission | Level | For |
|---|---|---|---|
| Account | Workers Scripts | Edit | both Workers, their Durable Objects and rate limits |
| Account | Account Settings | Read | wrangler |
| Zone (`impf.ai`) | Workers Routes | Edit | the Custom Domains `api.impf.ai` and `console.impf.ai` |

Cloudflare's documentation names no permission for deploying a Worker with an Email Service `send_email` binding.  If
the console's deploy is refused with an authorisation error that mentions email, add **Account · Email Sending ·
Edit** (the permission Email Service's REST API needs): **My Profile → API Tokens →** the token **→ ⋯ → Edit**.
Editing a token's permissions keeps its value; nothing changes in GitHub.

### 2.3 The code on `main`

The workflow deploys from `main`, and GitHub offers **Run workflow** only for a workflow that is on the default
branch.  If the platform's code is still on a branch, merge it into `main` through a pull request first.  Merging is
safe before anything below is set: the run it starts builds and tests both Workers, deploys nothing, and says why —
**Actions → platform →** the run **→ Annotations**:

```text
the API is not deployed until the variable API_ADMIN_TOKEN_SHA256 is set (docs/platform.md, Part 3)
```

---

## Part 3. The API, api.impf.ai

### 3.1 The owner's token

The owner's endpoints (`/admin/…`: organisations, credits, keys) answer one token, which you make and keep.  GitHub and
Cloudflare only ever hold its SHA-256.

```bash
token=$(openssl rand -hex 32)
```

```bash
printf '%s\n' "$token"
```

Copy what it prints into your password manager ("TaoChronos API — owner's token").  Then its SHA-256 — on Linux or WSL:

```bash
printf '%s' "$token" | sha256sum | cut -d' ' -f1
```

on macOS:

```bash
printf '%s' "$token" | shasum -a 256 | cut -d' ' -f1
```

Either prints 64 hexadecimal characters.  Without `openssl`, Python makes both:

```bash
token=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```

```bash
python3 -c "import hashlib, sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$token"
```

Use `printf '%s'`, never `echo`, to hash the token: `echo` adds a newline, the digest of the token and a newline is
another digest, and the endpoints then refuse the token (401, `admin`).

### 3.2 The variable

GitHub → the repository → **Settings → Secrets and variables → Actions → Variables → New repository variable**:

* **Name:** `API_ADMIN_TOKEN_SHA256`
* **Value:** the 64 characters

A variable, not a secret: a digest reveals nothing, and the workflow reads it as a variable.

### 3.3 Deploy

**Actions → platform → Run workflow →** *Use workflow from* `main` **→ Run workflow.**  The first run compiles both
Workers and takes a while.  In its step **Deploy the developer API (api.impf.ai)** you should see:

```text
the corpus Worker: taochronos-corpus
the owner's endpoints: on
```

(or, instead of the first line, a warning that the corpus's Worker is not deployed: 3.5).  The last step, **Check what
was deployed answers**, prints the API's index.

### 3.4 Check

```bash
curl -sS https://api.impf.ai/v1
```

A JSON index: the products, their prices and the prices' version.  Just after the first deploy the Custom Domain's
certificate may take a few minutes; an SSL error or a 52x meanwhile passes on its own.  In the dashboard, **Workers &
Pages → taochronos-api → Settings → Domains & Routes** lists `api.impf.ai`.

### 3.5 The corpus

The API's two products are the full corpus's own tools.  `cloud/api/deploy.sh` binds the corpus's Worker
(`taochronos-corpus`) when the account has it **at the time of the deploy**.  Without it every paid call is answered
503 (`corpus`) — nothing is reserved, nothing charged.  If the corpus is deployed later
([deploy.md Part 3](deploy.md#part-3-the-whole-corpus)), run the platform workflow once more so that the API binds it.

### 3.6 A first organisation, its credits and its keys

For a pilot's first developers, before the console is open — or any time.  In your terminal, the token and two
shorthands:

```bash
export TAO_ADMIN='…'
```

```bash
A=https://api.impf.ai/admin; H=(-H "Authorization: Bearer $TAO_ADMIN" -H "Content-Type: application/json")
```

**An organisation** (it is given a project named `default`); its id is printed:

```bash
org=$(curl -fsS -X POST "$A/orgs" "${H[@]}" -d '{"name": "Pilot lab"}' | python3 -c 'import json, sys; print(json.load(sys.stdin)["org"]["id"])') && echo "$org"
```

`org_` and 26 characters.  Note it with the organisation's name: it is how you name the organisation from now on.

**Credits**, once per reference — the same reference again adds nothing, so a request repeated after a lost answer is
safe:

```bash
curl -fsS -X POST "$A/orgs/$org/grants" "${H[@]}" -d '{"credits": 10000, "reference": "pilot-2026-12", "note": "pilot, December"}'
```

`{"added":true,"credits":{"available":10000,"held":0,"net":10000}}`.

**A key** — a test key first: it spends nothing, and the organisation's test keys make a hundred calls a day in all.

```bash
curl -fsS -X POST "$A/orgs/$org/keys" "${H[@]}" -d '{"environment": "test", "name": "lab laptop"}'
```

`{"environment":"test","id":"key_…","key":"tao_test_…","shown":"tao_test_…wxyz"}`.  **The key is in this answer
only**: nobody can show it again.  Give it to the developer by something better than plain mail or chat if you can (a
password manager's sharing, an end-to-end encrypted message).  A live key is the same with `"environment": "live"`.
Optional fields: `"scopes"` — a list from `evidence:search`, `citations:verify`, `usage:read` (all three if left out);
`"project"` — a project's id; `"expires_days"` — 1 to 3650.

**Try it** as the developer will:

```bash
curl -sS https://api.impf.ai/v1/evidence/search -H "Authorization: Bearer tao_test_…" -H "Content-Type: application/json" -d '{"query": "桂枝汤 汗出 恶风", "k": 3}'
```

**See the organisation** — its credits, projects, keys (never a key itself), today's usage, what lapsed:

```bash
curl -fsS "$A/orgs/$org" -H "Authorization: Bearer $TAO_ADMIN" | python3 -m json.tool
```

Every owner's endpoint: [cloud/api/README.md, *The owner's endpoints*](../cloud/api/README.md#the-owners-endpoints).

### 3.7 Prices and limits

They are in `cloud/api/wrangler.toml`, under `[vars]` (Part 9.2).  Change them there, through a pull request: the push
to `main` deploys them.  Not in the dashboard — every deploy replaces a Worker's variables with its file's.  A change
of price changes the prices' version (`p` and 8 hexadecimal characters), kept with every reservation and charge; a
call in flight keeps the price it was let through at.

---

## Part 4. The sending domain (Email Service)

The console sends its mail from `noreply@impf.ai` through Cloudflare's Email Service.

### 4.1 First, DMARC

Onboarding adds a DMARC record — TXT `_dmarc.impf.ai`, `v=DMARC1; p=reject;` — **if the domain has none**.
`p=reject` asks every receiving server to refuse mail that says it is from `@impf.ai` and is not authenticated as
such.  If anything else sends as `@impf.ai` (a company mailbox, a newsletter tool) without SPF or DKIM set up for
`impf.ai`, its mail would start to bounce.  Dashboard → `impf.ai` → **DNS → Records**, search `_dmarc`:

* a record is there: onboarding leaves it alone;
* none, and nothing else sends as `@impf.ai`: go on;
* none, and something else does, or you are not sure: add one of your own first — TXT `_dmarc`, `v=DMARC1; p=none;` —
  and make it stricter once every sender is authenticated.

### 4.2 Onboard the domain

1. Dashboard → **Compute → Email Service → Email Sending → Onboard Domain**.
2. Choose `impf.ai`, review the DNS records, **Done**.

Cloudflare adds, beside the zone's other records:

| Type | Name | Content |
|---|---|---|
| MX | `cf-bounce.impf.ai` | `route1.mx.cloudflare.net`, `route2…`, `route3…` |
| TXT | `cf-bounce.impf.ai` | `v=spf1 include:_spf.mx.cloudflare.net ~all` |
| TXT | `cf-bounce._domainkey.impf.ai` | the DKIM key |
| TXT | `_dmarc.impf.ai` | `v=DMARC1; p=reject;` — only if there was none (4.1) |

The domain's inbound mail — its own MX records, Email Routing — is not touched: sending and routing are separate.
Verification is automatic, usually within 5 to 15 minutes, at most 24 hours.  Its state: **Email Sending →
Settings → DNS records** (*Locked* and *Unlocked* both mean configured).

**A subdomain kept for mail** (`mail.impf.ai`, say) instead of the apex: onboard it, then change `MAIL_FROM` and
`allowed_sender_addresses` in `cloud/console/wrangler.toml` to the same address on it.  The two must agree, or every
mail is refused (`E_SENDER_NOT_VERIFIED`).  Cloudflare's documentation implies that subdomains can be onboarded without
quite saying so; the console is set up for the apex.

### 4.3 Turn the email previews off — now

Email Service keeps a preview of every message sent while previews are on — its text, HTML and headers, for about
seven days — and **they are on by default**.  The console's codes are in its mails' bodies.

**Compute → Email Service → Email Sending →** `impf.ai` **→ Settings →** *Enable email preview*: **off**.

Only messages sent while it is on are kept, so turn it off before the console sends anything (Part 5), and again
whenever a domain is onboarded anew.

### 4.4 The daily quota

Cloudflare publishes no number — "new accounts start with a conservative daily quota and scale up over time" — and
its documentation does not say where the dashboard shows an account's.  Mail past the quota is refused by Email
Service: the console tries again, but a person waits for a code that does not come.  So the console has a daily cap of
its own, `AUTH_MAILS_PER_DAY` (default 1000), past which it refuses new verifications at once — "Today's verification
mail is spent: try tomorrow." — visibly, rather than silently.

1. Ask Cloudflare for your account's number with the *Limit Increase Request Form* linked from
   [Email Service's limits page](https://developers.cloudflare.com/email-service/platform/limits/) (or ask support), and
   for more if you expect it.
2. Set `AUTH_MAILS_PER_DAY` in `cloud/console/wrangler.toml` to about four-fifths of it: the rest is for the notices
   (a passkey added, an address changed), which the cap does not count.  Until you know the number, `100` is plenty for
   a pilot.

### 4.5 Following mail

* **Email Service's Activity log** (linked from the sending domain's settings): each message's state — *Sent*,
  *Delivered*, *Delivery failed*, *Rejected (suppressed)*, *Failed* — up to 30 days back.
* **The console's Workers Logs:** a line `mail <template> <code>` for every mail Email Service refused — the template
  and the error's code, never the address (Part 10.4 says what each code means).
* Email Routing's summary counts mail sent by a Worker as *dropped* even when it was delivered: ignore it there.

---

## Part 5. The console, console.impf.ai

### 5.1 The account secret

`ACCOUNT_SECRET` is the key the console derives its email codes under; it keeps no code anywhere.  At least 32
characters:

```bash
openssl rand -base64 48
```

(or `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).  GitHub → **Settings → Secrets and variables →
Actions → Secrets → New repository secret**: **Name** `ACCOUNT_SECRET`, **Secret** the value.  You need not keep it
anywhere else: changing it later only stops the codes in flight (8.2).

### 5.2 Deploy

**Actions → platform → Run workflow.**  The API is deployed first, then the console, then `cloud/console/deploy.sh`
gives the console its secret.  Registration stays **off** until Part 7.

### 5.3 Check

```bash
curl -sS https://console.impf.ai/auth/config
```

`{"registration":"off","rp_id":"impf.ai","turnstile":null}`.  Open https://console.impf.ai: the sign-in page, in
Chinese or English by the browser's language (**中文** / **EN** at the top switches it).

### 5.4 The mail test

With registration off, signing in still works — and an address that has no account is sent a mail saying so, with no
code in it.  That makes a test of delivery that creates nothing:

1. At https://console.impf.ai, sign in by email with an address of yours that has no account.  Do it for each kind of
   address your developers will use: Gmail, Outlook (Hotmail), Yahoo, iCloud, and an institution's — a university's,
   a hospital's — whose filters are often the strictest.
2. Each should receive, within a minute, *TaoChronos: no account uses this address* (in Chinese if the page was in
   Chinese) from **道乃久 TaoChronos** `<noreply@impf.ai>`.  Look in the spam folder too; if it is there, mark it as
   not spam.
3. Where one does not arrive: Email Service's Activity log (4.5) for its state, and the console's Workers Logs for a
   `mail … E_…` line (Part 10.4).

Each address may be sent five mails an hour and ten a day; **Resend** waits a minute.

### 5.5 Optional: an address for questions

`SUPPORT_ADDRESS` is not set by default, and the mails then say "If you have questions, contact IMPF-AI."  Add it under
`[vars]` in `cloud/console/wrangler.toml` — `SUPPORT_ADDRESS = "support@impf.ai"`, an address that receives mail — and
they say "Questions: write to support@impf.ai."

---

## Part 6. Turnstile

Turnstile stands before every step that sends mail — registering, signing in by email, changing an address — so that
a script cannot spend the day's mail for everyone.  Registration is opened only with it.

### 6.1 The widget

1. Dashboard → **Turnstile → Add widget**.
2. **Widget name:** `console.impf.ai`.
3. **Region:** *Rest of World* — the console serves Singapore and the other international regions, and the page
   loads Turnstile from `challenges.cloudflare.com`, the one host its content-security policy allows for it.  The
   region cannot be changed later.
4. **Hostname management:** `console.impf.ai` — the console refuses a token solved on any other host.
5. **Widget mode:** *Managed* — most people see a checkbox at most.
6. **Pre-clearance support:** no.
7. **Create**, then copy the **site key** and the **secret key**.

### 6.2 The two settings

* Variable `TURNSTILE_SITE_KEY` — the site key (public: the page shows it).
* Secret `TURNSTILE_SECRET` — the secret key.

**Run workflow.**  The console's deploy step says `Turnstile: on`.

### 6.3 Check

```bash
curl -sS https://console.impf.ai/auth/config
```

`"turnstile"` is now the site key.  The sign-in page shows the widget under the email field; sign in by email once
(5.4) to see it pass.  The console checks each token with Cloudflare: solved for `console.impf.ai`, for this step
(`signin`, `register` or `email_change`), within its five minutes, and used once.

### 6.4 Turning it off again

Delete both settings and run the workflow: the page stops showing the widget, the console stops asking for it, and
registration closes (Part 7).  The secret stays stored on the Worker, unused; to delete it too: **Workers & Pages →
taochronos-console → Settings → Variables and Secrets** → `TURNSTILE_SECRET` → delete.

---

## Part 7. Opening registration

### 7.1 Before

- [ ] The mail test (5.4) passed for each kind of address you expect.
- [ ] Email previews are off (4.3).
- [ ] `AUTH_MAILS_PER_DAY` is below the account's quota (4.4).
- [ ] Turnstile is on (Part 6).
- [ ] The trial is decided (7.2).

### 7.2 The trial

`CONSOLE_TRIAL_CREDITS` (variable): the credits each new organisation starts with — `100` is ten searches at the
default prices; empty or `0`, none.  At most `TRIALS_PER_DAY` organisations a day are given it (50, in
`cloud/console/wrangler.toml`); those after start with none, and you can grant them credits (8.1).

### 7.3 Open

Variable `CONSOLE_REGISTRATION` = `open`, then **Run workflow**.  The console's deploy step says `registration: open` —
or, if Turnstile is not set, warns that registration stays closed.

```bash
curl -sS https://console.impf.ai/auth/config
```

`"registration":"open"`.

### 7.4 Register yourself

At https://console.impf.ai → **Register**: your address → the code from the mail → **Create a passkey** (or *Not now:
sign in by email* — the mailbox alone then opens the account, and the page says so) → ten recovery codes: keep them →
the overview, with the organisation, its id and the trial.  Under **API keys**: a test key, then a live key — which
needs a passkey's touch in the last five minutes; the page asks for one when it is needed.  Spend the test key as in
3.6.

### 7.5 Closing it again

Delete `CONSOLE_REGISTRATION` (or set it to anything but `open`) and run the workflow.  Those who registered still
sign in; nobody new can.

---

## Part 8. Running it

### 8.1 Credits for someone who registered

The console's overview shows each organisation's id — "Organisation id: org_…".  Ask the developer for it, then, with
`A` and `H` as in 3.6:

```bash
curl -fsS -X POST "$A/orgs/org_…/grants" "${H[@]}" -d '{"credits": 5000, "reference": "invoice-2026-0042", "note": "December"}'
```

A reference counts once per organisation, so a repeated request never adds twice; use one you can find again — an
invoice's number, an order's.  A correction, of either sign: `…/adjustments`, with the same fields.

### 8.2 Day to day

| Task | How |
|---|---|
| A key has leaked | `POST $A/orgs/<org>/keys/<key id>/revoke` (the key's id from `GET $A/orgs/<org>`) — or its owner revokes it in the console.  Refused from then on |
| A project's monthly limit | `POST $A/orgs/<org>/projects/<project>/limit` with `{"monthly_limit": 2000}`; `null` for none |
| An organisation's state | `GET $A/orgs/<org>` |
| Rotate `ACCOUNT_SECRET` | a new value (5.1) → the secret → **Run workflow**.  Only codes in flight stop working: sessions, keys and recovery codes are kept as digests that need no secret |
| Rotate the owner's token | a new token (3.1) → its SHA-256 in `API_ADMIN_TOKEN_SHA256` → **Run workflow**: the old token stops working when the deploy ends |
| Turn the owner's endpoints off | set `API_ADMIN_TOKEN_SHA256` to `off` → **Run workflow**: the API stays deployed; `/admin/…` answers 404 |
| Change prices or limits | `[vars]` in the Worker's `wrangler.toml`, through a pull request (Part 9) |
| A developer reports an error | ask for the answer's `X-Request-Id` (`req_…`) and look for it in `taochronos-api`'s Workers Logs |
| Roll a Worker back | **Workers & Pages →** the Worker **→ Deployments →** an earlier version **→ Rollback** |

### 8.3 What not to do

* **Do not rename or delete the two Workers, or rename their classes** `Account` and `Identity`: every organisation's
  keys and credits, and every person's account, are in their Durable Objects.
* **Do not set variables in the dashboard**: the next deploy replaces them with `wrangler.toml`'s.
* **Do not give another Worker a rate limit with namespace 7321, 7322 or 7331**: bindings with the same namespace id
  share one count across the account.

### 8.4 What the Workers log

Workers Logs is on for both Workers (each Worker's **Logs** in **Workers & Pages**).  No line holds a key, a code, a
cookie or an address.

| Line | Means |
|---|---|
| `api req_…: corpus …` | the corpus failed that call (502, not charged) |
| `api req_…: settle …` | a result could not be settled: its reservation lapses — released, not charged |
| `api req_…: admin token refused` | someone tried the owner's endpoints with another token |
| `mail <template> <code>` | Email Service refused a mail (10.4) |
| `provision org_…: not yet` | a new organisation's account could not be made ready yet; the person's next visit does it |
| `console: …`, `identity storage …`, `account storage …` | an internal error (the person saw a 500) |

---

## Part 9. Every setting

### 9.1 GitHub

**Settings → Secrets and variables → Actions.**

| Name | Kind | Value | Effect |
|---|---|---|---|
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | secrets | the deploy token, the account's id | every Worker's deploy |
| `API_ADMIN_TOKEN_SHA256` | variable | 64 hexadecimal characters (3.1) | deploys the API; the owner's endpoints on (anything else: off) |
| `ACCOUNT_SECRET` | secret | 32 characters or more (5.1) | deploys the console |
| `TURNSTILE_SITE_KEY` | variable | the widget's site key | Turnstile on — with… |
| `TURNSTILE_SECRET` | secret | the widget's secret key | …this; without both, no Turnstile |
| `CONSOLE_REGISTRATION` | variable | `open` | registration open, if Turnstile is on |
| `CONSOLE_TRIAL_CREDITS` | variable | a whole number, up to 9 digits | each new organisation's trial |

### 9.2 The API — `cloud/api/wrangler.toml`, `[vars]`

A value below its least, or not a number, is ignored and the default applies.

| Name | Default | Least | What |
|---|---|---|---|
| `PRICE_EVIDENCE_SEARCH` | 10 | 0 | credits a search costs a live key |
| `PRICE_CITATIONS_VERIFY` | 2 | 0 | credits a verification costs a live key |
| `KEY_RATE_PER_MINUTE` | 60 | 1 | calls a key may make a minute |
| `KEY_CONCURRENCY` | 2 | 1 | a key's calls in flight |
| `ORG_CONCURRENCY` | 4 | 1 | an organisation's calls in flight — its share of the corpus's one instance |
| `TEST_CALLS_PER_DAY` | 100 | 0 | the calls an organisation's test keys make a day, together |
| `HOLD_SECONDS` | 120 | 10 | a reservation nobody settles lapses after this: released, not charged |
| `CORPUS_TIMEOUT_SECONDS` | 60 | 5 (at most 90) | the corpus's time for a call — never more than `HOLD_SECONDS` less 15 — then it is aborted |
| `IDEMPOTENCY_HOURS` | 24 | 1 | how long an `Idempotency-Key`'s answer is kept |
| `MAX_KEYS` | 50 | 1 | an organisation's keys not revoked |
| `ADMIN_TOKEN_SHA256` | empty | — | leave it empty: `deploy.sh` writes the variable's value into the deployed copy |
| `DOCS_URL` | this repository's `cloud/api/README.md` | — | optional: the documentation `GET /v1` points to |

Bindings: `ACCOUNT` — the Durable Object class `Account` (migration `v1`); `IP_LIMIT` — 600 requests a minute from one
address (namespace 7321); `KEY_LIMIT` — 120 a minute for one key (namespace 7322); `CORPUS` — added by `deploy.sh`
when `taochronos-corpus` exists.  The edge's limits are approximate and kept per Cloudflare location; the exact ones
(the key's rate, in flight, credits) are the Account object's.

### 9.3 The console — `cloud/console/wrangler.toml`, `[vars]`

| Name | Default | Least | What |
|---|---|---|---|
| `REGISTRATION` | `off` | — | written by `deploy.sh`: `open` only with `CONSOLE_REGISTRATION` = `open` and Turnstile |
| `RP_ID` | `impf.ai` | — | the passkeys' relying party.  **Changing it makes every passkey unusable** |
| `RP_NAME` | 道乃久 TaoChronos | — | the name a passkey dialog shows |
| `CONSOLE_ORIGIN` | `https://console.impf.ai` | — | the page's origin: changes are taken from it alone, passkeys made for it alone (several: comma-separated) |
| `MAIL_FROM` | `noreply@impf.ai` | — | the sender: on an onboarded domain, and the same as `allowed_sender_addresses` below |
| `MAIL_FROM_NAME` | 道乃久 TaoChronos | — | the sender's name |
| `SUPPORT_ADDRESS` | not set | — | optional (5.5) |
| `CODE_MINUTES` | 10 | 1 | a code's life |
| `FLOW_MINUTES` | 30 | 1 | a verification's life |
| `CODE_ATTEMPTS` | 5 | 1 | the wrong codes a verification takes |
| `RESEND_SECONDS` | 60 | 1 | the wait before a resend |
| `FLOW_SENDS` | 5 | 1 | the mails one verification may send |
| `GRANT_MINUTES` | 15 | 1 | time, after the right code, to finish registering or to give a recovery code |
| `MAILS_PER_ADDRESS_HOUR` | 5 | 1 | verification mails to one address an hour… |
| `MAILS_PER_ADDRESS_DAY` | 10 | 1 | …and a day |
| `STARTS_PER_NETWORK_HOUR` | 20 | 1 | verifications an hour from one IPv4 address or one IPv6 /64 |
| `STARTS_PER_WIDE_NETWORK_HOUR` | 100 | 1 | …from one IPv4 /24 or IPv6 /48 |
| `EMAIL_CHANGES_PER_HOUR` | 5 | 1 | address changes an account an hour |
| `AUTH_MAILS_PER_DAY` | 1000 | 1 | verification mails a day in all (4.4) |
| `SESSION_DAYS` | 30 | 0.01 | a session's longest life |
| `SESSION_IDLE_DAYS` | 7 | 0.01 | a session's life unused |
| `STEPUP_MINUTES` | 5 | 0.1 | how long a passkey's touch counts (live keys, removing a passkey, new recovery codes, an address change, a limit) |
| `FRESH_MINUTES` | 10 | 0.1 | for an account without a passkey: how recent its sign-in must be to add a first passkey or change its address |
| `TRIAL_CREDITS` | 0 | 0 | written by `deploy.sh` from `CONSOLE_TRIAL_CREDITS` |
| `TRIALS_PER_DAY` | 50 | 0 | trials given a day, in all |
| `TURNSTILE_SITE_KEY` | empty | — | written by `deploy.sh` from the variable |

Bindings: `IDENTITY` — the Durable Object class `Identity` (migration `v1`); `ACCOUNT` — `taochronos-api`'s `Account`
class; `AUTH_EMAIL` — Email Service, `allowed_sender_addresses = ["noreply@impf.ai"]`; `AUTH_LIMIT` — 60 changes a
minute from one address (namespace 7331), before the identity object is asked anything.  The Worker's secrets,
put by `deploy.sh`: `ACCOUNT_SECRET`, `TURNSTILE_SECRET`.

---

## Part 10. Troubleshooting

### 10.1 The workflow

| Message | Cause | Fix |
|---|---|---|
| `nothing is deployed until CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are set` | the deploy secrets are missing | [deploy.md 2.3](deploy.md#23-github-secrets-and-variables) |
| `the API is not deployed until the variable API_ADMIN_TOKEN_SHA256 is set` | — | 3.1–3.2 |
| `the console is not deployed until the secret ACCOUNT_SECRET (32+ characters) is set` | missing, or shorter than 32 | 5.1 |
| `API_ADMIN_TOKEN_SHA256 is not 64 hex characters: the owner's endpoints stay off` | a typo, or a value with spaces in it | 3.1 (the API is deployed all the same) |
| `the full corpus's Worker is not deployed: every paid call is answered 503` | no `taochronos-corpus` on the account | [deploy.md Part 3](deploy.md#part-3-the-whole-corpus), then run again |
| `CONSOLE_REGISTRATION is open but Turnstile is not set …` | — | Part 6 |
| `externally managed DNS records`, or a Custom Domain refused | `api` or `console` has a DNS record of its own | delete that record (2.1), run again |
| `Authentication error [code: 10000]` | the token or the account id is wrong | [deploy.md 2.2](deploy.md#22-the-cloudflare-deploy-token) |
| `No access to the specified resource` | the token's zone resources lack `impf.ai` | edit the token |
| the console's deploy fails on its `ACCOUNT` binding | the API's deploy did not succeed | the API's step first |
| the console's deploy refused at the `send_email` binding | a permission (it names one), or the sending domain | 2.2, or 4.2 |
| the step **The developer API as built, end to end** fails | the API as built failed a check (the log lists it) | not configuration: nothing was deployed |

### 10.2 What a developer's program sees

| Answer | Cause | Fix |
|---|---|---|
| 503 `corpus`, `Retry-After` | the corpus is starting or busy — or not bound | wait; 3.5 |
| 502 `corpus` | the corpus failed (nothing charged) | the corpus's logs |
| 503 `accounts` | the organisation's object could not be asked | retry; Workers Logs if it lasts |
| 401 `invalid_key` | a key mistyped, cut short, or of no organisation | the key as it was shown |
| 401 `revoked_key`, `expired_key` | — | a new key |
| 402 `credits`, `project_limit` | not enough credits; the project's month spent | 8.1; 8.2 |
| 429 `rate`, `concurrency`, `test_allowance`, `address` | a key's minute, calls in flight, the test keys' day, the edge's per-address limit | 9.2 |
| 404 on `/admin/…` | the owner's endpoints are off | 3.2–3.3 |
| 401 `admin` | not the token whose SHA-256 is set — often hashed with `echo` | 3.1 |

### 10.3 What a person sees in the console

| Message | Cause | Fix |
|---|---|---|
| "The service is unavailable: try later." at every step | the Worker has no `ACCOUNT_SECRET` | 5.1–5.2 |
| "Registration is closed for now." | registration off | Part 7 |
| "The human check failed: please retry." | the token's five minutes passed, it was used before, or the widget is not for `console.impf.ai` | wait for the widget to refresh, then send again; 6.1, step 4 |
| "Wrong origin." | the page was opened at another address than `CONSOLE_ORIGIN` | https://console.impf.ai |
| "Today's verification mail is spent: try tomorrow." | `AUTH_MAILS_PER_DAY` reached | it resets at 00:00 UTC; 4.4 |
| "Too many requests from this network: try later." | 20 verifications an hour from one address or /64, 100 from a /24 or /48, or 60 changes a minute | a team behind one address: raise `STARTS_PER_NETWORK_HOUR` |
| "Too much mail to this address: try later." | five an hour, ten a day | wait |
| a passkey dialog fails at once | the page is on a host outside `RP_ID` | https://console.impf.ai |
| no mail | — | 10.4 |

### 10.4 Mail that does not arrive

| In the console's Workers Logs | Means | Fix |
|---|---|---|
| `mail … E_SENDER_DOMAIN_NOT_AVAILABLE`, `E_SENDER_DOMAIN_NOT_CONFIGURED` | `MAIL_FROM`'s domain is not onboarded, or not verified yet | 4.2 |
| `mail … E_SENDER_NOT_VERIFIED` | `MAIL_FROM` is not in `allowed_sender_addresses` | make them the same (9.3) |
| `mail … E_RECIPIENT_PLAN_RESTRICTED` | the account is not on Workers Paid: verified addresses only | 2.1 |
| `mail … E_RECIPIENT_SUPPRESSED` | the address bounced or complained before | the Activity log; the person uses another address |
| `mail … E_ACCOUNT_SUSPENDED` | — | Cloudflare's support |
| `mail … no_binding` | the Worker has no `AUTH_EMAIL` binding | it is in `wrangler.toml`: run the workflow again |
| `mail … no_answer`, or another code | a passing failure: tried again, four times at most, never past the mail's time | if it lasts: the quota (4.4) |
| no line; the Activity log says *Delivered* | delivered: the receiving side filed it | the spam folder, an institution's filter |
| no line; the Activity log says *Delivery failed* | the receiving server refused it | its reason in the Activity log |

---

## Part 11. Checking it on your own computer

What the workflow checks, and the console in a real browser besides — Linux or WSL, with the Rust toolchain
(`rust/rust-toolchain.toml`) and Node 22.  The tools, pinned:

```bash
rust/platform/build.sh --install
```

```bash
(cd cloud/api && npm ci --ignore-scripts --no-audit --no-fund) && (cd cloud/console && npm ci --ignore-scripts --no-audit --no-fund)
```

```bash
rust/platform/build.sh api && rust/platform/build.sh console
```

The API, in local workerd beside a stand-in corpus:

```bash
cloud/api/test/run.sh
```

The console in Chromium with a virtual authenticator — registration by code and passkey, recovery codes, keys, the
address changes — then its key spent on the API (needs Playwright with Chromium):

```bash
cloud/console/test/run.sh
```

No mail leaves: local workerd writes each one to a file, where the test reads its code.  Turnstile is off locally.
The core's own tests and checks: [rust/platform/README.md](../rust/platform/README.md).
