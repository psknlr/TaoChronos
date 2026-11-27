# The account console · 控制台的部署

`https://console.impf.ai` — where a developer registers with their email address, makes a passkey, keeps recovery
codes, and makes the API keys of their organisation.  A Cloudflare Worker in Rust (`rust/platform/console`); its page
(`rust/platform/console/public`) is served by it.  Why it is built as it is:
[ADR 0038](../../docs/adr/0038-accounts-keys-and-credits.md).  The developer API it makes keys for:
[cloud/api/README.md](../api/README.md).

The platform workflow (`.github/workflows/platform.yml`) builds both Workers, tests the API as built, and deploys:
the API once `API_ADMIN_TOKEN_SHA256` is set, the console once `ACCOUNT_SECRET` is.  The console is deployed with
registration **off**; it is opened by the owner, last, after the steps below.

## 1. Email Service: a sending domain

On Workers Paid (the account's plan since [ADR 0023](../../docs/adr/0023-workers-paid.md)), Email Service sends to any
address; on the Free plan only to verified ones.

1. Dashboard → **Compute → Email Service → Email Sending → Onboard domain**: `impf.ai` (or a subdomain kept for mail
   such as `mail.impf.ai`; then `MAIL_FROM` and `allowed_sender_addresses` in `wrangler.toml` name it).  Cloudflare adds
   its records — MX, SPF and DKIM under `cf-bounce.<domain>`, and DMARC if the domain has none — apart from Email
   Routing's: the inbound mail of `impf.ai` is not changed.
2. **Turn email previews off, before anything is sent.**  New sending domains keep a preview of every message — its
   text, HTML and headers — for about seven days, on by default: a verification code in a body would be kept there.
   The domain → **Settings** → *Enable email preview*: off.  (By API: `PATCH /zones/{zone_id}/email/sending/subdomains/{id}`
   with `{"preview_enabled": false}`.)  A domain is created with previews on and cannot be created without them: turn
   them off at once.
3. **The daily quota.**  Cloudflare publishes no number ("new accounts start with a conservative daily quota and scale
   up over time"); the dashboard shows the account's.  Set the console's `AUTH_MAILS_PER_DAY` (`wrangler.toml`) below
   it: the console then refuses a flow with "today's verification mail is spent" rather than leave a person waiting for
   mail that will not come.
4. A check before the domain carries a sign-up: send yourself a code (step 4 below, with registration still off: sign
   in with an address that has no account sends the "no account" mail) from QQ, 163, Gmail and Outlook addresses, and
   an institution's; see each arrive.  The console's log (Workers Logs: `mail <template> <code>`) names a refusal by its
   code, never an address.

## 2. The secrets and the variables

Repository → **Settings → Secrets and variables → Actions**:

| | Kind | What |
|---|---|---|
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | secrets | as for the other Workers |
| `API_ADMIN_TOKEN_SHA256` | variable | the sha256 of the owner's token for the API's `/admin/…` ([cloud/api/README.md](../api/README.md)) — deploys the API |
| `ACCOUNT_SECRET` | secret | 32+ characters — deploys the console; its codes are derived under it: `openssl rand -base64 48` |
| `CONSOLE_REGISTRATION` | variable | `open` to let anyone register; anything else: off (signing in still works) |
| `CONSOLE_TRIAL_CREDITS` | variable | credits a new organisation is given; empty: none (at most `TRIALS_PER_DAY` a day) |
| `TURNSTILE_SITE_KEY` | variable | Turnstile before every flow that sends mail, with… |
| `TURNSTILE_SECRET` | secret | …its secret: a widget for the hostname `console.impf.ai` |

`ACCOUNT_SECRET` can be changed: only the codes in flight stop working (sessions, keys and recovery codes are kept as
digests that need no key).  The token needs **Workers Scripts: Edit** and **Workers Routes: Edit** for the zone, as the
other Workers' does; the console's `send_email` binding needs Email Service set up as above.

## 3. Deploy

Push to `main` (or run the *platform* workflow): the API first — the console binds its `Account` class — then the
console, then its secrets.  `https://api.impf.ai/v1` and `https://console.impf.ai/auth/config` answer.

## 4. Open registration

When the mail of step 1 arrives everywhere it should: set `CONSOLE_REGISTRATION` to `open` and run the workflow.  To
close it again, unset it: those who registered still sign in.

## What a person can do there

Register with a code sent to their address; make a passkey (or not: the mailbox then opens the account, and the page
says so); keep ten recovery codes; sign in with the passkey alone, or with a code and — when a passkey guards the
account — a recovery code; see and end their sessions; change their address (a code to the new one, a notice to the
old); add and remove passkeys; make test keys, and live keys after a passkey's touch; see their organisation's credits
and usage by day.  What is kept of them: ADR 0038, *Consequences*.

## Checking it here

```bash
rust/platform/build.sh --install
```

```bash
(cd cloud/api && npm ci --ignore-scripts --no-audit --no-fund) && (cd cloud/console && npm ci --ignore-scripts --no-audit --no-fund)
```

```bash
rust/platform/build.sh api && rust/platform/build.sh console
```

```bash
cloud/console/test/run.sh
```

The last one runs both Workers in local workerd beside a stand-in corpus, drives the console in Chromium with a virtual
authenticator (registration by code and passkey, recovery codes, the trial, a live key, a passkey sign-in, a change from
another origin refused), and spends the key it made on the API.  It needs Playwright with Chromium, which this
repository does not pin.  No mail leaves: local workerd writes each one to a file, where the test reads its code.
