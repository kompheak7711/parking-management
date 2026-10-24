import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CustomerConflictError,
  CustomerIdNumberInUseError,
  type CustomerDetail,
  CustomerIdempotencyReuseError,
  CustomerRequestError,
  CustomerUnavailableError,
  customerApi,
} from "./customerClient";

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(document, "cookie", { configurable: true, value: "" });
});

const current = {
  customer_id: "customer-1",
  legal_name: "Dara Sok",
  phone_number: null,
  email_address: null,
  contact_address: null,
  memo: null,
  id_document_number: "N0123456",
  version: 4,
  active: true,
  deactivated_at: null,
  deactivation_reason: null,
  relationships: {
    reservations: [],
    primary_tenant_leases: [],
    signer_leases: [],
    occupancies: [],
    invoices: [],
    payments: [],
    customer_credit: [],
    refunds: [],
  },
  audit_history: [],
  audit_history_next_cursor: null,
  can_manage: true,
  can_deactivate: true,
  can_view_audit: false,
  audit_history_available: false,
} satisfies CustomerDetail;

describe("Customer API client", () => {
  it("TEST-FE-037 parses the canonical bounded Customer list envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            data: [
              {
                customer_id: "customer-1",
                legal_name: "Dara Sok",
                active: true,
                relationship_indicators: [],
              },
            ],
            page: { next_cursor: "opaque-next", limit: 100 },
            meta: { request_id: "request-1", can_manage: true },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(customerApi.list("property-1")).resolves.toEqual({
      items: [
        {
          customer_id: "customer-1",
          legal_name: "Dara Sok",
          active: true,
          relationship_indicators: [],
        },
      ],
      next_cursor: "opaque-next",
      can_manage: true,
    });
  });

  it("TEST-FE-038 preserves minimized reuse candidates and sends CSRF", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "CUSTOMER_REUSE_REQUIRED",
            reuse_candidates: [
              { customer_id: "customer-1", legal_name: "Dara Sok" },
            ],
          },
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const error = await customerApi
      .create(
        "property-1",
        "customer-command-1",
        {
          legal_name: "Dara S.",
        },
        "11111111-1111-4111-8111-111111111111",
      )
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CustomerConflictError);
    expect((error as CustomerConflictError).candidates).toEqual([
      {
        customer_id: "customer-1",
        legal_name: "Dara Sok",
        active: true,
        relationship_indicators: [],
      },
    ]);
    expect(
      new Headers(fetchMock.mock.calls[0]?.[1]?.headers).get("X-CSRF-Token"),
    ).toBe("csrf-token");
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/properties/property-1/customers",
    );
    const requestBody = fetchMock.mock.calls[0]?.[1]?.body;
    expect(typeof requestBody).toBe("string");
    if (typeof requestBody !== "string") {
      throw new Error("Customer creation body was not serialized JSON");
    }
    expect(JSON.parse(requestBody)).toMatchObject({
      customer_id: "customer-command-1",
      legal_name: "Dara S.",
    });
  });

  it("TEST-FE-039 sends the exact optimistic version on Customer updates", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response(null, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      customerApi.update(
        current,
        { legal_name: "Dara Sok II" },
        "22222222-2222-4222-8222-222222222222",
      ),
    ).rejects.toBeInstanceOf(CustomerConflictError);
    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-token");
    expect(headers.get("If-Match")).toBe('"4"');
  });

  it("TEST-FE-129 keeps API-016 idempotency-key reuse on the unresolved command path", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: { code: "IDEMPOTENCY_KEY_REUSED" },
            meta: { request_id: "request-idempotency-reuse" },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const caught = await customerApi
      .update(
        current,
        { legal_name: "Different canonical input" },
        "22222222-2222-4222-8222-222222222222",
      )
      .catch((error: unknown) => error);

    expect(caught).toBeInstanceOf(CustomerIdempotencyReuseError);
    expect(caught).toMatchObject({
      outcomeUnknown: true,
      requestId: "request-idempotency-reuse",
    });
  });

  it("TEST-FE-049 treats a concealed Customer 404 as access loss", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "NOT_FOUND" } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(customerApi.get("customer-1")).rejects.toBeInstanceOf(
      CustomerUnavailableError,
    );
  });

  it("TEST-FE-089 parses authoritative present and absent creation status", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: { recorded: true, expired: false, customer: current },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: { recorded: false, expired: false, customer: null },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            data: { recorded: true, expired: true, customer: current },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      customerApi.commandStatus(
        "property-1",
        "customer-command-1",
        "create",
        "command-1",
      ),
    ).resolves.toEqual({ recorded: true, expired: false, customer: current });
    await expect(
      customerApi.commandStatus(
        "property-1",
        "customer-command-2",
        "create",
        "command-2",
      ),
    ).resolves.toEqual({ recorded: false, expired: false, customer: null });
    await expect(
      customerApi.commandStatus(
        "property-1",
        "customer-command-3",
        "update",
        "command-3",
      ),
    ).resolves.toEqual({ recorded: true, expired: true, customer: current });
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/properties/property-1/customers/customer-command-1/command-status?action=create&idempotency_key=command-1",
      "/api/v1/properties/property-1/customers/customer-command-2/command-status?action=create&idempotency_key=command-2",
      "/api/v1/properties/property-1/customers/customer-command-3/command-status?action=update&idempotency_key=command-3",
    ]);
  });

  it("TEST-FE-053 preserves safe validation fields and correlation ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "VALIDATION_ERROR",
              message: "The request did not match the required schema.",
              fields: ["body.memo"],
            },
            meta: { request_id: "request-validation-1" },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const error = await customerApi
      .get("customer-1")
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CustomerRequestError);
    expect(error).toMatchObject({
      message: "The request did not match the required schema.",
      fields: ["body.memo"],
      requestId: "request-validation-1",
    });
  });

  it("TEST-FE-077 classifies ambiguous Customer creation outcomes", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockRejectedValueOnce(new TypeError("connection closed"))
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({ data: { customer_id: "customer-2" } }),
            {
              status: 201,
              headers: { "Content-Type": "application/json" },
            },
          ),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ error: { code: "UNAVAILABLE" } }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );

    for (const legalName of [
      "Network outcome",
      "Malformed response",
      "Server failure",
    ]) {
      const error = await customerApi
        .create(
          "property-1",
          `customer-${legalName}`,
          {
            legal_name: legalName,
          },
          "33333333-3333-4333-8333-333333333333",
        )
        .catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(CustomerRequestError);
      expect(error).toMatchObject({ outcomeUnknown: true });
    }
  });

  it("TEST-FE-086 classifies malformed successful update and deactivation responses as unknown", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          new Response("null", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify("committed"), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    );

    const updateError = await customerApi
      .update(
        current,
        { memo: "possibly saved" },
        "44444444-4444-4444-8444-444444444444",
      )
      .catch((caught: unknown) => caught);
    expect(updateError).toBeInstanceOf(CustomerRequestError);
    expect(updateError).toMatchObject({ outcomeUnknown: true });

    const deactivateError = await customerApi
      .deactivate(
        current,
        "possibly deactivated",
        "55555555-5555-4555-8555-555555555555",
      )
      .catch((caught: unknown) => caught);
    expect(deactivateError).toBeInstanceOf(CustomerRequestError);
    expect(deactivateError).toMatchObject({ outcomeUnknown: true });
  });

  it("TEST-FE-V059B-02 names the Customer that already has the ID number", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=csrf-token",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "CUSTOMER_ID_NUMBER_IN_USE",
              fields: ["id_document_number"],
              existing_customer: {
                customer_id: "customer-1",
                legal_name: "Dara Sok",
              },
            },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const error = await customerApi
      .create(
        "property-1",
        "customer-command-2",
        { legal_name: "Dara S.", id_document_number: "n 0123-456" },
        "22222222-2222-4222-8222-222222222222",
      )
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CustomerIdNumberInUseError);
    expect((error as CustomerIdNumberInUseError).message).toBe(
      "Another Customer (Dara Sok) already has this ID number or passport number. Use the existing Customer.",
    );
    expect((error as CustomerIdNumberInUseError).candidates).toEqual([
      {
        customer_id: "customer-1",
        legal_name: "Dara Sok",
        active: true,
        relationship_indicators: [],
      },
    ]);
  });
});
