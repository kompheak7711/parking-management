// Real IndexedDB/WebCrypto and same-origin tab checks with newly generated synthetic actors.
import { billingJournal } from "../invoiceClient";
import { INTENT_DATABASE, sealedIntentStore } from "../sealedIntentStore";
import { createFinancialRecovery } from "../financialRecovery";
import {
  FinancialClientError,
  type FinancialTransport,
} from "../financialClient";
import { validateFinancialReply } from "../financialResponse";
import { ids, command, fixture } from "./financialFixtures";
function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
function current(actorId: string = crypto.randomUUID()) {
  return {
    actorId,
    propertyId: ids.property,
    signal: new AbortController().signal,
  };
}
function sent(counter: { sends: number }): number {
  return counter.sends;
}
function unavailable(counter: { sends: number }): FinancialTransport {
  return {
    send: () => {
      counter.sends += 1;
      return Promise.reject(new FinancialClientError("UNAVAILABLE", true));
    },
  };
}
function successful(counter: { sends: number }): FinancialTransport {
  return {
    send: (scope, request) => {
      counter.sends += 1;
      return Promise.resolve(
        validateFinancialReply(
          fixture(request.operation),
          request,
          scope.propertyId,
          ids.key,
        ),
      );
    },
  };
}
async function encryptedRecord(
  actor: string,
): Promise<Record<string, unknown>> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open(INTENT_DATABASE, 1);
    open.onsuccess = () => {
      resolve(open.result);
    };
    open.onerror = () => {
      reject(new Error("Synthetic store unavailable"));
    };
  });
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction("pending", "readonly"),
        get = tx.objectStore("pending").get(actor);
      tx.oncomplete = () => {
        resolve(get.result as Record<string, unknown>);
      };
      tx.onerror = () => {
        reject(new Error("Synthetic read failed"));
      };
    });
  } finally {
    db.close();
  }
}
export async function runFinancialCommandBrowserChecks(): Promise<string[]> {
  const passed: string[] = [],
    scope = current(),
    count = { sends: 0 },
    recovery = createFinancialRecovery(
      sealedIntentStore,
      unavailable(count),
      () => "synthetic-csrf",
    );
  const result = await recovery.submit(scope, command(6));
  check(result.kind === "pending", "Unknown outcome retained");
  const raw = await encryptedRecord(scope.actorId);
  check(
    Object.keys(raw).sort().join() === "ciphertext,iv,key,requestKey",
    "Shared four-field ciphertext layout",
  );
  check(
    raw.key instanceof CryptoKey &&
      !raw.key.extractable &&
      raw.key.algorithm.name === "AES-GCM",
    "Nonextractable encryption key",
  );
  check(
    raw.ciphertext instanceof ArrayBuffer &&
      raw.iv instanceof Uint8Array &&
      raw.iv.byteLength === 12,
    "Encrypted original intent",
  );
  check(
    (await recovery.load(scope)).kind === "pending" && sent(count) === 1,
    "Load never transmits",
  );
  check(
    (await recovery.submit(scope, command(0))).kind === "blocked" &&
      sent(count) === 1,
    "Pending blocks another command",
  );
  const replay = createFinancialRecovery(
    sealedIntentStore,
    successful(count),
    () => "synthetic-csrf",
  );
  check(
    (await replay.replay(scope, result.command.key)).kind === "success",
    "Explicit exact-key replay",
  );
  check(
    (await sealedIntentStore.read(scope.actorId)) === null,
    "Validated success retires original",
  );
  passed.push("TEST-FE-314");

  const legacyScope = current(),
    legacyKey = crypto.randomUUID();
  await sealedIntentStore.begin(legacyScope.actorId, {
    requestKey: legacyKey,
    plaintext: JSON.stringify({
      key: legacyKey,
      command: {
        action: "issue",
        propertyId: ids.property,
        id: ids.invoice,
        version: 1,
      },
    }),
  });
  const before = await sealedIntentStore.read(legacyScope.actorId),
    sends = count.sends;
  check(
    (await billingJournal.load(legacyScope.actorId))?.key === legacyKey,
    "Legacy adapter reads its own original record",
  );
  check(
    (await recovery.load(legacyScope)).kind === "foreign",
    "Financial adapter recognizes foreign ownership",
  );
  check(
    (await recovery.submit(legacyScope, command(0))).kind === "blocked" &&
      sent(count) === sends,
    "Financial command cannot bypass legacy reservation",
  );
  check(
    JSON.stringify(await sealedIntentStore.read(legacyScope.actorId)) ===
      JSON.stringify(before),
    "Legacy bytes retained",
  );
  await sealedIntentStore.clear(legacyScope.actorId, legacyKey); // Only this newly created synthetic record.
  passed.push("TEST-FE-315");

  const corruptScope = current(),
    corruptKey = crypto.randomUUID();
  await sealedIntentStore.begin(corruptScope.actorId, {
    requestKey: corruptKey,
    plaintext: '{"namespace":"property-rental.financial-command","version":99}',
  });
  const corrupt = await sealedIntentStore.read(corruptScope.actorId);
  check(
    (await recovery.load(corruptScope)).kind === "unavailable",
    "Corrupt financial envelope fails closed",
  );
  check(
    (await recovery.submit(corruptScope, command(0))).kind === "blocked" &&
      sent(count) === sends,
    "Corrupt envelope cannot dispatch",
  );
  check(
    JSON.stringify(await sealedIntentStore.read(corruptScope.actorId)) ===
      JSON.stringify(corrupt),
    "Corrupt evidence retained",
  );
  await sealedIntentStore.clear(corruptScope.actorId, corruptKey);
  passed.push("TEST-FE-316");
  return passed;
}
export async function prepareCommandReload(): Promise<{
  actor: string;
  key: string;
  wireBody: string;
}> {
  const scope = current(),
    count = { sends: 0 };
  const result = await createFinancialRecovery(
    sealedIntentStore,
    unavailable(count),
    () => "synthetic-csrf",
  ).submit(scope, command(6));
  check(
    result.kind === "pending" && sent(count) === 1,
    "Prepare interrupted synthetic command",
  );
  return {
    actor: scope.actorId,
    key: result.command.key,
    wireBody: result.command.wireBody,
  };
}
export async function verifyCommandReload(
  actor: string,
  key: string,
  wireBody: string,
): Promise<string> {
  const count = { sends: 0 },
    scope = current(actor),
    recovery = createFinancialRecovery(
      sealedIntentStore,
      successful(count),
      () => "synthetic-csrf",
    );
  const loaded = await recovery.load(scope);
  check(
    loaded.kind === "pending" &&
      loaded.command.key === key &&
      loaded.command.wireBody === wireBody &&
      sent(count) === 0,
    "Reload preserves original without replay",
  );
  check(
    (await recovery.replay(scope, key)).kind === "success",
    "Explicit replay after reload",
  );
  check(
    (await sealedIntentStore.read(actor)) === null,
    "Reload replay retires original",
  );
  return "TEST-FE-317";
}
export async function raceFinancialCommand(
  actor: string,
): Promise<{ kind: string; key: string | null; sends: number }> {
  const count = { sends: 0 };
  const result = await createFinancialRecovery(
    sealedIntentStore,
    unavailable(count),
    () => "synthetic-csrf",
  ).submit(current(actor), command(6));
  return {
    kind: result.kind,
    key: result.kind === "pending" ? result.command.key : null,
    sends: count.sends,
  };
}
export async function verifyCommandRace(
  actor: string,
  winner: string,
): Promise<string> {
  const count = { sends: 0 },
    scope = current(actor),
    recovery = createFinancialRecovery(
      sealedIntentStore,
      successful(count),
      () => "synthetic-csrf",
    );
  const loaded = await recovery.load(scope);
  check(
    loaded.kind === "pending" && loaded.command.key === winner,
    "Exact winning tab persisted",
  );
  check(
    (await recovery.replay(scope, crypto.randomUUID())).kind === "blocked" &&
      sent(count) === 0,
    "Stale tab cannot substitute request key",
  );
  let denied = false;
  try {
    await sealedIntentStore.clear(actor, crypto.randomUUID());
  } catch {
    denied = true;
  }
  check(
    denied && (await sealedIntentStore.read(actor))?.requestKey === winner,
    "Stale clearance cannot remove winner",
  );
  check(
    (await recovery.replay(scope, winner)).kind === "success",
    "Winning command can explicitly recover",
  );
  return "TEST-FE-318";
}
