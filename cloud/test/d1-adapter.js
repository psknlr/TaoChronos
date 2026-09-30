// A D1 database over node:sqlite, for the tests of the D1 backup (cloud/site/src/backup/): prepare/bind/all/first/raw/
// run and batch, as the Workers binding answers them.  It also measures what a Worker would spend: the SQL runs in the
// database service, not in the Worker, so its time is kept apart (`sqlMs`), while the results are handed over as JSON
// and parsed on the Worker's side, as the binding does.

import { DatabaseSync } from "node:sqlite";

// The Worker's time is measured on the main thread's clock: everything here runs on it (node:sqlite is synchronous),
// and process.cpuUsage() would also count V8's own background threads (compiler, GC helpers) that a Worker's CPU
// time does not.
const cpuMs = () => performance.now();

export class D1Adapter {
  constructor(path, { readOnly = false } = {}) {
    this.sqlite = new DatabaseSync(path, { readOnly });
    this.sqlMs = 0;
    this.statements = 0;
  }

  prepare(sql) {
    return new Statement(this, sql, []);
  }

  async batch(statements) {
    return Promise.all(statements.map((s) => s.all()));
  }

  exec(sql) {
    this.sqlite.exec(sql);
  }

  close() {
    this.sqlite.close();
  }

  /** Run SQL out of the Worker's account; the results come back as the JSON the binding would parse. */
  _run(sql, params, arrays) {
    const start = cpuMs();
    this.statements++;
    try {
      const stmt = this.sqlite.prepare(sql);
      if (arrays) stmt.setReturnArrays(true);
      const rows = stmt.all(...params.map((p) => (typeof p === "boolean" ? Number(p) : p)));
      return JSON.stringify(rows.map((r) => (arrays ? r : { ...r })));
    } finally {
      this.sqlMs += cpuMs() - start;
    }
  }
}

class Statement {
  constructor(db, sql, params) {
    this.db = db;
    this.sql = sql;
    this.params = params;
  }

  bind(...params) {
    return new Statement(this.db, this.sql, params);
  }

  async all() {
    const results = JSON.parse(this.db._run(this.sql, this.params, false));
    return { results, success: true, meta: { rows_read: 0, rows_written: 0 } };
  }

  async first(column) {
    const { results } = await this.all();
    if (!results.length) return null;
    return column ? results[0][column] : results[0];
  }

  async raw() {
    return JSON.parse(this.db._run(this.sql, this.params, true));
  }

  async run() {
    return this.all();
  }
}

/** The Worker's CPU for fn(): all of the process's CPU but the SQL's. */
export async function workerCpu(dbs, fn) {
  const sql0 = dbs.reduce((a, d) => a + d.sqlMs, 0);
  const start = cpuMs();
  const value = await fn();
  const total = cpuMs() - start;
  const sql = dbs.reduce((a, d) => a + d.sqlMs, 0) - sql0;
  return { value, ms: total - sql, sqlMs: sql };
}
