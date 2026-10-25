import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ServiceSettingsError,
  serviceSettingsApi,
  settingsOf,
} from "./serviceSettingsClient";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const READ = {
  services: [
    {
      service_id: "s-1",
      service_code: "TRASH_COLLECTION",
      name_en: "Trash Collection",
      name_km: null,
      service_type_id: null,
      version: 1,
      rate_today_usd_cents: 300,
      next_rate: { monthly_rate_usd_cents: 350, effective_date: "2026-12-01" },
      approval_periods: [
        {
          approval_period_id: "a-1",
          effective_from: "2026-01-01",
          effective_through: null,
        },
      ],
      leases_using: 4,
    },
  ],
  service_types: [],
  today: "2026-10-25",
  can_manage: true,
};

function answer(status: number, body: unknown) {
  return vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

describe("Service settings client", () => {
  it("TEST-FE-1002 reads the Settings answer strictly, sends changes with the CSRF token, and maps each refusal code", async () => {
    expect(settingsOf(READ).services[0]?.next_rate).toEqual({
      monthly_rate_usd_cents: 350,
      effective_date: "2026-12-01",
    });
    for (const bad of [
      { ...READ, can_manage: "yes" },
      { ...READ, services: [{ ...READ.services[0], leases_using: -1 }] },
      { ...READ, services: [{ ...READ.services[0], version: 1.5 }] },
    ]) {
      expect(() => settingsOf(bad)).toThrow(ServiceSettingsError);
    }

    const read = answer(200, { data: READ });
    vi.stubGlobal("fetch", read);
    expect((await serviceSettingsApi.read("p 1")).today).toBe("2026-10-25");
    expect(read).toHaveBeenCalledWith(
      "/api/v1/properties/p%201/service-settings",
      expect.objectContaining({ method: "GET", credentials: "include" }),
    );

    // A change without the CSRF cookie is not sent.
    const none = answer(200, { data: {} });
    vi.stubGlobal("fetch", none);
    await expect(
      serviceSettingsApi.removeType("p-1", "t-1", 2),
    ).rejects.toMatchObject({ failure: "unknown" });
    expect(none).not.toHaveBeenCalled();

    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "other=1; __Host-prm_csrf=token-1",
    );
    const sent = answer(200, { data: {} });
    vi.stubGlobal("fetch", sent);
    await serviceSettingsApi.removeType("p-1", "t-1", 2);
    expect(sent).toHaveBeenCalledWith(
      "/api/v1/properties/p-1/service-types/t-1/remove",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ version: 2 }),
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": "token-1",
        },
      }),
    );

    for (const [status, code, failure] of [
      [409, "SETTINGS_OUT_OF_DATE", "out_of_date"],
      [409, "SETTINGS_ID_REUSED", "id_reused"],
      [409, "LEASE_HOLDS_TWO_OF_TYPE", "lease_holds_two"],
      [409, "SERVICE_TYPE_HAS_SERVICES", "type_has_services"],
      [409, "SOMETHING_ELSE", "unknown"],
      [403, "", "not_allowed"],
      [404, "", "not_found"],
      [422, "", "invalid"],
      [503, "", "unknown"],
    ] as const) {
      vi.stubGlobal("fetch", answer(status, { error: { code } }));
      await expect(
        serviceSettingsApi.changeType("p-1", "t-1", {
          name_en: "Parking",
          name_km: null,
          one_per_lease: true,
          version: 1,
        }),
      ).rejects.toMatchObject({ failure });
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("offline"))),
    );
    await expect(serviceSettingsApi.read("p-1")).rejects.toMatchObject({
      failure: "unknown",
    });
  });
});
