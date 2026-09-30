# ADR 0012 — 道乃久默认服务: a relay holds the key; conversations recorded only with consent

**Status:** accepted · 2026-09-28

## Context

The published page (GitHub Pages, now at `chat.impf.ai`; the repository is private) asked every visitor for an API key
of their own.  IMPF-AI wants visitors to ask at once on its MiniMax key, the key stored encrypted and never shown, and the
conversations of the test period returned to the repository.

A static page cannot hold a key: whatever encoding it ships in, the browser must decrypt it and send it in clear to the
provider, where any visitor reads it in the developer tools.  Nor can a static page write to a private repository: the
token it would need is a key of the same kind, and one that opens the repository.

## Decision

1. **A relay, not the page, holds the key.**  `relay/` is a Cloudflare Worker (`chat-api.impf.ai`; IMPF-AI's DNS is on
   Cloudflare) that forwards the page's OpenAI-format calls to MiniMax with the key as a Worker secret.  The key reaches
   Cloudflare from the repository's Actions secrets at deployment (`.github/workflows/relay.yml`); it is in no file, page
   or log.  The page sends no key to the relay.
2. **The relay limits what it forwards**: the page's origins; the allowed models; output capped; per visitor per minute
   and per day, and in all per day (Durable Object counters keyed by a hash of address and day — no address is stored).
   The limits bound what an abuser can spend; origin checks only keep other web pages out.
3. **The page uses it when it answers.**  The build names the relay (`site.json`); the page reads its health on load and
   makes 道乃久默认服务 the model of a visitor who has none; when the relay is down the page is what it was (own key).
4. **Records only with consent.**  Visitors' questions may carry health information, so recording is opt-in: before the
   first question the page says what is recorded and asks; the choice is the visitor's, kept in their browser and
   changeable at any time.  A record is one compact object per finished turn — question, answer, tools, the citation
   checks, model, usage — never a key, the settings or an address; the relay keeps only those fields.
5. **The relay never holds a GitHub token.**  It stores records (a second Durable Object); the repository pulls them
   (`.github/workflows/chat-logs.yml`, hourly, with its own `GITHUB_TOKEN` and a collector token shared with the relay),
   commits them to `data/chat-logs/` and only then lets the relay delete them.  A compromised relay can leak waiting
   records, not the repository.
6. The site carries the texts' attribution itself (`attribution.html`): links into a private repository would break the
   licence's credit for visitors.
7. **The page names no vendor** (IMPF-AI's choice): the default service appears as 道乃久默认服务 / Tao-R1 wherever a model
   would be named, MiniMax's presets are not listed, and the consent notice speaks of recording to the institute's server
   (where the records are kept is IMPF-AI's to decide; what is recorded, and why, the notice states).  The standing
   instructions keep the underlying model, so the assistant, asked what it is built on, answers truthfully.  (Superseded
   by [ADR 0014](0014-identity-fixed-reply.md): the instructions no longer name it, the assistant neither names nor denies
   it, and a question only about who answers gets a fixed reply from the page.)

## Consequences

- IMPF-AI sets four secrets once (Cloudflare token and account, the MiniMax key, the collector token) and runs the relay
  workflow (`relay/SETUP.md`); until then nothing changes for visitors.
- Cost is bounded by the relay's daily totals and by the MiniMax plan.  A Token Plan (subscription) key serves one
  account holder within 5-hour and weekly windows; a pay-as-you-go key, which spends only the balance paid in, suits a
  public site better.
- The records live in the private repository.  Making the repository public requires moving `data/chat-logs/` first.
- Records arrive within the hour, not at once; a failed push leaves them on the relay for the next run.
