import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  InvoiceClientError,
  executeBilling,
  formatUsd,
  invoiceApi,
  money,
  parseUsd,
} from "./invoiceClient";
function bodyOf(init: RequestInit | undefined): unknown {
  if (typeof init?.body !== "string")
    throw new Error("Expected JSON request body");
  return JSON.parse(init.body) as unknown;
}
const usd = (minor_units: number) => ({ currency: "USD", minor_units });
function invoice() {
  return {
    id: "invoice/one",
    property_id: "property/one",
    customer_id: "customer",
    lease_id: null,
    invoice_number: "INV-047",
    category: "RENT",
    status: "UNPAID",
    invoice_date: "2026-09-01",
    due_date: "2026-09-05",
    billing_period: null,
    version: 2,
    original_total: usd(31000),
    adjusted_total: usd(31000),
    active_application_total: usd(0),
    outstanding_balance: usd(31000),
    adjustments: [],
    void_event: null,
    lines: [
      {
        id: "line",
        sequence: 1,
        description: "Rent",
        category: "RENT",
        original_amount: usd(31000),
        adjusted_amount: usd(31000),
        outstanding_balance: usd(31000),
        period: null,
        source: { id: "lease" },
        calculation_evidence: { formula: "approved" },
      },
    ],
  };
}
function response(data: unknown, status = 200) {
  return new Response(
    JSON.stringify({
      data,
      page: { next_cursor: "next-token" },
      meta: { billing_capabilities: ["invoices.issue"] },
    }),
    { status },
  );
}
beforeEach(() =>
  Object.defineProperty(document, "cookie", {
    configurable: true,
    value: "__Host-prm_csrf=csrf%20token",
  }),
);
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "cookie", { configurable: true, value: "" });
});
describe("V1-047 invoice client", () => {
  it("parses exact USD cents without rounding or floating-point multiplication", () => {
    expect(parseUsd("15")).toEqual(usd(1500));
    expect(parseUsd("0.01")).toEqual(usd(1));
    expect(parseUsd("90000000000000.00")).toEqual(usd(9000000000000000));
    expect(formatUsd(parseUsd("310.05"))).toBe("USD 310.05");
  });
  it.each([
    "1.001",
    "-1",
    "1e2",
    "01",
    " 1",
    "1.",
    ".5",
    "NaN",
    "90000000000000.01",
  ])("rejects invalid or unbounded amount %s", (value) => {
    expect(() => parseUsd(value)).toThrow(InvoiceClientError);
  });
  it.each([
    usd(0.5),
    usd(-1),
    usd(Number.MAX_SAFE_INTEGER + 1),
    { currency: "KHR", minor_units: 100 },
    { currency: "USD", minor_units: "100" },
  ])("fails closed on malformed money", (value) => {
    expect(() => money(value)).toThrow(InvoiceClientError);
  });
  it("encodes IDs and filters and requires capability metadata", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response([invoice()]));
    vi.stubGlobal("fetch", fetcher);
    const result = await invoiceApi.list("property/one", {
      status: "UNPAID",
      customer_id: "c&x",
      cursor: "a+b",
    });
    expect(result.capabilities).toEqual(["invoices.issue"]);
    expect(result.next_cursor).toBe("next-token");
    expect(fetcher.mock.calls[0]?.[0]).toContain(
      "/properties/property%2Fone/invoices?",
    );
    expect(fetcher.mock.calls[0]?.[0]).toContain("customer_id=c%26x");
    expect(fetcher.mock.calls[0]?.[0]).toContain("cursor=a%2Bb");
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      credentials: "include",
      method: "GET",
    });
    expect(result.items[0]?.lines[0]?.source).toEqual({ id: "lease" });
  });
  it("sends version, CSRF and unchanged idempotency identity with allowlisted body only", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response(invoice()));
    vi.stubGlobal("fetch", fetcher);
    await invoiceApi.adjust(
      "invoice/one",
      {
        invoice_line_id: "line",
        adjustment_type: "CREDIT",
        amount: parseUsd("15.00"),
        source_reference: "approved",
        reason: "correction",
      },
      2,
      "same-key",
    );
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/invoices/invoice%2Fone/adjustments",
    );
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: {
        "X-CSRF-Token": "csrf token",
        "Idempotency-Key": "same-key",
        "If-Match": '"2"',
      },
    });
    expect(bodyOf(fetcher.mock.calls[0]?.[1])).toEqual({
      invoice_line_id: "line",
      adjustment_type: "CREDIT",
      amount: usd(1500),
      source_reference: "approved",
      reason: "correction",
    });
  });
  it("covers draft creation, correction, issue and void command shapes", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(response(invoice())));
    vi.stubGlobal("fetch", fetcher);
    await invoiceApi.create("property", "obligation", "k1");
    await invoiceApi.correctDraft("invoice", "new-source", "reason", 2, "k2");
    await invoiceApi.issue("invoice", 2, "k3");
    await invoiceApi.void("invoice", "invalid", 2, "k4");
    expect(fetcher.mock.calls.map((call) => bodyOf(call[1]))).toEqual([
      { authorized_nonrecurring_obligation_id: "obligation" },
      { authorized_nonrecurring_obligation_id: "new-source", reason: "reason" },
      {},
      { reason: "invalid" },
    ]);
    expect(fetcher.mock.calls[1]?.[1]?.method).toBe("PATCH");
  });
  it("fails before fetch without CSRF or with an invalid version", async () => {
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "",
    });
    await expect(invoiceApi.issue("id", 1, "key")).rejects.toMatchObject({
      code: "CSRF_UNAVAILABLE",
      outcomeUnknown: false,
    });
    await expect(
      invoiceApi.issue("id", 2147483648, "key"),
    ).rejects.toMatchObject({ code: "INVALID_VERSION" });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("never automatically retries an unknown mutation outcome", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new Error("private diagnostics"));
    vi.stubGlobal("fetch", fetcher);
    await expect(invoiceApi.issue("id", 2, "key")).rejects.toMatchObject({
      code: "NETWORK",
      outcomeUnknown: true,
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await expect(invoiceApi.get("id")).rejects.toMatchObject({
      outcomeUnknown: false,
    });
  });
  it.each([500, 502, 503])(
    "keeps mutation outcome unknown for %s",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn<typeof fetch>()
          .mockResolvedValue(new Response("not JSON", { status })),
      );
      await expect(invoiceApi.issue("id", 2, "key")).rejects.toMatchObject({
        status,
        outcomeUnknown: true,
      });
    },
  );
  it("reports stale version without reflecting arbitrary server content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "INVOICE_VERSION_CONFLICT",
              current_version: 3,
              message: "private secret",
            },
          }),
          { status: 412 },
        ),
      ),
    );
    await expect(invoiceApi.issue("id", 2, "key")).rejects.toMatchObject({
      status: 412,
      currentVersion: 3,
      outcomeUnknown: false,
    });
  });
  it("treats malformed successful mutation as unknown and rejects invalid invoice amounts", async () => {
    const malformed = { ...invoice(), adjusted_total: usd(1.5) };
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockImplementation(() => Promise.resolve(response(malformed))),
    );
    await expect(invoiceApi.issue("id", 2, "key")).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      outcomeUnknown: true,
    });
    await expect(invoiceApi.get("id")).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
      outcomeUnknown: false,
    });
  });
  it("uses exact late decision amounts and all three append-only correction kinds", async () => {
    const charge = {
      id: "charge",
      property_id: "p",
      customer_id: "c",
      original_amount: usd(1500),
      adjusted_obligation: usd(1000),
      remaining_balance: usd(1000),
      corrections: [],
    };
    const decision = {
      id: "decision",
      property_id: "p",
      customer_id: "c",
      source_invoice: { id: "i" },
      outcome: "REDUCED",
      approved_amount: usd(1500),
      calculated_default_amount: usd(3100),
      charge: { id: "charge" },
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(decision))
      .mockImplementation(() => Promise.resolve(response(charge)));
    vi.stubGlobal("fetch", fetcher);
    await invoiceApi.decide("i", "REDUCED", parseUsd("15"), "approved", "k");
    await invoiceApi.correctCharge(
      "charge",
      { kind: "REDUCTION", amount: parseUsd("5"), reason: "r" },
      "c1",
    );
    await invoiceApi.correctCharge(
      "charge",
      { kind: "CHARGE_REVERSAL", reason: "r" },
      "c2",
    );
    await invoiceApi.correctCharge(
      "charge",
      {
        kind: "REDUCTION_REVERSAL",
        reverses_correction_id: "prior",
        reason: "r",
      },
      "c3",
    );
    expect(fetcher.mock.calls.map((call) => bodyOf(call[1]))).toEqual([
      { outcome: "REDUCED", approved_amount: usd(1500), reason: "approved" },
      { kind: "REDUCTION", amount: usd(500), reason: "r" },
      { kind: "CHARGE_REVERSAL", reason: "r" },
      {
        kind: "REDUCTION_REVERSAL",
        reverses_correction_id: "prior",
        reason: "r",
      },
    ]);
  });
  it("preserves logical run identity, kind, dates and period through an exact replay", async () => {
    const input = {
      logical_run_key: "rent:2026-09",
      business_date: "2026-09-01",
      period_start: "2026-09-01",
      period_end: "2026-09-30",
    };
    const result = {
      id: "run",
      property_id: "p",
      run_kind: "RENT",
      logical_run_key: input.logical_run_key,
      business_date: input.business_date,
      period: { start: input.period_start, end: input.period_end },
      status: "COMPLETE",
      attempts: [],
    };
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(response(result)));
    vi.stubGlobal("fetch", fetcher);
    const pending = {
      key: "same",
      command: {
        action: "run" as const,
        propertyId: "p",
        kind: "rent" as const,
        input,
      },
    };
    await executeBilling(invoiceApi, pending);
    await executeBilling(invoiceApi, pending);
    expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]);
    expect(bodyOf(fetcher.mock.calls[0]?.[1])).toEqual(input);
  });
});
