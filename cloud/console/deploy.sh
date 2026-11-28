#!/usr/bin/env bash
# Deploys the account console (taochronos-console: console.impf.ai), built by rust/platform/build.sh console, after the
# developer API (whose Account class it binds), then gives it its secrets.  The owner's choices come from the
# repository's variables: registration open or not, a new account's trial, Turnstile's site key.  Run by
# .github/workflows/platform.yml.  SETUP.md says what the account must have first (Email Service's sending domain, its
# previews off).
# Environment: CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, ACCOUNT_SECRET (32+ characters); optional: CONSOLE_REGISTRATION
# (open), CONSOLE_TRIAL_CREDITS (a whole number), TURNSTILE_SITE_KEY with TURNSTILE_SECRET.
set -euo pipefail
cd "$(dirname "$0")"
[ -f ../../rust/platform/console/build/worker/shim.mjs ] || { echo "not built: rust/platform/build.sh console" >&2; exit 1; }
secret="$(printf '%s' "${ACCOUNT_SECRET:-}" | tr -d '[:space:]')"
[ "${#secret}" -ge 32 ] || { echo "::error::ACCOUNT_SECRET must be at least 32 characters" >&2; exit 1; }
cp wrangler.toml wrangler.deploy.toml
site_key="$(printf '%s' "${TURNSTILE_SITE_KEY:-}" | tr -d '[:space:]')"
turnstile="$(printf '%s' "${TURNSTILE_SECRET:-}" | tr -d '[:space:]')"
turnstile_on=0
if [[ "$site_key" =~ ^[0-9A-Za-z_-]{8,100}$ ]] && [ -n "$turnstile" ]; then turnstile_on=1; fi
# registration is opened only with Turnstile before it: without it, a few networks' allowances are enough to spend the
# day's verification mail for everyone (docs/adr/0038-accounts-keys-and-credits.md)
if [ "${CONSOLE_REGISTRATION:-}" = "open" ]; then
  if [ "$turnstile_on" = 1 ]; then
    sed -i 's/^REGISTRATION = "off"$/REGISTRATION = "open"/' wrangler.deploy.toml
    echo "registration: open"
  else
    echo "::warning::CONSOLE_REGISTRATION is open but Turnstile is not set (TURNSTILE_SITE_KEY, TURNSTILE_SECRET): registration stays closed"
  fi
fi
if [[ "${CONSOLE_TRIAL_CREDITS:-}" =~ ^[0-9]{1,9}$ ]]; then
  sed -i "s/^TRIAL_CREDITS = \"0\"$/TRIAL_CREDITS = \"$CONSOLE_TRIAL_CREDITS\"/" wrangler.deploy.toml
fi
if [ "$turnstile_on" = 1 ]; then
  sed -i "s/^TURNSTILE_SITE_KEY = \"\"$/TURNSTILE_SITE_KEY = \"$site_key\"/" wrangler.deploy.toml
  echo "Turnstile: on"
fi
npx --no -- wrangler deploy --config wrangler.deploy.toml
printf '%s' "$secret" | npx --no -- wrangler secret put ACCOUNT_SECRET --config wrangler.deploy.toml
if grep -q '^TURNSTILE_SITE_KEY = "[^"]' wrangler.deploy.toml; then
  printf '%s' "$turnstile" | npx --no -- wrangler secret put TURNSTILE_SECRET --config wrangler.deploy.toml
fi
