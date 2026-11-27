// 访客编号 — who a browser is to the activity ledger (security/ledger.js), without the ledger knowing who anyone is.
// Shared by both Workers, as the sentinel is; tested under Node (security/test/visitor.test.js).
//
// The sentinel knows a visitor by a hash of the address, which is the right key for a limit and the wrong one for a
// count: fifty people behind a hospital's address are one visitor, and one person on a phone is a new visitor with every
// cell tower.  The ledger counts browsers instead:
//
//   the cookie    __Host-tcv = <id>.<day issued>.<mac> — 128 random bits, set by the site's Worker on a page a browser
//                 opens, HttpOnly (no script reads it), host-only (it goes to chat.impf.ai and nowhere else), signed (an
//                 id the site did not issue is not counted), and good for VISITOR_DAYS from the day it was issued: a
//                 visit does not extend it, so the same browser is a new visitor after thirteen months
//   the id        v_<24 hex> = HMAC(key, id) — what the ledger keeps.  The cookie's own value is kept nowhere: whoever
//                 reads the ledger cannot make a cookie from it, and whoever holds a cookie cannot find its rows without
//                 the key
//   the pass      <id>.<expiry>.<mac>, a day long — what the page shows the relay (X-Tao-Visitor) so that a question
//                 asked of 道乃久默认服务 counts for the same visitor: the relay is another host, and a cookie that
//                 reached it would have to reach every *.impf.ai host
//
// What is never part of it: the address, the user agent, a canvas or a font list — a fingerprint identifies people who
// did not agree to be told apart; a cookie is theirs to delete.  A browser that asks not to be tracked (Sec-GPC, DNT) or
// whose user switched the count off (设置 → 数据: the cookie's value is then "off") gets no id, and what it does is
// counted without one.  The key (ACTIVITY_KEY, a secret of both Workers) must stay what it is: with another key every
// browser is a new visitor.  Without it there is no ledger, and the Workers are what they were.

export const COOKIE = "__Host-tcv";
export const OFF = "off";

export const DEFAULTS = {
  ACTIVITY: "on",               // off: no ledger, whatever else is set
  // notice — a browser gets an id unless it asks not to be tracked or its user switched the count off;
  // optin — only after the user switched it on (设置 → 数据); off — no ids: everything is counted without a visitor
  ACTIVITY_IDS: "notice",
  VISITOR_DAYS: "390",          // an id's life from the day it was issued, never extended (13 months)
  VISITOR_PASS_HOURS: "24",     // the pass the page shows the relay
  SESSION_GAP_MINUTES: "30",    // a visit ends when a visitor does nothing for this long
  ACTIVITY_EVENT_DAYS: "90",    // the events themselves, in D1: after this only the day's sums remain
  ACTIVITY_VISITOR_DAYS: "760", // a visitor's rows after their last visit (25 months); then they are deleted, and counted as having been
  ACTIVITY_TURN_DAYS: "7",      // how long the relay remembers which turn a call belongs to (the only link to a conversation)
  ACTIVITY_KEEP: "200000",      // events waiting to be written at most: beyond, new ones are dropped and counted as lost
  ACTIVITY_MIN_CELL: "1",       // the stats' places with fewer visitors than this are folded into "other" (the reports use their own)
};

export function ledgerConfig(env = {}) {
  const get = (k) => (env[k] !== undefined && env[k] !== "" ? String(env[k]) : DEFAULTS[k]);
  const num = (k, least = 0) => { const v = Number(get(k)); return Number.isFinite(v) && v >= least ? v : Number(DEFAULTS[k]); };
  const key = String(env.ACTIVITY_KEY || "").trim();
  const ids = get("ACTIVITY_IDS").toLowerCase();
  const on = get("ACTIVITY").toLowerCase() !== "off" && key.length >= 32;
  return {
    on,
    key: on ? key : "",
    ids: !on ? "off" : ["notice", "optin", "off"].includes(ids) ? ids : "notice",
    visitorDays: Math.floor(num("VISITOR_DAYS", 1)),
    passMs: Math.round(num("VISITOR_PASS_HOURS", 0.01) * 3600000),
    gapMinutes: num("SESSION_GAP_MINUTES", 1),
    eventDays: Math.floor(num("ACTIVITY_EVENT_DAYS", 1)),
    keepDays: Math.floor(num("ACTIVITY_VISITOR_DAYS", 1)),
    turnDays: num("ACTIVITY_TURN_DAYS", 0.01),
    keep: Math.floor(num("ACTIVITY_KEEP", 0)),
    minCell: Math.floor(num("ACTIVITY_MIN_CELL", 1)),
  };
}

// ------------------------------------------------------------------ keys
const encoder = new TextEncoder();
const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hmacKey = (raw) => crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);

// one key for each use, derived from the secret: what is signed for one purpose is never valid for another
const derived = new Map(); // `${secret}\n${label}` → Promise<CryptoKey>

function keyFor(secret, label) {
  const at = `${secret}\n${label}`;
  if (!derived.has(at)) {
    if (derived.size > 64) derived.clear();
    const made = (async () => hmacKey(await crypto.subtle.sign("HMAC", await hmacKey(encoder.encode(secret)), encoder.encode(`taochronos/ledger/v1/${label}`))))();
    derived.set(at, made);
    // one that could not be made is not kept: the next request asks again, where every one after it would have failed
    made.catch(() => { if (derived.get(at) === made) derived.delete(at); });
  }
  return derived.get(at);
}

const mac = async (secret, label, text) => new Uint8Array(await crypto.subtle.sign("HMAC", await keyFor(secret, label), encoder.encode(text)));

/** Two strings compared without their difference showing in the time it takes. */
function same(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

// ------------------------------------------------------------------ the cookie and the id
const ID = /^[A-Za-z0-9_-]{22}$/;
const DAY36 = /^[0-9a-z]{1,6}$/;
const MAC = /^[A-Za-z0-9_-]{22}$/;
const VISITOR = /^v_[0-9a-f]{24}$/;
const dayNumber = (now) => Math.floor(now / 86400000);

/** Is this a visitor's id as the ledger keeps it? */
export const isVisitor = (v) => typeof v === "string" && VISITOR.test(v);

/** The ledger's id for a cookie's id. */
export const visitorOf = async (id, secret) => `v_${hex(await mac(secret, "visitor", id)).slice(0, 24)}`;

/** A new visitor: {value (the cookie's), visitor (the ledger's id), issued (the day, as days since 1970)}. */
export async function mint(secret, now = Date.now()) {
  const id = b64url(crypto.getRandomValues(new Uint8Array(16)));
  const issued = dayNumber(now);
  const body = `${id}.${issued.toString(36)}`;
  return { value: `${body}.${b64url(await mac(secret, "cookie", body)).slice(0, 22)}`, visitor: await visitorOf(id, secret), issued };
}

/** The cookie's value among a request's cookies, or null. */
export function cookieValue(header, name = COOKIE) {
  for (const part of String(header || "").split(";")) {
    const at = part.indexOf("=");
    if (at > 0 && part.slice(0, at).trim() === name) return part.slice(at + 1).trim();
  }
  return null;
}

/**
 * What a request's cookie says: {state: "none"} (it has none), {state: "off"} (the user switched the count off),
 * {state: "valid", visitor, issued, left} (left: the days it still lasts), {state: "expired"}, or {state: "forged"} —
 * not one this site issued with this key.
 */
export async function readCookie(header, secret, now = Date.now(), days = Number(DEFAULTS.VISITOR_DAYS)) {
  const value = cookieValue(header);
  if (value === null || value === "") return { state: "none" };
  if (value === OFF) return { state: "off" };
  const parts = value.split(".");
  if (parts.length !== 3 || !ID.test(parts[0]) || !DAY36.test(parts[1]) || !MAC.test(parts[2])) return { state: "forged" };
  if (!same(b64url(await mac(secret, "cookie", `${parts[0]}.${parts[1]}`)).slice(0, 22), parts[2])) return { state: "forged" };
  const issued = parseInt(parts[1], 36);
  const age = dayNumber(now) - issued;
  if (age < -1) return { state: "forged" }; // issued in the future: not by this clock
  if (age > days) return { state: "expired" };
  return { state: "valid", visitor: await visitorOf(parts[0], secret), issued, left: Math.max(0, days - age) };
}

/** The Set-Cookie header for a value that lasts `days` more days ("off" lasts as long as an id would). */
export const setCookie = (value, days) =>
  `${COOKIE}=${value}; Path=/; Max-Age=${Math.max(1, Math.round(days)) * 86400}; Secure; HttpOnly; SameSite=Lax`;

/** The Set-Cookie header that takes the cookie away. */
export const clearCookie = () => `${COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax`;

/** Does the browser ask not to be tracked (Global Privacy Control, or the older Do Not Track)? */
export const declines = (request) => request.headers.get("Sec-GPC") === "1" || request.headers.get("DNT") === "1";

/**
 * Who a request is, for the ledger: {state, visitor, cookie}.
 *
 *   state    disabled (no ledger, or no ids) · declined (the browser asks not to be tracked) · off (the user switched the
 *            count off) · valid · new (an id was just made: `cookie` is the Set-Cookie to send) · none (no id, and none
 *            is made for this request)
 *   visitor  the ledger's id, when there is one (valid, new)
 *
 * mintable: may this request be given an id — a page a browser opened, never an API call, a tool's request, or what
 * another site's page made a browser send.  optedIn: the user asked for one just now (the choice endpoint), which is
 * the only way to one in "optin" mode.
 */
export async function identify(request, cfg, now = Date.now(), { mintable = false, optedIn = false } = {}) {
  if (!cfg?.on || cfg.ids === "off") return { state: "disabled", visitor: null, cookie: null };
  if (declines(request)) return { state: "declined", visitor: null, cookie: null };
  const seen = await readCookie(request.headers.get("Cookie"), cfg.key, now, cfg.visitorDays);
  if (seen.state === "off" && !optedIn) return { state: "off", visitor: null, cookie: null };
  if (seen.state === "valid") return { state: "valid", visitor: seen.visitor, issued: seen.issued, cookie: null };
  if (optedIn || (mintable && cfg.ids === "notice")) {
    const made = await mint(cfg.key, now);
    return { state: "new", visitor: made.visitor, issued: made.issued, cookie: setCookie(made.value, cfg.visitorDays) };
  }
  return { state: "none", visitor: null, cookie: null };
}

// ------------------------------------------------------------------ the pass
const EXP36 = /^[0-9a-z]{1,9}$/;

/** A pass for a visitor, good for `ttl` milliseconds: what the page shows the relay. */
export async function passFor(visitor, secret, now = Date.now(), ttl = Number(DEFAULTS.VISITOR_PASS_HOURS) * 3600000) {
  const body = `${visitor}.${Math.floor((now + ttl) / 1000).toString(36)}`;
  return `${body}.${b64url(await mac(secret, "pass", body)).slice(0, 22)}`;
}

/** The visitor a pass is for, or null: not one this key signed, or past its time. */
export async function readPass(pass, secret, now = Date.now()) {
  const parts = String(pass || "").split(".");
  if (parts.length !== 3 || !VISITOR.test(parts[0]) || !EXP36.test(parts[1]) || !MAC.test(parts[2])) return null;
  if (!same(b64url(await mac(secret, "pass", `${parts[0]}.${parts[1]}`)).slice(0, 22), parts[2])) return null;
  return parseInt(parts[1], 36) * 1000 > now ? parts[0] : null;
}

// ------------------------------------------------------------------ what else is keyed
/**
 * A turn as the relay remembers it for a few days (security/ledger.js, ledger_turns): keyed, so that the page's own id
 * of a turn — which a conversation record carries in clear — cannot be looked up there by whoever holds the records.
 * Without a key (no ledger) a plain digest: the table then holds nothing but the count.
 */
export async function turnKey(id, secret = "") {
  const text = String(id);
  if (secret) return `t${hex(await mac(secret, "turn", text)).slice(0, 32)}`;
  return `t${hex(await crypto.subtle.digest("SHA-256", encoder.encode(text))).slice(0, 32)}`;
}

/** A visitor's name in the archive for one day: the same all that day, another the next — the archive's files say how
 * many visitors a day had, and never that two days' visitors were the same one. */
export const dayAlias = async (visitor, day, secret) => `d_${hex(await mac(secret, "day", `${visitor}|${day}`)).slice(0, 20)}`;
