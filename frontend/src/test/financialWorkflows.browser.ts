// Local synthetic verification only; all requests use injected fetch and newly generated actors.
import { createElement, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  FinancialManagement,
  FinancialCurrentAfterConfirmation,
  type ConfirmedFinancialAction,
} from "../FinancialManagement";
import { createFinancialTransport } from "../financialClient";
import {
  createFinancialReferenceClient,
  FINANCIAL_CAPABILITIES,
} from "../financialReferenceClient";
import { createFinancialRecovery } from "../financialRecovery";
import { sealedIntentStore } from "../sealedIntentStore";
import {
  FINANCIAL_OPERATIONS,
  financialObject,
  financialId,
  isFinancialCommand,
  type FinancialObject,
} from "../financialContracts";
import { parseFinancialJson, stringifyFinancialJson } from "../financialJson";
import { TargetEvidence } from "../FinancialEvidence";
import {
  FINANCIAL_COMMAND_CAPABILITIES,
  type FinancialUiServices,
} from "../financialUi";
import { FINANCIAL_ACTION_LABELS } from "../FinancialRecoveryNotice";
import { commands, command, fixture, ids } from "./financialFixtures";
import { actionContextFixtures } from "./financialActionContextFixtures";
import "../styles.css";

function check(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
interface RequestEvidence {
  url: string;
  method: string;
  body: string | null;
  key: string | null;
  actor: string | null;
  property: string | null;
  signal: AbortSignal | null | undefined;
}
interface Scenario {
  actorId: string;
  root: Root;
  host: HTMLElement;
  services: FinancialUiServices;
  calls: RequestEvidence[];
  seed: RequestEvidence | null;
  release: (() => void) | null;
  outcome: "success" | "unknown";
  grant: boolean;
  originalPrint: typeof window.print;
  prints: number;
  historyUnavailable?: boolean;
  savedOutcome?: FinancialObject;
  currentOutcomeRefund?: FinancialObject;
  outcomeReadsUnavailable?: boolean;
  preparation?: { promise: Promise<void>; release: () => void };
}
let scenario: Scenario | null = null;
const ownedActors = new Set<string>();
function current(): Scenario {
  check(scenario, "Synthetic scenario is not mounted");
  return scenario;
}
function grantSet(capability: string, enabled = true) {
  return Object.fromEntries(
    FINANCIAL_CAPABILITIES.map((c) => [c, enabled && c === capability]),
  );
}
function response(
  data: FinancialObject | FinancialObject[],
  init: RequestInit | undefined,
  page?: FinancialObject,
) {
  const headers = new Headers(init?.headers),
    requestId = headers.get("X-Request-ID"),
    property = headers.get("X-Financial-Property-ID");
  return new Response(
    stringifyFinancialJson({
      data,
      ...(page ? { page } : {}),
      meta: {
        request_id: requestId,
        actor_id: headers.get("X-Billing-Actor-ID"),
        ...(property ? { property_id: property } : {}),
      },
    }),
    {
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": requestId ?? "",
      },
    },
  );
}
function callEvidence(
  url: RequestInfo | URL,
  init: RequestInit | undefined,
): RequestEvidence {
  check(typeof url === "string", "Synthetic request must use a finite URL");
  const headers = new Headers(init?.headers);
  return {
    url,
    method: init?.method ?? "",
    body: typeof init?.body === "string" ? init.body : null,
    key: headers.get("Idempotency-Key"),
    actor: headers.get("X-Billing-Actor-ID"),
    property: headers.get("X-Financial-Property-ID"),
    signal: init?.signal,
  };
}
function hostRoot() {
  check(!scenario, "Previous synthetic scenario must be cleaned up");
  const host = document.createElement("div");
  host.id = "synthetic-financial-workflow";
  host.className = "workspace-panel";
  document.body.append(host);
  return { host, root: createRoot(host) };
}
function mountManagement() {
  const s = current();
  s.root.render(
    createElement(
      StrictMode,
      null,
      createElement(FinancialManagement, {
        key: s.actorId,
        actorId: s.actorId,
        services: s.services,
      }),
    ),
  );
}
export async function startFinancialWorkflowBrowserScenario(
  index: number,
  options: {
    seedPending?: boolean;
    outcome?: "success" | "unknown";
    readOnly?: boolean;
    staffReview?: boolean;
    reviewCorrection2?: boolean;
    draftCorrection2?: boolean;
    outcomeCorrection1?: boolean;
  } = {},
) {
  const input = command(index);
  check(isFinancialCommand(input.operation), "Expected synthetic command");
  const operation = input.operation,
    actorId = crypto.randomUUID();
  ownedActors.add(actorId);
  const s: Scenario = {
    actorId,
    ...hostRoot(),
    services: {} as FinancialUiServices,
    calls: [],
    seed: null,
    release: null,
    outcome: "unknown",
    grant: true,
    originalPrint: window.print,
    prints: 0,
  };
  scenario = s;
  const grant = options.readOnly
    ? "payments.read"
    : FINANCIAL_COMMAND_CAPABILITIES[operation];
  if (grant === null)
    throw new Error("Use the separate Lease enforcement browser workflow.");
  const grants = (enabled = true) =>
    options.staffReview
      ? Object.fromEntries(
          FINANCIAL_CAPABILITIES.map((c) => [
            c,
            enabled &&
              [
                "payments.read",
                "payments.record",
                "refunds.create",
                "receipts.read",
                ...(options.draftCorrection2
                  ? ["refunds.corrections.reverse"]
                  : []),
                ...(options.reviewCorrection2
                  ? [
                      "payments.allocate",
                      "credits.recognize",
                      "refunds.correct",
                      "exchange_rates.manage",
                    ]
                  : []),
              ].includes(c),
          ]),
        )
      : {
          ...grantSet(grant, enabled),
          ...(options.outcomeCorrection1 ? { "refunds.read": enabled } : {}),
        };
  const fetcher: typeof fetch = async (url, init) => {
    const call = callEvidence(url, init);
    s.calls.push(call);
    if (call.url.includes("financial-workspaces"))
      return response(
        [
          {
            property_id: ids.property,
            name: "Synthetic River Property",
            timezone: "Asia/Phnom_Penh",
            capabilities: grants(),
          },
          {
            property_id: ids.other,
            name: "Synthetic Garden Property",
            timezone: "Asia/Phnom_Penh",
            capabilities: grants(),
          },
        ],
        init,
        { limit: 100, next_cursor: null },
      );
    if (call.url.includes("financial-capabilities"))
      return response(
        { property_id: call.property, capabilities: grants(s.grant) },
        init,
      );
    if (
      options.reviewCorrection2 &&
      call.url.includes("/payments/khr-preview")
    ) {
      check(
        call.method === "POST" && call.body !== null,
        "Synthetic preview requires its explicit input",
      );
      const amount = financialObject(
        parseFinancialJson(call.body),
      ).usd_amount_cents;
      check(
        typeof amount === "number" || typeof amount === "bigint",
        "Synthetic exact preview amount is required",
      );
      return response(
        {
          property_id: ids.property,
          provisional: true,
          status: "source_unavailable",
          usd_amount_cents: amount,
          manual_fallback_allowed: true,
        },
        init,
      );
    }
    if (
      options.reviewCorrection2 &&
      call.method === "GET" &&
      new URL(call.url, "https://synthetic.invalid").pathname.endsWith(
        `/payments/${ids.payment}/allocations`,
      ) &&
      new URL(call.url, "https://synthetic.invalid").searchParams.get(
        "allocation_id",
      ) === ids.allocation
    ) {
      if (s.historyUnavailable)
        throw new Error("Synthetic history refresh is unavailable");
      return response(recordedAllocationBrowserFixture(actorId), init, {
        limit: 50,
        next_cursor: null,
      });
    }
    if (options.draftCorrection2 && call.method === "GET") {
      const path = new URL(call.url, "https://synthetic.invalid").pathname;
      if (
        path.endsWith(
          `/refunds/${ids.refund}/corrections/${ids.event}/reversal-context`,
        )
      )
        return response(draftReversalBrowserContext(actorId), init, {
          limit: 50,
          next_cursor: null,
        });
      if (path.endsWith(`/refund-sources/PET_DEPOSIT/${ids.payment}`))
        return response(
          {
            source_type: "PET_DEPOSIT",
            source_id: ids.payment,
            property_id: ids.property,
            recipient_customer_id: ids.customer,
            refund_currency: "USD",
            available_usd_cents: 20000,
            eligible: true,
            pet_refund_review_id: ids.event,
            pet_departure_id: ids.other,
            pet_approval_id: ids.application,
            lease_id: ids.invoice,
            qualified_at: "2026-09-01T12:00:00+07:00",
          },
          init,
        );
    }
    if (call.method === "GET") {
      if (options.outcomeCorrection1) {
        if (s.outcomeReadsUnavailable)
          throw new Error(
            "Synthetic current read unavailable after intervening return",
          );
        if (call.url.includes(`/refunds/${ids.refund}`)) {
          check(
            s.currentOutcomeRefund,
            "Synthetic Refund read requires a recorded payout",
          );
          return response(s.currentOutcomeRefund, init);
        }
      }
      if (options.staffReview) {
        const path = new URL(call.url, "https://synthetic.invalid").pathname;
        if (path.endsWith("/payment-methods")) {
          if (s.preparation) await s.preparation.promise;
          return response(
            [
              {
                id: ids.method,
                property_id: ids.property,
                code: "CASH",
                display_name: "Synthetic accepted cash",
              },
            ],
            init,
            { limit: 100, next_cursor: null },
          );
        }
        const payment = {
          id: ids.payment,
          property_id: ids.property,
          payer_customer_id: ids.customer,
          payment_number: "PAY-ORIGINAL-SYNTHETIC",
          payment_method_id: ids.method,
          payment_method_name_snapshot: "Synthetic accepted cash",
          received_currency: "USD",
          received_amount_minor: 200,
          usd_accounting_value_cents: 200,
          payment_date: "2026-09-01",
          status: "RECEIVED",
          confirmed_at: "2026-09-01T12:00:00+07:00",
          confirmed_by: actorId,
        };
        const receipt = {
          id: ids.receipt,
          property_id: ids.property,
          payment_id: ids.payment,
          payer_customer_id: ids.customer,
          receipt_number: "R-ORIGINAL-SYNTHETIC",
          issued_at: "2026-09-01T12:00:00.123456+07:00",
          issued_by: actorId,
          identity_snapshot: { payer_legal_name: "Synthetic original payer" },
        };
        const posted = s.calls.some((c) => c.method === "POST");
        const resource = {
          payment,
          receipt,
          exchange_rate: null,
          confirmation_evidence: {
            received_at: "2026-09-01T11:59:00.123456+07:00",
            evidence_reference: "Synthetic original receipt evidence",
          },
          position: {
            available_usd_cents: posted ? 100 : 200,
            dispositions: {
              allocation_usd_cents: 0,
              deposit_usd_cents: 0,
              credit_usd_cents: 0,
              refund_usd_cents: posted ? 100 : 0,
            },
          },
        };
        if (path.endsWith("/payments"))
          return response(
            [
              resource,
              {
                ...resource,
                payment: {
                  ...payment,
                  id: ids.other,
                  payment_number: "PAY-KHR-SYNTHETIC",
                  received_currency: "KHR",
                  received_amount_minor: 4143,
                  usd_accounting_value_cents: 101,
                },
              },
            ],
            init,
            { limit: 50, next_cursor: null },
          );
        if (path.endsWith(`/payments/${ids.payment}`))
          return response(resource, init);
        if (path.endsWith(`/receipts/${ids.receipt}`))
          return response(
            {
              ...resource,
              financial_position: {
                status: "RECEIVED",
                allocated_usd_cents: 0,
                deposit_directed_usd_cents: 0,
                available_usd_cents: posted ? 100 : 200,
              },
              reprints: { items: [], page: { limit: 50, next_cursor: null } },
            },
            init,
          );
      }

      if (call.url.includes("refund-sources") && operation === "refundCreate")
        return response(
          {
            property_id: ids.property,
            source_type: "PAYMENT",
            source_id: ids.payment,
            recipient_customer_id: ids.customer,
            refund_currency: "USD",
            available_usd_cents: 200,
            eligible: true,
            source_payment: {
              id: ids.payment,
              property_id: ids.property,
              payer_customer_id: ids.customer,
              payment_number: "PAY-SYNTHETIC",
              payment_method_id: ids.method,
              payment_method_name_snapshot: "Synthetic Bank",
              received_currency: "USD",
              received_amount_minor: 200,
              usd_accounting_value_cents: 200,
              payment_date: "2026-09-01",
              status: "RECEIVED",
              confirmed_at: "2026-09-01T12:00:00+07:00",
              confirmed_by: actorId,
            },
            source_exchange_rate: null,
            receipt_evidence: {
              received_at: "2026-09-01T11:59:00+07:00",
              evidence_reference: "Synthetic original receipt",
            },
          },
          init,
        );
      if (options.readOnly && call.url.endsWith("/payments?limit=50"))
        return response([], init, { limit: 50, next_cursor: null });
      throw new Error("Synthetic current source deliberately unavailable");
    }
    if (s.release)
      await new Promise<void>((resolve) => {
        s.release = resolve;
      });
    const result = fixture(operation);
    if (options.outcomeCorrection1) {
      check(
        operation === "refundCreate",
        "Intervening-return fixture is limited to Refund creation",
      );
      s.savedOutcome ??= financialObject(result.data);
      s.currentOutcomeRefund ??= s.savedOutcome;
      result.data = s.savedOutcome;
    }
    if (s.outcome === "unknown") throw new Error("Synthetic lost response");
    result.meta = {
      actor_id: call.actor,
      property_id: call.property,
      request_id: new Headers(init?.headers).get("X-Request-ID"),
    };
    return new Response(stringifyFinancialJson(result), {
      status: FINANCIAL_OPERATIONS[operation][2],
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": new Headers(init?.headers).get("X-Request-ID") ?? "",
      },
    });
  };
  const transport = createFinancialTransport(fetcher, () => "synthetic-csrf"),
    recovery = createFinancialRecovery(
      sealedIntentStore,
      transport,
      () => "synthetic-csrf",
    );
  s.services = {
    transport,
    recovery,
    references: createFinancialReferenceClient(fetcher, () => "synthetic-csrf"),
  };
  if (options.seedPending ?? true) {
    const result = await recovery.submit(
      {
        actorId,
        propertyId: ids.property,
        signal: new AbortController().signal,
      },
      input,
    );
    check(
      result.kind === "pending",
      "Synthetic unknown outcome must create original encrypted intent",
    );
    s.seed = s.calls.find((c) => c.method === "POST") ?? null;
    check(s.seed, "Synthetic original attempt missing");
    s.calls = [];
  }
  s.outcome = options.outcome ?? "success";
  mountManagement();
  return {
    operation,
    label: FINANCIAL_ACTION_LABELS[operation],
    propertyId: ids.property,
    otherPropertyId: ids.other,
    actorId,
  };
}
export async function financialWorkflowBrowserEvidence() {
  const s = current(),
    opened = await sealedIntentStore.read(s.actorId);
  return {
    actorId: s.actorId,
    seed: s.seed ? { ...s.seed, signal: undefined } : null,
    calls: s.calls.map((c) => ({
      ...c,
      signal: undefined,
      aborted: c.signal?.aborted ?? false,
    })),
    savedKey: opened?.requestKey ?? null,
    savedContainsCsrf: opened?.plaintext.includes("synthetic-csrf") ?? false,
    prints: s.prints,
    encryptedStoreAvailable:
      typeof crypto.subtle.encrypt === "function" &&
      typeof indexedDB.open === "function",
  };
}
export function controlFinancialWorkflowBrowserScenario(
  action:
    | "unknown"
    | "success"
    | "pause-post"
    | "release-post"
    | "pause-methods"
    | "release-methods"
    | "revoke"
    | "unmount"
    | "new-actor"
    | "remount",
) {
  const s = current();
  if (action === "unknown" || action === "success") s.outcome = action;
  else if (action === "pause-methods") {
    let release!: () => void;
    const promise = new Promise<void>((resolve) => {
      release = resolve;
    });
    s.preparation = { promise, release };
  } else if (action === "release-methods") {
    s.preparation?.release();
    delete s.preparation;
  } else if (action === "pause-post") s.release = () => undefined;
  else if (action === "release-post") {
    s.release?.();
    s.release = null;
  } else if (action === "revoke") s.grant = false;
  else if (action === "unmount") s.root.render(null);
  else if (action === "new-actor") {
    s.actorId = crypto.randomUUID();
    ownedActors.add(s.actorId);
    mountManagement();
  } else mountManagement();
}
export function startFinancialReceiptPrintBrowserScenario(
  status: "RECEIVED" | "REVERSED",
) {
  const sample = actionContextFixtures.find(
    (row) =>
      row.request.purpose === "receipt_reprint" &&
      financialObject(financialObject(row.data.payment_resource).payment)
        .status === status,
  );
  check(sample, "Synthetic original Receipt fixture missing");
  const actorId = crypto.randomUUID();
  ownedActors.add(actorId);
  const s: Scenario = {
    actorId,
    ...hostRoot(),
    services: {} as FinancialUiServices,
    calls: [],
    seed: null,
    release: null,
    outcome: "success",
    grant: true,
    originalPrint: window.print,
    prints: 0,
  };
  scenario = s;
  window.print = () => {
    s.prints += 1;
  };
  const fetcher: typeof fetch = (url, init) => {
    const call = callEvidence(url, init);
    s.calls.push(call);
    check(
      call.method === "GET" && call.url.includes(sample.request.source_id),
      "Receipt copy uses original identity GET only",
    );
    return Promise.resolve(
      response(sample.data, init, { limit: 50, next_cursor: null }),
    );
  };
  const receipt = financialObject(financialObject(sample.data.context).receipt),
    confirmed: ConfirmedFinancialAction = {
      operation: "receiptReprint",
      target: { id: sample.request.source_id },
      wireBody: stringifyFinancialJson({
        reason: "Synthetic confirmed original copy",
      }),
      reply: {
        requestId: "synthetic-browser-reprint",
        propertyId: sample.propertyId,
        data: {
          receipt_id: financialId(receipt.id),
          receipt_number: receipt.receipt_number ?? null,
          reprint: {
            id: ids.event,
            receipt_id: receipt.id ?? null,
            reprinted_at: "2026-09-08T12:00:00+07:00",
            reprinted_by: actorId,
            reason: "Synthetic confirmed original copy",
            delivery_reference: null,
          },
        },
      },
    };
  const transport = createFinancialTransport(fetcher, () => "synthetic-csrf");
  s.services = {
    transport,
    references: createFinancialReferenceClient(fetcher),
    recovery: createFinancialRecovery(
      sealedIntentStore,
      transport,
      () => "synthetic-csrf",
    ),
  };
  s.root.render(
    createElement(
      "main",
      { className: "financial-management" },
      createElement("h2", null, "Synthetic unrelated financial screen"),
      createElement(FinancialCurrentAfterConfirmation, {
        scope: {
          actorId,
          propertyId: sample.propertyId,
          signal: new AbortController().signal,
        },
        capabilities: grantSet("receipts.reprint") as Parameters<
          typeof FinancialCurrentAfterConfirmation
        >[0]["capabilities"],
        services: s.services,
        confirmed,
      }),
      createElement(
        "p",
        null,
        "Synthetic private non-Receipt content must not print",
      ),
    ),
  );
  return {
    payerName: financialObject(receipt.identity_snapshot).payer_legal_name,
    receiptNumber: receipt.receipt_number,
    reprintId: ids.event,
    status,
  };
}
export async function cleanupFinancialWorkflowBrowserScenario() {
  const s = current();
  releaseFinancialWorkflowBrowserAttempt();
  s.release?.();
  s.preparation?.release();
  s.root.unmount();
  s.host.remove();
  window.print = s.originalPrint;
  for (const actor of ownedActors) {
    const opened = await sealedIntentStore.read(actor);
    if (opened) await sealedIntentStore.clear(actor, opened.requestKey);
  }
  ownedActors.clear();
  scenario = null;
}
export const financialWorkflowBrowserCommandCount = commands.length;

let releaseBrowserAttemptLock: (() => void) | null = null;
export async function holdFinancialWorkflowBrowserAttempt() {
  const actorId = current().actorId;
  await new Promise<void>((resolve, reject) => {
    void navigator.locks
      .request(`property-rental.financial-attempt:${actorId}`, async () => {
        await new Promise<void>((release) => {
          releaseBrowserAttemptLock = release;
          resolve();
        });
      })
      .catch(reject);
  });
}
export function releaseFinancialWorkflowBrowserAttempt() {
  releaseBrowserAttemptLock?.();
  releaseBrowserAttemptLock = null;
}
export async function verifyFinancialWorkflowBrowserReplay() {
  const s = current(),
    posts = s.calls.filter((c) => c.method === "POST"),
    first = posts[0];
  check(
    s.seed && posts.length === 1 && first,
    "Only explicit replay may send exactly one new attempt",
  );
  check(
    first.key === s.seed.key &&
      first.body === s.seed.body &&
      first.url === s.seed.url &&
      first.actor === s.seed.actor &&
      first.property === s.seed.property,
    "Replay must preserve original bytes, key, operation and scope",
  );
  check(
    (await sealedIntentStore.read(s.actorId)) === null,
    "Validated replay retires original encrypted intent",
  );
  check(
    s.host.querySelector('[aria-label="Confirmed financial result"]'),
    "Confirmed result remains visible independently of current-read availability",
  );
  return "TEST-FE-499";
}
export async function verifyFinancialWorkflowBrowserNewAndReplay() {
  const s = current(),
    posts = s.calls.filter((c) => c.method === "POST"),
    first = posts[0],
    second = posts[1];
  check(
    !s.seed && posts.length === 2 && first && second,
    "Exactly one new command and one explicitly reviewed original replay",
  );
  check(
    first.key &&
      first.key === second.key &&
      first.body === second.body &&
      first.actor === second.actor &&
      first.property === second.property,
    "New unknown and replay preserve exact original intent",
  );
  check(
    (await sealedIntentStore.read(s.actorId)) === null,
    "Success alone retires the original unknown outcome",
  );
  check(
    s.host.querySelector('[aria-label="Confirmed financial result"]'),
    "New/replayed result remains visible",
  );
  return "TEST-FE-500";
}
export async function verifyFinancialWorkflowBrowserRevoked() {
  const s = current();
  check(
    s.seed && !s.calls.some((c) => c.method === "POST"),
    "Revoked replay cannot dispatch",
  );
  check(
    (await sealedIntentStore.read(s.seed.actor ?? ""))?.requestKey ===
      s.seed.key,
    "Permission loss preserves original pending record",
  );
  return "TEST-FE-501";
}
export async function verifyFinancialWorkflowBrowserStale() {
  const s = current(),
    posts = s.calls.filter((c) => c.method === "POST");
  check(
    s.seed && posts.length === 1 && posts[0]?.signal?.aborted,
    "Old in-flight scope is aborted",
  );
  check(
    !s.host.querySelector('[aria-label="Confirmed financial result"]'),
    "Late success cannot populate a changed or unmounted scope",
  );
  check(
    (await sealedIntentStore.read(s.seed.actor ?? ""))?.requestKey ===
      s.seed.key,
    "Uncertain original intent remains in its original actor store",
  );
  return "TEST-FE-502";
}
export async function verifyFinancialWorkflowBrowserAttemptRefusal() {
  const s = current();
  check(
    s.seed && !s.calls.some((c) => c.method === "POST"),
    "A real held browser attempt lock prevents replay dispatch",
  );
  check(
    (await sealedIntentStore.read(s.actorId))?.requestKey === s.seed.key,
    "Cross-tab coordination refusal preserves pending evidence",
  );
  return "TEST-FE-503";
}
export function verifyFinancialWorkflowBrowserReceipt() {
  const s = current(),
    copy = s.host.querySelector(".financial-receipt-print");
  check(
    copy &&
      s.prints === 1 &&
      s.calls.length === 1 &&
      s.calls[0]?.method === "GET",
    "Only an explicit original Receipt print follows its authorized identity read",
  );
  check(
    getComputedStyle(s.host.querySelector("h2") as HTMLElement).display ===
      "none",
    "Unrelated financial heading must not print",
  );
  check(
    !document.body.innerText.includes("Synthetic private non-Receipt content"),
    "Only selected Receipt content survives print layout",
  );
  check(
    document.body.innerText.includes(ids.event),
    "Original confirmed reprint reference is preserved in print layout",
  );
  return "TEST-FE-504";
}

export function verifyFinancialMoneyBrowser() {
  const table = document.querySelector(
    '[aria-label="Payment list page"] table',
  );
  check(table, "Payment table must be loaded");
  const cells = Array.from(table.querySelectorAll(".financial-money"));
  check(
    cells.length === 6 &&
      cells.every((c) => getComputedStyle(c).textAlign === "right"),
    "Both amount headers and all USD/KHR cells must align right",
  );
  check(
    table.textContent.includes("USD 2.00") &&
      table.textContent.includes("KHR 4,143"),
    "Exact currency labels and amounts must remain visible",
  );
  const wrapper = table.closest(".financial-table-scroll");
  check(
    wrapper &&
      getComputedStyle(wrapper).overflowX === "auto" &&
      wrapper.getBoundingClientRect().width <= window.innerWidth,
    "Financial table keeps bounded narrow-screen overflow",
  );
  return "TEST-FE-513";
}
export function verifyFinancialReviewOwnershipBrowser() {
  const dialog = document.querySelector('[role="dialog"]');
  check(
    dialog?.textContent.includes("Confirm: Record USD refund") &&
      !dialog.textContent.includes("Confirm: Record payment"),
    "Late cross-form preparation cannot replace the chosen Refund review",
  );
  check(
    current().calls.every((c) => c.method === "GET"),
    "Preparing or superseding an action cannot submit it",
  );
  return "TEST-FE-514";
}
export function verifyFinancialStaleReadsBrowser() {
  check(
    document.querySelector(
      '[aria-label="Selected Payment record"] [aria-label="Original payment facts"]',
    ),
    "Original Payment facts remain after a Refund",
  );
  check(
    document.querySelector(
      '[aria-label="Original Receipt record"] [aria-label="Original Receipt identity"]',
    ),
    "Original Receipt identity remains after a Refund",
  );
  check(
    !document.querySelector(
      '[aria-label="Selected Payment record"] [aria-label="Current payment position"]',
    ) &&
      !document.querySelector(
        '[aria-label="Original Receipt record"] [aria-label="Current Receipt-linked Payment context"]',
      ),
    "The earlier Payment and Receipt positions cannot remain labelled current",
  );
  check(
    document.body.textContent.includes(
      "Loaded financial facts are out of date",
    ),
    "Stale reads must explain the required reload",
  );
  check(
    current().calls.filter((c) => c.method === "POST").length === 1,
    "Only the explicitly confirmed Refund is sent",
  );
  return "TEST-FE-515";
}

function recordedAllocationBrowserFixture(actorId: string): FinancialObject {
  const instant = "2026-09-01T12:00:00.123456+07:00";
  return {
    allocation: {
      id: ids.allocation,
      payment_id: ids.payment,
      property_id: ids.property,
      target_kind: "INVOICE",
      target_id: ids.invoice,
      invoice_id: ids.invoice,
      late_payment_charge_id: null,
      target_customer_id: ids.customer,
      amount_usd_cents: 100,
      posted_at: instant,
      posted_by: actorId,
      authorization_reference: "payments.allocate",
      reversal: null,
      within_invoice_basis: "RENT_THEN_RECURRING_SERVICES_PROPOSAL",
      between_invoice_basis: "FIFO_PROPOSAL",
      between_invoice_sequence: 1,
      customer_designation_reference: null,
      proposal_batch_id: ids.key,
      proposal_generated_at: instant,
      selected_invoice_number_snapshot: "INV-ORIGINAL-SYNTHETIC",
      selected_invoice_due_date: "2026-09-01",
      selected_invoice_issued_at: instant,
      proposal_trace: {
        payment_id: ids.payment,
        property_id: ids.property,
        proposal_batch_id: ids.key,
        generated_at: instant,
        available_usd_cents: 100,
        unallocated_after_usd_cents: 0,
        policy: "DUE_ISSUED_NUMBER_ID/RENT_SERVICE_SOURCE_ORDER",
        payment_scope: "NORMAL_CUSTOMER",
        continuation_status: "COMPLETE",
        designation_reference: null,
        targets: [
          {
            invoice_id: ids.invoice,
            invoice_number: "INV-ORIGINAL-SYNTHETIC",
            version: 1,
            target_customer_id: ids.customer,
            due_date: "2026-09-01",
            issued_at: instant,
            sequence: 1,
            amount_usd_cents: 100,
            details: [
              {
                invoice_line_id: ids.other,
                category: "RENT",
                amount_usd_cents: 100,
                outstanding_usd_cents: 100,
                attribution_basis: "RENT_FIRST_PROPOSAL",
              },
            ],
          },
        ],
      },
    },
    details: [
      {
        id: ids.event,
        detail_sequence: 1,
        invoice_line_id: ids.other,
        late_payment_charge_id: null,
        invoice_line_category_snapshot: "RENT",
        proposed_amount_usd_cents: 100,
        posted_amount_usd_cents: 100,
        attribution_basis: "RENT_FIRST_PROPOSAL",
      },
    ],
  };
}

export function setFinancialHistoryBrowserUnavailable(value: boolean) {
  current().historyUnavailable = value;
}

export function verifyFinancialRecordedProposalBrowser() {
  const region = current().host.querySelector(
    '[aria-label="Original recorded proposal"]',
  );
  check(
    region,
    "Selected Allocation must include its original non-null proposal trace",
  );
  check(
    region.textContent.includes("Outstanding at proposal") &&
      region.textContent.includes("USD 1.00"),
    "Original pre-post amount stays explicitly historical",
  );
  check(
    !region.textContent.includes("Current outstanding") &&
      !region.textContent.includes("Confirmation posts only"),
    "Saved trace cannot claim a current position or invite confirmation",
  );
  return "TEST-FE-526";
}

export function showFinancialMoneyHeaderBrowser() {
  const sample = [...actionContextFixtures]
    .reverse()
    .find(
      (s) =>
        s.request.purpose === "allocation_reversal" &&
        financialObject(s.data.target).kind === "INVOICE",
    );
  check(sample, "Original synthetic Allocation target evidence is required");
  current().root.render(
    createElement(
      "section",
      { className: "panel financial-management" },
      createElement(TargetEvidence, {
        target: sample.data.target,
        items: sample.data.items,
      }),
    ),
  );
}

export function verifyFinancialMoneyHeaderBrowser() {
  const host = current().host;
  const header = Array.from(host.querySelectorAll("th")).find(
    (node) => node.textContent === "Original attribution / proposal",
  );
  check(
    header && getComputedStyle(header).textAlign === "right",
    "Proposed-money header aligns with its exact cells",
  );
  const table = header.closest("table"),
    wrapper = table?.closest(".financial-table-scroll");
  check(
    table?.textContent.includes("Proposed: USD") &&
      wrapper &&
      getComputedStyle(wrapper).overflowX === "auto" &&
      wrapper.getBoundingClientRect().width <= innerWidth,
    "Exact proposed currency and bounded narrow-screen overflow are preserved",
  );
  return "TEST-FE-527";
}

export async function verifyFinancialDraftDiscardBrowser() {
  const s = current();
  check(
    s.calls.every((c) => c.method === "GET"),
    "Draft navigation must not submit a financial action",
  );
  check(
    (await sealedIntentStore.read(s.actorId)) === null,
    "Unsent drafts are never persisted as encrypted command intents or automatically replayed",
  );
  return "TEST-FE-528";
}

function draftReversalBrowserContext(actorId: string): FinancialObject {
  const sample = [...actionContextFixtures]
    .reverse()
    .find(
      (item) =>
        item.request.purpose === "refund_correction_reversal" &&
        financialObject(item.data.context).reversal === null &&
        financialObject(
          financialObject(financialObject(item.data.context).refund).refund,
        ).source_lifecycle_event_id === null,
    );
  check(
    sample?.request.refund_id,
    "Synthetic reversible USD Refund context required",
  );
  let serialized = stringifyFinancialJson(sample.data);
  for (const [from, to] of [
    [sample.actorId, actorId],
    [sample.propertyId, ids.property],
    [sample.request.source_id, ids.event],
    [sample.request.refund_id, ids.refund],
  ])
    serialized = serialized.replaceAll(
      JSON.stringify(from),
      JSON.stringify(to),
    );
  return financialObject(parseFinancialJson(serialized));
}

export function verifyFinancialSourceDraftBrowser() {
  const s = current(),
    region = s.host.querySelector("#financial-refund-workspace");
  check(
    region?.textContent.includes("Selected Refund source"),
    "Cancelled source change retains loaded finite source facts",
  );
  check(
    s.calls.every((call) => call.method === "GET"),
    "Source cancellation cannot submit a command",
  );
  return "TEST-FE-540";
}
export async function verifyFinancialOperationDraftBrowser(posts: number) {
  const s = current(),
    sent = s.calls.filter((call) => call.method === "POST");
  check(
    sent.length === posts &&
      sent.every((call) =>
        call.url.endsWith(
          `/refunds/${ids.refund}/verified-returns/${ids.event}/reverse`,
        ),
      ),
    "Only the explicitly confirmed correction may be sent",
  );
  if (posts === 2)
    check(
      sent[0]?.key === sent[1]?.key && sent[0]?.body === sent[1]?.body,
      "Replay retains its original key and exact bytes",
    );
  check(
    (await sealedIntentStore.read(s.actorId)) === null,
    "Confirmed correction clears only its encrypted recovery journal",
  );
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  check(
    event.defaultPrevented,
    "Unrelated unsent payout still warns on unload",
  );
  return "TEST-FE-541";
}
export async function verifyFinancialSelectionDraftBrowser(posts: number) {
  const s = current(),
    sent = s.calls.filter((call) => call.method === "POST");
  check(sent.length === posts, "Selection edits never send another action");
  if (posts === 2) {
    check(
      sent[0]?.key === sent[1]?.key && sent[0]?.body === sent[1]?.body,
      "Original Payment replay must retain key and bytes",
    );
    check(
      sent[0]?.body &&
        financialObject(parseFinancialJson(sent[0].body)).payment_scope_kind ===
          "NORMAL_CUSTOMER",
      "Later payer selection cannot change the original Payment",
    );
  }
  check(
    (await sealedIntentStore.read(s.actorId)) === null,
    "No unresolved journal remains",
  );
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  check(event.defaultPrevented, "Unsent payer selection still warns on unload");
  return "TEST-FE-542";
}

export function verifyFinancialFrozenOutcomeBrowser(operation: string) {
  if (
    ![
      "creditRecognize",
      "creditReverse",
      "creditApply",
      "creditApplicationReverse",
      "refundCreate",
      "refundReturn",
      "refundReturnReverse",
    ].includes(operation)
  )
    return null;
  const result = current().host.querySelector(
    '[aria-label="Confirmed financial result"]',
  );
  check(result, "Confirmed saved result required");
  const refund = operation.startsWith("refund");
  const position = result.querySelector(
    `[aria-label="${refund ? "Refund value" : "Credit position"} at original confirmation"]`,
  );
  check(
    position?.textContent.includes(
      operation === "refundReturn" ? "USD 0.00" : "USD 1.00",
    ),
    "Frozen amounts remain attributed to their original confirmation",
  );
  check(
    !result.querySelector('[aria-label^="Current "]'),
    "No saved command position may claim Current",
  );
  return "TEST-FE-546";
}

export function recordFinancialOutcomeBrowserReturn(unavailable: boolean) {
  const s = current();
  check(
    s.savedOutcome && s.outcome === "unknown",
    "Original synthetic payout must be saved before intervening return",
  );
  s.currentOutcomeRefund = financialObject(fixture("refundReturn").data);
  s.outcomeReadsUnavailable = unavailable;
}

export async function verifyFinancialInterveningReturnBrowser(
  unavailable: boolean,
) {
  const s = current(),
    posts = s.calls.filter((call) => call.method === "POST");
  check(
    posts.length === 2 &&
      posts[0]?.key === posts[1]?.key &&
      posts[0]?.body === posts[1]?.body,
    "Delayed replay must retain original key and bytes with no extra action",
  );
  check(
    s.savedOutcome?.net_refund_usd_cents === 100 &&
      s.currentOutcomeRefund?.net_refund_usd_cents === 0,
    "Original saved payout and later fully returned value remain separate",
  );
  check(
    (await sealedIntentStore.read(s.actorId)) === null,
    "Validated original replay clears only its encrypted journal",
  );
  verifyFinancialFrozenOutcomeBrowser("refundCreate");
  const workspace = s.host.querySelector('[aria-label="Refund workspace"]');
  const currentValue = workspace?.querySelector(
    '[aria-label="Current Refund value"]',
  );
  if (unavailable)
    check(
      !currentValue && workspace?.querySelector('[role="alert"]'),
      "Failed read cannot relabel saved payout as current",
    );
  else
    check(
      currentValue?.textContent.includes("Current net Refund USDUSD 0.00"),
      "Authorized fresh read reports the later zero net Refund as Current",
    );
  check(
    s.calls.filter(
      (call) =>
        call.method === "GET" && call.url.includes(`/refunds/${ids.refund}`),
    ).length === 1,
    "Fresh Refund must use the authorized read route once",
  );
  return "TEST-FE-547";
}
