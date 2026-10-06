// The sentinel under Node: the fingerprint, the score, the memory (WatchCore on an in-memory SQLite), the endpoints.
// Run: node --test security/test/

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { assess, bodyShape, browserOf, cspReports, DEFAULTS, expectsClientHints, expectsSecFetch, fingerprint, ipKey, isHoneypot, logLine, sentinelConfig,
  serveSecurity, uaClass, WatchCore } from "../sentinel.js";

/** The Durable Object SQL API's shape over node:sqlite. */
function sqlStore() {
  const db = new DatabaseSync(":memory:");
  return {
    exec(query, ...params) {
      const stmt = db.prepare(query);
      const rows = /^\s*select|returning/i.test(query) ? stmt.all(...params) : (stmt.run(...params), []);
      return { toArray: () => rows, one: () => { if (rows.length !== 1) throw new Error(`expected one row, got ${rows.length}`); return rows[0]; } };
    },
  };
}

const T0 = Date.UTC(2026, 9, 5, 8, 0, 0);
const CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36";
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";
const WECHAT = "Mozilla/5.0 (Linux; Android 13; 2211133C Build/TKQ1.220905.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 XWEB/1160065 MMWEBSDK/20231202 MMWEBID/3463 MicroMessenger/8.0.47.2560(0x28002F30)";
const PAGE = "https://chat.impf.ai";

/** A request as the page's browser makes it to the relay. */
function pageRequest(path = "https://chat-api.impf.ai/v1/chat/completions", { ua = CHROME, headers = {}, cf = {}, method = "POST" } = {}) {
  const req = new Request(path, { method, headers: { "User-Agent": ua, Accept: "text/event-stream", "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, br", Origin: PAGE, Referer: `${PAGE}/`, "Sec-Fetch-Site": "same-site", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
    "Sec-CH-UA": '"Chromium";v="129", "Not=A?Brand";v="8"', "Sec-CH-UA-Mobile": "?0", "Sec-CH-UA-Platform": '"Windows"',
    "Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.7", "CF-Ray": "8c1-HKG", ...headers }, body: method === "POST" ? "{}" : undefined });
  req.cf = { asn: 4134, asOrganization: "Chinanet", country: "CN", regionCode: "GD", city: "Guangzhou", colo: "HKG", httpProtocol: "HTTP/2",
    tlsVersion: "TLSv1.3", tlsCipher: "AEAD-AES128-GCM-SHA256", tlsClientHelloLength: 1234, tlsClientExtensionsSha1: "abc=", tlsClientCiphersSha1: "def=",
    clientTcpRtt: 42, clientAcceptEncoding: "gzip, deflate, br, zstd", ...cf };
  return req;
}

const PAGE_BODY = { model: "Tao-R1", messages: [{ role: "system", content: "你是道乃久……" }, { role: "user", content: "桂枝汤主治什么？" }], stream: true,
  tools: [{ type: "function", function: { name: "classics.search" } }], tool_choice: "auto", max_completion_tokens: 8192, stream_options: { include_usage: true } };

// ------------------------------------------------------------------ the request
test("user agents by kind, and what a browser is expected to send", () => {
  assert.equal(uaClass(CHROME), "browser");
  assert.equal(uaClass(IPHONE), "browser");
  assert.equal(uaClass(WECHAT), "browser");
  assert.equal(uaClass("python-requests/2.31.0"), "tool");
  assert.equal(uaClass("Python-urllib/3.11"), "tool");
  assert.equal(uaClass("Go-http-client/1.1"), "tool");
  assert.equal(uaClass("curl/8.4.0"), "tool");
  assert.equal(uaClass("Mozilla/5.0 (compatible; Nuclei - Open-source project)"), "scanner");
  assert.equal(uaClass("Mozilla/5.0 (compatible; CensysInspect/1.1)"), "scanner");
  assert.equal(uaClass("ChatGPT-User/1.0"), "bot");
  assert.equal(uaClass("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"), "bot");
  assert.equal(uaClass("PerplexityBot/1.0"), "bot");
  assert.equal(uaClass(""), "empty");
  assert.equal(uaClass(undefined), "empty");
  assert.equal(uaClass("taochronos-collector/1"), "other");
  assert.equal(uaClass("Mozilla/5.0"), "tool"); // a bare shell of a browser string
  assert.deepEqual(browserOf(CHROME), { engine: "chromium", major: 129, ios: false });
  assert.deepEqual(browserOf(IPHONE), { engine: "webkit", major: 17, ios: true });
  assert.deepEqual(browserOf(WECHAT), { engine: "chromium", major: 116, ios: false });
  assert.equal(browserOf("curl/8"), null);
  assert.equal(expectsSecFetch(browserOf(CHROME)), true);
  assert.equal(expectsSecFetch(browserOf(IPHONE)), true);
  assert.equal(expectsSecFetch(browserOf(IPHONE.replace("OS 17_5", "OS 15_2").replace("Version/17.5", "Version/15.2"))), false);
  assert.equal(expectsClientHints(browserOf(CHROME)), true);
  assert.equal(expectsClientHints(browserOf("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1")), false);
  assert.equal(expectsClientHints(browserOf("Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0")), false);
});

test("scanner paths, and nothing the site serves", () => {
  for (const p of ["/wp-config.php", "/wp-config.php.bak", "/blog/wp-config.php", "/wordpress/wp-config.php", "/wp-json/batch/v1", "/.git/HEAD",
    "/.env", "/.env.production", "/xmlrpc.php", "/phpmyadmin/index.php", "/vendor/phpunit/phpunit/src/Util/PHP/eval-stdin.php", "/actuator/health",
    "/cgi-bin/luci", "/boaform/admin/formLogin", "/HNAP1/", "/index.php", "/admin/login.asp", "/backup.sql", "/.aws/credentials", "/.DS_Store",
    "/server-status", "/owa/auth/logon.aspx", "/id_rsa.pem"]) assert.equal(isHoneypot(p), true, p);
  for (const p of ["/", "/about", "/attribution.html", "/js/worker.js", "/js/app.js", "/css/app.css", "/runtime/corpus.sqlite.xz", "/runtime/boot.json",
    "/pyodide/python_stdlib.zip", "/pyodide/pyodide.asm.wasm", "/runtime/home.zip", "/assets/logo.svg", "/manifest.webmanifest", "/robots.txt",
    "/sitemap.xml", "/site.json", "/providers.json", "/.well-known/security.txt", "/api/info", "/api/call", "/v1/health", "/v1/chat/completions",
    "/v1/logs", "/v1/logs/export", "/favicon.ico"]) assert.equal(isHoneypot(p), false, p);
});

test("the fingerprint: the edge's properties and the browser's headers, the referer's origin only, traversal noted", () => {
  const fp = fingerprint(pageRequest("https://chat-api.impf.ai/v1/chat/completions?x=1", { headers: { Referer: `${PAGE}/?q=%E6%A1%82%E6%9E%9D%E6%B1%A4` } }), T0);
  assert.equal(fp.ts, "2026-10-05T08:00:00.000Z");
  assert.deepEqual([fp.method, fp.host, fp.path, fp.query, fp.ip], ["POST", "chat-api.impf.ai", "/v1/chat/completions", 3, "203.0.113.7"]);
  assert.deepEqual([fp.asn, fp.asOrg, fp.country, fp.region, fp.city, fp.colo, fp.proto, fp.tls], [4134, "Chinanet", "CN", "GD", "Guangzhou", "HKG", "HTTP/2", "TLSv1.3"]);
  assert.deepEqual([fp.hello, fp.ext, fp.ciphers, fp.rtt, fp.enc, fp.ray], [1234, "abc=", "def=", 42, "gzip, deflate, br, zstd", "8c1-HKG"]);
  assert.equal(fingerprint(pageRequest(undefined, { headers: { "X-Requested-With": "com.tencent.mm" } }), T0).xrw, "com.tencent.mm");
  // the address as counted: IPv6 by its /64
  assert.equal(ipKey("203.0.113.7"), "203.0.113.7");
  assert.equal(ipKey("2001:db8:85a3:8d3:1319:8a2e:370:7348"), "2001:db8:85a3:8d3::/64");
  assert.equal(ipKey("2001:DB8:0000:0001::1"), "2001:db8:0:1::/64");
  assert.equal(ipKey("::1"), "0:0:0:0::/64");
  assert.equal(ipKey("2400:3200::1"), "2400:3200:0:0::/64");
  assert.equal(ipKey(""), "unknown");
  assert.equal(fp.referer, PAGE); // never the path: it may carry what a visitor typed
  assert.deepEqual([fp.sfSite, fp.sfMode, fp.sfDest, fp.chMobile, fp.lang], ["same-site", "cors", "empty", "?0", "zh-CN,zh;q=0.9"]);
  assert.equal(fp.uaClass, "browser");
  assert.equal(fp.bot, undefined); // no Bot Management on this plan
  assert.equal(fp.traversal, undefined);
  const bm = fingerprint(pageRequest("https://chat-api.impf.ai/v1/health", { method: "GET", cf: { botManagement: { score: 99, verifiedBot: false, ja4: "t13d..." } } }), T0);
  assert.deepEqual(bm.bot, { score: 99, verified: false, ja4: "t13d..." });
  const bad = fingerprint(new Request("https://chat.impf.ai/static/..%2f..%2fetc/passwd", { headers: { "User-Agent": "x".repeat(400) } }), T0);
  assert.equal(bad.traversal, true);
  assert.equal(bad.ua.length, 300);
  assert.equal(bad.ip, "unknown");
  const xff = fingerprint(new Request("https://chat.impf.ai/", { headers: { "X-Forwarded-For": "198.51.100.9, 10.0.0.1" } }), T0);
  assert.equal(xff.ip, "unknown"); // a client's claim is not the address
  assert.deepEqual(assess(xff, { route: "other" }).reasons.includes("no_cf_ip"), true);
});

// ------------------------------------------------------------------ the score
test("the page's own request scores nothing; what is not the page's is named", async () => {
  const shape = await bodyShape(PAGE_BODY);
  assert.deepEqual([shape.msgs, shape.system, shape.stream, shape.streamOptions, shape.tools, shape.maxTokensKey, shape.sys.length, shape.q.length],
    [2, true, true, true, 1, "max_completion_tokens", 16, 16]);
  // the system prompt by its head: the page appends a visitor's own instructions, which change nothing here
  const long = "你是道乃久。".repeat(400);
  const withInstructions = await bodyShape({ ...PAGE_BODY, messages: [{ role: "system", content: `${long}\n\n## 用户的附加指令\n请用文言回答` }, PAGE_BODY.messages[1]] });
  assert.equal(withInstructions.sys, (await bodyShape({ ...PAGE_BODY, messages: [{ role: "system", content: long }, PAGE_BODY.messages[1]] })).sys);
  assert.equal(shape.chars, "你是道乃久……".length + "桂枝汤主治什么？".length);
  const ctx = { route: "chat", origins: [PAGE], shape, ownPrefix: DEFAULTS.OWN_UA_PREFIX };
  const page = assess(fingerprint(pageRequest(), T0), ctx);
  assert.deepEqual(page, { route: "chat", own: false, score: 0, reasons: [] });
  const wechat = assess(fingerprint(pageRequest(undefined, { ua: WECHAT, headers: { "Sec-CH-UA": "" } }), T0), ctx);
  assert.equal(wechat.score, 1); // an in-app browser without client hints: a point, not a verdict
  assert.deepEqual(wechat.reasons, ["no_ch_ua"]);
  const iphone = assess(fingerprint(pageRequest(undefined, { ua: IPHONE, headers: { "Sec-CH-UA": "" } }), T0), ctx);
  assert.equal(iphone.score, 0); // WebKit sends no client hints
  const known = assess(fingerprint(pageRequest(), T0), { ...ctx, knownPrompts: [shape.sys.slice(0, 8)] });
  assert.equal(known.score, 0);
  const unknown = assess(fingerprint(pageRequest(), T0), { ...ctx, knownPrompts: ["ffffffff"] });
  assert.deepEqual(unknown.reasons, ["unknown_prompt"]);
  // a script with the page's origin pasted in
  const script = new Request("https://chat-api.impf.ai/v1/chat/completions", { method: "POST", headers: { "User-Agent": "python-requests/2.31.0", Origin: PAGE,
    Accept: "application/json", "CF-Connecting-IP": "203.0.113.8" }, body: "{}" });
  script.cf = { asn: 14061, country: "US", httpProtocol: "HTTP/1.1", tlsVersion: "TLSv1.3" };
  const bare = await bodyShape({ model: "Tao-R1", messages: [{ role: "user", content: "hi" }], max_tokens: 100 });
  const a = assess(fingerprint(script, T0), { ...ctx, shape: bare });
  assert.deepEqual(a.reasons, ["ua_tool", "dc_asn", "no_stream", "no_stream_options", "max_tokens_key", "no_tools", "no_system"]);
  assert.equal(a.score, 3 + 2 + 1 + 1 + 1 + 1 + 2);
  // a browser string without what a browser sends; a crawler's name; a foreign page; an old protocol
  const hollow = new Request("https://chat-api.impf.ai/v1/chat/completions", { method: "POST", headers: { "User-Agent": CHROME, Origin: "https://evil.example",
    Referer: "https://evil.example/x", "CF-Connecting-IP": "198.51.100.3" }, body: "{}" });
  hollow.cf = { tlsVersion: "TLSv1.1", httpProtocol: "HTTP/1.1" };
  const h = assess(fingerprint(hollow, T0), { ...ctx, shape });
  assert.deepEqual(h.reasons, ["no_sec_fetch", "no_lang", "no_ch_ua", "old_proto", "tls_old", "origin_foreign", "referer_foreign"]);
  const crawler = assess(fingerprint(pageRequest(undefined, { ua: "ChatGPT-User/1.0", headers: { "Sec-CH-UA": "" } }), T0), ctx);
  assert.deepEqual(crawler.reasons, ["ua_bot_unverified"]);
  const verified = assess(fingerprint(pageRequest(undefined, { ua: "ChatGPT-User/1.0", headers: { "Sec-CH-UA": "" }, cf: { verifiedBotCategory: "AI Assistant" } }), T0), ctx);
  assert.equal(verified.score, 0);
  const noOrigin = assess(fingerprint(pageRequest(undefined, { headers: { Origin: "" } }), T0), ctx);
  assert.deepEqual(noOrigin.reasons, ["origin_missing"]);
  const nav = assess(fingerprint(pageRequest(undefined, { headers: { "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document" } }), T0), ctx);
  assert.deepEqual(nav.reasons, ["sec_fetch_mode", "sec_fetch_dest"]);
  const del = assess(fingerprint(pageRequest(undefined, { method: "DELETE" }), T0), { route: "other", origins: [PAGE] });
  assert.deepEqual(del.reasons, ["method_odd"]);
  const own = assess(fingerprint(pageRequest(undefined, { ua: "taochronos-collector/1", headers: { "Sec-CH-UA": "" } }), T0), { route: "honeypot", ownPrefix: "taochronos-" });
  assert.deepEqual([own.own, own.score, own.reasons], [true, 10, ["honeypot"]]);
  const warp = assess(fingerprint(pageRequest(undefined, { cf: { asn: 13335 } }), T0), ctx);
  assert.deepEqual([warp.score, warp.reasons], [0, ["warp"]]);
  const identity = assess(fingerprint(pageRequest(undefined, { cf: { clientAcceptEncoding: "identity" } }), T0), ctx);
  assert.deepEqual(identity.reasons, ["enc_odd"]);
  const hinted = assess(fingerprint(pageRequest(undefined, { ua: "python-requests/2.31.0", headers: { "Sec-Fetch-Mode": "" } }), T0), ctx);
  assert.deepEqual(hinted.reasons, ["ua_tool", "ch_ua_odd"]); // client hints from what is not a Chromium browser
});

// ------------------------------------------------------------------ the memory
const cfgOf = (env = {}) => sentinelConfig(env);

test("a visitor's row: counts without the address; the address once flagged; the events waiting", async () => {
  const w = new WatchCore(sqlStore());
  const cfg = cfgOf();
  const fp = fingerprint(pageRequest(), T0);
  const ok = await w.observe(fp, assess(fp, { route: "chat", origins: [PAGE] }), { status: null }, cfg, T0);
  assert.deepEqual([ok.score, ok.flagged, ok.blocked, ok.shadow], [0, false, false, false]);
  assert.equal(ok.who.length, 24);
  let row = w.row(ok.who);
  assert.deepEqual([row.ip, Number(row.n), Number(row.flagged)], [null, 1, 0]);
  assert.deepEqual(w.records().items, []); // nothing to collect
  // the same address, as a script
  const script = fingerprint(pageRequest(undefined, { ua: "python-requests/2.31.0", headers: { "Sec-Fetch-Mode": "", "Accept-Language": "", "Sec-CH-UA": "" } }), T0 + 1000);
  const flagged = await w.observe(script, assess(script, { route: "chat", origins: [PAGE], shape: { system: false, stream: false, tools: 0, msgs: 1, chars: 2 } }), { status: null }, cfg, T0 + 1000);
  assert.equal(flagged.flagged, true);
  assert.equal(flagged.who, ok.who);
  row = w.row(ok.who);
  assert.deepEqual([row.ip, Number(row.n), Number(row.flagged)], [null, 1, 0]); // the flag waits for the minute's write; the event has it now
  const seen = w.summary(T0 + 2000).top[0];
  assert.deepEqual([seen.ip, seen.n, seen.flagged, seen.uas], ["203.0.113.7", 2, 1, 2]); // the summary counts what is not yet written
  await w.observe(script, assess(script, { route: "chat", origins: [PAGE] }), { status: null }, cfg, T0 + 61000);
  row = w.row(ok.who);
  assert.deepEqual([row.ip, Number(row.n), Number(row.flagged), JSON.parse(row.uas).length], ["203.0.113.7", 3, 1, 2]);
  assert.ok(!JSON.parse(row.uas).some((u) => u.includes("python")), row.uas); // agents counted by hash, kept whole only in the event
  const { items, last, more } = w.records();
  assert.deepEqual([items.length, last, more], [1, 1, false]);
  const ev = items[0].event;
  assert.deepEqual([ev.kind, ev.route, ev.fp.ip, ev.fp.ua, ev.decision.mode, ev.decision.blocked, ev.state.n], ["flag", "chat", "203.0.113.7", "python-requests/2.31.0", "observe", false, 2]);
  assert.ok(ev.reasons.includes("ua_tool"));
  assert.deepEqual(w.remove(1), { remaining: 0 });
  const summary = w.summary(T0 + 2000);
  assert.deepEqual([summary.visitors, summary.events, summary.blocked.length, summary.top[0].ip, summary.top[0].n], [1, 0, 0, "203.0.113.7", 3]);
  // the system prompts seen, by their hashes: what KNOWN_PROMPTS is set from
  const shape = await bodyShape(PAGE_BODY);
  for (let i = 0; i < 3; i++) await w.observe(fp, { route: "chat", own: false, score: 0, reasons: [] }, { shape }, cfg, T0 + 3000 + i);
  assert.deepEqual(w.summary(T0 + 4000).prompts, [{ sys: shape.sys, n: 3, first: fp.ts, last: fp.ts }]);
  // with a salt the key does not change with the month; without one it does
  const salted = cfgOf({ SENTINEL_SALT: "s" });
  assert.equal(await WatchCore.who("1.2.3.4", salted, T0), await WatchCore.who("1.2.3.4", salted, T0 + 40 * 86400000));
  assert.equal(await WatchCore.who("2001:db8:1:2:aaaa::1", salted, T0), await WatchCore.who("2001:db8:1:2:bbbb::2", salted, T0));
  assert.notEqual(await WatchCore.who("1.2.3.4", cfg, T0), await WatchCore.who("1.2.3.4", cfg, T0 + 40 * 86400000));
});

test("a scanner path refuses its address for a day, whatever the mode; the owner's own clients never", async () => {
  const w = new WatchCore(sqlStore());
  const cfg = cfgOf(); // observe
  const probe = fingerprint(new Request("https://chat-api.impf.ai/wp-config.php", { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "45.138.12.10" } }), T0);
  const r = await w.observe(probe, assess(probe, { route: "honeypot" }), { status: 404 }, cfg, T0);
  assert.deepEqual([r.blocked, r.shadow, r.retry], [true, false, 21600]); // a home network's address: the ordinary six hours
  assert.ok(r.score >= 13);
  const again = fingerprint(pageRequest(undefined, { headers: { "CF-Connecting-IP": "45.138.12.10" } }), T0 + 60000);
  const later = await w.observe(again, assess(again, { route: "chat", origins: [PAGE] }), {}, cfg, T0 + 60000);
  assert.equal(later.blocked, true);
  assert.equal(later.retry, 21600 - 60);
  const nextDay = await w.observe(again, assess(again, { route: "chat", origins: [PAGE] }), {}, cfg, T0 + 86400000 + 1000);
  assert.equal(nextDay.blocked, false);
  const hosted = fingerprint(new Request("https://chat-api.impf.ai/.env", { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "167.71.250.151" } }), T0);
  hosted.asn = 14061;
  assert.equal((await new WatchCore(sqlStore()).observe(hosted, assess(hosted, { route: "honeypot" }), { status: 404 }, cfg, T0)).retry, 86400); // a hosting network's: a day
  assert.equal((await w.blocked("45.138.12.10", cfg, T0 + 1000)).blocked, true);
  assert.equal((await w.blocked("203.0.113.7", cfg, T0 + 1000)).blocked, false);
  const kinds = w.records().items.map((i) => i.event.kind);
  assert.deepEqual(kinds, ["honeypot", "blocked"]);
  assert.equal(w.summary(T0 + 1000).blocked[0].ip, "45.138.12.10");
  // HONEYPOT = observe: noted, not refused
  const soft = new WatchCore(sqlStore());
  const s = await soft.observe(probe, assess(probe, { route: "honeypot" }), { status: 404 }, cfgOf({ HONEYPOT: "observe" }), T0);
  assert.deepEqual([s.blocked, s.shadow], [false, true]);
  // the repository's own client on such a path: refused like anyone (an agent string is anyone's to send), labelled in the event
  const own = fingerprint(new Request("https://chat-api.impf.ai/wp-config.php", { headers: { "User-Agent": "taochronos-deploy/1", "CF-Connecting-IP": "203.0.113.50" } }), T0);
  const o = await w.observe(own, assess(own, { route: "honeypot", ownPrefix: "taochronos-" }), { status: 404 }, cfg, T0);
  assert.deepEqual([o.blocked, o.shadow], [true, false]);
  assert.equal(w.records().items.at(-1).event.own, true);
});

test("over the block score: refused in enforce mode, a shadow in observe mode; the short windows add up", async () => {
  const mk = (ip, t, extra = {}) => {
    const req = new Request("https://chat-api.impf.ai/v1/chat/completions", { method: "POST", headers: { "User-Agent": "python-requests/2.31.0", Origin: PAGE,
      "CF-Connecting-IP": ip }, body: "{}" });
    req.cf = { asn: 14061, country: "US", ...extra.cf };
    return fingerprint(req, t);
  };
  const shape = { system: false, stream: false, streamOptions: false, tools: 0, msgs: 1, chars: 2, maxTokensKey: "max_tokens", q: "q1" };
  const observe = new WatchCore(sqlStore());
  const a = (fp) => assess(fp, { route: "chat", origins: [PAGE], shape });
  const r1 = await observe.observe(mk("198.51.100.1", T0), a(mk("198.51.100.1", T0)), { shape }, cfgOf(), T0);
  assert.equal(r1.score, 11);
  assert.deepEqual([r1.flagged, r1.blocked, r1.shadow], [true, false, true]);
  assert.equal(observe.records().items[0].event.kind, "shadow");
  const enforce = new WatchCore(sqlStore());
  const e1 = await enforce.observe(mk("198.51.100.1", T0), a(mk("198.51.100.1", T0)), { shape }, cfgOf({ SENTINEL: "enforce" }), T0);
  assert.deepEqual([e1.blocked, e1.retry], [true, 21600]);
  assert.equal(enforce.records().items[0].event.kind, "block");
  // the same question again and again, a burst, many errors, many probed paths
  const w = new WatchCore(sqlStore());
  const cfg = cfgOf();
  let last;
  for (let i = 0; i < 3; i++) last = await w.observe(mk("198.51.100.2", T0 + i * 1000), { route: "chat", own: false, score: 0, reasons: [] }, { shape: { q: "same" } }, cfg, T0 + i * 1000);
  assert.deepEqual(last.reasons, ["replay"]);
  for (let i = 0; i < 20; i++) last = await w.observe(mk("198.51.100.3", T0 + i * 100), { route: "chat", own: false, score: 0, reasons: [] }, {}, cfg, T0 + i * 100);
  assert.deepEqual(last.reasons, ["burst"]);
  for (let i = 0; i < 10; i++) last = await w.observe(mk("198.51.100.4", T0 + i * 1000), { route: "other", own: false, score: 0, reasons: [] }, { status: 400 }, cfg, T0 + i * 1000);
  assert.deepEqual(last.reasons, ["errors"]);
  for (let i = 0; i < 12; i++) last = await w.observe(mk("198.51.100.14", T0 + i * 1000), { route: "chat", own: false, score: 0, reasons: [] }, { status: i % 2 ? 429 : 503 }, cfg, T0 + i * 1000);
  assert.deepEqual(last.reasons, []); // our refusals and our failures are not the visitor's errors
  for (let i = 0; i < 8; i++) {
    const req = new Request(`https://chat.impf.ai/old/page-${i}`, { headers: { "User-Agent": CHROME, "CF-Connecting-IP": "198.51.100.5" } });
    last = await w.observe(fingerprint(req, T0 + i * 1000), { route: "other", own: false, score: 0, reasons: [] }, { status: 404 }, cfg, T0 + i * 1000);
  }
  assert.deepEqual(last.reasons, ["probing"]);
  assert.equal(last.score, 4);
  assert.equal(w.row(last.who).ip, null); // under the flag score: no address kept
  for (let i = 0; i < 10; i++) {
    const req = new Request("https://chat.impf.ai/api/info", { headers: { "User-Agent": `${CHROME} v${i}`, "CF-Connecting-IP": "198.51.100.6" } });
    last = await w.observe(fingerprint(req, T0 + i * 1000), { route: "api-read", own: false, score: 0, reasons: [] }, {}, cfg, T0 + i * 1000);
  }
  assert.deepEqual(last.reasons, ["ua_rotation"]);
  assert.equal(last.score, 2);
  // rows are written sparingly: a visitor's quiet minute is one write; the day's counts by route are kept
  const quietly = new WatchCore(sqlStore());
  const browser = (t) => fingerprint(new Request("https://chat.impf.ai/api/passage?id=x", { headers: { "User-Agent": CHROME, "Accept-Language": "zh-CN", "Sec-Fetch-Mode": "cors",
    "Sec-CH-UA": '"Chromium";v="129"', "CF-Connecting-IP": "203.0.113.70" } }), t);
  let calls = 0;
  const counting = quietly.sql.exec.bind(quietly.sql);
  quietly.sql.exec = (q, ...p) => { if (/INSERT INTO watch/.test(q)) calls++; return counting(q, ...p); };
  let r;
  for (let i = 0; i < 30; i++) r = await quietly.observe(browser(T0 + i * 1000), { route: "api-read", own: false, score: 0, reasons: [] }, {}, cfg, T0 + i * 1000);
  assert.equal(calls, 1); // the first sighting; the rest wait for the minute
  assert.deepEqual(r.today, { "api-read": 30 });
  r = await quietly.observe(browser(T0 + 61000), { route: "api-call", own: false, score: 0, reasons: [] }, {}, cfg, T0 + 61000);
  assert.equal(calls, 2);
  assert.deepEqual([Number(quietly.row(r.who).n), r.today], [31, { "api-read": 30, "api-call": 1 }]);
  r = await quietly.observe(browser(T0 + 62000), { route: "api-read", own: false, score: 0, reasons: [] }, { count: 25 }, cfg, T0 + 62000); // a Worker's own count of the minute
  assert.deepEqual(r.today, { "api-read": 55, "api-call": 1 });
  r = await quietly.observe(browser(T0 + 86400000 + 1000), { route: "api-read", own: false, score: 0, reasons: [] }, {}, cfg, T0 + 86400000 + 1000);
  assert.deepEqual(r.today, { "api-read": 1 }); // a new day
  // a refused scanner knocking on: one event a minute, not one a request
  const knock = new WatchCore(sqlStore());
  const probe = (t) => fingerprint(new Request("https://chat.impf.ai/api/info", { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "45.8.19.134" } }), t);
  await knock.observe(fingerprint(new Request("https://chat.impf.ai/.env", { headers: { "User-Agent": "Go-http-client/1.1", "CF-Connecting-IP": "45.8.19.134" } }), T0), { route: "honeypot", own: false, score: 10, reasons: ["honeypot"] }, { status: 404 }, cfg, T0);
  let writes = 0;
  const knocking = knock.sql.exec.bind(knock.sql);
  knock.sql.exec = (q, ...p) => { if (/INSERT INTO watch/.test(q)) writes++; return knocking(q, ...p); };
  for (let i = 1; i <= 120; i++) await knock.observe(probe(T0 + i * 1000), { route: "api-read", own: false, score: 3, reasons: ["ua_tool"] }, {}, cfg, T0 + i * 1000);
  assert.deepEqual(knock.records().items.map((i) => i.event.kind), ["honeypot", "blocked", "blocked"]);
  assert.equal(writes, 2); // two minutes of knocking: a row write a minute, not one a knock
  // a flagged client's minute is one write too
  const flaggedWrites = new WatchCore(sqlStore());
  let fw = 0;
  const counting2 = flaggedWrites.sql.exec.bind(flaggedWrites.sql);
  flaggedWrites.sql.exec = (q, ...p) => { if (/INSERT INTO watch/.test(q)) fw++; return counting2(q, ...p); };
  const tool = (t) => fingerprint(new Request("https://chat.impf.ai/api/passage?id=x", { headers: { "User-Agent": "python-requests/2.31.0", "CF-Connecting-IP": "34.151.137.169" } }), t);
  for (let i = 0; i < 60; i++) await flaggedWrites.observe(tool(T0 + i * 1000), { route: "api-read", own: false, score: 5, reasons: ["ua_tool", "dc_asn"] }, {}, cfg, T0 + i * 1000);
  assert.equal(fw, 1);
  assert.equal(flaggedWrites.summary(T0 + 59000).top[0].ip, "34.151.137.169"); // and the summary knows the address already
  // old rows are swept (an hour after the last sweep), blocked ones kept
  const old = await w.observe(mk("198.51.100.9", T0), { route: "chat", own: false, score: 0, reasons: [] }, {}, cfg, T0);
  await w.observe(mk("198.51.100.8", T0 + 8 * 86400000), { route: "chat", own: false, score: 0, reasons: [] }, {}, cfg, T0 + 8 * 86400000);
  assert.equal(w.row(old.who), null);
  assert.equal(w.row(e1.who), null); // (a different store)
});

test("the endpoints: the token for export, ack and summary; csp reports from anyone, within reason", async () => {
  const w = new WatchCore(sqlStore());
  const cfg = cfgOf();
  const token = "export-token-0123456789abcdef";
  const watch = { observe: (...a) => w.observe(...a), records: (...a) => w.records(...a), remove: (...a) => w.remove(...a), summary: (...a) => w.summary(...a) };
  const serve = (path, init = {}) => {
    const req = new Request(`https://chat-api.impf.ai${path}`, init);
    const url = new URL(req.url);
    return serveSecurity(req, url, { prefix: "/v1/security", token, watch, cfg, fp: fingerprint(req, T0), now: T0, cors: { Vary: "Origin" } });
  };
  assert.equal(await serve("/v1/health"), null);
  assert.equal((await serve("/v1/security/export")).status, 401);
  assert.equal((await serve("/v1/security/export", { headers: { Authorization: "Bearer wrong-wrong-wrong-wrong" } })).status, 401);
  assert.equal((await serve("/v1/security/nothing", { headers: { Authorization: `Bearer ${token}` } })).status, 404);
  const probe = fingerprint(new Request("https://chat-api.impf.ai/.git/HEAD", { headers: { "CF-Connecting-IP": "93.123.109.101" } }), T0);
  await w.observe(probe, assess(probe, { route: "honeypot" }), { status: 404 }, cfg, T0);
  const report = { "csp-report": { "document-uri": "https://chat.impf.ai/", "violated-directive": "script-src", "blocked-uri": "https://evil.example/x.js" } };
  const csp = await serve("/v1/security/csp", { method: "POST", headers: { "Content-Type": "application/csp-report", "CF-Connecting-IP": "203.0.113.7" }, body: JSON.stringify(report) });
  assert.equal(csp.status, 204);
  const extension = await serve("/v1/security/csp", { method: "POST", headers: { "CF-Connecting-IP": "203.0.113.7" },
    body: JSON.stringify({ "csp-report": { "blocked-uri": "chrome-extension://abc/inject.js", "violated-directive": "script-src" } }) });
  assert.equal(extension.status, 204); // taken, not kept: an extension's doing, not the page's
  assert.equal((await serve("/v1/security/csp")).status, 405);
  assert.equal((await serve("/v1/security/csp", { method: "POST", headers: { "Content-Length": "99999" }, body: "x" })).status, 413);
  const auth = { Authorization: `Bearer ${token}` };
  const page1 = await (await serve("/v1/security/export?limit=1", { headers: auth })).json();
  assert.deepEqual([page1.items.length, page1.last, page1.more, page1.items[0].event.kind, page1.items[0].event.fp.ip], [1, 1, true, "honeypot", "93.123.109.101"]);
  const page2 = await (await serve("/v1/security/export?after=1", { headers: auth })).json();
  assert.deepEqual([page2.items.length, page2.items[0].event.kind], [1, "csp"]);
  assert.deepEqual(page2.items[0].event.reports, [{ directive: "script-src", blocked: "https://evil.example", document: "https://chat.impf.ai/" }]); // reduced: origins and paths, never a query or a sample
  const ack = await (await serve("/v1/security/ack", { method: "POST", headers: auth, body: JSON.stringify({ through: 2 }) })).json();
  assert.equal(ack.remaining, 0);
  assert.equal((await serve("/v1/security/ack", { method: "POST", headers: auth, body: "{}" })).status, 400);
  const summary = await (await serve("/v1/security/summary", { headers: auth })).json();
  assert.deepEqual([summary.visitors, summary.blocked.length, summary.blocked[0].ip], [2, 1, "93.123.109.101"]);
  // the same violation again is not kept; reports beyond reason from one address are dropped
  const again = { "csp-report": { "document-uri": "https://chat.impf.ai/?q=secret", "violated-directive": "script-src", "blocked-uri": "https://evil.example/x.js?token=1" } };
  assert.equal((await serve("/v1/security/csp", { method: "POST", headers: { "CF-Connecting-IP": "203.0.113.7" }, body: JSON.stringify(again) })).status, 204);
  assert.equal(w.records().items.length, 0);
  let r;
  for (let i = 0; i < 25; i++) {
    r = await serve("/v1/security/csp", { method: "POST", headers: { "CF-Connecting-IP": "203.0.113.7", "Content-Type": "application/reports+json" },
      body: JSON.stringify([{ type: "csp-violation", body: { effectiveDirective: "img-src", blockedURL: `https://img${i}.example/a.png?x=1`, documentURL: "https://chat.impf.ai/about" } }]) });
  }
  assert.equal(r.status, 204);
  assert.equal(w.records().items.length, 19); // the first report of this address is in the same ten minutes
  assert.deepEqual(w.records().items[0].event.reports, [{ directive: "img-src", blocked: "https://img0.example", document: "https://chat.impf.ai/about" }]);
  // several reports in one POST: one round trip, one event
  const batch = await serve("/v1/security/csp", { method: "POST", headers: { "CF-Connecting-IP": "198.51.100.60", "Content-Type": "application/reports+json" },
    body: JSON.stringify([0, 1, 2].map((i) => ({ type: "csp-violation", body: { effectiveDirective: "connect-src", blockedURL: `https://api${i}.example/v1`, documentURL: "https://chat.impf.ai/" } }))) });
  assert.equal(batch.status, 204);
  assert.equal(w.records().items.at(-1).event.reports.length, 3);
  // the two shapes, reduced
  assert.deepEqual(cspReports(JSON.stringify({ "csp-report": { "effective-directive": "style-src-attr", "blocked-uri": "inline", "source-file": "https://chat.impf.ai/index.html?v=2", "line-number": 117, "script-sample": "padding:24px" } })),
    [{ directive: "style-src-attr", blocked: "inline", source: "https://chat.impf.ai/index.html", line: 117 }]);
  assert.deepEqual(cspReports("not json"), []);
  assert.deepEqual(cspReports(JSON.stringify([{ type: "deprecation", body: {} }])), []);
  // mode off: reports are not kept
  assert.equal((await serveSecurity(new Request("https://chat-api.impf.ai/v1/security/csp", { method: "POST", body: "{}" }), new URL("https://chat-api.impf.ai/v1/security/csp"),
    { prefix: "/v1/security", token, watch, cfg: cfgOf({ SENTINEL: "off" }), fp: probe, now: T0 })).status, 204);
  assert.equal(w.records().items.length, 20); // the batch above, and nothing from a sentinel that is off
});

test("config, and the log lines: only requests worth a look, the address only when flagged", () => {
  const c = sentinelConfig({ SENTINEL: "Enforce", HONEYPOT: "observe", FLAG_SCORE: "3", KNOWN_PROMPTS: "AB12, cd34", SENTINEL_SALT: "x" });
  assert.deepEqual([c.mode, c.honeypot, c.flagScore, c.blockScore, c.knownPrompts, c.salt, c.ownPrefix], ["enforce", "observe", 3, 10, ["ab12", "cd34"], "x", "taochronos-"]);
  assert.equal(sentinelConfig({ SENTINEL: "nonsense" }).mode, "observe");
  const silent = console.log;
  const lines = [];
  console.log = (l) => lines.push(l);
  try {
    const fp = fingerprint(pageRequest(), T0);
    assert.equal(logLine("relay", fp, { route: "chat", score: 0, reasons: [] }, { score: 0, reasons: [], who: "w" }, 200, c), null);
    const line = logLine("relay", fp, { route: "chat", score: 0, reasons: [] }, { score: 0, reasons: [], who: "w" }, 403, c);
    assert.deepEqual([line.status, line.ip, line.who, line.ua, line.cc, line.path], [403, undefined, "w", "browser", "CN", "/v1/chat/completions"]);
    const flagged = logLine("relay", fp, null, { score: 7, reasons: ["ua_tool"], who: "w", flagged: true }, null, c);
    assert.deepEqual([flagged.score, flagged.ip, flagged.reasons], [7, "203.0.113.7", ["ua_tool"]]);
    assert.equal(lines.length, 2);
    const sampled = sentinelConfig({ LOG_SAMPLE: "2" });
    const a = logLine("relay", fp, { route: "chat", score: 0, reasons: [] }, null, 200, sampled);
    const b = logLine("relay", fp, { route: "chat", score: 0, reasons: [] }, null, 200, sampled);
    assert.equal([a, b].filter(Boolean).length, 1);
  } finally {
    console.log = silent;
  }
});
