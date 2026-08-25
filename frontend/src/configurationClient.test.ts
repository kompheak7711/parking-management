import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EffectiveConfigurationConflictError,
  EffectiveConfigurationError,
  EffectiveConfigurationUnavailableError,
  effectiveConfigurationApi,
} from "./configurationClient";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "cookie", { configurable: true, value: "" });
});

function apiResponse(
  data: unknown,
  status = 200,
  meta: object = { request_id: "configuration-client-test" },
): Response {
  return new Response(JSON.stringify({ data, meta }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function pageResponse(
  data: unknown[],
  nextCursor: string | null = null,
): Response {
  return new Response(
    JSON.stringify({
      data,
      page: { limit: 25, next_cursor: nextCursor },
      meta: { request_id: "configuration-client-page" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

describe("effective configuration client", () => {
  it("TEST-FE-165 loads only bounded histories after capability discovery", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        apiResponse({
          read: true,
          manage_service_rates: true,
          manage_utility_rates: false,
          manage_exchange_rates: false,
        }),
      )
      .mockResolvedValueOnce(pageResponse([], "next-configured-service"))
      .mockResolvedValueOnce(pageResponse([]))
      .mockResolvedValueOnce(pageResponse([]))
      .mockResolvedValueOnce(pageResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      effectiveConfigurationApi.load("property/28"),
    ).resolves.toMatchObject({
      capabilities: { read: true, manage_service_rates: true },
      configuredServices: [],
      configuredServiceNextCursor: "next-configured-service",
      serviceRates: [],
      utilityRates: [],
      exchangeRates: [],
    });
    expect(fetchMock.mock.calls.map(([url]) => requestUrl(url))).toEqual([
      "/api/v1/properties/property%2F28/configuration-capabilities",
      "/api/v1/properties/property%2F28/configured-services?limit=25",
      "/api/v1/properties/property%2F28/service-rates?limit=25",
      "/api/v1/properties/property%2F28/utility-rates?limit=25",
      "/api/v1/properties/property%2F28/exchange-rates?limit=25",
    ]);
  });

  it("TEST-FE-166 does not fetch history when server read capability is absent", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      apiResponse({
        read: false,
        manage_service_rates: false,
        manage_utility_rates: false,
        manage_exchange_rates: false,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      effectiveConfigurationApi.load("property-28"),
    ).rejects.toBeInstanceOf(EffectiveConfigurationUnavailableError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-167 sends CSRF and one UUID idempotency key for an append command", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=configuration-token",
    });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      apiResponse({
        id: "50000000-0000-4000-8000-000000000028",
        property_service_id: "60000000-0000-4000-8000-000000000028",
        service_code: "TRASH_COLLECTION",
        display_name: "Trash Collection",
        monthly_rate_usd_cents: 1250,
        effective_date: "2026-09-01",
        source_memo: null,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await effectiveConfigurationApi.createServiceRate(
      "property-28",
      {
        property_service_id: "60000000-0000-4000-8000-000000000028",
        monthly_rate_usd_cents: 1250,
        effective_date: "2026-09-01",
        source_memo: null,
      },
      "40000000-0000-4000-8000-000000000028",
    );
    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("configuration-token");
    expect(headers.get("Idempotency-Key")).toBe(
      "40000000-0000-4000-8000-000000000028",
    );
  });

  it("TEST-FE-168 classifies concurrency and idempotency conflicts safely", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=configuration-token",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(apiResponse({}, 409)),
    );
    await expect(
      effectiveConfigurationApi.createUtilityRate(
        "property-28",
        {
          utility_type: "WATER",
          measurement_unit_code: "M3",
          rate_usd_per_unit: "0.5",
          effective_date: "2026-09-01",
          notice_at: "2026-08-01T00:00:00+07:00",
          notice_evidence: "Notice",
          source_memo: null,
        },
        "40000000-0000-4000-8000-000000000029",
      ),
    ).rejects.toBeInstanceOf(EffectiveConfigurationConflictError);
  });

  it("TEST-FE-169 preserves and follows the exact bounded history cursor", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        pageResponse(
          [
            {
              id: "50000000-0000-4000-8000-000000000028",
              property_service_id: "60000000-0000-4000-8000-000000000028",
              service_code: "TRASH_COLLECTION",
              display_name: "Trash Collection",
              monthly_rate_usd_cents: 1250,
              effective_date: "2026-09-01",
              source_memo: null,
            },
          ],
          "bounded-next-cursor",
        ),
      )
      .mockResolvedValueOnce(
        pageResponse(
          [
            {
              id: "60000000-0000-4000-8000-000000000028",
              property_id: "property/28",
              service_code: "TRASH_COLLECTION",
              display_name: "Trash Collection",
            },
          ],
          "bounded-configured-cursor",
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      effectiveConfigurationApi.loadServiceRates(
        "property/28",
        "bounded current cursor",
      ),
    ).resolves.toMatchObject({ nextCursor: "bounded-next-cursor" });
    expect(requestUrl(fetchMock.mock.calls[0]?.[0] ?? "")).toBe(
      "/api/v1/properties/property%2F28/service-rates?limit=25&cursor=bounded+current+cursor",
    );
    await effectiveConfigurationApi.loadConfiguredServices(
      "property/28",
      "configured current cursor",
    );
    expect(requestUrl(fetchMock.mock.calls[1]?.[0] ?? "")).toBe(
      "/api/v1/properties/property%2F28/configured-services?limit=25&cursor=configured+current+cursor",
    );
  });

  it("TEST-FE-175 preserves bounded safe diagnostics from an API failure", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=configuration-token",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "VALIDATION_ERROR",
              message: "unsafe server detail must not cross the boundary",
              fields: ["effective_date", "bad field", "x".repeat(129)],
            },
            meta: { request_id: "configuration-safe-reference" },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const error = await effectiveConfigurationApi
      .createServiceRate(
        "property-28",
        {
          property_service_id: "60000000-0000-4000-8000-000000000028",
          monthly_rate_usd_cents: 1250,
          effective_date: "2026-09-01",
          source_memo: null,
        },
        "40000000-0000-4000-8000-000000000028",
      )
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EffectiveConfigurationError);
    expect(error).toMatchObject({
      fields: ["effective_date"],
      requestId: "configuration-safe-reference",
    });
    expect(String(error)).not.toContain("unsafe server detail");
  });
});
