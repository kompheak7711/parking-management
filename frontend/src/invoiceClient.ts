import { parseFinancialJson, stringifyFinancialJson } from "./financialJson";
import {
  MAX_SEALED_INTENT_BYTES,
  sealedIntentStore,
} from "./sealedIntentStore";

export type JsonValue =
  | null
  | boolean
  | number
  | bigint
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type Evidence = Record<string, JsonValue>;
export interface Money {
  currency: "USD";
  minor_units: number | bigint;
}
export type InvoiceStatus =
  | "DRAFT"
  | "UNPAID"
  | "PARTIALLY_PAID"
  | "PAID"
  | "VOID";
export type InvoiceCategory =
  | "RENT"
  | "UTILITIES"
  | "SERVICE_CHARGES"
  | "DAMAGE_CHARGES"
  | "MISCELLANEOUS_CHARGES";
export interface InvoiceLine {
  id: string;
  sequence: number;
  description: string;
  category: InvoiceCategory;
  original_amount: Money;
  adjusted_amount: Money;
  outstanding_balance: Money;
  source: Evidence;
  calculation_evidence: Evidence;
  period: JsonValue;
}
export interface InvoiceResource {
  id: string;
  property_id: string;
  customer_id: string;
  lease_id: string | null;
  invoice_number: string;
  category: InvoiceCategory;
  status: InvoiceStatus;
  invoice_date: string;
  due_date: string | null;
  billing_period: JsonValue;
  version: number;
  original_total: Money;
  adjusted_total: Money;
  active_application_total: Money;
  outstanding_balance: Money;
  lines: InvoiceLine[];
  adjustments: Evidence[];
  void_event: JsonValue;
  evidence: Evidence;
}
export interface InvoicePage {
  items: InvoiceResource[];
  next_cursor: string | null;
  capabilities: string[];
}
export interface InvoiceFilters {
  status?: InvoiceStatus;
  category?: InvoiceCategory;
  customer_id?: string;
  lease_id?: string;
  cursor?: string;
  sort?: "invoice_date" | "-invoice_date";
}
export interface LatePaymentReview {
  invoice_id: string;
  property_id: string;
  overdue_balance: Money;
  default_rate_basis_points: number;
  calculated_default_amount: Money;
  eligible: boolean;
  blocking_conditions: string[];
  prior_decision: JsonValue;
}
export type DecisionOutcome = "CONFIRMED_DEFAULT" | "REDUCED" | "WAIVED";
export interface LatePaymentDecision {
  id: string;
  property_id: string;
  customer_id: string;
  source_invoice: Evidence;
  outcome: DecisionOutcome;
  approved_amount: Money;
  calculated_default_amount: Money;
  charge: { id: string } | null;
  evidence: Evidence;
}
export interface LatePaymentCharge {
  id: string;
  property_id: string;
  customer_id: string;
  original_amount: Money;
  adjusted_obligation: Money;
  remaining_balance: Money;
  corrections: Evidence[];
  evidence: Evidence;
  /** V1-056 slice 11g-3: false once the automatic pass runs (DL-087). */
  manual_corrections_open?: false;
}
export interface BillingRunInput {
  logical_run_key: string;
  business_date: string;
  period_start: string;
  period_end: string;
}
export interface BillingRun {
  id: string;
  property_id: string;
  run_kind: "RENT" | "UTILITIES";
  logical_run_key: string;
  business_date: string;
  status: string;
  period: { start: string; end: string };
  attempts: Evidence[];
  evidence: Evidence;
}
export interface AdjustmentInput {
  invoice_line_id: string;
  adjustment_type: "DEBIT" | "CREDIT";
  amount: Money;
  source_reference: string;
  reason: string;
}
export type ChargeCorrectionInput =
  | { kind: "REDUCTION"; amount: Money; reason: string }
  | { kind: "CHARGE_REVERSAL"; reason: string }
  | {
      kind: "REDUCTION_REVERSAL";
      reverses_correction_id: string;
      reason: string;
    };
export type OneTimeChargeCategory = "DAMAGE_CHARGES" | "MISCELLANEOUS_CHARGES";
export interface OneTimeChargeInput {
  charge_id: string;
  category: OneTimeChargeCategory;
  customer_id: string;
  lease_id: string | null;
  inspection_damage_finding_id: string | null;
  description: string;
  amount: Money;
  reason: string;
  evidence_reference: string;
}
/** The authorized source recorded for a one-time charge; a DRAFT Invoice is created from it. */
export interface OneTimeChargeRecord {
  obligation_id: string;
  category: OneTimeChargeCategory;
  customer_id: string;
  lease_id: string | null;
  inspection_damage_finding_id: string | null;
  description: string;
  amount: Money;
  reason: string;
  evidence_reference: string;
  evidence: Evidence;
}
/**
 * DL-103: one typed item of a Miscellaneous Invoice, its own approved charge. The server works
 * out the amount as the whole quantity times the unit price.
 */
export interface InvoiceItemInput {
  charge_id: string;
  description: string;
  quantity: number;
  unit_price: Money;
}
/** DL-103: one Invoice of 1 to 20 items with one reason and one approval for all of them. */
export interface ItemsInvoiceInput {
  customer_id: string;
  lease_id: string | null;
  reason: string;
  evidence_reference: string;
  items: InvoiceItemInput[];
}
/** DL-115 (I): a Services Invoice; each price comes from Settings › Regular services. */
export interface ServicesInvoiceInput {
  customer_id: string;
  lease_id: string | null;
  items: { charge_id: string; regular_service_id: string; quantity: number }[];
}
/** The evidence the server writes on every Services Invoice charge (migration 20270407_257). */
export const REGULAR_SERVICES_EVIDENCE = "Settings > Regular services price";
/** The Property setting for the Due Date of one-time charges, with its new version. */
export interface DueDaysSetting {
  property_id: string;
  one_time_charge_due_days: number;
  version: number;
}
/** An authorized Due Date chosen at issue; the reason is mandatory and recorded by the server. */
export interface IssueDueDateOverride {
  due_date: string;
  due_date_reason: string;
}
export interface InitialRentDueDateInput {
  override_id: string;
  due_date: string;
  reason: string;
}
/** The recorded override; the proposed date is the standard rule's date for comparison. */
export interface InitialRentDueDateOverride {
  override_id: string;
  property_id: string;
  lease_id: string;
  due_date: string;
  proposed_due_date: string;
  reason: string;
  evidence: Evidence;
}
export interface BillingTransmission {
  actorId: string;
  signal: AbortSignal;
}
export interface InvoiceApi {
  forActor?: (transmission: BillingTransmission) => InvoiceApi;
  capabilities?: (propertyId: string) => Promise<string[]>;
  list: (propertyId: string, filters?: InvoiceFilters) => Promise<InvoicePage>;
  get: (id: string) => Promise<InvoiceResource>;
  create: (
    propertyId: string,
    obligationId: string,
    key: string,
  ) => Promise<InvoiceResource>;
  /** DL-103: record every item's charge and the Draft in one request. */
  createWithItems: (
    propertyId: string,
    input: ItemsInvoiceInput,
    key: string,
  ) => Promise<InvoiceResource>;
  /** DL-115 (I): a Draft of Regular services at their Settings price, How many each. */
  createWithServices: (
    propertyId: string,
    input: ServicesInvoiceInput,
    key: string,
  ) => Promise<InvoiceResource>;
  /** DL-103: Edit items of a Draft made from typed items, with the reason for the change. */
  replaceItems: (
    id: string,
    input: ItemsInvoiceInput & { change_reason: string },
    version: number,
    key: string,
  ) => Promise<InvoiceResource>;
  correctDraft: (
    id: string,
    obligationId: string,
    reason: string,
    version: number,
    key: string,
  ) => Promise<InvoiceResource>;
  issue: (
    id: string,
    version: number,
    key: string,
    dueDate?: IssueDueDateOverride,
  ) => Promise<InvoiceResource>;
  adjust: (
    id: string,
    input: AdjustmentInput,
    version: number,
    key: string,
  ) => Promise<InvoiceResource>;
  void: (
    id: string,
    reason: string,
    version: number,
    key: string,
  ) => Promise<InvoiceResource>;
  lateReview: (id: string) => Promise<LatePaymentReview>;
  lateDecision: (id: string) => Promise<LatePaymentDecision>;
  decide: (
    id: string,
    outcome: DecisionOutcome,
    approvedAmount: Money,
    reason: string,
    key: string,
  ) => Promise<LatePaymentDecision>;
  charge: (id: string) => Promise<LatePaymentCharge>;
  correctCharge: (
    id: string,
    input: ChargeCorrectionInput,
    key: string,
  ) => Promise<LatePaymentCharge>;
  run: (
    propertyId: string,
    kind: "rent" | "utilities",
    input: BillingRunInput,
    key: string,
  ) => Promise<BillingRun>;
  getRun: (id: string) => Promise<BillingRun>;
  recordOneTimeCharge: (
    propertyId: string,
    input: OneTimeChargeInput,
    key: string,
  ) => Promise<OneTimeChargeRecord>;
  setInitialRentDueDate: (
    propertyId: string,
    leaseId: string,
    input: InitialRentDueDateInput,
    key: string,
  ) => Promise<InitialRentDueDateOverride>;
  setDueDays: (
    propertyId: string,
    days: number,
    reason: string,
    propertyVersion: number,
    key: string,
  ) => Promise<DueDaysSetting>;
}
export class InvoiceClientError extends Error {
  constructor(
    public readonly status: number | null,
    public readonly code: string,
    public readonly outcomeUnknown: boolean,
    public readonly currentVersion: number | null = null,
    public readonly fields: readonly string[] = [],
    public readonly requestId: string | null = null,
    public readonly currentDecision: LatePaymentDecision | null = null,
    public readonly currentCharge: LatePaymentCharge | null = null,
  ) {
    super(
      outcomeUnknown
        ? "Outcome not confirmed. Keep the same request and retry or reconcile before starting another command."
        : code === "INVOICE_LINE_FULLY_PAID"
          ? "This Invoice line is fully paid, so a debit Adjustment is not allowed. Bill the missed amount as a one-time charge instead."
          : status === 401
            ? "Sign in again to use billing."
            : status === 403 || status === 404
              ? "Billing resource unavailable or access denied."
              : status === 409 || status === 412
                ? "The resource changed or this action conflicts. Reload and review the current state."
                : "The billing request could not be completed.",
    );
    this.name = "InvoiceClientError";
  }
}
const maximum = 9_000_000_000_000_000;
function invalid(): never {
  throw new InvoiceClientError(null, "INVALID_RESPONSE", false);
}
function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  return typeof value === "string" ? value : invalid();
}
function nullableText(value: unknown): string | null {
  return value === null ? null : text(value);
}
function integer(value: unknown, minimum = 0): number {
  return typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= minimum &&
    value <= Number.MAX_SAFE_INTEGER
    ? value
    : invalid();
}
function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : invalid();
}
function choice<T extends string>(value: unknown, options: readonly T[]): T {
  return typeof value === "string" && options.includes(value as T)
    ? (value as T)
    : invalid();
}
function json(value: unknown): JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean")
    return value;
  if (typeof value === "bigint") return value;
  if (typeof value === "number")
    return Number.isFinite(value) ? value : invalid();
  if (Array.isArray(value)) return value.map(json);
  const result: Evidence = {};
  for (const [key, child] of Object.entries(object(value))) {
    Object.defineProperty(result, key, {
      value: json(child),
      enumerable: true,
    });
  }
  return result;
}
function evidence(value: unknown): Evidence {
  object(value);
  return json(value) as Evidence;
}
export function money(value: unknown): Money {
  const row = object(value);
  if (row.currency !== "USD") return invalid();
  const units = row.minor_units;
  if (
    typeof units !== "bigint" &&
    !(typeof units === "number" && Number.isSafeInteger(units))
  )
    return invalid();
  const exact = BigInt(units);
  if (exact < -(1n << 63n) || exact > (1n << 63n) - 1n) return invalid();
  return { currency: "USD", minor_units: units };
}
/** Command policy is narrower than server accounting totals. */
export function requestMoney(value: Money): {
  currency: "USD";
  minor_units: number;
} {
  const cents = BigInt(money(value).minor_units);
  if (cents < 0n || cents > BigInt(maximum)) return invalid();
  return { currency: "USD", minor_units: Number(cents) };
}
/** Parse decimal user input without floating-point multiplication or rounding. */
export function parseUsd(value: string): Money {
  if (!/^(0|[1-9][0-9]*)(\.[0-9]{1,2})?$/.test(value)) return invalid();
  const [whole = "", fraction = ""] = value.split(".");
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  if (cents > BigInt(maximum)) return invalid();
  return { currency: "USD", minor_units: Number(cents) };
}
export function formatUsd(value: Money): string {
  const signed = BigInt(money(value).minor_units);
  const cents = signed < 0n ? -signed : signed;
  return (
    "USD " +
    (signed < 0n ? "-" : "") +
    (cents / 100n).toString() +
    "." +
    (cents % 100n).toString().padStart(2, "0")
  );
}
const categories: readonly InvoiceCategory[] = [
  "RENT",
  "UTILITIES",
  "SERVICE_CHARGES",
  "DAMAGE_CHARGES",
  "MISCELLANEOUS_CHARGES",
];
function invoice(value: unknown): InvoiceResource {
  const row = object(value);
  return {
    id: text(row.id),
    property_id: text(row.property_id),
    customer_id: text(row.customer_id),
    lease_id: nullableText(row.lease_id),
    invoice_number: text(row.invoice_number),
    category: choice(row.category, categories),
    status: choice(row.status, [
      "DRAFT",
      "UNPAID",
      "PARTIALLY_PAID",
      "PAID",
      "VOID",
    ] as const),
    invoice_date: text(row.invoice_date),
    due_date: nullableText(row.due_date),
    version: integer(row.version, 1),
    billing_period: json(row.billing_period),
    original_total: money(row.original_total),
    adjusted_total: money(row.adjusted_total),
    active_application_total: money(row.active_application_total),
    outstanding_balance: money(row.outstanding_balance),
    lines: array(row.lines).map((value) => {
      const line = object(value);
      return {
        id: text(line.id),
        sequence: integer(line.sequence, 1),
        description: text(line.description),
        category: choice(line.category, categories),
        original_amount: money(line.original_amount),
        adjusted_amount: money(line.adjusted_amount),
        outstanding_balance: money(line.outstanding_balance),
        source: evidence(line.source),
        calculation_evidence: evidence(line.calculation_evidence),
        period: json(line.period),
      };
    }),
    adjustments: array(row.adjustments).map(evidence),
    void_event: json(row.void_event),
    evidence: evidence(row),
  };
}
function lateReview(value: unknown): LatePaymentReview {
  const row = object(value);
  if (
    typeof row.eligible !== "boolean" ||
    row.default_rate_basis_points !== 1000
  )
    return invalid();
  return {
    invoice_id: text(row.invoice_id),
    property_id: text(row.property_id),
    overdue_balance: money(row.overdue_balance),
    default_rate_basis_points: 1000,
    calculated_default_amount: money(row.calculated_default_amount),
    eligible: row.eligible,
    blocking_conditions: array(row.blocking_conditions).map(text),
    prior_decision: json(row.prior_decision),
  };
}
function decision(value: unknown): LatePaymentDecision {
  const row = object(value);
  return {
    id: text(row.id),
    property_id: text(row.property_id),
    customer_id: text(row.customer_id),
    source_invoice: evidence(row.source_invoice),
    outcome: choice(row.outcome, [
      "CONFIRMED_DEFAULT",
      "REDUCED",
      "WAIVED",
    ] as const),
    approved_amount: money(row.approved_amount),
    calculated_default_amount: money(row.calculated_default_amount),
    charge: row.charge === null ? null : { id: text(object(row.charge).id) },
    evidence: evidence(row),
  };
}
function charge(value: unknown): LatePaymentCharge {
  const row = object(value);
  return {
    id: text(row.id),
    property_id: text(row.property_id),
    customer_id: text(row.customer_id),
    original_amount: money(row.original_amount),
    adjusted_obligation: money(row.adjusted_obligation),
    remaining_balance: money(row.remaining_balance),
    corrections: array(row.corrections).map(evidence),
    evidence: evidence(row),
    ...(row.manual_corrections_open === false
      ? { manual_corrections_open: false as const }
      : {}),
  };
}
/** Only immutable reversal evidence proves this correction can never succeed. */
export function terminalChargeConflict(
  current: LatePaymentCharge,
  input: ChargeCorrectionInput,
): boolean {
  try {
    const reversed = current.corrections.some(
      (item) =>
        typeof item.id === "string" &&
        item.id.length > 0 &&
        item.kind === "CHARGE_REVERSAL" &&
        item.active === true &&
        BigInt(money(item.amount).minor_units) > 0n &&
        BigInt(money(item.resulting_obligation).minor_units) === 0n,
    );
    if (reversed)
      return (
        BigInt(current.adjusted_obligation.minor_units) === 0n &&
        BigInt(current.remaining_balance.minor_units) === 0n
      );
    if (input.kind !== "REDUCTION_REVERSAL") return false;
    const id = input.reverses_correction_id;
    return (
      current.corrections.some(
        (item) =>
          item.id === id &&
          item.kind === "REDUCTION" &&
          item.active === false &&
          BigInt(money(item.amount).minor_units) > 0n,
      ) &&
      current.corrections.some(
        (item) =>
          typeof item.id === "string" &&
          item.id.length > 0 &&
          item.kind === "REDUCTION_REVERSAL" &&
          item.reverses_correction_id === id &&
          BigInt(money(item.amount).minor_units) > 0n,
      )
    );
  } catch {
    return false;
  }
}
function oneTimeCharge(value: unknown): OneTimeChargeRecord {
  const row = object(value);
  return {
    obligation_id: text(row.obligation_id),
    category: choice(row.category, [
      "DAMAGE_CHARGES",
      "MISCELLANEOUS_CHARGES",
    ] as const),
    customer_id: text(row.customer_id),
    lease_id: nullableText(row.lease_id),
    inspection_damage_finding_id: nullableText(
      row.inspection_damage_finding_id,
    ),
    description: text(row.description),
    amount: {
      currency: "USD",
      minor_units: integer(row.amount_usd_cents, 1),
    },
    reason: text(row.reason),
    evidence_reference: text(row.evidence_reference),
    evidence: evidence(row),
  };
}
function dueDaysSetting(value: unknown): DueDaysSetting {
  const row = object(value);
  const days = integer(row.one_time_charge_due_days, 1);
  if (days > 90) return invalid();
  return {
    property_id: text(row.property_id),
    one_time_charge_due_days: days,
    version: integer(row.version, 1),
  };
}
function initialRentOverride(value: unknown): InitialRentDueDateOverride {
  const row = object(value);
  return {
    override_id: text(row.override_id),
    property_id: text(row.property_id),
    lease_id: text(row.lease_id),
    due_date: text(row.due_date),
    proposed_due_date: text(row.proposed_due_date),
    reason: text(row.reason),
    evidence: evidence(row),
  };
}
function run(value: unknown): BillingRun {
  const row = object(value),
    period = object(row.period);
  return {
    id: text(row.id),
    property_id: text(row.property_id),
    run_kind: choice(row.run_kind, ["RENT", "UTILITIES"] as const),
    logical_run_key: text(row.logical_run_key),
    business_date: text(row.business_date),
    status: text(row.status),
    period: { start: text(period.start), end: text(period.end) },
    attempts: array(row.attempts).map(evidence),
    evidence: evidence(row),
  };
}
function csrf(): string {
  const value = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith("__Host-prm_csrf="));
  if (!value) throw new InvoiceClientError(null, "CSRF_UNAVAILABLE", false);
  try {
    const token = decodeURIComponent(value.slice("__Host-prm_csrf=".length));
    if (token) return token;
  } catch {
    /* fail closed */
  }
  throw new InvoiceClientError(null, "CSRF_UNAVAILABLE", false);
}
/** JSON grammar is validated by the native parser. A second token stream keeps
 * integer lexemes exact; strings (including numeric-looking evidence) stay strings.
 * Non-integer numeric tokens in money are rejected, even if Number would round them.
 */
function losslessJson(raw: string): unknown {
  const shape: unknown = JSON.parse(raw);
  const lexemes: unknown = JSON.parse(
    raw.replace(
      /"(?:\\.|[^"\\])*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/g,
      (token) => (token.startsWith('"') ? token : JSON.stringify(token)),
    ),
  );
  function restore(value: unknown, token: unknown, key = ""): unknown {
    if (typeof value === "number") {
      const literal = text(token);
      if (!/^-?[0-9]+$/.test(literal))
        return key === "minor_units" ? literal : value;
      const exact = BigInt(literal);
      return exact >= BigInt(Number.MIN_SAFE_INTEGER) &&
        exact <= BigInt(Number.MAX_SAFE_INTEGER)
        ? Number(exact)
        : exact;
    }
    if (Array.isArray(value))
      return value.map((child, index) => restore(child, array(token)[index]));
    if (value !== null && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value).map(([key, child]) => [
          key,
          restore(child, object(token)[key], key),
        ]),
      );
    }
    return value;
  }
  return restore(shape, lexemes);
}
const fieldNames = new Set([
  "authorized_nonrecurring_obligation_id",
  "reason",
  "invoice_line_id",
  "adjustment_type",
  "amount",
  "amount.minor_units",
  "amount.currency",
  "source_reference",
  "outcome",
  "approved_amount",
  "approved_amount.minor_units",
  "approved_amount.currency",
  "kind",
  "reverses_correction_id",
  "logical_run_key",
  "business_date",
  "period_start",
  "period_end",
  "charge_id",
  "category",
  "customer_id",
  "lease_id",
  "inspection_damage_finding_id",
  "description",
  "amount_usd_cents",
  "evidence_reference",
  "days",
  "due_date",
  "due_date_reason",
]);
function safeFields(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [
    ...new Set(
      value.slice(0, 50).flatMap((field: unknown) => {
        if (typeof field !== "string" || field.length > 100) return [];
        const name = field.replace(/^body\./, "");
        return fieldNames.has(name) ? [name] : [];
      }),
    ),
  ];
}
function safeRequestId(value: unknown): string | null {
  return typeof value === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)
    ? value
    : null;
}
async function transport<T>(
  path: string,
  decode: (body: Record<string, unknown>) => T,
  command?: {
    method?: "POST" | "PATCH" | "PUT";
    body: object;
    key: string;
    version?: number;
    decisionInvoiceId?: string;
    chargeCorrection?: { id: string; input: ChargeCorrectionInput };
    /** V1-058 R5c: a POST that saves nothing (the riel preview) sends no key. */
    preview?: boolean;
  },
  transmission?: BillingTransmission,
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (command) {
    if (command.version !== undefined && command.version > 2_147_483_647)
      throw new InvoiceClientError(null, "INVALID_VERSION", false);
    if (!command.key && command.preview !== true)
      throw new InvoiceClientError(null, "IDEMPOTENCY_REQUIRED", false);
    if (transmission) {
      if (!transmission.actorId || transmission.signal.aborted)
        throw new InvoiceClientError(null, "WORKSPACE_INVALIDATED", false);
      headers["X-Billing-Actor-ID"] = transmission.actorId;
    }
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = csrf();
    if (command.preview !== true) headers["Idempotency-Key"] = command.key;
    if (command.version !== undefined)
      headers["If-Match"] = '"' + String(integer(command.version, 1)) + '"';
  }
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "include",
      signal: transmission?.signal,
      method: command?.method ?? (command ? "POST" : "GET"),
      headers,
      ...(command ? { body: JSON.stringify(command.body) } : {}),
    });
  } catch {
    throw new InvoiceClientError(null, "NETWORK", Boolean(command));
  }
  if (!response.ok) {
    let code = "REQUEST_FAILED",
      currentVersion: number | null = null;
    let fields: string[] = [];
    let requestId: string | null = null;
    let currentDecision: LatePaymentDecision | null = null;
    let currentCharge: LatePaymentCharge | null = null;
    try {
      const envelope = object(losslessJson(await response.text()));
      const error = object(envelope.error);
      fields = safeFields(error.fields);
      requestId =
        envelope.meta !== null && typeof envelope.meta === "object"
          ? safeRequestId((envelope.meta as Record<string, unknown>).request_id)
          : null;
      if (typeof error.code === "string" && /^[A-Z_]{1,80}$/.test(error.code))
        code = error.code;
      if (
        typeof error.current_version === "number" &&
        Number.isSafeInteger(error.current_version) &&
        error.current_version >= 1 &&
        error.current_version <= 2_147_483_647
      )
        currentVersion = error.current_version;
      if (
        response.status === 409 &&
        code === "CONFLICT" &&
        command?.decisionInvoiceId
      ) {
        // Only this command's authorized, final decision can retire its rejection.
        // A review snapshot or malformed/foreign state leaves recovery gated.
        const current = decision(error.current_state);
        if (current.source_invoice.id === command.decisionInvoiceId)
          currentDecision = current;
      }
      if (
        response.status === 409 &&
        code === "CONFLICT" &&
        command?.chargeCorrection
      ) {
        const current = charge(error.current_state);
        if (
          current.id === command.chargeCorrection.id &&
          terminalChargeConflict(current, command.chargeCorrection.input)
        )
          currentCharge = current;
      }
    } catch {
      /* Do not reflect arbitrary server content. */
    }
    throw new InvoiceClientError(
      response.status,
      code,
      Boolean(command) && command?.preview !== true && response.status >= 500,
      currentVersion,
      fields,
      requestId,
      currentDecision,
      currentCharge,
    );
  }
  try {
    return decode(object(losslessJson(await response.text())));
  } catch {
    throw new InvoiceClientError(
      response.status,
      "INVALID_RESPONSE",
      Boolean(command),
    );
  }
}
// V1-058 R5c: the Payments screens use the same request rules (CSRF, key, safe errors).
export { transport as billingTransport };
const encoded = encodeURIComponent;
/** The body of both item requests: the unit price is sent as whole US cents. */
function itemsBody(input: ItemsInvoiceInput) {
  return {
    customer_id: input.customer_id,
    lease_id: input.lease_id,
    reason: input.reason,
    evidence_reference: input.evidence_reference,
    items: input.items.map((item) => ({
      charge_id: item.charge_id,
      description: item.description,
      quantity: item.quantity,
      unit_price_usd_cents: requestMoney(item.unit_price).minor_units,
    })),
  };
}
const resource =
  <T>(decode: (value: unknown) => T) =>
  (body: Record<string, unknown>): T =>
    decode(body.data);
function createInvoiceApi(transmission?: BillingTransmission): InvoiceApi {
  function request<T>(
    path: string,
    decode: (body: Record<string, unknown>) => T,
    command?: {
      method?: "POST" | "PATCH" | "PUT";
      body: object;
      key: string;
      version?: number;
      decisionInvoiceId?: string;
      chargeCorrection?: { id: string; input: ChargeCorrectionInput };
    },
  ) {
    return transport(path, decode, command, transmission);
  }
  return {
    forActor: createInvoiceApi,
    capabilities: (propertyId) =>
      request(
        "/api/v1/properties/" + encoded(propertyId) + "/billing-capabilities",
        (body) => {
          const data = object(body.data);
          if (data.property_id !== propertyId) return invalid();
          return array(data.billing_capabilities).map(text);
        },
      ),
    list: (propertyId, filters = {}) => {
      const query = new URLSearchParams({
        limit: "50",
        sort: filters.sort ?? "-invoice_date",
      });
      for (const key of [
        "status",
        "category",
        "customer_id",
        "lease_id",
        "cursor",
      ] as const) {
        if (filters[key]) query.set(key, filters[key]);
      }
      return request(
        "/api/v1/properties/" +
          encoded(propertyId) +
          "/invoices?" +
          query.toString(),
        (body) => ({
          items: array(body.data).map(invoice),
          next_cursor: nullableText(object(body.page).next_cursor),
          capabilities:
            object(body.meta).billing_capabilities === undefined
              ? []
              : array(object(body.meta).billing_capabilities).map(text),
        }),
      );
    },
    get: (id) => request("/api/v1/invoices/" + encoded(id), resource(invoice)),
    create: (id, obligation, key) =>
      request(
        "/api/v1/properties/" + encoded(id) + "/invoices",
        resource(invoice),
        { key, body: { authorized_nonrecurring_obligation_id: obligation } },
      ),
    createWithItems: (id, input, key) =>
      request(
        "/api/v1/properties/" + encoded(id) + "/invoices/drafts",
        resource(invoice),
        { key, body: itemsBody(input) },
      ),
    createWithServices: (id, input, key) =>
      request(
        "/api/v1/properties/" + encoded(id) + "/invoices/services-drafts",
        resource(invoice),
        { key, body: { ...input } },
      ),
    replaceItems: (id, input, version, key) =>
      request("/api/v1/invoices/" + encoded(id) + "/items", resource(invoice), {
        method: "PUT",
        key,
        version,
        body: { ...itemsBody(input), change_reason: input.change_reason },
      }),
    correctDraft: (id, obligation, reason, version, key) =>
      request("/api/v1/invoices/" + encoded(id), resource(invoice), {
        method: "PATCH",
        key,
        version,
        body: { authorized_nonrecurring_obligation_id: obligation, reason },
      }),
    issue: (id, version, key, dueDate) =>
      request("/api/v1/invoices/" + encoded(id) + "/issue", resource(invoice), {
        key,
        version,
        body: dueDate
          ? {
              due_date: dueDate.due_date,
              due_date_reason: dueDate.due_date_reason,
            }
          : {},
      }),
    adjust: (id, input, version, key) =>
      request(
        "/api/v1/invoices/" + encoded(id) + "/adjustments",
        resource(invoice),
        {
          key,
          version,
          body: {
            invoice_line_id: input.invoice_line_id,
            adjustment_type: input.adjustment_type,
            amount: requestMoney(input.amount),
            source_reference: input.source_reference,
            reason: input.reason,
          },
        },
      ),
    void: (id, reason, version, key) =>
      request("/api/v1/invoices/" + encoded(id) + "/void", resource(invoice), {
        key,
        version,
        body: { reason },
      }),
    lateReview: (id) =>
      request(
        "/api/v1/invoices/" + encoded(id) + "/late-payment-review",
        resource(lateReview),
      ),
    lateDecision: (id) =>
      request(
        "/api/v1/invoices/" + encoded(id) + "/late-payment-decision",
        resource(decision),
      ),
    decide: (id, outcome, approvedAmount, reason, key) =>
      request(
        "/api/v1/invoices/" + encoded(id) + "/late-payment-decision",
        resource(decision),
        {
          key,
          decisionInvoiceId: id,
          body: {
            outcome,
            approved_amount: requestMoney(approvedAmount),
            reason,
          },
        },
      ),
    charge: (id) =>
      request("/api/v1/late-payment-charges/" + encoded(id), resource(charge)),
    correctCharge: (id, input, key) =>
      request(
        "/api/v1/late-payment-charges/" + encoded(id) + "/corrections",
        resource(charge),
        {
          key,
          chargeCorrection: { id, input },
          body:
            input.kind === "REDUCTION"
              ? {
                  kind: input.kind,
                  amount: requestMoney(input.amount),
                  reason: input.reason,
                }
              : input.kind === "CHARGE_REVERSAL"
                ? { kind: input.kind, reason: input.reason }
                : {
                    kind: input.kind,
                    reverses_correction_id: input.reverses_correction_id,
                    reason: input.reason,
                  },
        },
      ),
    run: (id, kind, input, key) =>
      request(
        "/api/v1/properties/" + encoded(id) + "/billing-runs/" + kind,
        resource(run),
        {
          key,
          body: {
            logical_run_key: input.logical_run_key,
            business_date: input.business_date,
            period_start: input.period_start,
            period_end: input.period_end,
          },
        },
      ),
    getRun: (id) =>
      request("/api/v1/billing-runs/" + encoded(id), resource(run)),
    recordOneTimeCharge: (id, input, key) =>
      request(
        "/api/v1/properties/" + encoded(id) + "/one-time-charges",
        resource(oneTimeCharge),
        {
          key,
          body: {
            charge_id: input.charge_id,
            category: input.category,
            customer_id: input.customer_id,
            lease_id: input.lease_id,
            inspection_damage_finding_id: input.inspection_damage_finding_id,
            description: input.description,
            amount_usd_cents: requestMoney(input.amount).minor_units,
            reason: input.reason,
            evidence_reference: input.evidence_reference,
          },
        },
      ),
    setInitialRentDueDate: (id, leaseId, input, key) =>
      request(
        "/api/v1/properties/" +
          encoded(id) +
          "/leases/" +
          encoded(leaseId) +
          "/initial-rent-due-date",
        resource(initialRentOverride),
        {
          key,
          body: {
            override_id: input.override_id,
            due_date: input.due_date,
            reason: input.reason,
          },
        },
      ),
    setDueDays: (id, days, reason, propertyVersion, key) =>
      request(
        "/api/v1/properties/" + encoded(id) + "/one-time-charge-due-days",
        resource(dueDaysSetting),
        { key, version: propertyVersion, body: { days, reason } },
      ),
  };
}
export const invoiceApi = createInvoiceApi();

/** V1-058 R7b-4: the Settings Business tab reads the one-time charge Due Date days and changes
 * them with the Property version. */
export interface DueDaysApi {
  get: (propertyId: string) => Promise<DueDaysSetting>;
  set: InvoiceApi["setDueDays"];
}
export const dueDaysApi: DueDaysApi = {
  get: (propertyId) =>
    transport(
      "/api/v1/properties/" + encoded(propertyId) + "/one-time-charge-due-days",
      resource(dueDaysSetting),
      undefined,
    ),
  set: invoiceApi.setDueDays,
};

/** Serializable intent is sealed before sending and replayed unchanged after interruption. */
export type BillingCommand =
  | { action: "create"; propertyId: string; obligationId: string }
  | {
      action: "correct";
      propertyId: string;
      id: string;
      obligationId: string;
      reason: string;
      version: number;
    }
  | {
      action: "issue";
      propertyId: string;
      id: string;
      version: number;
      dueDate?: IssueDueDateOverride;
    }
  | {
      action: "adjust";
      propertyId: string;
      id: string;
      input: AdjustmentInput;
      version: number;
    }
  | {
      action: "void";
      propertyId: string;
      id: string;
      reason: string;
      version: number;
    }
  | {
      action: "decide";
      propertyId: string;
      id: string;
      outcome: DecisionOutcome;
      amount: Money;
      reason: string;
    }
  | {
      action: "correctCharge";
      propertyId: string;
      id: string;
      input: ChargeCorrectionInput;
    }
  | {
      action: "run";
      propertyId: string;
      kind: "rent" | "utilities";
      input: BillingRunInput;
    }
  | { action: "oneTimeCharge"; propertyId: string; input: OneTimeChargeInput }
  | {
      action: "initialRentDueDate";
      propertyId: string;
      leaseId: string;
      input: InitialRentDueDateInput;
    }
  | {
      action: "dueDays";
      propertyId: string;
      days: number;
      reason: string;
      propertyVersion: number;
    };
export interface PendingBillingCommand {
  key: string;
  command: BillingCommand;
}
/** Reconstruct only a complete, original API invocation belonging to this actor. */
export function billingRunRetry(
  run: BillingRun,
  actorId: string,
  propertyId: string,
): PendingBillingCommand | null {
  const uuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const validId = (value: unknown): value is string =>
    typeof value === "string" &&
    uuid.test(value) &&
    value !== "00000000-0000-0000-0000-000000000000";
  const date = (value: string) =>
    /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString().slice(0, 10) === value;
  const e = run.evidence;
  if (
    !validId(e.idempotency_key) ||
    !validId(e.requester_actor_id) ||
    e.requester_actor_id !== actorId ||
    e.invocation_source !== "API" ||
    !validId(run.id) ||
    !validId(run.property_id) ||
    run.property_id !== propertyId ||
    !["RENT", "UTILITIES"].includes(run.run_kind) ||
    !run.logical_run_key ||
    run.logical_run_key.trim() !== run.logical_run_key ||
    run.logical_run_key.length > 200 ||
    !date(run.business_date) ||
    !date(run.period.start) ||
    !date(run.period.end) ||
    run.period.end < run.period.start ||
    Date.parse(run.period.end) - Date.parse(run.period.start) > 62 * 86400000
  )
    return null;
  return {
    key: e.idempotency_key,
    command: {
      action: "run",
      propertyId,
      kind: run.run_kind === "RENT" ? "rent" : "utilities",
      input: {
        logical_run_key: run.logical_run_key,
        business_date: run.business_date,
        period_start: run.period.start,
        period_end: run.period.end,
      },
    },
  };
}
export interface BillingJournal {
  load(actorId: string): Promise<PendingBillingCommand | null>;
  begin(actorId: string, pending: PendingBillingCommand): Promise<void>;
  clear(actorId: string, key: string): Promise<void>;
}
export function executeBilling(
  api: InvoiceApi,
  pending: PendingBillingCommand,
  transmission?: BillingTransmission,
) {
  if (transmission) {
    if (transmission.signal.aborted)
      throw new InvoiceClientError(null, "WORKSPACE_INVALIDATED", false);
    api = api.forActor?.(transmission) ?? api;
  }
  const c = pending.command,
    key = pending.key;
  switch (c.action) {
    case "create":
      return api.create(c.propertyId, c.obligationId, key);
    case "correct":
      return api.correctDraft(c.id, c.obligationId, c.reason, c.version, key);
    case "issue":
      return c.dueDate
        ? api.issue(c.id, c.version, key, c.dueDate)
        : api.issue(c.id, c.version, key);
    case "adjust":
      return api.adjust(c.id, c.input, c.version, key);
    case "void":
      return api.void(c.id, c.reason, c.version, key);
    case "decide":
      return api.decide(c.id, c.outcome, c.amount, c.reason, key);
    case "correctCharge":
      return api.correctCharge(c.id, c.input, key);
    case "run":
      return api.run(c.propertyId, c.kind, c.input, key);
    case "oneTimeCharge":
      return api.recordOneTimeCharge(c.propertyId, c.input, key);
    case "initialRentDueDate":
      return api.setInitialRentDueDate(c.propertyId, c.leaseId, c.input, key);
    case "dueDays":
      return api.setDueDays(
        c.propertyId,
        c.days,
        c.reason,
        c.propertyVersion,
        key,
      );
  }
}
export const billingJournal: BillingJournal = {
  async load(actorId) {
    const opened = await sealedIntentStore.read(actorId);
    if (!opened) return null;
    const parsed = object(
      parseFinancialJson(opened.plaintext, MAX_SEALED_INTENT_BYTES),
    );
    const command = object(parsed.command);
    if (
      parsed.key !== opened.requestKey ||
      typeof parsed.key !== "string" ||
      typeof command.propertyId !== "string" ||
      !command.propertyId ||
      ![
        "create",
        "correct",
        "issue",
        "adjust",
        "void",
        "decide",
        "correctCharge",
        "run",
        "oneTimeCharge",
        "dueDays",
        "initialRentDueDate",
      ].includes(text(command.action))
    ) {
      throw new Error(
        "Invalid billing recovery record. Commands remain blocked.",
      );
    }
    return parsed as unknown as PendingBillingCommand;
  },
  async begin(actorId, pending) {
    const requestKey = pending.key;
    const plaintext = stringifyFinancialJson(pending, MAX_SEALED_INTENT_BYTES);
    await sealedIntentStore.begin(actorId, { requestKey, plaintext });
  },
  clear: (actorId, requestKey) => sealedIntentStore.clear(actorId, requestKey),
};
