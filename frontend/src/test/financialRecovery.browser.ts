// Synthetic real-browser checks, run through the documented Playwright harness.
import { billingJournal } from "../invoiceClient";
import { parseFinancialJson, stringifyFinancialJson } from "../financialJson";
import {
  INTENT_DATABASE,
  MAX_SEALED_INTENT_BYTES,
  sealedIntentStore,
} from "../sealedIntentStore";

function check(value: unknown, label: string): asserts value {
  if (!value) throw new Error(label);
}
async function rejected(
  operation: () => Promise<unknown>,
  label: string,
): Promise<void> {
  let failed = false;
  try {
    await operation();
  } catch {
    failed = true;
  }
  check(failed, label);
}
function actor(): string {
  return "synthetic-financial-wire-" + crypto.randomUUID();
}
interface TestSealed {
  key: CryptoKey;
  iv: Uint8Array<ArrayBuffer>;
  ciphertext: ArrayBuffer;
  requestKey: string;
}
async function rawRecord(
  id: string,
  replacement?: TestSealed,
): Promise<TestSealed | undefined> {
  check(id.startsWith("synthetic-financial-wire-"), "Synthetic actor required");
  await sealedIntentStore.read(actor()); // Create only the normal version1 store if absent.
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(INTENT_DATABASE, 1);
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(new Error("Test database unavailable"));
    };
  });
  try {
    return await new Promise<TestSealed | undefined>((resolve, reject) => {
      const tx = db.transaction(
        "pending",
        replacement ? "readwrite" : "readonly",
      );
      const store = tx.objectStore("pending");
      const request = store.get(id);
      let result: TestSealed | undefined;
      request.onsuccess = () => {
        result = request.result as TestSealed | undefined;
        if (replacement) store.put(replacement, id);
      };
      tx.oncomplete = () => {
        resolve(result);
      };
      tx.onerror = tx.onabort = () => {
        reject(new Error("Synthetic transaction failed"));
      };
    });
  } finally {
    db.close();
  }
}
async function legacyRecord(
  id: string,
  requestKey: string,
): Promise<TestSealed> {
  const key = await crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const plaintext = JSON.stringify({
    key: requestKey,
    command: {
      action: "issue",
      propertyId: "synthetic-property",
      id: "synthetic-invoice",
      version: 3,
    },
  });
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv, additionalData: new TextEncoder().encode(id) },
    key,
    new TextEncoder().encode(plaintext),
  );
  return { key, iv, ciphertext, requestKey };
}

export async function runFinancialRecoveryBrowserChecks(): Promise<string[]> {
  const passed: string[] = [];
  {
    const id = actor(),
      key = crypto.randomUUID();
    check(
      (await rawRecord(id)) === undefined,
      "TEST-FE-277 fresh synthetic actor",
    );
    await rawRecord(id, await legacyRecord(id, key));
    const loaded = await billingJournal.load(id);
    check(
      loaded?.key === key &&
        loaded.command.action === "issue" &&
        loaded.command.propertyId === "synthetic-property",
      "TEST-FE-277 legacy read compatibility",
    );
    await billingJournal.clear(id, key);
    const body =
      '{"outstanding_usd_cents":9223372036854775807,"rate":4100.12345678901234567890}';
    const plaintext = stringifyFinancialJson({
      key,
      wireBody: stringifyFinancialJson(parseFinancialJson(body)),
    });
    await sealedIntentStore.begin(id, { requestKey: key, plaintext });
    check(
      (await sealedIntentStore.read(id))?.plaintext === plaintext,
      "TEST-FE-277 exact sealed round trip",
    );
    const raw = await rawRecord(id);
    check(
      raw &&
        Object.keys(raw).sort().join(",") === "ciphertext,iv,key,requestKey",
      "TEST-FE-277 physical record layout",
    );
    check(
      !raw.key.extractable && raw.iv.byteLength === 12,
      "TEST-FE-277 nonextractable key",
    );
    await rejected(
      () => crypto.subtle.exportKey("raw", raw.key),
      "TEST-FE-277 key export refused",
    );
    check(
      !new TextDecoder()
        .decode(raw.ciphertext)
        .includes("outstanding_usd_cents"),
      "TEST-FE-277 no plaintext financial body",
    );
    await rejected(
      () => billingJournal.load(id),
      "TEST-FE-277 foreign command cannot become billing",
    );
    check(
      (await sealedIntentStore.read(id))?.requestKey === key,
      "TEST-FE-277 foreign record retained",
    );
    await sealedIntentStore.clear(id, key);
    passed.push("TEST-FE-277");
  }
  {
    const a = actor(),
      b = actor(),
      key = crypto.randomUUID();
    await rawRecord(a, await legacyRecord(a, key));
    const raw = await rawRecord(a);
    check(raw, "TEST-FE-278 source");
    await rawRecord(b, raw);
    await rejected(
      () => sealedIntentStore.read(b),
      "TEST-FE-278 actor authentication",
    );
    check(
      (await billingJournal.load(a))?.key === key,
      "TEST-FE-278 original actor retained",
    );
    await rejected(
      () => sealedIntentStore.clear(a, crypto.randomUUID()),
      "TEST-FE-278 wrong key refusal",
    );
    check(
      (await sealedIntentStore.read(a))?.requestKey === key,
      "TEST-FE-278 wrong clear retained",
    );
    await sealedIntentStore.clear(a, key);
    await sealedIntentStore.clear(b, key);
    passed.push("TEST-FE-278");
  }
  {
    const id = actor(),
      key = crypto.randomUUID();
    const original = await legacyRecord(id, key);
    const broken = original.ciphertext.slice(0);
    const altered = new Uint8Array(broken);
    altered[0] = (altered[0] ?? 0) ^ 1;
    for (const record of [
      { ...original, ciphertext: broken },
      { ...original, iv: crypto.getRandomValues(new Uint8Array(12)) },
      { ...original, requestKey: crypto.randomUUID() },
    ]) {
      await rawRecord(id, record);
      await rejected(
        () => billingJournal.load(id),
        "TEST-FE-279 tampering rejected",
      );
      check(
        (await rawRecord(id))?.requestKey === record.requestKey,
        "TEST-FE-279 failed load never deletes",
      );
    }
    await rawRecord(id, original);
    await billingJournal.clear(id, key);
    passed.push("TEST-FE-279");
  }
  {
    const id = actor(),
      key = crypto.randomUUID();
    const intent: { requestKey: string; plaintext: string } = {
      requestKey: key,
      plaintext: "original reviewed request",
    };
    const saving = sealedIntentStore.begin(id, intent);
    intent.requestKey = "changed";
    intent.plaintext = "changed";
    await saving;
    check(
      (await sealedIntentStore.read(id))?.plaintext ===
        "original reviewed request",
      "TEST-FE-280 captured plaintext",
    );
    check(
      (await sealedIntentStore.read(id))?.requestKey === key,
      "TEST-FE-280 captured key",
    );
    await sealedIntentStore.clear(id, key);
    passed.push("TEST-FE-280");
  }
  {
    const id = actor(),
      key = crypto.randomUUID();
    const plaintext = "ខ".repeat(Math.floor(MAX_SEALED_INTENT_BYTES / 3)) + "x";
    check(
      new TextEncoder().encode(plaintext).byteLength ===
        MAX_SEALED_INTENT_BYTES,
      "TEST-FE-281 byte fixture",
    );
    await sealedIntentStore.begin(id, { requestKey: key, plaintext });
    check(
      (await sealedIntentStore.read(id))?.plaintext === plaintext,
      "TEST-FE-281 exact bound accepted",
    );
    await sealedIntentStore.clear(id, key);
    for (const invalid of [plaintext + "x", "\ud800"])
      await rejected(
        () =>
          sealedIntentStore.begin(id, { requestKey: key, plaintext: invalid }),
        "TEST-FE-281 invalid bytes rejected",
      );
    await rejected(
      () => sealedIntentStore.begin("", { requestKey: key, plaintext: "x" }),
      "TEST-FE-281 empty actor rejected",
    );
    await rejected(
      () => sealedIntentStore.begin(id, { requestKey: "", plaintext: "x" }),
      "TEST-FE-281 empty key rejected",
    );
    check(
      (await sealedIntentStore.read(id)) === null,
      "TEST-FE-281 invalid begin never writes",
    );
    for (const invalid of ["\ud800", "\udfff"]) {
      await rejected(
        () =>
          sealedIntentStore.begin(id + invalid, {
            requestKey: key,
            plaintext: "x",
          }),
        "TEST-FE-281 malformed actor before binding",
      );
      await rejected(
        () =>
          sealedIntentStore.begin(id, { requestKey: invalid, plaintext: "x" }),
        "TEST-FE-281 malformed request key",
      );
    }
    passed.push("TEST-FE-281");
  }
  {
    const id = actor(),
      key = crypto.randomUUID();
    const originalPut = Object.getOwnPropertyDescriptor(
      IDBObjectStore.prototype,
      "put",
    );
    check(originalPut, "TEST-FE-282 put descriptor");
    try {
      Object.defineProperty(IDBObjectStore.prototype, "put", {
        configurable: true,
        value() {
          throw new DOMException(
            "Synthetic quota failure",
            "QuotaExceededError",
          );
        },
      });
      await rejected(
        () =>
          sealedIntentStore.begin(id, {
            requestKey: key,
            plaintext: "synthetic",
          }),
        "TEST-FE-282 write abort",
      );
    } finally {
      Object.defineProperty(IDBObjectStore.prototype, "put", originalPut);
    }
    check(
      (await sealedIntentStore.read(id)) === null,
      "TEST-FE-282 aborted write absent",
    );
    await sealedIntentStore.begin(id, {
      requestKey: key,
      plaintext: "synthetic",
    });
    const originalDelete = Object.getOwnPropertyDescriptor(
      IDBObjectStore.prototype,
      "delete",
    );
    check(originalDelete, "TEST-FE-282 delete descriptor");
    try {
      Object.defineProperty(IDBObjectStore.prototype, "delete", {
        configurable: true,
        value() {
          throw new DOMException("Synthetic storage failure", "UnknownError");
        },
      });
      await rejected(
        () => sealedIntentStore.clear(id, key),
        "TEST-FE-282 clearance abort",
      );
    } finally {
      Object.defineProperty(IDBObjectStore.prototype, "delete", originalDelete);
    }
    check(
      (await sealedIntentStore.read(id))?.requestKey === key,
      "TEST-FE-282 aborted clearance retained",
    );
    await sealedIntentStore.clear(id, key);
    passed.push("TEST-FE-282");
  }
  return passed;
}

export async function prepareReloadCheck(): Promise<{
  actor: string;
  key: string;
}> {
  const id = actor(),
    key = crypto.randomUUID();
  await rawRecord(id, await legacyRecord(id, key));
  return { actor: id, key };
}
export async function verifyReloadCheck(
  id: string,
  key: string,
): Promise<string> {
  const previousFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = () => {
    calls += 1;
    return Promise.reject(new Error("No dispatch allowed"));
  };
  try {
    check(
      (await billingJournal.load(id))?.key === key,
      "TEST-FE-283 recovery after reload",
    );
    check(calls === 0, "TEST-FE-283 no automatic replay");
    check(
      (await sealedIntentStore.read(id))?.requestKey === key,
      "TEST-FE-283 loaded command remains pending",
    );
    await billingJournal.clear(id, key);
  } finally {
    globalThis.fetch = previousFetch;
  }
  return "TEST-FE-283";
}
export async function reserveRace(id: string, key: string): Promise<string> {
  check(
    id.startsWith("synthetic-financial-wire-"),
    "Synthetic race actor required",
  );
  try {
    await sealedIntentStore.begin(id, {
      requestKey: key,
      plaintext: "synthetic race",
    });
    return key;
  } catch {
    return "blocked";
  }
}
export async function verifyRace(
  id: string,
  winner: string,
  loser: string,
): Promise<string> {
  check(
    (await sealedIntentStore.read(id))?.requestKey === winner,
    "TEST-FE-284 exactly one tab owns reservation",
  );
  await rejected(
    () => sealedIntentStore.clear(id, loser),
    "TEST-FE-284 stale tab cannot clear winner",
  );
  check(
    (await sealedIntentStore.read(id))?.requestKey === winner,
    "TEST-FE-284 winner retained",
  );
  await sealedIntentStore.clear(id, winner);
  return "TEST-FE-284";
}
