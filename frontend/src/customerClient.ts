export interface CustomerListItem {
  customer_id: string;
  legal_name: string;
  active: boolean;
  relationship_indicators: string[];
}

export interface CustomerHistoryEvent {
  event_id: string;
  occurred_at: string;
  actor_id: string;
  action: string;
  reason: string;
  previous_state: unknown;
  resulting_state: unknown;
  correlation_id: string;
  outcome: string;
}

export interface CustomerRelationships {
  reservations: unknown[];
  primary_tenant_leases: unknown[];
  signer_leases: unknown[];
  occupancies: unknown[];
  invoices: unknown[];
  payments: unknown[];
  customer_credit: unknown[];
  refunds: unknown[];
}

export interface CustomerDetail {
  customer_id: string;
  legal_name: string;
  phone_number: string | null;
  email_address: string | null;
  contact_address: string | null;
  memo: string | null;
  // DL-071 answer 11: required for new Customers; null only for Customers recorded before.
  id_document_number: string | null;
  version: number;
  active: boolean;
  deactivated_at: string | null;
  deactivation_reason: string | null;
  relationships: CustomerRelationships;
  audit_history: CustomerHistoryEvent[];
  audit_history_next_cursor: string | null;
  can_manage: boolean;
  can_deactivate: boolean;
  can_view_audit: boolean;
  audit_history_available: boolean;
}

export interface CustomerListPage {
  items: CustomerListItem[];
  next_cursor: string | null;
  can_manage: boolean;
}

export interface CustomerFinancialSummary {
  source_status: string;
  source_availability: {
    deposits: string;
    invoices: string;
    late_charges: string;
    payments: string;
    customer_credit: string;
  };
  currency_summaries: unknown[];
  deposit_liabilities: CustomerDepositLiability[];
  deposit_liabilities_page: { next_cursor: string | null; limit: number };
  deposit_aggregate: {
    count: number;
    required_usd_cents: number;
    received_usd_cents: number;
    held_refundable_usd_cents: number;
    outstanding_required_usd_cents: number;
  };
  customer_credit_is_separate_from_deposit: boolean;
}

export interface CustomerDepositLiability {
  deposit_id: string;
  deposit_type: "SECURITY" | "PET";
  reservation_id: string | null;
  lease_id: string | null;
  pet_approval_id: string | null;
  required_usd_cents: number;
  received_usd_cents: number;
  held_refundable_usd_cents: number;
  outstanding_required_usd_cents: number;
}

export interface CustomerCommandStatus {
  recorded: boolean;
  expired?: boolean;
  customer: CustomerDetail | null;
}

export interface CustomerSource {
  legal_name: string;
  phone_number?: string | null;
  email_address?: string | null;
  contact_address?: string | null;
  memo?: string | null;
  id_document_number?: string | null;
  confirmed_distinct?: boolean;
}

export interface CustomerApi {
  list: (
    propertyId: string,
    filters?: { query?: string; active?: boolean; cursor?: string },
  ) => Promise<CustomerListPage>;
  get: (customerId: string, historyCursor?: string) => Promise<CustomerDetail>;
  commandStatus: (
    propertyId: string,
    customerId: string,
    action: "create" | "update" | "deactivate",
    idempotencyKey: string,
  ) => Promise<CustomerCommandStatus>;
  create: (
    propertyId: string,
    customerId: string,
    source: CustomerSource,
    idempotencyKey: string,
  ) => Promise<CustomerDetail>;
  update: (
    current: CustomerDetail,
    source: Partial<CustomerSource>,
    idempotencyKey: string,
  ) => Promise<CustomerDetail>;
  deactivate: (
    current: CustomerDetail,
    reason: string,
    idempotencyKey: string,
  ) => Promise<CustomerDetail>;
  financialSummary: (
    customerId: string,
    depositCursor?: string,
  ) => Promise<CustomerFinancialSummary>;
}

export class CustomerUnavailableError extends Error {
  constructor() {
    super("Customer access is unavailable for this session.");
    this.name = "CustomerUnavailableError";
  }
}

export class CustomerConflictError extends Error {
  readonly candidates: CustomerListItem[];

  constructor(candidates: CustomerListItem[] = []) {
    super(
      "The Customer changed or may already exist. Review and retry explicitly.",
    );
    this.name = "CustomerConflictError";
    this.candidates = candidates;
  }
}

// DL-071 answer 11: another Customer has this ID number; staff must use that Customer.
export class CustomerIdNumberInUseError extends CustomerConflictError {
  constructor(existing: CustomerListItem[] = []) {
    super(existing);
    this.message =
      existing.length > 0
        ? `Another Customer (${existing[0]?.legal_name ?? ""}) already has this ID number or passport number. Use the existing Customer.`
        : "Another Customer already has this ID number or passport number. Use the existing Customer.";
    this.name = "CustomerIdNumberInUseError";
  }
}

export class CustomerRequestError extends Error {
  readonly fields: string[];
  readonly outcomeUnknown: boolean;
  readonly requestId: string | null;

  constructor(
    safeMessage = "The Customer request was not completed.",
    fields: string[] = [],
    requestId: string | null = null,
    outcomeUnknown = false,
  ) {
    super(safeMessage);
    this.name = "CustomerRequestError";
    this.fields = fields;
    this.requestId = requestId;
    this.outcomeUnknown = outcomeUnknown;
  }
}

export class CustomerIdempotencyReuseError extends CustomerRequestError {
  constructor(requestId: string | null = null) {
    super(
      "A prior Customer command exists under this command identity. Reconcile that exact command before retrying.",
      [],
      requestId,
      true,
    );
    this.name = "CustomerIdempotencyReuseError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function csrfToken(): string | null {
  const prefix = "__Host-prm_csrf=";
  const entry = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return entry === undefined
    ? null
    : decodeURIComponent(entry.slice(prefix.length));
}

async function request(
  path: string,
  init: RequestInit,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new CustomerRequestError(
      "The Customer request outcome is unknown.",
      [],
      null,
      init.method !== "GET",
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (response.ok && init.method !== "GET") {
      throw new CustomerRequestError(
        "The Customer request outcome is unknown.",
        [],
        response.headers.get("X-Request-ID"),
        true,
      );
    }
    payload = null;
  }
  if (
    response.status === 401 ||
    response.status === 403 ||
    (response.status === 404 && path.startsWith("/api/v1/customers/"))
  ) {
    throw new CustomerUnavailableError();
  }
  if (response.status === 409) {
    const error =
      isObject(payload) && isObject(payload.error) ? payload.error : null;
    const meta =
      isObject(payload) && isObject(payload.meta) ? payload.meta : null;
    if (error?.code === "IDEMPOTENCY_KEY_REUSED") {
      throw new CustomerIdempotencyReuseError(
        meta !== null && typeof meta.request_id === "string"
          ? meta.request_id
          : response.headers.get("X-Request-ID"),
      );
    }
    if (error?.code === "CUSTOMER_ID_NUMBER_IN_USE") {
      throw new CustomerIdNumberInUseError(
        isObject(error.existing_customer)
          ? [reuseCandidate(error.existing_customer)]
          : [],
      );
    }
    const candidates =
      error !== null && Array.isArray(error.reuse_candidates)
        ? error.reuse_candidates.map(reuseCandidate)
        : [];
    throw new CustomerConflictError(candidates);
  }
  if (response.status === 412) throw new CustomerConflictError();
  if (!response.ok) {
    const error =
      isObject(payload) && isObject(payload.error) ? payload.error : null;
    const meta =
      isObject(payload) && isObject(payload.meta) ? payload.meta : null;
    throw new CustomerRequestError(
      error !== null && typeof error.message === "string"
        ? error.message
        : undefined,
      error !== null && Array.isArray(error.fields)
        ? error.fields.filter(
            (field): field is string => typeof field === "string",
          )
        : [],
      meta !== null && typeof meta.request_id === "string"
        ? meta.request_id
        : null,
      init.method !== "GET" && response.status >= 500,
    );
  }
  if (!isObject(payload)) {
    throw new CustomerRequestError(
      init.method !== "GET"
        ? "The Customer request outcome is unknown."
        : undefined,
      [],
      response.headers.get("X-Request-ID"),
      init.method !== "GET",
    );
  }
  return payload;
}

function resourceData(
  envelope: Record<string, unknown>,
): Record<string, unknown> {
  if (!isObject(envelope.data)) throw new CustomerRequestError();
  return envelope.data;
}

function stringArray(value: unknown): string[] {
  if (
    !Array.isArray(value) ||
    !value.every((entry) => typeof entry === "string")
  ) {
    throw new CustomerRequestError();
  }
  return value;
}

function unknownArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new CustomerRequestError();
  return value;
}

function nullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value !== "string") throw new CustomerRequestError();
  return value;
}

function listItem(value: unknown): CustomerListItem {
  if (
    !isObject(value) ||
    typeof value.customer_id !== "string" ||
    typeof value.legal_name !== "string" ||
    typeof value.active !== "boolean"
  ) {
    throw new CustomerRequestError();
  }
  return {
    customer_id: value.customer_id,
    legal_name: value.legal_name,
    active: value.active,
    relationship_indicators: stringArray(value.relationship_indicators),
  };
}

function reuseCandidate(value: unknown): CustomerListItem {
  if (
    !isObject(value) ||
    typeof value.customer_id !== "string" ||
    typeof value.legal_name !== "string"
  ) {
    throw new CustomerRequestError();
  }
  return {
    customer_id: value.customer_id,
    legal_name: value.legal_name,
    active: true,
    relationship_indicators: [],
  };
}

function historyEvent(value: unknown): CustomerHistoryEvent {
  if (
    !isObject(value) ||
    typeof value.event_id !== "string" ||
    typeof value.occurred_at !== "string" ||
    typeof value.actor_id !== "string" ||
    typeof value.action !== "string" ||
    typeof value.reason !== "string" ||
    typeof value.correlation_id !== "string" ||
    typeof value.outcome !== "string"
  ) {
    throw new CustomerRequestError();
  }
  return {
    event_id: value.event_id,
    occurred_at: value.occurred_at,
    actor_id: value.actor_id,
    action: value.action,
    reason: value.reason,
    previous_state: value.previous_state ?? null,
    resulting_state: value.resulting_state ?? null,
    correlation_id: value.correlation_id,
    outcome: value.outcome,
  };
}

function relationships(value: unknown): CustomerRelationships {
  if (!isObject(value)) throw new CustomerRequestError();
  return {
    reservations: unknownArray(value.reservations),
    primary_tenant_leases: unknownArray(value.primary_tenant_leases),
    signer_leases: unknownArray(value.signer_leases),
    occupancies: unknownArray(value.occupancies),
    invoices: unknownArray(value.invoices),
    payments: unknownArray(value.payments),
    customer_credit: unknownArray(value.customer_credit),
    refunds: unknownArray(value.refunds),
  };
}

function detail(value: unknown): CustomerDetail {
  if (
    !isObject(value) ||
    typeof value.customer_id !== "string" ||
    typeof value.legal_name !== "string" ||
    typeof value.version !== "number" ||
    typeof value.active !== "boolean" ||
    typeof value.can_manage !== "boolean" ||
    typeof value.can_deactivate !== "boolean" ||
    typeof value.can_view_audit !== "boolean" ||
    typeof value.audit_history_available !== "boolean" ||
    (value.audit_history_next_cursor !== null &&
      typeof value.audit_history_next_cursor !== "string") ||
    !Array.isArray(value.audit_history)
  ) {
    throw new CustomerRequestError();
  }
  return {
    customer_id: value.customer_id,
    legal_name: value.legal_name,
    phone_number: nullableString(value.phone_number),
    email_address: nullableString(value.email_address),
    contact_address: nullableString(value.contact_address),
    memo: nullableString(value.memo),
    id_document_number: nullableString(value.id_document_number),
    version: value.version,
    active: value.active,
    deactivated_at: nullableString(value.deactivated_at),
    deactivation_reason: nullableString(value.deactivation_reason),
    relationships: relationships(value.relationships),
    audit_history: value.audit_history.map(historyEvent),
    audit_history_next_cursor: value.audit_history_next_cursor,
    can_manage: value.can_manage,
    can_deactivate: value.can_deactivate,
    can_view_audit: value.can_view_audit,
    audit_history_available: value.audit_history_available,
  };
}

function mutationHeaders(
  idempotencyKey: string,
  version?: number,
): HeadersInit {
  const token = csrfToken();
  if (token === null || token.length === 0) throw new CustomerRequestError();
  return {
    "Content-Type": "application/json",
    "X-CSRF-Token": token,
    "Idempotency-Key": idempotencyKey,
    ...(version === undefined ? {} : { "If-Match": `"${String(version)}"` }),
  };
}

async function list(
  propertyId: string,
  filters: { query?: string; active?: boolean; cursor?: string } = {},
): Promise<CustomerListPage> {
  const query = new URLSearchParams();
  if (filters.query !== undefined) query.set("query", filters.query);
  if (filters.active !== undefined) query.set("active", String(filters.active));
  if (filters.cursor !== undefined) query.set("cursor", filters.cursor);
  const suffix = query.size === 0 ? "" : `?${query.toString()}`;
  const envelope = await request(
    `/api/v1/properties/${encodeURIComponent(propertyId)}/customers${suffix}`,
    { method: "GET" },
  );
  const data = envelope.data;
  const page = envelope.page;
  const meta = envelope.meta;
  if (
    !Array.isArray(data) ||
    !isObject(page) ||
    !isObject(meta) ||
    (page.next_cursor !== null && typeof page.next_cursor !== "string") ||
    typeof meta.can_manage !== "boolean"
  ) {
    throw new CustomerRequestError();
  }
  return {
    items: data.map(listItem),
    next_cursor: page.next_cursor,
    can_manage: meta.can_manage,
  };
}

async function get(
  customerId: string,
  historyCursor?: string,
): Promise<CustomerDetail> {
  const query =
    historyCursor === undefined
      ? ""
      : `?history_cursor=${encodeURIComponent(historyCursor)}`;
  return detail(
    resourceData(
      await request(
        `/api/v1/customers/${encodeURIComponent(customerId)}${query}`,
        {
          method: "GET",
        },
      ),
    ),
  );
}

async function commandStatus(
  propertyId: string,
  customerId: string,
  action: "create" | "update" | "deactivate",
  idempotencyKey: string,
): Promise<CustomerCommandStatus> {
  const query = new URLSearchParams({
    action,
    idempotency_key: idempotencyKey,
  });
  const data = resourceData(
    await request(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/customers/${encodeURIComponent(customerId)}/command-status?${query.toString()}`,
      { method: "GET" },
    ),
  );
  if (typeof data.recorded !== "boolean") throw new CustomerRequestError();
  if (typeof data.expired !== "boolean") throw new CustomerRequestError();
  if (!data.recorded) {
    if (data.customer !== null) throw new CustomerRequestError();
    return { recorded: false, expired: data.expired, customer: null };
  }
  return {
    recorded: true,
    expired: data.expired,
    customer: detail(data.customer),
  };
}

async function create(
  propertyId: string,
  customerId: string,
  source: CustomerSource,
  idempotencyKey: string,
): Promise<CustomerDetail> {
  const envelope = await request(
    `/api/v1/properties/${encodeURIComponent(propertyId)}/customers`,
    {
      method: "POST",
      headers: mutationHeaders(idempotencyKey),
      body: JSON.stringify({ customer_id: customerId, ...source }),
    },
  );
  try {
    return detail(resourceData(envelope));
  } catch (error: unknown) {
    if (error instanceof CustomerRequestError) {
      throw new CustomerRequestError(
        "The Customer creation outcome is unknown.",
        error.fields,
        error.requestId,
        true,
      );
    }
    throw error;
  }
}

async function update(
  current: CustomerDetail,
  source: Partial<CustomerSource>,
  idempotencyKey: string,
): Promise<CustomerDetail> {
  const envelope = await request(
    `/api/v1/customers/${encodeURIComponent(current.customer_id)}`,
    {
      method: "PATCH",
      headers: mutationHeaders(idempotencyKey, current.version),
      body: JSON.stringify(source),
    },
  );
  try {
    return detail(resourceData(envelope));
  } catch (error: unknown) {
    if (error instanceof CustomerRequestError) {
      throw new CustomerRequestError(
        "The Customer update outcome is unknown.",
        error.fields,
        error.requestId,
        true,
      );
    }
    throw error;
  }
}

async function deactivate(
  current: CustomerDetail,
  reason: string,
  idempotencyKey: string,
): Promise<CustomerDetail> {
  const envelope = await request(
    `/api/v1/customers/${encodeURIComponent(current.customer_id)}`,
    {
      method: "PATCH",
      headers: mutationHeaders(idempotencyKey, current.version),
      body: JSON.stringify({
        deactivate: true,
        deactivation_reason: reason,
      }),
    },
  );
  try {
    return detail(resourceData(envelope));
  } catch (error: unknown) {
    if (error instanceof CustomerRequestError) {
      throw new CustomerRequestError(
        "The Customer deactivation outcome is unknown.",
        error.fields,
        error.requestId,
        true,
      );
    }
    throw error;
  }
}

async function financialSummary(
  customerId: string,
  depositCursor?: string,
): Promise<CustomerFinancialSummary> {
  const parameters = new URLSearchParams({ deposit_limit: "50" });
  if (depositCursor !== undefined)
    parameters.set("deposit_cursor", depositCursor);
  const value = resourceData(
    await request(
      `/api/v1/customers/${encodeURIComponent(customerId)}/financial-summary?${parameters.toString()}`,
      {
        method: "GET",
      },
    ),
  );
  if (
    typeof value.source_status !== "string" ||
    typeof value.source_availability !== "object" ||
    value.source_availability === null ||
    typeof value.deposit_liabilities_page !== "object" ||
    value.deposit_liabilities_page === null ||
    typeof value.deposit_aggregate !== "object" ||
    value.deposit_aggregate === null ||
    typeof value.customer_credit_is_separate_from_deposit !== "boolean"
  ) {
    throw new CustomerRequestError();
  }
  const availability = value.source_availability as Record<string, unknown>;
  if (
    typeof availability.deposits !== "string" ||
    typeof availability.invoices !== "string" ||
    typeof availability.late_charges !== "string" ||
    typeof availability.payments !== "string" ||
    typeof availability.customer_credit !== "string"
  )
    throw new CustomerRequestError();
  const page = value.deposit_liabilities_page as Record<string, unknown>;
  if (
    (page.next_cursor !== null && typeof page.next_cursor !== "string") ||
    !Number.isSafeInteger(page.limit)
  )
    throw new CustomerRequestError();
  const aggregate = value.deposit_aggregate as Record<string, unknown>;
  for (const field of [
    "count",
    "required_usd_cents",
    "received_usd_cents",
    "held_refundable_usd_cents",
    "outstanding_required_usd_cents",
  ]) {
    if (!Number.isSafeInteger(aggregate[field]))
      throw new CustomerRequestError();
  }
  const liabilities = unknownArray(value.deposit_liabilities).map((entry) => {
    if (typeof entry !== "object" || entry === null)
      throw new CustomerRequestError();
    const item = entry as Record<string, unknown>;
    if (
      typeof item.deposit_id !== "string" ||
      (item.deposit_type !== "SECURITY" && item.deposit_type !== "PET") ||
      !Number.isSafeInteger(item.required_usd_cents) ||
      !Number.isSafeInteger(item.received_usd_cents) ||
      !Number.isSafeInteger(item.held_refundable_usd_cents) ||
      !Number.isSafeInteger(item.outstanding_required_usd_cents)
    ) {
      throw new CustomerRequestError();
    }
    const optionalIdentity = (field: string): string | null => {
      const candidate = item[field];
      if (candidate !== null && typeof candidate !== "string")
        throw new CustomerRequestError();
      return candidate;
    };
    return {
      deposit_id: item.deposit_id,
      deposit_type: item.deposit_type,
      reservation_id: optionalIdentity("reservation_id"),
      lease_id: optionalIdentity("lease_id"),
      pet_approval_id: optionalIdentity("pet_approval_id"),
      required_usd_cents: item.required_usd_cents as number,
      received_usd_cents: item.received_usd_cents as number,
      held_refundable_usd_cents: item.held_refundable_usd_cents as number,
      outstanding_required_usd_cents:
        item.outstanding_required_usd_cents as number,
    } satisfies CustomerDepositLiability;
  });
  return {
    source_status: value.source_status,
    source_availability: {
      deposits: availability.deposits,
      invoices: availability.invoices,
      late_charges: availability.late_charges,
      payments: availability.payments,
      customer_credit: availability.customer_credit,
    },
    currency_summaries: unknownArray(value.currency_summaries),
    deposit_liabilities: liabilities,
    deposit_liabilities_page: {
      next_cursor:
        typeof page.next_cursor === "string" ? page.next_cursor : null,
      limit: page.limit as number,
    },
    deposit_aggregate: {
      count: aggregate.count as number,
      required_usd_cents: aggregate.required_usd_cents as number,
      received_usd_cents: aggregate.received_usd_cents as number,
      held_refundable_usd_cents: aggregate.held_refundable_usd_cents as number,
      outstanding_required_usd_cents:
        aggregate.outstanding_required_usd_cents as number,
    },
    customer_credit_is_separate_from_deposit:
      value.customer_credit_is_separate_from_deposit,
  };
}

export const customerApi: CustomerApi = {
  list,
  get,
  commandStatus,
  create,
  update,
  deactivate,
  financialSummary,
};
