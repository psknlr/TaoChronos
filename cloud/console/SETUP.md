# The account console · 控制台的部署

`https://console.impf.ai` — where a developer registers with their email address, makes a passkey, keeps recovery
codes, and makes the API keys of their organisation.  A Cloudflare Worker in Rust (`rust/platform/console`); its page
(`rust/platform/console/public`) is served by it.  Why it is built as it is:
[ADR 0038](../../docs/adr/0038-accounts-keys-and-credits.md).  The developer API it makes keys for:
[cloud/api/README.md](../api/README.md).

**Setting it up — every step, every setting, and what to do when something goes wrong:
[docs/platform.md](../../docs/platform.md).**  The platform workflow (`.github/workflows/platform.yml`) deploys the API
once `API_ADMIN_TOKEN_SHA256` is set and the console once `ACCOUNT_SECRET` is, with registration **off**.  In order:

1. **The API:** the variable `API_ADMIN_TOKEN_SHA256`, the SHA-256 of the owner's token (Part 3).
2. **Email Service:** onboard the sending domain — mind the DMARC record it may add — and **turn its email previews
   off before anything is sent**; ask Cloudflare for the account's daily quota (it is published nowhere) and set
   `AUTH_MAILS_PER_DAY` below it (Part 4).
3. **The console:** the secret `ACCOUNT_SECRET`, 32 characters or more; then the mail test, which creates nothing
   (Part 5).
4. **Turnstile:** a widget for `console.impf.ai`, region *Rest of World*; the variable `TURNSTILE_SITE_KEY` and the
   secret `TURNSTILE_SECRET` (Part 6).
5. **Registration:** `CONSOLE_REGISTRATION` = `open` — kept closed without Turnstile — and `CONSOLE_TRIAL_CREDITS` if a
   new organisation is given a trial (Part 7).

## What a person can do there

Register with a code sent to their address; make a passkey (or not: the mailbox then opens the account, and the page
says so); keep ten recovery codes; sign in with the passkey alone, or with a code and — when a passkey guards the
account — a recovery code; see and end their sessions; change their address (a code to the new one, a notice to the
old; an address that already has an account is sent a notice instead, and the page answers alike either way); add and
remove passkeys; make test keys, and live keys after a passkey's touch — each key theirs, its calls among their own
five a day; see what is left of today's five and their latest requests, their organisation's credits and usage by
day, and their account id (the security page), for the owner to name them by.  What is kept of them: ADR 0038,
*Consequences*, and ADR 0039.

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
authenticator (registration by code and passkey, recovery codes, the trial, a live key, a passkey sign-in, a sign-in by
the mailbox and a recovery code, a move to an address another account has and to a new one, a change from another
origin refused), and spends the key it made on the API.  It needs Playwright with Chromium, which this
repository does not pin.  No mail leaves: local workerd writes each one to a file, where the test reads its code.
