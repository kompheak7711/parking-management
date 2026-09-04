export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };
export type Evidence = Record<string, JsonValue>;
export interface Money {
  currency: "USD";
  minor_units: number;
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
  due_date: string;
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
export interface InvoiceApi {
  list: (propertyId: string, filters?: InvoiceFilters) => Promise<InvoicePage>;
  get: (id: string) => Promise<InvoiceResource>;
  create: (
    propertyId: string,
    obligationId: string,
    key: string,
  ) => Promise<InvoiceResource>;
  correctDraft: (
    id: string,
    obligationId: string,
    reason: string,
    version: number,
    key: string,
  ) => Promise<InvoiceResource>;
  issue: (id: string, version: number, key: string) => Promise<InvoiceResource>;
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
}
export class InvoiceClientError extends Error {
  constructor(
    public readonly status: number | null,
    public readonly code: string,
    public readonly outcomeUnknown: boolean,
    public readonly currentVersion: number | null = null,
  ) {
    super(
      outcomeUnknown
        ? "Outcome not confirmed. Keep the same request and retry or reconcile before starting another command."
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
    value <= maximum
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
  return { currency: "USD", minor_units: integer(row.minor_units) };
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
  const cents = BigInt(money(value).minor_units);
  return (
    "USD " +
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
    due_date: text(row.due_date),
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
async function request<T>(
  path: string,
  decode: (body: Record<string, unknown>) => T,
  command?: {
    method?: "POST" | "PATCH";
    body: object;
    key: string;
    version?: number;
  },
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (command) {
    if (command.version !== undefined && command.version > 2_147_483_647)
      throw new InvoiceClientError(null, "INVALID_VERSION", false);
    if (!command.key)
      throw new InvoiceClientError(null, "IDEMPOTENCY_REQUIRED", false);
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = csrf();
    headers["Idempotency-Key"] = command.key;
    if (command.version !== undefined)
      headers["If-Match"] = '"' + String(integer(command.version, 1)) + '"';
  }
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "include",
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
    try {
      const error = object(object(await response.json()).error);
      if (typeof error.code === "string" && /^[A-Z_]{1,80}$/.test(error.code))
        code = error.code;
      if (
        typeof error.current_version === "number" &&
        Number.isSafeInteger(error.current_version)
      )
        currentVersion = error.current_version;
    } catch {
      /* Do not reflect arbitrary server content. */
    }
    throw new InvoiceClientError(
      response.status,
      code,
      Boolean(command) && response.status >= 500,
      currentVersion,
    );
  }
  try {
    return decode(object(await response.json()));
  } catch {
    throw new InvoiceClientError(
      response.status,
      "INVALID_RESPONSE",
      Boolean(command),
    );
  }
}
const encoded = encodeURIComponent;
const resource =
  <T>(decode: (value: unknown) => T) =>
  (body: Record<string, unknown>): T =>
    decode(body.data);
export const invoiceApi: InvoiceApi = {
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
        capabilities: array(object(body.meta).billing_capabilities).map(text),
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
  correctDraft: (id, obligation, reason, version, key) =>
    request("/api/v1/invoices/" + encoded(id), resource(invoice), {
      method: "PATCH",
      key,
      version,
      body: { authorized_nonrecurring_obligation_id: obligation, reason },
    }),
  issue: (id, version, key) =>
    request("/api/v1/invoices/" + encoded(id) + "/issue", resource(invoice), {
      key,
      version,
      body: {},
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
          amount: money(input.amount),
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
        body: { outcome, approved_amount: money(approvedAmount), reason },
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
        body:
          input.kind === "REDUCTION"
            ? {
                kind: input.kind,
                amount: money(input.amount),
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
  getRun: (id) => request("/api/v1/billing-runs/" + encoded(id), resource(run)),
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
  | { action: "issue"; propertyId: string; id: string; version: number }
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
    };
export interface PendingBillingCommand {
  key: string;
  command: BillingCommand;
}
export interface BillingJournal {
  load(actorId: string): Promise<PendingBillingCommand | null>;
  begin(actorId: string, pending: PendingBillingCommand): Promise<void>;
  clear(actorId: string, key: string): Promise<void>;
}
export function executeBilling(
  api: InvoiceApi,
  pending: PendingBillingCommand,
) {
  const c = pending.command,
    key = pending.key;
  switch (c.action) {
    case "create":
      return api.create(c.propertyId, c.obligationId, key);
    case "correct":
      return api.correctDraft(c.id, c.obligationId, c.reason, c.version, key);
    case "issue":
      return api.issue(c.id, c.version, key);
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
  }
}
interface SealedBilling {
  key: CryptoKey;
  iv: Uint8Array<ArrayBuffer>;
  ciphertext: ArrayBuffer;
  requestKey: string;
}
function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("property-rental.billing-intent.v1", 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore("pending");
    };
    request.onerror = () => {
      reject(new Error("Billing recovery storage unavailable."));
    };
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onblocked = () => {
      reject(new Error("Billing recovery storage blocked."));
    };
  });
}
async function journalTransaction<T>(
  actorId: string,
  mode: IDBTransactionMode,
  apply: (store: IDBObjectStore, stored: SealedBilling | undefined) => T,
): Promise<T> {
  const db = await database();
  try {
    return await new Promise<T>((resolve, reject) => {
      const tx = db.transaction("pending", mode),
        store = tx.objectStore("pending");
      const request = store.get(actorId);
      let result: T;
      tx.oncomplete = () => {
        resolve(result);
      };
      tx.onabort = tx.onerror = () => {
        reject(
          new Error(
            "Billing recovery storage failed. Commands remain blocked.",
          ),
        );
      };
      request.onsuccess = () => {
        try {
          result = apply(store, request.result as SealedBilling | undefined);
        } catch {
          tx.abort();
        }
      };
    });
  } finally {
    db.close();
  }
}
export const billingJournal: BillingJournal = {
  async load(actorId) {
    const sealed = await journalTransaction(
      actorId,
      "readonly",
      (_store, stored) => stored,
    );
    if (!sealed) return null;
    const plaintext = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: sealed.iv,
        additionalData: new TextEncoder().encode(actorId),
      },
      sealed.key,
      sealed.ciphertext,
    );
    const parsed = object(
      JSON.parse(new TextDecoder().decode(plaintext)) as unknown,
    );
    const command = object(parsed.command);
    if (
      parsed.key !== sealed.requestKey ||
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
      ].includes(text(command.action))
    ) {
      throw new Error(
        "Invalid billing recovery record. Commands remain blocked.",
      );
    }
    return parsed as unknown as PendingBillingCommand;
  },
  async begin(actorId, pending) {
    const key = await crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt(
      {
        name: "AES-GCM",
        iv,
        additionalData: new TextEncoder().encode(actorId),
      },
      key,
      new TextEncoder().encode(JSON.stringify(pending)),
    );
    await journalTransaction(actorId, "readwrite", (store, existing) => {
      if (existing)
        throw new Error("An earlier billing request must be reconciled.");
      store.put(
        {
          key,
          iv,
          ciphertext,
          requestKey: pending.key,
        } satisfies SealedBilling,
        actorId,
      );
    });
  },
  async clear(actorId, requestKey) {
    await journalTransaction(actorId, "readwrite", (store, existing) => {
      if (existing && existing.requestKey !== requestKey)
        throw new Error("A different request remains pending.");
      if (existing) store.delete(actorId);
    });
  },
};
