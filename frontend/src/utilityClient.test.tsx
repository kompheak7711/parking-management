import { afterEach, describe, expect, it, vi } from "vitest";

import {
  UtilityClientError,
  UtilityConflictError,
  utilityApi,
} from "./utilityClient";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  Object.defineProperty(document, "cookie", { configurable: true, value: "" });
});

function response(data: unknown, status = 200, page?: object): Response {
  return new Response(
    JSON.stringify({ data, page, meta: { request_id: "utility-test" } }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

const meter = {
  id: "10000000-0000-4000-8000-000000000001",
  property_id: "10000000-0000-4000-8000-000000000002",
  unit_id: "10000000-0000-4000-8000-000000000003",
  utility_type: "ELECTRICITY",
  serial_number: "ELEC-301",
  measurement_unit_code: "KWH",
  description: null,
  installed_date: "2026-08-01",
  failure_date: null,
  deactivated_date: null,
  current: true,
  version: 2,
  memo: null,
  replacement: {
    replaced_meter_id: null,
    replacement_meter_id: null,
    replacement_date: null,
  },
  readings_url: "/api/v1/meters/10000000-0000-4000-8000-000000000001/readings",
};

describe("Utility client", () => {
  it("TEST-FE-213 preserves deterministic pagination cursors", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        response([meter], 200, { limit: 25, next_cursor: "next meter" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      utilityApi.loadMeters("unit/id", "current cursor"),
    ).resolves.toMatchObject({ nextCursor: "next meter", items: [meter] });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "/api/v1/units/unit%2Fid/meters?limit=25&cursor=current%20cursor",
    );
  });

  it("TEST-FE-214 sends CSRF and idempotency evidence without calculating", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=utility-token",
    });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response(meter));
    vi.stubGlobal("fetch", fetchMock);
    await utilityApi.installMeter(
      meter.unit_id,
      {
        utility_type: "ELECTRICITY",
        serial_number: "ELEC-301",
        measurement_unit_code: "KWH",
        description: null,
        installed_date: "2026-08-01",
        memo: null,
        initial_reading: {
          reading_date: "2026-08-01",
          reading_value: "10.000000",
          source_evidence: "Photograph ref 1",
        },
      },
      "10000000-0000-4000-8000-000000000004",
    );
    const init = fetchMock.mock.calls[0]?.[1];
    const headers = new Headers(init?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("utility-token");
    expect(headers.get("Idempotency-Key")).toBe(
      "10000000-0000-4000-8000-000000000004",
    );
    expect(init?.body).toContain('"reading_value":"10.000000"');
  });

  it("TEST-FE-215 parses the authoritative pending broken-Meter state", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=utility-token",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        response({
          status: "PENDING_FUTURE_ACTUAL_BASIS",
          property_id: meter.property_id,
          unit_id: meter.unit_id,
          utility_type: "ELECTRICITY",
          consumption_period_id: null,
          calculation_kind: null,
          period_start: "2026-08-02",
          period_end: "2026-08-31",
          consumption_quantity: null,
          represented_days: 30,
          meter_id: null,
          start_reading_id: null,
          end_reading_id: null,
          failed_meter_id: meter.id,
          replacement_meter_id: "10000000-0000-4000-8000-000000000005",
          basis_kind: null,
          basis_period_ids: [],
          basis_sources: [],
          total_basis_consumption: null,
          total_basis_days: null,
          weighted_daily_average: null,
          generation_date: null,
          rate_id: null,
          rate_effective_date: null,
          rate_usd_per_unit: null,
          amount_usd_cents: null,
        }),
      ),
    );
    await expect(
      utilityApi.preview({
        property_id: meter.property_id,
        source_kind: "ESTIMATION_CASE",
        source_id: "10000000-0000-4000-8000-000000000006",
        generation_at: "2026-08-31T12:00:00+07:00",
      }),
    ).resolves.toMatchObject({
      status: "PENDING_FUTURE_ACTUAL_BASIS",
      amount_usd_cents: null,
      basis_period_ids: [],
    });
  });

  it("TEST-FE-216 safely classifies conflict and malformed envelopes", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=utility-token",
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response({}, 409))
      .mockResolvedValueOnce(response({ ...meter, utility_type: "GAS" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      utilityApi.recordReading(
        meter.id,
        {
          expected_meter_version: 2,
          reading_date: "2026-08-31",
          reading_value: "20",
          source_kind: "MANUAL",
          source_evidence: "Photo",
        },
        "10000000-0000-4000-8000-000000000007",
      ),
    ).rejects.toBeInstanceOf(UtilityConflictError);
    await expect(utilityApi.loadMeters(meter.unit_id)).rejects.toBeInstanceOf(
      UtilityClientError,
    );
  });
});
