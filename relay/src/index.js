// The Worker: the relay (relay.js) and its two Durable Objects — the counters that limit use together with the sentinel's
// memory of visitors (security/sentinel.js), and the conversation records waiting for the repository's collector.  With
// the private bucket ARCHIVE (security/archive.js), each object drains what it keeps waiting into the bucket instead.
// The visitors' sponsorships (their own API keys, encrypted: relay/src/sponsors.js) are a third object, apart from the
// records: nothing drains them anywhere.  The counters' object also remembers which turn a call belongs to (a question
// is counted once however many calls it takes) and, with the ledger's key and registry (ACTIVITY_KEY, ACTIVITY_DB),
// keeps the activity ledger's outbox and drains it from the same alarm (security/ledger.js).
// Deployed by .github/workflows/relay.yml (relay/README.md).

import { DurableObject } from "cloudflare:workers";
import { Drainer, EVENTS, RECORDS } from "../../security/archive.js";
import { LedgerCore, LedgerDrainer } from "../../security/ledger.js";
import { WatchCore } from "../../security/sentinel.js";
import { UsageCore, usageConfig } from "../../security/usage.js";
import { ledgerConfig } from "../../security/visitor.js";
import { evented, gateCall, logged, turnFinished, turnRecorded } from "./gate.js";
import { handle, placedFetch } from "./relay.js";
import { SponsorBookCore } from "./sponsors.js";
import { LimiterCore, LogBookCore } from "./state.js";

export class Limiter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new LimiterCore(ctx.storage.sql);
    this.watch = new WatchCore(ctx.storage.sql);
    this.usage = new UsageCore(ctx.storage.sql);
    this.drainer = new Drainer(ctx.storage, env.ARCHIVE, { store: this.watch, prefix: EVENTS("relay"), field: "event", extra: { source: "relay" } });
    // which turn a call belongs to, and — with the ledger's key and registry — the activity ledger's outbox and what
    // empties it (security/ledger.js)
    this.ledgerConfig = ledgerConfig(env);
    this.ledger = new LedgerCore(ctx.storage.sql, "relay");
    this.ledgerDrain = new LedgerDrainer(ctx.storage, this.ledger, { db: this.ledgerConfig.on ? env.ACTIVITY_DB : null, bucket: env.ARCHIVE,
      cfg: this.ledgerConfig, offset: usageConfig(env).offset });
  }

  /** The sentinel's events into the archive's bucket (security/archive.js), and the ledger's outbox into its registry
   * and the archive: one alarm for both, each asking for the next when it needs one. */
  async alarm() {
    await this.drainer.run();
    try {
      await this.ledgerDrain.run();
    } catch (err) {
      console.error("ledger", "alarm", err?.name || "Error");
    }
  }

  hit(who, kind, limits) {
    return this.core.hit(who, kind, limits);
  }

  /** One round trip for a call: the sentinel sees the request (and may refuse it), then the counters; the turn the
   * call belongs to, its question counted once, and the ledger's events of it (gate.js: gateCall, where each argument
   * is said). */
  async gate(args) {
    const now = Date.now();
    if (args.activity?.ledger && !this.ledgerDrain.on) args = { ...args, activity: { ...args.activity, ledger: false } }; // nowhere to drain it to
    const out = await gateCall(this, args, now);
    if (evented(out.watch, args.a, { shape: args.shape, status: args.status })) await this.drainer.arm(now);
    if (args.activity?.ledger) await this.ledgerDrain.arm(now);
    return out;
  }

  // ---- the activity ledger (security/ledger.js): each a no-op without it
  /** How a model call ended and what it cost (relay.js: settle). */
  async settle(outcome) {
    if (!this.ledgerDrain.on) return;
    this.ledger.settle(outcome, Date.now(), { offset: this.ledgerDrain.offset, keep: this.ledgerConfig.keep });
    await this.ledgerDrain.arm();
  }

  /** A turn's end, as the page tells it (POST /v1/activity). */
  async finished(act, key, info) {
    if (!this.ledgerDrain.on) return;
    const now = Date.now();
    turnFinished(this.ledger, act, key, info, now, this.ledgerConfig);
    await this.ledgerDrain.arm(now);
  }

  /** A conversation record taken in for a turn (POST /v1/logs). */
  async recorded(act, key, info) {
    if (!this.ledgerDrain.on) return;
    const now = Date.now();
    turnRecorded(this.ledger, act, key, info, now, this.ledgerConfig);
    await this.ledgerDrain.arm(now);
  }

  /** Anything else worth an event: a feedback, a sponsorship. */
  async logged(act) {
    if (!this.ledgerDrain.on) return;
    logged(this.ledger, { ...act, ledger: true, keep: this.ledgerConfig.keep });
    await this.ledgerDrain.arm();
  }

  ledgerHealth() {
    return this.ledger.health();
  }

  /** The owner's daily counts (security/usage.js): read with the collector's token alone (relay.js: stats). */
  stats(days, today) {
    return this.usage.stats(days, today);
  }

  async observe(fp, a, extra, cfg) {
    const w = await this.watch.observe(fp, a, extra, cfg);
    if (evented(w, a, extra)) await this.drainer.arm();
    // a request noted is an event of the ledger too, with what the sentinel made of it
    if (extra?.activity && this.ledgerDrain.on) {
      logged(this.ledger, { ...extra.activity, fp, a, w, status: extra.status, ledger: true, keep: this.ledgerConfig.keep });
      await this.ledgerDrain.arm();
    }
    return w;
  }

  spend(who, kind, tokens) {
    return this.core.spend(who, kind, tokens);
  }

  async records(after, limit) {
    await this.drainer.arm(); // the collector's hourly look: what waits since the bucket was bound goes too
    return this.watch.records(after, limit);
  }

  remove(through) {
    return this.watch.remove(through);
  }

  summary() {
    return this.watch.summary();
  }
}

export class LogBook extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new LogBookCore(ctx.storage.sql);
    this.drainer = new Drainer(ctx.storage, env.ARCHIVE, { store: this.core, prefix: RECORDS, field: "record" });
  }

  /** The records, into the archive's bucket (security/archive.js). */
  async alarm() {
    await this.drainer.run();
  }

  async add(record, received, keep) {
    const id = this.core.add(record, received, keep);
    if (id !== null) await this.drainer.arm();
    return id;
  }

  async records(after, limit) {
    await this.drainer.arm();
    return this.core.records(after, limit);
  }

  remove(through) {
    return this.core.remove(through);
  }
}

export class SponsorBook extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new SponsorBookCore(ctx.storage.sql);
  }

  add(row, keep) {
    return this.core.add(row, keep);
  }

  list() {
    return this.core.list();
  }

  get(id) {
    return this.core.get(id);
  }

  remove(id) {
    return this.core.remove(id);
  }
}

/** Where a model service is called from when not from where the Worker runs (relay.js: UPSTREAM_VIA for the default
 * model, OPENAI_LOCATION for the second): a Durable Object created with that location hint lives there, and so do the
 * calls it makes.  The Worker runs at the Cloudflare location the visitor reached — for a visitor in mainland China one
 * in Europe or North America, far from a model service in mainland China — and OpenAI refuses some regions such a
 * location may be in.  It keeps nothing, and forwards only to the two model services' own hosts (placedFetch). */
export class Egress extends DurableObject {
  fetch(request) {
    return placedFetch(request, this.env, (input, init) => fetch(input, init));
  }
}

// what this instance remembers of the places the default model is asked from, between calls (relay.js, reach): the one
// that was just silent, failing or refusing is asked last for a while.  An instance serves one Cloudflare location, and
// it is that location's own path to the model service that fails; another instance finds out for itself
const ROUTES = new Map();

export default {
  async fetch(request, env, ctx) {
    const limiter = () => env.LIMITER.get(env.LIMITER.idFromName("limits"));
    const book = () => env.LOGBOOK.get(env.LOGBOOK.idFromName("records"));
    const sponsors = () => env.SPONSORS.get(env.SPONSORS.idFromName("sponsors"));
    return handle(request, env, {
      limit: (who, kind, limits) => limiter().hit(who, kind, limits),
      gate: (args) => limiter().gate(args),
      observe: (fp, a, extra, cfg) => limiter().observe(fp, a, extra, cfg),
      spend: (who, kind, tokens) => limiter().spend(who, kind, tokens),
      stats: (days, today) => limiter().stats(days, today),
      // the activity ledger's outbox (the Limiter object keeps it: security/ledger.js)
      ledger: {
        settle: (outcome) => limiter().settle(outcome),
        finished: (act, key, info) => limiter().finished(act, key, info),
        recorded: (act, key, info) => limiter().recorded(act, key, info),
        logged: (act) => limiter().logged(act),
        health: () => limiter().ledgerHealth(),
      },
      watch: {
        observe: (fp, a, extra, cfg) => limiter().observe(fp, a, extra, cfg),
        records: (after, limit) => limiter().records(after, limit),
        remove: (through) => limiter().remove(through),
        summary: () => limiter().summary(),
      },
      logbook: {
        add: (record, received, keep) => book().add(record, received, keep),
        records: (after, limit) => book().records(after, limit),
        remove: (through) => book().remove(through),
      },
      sponsors: {
        add: (row, keep) => sponsors().add(row, keep),
        list: () => sponsors().list(),
        get: (id) => sponsors().get(id),
        remove: (id) => sponsors().remove(id),
      },
      // per visitor and Cloudflare location, over ten seconds (wrangler.toml: [[ratelimits]]); without the binding, no gate
      burst: async (key) => {
        if (!env.BURST) return true;
        const { success } = await env.BURST.limit({ key });
        return success;
      },
      // work that may finish after the answer went out (a note of a request, the tokens an answer cost)
      defer: (promise) => ctx.waitUntil(Promise.resolve(promise).catch((err) => console.error("deferred", err?.name || "Error"))),
      fetch: (input, init) => fetch(input, init),
      // a call made from a Durable Object placed at `location` (Egress).  The visitor leaving still ends it: the
      // stream it answers with is cancelled (a signal does not cross into the object)
      egress: (location, input, init = {}) => {
        const { signal, ...rest } = init;
        return env.EGRESS.get(env.EGRESS.idFromName(`egress-${location}`), { locationHint: location }).fetch(input, rest);
      },
      routes: ROUTES,
      now: () => Date.now(),
    });
  },
};
