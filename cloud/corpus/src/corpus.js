// The corpus Worker's answers, apart from the container they come from (index.js; tested under Node).
//
// A container is started on demand and sleeps when unused; starting takes seconds.  What the runtime says about itself
// — its info (with the standing instructions) and its tool catalogs — does not change while the deployed version is the
// same, so it is kept (in the Durable Object's storage, per version) and answered at once, even while the container
// sleeps: the page can then begin a conversation at once, and a page asking for it wakes the container, which is up by
// the time the model calls a tool.  Everything else goes to the container.

// What is kept, by path: the key it is kept under, and the one query the container is asked for it.  The key and the
// question always agree, whatever else a request's query says: asked as the request came, `?mode=core&mode=all` was
// kept as the core catalog (the first `mode`) while the runtime answered the full one (it reads the last) — one such
// request before any other, and every page would have been given every tool until the next deployment.
const KEPT = {
  "/api/info": () => ({ key: "info", search: "" }),
  "/api/catalog": (q) => {
    const mode = q.get("mode") || "core";
    return ["core", "all"].includes(mode) ? { key: `catalog:${mode}`, search: `?mode=${mode}` } : null;
  },
};

export const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

/** What the page is told while the container cannot be reached. */
export const unavailable = () =>
  json({ error: "全量语料服务正在启动或暂不可用，请稍后再试", starting: true }, 503, { "Retry-After": "10", "X-TC-Corpus": "unavailable" });

/** What the page is told when this Worker has no container (the account cannot run containers yet): as without it. */
export const none = () =>
  json({ error: "本站的全量语料服务未部署：网页改用内置运行环境的要籍语料", corpus: "none" }, 503, { "X-TC-Corpus": "none" });

/**
 * The Durable Object's answer (call: its fetch).  It throws when its class has no container — the Worker was uploaded
 * but its container was not deployed — or on any other error: the page is then told what it can fall back on.
 */
export async function reach(call) {
  try {
    return await call();
  } catch (err) {
    const message = String(err?.message || err);
    console.error("corpus", message);
    return /containers have not been enabled/i.test(message) ? none() : unavailable();
  }
}

/**
 * A call sent to the container, which is started — and waited for until it listens — only when it is not known to be
 * up.  The start-and-wait is not free once the container runs: each time it asks the container's port again (a round
 * trip to the container) and writes the object's state (a storage write, the object's other requests held meanwhile),
 * and every tool call of every round would pay for it.  A container this object started and found listening, and that
 * still runs, is asked at once; one that does not answer as the runtime does is no longer taken for up, so the next
 * call starts it, or waits for it, again.
 *
 * box: {
 *   up() → boolean                 started and found listening by this object, and still running
 *   mark(up)                       remember that it is, or is not
 *   start() → Promise              start it if it is not running, and wait until it listens (throws when it cannot)
 *   send() → Promise<Response>     the call, to the container
 * }
 */
export async function forwarded(box) {
  if (!box.up()) {
    try {
      await box.start();
      box.mark(true);
    } catch (err) {
      box.mark(false);
      console.error("start", err?.message || err);
      return unavailable();
    }
  }
  let res;
  try {
    res = await box.send();
  } catch (err) {
    box.mark(false); // it went away under the call: the page is told (reach), and the next call starts it again
    throw err;
  }
  if (res.status >= 500 && !(res.headers.get("Content-Type") || "").includes("json")) { // not the runtime's own answer
    box.mark(false);
    return unavailable();
  }
  return res;
}

/**
 * box: {
 *   version,                               the deployed version (the Worker's VERSION: commit and store)
 *   get(key), put(key, value), list(prefix) → Map, delete(keys)       the Durable Object's storage
 *   warm()                                 start the container if it is not running (not waited for)
 *   forward(request) → Promise<Response>   the request to the container, started and waited for
 * }
 */
export async function route(request, box) {
  const url = new URL(request.url);
  const kept = request.method === "GET" && KEPT[url.pathname]?.(url.searchParams);
  if (!kept) return box.forward(request);
  const key = `snap:${box.version}:${kept.key}`;
  const hit = await box.get(key);
  if (hit) {
    box.warm();
    return new Response(hit, { status: 200, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-TC-Corpus": "kept" } });
  }
  url.search = kept.search; // the question the key names, not the request's own
  const res = await box.forward(new Request(url, request));
  if (res.status !== 200) return res;
  const body = await res.text();
  try {
    JSON.parse(body);
  } catch {
    return json({ error: "the corpus answered something that is not JSON" }, 502);
  }
  await box.put(key, body);
  const old = [...(await box.list("snap:")).keys()].filter((k) => !k.startsWith(`snap:${box.version}:`));
  if (old.length) await box.delete(old);
  return new Response(body, { status: 200, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-TC-Corpus": "live" } });
}
