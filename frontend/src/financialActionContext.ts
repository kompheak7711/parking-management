import {
  captureFinancialRequest,
  exactKeys,
  financialId,
  financialInstant,
  financialInteger,
  financialObject,
  invalidFinancial,
  type FinancialObject,
} from "./financialContracts";
import { validateFinancialReply } from "./financialResponse";
import { ExactJsonNumber } from "./financialJson";

export const FINANCIAL_ACTION_PURPOSES = [
  "allocation",
  "allocation_reversal",
  "receipt_reprint",
  "credit_recognition",
  "credit_reversal",
  "credit_application",
  "credit_application_reversal",
  "refund_return",
  "refund_correction_reversal",
] as const;
export type FinancialActionPurpose = (typeof FINANCIAL_ACTION_PURPOSES)[number];
export interface FinancialActionContextInput {
  operation: "financialActionContext";
  purpose: FinancialActionPurpose;
  source_id: string;
  target_kind?: "INVOICE" | "LATE_PAYMENT_CHARGE";
  target_id?: string;
  refund_id?: string;
  limit?: number;
  cursor?: string;
}
const maximumEvent = 9_000_000_000_000_000n;
const revisionPattern = /^[0-9a-f]{64}$/;
function text(value: unknown): string {
  if (typeof value !== "string") return invalidFinancial();
  return value;
}
function id(value: unknown): string {
  const checked = financialId(value);
  if (checked !== value) invalidFinancial();
  return checked;
}
function same(value: unknown, expected: unknown): void {
  if (id(value) !== id(expected)) invalidFinancial();
}
function optionalId(value: unknown): void {
  if (value !== null) id(value);
}
function label(value: unknown): void {
  if (typeof value !== "string" || !/[^ ]/.test(value) || value.includes("\0"))
    invalidFinancial();
}
function choice(value: unknown, values: readonly string[]): string {
  if (typeof value !== "string" || !values.includes(value))
    return invalidFinancial();
  return value;
}
function money(
  value: unknown,
  minimum = 0n,
  maximum = 9_223_372_036_854_775_807n,
): bigint {
  return BigInt(financialInteger(value, minimum, maximum));
}
function date(value: unknown): void {
  const checked = text(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(checked)) invalidFinancial();
  financialInstant(checked + "T00:00:00Z");
}
export function financialActionCursor(value: unknown): {
  revision: string;
  sequence: number;
  id: string;
} {
  const match =
    /^([0-9a-f]{64}):([1-9][0-9]{0,4}):([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(
      text(value),
    );
  if (!match || Number(match[2]) > 32767) return invalidFinancial();
  return {
    revision: text(match[1]),
    sequence: Number(match[2]),
    id: id(match[3]),
  };
}
export function captureFinancialActionContext(input: FinancialObject): void {
  exactKeys(
    input,
    ["operation", "purpose", "source_id"],
    ["target_kind", "target_id", "refund_id", "limit", "cursor"],
  );
  choice(input.purpose, FINANCIAL_ACTION_PURPOSES);
  input.source_id = financialId(input.source_id);
  const posting =
    input.purpose === "allocation" || input.purpose === "credit_application";
  if ((input.target_kind === undefined) !== (input.target_id === undefined))
    invalidFinancial();
  if (input.target_id !== undefined) {
    if (!posting) invalidFinancial();
    choice(input.target_kind, ["INVOICE", "LATE_PAYMENT_CHARGE"]);
    input.target_id = financialId(input.target_id);
  }
  if (
    (input.purpose === "refund_correction_reversal") !==
    (input.refund_id !== undefined)
  )
    invalidFinancial();
  if (input.refund_id !== undefined)
    input.refund_id = financialId(input.refund_id);
  if (input.limit !== undefined) financialInteger(input.limit, 1n, 100n);
  if (input.cursor !== undefined) financialActionCursor(input.cursor);
}
export function financialActionContextPath(
  property: string,
  input: FinancialObject,
): string {
  const source = financialId(input.source_id);
  const paths: Record<FinancialActionPurpose, string> = {
    allocation: `/payments/${source}/allocation-context`,
    allocation_reversal: `/payment-allocations/${source}/reversal-context`,
    receipt_reprint: `/receipts/${source}/reprint-context`,
    credit_recognition: `/payments/${source}/credit-recognition-context`,
    credit_reversal: `/customer-credits/${source}/reversal-context`,
    credit_application: `/customer-credits/${source}/application-context`,
    credit_application_reversal: `/credit-applications/${source}/reversal-context`,
    refund_return: `/refunds/${source}/verified-return-context`,
    refund_correction_reversal: `/refunds/${input.purpose === "refund_correction_reversal" ? financialId(input.refund_id) : source}/corrections/${source}/reversal-context`,
  };
  return `/api/v1/properties/${financialId(property)}${paths[choice(input.purpose, FINANCIAL_ACTION_PURPOSES) as FinancialActionPurpose]}`;
}
function reversal(
  value: unknown,
  parentField: string,
  parent: string,
  capability: string,
): void {
  if (value === null) return;
  const row = financialObject(value);
  exactKeys(row, [
    "id",
    parentField,
    "reason",
    "occurred_at",
    "actor_id",
    "authorization_reference",
  ]);
  id(row.id);
  same(row[parentField], parent);
  label(row.reason);
  financialInstant(row.occurred_at);
  id(row.actor_id);
  if (row.authorization_reference !== capability) invalidFinancial();
}
function rateMillionths(value: unknown): bigint {
  const literal =
    value instanceof ExactJsonNumber
      ? value.literal
      : typeof value === "string"
        ? value
        : typeof value === "bigint" ||
            (typeof value === "number" && Number.isSafeInteger(value))
          ? String(value)
          : invalidFinancial();
  if (!/^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$/.test(literal))
    return invalidFinancial();
  const [whole = "", fraction = ""] = literal.split(".");
  const scaled = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  if (scaled <= 0n) invalidFinancial();
  return scaled;
}
function ceilRatio(numerator: bigint, denominator: bigint): bigint {
  return (numerator + denominator - 1n) / denominator;
}
function sourceExchangeRate(
  value: unknown,
  payment: FinancialObject,
  includesActor: boolean,
): FinancialObject | null {
  if (payment.received_currency === "USD") {
    if (value !== null) invalidFinancial();
    return null;
  }
  const fx = financialObject(value);
  exactKeys(fx, [
    "id",
    "reference_rate_khr_per_usd",
    "system_rate_khr_per_usd",
    "markup_basis_points",
    "rate_source",
    "applicable_at",
    ...(includesActor ? ["entered_by"] : []),
    "channel_actual_currency",
    "channel_actual_amount_minor",
    "channel_actual_usd_value_cents",
    "channel_actual_rate_khr_per_usd",
    "channel_confirmed_at",
  ]);
  same(fx.id, payment.exchange_rate_record_id);
  const reference = rateMillionths(fx.reference_rate_khr_per_usd),
    system = money(fx.system_rate_khr_per_usd, 1n);
  if (
    money(fx.markup_basis_points, 50n, 50n) !== 50n ||
    system !== ceilRatio(reference * 1005n, 1_000_000_000n)
  )
    invalidFinancial();
  choice(fx.rate_source, ["ABA_AUTOMATIC", "ABA_EQUIVALENT_MANUAL"]);
  if (includesActor) {
    optionalId(fx.entered_by);
    if (fx.rate_source === "ABA_EQUIVALENT_MANUAL" && fx.entered_by === null)
      invalidFinancial();
  }
  const confirmed = financialInstant(payment.confirmed_at);
  if (financialInstant(fx.applicable_at) > confirmed) invalidFinancial();
  const channel = [
    "channel_actual_currency",
    "channel_actual_amount_minor",
    "channel_actual_usd_value_cents",
    "channel_actual_rate_khr_per_usd",
  ].some((key) => fx[key] !== null);
  if (channel) {
    label(payment.channel_transaction_reference);
    if (financialInstant(fx.channel_confirmed_at) > confirmed)
      invalidFinancial();
  } else if (fx.channel_confirmed_at !== null) invalidFinancial();
  if (
    fx.channel_actual_currency !== null &&
    fx.channel_actual_currency !== "KHR"
  )
    invalidFinancial();
  const received = money(payment.received_amount_minor, 1n, maximumEvent),
    accounting = money(payment.usd_accounting_value_cents, 1n, maximumEvent);
  if (
    fx.channel_actual_amount_minor !== null &&
    money(fx.channel_actual_amount_minor, 1n) !== received
  )
    invalidFinancial();
  if (
    fx.channel_actual_usd_value_cents !== null &&
    money(fx.channel_actual_usd_value_cents, 1n) !== accounting
  )
    invalidFinancial();
  const usedRate =
    fx.channel_actual_rate_khr_per_usd === null
      ? system * 1_000_000n
      : rateMillionths(fx.channel_actual_rate_khr_per_usd);
  if (
    fx.channel_actual_amount_minor === null &&
    received !== ceilRatio(accounting * usedRate, 100_000_000n)
  )
    invalidFinancial();
  if (
    fx.channel_actual_amount_minor !== null &&
    fx.channel_actual_usd_value_cents === null
  ) {
    const numerator = received * 100_000_000n;
    if (
      accounting !==
      numerator / usedRate + ((numerator % usedRate) * 2n >= usedRate ? 1n : 0n)
    )
      invalidFinancial();
  }
  return fx;
}
function sourcePaymentFacts(
  resource: FinancialObject,
  payment: FinancialObject,
): void {
  exactKeys(resource, [
    "payment",
    "property_timezone",
    "position",
    "receipt",
    "reversal",
    "exchange_rate_evidence_id",
    "exchange_rate",
  ]);
  exactKeys(payment, [
    "id",
    "status",
    "lease_id",
    "property_id",
    "confirmed_at",
    "confirmed_by",
    "payment_date",
    "payment_number",
    "payer_customer_id",
    "payer_intent_memo",
    "payment_method_id",
    "received_currency",
    "payment_scope_kind",
    "identified_invoice_id",
    "received_amount_minor",
    "authorization_reference",
    "exchange_rate_record_id",
    "usd_accounting_value_cents",
    "payment_method_code_snapshot",
    "payment_method_name_snapshot",
    "channel_transaction_reference",
    "identified_late_payment_charge_id",
  ]);
  if (resource.property_timezone !== "Asia/Phnom_Penh") invalidFinancial();
  for (const key of [
    "id",
    "property_id",
    "confirmed_by",
    "payer_customer_id",
    "payment_method_id",
  ])
    id(payment[key]);
  for (const key of [
    "lease_id",
    "identified_invoice_id",
    "identified_late_payment_charge_id",
    "exchange_rate_record_id",
  ])
    optionalId(payment[key]);
  for (const key of [
    "payment_number",
    "authorization_reference",
    "payment_method_code_snapshot",
    "payment_method_name_snapshot",
  ])
    label(payment[key]);
  for (const key of ["payer_intent_memo", "channel_transaction_reference"])
    if (payment[key] !== null) label(payment[key]);
  date(payment.payment_date);
  financialInstant(payment.confirmed_at);
  choice(payment.status, ["RECEIVED", "REVERSED"]);
  choice(payment.payment_scope_kind, [
    "NORMAL_CUSTOMER",
    "THIRD_PARTY_IDENTIFIED",
  ]);
  choice(payment.received_currency, ["USD", "KHR"]);
  money(payment.received_amount_minor, 1n, maximumEvent);
  if (resource.receipt !== null) {
    const linked = financialObject(resource.receipt);
    exactKeys(linked, ["id", "receipt_number"]);
    id(linked.id);
    label(linked.receipt_number);
  }
  if ((resource.reversal !== null) !== (payment.status === "REVERSED"))
    invalidFinancial();
  if (resource.reversal !== null) {
    const reversed = financialObject(resource.reversal);
    exactKeys(reversed, [
      "id",
      "payment_id",
      "reason",
      "occurred_at",
      "actor_id",
      "authorization_reference",
    ]);
    id(reversed.id);
    same(reversed.payment_id, payment.id);
    id(reversed.actor_id);
    label(reversed.reason);
    label(reversed.authorization_reference);
    if (
      financialInstant(reversed.occurred_at) <
      financialInstant(payment.confirmed_at)
    )
      invalidFinancial();
  }
  if (payment.received_currency === "USD") {
    if (
      payment.exchange_rate_record_id !== null ||
      resource.exchange_rate_evidence_id !== null ||
      money(payment.received_amount_minor, 1n, maximumEvent) !==
        money(payment.usd_accounting_value_cents, 1n, maximumEvent)
    )
      invalidFinancial();
  } else
    same(resource.exchange_rate_evidence_id, payment.exchange_rate_record_id);
  sourceExchangeRate(resource.exchange_rate, payment, true);
}
function repeatedCreditExchangeRate(
  value: unknown,
  resource: FinancialObject,
): void {
  const payment = financialObject(resource.payment);
  const creditRate = sourceExchangeRate(value, payment, false);
  if (creditRate === null) return;
  const original = financialObject(resource.exchange_rate);
  for (const [key, value] of Object.entries(creditRate)) {
    const expected = original[key];
    if (value === null || expected === null) {
      if (value !== expected) invalidFinancial();
    } else if (
      key === "reference_rate_khr_per_usd" ||
      key === "channel_actual_rate_khr_per_usd"
    ) {
      if (rateMillionths(value) !== rateMillionths(expected))
        invalidFinancial();
    } else if (
      [
        "system_rate_khr_per_usd",
        "markup_basis_points",
        "channel_actual_amount_minor",
        "channel_actual_usd_value_cents",
      ].includes(key)
    ) {
      if (money(value) !== money(expected)) invalidFinancial();
    } else if (key === "applicable_at" || key === "channel_confirmed_at") {
      if (financialInstant(value) !== financialInstant(expected))
        invalidFinancial();
    } else if (value !== expected) invalidFinancial();
  }
}

function credit(
  value: unknown,
  property: string,
  resource: FinancialObject,
  requestId: string,
): FinancialObject {
  const payment = financialObject(resource.payment);
  const row = financialObject(value),
    item = financialObject(row.credit),
    position = financialObject(row.position);
  exactKeys(row, ["credit", "position", "source_payment", "exchange_rate"]);
  exactKeys(item, [
    "id",
    "customer_id",
    "source_payment_id",
    "recognized_usd_cents",
    "recognized_at",
    "recognized_by",
    "reason",
    "customer_authorization_reference",
    "authorization_reference",
  ]);
  exactKeys(position, [
    "customer_credit_id",
    "customer_id",
    "source_payment_id",
    "property_id",
    "recognized_usd_cents",
    "applied_usd_cents",
    "refunded_usd_cents",
    "reversed_usd_cents",
    "available_usd_cents",
  ]);
  repeatedCreditExchangeRate(row.exchange_rate, resource);
  validateFinancialReply(
    { data: row, meta: { property_id: property, request_id: requestId } },
    captureFinancialRequest({
      operation: "creditGet",
      target: { id: id(item.id) },
    }),
    property,
    requestId,
  );
  const source = financialObject(row.source_payment);
  exactKeys(source, [
    "id",
    "property_id",
    "payer_customer_id",
    "received_currency",
    "received_amount_minor",
    "usd_accounting_value_cents",
    "confirmed_at",
    "exchange_rate_record_id",
    "channel_transaction_reference",
  ]);
  for (const [key, value] of Object.entries(source))
    if (value !== payment[key]) invalidFinancial();
  same(item.source_payment_id, payment.id);
  same(item.customer_id, payment.payer_customer_id);
  same(position.customer_credit_id, item.id);
  same(position.customer_id, item.customer_id);
  same(position.source_payment_id, payment.id);
  same(position.property_id, property);
  const recognized = money(item.recognized_usd_cents, 1n, maximumEvent);
  if (money(position.recognized_usd_cents, 1n, maximumEvent) !== recognized)
    invalidFinancial();
  const amounts = [
    "applied_usd_cents",
    "refunded_usd_cents",
    "reversed_usd_cents",
    "available_usd_cents",
  ].map((key) => money(position[key], 0n, recognized));
  if (amounts.reduce((sum, amount) => sum + amount, 0n) !== recognized)
    invalidFinancial();
  const reversed = money(position.reversed_usd_cents, 0n, recognized);
  const active = recognized - reversed;
  if (
    (reversed !== 0n && reversed !== recognized) ||
    recognized > money(payment.usd_accounting_value_cents, 1n, maximumEvent) ||
    active >
      money(
        financialObject(financialObject(resource.position).dispositions)
          .credit_usd_cents,
      ) ||
    (payment.status === "REVERSED" && active !== 0n)
  )
    invalidFinancial();
  if (
    financialInstant(item.recognized_at) <
    financialInstant(payment.confirmed_at)
  )
    invalidFinancial();
  id(item.recognized_by);
  label(item.reason);
  label(item.customer_authorization_reference);
  if (item.authorization_reference !== "credits.recognize") invalidFinancial();
  return row;
}
function target(value: unknown, property: string): FinancialObject {
  const row = financialObject(value);
  id(row.id);
  same(row.property_id, property);
  id(row.customer_id);
  optionalId(row.lease_id);
  if (row.kind === "INVOICE") {
    exactKeys(row, [
      "kind",
      "id",
      "property_id",
      "customer_id",
      "lease_id",
      "invoice_number",
      "status",
      "due_date",
      "issued_at",
      "outstanding_usd_cents",
      "line_count",
      "original_total_usd_cents",
      "adjusted_total_usd_cents",
    ]);
    label(row.invoice_number);
    date(row.due_date);
    const status = choice(row.status, [
      "DRAFT",
      "UNPAID",
      "PARTIALLY_PAID",
      "PAID",
      "VOID",
    ]);
    if (row.issued_at !== null) financialInstant(row.issued_at);
    const count = money(row.line_count, 0n, 32767n),
      originalTotal = money(row.original_total_usd_cents),
      adjustedTotal = money(row.adjusted_total_usd_cents),
      outstanding = money(row.outstanding_usd_cents, 0n, adjustedTotal);
    if (
      (count === 0n && (originalTotal !== 0n || adjustedTotal !== 0n)) ||
      (count > 0n && originalTotal < count)
    )
      invalidFinancial();
    if (
      (["DRAFT", "VOID", "PAID"].includes(status) && outstanding !== 0n) ||
      (["UNPAID", "PARTIALLY_PAID"].includes(status) && outstanding === 0n)
    )
      invalidFinancial();
  } else {
    exactKeys(row, [
      "kind",
      "id",
      "property_id",
      "customer_id",
      "lease_id",
      "source_invoice_id",
      "payable_at",
      "original_usd_cents",
      "reversed",
      "adjusted_obligation_usd_cents",
      "remaining_balance_usd_cents",
    ]);
    if (row.kind !== "LATE_PAYMENT_CHARGE" || typeof row.reversed !== "boolean")
      invalidFinancial();
    id(row.source_invoice_id);
    financialInstant(row.payable_at);
    const original = money(row.original_usd_cents, 1n),
      adjusted = money(row.adjusted_obligation_usd_cents, 0n, original);
    const remaining = money(row.remaining_balance_usd_cents, 0n, adjusted);
    if (row.reversed && (adjusted !== 0n || remaining !== 0n))
      invalidFinancial();
  }
  return row;
}
function targetScope(
  row: FinancialObject,
  payment: FinancialObject,
  creditCustomer: unknown,
): void {
  if (creditCustomer !== null) {
    same(row.customer_id, creditCustomer);
    return;
  }
  const scope = choice(payment.payment_scope_kind, [
    "NORMAL_CUSTOMER",
    "THIRD_PARTY_IDENTIFIED",
  ]);
  if (scope === "NORMAL_CUSTOMER")
    same(row.customer_id, payment.payer_customer_id);
  else {
    if (
      payment.lease_id === null &&
      payment.identified_invoice_id === null &&
      payment.identified_late_payment_charge_id === null
    )
      invalidFinancial();
    if (payment.lease_id !== null) same(row.lease_id, payment.lease_id);
  }
  if (payment.identified_invoice_id !== null)
    same(
      row.kind === "INVOICE" ? row.id : row.source_invoice_id,
      payment.identified_invoice_id,
    );
  if (payment.identified_late_payment_charge_id !== null) {
    if (row.kind !== "LATE_PAYMENT_CHARGE") invalidFinancial();
    same(row.id, payment.identified_late_payment_charge_id);
  }
}
function originalEvent(
  value: unknown,
  allocation: boolean,
  source: string,
  payment: FinancialObject,
  creditRow: FinancialObject | null,
  selected: FinancialObject,
): FinancialObject {
  const row = financialObject(value);
  exactKeys(row, [
    "id",
    "target_kind",
    "target_id",
    "amount_usd_cents",
    "within_invoice_basis",
    "customer_designation_reference",
    "proposal_generated_at",
    "authorization_reference",
    ...(allocation
      ? [
          "payment_id",
          "target_customer_id",
          "between_invoice_basis",
          "proposal_batch_id",
          "between_invoice_sequence",
          "selected_invoice_due_date",
          "selected_invoice_issued_at",
          "selected_invoice_number_snapshot",
          "posted_at",
          "posted_by",
        ]
      : ["customer_credit_id", "occurred_at", "actor_id"]),
  ]);
  same(row.id, source);
  same(row.target_id, selected.id);
  if (row.target_kind !== selected.kind) invalidFinancial();
  money(row.amount_usd_cents, 1n, maximumEvent);
  choice(row.within_invoice_basis, [
    "RENT_THEN_RECURRING_SERVICES_PROPOSAL",
    "CUSTOMER_DESIGNATED",
    "OTHER_APPLICABLE_OBLIGATION",
    "NOT_APPLICABLE",
    // The re-posted rest of a Credit payment a correction put back keeps this label (V1-056
    // sub-slices 10e-3e and 10e-3e-2); the database writes it only on a Credit payment and its
    // lines, never on a Payment allocation.
    ...(allocation ? [] : ["PUT_BACK_BY_CORRECTION"]),
  ]);
  if (row.customer_designation_reference !== null)
    label(row.customer_designation_reference);
  if (row.proposal_generated_at !== null)
    financialInstant(row.proposal_generated_at);
  if (allocation) {
    same(row.payment_id, payment.id);
    same(row.target_customer_id, selected.customer_id);
    if (
      financialInstant(row.posted_at) < financialInstant(payment.confirmed_at)
    )
      invalidFinancial();
    id(row.posted_by);
    if (row.authorization_reference !== "payments.allocate") invalidFinancial();
    const basis = choice(row.between_invoice_basis, [
      "FIFO_PROPOSAL",
      "CUSTOMER_DESIGNATED",
      "THIRD_PARTY_DESIGNATED",
      "DIRECT_LATE_PAYMENT_CHARGE",
      // A confirmed wrong-Unit Payment move (BR-PAY-042, V1-056 slice 7).
      "WRONG_UNIT_MOVE",
    ]);
    if (
      ["CUSTOMER_DESIGNATED", "THIRD_PARTY_DESIGNATED"].includes(basis) !==
      (row.customer_designation_reference !== null)
    )
      invalidFinancial();
    const proposed = row.proposal_batch_id !== null;
    if (proposed) {
      id(row.proposal_batch_id);
      money(row.between_invoice_sequence, 1n, 32767n);
      date(row.selected_invoice_due_date);
      financialInstant(row.selected_invoice_issued_at);
      label(row.selected_invoice_number_snapshot);
      financialInstant(row.proposal_generated_at);
      if (selected.kind !== "INVOICE" || basis === "DIRECT_LATE_PAYMENT_CHARGE")
        invalidFinancial();
    } else if (
      [
        row.between_invoice_sequence,
        row.selected_invoice_due_date,
        row.selected_invoice_issued_at,
        row.selected_invoice_number_snapshot,
        row.proposal_generated_at,
      ].some((v) => v !== null) ||
      basis === "FIFO_PROPOSAL" ||
      row.within_invoice_basis === "RENT_THEN_RECURRING_SERVICES_PROPOSAL"
    )
      invalidFinancial();
    if (
      (selected.kind === "LATE_PAYMENT_CHARGE") !==
      (row.within_invoice_basis === "NOT_APPLICABLE")
    )
      invalidFinancial();
  } else {
    same(row.customer_credit_id, financialObject(creditRow?.credit).id);
    if (
      financialInstant(row.occurred_at) <=
      financialInstant(financialObject(creditRow?.credit).recognized_at)
    )
      invalidFinancial();
    id(row.actor_id);
    if (
      row.authorization_reference !== "credits.apply" ||
      (row.within_invoice_basis === "CUSTOMER_DESIGNATED") !==
        (row.customer_designation_reference !== null) ||
      (row.within_invoice_basis === "RENT_THEN_RECURRING_SERVICES_PROPOSAL") !==
        (row.proposal_generated_at !== null)
    )
      invalidFinancial();
    if (
      selected.kind === "INVOICE"
        ? row.within_invoice_basis === "NOT_APPLICABLE"
        : !["NOT_APPLICABLE", "CUSTOMER_DESIGNATED"].includes(
            text(row.within_invoice_basis),
          )
    )
      invalidFinancial();
  }
  return row;
}
function refundSummary(
  context: FinancialObject,
  property: string,
  expected: string,
  payment: FinancialObject | null,
  creditRow: FinancialObject | null,
  paymentResource: FinancialObject | null,
): FinancialObject {
  const summary = financialObject(context.refund),
    row = financialObject(summary.refund),
    source = financialObject(summary.source);
  exactKeys(summary, ["refund", "source", "net_refund_usd_cents"]);
  exactKeys(source, ["type", "id", "property_id"]);
  exactKeys(row, [
    "id",
    "refund_number",
    "source_payment_id",
    "source_customer_credit_id",
    "source_deposit_id",
    "source_lifecycle_event_id",
    "pet_refund_review_id",
    "recipient_customer_id",
    "refund_amount_minor",
    "refund_currency",
    "usd_accounting_value_cents",
    "processed_at",
    "processed_by",
    "reason",
    "authorization_reference",
  ]);
  same(source.property_id, property);
  same(row.id, expected);
  id(row.recipient_customer_id);
  label(row.refund_number);
  label(row.reason);
  label(row.authorization_reference);
  financialInstant(row.processed_at);
  id(row.processed_by);
  const payout = money(row.refund_amount_minor, 1n);
  if (
    row.refund_currency !== "USD" ||
    money(row.usd_accounting_value_cents, 1n) !== payout
  )
    invalidFinancial();
  money(summary.net_refund_usd_cents, 0n, payout);
  const kind = choice(source.type, ["PAYMENT", "CREDIT", "DEPOSIT"]);
  const fields = {
    PAYMENT: "source_payment_id",
    CREDIT: "source_customer_credit_id",
    DEPOSIT: "source_deposit_id",
  };
  for (const [key, field] of Object.entries(fields)) {
    if (key === kind) same(row[field], source.id);
    else if (row[field] !== null) invalidFinancial();
  }
  optionalId(row.source_lifecycle_event_id);
  optionalId(row.pet_refund_review_id);
  if (kind === "DEPOSIT") {
    if (
      payment !== null ||
      creditRow !== null ||
      (row.source_lifecycle_event_id !== null) ===
        (row.pet_refund_review_id !== null)
    )
      invalidFinancial();
    const deposit = financialObject(context.deposit_source);
    exactKeys(deposit, ["id", "deposit_type", "held_usd_cents"]);
    same(deposit.id, source.id);
    choice(deposit.deposit_type, ["SECURITY", "PET"]);
    money(deposit.held_usd_cents);
    if (
      (deposit.deposit_type === "PET") !==
      (row.pet_refund_review_id !== null)
    )
      invalidFinancial();
  } else {
    if (
      !payment ||
      context.deposit_source !== null ||
      row.source_lifecycle_event_id !== null ||
      row.pet_refund_review_id !== null
    )
      invalidFinancial();
    same(row.recipient_customer_id, payment.payer_customer_id);
    if (kind === "PAYMENT") {
      if (creditRow !== null) invalidFinancial();
      same(source.id, payment.id);
    } else same(source.id, financialObject(creditRow?.credit).id);
    const originalSource =
      kind === "PAYMENT"
        ? payment.usd_accounting_value_cents
        : financialObject(creditRow?.credit).recognized_usd_cents;
    const currentRefunded =
      kind === "PAYMENT"
        ? financialObject(
            financialObject(paymentResource?.position).dispositions,
          ).refund_usd_cents
        : financialObject(creditRow?.position).refunded_usd_cents;
    if (
      payout > money(originalSource, 1n, maximumEvent) ||
      money(summary.net_refund_usd_cents) > money(currentRefunded) ||
      financialInstant(row.processed_at) <=
        financialInstant(
          kind === "PAYMENT"
            ? payment.confirmed_at
            : financialObject(creditRow?.credit).recognized_at,
        )
    )
      invalidFinancial();
  }
  return row;
}
function correction(
  value: unknown,
  refund: FinancialObject,
  expected: string,
  original: FinancialObject | null,
): FinancialObject {
  const row = financialObject(value);
  exactKeys(row, [
    "id",
    "refund_id",
    "correction_kind",
    "reverses_correction_id",
    "source_balance_effect_usd_cents",
    "source_balance_effect_original_minor",
    "previous_net_refund_usd_cents",
    "resulting_net_refund_usd_cents",
    "reason",
    "evidence_reference",
    "occurred_at",
    "actor_id",
    "authorization_reference",
    "verified_return_amount_minor",
    "verified_return_currency",
    "verified_returned_at",
    "return_method_reference",
  ]);
  same(row.id, expected);
  same(row.refund_id, refund.id);
  const ceiling = money(refund.refund_amount_minor, 1n);
  const effect = money(row.source_balance_effect_usd_cents, -ceiling, ceiling);
  if (
    effect === 0n ||
    money(row.previous_net_refund_usd_cents, 0n, ceiling) - effect !==
      money(row.resulting_net_refund_usd_cents, 0n, ceiling)
  )
    invalidFinancial();
  label(row.reason);
  label(row.evidence_reference);
  label(row.authorization_reference);
  const occurred = financialInstant(row.occurred_at);
  id(row.actor_id);
  if (original === null) {
    if (
      row.correction_kind !== "VALUE_CORRECTION" ||
      row.reverses_correction_id !== null ||
      effect < 0n
    )
      invalidFinancial();
  } else {
    same(row.reverses_correction_id, original.id);
    if (
      row.correction_kind !== "CORRECTION_REVERSAL" ||
      effect !== -money(original.source_balance_effect_usd_cents, 1n, ceiling)
    )
      invalidFinancial();
  }
  const returned = [
    row.verified_return_amount_minor,
    row.verified_return_currency,
    row.verified_returned_at,
    row.return_method_reference,
  ];
  // Only the retained Reservation lifecycle path predates demonstrated-return evidence.
  if (refund.source_lifecycle_event_id !== null) {
    if (
      row.source_balance_effect_original_minor !== null ||
      returned.some((v) => v !== null)
    )
      invalidFinancial();
    return row;
  }
  const payoutAt = financialInstant(refund.processed_at);
  if (
    money(row.source_balance_effect_original_minor, -ceiling, ceiling) !==
      effect ||
    occurred <= payoutAt ||
    row.authorization_reference !==
      (original === null ? "refunds.correct" : "refunds.corrections.reverse")
  )
    invalidFinancial();
  if (original === null) {
    if (
      returned.some((v) => v === null) ||
      row.verified_return_currency !== "USD" ||
      money(row.verified_return_amount_minor, 1n, ceiling) !== effect
    )
      invalidFinancial();
    const returnedAt = financialInstant(row.verified_returned_at);
    if (returnedAt < payoutAt || returnedAt > occurred) invalidFinancial();
    label(row.return_method_reference);
  } else if (
    returned.some((v) => v !== null) ||
    occurred <= financialInstant(original.occurred_at)
  )
    invalidFinancial();
  return row;
}
function detail(
  item: FinancialObject,
  expectedKind: string | null,
  source: string,
  selected: FinancialObject | null,
  original: FinancialObject | null,
): void {
  if (expectedKind === null || item.kind !== expectedKind || selected === null)
    invalidFinancial();
  const row = financialObject(item.data);
  if (expectedKind === "INVOICE_LINE") {
    exactKeys(row, [
      "invoice_id",
      "category",
      "description",
      "original_amount_usd_cents",
      "adjusted_amount_usd_cents",
      "outstanding_usd_cents",
    ]);
    same(row.invoice_id, selected.id);
    label(row.category);
    label(row.description);
    money(row.original_amount_usd_cents);
    const adjusted = money(row.adjusted_amount_usd_cents);
    const outstanding = money(row.outstanding_usd_cents, 0n, adjusted);
    if (
      ["DRAFT", "VOID", "PAID"].includes(text(selected.status)) &&
      outstanding !== 0n
    )
      invalidFinancial();
  } else {
    const allocation = expectedKind === "ALLOCATION_LINE",
      parent = allocation ? "allocation_id" : "application_id",
      amountKey = allocation
        ? "posted_amount_usd_cents"
        : "applied_amount_usd_cents";
    exactKeys(row, [
      parent,
      "target_kind",
      "target_id",
      "category",
      "proposed_amount_usd_cents",
      amountKey,
      "attribution_basis",
      "current_outstanding_usd_cents",
    ]);
    same(row[parent], source);
    id(row.target_id);
    money(
      row[amountKey],
      1n,
      money(original?.amount_usd_cents, 1n, maximumEvent),
    );
    if (row.proposed_amount_usd_cents !== null)
      money(row.proposed_amount_usd_cents, 1n, maximumEvent);
    choice(row.attribution_basis, [
      "RENT_FIRST_PROPOSAL",
      "SERVICE_PROPOSAL",
      "CUSTOMER_DESIGNATED",
      "OTHER_CONFIRMED",
      "DIRECT_LATE_PAYMENT_CHARGE",
      ...(allocation ? ["THIRD_PARTY_DESIGNATED"] : ["PUT_BACK_BY_CORRECTION"]),
    ]);
    // A line and its payment carry the put-back label together or not at all (the database's
    // header and detail agreement, sub-slice 10e-3e).
    if (
      (row.attribution_basis === "PUT_BACK_BY_CORRECTION") !==
      (original?.within_invoice_basis === "PUT_BACK_BY_CORRECTION")
    )
      invalidFinancial();
    const current = money(row.current_outstanding_usd_cents);
    if (selected.kind === "INVOICE") {
      if (row.target_kind !== "INVOICE_LINE") invalidFinancial();
      label(row.category);
      if (current > money(selected.outstanding_usd_cents)) invalidFinancial();
    } else {
      if (
        row.target_kind !== "LATE_PAYMENT_CHARGE" ||
        row.category !== null ||
        current !== money(selected.remaining_balance_usd_cents)
      )
        invalidFinancial();
      same(row.target_id, selected.id);
    }
  }
}
export function validateFinancialActionContext(
  envelope: FinancialObject,
  input: FinancialObject,
  property: string,
  requestId: string,
): { limit: number; nextCursor: string | null } {
  const row = financialObject(envelope.data),
    context = financialObject(row.context);
  exactKeys(row, [
    "property_id",
    "purpose",
    "source_id",
    "refund_id",
    "requested_target_kind",
    "requested_target_id",
    "payment_resource",
    "context",
    "target",
    "revision",
    "items",
    "item_count",
  ]);
  const purpose = choice(input.purpose, FINANCIAL_ACTION_PURPOSES),
    source = id(input.source_id);
  same(row.property_id, property);
  same(row.source_id, source);
  if (
    row.purpose !== purpose ||
    row.refund_id !== (input.refund_id ?? null) ||
    row.requested_target_kind !== (input.target_kind ?? null) ||
    row.requested_target_id !== (input.target_id ?? null) ||
    !revisionPattern.test(text(row.revision))
  )
    invalidFinancial();
  const paymentResource =
    row.payment_resource === null
      ? null
      : financialObject(row.payment_resource);
  const payment =
    paymentResource === null ? null : financialObject(paymentResource.payment);
  if (payment !== null) {
    sourcePaymentFacts(paymentResource ?? invalidFinancial(), payment);
    validateFinancialReply(
      {
        data: paymentResource,
        meta: { property_id: property, request_id: requestId },
      },
      captureFinancialRequest({
        operation: "paymentGet",
        target: { id: id(payment.id) },
      }),
      property,
      requestId,
    );
    const position = financialObject(paymentResource?.position),
      dispositions = financialObject(position.dispositions);
    exactKeys(position, [
      "currency",
      "original_usd_cents",
      "available_usd_cents",
      "dispositions",
    ]);
    exactKeys(dispositions, [
      "allocation_usd_cents",
      "credit_usd_cents",
      "deposit_usd_cents",
      "refund_usd_cents",
    ]);
    const original = money(
        payment.usd_accounting_value_cents,
        1n,
        maximumEvent,
      ),
      available = money(position.available_usd_cents, 0n, original);
    const used = Object.values(dispositions).reduce<bigint>(
      (sum, value) => sum + money(value, 0n, original),
      0n,
    );
    if (
      position.currency !== "USD" ||
      money(position.original_usd_cents, 1n, maximumEvent) !== original ||
      used > original ||
      (payment.status === "REVERSED" && used !== 0n) ||
      available !== (payment.status === "REVERSED" ? 0n : original - used)
    )
      invalidFinancial();
    if (
      payment.received_currency === "USD" &&
      money(payment.received_amount_minor, 1n, maximumEvent) !== original
    )
      invalidFinancial();
    optionalId(payment.lease_id);
    optionalId(payment.identified_invoice_id);
    optionalId(payment.identified_late_payment_charge_id);
  } else if (!purpose.startsWith("refund_")) invalidFinancial();
  const creditRow = Object.hasOwn(context, "credit")
    ? credit(
        context.credit,
        property,
        paymentResource ?? invalidFinancial(),
        requestId,
      )
    : null;
  const selected = row.target === null ? null : target(row.target, property);
  const posting = purpose === "allocation" || purpose === "credit_application";
  const reversing =
    purpose === "allocation_reversal" ||
    purpose === "credit_application_reversal";
  if (posting) {
    if ((input.target_id !== undefined) !== (selected !== null))
      invalidFinancial();
    if (
      selected &&
      (selected.id !== input.target_id || selected.kind !== input.target_kind)
    )
      invalidFinancial();
  } else if (reversing ? selected === null : selected !== null)
    invalidFinancial();
  if (selected)
    targetScope(
      selected,
      payment ?? invalidFinancial(),
      creditRow ? financialObject(creditRow.credit).customer_id : null,
    );
  let original: FinancialObject | null = null;
  if (purpose === "allocation" || purpose === "credit_recognition") {
    exactKeys(
      context,
      purpose === "allocation" ? [] : ["applicable_obligations"],
    );
    same(payment?.id, source);
    if (
      purpose === "credit_recognition" &&
      typeof context.applicable_obligations !== "boolean"
    )
      invalidFinancial();
  } else if (purpose === "receipt_reprint") {
    exactKeys(context, ["receipt"]);
    const receipt = financialObject(context.receipt);
    exactKeys(receipt, [
      "id",
      "receipt_number",
      "payment_id",
      "payer_customer_id",
      "issued_at",
      "issued_by",
      "identity_snapshot",
    ]);
    same(receipt.id, source);
    same(receipt.payment_id, payment?.id);
    same(receipt.payer_customer_id, payment?.payer_customer_id);
    // DL-071 answer 10 (V1-059 part B): a Receipt has its Payment's number (RCP...); a
    // Receipt recorded before keeps its earlier R-<id> number.
    if (
      (receipt.receipt_number !== payment?.payment_number &&
        receipt.receipt_number !== `R-${source}`) ||
      financialInstant(receipt.issued_at) <
        financialInstant(payment?.confirmed_at)
    )
      invalidFinancial();
    same(receipt.issued_by, payment?.confirmed_by);
    const identity = financialObject(receipt.identity_snapshot);
    exactKeys(identity, ["payer_legal_name"]);
    label(identity.payer_legal_name);
    const linked = financialObject(paymentResource?.receipt);
    same(linked.id, source);
    if (linked.receipt_number !== receipt.receipt_number) invalidFinancial();
  } else if (
    purpose === "credit_application" ||
    purpose === "credit_reversal"
  ) {
    exactKeys(context, [
      "credit",
      ...(purpose === "credit_reversal" ? ["reversal"] : []),
    ]);
    same(financialObject(creditRow?.credit).id, source);
    if (purpose === "credit_reversal") {
      reversal(
        context.reversal,
        "customer_credit_id",
        source,
        "credits.reverse",
      );
      if (
        context.reversal !== null &&
        financialInstant(financialObject(context.reversal).occurred_at) <=
          financialInstant(financialObject(creditRow?.credit).recognized_at)
      )
        invalidFinancial();
      const creditPosition = financialObject(creditRow?.position);
      if (
        (context.reversal !== null) !==
        (money(creditPosition.reversed_usd_cents) ===
          money(creditPosition.recognized_usd_cents, 1n, maximumEvent))
      )
        invalidFinancial();
    }
  } else if (reversing) {
    const allocation = purpose === "allocation_reversal";
    exactKeys(context, [
      allocation ? "allocation" : "application",
      "reversal",
      ...(allocation ? [] : ["credit"]),
    ]);
    original = originalEvent(
      context[allocation ? "allocation" : "application"],
      allocation,
      source,
      payment ?? invalidFinancial(),
      creditRow,
      selected ?? invalidFinancial(),
    );
    reversal(
      context.reversal,
      allocation ? "payment_allocation_id" : "credit_application_id",
      source,
      allocation
        ? "payments.allocations.reverse"
        : "credits.applications.reverse",
    );
    if (
      context.reversal !== null &&
      financialInstant(financialObject(context.reversal).occurred_at) <=
        financialInstant(original[allocation ? "posted_at" : "occurred_at"])
    )
      invalidFinancial();
    const sourceCeiling = allocation
      ? payment?.usd_accounting_value_cents
      : financialObject(creditRow?.credit).recognized_usd_cents;
    const selectedAmount = money(
      original.amount_usd_cents,
      1n,
      money(sourceCeiling, 1n, maximumEvent),
    );
    if (context.reversal === null) {
      const activeAmount = allocation
        ? financialObject(
            financialObject(paymentResource?.position).dispositions,
          ).allocation_usd_cents
        : financialObject(creditRow?.position).applied_usd_cents;
      if (selectedAmount > money(activeAmount)) invalidFinancial();
    }
  } else {
    exactKeys(context, [
      "refund",
      "deposit_source",
      ...(creditRow ? ["credit"] : []),
      ...(purpose === "refund_correction_reversal"
        ? ["correction", "reversal"]
        : []),
    ]);
    const refund = refundSummary(
      context,
      property,
      purpose === "refund_return" ? source : id(input.refund_id),
      payment,
      creditRow,
      paymentResource,
    );
    if (purpose === "refund_correction_reversal") {
      const originalCorrection = correction(
        context.correction,
        refund,
        source,
        null,
      );
      if (context.reversal !== null)
        correction(
          context.reversal,
          refund,
          id(financialObject(context.reversal).id),
          originalCorrection,
        );
      else if (
        money(originalCorrection.source_balance_effect_usd_cents, 1n) >
        money(refund.refund_amount_minor, 1n) -
          money(financialObject(context.refund).net_refund_usd_cents)
      )
        invalidFinancial();
    }
  }
  const page = financialObject(envelope.page);
  exactKeys(page, ["limit", "next_cursor"]);
  const limit = Number(financialInteger(input.limit ?? 50, 1n, 100n));
  const itemCount = Number(financialInteger(row.item_count, 0n, 32767n));
  if (
    page.limit !== limit ||
    !Array.isArray(row.items) ||
    row.items.length > Math.min(limit, itemCount)
  )
    invalidFinancial();
  let previous =
    input.cursor === undefined ? null : financialActionCursor(input.cursor);
  if (previous && previous.revision !== row.revision) invalidFinancial();
  const expectedKind =
    purpose === "allocation_reversal"
      ? "ALLOCATION_LINE"
      : purpose === "credit_application_reversal"
        ? "CREDIT_APPLICATION_LINE"
        : posting && selected?.kind === "INVOICE"
          ? "INVOICE_LINE"
          : null;
  if (
    (expectedKind === null && itemCount !== 0) ||
    (expectedKind === "INVOICE_LINE" &&
      money(selected?.line_count, 0n, 32767n) !== BigInt(itemCount))
  )
    invalidFinancial();
  for (const raw of row.items) {
    const item = financialObject(raw);
    exactKeys(item, ["sequence", "id", "kind", "data"]);
    const sequence = Number(
        financialInteger(
          item.sequence,
          1n,
          purpose === "credit_application_reversal" ? 500n : 32767n,
        ),
      ),
      identity = id(item.id);
    if (
      previous &&
      (sequence < previous.sequence ||
        (sequence === previous.sequence && identity <= previous.id))
    )
      invalidFinancial();
    detail(item, expectedKind, source, selected, original);
    previous = { sequence, id: identity, revision: text(row.revision) };
  }
  const nextCursor = page.next_cursor === null ? null : text(page.next_cursor);
  if (nextCursor !== null) {
    financialActionCursor(nextCursor);
    if (
      row.items.length !== limit ||
      !previous ||
      nextCursor !==
        `${text(row.revision)}:${previous.sequence.toString()}:${previous.id}`
    )
      invalidFinancial();
  }
  return { limit, nextCursor };
}
