// The Worker behind https://chat.impf.ai: the site and its API (site.js), and the sentinel's memory of visitors (a Durable
// Object over security/sentinel.js; with the private bucket ARCHIVE it drains its events there: security/archive.js).
// The same object keeps the activity ledger's outbox (security/ledger.js) when the Worker has the ledger's key and its
// registry (ACTIVITY_KEY, ACTIVITY_DB), and drains it into the registry and the archive from the same alarm.
// Deployed by .github/workflows/site.yml.

import { DurableObject } from "cloudflare:workers";
import { Drainer, EVENTS } from "../../../security/archive.js";
import { LedgerCore, LedgerDrainer } from "../../../security/ledger.js";
import { WatchCore } from "../../../security/sentinel.js";
import { UsageCore, usageConfig } from "../../../security/usage.js";
import { ledgerConfig } from "../../../security/visitor.js";
import { handle } from "./site.js";

export class Watch extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new WatchCore(ctx.storage.sql);
    this.counts = new UsageCore(ctx.storage.sql);
    this.drainer = new Drainer(ctx.storage, env.ARCHIVE, { store: this.core, prefix: EVENTS("site"), field: "event", extra: { source: "site" } });
    // the activity ledger's outbox, and what empties it (security/ledger.js): nothing without the key and the registry
    this.ledgerConfig = ledgerConfig(env);
    this.ledger = new LedgerCore(ctx.storage.sql, "site");
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

  /** Events of the activity ledger, from an instance of the Worker (site.js: record); lost: how many it could not bring
   * before. */
  async activity(events, lost = 0) {
    if (!this.ledgerDrain.on) return;
    const now = Date.now();
    for (const event of Array.isArray(events) ? events.slice(0, 1000) : []) this.ledger.note(event, now, this.ledgerConfig.keep);
    this.ledger.bump("lost", Math.max(0, Math.floor(Number(lost) || 0)));
    await this.ledgerDrain.arm(now);
  }

  ledgerHealth() {
    return this.ledger.health();
  }

  /** The pages opened, by day and place: the owner's daily counts (security/usage.js). */
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
const ledger = { events: [], sums: new Map(), pending: false, lost: 0 }; // the ledger's events, until they go to the object (site.js: record)

export default {
  fetch(request, env, ctx) {
    const watch = () => env.WATCH.get(env.WATCH.idFromName("watch"));
    return handle(request, env, {
      local,
      usage,
      ledger,
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
        activity: (events, lost) => watch().activity(events, lost),
        ledgerHealth: () => watch().ledgerHealth(),
      } : null,
      // work that may finish after the answer went out (a note of a request)
      defer: (promise) => ctx.waitUntil(Promise.resolve(promise).catch((err) => console.error("deferred", err?.name || "Error"))),
      now: () => Date.now(),
    });
  },
};
