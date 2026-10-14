// The Worker behind https://chat.impf.ai: the site and its API (site.js), and the sentinel's memory of visitors (a Durable
// Object over security/sentinel.js; with the private bucket ARCHIVE it drains its events there: security/archive.js).
// Deployed by .github/workflows/site.yml.

import { DurableObject } from "cloudflare:workers";
import { Drainer, EVENTS } from "../../../security/archive.js";
import { WatchCore } from "../../../security/sentinel.js";
import { UsageCore } from "../../../security/usage.js";
import { handle } from "./site.js";

export class Watch extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new WatchCore(ctx.storage.sql);
    this.counts = new UsageCore(ctx.storage.sql);
    this.drainer = new Drainer(ctx.storage, env.ARCHIVE, { store: this.core, prefix: EVENTS("site"), field: "event", extra: { source: "site" } });
  }

  /** The sentinel's events, into the archive's bucket (security/archive.js). */
  async alarm() {
    await this.drainer.run();
  }

  /** The pages opened, by day and place, for the settings' 统计 pane (security/usage.js). */
  usage(counts, seen, today) {
    return this.counts.add(counts, seen, today);
  }

  stats(days, today) {
    return this.counts.stats(days, today);
  }

  async observe(fp, a, extra, cfg) {
    const w = await this.core.observe(fp, a, extra, cfg);
    // an event written (security/sentinel.js: WatchCore.record): the archive drains it a moment later
    if (w && (w.flagged || w.blocked || w.shadow || a?.route === "honeypot" || extra?.kind === "csp")) await this.drainer.arm();
    return w;
  }

  blocked(ip, cfg) {
    return this.core.blocked(ip, cfg);
  }

  async records(after, limit) {
    await this.drainer.arm(); // the collector's hourly look: what waits since the bucket was bound goes too
    return this.core.records(after, limit);
  }

  remove(through) {
    return this.core.remove(through);
  }

  summary() {
    return this.core.summary();
  }
}

const local = new Map(); // this instance's memory of its readers between round trips to the object (site.js: consult)
const usage = { counts: new Map(), visitors: new Map(), pending: false }; // the pages opened, until they go to the object (site.js: tally)

export default {
  fetch(request, env, ctx) {
    const watch = () => env.WATCH.get(env.WATCH.idFromName("watch"));
    return handle(request, env, {
      local,
      usage,
      // per visitor and Cloudflare location, over a minute (wrangler.toml: [[ratelimits]]); without the binding, no limit
      limit: async (kind, key) => {
        const binding = kind === "call" ? env.CALL_LIMIT : env.READ_LIMIT;
        if (!binding) return true;
        const { success } = await binding.limit({ key });
        return success;
      },
      // the sentinel's memory (wrangler.toml: [[durable_objects.bindings]]); without the binding, nothing is recorded
      watch: env.WATCH ? {
        observe: (fp, a, extra, cfg) => watch().observe(fp, a, extra, cfg),
        blocked: (ip, cfg) => watch().blocked(ip, cfg),
        records: (after, limit) => watch().records(after, limit),
        remove: (through) => watch().remove(through),
        summary: () => watch().summary(),
        usage: (counts, seen, today) => watch().usage(counts, seen, today),
        stats: (days, today) => watch().stats(days, today),
      } : null,
      // work that may finish after the answer went out (a note of a request)
      defer: (promise) => ctx.waitUntil(Promise.resolve(promise).catch((err) => console.error("deferred", err?.name || "Error"))),
      now: () => Date.now(),
    });
  },
};
