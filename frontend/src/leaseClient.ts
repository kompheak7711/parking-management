export type LeaseStatus = "DRAFTED" | "SIGNED" | "CANCELLED" | "TERMINATED";
export type LeasePeriodFilter =
  | "current"
  | "future"
  | "historical"
  | "approaching_end";

export interface LeaseSignerResource {
  signer_id: string;
  customer_id: string;
  customer_name: string;
  is_primary_tenant: boolean;
  signed_at: string | null;
  added_at: string;
}

export interface OccupancyResource {
  occupancy_id: string;
  customer_id: string;
  customer_name: string;
  move_in_date: string;
  move_out_date: string | null;
  version: number;
}

export interface LeaseTimelineEvent {
  event_id: string;
  event_kind: string;
  occurred_at: string;
  reason: string;
  actor_id: string;
  source_reference: string | null;
  source_href: string | null;
}

export interface LeaseServiceTermResource {
  term_id: string;
  property_service_id: string;
  service_name: string;
  applicable_from: string;
  applicable_through: string | null;
  service_approval_period_id: string;
  terms_reference: string;
}

export interface LeaseResource {
  lease_id: string;
  property_id: string;
  unit_id: string;
  unit_number: string;
  primary_tenant_id: string;
  primary_tenant_name: string;
  status: LeaseStatus;
  start_date: string | null;
  end_date: string | null;
  monthly_rent_usd_cents: number | null;
  predecessor_lease_id: string | null;
  signed_at: string | null;
  terminated_at: string | null;
  actual_termination_date: string | null;
  version: number;
  created_at: string;
  pet_deposit_required: boolean;
  pet_description: string | null;
  security_deposit_id: string | null;
  planned_occupant_customer_ids: string[];
  service_terms: LeaseServiceTermResource[];
  signers: LeaseSignerResource[];
  occupancies: OccupancyResource[];
  timeline: LeaseTimelineEvent[];
  timeline_next_cursor: string | null;
  can_edit: boolean;
  can_manage_signers: boolean;
  can_sign: boolean;
  can_terminate: boolean;
  can_move_in: boolean;
  can_renew: boolean;
}

export interface LeaseFilters {
  status?: LeaseStatus;
  unit_id?: string;
  customer_id?: string;
  starts_on_or_after?: string;
  ends_on_or_before?: string;
  period?: LeasePeriodFilter;
  as_of?: string;
  approaching_days?: number;
  cursor?: string;
}

export interface LeasePage {
  items: LeaseResource[];
  next_cursor: string | null;
  can_create: boolean;
}

export interface LeaseTimelinePage {
  items: LeaseTimelineEvent[];
  next_cursor: string | null;
}

export interface LeaseDraftSource {
  lease_id: string;
  unit_id: string;
  primary_tenant_id: string;
  primary_signer_id: string;
  start_date: string | null;
  end_date: string | null;
  monthly_rent_usd_cents: number | null;
  predecessor_lease_id: string | null;
  additional_signers: { signer_id: string; customer_id: string }[];
  planned_occupant_customer_ids: string[];
  service_terms: {
    term_id: string;
    property_service_id: string;
    applicable_from: string;
    applicable_through: string | null;
    service_approval_period_id: string;
    terms_reference: string;
  }[];
  pet_term: {
    approval_id: string;
    approved_date: string;
    deposit_required_by_signed_terms: boolean;
    pet_description: string | null;
  } | null;
  security_deposit_id: string | null;
  event_id: string;
  reason: string;
}

export interface LeaseDraftUpdateSource {
  event_id: string;
  start_date: string | null;
  end_date: string | null;
  monthly_rent_usd_cents: number | null;
  reason: string;
}

export interface LeaseSignerSource {
  signer_id: string;
  customer_id: string;
  event_id: string;
  reason: string;
}

// No signing time: the server records the database's own time (Q-2026-10-14-110).
export interface LeaseSignatureSource {
  event_id: string;
  reason: string;
}

/** Signing may name the active Reservation it completes (DL-066). */
export interface LeaseSignSource extends LeaseSignatureSource {
  reservation_id?: string;
}

export interface LeaseRenewSource {
  lease_id: string;
  primary_signer_id: string;
  event_id: string;
  start_date: string;
  end_date: string;
  monthly_rent_usd_cents: number;
  reason: string;
}

export type TerminationBasis =
  | "VOLUNTARY_EARLY"
  | "CUSTOMER_VIOLATION"
  | "SIGNED_LEASE_OTHER"
  | "UNPAID_INITIAL_OBLIGATION";

/** Explicit signed-Lease authority; the server and database verify every basis rule. */
export interface TerminationContextSource {
  basis: TerminationBasis;
  signed_lease_provision: string;
  approved_grounds: string;
  management_authorization_reference: string;
  evidence_reference: string;
  notice_required: boolean;
  notice_id?: string;
  notice_period_ends_on?: string;
  notice_exception_reason?: string;
  warning_ids?: string[];
}

export interface LeaseTerminateSource {
  event_id: string;
  actual_termination_date: string;
  governing_event_reference: string;
  reason: string;
  context?: TerminationContextSource;
}

export interface NeverMovedInSource {
  resolution_id: string;
  unit_status: "VACANT" | "CLEANING";
  unit_status_reason?: string;
  reason: string;
}

export interface MovedInCreditSource {
  resolution_id: string;
  reason: string;
}

/** The recorded follow-up to a termination for an unpaid Initial obligation. */
export interface UnpaidInitialResolution {
  resolution_id: string;
  termination_event_id: string;
  lease_id: string;
  path: "NEVER_MOVED_IN" | "MOVED_IN";
  cause: string;
  resulting_unit_status: "VACANT" | "CLEANING" | null;
  deposit_disposition_id: string | null;
  invoice_void_event_id: string | null;
  adjustment_ids: string[];
  credit_usd_cents: number;
}

export interface MoveInSource {
  event_id: string;
  lease_id: string;
  expected_lease_version: number;
  expected_unit_version: number;
  actual_move_in_date: string;
  occupants: { occupancy_id: string; customer_id: string }[];
  reason: string;
}

/** Cancels a draft Lease only (BR-LEASE-004). */
export interface LeaseCancelSource {
  event_id: string;
  reason: string;
}

/** The physical move-in of a Lease whose signing completed its Reservation (DL-066). */
export interface LeaseMoveInSource {
  event_id: string;
  actual_move_in_date: string;
  occupants: { occupancy_id: string; customer_id: string }[];
  reason: string;
}

export interface MoveInResult {
  event_id: string;
  property_id: string;
  reservation_id: string;
  reservation_version: number;
  lease_id: string;
  lease_version: number;
  unit_id: string;
  unit_version: number;
  deposit_id: string;
  deposit_version: number;
  actual_move_in_date: string;
  occupancy_ids: string[];
}

export interface LeaseApi {
  list: (propertyId: string, filters?: LeaseFilters) => Promise<LeasePage>;
  get: (leaseId: string) => Promise<LeaseResource>;
  timeline: (leaseId: string, cursor?: string) => Promise<LeaseTimelinePage>;
  create: (
    propertyId: string,
    source: LeaseDraftSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  update: (
    lease: LeaseResource,
    source: LeaseDraftUpdateSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  addSigner: (
    lease: LeaseResource,
    source: LeaseSignerSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  recordSignature: (
    lease: LeaseResource,
    signerId: string,
    source: LeaseSignatureSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  sign: (
    lease: LeaseResource,
    source: LeaseSignSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  renew: (
    lease: LeaseResource,
    source: LeaseRenewSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  terminate: (
    lease: LeaseResource,
    source: LeaseTerminateSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  cancel: (
    lease: LeaseResource,
    source: LeaseCancelSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  recordMoveIn: (
    lease: LeaseResource,
    source: LeaseMoveInSource,
    idempotencyKey: string,
  ) => Promise<LeaseResource>;
  completeMoveIn: (
    reservationId: string,
    expectedReservationVersion: number,
    source: MoveInSource,
    idempotencyKey: string,
  ) => Promise<MoveInResult>;
  resolveNeverMovedIn: (
    propertyId: string,
    terminationEventId: string,
    source: NeverMovedInSource,
    idempotencyKey: string,
  ) => Promise<UnpaidInitialResolution>;
  creditMovedInInitialRent: (
    propertyId: string,
    terminationEventId: string,
    source: MovedInCreditSource,
    idempotencyKey: string,
  ) => Promise<UnpaidInitialResolution>;
}

export class LeaseUnavailableError extends Error {
  constructor() {
    super("Lease management is unavailable for this session.");
    this.name = "LeaseUnavailableError";
  }
}

export class LeaseConflictError extends Error {
  constructor() {
    super(
      "The Lease changed or conflicts with current Unit availability. Reload before retrying.",
    );
    this.name = "LeaseConflictError";
  }
}

export class LeaseRequestError extends Error {
  constructor() {
    super("The Lease request was not completed.");
    this.name = "LeaseRequestError";
  }
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (value === undefined) throw new LeaseRequestError();
  return decodeURIComponent(value.slice(prefix.length));
}

async function request(
  path: string,
  init: RequestInit,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "include", ...init });
  } catch {
    throw new LeaseUnavailableError();
  }
  if (response.status === 409 || response.status === 412)
    throw new LeaseConflictError();
  if (response.status === 503) throw new LeaseUnavailableError();
  if (!response.ok) throw new LeaseRequestError();
  const value: unknown = await response.json();
  if (typeof value !== "object" || value === null)
    throw new LeaseRequestError();
  return value as Record<string, unknown>;
}

function data(value: Record<string, unknown>): Record<string, unknown> {
  if (typeof value.data !== "object" || value.data === null)
    throw new LeaseRequestError();
  return value.data as Record<string, unknown>;
}

function lease(value: unknown): LeaseResource {
  if (typeof value !== "object" || value === null)
    throw new LeaseRequestError();
  return value as LeaseResource;
}

function nullableId(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") throw new LeaseRequestError();
  return value;
}

/** Accept only the follow-up record that answers this exact termination and resolution. */
function resolution(
  value: Record<string, unknown>,
  expected: { termination: string; resolution: string; path: string },
): UnpaidInitialResolution {
  const adjustments = value.adjustment_ids;
  const status = value.resulting_unit_status ?? null;
  if (
    value.termination_event_id !== expected.termination ||
    value.resolution_id !== expected.resolution ||
    value.path !== expected.path ||
    typeof value.lease_id !== "string" ||
    typeof value.cause !== "string" ||
    !Array.isArray(adjustments) ||
    adjustments.some((item) => typeof item !== "string") ||
    typeof value.credit_usd_cents !== "number" ||
    !Number.isSafeInteger(value.credit_usd_cents) ||
    value.credit_usd_cents < 0 ||
    (status !== null && status !== "VACANT" && status !== "CLEANING")
  )
    throw new LeaseRequestError();
  return {
    resolution_id: expected.resolution,
    termination_event_id: expected.termination,
    lease_id: value.lease_id,
    path: expected.path as UnpaidInitialResolution["path"],
    cause: value.cause,
    resulting_unit_status: status,
    deposit_disposition_id: nullableId(value.deposit_disposition_id),
    invoice_void_event_id: nullableId(value.invoice_void_event_id),
    adjustment_ids: adjustments as string[],
    credit_usd_cents: value.credit_usd_cents,
  };
}

function resolutionPath(
  propertyId: string,
  terminationEventId: string,
  kind: "never-moved-in" | "moved-in-credit",
): string {
  return `/api/v1/properties/${encodeURIComponent(propertyId)}/lease-terminations/${encodeURIComponent(terminationEventId)}/unpaid-initial-${kind}`;
}

function commandHeaders(idempotencyKey: string, version?: number): HeadersInit {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
    "X-CSRF-Token": csrfToken(),
    ...(version === undefined ? {} : { "If-Match": `"${String(version)}"` }),
  };
}

async function leaseCommand(
  path: string,
  method: "POST" | "PATCH",
  source: object,
  idempotencyKey: string,
  version?: number,
): Promise<LeaseResource> {
  return lease(
    data(
      await request(path, {
        method,
        headers: commandHeaders(idempotencyKey, version),
        body: JSON.stringify(source),
      }),
    ),
  );
}

export const leaseApi: LeaseApi = {
  list: async (propertyId, filters = {}) => {
    const parameters = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "")
        parameters.set(key, String(value));
    });
    const encoded = parameters.toString();
    const body = await request(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/leases${encoded === "" ? "" : `?${encoded}`}`,
      { method: "GET" },
    );
    if (!Array.isArray(body.data)) throw new LeaseRequestError();
    const page =
      typeof body.page === "object" && body.page !== null
        ? (body.page as Record<string, unknown>)
        : {};
    const meta =
      typeof body.meta === "object" && body.meta !== null
        ? (body.meta as Record<string, unknown>)
        : {};
    return {
      items: body.data.map(lease),
      next_cursor:
        typeof page.next_cursor === "string" ? page.next_cursor : null,
      can_create: meta.can_create === true,
    };
  },
  get: async (leaseId) =>
    lease(
      data(
        await request(`/api/v1/leases/${encodeURIComponent(leaseId)}`, {
          method: "GET",
        }),
      ),
    ),
  timeline: async (leaseId, cursor) => {
    const parameters = new URLSearchParams({ limit: "50" });
    if (cursor !== undefined) parameters.set("cursor", cursor);
    const body = await request(
      `/api/v1/leases/${encodeURIComponent(leaseId)}/timeline?${parameters.toString()}`,
      { method: "GET" },
    );
    if (!Array.isArray(body.data)) throw new LeaseRequestError();
    const page =
      typeof body.page === "object" && body.page !== null
        ? (body.page as Record<string, unknown>)
        : {};
    return {
      items: body.data as LeaseTimelineEvent[],
      next_cursor:
        typeof page.next_cursor === "string" ? page.next_cursor : null,
    };
  },
  create: (propertyId, source, key) =>
    leaseCommand(
      `/api/v1/properties/${encodeURIComponent(propertyId)}/leases`,
      "POST",
      source,
      key,
    ),
  update: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}`,
      "PATCH",
      source,
      key,
      value.version,
    ),
  addSigner: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}/signers`,
      "POST",
      source,
      key,
      value.version,
    ),
  recordSignature: (value, signerId, source, key) =>
    leaseCommand(
      `/api/v1/lease-signers/${encodeURIComponent(signerId)}?lease_id=${encodeURIComponent(value.lease_id)}`,
      "PATCH",
      source,
      key,
      value.version,
    ),
  sign: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}/sign`,
      "POST",
      source,
      key,
      value.version,
    ),
  cancel: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}/cancel`,
      "POST",
      source,
      key,
      value.version,
    ),
  recordMoveIn: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}/move-in`,
      "POST",
      source,
      key,
      value.version,
    ),
  renew: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}/renew`,
      "POST",
      source,
      key,
    ),
  terminate: (value, source, key) =>
    leaseCommand(
      `/api/v1/leases/${encodeURIComponent(value.lease_id)}/terminate`,
      "POST",
      source,
      key,
      value.version,
    ),
  completeMoveIn: async (
    reservationId,
    expectedReservationVersion,
    source,
    key,
  ) =>
    data(
      await request(
        `/api/v1/reservations/${encodeURIComponent(reservationId)}/complete-move-in`,
        {
          method: "POST",
          headers: commandHeaders(key, expectedReservationVersion),
          body: JSON.stringify(source),
        },
      ),
    ) as unknown as MoveInResult,
  resolveNeverMovedIn: async (propertyId, terminationEventId, source, key) =>
    resolution(
      data(
        await request(
          resolutionPath(propertyId, terminationEventId, "never-moved-in"),
          {
            method: "POST",
            headers: commandHeaders(key),
            body: JSON.stringify(source),
          },
        ),
      ),
      {
        termination: terminationEventId,
        resolution: source.resolution_id,
        path: "NEVER_MOVED_IN",
      },
    ),
  creditMovedInInitialRent: async (
    propertyId,
    terminationEventId,
    source,
    key,
  ) =>
    resolution(
      data(
        await request(
          resolutionPath(propertyId, terminationEventId, "moved-in-credit"),
          {
            method: "POST",
            headers: commandHeaders(key),
            body: JSON.stringify(source),
          },
        ),
      ),
      {
        termination: terminationEventId,
        resolution: source.resolution_id,
        path: "MOVED_IN",
      },
    ),
};
