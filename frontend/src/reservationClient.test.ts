import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ReservationConflictError,
  ReservationRequestError,
  ReservationResource,
  ReservationUnavailableError,
  reservationApi,
} from "./reservationClient";

const reservation: ReservationResource = {
  reservation_id: "reservation-1",
  property_id: "property-1",
  unit_id: "unit-1",
  unit_number: "101",
  customer_id: "customer-1",
  customer_name: "Customer One",
  reservation_date: "2026-08-26",
  original_expiration_date: "2026-09-05",
  effective_expiration_date: "2026-09-05",
  agreed_monthly_rent_usd_cents: 50000,
  status: "ACTIVE",
  version: 2,
  deposit_id: "deposit-1",
  deposit_required_usd_cents: 50000,
  deposit_received_usd_cents: 10000,
  deposit_outcome_state: "PENDING_V1_031",
  cancellation_reason_code: null,
  cancellation_responsibility: null,
  resulting_lease_id: null,
  extension_notice: null,
  can_extend: true,
  can_cancel: true,
  receipts: [],
  lifecycle_events: [],
  deposit_outcomes: [],
  extension_days_remaining: 10,
};

beforeEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(document, "cookie", {
    configurable: true,
    value: "__Host-prm_csrf=reservation-token",
    writable: true,
  });
});

describe("Reservation API client", () => {
  it("TEST-FE-179 sends bounded status filters and decodes the approved vocabulary", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          data: { items: [reservation], next_cursor: null, can_create: true },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const page = await reservationApi.list("property-1", "ACTIVE");

    expect(fetchMock).toHaveBeenCalledWith(
      "/properties/property-1/reservations?status=ACTIVE",
      expect.objectContaining({ credentials: "include", method: "GET" }),
    );
    expect(page.items).toEqual([reservation]);
    expect(page.can_create).toBe(true);
  });

  it("TEST-FE-180 sends CSRF, idempotency, and version preconditions for extension", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: reservation }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await reservationApi.extend(
      reservation,
      {
        notice_id: "notice-1",
        new_expiration_date: "2026-09-12",
        reason_memo: "Approved",
      },
      "command-1",
    );

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("reservation-token");
    expect(headers.get("Idempotency-Key")).toBe("command-1");
    expect(headers.get("If-Match")).toBe('"2"');
  });

  it("TEST-FE-181 classifies concurrency conflicts without exposing server details", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 412 }));

    await expect(
      reservationApi.cancel(
        reservation,
        {
          event_id: "event-1",
          reason_code: "CUSTOMER_WITHDREW",
          responsibility: "CUSTOMER",
          property_could_provide_unit: true,
          reason_memo: "Customer request",
          coordination_reference: null,
        },
        "command-1",
      ),
    ).rejects.toBeInstanceOf(ReservationConflictError);
    // V1-056 slice 3b: every cancellation uses the cancel route; the Deposit outcome is a draft.
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/reservations/reservation-1/cancel",
    );
  });

  it("TEST-FE-211 reloads detail after the replay-stable disposition result", async () => {
    // V1-056 slice 3b: the cancel route returns the Reservation itself; the Deposit is held
    // until its draft is confirmed, so there is no disposition result to reload from.
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          data: {
            ...reservation,
            status: "CANCELLED",
            version: 3,
            deposit_outcome_state: "AWAITING_DECISION",
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const result = await reservationApi.cancel(
      reservation,
      {
        event_id: "event-1",
        reason_code: "CUSTOMER_WITHDREW",
        responsibility: "CUSTOMER",
        property_could_provide_unit: true,
        reason_memo: "Customer request",
        coordination_reference: null,
      },
      "command-1",
    );

    expect(result.status).toBe("CANCELLED");
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/reservations/reservation-1/cancel",
    ]);
  });
  it("TEST-FE-1081 a timeout, too many requests or a server failure is no answer, not a refusal (V1-060 B7)", async () => {
    for (const status of [408, 429, 500, 502, 503, 504]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(null, { status }),
      );
      await expect(reservationApi.get("reservation-1")).rejects.toBeInstanceOf(
        ReservationUnavailableError,
      );
      vi.restoreAllMocks();
    }
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 422 }),
    );
    await expect(reservationApi.get("reservation-1")).rejects.toBeInstanceOf(
      ReservationRequestError,
    );
  });
  it("TEST-FE-1095 an answer of success that cannot be read is no answer; a refusal keeps its status (V1-060 B7)", async () => {
    for (const body of ["not json", "null", JSON.stringify({ meta: {} })]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(body, { status: 201 }),
      );
      await expect(reservationApi.get("reservation-1")).rejects.toBeInstanceOf(
        ReservationUnavailableError,
      );
      vi.restoreAllMocks();
    }
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 404 }),
    );
    await expect(reservationApi.get("reservation-1")).rejects.toMatchObject({
      name: "ReservationRequestError",
      status: 404,
    });
  });
});
