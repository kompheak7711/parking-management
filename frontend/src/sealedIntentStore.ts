/** Shared actor-keyed reservation; preserves the existing billing database format. */
export const INTENT_DATABASE = "property-rental.billing-intent.v1";
export const MAX_SEALED_INTENT_BYTES = 1_048_576;

export class IntentStorageError extends Error {
  constructor() {
    super("Financial recovery unavailable. Commands remain blocked.");
    this.name = "IntentStorageError";
  }
}
export interface OpenIntent {
  requestKey: string;
  plaintext: string;
}
interface SealedIntent {
  key: CryptoKey;
  iv: Uint8Array<ArrayBuffer>;
  ciphertext: ArrayBuffer;
  requestKey: string;
}

function identity(value: string): void {
  if (typeof value !== "string" || !value || value.length > 1024)
    throw new IntentStorageError();
  if (
    new TextDecoder("utf-8", { fatal: true }).decode(
      new TextEncoder().encode(value),
    ) !== value
  )
    throw new IntentStorageError();
}
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const fail = () => {
      settled = true;
      reject(new IntentStorageError());
    };
    const request = indexedDB.open(INTENT_DATABASE, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains("pending"))
        request.result.createObjectStore("pending");
    };
    request.onerror = request.onblocked = fail;
    request.onsuccess = () => {
      const db = request.result;
      if (settled) {
        db.close();
        return;
      }
      settled = true;
      db.onversionchange = () => {
        db.close();
      };
      resolve(db);
    };
  });
}

async function transaction<T>(
  actorId: string,
  mode: IDBTransactionMode,
  apply: (store: IDBObjectStore, stored: unknown) => T,
): Promise<T> {
  identity(actorId);
  const db = await database();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction("pending", mode);
      const store = tx.objectStore("pending");
      const request = store.get(actorId);
      let result: T;
      tx.oncomplete = () => {
        resolve(result);
      };
      tx.onerror = tx.onabort = () => {
        reject(new IntentStorageError());
      };
      request.onsuccess = () => {
        try {
          result = apply(store, request.result as unknown);
        } catch {
          tx.abort();
        }
      };
    });
  } finally {
    db.close();
  }
}

function sealed(value: unknown): SealedIntent {
  if (!value || typeof value !== "object") throw new IntentStorageError();
  const record = value as Partial<SealedIntent>;
  if (
    Object.keys(value).length !== 4 ||
    !record.key ||
    record.key.type !== "secret" ||
    record.key.extractable ||
    record.key.algorithm.name !== "AES-GCM" ||
    (record.key.algorithm as AesKeyAlgorithm).length !== 256 ||
    !(record.iv instanceof Uint8Array) ||
    record.iv.byteLength !== 12 ||
    !(record.ciphertext instanceof ArrayBuffer) ||
    record.ciphertext.byteLength < 16 ||
    record.ciphertext.byteLength > MAX_SEALED_INTENT_BYTES + 16 ||
    typeof record.requestKey !== "string"
  )
    throw new IntentStorageError();
  identity(record.requestKey);
  return record as SealedIntent;
}

export interface SealedIntentStore {
  read(actorId: string): Promise<OpenIntent | null>;
  begin(actorId: string, intent: OpenIntent): Promise<void>;
  clear(actorId: string, requestKey: string): Promise<void>;
}

/** Plaintext exists only in memory; no tokens, command dispatch or automatic replay. */
export const sealedIntentStore: SealedIntentStore = {
  async read(actorId) {
    try {
      const stored = await transaction(
        actorId,
        "readonly",
        (_store, value) => value,
      );
      if (stored === undefined) return null;
      const record = sealed(stored);
      const plaintext = await crypto.subtle.decrypt(
        {
          name: "AES-GCM",
          iv: record.iv,
          additionalData: new TextEncoder().encode(actorId),
        },
        record.key,
        record.ciphertext,
      );
      return {
        requestKey: record.requestKey,
        plaintext: new TextDecoder("utf-8", { fatal: true }).decode(plaintext),
      };
    } catch {
      throw new IntentStorageError();
    }
  },
  async begin(actorId, intent) {
    try {
      const { requestKey, plaintext } = intent;
      identity(actorId);
      identity(requestKey);
      if (
        typeof plaintext !== "string" ||
        plaintext.length > MAX_SEALED_INTENT_BYTES
      )
        throw new IntentStorageError();
      const data = new TextEncoder().encode(plaintext);
      if (
        data.byteLength > MAX_SEALED_INTENT_BYTES ||
        new TextDecoder("utf-8", { fatal: true }).decode(data) !== plaintext
      )
        throw new IntentStorageError();
      const key = await crypto.subtle.generateKey(
        { name: "AES-GCM", length: 256 },
        false,
        ["encrypt", "decrypt"],
      );
      const iv = crypto.getRandomValues(new Uint8Array(12));
      const ciphertext = await crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv,
          additionalData: new TextEncoder().encode(actorId),
        },
        key,
        data,
      );
      await transaction(actorId, "readwrite", (store, existing) => {
        if (existing !== undefined) throw new IntentStorageError();
        store.put(
          { key, iv, ciphertext, requestKey } satisfies SealedIntent,
          actorId,
        );
      });
    } catch {
      throw new IntentStorageError();
    }
  },
  async clear(actorId, requestKey) {
    try {
      identity(requestKey);
      await transaction(actorId, "readwrite", (store, existing) => {
        if (existing !== undefined) {
          if (sealed(existing).requestKey !== requestKey)
            throw new IntentStorageError();
          store.delete(actorId);
        }
      });
    } catch {
      throw new IntentStorageError();
    }
  },
};
