/** Opt-in synthetic browser harness. Never imported by the application. */
import { createRoot, type Root } from "react-dom/client";
import { LeaseEnforcementManagement } from "../LeaseEnforcementManagement";
import { createEnforcementClient } from "../leaseEnforcementClient";
import { createFinancialTransport } from "../financialClient";
import {
  createFinancialRecovery,
  decodeFinancialIntent,
} from "../financialRecovery";
import { sealedIntentStore, INTENT_DATABASE } from "../sealedIntentStore";
import { financialObject, type FinancialObject } from "../financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "../financialJson";
import {
  ENFORCEMENT_CAPABILITIES,
  type EnforcementRead,
} from "../leaseEnforcementContract";
import type { EnforcementServices } from "../leaseEnforcementUi";
import {
  ids,
  readData,
  additionalRentSource,
  warningRecord,
  eventRecord,
  caseRecord,
} from "./leaseEnforcementFixtures";
import "../styles.css";

function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
function syntheticOnly() {
  check(
    location.hostname === "127.0.0.1" && location.port === "5204",
    "Owned synthetic origin required",
  );
}
function harness(allow: string[] = [...ENFORCEMENT_CAPABILITIES]) {
  const originals = new Map<
    string,
    { body: string; envelope: FinancialObject }
  >();
  const state = {
    allow,
    voided: false,
    caseExists: false,
    hasSecondSource: false,
    loseNext: false,
    deny: false,
    rejectValidation: false,
    validationRejections: 0,
    block: null as null | { phase: "post" | "reads"; promise: Promise<void> },
    warnings: [] as FinancialObject[],
    events: [] as FinancialObject[],
  };
  const calls: {
    url: string;
    method: string;
    body: string | null;
    key: string | null;
    property: string | null;
    actor: string | null;
    signal: AbortSignal | null | undefined;
  }[] = [];
  const fetcher: typeof fetch = async (supplied, init) => {
    if (typeof supplied !== "string") throw new Error("Finite route required");
    const url = new URL(supplied, "https://synthetic.invalid"),
      headers = new Headers(init?.headers),
      key = headers.get("Idempotency-Key"),
      requestId = headers.get("X-Request-ID"),
      prop = headers.get("X-Financial-Property-ID"),
      actor = headers.get("X-Billing-Actor-ID"),
      method = init?.method ?? "",
      body = typeof init?.body === "string" ? init.body : null;
    calls.push({
      url: supplied,
      method,
      body,
      key,
      property: prop,
      actor,
      signal: init?.signal,
    });
    if (state.block?.phase === (method === "POST" ? "post" : "reads"))
      await state.block.promise;
    const respond = (envelope: FinancialObject, status = 200) =>
      new Response(stringifyFinancialJson(envelope), {
        status,
        headers: {
          "Content-Type": "application/json",
          "X-Request-ID": requestId ?? "",
        },
      });
    if (method === "POST") {
      if (state.rejectValidation) {
        state.validationRejections++;
        return respond(
          {
            error: { code: "VALIDATION_ERROR" },
            meta: { request_id: requestId },
          },
          422,
        );
      }
      if (state.deny)
        return respond(
          { error: { code: "FORBIDDEN" }, meta: { request_id: requestId } },
          403,
        );
      if (!key || !body || !prop || actor !== ids.actor)
        throw new Error("Missing command scope");
      const previous = originals.get(key);
      if (previous && previous.body !== body)
        return respond(
          {
            error: { code: "IDEMPOTENCY_KEY_REUSED" },
            meta: { request_id: requestId, property_id: prop },
          },
          409,
        );
      if (previous) return respond(previous.envelope, 201);
      const command = financialObject(parseFinancialJson(body));
      let data: FinancialObject;
      if (url.pathname.endsWith("/violation-warnings")) {
        data = warningRecord(command);
        state.warnings.push(data);
      } else if (url.pathname.endsWith("/rent-nonpayment-cases")) {
        state.caseExists = true;
        data = caseRecord();
      } else {
        data = eventRecord(command, true, state.voided);
        state.events.push(eventRecord(command, false, state.voided));
      }
      const envelope = {
        data,
        meta: { request_id: requestId, property_id: prop },
      };
      originals.set(key, { body, envelope });
      if (state.loseNext) {
        state.loseNext = false;
        throw new Error("Synthetic lost response");
      }
      return respond(envelope, 201);
    }
    let input: EnforcementRead;
    const limit = Number(url.searchParams.get("limit") ?? 50),
      offset = Number(url.searchParams.get("offset") ?? 0);
    if (url.pathname.endsWith("/lease-enforcement-workspaces"))
      input = { kind: "workspaces", limit };
    else if (url.pathname.endsWith("/lease-enforcement-leases"))
      input = {
        kind: "leases",
        purpose:
          url.searchParams.get("purpose") === "WARNINGS"
            ? "WARNINGS"
            : "NONPAYMENT",
        limit,
      };
    else if (url.pathname.endsWith("/rent-nonpayment-alerts"))
      input = { kind: "alerts", limit };
    else if (url.pathname.endsWith("/violation-warning-context"))
      input = { kind: "warningContext", leaseId: ids.lease };
    else if (url.pathname.endsWith("/violation-warnings"))
      input = { kind: "warnings", leaseId: ids.lease, limit, offset };
    else if (url.pathname.endsWith("/rent-nonpayment-sources"))
      input = { kind: "sources", leaseId: ids.lease, limit };
    else if (url.pathname.endsWith("/rent-nonpayment-action-cases"))
      input = { kind: "actionCases", leaseId: ids.lease, limit };
    else if (url.pathname.endsWith("/rent-nonpayment-cases"))
      input = { kind: "cases", leaseId: ids.lease, limit, offset };
    else if (url.pathname.endsWith("/events"))
      input = { kind: "events", caseId: ids.case, limit, offset };
    else if (url.pathname.endsWith("/action-context"))
      input = { kind: "eventContext", caseId: ids.case };
    else if (url.pathname.endsWith(ids.case))
      input = { kind: "case", caseId: ids.case };
    else throw new Error(`Unexpected synthetic read ${supplied}`);
    const data = readData(input, state.voided, state.allow);
    if (input.kind === "warnings") {
      data.items = state.warnings.slice(offset, offset + limit);
      data.total = state.warnings.length;
    }
    if (input.kind === "events") {
      data.items = state.events.slice(offset, offset + limit);
      data.total = state.events.length;
    }
    if (input.kind === "warningContext")
      data.suggested_sequence = state.warnings.length + 1;
    if (input.kind === "sources" && state.caseExists)
      data.items = state.hasSecondSource ? [additionalRentSource()] : [];
    if (
      (input.kind === "cases" || input.kind === "actionCases") &&
      !state.caseExists
    ) {
      data.items = [];
      if (input.kind === "cases") data.total = 0;
    }
    if (
      input.kind === "workspaces" &&
      (state.allow.length === 0 || actor !== ids.actor)
    )
      data.items = [];
    return respond({
      data,
      meta: {
        request_id: requestId,
        ...(input.kind === "workspaces"
          ? { actor_id: actor }
          : { property_id: prop }),
      },
    });
  };
  const services: EnforcementServices = {
    reads: createEnforcementClient(fetcher),
    recovery: createFinancialRecovery(
      sealedIntentStore,
      createFinancialTransport(fetcher, () => "synthetic-csrf"),
      () => "synthetic-csrf",
    ),
  };
  return { state, calls, originals, services };
}

type BrowserHarness = ReturnType<typeof harness>;
interface ServerSnapshot {
  allow: string[];
  voided: boolean;
  caseExists: boolean;
  hasSecondSource: boolean;
  loseNext: boolean;
  deny: boolean;
  rejectValidation: boolean;
  validationRejections: number;
  warnings: FinancialObject[];
  events: FinancialObject[];
  originals: [string, { body: string; envelope: FinancialObject }][];
}
let root: Root | null = null,
  host: HTMLDivElement | null = null;
let current: BrowserHarness | null = null;
function active() {
  check(current, "Start synthetic browser harness first");
  return current;
}
export function stopEnforcementBrowser() {
  root?.unmount();
  root = null;
  host?.remove();
  host = null;
}
export function startEnforcementBrowser(
  scenario = "warning",
  snapshot?: ServerSnapshot,
) {
  syntheticOnly();
  stopEnforcementBrowser();
  const allow =
    scenario === "drafts"
      ? ["rent_nonpayment.case_manage", "rent_nonpayment.event_post"]
      : scenario === "warning"
        ? ["leases.warn"]
        : scenario === "history"
          ? ["leases.read"]
          : scenario === "followup"
            ? ["rent_nonpayment.event_post"]
            : ["rent_nonpayment.read", "rent_nonpayment.case_manage"];
  current = harness(snapshot?.allow ?? allow);
  if (snapshot) {
    const { originals, ...state } = snapshot;
    Object.assign(current.state, state);
    for (const [key, value] of originals) current.originals.set(key, value);
  } else if (scenario === "drafts") {
    current.state.caseExists = true;
    current.state.rejectValidation = true;
    current.state.hasSecondSource = true;
  } else if (scenario === "lost-open") current.state.loseNext = true;
  else if (scenario === "followup") {
    current.state.voided = true;
    current.state.caseExists = true;
  } else if (scenario === "history") current.state.warnings = [warningRecord()];
  host = document.createElement("div");
  host.id = "synthetic-enforcement-browser";
  document.body.replaceChildren(host);
  root = createRoot(host);
  root.render(
    <LeaseEnforcementManagement
      actorId={ids.actor}
      services={current.services}
    />,
  );
  return {
    actor: ids.actor,
    property: ids.property,
    lease: ids.lease,
    rent: ids.rent,
    case: ids.case,
    scenario,
  };
}
export function captureEnforcementBrowserServer(): ServerSnapshot {
  const h = active();
  return {
    allow: [...h.state.allow],
    voided: h.state.voided,
    caseExists: h.state.caseExists,
    hasSecondSource: h.state.hasSecondSource,
    loseNext: h.state.loseNext,
    deny: h.state.deny,
    rejectValidation: h.state.rejectValidation,
    validationRejections: h.state.validationRejections,
    warnings: h.state.warnings,
    events: h.state.events,
    originals: [...h.originals],
  };
}
export function allowEnforcementBrowserCommands() {
  syntheticOnly();
  active().state.rejectValidation = false;
}
export function voidEnforcementBrowserSource() {
  active().state.voided = true;
}
export function changeEnforcementBrowserActor() {
  root?.render(
    <LeaseEnforcementManagement
      actorId={ids.other}
      services={active().services}
    />,
  );
}
export async function enforcementBrowserEvidence() {
  const h = active(),
    record = await sealedIntentStore.read(ids.actor);
  return {
    calls: h.calls.map(({ signal, ...call }) => ({
      ...call,
      aborted: signal?.aborted ?? false,
    })),
    originals: h.originals.size,
    validationRejections: h.state.validationRejections,
    warnings: h.state.warnings.length,
    events: h.state.events.length,
    pending: record ? decodeFinancialIntent(record, ids.actor) : null,
    localKeys: Object.keys(localStorage),
    sessionKeys: Object.keys(sessionStorage),
    search: location.search,
    hash: location.hash,
  };
}
export async function verifyEnforcementBrowserWorkflow(testId: string) {
  syntheticOnly();
  const h = active(),
    e = await enforcementBrowserEvidence(),
    posts = e.calls.filter((c) => c.method === "POST");
  check(
    e.localKeys.length === 0 &&
      e.sessionKeys.length === 0 &&
      !e.search &&
      !e.hash,
    "No plaintext browser web-storage or URL evidence",
  );
  const passed: string[] = [];
  if (testId === "TEST-FE-615") {
    check(
      h.state.warnings.length === 1 &&
        !h.state.caseExists &&
        posts.length === 1 &&
        !e.pending,
      "One confirmed warning only",
    );
    check(
      !e.calls.some(
        (c) => c.method === "GET" && c.url.includes("/violation-warnings"),
      ),
      "Warning-only staff must not fetch history",
    );
    check(
      document
        .querySelector('[aria-label="Original confirmed enforcement action"]')
        ?.textContent.includes("Original confirmed action"),
      "Visible confirmed warning evidence",
    );
    passed.push("TEST-FE-615");
  } else if (testId === "TEST-FE-616") {
    check(
      h.state.voided &&
        h.state.caseExists &&
        h.originals.size === 1 &&
        posts.length === 1 &&
        !e.pending,
      "One replay on restored synthetic server; one original case",
    );
    const original = document.querySelector(
        '[aria-label="Original recorded assessment"]',
      ),
      fresh = document.querySelector(
        '[aria-label="Current case after confirmation"]',
      );
    check(
      original?.textContent.includes("USD 800.00") &&
        fresh?.textContent.includes("USD 0.00") &&
        fresh.textContent.includes("VOID"),
      "Original amount remains distinct from current VOID zero after real reload",
    );
    const entry = [...h.originals.entries()][0];
    check(
      entry && posts[0]?.key === entry[0] && posts[0].body === entry[1].body,
      "Replay exact key and bytes",
    );
    passed.push("TEST-FE-616");
  } else if (testId === "TEST-FE-617") {
    check(
      h.state.events.length === 1 &&
        h.state.events[0]?.event_kind === "AUTHORIZED_FOLLOW_UP" &&
        h.state.events[0].remaining_rent_usd_cents === 0 &&
        posts.length === 1 &&
        !e.pending,
      "Explicit follow-up at zero only",
    );
    check(
      !e.calls.some(
        (c) =>
          c.method === "GET" &&
          (c.url.includes("/events") ||
            c.url.endsWith(ids.case) ||
            c.url.includes("/rent-nonpayment-alerts")),
      ),
      "Event-only staff do not fetch history or alerts",
    );
    check(
      !posts[0]?.body?.includes("remaining_rent") &&
        !posts[0]?.body?.includes("event_date"),
      "No client-supplied financial assessment",
    );
    passed.push("TEST-FE-617");
  } else if (testId === "TEST-FE-619") {
    check(
      !posts.length &&
        document.body.textContent.includes("Synthetic quiet-hours violation"),
      "Read-only warning evidence",
    );
    check(
      !document.querySelector('form[aria-label="Record Lease warning"]'),
      "Read-only staff cannot record warnings",
    );
    check(
      document.documentElement.scrollWidth <= window.innerWidth,
      "Narrow viewport has no horizontal overflow",
    );
    passed.push("TEST-FE-619");
  } else if (testId === "TEST-FE-628") {
    check(
      h.state.validationRejections === 1 &&
        h.state.events.length === 1 &&
        posts.length === 2 &&
        !e.pending &&
        h.originals.size === 1,
      "One rejected attempt and one explicitly confirmed event, no pending action",
    );
    check(
      posts[0]?.body === posts[1]?.body && posts[0]?.key !== posts[1]?.key,
      "Definitive rejection retires only the unrecorded request; preserved input requires a fresh confirmation",
    );
    const value = (label: string) =>
      Array.from(
        document.querySelectorAll<
          HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
        >("input,textarea,select"),
      ).find((field) =>
        Array.from(field.labels ?? []).some(
          (item) => item.textContent === label,
        ),
      )?.value;
    check(
      value("Reason for opening case") ===
        "Unrelated synthetic opening draft" &&
        value("Reason for nonpayment event") === "" &&
        value("Rent case available for an event") === ids.case,
      "Only recorded event input clears; unrelated opening draft and selected case survive",
    );
    check(
      document.documentElement.scrollWidth <= window.innerWidth,
      "Draft workflow fits narrow viewport",
    );
    passed.push("TEST-FE-628");
  } else throw new Error("Unknown executable browser scenario");
  check(
    passed.length === 1 && passed[0] === testId,
    "Only a verified browser scenario is registered",
  );
  return {
    testId,
    status: "PASS",
    posts: posts.length,
    originals: h.originals.size,
    pending: !!e.pending,
  };
}
// TEST-FE-618 exercises the real IndexedDB encrypted record and Web Locks boundary.
export async function runEnforcementBrowserPendingIsolationCheck() {
  syntheticOnly();
  const h = active(),
    record = await sealedIntentStore.read(ids.actor);
  check(record, "Pending original required");
  const pending = decodeFinancialIntent(record, ids.actor);
  check(pending, "Valid pending enforcement command required");
  const before = h.calls.length;
  const held = await new Promise<boolean>((resolve, reject) => {
    void navigator.locks.request(
      `property-rental.financial-attempt:${ids.actor}`,
      async () => {
        try {
          const result = await h.services.recovery.replay(
            {
              actorId: ids.actor,
              propertyId: ids.property,
              signal: new AbortController().signal,
            },
            pending.key,
          );
          resolve(result.kind === "blocked");
        } catch (error) {
          reject(
            error instanceof Error
              ? error
              : new Error("Synthetic browser check failed"),
          );
        }
      },
    );
  });
  check(
    held && h.calls.length === before,
    "Held browser lock blocks a concurrent original replay before transport",
  );
  check(
    (
      await h.services.recovery.load({
        actorId: ids.other,
        propertyId: ids.property,
        signal: new AbortController().signal,
      })
    ).kind === "ready",
    "Actor boundary hides another actor original",
  );
  check(
    (
      await h.services.recovery.load({
        actorId: ids.actor,
        propertyId: ids.other,
        signal: new AbortController().signal,
      })
    ).kind === "other-property",
    "Property boundary preserves original identity",
  );
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const r = indexedDB.open(INTENT_DATABASE, 1);
    r.onsuccess = () => {
      resolve(r.result);
    };
    r.onerror = () => {
      reject(new Error("Synthetic storage inspection failed"));
    };
  });
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("pending", "readonly"),
        request = tx.objectStore("pending").get(ids.actor);
      request.onsuccess = () => {
        try {
          const raw = request.result as {
            key: CryptoKey;
            iv: Uint8Array;
            ciphertext: ArrayBuffer;
            requestKey: string;
          };
          check(
            raw.key instanceof CryptoKey &&
              !raw.key.extractable &&
              raw.ciphertext instanceof ArrayBuffer &&
              raw.iv instanceof Uint8Array,
            "Pending record uses non-extractable key and ciphertext",
          );
          check(
            Object.keys(raw).sort().join(",") ===
              "ciphertext,iv,key,requestKey" && raw.requestKey === pending.key,
            "No plaintext intent fields in IndexedDB",
          );
        } catch (error) {
          reject(
            error instanceof Error
              ? error
              : new Error("Synthetic browser check failed"),
          );
        }
      };
      tx.oncomplete = () => {
        resolve();
      };
      tx.onabort = tx.onerror = () => {
        reject(new Error("Synthetic read-only storage inspection failed"));
      };
    });
  } finally {
    db.close();
  }
  const passed: string[] = [];
  passed.push("TEST-FE-618");
  return {
    testId: passed[0],
    status: "PASS",
    realIndexedDB: true,
    nonExtractableKey: true,
    realWebLock: true,
    actorAndPropertyIsolation: true,
  };
}
