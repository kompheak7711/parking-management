// TEST-FE-580: synthetic real-browser ledger navigation, privacy, pagination and responsive evidence.
/** Opt-in, synthetic-only real-browser harness. The application never imports it. */
import { createRoot, type Root } from "react-dom/client";
import { CustomerAccountLedger } from "../CustomerAccountLedger";
import {
  createCustomerLedgerClient,
  type CustomerLedgerApi,
} from "../customerLedgerClient";
import {
  canonicalLedgerEvents,
  ledgerComponent,
  ledgerComposition,
  ledgerEvent,
  ledgerKhrScenario,
  ledgerVoidScenario,
  ledgerId,
  ledgerIds,
  ledgerPosition,
  ledgerRequestUrl,
  syntheticLedgerResponse,
  type SyntheticLedger,
} from "../customerLedgerFixtures";
import "../styles.css";
let root: Root | null = null,
  host: HTMLDivElement | null = null;
let state: SyntheticLedger = {},
  api: CustomerLedgerApi | null = null;
let calls: {
  url: string;
  method: string | undefined;
  actor: string | null;
  property: string | null;
  bodyPresent: boolean;
  signal: AbortSignal | null | undefined;
}[] = [];
let hold = false,
  release: (() => void) | null = null;
export function ledgerBrowserEvidence() {
  return {
    calls: calls.map(({ signal, ...call }) => ({
      ...call,
      aborted: signal?.aborted ?? false,
    })),
    storage: {
      localKeys: Object.keys(localStorage),
      sessionKeys: Object.keys(sessionStorage),
    },
    search: location.search,
    hash: location.hash,
  };
}
export function stopLedgerBrowser() {
  root?.unmount();
  root = null;
  host?.remove();
  host = null;
  release?.();
  release = null;
  api = null;
}
export function startLedgerBrowser(scenario = "canonical", selected = true) {
  stopLedgerBrowser();
  calls = [];
  hold = false;
  state = {};
  if (scenario === "KHR") state = ledgerKhrScenario();
  if (scenario === "issued-void") state = ledgerVoidScenario();
  if (scenario === "draft-void") state = ledgerVoidScenario(true);
  if (scenario === "large")
    state.position = ledgerPosition("9".repeat(64), "0", {
      security_deposit_usd_cents: "900000000000000000",
      pet_deposit_usd_cents: "12345",
    });
  if (scenario === "empty") state.events = [];
  if (scenario === "history-pages")
    state.events = Array.from({ length: 101 }, (_, index) =>
      ledgerEvent("INVOICE_ISSUED", index + 1, {
        occurred_at: "2026-07-01T00:00:00.000001+00:00",
      }),
    );
  if (scenario === "component-pages") {
    const event = ledgerEvent("INVOICE_ISSUED", 1, { component_count: 51 });
    state.events = [event];
    state.components = Array.from({ length: 51 }, (_, index) =>
      ledgerComponent(event, index + 1),
    );
  }
  if (scenario === "picker-pages")
    state.customers = Array.from({ length: 51 }, (_, index) => ({
      id: ledgerId(index + 1),
      legal_name: `Synthetic Customer ${String(index + 1)}`,
    }));
  if (scenario === "composition-pages")
    state.composition = Array.from({ length: 51 }, (_, index) =>
      ledgerComposition(index + 1),
    );
  if (scenario === "canonical")
    state.composition = [
      ledgerComposition(),
      ledgerComposition(2),
      ledgerComposition(3, {
        balance_kind: "LATE_PAYMENT_CHARGE",
        balance_source_id: ledgerIds.other,
        invoice_id: null,
        invoice_line_id: null,
        late_payment_charge_id: ledgerIds.other,
        category: null,
        description: "Separate Late-payment Charge",
        balance_usd_cents: "2100",
        detail_key: `LATE_PAYMENT_CHARGE:${ledgerIds.other}`,
      }),
    ];
  api = createCustomerLedgerClient(async (url, init) => {
    const headers = new Headers(init?.headers);
    calls.push({
      url: ledgerRequestUrl(url),
      method: init?.method,
      actor: headers.get("X-Billing-Actor-ID"),
      property: headers.get("X-Financial-Property-ID"),
      bodyPresent: init?.body !== undefined,
      signal: init?.signal,
    });
    if (hold) {
      hold = false;
      await new Promise<void>((done) => {
        release = done;
      });
    }
    return syntheticLedgerResponse(ledgerRequestUrl(url), init ?? {}, state);
  });
  host = document.createElement("div");
  host.id = "synthetic-ledger-root";
  document.body.append(host);
  root = createRoot(host);
  root.render(
    <CustomerAccountLedger
      actorId={ledgerIds.actor}
      api={api}
      requested={
        selected
          ? {
              customerId: ledgerIds.customer,
              propertyId: ledgerIds.property,
              sequence: 1,
            }
          : undefined
      }
    />,
  );
  return {
    actorId: ledgerIds.actor,
    propertyId: ledgerIds.property,
    customerId: ledgerIds.customer,
    canonicalEventCount: canonicalLedgerEvents().length,
  };
}
export function controlLedgerBrowser(
  action:
    | "stale"
    | "deny"
    | "unavailable"
    | "recover"
    | "hold-next"
    | "release"
    | "change-actor",
) {
  if (action === "stale") state.revision = "c".repeat(64);
  if (action === "deny") state.failure = 403;
  if (action === "unavailable") state.failure = 503;
  if (action === "recover") state.failure = undefined;
  if (action === "hold-next") hold = true;
  if (action === "release") {
    release?.();
    release = null;
  }
  if (action === "change-actor" && api)
    root?.render(<CustomerAccountLedger actorId={ledgerIds.other} api={api} />);
}

/** The external browser driver calls this after its scenario assertions pass. */
export function verifyLedgerBrowserEvidence() {
  const evidence = ledgerBrowserEvidence();
  if (
    evidence.calls.length === 0 ||
    evidence.calls.some((call) => {
      const url = new URL(call.url, location.origin);
      return (
        call.method !== "GET" ||
        call.bodyPresent ||
        call.actor !== ledgerIds.actor ||
        call.property !== ledgerIds.property ||
        url.origin !== location.origin ||
        url.pathname !==
          `/api/v1/customers/${ledgerIds.customer}/account-ledger`
      );
    }) ||
    evidence.storage.localKeys.length !== 0 ||
    evidence.storage.sessionKeys.length !== 0 ||
    evidence.search !== "" ||
    evidence.hash !== ""
  ) {
    throw new Error("Synthetic ledger browser privacy evidence failed");
  }
  return "TEST-FE-580";
}
