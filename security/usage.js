// Usage by day and place, counted by both Workers: pages opened and by how many visitors (the site), questions asked of
// the default service, the model calls they took and by how many visitors (the relay) — each by the country and
// first-level region Cloudflare places the request in.  No address is kept: a visitor is counted once a day by the
// sentinel's hashed key, and the keys go after two days.  The days are the site's readers' (UTC+8 unless
// STATS_UTC_OFFSET says otherwise).
//
// The counts are the owner's and are shown on no page.  They are read with the collector's token (LOG_EXPORT_TOKEN, a
// secret of the repository and of the Workers) — by the repository's workflows (security/activity.py) — and by nobody
// else: there is no public mode, no token a page asks for, and no answer a browser on another origin may read.

import { bearerOk, json } from "./sentinel.js";

/** view, visitor: the site's; question, call, asker: the relay's.  visitor and asker are counted once a visitor a day. */
export const KINDS = ["view", "visitor", "question", "call", "asker"];
const KEEP_DAYS = 400;
const SEEN_DAYS = 2;
const MAX_DAYS = 366;
const MAX_PLACES = 500;

export function usageConfig(env = {}) {
  const raw = env.STATS_UTC_OFFSET;
  const offset = raw === undefined || raw === null || String(raw).trim() === "" ? 8 : Number(raw);
  return { offset: Number.isFinite(offset) && Math.abs(offset) <= 14 ? offset : 8 };
}

/** The day a moment falls on, `offset` hours from UTC. */
export function usageDay(now, offset = 8) {
  return new Date(now + offset * 3600000).toISOString().slice(0, 10);
}

/** day ± n days. */
export function shiftDay(day, n) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Where a request comes from, as Cloudflare places it: a country's ISO code (XX: unknown) and its first-level region's
 * (ISO 3166-2, without the country: GD for 广东; the page names China's). */
export function place(fp) {
  const code = String(fp?.country || "").toUpperCase();
  return {
    country: /^[A-Z]{2}$/.test(code) && code !== "T1" ? code : "XX",
    region: String(fp?.region || "").replace(/[\u0000-\u001f|]/g, "").trim().slice(0, 60),
  };
}

/** The counts in a Durable Object's SQLite. */
export class UsageCore {
  constructor(sql) {
    this.sql = sql;
    sql.exec("CREATE TABLE IF NOT EXISTS usage (day TEXT NOT NULL, kind TEXT NOT NULL, country TEXT NOT NULL, region TEXT NOT NULL, " +
      "n INTEGER NOT NULL, PRIMARY KEY (day, kind, country, region))");
    sql.exec("CREATE TABLE IF NOT EXISTS usage_seen (day TEXT NOT NULL, kind TEXT NOT NULL, who TEXT NOT NULL, PRIMARY KEY (day, kind, who))");
    this.pruned = "";
  }

  /** counts: [{day, kind, country, region, n}]; seen: [{day, kind, who, country, region}] — a visitor not yet seen that
   * day adds one to its kind.  today: the day to prune from (once a day). */
  add(counts = [], seen = [], today = "") {
    const bump = (day, kind, country, region, n) => this.sql.exec(
      "INSERT INTO usage (day, kind, country, region, n) VALUES (?, ?, ?, ?, ?) " +
      "ON CONFLICT (day, kind, country, region) DO UPDATE SET n = n + excluded.n", day, kind, country, region, n);
    for (const c of counts) {
      const n = Math.floor(Number(c?.n) || 0);
      if (KINDS.includes(c?.kind) && n > 0 && /^\d{4}-\d{2}-\d{2}$/.test(c.day)) bump(c.day, c.kind, String(c.country), String(c.region || ""), n);
    }
    for (const s of seen) {
      if (!KINDS.includes(s?.kind) || !s.who || !/^\d{4}-\d{2}-\d{2}$/.test(s.day)) continue;
      const fresh = this.sql.exec("INSERT INTO usage_seen (day, kind, who) VALUES (?, ?, ?) ON CONFLICT DO NOTHING RETURNING who",
        s.day, s.kind, String(s.who)).toArray();
      if (fresh.length) bump(s.day, s.kind, String(s.country), String(s.region || ""), 1);
    }
    if (today && this.pruned !== today) {
      this.sql.exec("DELETE FROM usage WHERE day < ?", shiftDay(today, -KEEP_DAYS));
      this.sql.exec("DELETE FROM usage_seen WHERE day < ?", shiftDay(today, -(SEEN_DAYS - 1)));
      this.pruned = today;
    }
  }

  /** A call the relay let through: a call, and a question with its visitor once a day when the page asked one. */
  call({ day, country, region, turn }, who) {
    const counts = [{ day, kind: "call", country, region, n: 1 }];
    if (turn) counts.push({ day, kind: "question", country, region, n: 1 });
    this.add(counts, turn && who ? [{ day, kind: "asker", who, country, region }] : [], day);
  }

  /** The `days` days to `today`: each kind a day (daily), over them (totals) and over the as many days before (previous,
   * for the change), today's, and by place over them (the largest first). */
  stats(days, today) {
    const n = Math.min(Math.max(Math.floor(Number(days)) || 30, 1), MAX_DAYS);
    const from = shiftDay(today, -(n - 1));
    const before = shiftDay(today, -(2 * n - 1));
    const list = Array.from({ length: n }, (_, i) => shiftDay(from, i));
    const at = new Map(list.map((d, i) => [d, i]));
    const zero = () => Object.fromEntries(KINDS.map((k) => [k, 0]));
    const daily = Object.fromEntries(KINDS.map((k) => [k, list.map(() => 0)]));
    const totals = zero();
    const previous = zero();
    const rows = this.sql.exec("SELECT day, kind, SUM(n) AS n FROM usage WHERE day >= ? AND day <= ? GROUP BY day, kind", before, today).toArray();
    for (const r of rows) {
      if (!KINDS.includes(r.kind)) continue;
      const v = Number(r.n) || 0;
      if (at.has(r.day)) { daily[r.kind][at.get(r.day)] += v; totals[r.kind] += v; } else previous[r.kind] += v;
    }
    const byPlace = new Map();
    for (const r of this.sql.exec("SELECT country, region, kind, SUM(n) AS n FROM usage WHERE day >= ? AND day <= ? GROUP BY country, region, kind",
      from, today).toArray()) {
      if (!KINDS.includes(r.kind)) continue;
      const key = `${r.country}|${r.region}`;
      if (!byPlace.has(key)) byPlace.set(key, { country: r.country, region: r.region, ...zero() });
      byPlace.get(key)[r.kind] += Number(r.n) || 0;
    }
    const places = [...byPlace.values()].sort((a, b) => (b.view - a.view) || (b.question - a.question) || (b.call - a.call)).slice(0, MAX_PLACES);
    return { days: list, daily, totals, previous, today: Object.fromEntries(KINDS.map((k) => [k, daily[k][n - 1]])), places };
  }
}

/** GET …/stats?days=N: the counts, for the holder of the collector's token (`token`) alone; stats(days) → the counts
 * (null: there are none here — which, too, is told to the holder alone).  No CORS headers: no page, ours or another's,
 * reads them.  Without the token set on the Worker, nobody does. */
export async function serveStats(request, url, { token, stats, today, offset = 8 }) {
  if (request.method !== "GET" && request.method !== "HEAD") return json({ error: "method not allowed" }, 405);
  if (!(await bearerOk(request, token))) return json({ error: "需要收集令牌" }, 401);
  if (!stats) return json({ error: "这里没有统计" }, 404);
  const days = Math.min(Math.max(Math.floor(Number(url.searchParams.get("days"))) || 30, 1), MAX_DAYS);
  return json({ v: 1, asOf: today, offset, ...(await stats(days)) }, 200); // today: its counts
}
