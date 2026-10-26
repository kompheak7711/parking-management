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
  MeterSerialNumberInUseError,
  UtilityClientError,
  UtilityConflictError,
  type BatchReadingInput,
  type BatchReadingResult,
  type MeterInstallInput,
  type MeterReplaceInput,
  type ReadingInput,
  type ReadingSheet,
  type ReadingSheetRow,
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
  // A new Unit with no meters yet.
  unit("U301", "3", "VACANT"),
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
      replacement: {
        replaced_meter_id: null,
        replacement_meter_id: "el-201",
        replacement_date: "2026-08-24",
      },
    }),
    meter("el-201", "U201", "ELECTRICITY", {
      installed_date: "2026-08-24",
      replacement: {
        replaced_meter_id: "el-201-old",
        replacement_meter_id: null,
        replacement_date: "2026-08-24",
      },
    }),
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
    readSheet: vi.fn(),
    blankSheet: vi.fn(),
    preview: vi.fn(),
    ...overrides,
  };
}

function unitApi(items: UnitResource[] = UNITS): Pick<UnitApi, "list"> {
  return {
    list: vi.fn().mockResolvedValue({
      items,
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
    units?: UnitResource[];
  } = {},
) {
  const api = options.api ?? utilityApi();
  const units = unitApi(options.units);
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

const SHEET_ROWS: ReadingSheetRow[] = [
  { row: 2, unit: "U101", electricity: "1,300", water: "38" },
  { row: 3, unit: "U102", electricity: "340", water: "5" },
  { row: 4, unit: "u201", electricity: "", water: "20" },
  { row: 5, unit: "U999", electricity: "1", water: "2" },
  { row: 6, unit: "301", electricity: "60", water: "21" },
  { row: 7, unit: "U301", electricity: "7", water: "" },
];

function sheetOf(rows: ReadingSheetRow[]) {
  return vi.fn(() =>
    Promise.resolve({
      file_name: "readings.csv",
      problem: null,
      rows,
    } satisfies ReadingSheet),
  );
}

/** Opens Import, chooses a file and returns the Check readings dialog. */
async function openCheck(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: /^Import/ }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Spreadsheet file"), {
    target: { files: [new File(["x"], "readings.csv")] },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Check the file" }),
  );
  await within(dialog).findByText("Check readings");
  return screen.getByRole("dialog");
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
    // Four Units, read twice.
    expect(api.loadMeters).toHaveBeenCalledTimes(8);
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
    expect(await screen.findByText("Electricity meters")).toBeTruthy();
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

describe("Utilities Meters tab (V1-058 R4b)", () => {
  function openMeters(hash = "#/utilities/meters") {
    window.location.hash = hash;
  }

  it("TEST-FE-883 The Meters list counts the meters in use, shows replaced meters last, and filters by card, status and Unit", async () => {
    openMeters();
    show();
    expect(
      await screen.findByRole("button", {
        name: "Electricity meters: 3. In use, one per Unit · All working",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Broken meters: 0. None broken" }),
    ).toBeTruthy();
    const serials = () =>
      screen
        .getAllByRole("link")
        .map((link) => link.textContent)
        .filter((text) => text.startsWith("EL-") || text.startsWith("WA-"));
    expect(serials()).toEqual([
      "EL-U101",
      "WA-U101",
      "EL-U102",
      "WA-U102",
      "EL-U201",
      "WA-U201",
      "EL-OLD-201",
    ]);
    expect(screen.getByText("Replaced 24/08/2026")).toBeTruthy();
    expect(screen.getByText("7 meters")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "EL-OLD-201" }).getAttribute("href"),
    ).toBe("#/utilities/meter%3Ael-201-old");

    fireEvent.click(screen.getByRole("button", { name: /^Water meters: 3/ }));
    expect(serials()).toEqual(["WA-U101", "WA-U102", "WA-U201"]);
    expect(screen.getByText("Showing: Water meters.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "replaced" },
    });
    expect(serials()).toEqual(["EL-OLD-201"]);
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "all" },
    });
    fireEvent.change(screen.getByLabelText("Unit"), {
      target: { value: "U102" },
    });
    expect(serials()).toEqual(["EL-U102", "WA-U102"]);
  });

  it("TEST-FE-884 Add meter refuses a second working meter of a kind, sends the meter with its first reading on the day it is put in, and names a serial already used", async () => {
    openMeters();
    const installMeter = vi
      .fn()
      .mockRejectedValueOnce(new MeterSerialNumberInUseError([], "req-2"))
      .mockResolvedValueOnce(meter("el-301", "U301", "ELECTRICITY"));
    const { units } = show({ api: utilityApi({ installMeter }) });
    fireEvent.click(await screen.findByRole("button", { name: /Add meter/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Unit/), {
      target: { value: "unit-U101" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Serial/), {
      target: { value: "EL-U101-B" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    expect(
      within(dialog).getByText(
        "U101 already has a working electricity meter (EL-U101). A Unit can have only one.",
      ),
    ).toBeTruthy();
    expect(installMeter).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText(/^Unit/), {
      target: { value: "unit-U301" },
    });
    expect(
      within(dialog).getByText(
        "The number printed on the meter. If it has none, use a code such as EL-U301.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    expect(
      await within(dialog).findByText(
        "EL-U101-B is already used by another meter.",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Serial/), {
      target: { value: "EL-U301" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    expect(await screen.findByText("EL-U301 added to U301.")).toBeTruthy();
    expect(installMeter).toHaveBeenLastCalledWith(
      "unit-U301",
      {
        utility_type: "ELECTRICITY",
        serial_number: "EL-U301",
        measurement_unit_code: "KWH",
        description: null,
        installed_date: READING_DAY,
        memo: null,
        initial_reading: {
          reading_date: READING_DAY,
          reading_value: "0",
          source_evidence: "Typed in the Add meter dialog",
        },
      } satisfies MeterInstallInput,
      expect.stringMatching(/^[0-9a-f-]{36}$/) as string,
    );
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-885 A meter's page shows its facts, its readings and the meter it replaced or was replaced by, with a Back link instead of tabs", async () => {
    openMeters("#/utilities/meter%3Ael-201-old");
    show();
    expect(
      await screen.findByRole("heading", { name: "EL-OLD-201" }),
    ).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Meter readings" })).toBeNull();
    expect(
      screen.getByRole("link", { name: /Back to Meters/ }).getAttribute("href"),
    ).toBe("#/utilities/meters");
    expect(screen.getByText("Found broken")).toBeTruthy();
    expect(screen.getByText("20/08/2026")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "EL-U201" }).getAttribute("href"),
    ).toBe("#/utilities/meter%3Ael-201");
    expect(screen.getByText("100 kWh")).toBeTruthy();
    // A replaced meter cannot be replaced again.
    expect(screen.queryByRole("button", { name: /Replace meter/ })).toBeNull();

    window.location.hash = "#/utilities/meter%3Ael-201";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { name: "EL-U201" }),
    ).toBeTruthy();
    expect(screen.getByText("Replaced")).toBeTruthy();
    expect(screen.getByRole("link", { name: "EL-OLD-201" })).toBeTruthy();
  });

  it("TEST-FE-886 Replace meter checks the dates against the last good reading and today, keeps the key for Try again, and opens the new meter", async () => {
    openMeters("#/utilities/meter%3Ael-101");
    const replaceMeter = vi
      .fn()
      .mockRejectedValueOnce(new UtilityClientError())
      .mockResolvedValueOnce(
        meter("el-101-new", "U101", "ELECTRICITY", {
          serial_number: "EL-U101-B",
        }),
      );
    show({ api: utilityApi({ replaceMeter }) });
    fireEvent.click(
      await screen.findByRole("button", { name: /Replace meter/ }),
    );
    const dialog = screen.getByRole("dialog", { name: "Replace EL-U101?" });
    const submit = () => {
      fireEvent.click(
        within(dialog).getByRole("button", { name: /Replace meter|Try again/ }),
      );
    };
    fireEvent.change(within(dialog).getByLabelText(/^Found broken on/), {
      target: { value: "2026-09-20" },
    });
    submit();
    expect(
      within(dialog).getByText("The date cannot be before 24/09/2026."),
    ).toBeTruthy();
    expect(within(dialog).getByText("Write the serial.")).toBeTruthy();
    expect(within(dialog).getByText("Write what is wrong.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Found broken on/), {
      target: { value: READING_DAY },
    });
    fireEvent.change(within(dialog).getByLabelText(/^New meter serial/), {
      target: { value: "EL-U101-B" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Display is blank" },
    });
    submit();
    expect(
      within(dialog).getByText(
        "The new meter must be put in at least one day after the old one was found broken.",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Found broken on/), {
      target: { value: "2026-10-20" },
    });
    submit();
    expect(await within(dialog).findByText(/No answer came back/)).toBeTruthy();
    submit();
    await waitFor(() => {
      expect(window.location.hash).toBe("#/utilities/meter%3Ael-101-new");
    });
    const expected: MeterReplaceInput = {
      expected_version: 4,
      failed_boundary_reading_id: "reading-el-101-2026-09-24",
      failure_date: "2026-10-20",
      replacement_date: READING_DAY,
      reason: "Display is blank",
      replacement_meter: {
        serial_number: "EL-U101-B",
        description: null,
        memo: null,
      },
      replacement_initial_reading: {
        reading_date: READING_DAY,
        reading_value: "0",
        source_evidence: "Typed in the Replace meter dialog",
      },
    };
    expect(replaceMeter).toHaveBeenCalledTimes(2);
    const calls = replaceMeter.mock.calls as [
      string,
      MeterReplaceInput,
      string,
    ][];
    expect(calls[0]?.[1]).toEqual(expected);
    expect(calls[1]?.[2]).toBe(calls[0]?.[2]);
  });

  it("TEST-FE-887 A person who may not manage meters sees the list and the meter page but no Add meter or Replace meter", async () => {
    openMeters();
    show({
      capabilities: new Set(["utility.read", "utility_readings.record"]),
    });
    await screen.findByText("7 meters");
    expect(screen.queryByRole("button", { name: /Add meter/ })).toBeNull();
    window.location.hash = "#/utilities/meter%3Ael-101";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { name: "EL-U101" }),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Replace meter/ })).toBeNull();
  });
  it("TEST-FE-888 A broken meter comes first, is counted with the next reading day, opens with its found-broken day filled, and is replaced from its newest checked reading; a changed meter reads the list again", async () => {
    openMeters();
    const list = meters().map((item) =>
      item.id === "wa-101" ? { ...item, failure_date: "2026-10-20" } : item,
    );
    const readings = (meterId: string) =>
      meterId === "wa-101"
        ? [
            // Not checked yet: the server never uses it as the boundary.
            reading("wa-101", "2026-10-19", "44", {
              validated: false,
              validated_at: null,
              validated_by: null,
            } as Partial<UtilityReading>),
            reading("wa-101", "2026-09-24", "40"),
          ]
        : (READINGS[meterId] ?? []);
    const replaceMeter = vi.fn().mockRejectedValue(new UtilityConflictError());
    const { units } = show({
      api: utilityApi(
        {
          replaceMeter,
          loadReadings: vi.fn((meterId: string) =>
            Promise.resolve({ items: readings(meterId), nextCursor: null }),
          ),
        },
        list,
      ),
    });
    expect(
      await screen.findByRole("button", {
        name: "Broken meters: 1. Replace before 24/11/2026",
      }),
    ).toBeTruthy();
    const first = screen
      .getAllByRole("link")
      .find((link) => link.textContent.startsWith("WA-"));
    expect(first?.textContent).toBe("WA-U101");
    expect(screen.getByText("Broken since 20/10/2026")).toBeTruthy();

    window.location.hash = "#/utilities/meter%3Awa-101";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByText(
        "A broken meter cannot be read. Replace it first.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Replace meter/ }));
    const dialog = screen.getByRole("dialog");
    const found =
      within(dialog).getByLabelText<HTMLInputElement>(/^Found broken on/);
    expect(found.value).toBe("2026-10-20");
    expect(
      within(dialog).getByText(
        "Not before the last good reading (24/09/2026).",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^New meter serial/), {
      target: { value: "WA-U101-B" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Dial stuck" },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Replace meter" }),
    );
    expect(
      await screen.findByText(
        "The meters changed while the form was open, so the list was read again. Check and try again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const sent = (
      replaceMeter.mock.calls as [string, MeterReplaceInput, string][]
    )[0];
    expect(sent?.[1].failed_boundary_reading_id).toBe(
      "reading-wa-101-2026-09-24",
    );
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-889 Add meter says when it was refused, gives changed values a new key, and reads the list again when closed after a lost answer", async () => {
    openMeters();
    const installMeter = vi
      .fn()
      .mockRejectedValueOnce(new UtilityClientError(undefined, [], "req-3"))
      .mockRejectedValueOnce(new UtilityClientError())
      .mockRejectedValueOnce(new UtilityClientError());
    const { units } = show({ api: utilityApi({ installMeter }) });
    fireEvent.click(await screen.findByRole("button", { name: /Add meter/ }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    // Nothing chosen: the cursor goes to the Unit and its error is linked to it.
    const unitBox = within(dialog).getByLabelText(/^Unit/);
    expect(unitBox.getAttribute("aria-describedby")).toBe("add-unit-err");
    await waitFor(() => {
      expect(document.activeElement).toBe(unitBox);
    });
    fireEvent.change(unitBox, { target: { value: "unit-U301" } });
    fireEvent.change(within(dialog).getByLabelText(/^Serial/), {
      target: { value: "EL-U301" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    expect(
      await within(dialog).findByText(
        "It was not saved. Check the values and try again.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Add meter" }));
    await within(dialog).findByText(/No answer came back/);
    fireEvent.change(within(dialog).getByLabelText(/^Serial/), {
      target: { value: "EL-U301-A" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(installMeter).toHaveBeenCalledTimes(3);
    });
    const keys = installMeter.mock.calls.map((call) => String(call[2]));
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
    await within(dialog).findByText(/No answer came back/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
  });
});

describe("Utilities Import readings (V1-058 R4c)", () => {
  it("TEST-FE-890 Import opens from the reading list, downloads the blank file with every Unit, asks for a file, and sends the chosen file to be read", async () => {
    const blob = new Blob(["xlsx"]);
    const blankSheet = vi.fn().mockResolvedValue(blob);
    const readSheet = vi.fn().mockResolvedValue({
      file_name: "readings.csv",
      problem: "COLUMNS",
      rows: [],
    } satisfies ReadingSheet);
    const createObjectURL = vi.fn(() => "blob:sheet");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL, revokeObjectURL }),
    );
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    show({ api: utilityApi({ blankSheet, readSheet }) });
    fireEvent.click(await screen.findByRole("button", { name: /^Import/ }));
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("Import readings from a spreadsheet"),
    ).toBeTruthy();
    expect(
      within(dialog).getByText(
        /Import the readings for reading day 24\/10\/2026 from an \.xlsx or \.csv file\./,
      ),
    ).toBeTruthy();

    fireEvent.click(
      within(dialog).getByRole("button", { name: /Download the blank file/ }),
    );
    await waitFor(() => {
      expect(click).toHaveBeenCalledTimes(1);
    });
    expect(blankSheet).toHaveBeenCalledWith("property-1", [
      "U101",
      "U102",
      "U201",
      "U301",
    ]);
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:sheet");

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Check the file" }),
    );
    expect(within(dialog).getByText("Choose a file first.")).toBeTruthy();
    const fileBox = within(dialog).getByLabelText("Spreadsheet file");
    expect(fileBox.getAttribute("aria-describedby")).toBe("im-file-err");

    fireEvent.change(fileBox, {
      target: { files: [new File(["Unit,Meter\n"], "readings.csv")] },
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Check the file" }),
    );
    expect(
      await within(dialog).findByText(
        "The first row needs the three column names Unit, Electricity and Water.",
      ),
    ).toBeTruthy();
    expect(readSheet).toHaveBeenCalledWith(
      "property-1",
      "readings.csv",
      btoa("Unit,Meter\n"),
    );
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it("TEST-FE-891 Check readings lists each reading with its previous reading, puts the lines that need fixing first, and confirms the ready ones in one step", async () => {
    const recordBatch = vi.fn(
      (_property: string, _mode: string, items: BatchReadingInput[]) =>
        Promise.resolve(
          items.map((item, index): BatchReadingResult => {
            const failed = item.meter_id === "wa-201";
            return {
              index,
              idempotency_key: item.idempotency_key,
              status: failed ? "FAILED" : "SUCCEEDED",
              reading: failed
                ? null
                : reading(
                    item.meter_id,
                    item.reading.reading_date,
                    item.reading.reading_value,
                  ),
              error: failed ? { code: "CONFLICT" } : null,
            };
          }),
        ),
    );
    const { units } = show({
      api: utilityApi({ readSheet: sheetOf(SHEET_ROWS), recordBatch }),
    });
    const dialog = await openCheck();
    expect(
      within(dialog).getByText(/9 readings\. 3 are ready\. 6 need fixing\./),
    ).toBeTruthy();
    const lines = within(dialog).getAllByRole("row").slice(1);
    expect(lines).toHaveLength(9);
    // The six lines that need fixing come first, on the error tint.
    expect(
      lines.slice(0, 6).every((line) => line.className === "ui-imbad"),
    ).toBe(true);
    expect(lines.slice(6).map((line) => line.textContent)).toEqual([
      "U101Electricity1,2001,300Ready",
      "U102Water—5Ready",
      "U201Water1520Ready",
    ]);
    // Previous is the reading before reading day, even when this month's is already saved.
    expect(
      within(dialog).getByText("Already saved this month: 330").closest("tr")
        ?.textContent,
    ).toContain("U102Electricity300340");
    for (const text of [
      "Lower than previous",
      "Already saved this month: 330",
      "Empty. Type the reading.",
      "There is no Unit U999.",
    ]) {
      expect(within(dialog).getByText(text)).toBeTruthy();
    }
    // A Unit on two rows: neither row is confirmed.
    expect(
      within(dialog).getAllByText(
        "U301 is on more than one row (rows 6, 7). Keep one row.",
      ),
    ).toHaveLength(2);
    expect(
      within(dialog).getByLabelText(
        "Confirm the 3 ready readings now. Fix the other 6 on the screen.",
      ),
    ).toHaveProperty("checked", true);

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    expect(
      await screen.findByText("2 readings confirmed from readings.csv."),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(recordBatch).toHaveBeenCalledTimes(1);
    const [property, mode, items] = recordBatch.mock.calls[0] ?? [];
    expect(property).toBe("property-1");
    expect(mode).toBe("PARTIAL");
    expect(
      items?.map((item) => [
        item.meter_id,
        item.reading.reading_value,
        item.reading.reading_date,
        item.reading.expected_meter_version,
        item.reading.source_evidence,
      ]),
    ).toEqual([
      ["el-101", "1300", READING_DAY, 4, "Imported from readings.csv"],
      ["wa-102", "5", READING_DAY, 4, "Imported from readings.csv"],
      ["wa-201", "20", READING_DAY, 4, "Imported from readings.csv"],
    ]);
    // The result lists every reading that was not confirmed and why.
    expect(
      screen.getByText(
        "U201 Water: The meter changed. Check it on the screen.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("U101 Water: Lower than previous")).toBeTruthy();
    // A reading the server refused reads the list again.
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-892 Confirm nothing saves nothing while a line needs fixing, sends every reading in one all-or-nothing step when all are ready, and keeps the keys for Try again", async () => {
    const recordBatch = vi
      .fn()
      .mockRejectedValueOnce(new UtilityClientError())
      .mockRejectedValueOnce(new UtilityConflictError());
    const readSheet = vi
      .fn()
      .mockImplementationOnce(sheetOf(SHEET_ROWS))
      .mockImplementation(
        sheetOf([{ row: 2, unit: "101", electricity: "1,250", water: "41" }]),
      );
    const { units } = show({ api: utilityApi({ readSheet, recordBatch }) });
    let dialog = await openCheck();
    fireEvent.click(
      within(dialog).getByLabelText(
        "Confirm nothing until every reading is right.",
      ),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    expect(
      await screen.findByText(
        "Nothing confirmed from readings.csv. Fix the file and import it again.",
      ),
    ).toBeTruthy();
    expect(recordBatch).not.toHaveBeenCalled();

    dialog = await openCheck();
    expect(
      within(dialog).getByText(/2 readings\. 2 are ready\. 0 need fixing\./),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByLabelText(
        "Confirm nothing until every reading is right.",
      ),
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    await within(dialog).findByText(/No answer came back/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByText(
        "Nothing was confirmed. The meters changed while the list was open, so the readings were read again. Import the file again.",
      ),
    ).toBeTruthy();
    const [first, second] = recordBatch.mock.calls;
    expect(first?.[1]).toBe("ATOMIC_ALL");
    expect(first?.[3]).toEqual(expect.any(String));
    expect(second?.[3]).toBe(first?.[3]);
    expect(
      (second?.[2] as BatchReadingInput[]).map((item) => item.idempotency_key),
    ).toEqual(
      (first?.[2] as BatchReadingInput[]).map((item) => item.idempotency_key),
    );
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
  });

  it("TEST-FE-893 A much higher reading is ready with a check note; Import is only on the reading list and only for a person who may record readings", async () => {
    show({
      api: utilityApi({
        readSheet: sheetOf([
          { row: 2, unit: "U101", electricity: "1900", water: "" },
          { row: 3, unit: "U301", electricity: "7", water: "" },
        ]),
      }),
    });
    const dialog = await openCheck();
    expect(within(dialog).getByText("Ready")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Much more than usual (about 100). Check the meter.",
      ),
    ).toBeTruthy();
    // An empty Water box of a Unit that has a water meter needs fixing; a Unit with no meter
    // of that kind is named, and its empty box is left out.
    expect(within(dialog).getByText("Empty. Type the reading.")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "This Unit has no electricity meter. A Manager adds it on the Meters tab.",
      ),
    ).toBeTruthy();
    expect(within(dialog).getAllByRole("row")).toHaveLength(4);
    cleanup();

    show({ capabilities: new Set(["utility.read"]) });
    await screen.findByText("1 of 6 meters read");
    expect(screen.queryByRole("button", { name: /^Import/ })).toBeNull();
    cleanup();

    show({ today: "2026-10-20" });
    await screen.findByText(/Reading day is 24\/10\/2026/);
    expect(screen.queryByRole("button", { name: /^Import/ })).toBeNull();
  });

  it("TEST-FE-895 More than 100 readings go in batches of 100; after batch 2 is refused, Try again skips batch 1, and closing still names the readings batch 1 confirmed", async () => {
    const many = Array.from({ length: 55 }, (_, index) =>
      unit(`U${String(500 + index)}`, "5", "OCCUPIED"),
    );
    const list = many.flatMap((item) => [
      meter(`el-${item.unit_number}`, item.unit_number, "ELECTRICITY"),
      meter(`wa-${item.unit_number}`, item.unit_number, "WATER"),
    ]);
    const answer = (items: BatchReadingInput[]) =>
      Promise.resolve(
        items.map(
          (item, index): BatchReadingResult => ({
            index,
            idempotency_key: item.idempotency_key,
            status: "SUCCEEDED",
            reading: reading(
              item.meter_id,
              item.reading.reading_date,
              item.reading.reading_value,
            ),
            error: null,
          }),
        ),
      );
    const recordBatch = vi
      .fn()
      .mockImplementationOnce(
        (_p: string, _m: string, items: BatchReadingInput[]) => answer(items),
      )
      .mockRejectedValueOnce(new UtilityClientError(undefined, [], "req-9"))
      .mockRejectedValueOnce(new UtilityClientError(undefined, [], "req-10"));
    const readSheet = sheetOf(
      many.map((item, index) => ({
        row: index + 2,
        unit: item.unit_number,
        electricity: "5",
        water: "6",
      })),
    );
    const { units } = show({
      api: utilityApi({ readSheet, recordBatch }, list),
      units: many,
    });
    const dialog = await openCheck();
    expect(
      within(dialog).getByText(
        /110 readings\. 110 are ready\. 0 need fixing\./,
      ),
    ).toBeTruthy();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    await within(dialog).findByText(
      "It was not saved. Check the values and try again.",
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Confirm readings" }),
    );
    await waitFor(() => {
      expect(recordBatch).toHaveBeenCalledTimes(3);
    });
    const sizes = recordBatch.mock.calls.map(
      (call) => (call[2] as BatchReadingInput[]).length,
    );
    expect(sizes).toEqual([100, 10, 10]);
    expect(recordBatch.mock.calls[2]?.[3]).toBe(recordBatch.mock.calls[1]?.[3]);
    expect(recordBatch.mock.calls[1]?.[3]).not.toBe(
      recordBatch.mock.calls[0]?.[3],
    );
    await within(dialog).findByText(
      "It was not saved. Check the values and try again.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(
      await screen.findByText("100 readings confirmed from readings.csv."),
    ).toBeTruthy();
    expect(
      screen.getAllByText(/: Not saved\. Type it on the screen\.$/),
    ).toHaveLength(10);
    await waitFor(() => {
      expect(units.list).toHaveBeenCalledTimes(2);
    });
  });
});
