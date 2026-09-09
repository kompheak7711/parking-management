import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { depositApi } from "./depositClient";

const deposit = {
  deposit_id: "deposit-1",
  property_id: "property-1",
  deposit_type: "PET",
  customer_id: "customer-1",
  reservation_id: null,
  lease_id: "lease-1",
  pet_approval_id: "approval-1",
  required_usd_cents: 20000,
  received_usd_cents: 20000,
  held_refundable_usd_cents: 20000,
  outstanding_required_usd_cents: 0,
  version: 1,
  reservation_version: null,
  pet_departure_id: null,
  pet_refund_review_id: null,
  refund_qualified: false,
  can_manage: true,
  can_reverse_receipt: true,
  can_qualify_pet_refund: true,
  new_receipt_creation_deferred: true,
  final_settlement_disposition_deferred: true,
};

describe("depositClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    document.cookie = "__Host-prm_csrf=csrf; Secure; Path=/";
  });

  it("TEST-FE-196 loads bounded Deposit source history", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          data: [{ event_id: "event-1", event_kind: "RECEIPT" }],
          page: { next_cursor: "older" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    const page = await depositApi.ledger("deposit-1");
    expect(page.next_cursor).toBe("older");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/deposits/deposit-1/ledger?limit=50",
      expect.objectContaining({ credentials: "include", method: "GET" }),
    );
  });

  it("TEST-FE-204 preserves empty-list management capability from the server", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ data: [], meta: { can_manage: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(depositApi.leaseDeposits("lease-1")).resolves.toEqual({
      items: [],
      can_manage: true,
    });
  });

  it("TEST-FE-197 sends split departure commands with CSRF and idempotency", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ data: deposit }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await depositApi.recordDeparture(
      "lease-1",
      {
        departure_id: "departure-1",
        deposit_id: "deposit-1",
        permanently_left_date: "2026-08-26",
        reason: "Pet permanently left",
      },
      "key-1",
    );
    const [path, init] = fetchMock.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/leases/lease-1/pet-departures");
    expect(init).toEqual(
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
    const requestHeaders = new Headers(init?.headers);
    expect(requestHeaders.get("Idempotency-Key")).toBe("key-1");
    expect(requestHeaders.get("X-CSRF-Token")).toBe("csrf");
  });
});
