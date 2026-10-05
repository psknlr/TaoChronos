// The Worker: the relay (relay.js) and its two Durable Objects — the counters that limit use together with the sentinel's
// memory of visitors (security/sentinel.js), and the conversation records waiting for the repository's collector.
// Deployed by .github/workflows/relay.yml (relay/README.md).

import { DurableObject } from "cloudflare:workers";
import { WatchCore } from "../../security/sentinel.js";
import { handle } from "./relay.js";
import { LimiterCore, LogBookCore } from "./state.js";

export class Limiter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new LimiterCore(ctx.storage.sql);
    this.watch = new WatchCore(ctx.storage.sql);
  }

  hit(who, kind, limits) {
    return this.core.hit(who, kind, limits);
  }

  /** One round trip for a call: the sentinel sees the request (and may refuse it), then the counters.  `served`: the
   * call is let through only for a caller the relay answered today (a record of the default service's conversation). */
  async gate({ who, kind, limits, fp, a, shape, status, cfg, served, reserve }) {
    const watch = fp && a ? await this.watch.observe(fp, a, { shape, status }, cfg) : null;
    if (watch?.blocked) return { ok: false, reason: "blocked", retry: watch.retry, watch };
    if (served && !this.core.served(who, served)) return { ok: false, reason: "not_served", retry: 0, watch };
    return { ...this.core.hit(who, kind, limits, Date.now(), reserve), watch };
  }

  observe(fp, a, extra, cfg) {
    return this.watch.observe(fp, a, extra, cfg);
  }

  spend(who, kind, tokens) {
    return this.core.spend(who, kind, tokens);
  }

  records(after, limit) {
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
  }

  add(record, received, keep) {
    return this.core.add(record, received, keep);
  }

  records(after, limit) {
    return this.core.records(after, limit);
  }

  remove(through) {
    return this.core.remove(through);
  }
}

export default {
  async fetch(request, env, ctx) {
    const limiter = () => env.LIMITER.get(env.LIMITER.idFromName("limits"));
    const book = () => env.LOGBOOK.get(env.LOGBOOK.idFromName("records"));
    return handle(request, env, {
      limit: (who, kind, limits) => limiter().hit(who, kind, limits),
      gate: (args) => limiter().gate(args),
      observe: (fp, a, extra, cfg) => limiter().observe(fp, a, extra, cfg),
      spend: (who, kind, tokens) => limiter().spend(who, kind, tokens),
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
      // per visitor and Cloudflare location, over ten seconds (wrangler.toml: [[ratelimits]]); without the binding, no gate
      burst: async (key) => {
        if (!env.BURST) return true;
        const { success } = await env.BURST.limit({ key });
        return success;
      },
      // work that may finish after the answer went out (a note of a request, the tokens an answer cost)
      defer: (promise) => ctx.waitUntil(Promise.resolve(promise).catch((err) => console.error("deferred", err?.name || "Error"))),
      fetch: (input, init) => fetch(input, init),
      now: () => Date.now(),
    });
  },
};
