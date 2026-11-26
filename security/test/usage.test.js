// The usage counts under Node (UsageCore on an in-memory SQLite): by day and place, a visitor once a day, the window and
// the one before it, the readers' days, what is pruned, and who may read them.
// Run: node --test security/test/

import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { KINDS, place, serveStats, shiftDay, UsageCore, usageConfig, usageDay } from "../usage.js";

/** The Durable Object SQL API's shape over node:sqlite. */
function sqlStore() {
  const db = new DatabaseSync(":memory:");
  return {
    db,
    exec(query, ...params) {
      const stmt = db.prepare(query);
      const rows = /^\s*select|returning/i.test(query) ? stmt.all(...params) : (stmt.run(...params), []);
      return { toArray: () => rows, one: () => rows[0] };
    },
  };
}

const TOKEN = "stats-token-0123456789abcdef";
const at = (country, region) => ({ country, region });

test("counts add up by day, kind and place, and a visitor is counted once a day", () => {
  const u = new UsageCore(sqlStore());
  const gd = at("CN", "Guangdong");
  u.add([{ day: "2026-10-06", kind: "view", ...gd, n: 3 }, { day: "2026-10-06", kind: "view", ...gd, n: 2 }, { day: "2026-10-06", kind: "view", ...at("US", "California"), n: 1 }]);
  u.add([], [{ day: "2026-10-06", kind: "visitor", who: "a", ...gd }, { day: "2026-10-06", kind: "visitor", who: "a", ...gd },
    { day: "2026-10-06", kind: "visitor", who: "b", ...gd }, { day: "2026-10-07", kind: "visitor", who: "a", ...gd }]);
  u.add([{ day: "2026-10-06", kind: "nonsense", ...gd, n: 9 }, { day: "bad", kind: "view", ...gd, n: 9 }, { day: "2026-10-06", kind: "view", ...gd, n: 0 }]);
  const s = u.stats(2, "2026-10-07");
  assert.deepEqual(s.days, ["2026-10-06", "2026-10-07"]);
  assert.deepEqual(s.daily.view, [6, 0]);
  assert.deepEqual(s.daily.visitor, [2, 1]); // a and b on the 6th, a again on the 7th
  assert.equal(s.totals.view, 6);
  assert.deepEqual(s.today, { view: 0, visitor: 1, question: 0, call: 0, asker: 0 });
  assert.deepEqual(s.places[0], { country: "CN", region: "Guangdong", view: 5, visitor: 3, question: 0, call: 0, asker: 0 });
  assert.deepEqual(s.places[1], { country: "US", region: "California", view: 1, visitor: 0, question: 0, call: 0, asker: 0 });
  assert.deepEqual(Object.keys(s.daily), KINDS);
});

test("the window and the one before it, for the change", () => {
  const u = new UsageCore(sqlStore());
  for (let i = 0; i < 14; i++) u.add([{ day: shiftDay("2026-10-07", -i), kind: "question", ...at("CN", "Beijing"), n: i < 7 ? 2 : 1 }]);
  const s = u.stats(7, "2026-10-07");
  assert.equal(s.days.length, 7);
  assert.equal(s.totals.question, 14);
  assert.equal(s.previous.question, 7);
  assert.equal(u.stats(9999, "2026-10-07").days.length, 366); // at most a year
  assert.equal(u.stats("x", "2026-10-07").days.length, 30);
});

test("the readers' day: UTC+8 by default; a place as Cloudflare names it, cleaned", () => {
  assert.equal(usageDay(Date.UTC(2026, 9, 6, 16, 30), 8), "2026-10-07"); // 00:30 in Beijing
  assert.equal(usageDay(Date.UTC(2026, 9, 6, 15, 59), 8), "2026-10-06");
  assert.equal(usageDay(Date.UTC(2026, 9, 6, 16, 30), 0), "2026-10-06");
  assert.deepEqual(usageConfig({}), { offset: 8 });
  assert.deepEqual(usageConfig({ STATS_TOKEN: " t ", STATS_PUBLIC: "1", STATS_UTC_OFFSET: "-5" }), { offset: -5 }); // no token of its own, no public mode
  assert.equal(usageConfig({ STATS_UTC_OFFSET: "99" }).offset, 8);
  assert.deepEqual(place({ country: "cn", region: "Guang|dong\n" }), { country: "CN", region: "Guangdong" });
  assert.deepEqual(place({ country: "T1" }), { country: "XX", region: "" }); // Tor
  assert.deepEqual(place({}), { country: "XX", region: "" });
});

test("old counts and the visitors' keys are pruned", () => {
  const store = sqlStore();
  const u = new UsageCore(store);
  u.add([{ day: "2025-01-01", kind: "view", ...at("CN", "Hubei"), n: 1 }, { day: "2026-10-01", kind: "view", ...at("CN", "Hubei"), n: 1 }],
    [{ day: "2026-10-01", kind: "visitor", who: "old", ...at("CN", "Hubei") }, { day: "2026-10-06", kind: "visitor", who: "kept", ...at("CN", "Hubei") }]);
  u.add([], [], "2026-10-07");
  assert.deepEqual(store.db.prepare("SELECT day FROM usage ORDER BY day").all().map((r) => r.day), ["2026-10-01", "2026-10-01", "2026-10-06"]);
  assert.deepEqual(store.db.prepare("SELECT who FROM usage_seen").all().map((r) => r.who), ["kept"]); // a key is kept for a day after its own
});

test("the counts are the owner's: read with the collector's token alone, by no page", async () => {
  const u = new UsageCore(sqlStore());
  u.add([{ day: "2026-10-07", kind: "call", ...at("CN", "Zhejiang"), n: 4 }]);
  const ask = (token, days = "7") => new Request(`https://chat-api.impf.ai/v1/stats?days=${days}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const serve = (request, token) => serveStats(request, new URL(request.url), { token, stats: (d) => u.stats(d, "2026-10-07"), today: "2026-10-07", offset: 8 });
  // without the token set on the Worker, nobody; with it, its holder alone — a refusal says nothing of how
  for (const [given, set] of [[TOKEN, ""], [null, TOKEN], ["not-the-token-at-all", TOKEN]]) {
    const res = await serve(ask(given), set);
    assert.equal(res.status, 401);
    assert.deepEqual(await res.json(), { error: "需要收集令牌" });
  }
  const ok = await serve(ask(TOKEN), TOKEN);
  assert.equal(ok.status, 200);
  const body = await ok.json();
  assert.deepEqual([body.v, body.asOf, body.offset, body.totals.call, body.days.length], [1, "2026-10-07", 8, 4, 7]);
  assert.equal(ok.headers.get("Cache-Control"), "no-store");
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), null); // no page reads them, ours or another's
  const post = await serveStats(new Request("https://x/v1/stats", { method: "POST" }), new URL("https://x/v1/stats"), { token: TOKEN, stats: () => ({}) });
  assert.equal(post.status, 405);
});
