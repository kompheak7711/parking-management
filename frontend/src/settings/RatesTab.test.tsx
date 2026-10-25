import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type ConfiguredService,
  EffectiveConfigurationConflictError,
  EffectiveConfigurationError,
  type EffectiveConfigurationSnapshot,
  EffectiveConfigurationUnavailableError,
  type ServiceRate,
  type UtilityRate,
} from "../configurationClient";
import { type RatesApi, RatesTab, serviceNow, utilityRows } from "./RatesTab";
import {
  type ServiceSettings,
  ServiceSettingsError,
  type ServiceSettingsApi,
} from "./serviceSettingsClient";

afterEach(() => {
  cleanup();
});

const TODAY = "2026-10-25";

const TRASH: ConfiguredService = {
  id: "svc-trash",
  property_id: "property-1",
  service_code: "TRASH",
  display_name: "Trash Collection",
};
const PARKING: ConfiguredService = {
  id: "svc-parking",
  property_id: "property-1",
  service_code: "PARKING",
  display_name: "Parking",
};

function serviceRate(extra: Partial<ServiceRate>): ServiceRate {
  return {
    id: "sr-1",
    property_service_id: TRASH.id,
    service_code: "TRASH",
    display_name: "Trash Collection",
    monthly_rate_usd_cents: 300,
    effective_date: "2025-01-01",
    source_memo: null,
    ...extra,
  };
}

function utilityRate(extra: Partial<UtilityRate>): UtilityRate {
  return {
    id: "ur-1",
    utility_type: "ELECTRICITY",
    measurement_unit_code: "KWH",
    rate_usd_per_unit: "0.22000000",
    effective_date: "2025-01-01",
    notice_at: "2024-12-01T05:00:00Z",
    notice_evidence: "Letter under each door",
    source_memo: null,
    ...extra,
  };
}

function snapshot(
  extra: Partial<EffectiveConfigurationSnapshot> = {},
): EffectiveConfigurationSnapshot {
  return {
    capabilities: {
      read: true,
      manage_service_rates: true,
      manage_utility_rates: true,
      manage_exchange_rates: true,
    },
    configuredServices: [TRASH],
    configuredServiceNextCursor: "svc-2",
    serviceRates: [
      serviceRate({}),
      serviceRate({
        id: "sr-2",
        monthly_rate_usd_cents: 350,
        effective_date: "2026-12-01",
        source_memo: "New contract",
      }),
    ],
    serviceNextCursor: null,
    utilityRates: [
      utilityRate({}),
      utilityRate({
        id: "ur-2",
        rate_usd_per_unit: "0.25000000",
        effective_date: "2026-02-01",
        notice_at: "2026-01-10T03:00:00Z",
      }),
    ],
    utilityNextCursor: "ut-2",
    exchangeRates: [],
    exchangeNextCursor: null,
    ...extra,
  };
}

function apiOf(load: () => Promise<EffectiveConfigurationSnapshot>) {
  return {
    load: vi.fn(load),
    loadConfiguredServices: vi.fn(() =>
      Promise.resolve({ items: [PARKING], nextCursor: null }),
    ),
    loadServiceRates: vi.fn(() =>
      Promise.resolve({ items: [], nextCursor: null }),
    ),
    loadUtilityRates: vi.fn(() =>
      Promise.resolve({
        items: [
          utilityRate({
            id: "ur-3",
            utility_type: "WATER",
            measurement_unit_code: "M3",
            rate_usd_per_unit: "0.60000000",
            effective_date: "2026-02-01",
            notice_at: "2026-01-10T03:00:00Z",
          }),
          utilityRate({
            id: "ur-4",
            rate_usd_per_unit: "0.27500000",
            effective_date: "2026-11-24",
            notice_at: "2026-10-20T05:00:00Z",
            notice_evidence: "Telegram group",
          }),
        ],
        nextCursor: null,
      }),
    ),
    createServiceRate: vi.fn<RatesApi["createServiceRate"]>(() =>
      Promise.resolve(serviceRate({})),
    ),
    createUtilityRate: vi.fn<RatesApi["createUtilityRate"]>(() =>
      Promise.resolve(utilityRate({})),
    ),
  };
}

function settingsOf(extra: Partial<ServiceSettings> = {}): ServiceSettings {
  return {
    services: [
      {
        service_id: TRASH.id,
        service_code: "TRASH_COLLECTION",
        name_en: "Trash Collection",
        name_km: "ប្រមូលសំរាម",
        service_type_id: "type-trash",
        version: 3,
        rate_today_usd_cents: 300,
        next_rate: null,
        approval_periods: [],
        leases_using: 2,
      },
      {
        service_id: PARKING.id,
        service_code: "SVC_1",
        name_en: "Parking",
        name_km: null,
        service_type_id: null,
        version: 1,
        rate_today_usd_cents: null,
        next_rate: null,
        approval_periods: [],
        leases_using: 0,
      },
    ],
    service_types: [
      {
        service_type_id: "type-trash",
        name_en: "Trash",
        name_km: "សំរាម",
        one_per_lease: true,
        removed: false,
        version: 4,
        services: 1,
      },
      {
        service_type_id: "type-laundry",
        name_en: "Laundry",
        name_km: null,
        one_per_lease: false,
        removed: false,
        version: 1,
        services: 0,
      },
      {
        service_type_id: "type-old",
        name_en: "Old",
        name_km: null,
        one_per_lease: false,
        removed: true,
        version: 2,
        services: 0,
      },
    ],
    today: TODAY,
    can_manage: true,
    ...extra,
  };
}

function servicesOf(
  read: () => Promise<ServiceSettings> = () => Promise.resolve(settingsOf()),
) {
  return {
    read: vi.fn<ServiceSettingsApi["read"]>(read),
    addService: vi.fn<ServiceSettingsApi["addService"]>(() =>
      Promise.resolve({}),
    ),
    changeService: vi.fn<ServiceSettingsApi["changeService"]>(() =>
      Promise.resolve({}),
    ),
    addType: vi.fn<ServiceSettingsApi["addType"]>(() => Promise.resolve({})),
    changeType: vi.fn<ServiceSettingsApi["changeType"]>(() =>
      Promise.resolve({}),
    ),
    removeType: vi.fn<ServiceSettingsApi["removeType"]>(() =>
      Promise.resolve({}),
    ),
  };
}

function show(
  api = apiOf(() => Promise.resolve(snapshot())),
  language: "en" | "km" = "en",
  services = servicesOf(),
) {
  render(
    <RatesTab
      active
      api={api}
      language={language}
      propertyId="property-1"
      services={services}
      today={TODAY}
    />,
  );
  return api;
}

const rowsOf = (region: HTMLElement) =>
  within(within(region).getAllByRole("table").at(0) ?? region)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );

describe("Settings: Rates and services", () => {
  it("TEST-FE-955 lists every page of Utility Rates newest first with until, starts later or active, and when the tenants were told; Services show the rate today, the next change and the history", async () => {
    const api = show();
    const utility = await screen.findByRole("region", {
      name: "Utility Rates",
    });
    expect(api.loadUtilityRates).toHaveBeenCalledWith("property-1", "ut-2");
    expect(api.loadConfiguredServices).toHaveBeenCalledWith(
      "property-1",
      "svc-2",
    );
    expect(rowsOf(utility)).toEqual([
      [
        "Electricity",
        "$0.275 / kWh",
        "24/11/2026",
        "Starts later",
        "20/10/2026Telegram group",
      ],
      [
        "Electricity",
        "$0.25 / kWh",
        "01/02/2026",
        "23/11/2026",
        "10/01/2026Letter under each door",
      ],
      [
        "Water",
        "$0.60 / m³",
        "01/02/2026",
        "Active",
        "10/01/2026Letter under each door",
      ],
      [
        "Electricity",
        "$0.22 / kWh",
        "01/01/2025",
        "31/01/2026",
        "01/12/2024Letter under each door",
      ],
    ]);
    const services = screen.getByRole("region", { name: "Services" });
    expect(rowsOf(services)).toEqual([
      [
        "Trash Collectionប្រមូលសំរាម",
        "Trash",
        "$3.00",
        "$3.50 · 01/12/2026",
        "2",
        "EditNew rate",
      ],
      ["Parking", "No type", "—", "—", "0", "EditNew rate"],
    ]);
    const history = within(services).getAllByRole("table").at(1) ?? services;
    expect(
      within(history)
        .getAllByRole("row")
        .slice(1)
        .map((row) => row.textContent),
    ).toEqual([
      "Trash Collection$3.5001/12/2026New contract",
      "Trash Collection$3.0001/01/2025—",
    ]);
    expect(
      within(services).getByText(
        /Move-out cleaning rates come in the next step/,
      ),
    ).toBeTruthy();
    // The helpers on their own.
    expect(
      serviceNow(
        [serviceRate({ effective_date: "2026-11-01" })],
        TRASH.id,
        TODAY,
      ),
    ).toEqual({
      now: null,
      next: serviceRate({ effective_date: "2026-11-01" }),
    });
    expect(utilityRows([]).length).toBe(0);
  });

  it("TEST-FE-956 a new Utility Rate starts on a 24th after today, after the tenants were told, and is sent with the fixed unit and one key per form; a new Service rate starts on the 1st of a later month", async () => {
    const api = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Schedule a new Rate" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Schedule a new Rate" });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-25" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Tenants told on/), {
      target: { value: "2026-10-26" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Enter the rate in dollars, for example 0.25."),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Enter a 24th after today, like 24/11/2026."),
    ).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Enter a day before the start day and not after today.",
      ),
    ).toBeTruthy();
    expect(
      within(dialog).getByText("Write how the tenants were told."),
    ).toBeTruthy();
    expect(
      within(dialog)
        .getByLabelText(/^Rate per kWh/)
        .getAttribute("aria-invalid"),
    ).toBe("true");
    // A rate of that kind already starts on that day.
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-24" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("A rate already starts on that day."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Kind"), {
      target: { value: "WATER" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Rate per kWh/), {
      target: { value: "0.65" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Tenants told on/), {
      target: { value: "2026-10-20" },
    });
    fireEvent.change(
      within(dialog).getByLabelText(/^How the tenants were told/),
      { target: { value: " Telegram group " } },
    );
    // No answer, then the same values again, then a refusal, then changed values.
    api.createUtilityRate
      .mockRejectedValueOnce(new EffectiveConfigurationError())
      .mockRejectedValueOnce(
        new EffectiveConfigurationError(undefined, [], null, 400),
      );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/without changing anything/),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        "The server did not accept this. Check the values and try again.",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Rate per kWh/), {
      target: { value: "0.12345" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("New Water Rate from 24/11/2026."),
    ).toBeTruthy();
    expect(api.createUtilityRate).toHaveBeenCalledTimes(3);
    const [first, second, third] = api.createUtilityRate.mock.calls;
    expect(third?.[1].rate_usd_per_unit).toBe("0.12345");
    // Changed values are a new request with a new key.
    expect(third?.[2]).not.toBe(first?.[2]);
    expect(first?.[1]).toEqual({
      utility_type: "WATER",
      measurement_unit_code: "M3",
      rate_usd_per_unit: "0.65",
      effective_date: "2026-11-24",
      notice_at: "2026-10-20T12:00:00+07:00",
      notice_evidence: "Telegram group",
      source_memo: null,
    });
    // The retry with the same values after a lost answer uses the same key.
    expect(second?.[2]).toBe(first?.[2]);
    expect(api.load).toHaveBeenCalledTimes(2);

    fireEvent.click(
      screen.getByRole("button", { name: "New rate: Trash Collection" }),
    );
    dialog = screen.getByRole("dialog", {
      name: "New rate · Trash Collection",
    });
    expect(
      within(dialog).getByLabelText<HTMLInputElement>(/^Monthly rate/).value,
    ).toBe("3.00");
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-15" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText(
        "Enter the first day of a month after today, like 01/12/2026.",
      ),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-12-01" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("A rate already starts on that day."),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2027-01-01" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "4.5" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Note/), {
      target: { value: "Owner decision" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Trash Collection saved.")).toBeTruthy();
    expect(api.createServiceRate).toHaveBeenCalledWith(
      "property-1",
      {
        property_service_id: TRASH.id,
        monthly_rate_usd_cents: 450,
        effective_date: "2027-01-01",
        source_memo: "Owner decision",
      },
      expect.any(String),
    );
  });

  it("TEST-FE-957 a rate that met another says so in the open form and reads again; a Property change during a save frees the form; no right to change hides the buttons; no right to read says so; a failed read offers Retry; Khmer words", async () => {
    const api = show();
    api.createServiceRate.mockRejectedValueOnce(
      new EffectiveConfigurationConflictError(),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "New rate: Parking" }),
    );
    const dialog = screen.getByRole("dialog", { name: "New rate · Parking" });
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "10" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-01" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/someone else changed the rates/),
    ).toBeTruthy();
    // What was typed stays.
    expect(
      within(dialog).getByLabelText<HTMLInputElement>(/^Monthly rate/).value,
    ).toBe("10");
    await waitFor(() => {
      expect(api.load).toHaveBeenCalledTimes(2);
    });
    cleanup();

    // A Property change while a save is out: the answer is dropped and the form is free.
    const finish: { save?: () => void } = {};
    const race = apiOf(() => Promise.resolve(snapshot()));
    race.createServiceRate.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish.save = () => {
            resolve(snapshot().serviceRates[0] ?? ({} as never));
          };
        }),
    );
    const { rerender } = render(
      <RatesTab
        active
        api={race}
        language="en"
        propertyId="property-1"
        services={servicesOf()}
        today={TODAY}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "New rate: Parking" }),
    );
    let form = screen.getByRole("dialog", { name: "New rate · Parking" });
    fireEvent.change(within(form).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-01" },
    });
    fireEvent.change(within(form).getByLabelText(/^Monthly rate/), {
      target: { value: "10" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    rerender(
      <RatesTab
        active
        api={race}
        language="en"
        propertyId="property-2"
        services={servicesOf()}
        today={TODAY}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "New rate: Parking" }),
    );
    form = screen.getByRole("dialog", { name: "New rate · Parking" });
    expect(
      within(form).getByRole<HTMLButtonElement>("button", { name: "Save" })
        .disabled,
    ).toBe(false);
    finish.save?.();
    await Promise.resolve();
    expect(screen.queryByText("Parking saved.")).toBeNull();
    cleanup();

    show(
      apiOf(() =>
        Promise.resolve(
          snapshot({
            capabilities: {
              read: true,
              manage_service_rates: false,
              manage_utility_rates: false,
              manage_exchange_rates: false,
            },
          }),
        ),
      ),
    );
    await screen.findByRole("region", { name: "Utility Rates" });
    expect(
      screen.queryByRole("button", { name: "Schedule a new Rate" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: /^New rate/ })).toBeNull();
    cleanup();

    show(
      apiOf(() => Promise.reject(new EffectiveConfigurationUnavailableError())),
    );
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    let fail = true;
    show(
      apiOf(() =>
        fail ? Promise.reject(new Error("down")) : Promise.resolve(snapshot()),
      ),
    );
    const retry = await screen.findByRole("button", { name: "Retry" });
    fail = false;
    fireEvent.click(retry);
    expect(
      await screen.findByRole("region", { name: "Utility Rates" }),
    ).toBeTruthy();
    cleanup();

    show(undefined, "km");
    expect(
      await screen.findByRole("region", { name: "អត្រាទឹកភ្លើង" }),
    ).toBeTruthy();
    expect(screen.getByRole("region", { name: "សេវា" })).toBeTruthy();
  });

  it("TEST-FE-999 Add a Service sends its own id, names, type, first rate in cents and a start on the 1st; the same values again keep the id; Edit changes names and type with the version", async () => {
    const services = servicesOf();
    show(undefined, "en", services);
    fireEvent.click(
      await screen.findByRole("button", { name: "Add a Service" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Add a Service" });
    // The type list leaves out removed types.
    expect(
      within(dialog)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "No type",
      "Trash · Only one per Lease",
      "Laundry · One or more per Lease",
    ]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Enter a name of 1 to 100 letters."),
    ).toBeTruthy();
    expect(services.addService).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "  Wash and fold " },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Name in Khmer/), {
      target: { value: "បោកអ៊ុត" },
    });
    fireEvent.change(within(dialog).getByLabelText("Type"), {
      target: { value: "type-laundry" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "12.50" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-15" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    const notFirst = /Enter the first day of this month or a later month/;
    expect(within(dialog).getByText(notFirst)).toBeTruthy();
    // A month already gone is refused too.
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-09-01" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText(notFirst)).toBeTruthy();
    expect(services.addService).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-11-01" },
    });
    services.addService.mockRejectedValueOnce(
      new ServiceSettingsError("unknown"),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/may be saved already/),
    ).toBeTruthy();
    // Changed values after no answer still use the same id: the server refuses them rather
    // than adding a second Service.
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "13" },
    });
    services.addService.mockRejectedValueOnce(
      new ServiceSettingsError("id_reused"),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    // It was saved the first time: the form closes and the list is read again.
    expect(await screen.findByText(/This was already saved/)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const [first, again] = services.addService.mock.calls;
    expect(first?.[1]).toEqual({
      service_id: expect.any(String) as string,
      name_en: "Wash and fold",
      name_km: "បោកអ៊ុត",
      service_type_id: "type-laundry",
      monthly_rate_usd_cents: 1250,
      starts_on: "2026-11-01",
    });
    expect(again?.[1].service_id).toBe(first?.[1].service_id);
    expect(again?.[1].monthly_rate_usd_cents).toBe(1300);
    // Read again after no answer and after the refusal.
    await waitFor(() => {
      expect(services.read).toHaveBeenCalledTimes(3);
    });
    // Once confirmed, a new Service gets a new id; after no answer the id is kept even when
    // the form is closed and opened again.
    fireEvent.click(screen.getByRole("button", { name: "Add a Service" }));
    dialog = screen.getByRole("dialog", { name: "Add a Service" });
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Wash and fold" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "12.50" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-10-01" },
    });
    services.addService.mockRejectedValueOnce(
      new ServiceSettingsError("unknown"),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/may be saved already/),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Add a Service" }));
    dialog = screen.getByRole("dialog", { name: "Add a Service" });
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Wash and fold" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Monthly rate/), {
      target: { value: "12.50" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Starts on/), {
      target: { value: "2026-10-01" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Wash and fold added.");
    const [, , third, fourth] = services.addService.mock.calls;
    expect(third?.[1].service_id).not.toBe(first?.[1].service_id);
    expect(fourth?.[1]).toEqual(third?.[1]);
    await waitFor(() => {
      expect(services.read).toHaveBeenCalledTimes(5);
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Edit: Trash Collection" }),
    );
    dialog = screen.getByRole("dialog", { name: "Edit · Trash Collection" });
    expect(
      within(dialog).getByText(/A new name shows only on new Invoices/),
    ).toBeTruthy();
    expect(within(dialog).queryByLabelText(/^Monthly rate/)).toBeNull();
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Trash pick-up" },
    });
    fireEvent.change(within(dialog).getByLabelText("Type"), {
      target: { value: "" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Trash pick-up saved.");
    expect(services.changeService).toHaveBeenCalledWith(
      "property-1",
      TRASH.id,
      {
        name_en: "Trash pick-up",
        name_km: "ប្រមូលសំរាម",
        service_type_id: null,
        version: 3,
      },
    );
  });

  it("TEST-FE-1000 Service types: Only one or One or more with a Services count; Remove only for a type with no Services; refusals say why and an old version reads again", async () => {
    const services = servicesOf();
    show(undefined, "en", services);
    const types = await screen.findByRole("region", { name: "Service types" });
    expect(rowsOf(types)).toEqual([
      ["Trash", "Only one per Lease", "1", "EditHas 1 Service"],
      ["Laundry", "One or more per Lease", "0", "EditRemove"],
    ]);
    expect(
      within(types).queryByRole("button", { name: "Remove: Trash" }),
    ).toBeNull();

    fireEvent.click(
      within(types).getByRole("button", { name: "Add a Service type" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Add a Service type" });
    expect(
      within(dialog).getByRole<HTMLInputElement>("radio", {
        name: "Only one per Lease",
      }).checked,
    ).toBe(true);
    fireEvent.change(within(dialog).getByLabelText(/^Name in English/), {
      target: { value: "Parking" },
    });
    fireEvent.click(
      within(dialog).getByRole("radio", { name: "One or more per Lease" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Parking added.");
    expect(services.addType.mock.calls[0]?.[1]).toEqual({
      service_type_id: expect.any(String) as string,
      name_en: "Parking",
      name_km: null,
      one_per_lease: false,
    });

    // Making a type Only one while a Lease holds two of it is refused in plain words.
    services.changeType.mockRejectedValueOnce(
      new ServiceSettingsError("lease_holds_two"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit: Laundry" }));
    dialog = screen.getByRole("dialog", { name: "Edit · Laundry" });
    fireEvent.click(
      within(dialog).getByRole("radio", { name: "Only one per Lease" }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(
        /A Lease holds two Services of this type/,
      ),
    ).toBeTruthy();
    expect(services.changeType).toHaveBeenCalledWith(
      "property-1",
      "type-laundry",
      {
        name_en: "Laundry",
        name_km: null,
        one_per_lease: true,
        version: 1,
      },
    );
    // Someone changed it first: the lists are read again.
    const reads = services.read.mock.calls.length;
    services.read.mockImplementation(() => {
      const newer = settingsOf();
      return Promise.resolve({
        ...newer,
        service_types: newer.service_types.map((type) =>
          type.service_type_id === "type-laundry"
            ? { ...type, version: 5 }
            : type,
        ),
      });
    });
    services.changeType.mockRejectedValueOnce(
      new ServiceSettingsError("out_of_date"),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await within(dialog).findByText(/Someone changed this first/),
    ).toBeTruthy();
    await waitFor(() => {
      expect(services.read.mock.calls.length).toBe(reads + 1);
    });
    // The next Save sends the version of the newest read.
    services.changeType.mockRejectedValueOnce(
      new ServiceSettingsError("lease_holds_two"),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(services.changeType.mock.lastCall?.[2].version).toBe(5);
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    services.removeType.mockRejectedValueOnce(
      new ServiceSettingsError("type_has_services"),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove: Laundry" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Laundry" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    // The form closes with the reason; the list is read again.
    expect(
      await screen.findByText(/has Services, so it cannot be removed/),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove: Laundry" }),
    );
    dialog = screen.getByRole("dialog", { name: "Remove · Laundry" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await screen.findByText("Laundry removed.");
    expect(services.removeType).toHaveBeenLastCalledWith(
      "property-1",
      "type-laundry",
      5,
    );
  });

  it("TEST-FE-1001 without Settings access the Services and types are read-only; a failed Services read keeps the rates and says so; Khmer names show in Khmer", async () => {
    show(
      undefined,
      "en",
      servicesOf(() => Promise.resolve(settingsOf({ can_manage: false }))),
    );
    const types = await screen.findByRole("region", { name: "Service types" });
    expect(screen.queryByRole("button", { name: "Add a Service" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull();
    expect(within(types).queryByRole("button")).toBeNull();
    // The rate right is separate: New rate still shows.
    expect(
      screen.getByRole("button", { name: "New rate: Parking" }),
    ).toBeTruthy();
    cleanup();

    show(
      undefined,
      "en",
      servicesOf(() => Promise.reject(new ServiceSettingsError("unknown"))),
    );
    expect(
      await screen.findByText(
        /Service names and types could not be read just now/,
      ),
    ).toBeTruthy();
    expect(screen.getByRole("region", { name: "Utility Rates" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Service types" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a Service" })).toBeNull();
    cleanup();

    show(undefined, "km");
    const khmer = await screen.findByRole("region", { name: "ប្រភេទសេវា" });
    expect(within(khmer).getByText("សំរាម")).toBeTruthy();
    expect(screen.getByText("ប្រមូលសំរាម")).toBeTruthy();
  });
});
