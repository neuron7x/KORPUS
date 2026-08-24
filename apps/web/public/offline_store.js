const DB_NAME = "korpus-offline-v1";
const STORE = "packs";
const ACTIVE = "active";

function openDatabase(indexedDB) {
  if (!indexedDB) throw new Error("IndexedDB unavailable; offline pack persistence is disabled");
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("offline database open failed"));
  });
}

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("offline database request failed"));
  });
}

export function createOfflinePackStore(indexedDB = globalThis.indexedDB) {
  return Object.freeze({
    async load() {
      const db = await openDatabase(indexedDB);
      try { return await requestResult(db.transaction(STORE, "readonly").objectStore(STORE).get(ACTIVE)); }
      finally { db.close(); }
    },
    async save(pack) {
      if (!pack || typeof pack !== "object") throw new Error("validated offline pack required");
      const db = await openDatabase(indexedDB);
      try { await requestResult(db.transaction(STORE, "readwrite").objectStore(STORE).put(pack, ACTIVE)); }
      finally { db.close(); }
    },
    async clear() {
      const db = await openDatabase(indexedDB);
      try { await requestResult(db.transaction(STORE, "readwrite").objectStore(STORE).delete(ACTIVE)); }
      finally { db.close(); }
    },
  });
}
