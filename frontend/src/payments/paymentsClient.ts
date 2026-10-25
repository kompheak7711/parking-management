// V1-058 R5c: the requests of the rebuilt Payments screens. Receive payment saves the payment,
// its Receipt and what it pays in one step on the server (DL-077); the list it ticks from comes
// from the same order the server checks.

import {
  billingTransport,
  type BillingTransmission,
  InvoiceClientError,
} from "../invoiceClient";
import type { PayableItem, PaysTargetInput } from "./payFor";

export interface PaymentMethodOption {
  id: string;
  code: string;
  displayName: string;
}

export interface ReceiveInput {
  payer_customer_id: string;
  payment_method_id: string;
  received_at: string;
  evidence_reference: string;
  payer_intent_memo: string | null;
  amount: { currency: "USD" | "KHR"; minor_units: number };
  /** Riel only: the dollar value the money counts as. */
  usd_accounting_amount?: { currency: "USD"; minor_units: number };
  pays: { mode: "OLDEST_FIRST" | "NAMED"; targets: PaysTargetInput[] };
}

export interface ReceivedAllocation {
  kind: "INVOICE" | "LATE_PAYMENT_CHARGE";
  invoiceNumber: string;
  amount: number;
}

export interface ReceiveResult {
  paymentId: string;
  receiptNumber: string;
  currency: "USD" | "KHR";
  receivedMinor: number;
  usdCents: number;
  allocations: ReceivedAllocation[];
  left: number;
}

export interface KhrRate {
  /** Riel for one dollar, after the markup and rounding up (BR-MONEY-005 to 008). */
  rate: number;
}

/** The seven kinds the Payments cards split each payment into (DESIGN.md Summary cards). */
export const PAY_KINDS = [
  "RENT",
  "UTIL",
  "SVC",
  "LATE",
  "DEPOSIT",
  "MOVEOUT",
  "CREDIT",
] as const;
export type PayKind = (typeof PAY_KINDS)[number];

export interface PaymentRow {
  paymentId: string;
  receiptNumber: string | null;
  paymentDate: string;
  receivedAt: string;
  customerId: string;
  methodName: string;
  methodCode: string;
  status: "RECEIVED" | "REVERSED";
  currency: "USD" | "KHR";
  receivedMinor: number;
  usdCents: number;
  left: number;
  /** Refunded straight from this payment; in none of the seven kinds. */
  refunded: number;
  kinds: Partial<Record<PayKind, number>>;
}

export interface PaymentsSummary {
  from: string;
  to: string;
  truncated: boolean;
  payments: number;
  received: number;
  left: number;
  leftPayments: number;
  refunded: number;
  rielMinor: number;
  rielUsd: number;
  kinds: Record<PayKind, { cents: number; payments: number }>;
  rows: PaymentRow[];
}

export interface ReceiptLine {
  kind: "INVOICE" | "LATE_PAYMENT_CHARGE" | "DEPOSIT" | "CREDIT" | "REFUND";
  invoiceId: string | null;
  invoiceNumber: string | null;
  category: string | null;
  dueDate: string | null;
  depositType: string | null;
  amount: number;
}

export interface ReceiptView {
  paymentId: string;
  receiptId: string | null;
  receiptNumber: string | null;
  status: "RECEIVED" | "REVERSED";
  customerId: string;
  receivedAt: string;
  currency: "USD" | "KHR";
  receivedMinor: number;
  usdCents: number;
  /** Riel for one dollar when the money came in riel. */
  rate: string | null;
  methodName: string;
  methodCode: string;
  reference: string | null;
  payerNote: string | null;
  receivedBy: string | null;
  left: number;
  lines: ReceiptLine[];
  reprints: { at: string; by: string; reason: string }[];
  reprintCount: number;
}

export interface PaymentsApi {
  payable(propertyId: string, customerId: string): Promise<PayableItem[]>;
  methods(propertyId: string): Promise<PaymentMethodOption[]>;
  khrRate(propertyId: string): Promise<KhrRate | null>;
  receive(
    propertyId: string,
    input: ReceiveInput,
    key: string,
  ): Promise<ReceiveResult>;
  summary(
    propertyId: string,
    from: string,
    to: string,
  ): Promise<PaymentsSummary>;
  receipt(propertyId: string, paymentId: string): Promise<ReceiptView>;
  reprint(receiptId: string, reason: string, key: string): Promise<void>;
}

function invalid(): never {
  throw new InvoiceClientError(null, "INVALID_RESPONSE", false);
}
function object(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : invalid();
}
function text(value: unknown): string {
  return typeof value === "string" ? value : invalid();
}
function cents(value: unknown): number {
  const number = typeof value === "bigint" ? Number(value) : value;
  return typeof number === "number" &&
    Number.isSafeInteger(number) &&
    number >= 0
    ? number
    : invalid();
}
function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : invalid();
}

function payableItem(value: unknown): PayableItem {
  const item = object(value);
  const kind = item.kind;
  if (kind !== "INVOICE" && kind !== "LATE_PAYMENT_CHARGE") return invalid();
  return {
    kind,
    id: text(item.id),
    invoiceId: text(item.invoice_id),
    invoiceNumber: text(item.invoice_number),
    category: item.category === null ? null : text(item.category),
    dueDate: item.due_date === null ? null : text(item.due_date),
    owed: cents(item.owed_usd_cents),
  };
}

function received(value: unknown): ReceiveResult {
  const data = object(value);
  const payment = object(data.payment);
  const currency = payment.received_currency;
  if (currency !== "USD" && currency !== "KHR") return invalid();
  return {
    paymentId: text(payment.id),
    receiptNumber: text(object(data.receipt).receipt_number),
    currency,
    receivedMinor: cents(payment.received_amount_minor),
    usdCents: cents(payment.usd_accounting_value_cents),
    allocations: list(data.allocations).map((entry) => {
      const allocation = object(entry);
      const kind = allocation.target_kind;
      if (kind !== "INVOICE" && kind !== "LATE_PAYMENT_CHARGE")
        return invalid();
      return {
        kind,
        invoiceNumber: text(allocation.invoice_number),
        amount: cents(allocation.amount_usd_cents),
      };
    }),
    left: cents(data.left_usd_cents),
  };
}

function maybeText(value: unknown): string | null {
  return value === null || value === undefined ? null : text(value);
}
function status(value: unknown): "RECEIVED" | "REVERSED" {
  return value === "RECEIVED" || value === "REVERSED" ? value : invalid();
}
function currency(value: unknown): "USD" | "KHR" {
  return value === "USD" || value === "KHR" ? value : invalid();
}
function kindsOf(value: unknown): Partial<Record<PayKind, number>> {
  const kinds = object(value);
  const out: Partial<Record<PayKind, number>> = {};
  for (const [kind, amount] of Object.entries(kinds)) {
    if (!(PAY_KINDS as readonly string[]).includes(kind)) return invalid();
    out[kind as PayKind] = cents(amount);
  }
  return out;
}

function paymentRow(value: unknown): PaymentRow {
  const row = object(value);
  return {
    paymentId: text(row.payment_id),
    receiptNumber: maybeText(row.receipt_number),
    paymentDate: text(row.payment_date),
    receivedAt: text(row.received_at),
    customerId: text(row.customer_id),
    methodName: text(row.method_name),
    methodCode: text(row.method_code),
    status: status(row.status),
    currency: currency(row.received_currency),
    receivedMinor: cents(row.received_amount_minor),
    usdCents: cents(row.usd_cents),
    left: cents(row.left_usd_cents),
    refunded: cents(row.refunded_usd_cents),
    kinds: kindsOf(row.kinds),
  };
}

function summaryOf(value: unknown): PaymentsSummary {
  const data = object(value);
  const totals = object(data.totals);
  const kinds = object(totals.kinds);
  const truncated = data.truncated;
  if (typeof truncated !== "boolean") return invalid();
  return {
    from: text(data.from),
    to: text(data.to),
    truncated,
    payments: cents(totals.payments),
    received: cents(totals.received_usd_cents),
    left: cents(totals.left_usd_cents),
    leftPayments: cents(totals.left_payments),
    refunded: cents(totals.refunded_usd_cents),
    rielMinor: cents(totals.riel_received_minor),
    rielUsd: cents(totals.riel_usd_cents),
    kinds: Object.fromEntries(
      PAY_KINDS.map((kind) => {
        const card = object(kinds[kind]);
        return [
          kind,
          { cents: cents(card.usd_cents), payments: cents(card.payments) },
        ];
      }),
    ) as Record<PayKind, { cents: number; payments: number }>,
    rows: list(data.rows).map(paymentRow),
  };
}

function receiptOf(value: unknown): ReceiptView {
  const data = object(value);
  const state = status(data.status);
  return {
    paymentId: text(data.payment_id),
    receiptId: maybeText(data.receipt_id),
    receiptNumber: maybeText(data.receipt_number),
    status: state,
    customerId: text(data.customer_id),
    receivedAt: text(data.received_at),
    currency: currency(data.received_currency),
    receivedMinor: cents(data.received_amount_minor),
    usdCents: cents(data.usd_cents),
    rate: maybeText(data.system_rate_khr_per_usd),
    methodName: text(data.method_name),
    methodCode: text(data.method_code),
    reference: maybeText(data.reference),
    payerNote: maybeText(data.payer_note),
    receivedBy: maybeText(data.received_by),
    // A reversed payment pays nothing, so none of it waits (as in the period summary).
    left: state === "REVERSED" ? 0 : cents(data.left_usd_cents),
    lines: list(data.lines).map((entry) => {
      const line = object(entry);
      const kind = line.kind;
      if (
        kind !== "INVOICE" &&
        kind !== "LATE_PAYMENT_CHARGE" &&
        kind !== "DEPOSIT" &&
        kind !== "CREDIT" &&
        kind !== "REFUND"
      )
        return invalid();
      return {
        kind,
        invoiceId: maybeText(line.invoice_id),
        invoiceNumber: maybeText(line.invoice_number),
        category: maybeText(line.category),
        dueDate: maybeText(line.due_date),
        depositType: maybeText(line.deposit_type),
        amount: cents(line.amount_usd_cents),
      };
    }),
    reprints: list(data.reprints).map((entry) => {
      const reprint = object(entry);
      return {
        at: text(reprint.reprinted_at),
        by: text(reprint.reprinted_by),
        reason: text(reprint.reason),
      };
    }),
    reprintCount: cents(data.reprint_count),
  };
}

const encoded = encodeURIComponent;

export function createPaymentsApi(
  transmission?: BillingTransmission,
): PaymentsApi {
  return {
    payable: (propertyId, customerId) =>
      billingTransport(
        "/api/v1/properties/" +
          encoded(propertyId) +
          "/payments/payable?customer_id=" +
          encoded(customerId),
        (body) => list(object(body.data).items).map(payableItem),
        undefined,
        transmission,
      ),
    methods: (propertyId) =>
      billingTransport(
        "/api/v1/properties/" + encoded(propertyId) + "/payment-methods",
        (body) =>
          list(body.data).map((entry) => {
            const method = object(entry);
            return {
              id: text(method.id),
              code: text(method.code),
              displayName: text(method.display_name),
            };
          }),
        undefined,
        transmission,
      ),
    // The rate comes from a preview of one dollar; no key is sent and nothing is saved.
    khrRate: (propertyId) =>
      billingTransport(
        "/api/v1/properties/" + encoded(propertyId) + "/payments/khr-preview",
        (body) => {
          const data = object(body.data);
          return data.status === "available"
            ? { rate: cents(data.system_rate_khr_per_usd) }
            : null;
        },
        { body: { usd_amount_cents: 100 }, key: "", preview: true },
        transmission,
      ),
    receive: (propertyId, input, key) =>
      billingTransport(
        "/api/v1/properties/" + encoded(propertyId) + "/payments/receive",
        (body) => received(body.data),
        { key, body: input },
        transmission,
      ),
    summary: (propertyId, from, to) =>
      billingTransport(
        "/api/v1/properties/" +
          encoded(propertyId) +
          "/payments/summary?from=" +
          encoded(from) +
          "&to=" +
          encoded(to),
        (body) => summaryOf(body.data),
        undefined,
        transmission,
      ),
    receipt: (propertyId, paymentId) =>
      billingTransport(
        "/api/v1/properties/" +
          encoded(propertyId) +
          "/payments/" +
          encoded(paymentId) +
          "/receipt-lines",
        (body) => receiptOf(body.data),
        undefined,
        transmission,
      ),
    reprint: (receiptId, reason, key) =>
      billingTransport(
        "/api/v1/receipts/" + encoded(receiptId) + "/reprints",
        () => undefined,
        { key, body: { reason } },
        transmission,
      ),
  };
}

export const paymentsApi = createPaymentsApi();
