import { validateDueConfirmation } from "./financialDueConfirmation";
import { duePreviewBody } from "./financialDuePreview";
import {
  ExactJsonNumber,
  parseFinancialJson,
  stringifyFinancialJson,
  type FinancialJson,
} from "./financialJson";

// Internal wrappers may quote/escape a full bounded wire body. Wire limits stay separate.
export const FINANCIAL_ENVELOPE_BYTES = 1_048_576;
export type FinancialObject = Record<string, FinancialJson>;
export class FinancialContractError extends Error {
  constructor() {
    super("Financial request or evidence is invalid.");
    this.name = "FinancialContractError";
  }
}
export function invalidFinancial(): never {
  throw new FinancialContractError();
}
export function financialObject(value: unknown): FinancialObject {
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    value instanceof ExactJsonNumber
  )
    return invalidFinancial();
  return value as FinancialObject;
}
export function exactKeys(
  row: FinancialObject,
  required: string[],
  optional: string[] = [],
): void {
  if (
    required.some((key) => !Object.hasOwn(row, key)) ||
    Object.keys(row).some(
      (key) => !required.includes(key) && !optional.includes(key),
    )
  )
    invalidFinancial();
}
export function financialId(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value) ||
    value === "00000000-0000-0000-0000-000000000000"
  )
    return invalidFinancial();
  return value.toLowerCase();
}
export function financialInteger(
  value: unknown,
  min = 0n,
  max = 9_223_372_036_854_775_807n,
): number | bigint {
  if (
    !(
      typeof value === "bigint" ||
      (typeof value === "number" &&
        Number.isSafeInteger(value) &&
        !Object.is(value, -0))
    )
  )
    return invalidFinancial();
  if (BigInt(value) < min || BigInt(value) > max) return invalidFinancial();
  return value;
}
const maxAmount = 9_000_000_000_000_000n;
const positive = (value: unknown) => financialInteger(value, 1n, maxAmount);
// Python str.strip whitespace, including U+001C..001F and excluding U+FEFF.
const boundarySpace = new Set([
  9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, 8192, 8193, 8194, 8195,
  8196, 8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287, 12288,
]);
function text(value: unknown, max: number, rejectNul = false): void {
  if (
    typeof value !== "string" ||
    !value ||
    Array.from(value).length > max ||
    boundarySpace.has(value.charCodeAt(0)) ||
    boundarySpace.has(value.charCodeAt(value.length - 1)) ||
    (rejectNul && value.includes("\0"))
  )
    invalidFinancial();
}
function choice(value: unknown, choices: readonly string[]): string {
  if (typeof value !== "string" || !choices.includes(value))
    return invalidFinancial();
  return value;
}
function instant(value: unknown): void {
  if (typeof value !== "string") return invalidFinancial();
  const match =
    /^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$/.exec(
      value,
    );
  if (!match) return invalidFinancial();
  const [year = 0, month = 0, day = 0, hour = 99, minute = 99, second = 99] =
    match.slice(1).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > (days[month - 1] ?? 0) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  )
    invalidFinancial();
}
export function financialInstant(value: unknown): bigint {
  instant(value);
  if (typeof value !== "string") return invalidFinancial();
  const milliseconds = Date.parse(value);
  if (!Number.isSafeInteger(milliseconds)) return invalidFinancial();
  const fraction = /\.([0-9]{1,6})(?:Z|[+-])/.exec(value)?.[1] ?? "";
  return (
    BigInt(milliseconds) * 1000n + BigInt(fraction.padEnd(6, "0").slice(3))
  );
}
function rate(value: unknown): void {
  if (
    typeof value !== "string" ||
    value.length > 21 ||
    !/^(?:0|[1-9][0-9]{0,13})(?:\.[0-9]{1,6})?$/.test(value)
  )
    invalidFinancial();
}
function optional(
  row: FinancialObject,
  key: string,
  check: (value: FinancialJson) => unknown,
): void {
  if (row[key] !== undefined && row[key] !== null) check(row[key]);
}
function amount(value: unknown, currency: string): void {
  const row = financialObject(value);
  exactKeys(row, ["currency", "minor_units"]);
  if (row.currency !== currency) invalidFinancial();
  positive(row.minor_units);
}
function payment(row: FinancialObject): void {
  const common = [
    "payer_customer_id",
    "payment_method_id",
    "received_at",
    "evidence_reference",
    "amount",
  ];
  const extras = [
    "payment_scope_kind",
    "lease_id",
    "identified_invoice_id",
    "identified_late_payment_charge_id",
    "payer_intent_memo",
    "channel_transaction_reference",
  ];
  const currency = financialObject(row.amount).currency;
  choice(currency, ["USD", "KHR"]);
  exactKeys(
    row,
    [...common, ...(currency === "KHR" ? ["usd_accounting_amount"] : [])],
    [
      ...extras,
      ...(currency === "KHR" ? ["manual_reference", "channel_evidence"] : []),
    ],
  );
  financialId(row.payer_customer_id);
  financialId(row.payment_method_id);
  instant(row.received_at);
  text(row.evidence_reference, 500, true);
  amount(row.amount, currency as string);
  if (row.payment_scope_kind !== undefined)
    choice(row.payment_scope_kind, [
      "NORMAL_CUSTOMER",
      "THIRD_PARTY_IDENTIFIED",
    ]);
  for (const key of [
    "lease_id",
    "identified_invoice_id",
    "identified_late_payment_charge_id",
  ])
    optional(row, key, financialId);
  optional(row, "payer_intent_memo", (value) => {
    text(value, 2000, true);
  });
  optional(row, "channel_transaction_reference", (value) => {
    text(value, 500, true);
  });
  if (currency === "KHR") {
    amount(row.usd_accounting_amount, "USD");
    optional(row, "manual_reference", (value) => {
      const manual = financialObject(value);
      exactKeys(manual, [
        "reference_rate_khr_per_usd",
        "source_reference",
        "applicable_at",
        "fallback_reason",
      ]);
      rate(manual.reference_rate_khr_per_usd);
      instant(manual.applicable_at);
      text(manual.source_reference, 500, true);
      text(manual.fallback_reason, 500, true);
    });
    optional(row, "channel_evidence", (value) => {
      const channel = financialObject(value);
      exactKeys(
        channel,
        ["transaction_reference", "confirmed_at"],
        [
          "actual_currency",
          "actual_amount_minor",
          "actual_usd_value_cents",
          "actual_rate_khr_per_usd",
        ],
      );
      text(channel.transaction_reference, 500, true);
      instant(channel.confirmed_at);
      optional(channel, "actual_currency", (value) => choice(value, ["KHR"]));
      optional(channel, "actual_amount_minor", positive);
      optional(channel, "actual_usd_value_cents", positive);
      optional(channel, "actual_rate_khr_per_usd", rate);
    });
  }
}
function intent(value: unknown, credit: boolean): void {
  const row = financialObject(value);
  stringifyFinancialJson(row, 250_000);
  const stack: { value: FinancialJson; depth: number; key: string }[] = [
    { value: row, depth: 0, key: "" },
  ];
  while (stack.length) {
    const current = stack.pop();
    if (!current) return invalidFinancial();
    if (credit && current.depth > 24) invalidFinancial();
    const item = current.value;
    if (item === null || typeof item === "string") continue;
    if (typeof item === "number" || typeof item === "bigint") {
      const limit =
        current.key === "outstanding_usd_cents"
          ? 9_223_372_036_854_775_807n
          : maxAmount;
      financialInteger(item, -limit, limit);
      continue;
    }
    if (typeof item === "boolean" || item instanceof ExactJsonNumber)
      invalidFinancial();
    if (Array.isArray(item)) {
      if (
        (current.key === "details" || current.key === "targets") &&
        item.length > 500
      )
        invalidFinancial();
      for (const child of item)
        stack.push({ value: child, depth: current.depth + 1, key: "" });
    } else
      for (const [key, child] of Object.entries(financialObject(item)))
        stack.push({ value: child, depth: current.depth + 1, key });
  }
  choice(row.mode, ["PROPOSAL", "DESIGNATED", "DIRECT_CHARGE"]);
  if (row.mode === "PROPOSAL") {
    exactKeys(row, ["mode", "proposal"]);
    const proposal = financialObject(row.proposal);
    if (credit) {
      financialId(proposal.invoice_id);
      positive(proposal.amount_usd_cents);
    }
  } else if (row.mode === "DIRECT_CHARGE") {
    exactKeys(row, ["mode", "late_payment_charge_id", "amount_usd_cents"]);
    financialId(row.late_payment_charge_id);
    positive(row.amount_usd_cents);
  } else if (!credit) {
    exactKeys(row, ["mode", "targets", "designation_reference"]);
    text(row.designation_reference, 500);
    if (
      !Array.isArray(row.targets) ||
      row.targets.length < 1 ||
      row.targets.length > 500
    )
      invalidFinancial();
  } else {
    const invoice = Object.hasOwn(row, "invoice_id");
    const versioned = invoice && Object.hasOwn(row, "invoice_version");
    const target = invoice ? "invoice_id" : "late_payment_charge_id";
    exactKeys(row, [
      "mode",
      target,
      "amount_usd_cents",
      "designation_reference",
      ...(invoice ? ["details"] : []),
      ...(versioned ? ["invoice_version"] : []),
    ]);
    financialId(row[target]);
    positive(row.amount_usd_cents);
    text(row.designation_reference, 500, true);
    if (invoice) {
      if (versioned) {
        validateDueConfirmation(
          row.details,
          row.amount_usd_cents,
          row.invoice_version,
        );
        return;
      }
      if (
        !Array.isArray(row.details) ||
        row.details.length < 1 ||
        row.details.length > 500
      )
        return invalidFinancial();
      for (const value of row.details) {
        const detail = financialObject(value);
        exactKeys(detail, ["invoice_line_id", "amount_usd_cents"]);
        financialId(detail.invoice_line_id);
        positive(detail.amount_usd_cents);
      }
    }
  }
}

export function financialCalendarDate(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value))
    return invalidFinancial();
  instant(`${value}T00:00:00Z`);
  return value;
}
export function financialText(value: unknown, maximum: number): string {
  text(value, maximum, true);
  return value as string;
}
// Relative routes are generated only from this finite registry and validated IDs.
export const FINANCIAL_OPERATIONS = {
  leaseWarningRecord: ["POST", "/leases/:id/violation-warnings", 201],
  rentNonpaymentOpen: ["POST", "/leases/:id/rent-nonpayment-cases", 201],
  rentNonpaymentEvent: ["POST", "/rent-nonpayment-cases/:id/events", 201],
  paymentList: ["GET", "/properties/:propertyId/payments", 200],
  paymentGet: ["GET", "/payments/:id", 200],
  paymentRecord: ["POST", "/properties/:propertyId/payments", 201],
  allocationProposal: ["GET", "/payments/:id/allocation-proposal", 200],
  allocationPreview: ["POST", "/payments/:id/allocation-preview", 200],
  allocationList: ["GET", "/payments/:id/allocations", 200],
  allocationPost: ["POST", "/payments/:id/allocations", 201],
  allocationReverse: ["POST", "/payment-allocations/:id/reverse", 200],
  paymentReverse: ["POST", "/payments/:id/reverse", 200],
  paymentReceipt: ["GET", "/payments/:id/receipt", 200],
  receiptGet: ["GET", "/receipts/:id", 200],
  receiptReprint: ["POST", "/receipts/:id/reprints", 200],
  creditList: ["GET", "/customers/:id/credits", 200],
  creditGet: ["GET", "/customer-credits/:id", 200],
  creditLedger: ["GET", "/customer-credits/:id/ledger", 200],
  creditRecognize: ["POST", "/payments/:id/credit-recognitions", 201],
  creditReverse: ["POST", "/customer-credits/:id/reverse", 200],
  creditProposal: ["GET", "/customer-credits/:id/application-proposal", 200],
  creditPreview: ["POST", "/customer-credits/:id/application-preview", 200],
  creditApply: ["POST", "/customer-credits/:id/applications", 201],
  creditApplication: ["GET", "/credit-applications/:id", 200],
  creditApplicationReverse: ["POST", "/credit-applications/:id/reverse", 200],
  refundList: ["GET", "/properties/:propertyId/refunds", 200],
  refundGet: ["GET", "/refunds/:id", 200],
  refundSource: ["GET", "/refund-sources/:sourceType/:id", 200],
  refundCreate: ["POST", "/refunds", 201],
  refundReturn: ["POST", "/refunds/:id/verified-returns", 200],
  refundReturnReverse: [
    "POST",
    "/refunds/:id/verified-returns/:correctionId/reverse",
    200,
  ],
} as const;
export type FinancialOperation = keyof typeof FINANCIAL_OPERATIONS;
export type FinancialPreviewOperation = "allocationPreview" | "creditPreview";
export type FinancialCommandOperation = {
  [K in FinancialOperation]: K extends FinancialPreviewOperation
    ? never
    : (typeof FINANCIAL_OPERATIONS)[K][0] extends "POST"
      ? K
      : never;
}[FinancialOperation];
export type EnforcementCommandOperation =
  | "leaseWarningRecord"
  | "rentNonpaymentOpen"
  | "rentNonpaymentEvent";
export function isEnforcementCommand(
  operation: FinancialOperation,
): operation is EnforcementCommandOperation {
  return (
    operation === "leaseWarningRecord" ||
    operation === "rentNonpaymentOpen" ||
    operation === "rentNonpaymentEvent"
  );
}
type Parameters<P extends string> =
  P extends `${string}/:${infer K}/${infer Rest}`
    ? K | Parameters<`/${Rest}`>
    : P extends `${string}/:${infer K}`
      ? K
      : never;
export type FinancialRequest = {
  [K in FinancialOperation]: {
    operation: K;
    target: Record<
      Exclude<Parameters<(typeof FINANCIAL_OPERATIONS)[K][1]>, "propertyId">,
      string
    >;
  } & (K extends FinancialCommandOperation | FinancialPreviewOperation
    ? { body: FinancialObject }
    : { query?: FinancialObject });
}[FinancialOperation];
export interface CapturedFinancialRequest {
  operation: FinancialOperation;
  target: Readonly<Record<string, string>>;
  query: Readonly<FinancialObject>;
  wireBody: string | null;
}
export function commandBody(
  operation: FinancialCommandOperation,
  raw: string,
): FinancialObject {
  const row = financialObject(parseFinancialJson(raw));
  const pending: FinancialJson[] = [row];
  while (pending.length) {
    const value = pending.pop();
    if (typeof value === "string" && value.includes("\0")) invalidFinancial();
    if (Array.isArray(value)) {
      for (const child of value) pending.push(child);
    } else if (value !== null && typeof value === "object") {
      for (const [key, child] of Object.entries(value)) {
        if (key.includes("\0")) invalidFinancial();
        pending.push(child as FinancialJson);
      }
    }
  }
  const reason = () => {
    text(row.reason, 1000);
  };
  switch (operation) {
    case "leaseWarningRecord":
      exactKeys(row, [
        "warning_sequence",
        "violation_date",
        "warning_date",
        "violation_description",
        "lease_provision",
        "communication_record",
        "reason",
      ]);
      financialInteger(row.warning_sequence, 1n, 32767n);
      financialCalendarDate(row.violation_date);
      financialCalendarDate(row.warning_date);
      for (const field of [
        "violation_description",
        "lease_provision",
        "communication_record",
      ])
        text(row[field], 2000, true);
      text(row.reason, 500, true);
      break;
    case "rentNonpaymentOpen":
      exactKeys(row, ["rent_invoice_line_id", "reason"]);
      financialId(row.rent_invoice_line_id);
      text(row.reason, 500, true);
      break;
    case "rentNonpaymentEvent":
      exactKeys(
        row,
        ["event_kind", "reason"],
        [
          "notice_document_reference",
          "communication_record",
          "authorization_reference",
        ],
      );
      choice(row.event_kind, [
        "TWENTY_DAY_WARNING",
        "THIRTY_DAY_SERIOUS_DEFAULT",
        "CURE",
        "AUTHORIZED_FOLLOW_UP",
      ]);
      text(row.reason, 500, true);
      for (const field of [
        "notice_document_reference",
        "communication_record",
        "authorization_reference",
      ])
        optional(row, field, (value) => {
          text(value, field === "communication_record" ? 2000 : 500, true);
        });
      if (
        (row.event_kind === "TWENTY_DAY_WARNING" &&
          row.notice_document_reference == null) ||
        (row.event_kind === "AUTHORIZED_FOLLOW_UP" &&
          row.authorization_reference == null)
      )
        invalidFinancial();
      break;
    case "paymentRecord":
      payment(row);
      break;
    case "allocationPost":
      exactKeys(row, ["intent"]);
      intent(row.intent, false);
      break;
    case "creditApply":
      exactKeys(row, ["currency", "intent"]);
      choice(row.currency, ["USD"]);
      intent(row.intent, true);
      break;
    case "paymentReverse":
      exactKeys(row, ["reason", "expected_status"]);
      reason();
      choice(row.expected_status, ["RECEIVED"]);
      break;
    case "allocationReverse":
    case "creditReverse":
    case "creditApplicationReverse":
      exactKeys(row, ["reason"]);
      reason();
      break;
    case "receiptReprint":
      exactKeys(row, ["reason"], ["delivery_reference"]);
      reason();
      optional(row, "delivery_reference", (value) => {
        if (
          typeof value !== "string" ||
          Array.from(value).length < 1 ||
          Array.from(value).length > 500
        )
          invalidFinancial();
      });
      break;
    case "creditRecognize":
      exactKeys(row, [
        "currency",
        "amount_usd_cents",
        "payer_authorization_reference",
        "reason",
      ]);
      choice(row.currency, ["USD"]);
      positive(row.amount_usd_cents);
      text(row.payer_authorization_reference, 500, true);
      reason();
      break;
    case "refundCreate": {
      exactKeys(
        row,
        ["currency", "source_type", "source_id", "amount_usd_cents", "reason"],
        ["pet_refund_review_id"],
      );
      choice(row.currency, ["USD"]);
      choice(row.source_type, ["PAYMENT", "CREDIT", "PET_DEPOSIT"]);
      financialId(row.source_id);
      positive(row.amount_usd_cents);
      reason();
      const review =
        row.pet_refund_review_id !== undefined &&
        row.pet_refund_review_id !== null;
      if ((row.source_type === "PET_DEPOSIT") !== review) invalidFinancial();
      if (review) financialId(row.pet_refund_review_id);
      break;
    }
    case "refundReturn":
      exactKeys(row, [
        "currency",
        "returned_amount_minor",
        "returned_at",
        "return_method_reference",
        "evidence_reference",
        "reason",
      ]);
      choice(row.currency, ["USD"]);
      positive(row.returned_amount_minor);
      instant(row.returned_at);
      text(row.return_method_reference, 500, true);
      text(row.evidence_reference, 500, true);
      reason();
      break;
    case "refundReturnReverse":
      exactKeys(row, ["evidence_reference", "reason"]);
      text(row.evidence_reference, 500, true);
      reason();
      break;
    default:
      invalidFinancial();
  }
  return row;
}
export function isFinancialPreview(
  operation: FinancialOperation,
): operation is FinancialPreviewOperation {
  return operation === "allocationPreview" || operation === "creditPreview";
}
export function isFinancialCommand(
  operation: FinancialOperation,
): operation is FinancialCommandOperation {
  return (
    FINANCIAL_OPERATIONS[operation][0] === "POST" &&
    !isFinancialPreview(operation)
  );
}
function queryFor(
  operation: FinancialOperation,
  query: FinancialObject,
  target: Record<string, string>,
): void {
  const paged = [
    "paymentList",
    "allocationList",
    "paymentReceipt",
    "receiptGet",
    "creditList",
    "creditLedger",
    "refundList",
    "refundGet",
  ].includes(operation);
  const extra: string[] =
    operation === "paymentList"
      ? ["customer_id", "status", "payment_method_id", "sort"]
      : operation === "allocationList"
        ? ["allocation_id"]
        : operation === "refundList"
          ? ["customer_id"]
          : operation === "creditProposal"
            ? ["invoice_id", "amount_usd_cents"]
            : operation === "refundSource"
              ? ["pet_refund_review_id"]
              : [];
  exactKeys(
    query,
    operation === "creditProposal"
      ? ["invoice_id", "amount_usd_cents"]
      : operation === "refundSource" && target.sourceType === "PET_DEPOSIT"
        ? ["pet_refund_review_id"]
        : [],
    [...(paged ? ["limit", "cursor"] : []), ...extra],
  );
  for (const [key, value] of Object.entries(query)) {
    if (key.endsWith("_id")) financialId(value);
    else if (key === "limit") financialInteger(value, 1n, 100n);
    else if (key === "amount_usd_cents") positive(value);
    else if (key === "status") choice(value, ["RECEIVED", "REVERSED"]);
    else if (key === "sort") choice(value, ["-payment_date"]);
    else if (key === "cursor") {
      const max =
        operation === "paymentList"
          ? 256
          : ["allocationList", "paymentReceipt", "receiptGet"].includes(
                operation,
              )
            ? 512
            : 1024;
      if (
        typeof value !== "string" ||
        !value ||
        value.length > max ||
        !/^[\x21-\x7e]+$/.test(value)
      )
        invalidFinancial();
    }
  }
  if (
    operation === "refundSource" &&
    target.sourceType !== "PET_DEPOSIT" &&
    Object.hasOwn(query, "pet_refund_review_id")
  )
    invalidFinancial();
}
/** Capture through the descriptor-safe exact serializer before inspecting caller data. */
export function captureFinancialRequest(
  input: FinancialRequest,
): CapturedFinancialRequest {
  return captureWireRequest(
    parseFinancialJson(
      stringifyFinancialJson(input, FINANCIAL_ENVELOPE_BYTES),
      FINANCIAL_ENVELOPE_BYTES,
    ),
  );
}
/** Restore a finite operation and original wire bytes; stored paths are never accepted. */
export function captureWireRequest(input: unknown): CapturedFinancialRequest {
  const row = financialObject(
    parseFinancialJson(
      stringifyFinancialJson(input, FINANCIAL_ENVELOPE_BYTES),
      FINANCIAL_ENVELOPE_BYTES,
    ),
  );
  if (
    typeof row.operation !== "string" ||
    !Object.hasOwn(FINANCIAL_OPERATIONS, row.operation)
  )
    return invalidFinancial();
  const operation = row.operation as FinancialOperation;
  const command = isFinancialCommand(operation);
  const carriesBody = command || isFinancialPreview(operation);
  exactKeys(
    row,
    [
      "operation",
      "target",
      ...(carriesBody
        ? [Object.hasOwn(row, "wireBody") ? "wireBody" : "body"]
        : []),
    ],
    carriesBody ? [] : ["query"],
  );
  const targetRow = financialObject(row.target);
  const parameters = [
    ...FINANCIAL_OPERATIONS[operation][1].matchAll(/:([a-zA-Z]+)/g),
  ]
    .map((match) => match[1] ?? invalidFinancial())
    .filter((key) => key !== "propertyId");
  exactKeys(targetRow, parameters);
  const target: Record<string, string> = {};
  for (const key of parameters) {
    if (key === "sourceType") {
      choice(targetRow[key], ["PAYMENT", "CREDIT", "PET_DEPOSIT"]);
      target[key] = targetRow[key] as string;
    } else target[key] = financialId(targetRow[key]);
  }
  const query = carriesBody ? {} : financialObject(row.query ?? {});
  queryFor(operation, query, target);
  const wireBody = carriesBody
    ? Object.hasOwn(row, "wireBody")
      ? row.wireBody
      : stringifyFinancialJson(row.body)
    : null;
  if (carriesBody) {
    if (typeof wireBody !== "string") return invalidFinancial();
    if (isFinancialCommand(operation)) commandBody(operation, wireBody);
    else
      duePreviewBody(
        operation === "allocationPreview" ? "PAYMENT" : "CREDIT",
        wireBody,
      );
  }
  return Object.freeze({
    operation,
    target: Object.freeze(target),
    query: Object.freeze(query),
    wireBody: wireBody as string | null,
  });
}
export function financialPath(
  request: CapturedFinancialRequest,
  propertyId: string,
): string {
  const path = FINANCIAL_OPERATIONS[request.operation][1].replace(
    /:([a-zA-Z]+)/g,
    (_, key: string) =>
      key === "propertyId"
        ? financialId(propertyId)
        : (request.target[key] ?? invalidFinancial()),
  );
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(request.query))
    query.set(
      key,
      key.endsWith("_id")
        ? financialId(value)
        : typeof value === "string" ||
            typeof value === "number" ||
            typeof value === "bigint"
          ? String(value)
          : invalidFinancial(),
    );
  return `/api/v1${path}${query.size ? `?${query}` : ""}`;
}
