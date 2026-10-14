// The relay's two stores, each one Durable Object (SQLite): the counters that limit use, and the conversation records
// waiting to be collected into the repository.  Plain classes over a `sql` object with the Durable Object SQL API's
// shape — exec(query, ...bindings) returning a cursor with toArray() and one() — so that they run under Node in tests.

export const day = (now) => new Date(now).toISOString().slice(0, 10);

/**
 * Fixed windows: per caller per minute (in memory — a minute is lost at worst when the object is evicted), per caller
 * per day and in all per day (stored).  A request is counted only when it is let through.  Tokens — what the answers
 * cost, as the upstream reports them when an answer ends (spend) — per caller per day and in all per day, stored too:
 * a call is refused once the day's tokens are spent, so a visitor's cost is bounded by use, not only by calls.
 */
export class LimiterCore {
  constructor(sql) {
    this.sql = sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS hits (k TEXT PRIMARY KEY, n INTEGER NOT NULL, day TEXT NOT NULL)");
    // the callers answered lately, by a key without the day (a record may come in after midnight): when, last
    this.sql.exec("CREATE TABLE IF NOT EXISTS served (k TEXT PRIMARY KEY, last INTEGER NOT NULL)");
    this.minute = new Map();
    this.currentMinute = -1;
    this.currentDay = null;
  }

  count(key) {
    const rows = this.sql.exec("SELECT n FROM hits WHERE k = ?", key).toArray();
    return rows.length ? Number(rows[0].n) : 0;
  }

  bump(key, today, by = 1) {
    this.sql.exec("INSERT INTO hits (k, n, day) VALUES (?, MAX(0, ?), ?) ON CONFLICT(k) DO UPDATE SET n = MAX(0, n + ?)", key, by, today, by);
  }

  /** limits: {perMinute, perDay, total, tokensPerDay, totalTokens} (total, totalTokens: all callers together per day;
   * 0 = none).  `reserve`: tokens charged now for the call let through (an estimate from the request's size, reconciled
   * by spend() when the answer's usage is known — else thirty calls could be in flight before the first is counted). */
  hit(who, kind, limits, now = Date.now(), reserve = 0) {
    const today = day(now);
    if (today !== this.currentDay) {
      this.sql.exec("DELETE FROM hits WHERE day <> ?", today);
      this.sql.exec("DELETE FROM served WHERE last < ?", now - 2 * 86400000);
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
    if (limits.totalTokens && this.count(`kt:${kind}:${today}`) >= limits.totalTokens) return { ok: false, reason: "total_tokens", retry: secondsToMidnight(now) };
    if (limits.tokensPerDay && this.count(`k:${kind}:${who}:${today}`) >= limits.tokensPerDay) return { ok: false, reason: "tokens", retry: secondsToMidnight(now) };
    this.minute.set(mk, m + 1);
    this.bump(dk, today);
    if (limits.total) this.bump(tk, today);
    const reserved = (limits.tokensPerDay || limits.totalTokens) && reserve > 0 ? Math.floor(reserve) : 0;
    if (reserved) this.spend(who, kind, reserved, now);
    return { ok: true, remaining: limits.perDay ? limits.perDay - d - 1 : null, reserved };
  }

  /** Tokens an answer cost, added to the caller's day and to the day (counted after the fact: the call was let through);
   * negative, what was reserved beyond the cost. */
  spend(who, kind, tokens, now = Date.now()) {
    const n = Math.floor(Number(tokens));
    if (!n) return;
    const today = day(now);
    this.bump(`k:${kind}:${who}:${today}`, today, n);
    this.bump(`kt:${kind}:${today}`, today, n);
  }

  /** Has this caller been let through today, for this kind of call? */
  served(who, kind, now = Date.now()) {
    return this.count(`d:${kind}:${who}:${day(now)}`) > 0;
  }

  /** A caller answered now, by a key that does not change with the day (written at most once in ten minutes). */
  markServed(key, now = Date.now()) {
    const rows = this.sql.exec("SELECT last FROM served WHERE k = ?", key).toArray();
    if (rows.length && now - Number(rows[0].last) < 600000) return;
    this.sql.exec("INSERT INTO served (k, last) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET last = excluded.last", key, now);
  }

  /** Was one of these keys answered in the last `within` milliseconds (a day and two hours: a record of a turn that
   * ended before midnight, sent after)? */
  wasServed(keys, now = Date.now(), within = 26 * 3600000) {
    for (const key of keys) {
      const rows = this.sql.exec("SELECT last FROM served WHERE k = ?", key).toArray();
      if (rows.length && now - Number(rows[0].last) < within) return true;
    }
    return false;
  }

  /** The tokens spent today: by this caller, and by all. */
  spent(who, kind, now = Date.now()) {
    const today = day(now);
    return { caller: this.count(`k:${kind}:${who}:${today}`), all: this.count(`kt:${kind}:${today}`) };
  }
}

const secondsToMidnight = (now) => Math.ceil((86400000 - (now % 86400000)) / 1000);

/**
 * Records in arrival order.  AUTOINCREMENT: an id is never used twice, even after the rows before it were deleted,
 * so the collector's cursor (the last id it committed) stays valid.  A record taken in is kept until it is collected
 * (into the repository, or the archive: security/archive.js): when `keep` are waiting, a new one is refused — never an
 * older one dropped to make room (docs/adr/0023-workers-paid.md).
 */
export class LogBookCore {
  constructor(sql) {
    this.sql = sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, received TEXT NOT NULL, record TEXT NOT NULL)");
    this.size = null; // the records waiting: counted once, then kept here
  }

  waiting() {
    if (this.size === null) this.size = Number(this.sql.exec("SELECT COUNT(*) AS n FROM logs").one().n);
    return this.size;
  }

  /** The record's id, or null when `keep` records wait already (0: no bound). */
  add(record, received, keep = 50000) {
    if (keep && this.waiting() >= keep) return null;
    const { id } = this.sql.exec("INSERT INTO logs (received, record) VALUES (?, ?) RETURNING id", received, record).one();
    if (this.size !== null) this.size += 1;
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
    this.size = null;
    return { remaining: this.waiting() };
  }
}
