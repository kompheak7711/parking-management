/** Synthetic ledger wire fixtures; never import from a production entry point. */
import { financialInstant, type FinancialObject } from "./financialContracts";
import {
  LEDGER_EVENTS,
  LEDGER_BUCKETS,
  LEDGER_BALANCES,
  type LedgerEventKind,
} from "./customerLedgerClient";
export const ledgerIds = {
  actor: "00000000-0000-4000-8000-000000000001",
  property: "00000000-0000-4000-8000-000000000002",
  customer: "00000000-0000-4000-8000-000000000003",
  invoice: "00000000-0000-4000-8000-000000000004",
  payment: "00000000-0000-4000-8000-000000000005",
  other: "00000000-0000-4000-8000-000000000006",
};
export function ledgerId(index: number): string {
  return `10000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
}
export const ledgerRevision = "a".repeat(64);
export function ledgerPosition(
  invoice = "21000",
  charge = "2100",
  extra: Record<string, string> = {},
): FinancialObject {
  return {
    invoice_usd_cents: invoice,
    charge_usd_cents: charge,
    credit_usd_cents: "0",
    payment_usd_cents: "0",
    security_deposit_usd_cents: "0",
    pet_deposit_usd_cents: "0",
    total_owed_usd_cents: (BigInt(invoice) + BigInt(charge)).toString(),
    ...extra,
  };
}
export function ledgerEvent(
  kind: LedgerEventKind = "INVOICE_ISSUED",
  index = 1,
  extra: FinancialObject = {},
): FinancialObject {
  return {
    property_id: ledgerIds.property,
    customer_id: ledgerIds.customer,
    event_kind: kind,
    event_order: LEDGER_EVENTS[kind][0],
    event_id: ledgerId(index),
    occurred_at: `2026-07-${String(Math.min(index, 28)).padStart(2, "0")}T00:00:00+00:00`,
    business_date: "2026-07-01",
    source_table: "invoices",
    source_reference: `SYNTHETIC-${String(index)}`,
    recorded_amount_usd_cents:
      kind === "INVOICE_VOIDED" || kind === "DRAFT_INVOICE_VOIDED"
        ? null
        : "51000",
    source_audit: {},
    invoice_id: ledgerIds.invoice,
    late_payment_charge_id: null,
    payment_id: null,
    customer_credit_id: null,
    deposit_id: null,
    refund_id: null,
    component_count: 1,
    invoice_effect_usd_cents: "51000",
    charge_effect_usd_cents: "0",
    credit_effect_usd_cents: "0",
    payment_effect_usd_cents: "0",
    security_deposit_effect_usd_cents: "0",
    pet_deposit_effect_usd_cents: "0",
    position_after_instant: ledgerPosition("51000", "0"),
    ...extra,
  };
}
export function canonicalLedgerEvents(): FinancialObject[] {
  return [
    ledgerEvent("INVOICE_ISSUED", 1, { component_count: 2 }),
    ledgerEvent("PAYMENT_RECEIVED", 2, {
      source_table: "payments",
      invoice_id: null,
      recorded_amount_usd_cents: "30000",
      invoice_effect_usd_cents: "0",
      payment_effect_usd_cents: "30000",
      payment_id: ledgerIds.payment,
      position_after_instant: ledgerPosition("51000", "0", {
        payment_usd_cents: "30000",
      }),
    }),
    ledgerEvent("PAYMENT_ALLOCATED", 3, {
      component_count: 2,
      source_table: "payment_allocations",
      recorded_amount_usd_cents: "30000",
      invoice_effect_usd_cents: "-30000",
      payment_effect_usd_cents: "-30000",
      payment_id: ledgerIds.payment,
      position_after_instant: ledgerPosition("21000", "0"),
    }),
    ledgerEvent("LATE_PAYMENT_CHARGED", 4, {
      source_table: "late_payment_charges",
      recorded_amount_usd_cents: "2100",
      invoice_effect_usd_cents: "0",
      charge_effect_usd_cents: "2100",
      late_payment_charge_id: ledgerIds.other,
      position_after_instant: ledgerPosition(),
    }),
  ];
}
export function ledgerComponent(
  event: FinancialObject = ledgerEvent(),
  index = 1,
  extra: FinancialObject = {},
): FinancialObject {
  const result = Object.fromEntries(
    Object.entries(event).filter(
      ([key]) =>
        key !== "component_count" &&
        key !== "position_after_instant" &&
        !key.endsWith("_effect_usd_cents"),
    ),
  );
  return {
    ...result,
    invoice_line_id: ledgerId(100 + index),
    balance_kind: "INVOICE",
    balance_source_id: ledgerId(100 + index),
    effect_usd_cents: index === 1 ? "50000" : "1000",
    category: index === 1 ? "RENT" : "SERVICE",
    description: index === 1 ? "July Rent" : "Trash Collection",
    detail_key: index.toString(16).padStart(64, "0"),
    ...extra,
  };
}
export function ledgerComposition(
  index = 1,
  extra: FinancialObject = {},
): FinancialObject {
  const source = ledgerId(100 + index);
  return {
    property_id: ledgerIds.property,
    customer_id: ledgerIds.customer,
    balance_kind: "INVOICE",
    balance_source_id: source,
    invoice_id: ledgerIds.invoice,
    invoice_line_id: source,
    late_payment_charge_id: null,
    category: index === 1 ? "RENT" : "SERVICE",
    description: index === 1 ? "July Rent" : "Trash Collection",
    balance_usd_cents: index === 1 ? "20000" : "1000",
    detail_key: `INVOICE:${source}`,
    ...extra,
  };
}
export function ledgerEnvelope(
  items = canonicalLedgerEvents(),
  section = "history",
  position = ledgerPosition(),
): FinancialObject {
  return {
    data: {
      property_id: ledgerIds.property,
      customer_id: ledgerIds.customer,
      customer_name: "Synthetic Customer",
      source_revision: ledgerRevision,
      position,
      event_count: section === "history" ? items.length : 4,
      section,
      items,
    },
    page: { limit: 50, next_cursor: null },
    meta: {
      actor_id: ledgerIds.actor,
      property_id: ledgerIds.property,
      request_id: "",
    },
  };
}
export function ledgerWireResponse(
  envelope: FinancialObject,
  init: RequestInit,
  status = 200,
): Response {
  const requestId = new Headers(init.headers).get("X-Request-ID") ?? "";
  const row = {
    ...envelope,
    meta: { ...(envelope.meta as FinancialObject), request_id: requestId },
  };
  return new Response(JSON.stringify(row), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": requestId,
      "Cache-Control": "private, no-store",
      Vary: "Cookie",
    },
  });
}
export function ledgerErrorResponse(
  status: number,
  init: RequestInit,
): Response {
  const codes: Record<number, string> = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    503: "SERVICE_UNAVAILABLE",
  };
  return ledgerWireResponse(
    {
      error: {
        code: codes[status] ?? "INTERNAL_ERROR",
        message: "Synthetic safe failure.",
        fields: [],
        rule_ids: [],
        current_version: null,
      },
      meta: {},
    },
    init,
    status,
  );
}
export function ledgerCursorToken(
  row: FinancialObject,
  section = "history",
  revision = ledgerRevision,
): string {
  return btoa(
    JSON.stringify(
      section === "history"
        ? [
            1,
            "b".repeat(64),
            revision,
            row.occurred_at,
            row.event_kind,
            row.event_id,
          ]
        : [1, "b".repeat(64), revision, row.detail_key],
    ),
  )
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}
export interface SyntheticLedger {
  events?: FinancialObject[];
  composition?: FinancialObject[];
  components?: FinancialObject[];
  position?: FinancialObject;
  customers?: { id: string; legal_name: string }[];
  revision?: string;
  failure?: number;
}
export function syntheticLedgerResponse(
  url: string,
  init: RequestInit,
  state: SyntheticLedger = {},
): Response {
  if (state.failure) return ledgerErrorResponse(state.failure, init);
  const params = new URL(url, "http://127.0.0.1").searchParams,
    section = url.startsWith("/api/v1/customer-ledger/customers")
      ? "customers"
      : (params.get("section") ?? "history");
  const limit = Number(params.get("limit") ?? "50"),
    revision = state.revision ?? ledgerRevision;
  if (params.get("revision") && params.get("revision") !== revision)
    return ledgerErrorResponse(409, init);
  const events = state.events ?? canonicalLedgerEvents();
  let items: FinancialObject[] =
    section === "customers"
      ? (state.customers ?? [
          { id: ledgerIds.customer, legal_name: "Synthetic Customer" },
        ])
      : section === "history"
        ? events.filter(
            (row) =>
              (!params.get("kind") || row.event_kind === params.get("kind")) &&
              (!params.get("from") ||
                financialInstant(row.occurred_at) >=
                  financialInstant(params.get("from"))) &&
              (!params.get("through") ||
                financialInstant(row.occurred_at) <=
                  financialInstant(params.get("through"))),
          )
        : section === "composition"
          ? (state.composition ?? [ledgerComposition(), ledgerComposition(2)])
          : (state.components ??
            ledgerSourceComponents(
              events.find((row) => row.event_id === params.get("event_id")) ??
                ledgerEvent(),
            ));
  const cursor = params.get("cursor");
  if (cursor) {
    const key: unknown =
      section === "customers"
        ? cursor
        : (
            JSON.parse(
              atob(cursor.replace(/-/g, "+").replace(/_/g, "/")),
            ) as unknown[]
          )[section === "history" ? 5 : 3];
    const index = items.findIndex(
      (row) =>
        (section === "customers"
          ? row.id
          : section === "history"
            ? row.event_id
            : row.detail_key) === key,
    );
    items = items.slice(index + 1);
  }
  const more = items.length > limit;
  items = items.slice(0, limit);
  const next =
    more && items.length
      ? section === "customers"
        ? (items.at(-1)?.id ?? null)
        : ledgerCursorToken(items.at(-1) ?? {}, section, revision)
      : null;
  const data =
    section === "customers"
      ? items
      : {
          property_id: ledgerIds.property,
          customer_id: ledgerIds.customer,
          customer_name: "Synthetic Customer",
          source_revision: revision,
          position:
            state.position ??
            (events.length ? ledgerPosition() : ledgerPosition("0", "0")),
          event_count: events.length,
          section,
          items,
        };
  return ledgerWireResponse(
    {
      data,
      page: { limit, next_cursor: next },
      meta: { actor_id: ledgerIds.actor, property_id: ledgerIds.property },
    },
    init,
  );
}

export function ledgerRequestUrl(value: RequestInfo | URL | undefined): string {
  if (typeof value === "string") return value;
  if (value instanceof URL) return value.href;
  if (value instanceof Request) return value.url;
  throw new Error("Synthetic request URL missing");
}

function ledgerSourceComponents(event: FinancialObject): FinancialObject[] {
  if (event.event_kind === "INVOICE_ISSUED" && event.component_count === 2)
    return [ledgerComponent(event), ledgerComponent(event, 2)];
  const buckets = [
    ["invoice", "INVOICE", ledgerId(101)],
    ["charge", "LATE_PAYMENT_CHARGE", ledgerIds.other],
    ["credit", "CREDIT", ledgerIds.other],
    ["payment", "UNALLOCATED_PAYMENT", ledgerIds.payment],
    ["security_deposit", "SECURITY_DEPOSIT", ledgerIds.other],
    ["pet_deposit", "PET_DEPOSIT", ledgerIds.other],
  ] as const satisfies readonly (readonly [
    keyof typeof LEDGER_BUCKETS,
    keyof typeof LEDGER_BALANCES,
    string,
  ])[];
  return buckets
    .filter(([key]) => event[`${key}_effect_usd_cents`] !== "0")
    .map(([key, kind, id], index) => {
      const effect = event[`${key}_effect_usd_cents`];
      if (typeof effect !== "string")
        throw new Error("Synthetic ledger effect missing");
      return ledgerComponent(event, index + 1, {
        balance_kind: kind,
        balance_source_id: id,
        effect_usd_cents: effect,
        invoice_line_id: kind === "INVOICE" ? id : null,
        category: kind === "INVOICE" ? "RENT" : null,
        description: kind === "INVOICE" ? "July Rent" : null,
      });
    });
}

export function ledgerKhrScenario(): SyntheticLedger {
  const position = ledgerPosition("0", "0", { payment_usd_cents: "10000" });
  const event = ledgerEvent("PAYMENT_RECEIVED", 1, {
    source_table: "payments",
    invoice_id: null,
    payment_id: ledgerIds.payment,
    recorded_amount_usd_cents: "10000",
    invoice_effect_usd_cents: "0",
    payment_effect_usd_cents: "10000",
    position_after_instant: position,
    source_audit: {
      received_currency: "KHR",
      received_amount_minor: "408300",
      usd_accounting_value_cents: "10000",
      payment_method: "Synthetic cash",
      exchange_rate: {
        reference_rate_khr_per_usd: "4062.000000",
        markup_basis_points: "50",
        system_rate_khr_per_usd: "4083.000000",
        applicable_at: "2026-07-01T00:00:00+00:00",
        rate_source: "SYNTHETIC",
      },
    },
  });
  return {
    events: [event],
    position,
    components: ledgerSourceComponents(event),
  };
}

/** Mirrors migration48: void has effects but no recorded transaction amount. */
export function ledgerVoidScenario(draft = false): SyntheticLedger {
  const position = ledgerPosition("0", "0");
  const event = ledgerEvent(
    draft ? "DRAFT_INVOICE_VOIDED" : "INVOICE_VOIDED",
    1,
    {
      source_table: "invoice_void_events",
      recorded_amount_usd_cents: null,
      component_count: draft ? 1 : 2,
      invoice_effect_usd_cents: draft ? "0" : "-51000",
      position_after_instant: position,
      source_audit: { reason: "Synthetic Invoice void" },
    },
  );
  return {
    events: [event],
    position,
    composition: [],
    components: draft
      ? [
          ledgerComponent(event, 1, {
            balance_kind: "NONE",
            balance_source_id: ledgerIds.invoice,
            invoice_line_id: null,
            effect_usd_cents: "0",
            category: null,
            description: null,
          }),
        ]
      : [
          ledgerComponent(event, 1, { effect_usd_cents: "-50000" }),
          ledgerComponent(event, 2, { effect_usd_cents: "-1000" }),
        ],
  };
}
