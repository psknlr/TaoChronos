// What the Workers' bindings are under Node, for the tests of the ledger (security/ledger.js, ledger-d1.js) and of the
// Workers that write to it: a Durable Object's SQL and its one alarm, a D1 database, an R2 bucket — each holding to what
// the real one holds to, where a test can depend on it.

import { createHash } from "node:crypto";
import { DatabaseSync } from "node:sqlite";

/** The Durable Object SQL API's shape over node:sqlite. */
export function sqlStore() {
  const db = new DatabaseSync(":memory:");
  return {
    db,
    exec(query, ...params) {
      const stmt = db.prepare(query);
      const rows = /^\s*select|returning/i.test(query) ? stmt.all(...params) : (stmt.run(...params), []);
      return { toArray: () => rows, one: () => { if (rows.length !== 1) throw new Error(`expected one row, got ${rows.length}`); return rows[0]; } };
    },
  };
}

/** A Durable Object's storage, as far as its alarm goes: one alarm, set or not. */
export function alarmStorage() {
  return { at: null, sets: [], async getAlarm() { return this.at; }, async setAlarm(t) { this.at = t; this.sets.push(t); } };
}

/**
 * A D1 database over node:sqlite: prepare/bind/all/first/run and batch — a batch is one transaction, as D1's is, and
 * D1's own limits are held to (a statement of 100 KB, a hundred parameters, a value of two megabytes).  `fail`: a
 * function of the SQL that makes a statement throw (D1 out of reach).
 */
export function d1({ fail = () => false } = {}) {
  const db = new DatabaseSync(":memory:");
  const state = { statements: 0, batches: 0 };
  const run = (sql, params) => {
    state.statements += 1;
    if (fail(sql)) throw new Error("D1_ERROR: unavailable");
    if (Buffer.byteLength(sql) > 100_000) throw new Error("D1_ERROR: statement too long: SQLITE_TOOBIG");
    if (params.length > 100) throw new Error("D1_ERROR: too many SQL variables");
    for (const p of params) if (typeof p === "string" && Buffer.byteLength(p) > 2_000_000) throw new Error("D1_ERROR: string or blob too big: SQLITE_TOOBIG");
    return db.prepare(sql).all(...params.map((p) => (typeof p === "boolean" ? Number(p) : p === undefined ? null : p))).map((r) => ({ ...r }));
  };
  const statement = (sql, params = []) => ({
    sql, params,
    bind: (...next) => statement(sql, next),
    all: async () => ({ results: run(sql, params), success: true }),
    first: async () => run(sql, params)[0] ?? null,
    run: async () => ({ results: run(sql, params), success: true }),
  });
  return {
    sqlite: db, state,
    prepare: (sql) => statement(sql),
    async batch(statements) {
      state.batches += 1;
      db.exec("BEGIN");
      try {
        const out = statements.map((s) => ({ results: run(s.sql, s.params), success: true }));
        db.exec("COMMIT");
        return out;
      } catch (err) {
        db.exec("ROLLBACK");
        throw err;
      }
    },
    /** Rows of a query, for a test's own look. */
    rows: (sql, ...params) => db.prepare(sql).all(...params).map((r) => ({ ...r })),
  };
}

/** An R2 bucket in memory: a put whose sha256 does not match its body is refused, as R2 refuses it; an object is listed
 * with its size and the checksum R2 kept.  `fail(key)` makes a put throw. */
export function bucket({ fail = () => false } = {}) {
  const objects = new Map();
  const puts = [];
  const bytesOf = (body) => (typeof body === "string" ? Buffer.from(body) : Buffer.from(body));
  return {
    objects, puts,
    async put(key, body, options = {}) {
      puts.push(key);
      if (fail(key)) throw new Error("R2 unavailable");
      const bytes = bytesOf(body);
      const sha = createHash("sha256").update(bytes).digest();
      if (options.sha256 && sha.toString("hex") !== options.sha256) throw new Error("sha256 mismatch");
      objects.set(key, { bytes, options, sha });
      return { key, size: bytes.length };
    },
    async get(key) {
      const o = objects.get(key);
      return o ? { text: async () => o.bytes.toString("utf8"), arrayBuffer: async () => o.bytes.buffer.slice(o.bytes.byteOffset, o.bytes.byteOffset + o.bytes.length),
        size: o.bytes.length, customMetadata: o.options.customMetadata } : null;
    },
    async list({ prefix = "", limit = 1000, cursor } = {}) {
      const keys = [...objects.keys()].filter((k) => k.startsWith(prefix)).sort();
      const from = cursor ? Number(cursor) : 0;
      const page = keys.slice(from, from + limit);
      const truncated = from + limit < keys.length;
      return { objects: page.map((key) => ({ key, size: objects.get(key).bytes.length, checksums: { sha256: new Uint8Array(objects.get(key).sha).buffer } })),
        truncated, cursor: truncated ? String(from + limit) : undefined };
    },
    async delete(key) { objects.delete(key); },
  };
}
