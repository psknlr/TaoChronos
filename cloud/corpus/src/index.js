// The corpus Worker: a Durable Object that starts the full corpus's container (Dockerfile) on demand and forwards the
// site's API calls to it (corpus.js).  It has no route and no workers.dev address: only the site's Worker reaches it,
// through its service binding.  Deployed by .github/workflows/site.yml (cloud/README.md).

import { Container } from "@cloudflare/containers";
import { route, unavailable } from "./corpus.js";

const PORT = 8080;
// a container starting from its image: the instance, then Python and the runtime over the full corpus (tens of seconds)
const START = { instanceGetTimeoutMS: 60_000, portReadyTimeoutMS: 180_000, waitInterval: 500 };

const randomToken = () => [...crypto.getRandomValues(new Uint8Array(24))].map((b) => b.toString(16).padStart(2, "0")).join("");

export class Corpus extends Container {
  defaultPort = PORT;
  sleepAfter = "15m";

  constructor(ctx, env) {
    super(ctx, env);
    if (env.SLEEP_AFTER) this.sleepAfter = env.SLEEP_AFTER;
    // the token the container is started with and every forwarded call carries (the container answers nothing without
    // it); kept, so that a container started before this object was last evicted still takes it
    ctx.blockConcurrencyWhile(async () => {
      let token = await ctx.storage.get("token");
      if (!token) {
        token = randomToken();
        await ctx.storage.put("token", token);
      }
      this.token = token;
      this.envVars = { TAOCHRONOS_TOKEN: token };
    });
  }

  async fetch(request) {
    return route(request, {
      version: this.env.VERSION || "unversioned",
      get: (key) => this.ctx.storage.get(key),
      put: (key, value) => this.ctx.storage.put(key, value),
      list: (prefix) => this.ctx.storage.list({ prefix }),
      delete: (keys) => this.ctx.storage.delete(keys),
      warm: () => this.warm(),
      forward: (req) => this.forward(req),
    });
  }

  warm() {
    this.renewActivityTimeout();
    this.startAndWaitForPorts({ ports: PORT, cancellationOptions: START }).catch((err) => console.error("warm", err?.message || err));
  }

  async forward(request) {
    try {
      await this.startAndWaitForPorts({ ports: PORT, cancellationOptions: START });
    } catch (err) {
      console.error("start", err?.message || err);
      return unavailable();
    }
    const headers = new Headers(request.headers);
    headers.set("X-TC-Token", this.token);
    const res = await this.containerFetch(new Request(request, { headers }), PORT);
    return res.status >= 500 && !(res.headers.get("Content-Type") || "").includes("json") ? unavailable() : res;
  }

  onError(error) {
    console.error("container", error?.message || error); // reported; the next call starts it again
  }
}

export default {
  async fetch(request, env) {
    // one instance, placed near the site's readers (a Durable Object stays where it was first created)
    const id = env.CORPUS.idFromName("main");
    return env.CORPUS.get(id, { locationHint: env.LOCATION_HINT || "apac" }).fetch(request);
  },
};
