import { describe, expect, it } from "vitest";

import type {
  ServiceSetting,
  ServiceSettings,
} from "../settings/serviceSettingsClient";
import { choose, defaultChosen, rateOn, serviceGroups } from "./leaseServices";

function service(extra: Partial<ServiceSetting>): ServiceSetting {
  return {
    service_id: "s-1",
    service_code: "SVC_1",
    name_en: "Water filter",
    name_km: null,
    service_type_id: null,
    version: 1,
    rate_today_usd_cents: 400,
    next_rate: null,
    rates: [{ monthly_rate_usd_cents: 400, effective_date: "2026-01-01" }],
    approval_periods: [
      {
        approval_period_id: "a-1",
        effective_from: "2026-01-01",
        effective_through: null,
      },
    ],
    leases_using: 0,
    ...extra,
  };
}

const SETTINGS: ServiceSettings = {
  services: [
    service({
      service_id: "trash",
      service_code: "TRASH_COLLECTION",
      service_type_id: "t-trash",
    }),
    service({
      service_id: "short",
      service_type_id: "t-old",
      approval_periods: [
        {
          approval_period_id: "a-2",
          effective_from: "2026-01-01",
          effective_through: "2027-06-30",
        },
      ],
    }),
    service({ service_id: "free" }),
  ],
  service_types: [
    {
      service_type_id: "t-trash",
      name_en: "Trash",
      name_km: "សំរាម",
      one_per_lease: true,
      removed: false,
      version: 1,
      services: 1,
    },
    {
      service_type_id: "t-old",
      name_en: "Old",
      name_km: null,
      one_per_lease: true,
      removed: true,
      version: 2,
      services: 1,
    },
  ],
  today: "2026-10-25",
  can_manage: true,
};

describe("New Lease Services", () => {
  it("TEST-FE-1003 groups Services by type (no type and removed types last), opens only those approved for the whole Lease, takes the rate on the Start Date, defaults to Trash Collection or the renewed Lease's Services, and keeps one per Only one type", () => {
    const groups = serviceGroups(SETTINGS, "2026-11-01", "2027-10-31");
    // A removed type keeps its group while a Service has it: still only one per Lease.
    expect(groups.map((group) => [group.typeId, group.onePerLease])).toEqual([
      ["t-trash", true],
      ["t-old", true],
      [null, false],
    ]);
    // An approval that ends before the End Date does not cover the Lease.
    expect(groups[1]?.choices[0]?.approvalPeriodId).toBeNull();
    const other = groups[2]?.choices ?? [];
    expect(other.map((choice) => choice.approvalPeriodId)).toEqual(["a-1"]);
    const later = serviceGroups(
      {
        ...SETTINGS,
        services: [
          service({
            approval_periods: [
              {
                approval_period_id: "a-9",
                effective_from: "2027-02-01",
                effective_through: null,
              },
            ],
          }),
        ],
      },
      "2026-11-01",
      "2027-10-31",
    );
    expect(later[0]?.choices[0]?.startsLater).toBe("2027-02-01");

    // Every rate counts: a past Start Date and one after two later changes.
    const changing = service({
      rates: [
        { monthly_rate_usd_cents: 300, effective_date: "2025-01-01" },
        { monthly_rate_usd_cents: 400, effective_date: "2026-01-01" },
        { monthly_rate_usd_cents: 450, effective_date: "2027-01-01" },
        { monthly_rate_usd_cents: 500, effective_date: "2027-06-01" },
      ],
    });
    expect(rateOn(changing, "2025-12-31")).toBe(300);
    expect(rateOn(changing, "2026-12-31")).toBe(400);
    expect(rateOn(changing, "2027-01-01")).toBe(450);
    expect(rateOn(changing, "2027-07-01")).toBe(500);
    expect(rateOn(changing, "2024-07-01")).toBeNull();

    const dates = ["2026-11-01", "2027-10-31"] as const;
    expect([...defaultChosen(SETTINGS, ...dates, null)]).toEqual(["trash"]);
    // Trash Collection is not chosen when it is not open for the dates.
    expect([
      ...defaultChosen(SETTINGS, "2025-06-01", "2026-05-31", null),
    ]).toEqual([]);
    // A renewal takes what the old Lease still had at its end, open now, one per Only one
    // type (the latest), and nothing that is greyed or gone.
    const renewed = defaultChosen(
      {
        ...SETTINGS,
        services: [
          ...SETTINGS.services,
          service({ service_id: "trash-big", service_type_id: "t-trash" }),
        ],
      },
      ...dates,
      {
        endDate: "2026-10-31",
        terms: [
          {
            property_service_id: "trash",
            applicable_from: "2025-11-01",
            applicable_through: null,
          },
          {
            property_service_id: "trash-big",
            applicable_from: "2026-05-01",
            applicable_through: null,
          },
          {
            property_service_id: "free",
            applicable_from: "2025-11-01",
            applicable_through: "2026-04-30",
          },
          {
            property_service_id: "short",
            applicable_from: "2025-11-01",
            applicable_through: null,
          },
          {
            property_service_id: "gone",
            applicable_from: "2025-11-01",
            applicable_through: null,
          },
        ],
      },
    );
    expect([...renewed]).toEqual(["trash-big"]);

    const trash = groups[0];
    if (trash === undefined) throw new Error("no group");
    const two = { ...trash, choices: [...trash.choices, ...other] };
    expect([...choose(new Set(["trash"]), two, "free", true)]).toEqual([
      "free",
    ]);
    expect([...choose(new Set(["trash"]), two, null, true)]).toEqual([]);
    const many = { ...two, onePerLease: false };
    expect([...choose(new Set(["trash"]), many, "free", true)]).toEqual([
      "trash",
      "free",
    ]);
    expect([...choose(new Set(["trash"]), many, "trash", false)]).toEqual([]);
  });
});
