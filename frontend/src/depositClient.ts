export type DepositType = "SECURITY" | "PET";

export interface DepositResource {
  deposit_id: string;
  property_id: string;
  deposit_type: DepositType;
  customer_id: string;
  reservation_id: string | null;
  lease_id: string | null;
  pet_approval_id: string | null;
  required_usd_cents: number;
  received_usd_cents: number;
  held_refundable_usd_cents: number;
  outstanding_required_usd_cents: number;
  version: number;
  reservation_version: number | null;
  pet_departure_id: string | null;
  pet_refund_review_id: string | null;
  refund_qualified: boolean;
  can_manage: boolean;
  can_reverse_receipt: boolean;
  can_qualify_pet_refund: boolean;
  new_receipt_creation_deferred: true;
  final_settlement_disposition_deferred: true;
}

export interface DepositLedgerEvent {
  event_id: string;
  event_kind: string;
  occurred_at: string;
  amount_usd_cents: number | null;
  source_id: string | null;
  reason: string | null;
  evidence_reference: string | null;
  actor_id: string;
  authorization_reference: string | null;
  currency: string | null;
  amount_minor: number | null;
  reference_number: string | null;
  governing_source_kind: "RESERVATION" | "LEASE" | "FINAL_SETTLEMENT" | null;
  governing_source_id: string | null;
  source_lifecycle_event_id: string | null;
  effective_date: string | null;
  can_reverse: boolean;
}

export interface DepositLedgerPage {
  items: DepositLedgerEvent[];
  next_cursor: string | null;
}

export interface DepositCollection {
  items: DepositResource[];
  can_manage: boolean;
}

export interface PetDepartureResource {
  departure_id: string;
  deposit_id: string;
  lease_id: string;
  pet_approval_id: string;
  permanently_left_date: string;
  reason: string;
  occurred_at: string;
  actor_id: string;
  refund_review_id: string | null;
}

export interface PetRefundReviewResource {
  review_id: string;
  departure_id: string;
  deposit_id: string;
  obligations_reviewed_usd_cents: number;
  review_findings: string;
  resolution_reference: string;
  reason: string;
  reviewed_at: string;
  reviewed_by: string;
  authorization_reference: string;
  refundable_usd_cents: number;
  current_refundable_usd_cents: number;
}

export interface DepositApi {
  reservationDeposits: (reservationId: string) => Promise<DepositCollection>;
  leaseDeposits: (leaseId: string) => Promise<DepositCollection>;
  get: (depositId: string) => Promise<DepositResource>;
  ledger: (depositId: string, cursor?: string) => Promise<DepositLedgerPage>;
  createPetDeposit: (
    leaseId: string,
    source: {
      deposit_id: string;
      pet_approval_id: string;
      required_usd_cents: number;
      required_effective_date: string;
      reason: string;
    },
    key: string,
  ) => Promise<DepositResource>;
  reverseReceipt: (
    receiptId: string,
    source: { reversal_id: string; reason: string },
    key: string,
  ) => Promise<DepositResource>;
  reverseDisposition: (
    dispositionId: string,
    source: {
      reversal_id: string;
      reason: string;
      evidence_reference: string;
      replacement_disposition_id: string | null;
      expected_reservation_version: number | null;
    },
    key: string,
  ) => Promise<DepositResource>;
  recordDeparture: (
    leaseId: string,
    source: {
      departure_id: string;
      deposit_id: string;
      permanently_left_date: string;
      reason: string;
    },
    key: string,
  ) => Promise<DepositResource>;
  departures: (leaseId: string) => Promise<PetDepartureResource[]>;
  qualifyReview: (
    departureId: string,
    source: {
      review_id: string;
      deposit_id: string;
      obligations_reviewed_usd_cents: number;
      review_findings: string;
      resolution_reference: string;
      reason: string;
    },
    key: string,
  ) => Promise<DepositResource>;
  review: (reviewId: string) => Promise<PetRefundReviewResource>;
}

export class DepositUnavailableError extends Error {
  constructor() {
    super("Deposit workflows are unavailable for this session.");
    this.name = "DepositUnavailableError";
  }
}

export class DepositRequestError extends Error {
  constructor() {
    super("The Deposit request was not completed.");
    this.name = "DepositRequestError";
  }
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (value === undefined) throw new DepositRequestError();
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
    throw new DepositUnavailableError();
  }
  if (response.status === 503) throw new DepositUnavailableError();
  if (!response.ok) throw new DepositRequestError();
  const value: unknown = await response.json();
  if (typeof value !== "object" || value === null)
    throw new DepositRequestError();
  return value as Record<string, unknown>;
}

function data(value: Record<string, unknown>): unknown {
  if (!("data" in value)) throw new DepositRequestError();
  return value.data;
}

function resource(value: unknown): DepositResource {
  if (typeof value !== "object" || value === null)
    throw new DepositRequestError();
  return value as DepositResource;
}

function headers(key: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": key,
    "X-CSRF-Token": csrfToken(),
  };
}

async function command(
  path: string,
  source: object,
  key: string,
): Promise<DepositResource> {
  return resource(
    data(
      await request(path, {
        method: "POST",
        headers: headers(key),
        body: JSON.stringify(source),
      }),
    ),
  );
}

async function collection(path: string): Promise<DepositCollection> {
  const body = await request(path, { method: "GET" });
  const value = data(body);
  if (!Array.isArray(value)) throw new DepositRequestError();
  const meta =
    typeof body.meta === "object" && body.meta !== null
      ? (body.meta as Record<string, unknown>)
      : {};
  if (typeof meta.can_manage !== "boolean") throw new DepositRequestError();
  return { items: value.map(resource), can_manage: meta.can_manage };
}

export const depositApi: DepositApi = {
  reservationDeposits: (id) =>
    collection(`/api/v1/reservations/${encodeURIComponent(id)}/deposits`),
  leaseDeposits: (id) =>
    collection(`/api/v1/leases/${encodeURIComponent(id)}/deposits`),
  get: async (id) =>
    resource(
      data(
        await request(`/api/v1/deposits/${encodeURIComponent(id)}`, {
          method: "GET",
        }),
      ),
    ),
  ledger: async (id, cursor) => {
    const parameters = new URLSearchParams({ limit: "50" });
    if (cursor !== undefined) parameters.set("cursor", cursor);
    const body = await request(
      `/api/v1/deposits/${encodeURIComponent(id)}/ledger?${parameters.toString()}`,
      { method: "GET" },
    );
    const value = data(body);
    if (!Array.isArray(value)) throw new DepositRequestError();
    const page =
      typeof body.page === "object" && body.page !== null
        ? (body.page as Record<string, unknown>)
        : {};
    return {
      items: value as DepositLedgerEvent[],
      next_cursor:
        typeof page.next_cursor === "string" ? page.next_cursor : null,
    };
  },
  createPetDeposit: (leaseId, source, key) =>
    command(
      `/api/v1/leases/${encodeURIComponent(leaseId)}/pet-deposits`,
      source,
      key,
    ),
  reverseReceipt: (id, source, key) =>
    command(
      `/api/v1/deposit-receipts/${encodeURIComponent(id)}/reverse`,
      source,
      key,
    ),
  reverseDisposition: (id, source, key) =>
    command(
      `/api/v1/deposit-dispositions/${encodeURIComponent(id)}/reverse`,
      source,
      key,
    ),
  recordDeparture: (leaseId, source, key) =>
    command(
      `/api/v1/leases/${encodeURIComponent(leaseId)}/pet-departures`,
      source,
      key,
    ),
  departures: async (leaseId) => {
    const value = data(
      await request(
        `/api/v1/leases/${encodeURIComponent(leaseId)}/pet-departures`,
        {
          method: "GET",
        },
      ),
    );
    if (!Array.isArray(value)) throw new DepositRequestError();
    return value as PetDepartureResource[];
  },
  qualifyReview: (departureId, source, key) =>
    command(
      `/api/v1/pet-departures/${encodeURIComponent(departureId)}/refund-review`,
      source,
      key,
    ),
  review: async (reviewId) => {
    const value = data(
      await request(
        `/api/v1/pet-deposit-refund-reviews/${encodeURIComponent(reviewId)}`,
        { method: "GET" },
      ),
    );
    if (typeof value !== "object" || value === null)
      throw new DepositRequestError();
    return value as PetRefundReviewResource;
  },
};
