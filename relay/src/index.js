// The Worker: the relay (relay.js) and its two Durable Objects — the counters that limit use, and the conversation
// records waiting for the repository's collector.  Deployed by .github/workflows/relay.yml (relay/README.md).

import { DurableObject } from "cloudflare:workers";
import { handle } from "./relay.js";
import { LimiterCore, LogBookCore } from "./state.js";

export class Limiter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.core = new LimiterCore(ctx.storage.sql);
  }

  hit(who, kind, limits) {
    return this.core.hit(who, kind, limits);
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
  async fetch(request, env) {
    const limiter = () => env.LIMITER.get(env.LIMITER.idFromName("limits"));
    const book = () => env.LOGBOOK.get(env.LOGBOOK.idFromName("records"));
    return handle(request, env, {
      limit: (who, kind, limits) => limiter().hit(who, kind, limits),
      logbook: {
        add: (record, received, keep) => book().add(record, received, keep),
        records: (after, limit) => book().records(after, limit),
        remove: (through) => book().remove(through),
      },
      fetch: (input, init) => fetch(input, init),
      now: () => Date.now(),
    });
  },
};
