// Sponsorship (赞助): a visitor gives the default service an API key of their own, and the model it is for, so that more
// visitors can ask.  Such a key spends the visitor's money, so it is kept only here: encrypted (AES-GCM, under a key
// derived from the Worker's secret SPONSOR_SECRET) in a Durable Object of its own (relay/src/index.js, SponsorBook).
// It is never kept with the conversation records (those are collected into the repository), never written to a log,
// never sent back to a browser.  Only the owner reads it, with SPONSOR_SECRET (relay/collect.py sponsors).  The relay
// never calls a sponsored key itself: the owner reviews each one and decides whether to use it.

const encoder = new TextEncoder();
const decoder = new TextDecoder();

/** SPONSOR_SECRET's least length: below it the sponsorship is off (the secret both encrypts and lets the owner read). */
export const SPONSOR_SECRET_MIN = 32;

export const sponsorReady = (env) => String(env?.SPONSOR_SECRET || "").length >= SPONSOR_SECRET_MIN;

const b64 = (bytes) => btoa(String.fromCharCode(...bytes));
const unb64 = (text) => Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

async function hmac(secret, message) {
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(message)));
}

const sealKeys = new Map(); // SPONSOR_SECRET → its AES-GCM key (derived once per isolate)

/** The encryption key: HMAC-SHA-256 of a fixed label under SPONSOR_SECRET, so the secret itself is never the key. */
async function sealKey(secret) {
  if (!sealKeys.has(secret)) {
    const raw = await hmac(secret, "taochronos-sponsor/aes-gcm/v1");
    sealKeys.set(secret, crypto.subtle.importKey("raw", raw, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]));
  }
  return sealKeys.get(secret);
}

/** A key, encrypted: "v1.<iv>.<ciphertext>" (base64; a fresh 96-bit IV each time). */
export async function seal(plain, secret) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await sealKey(secret), encoder.encode(plain)));
  return `v1.${b64(iv)}.${b64(ct)}`;
}

/** The key again, or null when it cannot be opened (SPONSOR_SECRET changed since, or the text is not one of ours). */
export async function unseal(sealed, secret) {
  const m = /^v1\.([A-Za-z0-9+/=]+)\.([A-Za-z0-9+/=]+)$/.exec(String(sealed || ""));
  if (!m) return null;
  try {
    return decoder.decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(m[1]) }, await sealKey(secret), unb64(m[2])));
  } catch {
    return null;
  }
}

/** The same key given twice is one sponsorship: known by a keyed hash of it (it cannot be recovered from this). */
export async function fingerprint(key, secret) {
  return hex(await hmac(secret, `taochronos-sponsor/fingerprint/v1|${key}`)).slice(0, 32);
}

/** What the owner's list shows of a key: enough to tell keys apart, never enough to use one. */
export function hint(key) {
  return key.length >= 16 ? `${key.slice(0, 3)}…${key.slice(-4)}` : `…${key.slice(-2)}`;
}

const CONTROL = /[\u0000-\u001f\u007f]/;
const text = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "");

/**
 * A sponsorship as the page sends it — {v: 1, agree: true, key, model, provider?, base_url?, note?, contact?} — reduced
 * to its known fields and their limits.  Returns {sponsor} or {error} (in words a visitor can act on).  Nothing else
 * the request carries is kept.
 */
export function normalizeSponsor(r) {
  if (!r || typeof r !== "object" || Array.isArray(r) || r.v !== 1) return { error: "赞助信息格式不对" };
  if (r.agree !== true) return { error: "请先勾选同意说明" };
  const key = typeof r.key === "string" ? r.key.trim() : "";
  if (!/^[\x21-\x7e]{8,400}$/.test(key)) return { error: "API Key 格式不对：应为 8～400 个字符，不含空格" };
  const model = text(r.model, 120);
  if (!model || CONTROL.test(model)) return { error: "请填写模型名" };
  const provider = text(r.provider, 60);
  if (CONTROL.test(provider)) return { error: "服务商名称格式不对" };
  let base = "";
  const rawBase = text(r.base_url, 300);
  if (rawBase) {
    let u;
    try { u = new URL(rawBase); } catch { return { error: "接口地址不是有效的网址" }; }
    if (u.protocol !== "https:" || u.username || u.password) return { error: "接口地址须以 https:// 开头，且不含用户名或密码" };
    base = `${u.origin}${u.pathname}`.replace(/\/+$/, ""); // no query, no fragment: a key never travels in one here
  }
  const note = text(r.note, 1000);
  const contact = text(r.contact, 200);
  return { sponsor: { key, model, provider, base_url: base, note, contact } };
}

/** A sponsorship as it is stored: the key encrypted, its fingerprint and hint beside it. */
export async function sealSponsor(s, secret, received) {
  return {
    received, provider: s.provider, base_url: s.base_url, model: s.model, note: s.note, contact: s.contact,
    hint: hint(s.key), fp: await fingerprint(s.key, secret), sealed: await seal(s.key, secret),
  };
}

const PUBLIC_COLUMNS = "id, received, provider, base_url, model, hint, note, contact";

/**
 * The sponsorships, in a Durable Object of their own (SQLite; the same `sql` shape as state.js, so that it runs under
 * Node in tests).  A key given again replaces what was said of it (its model, its note), not adds a row.  At most `keep`
 * are kept: beyond, a new one is refused (none dropped).
 */
export class SponsorBookCore {
  constructor(sql) {
    this.sql = sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS sponsors (id INTEGER PRIMARY KEY AUTOINCREMENT, received TEXT NOT NULL,
      fp TEXT NOT NULL UNIQUE, provider TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL, hint TEXT NOT NULL,
      sealed TEXT NOT NULL, note TEXT NOT NULL, contact TEXT NOT NULL)`);
  }

  /** {id, updated} — or null when `keep` are kept already (0: no bound). */
  add(row, keep = 1000) {
    const known = this.sql.exec("SELECT id FROM sponsors WHERE fp = ?", row.fp).toArray();
    if (known.length) {
      const id = Number(known[0].id);
      this.sql.exec("UPDATE sponsors SET received = ?, provider = ?, base_url = ?, model = ?, note = ?, contact = ?, sealed = ? WHERE id = ?",
        row.received, row.provider, row.base_url, row.model, row.note, row.contact, row.sealed, id);
      return { id, updated: true };
    }
    if (keep && Number(this.sql.exec("SELECT COUNT(*) AS n FROM sponsors").one().n) >= keep) return null;
    const { id } = this.sql.exec(`INSERT INTO sponsors (received, fp, provider, base_url, model, hint, sealed, note, contact)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id`, row.received, row.fp, row.provider, row.base_url, row.model, row.hint,
    row.sealed, row.note, row.contact).one();
    return { id: Number(id), updated: false };
  }

  /** Every sponsorship without its key (the hint only), newest first. */
  list() {
    return this.sql.exec(`SELECT ${PUBLIC_COLUMNS} FROM sponsors ORDER BY id DESC`).toArray().map((r) => ({ ...r, id: Number(r.id) }));
  }

  /** One, with its sealed key (for the owner, who asked for it by id). */
  get(id) {
    const rows = this.sql.exec(`SELECT ${PUBLIC_COLUMNS}, sealed FROM sponsors WHERE id = ?`, id).toArray();
    return rows.length ? { ...rows[0], id: Number(rows[0].id) } : null;
  }

  remove(id) {
    const before = this.sql.exec("SELECT COUNT(*) AS n FROM sponsors WHERE id = ?", id).one().n;
    this.sql.exec("DELETE FROM sponsors WHERE id = ?", id);
    return { removed: Number(before) };
  }
}
