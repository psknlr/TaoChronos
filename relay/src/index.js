// The Worker: the relay (relay.js) and its two Durable Objects — the counters that limit use together with the sentinel's
// memory of visitors (security/sentinel.js), and the conversation records waiting for the repository's collector.  With
// the private bucket ARCHIVE (security/archive.js), each object drains what it keeps waiting into the bucket instead.
// The visitors' sponsorships (their own API keys, encrypted: relay/src/sponsors.js) are a third object, apart from the
// records: nothing drains them anywhere.
// Deployed by .github/workflows/relay.yml (relay/README.md).

import { DurableObject } from "cloudflare:workers";
import { Drainer, EVENTS, RECORDS } from "../../security/archive.js";
import { WatchCore } from "../../security/sentinel.js";
import { UsageCore } from "../../security/usage.js";
import { handle, placedFetch } from "./relay.js";
import { SponsorBookCore } from "./sponsors.js";
import { ANSWERS, LimiterCore, LogBookCore } from "./state.js";

/** Did the sentinel write an event for this request (security/sentinel.js: WatchCore.record)?  Then the archive drains. */
const evented = (w, a, extra = {}) => Boolean(w && (w.flagged || w.blocked || w.shadow || a?.route === "honeypot" || extra.kind === "csp"));

export class Limiter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new LimiterCore(ctx.storage.sql);
    this.watch = new WatchCore(ctx.storage.sql);
    this.usage = new UsageCore(ctx.storage.sql);
    this.drainer = new Drainer(ctx.storage, env.ARCHIVE, { store: this.watch, prefix: EVENTS("relay"), field: "event", extra: { source: "relay" } });
  }

  /** The sentinel's events, into the archive's bucket (security/archive.js). */
  async alarm() {
    await this.drainer.run();
  }

  hit(who, kind, limits) {
    return this.core.hit(who, kind, limits);
  }

  /** One round trip for a call: the sentinel sees the request (and may refuse it), then the counters.  `served`: the
   * call is let through only for a caller the relay answered lately (a record of the default service's conversation;
   * the caller is known by the sentinel's key, which does not change at midnight — yesterday's is tried too for the
   * month's turn).  `question`: a model counted in questions (relay.js, secondChat) — the question is asked first, and
   * counted only with the call it lets through. */
  async gate({ who, kind, limits, fp, a, shape, status, cfg, served, reserve, usage, question }) {
    const now = Date.now();
    const watch = fp && a ? await this.watch.observe(fp, a, { shape, status }, cfg) : null;
    if (evented(watch, a, { shape, status })) await this.drainer.arm(now);
    if (watch?.blocked) return { ok: false, reason: "blocked", retry: watch.retry, watch };
    const keys = fp ? [await WatchCore.who(fp.ip, cfg, now), await WatchCore.who(fp.ip, cfg, now - 86400000)] : [];
    if (served && !(fp ? this.core.wasServed(keys, now) : this.core.served(who, served, now))) return { ok: false, reason: "not_served", retry: 0, watch };
    const q = question ? this.core.question(who, question, now) : null;
    if (q && !q.ok) return { ...q, watch };
    const gate = this.core.hit(who, kind, limits, now, reserve);
    if (gate.ok) q?.commit?.();
    if (gate.ok && ANSWERS.has(kind) && keys.length) this.core.markServed(keys[0], now);
    if (gate.ok && ANSWERS.has(kind) && usage) {
      try { this.usage.call(usage, keys[0]); } catch (err) { console.error("usage", err?.name || "Error"); } // never in a call's way
    }
    return { ...gate, watch };
  }

  /** The counts for the settings' 统计 pane (security/usage.js). */
  stats(days, today) {
    return this.usage.stats(days, today);
  }

  async observe(fp, a, extra, cfg) {
    const w = await this.watch.observe(fp, a, extra, cfg);
    if (evented(w, a, extra)) await this.drainer.arm();
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
