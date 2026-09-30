// The local D1 emulator (wrangler's platform proxy: workerd's own D1) as a target for the D1 import
// (`python -m taochronos.chat.d1 import … --bridge "node cloud/test/d1-emulator.mjs --state DIR --databases N"`): one JSON
// request a line on stdin — {db, sql, params, mode: "run" | "raw"} or {reset, databases} — one answer a line on
// stdout, with D1's own meta (rows_read, rows_written).  A development tool (the import simulation of ADR 0017), not
// run in CI: it needs wrangler (WRANGLER_DIST: the path of wrangler-dist/cli.js, or `wrangler` resolvable from here).

import { mkdirSync, writeFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { resolve } from "node:path";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : fallback;
};
const state = resolve(arg("--state", ".d1-emulator"));
const databases = Number(arg("--databases", "5"));
const { getPlatformProxy } = await import(process.env.WRANGLER_DIST || "wrangler");

mkdirSync(state, { recursive: true });
const config = [`name = "d1-emulator"`, `main = "worker.js"`, `compatibility_date = "2025-09-01"`];
for (let k = 0; k < databases; k++) {
  config.push("", "[[d1_databases]]", `binding = "D1_${k}"`, `database_name = "taochronos-d1-${k}"`,
    `database_id = "00000000-0000-4000-8000-${String(k).padStart(12, "0")}"`);
}
writeFileSync(`${state}/wrangler.toml`, `${config.join("\n")}\n`);
writeFileSync(`${state}/worker.js`, "export default { fetch() { return new Response('ok'); } };\n");
const proxy = await getPlatformProxy({ configPath: `${state}/wrangler.toml`, persist: { path: `${state}/persist` } });
const say = (x) => process.stdout.write(`${JSON.stringify(x)}\n`);

async function reset(n) {
  for (let k = 0; k < n; k++) {
    const db = proxy.env[`D1_${k}`];
    const { results } = await db.prepare("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'").all();
    const kinds = { trigger: 0, view: 1, table: 2 };
    const drop = results.filter((r) => r.type in kinds && !/^fts_(data|idx|config|docsize|content)$/.test(r.name))
      .sort((a, b) => kinds[a.type] - kinds[b.type] || (a.name === "fts" ? -1 : b.name === "fts" ? 1 : 0));
    for (const r of drop) await db.prepare(`DROP ${r.type.toUpperCase()} IF EXISTS "${r.name}"`).run();
  }
}

say({ ready: true, databases });
const lines = createInterface({ input: process.stdin });
for await (const line of lines) {
  if (!line.trim()) continue;
  const req = JSON.parse(line);
  try {
    if (req.reset) {
      await reset(req.databases || databases);
      say({ ok: true });
      continue;
    }
    const db = proxy.env[`D1_${req.db}`];
    if (!db) throw new Error(`no database ${req.db}`);
    const stmt = db.prepare(req.sql).bind(...(req.params || []));
    if (req.mode === "raw") {
      say({ ok: true, results: await stmt.raw() });
    } else {
      const r = await stmt.run();
      say({ ok: true, meta: r.meta });
    }
  } catch (err) {
    say({ ok: false, error: String(err?.message || err) });
  }
}
await proxy.dispose();
