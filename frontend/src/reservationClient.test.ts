import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ReservationConflictError,
  ReservationResource,
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
        approved_at: "2026-09-01T00:00:00Z",
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
          outcome_id: "outcome-1",
          reason_code: "CUSTOMER_WITHDREW",
          responsibility: "CUSTOMER",
          property_could_provide_unit: true,
          reason_memo: "Customer request",
          coordination_reference: null,
          refund_number: null,
        },
        "command-1",
      ),
    ).rejects.toBeInstanceOf(ReservationConflictError);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/reservations/reservation-1/security-deposit-dispositions",
    );
  });

  it("TEST-FE-211 reloads detail after the replay-stable disposition result", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: {
              reservation_id: reservation.reservation_id,
              version: 3,
              deposit_outcome_state: "NON_REFUNDABLE_DISPOSITION",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: {
              ...reservation,
              status: "CANCELLED",
              version: 3,
              deposit_outcome_state: "NON_REFUNDABLE_DISPOSITION",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    const result = await reservationApi.cancel(
      reservation,
      {
        event_id: "event-1",
        outcome_id: "outcome-1",
        reason_code: "CUSTOMER_WITHDREW",
        responsibility: "CUSTOMER",
        property_could_provide_unit: true,
        reason_memo: "Customer request",
        coordination_reference: null,
        refund_number: null,
      },
      "command-1",
    );

    expect(result.status).toBe("CANCELLED");
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/reservations/reservation-1/security-deposit-dispositions",
      "/reservations/reservation-1",
    ]);
  });
});
