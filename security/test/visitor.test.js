// The visitor's id (security/visitor.js) under Node: the cookie the site issues and reads, what it refuses, the id the
// ledger keeps, the pass the relay reads, and who gets none.  Run: node --test security/test/

import assert from "node:assert/strict";
import test from "node:test";

import { clearCookie, COOKIE, cookieValue, dayAlias, declines, identify, isVisitor, ledgerConfig, mint, passFor, readCookie, readPass, setCookie,
  turnKey, visitorOf } from "../visitor.js";

const KEY = "activity-key-for-tests-0123456789abcdef";
const OTHER = "another-key-for-tests-0123456789abcdef!";
const T0 = Date.UTC(2026, 10, 25, 12, 0, 0);
const DAY = 86400000;
const cfg = (env = {}) => ledgerConfig({ ACTIVITY_KEY: KEY, ...env });
const req = (headers = {}) => new Request("https://chat.impf.ai/", { headers });

test("without the key there is no ledger; with it, ids by notice unless set otherwise", () => {
  assert.equal(ledgerConfig({}).on, false);
  assert.equal(ledgerConfig({ ACTIVITY_KEY: "short" }).on, false);
  assert.equal(ledgerConfig({}).ids, "off");
  const c = cfg();
  assert.equal(c.on, true);
  assert.equal(c.ids, "notice");
  assert.equal(c.visitorDays, 390);
  assert.equal(c.passMs, 86400000);
  assert.equal(cfg({ ACTIVITY: "off" }).on, false);
  assert.equal(cfg({ ACTIVITY: "off" }).key, ""); // nothing is signed for a ledger that is off
  assert.equal(cfg({ ACTIVITY_IDS: "optin" }).ids, "optin");
  assert.equal(cfg({ ACTIVITY_IDS: "nonsense" }).ids, "notice");
  assert.equal(cfg({ VISITOR_DAYS: "-3" }).visitorDays, 390); // a number that makes no sense: the default
});

test("a cookie the site issued is read back as the same visitor; the id says nothing of the cookie", async () => {
  const made = await mint(KEY, T0);
  assert.match(made.value, /^[A-Za-z0-9_-]{22}\.[0-9a-z]+\.[A-Za-z0-9_-]{22}$/);
  assert.ok(isVisitor(made.visitor));
  const seen = await readCookie(`a=1; ${COOKIE}=${made.value}; b=2`, KEY, T0 + 5 * DAY);
  assert.deepEqual(seen, { state: "valid", visitor: made.visitor, issued: made.issued, left: 385 });
  assert.equal(made.visitor, await visitorOf(made.value.split(".")[0], KEY));
  assert.ok(!made.value.includes(made.visitor.slice(2)));
  const again = await mint(KEY, T0);
  assert.notEqual(again.visitor, made.visitor); // random: two browsers are two visitors
  // another key: another id for the same cookie, and the cookie itself is not one it signed
  assert.notEqual(await visitorOf(made.value.split(".")[0], OTHER), made.visitor);
  assert.equal((await readCookie(`${COOKIE}=${made.value}`, OTHER, T0)).state, "forged");
});

test("a cookie lasts from the day it was issued, never longer; what the site did not issue is refused", async () => {
  const made = await mint(KEY, T0);
  const header = `${COOKIE}=${made.value}`;
  assert.equal((await readCookie(header, KEY, T0 + 390 * DAY)).state, "valid");
  assert.equal((await readCookie(header, KEY, T0 + 391 * DAY)).state, "expired");
  assert.equal((await readCookie(header, KEY, T0 + 20 * DAY, 10)).state, "expired");
  assert.equal((await readCookie(header, KEY, T0 - 3 * DAY)).state, "forged"); // issued in the future
  const [id, issued, sig] = made.value.split(".");
  const later = (parseInt(issued, 36) + 300).toString(36); // the day moved on, to live longer: the signature covers it
  for (const forged of [`${id}.${later}.${sig}`, `${id}.${issued}.${"A".repeat(22)}`, `${"B".repeat(22)}.${issued}.${sig}`, "x.y.z", "v_0123", `${id}.${issued}`]) {
    assert.equal((await readCookie(`${COOKIE}=${forged}`, KEY, T0)).state, "forged", forged);
  }
  assert.equal((await readCookie("", KEY, T0)).state, "none");
  assert.equal((await readCookie("other=1", KEY, T0)).state, "none");
  assert.equal((await readCookie(`${COOKIE}=off`, KEY, T0)).state, "off");
  assert.equal(cookieValue(`x=1; ${COOKIE}=abc`), "abc");
  assert.equal(cookieValue(`not${COOKIE}=abc`), null);
});

test("the cookie is the site's alone: host-only, HttpOnly, sent over https, kept for the days it has left", () => {
  assert.equal(setCookie("abc", 390), `${COOKIE}=abc; Path=/; Max-Age=33696000; Secure; HttpOnly; SameSite=Lax`);
  assert.ok(COOKIE.startsWith("__Host-")); // a browser keeps it only without a Domain: no other impf.ai host is sent it
  assert.match(clearCookie(), /Max-Age=0/);
});

test("who gets an id: a page a browser opens, in notice mode — not one that asks not to be tracked or switched it off", async () => {
  const c = cfg();
  const fresh = await identify(req(), c, T0, { mintable: true });
  assert.equal(fresh.state, "new");
  assert.ok(isVisitor(fresh.visitor));
  assert.match(fresh.cookie, /^__Host-tcv=[^;]+; Path=\/; Max-Age=33696000; Secure; HttpOnly; SameSite=Lax$/);
  const value = fresh.cookie.split(";")[0];
  const back = await identify(req({ Cookie: value }), c, T0 + 1000, { mintable: true });
  assert.deepEqual({ state: back.state, visitor: back.visitor, cookie: back.cookie }, { state: "valid", visitor: fresh.visitor, cookie: null });
  // an API call, or a tool's request, is never given one
  assert.deepEqual(await identify(req(), c, T0), { state: "none", visitor: null, cookie: null });
  // Global Privacy Control and Do Not Track: no id is made, and one the browser already holds is not used
  for (const h of [{ "Sec-GPC": "1" }, { DNT: "1" }]) {
    assert.equal(declines(req(h)), true);
    assert.deepEqual(await identify(req({ ...h, Cookie: value }), c, T0, { mintable: true }), { state: "declined", visitor: null, cookie: null });
  }
  assert.equal(declines(req({ DNT: "0" })), false);
  // switched off under 设置 → 数据: none is made again
  assert.deepEqual(await identify(req({ Cookie: `${COOKIE}=off` }), c, T0, { mintable: true }), { state: "off", visitor: null, cookie: null });
  // an expired or a forged cookie is replaced by a new visitor
  const old = await identify(req({ Cookie: value }), c, T0 + 400 * DAY, { mintable: true });
  assert.equal(old.state, "new");
  assert.notEqual(old.visitor, fresh.visitor);
  assert.equal((await identify(req({ Cookie: `${COOKIE}=a.b.c` }), c, T0, { mintable: true })).state, "new");
});

test("optin: an id only once the user asked for one; off, or no ledger: none at all", async () => {
  const optin = cfg({ ACTIVITY_IDS: "optin" });
  assert.equal((await identify(req(), optin, T0, { mintable: true })).state, "none");
  const asked = await identify(req(), optin, T0, { optedIn: true });
  assert.equal(asked.state, "new");
  assert.equal((await identify(req({ Cookie: asked.cookie.split(";")[0] }), optin, T0, { mintable: true })).state, "valid");
  // switched off, then on again: the choice endpoint makes a new one over "off"
  assert.equal((await identify(req({ Cookie: `${COOKIE}=off` }), cfg(), T0, { optedIn: true })).state, "new");
  assert.equal((await identify(req({ "Sec-GPC": "1" }), cfg(), T0, { optedIn: true })).state, "declined"); // the browser's word stands
  for (const none of [cfg({ ACTIVITY_IDS: "off" }), ledgerConfig({}), cfg({ ACTIVITY: "off" })]) {
    assert.deepEqual(await identify(req(), none, T0, { mintable: true, optedIn: true }), { state: "disabled", visitor: null, cookie: null });
  }
});

test("the pass names its visitor to whoever has the key, for a day", async () => {
  const visitor = (await mint(KEY, T0)).visitor;
  const pass = await passFor(visitor, KEY, T0);
  assert.equal(await readPass(pass, KEY, T0 + 23 * 3600000), visitor);
  assert.equal(await readPass(pass, KEY, T0 + 25 * 3600000), null); // past its time
  assert.equal(await readPass(pass, OTHER, T0), null);
  const [v, exp, sig] = pass.split(".");
  const longer = (parseInt(exp, 36) + 86400 * 30).toString(36);
  for (const bad of [`${v}.${longer}.${sig}`, `v_${"0".repeat(24)}.${exp}.${sig}`, `${v}.${exp}`, "", null, "a.b.c", `${v}.${exp}.${sig}.x`]) {
    assert.equal(await readPass(bad, KEY, T0), null, String(bad));
  }
  // a cookie's value is not a pass, nor a pass a cookie: each use has its own key
  const made = await mint(KEY, T0);
  assert.equal(await readPass(made.value, KEY, T0), null);
  assert.equal((await readCookie(`${COOKIE}=${pass}`, KEY, T0)).state, "forged");
});

test("a turn's key and a visitor's name for a day are keyed; without a key a turn is a plain digest", async () => {
  const keyed = await turnKey("m_abc123", KEY);
  assert.match(keyed, /^t[0-9a-f]{32}$/);
  assert.equal(keyed, await turnKey("m_abc123", KEY));
  assert.notEqual(keyed, await turnKey("m_abc123", OTHER));
  assert.notEqual(keyed, await turnKey("m_abc123")); // the unkeyed digest anyone could compute is not what is kept
  assert.notEqual(keyed, await turnKey("m_abc124", KEY));
  const v = "v_0123456789abcdef01234567";
  const d1 = await dayAlias(v, "2026-11-25", KEY);
  assert.match(d1, /^d_[0-9a-f]{20}$/);
  assert.equal(d1, await dayAlias(v, "2026-11-25", KEY));
  assert.notEqual(d1, await dayAlias(v, "2026-11-26", KEY)); // another day, another name
  assert.ok(!d1.includes(v.slice(2, 12)));
});

test("a key that could not be derived is asked for again, not kept as a failure", async () => {
  // the keys are derived once and kept (keyFor); one failure to derive must not be every later request's
  const NEW = "a-key-no-other-test-has-derived-0123456789";
  const sign = crypto.subtle.sign;
  let failing = true;
  crypto.subtle.sign = function (...args) { return failing ? Promise.reject(new Error("no signature now")) : sign.apply(this, args); };
  try {
    await assert.rejects(mint(NEW, T0), /no signature now/);
    await assert.rejects(turnKey("m_abc123", NEW), /no signature now/);
    failing = false;
    const made = await mint(NEW, T0); // the same key, the same labels: asked for again, and made
    assert.equal((await readCookie(`${COOKIE}=${made.value}`, NEW, T0)).visitor, made.visitor);
    assert.match(await turnKey("m_abc123", NEW), /^t[0-9a-f]{32}$/);
  } finally {
    delete crypto.subtle.sign;
  }
  assert.equal(crypto.subtle.sign, sign);
});
