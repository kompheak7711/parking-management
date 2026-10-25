import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ReportsNotAllowedError,
  ReportsUnavailableError,
  reportsApi,
} from "./reportsClient";

const PROPERTY = "11111111-1111-4111-8111-111111111111";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const home = {
  as_of: "2026-10-25T03:30:00+00:00",
  business_date: "2026-10-25",
  timezone: "Asia/Phnom_Penh",
  sections: ["leases"],
  cards: { lease_renewal: { count: 1, end_on_or_before: "2026-12-24" } },
  jobs: {},
  todo: [
    {
      kind: "lease_ending",
      date: "2026-10-31",
      group: "this_week",
      lease_id: "22222222-2222-4222-8222-222222222222",
      unit_number: "U204",
    },
  ],
  todo_counts: { overdue: 0, today: 0, this_week: 1, later: 0 },
};

describe("reportsClient", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("TEST-FE-V57-001 reads the Home page of the Property with the session cookie", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(answer({ data: home, meta: { request_id: "r" } }));
    const page = await reportsApi.home(PROPERTY);
    expect(page.cards.lease_renewal?.count).toBe(1);
    expect(page.todo[0]?.group).toBe("this_week");
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(`/api/v1/properties/${PROPERTY}/home`);
    expect(init.credentials).toBe("include");
    expect(init.method).toBeUndefined();
  });

  it("TEST-FE-V57-002 tells a refused read from an unavailable one", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(answer({}, 403));
    await expect(reportsApi.home(PROPERTY)).rejects.toBeInstanceOf(
      ReportsNotAllowedError,
    );
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(answer({}, 503));
    await expect(reportsApi.home(PROPERTY)).rejects.toBeInstanceOf(
      ReportsUnavailableError,
    );
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("offline"),
    );
    await expect(reportsApi.home(PROPERTY)).rejects.toBeInstanceOf(
      ReportsUnavailableError,
    );
  });

  it("TEST-FE-V57-003 refuses a Home answer without its to-do groups", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      answer({
        data: { ...home, todo: [{ kind: "lease_ending", date: "2026-10-31" }] },
      }),
    );
    await expect(reportsApi.home(PROPERTY)).rejects.toBeInstanceOf(
      ReportsUnavailableError,
    );
  });

  it("TEST-FE-V57-004 reads a Totals report with only the filters given", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      answer({
        data: {
          report: "total_income",
          currency: "USD",
          filter: {
            unit_id: null,
            unit_number: null,
            floor: "2",
            from: null,
            to: null,
          },
          years: [{ year: 2026, months: Array(12).fill(null), total: 0 }],
          summary: {
            total: 0,
            highest_month: null,
            highest_unit: null,
            no_unit_amount: 0,
          },
          chart: { months: [], top_units: [] },
        },
      }),
    );
    const page = await reportsApi.totals(PROPERTY, "total_income", {
      floor: "2",
      from: "",
    });
    expect(page.years[0]?.months).toHaveLength(12);
    const [path] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(
      `/api/v1/properties/${PROPERTY}/reports/totals/total_income?floor=2`,
    );
  });

  it("TEST-FE-V57-005 refuses a Totals year without twelve months", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      answer({
        data: {
          report: "total_water",
          filter: {},
          years: [{ year: 2026, months: [1, 2], total: 3 }],
          summary: {},
          chart: {},
        },
      }),
    );
    await expect(
      reportsApi.totals(PROPERTY, "total_water"),
    ).rejects.toBeInstanceOf(ReportsUnavailableError);
  });
});
