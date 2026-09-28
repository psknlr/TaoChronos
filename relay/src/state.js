// The relay's two stores, each one Durable Object (SQLite): the counters that limit use, and the conversation records
// waiting to be collected into the repository.  Plain classes over a `sql` object with the Durable Object SQL API's
// shape — exec(query, ...bindings) returning a cursor with toArray() and one() — so that they run under Node in tests.

export const day = (now) => new Date(now).toISOString().slice(0, 10);

/**
 * Fixed windows: per caller per minute (in memory — a minute is lost at worst when the object is evicted), per caller
 * per day and in all per day (stored).  A request is counted only when it is let through.
 */
export class LimiterCore {
  constructor(sql) {
    this.sql = sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS hits (k TEXT PRIMARY KEY, n INTEGER NOT NULL, day TEXT NOT NULL)");
    this.minute = new Map();
    this.currentMinute = -1;
    this.currentDay = null;
  }

  count(key) {
    const rows = this.sql.exec("SELECT n FROM hits WHERE k = ?", key).toArray();
    return rows.length ? Number(rows[0].n) : 0;
  }

  bump(key, today) {
    this.sql.exec("INSERT INTO hits (k, n, day) VALUES (?, 1, ?) ON CONFLICT(k) DO UPDATE SET n = n + 1", key, today);
  }

  /** limits: {perMinute, perDay, total} (total: all callers together per day; 0 = none). */
  hit(who, kind, limits, now = Date.now()) {
    const today = day(now);
    if (today !== this.currentDay) {
      this.sql.exec("DELETE FROM hits WHERE day <> ?", today);
      this.currentDay = today;
    }
    const minute = Math.floor(now / 60000);
    if (minute !== this.currentMinute) {
      this.minute.clear();
      this.currentMinute = minute;
    }
    const mk = `${kind}:${who}`;
    const m = this.minute.get(mk) || 0;
    const retry = 60 - Math.floor((now / 1000) % 60);
    if (limits.perMinute && m >= limits.perMinute) return { ok: false, reason: "minute", retry };
    const tk = `t:${kind}:${today}`;
    if (limits.total && this.count(tk) >= limits.total) return { ok: false, reason: "total", retry: secondsToMidnight(now) };
    const dk = `d:${kind}:${who}:${today}`;
    const d = this.count(dk);
    if (limits.perDay && d >= limits.perDay) return { ok: false, reason: "day", retry: secondsToMidnight(now) };
    this.minute.set(mk, m + 1);
    this.bump(dk, today);
    if (limits.total) this.bump(tk, today);
    return { ok: true, remaining: limits.perDay ? limits.perDay - d - 1 : null };
  }
}

const secondsToMidnight = (now) => Math.ceil((86400000 - (now % 86400000)) / 1000);

/**
 * Records in arrival order.  AUTOINCREMENT: an id is never used twice, even after the rows before it were deleted,
 * so the collector's cursor (the last id it committed) stays valid.
 */
export class LogBookCore {
  constructor(sql) {
    this.sql = sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, received TEXT NOT NULL, record TEXT NOT NULL)");
  }

  add(record, received, keep = 50000) {
    const { id } = this.sql.exec("INSERT INTO logs (received, record) VALUES (?, ?) RETURNING id", received, record).one();
    if (keep && id % 100 === 0) this.sql.exec("DELETE FROM logs WHERE id <= ?", id - keep); // never collected: the oldest go
    return Number(id);
  }

  records(after = 0, limit = 500) {
    const rows = this.sql.exec("SELECT id, received, record FROM logs WHERE id > ? ORDER BY id LIMIT ?", after, limit + 1).toArray();
    const more = rows.length > limit;
    const items = rows.slice(0, limit).map((r) => ({ id: Number(r.id), received: r.received, record: JSON.parse(r.record) }));
    return { items, last: items.length ? items[items.length - 1].id : after, more };
  }

  remove(through) {
    this.sql.exec("DELETE FROM logs WHERE id <= ?", through);
    return { remaining: Number(this.sql.exec("SELECT COUNT(*) AS n FROM logs").one().n) };
  }
}
