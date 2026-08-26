import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LeaseConflictError, leaseApi } from "./leaseClient";

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

function response(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Lease API client", () => {
  it("TEST-FE-185 sends bounded status, Unit, Customer, date, and period filters", async () => {
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

  it("TEST-FE-186 sends CSRF, idempotency, and If-Match for explicit signing", async () => {
    const lease = {
      lease_id: "lease-1",
      version: 4,
    } as Parameters<typeof leaseApi.sign>[0];
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        response({ data: { lease_id: "lease-1", version: 5 } }),
      );

    await leaseApi.sign(
      lease,
      {
        event_id: "event-1",
        signed_at: "2026-08-26T01:00:00Z",
        reason: "All Signers completed",
      },
      "command-1",
    );

    const call = fetcher.mock.calls[0];
    expect(call?.[0]).toBe("/api/v1/leases/lease-1/sign");
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
});
