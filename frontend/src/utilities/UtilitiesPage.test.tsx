import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LeaseApi, LeaseResource } from "../leaseClient";
import type { UnitApi, UnitResource } from "../unitClient";
import {
  UtilityClientError,
  UtilityConflictError,
  type ReadingInput,
  type UtilityApi,
  type UtilityMeter,
  type UtilityReading,
  type UtilityType,
} from "../utilityClient";
import { UtilitiesPage } from "./UtilitiesPage";

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

beforeEach(() => {
  window.location.hash = "#/utilities";
  document.cookie = "__Host-prm_csrf=token";
});

const READING_DAY = "2026-10-25";

function unit(
  number: string,
  floor: string,
  status: UnitResource["status"],
): UnitResource {
  return {
    unit_id: `unit-${number}`,
    property_id: "property-1",
    unit_number: number,
    floor,
    floor_item_id: null,
    unit_type: "STUDIO",
    status,
    version: 1,
    size_square_metres: "36.00",
    bedrooms: 1,
    bathrooms: 1,
    view_item_id: null,
    kitchen_item_id: null,
    notes: null,
    room_feature_ids: [],
    current_reservation: null,
    current_lease: null,
    current_occupancy: null,
    active_meter_summary: null,
    operational_alerts: [],
  };
}

const UNITS = [
  unit("U201", "2", "OCCUPIED"),
  unit("U101", "1", "OCCUPIED"),
  unit("U102", "1", "VACANT"),
];

function meter(
  id: string,
  unitNumber: string,
  type: UtilityType,
  overrides: Partial<UtilityMeter> = {},
): UtilityMeter {
  return {
    id,
    property_id: "property-1",
    unit_id: `unit-${unitNumber}`,
    utility_type: type,
    serial_number: `${type === "ELECTRICITY" ? "EL" : "WA"}-${unitNumber}`,
    measurement_unit_code: type === "ELECTRICITY" ? "KWH" : "M3",
    description: null,
    installed_date: "2026-01-01",
    failure_date: null,
    deactivated_date: null,
    current: true,
    version: 4,
    memo: null,
    replacement: {
      replaced_meter_id: null,
      replacement_meter_id: null,
      replacement_date: null,
    },
    readings_url: `/api/v1/meters/${id}/readings`,
    ...overrides,
  };
}

function reading(
  meterId: string,
  day: string,
  value: string,
  overrides: Partial<UtilityReading> = {},
): UtilityReading {
  return {
    id: `reading-${meterId}-${day}`,
    property_id: "property-1",
    meter_id: meterId,
    unit_id: "unit",
    utility_type: "ELECTRICITY",
    measurement_unit_code: "KWH",
    reading_date: day,
    original_value: value,
    effective_value: value,
    source: { kind: "MANUAL", evidence: "Typed" },
    version: 1,
    corrections: [],
    validated: true,
    validated_at: `${day}T03:00:00Z`,
    validated_by: "actor-1",
    ...overrides,
  } as UtilityReading;
}

function meters(): UtilityMeter[] {
  return [
    meter("el-101", "U101", "ELECTRICITY"),
    meter("wa-101", "U101", "WATER"),
    meter("el-102", "U102", "ELECTRICITY"),
    meter("wa-102", "U102", "WATER"),
    meter("el-201-old", "U201", "ELECTRICITY", {
      serial_number: "EL-OLD-201",
      current: false,
      failure_date: "2026-08-20",
      deactivated_date: "2026-08-24",
    }),
    meter("el-201", "U201", "ELECTRICITY", { installed_date: "2026-08-24" }),
    meter("wa-201", "U201", "WATER"),
  ];
}

const READINGS: Record<string, UtilityReading[]> = {
  "el-101": [
    reading("el-101", "2026-09-24", "1200"),
    reading("el-101", "2026-08-24", "1100"),
    reading("el-101", "2026-07-24", "1000"),
  ],
  "wa-101": [reading("wa-101", "2026-09-24", "40")],
  "el-102": [
    reading("el-102", "2026-10-24", "330"),
    reading("el-102", "2026-09-24", "300", {
      original_value: "310",
      corrections: [
        {
          id: "correction-1",
          previous_value: "310",
          corrected_value: "300",
          reason: "Typed wrong",
          occurred_at: "2026-09-25T03:00:00Z",
          actor_id: "actor-1",
          authorization_reference: "Manager",
        },
      ],
    }),
  ],
  "wa-102": [],
  "el-201-old": [
    reading("el-201-old", "2026-08-24", "600"),
    reading("el-201-old", "2026-07-24", "500"),
  ],
  "el-201": [
    reading("el-201", "2026-09-24", "50"),
    reading("el-201", "2026-08-24", "0"),
  ],
  // Read three days late in September.
  "wa-201": [
    reading("wa-201", "2026-09-27", "15"),
    reading("wa-201", "2026-08-24", "10"),
  ],
};

function utilityApi(
  overrides: Partial<UtilityApi> = {},
  list: UtilityMeter[] = meters(),
): UtilityApi {
  return {
    load: vi.fn(),
    loadMeters: vi.fn((unitId: string) =>
      Promise.resolve({
        items: list.filter((item) => item.unit_id === unitId),
        nextCursor: null,
      }),
    ),
    loadReadings: vi.fn((meterId: string) =>
      Promise.resolve({ items: READINGS[meterId] ?? [], nextCursor: null }),
    ),
    loadRates: vi.fn(),
    installMeter: vi.fn(),
    replaceMeter: vi.fn(),
    recordReading: vi.fn((meterId: string, input: ReadingInput) =>
      Promise.resolve(
        reading(meterId, input.reading_date, input.reading_value),
      ),
    ),
    correctReading: vi.fn(),
    recordBatch: vi.fn(),
    createRate: vi.fn(),
    preview: vi.fn(),
    ...overrides,
  };
}

function unitApi(): Pick<UnitApi, "list"> {
  return {
    list: vi.fn().mockResolvedValue({
      items: UNITS,
      next_cursor: null,
      can_manage: false,
    }),
  };
}

function leaseApi(): Pick<LeaseApi, "list"> {
  return {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          lease_id: "lease-1",
          unit_id: "unit-U101",
          unit_number: "U101",
          primary_tenant_name: "Sok Dara",
        } as LeaseResource,
      ],
      next_cursor: null,
    }),
  };
}

function show(
  options: {
    api?: UtilityApi;
    today?: string;
    capabilities?: ReadonlySet<string> | null;
  } = {},
) {
  const api = options.api ?? utilityApi();
  const units = unitApi();
  render(
    <UtilitiesPage
      active
      capabilities={options.capabilities ?? null}
      language="en"
      leaseApi={leaseApi()}
      propertyId="property-1"
      today={options.today ?? READING_DAY}
      unitApi={units}
      utilityApi={api}
    />,
  );
  return { api, units };
}

function rowOf(unitNumber: string): HTMLElement {
  const cell = screen.getByText(unitNumber, { selector: "b" });
  const row = cell.closest("tr");
  if (row === null) throw new Error(`No row for ${unitNumber}`);
  return row;
}

function input(unitNumber: string): HTMLInputElement {
  return within(rowOf(unitNumber)).getByRole<HTMLInputElement>("textbox");
}

describe("Utilities page (V1-058 R4)", () => {
  it("TEST-FE-874 On reading day This month lists every working meter with its last reading, the progress, and the floor and Only not read filters", async () => {
    show();
    expect(await screen.findByText("1 of 6 meters read")).toBeTruthy();
    expect(
      screen.getByText(
        "Read every meter, including empty rooms. Invoices are made on 25/10/2026 from these readings.",
      ),
    ).toBeTruthy();
    expect(within(rowOf("U101")).getByText("1,200")).toBeTruthy();
    expect(within(rowOf("U101")).getByText("Sok Dara")).toBeTruthy();
    expect(
      within(rowOf("U102")).getByText("Vacant. The Property pays."),
    ).toBeTruthy();
    expect(within(rowOf("U102")).getByText("Saved 24/10/2026")).toBeTruthy();
    expect(within(rowOf("U102")).getByText("30 kWh")).toBeTruthy();
    // The replaced meter of U201 is not on the list; the new one is.
    expect(within(rowOf("U201")).getByText("EL-U201")).toBeTruthy();
    expect(screen.queryByText("EL-OLD-201")).toBeNull();
    expect(
      screen.getByRole("button", { name: /Electricity/ }).textContent,
    ).toContain("1/3");

    fireEvent.change(screen.getByLabelText("All floors"), {
      target: { value: "2" },
    });
    expect(screen.queryByText("U101", { selector: "b" })).toBeNull();
    expect(screen.getByText("U201", { selector: "b" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("All floors"), {
      target: { value: "all" },
    });
    fireEvent.click(screen.getByLabelText("Only not read"));
    expect(screen.queryByText("U102", { selector: "b" })).toBeNull();
    expect(screen.getByText("U101", { selector: "b" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Water/ }));
    expect(within(rowOf("U101")).getByText("40")).toBeTruthy();
    expect(within(rowOf("U102")).getByText("No reading yet")).toBeTruthy();
  });

  it("TEST-FE-875 Saving a reading sends today's date, the meter version and a key, marks the line Saved and moves to the next meter", async () => {
    const { api } = show();
    await screen.findByText("1 of 6 meters read");
    fireEvent.change(input("U101"), { target: { value: "1,250" } });
    expect(within(rowOf("U101")).getByText("50 kWh")).toBeTruthy();
    expect(within(rowOf("U101")).getByText("Not saved yet")).toBeTruthy();
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );

    await screen.findByText("U101 EL-U101: saved.");
    expect(api.recordReading).toHaveBeenCalledWith(
      "el-101",
      {
        expected_meter_version: 4,
        reading_date: READING_DAY,
        reading_value: "1250",
        source_kind: "MANUAL",
        source_evidence: "Typed on the Meter readings screen",
      },
      expect.stringMatching(/^[0-9a-f-]{36}$/) as string,
    );
    expect(within(rowOf("U101")).getByText("Saved")).toBeTruthy();
    expect(screen.getByText("2 of 6 meters read")).toBeTruthy();
    await waitFor(() => {
      expect(document.activeElement).toBe(input("U201"));
    });

    // The next save on the same meter would use the new version.
    fireEvent.change(input("U201"), { target: { value: "120" } });
    fireEvent.keyDown(input("U201"), { key: "Enter" });
    await screen.findByText("U201 EL-U201: saved.");
    expect(api.recordReading).toHaveBeenLastCalledWith(
      "el-201",
      expect.objectContaining({ reading_value: "120" }) as ReadingInput,
      expect.any(String) as string,
    );
  });

  it("TEST-FE-876 A reading lower than the last or not a whole number is refused on the screen; much more than usual asks to check first", async () => {
    const { api } = show();
    await screen.findByText("1 of 6 meters read");
    fireEvent.change(input("U101"), { target: { value: "1100" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    expect(
      screen.getByText(
        "Lower than the last reading (1,200). Check the meter. If it is broken, a Manager replaces it on the Meters tab.",
      ),
    ).toBeTruthy();
    expect(input("U101").getAttribute("aria-invalid")).toBe("true");

    fireEvent.change(input("U101"), { target: { value: "12.5" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    expect(screen.getByText("Enter whole numbers only.")).toBeTruthy();
    expect(api.recordReading).not.toHaveBeenCalled();

    // Usual use is 100 kWh; 400 kWh is much more.
    fireEvent.change(input("U101"), { target: { value: "1600" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    expect(
      screen.getByText(
        "400 kWh is much more than usual (about 100 kWh). Check the meter, then save again.",
      ),
    ).toBeTruthy();
    expect(api.recordReading).not.toHaveBeenCalled();
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save anyway U101/ }),
    );
    await screen.findByText("U101 EL-U101: saved.");
    expect(api.recordReading).toHaveBeenCalledTimes(1);
  });

  it("TEST-FE-877 A changed meter reads the list again; a lost answer keeps the key for Try again; a refusal says so", async () => {
    const recordReading = vi
      .fn()
      .mockRejectedValueOnce(new UtilityClientError())
      .mockRejectedValueOnce(new UtilityClientError(undefined, [], "req-1"))
      .mockRejectedValueOnce(new UtilityConflictError());
    const { api, units } = show({ api: utilityApi({ recordReading }) });
    await screen.findByText("1 of 6 meters read");

    fireEvent.change(input("U101"), { target: { value: "1250" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    await screen.findByText(
      "The reading was not saved. Check the connection and try again.",
    );
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    await screen.findByText(
      "The reading was refused. It may be lower than a reading already saved, or dated before the meter was put in.",
    );
    const keys = recordReading.mock.calls.map((call) => String(call[2]));
    expect(keys[0]).toBe(keys[1]);

    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    await screen.findByText(
      "This meter changed while you were typing, so the list was read again. Check the reading and save again.",
    );
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
    expect(api.loadMeters).toHaveBeenCalledTimes(6);
  });

  it("TEST-FE-878 Before reading day This month shows the month's readings; Pick a month lists one month; 6 months shows a grid with the use under each reading", async () => {
    show({ today: "2026-10-10" });
    expect(
      await screen.findByText(
        "Reading day is 24/10/2026. The list to type the readings opens that day.",
      ),
    ).toBeTruthy();
    expect(within(rowOf("U102")).getByText("330")).toBeTruthy();
    expect(screen.queryByText("U101", { selector: "b" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: /New reading/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Water/ }));
    expect(screen.getByText("No readings in October 2026.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Electricity/ }));

    fireEvent.click(screen.getByRole("button", { name: "Pick a month" }));
    fireEvent.change(screen.getByLabelText("Month", { selector: "select" }), {
      target: { value: "2026-09" },
    });
    const row = rowOf("U101");
    expect(within(row).getByText("1,200")).toBeTruthy();
    expect(within(row).getByText("100 kWh")).toBeTruthy();
    expect(
      within(rowOf("U102")).getByText(/Corrected from 310\./),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "6 months" }));
    const grid = screen.getByRole("table");
    const heads = within(grid)
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent);
    expect(heads).toEqual([
      "Unit",
      "October 2026",
      "September 2026",
      "August 2026",
      "July 2026",
    ]);
    // On 24/08 the new U201 meter (first reading 0) wins over the old one.
    const u201 = within(grid).getByRole("rowheader", { name: /U201/ });
    const cells = within(u201.closest("tr") ?? grid).getAllByRole("cell");
    expect(cells[2]?.textContent).toBe("0");
    expect(cells[1]?.textContent).toBe("5050 kWh");
    expect(
      screen.getByText(
        "Each box shows the reading and, under it, the use since the reading before, in kWh.",
      ),
    ).toBeTruthy();

    // A reading typed on another day of the month goes in that month's column.
    fireEvent.click(screen.getByRole("button", { name: /Water/ }));
    const water = screen.getByRole("table");
    expect(
      within(water)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Unit", "September 2026", "August 2026"]);
    const waterRow = within(water)
      .getByRole("rowheader", { name: /U201/ })
      .closest("tr");
    if (waterRow === null) throw new Error("No U201 row");
    expect(within(waterRow).getAllByRole("cell")[0]?.textContent).toBe(
      "155 m³",
    );
    expect(
      within(water)
        .getByRole("rowheader", { name: /U101/ })
        .closest("tr")
        ?.querySelectorAll("td")[0]?.textContent,
    ).toBe("40");
  });

  it("TEST-FE-879 The Unit box takes U201, u201 or 201, shows that Unit's readings with the meter on each line, and names a Unit that does not exist", async () => {
    show({ today: "2026-10-10" });
    await screen.findByText(/Reading day is 24\/10\/2026/);
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    const box = screen.getByLabelText("Unit");
    fireEvent.change(box, { target: { value: "201" } });
    fireEvent.submit(box);
    expect(screen.getAllByText("EL-OLD-201")).toHaveLength(2);
    expect(screen.getAllByText("EL-U201")).toHaveLength(2);
    expect(
      screen.getAllByText("New meter put in. First reading."),
    ).toHaveLength(2);

    fireEvent.change(box, { target: { value: "u999" } });
    fireEvent.blur(box);
    expect(
      screen.getByText(
        'No Unit "u999". Type a Unit number such as U101, or clear the box to see all Units.',
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "All Units" }));
    expect(screen.queryByText(/No Unit/)).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Unit" })).toBeTruthy();
  });

  it("TEST-FE-880 A person who may not record readings sees no Save; a broken meter cannot be read and points to Replace meter; the Meters tab has its own address", async () => {
    const list = meters().map((item) =>
      item.id === "el-201" ? { ...item, failure_date: "2026-10-20" } : item,
    );
    show({
      api: utilityApi({}, list),
      capabilities: new Set(["utility.read"]),
    });
    await screen.findByText("1 of 5 meters read");
    expect(
      screen.getByText("You may see the readings but not save them."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Save/ })).toBeNull();
    expect(input("U101").disabled).toBe(true);
    const broken = rowOf("U201");
    expect(within(broken).getByText("Broken")).toBeTruthy();
    expect(
      within(broken).getByText(
        "A broken meter cannot be read. Replace it first.",
      ),
    ).toBeTruthy();
    expect(
      within(broken)
        .getByRole("link", { name: "Replace meter" })
        .getAttribute("href"),
    ).toBe("#/utilities/meters");

    window.location.hash = "#/utilities/meters";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByText(/The new Meters list comes in the next step/),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Meters" }).getAttribute("aria-current"),
    ).toBe("page");
  });
  it("TEST-FE-881 Two saves that end close together both stay; a new value gets a new key; after the last meter the cursor goes to the count", async () => {
    const answers: ((value: UtilityReading) => void)[] = [];
    const keys: string[] = [];
    const recordReading = vi.fn(
      (meterId: string, input: ReadingInput, key: string) =>
        new Promise<UtilityReading>((resolve, reject) => {
          keys.push(key);
          // The first Water try is lost on the way.
          if (input.reading_value === "45") {
            reject(new UtilityClientError());
            return;
          }
          answers.push(() => {
            resolve(reading(meterId, input.reading_date, input.reading_value));
          });
        }),
    );
    show({ api: utilityApi({ recordReading }) });
    await screen.findByText("1 of 6 meters read");
    fireEvent.change(input("U101"), { target: { value: "1250" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    fireEvent.change(input("U201"), { target: { value: "120" } });
    fireEvent.click(
      within(rowOf("U201")).getByRole("button", { name: /^Save U/ }),
    );
    expect(answers).toHaveLength(2);
    answers[0]?.(reading("x", "x", "x"));
    answers[1]?.(reading("x", "x", "x"));
    await screen.findByText("3 of 6 meters read");
    expect(within(rowOf("U101")).getByText("Saved")).toBeTruthy();
    expect(within(rowOf("U201")).getByText("Saved")).toBeTruthy();
    // Every Electricity meter is read: the cursor goes to the count.
    await waitFor(() => {
      expect(document.activeElement?.id).toBe("ut-progress");
    });

    fireEvent.click(screen.getByRole("button", { name: /Water/ }));
    fireEvent.change(input("U101"), { target: { value: "45" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    await screen.findByText(
      "The reading was not saved. Check the connection and try again.",
    );
    fireEvent.change(input("U101"), { target: { value: "46" } });
    fireEvent.click(
      within(rowOf("U101")).getByRole("button", { name: /^Save U/ }),
    );
    expect(keys).toHaveLength(4);
    expect(keys[2]).not.toBe(keys[3]);
  });

  it("TEST-FE-882 A Unit whose readings cannot be read is named and the list is never called done without it; the Unit box waits while U10 may still become U101", async () => {
    const api = utilityApi({
      loadReadings: vi.fn((meterId: string) =>
        meterId === "wa-201"
          ? Promise.reject(new UtilityClientError())
          : Promise.resolve({
              items: READINGS[meterId] ?? [],
              nextCursor: null,
            }),
      ),
    });
    show({ api });
    expect(
      await screen.findByText(
        "The meters of U201 could not be read. Try again.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("1 of 4 meters read")).toBeTruthy();
    expect(screen.queryByText("U201", { selector: "b" })).toBeNull();
    expect(
      screen.queryByText(
        "All meters are read. Invoices will be made on the 25th.",
      ),
    ).toBeNull();
    cleanup();

    const units = [unit("U10", "1", "VACANT"), unit("U101", "1", "VACANT")];
    render(
      <UtilitiesPage
        active
        capabilities={null}
        language="en"
        leaseApi={leaseApi()}
        propertyId="property-1"
        today="2026-10-10"
        unitApi={{
          list: vi.fn().mockResolvedValue({
            items: units,
            next_cursor: null,
            can_manage: false,
          }),
        }}
        utilityApi={utilityApi()}
      />,
    );
    await screen.findByText(/Reading day is/);
    const box = screen.getByLabelText("Unit");
    fireEvent.change(box, { target: { value: "U10" } });
    expect(screen.queryByRole("button", { name: "All Units" })).toBeNull();
    fireEvent.change(box, { target: { value: "U101" } });
    expect(screen.getByRole("button", { name: "All Units" })).toBeTruthy();
  });
});
