// The corpus Worker's answers, apart from the container they come from (index.js; tested under Node).
//
// A container is started on demand and sleeps when unused; starting takes seconds.  What the runtime says about itself
// — its info (with the standing instructions) and its tool catalogs — does not change while the deployed version is the
// same, so it is kept (in the Durable Object's storage, per version) and answered at once, even while the container
// sleeps: the page can then begin a conversation at once, and a page asking for it wakes the container, which is up by
// the time the model calls a tool.  Everything else goes to the container.

const KEPT = { "/api/info": () => "info", "/api/catalog": (q) => (["core", "all"].includes(q.get("mode") || "core") ? `catalog:${q.get("mode") || "core"}` : null) };

export const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

/** What the page is told while the container cannot be reached. */
export const unavailable = () =>
  json({ error: "全量语料服务正在启动或暂不可用，请稍后再试", starting: true }, 503, { "Retry-After": "10", "X-TC-Corpus": "unavailable" });

/** What the page is told when this Worker has no container (the account cannot run containers yet): as without it. */
export const none = () =>
  json({ error: "本站的全量语料服务未部署：网页在浏览器里运行要籍语料", corpus: "none" }, 503, { "X-TC-Corpus": "none" });

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
  const key = `snap:${box.version}:${kept}`;
  const hit = await box.get(key);
  if (hit) {
    box.warm();
    return new Response(hit, { status: 200, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "X-TC-Corpus": "kept" } });
  }
  const res = await box.forward(request);
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
