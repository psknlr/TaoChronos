// Conversations live in this browser's IndexedDB (a memory map when it is unavailable, e.g. some private windows).
// Nothing here leaves the browser.  A conversation marked `ephemeral` (a diet conversation the visitor has not chosen to
// keep: diet/privacy.js) is never written: it lives only in the page's memory, and is gone when the page is.

const DB = "taochronos";
const STORE = "conversations";
let dbPromise = null;
let current = null; // the open connection, while it is
const memory = new Map();

/** The connection, opened once and kept — until the browser closes it under the page (a tab it reclaims in the
 * background, its storage cleared or failing) or another tab asks to upgrade the database: then it is forgotten, and
 * the next use opens a new one.  null: no IndexedDB here (some private windows), the memory map instead. */
function open() {
  if (dbPromise) return dbPromise;
  const opening = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" }).createIndex("updated", "updated");
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onclose = () => forget(db); // closed by the browser, not by the page
        db.onversionchange = () => forget(db); // another tab's upgrade waits for this connection to close
        current = db;
        resolve(db);
      };
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  dbPromise = opening;
  return opening;
}

/** A connection that is closed, or closing: not used again. */
function forget(db) {
  try { db.close(); } catch { /* closed already */ }
  if (current === db) {
    current = null;
    dbPromise = null;
  }
}

/** A transaction refused because its connection is gone (Chromium: "The database connection is closing"; Safari:
 * "Connection to Indexed Database server lost"): worth one more try on a new connection. */
const connectionGone = (err) => err?.name === "InvalidStateError" || /connection (is )?clos|server lost|closed/i.test(String(err?.message || ""));

function tx(db, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const store = t.objectStore(STORE);
    let result;
    Promise.resolve(fn(store)).then((r) => { result = r; });
    t.oncomplete = () => resolve(result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

/** `fn` in a transaction — once more on a new connection if the browser closed the one the page had.  {db: false} when
 * there is no IndexedDB here. */
async function run(mode, fn) {
  for (let attempt = 0; ; attempt++) {
    const db = await open();
    if (!db) return { db: false };
    try {
      return { db: true, value: await tx(db, mode, fn) };
    } catch (err) {
      if (attempt === 0 && connectionGone(err)) {
        forget(db);
        continue;
      }
      throw err;
    }
  }
}

const req = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

export const persistent = async () => Boolean(await open());

export async function listConversations() {
  const got = await run("readonly", (s) => req(s.getAll()));
  const all = got.db ? got.value : [...memory.values()];
  return (all || []).sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.updated - a.updated);
}

export async function getConversation(id) {
  const got = await run("readonly", (s) => req(s.get(id)));
  return got.db ? got.value : memory.get(id) || null;
}

export async function putConversation(conv) {
  if (conv?.ephemeral) return;
  const copy = structuredClone(conv);
  try {
    const got = await run("readwrite", (s) => req(s.put(copy)));
    if (!got.db) memory.set(copy.id, copy);
  } catch (err) {
    memory.set(copy.id, copy);
    throw err;
  }
}

export async function deleteConversation(id) {
  const got = await run("readwrite", (s) => req(s.delete(id)));
  if (!got.db) memory.delete(id);
}

export async function clearConversations() {
  const got = await run("readwrite", (s) => req(s.clear()));
  if (!got.db) memory.clear();
}
