import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  InvoiceClientError,
  BillingRun,
  billingRunRetry,
  executeBilling,
  formatUsd,
  invoiceApi,
  money,
  parseUsd,
} from "./invoiceClient";
function required<T>(value: T | null | undefined): T {
  if (value === null || value === undefined)
    throw new Error("Missing test value");
  return value;
}
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
  it.each([
    "valid",
    "foreign",
    "malformed",
    "key-conflict",
    "server-error",
    "read",
  ])(
    "decodes only the exact terminal decision conflict: %s",
    async (variant) => {
      const state = {
        id: "decision",
        property_id: "property/one",
        customer_id: "customer",
        source_invoice: { id: variant === "foreign" ? "other" : "invoice/one" },
        outcome: variant === "malformed" ? "PENDING" : "CONFIRMED_DEFAULT",
        approved_amount: usd(3100),
        calculated_default_amount: usd(3100),
        charge: { id: "charge" },
      };
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({
              error: {
                code:
                  variant === "key-conflict"
                    ? "IDEMPOTENCY_KEY_REUSED"
                    : "CONFLICT",
                current_state: state,
              },
              meta: { request_id: "conflict-123" },
            }),
            { status: variant === "server-error" ? 503 : 409 },
          ),
        ),
      );
      const result = await (
        variant === "read"
          ? invoiceApi.lateDecision("invoice/one")
          : invoiceApi.decide(
              "invoice/one",
              "WAIVED",
              parseUsd("0"),
              "reason",
              "saved",
            )
      ).catch((error: unknown) => error);
      expect(result).toBeInstanceOf(InvoiceClientError);
      expect(result).toMatchObject({ requestId: "conflict-123" });
      if (variant === "valid")
        expect(result).toMatchObject({
          currentDecision: {
            id: "decision",
            source_invoice: { id: "invoice/one" },
            outcome: "CONFIRMED_DEFAULT",
          },
        });
      else expect(result).toMatchObject({ currentDecision: null });
    },
  );
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
    { currency: "USD", minor_units: -(1n << 63n) - 1n },
    usd(Number.MAX_SAFE_INTEGER + 1),
    { currency: "KHR", minor_units: 100 },
    { currency: "USD", minor_units: "100" },
  ])("fails closed on malformed money", (value) => {
    expect(() => money(value)).toThrow(InvoiceClientError);
  });
  it("encodes IDs and filters and accepts capability metadata", async () => {
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
  it("TEST-052 accepts a DRAFT one-time charge whose Due Date is not set until issue", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          response([{ ...invoice(), status: "DRAFT", due_date: null }]),
        ),
    );
    const result = await invoiceApi.list("property/one", {});
    expect(result.items[0]?.status).toBe("DRAFT");
    expect(result.items[0]?.due_date).toBeNull();
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

describe("V1-047 correction transport regressions", () => {
  it("keeps canonical list data when visibility metadata is absent", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: [invoice()],
            page: { next_cursor: null, limit: 50 },
            meta: { request_id: "read-1" },
          }),
        ),
      ),
    );
    const result = await invoiceApi.list("property/one");
    expect(result.items).toHaveLength(1);
    expect(result.capabilities).toEqual([]);
  });
  it.each([
    ["9000000000000001", "USD 90000000000000.01"],
    ["9007199254740991", "USD 90071992547409.91"],
    ["9007199254740992", "USD 90071992547409.92"],
    ["9007199254740993", "USD 90071992547409.93"],
    ["9223372036854775806", "USD 92233720368547758.06"],
    ["9223372036854775807", "USD 92233720368547758.07"],
  ])(
    "decodes raw JSON integer money %s losslessly on successful commands",
    async (literal, display) => {
      const raw = JSON.stringify({ data: invoice() }).replaceAll(
        '"minor_units":31000',
        '"minor_units":' + literal,
      );
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(raw)));
      const result = await invoiceApi.create("property", "obligation", "key");
      expect(BigInt(result.original_total.minor_units)).toBe(BigInt(literal));
      expect(formatUsd(result.adjusted_total)).toBe(display);
      expect(formatUsd(required(result.lines[0]).adjusted_amount)).toBe(
        display,
      );
      expect(formatUsd(money(result.evidence.original_total))).toBe(display);
    },
  );
  it("preserves the signed-bigint lower boundary in raw immutable monetary evidence", async () => {
    const raw = JSON.stringify({
      data: { ...invoice(), adjustments: [{ amount: usd(1) }] },
    }).replace('"minor_units":1}', '"minor_units":-9223372036854775808}');
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(raw)));
    const result = await invoiceApi.get("id");
    expect(formatUsd(money(result.adjustments[0]?.amount))).toBe(
      "USD -92233720368547758.08",
    );
    expect(formatUsd(money(usd(-1)))).toBe("USD -0.01");
  });
  it.each([
    "9223372036854775808",
    "-9223372036854775809",
    "1.0000000000000000001",
    "9007199254740990.1",
    '"9223372036854775807"',
  ])(
    "rejects malformed or out-of-range raw money %s without rounded success",
    async (literal) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(
              JSON.stringify({ data: invoice() }).replace(
                '"minor_units":31000',
                '"minor_units":' + literal,
              ),
            ),
          ),
      );
      await expect(invoiceApi.issue("id", 1, "key")).rejects.toMatchObject({
        code: "INVALID_RESPONSE",
        outcomeUnknown: true,
      });
    },
  );
  it("never serializes response-only amounts as financial command input", async () => {
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    expect(() =>
      invoiceApi.decide(
        "id",
        "CONFIRMED_DEFAULT",
        { currency: "USD", minor_units: 9223372036854775807n },
        "reason",
        "key",
      ),
    ).toThrow(InvoiceClientError);
    expect(() =>
      invoiceApi.decide(
        "id",
        "WAIVED",
        { currency: "USD", minor_units: -1n },
        "reason",
        "key",
      ),
    ).toThrow(InvoiceClientError);
    expect(fetcher).not.toHaveBeenCalled();
    fetcher.mockResolvedValue(response(invoice()));
    await invoiceApi.adjust(
      "id",
      {
        invoice_line_id: "line",
        adjustment_type: "DEBIT",
        amount: { currency: "USD", minor_units: 9000000000000000n },
        source_reference: "source",
        reason: "reason",
      },
      1,
      "key",
    );
    expect(fetcher.mock.calls[0]?.[1]?.body).toContain(
      '"minor_units":9000000000000000',
    );
  });
  it("sends the confirming actor on stale-tab replay despite a new CSRF cookie", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=actor-B-token",
    });
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response(invoice()));
    vi.stubGlobal("fetch", fetcher);
    const transmission = {
      actorId: "actor-A",
      signal: new AbortController().signal,
    };
    await executeBilling(
      invoiceApi,
      {
        key: "original-key",
        command: {
          action: "issue",
          propertyId: "property",
          id: "id",
          version: 2,
        },
      },
      transmission,
    );
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      headers: {
        "X-Billing-Actor-ID": "actor-A",
        "X-CSRF-Token": "actor-B-token",
        "Idempotency-Key": "original-key",
      },
      signal: transmission.signal,
    });
  });
  it("stops a cancelled transmission before reading cookies or calling fetch", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    await expect(
      required(invoiceApi.forActor)({
        actorId: "actor-A",
        signal: controller.signal,
      }).issue("id", 1, "key"),
    ).rejects.toMatchObject({
      code: "WORKSPACE_INVALIDATED",
      outcomeUnknown: false,
    });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("reads action visibility at a separate scoped authenticated endpoint", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      response({
        property_id: "property/one",
        billing_capabilities: ["billing.generate"],
      }),
    );
    vi.stubGlobal("fetch", fetcher);
    expect(await required(invoiceApi.capabilities)("property/one")).toEqual([
      "billing.generate",
    ]);
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/properties/property%2Fone/billing-capabilities",
    );
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      credentials: "include",
      method: "GET",
    });
  });
  it("retains only bounded known field paths and safe correlation IDs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "VALIDATION_ERROR",
              message: "password=secret SQL trace",
              fields: [
                "body.reason",
                "body.amount.minor_units",
                "body.reason",
                "body.password",
                "<script>",
                { field: "reason", message: "secret" },
                "x".repeat(1000),
              ],
            },
            meta: { request_id: "correlation_123-abc:4.2" },
          }),
          { status: 422 },
        ),
      ),
    );
    const error = await invoiceApi
      .void("id", "reason", 1, "key")
      .catch((error: unknown) => error);
    expect(error).toMatchObject({
      fields: ["reason", "amount.minor_units"],
      requestId: "correlation_123-abc:4.2",
    });
    expect(JSON.stringify(error)).not.toMatch(/password|secret|script/);
  });
  it("discards unsafe correlation payloads independently of valid errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "PRECONDITION_FAILED",
              current_version: 3,
              fields: [],
            },
            meta: { request_id: "<secret>" },
          }),
          { status: 412 },
        ),
      ),
    );
    await expect(invoiceApi.issue("id", 2, "key")).rejects.toMatchObject({
      code: "PRECONDITION_FAILED",
      currentVersion: 3,
      requestId: null,
    });
  });
});

const retryActor = "11111111-1111-4111-8111-111111111111";
const retryProperty = "22222222-2222-4222-8222-222222222222";
function retryRun(): BillingRun {
  return {
    id: "33333333-3333-4333-8333-333333333333",
    property_id: retryProperty,
    run_kind: "RENT",
    logical_run_key: "rent/2026-09",
    business_date: "2026-08-25",
    status: "RETRYABLE",
    period: { start: "2026-09-01", end: "2026-09-30" },
    attempts: [],
    evidence: {
      idempotency_key: "44444444-4444-4444-8444-444444444444",
      requester_actor_id: retryActor,
      invocation_source: "API",
    },
  };
}
describe("inspected billing-run retry identity", () => {
  it("reconstructs the original key, actor/source, kind, Property, logical identity and dates", () => {
    expect(billingRunRetry(retryRun(), retryActor, retryProperty)).toEqual({
      key: "44444444-4444-4444-8444-444444444444",
      command: {
        action: "run",
        propertyId: retryProperty,
        kind: "rent",
        input: {
          logical_run_key: "rent/2026-09",
          business_date: "2026-08-25",
          period_start: "2026-09-01",
          period_end: "2026-09-30",
        },
      },
    });
  });
  it.each([
    { idempotency_key: null },
    { idempotency_key: "malformed" },
    { idempotency_key: "00000000-0000-0000-0000-000000000000" },
    { requester_actor_id: null },
    { requester_actor_id: "55555555-5555-4555-8555-555555555555" },
    { invocation_source: "SCHEDULED" },
    { invocation_source: null },
  ])(
    "refuses missing, malformed or foreign invocation identity %s",
    (changes) => {
      const run = retryRun();
      for (const [key, value] of Object.entries(changes)) {
        if (typeof value === "string") run.evidence[key] = value;
        else if (value === null) run.evidence[key] = null;
      }
      expect(billingRunRetry(run, retryActor, retryProperty)).toBeNull();
    },
  );
  it.each([
    { logical_run_key: "" },
    { logical_run_key: "x".repeat(201) },
    { business_date: "2026-02-30" },
    { period: { start: "2026-09-30", end: "2026-09-01" } },
    { period: { start: "2026-01-01", end: "2026-09-30" } },
    { property_id: "55555555-5555-4555-8555-555555555555" },
  ])("refuses invalid saved canonical run inputs %s", (changes) => {
    expect(
      billingRunRetry({ ...retryRun(), ...changes }, retryActor, retryProperty),
    ).toBeNull();
  });
});

describe("V1-055 one-time charge transport", () => {
  const input = {
    charge_id: "11111111-1111-4111-8111-111111111111",
    category: "DAMAGE_CHARGES" as const,
    customer_id: "customer",
    lease_id: null,
    inspection_damage_finding_id: null,
    description: "Broken window",
    amount: { currency: "USD" as const, minor_units: 4550 },
    reason: "Tenant damage",
    evidence_reference: "INSPECTION-9",
  };
  const snapshot = {
    obligation_id: input.charge_id,
    category: "DAMAGE_CHARGES",
    customer_id: "customer",
    lease_id: null,
    inspection_damage_finding_id: null,
    description: "Broken window",
    amount_usd_cents: 4550,
    reason: "Tenant damage",
    evidence_reference: "INSPECTION-9",
  };
  it("posts integer cents with the sealed identity and replays the exact request", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(() => Promise.resolve(response(snapshot)));
    vi.stubGlobal("fetch", fetcher);
    const pending = {
      key: "same-key",
      command: { action: "oneTimeCharge" as const, propertyId: "p/1", input },
    };
    const result = await executeBilling(invoiceApi, pending);
    await executeBilling(invoiceApi, pending);
    expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]);
    const [path, init] = fetcher.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/properties/p%2F1/one-time-charges");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("same-key");
    expect(bodyOf(init)).toEqual({
      charge_id: input.charge_id,
      category: "DAMAGE_CHARGES",
      customer_id: "customer",
      lease_id: null,
      inspection_damage_finding_id: null,
      description: "Broken window",
      amount_usd_cents: 4550,
      reason: "Tenant damage",
      evidence_reference: "INSPECTION-9",
    });
    expect("obligation_id" in result && result.obligation_id).toBe(
      input.charge_id,
    );
    expect(formatUsd(money(input.amount))).toBe("USD 45.50");
  });
  it("rejects a malformed one-time charge response and keeps the outcome unknown", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(response({ ...snapshot, amount_usd_cents: "45.5" })),
    );
    await expect(
      invoiceApi.recordOneTimeCharge("p", input, "k"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", outcomeUnknown: true });
  });
  it("reports only known invalid one-time charge fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "VALIDATION_ERROR",
              fields: [
                "body.amount_usd_cents",
                "body.evidence_reference",
                "body.secret",
              ],
            },
          }),
          { status: 422 },
        ),
      ),
    );
    await expect(
      invoiceApi.recordOneTimeCharge("p", input, "k"),
    ).rejects.toMatchObject({
      status: 422,
      fields: ["amount_usd_cents", "evidence_reference"],
    });
  });
});

describe("V1-055 due days transport", () => {
  it("sends the Property version as If-Match with days and reason and replays exactly", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() =>
      Promise.resolve(
        response({
          property_id: "p/1",
          one_time_charge_due_days: 14,
          version: 8,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    const pending = {
      key: "due-key",
      command: {
        action: "dueDays" as const,
        propertyId: "p/1",
        days: 14,
        reason: "Owner policy",
        propertyVersion: 7,
      },
    };
    const result = await executeBilling(invoiceApi, pending);
    await executeBilling(invoiceApi, pending);
    expect(fetcher.mock.calls[0]).toEqual(fetcher.mock.calls[1]);
    const [path, init] = fetcher.mock.calls[0] ?? [];
    expect(path).toBe("/api/v1/properties/p%2F1/one-time-charge-due-days");
    expect(init?.method).toBe("POST");
    const headers = new Headers(init?.headers);
    expect(headers.get("If-Match")).toBe('"7"');
    expect(headers.get("Idempotency-Key")).toBe("due-key");
    expect(bodyOf(init)).toEqual({ days: 14, reason: "Owner policy" });
    expect(result).toEqual({
      property_id: "p/1",
      one_time_charge_due_days: 14,
      version: 8,
    });
  });
  it.each([0, 91, 1.5, "14"])(
    "rejects a due days response with the value %s",
    async (days) => {
      vi.stubGlobal(
        "fetch",
        vi.fn<typeof fetch>().mockResolvedValue(
          response({
            property_id: "p",
            one_time_charge_due_days: days,
            version: 2,
          }),
        ),
      );
      await expect(
        invoiceApi.setDueDays("p", 14, "r", 1, "k"),
      ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    },
  );
  it("refuses a Property version beyond the server bound before sending", async () => {
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    await expect(
      invoiceApi.setDueDays("p", 14, "r", 2_147_483_648, "k"),
    ).rejects.toMatchObject({ code: "INVALID_VERSION" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
