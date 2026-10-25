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

export interface PaymentsApi {
  payable(propertyId: string, customerId: string): Promise<PayableItem[]>;
  methods(propertyId: string): Promise<PaymentMethodOption[]>;
  khrRate(propertyId: string): Promise<KhrRate | null>;
  receive(
    propertyId: string,
    input: ReceiveInput,
    key: string,
  ): Promise<ReceiveResult>;
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
  };
}

export const paymentsApi = createPaymentsApi();
