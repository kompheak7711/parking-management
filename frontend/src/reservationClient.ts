export type ReservationStatus = "ACTIVE" | "CANCELLED" | "COMPLETED";
export type CancellationResponsibility = "CUSTOMER" | "PROPERTY";

export interface ExtensionNotice {
  notice_id: string;
  previous_expiration_date: string;
  new_expiration_date: string;
  approved_at: string;
  reason_memo: string | null;
}

export interface ReservationResource {
  reservation_id: string;
  property_id: string;
  unit_id: string;
  unit_number: string;
  customer_id: string;
  customer_name: string;
  reservation_date: string;
  original_expiration_date: string;
  effective_expiration_date: string;
  agreed_monthly_rent_usd_cents: number;
  status: ReservationStatus;
  version: number;
  deposit_id: string;
  deposit_required_usd_cents: number;
  deposit_received_usd_cents: number;
  deposit_outcome_state: string;
  cancellation_reason_code: string | null;
  cancellation_responsibility: CancellationResponsibility | null;
  resulting_lease_id: string | null;
  extension_notice: ExtensionNotice | null;
  can_extend: boolean;
  can_cancel: boolean;
  receipts: {
    receipt_id: string;
    payment_id: string;
    amount_usd_cents: number;
    occurred_at: string;
    actor_id: string;
  }[];
  lifecycle_events: {
    event_id: string;
    event_kind: string;
    reason_code: string;
    responsibility: CancellationResponsibility;
    reason_memo: string | null;
    coordination_reference: string | null;
    authorization_reference: string;
    occurred_at: string;
    business_date: string;
    actor_id: string;
  }[];
  deposit_outcomes: {
    outcome_id: string;
    outcome_kind: string;
    amount_usd_cents: number;
    source_lifecycle_event_id: string;
    reason: string;
    occurred_at: string;
    actor_id: string;
    authorization_reference: string;
  }[];
  extension_days_remaining: number | null;
}

export interface ReservationPage {
  items: ReservationResource[];
  next_cursor: string | null;
  can_create: boolean;
}

export interface ReservationApi {
  list: (
    propertyId: string,
    status?: ReservationStatus,
    cursor?: string,
  ) => Promise<ReservationPage>;
  get: (reservationId: string) => Promise<ReservationResource>;
  create: (
    propertyId: string,
    source: ReservationCreateSource,
    idempotencyKey: string,
  ) => Promise<ReservationResource>;
  /** V1-061 (DL-112): the deposit received and the Reservation, saved together or not at all. */
  createWithPayment: (
    propertyId: string,
    source: ReservationWithPaymentSource,
    idempotencyKey: string,
  ) => Promise<{
    reservation: ReservationResource;
    receiptNumber: string | null;
  }>;
  extend: (
    reservation: ReservationResource,
    source: ReservationExtendSource,
    idempotencyKey: string,
  ) => Promise<ReservationResource>;
  cancel: (
    reservation: ReservationResource,
    source: ReservationCancelSource,
    idempotencyKey: string,
  ) => Promise<ReservationResource>;
}

export interface ReservationCreateSource {
  reservation_id: string;
  unit_id: string;
  customer_id: string;
  reservation_date: string;
  agreed_monthly_rent_usd_cents: number;
  expiration_date: string;
  acceptance_id: string;
  accepted_initial_deposit_usd_cents: number;
  required_security_deposit_usd_cents: number;
  acceptance_reason: string;
  deposit_id: string;
  receipt_id: string;
  payment_id: string;
}

/** The money received with Make Reservation: the Customer's own, in USD (DL-112). */
export interface OwnMoneySource {
  payment_method_id: string;
  received_at: string;
  evidence_reference: string;
  payer_intent_memo: string | null;
  amount: { currency: "USD"; minor_units: number };
}

export type ReservationWithPaymentSource = Omit<
  ReservationCreateSource,
  "payment_id"
> & { payment: OwnMoneySource };

export interface ReservationExtendSource {
  notice_id: string;
  new_expiration_date: string;
  reason_memo: string;
}

export interface ReservationCancelSource {
  event_id: string;
  reason_code: string;
  responsibility: CancellationResponsibility;
  property_could_provide_unit: boolean;
  reason_memo: string;
  coordination_reference: string | null;
}

export class ReservationUnavailableError extends Error {
  constructor() {
    super("Reservation management is unavailable for this session.");
    this.name = "ReservationUnavailableError";
  }
}

export class ReservationConflictError extends Error {
  constructor() {
    super(
      "The Reservation changed or conflicts with current availability. Reload before retrying.",
    );
    this.name = "ReservationConflictError";
  }
}

export class ReservationRequestError extends Error {
  /** V1-060 B7: the answer's status, when the server gave one. */
  constructor(public readonly status: number | null = null) {
    super("The Reservation request was not completed.");
    this.name = "ReservationRequestError";
  }
}

function csrfToken(): string {
  const prefix = "__Host-prm_csrf=";
  const value = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (value === undefined) throw new ReservationRequestError();
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
    throw new ReservationUnavailableError();
  }
  if (response.status === 409 || response.status === 412) {
    throw new ReservationConflictError();
  }
  // V1-060 B7: a timeout, too many requests or a server failure cannot say whether a command was
  // saved, so they count as no answer, as a lost connection does.
  if (
    response.status === 408 ||
    response.status === 429 ||
    response.status >= 500
  )
    throw new ReservationUnavailableError();
  if (!response.ok) throw new ReservationRequestError(response.status);
  // V1-060 B7: an answer of success that cannot be read cannot say what was saved, so it counts
  // as no answer.
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ReservationUnavailableError();
  }
  if (typeof value !== "object" || value === null)
    throw new ReservationUnavailableError();
  return value as Record<string, unknown>;
}

function data(value: Record<string, unknown>): Record<string, unknown> {
  if (typeof value.data !== "object" || value.data === null) {
    throw new ReservationUnavailableError();
  }
  return value.data as Record<string, unknown>;
}

function commandHeaders(idempotencyKey: string, version?: number): HeadersInit {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
    "X-CSRF-Token": csrfToken(),
    ...(version === undefined ? {} : { "If-Match": `"${String(version)}"` }),
  };
}

function resource(value: unknown): ReservationResource {
  if (typeof value !== "object" || value === null)
    throw new ReservationUnavailableError();
  return value as ReservationResource;
}

export const reservationApi: ReservationApi = {
  list: async (propertyId, status, cursor) => {
    const parameters = new URLSearchParams();
    if (status !== undefined) parameters.set("status", status);
    if (cursor !== undefined) parameters.set("cursor", cursor);
    const encoded = parameters.toString();
    const query = encoded === "" ? "" : `?${encoded}`;
    const body = data(
      await request(
        `/properties/${encodeURIComponent(propertyId)}/reservations${query}`,
        {
          method: "GET",
        },
      ),
    );
    if (!Array.isArray(body.items)) throw new ReservationRequestError();
    return {
      items: body.items.map(resource),
      next_cursor:
        typeof body.next_cursor === "string" ? body.next_cursor : null,
      can_create: body.can_create === true,
    };
  },
  get: async (reservationId) =>
    resource(
      data(
        await request(`/reservations/${encodeURIComponent(reservationId)}`, {
          method: "GET",
        }),
      ),
    ),
  create: async (propertyId, source, idempotencyKey) =>
    resource(
      data(
        await request(
          `/properties/${encodeURIComponent(propertyId)}/reservations`,
          {
            method: "POST",
            headers: commandHeaders(idempotencyKey),
            body: JSON.stringify(source),
          },
        ),
      ),
    ),
  createWithPayment: async (propertyId, source, idempotencyKey) => {
    const body = data(
      await request(
        `/properties/${encodeURIComponent(propertyId)}/reservations/with-payment`,
        {
          method: "POST",
          headers: commandHeaders(idempotencyKey),
          body: JSON.stringify(source),
        },
      ),
    );
    return {
      reservation: resource(body),
      receiptNumber:
        typeof body.receipt_number === "string" ? body.receipt_number : null,
    };
  },
  extend: async (reservation, source, idempotencyKey) =>
    resource(
      data(
        await request(
          `/reservations/${encodeURIComponent(reservation.reservation_id)}/extend`,
          {
            method: "POST",
            headers: commandHeaders(idempotencyKey, reservation.version),
            body: JSON.stringify(source),
          },
        ),
      ),
    ),
  cancel: async (reservation, source, idempotencyKey) =>
    resource(
      data(
        await request(
          `/reservations/${encodeURIComponent(reservation.reservation_id)}/cancel`,
          {
            method: "POST",
            headers: commandHeaders(idempotencyKey, reservation.version),
            body: JSON.stringify(source),
          },
        ),
      ),
    ),
};
