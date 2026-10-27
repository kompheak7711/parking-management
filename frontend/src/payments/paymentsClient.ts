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

export interface ConfirmedPayment {
  paymentId: string;
  receiptNumber: string;
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

/** V1-058 R5d: the late-payment card of one Invoice (DESIGN.md "Late-payment card"). */
export type ReductionReason =
  | "WRONG_INVOICE"
  | "PAID_ON_TIME_RECORDED_LATE"
  | "OTHER_STAFF_MISTAKE";

export interface LateChargeChange {
  kind: "REDUCTION" | "CHARGE_REVERSAL" | "REDUCTION_REVERSAL";
  previous: number;
  resulting: number;
  at: string;
  by: string | null;
  reasonCode: ReductionReason | null;
  whatHappened: string | null;
  reason: string;
}

export interface LateChargeCard {
  chargeId: string;
  invoiceId: string;
  customerId: string;
  payableAt: string;
  /** The charge moment: what was unpaid was measured then (a late job run is later). */
  chargedAt: string;
  /** The rate applies only to a full charge; an early person-made decision may be lower. */
  fullRate: boolean;
  byApp: boolean;
  addedBy: string | null;
  unpaidAtCharge: number;
  rateBasisPoints: number;
  original: number;
  now: number;
  stillOwed: number;
  paid: number;
  changes: LateChargeChange[];
  paidBy: {
    kind: "PAYMENT" | "CREDIT" | "DEPOSIT";
    paymentId: string | null;
    receiptNumber: string | null;
    amount: number;
    at: string;
  }[];
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
  /** V1-060 B6: money received for a deposit, saved with its Receipt and paying no Invoice. */
  confirm(
    propertyId: string,
    input: Omit<ReceiveInput, "pays">,
    key: string,
  ): Promise<ConfirmedPayment>;
  summary(
    propertyId: string,
    from: string,
    to: string,
  ): Promise<PaymentsSummary>;
  receipt(propertyId: string, paymentId: string): Promise<ReceiptView>;
  reprint(receiptId: string, reason: string, key: string): Promise<void>;
  lateCharge(
    propertyId: string,
    invoiceId: string,
  ): Promise<LateChargeCard | null>;
  reduceLateCharge(
    chargeId: string,
    newAmount: number,
    reason: ReductionReason,
    whatHappened: string,
    key: string,
  ): Promise<void>;
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

const REDUCTION_REASONS = [
  "WRONG_INVOICE",
  "PAID_ON_TIME_RECORDED_LATE",
  "OTHER_STAFF_MISTAKE",
] as const;

function lateCardOf(value: unknown): LateChargeCard | null {
  if (value === null) return null;
  const data = object(value);
  return {
    chargeId: text(data.charge_id),
    invoiceId: text(data.invoice_id),
    customerId: text(data.customer_id),
    payableAt: text(data.payable_at),
    chargedAt: text(data.charged_at),
    fullRate:
      data.decision_outcome === "CONFIRMED_DEFAULT" &&
      cents(data.calculated_default_usd_cents) ===
        cents(data.original_usd_cents),
    byApp: data.by_app === true,
    addedBy: maybeText(data.added_by),
    unpaidAtCharge: cents(data.unpaid_at_charge_usd_cents),
    rateBasisPoints: cents(data.rate_basis_points),
    original: cents(data.original_usd_cents),
    now: cents(data.now_usd_cents),
    stillOwed: cents(data.still_owed_usd_cents),
    paid: cents(data.paid_usd_cents),
    changes: list(data.changes).map((entry) => {
      const change = object(entry);
      const kind = change.kind;
      if (
        kind !== "REDUCTION" &&
        kind !== "CHARGE_REVERSAL" &&
        kind !== "REDUCTION_REVERSAL"
      )
        return invalid();
      const code = change.reason_code;
      return {
        kind,
        previous: cents(change.previous_usd_cents),
        resulting: cents(change.resulting_usd_cents),
        at: text(change.at),
        by: maybeText(change.by),
        reasonCode:
          code === null || code === undefined
            ? null
            : (REDUCTION_REASONS.find((reason) => reason === code) ??
              invalid()),
        whatHappened: maybeText(change.what_happened),
        reason: text(change.reason),
      };
    }),
    paidBy: list(data.paid_by).map((entry) => {
      const item = object(entry);
      const kind = item.kind;
      if (kind !== "PAYMENT" && kind !== "CREDIT" && kind !== "DEPOSIT")
        return invalid();
      return {
        kind,
        paymentId: maybeText(item.payment_id),
        receiptNumber: maybeText(item.receipt_number),
        amount: cents(item.amount_usd_cents),
        at: text(item.at),
      };
    }),
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
    confirm: (propertyId, input, key) =>
      billingTransport(
        "/api/v1/properties/" + encoded(propertyId) + "/payments",
        (body) => {
          const data = object(body.data);
          return {
            paymentId: text(object(data.payment).id),
            receiptNumber: text(object(data.receipt).receipt_number),
          };
        },
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
    lateCharge: (propertyId, invoiceId) =>
      billingTransport(
        "/api/v1/properties/" +
          encoded(propertyId) +
          "/invoices/" +
          encoded(invoiceId) +
          "/late-charge",
        (body) => lateCardOf(body.data),
        undefined,
        transmission,
      ),
    reduceLateCharge: (chargeId, newAmount, reason, whatHappened, key) =>
      billingTransport(
        "/api/v1/late-payment-charges/" + encoded(chargeId) + "/reductions",
        () => undefined,
        {
          key,
          body: {
            new_amount: { currency: "USD", minor_units: newAmount },
            reason,
            what_happened: whatHappened,
          },
        },
        transmission,
      ),
  };
}

export const paymentsApi = createPaymentsApi();
