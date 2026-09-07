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
function credit(
  value: unknown,
  property: string,
  payment: FinancialObject,
  requestId: string,
): FinancialObject {
  const row = financialObject(value),
    item = financialObject(row.credit),
    position = financialObject(row.position);
  exactKeys(row, ["credit", "position", "source_payment", "exchange_rate"]);
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
  financialInstant(item.recognized_at);
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
    const outstanding = money(row.outstanding_usd_cents);
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
  ]);
  if (row.customer_designation_reference !== null)
    label(row.customer_designation_reference);
  if (row.proposal_generated_at !== null)
    financialInstant(row.proposal_generated_at);
  if (allocation) {
    same(row.payment_id, payment.id);
    same(row.target_customer_id, selected.customer_id);
    financialInstant(row.posted_at);
    id(row.posted_by);
    if (row.authorization_reference !== "payments.allocate") invalidFinancial();
    const basis = choice(row.between_invoice_basis, [
      "FIFO_PROPOSAL",
      "CUSTOMER_DESIGNATED",
      "THIRD_PARTY_DESIGNATED",
      "DIRECT_LATE_PAYMENT_CHARGE",
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
    financialInstant(row.occurred_at);
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
): FinancialObject {
  const summary = financialObject(context.refund),
    row = financialObject(summary.refund),
    source = financialObject(summary.source);
  exactKeys(summary, ["refund", "source", "net_refund_usd_cents"]);
  exactKeys(source, ["type", "id", "property_id"]);
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
    choice(deposit.deposit_type, ["RESERVATION", "PET"]);
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
  financialInstant(row.occurred_at);
  id(row.actor_id);
  if (
    row.source_balance_effect_original_minor !== null &&
    money(row.source_balance_effect_original_minor, -ceiling, ceiling) !==
      effect
  )
    invalidFinancial();
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
  if (returned.some((v) => v !== null)) {
    if (
      original !== null ||
      returned.some((v) => v === null) ||
      row.verified_return_currency !== "USD" ||
      money(row.verified_return_amount_minor, 1n, ceiling) !== effect
    )
      invalidFinancial();
    financialInstant(row.verified_returned_at);
    label(row.return_method_reference);
  } else if (original === null && refund.source_deposit_id === null)
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
      ...(allocation ? ["THIRD_PARTY_DESIGNATED"] : []),
    ]);
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
    ? credit(context.credit, property, payment ?? invalidFinancial(), requestId)
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
    same(receipt.id, source);
    same(receipt.payment_id, payment?.id);
    same(receipt.payer_customer_id, payment?.payer_customer_id);
    label(receipt.receipt_number);
    financialInstant(receipt.issued_at);
    id(receipt.issued_by);
    financialObject(receipt.identity_snapshot);
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
    if (purpose === "credit_reversal")
      reversal(
        context.reversal,
        "customer_credit_id",
        source,
        "credits.reverse",
      );
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
    }
  }
  const page = financialObject(envelope.page);
  exactKeys(page, ["limit", "next_cursor"]);
  const limit = Number(financialInteger(input.limit ?? 50, 1n, 100n));
  if (
    page.limit !== limit ||
    !Array.isArray(row.items) ||
    row.items.length > limit
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
