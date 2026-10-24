import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MeterSerialNumberInUseError,
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

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
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

const reading = {
  id: "10000000-0000-4000-8000-000000000010",
  property_id: meter.property_id,
  meter_id: meter.id,
  unit_id: meter.unit_id,
  utility_type: "ELECTRICITY",
  measurement_unit_code: "KWH",
  reading_date: "2026-08-01",
  original_value: "10.000000",
  effective_value: "10.000000",
  validated: true,
  validated_at: "2026-08-01T12:00:00Z",
  validated_by: "10000000-0000-4000-8000-000000000011",
  source: { kind: "MANUAL", evidence: "Meter photograph" },
  version: 1,
  corrections: [],
};

const rate = {
  id: "10000000-0000-4000-8000-000000000012",
  utility_type: "ELECTRICITY",
  measurement_unit_code: "KWH",
  rate_usd_per_unit: "0.250000",
  effective_date: "2026-08-01",
  notice_at: "2026-07-01T12:00:00+07:00",
  notice_evidence: "Customer notice batch 7",
  source_memo: null,
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

  it("TEST-FE-222 preserves complete paginated mixed pending and validated history", async () => {
    const meters = Array.from({ length: 26 }, (_, index) => ({
      ...meter,
      id: `meter-${String(index + 1)}`,
      serial_number: `ELEC-${String(index + 1)}`,
      readings_url: `/api/v1/meters/meter-${String(index + 1)}/readings`,
    }));
    const rates = Array.from({ length: 26 }, (_, index) => ({
      ...rate,
      id: `rate-${String(index + 1)}`,
      effective_date: `2026-${String((index % 12) + 1).padStart(2, "0")}-01`,
    }));
    const firstMeter = meters[0];
    if (firstMeter === undefined) throw new Error("Meter fixture missing");
    const readings = Array.from({ length: 26 }, (_, index) =>
      index === 25
        ? {
            ...reading,
            id: `reading-${String(index + 1)}`,
            meter_id: firstMeter.id,
            reading_date: "2026-08-26",
            validated: false,
            validated_at: null,
            validated_by: null,
          }
        : {
            ...reading,
            id: `reading-${String(index + 1)}`,
            meter_id: firstMeter.id,
            reading_date: `2026-08-${String(index + 1).padStart(2, "0")}`,
          },
    );
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = new URL(requestUrl(input), "http://localhost");
      const cursor = url.searchParams.get("cursor");
      if (url.pathname.includes("/utility-rates")) {
        return Promise.resolve(
          cursor === null
            ? response(rates.slice(0, 25), 200, {
                limit: 25,
                next_cursor: "rates-2",
              })
            : response(rates.slice(25), 200, {
                limit: 25,
                next_cursor: null,
              }),
        );
      }
      if (url.pathname.includes("/units/")) {
        return Promise.resolve(
          cursor === null
            ? response(meters.slice(0, 25), 200, {
                limit: 25,
                next_cursor: "meters-2",
              })
            : response(meters.slice(25), 200, {
                limit: 25,
                next_cursor: null,
              }),
        );
      }
      if (url.pathname.includes(`/meters/${firstMeter.id}/readings`)) {
        return Promise.resolve(
          cursor === null
            ? response(readings.slice(0, 25), 200, {
                limit: 25,
                next_cursor: "readings-2",
              })
            : response(readings.slice(25), 200, {
                limit: 25,
                next_cursor: null,
              }),
        );
      }
      return Promise.resolve(
        response([], 200, { limit: 25, next_cursor: null }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await utilityApi.load(meter.property_id, meter.unit_id);

    expect(result.meters).toHaveLength(26);
    expect(result.rates).toHaveLength(26);
    expect(result.readings[firstMeter.id]).toHaveLength(26);
    expect(result.readings[firstMeter.id]?.[0]).toMatchObject({
      validated: true,
      validated_at: "2026-08-01T12:00:00Z",
      validated_by: "10000000-0000-4000-8000-000000000011",
    });
    expect(result.readings[firstMeter.id]?.[25]).toMatchObject({
      id: "reading-26",
      validated: false,
      validated_at: null,
      validated_by: null,
    });
    const requestedUrls = fetchMock.mock.calls.map(([input]) =>
      requestUrl(input),
    );
    expect(requestedUrls).toContain(
      `/api/v1/units/${meter.unit_id}/meters?limit=25&cursor=meters-2`,
    );
    expect(requestedUrls).toContain(
      `/api/v1/properties/${meter.property_id}/utility-rates?limit=25&cursor=rates-2`,
    );
    expect(requestedUrls).toContain(
      `/api/v1/meters/${firstMeter.id}/readings?limit=25&cursor=readings-2`,
    );
  });

  it("TEST-FE-223 rejects a repeated cursor without returning partial history", async () => {
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.includes("/utility-rates")) {
        return Promise.resolve(
          response([], 200, { limit: 25, next_cursor: null }),
        );
      }
      return Promise.resolve(
        response([meter], 200, { limit: 25, next_cursor: "repeated" }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      utilityApi.load(meter.property_id, meter.unit_id),
    ).rejects.toBeInstanceOf(UtilityClientError);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[2]?.[0]).toBe(
      `/api/v1/units/${meter.unit_id}/meters?limit=25&cursor=repeated`,
    );
  });

  it("TEST-FE-227 rejects inconsistent Reading validation provenance", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        response(
          [
            {
              ...reading,
              validated: false,
              validated_at: reading.validated_at,
              validated_by: reading.validated_by,
            },
          ],
          200,
          { limit: 25, next_cursor: null },
        ),
      )
      .mockResolvedValueOnce(
        response(
          [{ ...reading, validated_at: null, validated_by: null }],
          200,
          { limit: 25, next_cursor: null },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(utilityApi.loadReadings(meter.id)).rejects.toBeInstanceOf(
      UtilityClientError,
    );
    await expect(utilityApi.loadReadings(meter.id)).rejects.toBeInstanceOf(
      UtilityClientError,
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

  it("TEST-FE-224 parses server-authoritative correction impacts", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=utility-token",
    });
    const correction = {
      id: "10000000-0000-4000-8000-000000000020",
      previous_value: "10.000000",
      corrected_value: "12.000000",
      reason: "Verified photograph",
      occurred_at: "2026-08-02T12:00:00Z",
      actor_id: "10000000-0000-4000-8000-000000000011",
      authorization_reference: "approval-2",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        response({
          reading: {
            ...reading,
            effective_value: "12.000000",
            version: 2,
            corrections: [correction],
          },
          correction,
          affected_calculations: [
            {
              consumption_period_id: "10000000-0000-4000-8000-000000000021",
              previous_consumption_quantity: "20.000000",
              corrected_consumption_quantity: "22.000000",
              billing_effect_kind: "POST_ISSUANCE_ADJUSTMENT",
              issued_line: {
                invoice_line_id: "10000000-0000-4000-8000-000000000022",
                source_invoice_id: "10000000-0000-4000-8000-000000000023",
                calculated_difference_usd_cents: 50,
                invoice_adjustment_id: "10000000-0000-4000-8000-000000000024",
              },
            },
          ],
        }),
      ),
    );

    await expect(
      utilityApi.correctReading(
        reading.id,
        {
          expected_version: 1,
          corrected_value: "12.000000",
          reason: "Verified photograph",
          authorization_reference: "approval-2",
        },
        "10000000-0000-4000-8000-000000000025",
      ),
    ).resolves.toMatchObject({
      reading: { original_value: "10.000000", effective_value: "12.000000" },
      affected_calculations: [
        {
          billing_effect_kind: "POST_ISSUANCE_ADJUSTMENT",
          issued_line: {
            calculated_difference_usd_cents: 50,
            invoice_adjustment_id: "10000000-0000-4000-8000-000000000024",
          },
        },
      ],
    });
  });

  it("TEST-FE-228 sends ATOMIC_ALL envelope identity and preserves ordered replay-safe results", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=utility-token",
    });
    const envelopeKey = "10000000-0000-4000-8000-000000000030";
    const itemKeys = [
      "10000000-0000-4000-8000-000000000031",
      "10000000-0000-4000-8000-000000000032",
    ];
    const items = itemKeys.map((idempotencyKey, index) => ({
      idempotency_key: idempotencyKey,
      meter_id: meter.id,
      reading: {
        expected_meter_version: index + 2,
        reading_date: index === 0 ? "2026-08-31" : "2026-09-30",
        reading_value: index === 0 ? "20.000000" : "30.000000",
        source_kind: "MANUAL" as const,
        source_evidence: `Photograph ${String(index + 1)}`,
      },
    }));
    const atomicResponse = {
      mode: "ATOMIC_ALL",
      items: items.map((item, index) => ({
        index,
        idempotency_key: item.idempotency_key,
        status: "SUCCEEDED",
        reading: {
          ...reading,
          id: `10000000-0000-4000-8000-00000000004${String(index)}`,
          reading_date: item.reading.reading_date,
          effective_value: item.reading.reading_value,
        },
        error: null,
      })),
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(atomicResponse))
      .mockResolvedValueOnce(response(atomicResponse))
      .mockResolvedValueOnce(response({}, 409))
      .mockResolvedValueOnce(response({}, 422));
    vi.stubGlobal("fetch", fetchMock);

    const success = await utilityApi.recordBatch(
      meter.property_id,
      "ATOMIC_ALL",
      items,
      envelopeKey,
    );
    await expect(
      utilityApi.recordBatch(
        meter.property_id,
        "ATOMIC_ALL",
        items,
        envelopeKey,
      ),
    ).resolves.toEqual(success);
    const firstItem = items[0];
    const secondItem = items[1];
    if (firstItem === undefined || secondItem === undefined) {
      throw new Error("Atomic item fixtures missing");
    }
    await expect(
      utilityApi.recordBatch(
        meter.property_id,
        "ATOMIC_ALL",
        [
          {
            ...firstItem,
            reading: { ...firstItem.reading, reading_value: "21.000000" },
          },
          secondItem,
        ],
        envelopeKey,
      ),
    ).rejects.toBeInstanceOf(UtilityConflictError);
    await expect(
      utilityApi.recordBatch(
        meter.property_id,
        "ATOMIC_ALL",
        items,
        "10000000-0000-4000-8000-000000000033",
      ),
    ).rejects.toBeInstanceOf(UtilityClientError);

    expect(success.map((item) => item.index)).toEqual([0, 1]);
    expect(success.map((item) => item.idempotency_key)).toEqual(itemKeys);
    expect(success.map((item) => item.reading?.effective_value)).toEqual([
      "20.000000",
      "30.000000",
    ]);
    for (const [, init] of fetchMock.mock.calls) {
      if (typeof init?.body !== "string") {
        throw new Error("Atomic request body missing");
      }
      const body = JSON.parse(init.body) as { mode: string };
      expect(body.mode).toBe("ATOMIC_ALL");
      expect(body.mode).not.toBe("PARTIAL");
    }
    expect(
      fetchMock.mock.calls
        .slice(0, 3)
        .map(([, init]) => new Headers(init?.headers).get("Idempotency-Key")),
    ).toEqual([envelopeKey, envelopeKey, envelopeKey]);
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

  it("TEST-FE-V059B-01 names a Meter serial already used in the Property", async () => {
    Object.defineProperty(document, "cookie", {
      configurable: true,
      value: "__Host-prm_csrf=utility-token",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "METER_SERIAL_NUMBER_IN_USE",
              fields: ["serial_number"],
            },
            meta: { request_id: "serial-in-use" },
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const install = utilityApi.installMeter(
      meter.unit_id,
      {
        utility_type: "WATER",
        serial_number: "WA-U101",
        measurement_unit_code: "M3",
        description: null,
        installed_date: "2026-08-01",
        memo: null,
        initial_reading: {
          reading_date: "2026-08-01",
          reading_value: "1.000000",
          source_evidence: "Photograph ref 1",
        },
      },
      "10000000-0000-4000-8000-000000000005",
    );
    await expect(install).rejects.toBeInstanceOf(MeterSerialNumberInUseError);
    await expect(install).rejects.toMatchObject({
      fields: ["serial_number"],
      message:
        "Another Meter of this Property, current or replaced, already has this serial number.",
    });
  });
});
