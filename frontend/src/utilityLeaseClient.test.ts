import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  UtilityLeaseError,
  utilityLeaseApi,
  utilityReasonText,
} from "./utilityLeaseClient";

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

function reply(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ data, meta: { request_id: "r-1" } }), {
    status,
  });
}
function refusal(code: string, status: number): Response {
  return new Response(
    JSON.stringify({ error: { code }, meta: { request_id: "r-2" } }),
    { status },
  );
}
function bodyOf(init: RequestInit | undefined): unknown {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON body");
  return JSON.parse(init.body) as unknown;
}

describe("Lease Utility client", () => {
  it("posts the baseline to the Lease route with CSRF and an idempotency key and checks the event", async () => {
    const fetcher = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(reply({ event_id: "event-1" }, 201));
    const input = {
      event_id: "event-1",
      baseline_date: "2026-09-02",
      reason: "Baseline",
      evidence_reference: "Sheet 1",
      items: [{ meter_id: "m-1", reading_id: "r-1" }],
    };
    await utilityLeaseApi.recordBaseline("p/1", "l/1", input, "key-1");
    const [path, init] = fetcher.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/properties/p%2F1/leases/l%2F1/utility-baseline");
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("Idempotency-Key")).toBe("key-1");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-value");
    expect(bodyOf(init)).toEqual(input);
    fetcher.mockResolvedValue(reply({ event_id: "another" }, 201));
    await expect(
      utilityLeaseApi.recordBaseline("p", "l", input, "key-1"),
    ).rejects.toMatchObject({ code: "RESOURCE_MISMATCH" });
  });

  it("uses the final input, final Invoice and catch-up routes and checks the answered identity", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    fetcher.mockResolvedValueOnce(reply({ event_id: "e-1" }, 201));
    await utilityLeaseApi.recordFinalInputs(
      "p",
      "l",
      {
        event_id: "e-1",
        move_out_event_id: "m-1",
        reason: "r",
        authorization_reference: "a",
        evidence_reference: "e",
        items: [
          {
            meter_id: "x",
            resolution: "UNRESOLVED",
            unresolved_reason: "MISSING_READING",
          },
        ],
      },
      "k",
    );
    fetcher.mockResolvedValueOnce(reply({ invoice_id: "i-1" }, 201));
    await utilityLeaseApi.createFinalInvoice(
      "p",
      "l",
      {
        invoice_id: "i-1",
        final_input_event_id: "e-1",
        due_date: "2026-10-20",
        due_date_reason: "Agreed",
      },
      "k",
    );
    fetcher.mockResolvedValueOnce(reply({ invoice_id: "i-2" }, 201));
    await utilityLeaseApi.createCatchUpInvoice(
      "p",
      "l",
      { invoice_id: "i-2", consumption_period_id: "period-1" },
      "k",
    );
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/properties/p/leases/l/move-out-final-utility-inputs",
      "/api/v1/properties/p/leases/l/final-utility-invoice",
      "/api/v1/properties/p/leases/l/utility-catch-up-invoice",
    ]);
    expect(bodyOf(fetcher.mock.calls[1]?.[1])).toEqual({
      invoice_id: "i-1",
      final_input_event_id: "e-1",
      due_date: "2026-10-20",
      due_date_reason: "Agreed",
    });
    fetcher.mockResolvedValueOnce(reply({ invoice_id: "other" }, 201));
    await expect(
      utilityLeaseApi.createCatchUpInvoice(
        "p",
        "l",
        { invoice_id: "i-3", consumption_period_id: "period-1" },
        "k",
      ),
    ).rejects.toMatchObject({ code: "RESOURCE_MISMATCH" });
  });

  it("surfaces only the stable reason code and the request identifier of a refusal", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      refusal("UTILITY_UNRESOLVED_FINAL_INPUT", 422),
    );
    await expect(
      utilityLeaseApi.createFinalInvoice(
        "p",
        "l",
        { invoice_id: "i", final_input_event_id: "e" },
        "k",
      ),
    ).rejects.toMatchObject({
      status: 422,
      code: "UTILITY_UNRESOLVED_FINAL_INPUT",
      requestId: "r-2",
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "bad code <script>" } }), {
        status: 500,
      }),
    );
    await expect(utilityLeaseApi.readBaseline("p", "l")).rejects.toMatchObject({
      code: "REQUEST_FAILED",
    });
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    await expect(utilityLeaseApi.readBaseline("p", "l")).rejects.toMatchObject({
      code: "NETWORK",
    });
  });

  it("reads bounded pages and validates every unbilled period", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch");
    const row = {
      period_id: "period-1",
      unit_id: "unit-1",
      utility_type: "ELECTRICITY",
      start_date: "2026-08-03",
      end_date: "2026-08-31",
      consumption_quantity: "40.000000",
      lease_id: "lease-1",
      can_catch_up: true,
      gap_reason: "LATE_AFTER_SUCCEEDED_RUN",
    };
    fetcher.mockResolvedValueOnce(
      reply({ items: [row], limit: 50, offset: 0, creates_invoice: false }),
    );
    const page = await utilityLeaseApi.listUnbilled("p");
    expect(page.items[0]).toMatchObject({
      period_id: "period-1",
      can_catch_up: true,
    });
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/properties/p/unbilled-utility-periods",
    );
    fetcher.mockResolvedValueOnce(
      reply({ items: [{ ...row, gap_reason: "SOMETHING_ELSE" }] }),
    );
    await expect(utilityLeaseApi.listUnbilled("p", 50)).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
    expect(fetcher.mock.calls[1]?.[0]).toBe(
      "/api/v1/properties/p/unbilled-utility-periods?offset=50",
    );
    fetcher.mockResolvedValueOnce(
      reply({ items: [{ ...row, can_catch_up: "yes" }] }),
    );
    await expect(utilityLeaseApi.listUnbilled("p")).rejects.toBeInstanceOf(
      UtilityLeaseError,
    );
  });

  it("keeps plain-language text for every stable reason and a safe default", () => {
    expect(utilityReasonText("UTILITY_NOTHING_TO_BILL")).toMatch(
      /nothing to bill/,
    );
    expect(utilityReasonText("UTILITY_PERIOD_ALREADY_INVOICED")).toMatch(
      /already has/,
    );
    expect(utilityReasonText("SOMETHING_NEW")).toBe(
      "The Utility request could not be completed.",
    );
  });
});
