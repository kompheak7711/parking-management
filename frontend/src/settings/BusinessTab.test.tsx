import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExchangeRate } from "../configurationClient";
import { InvoiceClientError } from "../invoiceClient";
import {
  type PaymentMethodConfiguration,
  type PropertyBusinessConfiguration,
  PropertyConfigurationError,
  PropertyConfigurationUnavailableError,
  PropertySavedReadFailedError,
} from "../propertyClient";
import { BusinessTab, methodCode } from "./BusinessTab";

afterEach(() => {
  cleanup();
});

const METHODS: PaymentMethodConfiguration[] = [
  { code: "CASH", display_name: "Cash", accepted: true },
  { code: "ABA_PAY", display_name: "ABA PAY", accepted: true },
  { code: "CHEQUE", display_name: "Cheque", accepted: false },
];

const PROPERTY: PropertyBusinessConfiguration = {
  property_id: "property-1",
  name: "CHETANA Parking",
  address_text: "Street 271, Phnom Penh",
  timezone_name: "Asia/Phnom_Penh",
  payment_methods: METHODS,
  version: 4,
};

function rate(extra: Partial<ExchangeRate>): ExchangeRate {
  return {
    id: "rate-1",
    reference_rate_khr_per_usd: "4100",
    system_rate_khr_per_usd: 4121,
    rate_source: "ABA_AUTOMATIC",
    source_reference: null,
    applicable_at: "2026-10-20T02:00:00Z",
    usd_amount_cents: 10000,
    unrounded_payable_khr: "412100",
    payable_khr: 412100,
    fallback_reason: null,
    ...extra,
  };
}

function apiOf(
  property: () => Promise<PropertyBusinessConfiguration> = () =>
    Promise.resolve(PROPERTY),
) {
  return {
    property: {
      load: vi.fn(property),
      updateSource: vi.fn(() => Promise.resolve(PROPERTY)),
      updatePaymentMethods: vi.fn(() => Promise.resolve(PROPERTY)),
    },
    dueDays: {
      get: vi.fn(() =>
        Promise.resolve({
          property_id: "property-1",
          one_time_charge_due_days: 7,
          version: 4,
        }),
      ),
      set: vi.fn(() =>
        Promise.resolve({
          property_id: "property-1",
          one_time_charge_due_days: 10,
          version: 5,
        }),
      ),
    },
    units: {
      list: vi.fn(() =>
        Promise.resolve({
          items: [],
          next_cursor: null,
          can_manage: true,
        }),
      ),
    },
    rates: {
      load: vi.fn(() =>
        Promise.resolve({
          capabilities: {
            read: true,
            manage_service_rates: true,
            manage_utility_rates: true,
            manage_exchange_rates: true,
          },
          configuredServices: [],
          configuredServiceNextCursor: null,
          serviceRates: [],
          serviceNextCursor: null,
          utilityRates: [],
          utilityNextCursor: null,
          exchangeRates: [
            rate({}),
            rate({
              id: "rate-2",
              system_rate_khr_per_usd: 4135,
              rate_source: "ABA_EQUIVALENT_MANUAL",
              applicable_at: "2026-10-24T03:00:00Z",
            }),
          ],
          exchangeNextCursor: null,
        }),
      ),
    },
  };
}

function show(api = apiOf(), language: "en" | "km" = "en") {
  render(
    <BusinessTab
      active
      api={api}
      language={language}
      propertyId="property-1"
    />,
  );
  return api;
}

const card = (name: string) => screen.getByRole("region", { name });
const pairs = (region: HTMLElement) =>
  Array.from(region.querySelectorAll("dt")).map(
    (term) =>
      `${term.textContent}: ${term.nextElementSibling?.textContent ?? ""}`,
  );

describe("Settings: Business", () => {
  it("TEST-FE-950 shows the Property, the billing calendar with the server's days after issue, Reservations, Payment Methods, the latest riel rate and the numbers; values the server does not store yet say so", async () => {
    const api = show();
    const property = await screen.findByRole("region", { name: "Property" });
    expect(api.property.load).toHaveBeenCalledWith("property-1");
    expect(api.dueDays.get).toHaveBeenCalledWith("property-1");
    expect(pairs(property)).toEqual([
      "Property: CHETANA Parking",
      "Address: Street 271, Phnom Penh",
      "Units: 0",
      "Time zone: Asia/Phnom_Penh (UTC+7)Due dates, expiry and reading days use Phnom Penh time.",
      "Screen language: English and Khmer",
    ]);
    expect(pairs(card("Billing calendar"))).toEqual([
      "Meters read on the: 24th Set by the business rules",
      "Invoices issued on the: 25th Set by the business rules",
      "Rent and Utilities due on the: 5th Set by the business rules",
      "Other Invoices due: 7 days after issue",
      "Late-payment charge: 10% of the amount unpaid, added by the app on the day after the Due Date Set by the business rules",
    ]);
    expect(pairs(card("Reservations"))).toEqual([
      "Initial expiry at most: 21 days after the Reservation Date",
      "One extension of at most: 14 days, approved by a Manager",
      "Suggested deposit: 20% of the agreed monthly Rent",
    ]);
    const methods = card("Payment Methods");
    expect(
      within(methods)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "CashCASHActiveEdit",
      "ABA PAYABA_PAYActiveEdit",
      "ChequeCHEQUETurned offEdit",
    ]);
    // The newest confirmed rate.
    const fx = card("Riel exchange rate");
    expect(fx.textContent).toContain("4,135 ៛ per $1");
    expect(fx.textContent).toContain("Entered by hand, 24/10/2026 10:00.");
    expect(pairs(card("Numbers"))[0]).toBe(
      "Invoice numbers: INV + year + running number, for example INV260001",
    );
  });

  it("TEST-FE-951 Edit changes the Property name and address; the days after issue need 1 to 90 and a reason and send the Property version; a Payment Method is added with a new code, renamed or turned off, but one stays on", async () => {
    const api = show();
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Property" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Property" });
    fireEvent.change(within(dialog).getByLabelText(/^Property/), {
      target: { value: " " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Property/), {
      target: { value: "CHETANA Parking 2" },
    });
    fireEvent.change(within(dialog).getByLabelText("Address"), {
      target: { value: "  " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect(api.property.updateSource).toHaveBeenCalledWith(PROPERTY, {
      name: "CHETANA Parking 2",
      address_text: null,
    });
    expect(api.property.load).toHaveBeenCalledTimes(2);

    fireEvent.click(
      screen.getByRole("button", { name: "Edit: Other Invoices due" }),
    );
    dialog = screen.getByRole("dialog", { name: "Other Invoices due" });
    fireEvent.change(within(dialog).getByLabelText("Days after issue"), {
      target: { value: "91" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Enter a number from 1 to 90."),
    ).toBeTruthy();
    expect(within(dialog).getByText("Write the reason.")).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText("Days after issue"), {
      target: { value: "10" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Owner policy" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved.");
    expect(api.dueDays.set).toHaveBeenCalledWith(
      "property-1",
      10,
      "Owner policy",
      4,
      expect.any(String),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Add a method: Payment Methods" }),
    );
    dialog = screen.getByRole("dialog", { name: "Add a method" });
    fireEvent.change(within(dialog).getByLabelText(/^Method name/), {
      target: { value: "cash" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText('"cash" is already in the list.'),
    ).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText(/^Method name/), {
      target: { value: "Wing transfer" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Wing transfer saved.")).toBeTruthy();
    expect(api.property.updatePaymentMethods).toHaveBeenLastCalledWith(
      PROPERTY,
      [
        ...METHODS,
        {
          code: "WING_TRANSFER",
          display_name: "Wing transfer",
          accepted: true,
        },
      ],
    );

    fireEvent.click(screen.getByRole("button", { name: "Edit: ABA PAY" }));
    dialog = screen.getByRole("dialog", { name: "Edit method" });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("ABA PAY saved.");
    expect(api.property.updatePaymentMethods).toHaveBeenLastCalledWith(
      PROPERTY,
      [METHODS[0], { ...METHODS[1], accepted: false }, METHODS[2]],
    );
    expect(methodCode("ABA pay", METHODS)).toBe("ABA_PAY_2");
    expect(methodCode("ពាក្យ", METHODS)).toBe("METHOD");
  });

  it("TEST-FE-952 a change that met another change says so and reads again; the last method on cannot be turned off; Khmer words; a failed read offers Retry; no right says so; a saved change whose read-back failed still says saved; Save waits for the new version; a Property change drops an old answer", async () => {
    const api = apiOf(() =>
      Promise.resolve({
        ...PROPERTY,
        payment_methods: METHODS.slice(0, 1),
      }),
    );
    api.property.updatePaymentMethods.mockRejectedValueOnce(
      new PropertyConfigurationError(412),
    );
    show(api);
    fireEvent.click(await screen.findByRole("button", { name: "Edit: Cash" }));
    let dialog = screen.getByRole("dialog", { name: "Edit method" });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      within(dialog).getByText("Keep at least one method turned on."),
    ).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.change(within(dialog).getByLabelText(/^Method name/), {
      target: { value: "Cash (USD or riel)" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Someone changed these settings. They were read again; check and try again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.property.load).toHaveBeenCalledTimes(2);
    cleanup();

    show(apiOf(), "km");
    expect(
      await screen.findByRole("region", { name: "ប្រតិទិនគិតថ្លៃ" }),
    ).toBeTruthy();
    expect(
      screen.getAllByText("កំណត់ដោយច្បាប់អាជីវកម្ម").length,
    ).toBeGreaterThan(0);
    cleanup();

    let fail = true;
    show(
      apiOf(() =>
        fail ? Promise.reject(new Error("down")) : Promise.resolve(PROPERTY),
      ),
    );
    const retry = await screen.findByRole("button", { name: "Retry" });
    fail = false;
    fireEvent.click(retry);
    expect(
      await screen.findByRole("region", { name: "Property" }),
    ).toBeTruthy();
    cleanup();

    show(
      apiOf(() => Promise.reject(new PropertyConfigurationUnavailableError())),
    );
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    dialog = document.body;
    expect(within(dialog).queryByRole("button", { name: "Retry" })).toBeNull();
    cleanup();

    // The days dialog: another change met it, so it closes and reads again.
    const days = apiOf();
    days.dueDays.set.mockRejectedValueOnce(
      new InvoiceClientError(412, "STALE_VERSION", false, 5),
    );
    show(days);
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Other Invoices due" }),
    );
    dialog = screen.getByRole("dialog", { name: "Other Invoices due" });
    fireEvent.change(within(dialog).getByLabelText("Days after issue"), {
      target: { value: "10" },
    });
    fireEvent.change(within(dialog).getByLabelText(/^Reason/), {
      target: { value: "Owner policy" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText(
        "Someone changed these settings. They were read again; check and try again.",
      ),
    ).toBeTruthy();
    expect(days.dueDays.get).toHaveBeenCalledTimes(2);
    cleanup();

    // A refused days read means no right, not a failure.
    const noDays = apiOf();
    noDays.dueDays.get.mockRejectedValue(
      new InvoiceClientError(403, "FORBIDDEN", false),
    );
    show(noDays);
    expect(
      await screen.findByText("Your account cannot open this tab."),
    ).toBeTruthy();
    cleanup();

    // Saved, but reading back failed: it still says saved and reads again.
    // Save stays busy until the new version is read.
    const slow = apiOf();
    slow.property.updateSource.mockRejectedValueOnce(
      new PropertySavedReadFailedError(),
    );
    show(slow);
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Property" }),
    );
    const finish: {
      read?: (value: PropertyBusinessConfiguration) => void;
      save?: () => void;
    } = {};
    slow.property.load.mockImplementationOnce(
      () =>
        new Promise<PropertyBusinessConfiguration>((resolve) => {
          finish.read = resolve;
        }),
    );
    dialog = screen.getByRole("dialog", { name: "Property" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Add a method: Payment Methods" }),
    );
    const save = () =>
      within(
        screen.getByRole("dialog", { name: "Add a method" }),
      ).getByRole<HTMLButtonElement>("button", { name: "Save" });
    expect(save().disabled).toBe(true);
    finish.read?.({ ...PROPERTY, version: 5 });
    await waitFor(() => {
      expect(save().disabled).toBe(false);
    });
    cleanup();

    // A Property change while a save is out: the old answer is dropped.
    const race = apiOf();
    race.property.updateSource.mockImplementationOnce(
      () =>
        new Promise<PropertyBusinessConfiguration>((resolve) => {
          finish.save = () => {
            resolve(PROPERTY);
          };
        }),
    );
    const { rerender } = render(
      <BusinessTab active api={race} language="en" propertyId="property-1" />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit: Property" }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Property" })).getByRole(
        "button",
        { name: "Save" },
      ),
    );
    rerender(
      <BusinessTab active api={race} language="en" propertyId="property-2" />,
    );
    await screen.findByRole("region", { name: "Property" });
    finish.save?.();
    await Promise.resolve();
    expect(screen.queryByText("Saved.")).toBeNull();
    expect(race.property.load).toHaveBeenLastCalledWith("property-2");
  });
});
