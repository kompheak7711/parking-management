import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LeaseConflictError,
  LeaseUnitBookedError,
  leaseApi,
} from "./leaseClient";

beforeEach(() => {
  Object.defineProperty(document, "cookie", {
    configurable: true,
    value: "__Host-prm_csrf=csrf-value",
    writable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function bodyOf(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

function response(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Lease API client", () => {
  it("TEST-FE-185 sends bounded status, Parking, Customer, date, and period filters", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({
        data: [],
        page: { next_cursor: null, limit: 50 },
        meta: { can_create: true },
      }),
    );

    const page = await leaseApi.list("property-1", {
      status: "SIGNED",
      unit_id: "unit-1",
      customer_id: "customer-1",
      starts_on_or_after: "2026-01-01",
      ends_on_or_before: "2027-12-31",
      period: "approaching_end",
      as_of: "2026-08-26",
      approaching_days: 30,
    });

    expect(page.can_create).toBe(true);
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining("period=approaching_end"),
      expect.objectContaining({ credentials: "include", method: "GET" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      expect.stringContaining("customer_id=customer-1"),
      expect.anything(),
    );
  });

  it("TEST-FE-186 sends CSRF, idempotency, and If-Match for an explicit Lease command", async () => {
    const lease = {
      lease_id: "lease-1",
      version: 4,
    } as Parameters<typeof leaseApi.cancel>[0];
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        response({ data: { lease_id: "lease-1", version: 5 } }),
      );

    await leaseApi.cancel(
      lease,
      {
        event_id: "event-1",
        reason: "Draft no longer needed",
      },
      "command-1",
    );

    const call = fetcher.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/leases/lease-1/cancel");
    expect(call?.[1]?.method).toBe("POST");
    const headers = new Headers(call?.[1]?.headers);
    expect(headers.get("Idempotency-Key")).toBe("command-1");
    expect(headers.get("If-Match")).toBe('"4"');
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
  });

  it("TEST-FE-187 reports optimistic conflicts without retrying an ambiguous command", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(response({}, 412));
    const lease = { lease_id: "lease-1", version: 2 } as Parameters<
      typeof leaseApi.update
    >[0];

    await expect(
      leaseApi.update(
        lease,
        {
          event_id: "event-1",
          start_date: "2026-09-01",
          end_date: "2027-08-31",
          monthly_rent_usd_cents: 80000,
          reason: "Correction",
        },
        "command-1",
      ),
    ).rejects.toBeInstanceOf(LeaseConflictError);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-2167 a draft refused because a short-stay guest has booked the Unit carries the server's reason; any other refusal of that kind stays a conflict (DL-223)", async () => {
    const booked = {
      error: {
        code: "LEASE_UNIT_BOOKED",
        message:
          "A short-stay guest has booked this Unit on some of these days. Nothing was saved.",
      },
    };
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(booked, 409))
      .mockResolvedValueOnce(response({ error: { code: "CONFLICT" } }, 409))
      .mockResolvedValueOnce(new Response("not JSON", { status: 409 }));
    const lease = { lease_id: "lease-1", version: 2 } as Parameters<
      typeof leaseApi.update
    >[0];
    const send = () =>
      leaseApi.update(
        lease,
        {
          event_id: "event-1",
          start_date: "2026-11-11",
          end_date: "2027-11-30",
          monthly_rent_usd_cents: 29900,
          reason: "Start earlier",
        },
        "command-1",
      );

    const error: unknown = await send().catch((found: unknown) => found);
    expect(error).toBeInstanceOf(LeaseUnitBookedError);
    expect(error).not.toBeInstanceOf(LeaseConflictError);
    expect(error).toMatchObject({
      code: "LEASE_UNIT_BOOKED",
      message: booked.error.message,
    });
    await expect(send()).rejects.toBeInstanceOf(LeaseConflictError);
    await expect(send()).rejects.toBeInstanceOf(LeaseConflictError);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("TEST-FE-195 loads one exact bounded timeline continuation", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      response({
        data: [
          {
            event_id: "event-2",
            event_kind: "lease.draft.update",
            occurred_at: "2026-08-26T02:00:00Z",
            reason: "Corrected",
            actor_id: "actor-1",
            source_reference: "event-2",
            source_href: "/api/v1/leases/lease-1#timeline-event-2",
          },
        ],
        page: { next_cursor: null, limit: 50 },
      }),
    );

    const page = await leaseApi.timeline("lease-1", "cursor-1");

    expect(page.items[0]?.event_id).toBe("event-2");
    expect(page.next_cursor).toBeNull();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/leases/lease-1/timeline?limit=50&cursor=cursor-1",
      expect.objectContaining({ credentials: "include", method: "GET" }),
    );
  });

  const termination = "11111111-1111-4111-8111-111111111111";
  it("TEST-FE-659 sends the termination context with the Lease termination (C1: never for an unpaid Initial obligation)", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        response({ data: { lease_id: "lease-1", version: 5 } }),
      );
    await leaseApi.terminate(
      { lease_id: "lease-1", version: 4 } as Parameters<
        typeof leaseApi.terminate
      >[0],
      {
        event_id: termination,
        actual_termination_date: "2026-09-10",
        governing_event_reference: "BR-LEASE-025",
        reason: "Lease rule violation",
        context: {
          basis: "CUSTOMER_VIOLATION",
          signed_lease_provision: "Clause 9",
          approved_grounds: "Lease rule violation after three written warnings",
          management_authorization_reference: "AUTH-1",
          evidence_reference: "LEDGER-1",
          notice_required: false,
          notice_exception_reason: "Clause allows immediate termination",
        },
      },
      "command-3",
    );
    const call = fetcher.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/leases/lease-1/terminate");
    expect(new Headers(call?.[1]?.headers).get("If-Match")).toBe('"4"');
    expect(bodyOf(call?.[1]).context).toMatchObject({
      basis: "CUSTOMER_VIOLATION",
    });
  });

  it("TEST-FE-1135 the vehicle move-in and Change vehicle post to their own routes with the Lease version, and a coded refusal keeps the server's words (Parking Step 4)", async () => {
    const lease = { lease_id: "lease-1", version: 4 } as Parameters<
      typeof leaseApi.recordVehicleMoveIn
    >[0];
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        response({ data: { lease_id: "lease-1", version: 5 } }),
      )
      .mockResolvedValueOnce(
        response(
          {
            error: {
              code: "VEHICLE_TYPE",
              message: "This vehicle type cannot park in this Parking Type.",
            },
          },
          409,
        ),
      );
    const moved = await leaseApi.recordVehicleMoveIn(
      lease,
      {
        event_id: "event-1",
        actual_move_in_date: "2026-10-28",
        occupancy_id: "occupancy-1",
        vehicle_id: "vehicle-1",
        reason: "Vehicle moved in",
      },
      "command-1",
    );
    expect(moved.version).toBe(5);
    const call = fetcher.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/leases/lease-1/vehicle-move-in");
    expect(call?.[1]?.method).toBe("POST");
    const headers = new Headers(call?.[1]?.headers);
    expect(headers.get("Idempotency-Key")).toBe("command-1");
    expect(headers.get("If-Match")).toBe('"4"');
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");

    const refused = await leaseApi
      .changeVehicle(
        lease,
        {
          event_id: "event-2",
          change_date: "2026-10-28",
          occupancy_id: "occupancy-2",
          vehicle_id: "vehicle-2",
          reason: "Sold the old car",
        },
        "command-2",
      )
      .catch((error: unknown) => error);
    expect(refused).toBeInstanceOf(LeaseRefusedError);
    expect(refused).toMatchObject({
      code: "VEHICLE_TYPE",
      message: "This vehicle type cannot park in this Parking Type.",
    });
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      "/api/v1/leases/lease-1/vehicle-change",
    );

    // A plain conflict (someone changed the Lease first) is still a conflict, not a refusal.
    fetcher.mockResolvedValueOnce(
      response({ error: { code: "CONFLICT", message: "Conflict" } }, 409),
    );
    await expect(
      leaseApi.changeVehicle(
        lease,
        {
          event_id: "event-3",
          change_date: "2026-10-28",
          occupancy_id: "occupancy-3",
          vehicle_id: "vehicle-3",
          reason: "Sold the old car",
        },
        "command-3",
      ),
    ).rejects.toBeInstanceOf(LeaseConflictError);
  });
});
