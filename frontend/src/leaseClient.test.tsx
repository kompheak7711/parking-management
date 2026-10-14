import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LeaseConflictError, LeaseRequestError, leaseApi } from "./leaseClient";

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

  const termination = "11111111-1111-4111-8111-111111111111";
  const resolutionId = "22222222-2222-4222-8222-222222222222";
  const snapshot = {
    resolution_id: resolutionId,
    termination_event_id: termination,
    lease_id: "lease-1",
    path: "NEVER_MOVED_IN",
    cause: "CUSTOMER_UNPAID_INITIAL_OBLIGATION",
    resulting_unit_status: "VACANT",
    deposit_disposition_id: "disposition-1",
    invoice_void_event_id: null,
    adjustment_ids: ["adjustment-1"],
    credit_usd_cents: 4200,
  };

  it("TEST-FE-657 posts the unpaid Initial resolution to the Property route with CSRF and an idempotency key but no If-Match", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(response({ data: snapshot }, 201));
    const result = await leaseApi.resolveNeverMovedIn(
      "property/1",
      termination,
      {
        resolution_id: resolutionId,
        unit_status: "VACANT",
        reason: "Never moved in",
      },
      "command-1",
    );
    const call = fetcher.mock.calls[0];
    expect(call?.[0]).toBe(
      `/api/v1/properties/property%2F1/lease-terminations/${termination}/unpaid-initial-never-moved-in`,
    );
    expect(call?.[1]?.method).toBe("POST");
    const headers = new Headers(call?.[1]?.headers);
    expect(headers.get("Idempotency-Key")).toBe("command-1");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
    expect(headers.has("If-Match")).toBe(false);
    expect(bodyOf(call?.[1])).toEqual({
      resolution_id: resolutionId,
      unit_status: "VACANT",
      reason: "Never moved in",
    });
    expect(result).toMatchObject({
      path: "NEVER_MOVED_IN",
      credit_usd_cents: 4200,
      resulting_unit_status: "VACANT",
      invoice_void_event_id: null,
    });
  });

  it("TEST-FE-658 rejects an unpaid Initial resolution reply that does not match the request", async () => {
    const changes = [
      { termination_event_id: "33333333-3333-4333-8333-333333333333" },
      { resolution_id: "44444444-4444-4444-8444-444444444444" },
      { path: "MOVED_IN" },
      { credit_usd_cents: -1 },
      { credit_usd_cents: 1.5 },
      { adjustment_ids: [1] },
      { resulting_unit_status: "OCCUPIED" },
    ];
    for (const change of changes) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        response({ data: { ...snapshot, ...change } }, 201),
      );
      await expect(
        leaseApi.resolveNeverMovedIn(
          "property-1",
          termination,
          {
            resolution_id: resolutionId,
            unit_status: "VACANT",
            reason: "Never moved in",
          },
          "command-1",
        ),
      ).rejects.toBeInstanceOf(LeaseRequestError);
    }
  });

  it("TEST-FE-659 posts the moved-in credit and sends the termination context with the Lease termination", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        response(
          {
            data: {
              ...snapshot,
              path: "MOVED_IN",
              resulting_unit_status: null,
              deposit_disposition_id: null,
            },
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        response({ data: { lease_id: "lease-1", version: 5 } }),
      );
    const credit = await leaseApi.creditMovedInInitialRent(
      "property-1",
      termination,
      { resolution_id: resolutionId, reason: "Rent after termination" },
      "command-2",
    );
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      `/api/v1/properties/property-1/lease-terminations/${termination}/unpaid-initial-moved-in-credit`,
    );
    expect(credit.path).toBe("MOVED_IN");
    await leaseApi.terminate(
      { lease_id: "lease-1", version: 4 } as Parameters<
        typeof leaseApi.terminate
      >[0],
      {
        event_id: termination,
        actual_termination_date: "2026-09-10",
        occurred_at: "2026-09-10T02:00:00Z",
        governing_event_reference: "BR-LEASE-005",
        reason: "Customer did not pay",
        context: {
          basis: "UNPAID_INITIAL_OBLIGATION",
          signed_lease_provision: "Clause 7.3",
          approved_grounds: "Initial Rent unpaid",
          management_authorization_reference: "AUTH-1",
          evidence_reference: "LEDGER-1",
          notice_required: false,
          notice_exception_reason: "Clause allows immediate termination",
        },
      },
      "command-3",
    );
    const call = fetcher.mock.calls[1];
    expect(call?.[0]).toBe("/api/v1/leases/lease-1/terminate");
    expect(new Headers(call?.[1]?.headers).get("If-Match")).toBe('"4"');
    expect(bodyOf(call?.[1]).context).toMatchObject({
      basis: "UNPAID_INITIAL_OBLIGATION",
    });
  });
});
