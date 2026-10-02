/** Client for the Lease-scoped Utility routes: baseline, final inputs, final and catch-up Invoice. */

export type EvidenceRecord = Record<string, unknown>;

export interface DueDateOverride {
  due_date: string;
  due_date_reason: string;
}

export interface BaselineInput {
  event_id: string;
  supersedes_event_id?: string;
  baseline_date: string;
  reason: string;
  evidence_reference: string;
  items: { meter_id: string; reading_id: string }[];
}

export interface FinalInputItem {
  meter_id: string;
  resolution: "READING" | "ESTIMATE" | "UNRESOLVED";
  reading_id?: string;
  estimate_id?: string;
  unresolved_reason?: string;
}

export interface FinalInputsInput {
  event_id: string;
  move_out_event_id: string;
  supersedes_event_id?: string;
  reason: string;
  authorization_reference: string;
  evidence_reference: string;
  items: FinalInputItem[];
}

export interface UtilityInvoiceInput extends Partial<DueDateOverride> {
  invoice_id: string;
}

export interface FinalInvoiceInput extends UtilityInvoiceInput {
  final_input_event_id: string;
}

export interface CatchUpInput extends UtilityInvoiceInput {
  consumption_period_id: string;
}

export interface UnbilledPeriod {
  period_id: string;
  unit_id: string;
  utility_type: string;
  start_date: string;
  end_date: string;
  consumption_quantity: string;
  lease_id: string | null;
  can_catch_up: boolean;
  gap_reason: "LATE_AFTER_SUCCEEDED_RUN" | "NOT_MOVED_IN";
}

export interface UnbilledPage {
  items: UnbilledPeriod[];
  limit: number;
  offset: number;
  total: number | null;
}

/** A refusal; `code` is a stable reason such as UTILITY_NOTHING_TO_BILL, never server text. */
export class UtilityLeaseError extends Error {
  constructor(
    readonly status: number | null,
    readonly code: string,
    readonly requestId: string | null = null,
  ) {
    super("The Utility request could not be completed.");
    this.name = "UtilityLeaseError";
  }
}

export interface UtilityLeaseApi {
  readBaseline: (
    propertyId: string,
    leaseId: string,
    offset?: number,
  ) => Promise<EvidenceRecord>;
  recordBaseline: (
    propertyId: string,
    leaseId: string,
    input: BaselineInput,
    idempotencyKey: string,
  ) => Promise<EvidenceRecord>;
  readFinalInputs: (
    propertyId: string,
    leaseId: string,
    offset?: number,
  ) => Promise<EvidenceRecord>;
  recordFinalInputs: (
    propertyId: string,
    leaseId: string,
    input: FinalInputsInput,
    idempotencyKey: string,
  ) => Promise<EvidenceRecord>;
  createFinalInvoice: (
    propertyId: string,
    leaseId: string,
    input: FinalInvoiceInput,
    idempotencyKey: string,
  ) => Promise<EvidenceRecord>;
  createCatchUpInvoice: (
    propertyId: string,
    leaseId: string,
    input: CatchUpInput,
    idempotencyKey: string,
  ) => Promise<EvidenceRecord>;
  listUnbilled: (propertyId: string, offset?: number) => Promise<UnbilledPage>;
}

function csrf(): string {
  const prefix = "__Host-prm_csrf=";
  const found = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (found === undefined)
    throw new UtilityLeaseError(null, "CSRF_UNAVAILABLE");
  return decodeURIComponent(found.slice(prefix.length));
}

function record(value: unknown): EvidenceRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    throw new UtilityLeaseError(null, "INVALID_RESPONSE");
  return value as EvidenceRecord;
}

async function call(
  path: string,
  init: { method: "GET" | "POST"; key?: string; body?: object },
): Promise<EvidenceRecord> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.method === "POST") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = csrf();
    headers["Idempotency-Key"] = init.key ?? "";
  }
  let response: Response;
  try {
    response = await fetch(path, {
      method: init.method,
      credentials: "include",
      headers,
      ...(init.body === undefined ? {} : { body: JSON.stringify(init.body) }),
    });
  } catch {
    throw new UtilityLeaseError(null, "NETWORK");
  }
  let envelope: EvidenceRecord;
  try {
    envelope = record(await response.json());
  } catch {
    if (response.ok) throw new UtilityLeaseError(null, "INVALID_RESPONSE");
    throw new UtilityLeaseError(response.status, "REQUEST_FAILED");
  }
  if (!response.ok) {
    const error = envelope.error;
    const code =
      typeof error === "object" &&
      error !== null &&
      typeof (error as EvidenceRecord).code === "string" &&
      /^[A-Z_]{1,80}$/.test((error as EvidenceRecord).code as string)
        ? ((error as EvidenceRecord).code as string)
        : "REQUEST_FAILED";
    const meta = envelope.meta;
    const requestId =
      typeof meta === "object" &&
      meta !== null &&
      typeof (meta as EvidenceRecord).request_id === "string"
        ? ((meta as EvidenceRecord).request_id as string)
        : null;
    throw new UtilityLeaseError(response.status, code, requestId);
  }
  return record(envelope.data);
}

const leasePath = (propertyId: string, leaseId: string, name: string) =>
  `/api/v1/properties/${encodeURIComponent(propertyId)}/leases/${encodeURIComponent(leaseId)}/${name}`;
const pageQuery = (offset: number) =>
  offset > 0 ? `?offset=${String(offset)}` : "";

/** A command reply must name the very event or Invoice that was sent. */
function named(
  data: EvidenceRecord,
  field: string,
  id: string,
): EvidenceRecord {
  if (data[field] !== id)
    throw new UtilityLeaseError(null, "RESOURCE_MISMATCH");
  return data;
}

function unbilled(value: unknown): UnbilledPeriod {
  const row = record(value);
  const text = (name: string): string => {
    const field = row[name];
    if (typeof field !== "string")
      throw new UtilityLeaseError(null, "INVALID_RESPONSE");
    return field;
  };
  const gap = text("gap_reason");
  if (gap !== "LATE_AFTER_SUCCEEDED_RUN" && gap !== "NOT_MOVED_IN")
    throw new UtilityLeaseError(null, "INVALID_RESPONSE");
  if (typeof row.can_catch_up !== "boolean")
    throw new UtilityLeaseError(null, "INVALID_RESPONSE");
  return {
    period_id: text("period_id"),
    unit_id: text("unit_id"),
    utility_type: text("utility_type"),
    start_date: text("start_date"),
    end_date: text("end_date"),
    consumption_quantity:
      typeof row.consumption_quantity === "string" ||
      typeof row.consumption_quantity === "number"
        ? String(row.consumption_quantity)
        : "",
    lease_id: typeof row.lease_id === "string" ? row.lease_id : null,
    can_catch_up: row.can_catch_up,
    gap_reason: gap,
  };
}

export const utilityLeaseApi: UtilityLeaseApi = {
  readBaseline: (propertyId, leaseId, offset = 0) =>
    call(
      leasePath(propertyId, leaseId, "utility-baseline") + pageQuery(offset),
      { method: "GET" },
    ),
  recordBaseline: async (propertyId, leaseId, input, key) =>
    named(
      await call(leasePath(propertyId, leaseId, "utility-baseline"), {
        method: "POST",
        key,
        body: input,
      }),
      "event_id",
      input.event_id,
    ),
  readFinalInputs: (propertyId, leaseId, offset = 0) =>
    call(
      leasePath(propertyId, leaseId, "move-out-final-utility-inputs") +
        pageQuery(offset),
      { method: "GET" },
    ),
  recordFinalInputs: async (propertyId, leaseId, input, key) =>
    named(
      await call(
        leasePath(propertyId, leaseId, "move-out-final-utility-inputs"),
        {
          method: "POST",
          key,
          body: input,
        },
      ),
      "event_id",
      input.event_id,
    ),
  createFinalInvoice: async (propertyId, leaseId, input, key) =>
    named(
      await call(leasePath(propertyId, leaseId, "final-utility-invoice"), {
        method: "POST",
        key,
        body: input,
      }),
      "invoice_id",
      input.invoice_id,
    ),
  createCatchUpInvoice: async (propertyId, leaseId, input, key) =>
    named(
      await call(leasePath(propertyId, leaseId, "utility-catch-up-invoice"), {
        method: "POST",
        key,
        body: input,
      }),
      "invoice_id",
      input.invoice_id,
    ),
  listUnbilled: async (propertyId, offset = 0) => {
    const data = await call(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/unbilled-utility-periods${pageQuery(offset)}`,
      { method: "GET" },
    );
    if (!Array.isArray(data.items))
      throw new UtilityLeaseError(null, "INVALID_RESPONSE");
    const limit = data.limit;
    const total = data.total;
    return {
      items: data.items.map(unbilled),
      limit: typeof limit === "number" ? limit : 50,
      offset: typeof data.offset === "number" ? data.offset : offset,
      total: typeof total === "number" ? total : null,
    };
  },
};

/** Plain-language text for each stable reason code; unknown codes stay generic. */
export function utilityReasonText(code: string): string {
  const reasons: Record<string, string> = {
    UTILITY_NOTHING_TO_BILL: "There is nothing to bill for this Lease.",
    UTILITY_LEASE_NOT_TERMINATED:
      "The Lease must be terminated before a final Utility Invoice.",
    UTILITY_NOT_MOVED_IN: "The Customer has not moved in.",
    UTILITY_UNRESOLVED_FINAL_INPUT:
      "A final input is still unresolved. Record a successor final input first.",
    UTILITY_START_READING_MISSING: "A starting Reading is missing for a Meter.",
    UTILITY_EARLIER_READING_NOT_FINALIZED:
      "An earlier period is not finalized yet.",
    UTILITY_PERIOD_ALREADY_INVOICED: "This period already has an Invoice line.",
    UTILITY_NOT_RESPONSIBLE:
      "The Customer was not responsible for this period.",
    UTILITY_PERIOD_NOT_SKIPPED:
      "This period was not skipped by a monthly run, so a catch-up is not allowed.",
    IDEMPOTENCY_KEY_REUSED:
      "This request key was already used for different input. Reload before retrying.",
    CONFLICT: "The records changed or conflict. Reload before retrying.",
    FORBIDDEN: "You are not authorized for this Utility action.",
    NOT_FOUND: "The Property, Lease or source was not found.",
    VALIDATION_ERROR: "Check the entered values.",
  };
  return reasons[code] ?? "The Utility request could not be completed.";
}
