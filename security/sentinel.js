// 哨兵 — what the two Workers, the relay (chat-api.impf.ai, relay/) and the site (chat.impf.ai, cloud/site/), record
// about a request and decide from it; apart from the Workers themselves, so that it runs under Node in tests
// (security/test/sentinel.test.js) and both Workers behave alike (security/README.md).
//
//   fingerprint(request)      the request as seen at the edge: address, network (ASN), country, Cloudflare location,
//                             protocol, TLS, and the headers a browser sends (or an automated client leaves out)
//   assess(fp, context)       a score with its reasons: automation, spoofing, scanning, foreign origins, a body that is
//                             not the page's — from this one request alone
//   WatchCore                 the memory behind the score, in a Durable Object's SQLite: per visitor the counts, the
//                             user agents and probed paths, the short-window signals (bursts, replays, errors, probing),
//                             the block; the events of flagged requests, waiting for the repository's collector
//   serveSecurity(...)        the endpoints both Workers offer under a prefix: export and ack (the collector, with the
//                             LOG_EXPORT_TOKEN), summary (the owner), csp (the browsers' policy-violation reports)
//   logLine(...)              one line to Workers Logs for a request worth a look
//
// Modes (SENTINEL): off — nothing is recorded; observe (default) — recorded and flagged, never refused; enforce — also
// refused while blocked.  A scanner path (HONEYPOT = block, the default) is refused in observe mode too: nobody asks these
// hosts for /wp-config.php by mistake, and the address that did is refused for a day.  The repository's own clients
// (OWN_UA_PREFIX) are labelled, not exempted: an agent string is anyone's to send; their calls stay under the block score.
//
// Addresses.  A visitor is known by a hash (with SENTINEL_SALT, a secret, the same across days; without it, within a
// calendar month).  The address itself is kept only in the row and the events of a flagged visitor (score ≥ FLAG_SCORE)
// — what the owner needs to act on at the edge — and the collector takes the events to the repository, where they are
// deleted here.  A request the page makes with the headers a browser sends scores 0 and leaves only a count.

export const VERSION = 1;

export const DEFAULTS = {
  SENTINEL: "observe",            // off | observe | enforce
  HONEYPOT: "block",              // block | observe: what a scanner path does to its address
  FLAG_SCORE: "5",                // from this score a request is kept whole (with its address) as an event
  BLOCK_SCORE: "10",              // from this score an address is refused (enforce mode) for BLOCK_SECONDS
  BLOCK_SECONDS: "21600",
  HONEYPOT_BLOCK_SECONDS: "86400",  // for an address in a hosting network; a home network's (many people may share it) gets BLOCK_SECONDS
  WATCH_DAYS: "7",                // a visitor's row is forgotten this long after their last request
  EVENT_KEEP: "20000",            // events never collected beyond this many: the oldest go
  KNOWN_PROMPTS: "",              // sha256 prefixes (hex, comma-separated) of the page's system prompts; empty: not scored
  LOG_SAMPLE: "0",                // besides the requests worth a look, 1 in this many others to Workers Logs (0: none)
  OWN_UA_PREFIX: "taochronos-",   // the repository's own clients (the collector, the deploy checks): labelled in the events
};

export function sentinelConfig(env = {}) {
  const get = (k) => (env[k] !== undefined && env[k] !== "" ? String(env[k]) : DEFAULTS[k]);
  const num = (k) => Number(get(k));
  const mode = get("SENTINEL").toLowerCase();
  return {
    mode: ["off", "observe", "enforce"].includes(mode) ? mode : "observe",
    honeypot: get("HONEYPOT").toLowerCase() === "observe" ? "observe" : "block",
    flagScore: num("FLAG_SCORE"),
    blockScore: num("BLOCK_SCORE"),
    blockSeconds: num("BLOCK_SECONDS"),
    honeypotSeconds: num("HONEYPOT_BLOCK_SECONDS"),
    watchDays: num("WATCH_DAYS"),
    eventKeep: num("EVENT_KEEP"),
    knownPrompts: get("KNOWN_PROMPTS").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
    logSample: num("LOG_SAMPLE"),
    ownPrefix: get("OWN_UA_PREFIX"),
    salt: String(env.SENTINEL_SALT || ""),
  };
}

// ------------------------------------------------------------------ helpers
const encoder = new TextEncoder();
const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");

/** The first n hex characters of sha256(text). */
export async function digest(text, n = 16) {
  return hex(await crypto.subtle.digest("SHA-256", encoder.encode(String(text)))).slice(0, n);
}

/** A bearer token against the expected one, in constant time (both hashed first, so their lengths do not show). */
export async function bearerOk(request, expected) {
  expected = String(expected || "");
  const given = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (expected.length < 16 || !given) return false;
  const [a, b] = await Promise.all([crypto.subtle.digest("SHA-256", encoder.encode(given)), crypto.subtle.digest("SHA-256", encoder.encode(expected))]);
  const x = new Uint8Array(a);
  const y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

/** The body as text, or null when it is larger than `max` bytes: refused by its declared length, else read only up to
 * the limit (a body sent without a length is not taken whole into memory first). */
export async function readText(request, max) {
  const declared = request.headers.get("Content-Length");
  if (declared !== null && Number(declared) > max) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const parts = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      await reader.cancel().catch(() => {});
      return null;
    }
    parts.push(value);
  }
  const bytes = new Uint8Array(size);
  let at = 0;
  for (const part of parts) { bytes.set(part, at); at += part.byteLength; }
  return new TextDecoder().decode(bytes);
}

export const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

const textOf = (content) => {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  let out = "";
  for (const part of content) if (part && typeof part.text === "string") out += part.text;
  return out;
};

// ------------------------------------------------------------------ the request
// what is read of the request: the Cloudflare properties every plan has (the Bot Management ones are read when present)
// and the headers a browser sends with a fetch — a client that is not a browser leaves most of them out
const CF = [["asn", "asn"], ["asOrg", "asOrganization"], ["country", "country"], ["region", "regionCode"], ["city", "city"],
  ["colo", "colo"], ["proto", "httpProtocol"], ["tls", "tlsVersion"], ["cipher", "tlsCipher"], ["hello", "tlsClientHelloLength"],
  ["ext", "tlsClientExtensionsSha1"], ["ciphers", "tlsClientCiphersSha1"], ["rtt", "clientTcpRtt"], ["qrtt", "clientQuicRtt"],
  ["enc", "clientAcceptEncoding"], ["vbc", "verifiedBotCategory"]]; // enc: the client's own; Cloudflare rewrites the header
const HEADERS = [["ua", "User-Agent", 300], ["accept", "Accept", 120], ["lang", "Accept-Language", 80],
  ["origin", "Origin", 120], ["referer", "Referer", 300], ["sfSite", "Sec-Fetch-Site", 20], ["sfMode", "Sec-Fetch-Mode", 20],
  ["sfDest", "Sec-Fetch-Dest", 20], ["sfUser", "Sec-Fetch-User", 8], ["chUa", "Sec-CH-UA", 200], ["chMobile", "Sec-CH-UA-Mobile", 8],
  ["chPlatform", "Sec-CH-UA-Platform", 40], ["xrw", "X-Requested-With", 80], ["ctype", "Content-Type", 80], ["clen", "Content-Length", 20],
  ["ray", "CF-Ray", 40]];

/**
 * The address as a visitor is counted by: an IPv4 address itself; an IPv6 address by its /64 — the interface half changes
 * by the hour under privacy extensions, and a visitor who could be counted anew with each change would have no limit.
 */
export function ipKey(ip) {
  if (!ip || !ip.includes(":")) return ip || "unknown";
  const [head, tail = ""] = ip.split("::");
  const left = head ? head.split(":") : [];
  const right = tail ? tail.split(":") : [];
  const groups = [...left, ...Array(Math.max(0, 8 - left.length - right.length)).fill("0"), ...right].slice(0, 8)
    .map((g) => (g || "0").toLowerCase().replace(/^0+(?=.)/, ""));
  return `${groups.slice(0, 4).join(":")}::/64`;
}

/** The request as seen at the edge (a plain object: it travels to the Durable Object and into an event). */
export function fingerprint(request, now = Date.now()) {
  const url = new URL(request.url);
  const cf = request.cf || {};
  const h = (name) => request.headers.get(name);
  const fp = { ts: new Date(now).toISOString(), method: request.method, host: url.hostname, path: url.pathname.slice(0, 200),
    query: url.search.length > 1 ? url.search.length - 1 : 0 };
  fp.ip = h("CF-Connecting-IP") || "unknown"; // the edge sets it on every request; anything else is a client's claim
  for (const [k, name] of CF) if (cf[name] !== undefined && cf[name] !== null && cf[name] !== "") fp[k] = cf[name];
  if (!fp.country && h("CF-IPCountry")) fp.country = h("CF-IPCountry");
  const bm = cf.botManagement;
  if (bm && typeof bm === "object") {
    fp.bot = {};
    for (const [k, name] of [["score", "score"], ["verified", "verifiedBot"], ["ja3", "ja3Hash"], ["ja4", "ja4"], ["static", "staticResource"]]) {
      if (bm[name] !== undefined && bm[name] !== null) fp.bot[k] = bm[name];
    }
  }
  for (const [k, name, n] of HEADERS) {
    const v = h(name);
    if (v) fp[k] = v.length > n ? v.slice(0, n) : v;
  }
  if (fp.referer) { // its origin only: a path may carry what a visitor typed
    try { fp.referer = new URL(fp.referer).origin; } catch { fp.referer = fp.referer.slice(0, 80); }
  }
  if (/%2e%2e|\.\.(?:\/|\\|%2f|%5c)|%00|%252e|%c0%ae/i.test(request.url)) fp.traversal = true;
  fp.uaClass = uaClass(fp.ua);
  return fp;
}

// user agents by kind: what scans, what is a program, what claims to be a known crawler, what is a browser
const SCANNER = /masscan|zgrab|zmap|nmap|nikto|sqlmap|nuclei|dirbuster|gobuster|feroxbuster|ffuf|wfuzz|wpscan|acunetix|nessus|openvas|w3af|arachni|l9explore|l9tcpid|xmrig|censysinspect|expanse|paloaltonetworks|internetmeasurement|netsystemsresearch|projectdiscovery|odin|hello.?world|zoominfo|scanner/i;
const TOOL = /^curl\/|^wget\/|python-requests|python-urllib|python-httpx|^python\/|aiohttp|go-http-client|^java\/|okhttp|apache-httpclient|node-fetch|undici|^axios\/|^got \(|libwww|lwp-trivial|httpie|scrapy|postmanruntime|insomnia|^dart\/|^ruby|^php\/|guzzle|faraday|restsharp|winhttp|microsoft url control|coldfusion|headlesschrome|phantomjs|selenium|puppeteer|playwright|^mozilla\/[45]\.0$/i;
const BOT = /googlebot|bingbot|baiduspider|yandexbot|duckduckbot|applebot|sogou\s?(?:web\s?)?spider|360spider|bytespider|petalbot|facebookexternalhit|twitterbot|linkedinbot|slackbot|telegrambot|whatsapp|discordbot|gptbot|chatgpt-user|oai-searchbot|claudebot|claude-web|claude-user|claude-searchbot|anthropic-ai|perplexitybot|perplexity-user|google-extended|amazonbot|ccbot|meta-externalagent|meta-externalfetcher|diffbot|cohere-ai|youbot|duckassistbot|mistralai-user|semrushbot|ahrefsbot|mj12bot|dotbot|barkrowler|seznambot|archive\.org_bot|ia_archiver|timpibot|omgili|dataforseo|bravebot/i;
const BROWSER = /chrome\/|crios\/|firefox\/|fxios\/|safari\/|edg[ea]?\/|opr\/|micromessenger|qqbrowser|ucbrowser|baiduboxapp|quark|heytapbrowser|miuibrowser|huaweibrowser|samsungbrowser|vivobrowser|sogoumobilebrowser|mobile/i;

/** empty | scanner | tool | bot | browser | other. */
export function uaClass(ua) {
  if (!ua) return "empty";
  if (SCANNER.test(ua)) return "scanner";
  if (BOT.test(ua)) return "bot";
  if (TOOL.test(ua)) return "tool";
  if (/^mozilla\/5\.0/i.test(ua) && BROWSER.test(ua)) return "browser";
  return "other";
}

/** What a browser user agent says of its engine and version, or null: {engine: chromium | gecko | webkit, major, ios}. */
export function browserOf(ua) {
  if (!ua || uaClass(ua) !== "browser") return null;
  const ios = /iphone|ipad|ipod/i.test(ua);
  let m;
  if (ios) { // every browser on iOS is WebKit; its version is the system's
    m = /OS (\d+)[_.]\d/.exec(ua) || /Version\/(\d+)/.exec(ua);
    return { engine: "webkit", major: m ? Number(m[1]) : 0, ios: true };
  }
  if ((m = /Firefox\/(\d+)/.exec(ua))) return { engine: "gecko", major: Number(m[1]), ios: false };
  if ((m = /(?:Chrome|Chromium|CriOS|HeadlessChrome)\/(\d+)/.exec(ua))) return { engine: "chromium", major: Number(m[1]), ios: false };
  if ((m = /Version\/(\d+)[\d.]* .*Safari\//.exec(ua))) return { engine: "webkit", major: Number(m[1]), ios: false };
  return { engine: "other", major: 0, ios: false };
}

/** Does this browser send Sec-Fetch-* with a fetch?  Chromium since 76, Firefox since 90, WebKit since 16.4 (older
 * WebViews and in-app browsers may not: the version is read with a margin). */
export const expectsSecFetch = (b) => Boolean(b) && ((b.engine === "chromium" && b.major >= 80) || (b.engine === "gecko" && b.major >= 92) || (b.engine === "webkit" && b.major >= 17));

/** Does this browser send Sec-CH-UA?  Chromium since 89, never Firefox or WebKit (iOS Chrome is WebKit). */
export const expectsClientHints = (b) => Boolean(b) && b.engine === "chromium" && !b.ios && b.major >= 90;

// hosting and cloud networks (a scanner's or a scraper's usual home; a VPN user's too, so a signal, not a verdict):
// Amazon, Google, Microsoft, DigitalOcean, Vultr, Linode, OVH, Hetzner, Alibaba, Tencent, Huawei, M247, Datacamp, G-Core,
// Contabo, netcup, HVC, ColoCrossing, Unified Layer, GoDaddy, Leaseweb, Oracle, xTom, Voxility, Psychz, QuadraNet
export const DATACENTER = new Set([16509, 14618, 8987, 55960, 15169, 396982, 19527, 8075, 8068, 8069, 14061, 20473, 63949, 16276, 24940,
  213230, 45102, 37963, 134963, 132203, 45090, 132591, 55990, 136907, 136908, 9009, 212238, 60068, 199524, 51167, 197540, 29802, 36352,
  46606, 19871, 26496, 60781, 28753, 7203, 30633, 31898, 9312, 3223, 40676, 8100, 62904, 63023, 35916, 206092, 211252, 47583, 20454]);

// the paths a scanner asks for (lower-cased); none of them exists on these hosts.  Conservative: a hit refuses the
// address for a day, so nothing the site serves (.js, .json, .wasm, .whl, .zip, .xz, .svg, .css, .html, .txt, .xml,
// .webmanifest) and nothing under /.well-known/ is listed
const HONEYPOT_PREFIXES = ["/wp-", "/wordpress", "/blog/wp-", "/xmlrpc.php", "/.git", "/.svn", "/.hg", "/.env", "/.aws", "/.ssh",
  "/.docker", "/.vscode", "/.idea", "/.ds_store", "/phpmyadmin", "/pma/", "/myadmin", "/adminer", "/cgi-bin/", "/vendor/phpunit",
  "/actuator", "/jmx-console", "/web-console", "/manager/html", "/geoserver", "/druid/", "/nacos", "/solr/", "/jenkins", "/boaform",
  "/hnap1", "/goform/", "/eval-stdin", "/phpinfo", "/info.php", "/server-status", "/server-info", "/telescope", "/_profiler",
  "/owa/", "/ecp/", "/autodiscover", "/remote/login", "/console/", "/_ignition", "/laravel", "/config.json.bak", "/backup.sql",
  "/dump.sql", "/db.sql", "/.htaccess", "/.htpasswd", "/web.config", "/api/.env", "/debug/default", "/elmah.axd", "/cf_scripts"];
const HONEYPOT_SUFFIXES = [".php", ".php7", ".phtml", ".asp", ".aspx", ".jsp", ".jspx", ".cgi", ".bak", ".sql", ".old", ".orig", ".swp",
  ".save", ".rar", ".7z", ".env", ".ini", ".log", ".pem", ".key"];

/** Is this a path only a scanner asks for? */
export function isHoneypot(pathname) {
  const p = String(pathname || "").toLowerCase();
  if (p.startsWith("/.well-known/")) return false;
  for (const prefix of HONEYPOT_PREFIXES) if (p.startsWith(prefix)) return true;
  for (const suffix of HONEYPOT_SUFFIXES) if (p.endsWith(suffix)) return true;
  return false;
}

export const SYS_PREFIX = 1024; // the system prompt is hashed by its first characters: the page appends a visitor's own instructions after it

/**
 * The shape of a chat request's body, as the page sends it (web/js/llm/openai.js, web/js/agent.js): a system prompt
 * first, tools, stream with usage, max_completion_tokens.  Hashes only: never the text.
 */
export async function bodyShape(body) {
  const msgs = Array.isArray(body?.messages) ? body.messages : [];
  let chars = 0;
  for (const m of msgs) chars += textOf(m?.content).length;
  const first = msgs[0];
  const system = Boolean(first && first.role === "system");
  let lastUser = null;
  for (let i = msgs.length - 1; i >= 0; i--) if (msgs[i]?.role === "user") { lastUser = msgs[i]; break; }
  const shape = {
    msgs: msgs.length, chars, system, stream: body?.stream === true, streamOptions: Boolean(body?.stream_options),
    turn: msgs.length > 0 && msgs[msgs.length - 1]?.role === "user", // a question asked, not a tool round of one
    tools: Array.isArray(body?.tools) ? body.tools.length : 0,
    maxTokensKey: body && "max_completion_tokens" in body ? "max_completion_tokens" : body && "max_tokens" in body ? "max_tokens" : null,
  };
  if (system) shape.sys = await digest(textOf(first.content).slice(0, SYS_PREFIX), 16);
  // the question with its place in the conversation: a turn's tool rounds repeat the question with more messages after
  // it and are not replays; the same body sent again is
  if (lastUser) shape.q = await digest(`${textOf(lastUser.content)}|${msgs.length}`, 16);
  return shape;
}

// ------------------------------------------------------------------ the score of one request
/**
 * context: {route, origins, selfOrigin, shape, knownPrompts, ownPrefix}.  Routes: chat, logs (the relay); api-read,
 * api-call, page (the site); honeypot, csp, other (both).  Returns {route, own, score, reasons}.
 */
export function assess(fp, context = {}) {
  const route = context.route || "other";
  const reasons = [];
  let score = 0;
  const add = (reason, n) => { reasons.push(reason); score += n; };
  const own = Boolean(context.ownPrefix && fp.ua && fp.ua.startsWith(context.ownPrefix)); // a label: the owner's clients are never exempt
  if (route === "honeypot") add("honeypot", 10);
  if (fp.traversal) add("traversal", 6);
  if (fp.ip === "unknown") add("no_cf_ip", 3); // not through the edge as expected
  switch (fp.uaClass) {
    case "empty": add("no_ua", 3); break;
    case "scanner": add("ua_scanner", 6); break;
    case "tool": add("ua_tool", 3); break;
    case "bot": if (!fp.bot?.verified && !fp.vbc) add("ua_bot_unverified", 2); break; // a crawler has no business with these APIs
    case "other": if (!own) add("ua_other", 1); break;
    default: break;
  }
  const b = browserOf(fp.ua);
  if (b) {
    if (!fp.sfMode && expectsSecFetch(b)) add("no_sec_fetch", 2);
    if (!fp.lang) add("no_lang", 1);
    if (!fp.chUa && expectsClientHints(b)) add("no_ch_ua", 1);
    if (fp.proto && /^HTTP\/1\.[01]$/i.test(fp.proto)) add("old_proto", 1);
    if (fp.enc !== undefined && !/gzip|br|zstd|deflate/i.test(fp.enc)) add("enc_odd", 1); // a browser always compresses
  } else if (fp.chUa && fp.ua) add("ch_ua_odd", 2); // client hints come from Chromium browsers only
  if (fp.sfMode) {
    const api = route === "chat" || route === "logs" || route === "api-call" || route === "api-read";
    if (api && fp.sfMode !== "cors" && fp.sfMode !== "same-origin") add("sec_fetch_mode", 2);
    if (api && fp.sfDest && fp.sfDest !== "empty") add("sec_fetch_dest", 1);
  }
  if (fp.tls && /^TLSv1(\.[01])?$/i.test(fp.tls)) add("tls_old", 3);
  if (fp.asn !== undefined && DATACENTER.has(Number(fp.asn))) add("dc_asn", 2);
  if (Number(fp.asn) === 13335) reasons.push("warp"); // behind Cloudflare WARP (or a Worker): noted, not scored
  if (context.origins) {
    const origins = context.origins;
    const self = context.selfOrigin;
    if (fp.origin && !origins.includes(fp.origin) && fp.origin !== self) add("origin_foreign", 3);
    else if (!fp.origin && (route === "chat" || route === "logs")) add("origin_missing", 2);
    if (fp.referer && !origins.includes(fp.referer) && fp.referer !== self) add("referer_foreign", 2);
  }
  if (fp.method && !["GET", "POST", "OPTIONS", "HEAD", "PUT"].includes(fp.method)) add("method_odd", 2);
  const s = context.shape;
  if (route === "chat" && s) {
    if (!s.stream) add("no_stream", 1);
    if (!s.streamOptions) add("no_stream_options", 1);
    if (s.maxTokensKey !== "max_completion_tokens") add("max_tokens_key", 1);
    if (!s.tools) add("no_tools", 1);
    if (!s.system) add("no_system", 2);
    else if (context.knownPrompts?.length && !context.knownPrompts.some((p) => s.sys.startsWith(p))) add("unknown_prompt", 3);
    if (s.msgs > 400) add("many_messages", 1);
    if (s.chars > 1500000) add("huge_prompt", 1);
    if (s.stream && fp.accept && !/event-stream|\*\/\*/.test(fp.accept)) add("accept_odd", 1);
  }
  return { route, own, score, reasons };
}

// ------------------------------------------------------------------ the memory behind the score
const WINDOW = 600000; // the short windows: ten minutes
const BURST = 10000;   // and ten seconds
const parse = (text, fallback) => { try { const v = JSON.parse(text); return v ?? fallback; } catch { return fallback; } };
/** A short, synchronous hash (FNV-1a, 32 bits, hex) for counting distinct agents. */
const hashOf = (text) => {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(16).padStart(8, "0");
};
const addTo = (list, value, cap) => {
  if (value === undefined || value === null || value === "" || list.includes(value)) return list;
  list.push(value);
  return list.length > cap ? list.slice(list.length - cap) : list;
};

/**
 * Per visitor: a row (counts, agents, probed paths, networks, the block) and, in memory, the last ten minutes (lost at
 * worst when the object is evicted).  Over a `sql` object with the Durable Object SQL API's shape.
 */
export class WatchCore {
  constructor(sql) {
    this.sql = sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS watch (who TEXT PRIMARY KEY, ip TEXT, first TEXT NOT NULL, last TEXT NOT NULL, " +
      "n INTEGER NOT NULL, bad INTEGER NOT NULL, flagged INTEGER NOT NULL, score INTEGER NOT NULL, uas TEXT NOT NULL, paths TEXT NOT NULL, " +
      "nets TEXT NOT NULL, blocked_until INTEGER NOT NULL, blocks INTEGER NOT NULL, day TEXT NOT NULL DEFAULT '', today TEXT NOT NULL DEFAULT '{}')");
    // rows and events are written sparingly (the plan counts rows written per day, for the whole account): a visitor's
    // counts are kept here between writes, and written with the next one — at the latest a minute later
    this.pending = new Map(); // who → {n, bad, flagged, score, ip, routes: {route: n}, uas, paths, nets (since the last write), wrote, event, touched: ms}
    this.prompts = new Map(); // sys → {n, first, last}: the system prompts seen since the last flush (a minute)
    this.promptsWrote = 0;
    this.sql.exec("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, received TEXT NOT NULL, event TEXT NOT NULL)");
    // the system prompts seen (hashes): the page's own are the common ones — what KNOWN_PROMPTS is set from
    this.sql.exec("CREATE TABLE IF NOT EXISTS prompts (sys TEXT PRIMARY KEY, n INTEGER NOT NULL, first TEXT NOT NULL, last TEXT NOT NULL)");
    this.recent = new Map(); // who → {t: [ms], q: Map(hash → [ms]), bad: [ms], paths: Map(path → ms), csp: [ms]}
    this.swept = 0;
  }

  static fresh(wrote = 0) {
    return { n: 0, bad: 0, flagged: 0, score: 0, ip: null, routes: {}, uas: [], paths: [], nets: [], wrote, event: 0, touched: 0 };
  }

  /** The visitor's key: the address (an IPv6 one by its /64) hashed with the salt, or with the month. */
  static async who(ip, cfg, now) {
    return digest(`${ipKey(ip)}|${cfg.salt || new Date(now).toISOString().slice(0, 7)}`, 24);
  }

  sweep(now, cfg) {
    if (now - this.swept < 3600000) return;
    this.swept = now;
    const cutoff = new Date(now - Math.max(1, cfg.watchDays || 7) * 86400000).toISOString();
    this.sql.exec("DELETE FROM watch WHERE last < ? AND blocked_until < ?", cutoff, now);
    this.sql.exec("DELETE FROM prompts WHERE n <= 2 AND last < ?", cutoff); // a prompt seen once or twice: not the page's
    for (const [who, r] of this.recent) if (!r.t.length || now - r.t[r.t.length - 1] > WINDOW) this.recent.delete(who);
    // a visitor gone for ten minutes: what was not written of their last minute is let go (a count, not a record)
    for (const [who, p] of this.pending) if (now - Math.max(p.wrote, p.touched) > WINDOW) this.pending.delete(who);
  }

  /** The system prompts counted in memory, written once a minute (a row each), or now. */
  flushPrompts(now, force = false) {
    if (!this.prompts.size || (!force && now - this.promptsWrote < 60000)) return;
    for (const [sys, p] of this.prompts) {
      this.sql.exec("INSERT INTO prompts (sys, n, first, last) VALUES (?, ?, ?, ?) ON CONFLICT(sys) DO UPDATE SET n = n + excluded.n, last = excluded.last", sys, p.n, p.first, p.last);
    }
    this.prompts.clear();
    this.promptsWrote = now;
  }

  /** The last ten minutes of this visitor, with this request added: {burst, tenMin, replay, bad, probed}. */
  window(who, fp, a, extra, now) {
    let r = this.recent.get(who);
    if (!r) {
      if (this.recent.size >= 5000) this.recent.delete(this.recent.keys().next().value); // the oldest entry goes
      r = { t: [], q: new Map(), bad: [], paths: new Map(), csp: [], seen: new Set() };
      this.recent.set(who, r);
    }
    const since = now - WINDOW;
    const keep = (list) => { while (list.length && list[0] < since) list.shift(); };
    r.t.push(now); keep(r.t); if (r.t.length > 600) r.t.splice(0, r.t.length - 600);
    let burst = 0;
    for (let i = r.t.length - 1; i >= 0 && r.t[i] >= now - BURST; i--) burst++;
    let replay = 0;
    if (extra.shape?.q) {
      const list = r.q.get(extra.shape.q) || [];
      list.push(now); keep(list);
      r.q.set(extra.shape.q, list);
      replay = list.length;
      if (r.q.size > 50) r.q.delete(r.q.keys().next().value);
    }
    if (extra.status >= 400 && extra.status < 500 && extra.status !== 429) { r.bad.push(now); keep(r.bad); } // the visitor's errors, not ours
    if (extra.status === 404 || a.route === "honeypot") {
      for (const path of [...(Array.isArray(extra.paths) ? extra.paths : []), fp.path]) r.paths.set(path, now); // the held ones first: in order
      for (const [p, t] of r.paths) if (t < since) r.paths.delete(p);
      while (r.paths.size > 100) r.paths.delete(r.paths.keys().next().value);
    }
    const fresh = [];
    if (extra.kind === "csp") { // the reports not seen from this visitor in the window, within the window's allowance
      for (const report of Array.isArray(extra.reports) ? extra.reports : []) {
        const key = `${report?.directive}|${report?.blocked}|${report?.source}`;
        if (r.seen.has(key)) continue;
        keep(r.csp);
        if (r.csp.length >= 20) break;
        r.seen.add(key);
        if (r.seen.size > 50) r.seen.delete(r.seen.values().next().value);
        r.csp.push(now);
        fresh.push(report);
      }
    }
    return { burst, tenMin: r.t.length, replay, bad: r.bad.length, probed: r.paths.size, csp: r.csp.length, fresh };
  }

  row(who) {
    const rows = this.sql.exec("SELECT * FROM watch WHERE who = ?", who).toArray();
    return rows.length ? rows[0] : null;
  }

  /**
   * One request: fp (fingerprint), a (assess), extra {shape, status, kind, report}, cfg (sentinelConfig).  Returns
   * {who, score, reasons, flagged, blocked, shadow, until, retry}: blocked — refuse it; shadow — would be refused in
   * enforce mode.  Nothing is thrown out of here for the request's sake: an error is logged and a neutral answer given.
   */
  async observe(fp, a, extra = {}, cfg = sentinelConfig(), now = Date.now()) {
    const who = await WatchCore.who(fp.ip, cfg, now);
    try {
      return this.record(who, fp, a, extra, cfg, now);
    } catch (err) {
      console.error("sentinel", err?.name || "Error", err?.message || "");
      return { who, score: a.score, reasons: a.reasons, flagged: false, blocked: false, shadow: false, until: 0, retry: 0 };
    }
  }

  record(who, fp, a, extra, cfg, now) {
    this.sweep(now, cfg);
    const w = this.window(who, fp, a, extra, now);
    const reasons = [...a.reasons];
    let score = a.score;
    const add = (reason, n) => { reasons.push(reason); score += n; };
    if (w.burst >= 20) add("burst", 2);
    if (w.replay >= 3) add("replay", 2);
    if (w.bad >= 30) add("errors", 4);
    else if (w.bad >= 10) add("errors", 2);
    if (w.probed >= 8) add("probing", 4);
    else if (w.probed >= 4) add("probing", 2);
    if (extra.kind === "csp" && !w.fresh.length) return { who, score, reasons, flagged: false, blocked: false, shadow: false, until: 0, retry: 0, dropped: true };
    if (extra.shape?.sys) {
      const seen = this.prompts.get(extra.shape.sys) || { n: 0, first: fp.ts, last: fp.ts };
      seen.n += 1; seen.last = fp.ts;
      this.prompts.set(extra.shape.sys, seen);
      if (this.prompts.size > 200) this.flushPrompts(now, true);
    }
    this.flushPrompts(now);
    const prev = this.row(who);
    let p = this.pending.get(who);
    if (!p || !prev) { // a first sighting, or a row swept since: nothing carried over
      if (!p && this.pending.size >= 5000) this.pending.delete(this.pending.keys().next().value);
      p = WatchCore.fresh();
      this.pending.set(who, p);
    }
    p.touched = now;
    // the agents by a short hash: enough to count them (the agent itself is in a flagged visitor's events)
    p.uas = addTo(p.uas, fp.ua ? hashOf(fp.ua) : "-", 10);
    if (extra.status === 404 || a.route === "honeypot") for (const path of [...(Array.isArray(extra.paths) ? extra.paths : []), fp.path]) p.paths = addTo(p.paths, path, 20);
    p.nets = addTo(p.nets, fp.asn !== undefined ? `${fp.asn}/${fp.country || "?"}` : fp.country, 5);
    const merged = (stored, fresh, cap) => fresh.reduce((list, v) => addTo(list, v, cap), parse(stored, []));
    const uas = merged(prev?.uas, p.uas, 10);
    const paths = merged(prev?.paths, p.paths, 20);
    const nets = merged(prev?.nets, p.nets, 5);
    // many agents from one address: a rotating client — or many people behind one address (carrier NAT), so little weight
    if (uas.length >= 10) add("ua_rotation", 2);
    else if (uas.length >= 5) add("ua_rotation", 1);
    // the day's requests by route (the daily caps a Worker may set), kept across writes
    const day = fp.ts.slice(0, 10);
    const today = prev?.day === day ? parse(prev?.today, {}) : {};
    if (prev && prev.day !== day) p.routes = {}; // counts not yet written belong to the day before: a new day starts clean
    for (const [route, n] of Object.entries(p.routes)) today[route] = (today[route] || 0) + n;
    today[a.route] = (today[a.route] || 0) + Math.max(1, Math.floor(Number(extra.count) || 1));
    const flagged = score >= cfg.flagScore;
    const blockedBefore = Number(prev?.blocked_until || 0) > now;
    const honeypot = a.route === "honeypot";
    const wouldBlock = honeypot || score >= cfg.blockScore;
    const enforce = honeypot ? cfg.honeypot === "block" : cfg.mode === "enforce";
    let until = Number(prev?.blocked_until || 0);
    let blocks = Number(prev?.blocks || 0);
    let newBlock = false;
    if (wouldBlock && enforce && !blockedBefore) {
      const hosting = DATACENTER.has(Number(fp.asn));
      until = now + (honeypot ? (hosting ? cfg.honeypotSeconds : Math.min(cfg.honeypotSeconds, cfg.blockSeconds)) : cfg.blockSeconds) * 1000;
      blocks++;
      newBlock = true;
    }
    const blocked = blockedBefore || newBlock;
    const shadow = wouldBlock && !enforce;
    const worth = flagged || blocked || shadow || honeypot || extra.kind === "csp";
    const isBad = (extra.status >= 400 && extra.status < 500 && extra.status !== 429) || blocked;
    const k = Math.max(1, Math.floor(Number(extra.count) || 1)); // requests this one stands for (a Worker may report a reader's quiet minute at once)
    p.n += k;
    if (isBad) p.bad += 1;
    if (flagged) p.flagged += 1;
    p.score = Math.max(p.score, score);
    if (flagged || blocked || shadow) p.ip = fp.ip;
    p.routes[a.route] = (p.routes[a.route] || 0) + k;
    const n = Number(prev?.n || 0) + p.n;
    const bad = Number(prev?.bad || 0) + p.bad;
    // the row is written at a first sighting, a new block, a new day, and otherwise once a minute: a scanner knocking a
    // hundred times costs a row a minute, not a hundred (the events keep the record; the plan counts rows written per
    // day for the whole account)
    if (!prev || newBlock || prev.day !== day || now - p.wrote >= 60000) {
      const ip = p.ip || prev?.ip || null;
      this.sql.exec(
        "INSERT INTO watch (who, ip, first, last, n, bad, flagged, score, uas, paths, nets, blocked_until, blocks, day, today) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) " +
        "ON CONFLICT(who) DO UPDATE SET ip = excluded.ip, last = excluded.last, n = excluded.n, bad = excluded.bad, flagged = flagged + excluded.flagged, " +
        "score = MAX(score, excluded.score), uas = excluded.uas, paths = excluded.paths, nets = excluded.nets, blocked_until = excluded.blocked_until, " +
        "blocks = excluded.blocks, day = excluded.day, today = excluded.today",
        who, ip, prev?.first || fp.ts, fp.ts, n, bad, p.flagged, p.score, JSON.stringify(uas), JSON.stringify(paths), JSON.stringify(nets), until, blocks,
        day, JSON.stringify(today));
      Object.assign(p, WatchCore.fresh(now), { event: p.event, touched: now });
    }
    // an event: at most one every ten seconds for a visitor, one a minute once blocked (a refused scanner keeps
    // knocking); a browser's policy reports come several at a time (one event a POST) and have their own cap
    if (worth && (extra.kind === "csp" || now - p.event >= (blockedBefore ? 60000 : 10000))) {
      if (extra.kind !== "csp") p.event = now;
      const event = { v: VERSION, kind: extra.kind || (honeypot ? "honeypot" : newBlock ? "block" : blocked ? "blocked" : shadow ? "shadow" : "flag"),
        who, own: a.own || undefined, score, reasons, route: a.route, status: extra.status ?? null, fp, shape: extra.shape,
        decision: { mode: cfg.mode, blocked, shadow, until: until > now ? new Date(until).toISOString() : undefined },
        state: { n, bad, flagged: Number(prev?.flagged || 0) + p.flagged, blocks, burst: w.burst, tenMin: w.tenMin,
          replay: w.replay, probed: w.probed, uas: uas.length, paths: paths.slice(-5), nets, today } };
      if (extra.kind === "csp") event.reports = w.fresh;
      const { id } = this.sql.exec("INSERT INTO events (received, event) VALUES (?, ?) RETURNING id", fp.ts, JSON.stringify(event)).one();
      if (cfg.eventKeep && Number(id) % 100 === 0) this.sql.exec("DELETE FROM events WHERE id <= ?", Number(id) - cfg.eventKeep);
    }
    return { who, score, reasons, flagged, blocked, shadow, until, retry: blocked ? Math.max(1, Math.ceil((until - now) / 1000)) : 0, today };
  }

  /** Is this address refused now?  (A cheap check, for a request that is not otherwise recorded.) */
  async blocked(ip, cfg = sentinelConfig(), now = Date.now()) {
    const row = this.row(await WatchCore.who(ip, cfg, now));
    const until = Number(row?.blocked_until || 0);
    return until > now ? { blocked: true, until, retry: Math.max(1, Math.ceil((until - now) / 1000)) } : { blocked: false, until: 0, retry: 0 };
  }

  records(after = 0, limit = 500) {
    const rows = this.sql.exec("SELECT id, received, event FROM events WHERE id > ? ORDER BY id LIMIT ?", after, limit + 1).toArray();
    const more = rows.length > limit;
    const items = rows.slice(0, limit).map((r) => ({ id: Number(r.id), received: r.received, event: JSON.parse(r.event) }));
    return { items, last: items.length ? items[items.length - 1].id : after, more };
  }

  remove(through) {
    this.sql.exec("DELETE FROM events WHERE id <= ?", through);
    return { remaining: Number(this.sql.exec("SELECT COUNT(*) AS n FROM events").one().n) };
  }

  /** What the owner looks at: the visitors by score, the addresses refused now, the events waiting (the counts not yet
   * written are added in). */
  summary(now = Date.now(), limit = 50) {
    this.flushPrompts(now, true);
    const merged = (stored, fresh, cap) => (fresh || []).reduce((list, v) => addTo(list, v, cap), parse(stored, []));
    const strip = (r) => {
      const p = this.pending.get(r.who);
      return { who: r.who, ip: p?.ip || r.ip || undefined, first: r.first, last: r.last, n: Number(r.n) + (p?.n || 0), bad: Number(r.bad) + (p?.bad || 0),
        flagged: Number(r.flagged) + (p?.flagged || 0), score: Math.max(Number(r.score), p?.score || 0), uas: merged(r.uas, p?.uas, 10).length, paths: merged(r.paths, p?.paths, 20),
        nets: merged(r.nets, p?.nets, 5), blocks: Number(r.blocks),
        blocked_until: Number(r.blocked_until) > now ? new Date(Number(r.blocked_until)).toISOString() : undefined, day: r.day || undefined, today: parse(r.today, {}) };
    };
    const top = this.sql.exec("SELECT * FROM watch ORDER BY score DESC, n DESC LIMIT ?", limit).toArray().map(strip);
    const blocked = this.sql.exec("SELECT * FROM watch WHERE blocked_until > ? ORDER BY blocked_until DESC LIMIT ?", now, limit).toArray().map(strip);
    const visitors = Number(this.sql.exec("SELECT COUNT(*) AS n FROM watch").one().n);
    const events = Number(this.sql.exec("SELECT COUNT(*) AS n FROM events").one().n);
    const prompts = this.sql.exec("SELECT sys, n, first, last FROM prompts ORDER BY n DESC LIMIT 10").toArray().map((r) => ({ sys: r.sys, n: Number(r.n), first: r.first, last: r.last }));
    return { v: VERSION, now: new Date(now).toISOString(), visitors, events, blocked, top, prompts };
  }
}

// ------------------------------------------------------------------ the endpoints
/**
 * Under `prefix` (/v1/security on the relay, /api/security on the site):
 *   GET  export?after=&limit=   the events waiting (Bearer token)        POST ack {through}   delete them (Bearer token)
 *   GET  summary                the visitors by score, the blocked (Bearer token)
 *   POST csp                    a browser's Content-Security-Policy report (no token: browsers send them; kept as events)
 * watch: {observe, records, remove, summary} (the Durable Object's methods).  Null when the path is not one of these.
 */
export async function serveSecurity(request, url, { prefix, token, watch, cfg, fp, now = Date.now(), cors = {} }) {
  if (!url.pathname.startsWith(`${prefix}/`)) return null;
  const what = url.pathname.slice(prefix.length + 1);
  const headers = { ...cors };
  if (what === "csp") {
    if (request.method !== "POST") return json({ error: { message: "POST", type: "bad_request" } }, 405, { ...headers, Allow: "POST" });
    if (cfg.mode === "off") return new Response(null, { status: 204, headers });
    const text = await readText(request, 16384);
    if (text === null) return json({ error: { message: "报告过大", type: "too_large" } }, 413, headers);
    if (/(?:chrome|moz|safari-web)-extension:/.test(text)) return new Response(null, { status: 204, headers }); // a browser extension's, not the page's
    const reports = cspReports(text);
    if (reports.length) await watch.observe(fp, assess(fp, { route: "csp", ownPrefix: cfg.ownPrefix }), { kind: "csp", status: 204, reports }, cfg, now); // one round trip a POST
    return new Response(null, { status: 204, headers });
  }
  if (!(await bearerOk(request, token))) return json({ error: { message: "需要收集令牌", type: "unauthorized" } }, 401, headers);
  if (what === "export" && request.method === "GET") {
    const after = Math.max(0, Math.floor(Number(url.searchParams.get("after") || 0)) || 0);
    const limit = Math.min(1000, Math.max(1, Math.floor(Number(url.searchParams.get("limit") || 500)) || 500));
    return json(await watch.records(after, limit), 200, headers);
  }
  if (what === "ack" && request.method === "POST") {
    let body;
    try { body = JSON.parse(await request.text()); } catch { return json({ error: { message: "请求不是有效的 JSON", type: "bad_request" } }, 400, headers); }
    const through = Math.floor(Number(body?.through));
    if (!Number.isFinite(through) || through < 1) return json({ error: { message: "缺少 through", type: "bad_request" } }, 400, headers);
    return json(await watch.remove(through), 200, headers);
  }
  if (what === "summary" && request.method === "GET") return json(await watch.summary(now), 200, headers);
  return json({ error: { message: "没有这个接口", type: "not_found" } }, 404, headers);
}

/** A browser's policy reports — the legacy shape ({"csp-report": {...}}, hyphenated keys) or the Reporting API's (an
 * array of {type: "csp-violation", body: {...}}, camel-cased) — reduced to what the owner needs: the directive, the
 * blocked origin, where in the page; never a query string or a sample of the page's text. */
export function cspReports(text) {
  const j = parse(text, null);
  const bodies = Array.isArray(j) ? j.filter((r) => r && r.type === "csp-violation" && r.body).map((r) => r.body)
    : j && typeof j === "object" ? [j["csp-report"] || j.body || j] : [];
  const origin = (u) => { if (!u || typeof u !== "string") return undefined; try { return new URL(u).origin; } catch { return u.slice(0, 40); } };
  const noQuery = (u) => { if (!u || typeof u !== "string") return undefined; try { const x = new URL(u); return x.origin + x.pathname; } catch { return u.slice(0, 80); } };
  const out = [];
  for (const b of bodies) {
    if (!b || typeof b !== "object") continue;
    const pick = (camel, hyphen) => b[camel] ?? b[hyphen];
    const directive = pick("effectiveDirective", "effective-directive") || pick("violatedDirective", "violated-directive");
    if (!directive) continue;
    out.push({
      directive: String(directive).slice(0, 40), blocked: origin(pick("blockedURL", "blocked-uri")), document: noQuery(pick("documentURL", "document-uri")),
      disposition: pick("disposition", "disposition"), source: noQuery(pick("sourceFile", "source-file")), line: pick("lineNumber", "line-number"),
      status: pick("statusCode", "status-code"),
    });
  }
  return out.slice(0, 10).map((r) => JSON.parse(JSON.stringify(r)));
}

// ------------------------------------------------------------------ Workers Logs
let sampleCounter = 0;

/** One structured line for a request worth a look: a score, a refusal, an error — or one in LOG_SAMPLE others. */
export function logLine(tag, fp, a, w, status, cfg) {
  const score = w?.score ?? a?.score ?? 0;
  const sampled = cfg?.logSample > 0 && ++sampleCounter % cfg.logSample === 0;
  if (!(score >= 1 || (status && status >= 400) || w?.blocked || w?.shadow || sampled)) return null;
  const line = { sentinel: VERSION, tag, route: a?.route, status: status ?? null, score, reasons: w?.reasons || a?.reasons || [],
    who: w?.who, ip: w?.flagged || w?.blocked || w?.shadow ? fp.ip : undefined, blocked: w?.blocked || undefined, shadow: w?.shadow || undefined,
    ua: fp.uaClass, asn: fp.asn, cc: fp.country, colo: fp.colo, method: fp.method, path: fp.path, proto: fp.proto, tls: fp.tls, ray: fp.ray };
  for (const k of Object.keys(line)) if (line[k] === undefined) delete line[k];
  console.log(line); // an object: Workers Logs indexes its fields
  return line;
}
