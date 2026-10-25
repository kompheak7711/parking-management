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

function show(
  api = apiOf(() => Promise.resolve(snapshot())),
  language: "en" | "km" = "en",
) {
  render(
    <RatesTab
      active
      api={api}
      language={language}
      propertyId="property-1"
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
      ["Trash CollectionTRASH", "$3.00", "$3.50 · 01/12/2026", "New rate"],
      ["ParkingPARKING", "—", "—", "New rate"],
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
      within(services).getByText(/Service types and move-out cleaning rates/),
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
});
