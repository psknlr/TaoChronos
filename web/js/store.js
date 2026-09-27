// Conversations live in this browser's IndexedDB (a memory map when it is unavailable, e.g. some private windows).
// Nothing here leaves the browser.

const DB = "taochronos";
const STORE = "conversations";
let dbPromise = null;
const memory = new Map();

function open() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" }).createIndex("updated", "updated");
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

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

const req = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

export const persistent = async () => Boolean(await open());

export async function listConversations() {
  const db = await open();
  const all = db ? await tx(db, "readonly", (s) => req(s.getAll())) : [...memory.values()];
  return (all || []).sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.updated - a.updated);
}

export async function getConversation(id) {
  const db = await open();
  return db ? tx(db, "readonly", (s) => req(s.get(id))) : memory.get(id) || null;
}

export async function putConversation(conv) {
  const copy = structuredClone(conv);
  const db = await open();
  if (!db) { memory.set(copy.id, copy); return; }
  try {
    await tx(db, "readwrite", (s) => req(s.put(copy)));
  } catch (err) {
    memory.set(copy.id, copy);
    throw err;
  }
}

export async function deleteConversation(id) {
  const db = await open();
  if (!db) { memory.delete(id); return; }
  await tx(db, "readwrite", (s) => req(s.delete(id)));
}

export async function clearConversations() {
  const db = await open();
  if (!db) { memory.clear(); return; }
  await tx(db, "readwrite", (s) => req(s.clear()));
}
